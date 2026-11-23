"""SQLite：保证金笼母仓公共库层。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = DATA / "app.db"
FIXTURES = ROOT / "fixtures"
FRONTEND = ROOT / "frontend"

PRODUCT_META = {
    "product": "保证金笼",
    "skeleton": "保证金先入笼冻结，履约核验通过才解笼拨付，违约进罚没册，笼代与拨付罚没对账",
    "modules": [
        "bonds",
        "cages",
        "attest",
        "release",
        "forfeit",
        "reconcile",
        "locks",
        "audit",
        "topup",
        "split",
    ],
    "stubs": ["topup_cage", "split_cage"],
}


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def sha_password(password: str) -> str:
    import hashlib

    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  username TEXT PRIMARY KEY,
  password_sha TEXT NOT NULL,
  role TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bond_accounts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  party_key TEXT UNIQUE NOT NULL,
  party_name TEXT NOT NULL,
  balance REAL NOT NULL DEFAULT 0,
  frozen REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cage_code TEXT UNIQUE NOT NULL,
  party_key TEXT NOT NULL,
  contract_no TEXT NOT NULL,
  amount REAL NOT NULL,
  available REAL NOT NULL,
  generation INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL,
  beneficiary TEXT NOT NULL,
  created_at TEXT NOT NULL,
  frozen_at TEXT,
  FOREIGN KEY(party_key) REFERENCES bond_accounts(party_key)
);
CREATE TABLE IF NOT EXISTS attestations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cage_id INTEGER NOT NULL,
  outcome TEXT NOT NULL,
  evidence TEXT NOT NULL,
  attest_gen INTEGER NOT NULL,
  officer TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(cage_id) REFERENCES cages(id)
);
CREATE TABLE IF NOT EXISTS releases(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cage_id INTEGER NOT NULL,
  amount REAL NOT NULL,
  payee TEXT NOT NULL,
  cage_generation INTEGER NOT NULL,
  status TEXT NOT NULL,
  release_ref TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(cage_id) REFERENCES cages(id)
);
CREATE TABLE IF NOT EXISTS forfeits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cage_id INTEGER NOT NULL,
  amount REAL NOT NULL,
  reason TEXT NOT NULL,
  cage_generation INTEGER NOT NULL,
  status TEXT NOT NULL,
  forfeit_ref TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(cage_id) REFERENCES cages(id)
);
CREATE TABLE IF NOT EXISTS cage_locks(
  lock_key TEXT PRIMARY KEY,
  holder TEXT NOT NULL,
  acquired_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contention_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lock_key TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_trail(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT,
  payload TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topup_jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cage_id INTEGER NOT NULL,
  amount REAL NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS split_jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cage_id INTEGER NOT NULL,
  left_amount REAL NOT NULL,
  right_amount REAL NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deposit_ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  party_key TEXT NOT NULL,
  amount REAL NOT NULL,
  memo TEXT NOT NULL,
  created_at TEXT NOT NULL,
  actor TEXT NOT NULL
);
"""


def write_audit(conn: sqlite3.Connection, actor: str, action: str, target: str, payload: dict) -> None:
    conn.execute(
        """INSERT INTO audit_trail(actor,action,target,payload,created_at)
           VALUES (?,?,?,?,?)""",
        (actor, action, target, json.dumps(payload, ensure_ascii=False), now_iso()),
    )


def _load_json(name: str):
    path = FIXTURES / name
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def seed_users(conn: sqlite3.Connection) -> None:
    for u, role in (("admin", "admin"), ("clerk", "clerk"), ("viewer", "viewer")):
        conn.execute(
            "INSERT OR IGNORE INTO users(username,password_sha,role) VALUES (?,?,?)",
            (u, sha_password("123456"), role),
        )


def seed_bonds(conn: sqlite3.Connection) -> None:
    for row in _load_json("bonds.json"):
        exists = conn.execute(
            "SELECT id FROM bond_accounts WHERE party_key=?", (row["party_key"],)
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """INSERT INTO bond_accounts(party_key,party_name,balance,frozen,status,created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                row["party_key"],
                row["party_name"],
                float(row["balance"]),
                float(row.get("frozen", 0)),
                row.get("status", "正常"),
                row.get("created_at", now_iso()),
            ),
        )
        if float(row["balance"]) > 0:
            conn.execute(
                """INSERT INTO deposit_ledger(party_key,amount,memo,created_at,actor)
                   VALUES (?,?,?,?,?)""",
                (
                    row["party_key"],
                    float(row["balance"]),
                    "种子入金",
                    row.get("created_at", now_iso()),
                    "seed",
                ),
            )


def seed_cages(conn: sqlite3.Connection) -> None:
    for row in _load_json("cages.json"):
        exists = conn.execute(
            "SELECT id FROM cages WHERE cage_code=?", (row["cage_code"],)
        ).fetchone()
        if exists:
            continue
        amount = float(row["amount"])
        status = row.get("status", "已冻结")
        available = float(row.get("available", amount if status == "已冻结" else 0))
        conn.execute(
            """INSERT INTO cages(cage_code,party_key,contract_no,amount,available,
               generation,status,beneficiary,created_at,frozen_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                row["cage_code"],
                row["party_key"],
                row["contract_no"],
                amount,
                available,
                int(row.get("generation", 1)),
                status,
                row["beneficiary"],
                row.get("created_at", now_iso()),
                row.get("frozen_at"),
            ),
        )
        if status == "已冻结":
            acct = conn.execute(
                "SELECT id,frozen FROM bond_accounts WHERE party_key=?",
                (row["party_key"],),
            ).fetchone()
            if acct:
                # 种子笼已反映在 balance/frozen 字段时不重复扣
                pass


def seed_attest_samples(conn: sqlite3.Connection) -> None:
    """为已冻结笼预置一条待核验说明，便于页面冷启动有可读业务。"""
    rows = conn.execute(
        "SELECT id, generation FROM cages WHERE status='已冻结' ORDER BY id"
    ).fetchall()
    for cage in rows[:2]:
        n = conn.execute(
            "SELECT COUNT(*) c FROM attestations WHERE cage_id=?", (cage["id"],)
        ).fetchone()["c"]
        if n:
            continue
        # 不预置通过/违约结论，只保证表可查；实际核验由业务动作写入


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        seed_users(conn)
        seed_bonds(conn)
        seed_cages(conn)
        seed_attest_samples(conn)
        conn.commit()


def dashboard_stats(conn: sqlite3.Connection) -> dict:
    bonds = conn.execute("SELECT COUNT(*) c FROM bond_accounts").fetchone()["c"]
    cages = conn.execute("SELECT COUNT(*) c FROM cages").fetchone()["c"]
    frozen = conn.execute(
        "SELECT COALESCE(SUM(available),0) s FROM cages WHERE status='已冻结'"
    ).fetchone()["s"]
    released = conn.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM releases WHERE status='已拨付'"
    ).fetchone()["s"]
    forfeited = conn.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM forfeits WHERE status='已罚没'"
    ).fetchone()["s"]
    stubs = {
        "topup_jobs": conn.execute("SELECT COUNT(*) c FROM topup_jobs").fetchone()["c"],
        "split_jobs": conn.execute("SELECT COUNT(*) c FROM split_jobs").fetchone()["c"],
    }
    return {
        "bonds": bonds,
        "cages": cages,
        "frozen_available": frozen,
        "released_total": released,
        "forfeited_total": forfeited,
        "stubs": stubs,
        "meta": PRODUCT_META,
    }
