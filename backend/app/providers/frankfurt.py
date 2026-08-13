"""Boerse Frankfurt daily history — the free source that covers European venues.

Why this exists: neither of the other providers covers Europe on a free plan. Twelve
Data's free tier is US-only (its own error says so: *"This symbol is available starting
with the Grow or Venture plan"*), and Yahoo — the only free worldwide source — blocks by
IP and can stay blocked for a long time. Without this, every European holding shows no
data at all.

Boerse Frankfurt exposes a TradingView UDF endpoint that needs no key, no session and no
anti-bot challenge, and returns full OHLCV daily history. Verified live: 284 daily bars
for ASML (NL0010273215) and for TotalEnergies (FR0000120271).

**It is keyed on ISIN, and nothing else.** Tickers, slugs and company names were all
tested and rejected. Their search endpoint ignores its search term — it returns the
highest-turnover German stocks whatever you ask for — so an ISIN cannot be resolved from
a ticker automatically. ISINs are therefore supplied per instrument and never guessed:
an incorrect ISIN would silently return **a different company's prices**, which is far
worse than no data.

Two caveats worth knowing when reading these numbers:

* prices are the **Frankfurt listing**, not the home market. For a Paris- or
  Amsterdam-listed share the two track each other closely but are not identical, and
  Frankfurt volume on a foreign listing is usually much thinner;
* the endpoint is undocumented and can change without notice — which is exactly why it
  sits behind ``PriceProvider``.
"""

from __future__ import annotations

import re
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

HISTORY_URL = "https://api.boerse-frankfurt.de/v1/tradingview/history"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

#: Two letters (country), nine alphanumerics, one check digit.
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")


def looks_like_isin(value: str | None) -> bool:
    return bool(value) and bool(ISIN_PATTERN.match(value.strip().upper()))


class FrankfurtProvider(PriceProvider):
    name = "frankfurt"

    def __init__(
        self,
        min_interval_seconds: float = 1.0,
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._throttle = Throttle(min_interval_seconds)
        self._timeout = timeout_seconds
        self._client = client

    def is_enabled(self) -> bool:
        # No key needed. Whether it can serve a given instrument depends on having an
        # ISIN, which is decided per call rather than globally.
        return True

    def can_serve(self, ref: InstrumentRef) -> bool:
        return looks_like_isin(ref.isin)

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        isin = (ref.isin or "").strip().upper()
        if not looks_like_isin(isin):
            # Not an error worth alarming about: most instruments simply have no ISIN
            # recorded, and the chain moves on to the next provider.
            raise SymbolNotFound(f"{self.name} requires an ISIN")

        client = self._client or httpx.Client(timeout=self._timeout, headers=HEADERS)
        owns_client = self._client is None

        try:
            self._throttle.wait()
            try:
                response = client.get(
                    HISTORY_URL,
                    params={
                        "symbol": isin,
                        "resolution": "D",
                        "from": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
                        "to": int(datetime(end.year, end.month, end.day, 23, 59, tzinfo=timezone.utc).timestamp()),
                    },
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited(f"{self.name} is throttling requests")
            if response.status_code >= 400:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderUnavailable("malformed JSON response") from exc
        finally:
            if owns_client:
                client.close()

        return _parse_udf(payload, isin)


def _parse_udf(payload: dict, isin: str) -> list[Bar]:
    """Parse a TradingView UDF payload: parallel arrays keyed s/t/o/h/l/c/v."""
    status = payload.get("s")

    # "no_data" is the documented UDF way of saying the instrument is unknown here,
    # and an empty body is what this endpoint returns for an ISIN it does not list.
    if status in {"no_data", None}:
        raise SymbolNotFound(isin)
    if status != "ok":
        raise ProviderUnavailable(str(payload.get("errmsg") or status))

    timestamps = payload.get("t") or []
    closes = payload.get("c") or []
    opens = payload.get("o") or []
    highs = payload.get("h") or []
    lows = payload.get("l") or []
    volumes = payload.get("v") or []

    def at(series: list, index: int) -> float | None:
        value = series[index] if index < len(series) else None
        return float(value) if value is not None else None

    bars: list[Bar] = []
    for index, stamp in enumerate(timestamps):
        close = at(closes, index)
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

    bars.sort(key=lambda bar: bar.bar_date)
    return bars
