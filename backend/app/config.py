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
#: Timestamped copies of the live SQLite file — see `backup/service.py`.
#: Deliberately separate from DATA_DIR: a backup is a snapshot, not live
#: data, and keeping the two apart makes "what's the real database" always
#: unambiguous.
BACKUP_DIR = PROJECT_ROOT / "backups"

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

    # --- Benchmark for the historical value chart's comparison overlay ---
    # Not a held position: a normal Instrument row constructed directly from
    # these two symbols (see prices/history_service.py's
    # get_or_create_benchmark_instrument), bypassing symbol-mapping entirely —
    # there is no broker row to resolve from. Defaults to an S&P 500 ETF
    # rather than a raw index ticker (`^GSPC`) so it flows through the exact
    # same provider machinery as any other holding, live-verified against the
    # real provider chain before being set as the default (DEVLOG "Decision
    # 3e.1") — Yahoo was rate-limited at verification time, and the chain
    # failed over to Polygon, which served real bars.
    benchmark_broker_symbol: str | None = "SPY.US"
    benchmark_provider_symbol: str | None = "SPY"
    benchmark_name: str | None = "S&P 500 (SPY)"

    # --- Optional API keys (phase 2 onwards) ---
    perplexity_api_key: str | None = None

    # Keyed fallback for price history, used when Yahoo throttles.
    twelvedata_api_key: str | None = None
    # Candidate for Euronext coverage, which the Twelve Data free tier lacks.
    fmp_api_key: str | None = None

    # --- Phase 2+ : Price data sources ---
    # Eoddata and Finviz are keyless providers (no `api_key` parameter on
    # their `PriceProvider` classes) — there was never a setting for them to read,
    # so no key field exists here either. Adding one back would be UI clutter with
    # nothing behind it, exactly the mistake this comment is here to prevent.
    #
    # IEX Cloud, World Trading Data, Quandl and Stooq were removed entirely
    # (provider, setting and all) after being verified live and found genuinely
    # dead — see `providers/registry.py`'s module docstring and DEVLOG "Bug 2.5"
    # (IEX/WTD/Quandl) and "Decision 3q.1" (Stooq).
    polygon_api_key: str | None = None
    alpha_vantage_api_key: str | None = None
    tiingo_api_key: str | None = None
    barchart_api_key: str | None = None
    intrinio_api_key: str | None = None
    eodhd_api_key: str | None = None
    #: World Trading Data's named successor (see DEVLOG "Bug 2.6"). Thin free
    #: tier (100 req/month), so placed near the end of the fallback chain.
    marketstack_api_key: str | None = None

    # --- Price fetching guardrails ---
    # Yahoo rate-limits hard: four rapid requests were enough to earn a 429 that
    # outlasted a minute. Spacing calls out is what keeps a full refresh working.
    # 5s rather than 2: the observed block came from bursts during development, and a
    # portfolio refresh is not latency-sensitive. Being slower is what keeps it working.
    yahoo_min_interval_seconds: float = 5.0
    # After a 429, leave that provider alone for this long instead of retrying it on
    # every remaining instrument.
    provider_cooldown_seconds: float = 900.0
    # How long a single refresh request may spend before reporting what is left.
    # 300s (5 min) covers a ~37-holding portfolio in roughly one click at the
    # observed ~10s/instrument average across this app's provider throttles,
    # rather than needing 6-7 separate clicks at the previous 60s default.
    refresh_budget_seconds: float = 300.0

    # SEC EDGAR requires a named User-Agent with a contact address. Without it
    # requests are rejected, so the EDGAR provider stays disabled.
    sec_user_agent: str | None = None

    # --- Phase 3: scoring engine ---
    # Pillar/metric weights and thresholds, kept out of code so tuning them never
    # needs a deploy. See DEVLOG "Decision 3r.1".
    scoring_config_path: Path = BACKEND_DIR / "scoring.yaml"

    # --- Cost guardrails for Perplexity (phase 6) ---
    perplexity_model: str = "sonar"
    perplexity_cache_ttl_days: int = 7

    # --- CORS: the Vite dev server origin ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator(
        "twelvedata_api_key",
        "fmp_api_key",
        "perplexity_api_key",
        "sec_user_agent",
        "polygon_api_key",
        "alpha_vantage_api_key",
        "tiingo_api_key",
        "barchart_api_key",
        "intrinio_api_key",
        "eodhd_api_key",
        "marketstack_api_key",
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
    def polygon_enabled(self) -> bool:
        return bool(self.polygon_api_key)

    @property
    def alpha_vantage_enabled(self) -> bool:
        return bool(self.alpha_vantage_api_key)

    @property
    def tiingo_enabled(self) -> bool:
        return bool(self.tiingo_api_key)

    @property
    def barchart_enabled(self) -> bool:
        return bool(self.barchart_api_key)

    @property
    def intrinio_enabled(self) -> bool:
        return bool(self.intrinio_api_key)

    @property
    def eodhd_enabled(self) -> bool:
        return bool(self.eodhd_api_key)

    @property
    def marketstack_enabled(self) -> bool:
        return bool(self.marketstack_api_key)

    @property
    def benchmark_enabled(self) -> bool:
        return bool(self.benchmark_broker_symbol and self.benchmark_provider_symbol)


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.chmod(0o700)
    # .env holds provider API keys in plaintext (Decision 2.7) — restricted to the
    # owning user so another account on a shared machine can't just read them.
    # Both locations pydantic-settings checks; either may exist, or neither yet.
    for env_path in (BACKEND_DIR / ".env", PROJECT_ROOT / ".env"):
        if env_path.exists():
            env_path.chmod(0o600)
    return Settings()
