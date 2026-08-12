"""Stock Analyst API entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.routers import imports, portfolio, prices


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

app.include_router(portfolio.router)
app.include_router(imports.router)
app.include_router(prices.router)


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
            "finnhub": settings.finnhub_enabled,
            "twelvedata": bool(settings.twelvedata_api_key),
            "edgar": settings.edgar_enabled,
            "perplexity": settings.perplexity_enabled,
        },
    }
