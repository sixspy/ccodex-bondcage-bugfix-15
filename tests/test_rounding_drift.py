"""测甲：分位漂移累计 —— 一切金额写入名册前必须统一到分（2 位，HALF_UP）。

失败即证明：金额落库路径未统一分位舍入，冻结累计漂移。
"""
import pytest
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    init_db()
    yield


def _auth(c: TestClient, user="admin") -> dict:
    tok = c.post(
        "/api/login", json={"username": user, "password": "123456"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _fen_aligned(x: float) -> bool:
    return abs(x - round(x, 2)) < 1e-9


def test_open_and_deposit_normalize_to_fen():
    c = TestClient(app)
    h = _auth(c)
    # 六位小数开户入金：落库必须已是分位
    r = c.post(
        "/api/bonds",
        headers=h,
        json={
            "party_key": "P-ROUND",
            "party_name": "分位测试户",
            "initial_deposit": 10000.123456,
        },
    )
    assert r.status_code == 200
    bal = r.json()["balance"]
    assert _fen_aligned(bal), f"开户入金未统一到分: {bal!r}"
    assert bal == 10000.12
    # 六位小数追加入金：逐笔统一到分，累计不得漂移
    for _ in range(3):
        r = c.post(
            "/api/bonds/deposit",
            headers=h,
            json={"party_key": "P-ROUND", "amount": 3333.333333, "memo": "追加入金"},
        )
        assert r.status_code == 200
    acct = c.get("/api/bonds/P-ROUND", headers=h).json()["account"]
    assert _fen_aligned(acct["balance"]), f"入金累计漂移: {acct['balance']!r}"
    assert acct["balance"] == round(10000.12 + 3 * 3333.33, 2)
    # 入金流水同样必须分位落库
    deps = c.get("/api/bonds/P-ROUND", headers=h).json()["deposits"]
    assert all(_fen_aligned(d["amount"]) for d in deps)


def test_freeze_release_forfeit_amounts_fen_aligned():
    c = TestClient(app)
    h = _auth(c)
    c.post(
        "/api/bonds",
        headers=h,
        json={
            "party_key": "P-ROUND2",
            "party_name": "分位测试户二",
            "initial_deposit": 50000,
        },
    )
    # 入笼：六位小数 → 分位
    cage = c.post(
        "/api/cages/freeze",
        headers=h,
        json={
            "party_key": "P-ROUND2",
            "contract_no": "HT-ROUND-1",
            "amount": 6666.666666,
            "beneficiary": "受益人甲",
            "cage_code": "CG-ROUND-001",
        },
    ).json()
    assert _fen_aligned(cage["amount"]), f"入笼金额未统一到分: {cage['amount']!r}"
    assert cage["amount"] == 6666.67
    acct = c.get("/api/bonds/P-ROUND2", headers=h).json()["account"]
    assert _fen_aligned(acct["frozen"])
    assert acct["frozen"] == cage["amount"]
    # 核验通过 → 六位小数部分解笼
    assert (
        c.post(
            "/api/attestations",
            headers=h,
            json={"cage_id": cage["id"], "outcome": "通过", "evidence": "OK"},
        ).status_code
        == 200
    )
    rel = c.post(
        "/api/releases",
        headers=h,
        json={"cage_id": cage["id"], "amount": 1111.111111},
    ).json()
    assert _fen_aligned(rel["amount"]), f"解笼金额未统一到分: {rel['amount']!r}"
    detail = c.get(f"/api/cages/{cage['id']}", headers=h).json()["cage"]
    assert _fen_aligned(detail["available"])
    # 冻结累计 = 活笼可用，分位上严格相等
    acct = c.get("/api/bonds/P-ROUND2", headers=h).json()["account"]
    assert _fen_aligned(acct["frozen"])
    assert abs(acct["frozen"] - detail["available"]) < 1e-9
    # 罚没路径同样统一分位
    cage2 = c.post(
        "/api/cages/freeze",
        headers=h,
        json={
            "party_key": "P-ROUND2",
            "contract_no": "HT-ROUND-2",
            "amount": 1000.105,
            "beneficiary": "受益人乙",
            "cage_code": "CG-ROUND-002",
        },
    ).json()
    assert cage2["amount"] == round(1000.105, 2)
    assert (
        c.post(
            "/api/attestations",
            headers=h,
            json={"cage_id": cage2["id"], "outcome": "违约", "evidence": "逾期"},
        ).status_code
        == 200
    )
    fr = c.post(
        "/api/forfeits",
        headers=h,
        json={"cage_id": cage2["id"], "amount": 500.555, "reason": "逾期"},
    ).json()
    assert _fen_aligned(fr["amount"]), f"罚没金额未统一到分: {fr['amount']!r}"
    assert fr["amount"] == 500.56  # HALF_UP


def test_zero_change_after_rounding_rejected_and_rolled_back():
    """统一到分后为零的写入（零改）必须拒写，且草稿原子回滚。"""
    c = TestClient(app)
    h = _auth(c)
    c.post(
        "/api/bonds",
        headers=h,
        json={
            "party_key": "P-ZERO",
            "party_name": "零改测试户",
            "initial_deposit": 100,
        },
    )
    before = c.get("/api/bonds/P-ZERO", headers=h).json()
    bal_before = before["account"]["balance"]
    n_dep_before = len(before["deposits"])
    # 0.001 统一到分后为 0.00 → 零改拒写
    r = c.post(
        "/api/bonds/deposit",
        headers=h,
        json={"party_key": "P-ZERO", "amount": 0.001, "memo": "零改"},
    )
    assert r.status_code in (400, 409), f"零改未拒写: {r.status_code}"
    after = c.get("/api/bonds/P-ZERO", headers=h).json()
    # 原子回滚：余额不变、流水不增
    assert after["account"]["balance"] == bal_before
    assert len(after["deposits"]) == n_dep_before
    with connect() as conn:
        n_audit = conn.execute(
            "SELECT COUNT(*) c FROM audit_trail WHERE action='bond_deposit' AND target='P-ZERO'"
        ).fetchone()["c"]
    assert n_audit == 0, "零改草稿未原子回滚（审计留痕）"
