"""Builds the provider chain from settings.

Order matters: it is the fallback order. Yahoo comes first because it needs no key and
covers every market this portfolio touches; Twelve Data follows as the keyed backstop
for when Yahoo throttles.

Stooq was the original fallback and was decided against back in Decision 2.1 ("Stooq
as the fallback price source" → dropped): its export endpoint now answers with a
JavaScript proof-of-work challenge instead of CSV, and defeating that would mean
circumventing a bot-detection mechanism, which this project will not do. That decision
was never actually carried out in code, though — `StooqProvider` stayed registered here
for months, silently contributing nothing (confirmed live during the phase-2 cleanup
that finally removed it, DEVLOG "Decision 3q.1": its endpoint now 404s outright, and the
still-live URL Decision 2.1 originally tested serves the exact same challenge). Boerse
Frankfurt took its place — it needs no key and no session, and it is the only free
source found that covers European venues.

IEX Cloud, World Trading Data and Quandl (the WIKI dataset) were removed after being
verified live and found genuinely dead, not just moved: IEX Cloud's API refuses the TLS
handshake outright (the service was shut down), World Trading Data's endpoint returned an
explicit "deprecated and shut down, migrate to marketstack.com" JSON payload, and
Quandl's WIKI dataset (discontinued in 2018) sits behind a bot-detection wall. None of
these could be fixed with a URL update the way Frankfurter's and Polygon's moves were —
see DEVLOG "Bug 2.5" for the full audit and reasoning.

Marketstack was added as World Trading Data's named successor — its own shutdown message
pointed here, and the API was verified live rather than assumed. Its free tier is thin
(100 requests/month, not per day), so it sits near the end of the chain: reached only when
every more generous source has already failed on a given instrument, which keeps monthly
usage low. See DEVLOG "Bug 2.6".

Twelve Data moved ahead of Polygon (was #6, now #2) once usage tracking (DEVLOG "Decision
3m.1") made it measurable that they cover the exact same US holdings for this portfolio —
Twelve Data throttles to one request per 8s against an 800/day quota, Polygon to one per
12s against a much tighter 5/minute; every real refresh was serialising a large chunk of
the portfolio through the slower of two equally-capable sources purely because Polygon
happened to be added earlier in the list. See DEVLOG "Decision 3n.2".
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.providers.base import ProviderChain
from app.providers.barchart import BarchartProvider
from app.providers.boursorama import BoursoramaProvider
from app.providers.edgar import EdgarProvider
from app.providers.esef import EsefProvider
from app.providers.eoddata import EoddataProvider
from app.providers.eodhd import EodhidProvider
from app.providers.finviz import FinvizProvider
from app.providers.fmp import FmpProvider
from app.providers.frankfurt import FrankfurtProvider
from app.providers.intrinio import IntrinionProvider
from app.providers.marketstack import MarketstackProvider
from app.providers.polygon import PolygonProvider
from app.providers.tiingo import TiingoProvider
from app.providers.twelvedata import TwelveDataProvider
from app.providers.yahoo import YahooProvider
from app.providers.alpha_vantage import AlphaVantageProvider


@lru_cache
def get_provider_chain() -> ProviderChain:
    """Shared chain, so the per-provider throttles are process-wide.

    Building a fresh chain per request would reset the throttles and let concurrent
    refreshes burst — which is precisely what gets an IP rate-limited.
    """
    settings = get_settings()

    return ProviderChain(
        providers=[
            # 1. Free, worldwide, rate-limits hard but is the most reliable
            YahooProvider(min_interval_seconds=settings.yahoo_min_interval_seconds),
            # 2. US backstop for when Yahoo throttles — same coverage as Polygon
            # (below) for this portfolio, but 8s/request against an 800/day quota
            # vs Polygon's 12s against 5/minute: tried first so the common case
            # (Yahoo cooling down, most holdings falling back) serialises through
            # the faster, more generous of the two. See DEVLOG "Decision 3n.2".
            TwelveDataProvider(api_key=settings.twelvedata_api_key),
            # 3. US + crypto, good alternative when Twelve Data is unavailable too
            PolygonProvider(api_key=settings.polygon_api_key),
            # 4. Worldwide coverage, slower tier than Polygon
            AlphaVantageProvider(api_key=settings.alpha_vantage_api_key),
            # 5. Euronext Paris (no key), before other European sources
            BoursoramaProvider(),
            # 6. European shares via Frankfurt (ISIN-based, no key)
            FrankfurtProvider(),
            # 7. FMP fallback (Euronext coverage on free tier verified)
            FmpProvider(api_key=settings.fmp_api_key),
            # 8. Quote-only (see providers/tiingo.py): free-tier historical
            # ranges were deprecated by Tiingo, so this contributes nothing to
            # fetch_daily and only serves fetch_quote (live-estimate refresh)
            TiingoProvider(api_key=settings.tiingo_api_key),
            # 9. Worldwide, 400 req/day free tier
            BarchartProvider(api_key=settings.barchart_api_key),
            # 10. US + Canada, 500 req/day free tier
            IntrinionProvider(api_key=settings.intrinio_api_key),
            # 11. 150+ global bourses, 20 req/day free tier
            EodhidProvider(api_key=settings.eodhd_api_key),
            # 12. Stocks/crypto/forex, no key needed
            EoddataProvider(),
            # 13. Real API but a thin 100 req/month free tier — last of the
            # keyed sources so it is only spent on what nothing else covered
            MarketstackProvider(api_key=settings.marketstack_api_key),
            # 14. Last resort: US stocks via web scraping (fragile)
            FinvizProvider(),
        ],
        cooldown_seconds=settings.provider_cooldown_seconds,
    )


@lru_cache
def get_edgar_provider() -> EdgarProvider:
    """Shared instance, same reasoning as `get_provider_chain`: `EdgarProvider`
    caches the SEC ticker index in-process after its first request, and a
    fresh instance per call would throw that away and re-fetch it every time.
    Disabled (see `EdgarProvider.is_enabled`) until `SEC_USER_AGENT` is set.
    """
    return EdgarProvider(user_agent=get_settings().sec_user_agent)


@lru_cache
def get_esef_provider() -> EsefProvider:
    """Shared instance, same reasoning as `get_edgar_provider` — the ~7,300-
    entity ESEF index is fetched once and cached in-process, not re-fetched
    per call. No settings dependency: ESEF needs no key. See DEVLOG "Decision
    3t.1".
    """
    return EsefProvider()


@lru_cache
def get_alpha_vantage_provider() -> AlphaVantageProvider:
    """The exact `AlphaVantageProvider` instance living inside the shared
    price chain (`get_provider_chain`), not a fresh one — so a news-sentiment
    call (`routers/insights.py`) and a price call share one `Throttle` and
    never together exceed Alpha Vantage's real 5-req/min limit.
    """
    for provider in get_provider_chain().providers:
        if provider.name == "alpha_vantage":
            return provider
    raise RuntimeError("alpha_vantage provider missing from the chain")


@lru_cache
def get_fmp_provider() -> FmpProvider:
    """The exact `FmpProvider` instance living inside the shared price
    chain, same reasoning as `get_alpha_vantage_provider` — a corporate-
    action split lookup (`app/corporate_actions/service.py::detect_splits`)
    shares FMP's 250/day quota and `Throttle` with regular price refreshes
    rather than bursting through a second, unsynchronised instance. FMP
    replaced Yahoo as the split-detection source — see DEVLOG "Decision
    3u.34" — after Yahoo's real-portfolio scan proved to rate-limit
    inconsistently even when a raw single-symbol check succeeded.
    """
    for provider in get_provider_chain().providers:
        if provider.name == "fmp":
            return provider
    raise RuntimeError("fmp provider missing from the chain")


@lru_cache
def get_polygon_provider() -> PolygonProvider:
    """The exact `PolygonProvider` instance living inside the shared price
    chain, same reasoning as `get_fmp_provider` — a corporate-action split
    lookup (`app/corporate_actions/service.py::detect_splits`) shares
    Polygon's 5/minute quota and `Throttle` with regular price refreshes
    rather than bursting through a second, unsynchronised instance. Joined
    Alpha Vantage as an automatic cross-checking source for split detection
    — see DEVLOG "Decision 3u.41".
    """
    for provider in get_provider_chain().providers:
        if provider.name == "polygon":
            return provider
    raise RuntimeError("polygon provider missing from the chain")


@lru_cache
def get_eodhd_provider() -> EodhidProvider:
    """The exact `EodhidProvider` instance living inside the shared price
    chain, same reasoning as `get_fmp_provider` — shares EODHD's tight
    20/day quota and `Throttle` with regular price refreshes. Used only for
    the targeted, one-instrument-at-a-time corporate-action fallback
    (`app/corporate_actions/service.py::detect_one`) — never an automatic
    bulk source, deliberately, given that quota. See DEVLOG "Decision 3u.35".
    """
    for provider in get_provider_chain().providers:
        if provider.name == "eodhd":
            return provider
    raise RuntimeError("eodhd provider missing from the chain")


@lru_cache
def get_yahoo_provider() -> YahooProvider:
    """The exact `YahooProvider` instance living inside the shared price
    chain, same reasoning as `get_alpha_vantage_provider` — Yahoo's chart
    endpoint rate-limits hard (see `providers/yahoo.py`'s module docstring),
    so a corporate-action split lookup (`app/corporate_actions/service.py`)
    must share its `Throttle` with regular price refreshes rather than burst
    through a second, unsynchronised instance.
    """
    for provider in get_provider_chain().providers:
        if provider.name == "yahoo":
            return provider
    raise RuntimeError("yahoo provider missing from the chain")
