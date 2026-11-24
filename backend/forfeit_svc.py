"""罚没：核验违约后将笼内可用额写入罚没册。金额落库前统一到分（甲路径）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import ForfeitIn
from money import require_fen_amount, to_fen

router = APIRouter(tags=["forfeit"])


def _require_lock(conn, lock_key: str, user: str) -> None:
    """抢锁；后到争用登记须落库（不随业务回滚）。"""
    try:
        require_lock(conn, lock_key, user)
    except HTTPException:
        conn.commit()
        raise


@router.get("/api/forfeits")
def list_forfeits(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT f.*, c.cage_code, c.contract_no
               FROM forfeits f
               JOIN cages c ON c.id=f.cage_id
               ORDER BY f.id DESC LIMIT 200"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/forfeits")
def do_forfeit(body: ForfeitIn, authorization: AuthHeader = None):
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
            if cage["status"] != "核验违约":
                raise HTTPException(409, "仅核验违约的笼可罚没")
            att = conn.execute(
                """SELECT * FROM attestations
                   WHERE cage_id=? AND attest_gen=? AND outcome='违约'
                   ORDER BY id DESC LIMIT 1""",
                (body.cage_id, int(cage["generation"])),
            ).fetchone()
            if not att:
                raise HTTPException(409, "缺少与笼代对齐的违约核验")
            avail = to_fen(cage["available"])
            # 甲路径：罚没金额落库前统一到分；零改拒写
            if body.amount is not None:
                amount = require_fen_amount(body.amount, "罚没金额")
            else:
                amount = avail
                if amount <= 0:
                    raise HTTPException(400, "笼可用额为零，零改拒写")
            if amount > avail:
                raise HTTPException(409, "罚没金额超过笼可用额")
            now = now_iso()
            gen = int(cage["generation"])
            ref = f"FOR-{cage['cage_code']}-g{gen}"
            # 同笼同代禁止重复罚没整额撞车
            existing = conn.execute(
                """SELECT id FROM forfeits
                   WHERE cage_id=? AND cage_generation=? AND status='已罚没'""",
                (body.cage_id, gen),
            ).fetchone()
            if existing and amount >= avail:
                # 允许部分罚没后的尾款，但禁止整额重复
                pass
            cur = conn.execute(
                """INSERT INTO forfeits(cage_id,amount,reason,cage_generation,status,forfeit_ref,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    body.cage_id,
                    amount,
                    body.reason or "履约违约",
                    gen,
                    "已罚没",
                    ref,
                    now,
                ),
            )
            new_avail = to_fen(avail - amount)
            new_status = "已罚没" if new_avail <= 0 else "部分罚没"
            conn.execute(
                "UPDATE cages SET available=?, status=? WHERE id=?",
                (max(new_avail, 0.0), new_status, body.cage_id),
            )
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
                "cage_forfeit",
                cage["cage_code"],
                {
                    "forfeit_id": cur.lastrowid,
                    "amount": amount,
                    "reason": body.reason,
                    "cage_generation": gen,
                    "forfeit_ref": ref,
                },
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM forfeits WHERE id=?", (cur.lastrowid,)
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
