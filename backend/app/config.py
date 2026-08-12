"""Configuration de l'application, lue depuis l'environnement / le fichier .env.

Aucune clé n'est écrite en dur. Les fonctionnalités dont la clé est absente
se désactivent proprement plutôt que de faire échouer le démarrage.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> racine du projet
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Base de données ---
    database_url: str = f"sqlite:///{DATA_DIR / 'stock_analyst.db'}"

    # --- Devise de référence du compte, utilisée pour les totaux du portefeuille ---
    base_currency: str = "EUR"

    # --- Clés API optionnelles (phases 2+) ---
    finnhub_api_key: str | None = None
    perplexity_api_key: str | None = None

    # SEC EDGAR impose un User-Agent nominatif avec une adresse de contact.
    # Sans lui, les requêtes sont rejetées : le provider EDGAR reste alors désactivé.
    sec_user_agent: str | None = None

    # --- Garde-fous de coût pour Perplexity (phase 6) ---
    perplexity_model: str = "sonar"
    perplexity_cache_ttl_days: int = 7

    # --- CORS : origine du serveur de dev Vite ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def perplexity_enabled(self) -> bool:
        return bool(self.perplexity_api_key)

    @property
    def edgar_enabled(self) -> bool:
        return bool(self.sec_user_agent)

    @property
    def finnhub_enabled(self) -> bool:
        return bool(self.finnhub_api_key)


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()
