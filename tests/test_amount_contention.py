"""测丙：双人同写金额争用 —— 同一当事人双路写金额须抢账户锁，后到只记争用。

失败即证明：金额写入未统一抢账户锁，或争用登记随业务回滚丢失。
"""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import app
from db import init_db


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    init_db()
    yield


def _auth(c: TestClient, user: str) -> dict:
    tok = c.post(
        "/api/login", json={"username": user, "password": "123456"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _contention(c: TestClient, h: dict, lock_key: str):
    items = c.get("/api/contention", headers=h).json()["items"]
    return [x for x in items if x["lock_key"] == lock_key]


def test_dual_session_deposit_contention_durable():
    """双会话同时写同一当事人金额：持锁方写入，后到方 409 且争用落库。"""
    c_admin, c_clerk = TestClient(app), TestClient(app)
    h_admin, h_clerk = _auth(c_admin, "admin"), _auth(c_clerk, "clerk")
    c_admin.post(
        "/api/bonds",
        headers=h_admin,
        json={
            "party_key": "P-CONT",
            "party_name": "争用测试户",
            "initial_deposit": 5000,
        },
    )
    lock_key = "bond:P-CONT"
    # admin 持账户锁（运维入口显式持锁，模拟在途写）
    assert (
        c_admin.post(
            "/api/locks/acquire", headers=h_admin, json={"lock_key": lock_key}
        ).status_code
        == 200
    )
    barrier = threading.Barrier(2)
    results = {}

    def admin_deposit():
        barrier.wait()
        results["admin"] = c_admin.post(
            "/api/bonds/deposit",
            headers=h_admin,
            json={"party_key": "P-CONT", "amount": 100, "memo": "持锁方"},
        )

    def clerk_deposit():
        barrier.wait()
        results["clerk"] = c_clerk.post(
            "/api/bonds/deposit",
            headers=h_clerk,
            json={"party_key": "P-CONT", "amount": 200, "memo": "后到方"},
        )

    with ThreadPoolExecutor(2) as ex:
        list(ex.map(lambda f: f(), [admin_deposit, clerk_deposit]))
    assert results["admin"].status_code == 200, "持锁方同锁重入应放行"
    assert results["clerk"].status_code == 409, "后到争用方必须 409"
    # 争用登记须落库（不随业务回滚）
    cont = _contention(c_admin, h_admin, lock_key)
    assert any(x["actor"] == "clerk" for x in cont), "后到争用未落库"
    # 后到方未写业务：余额只加了持锁方的 100
    acct = c_admin.get("/api/bonds/P-CONT", headers=h_admin).json()["account"]
    assert acct["balance"] == 5100
    c_admin.post("/api/locks/release", headers=h_admin, json={"lock_key": lock_key})


def test_release_path_also_takes_account_lock():
    """解笼写金额同样须抢账户锁：他人持账户锁时，解笼 409 且记争用。"""
    c_admin, c_clerk = TestClient(app), TestClient(app)
    h_admin, h_clerk = _auth(c_admin, "admin"), _auth(c_clerk, "clerk")
    c_admin.post(
        "/api/bonds",
        headers=h_admin,
        json={
            "party_key": "P-CONT2",
            "party_name": "争用测试户二",
            "initial_deposit": 8000,
        },
    )
    cage = c_admin.post(
        "/api/cages/freeze",
        headers=h_admin,
        json={
            "party_key": "P-CONT2",
            "contract_no": "HT-CONT-1",
            "amount": 3000,
            "beneficiary": "争用受益人",
            "cage_code": "CG-CONT-001",
        },
    ).json()
    c_admin.post(
        "/api/attestations",
        headers=h_admin,
        json={"cage_id": cage["id"], "outcome": "通过", "evidence": "OK"},
    )
    lock_key = "bond:P-CONT2"
    # clerk 持账户锁
    assert (
        c_clerk.post(
            "/api/locks/acquire", headers=h_clerk, json={"lock_key": lock_key}
        ).status_code
        == 200
    )
    # admin 解笼：须抢同一账户锁 → 409 争用
    r = c_admin.post(
        "/api/releases", headers=h_admin, json={"cage_id": cage["id"], "amount": 1000}
    )
    assert r.status_code == 409, f"解笼未抢账户锁，status={r.status_code}"
    cont = _contention(c_admin, h_admin, lock_key)
    assert any(x["actor"] == "admin" for x in cont), "解笼争用未落库"
    # 业务未写：无拨付记录、笼可用未减
    detail = c_admin.get(f"/api/cages/{cage['id']}", headers=h_admin).json()
    assert detail["releases"] == []
    assert detail["cage"]["available"] == 3000
    c_clerk.post("/api/locks/release", headers=h_clerk, json={"lock_key": lock_key})
