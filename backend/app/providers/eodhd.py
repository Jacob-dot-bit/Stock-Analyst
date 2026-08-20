"""EODHD daily price history (150+ bourses mondiales)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import httpx

from app.providers.base import (
    Bar,
    InstrumentRef,
    PriceProvider,
    ProviderUnavailable,
    RateLimited,
    SplitEvent,
    SymbolNotFound,
    Throttle,
    is_us_listing,
)


class EodhidProvider(PriceProvider):
    """EODHD REST API for 150+ global exchanges.

    Free tier: 20 requests/day.
    """

    name = "eodhd"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self._throttle = Throttle(min_interval_seconds=5.0)  # ~20/day = ~5s spacing
        # Only used by fetch_splits, for unit-testing via a mock transport —
        # fetch_daily keeps its own inline client, untouched, to avoid any
        # risk to its already-verified behavior.
        self._client = client

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def can_serve(self, ref: InstrumentRef) -> bool:
        return bool(ref.provider_symbol)

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        """Fetch daily bars from EODHD."""
        symbol = ref.provider_symbol

        self._throttle.wait()

        try:
            client = httpx.Client(timeout=15.0)
            response = client.get(
                f"https://eodhd.com/api/eod/{symbol}",
                params={
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "api_token": self.api_key,
                    "fmt": "json",
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
            results = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc

        if isinstance(results, dict) and "error" in results:
            raise SymbolNotFound(results["error"])
        if not results:
            raise SymbolNotFound(f"no data for {symbol}")

        bars = []
        for result in results:
            bars.append(
                Bar(
                    bar_date=date.fromisoformat(result["date"][:10]),
                    open=result.get("open"),
                    high=result.get("high"),
                    low=result.get("low"),
                    close=result.get("close"),
                    volume=result.get("volume"),
                )
            )

        return bars

    def fetch_splits(
        self,
        ref: InstrumentRef,
        start: date,
        end: date,
        on_attempt: Callable[[str], None] | None = None,
        on_bytes: Callable[[str, int], None] | None = None,
    ) -> list[SplitEvent]:
        """Split/reverse-split history via `/api/splits/{symbol}` — verified
        live against APLD, the one case FMP's free tier won't answer for
        (`402 PlanLimited`): EODHD correctly returned its real 1:6 reverse
        split (`{"date": "2022-04-13", "split": "1.000000/6.000000"}`).

        Unlike `fetch_daily`'s bare `{symbol}` (which happens to work for
        `/api/eod/`), this endpoint needs the explicit `.US` suffix for US
        listings — confirmed live, since `provider_symbol` is bare for US
        instruments (Yahoo's own convention). Non-US symbols already carry
        a Yahoo-style suffix (e.g. `BMW.DE`) that happens to match EODHD's
        own convention for those markets too — not independently verified
        live the way the US case was, used as-is on that assumption.

        `on_attempt`/`on_bytes` — see `FmpProvider.fetch_splits`'s docstring
        for why this call bypasses `ProviderChain` and instruments itself.
        """
        symbol = ref.provider_symbol
        if not symbol:
            raise SymbolNotFound(f"{self.name} needs a provider symbol")
        if is_us_listing(ref):
            symbol = f"{symbol}.US"

        self._throttle.wait()
        if on_attempt is not None:
            on_attempt(self.name)

        client = self._client or httpx.Client(timeout=15.0)
        try:
            response = client.get(
                f"https://eodhd.com/api/splits/{symbol}",
                params={"api_token": self.api_key, "fmt": "json"},
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc
        finally:
            if self._client is None:
                client.close()

        if on_bytes is not None:
            on_bytes(self.name, len(response.content))

        if response.status_code == 429:
            raise RateLimited("rate limited")
        if response.status_code == 401:
            raise ProviderUnavailable("invalid API key")
        if response.status_code >= 400:
            raise ProviderUnavailable(f"HTTP {response.status_code}")

        try:
            results = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc

        if isinstance(results, dict) and "error" in results:
            raise SymbolNotFound(str(results["error"]))
        # Unlike fetch_daily, an empty list here is a valid "never split"
        # answer, not a sign the symbol is unknown.
        if not isinstance(results, list):
            return []

        events: list[SplitEvent] = []
        for row in results:
            if not isinstance(row, dict):
                continue
            raw_split = row.get("split")
            raw_date = row.get("date")
            if not raw_split or not raw_date:
                continue
            parts = str(raw_split).split("/")
            if len(parts) != 2:
                continue
            try:
                numerator, denominator = float(parts[0]), float(parts[1])
                effective_date = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            events.append(SplitEvent(effective_date=effective_date, numerator=numerator, denominator=denominator))

        return sorted((e for e in events if start <= e.effective_date <= end), key=lambda e: e.effective_date)
