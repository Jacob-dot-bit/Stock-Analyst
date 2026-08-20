"""Finviz daily price history (US stocks via scraping)."""

from __future__ import annotations

from datetime import date

import httpx

from app.providers.base import (
    Bar,
    InstrumentRef,
    PriceProvider,
    ProviderUnavailable,
    SymbolNotFound,
    Throttle,
    is_us_listing,
)


class FinvizProvider(PriceProvider):
    """Finviz web scraping for US stock prices.

    No official API; relies on undocumented web endpoints.
    Fragile and prone to anti-bot detection.
    """

    name = "finviz"

    def __init__(self) -> None:
        self._throttle = Throttle(min_interval_seconds=2.0)  # Be respectful

    def is_enabled(self) -> bool:
        return True

    def can_serve(self, ref: InstrumentRef) -> bool:
        return is_us_listing(ref) and bool(ref.provider_symbol)

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        """Attempt to fetch daily bars from Finviz.

        Note: Finviz actively blocks bots and this endpoint is fragile.
        Should only be used as a last resort fallback.
        """
        # .split, not .rpartition: provider_symbol for a US ticker is already
        # bare (e.g. "AAPL", no dot at all), and rpartition(".")[0] on a
        # string with no "." returns "" — silently sending an empty ticker.
        # See DEVLOG "Bug 2.11".
        symbol = ref.provider_symbol.split(".")[0]

        self._throttle.wait()

        try:
            client = httpx.Client(timeout=15.0)
            response = client.get(
                f"https://finviz.com/quote.ashx",
                params={"t": symbol},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                },
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc

        if response.status_code >= 400:
            raise ProviderUnavailable(f"HTTP {response.status_code}")

        html = response.text

        # Check for anti-bot detection
        if "error" in html.lower() or "robot" in html.lower():
            raise ProviderUnavailable("blocked by anti-bot detection")

        # Finviz doesn't provide historical data via their web scraping.
        # This is a placeholder that returns SymbolNotFound to indicate
        # we cannot reliably scrape historical data from Finviz.
        # Finviz is only useful for real-time quotes via their charts.
        raise SymbolNotFound(
            "Finviz does not provide historical data via web scraping; "
            "consider using their real-time quote endpoint instead"
        )
