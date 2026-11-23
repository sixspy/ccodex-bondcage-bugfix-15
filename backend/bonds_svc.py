"""保证金账户：开户、入金、查询。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import BondOpenIn, DepositIn

router = APIRouter(tags=["bonds"])


@router.get("/api/bonds")
def list_bonds(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT * FROM bond_accounts ORDER BY id"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/bonds/{party_key}")
def get_bond(party_key: str, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM bond_accounts WHERE party_key=?", (party_key,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "保证金户不存在")
        deposits = conn.execute(
            """SELECT * FROM deposit_ledger WHERE party_key=? ORDER BY id DESC LIMIT 50""",
            (party_key,),
        ).fetchall()
        cages = conn.execute(
            """SELECT id,cage_code,contract_no,amount,available,status,generation
               FROM cages WHERE party_key=? ORDER BY id DESC""",
            (party_key,),
        ).fetchall()
        return {
            "account": dict(row),
            "deposits": [dict(d) for d in deposits],
            "cages": [dict(c) for c in cages],
        }


@router.post("/api/bonds")
def open_bond(body: BondOpenIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    lock_key = f"bond:{body.party_key}"
    with connect() as conn:
        require_lock(conn, lock_key, user)
        try:
            exists = conn.execute(
                "SELECT id FROM bond_accounts WHERE party_key=?",
                (body.party_key,),
            ).fetchone()
            if exists:
                raise HTTPException(409, "当事人键已存在")
            now = now_iso()
            bal = float(body.initial_deposit)
            conn.execute(
                """INSERT INTO bond_accounts(party_key,party_name,balance,frozen,status,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (body.party_key, body.party_name, bal, 0.0, "正常", now),
            )
            if bal > 0:
                conn.execute(
                    """INSERT INTO deposit_ledger(party_key,amount,memo,created_at,actor)
                       VALUES (?,?,?,?,?)""",
                    (body.party_key, bal, "开户入金", now, user),
                )
            write_audit(
                conn,
                user,
                "bond_open",
                body.party_key,
                {"party_name": body.party_name, "initial_deposit": bal},
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM bond_accounts WHERE party_key=?",
                (body.party_key,),
            ).fetchone()
            return dict(row)
        finally:
            release(conn, lock_key, user)
            conn.commit()


@router.post("/api/bonds/deposit")
def deposit(body: DepositIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    lock_key = f"bond:{body.party_key}"
    with connect() as conn:
        require_lock(conn, lock_key, user)
        try:
            acct = conn.execute(
                "SELECT * FROM bond_accounts WHERE party_key=?",
                (body.party_key,),
            ).fetchone()
            if not acct:
                raise HTTPException(404, "保证金户不存在")
            if acct["status"] != "正常":
                raise HTTPException(409, "账户状态禁止入金")
            now = now_iso()
            amount = float(body.amount)
            conn.execute(
                "UPDATE bond_accounts SET balance = balance + ? WHERE party_key=?",
                (amount, body.party_key),
            )
            conn.execute(
                """INSERT INTO deposit_ledger(party_key,amount,memo,created_at,actor)
                   VALUES (?,?,?,?,?)""",
                (body.party_key, amount, body.memo or "手工入金", now, user),
            )
            write_audit(
                conn,
                user,
                "bond_deposit",
                body.party_key,
                {"amount": amount, "memo": body.memo},
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM bond_accounts WHERE party_key=?",
                (body.party_key,),
            ).fetchone()
            return dict(row)
        finally:
            release(conn, lock_key, user)
            conn.commit()
