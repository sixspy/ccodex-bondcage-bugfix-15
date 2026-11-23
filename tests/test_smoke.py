import pytest
from fastapi.testclient import TestClient

from app import app
from db import init_db


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


def test_health_and_seed():
    c = TestClient(app)
    health = c.get("/api/health").json()
    assert health["product"] == "保证金笼"
    assert health["bonds"] >= 4
    assert health["cages"] >= 3
    assert "topup_cage" in health["meta"]["stubs"]


def test_freeze_attest_release_flow():
    c = TestClient(app)
    h = _auth(c)
    # 开户并入笼
    assert (
        c.post(
            "/api/bonds",
            headers=h,
            json={
                "party_key": "P-FLOW",
                "party_name": "流程测试",
                "initial_deposit": 100000,
            },
        ).status_code
        == 200
    )
    cage = c.post(
        "/api/cages/freeze",
        headers=h,
        json={
            "party_key": "P-FLOW",
            "contract_no": "HT-FLOW-1",
            "amount": 40000,
            "beneficiary": "受益A",
            "cage_code": "CG-FLOW-001",
        },
    ).json()
    assert cage["status"] == "已冻结"
    assert cage["available"] == 40000
    # 核验通过
    att = c.post(
        "/api/attestations",
        headers=h,
        json={"cage_id": cage["id"], "outcome": "通过", "evidence": "OK"},
    )
    assert att.status_code == 200
    # 解笼
    rel = c.post(
        "/api/releases",
        headers=h,
        json={"cage_id": cage["id"]},
    ).json()
    assert rel["status"] == "已拨付"
    assert rel["amount"] == 40000
    recon = c.get("/api/reconcile/CG-FLOW-001", headers=h).json()
    assert recon["balanced"] is True
    proof = c.get("/api/proof/P-FLOW", headers=h).json()
    assert proof["frozen_matches_live"] is True


def test_forfeit_path():
    c = TestClient(app)
    h = _auth(c)
    cages = c.get("/api/cages", headers=h).json()["items"]
    frozen = [x for x in cages if x["status"] == "已冻结"][0]
    assert (
        c.post(
            "/api/attestations",
            headers=h,
            json={
                "cage_id": frozen["id"],
                "outcome": "违约",
                "evidence": "逾期",
            },
        ).status_code
        == 200
    )
    # 禁止改口
    assert (
        c.post(
            "/api/attestations",
            headers=h,
            json={"cage_id": frozen["id"], "outcome": "通过", "evidence": "x"},
        ).status_code
        == 409
    )
    fr = c.post(
        "/api/forfeits",
        headers=h,
        json={"cage_id": frozen["id"], "reason": "逾期未履约"},
    )
    assert fr.status_code == 200
    assert fr.json()["status"] == "已罚没"
    recon = c.get(f"/api/reconcile/{frozen['cage_code']}", headers=h).json()
    assert recon["balanced"] is True


def test_lock_contention():
    c = TestClient(app)
    h1 = _auth(c, "admin")
    h2 = _auth(c, "clerk")
    assert (
        c.post(
            "/api/locks/acquire", headers=h1, json={"lock_key": "cage:999"}
        ).status_code
        == 200
    )
    assert (
        c.post(
            "/api/locks/acquire", headers=h2, json={"lock_key": "cage:999"}
        ).status_code
        == 409
    )
    cont = c.get("/api/contention", headers=h1).json()["items"]
    assert any(x["lock_key"] == "cage:999" for x in cont)


def test_viewer_readonly():
    c = TestClient(app)
    h = _auth(c, "viewer")
    assert c.get("/api/bonds", headers=h).status_code == 200
    assert (
        c.post(
            "/api/bonds/deposit",
            headers=h,
            json={"party_key": "P-WEST", "amount": 1},
        ).status_code
        == 403
    )
