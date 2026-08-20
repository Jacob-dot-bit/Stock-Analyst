"""API endpoints for managing application settings and API keys."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import PROJECT_ROOT, get_settings
from app.providers.alpha_vantage import AlphaVantageProvider
from app.providers.barchart import BarchartProvider
from app.providers.base import InstrumentRef, ProviderError, ProviderUnavailable, RateLimited, SymbolNotFound
from app.providers.edgar import EdgarProvider
from app.providers.eodhd import EodhidProvider
from app.providers.fmp import FmpProvider
from app.providers.intrinio import IntrinionProvider
from app.providers.marketstack import MarketstackProvider
from app.providers.perplexity import PerplexityClient
from app.providers.polygon import PolygonProvider
from app.providers.registry import get_alpha_vantage_provider, get_edgar_provider, get_provider_chain
from app.providers.tiingo import TiingoProvider
from app.providers.twelvedata import TwelveDataProvider

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Every keyed provider, for the "test this key" endpoint. All nine share the
# same `__init__(self, api_key: str)` shape, which is what makes a single
# generic verification endpoint possible instead of one per provider.
TESTABLE_PROVIDERS = {
    "polygon": PolygonProvider,
    "alpha_vantage": AlphaVantageProvider,
    "twelvedata": TwelveDataProvider,
    "fmp": FmpProvider,
    "tiingo": TiingoProvider,
    "barchart": BarchartProvider,
    "intrinio": IntrinionProvider,
    "eodhd": EodhidProvider,
    "marketstack": MarketstackProvider,
}

# Settings attribute holding each provider's currently-saved key, so "test my
# saved key" works without the frontend ever having to hold the real value
# (it only ever sees whether a key is *present*, never what it is).
SETTINGS_KEY_ATTR = {
    "polygon": "polygon_api_key",
    "alpha_vantage": "alpha_vantage_api_key",
    "twelvedata": "twelvedata_api_key",
    "fmp": "fmp_api_key",
    "tiingo": "tiingo_api_key",
    "barchart": "barchart_api_key",
    "intrinio": "intrinio_api_key",
    "eodhd": "eodhd_api_key",
    "marketstack": "marketstack_api_key",
}

# Providers whose `fetch_daily` always fails by design and so can't be used to
# test a key — verify-key falls back to `fetch_quote` for these instead.
# Currently just Tiingo: its free tier dropped historical date-range support
# entirely (see DEVLOG "Bug 2.9"); only the latest-day quote still works.
QUOTE_ONLY_PROVIDERS = {"tiingo"}

# AAPL is covered by every one of the nine testable providers' free tiers —
# picked purely as a reliable, universal probe, not because these providers
# are US-only.
_TEST_REF = InstrumentRef(provider_symbol="AAPL", broker_symbol="AAPL.US", name="Apple")


class ProviderStatus(BaseModel):
    name: str
    enabled: bool
    description: str | None = None
    #: Where to get a free API key. None for providers that need no key at all.
    signup_url: str | None = None
    #: Whether this provider has a key field to configure at all. False for
    #: Yahoo, Boursorama, Frankfurt, Eoddata and Finviz — none of them
    #: accept an ``api_key``, so showing an input for them would edit nothing.
    #: The frontend uses this to decide whether to render the field.
    has_api_key: bool = False


class ApiKeysStatus(BaseModel):
    polygon: bool
    alpha_vantage: bool
    tiingo: bool
    barchart: bool
    intrinio: bool
    eodhd: bool
    marketstack: bool
    twelvedata: bool
    fmp: bool
    sec_user_agent: bool
    perplexity: bool


@router.get("/providers", response_model=list[ProviderStatus])
async def get_provider_status() -> list[ProviderStatus]:
    """Get status of all available price providers."""
    chain = get_provider_chain()

    descriptions = {
        "yahoo": "Yahoo Finance (worldwide, no key needed)",
        "polygon": "Polygon.io (US + crypto, 5 req/min free)",
        "alpha_vantage": "Alpha Vantage (worldwide, 5 req/min free)",
        "boursorama": "Boursorama (Euronext Paris, no key needed)",
        "frankfurt": "Boerse Frankfurt (European ISIN, no key needed)",
        "twelvedata": "Twelve Data (US fallback, 800 req/day free)",
        "fmp": "Financial Modeling Prep (Euronext, 250 req/day free)",
        "tiingo": "Tiingo (worldwide, 500 req/day free)",
        "barchart": "Barchart (worldwide, 400 req/day free)",
        "intrinio": "Intrinio (US + Canada, 500 req/day free)",
        "eodhd": "EODHD (150+ bourses, 20 req/day free)",
        "marketstack": "Marketstack (worldwide, 100 req/month free — last resort)",
        "eoddata": "Eoddata (stocks/crypto/forex, no key needed)",
        "finviz": "Finviz (US stocks via scraping, fragile)",
        "sec_user_agent": "SEC EDGAR (US company fundamentals for the Value/Growth/Quality "
        "scores — free, no signup, just a contact identifier)",
        "perplexity": "Perplexity Sonar (qualitative commentary, one instrument at a time — "
        "paid, ~$5-14 per 1000 requests)",
    }

    # Where to sign up for a free key. Every key here is one of the fields
    # `UpdateApiKeysRequest` actually accepts — kept in that one-to-one
    # correspondence on purpose, so a provider never gets a link (or an input
    # field) for a key its code has nowhere to put.
    #
    # IEX Cloud, World Trading Data and Quandl are absent on purpose: all three
    # were verified live and found dead or migrated to an incompatible API —
    # see DEVLOG "Bug 2.5". Not just a stale link (like Polygon's rename to
    # massive.com below): there is no working key to sign up for.
    signup_urls = {
        # polygon.io rebranded to massive.com (same product, same API at
        # api.polygon.io — only the marketing/signup site moved) after this
        # integration was first written; verified live rather than assumed.
        "polygon": "https://massive.com/pricing",
        "alpha_vantage": "https://www.alphavantage.co/support/#api-key",
        "twelvedata": "https://twelvedata.com/pricing",
        "fmp": "https://site.financialmodelingprep.com/developer/docs",
        "tiingo": "https://www.tiingo.com/account/api/token",
        "barchart": "https://www.barchart.com/ondemand",
        "intrinio": "https://intrinio.com/account/api_keys",
        # eodhistoricaldata.com rebranded to eodhd.com; the old knowledgebase
        # path 404s post-redirect, /register is the current signup page.
        "eodhd": "https://eodhd.com/register",
        # World Trading Data's named successor — see DEVLOG "Bug 2.6".
        "marketstack": "https://marketstack.com/product",
        # No signup — this links to the SEC's own explanation of the
        # User-Agent requirement, not a registration page. See DEVLOG
        # "Decision 3s.1".
        "sec_user_agent": "https://www.sec.gov/os/webmaster-faq#developers",
        # Verified live: perplexity.ai/settings/api is where a key is
        # generated/managed today.
        "perplexity": "https://www.perplexity.ai/settings/api",
    }

    statuses = []
    for provider in chain.providers:
        statuses.append(
            ProviderStatus(
                name=provider.name,
                enabled=provider.is_enabled(),
                description=descriptions.get(provider.name),
                signup_url=signup_urls.get(provider.name),
                has_api_key=provider.name in signup_urls,
            )
        )

    # EDGAR isn't part of the price-provider chain — it's a separate registry
    # (`get_edgar_provider`) for fundamentals, not daily/live prices — so the
    # loop above never sees it. Appended manually so its (already fully
    # wired) `sec_user_agent` field actually gets a card on the Settings
    # page, instead of being configurable only by hand-editing `.env`. See
    # DEVLOG "Decision 3s.1".
    statuses.append(
        ProviderStatus(
            name="sec_user_agent",
            enabled=get_edgar_provider().is_enabled(),
            description=descriptions["sec_user_agent"],
            signup_url=signup_urls["sec_user_agent"],
            has_api_key=True,
        )
    )

    # Same reasoning as sec_user_agent above: Perplexity is qualitative
    # commentary (`app/providers/perplexity.py`), not a price source, so
    # `get_provider_chain()` never sees it either — without this manual
    # append, `perplexity_api_key` (already accepted by the endpoints below)
    # had no card on the Settings page to be entered/tested through at all.
    statuses.append(
        ProviderStatus(
            name="perplexity",
            enabled=get_settings().perplexity_enabled,
            description=descriptions["perplexity"],
            signup_url=signup_urls["perplexity"],
            has_api_key=True,
        )
    )

    return statuses


@router.get("/api-keys", response_model=ApiKeysStatus)
async def get_api_keys_status() -> ApiKeysStatus:
    """Get which API keys are configured (without revealing values)."""
    settings = get_settings()

    return ApiKeysStatus(
        polygon=bool(settings.polygon_api_key),
        alpha_vantage=bool(settings.alpha_vantage_api_key),
        tiingo=bool(settings.tiingo_api_key),
        barchart=bool(settings.barchart_api_key),
        intrinio=bool(settings.intrinio_api_key),
        eodhd=bool(settings.eodhd_api_key),
        marketstack=bool(settings.marketstack_api_key),
        twelvedata=bool(settings.twelvedata_api_key),
        fmp=bool(settings.fmp_api_key),
        sec_user_agent=bool(settings.sec_user_agent),
        perplexity=bool(settings.perplexity_api_key),
    )


class VerifyKeyRequest(BaseModel):
    provider: str
    #: The key to test. Omit (or leave blank) to test the key already saved
    #: for this provider instead — lets "test" work on a masked, already-saved
    #: field without the frontend ever reading the real value back out.
    api_key: str | None = None


class VerifyKeyResponse(BaseModel):
    valid: bool
    message: str


@router.post("/verify-key", response_model=VerifyKeyResponse)
async def verify_api_key(payload: VerifyKeyRequest) -> VerifyKeyResponse:
    """Test a key against the real provider, without saving it.

    Catches a typo'd or expired key immediately instead of the alternative:
    the provider silently sits disabled or failing, and the first sign
    anything is wrong is a thinner-than-expected refresh report days later.
    """
    # EDGAR isn't a `PriceProvider` (no fetch_daily/fetch_quote), so it can't
    # go through the generic path below — tested directly instead by asking
    # SEC EDGAR to resolve a real, always-present ticker with the given
    # contact string. A rejected User-Agent surfaces as `ProviderUnavailable`
    # (SEC returns 403). See DEVLOG "Decision 3s.1".
    if payload.provider == "sec_user_agent":
        key = payload.api_key.strip() if payload.api_key else None
        if not key:
            key = get_settings().sec_user_agent
        if not key:
            return VerifyKeyResponse(
                valid=False, message="No contact string to test — type one or save one first."
            )
        try:
            _cik, registrant = EdgarProvider(user_agent=key, min_interval_seconds=0).resolve("AAPL")
        except ProviderUnavailable as exc:
            return VerifyKeyResponse(valid=False, message=f"Rejected by SEC EDGAR: {exc}")
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            return VerifyKeyResponse(valid=False, message=f"Could not reach SEC EDGAR: {exc}")
        # `registrant` (e.g. "Apple Inc.") already ends in a period as often
        # as not — no second one appended, unlike the other outcome messages.
        return VerifyKeyResponse(valid=True, message=f"Accepted — SEC EDGAR resolved AAPL to {registrant}")

    # Same reasoning as sec_user_agent above: Perplexity isn't a
    # `PriceProvider` either, so it can't go through the generic path below.
    # Tested with one minimal, cheap real call (max_tokens=16) rather than a
    # separate lighter-weight endpoint — this is the only code path that
    # actually reaches Perplexity, so it's worth exercising directly.
    if payload.provider == "perplexity":
        key = payload.api_key.strip() if payload.api_key else None
        if not key:
            key = get_settings().perplexity_api_key
        if not key:
            return VerifyKeyResponse(valid=False, message="No key to test — type one or save one first.")
        client = PerplexityClient(api_key=key, model=get_settings().perplexity_model)
        try:
            commentary = client.ask_about("AAPL", name="Apple Inc.", max_tokens=16)
        except RateLimited:
            return VerifyKeyResponse(
                valid=True, message="Key looks valid, but Perplexity is rate-limiting right now."
            )
        except ProviderError as exc:
            return VerifyKeyResponse(valid=False, message=f"Key rejected: {exc}")
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            return VerifyKeyResponse(valid=False, message=f"Could not reach Perplexity: {exc}")
        return VerifyKeyResponse(
            valid=True, message=f"Key works — Sonar responded ({len(commentary.content)} chars)."
        )

    provider_cls = TESTABLE_PROVIDERS.get(payload.provider)
    if provider_cls is None:
        raise HTTPException(
            status_code=400,
            detail=f"'{payload.provider}' does not accept a key, or is not a known provider.",
        )

    key = payload.api_key.strip() if payload.api_key else None
    if not key:
        settings = get_settings()
        key = getattr(settings, SETTINGS_KEY_ATTR[payload.provider], None)
    if not key:
        return VerifyKeyResponse(valid=False, message="No key to test — type one or save one first.")

    provider = provider_cls(api_key=key)
    today = datetime.now(UTC).date()

    try:
        if payload.provider in QUOTE_ONLY_PROVIDERS:
            price = provider.fetch_quote(_TEST_REF)
            if price is not None:
                return VerifyKeyResponse(valid=True, message=f"Key works — latest quote: {price}.")
            return VerifyKeyResponse(valid=True, message="Key accepted, but no quote came back for the test symbol.")

        bars = provider.fetch_daily(_TEST_REF, today - timedelta(days=5), today)
    except RateLimited:
        # The provider accepted the key well enough to rate-limit us rather
        # than reject the key outright — that is itself evidence the key is
        # valid, just not something to test again in the next few minutes.
        return VerifyKeyResponse(
            valid=True, message="Key looks valid, but the provider is rate-limiting right now."
        )
    except SymbolNotFound:
        return VerifyKeyResponse(
            valid=True,
            message="Key looks valid (the provider answered; it just doesn't have the test symbol).",
        )
    except ProviderError as exc:
        return VerifyKeyResponse(valid=False, message=f"Key rejected: {exc}")
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        return VerifyKeyResponse(valid=False, message=f"Could not reach the provider: {exc}")

    if bars:
        return VerifyKeyResponse(valid=True, message=f"Key works — received {len(bars)} day(s) of data.")
    return VerifyKeyResponse(valid=True, message="Key accepted, but no data came back for the test symbol.")


class UpdateApiKeysRequest(BaseModel):
    polygon: str | None = None
    alpha_vantage: str | None = None
    tiingo: str | None = None
    barchart: str | None = None
    intrinio: str | None = None
    eodhd: str | None = None
    marketstack: str | None = None
    twelvedata: str | None = None
    fmp: str | None = None
    sec_user_agent: str | None = None
    perplexity: str | None = None


class UpdateApiKeysResponse(BaseModel):
    status: str
    message: str


@router.put("/api-keys", response_model=UpdateApiKeysResponse)
async def update_api_keys(payload: UpdateApiKeysRequest) -> UpdateApiKeysResponse:
    """Update API keys by writing to .env file."""
    env_path = PROJECT_ROOT / ".env"

    try:
        # Read existing .env
        env_dict = {}
        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        env_dict[key.strip()] = value.strip()

        # Update with new values
        mapping = {
            "polygon": "POLYGON_API_KEY",
            "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
            "tiingo": "TIINGO_API_KEY",
            "barchart": "BARCHART_API_KEY",
            "intrinio": "INTRINIO_API_KEY",
            "eodhd": "EODHD_API_KEY",
            "marketstack": "MARKETSTACK_API_KEY",
            "twelvedata": "TWELVEDATA_API_KEY",
            "fmp": "FMP_API_KEY",
            "sec_user_agent": "SEC_USER_AGENT",
            "perplexity": "PERPLEXITY_API_KEY",
        }

        for field, env_key in mapping.items():
            value = getattr(payload, field, None)
            if value is not None:
                env_dict[env_key] = value
            elif env_key in env_dict and value == "":
                # Clear the key if empty string provided
                del env_dict[env_key]

        # Write back to .env. This file is the only copy of these secrets
        # anywhere (deliberately gitignored, never backed up) — an unclean
        # shutdown minutes after a plain write can lose it, since closing a
        # file only flushes Python's buffer into the OS page cache, not onto
        # the physical disk. fsync forces that last step before we report
        # success, so a confirmed save is actually durable.
        with open(env_path, "w") as f:
            for key, value in env_dict.items():
                f.write(f"{key}={value}\n")
            f.flush()
            os.fsync(f.fileno())
        # A plain open(path, "w") on a fresh file inherits the umask (typically
        # world/group-readable) — restrict it every time it's rewritten, not just
        # once at startup, since this is the path that recreates the file.
        env_path.chmod(0o600)

        # Clear the cached settings to force reload. Every separately
        # `@lru_cache`d provider factory must be cleared too, or it keeps
        # returning the same instance — built with whatever keys were set
        # the first time it ran — forever. Missing one here is exactly how
        # `sec_user_agent` stayed "disabled" after a real save until this was
        # caught live: `get_provider_chain` was cleared, `get_edgar_provider`
        # was not, since EDGAR isn't part of that chain (Decision 3r.1) and
        # was overlooked when this list was last touched. See DEVLOG
        # "Decision 3s.1".
        get_settings.cache_clear()
        get_provider_chain.cache_clear()
        get_edgar_provider.cache_clear()
        get_alpha_vantage_provider.cache_clear()

        return UpdateApiKeysResponse(
            status="success",
            message="API keys updated. Settings have been reloaded.",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {exc}") from exc
