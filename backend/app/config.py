"""Application settings, read from the environment / the .env file.

No key is ever hardcoded. Features whose key is missing disable themselves cleanly
rather than failing startup.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
DATA_DIR = PROJECT_ROOT / "data"

#: Values that look like a key but are the example text left in place. Treated as
#: unset: a placeholder sent to a provider yields an opaque 401, which is a far more
#: confusing failure than the feature simply staying disabled.
PLACEHOLDER_VALUES = {
    "votre_cle",
    "your_key",
    "your-api-key",
    "changeme",
    "xxx",
    "todo",
    "<your key here>",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Both locations are accepted because running commands from backend/ is natural
        # and putting .env there is an easy mistake to make. The project root wins when
        # both exist, since that is the documented location.
        env_file=(BACKEND_DIR / ".env", PROJECT_ROOT / ".env"),
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

    # Keyed fallback for price history, used when Yahoo throttles.
    twelvedata_api_key: str | None = None

    # --- Price fetching guardrails ---
    # Yahoo rate-limits hard: four rapid requests were enough to earn a 429 that
    # outlasted a minute. Spacing calls out is what keeps a full refresh working.
    yahoo_min_interval_seconds: float = 2.0
    # How long a single refresh request may spend before reporting what is left.
    refresh_budget_seconds: float = 60.0

    # SEC EDGAR requires a named User-Agent with a contact address. Without it
    # requests are rejected, so the EDGAR provider stays disabled.
    sec_user_agent: str | None = None

    # --- Cost guardrails for Perplexity (phase 6) ---
    perplexity_model: str = "sonar"
    perplexity_cache_ttl_days: int = 7

    # --- CORS: the Vite dev server origin ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator(
        "twelvedata_api_key",
        "finnhub_api_key",
        "perplexity_api_key",
        "sec_user_agent",
        mode="after",
    )
    @classmethod
    def _discard_placeholders(cls, value: str | None) -> str | None:
        """Treat leftover example text as if the key were not set at all.

        Someone copying the documented command verbatim ends up with
        ``TWELVEDATA_API_KEY=votre_cle``. Passing that to a provider produces an opaque
        401 halfway through a refresh; leaving the feature disabled is both honest and
        far easier to diagnose.
        """
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in PLACEHOLDER_VALUES:
            return None
        return cleaned

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
