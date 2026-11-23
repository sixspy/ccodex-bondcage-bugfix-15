"""保证金笼 — FastAPI 入口（加厚母仓）。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from attest_svc import router as attest_router
from audit_svc import router as audit_router
from auth import router as auth_router
from bonds_svc import router as bonds_router
from cages_svc import router as cages_router
from db import FRONTEND, PRODUCT_META, init_db
from forfeit_svc import router as forfeit_router
from locks import router as locks_router
from reconcile_svc import router as reconcile_router
from release_svc import router as release_router
from split_svc import router as split_router
from topup_svc import router as topup_router

PRODUCT = "保证金笼"
SKELETON = PRODUCT_META["skeleton"]

app = FastAPI(title=PRODUCT, description=SKELETON)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth_router,
    bonds_router,
    cages_router,
    attest_router,
    release_router,
    forfeit_router,
    reconcile_router,
    locks_router,
    audit_router,
    topup_router,
    split_router,
):
    app.include_router(r)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health():
    from db import DB_PATH, connect

    with connect() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM bond_accounts").fetchone()["c"]
        cages = conn.execute("SELECT COUNT(*) c FROM cages").fetchone()["c"]
        tables = conn.execute(
            "SELECT COUNT(*) c FROM sqlite_master WHERE type='table'"
        ).fetchone()["c"]
    return {
        "ok": True,
        "product": PRODUCT,
        "skeleton": SKELETON,
        "bonds": n,
        "cages": cages,
        "tables": tables,
        "db": str(DB_PATH),
        "meta": PRODUCT_META,
    }


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
