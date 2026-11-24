"""入笼冻结：可用保证金划入笼内，写笼代。金额落库前统一到分（甲路径）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import CageFreezeIn
from money import require_fen_amount, to_fen

router = APIRouter(tags=["cages"])


def _require_lock(conn, lock_key: str, user: str) -> None:
    """抢账户锁；后到争用登记须落库（不随业务回滚）。"""
    try:
        require_lock(conn, lock_key, user)
    except HTTPException:
        conn.commit()
        raise


def _next_cage_code(conn, party_key: str) -> str:
    n = conn.execute(
        "SELECT COUNT(*) c FROM cages WHERE party_key=?", (party_key,)
    ).fetchone()["c"]
    return f"CG-{party_key}-{n + 1:03d}"


@router.get("/api/cages")
def list_cages(authorization: AuthHeader = None, status: str | None = None):
    require_user(authorization)
    with connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM cages WHERE status=? ORDER BY id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM cages ORDER BY id DESC").fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/cages/{cage_id}")
def get_cage(cage_id: int, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        cage = conn.execute("SELECT * FROM cages WHERE id=?", (cage_id,)).fetchone()
        if not cage:
            raise HTTPException(404, "笼不存在")
        atts = conn.execute(
            "SELECT * FROM attestations WHERE cage_id=? ORDER BY id DESC",
            (cage_id,),
        ).fetchall()
        rels = conn.execute(
            "SELECT * FROM releases WHERE cage_id=? ORDER BY id DESC",
            (cage_id,),
        ).fetchall()
        fors = conn.execute(
            "SELECT * FROM forfeits WHERE cage_id=? ORDER BY id DESC",
            (cage_id,),
        ).fetchall()
        return {
            "cage": dict(cage),
            "attestations": [dict(a) for a in atts],
            "releases": [dict(r) for r in rels],
            "forfeits": [dict(f) for f in fors],
        }


@router.post("/api/cages/freeze")
def freeze_cage(body: CageFreezeIn, authorization: AuthHeader = None):
    """从账户可用余额划入新笼并冻结。"""
    user = require_writer(authorization)
    lock_key = f"bond:{body.party_key}"
    with connect() as conn:
        _require_lock(conn, lock_key, user)
        try:
            acct = conn.execute(
                "SELECT * FROM bond_accounts WHERE party_key=?",
                (body.party_key,),
            ).fetchone()
            if not acct:
                raise HTTPException(404, "保证金户不存在")
            if acct["status"] != "正常":
                raise HTTPException(409, "账户状态禁止入笼")
            # 甲路径：入笼金额落库前统一到分；零改拒写
            amount = require_fen_amount(body.amount, "入笼金额")
            free = to_fen(float(acct["balance"]) - float(acct["frozen"]))
            if amount > free:
                raise HTTPException(409, "可用保证金不足，无法入笼")
            code = body.cage_code or _next_cage_code(conn, body.party_key)
            dup = conn.execute(
                "SELECT id FROM cages WHERE cage_code=?", (code,)
            ).fetchone()
            if dup:
                raise HTTPException(409, "笼编码已存在")
            now = now_iso()
            cur = conn.execute(
                """INSERT INTO cages(cage_code,party_key,contract_no,amount,available,
                   generation,status,beneficiary,created_at,frozen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    code,
                    body.party_key,
                    body.contract_no,
                    amount,
                    amount,
                    1,
                    "已冻结",
                    body.beneficiary,
                    now,
                    now,
                ),
            )
            cage_id = cur.lastrowid
            conn.execute(
                "UPDATE bond_accounts SET frozen=? WHERE party_key=?",
                (to_fen(float(acct["frozen"]) + amount), body.party_key),
            )
            write_audit(
                conn,
                user,
                "cage_freeze",
                code,
                {
                    "cage_id": cage_id,
                    "amount": amount,
                    "contract_no": body.contract_no,
                    "beneficiary": body.beneficiary,
                    "generation": 1,
                },
            )
            conn.commit()
            row = conn.execute("SELECT * FROM cages WHERE id=?", (cage_id,)).fetchone()
            return dict(row)
        except Exception:
            conn.rollback()  # 草稿原子回滚
            raise
        finally:
            release(conn, lock_key, user)
            conn.commit()
