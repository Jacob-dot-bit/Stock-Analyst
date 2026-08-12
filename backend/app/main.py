"""Point d'entrée de l'API Stock Analyst."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.routers import imports, portfolio


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


settings = get_settings()

app = FastAPI(
    title="Stock Analyst",
    description=(
        "Suivi et analyse d'un portefeuille d'actions. Les données de portefeuille "
        "proviennent d'un export de fichier courtier : l'API XTB a été supprimée le "
        "14 mars 2025 et aucune synchronisation automatique n'est possible.\n\n"
        "Cet outil produit des indicateurs, pas des conseils en investissement."
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


@app.get("/api/health", tags=["system"])
def health() -> dict:
    """État de l'application et des intégrations optionnelles."""
    return {
        "status": "ok",
        "base_currency": settings.base_currency,
        "integrations": {
            "finnhub": settings.finnhub_enabled,
            "edgar": settings.edgar_enabled,
            "perplexity": settings.perplexity_enabled,
        },
    }
