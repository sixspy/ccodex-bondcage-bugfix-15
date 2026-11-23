import pytest
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    init_db()
    yield


def _auth(c: TestClient) -> dict:
    tok = c.post(
        "/api/login", json={"username": "admin", "password": "123456"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_topup_stub_no_balance_change():
    c = TestClient(app)
    h = _auth(c)
    cage = c.get("/api/cages", headers=h).json()["items"][0]
    before_amount = cage["amount"]
    before_avail = cage["available"]
    r = c.post(
        "/api/topup-stub",
        headers=h,
        json={"cage_id": cage["id"], "amount": 5000, "mode": "同笼扩代"},
    )
    assert r.status_code == 200
    assert r.json()["cage_unchanged"] is True
    after = c.get(f"/api/cages/{cage['id']}", headers=h).json()["cage"]
    assert after["amount"] == before_amount
    assert after["available"] == before_avail
    jobs = c.get("/api/topup/jobs", headers=h).json()["items"]
    assert any(j["status"] == "空桩登记" for j in jobs)


def test_split_stub_no_new_cage():
    c = TestClient(app)
    h = _auth(c)
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) c FROM cages").fetchone()["c"]
    cage = [x for x in c.get("/api/cages", headers=h).json()["items"] if x["available"] > 0][0]
    half = round(cage["available"] / 2, 2)
    other = round(cage["available"] - half, 2)
    r = c.post(
        "/api/split-stub",
        headers=h,
        json={
            "cage_id": cage["id"],
            "left_amount": half,
            "right_amount": other,
            "mode": "影子子笼",
        },
    )
    assert r.status_code == 200
    assert r.json()["cages_unchanged"] is True
    with connect() as conn:
        after = conn.execute("SELECT COUNT(*) c FROM cages").fetchone()["c"]
    assert after == before
