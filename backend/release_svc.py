"""解笼拨付：核验通过后把笼内可用额拨付给受益人。金额落库前统一到分（甲路径）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import ReleaseIn
from money import require_fen_amount, to_fen

router = APIRouter(tags=["release"])


def _require_lock(conn, lock_key: str, user: str) -> None:
    """抢锁；后到争用登记须落库（不随业务回滚）。"""
    try:
        require_lock(conn, lock_key, user)
    except HTTPException:
        conn.commit()
        raise


@router.get("/api/releases")
def list_releases(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT r.*, c.cage_code, c.contract_no
               FROM releases r
               JOIN cages c ON c.id=r.cage_id
               ORDER BY r.id DESC LIMIT 200"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/releases")
def do_release(body: ReleaseIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    lock_key = f"cage:{body.cage_id}"
    with connect() as conn:
        _require_lock(conn, lock_key, user)
        acct_lock = None
        try:
            cage = conn.execute(
                "SELECT * FROM cages WHERE id=?", (body.cage_id,)
            ).fetchone()
            if not cage:
                raise HTTPException(404, "笼不存在")
            # 双路写金额须抢账户锁（先笼锁后账户锁，全仓顺序一致）
            acct_lock = f"bond:{cage['party_key']}"
            _require_lock(conn, acct_lock, user)
            if cage["status"] != "核验通过":
                raise HTTPException(409, "仅核验通过的笼可解笼拨付")
            # 核验结论必须对齐当前笼代
            att = conn.execute(
                """SELECT * FROM attestations
                   WHERE cage_id=? AND attest_gen=? AND outcome='通过'
                   ORDER BY id DESC LIMIT 1""",
                (body.cage_id, int(cage["generation"])),
            ).fetchone()
            if not att:
                raise HTTPException(409, "缺少与笼代对齐的通过核验")
            avail = to_fen(cage["available"])
            # 甲路径：解笼金额落库前统一到分；零改拒写
            if body.amount is not None:
                amount = require_fen_amount(body.amount, "拨付金额")
            else:
                amount = avail
                if amount <= 0:
                    raise HTTPException(400, "笼可用额为零，零改拒写")
            if amount > avail:
                raise HTTPException(409, "拨付金额超过笼可用额")
            payee = body.payee or cage["beneficiary"]
            now = now_iso()
            gen = int(cage["generation"])
            ref = f"REL-{cage['cage_code']}-g{gen}-{int(now.replace(':', '').replace('-', '').replace('T', '')[-8:])}"
            cur = conn.execute(
                """INSERT INTO releases(cage_id,amount,payee,cage_generation,status,release_ref,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (body.cage_id, amount, payee, gen, "已拨付", ref, now),
            )
            new_avail = to_fen(avail - amount)
            new_status = "已解笼" if new_avail <= 0 else "部分解笼"
            conn.execute(
                "UPDATE cages SET available=?, status=? WHERE id=?",
                (max(new_avail, 0.0), new_status, body.cage_id),
            )
            # 账户：冻结减少，余额减少（资金离开系统），分位对齐落库
            acct = conn.execute(
                "SELECT balance, frozen FROM bond_accounts WHERE party_key=?",
                (cage["party_key"],),
            ).fetchone()
            conn.execute(
                """UPDATE bond_accounts
                   SET frozen=?, balance=?
                   WHERE party_key=?""",
                (
                    to_fen(float(acct["frozen"]) - amount),
                    to_fen(float(acct["balance"]) - amount),
                    cage["party_key"],
                ),
            )
            write_audit(
                conn,
                user,
                "cage_release",
                cage["cage_code"],
                {
                    "release_id": cur.lastrowid,
                    "amount": amount,
                    "payee": payee,
                    "cage_generation": gen,
                    "release_ref": ref,
                },
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM releases WHERE id=?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)
        except Exception:
            conn.rollback()  # 草稿原子回滚
            raise
        finally:
            if acct_lock:
                release(conn, acct_lock, user)
            release(conn, lock_key, user)
            conn.commit()
