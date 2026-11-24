"""测乙：对账差厘仍绿 —— 分位漂移被检出时绿灯必须熄灭（零容差）。

失败即证明：对账容差吞掉分位漂移，假绿瞒目。
"""
import pytest
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db, now_iso


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


def _plant_legacy_drift_cage():
    """直插一条存量分位漂移笼（模拟热修前的历史脏数据）：差一厘。"""
    with connect() as conn:
        conn.execute(
            """INSERT INTO bond_accounts(party_key,party_name,balance,frozen,status,created_at)
               VALUES ('P-LEGACY','存量漂移户',9000.004,5000.001,'正常',?)""",
            (now_iso(),),
        )
        conn.execute(
            """INSERT INTO cages(cage_code,party_key,contract_no,amount,available,
               generation,status,beneficiary,created_at,frozen_at)
               VALUES ('CG-LEGACY-001','P-LEGACY','HT-LEGACY-1',5000.001,5000.001,
               1,'已冻结','存量受益人',?,?)""",
            (now_iso(), now_iso()),
        )
        conn.commit()


def test_sub_fen_gap_extinguishes_green():
    """存量漂移笼：缺口一厘也必须判失衡，禁止假绿。"""
    _plant_legacy_drift_cage()
    c = TestClient(app)
    h = _auth(c)
    recon = c.get("/api/reconcile/CG-LEGACY-001", headers=h).json()
    assert recon["balanced"] is False, (
        f"差厘仍亮绿灯: gap={recon['gap']!r} balanced={recon['balanced']}"
    )
    summary = c.get("/api/reconcile", headers=h).json()["summary"]
    assert summary["unbalanced"] >= 1, "汇总未计入漂移失衡笼"


def test_fen_aligned_flow_stays_green():
    """正道：经 API 写入的数据必须分位对齐且对账绿灯（防矫枉过正）。"""
    c = TestClient(app)
    h = _auth(c)
    c.post(
        "/api/bonds",
        headers=h,
        json={
            "party_key": "P-GREEN",
            "party_name": "绿灯测试户",
            "initial_deposit": 20000.55,
        },
    )
    cage = c.post(
        "/api/cages/freeze",
        headers=h,
        json={
            "party_key": "P-GREEN",
            "contract_no": "HT-GREEN-1",
            "amount": 8888.88,
            "beneficiary": "绿灯受益人",
            "cage_code": "CG-GREEN-001",
        },
    ).json()
    c.post(
        "/api/attestations",
        headers=h,
        json={"cage_id": cage["id"], "outcome": "通过", "evidence": "OK"},
    )
    c.post(
        "/api/releases",
        headers=h,
        json={"cage_id": cage["id"], "amount": 3333.33},
    )
    recon = c.get("/api/reconcile/CG-GREEN-001", headers=h).json()
    assert recon["balanced"] is True, f"分位对齐数据被误判失衡: {recon}"
    assert abs(recon["gap"]) < 1e-9
    proof = c.get("/api/proof/P-GREEN", headers=h).json()
    assert proof["frozen_matches_live"] is True
