"""增补入笼空桩：只登记 topup_jobs + 审计，不改笼额与账户。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import TopupIn

router = APIRouter(tags=["topup"])


@router.get("/api/topup/jobs")
def list_jobs(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT j.*, c.cage_code FROM topup_jobs j
               JOIN cages c ON c.id=j.cage_id
               ORDER BY j.id DESC"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/topup-stub")
def topup_stub(body: TopupIn, authorization: AuthHeader = None):
    """
    空桩：题面落地前禁止真正扩额。
    允许登记 job，但 cages.amount / available 与 bond_accounts 保持不变。
    """
    user = require_writer(authorization)
    if body.mode not in ("同笼扩代", "新笼桥接"):
        raise HTTPException(400, "mode 须为同笼扩代或新笼桥接")
    lock_key = f"cage:{body.cage_id}"
    with connect() as conn:
        require_lock(conn, lock_key, user)
        try:
            cage = conn.execute(
                "SELECT * FROM cages WHERE id=?", (body.cage_id,)
            ).fetchone()
            if not cage:
                raise HTTPException(404, "笼不存在")
            if cage["status"] not in ("已冻结", "核验通过", "核验违约", "部分解笼", "部分罚没"):
                raise HTTPException(409, "当前笼状态禁止登记增补空桩")
            now = now_iso()
            cur = conn.execute(
                """INSERT INTO topup_jobs(cage_id,amount,mode,status,detail,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    body.cage_id,
                    float(body.amount),
                    body.mode,
                    "空桩登记",
                    "未改笼额；待题面实现",
                    now,
                ),
            )
            write_audit(
                conn,
                user,
                "topup_stub",
                cage["cage_code"],
                {
                    "job_id": cur.lastrowid,
                    "amount": float(body.amount),
                    "mode": body.mode,
                    "note": "stub_no_balance_change",
                },
            )
            conn.commit()
            # 断言：笼额未变
            after = conn.execute(
                "SELECT amount, available FROM cages WHERE id=?", (body.cage_id,)
            ).fetchone()
            if float(after["amount"]) != float(cage["amount"]) or float(
                after["available"]
            ) != float(cage["available"]):
                raise HTTPException(500, "空桩竟改了笼额，母仓损坏")
            return {
                "job_id": cur.lastrowid,
                "status": "空桩登记",
                "cage_unchanged": True,
                "mode": body.mode,
            }
        finally:
            release(conn, lock_key, user)
            conn.commit()
