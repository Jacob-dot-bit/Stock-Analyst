"""Polygon.io / Massive daily price history (US + crypto).

Polygon.io rebranded to Massive (see DEVLOG "Bug 2.5" for the signup-site
redirect this was first noticed from). Verified via Massive's official
`llms.txt`-linked docs, fetched mid-session, that the rebrand runs deeper than
the marketing site: their documented, current host is ``api.massive.com`` —
``api.polygon.io`` is not mentioned anywhere in it and isn't guaranteed to
keep working (the same trap Frankfurter's old host eventually fell into).
Live-verified both hosts still answer identically today; pointing at the
documented one now rather than waiting for the legacy one to break.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

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

AGGREGATES_URL = "https://api.massive.com/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"
SPLITS_URL = "https://api.massive.com/v3/reference/splits"


class PolygonProvider(PriceProvider):
    """Massive (formerly Polygon.io) REST API for US stocks and crypto.

    Free tier: 5 requests/minute.
    """

    name = "polygon"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self._throttle = Throttle(min_interval_seconds=12.0)  # 5 req/min = ~12s per req
        self._client = client

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def can_serve(self, ref: InstrumentRef) -> bool:
        return is_us_listing(ref) and bool(ref.provider_symbol)

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        """Fetch daily bars from Massive's aggregates endpoint."""
        # .split, not .rpartition: see DEVLOG "Bug 2.11" — this is what
        # "Ticker was incorrectly formatted" turned out to mean. AAPL.US
        # already resolves to the bare provider_symbol "AAPL" (no dot) before
        # it ever reaches this provider; rpartition(".")[0] on "AAPL" (no ".")
        # returns "", so every US ticker was silently sent to Massive as an
        # empty string, always.
        symbol = ref.provider_symbol.split(".")[0]

        self._throttle.wait()

        client = self._client or httpx.Client(timeout=15.0)
        owns_client = self._client is None
        try:
            try:
                response = client.get(
                    AGGREGATES_URL.format(symbol=symbol, start=start, end=end),
                    params={"sort": "asc", "apiKey": self.api_key},
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc
        finally:
            if owns_client:
                client.close()

        if response.status_code == 429:
            raise RateLimited("rate limited")
        if response.status_code == 401:
            raise ProviderUnavailable(f"invalid API key: {_error_detail(response)}")
        if response.status_code == 404:
            raise SymbolNotFound(f"symbol not found: {symbol}")
        if response.status_code >= 400:
            # Surface the body, not just the code: a 400 here has repeatedly
            # turned out to be an account/plan detail (see Tiingo, DEVLOG "Bug
            # 2.9") rather than a malformed request, and the bare status alone
            # sends the user chasing the wrong fix.
            raise ProviderUnavailable(f"HTTP {response.status_code}: {_error_detail(response)}")

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc

        results = data.get("results", [])
        if not results:
            raise SymbolNotFound(f"no data for {symbol}")

        bars = []
        for result in results:
            # "t" is a Unix millisecond timestamp (an int), not an ISO date
            # string — confirmed against Massive's documented sample response.
            # `date.fromisoformat(result["t"][:10])` (the original code here)
            # would have raised TypeError on every real result, never having
            # been exercised past the auth-rejection path in this session's
            # testing until a real key was tried.
            bar_date = datetime.fromtimestamp(result["t"] / 1000, tz=UTC).date()
            bars.append(
                Bar(
                    bar_date=bar_date,
                    open=result.get("o"),
                    high=result.get("h"),
                    low=result.get("l"),
                    close=result.get("c"),
                    volume=result.get("v"),
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
        """Split/reverse-split history via `/v3/reference/splits` — verified
        live against the same reference panel as FMP/EODHD/Alpha Vantage
        (DEVLOG "Decision 3u.41"): matched exactly on AAPL back to 1987
        (deeper than every other source tested) and APLD's real 2022 1:6
        reverse split, missed NVDA's 2000/2001 splits that Alpha Vantage/
        EODHD found, and returned nothing for the two European names tested
        (`can_serve` already restricts this provider to US listings, so that
        gap is expected, not a bug to fix here).

        Also surfaced, on APLD specifically, an isolated `800:1` reverse
        split dated 2003 — 22 years before this portfolio's real 2025
        position open, and not repeated by any other source checked. Ticker
        symbols get reused across unrelated companies over decades; this
        method returns the raw event as reported and does not itself decide
        whether it is real — that judgment (`suspect_ticker_reuse`) belongs
        to `corporate_actions/service.py`'s merge logic, which has the
        instrument's own history to compare against.

        `results[].split_from`/`split_to` map directly onto
        `SplitEvent`'s `denominator`/`numerator` — no factor conversion
        needed, unlike Alpha Vantage's single-float `split_factor`.

        Unlike `fetch_daily`, this bypasses `ProviderChain` (called directly
        by `corporate_actions/service.py`) — see `FmpProvider.fetch_splits`'s
        docstring for why `on_attempt`/`on_bytes` are threaded through
        directly instead.
        """
        symbol = ref.provider_symbol.split(".")[0]

        self._throttle.wait()
        if on_attempt is not None:
            on_attempt(self.name)

        client = self._client or httpx.Client(timeout=15.0)
        owns_client = self._client is None
        try:
            try:
                response = client.get(
                    SPLITS_URL,
                    params={"ticker": symbol, "apiKey": self.api_key},
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc
        finally:
            if owns_client:
                client.close()

        if on_bytes is not None:
            on_bytes(self.name, len(response.content))

        if response.status_code == 429:
            raise RateLimited("rate limited")
        if response.status_code == 401:
            raise ProviderUnavailable(f"invalid API key: {_error_detail(response)}")
        if response.status_code == 404:
            raise SymbolNotFound(f"symbol not found: {symbol}")
        if response.status_code >= 400:
            raise ProviderUnavailable(f"HTTP {response.status_code}: {_error_detail(response)}")

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc

        # Unlike fetch_daily, an empty `results` here is a valid "never
        # split" answer, not a sign the symbol is unknown — every genuine
        # error status was already raised above before parsing gets this far.
        events: list[SplitEvent] = []
        for row in data.get("results", []):
            try:
                effective_date = date.fromisoformat(row["execution_date"])
                numerator = float(row["split_to"])
                denominator = float(row["split_from"])
            except (KeyError, ValueError, TypeError):
                continue
            if numerator <= 0 or denominator <= 0:
                continue
            events.append(SplitEvent(effective_date=effective_date, numerator=numerator, denominator=denominator))

        return sorted((e for e in events if start <= e.effective_date <= end), key=lambda e: e.effective_date)


def _error_detail(response: httpx.Response) -> str:
    """Massive's error body, or the raw text if it isn't the usual JSON shape.

    Never assumes the body is a JSON object — see Tiingo's identical helper
    (DEVLOG "Bug 2.9") for why an error-reporting path must not itself raise.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict):
        return str(body.get("error", body))[:500]
    return str(body)[:500]
