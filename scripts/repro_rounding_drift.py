"""复现脚本：多位小数入金 → 冻结漂移 → 对账差厘假绿。

用法：
    python3 scripts/repro_rounding_drift.py [db_path]

默认写 data/repro_drift.db（本机文件库，非内存库），跑完打印证据。
退出码：0 = 缺陷复现（存在漂移/假绿）；1 = 未复现（口径已统一）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

DB = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "repro_drift.db"
if DB.exists():
    DB.unlink()

import db  # noqa: E402

db.DB_PATH = DB
db.init_db()

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

c = TestClient(app)
tok = c.post("/api/login", json={"username": "admin", "password": "123456"}).json()[
    "token"
]
H = {"Authorization": "Bearer " + tok}

drift_found = False


def show(label, value):
    print(f"  {label:<28} = {value!r}")


def fen_aligned(x: float) -> bool:
    return abs(x - round(x, 2)) < 1e-9


print("== 1) 六位小数开户入金 ==")
r = c.post(
    "/api/bonds",
    headers=H,
    json={
        "party_key": "P-DRIFT",
        "party_name": "漂移复现户",
        "initial_deposit": 10000.123456,
    },
)
assert r.status_code == 200, r.text
acct = r.json()
show("balance(落库原值)", acct["balance"])
if not fen_aligned(acct["balance"]):
    drift_found = True
    print("  !! 余额带六位小数落库，未统一到分位")

print("== 2) 六位小数追加入金 ==")
r = c.post(
    "/api/bonds/deposit",
    headers=H,
    json={"party_key": "P-DRIFT", "amount": 3333.333333, "memo": "漂移入金"},
)
assert r.status_code == 200, r.text
show("balance(入金后)", r.json()["balance"])

print("== 3) 六位小数入笼冻结 ==")
r = c.post(
    "/api/cages/freeze",
    headers=H,
    json={
        "party_key": "P-DRIFT",
        "contract_no": "HT-DRIFT-1",
        "amount": 6666.666666,
        "beneficiary": "复现受益人",
        "cage_code": "CG-DRIFT-001",
    },
)
assert r.status_code == 200, r.text
cage = r.json()
show("cage.amount", cage["amount"])
show("cage.available", cage["available"])
if not fen_aligned(cage["amount"]):
    drift_found = True
    print("  !! 笼额带六位小数落库")

print("== 4) 核验通过 + 六位小数部分解笼 ==")
r = c.post(
    "/api/attestations",
    headers=H,
    json={"cage_id": cage["id"], "outcome": "通过", "evidence": "复现"},
)
assert r.status_code == 200, r.text
r = c.post(
    "/api/releases",
    headers=H,
    json={"cage_id": cage["id"], "amount": 1111.111111},
)
assert r.status_code == 200, r.text
rel = r.json()
show("release.amount", rel["amount"])

print("== 5) 漂移证据：账户冻结 vs 活笼可用 ==")
proof = c.get("/api/proof/P-DRIFT", headers=H).json()
show("account.frozen", proof["account"]["frozen"])
show("live_cage_available", proof["live_cage_available"])
show("frozen_matches_live", proof["frozen_matches_live"])

print("== 6) 对账：差厘是否仍亮绿 ==")
recon = c.get("/api/reconcile/CG-DRIFT-001", headers=H).json()
show("amount", recon["amount"])
show("accounted(可用+拨付+罚没)", recon["accounted"])
show("gap", recon["gap"])
show("balanced(绿灯)", recon["balanced"])
if recon["balanced"] and abs(recon["gap"]) > 1e-9:
    drift_found = True
    print("  !! 假绿复现：缺口非零仍报平衡")
summary = c.get("/api/reconcile", headers=H).json()["summary"]
show("summary", summary)

print()
if drift_found:
    print("结论：缺陷复现 —— 分位漂移已落库 / 对账差厘假绿。")
    sys.exit(0)
print("结论：未复现 —— 写入已统一分位，对账零容差。")
sys.exit(1)
