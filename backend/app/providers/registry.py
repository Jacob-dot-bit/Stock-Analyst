"""Builds the provider chain from settings.

Order matters: it is the fallback order. Yahoo comes first because it needs no key and
covers every market this portfolio touches; Twelve Data follows as the keyed backstop
for when Yahoo throttles.

Stooq was the original fallback and has been removed: it now answers with a JavaScript
proof-of-work challenge instead of CSV. Getting past that would mean defeating a
bot-detection mechanism, so the source was dropped rather than worked around. Boerse
Frankfurt took its place — it needs no key and no session, and it is the only free
source found that covers European venues.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.providers.base import ProviderChain
from app.providers.fmp import FmpProvider
from app.providers.frankfurt import FrankfurtProvider
from app.providers.twelvedata import TwelveDataProvider
from app.providers.yahoo import YahooProvider


@lru_cache
def get_provider_chain() -> ProviderChain:
    """Shared chain, so the per-provider throttles are process-wide.

    Building a fresh chain per request would reset the throttles and let concurrent
    refreshes burst — which is precisely what gets an IP rate-limited.
    """
    settings = get_settings()

    return ProviderChain(
        [
            YahooProvider(min_interval_seconds=settings.yahoo_min_interval_seconds),
            # Before Twelve Data: needs no key and covers European venues, which the
            # Twelve Data free tier does not. Only serves instruments that have an ISIN.
            FrankfurtProvider(),
            TwelveDataProvider(api_key=settings.twelvedata_api_key),
            # Last: keyed, and the only candidate that may cover Euronext venues,
            # which is where the remaining gap is.
            FmpProvider(api_key=settings.fmp_api_key),
        ]
    )
