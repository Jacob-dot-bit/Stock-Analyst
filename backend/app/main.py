"""Stock Analyst API entry point."""

from __future__ import annotations

import ipaddress
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import init_db
from app.routers import (
    backup,
    corporate_actions,
    discovery,
    dividends,
    factors,
    imports,
    insights,
    journal,
    portfolio,
    prediction,
    prices,
    screener,
    scoring,
    tax,
    transactions,
    watchlist,
    settings as settings_router,
)

#: This API has no authentication at all — it is a personal, single-user, local-only
#: tool, and its only real access boundary is the loopback interface. "testclient" is
#: Starlette's TestClient convention for its in-process ASGI transport, not a spoofable
#: network address: it can never appear on a real socket, only inside the test suite.
LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "testclient"}

#: Narrow, single-route exception to loopback-only: an external automation
#: container triggers a price refresh over the docker bridge network (it cannot
#: reach 127.0.0.1 of the host — separate network namespace). Scoped to exactly
#: `POST /api/prices/refresh` in `loopback_only` below — every other endpoint
#: (holdings, API keys, transactions, ...) stays loopback-only, unauthenticated,
#: as designed (see DEVLOG "Decision 3k.1"). Also gated at the network layer:
#: the firewall only opens :8000 to this subnet while that container's outbound
#: egress is enabled — otherwise the request never reaches this process at all.
DOCKER_BRIDGE_SUBNET = ipaddress.ip_network("172.17.0.0/16")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


settings = get_settings()

app = FastAPI(
    title="Stock Analyst",
    description=(
        "Tracking and analysis of an equity portfolio. Portfolio data comes from a "
        "broker file export: the XTB API was shut down on 14 March 2025 and no "
        "automatic synchronisation is possible.\n\n"
        "This tool produces indicators, not investment advice.\n\n"
        "The API is language-neutral: human-readable text is returned as message "
        "codes with parameters, and rendered by the client."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def loopback_only(request: Request, call_next):
    """Refuse anything that didn't arrive over loopback. CORS only restricts what a
    *browser* is allowed to read back — a plain script or another machine on the LAN
    ignores it entirely — so it is not a real boundary on its own. This is: if the
    backend is ever started with `--host 0.0.0.0` (e.g. to check the portfolio from a
    phone), it stays unreachable rather than silently exposing every holding and the
    API-key endpoints, unauthenticated, to the whole network. See DEVLOG "Decision 3k.1".
    """
    client_host = request.client.host if request.client else None
    if client_host in LOOPBACK_CLIENTS:
        return await call_next(request)
    if client_host and request.url.path == "/api/prices/refresh" and request.method == "POST":
        try:
            from_bridge = ipaddress.ip_address(client_host) in DOCKER_BRIDGE_SUBNET
        except ValueError:
            from_bridge = False
        if from_bridge:
            return await call_next(request)
    return JSONResponse({"detail": "This API only accepts local connections."}, status_code=403)

app.include_router(portfolio.router)
app.include_router(imports.router)
app.include_router(prices.router)
app.include_router(transactions.router)
app.include_router(settings_router.router)
app.include_router(scoring.router)
app.include_router(watchlist.router)
app.include_router(screener.router)
app.include_router(insights.router)
app.include_router(discovery.router)
app.include_router(prediction.router)
app.include_router(factors.router)
app.include_router(dividends.router)
app.include_router(backup.router)
app.include_router(corporate_actions.router)
app.include_router(tax.router)
app.include_router(journal.router)


@app.get("/api/health", tags=["system"])
def health() -> dict:
    """Application status and which optional integrations are configured.

    ``env_files`` reports where settings were looked for and whether each file
    exists — the quickest way to see why a key that "was added" is not being read.
    """
    from app.config import BACKEND_DIR, PROJECT_ROOT

    return {
        "status": "ok",
        "base_currency": settings.base_currency,
        "env_files": {
            str(path): path.exists()
            for path in (PROJECT_ROOT / ".env", BACKEND_DIR / ".env")
        },
        "integrations": {
            "twelvedata": bool(settings.twelvedata_api_key),
            "fmp": bool(settings.fmp_api_key),
            "edgar": settings.edgar_enabled,
            "perplexity": settings.perplexity_enabled,
        },
    }
