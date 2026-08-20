"""Barchart daily price history (worldwide).

The API moved from ``ondemand.barchart.com`` to ``www.barchartondemand.com`` at some
point after this integration was first written; the old host 301-redirects there.
Verified live rather than assumed — see DEVLOG "Bug 2.5". Pointing at the current host
directly, the same fix applied to Frankfurter's FX provider for the same reason:
``httpx.get`` does not follow redirects by default, so the old URL would quietly parse
an HTML redirect page as JSON and fail with a confusing "invalid JSON response" instead
of a clear "moved."
"""

from __future__ import annotations

from datetime import date

import httpx

from app.providers.base import (
    Bar,
    InstrumentRef,
    PriceProvider,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    Throttle,
)

BARCHART_URL = "https://www.barchartondemand.com/v1/timeseries/queryEod"


class BarchartProvider(PriceProvider):
    """Barchart OnDemand REST API for global stocks.

    Free tier: 400 requests/day.
    """

    name = "barchart"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._throttle = Throttle(min_interval_seconds=0.25)

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def can_serve(self, ref: InstrumentRef) -> bool:
        return bool(ref.provider_symbol)

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        """Fetch daily bars from Barchart."""
        symbol = ref.provider_symbol

        self._throttle.wait()

        try:
            client = httpx.Client(timeout=15.0)
            response = client.get(
                BARCHART_URL,
                params={
                    "symbol": symbol,
                    "startDate": start.strftime("%Y%m%d"),
                    "endDate": end.strftime("%Y%m%d"),
                    "apikey": self.api_key,
                },
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimited("rate limited")
        if response.status_code == 401:
            raise ProviderUnavailable("invalid API key")
        if response.status_code >= 400:
            raise ProviderUnavailable(f"HTTP {response.status_code}")

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc

        if data.get("status", {}).get("code") != 200:
            error_msg = data.get("status", {}).get("message", "unknown error")
            if "not found" in error_msg.lower():
                raise SymbolNotFound(error_msg)
            raise ProviderUnavailable(error_msg)

        results = data.get("results", [])
        if not results:
            raise SymbolNotFound(f"no data for {symbol}")

        bars = []
        for result in results:
            bars.append(
                Bar(
                    bar_date=date.fromisoformat(result["timestamp"][:10]),
                    open=result.get("open"),
                    high=result.get("high"),
                    low=result.get("low"),
                    close=result.get("close"),
                    volume=result.get("volume"),
                )
            )

        return bars
