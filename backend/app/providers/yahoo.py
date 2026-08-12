"""Yahoo Finance daily history, through the public chart endpoint.

Why this endpoint rather than ``yfinance``: it is the same call the library makes for
price history, minus a large dependency that breaks several times a year. Fewer moving
parts between us and the data means fewer ways to break.

Why it needs careful handling: this endpoint rate-limits **hard**. Measured from a
single IP, four requests in quick succession were enough to earn a 429, and the block
was still in place a minute later. So the design here is defensive on purpose —
serialised calls, a minimum gap between them, and bounded backoff. Bursting is what
gets an address blocked; steady traffic is tolerated.

Unofficial and undocumented, this endpoint can change without notice. That is exactly
why it sits behind ``PriceProvider`` rather than being called directly.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone

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

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# A browser-like User-Agent is required: the endpoint answers 429 to the default
# python-httpx agent regardless of volume.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class YahooProvider(PriceProvider):
    name = "yahoo"

    def __init__(
        self,
        min_interval_seconds: float = 2.0,
        max_retries: int = 2,
        timeout_seconds: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._throttle = Throttle(min_interval_seconds)
        self._max_retries = max_retries
        self._timeout = timeout_seconds
        self._client = client

    def is_enabled(self) -> bool:
        # No API key, so always available — subject to rate limiting.
        return True

    def _get(self, symbol: str, params: dict) -> dict:
        client = self._client or httpx.Client(timeout=self._timeout, headers=HEADERS)
        owns_client = self._client is None

        try:
            for attempt in range(self._max_retries + 1):
                self._throttle.wait()
                try:
                    response = client.get(CHART_URL.format(symbol=symbol), params=params)
                except httpx.HTTPError as exc:
                    raise ProviderUnavailable(str(exc)) from exc

                if response.status_code == 429:
                    if attempt == self._max_retries:
                        raise RateLimited(f"{self.name} is throttling requests")
                    # Linear backoff. Yahoo's block outlasts short waits, so this is a
                    # courtesy pause before giving up, not a way to outlast the limit.
                    time.sleep(2.0 * (attempt + 1))
                    continue

                if response.status_code == 404:
                    raise SymbolNotFound(symbol)
                if response.status_code >= 400:
                    raise ProviderUnavailable(f"HTTP {response.status_code}")

                try:
                    return response.json()
                except ValueError as exc:
                    raise ProviderUnavailable("malformed JSON response") from exc

            raise RateLimited(f"{self.name} is throttling requests")
        finally:
            if owns_client:
                client.close()

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        symbol = ref.provider_symbol
        if not symbol:
            raise SymbolNotFound(f"{self.name} needs a provider symbol")

        payload = self._get(
            symbol,
            {
                "period1": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
                "period2": int(datetime(end.year, end.month, end.day, 23, 59, tzinfo=timezone.utc).timestamp()),
                "interval": "1d",
            },
        )

        chart = payload.get("chart") or {}
        if chart.get("error"):
            code = (chart["error"] or {}).get("code", "")
            if "NotFound" in str(code) or "Not Found" in str(code):
                raise SymbolNotFound(symbol)
            raise ProviderUnavailable(str(code))

        results = chart.get("result") or []
        if not results:
            raise SymbolNotFound(symbol)

        return _parse_bars(results[0])


def _parse_bars(result: dict) -> list[Bar]:
    timestamps = result.get("timestamp") or []
    quote_blocks = (result.get("indicators") or {}).get("quote") or [{}]
    quote = quote_blocks[0] if quote_blocks else {}

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    def at(series: list, index: int) -> float | None:
        value = series[index] if index < len(series) else None
        return float(value) if value is not None else None

    bars: list[Bar] = []
    for index, stamp in enumerate(timestamps):
        close = at(closes, index)
        # Yahoo pads its series with nulls on non-trading days. A bar with no close
        # carries no information and would pollute every indicator downstream.
        if close is None:
            continue
        bars.append(
            Bar(
                bar_date=datetime.fromtimestamp(stamp, tz=timezone.utc).date(),
                open=at(opens, index),
                high=at(highs, index),
                low=at(lows, index),
                close=close,
                volume=at(volumes, index),
            )
        )

    return bars
