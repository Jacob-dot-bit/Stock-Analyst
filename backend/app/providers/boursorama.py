"""Boursorama daily history — the source that finally covers Euronext Paris.

Found after every other free option failed for French instruments: Frankfurt does not
list French PEA ETFs, Twelve Data and FMP paywall non-US symbols, and Yahoo — which does
cover them — blocks by IP. This one covers both the ETFs and the Paris-listed shares,
which are the *home* market rather than a secondary German listing.

How it was found matters, because guessing had failed repeatedly: the page's own chart
bundle declares the endpoint. Reading what a page says it calls is evidence; inventing
plausible URLs is not, and several hours went into learning that difference.

## The required header

The endpoint answers ``410`` with an empty body unless the request carries
``X-Requested-With: XMLHttpRequest``. That looked like rate limiting for a while — it is
not; it is a hard requirement, and the same call succeeds immediately once the header is
present.

Sending it is ordinary client behaviour: it is the conventional header every AJAX
library sets, it describes the request accurately, and it is neither a token nor a
secret nor a challenge. That is the line this project draws — the same reason Stooq's
proof-of-work page and Euronext's encrypted payload were left alone.

## Symbols and the verification that goes with them

Boursorama prefixes tickers by instrument type: ``1rP`` for Euronext Paris shares,
``1rT`` for trackers. The prefix is derived from the broker's category, and **the name
in the response is checked against the name the broker reported**. That check is not
decoration: this project has already attached C3.ai's financials to Air Liquide once by
trusting a symbol, and a price series is just as easy to get wrong quietly.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx

from app.providers.base import (
    Bar,
    is_us_listing,
    InstrumentRef,
    PriceProvider,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    Throttle,
)
from app.providers.edgar import names_match

HISTORY_URL = "https://www.boursorama.com/bourse/action/graph/ws/GetTicksEOD"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    # Without this the endpoint answers 410 with an empty body. See module docstring.
    "X-Requested-With": "XMLHttpRequest",
}

#: Boursorama's day numbering counts from 1970-01-01, like a Unix day index.
EPOCH = date(1970, 1, 1)

#: Broker category -> symbol prefix. Trackers and shares live in different namespaces.
PREFIX_BY_CATEGORY = {"ETF": "1rT", "STOCK": "1rP"}

#: Tried in order when the category gives no clear answer.
FALLBACK_PREFIXES = ("1rP", "1rT")


class BoursoramaProvider(PriceProvider):
    name = "boursorama"

    def __init__(
        self,
        min_interval_seconds: float = 3.0,
        timeout_seconds: float = 25.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._throttle = Throttle(min_interval_seconds)
        self._timeout = timeout_seconds
        self._client = client

    def is_enabled(self) -> bool:
        return True

    def can_serve(self, ref: InstrumentRef) -> bool:
        # Euronext Paris only. A US ticker sent here resolves to nothing, or worse to
        # a French company sharing the letters.
        return not is_us_listing(ref) and bool(self._candidates(ref))

    def _candidates(self, ref: InstrumentRef) -> list[str]:
        """Symbols worth trying, most likely first."""
        symbol = ref.broker_symbol or ref.provider_symbol or ""
        # "TTE.FR" -> "TTE"; a provider symbol like "TTE.PA" works the same way.
        root = symbol.split(".")[0].strip().upper()
        if not root:
            return []

        preferred = PREFIX_BY_CATEGORY.get((ref.category or "").upper())
        order = [preferred] if preferred else []
        order += [p for p in FALLBACK_PREFIXES if p != preferred]
        return [f"{prefix}{root}" for prefix in order]

    def _request(self, symbol: str) -> dict:
        client = self._client or httpx.Client(timeout=self._timeout, headers=HEADERS)
        owns_client = self._client is None
        try:
            self._throttle.wait()
            try:
                response = client.get(
                    HISTORY_URL,
                    params={"symbol": symbol, "length": "365", "period": "0", "guid": ""},
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited(f"{self.name} is throttling requests")
            if response.status_code == 410:
                # Either an unknown symbol or a missing X-Requested-With header. The
                # header is always sent here, so treat it as unknown.
                raise SymbolNotFound(symbol)
            if response.status_code >= 400:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderUnavailable("malformed JSON response") from exc
        finally:
            if owns_client:
                client.close()

        if not isinstance(payload, dict):
            raise SymbolNotFound(symbol)
        return payload.get("d") or {}

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        candidates = self._candidates(ref)
        if not candidates:
            raise SymbolNotFound("no ticker to build a Boursorama symbol from")

        last_error: Exception | None = None
        for symbol in candidates:
            try:
                data = self._request(symbol)
            except SymbolNotFound as exc:
                last_error = exc
                continue

            quotes = data.get("QuoteTab") or []
            if not quotes:
                last_error = SymbolNotFound(symbol)
                continue

            # The response names the instrument, so a wrong prefix or a ticker
            # collision is caught here rather than becoming a silently wrong series.
            returned_name = str(data.get("Name") or "")
            if ref.name and returned_name and not names_match(ref.name, returned_name):
                last_error = SymbolNotFound(
                    f"{symbol} is '{returned_name}', not '{ref.name}'"
                )
                continue

            return _parse_quotes(quotes, start, end)

        raise last_error or SymbolNotFound(candidates[0])


def _parse_quotes(quotes: list[dict], start: date, end: date) -> list[Bar]:
    bars: list[Bar] = []
    for row in quotes:
        day_index, close = row.get("d"), row.get("c")
        if day_index is None or close is None:
            continue
        try:
            bar_date = EPOCH + timedelta(days=int(day_index))
        except (TypeError, ValueError):
            continue
        if not (start <= bar_date <= end):
            continue

        bars.append(
            Bar(
                bar_date=bar_date,
                open=_to_float(row.get("o")),
                high=_to_float(row.get("h")),
                low=_to_float(row.get("l")),
                close=float(close),
                volume=_to_float(row.get("v")),
            )
        )

    bars.sort(key=lambda bar: bar.bar_date)
    return bars


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
