"""Eoddata daily price history (actions + crypto + Forex)."""

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
)


class EoddataProvider(PriceProvider):
    """Eoddata REST API for stocks, crypto, and forex.

    No authentication required; open data.
    """

    name = "eoddata"

    def __init__(self) -> None:
        self._throttle = Throttle(min_interval_seconds=1.0)

    def is_enabled(self) -> bool:
        return True

    def can_serve(self, ref: InstrumentRef) -> bool:
        return bool(ref.provider_symbol)

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        """Fetch daily bars from Eoddata."""
        symbol = ref.provider_symbol

        self._throttle.wait()

        try:
            client = httpx.Client(timeout=15.0)
            response = client.get(
                f"https://eoddata.com/api/get-hist.php",
                params={
                    "s": symbol,
                    "d": start.strftime("%Y%m%d"),
                    "to": end.strftime("%Y%m%d"),
                    "o": "json",
                },
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc

        if response.status_code >= 400:
            raise ProviderUnavailable(f"HTTP {response.status_code}")

        try:
            results = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc

        if isinstance(results, dict) and results.get("error"):
            raise SymbolNotFound(results["error"])
        if not results:
            raise SymbolNotFound(f"no data for {symbol}")

        bars = []
        for result in results:
            bars.append(
                Bar(
                    bar_date=date.fromisoformat(result["Date"]),
                    open=float(result.get("Open", 0)),
                    high=float(result.get("High", 0)),
                    low=float(result.get("Low", 0)),
                    close=float(result.get("Close", 0)),
                    volume=float(result.get("Volume", 0)),
                )
            )

        return bars
