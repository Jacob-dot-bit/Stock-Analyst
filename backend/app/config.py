"""Application settings, read from the environment / the .env file.

No key is ever hardcoded. Features whose key is missing disable themselves cleanly
rather than failing startup.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    database_url: str = f"sqlite:///{DATA_DIR / 'stock_analyst.db'}"

    # --- Account base currency, used for portfolio totals ---
    base_currency: str = "EUR"

    # --- Optional API keys (phase 2 onwards) ---
    finnhub_api_key: str | None = None
    perplexity_api_key: str | None = None

    # SEC EDGAR requires a named User-Agent with a contact address. Without it
    # requests are rejected, so the EDGAR provider stays disabled.
    sec_user_agent: str | None = None

    # --- Cost guardrails for Perplexity (phase 6) ---
    perplexity_model: str = "sonar"
    perplexity_cache_ttl_days: int = 7

    # --- CORS: the Vite dev server origin ---
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
