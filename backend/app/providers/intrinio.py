"""Intrinio daily price history (US + Canada)."""

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


class IntrinionProvider(PriceProvider):
    """Intrinio REST API for US and Canadian stocks.

    Free tier: 500 requests/day.
    """

    name = "intrinio"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._throttle = Throttle(min_interval_seconds=0.2)

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def can_serve(self, ref: InstrumentRef) -> bool:
        return bool(ref.provider_symbol)

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        """Fetch daily bars from Intrinio."""
        # .split, not .rpartition: see DEVLOG "Bug 2.11" — provider_symbol
        # for a US ticker is already bare ("AAPL", no dot), and
        # rpartition(".")[0] on a string with no "." returns "", silently
        # sending an empty ticker rather than the intended one.
        symbol = ref.provider_symbol.split(".")[0]

        self._throttle.wait()

        try:
            client = httpx.Client(timeout=15.0)
            response = client.get(
                f"https://api-v2.intrinio.com/securities/{symbol}/prices",
                params={
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "api_key": self.api_key,
                },
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimited("rate limited")
        if response.status_code == 401:
            raise ProviderUnavailable("invalid API key")
        if response.status_code == 404:
            raise SymbolNotFound(f"symbol not found: {symbol}")
        if response.status_code >= 400:
            raise ProviderUnavailable(f"HTTP {response.status_code}")

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc

        results = data.get("data", [])
        if not results:
            raise SymbolNotFound(f"no data for {symbol}")

        bars = []
        for result in results:
            bars.append(
                Bar(
                    bar_date=date.fromisoformat(result["date"]),
                    open=result.get("open"),
                    high=result.get("high"),
                    low=result.get("low"),
                    close=result.get("close"),
                    volume=result.get("volume"),
                )
            )

        return bars
