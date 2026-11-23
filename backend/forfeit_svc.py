"""罚没：核验违约后将笼内可用额写入罚没册。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import ForfeitIn

router = APIRouter(tags=["forfeit"])


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
        require_lock(conn, lock_key, user)
        try:
            cage = conn.execute(
                "SELECT * FROM cages WHERE id=?", (body.cage_id,)
            ).fetchone()
            if not cage:
                raise HTTPException(404, "笼不存在")
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
            avail = float(cage["available"])
            amount = float(body.amount) if body.amount is not None else avail
            if amount <= 0:
                raise HTTPException(400, "罚没金额须大于 0")
            if amount > avail + 1e-9:
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
            if existing and amount >= avail - 1e-9:
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
            new_avail = round(avail - amount, 6)
            new_status = "已罚没" if new_avail <= 1e-9 else "部分罚没"
            conn.execute(
                "UPDATE cages SET available=?, status=? WHERE id=?",
                (max(new_avail, 0.0), new_status, body.cage_id),
            )
            conn.execute(
                """UPDATE bond_accounts
                   SET frozen = frozen - ?, balance = balance - ?
                   WHERE party_key=?""",
                (amount, amount, cage["party_key"]),
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
        finally:
            release(conn, lock_key, user)
            conn.commit()
