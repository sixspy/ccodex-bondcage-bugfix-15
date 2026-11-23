"""拆笼分拨空桩：只登记 split_jobs + 审计，不生成子笼、不改原笼。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import SplitIn

router = APIRouter(tags=["split"])


@router.get("/api/split/jobs")
def list_jobs(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT j.*, c.cage_code FROM split_jobs j
               JOIN cages c ON c.id=j.cage_id
               ORDER BY j.id DESC"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/split-stub")
def split_stub(body: SplitIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    if body.mode not in ("整笔切分", "影子子笼"):
        raise HTTPException(400, "mode 须为整笔切分或影子子笼")
    lock_key = f"cage:{body.cage_id}"
    with connect() as conn:
        require_lock(conn, lock_key, user)
        try:
            cage = conn.execute(
                "SELECT * FROM cages WHERE id=?", (body.cage_id,)
            ).fetchone()
            if not cage:
                raise HTTPException(404, "笼不存在")
            left = float(body.left_amount)
            right = float(body.right_amount)
            if abs(left + right - float(cage["available"])) > 1e-6:
                # 空桩仍校验算术意图，但不落子笼
                raise HTTPException(
                    400,
                    "左右金额之和须等于笼可用额（空桩预检）",
                )
            before_count = conn.execute("SELECT COUNT(*) c FROM cages").fetchone()["c"]
            now = now_iso()
            cur = conn.execute(
                """INSERT INTO split_jobs(cage_id,left_amount,right_amount,mode,status,detail,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    body.cage_id,
                    left,
                    right,
                    body.mode,
                    "空桩登记",
                    "未生成子笼；待题面实现",
                    now,
                ),
            )
            write_audit(
                conn,
                user,
                "split_stub",
                cage["cage_code"],
                {
                    "job_id": cur.lastrowid,
                    "left": left,
                    "right": right,
                    "mode": body.mode,
                    "note": "stub_no_child_cage",
                },
            )
            conn.commit()
            after_count = conn.execute("SELECT COUNT(*) c FROM cages").fetchone()["c"]
            if after_count != before_count:
                raise HTTPException(500, "空桩竟新增了笼，母仓损坏")
            return {
                "job_id": cur.lastrowid,
                "status": "空桩登记",
                "cages_unchanged": True,
                "mode": body.mode,
            }
        finally:
            release(conn, lock_key, user)
            conn.commit()
