"""Marketstack daily price history (worldwide).

Successor to World Trading Data: WTD's own API explicitly told us it had shut
down and pointed here (see DEVLOG "Bug 2.5"/2.6). Free tier is unusually thin —
100 requests **per month**, not per day — so this sits last in the fallback
chain: it should only ever be asked about an instrument every other source in
the chain has already failed on, which keeps monthly usage low without needing
an aggressive throttle here.
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

MARKETSTACK_URL = "https://api.marketstack.com/v1/eod"


class MarketstackProvider(PriceProvider):
    """Marketstack (apilayer) REST API for global stocks.

    Free tier: 100 requests/month — deliberately not relied on for routine
    coverage, only as a last-resort fallback.
    """

    name = "marketstack"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._throttle = Throttle(min_interval_seconds=1.0)

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def can_serve(self, ref: InstrumentRef) -> bool:
        return bool(ref.provider_symbol)

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        """Fetch daily bars from Marketstack."""
        symbol = ref.provider_symbol

        self._throttle.wait()

        try:
            client = httpx.Client(timeout=15.0)
            response = client.get(
                MARKETSTACK_URL,
                params={
                    "access_key": self.api_key,
                    "symbols": symbol,
                    "date_from": start.isoformat(),
                    "date_to": end.isoformat(),
                    "limit": 1000,
                },
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimited("rate limited")
        if response.status_code in (401, 403):
            raise ProviderUnavailable("invalid API key")
        if response.status_code >= 400:
            raise ProviderUnavailable(f"HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc

        if "error" in payload:
            code = payload["error"].get("code", "")
            if "invalid" in str(code).lower() or "not_found" in str(code).lower():
                raise SymbolNotFound(payload["error"].get("message", symbol))
            raise ProviderUnavailable(payload["error"].get("message", str(code)))

        rows = payload.get("data") or []
        if not rows:
            raise SymbolNotFound(f"no data for {symbol}")

        bars = []
        for row in rows:
            close = row.get("close")
            if close is None:
                continue
            bars.append(
                Bar(
                    bar_date=date.fromisoformat(row["date"][:10]),
                    open=row.get("open"),
                    high=row.get("high"),
                    low=row.get("low"),
                    close=close,
                    volume=row.get("volume"),
                )
            )

        if not bars:
            raise SymbolNotFound(f"no data for {symbol}")

        return bars
