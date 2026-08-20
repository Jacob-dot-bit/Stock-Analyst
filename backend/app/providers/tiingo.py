"""Tiingo latest-day price (worldwide) — quote-only, not historical.

Tiingo's `/tiingo/daily/{ticker}/prices` endpoint used to accept `startDate`/
`endDate` for a historical range. Verified live (via this app's "Test key"
button) that as of some point before 2026, Tiingo deprecated that usage on the
free "bulk" tier: any request with dates set now returns HTTP 400 with
`"This experimental feature has been officially been deprecated... You may
use the bulk endpoint as long as startDate and endDate are not specified
(i.e. the latest date's values)."` — their own error message names the
workaround. So this provider no longer serves `fetch_daily` (a date range) at
all; it serves only `fetch_quote` (the single latest day, no dates in the
request), which fits the live-estimate "fresh prices" feature perfectly and
costs nothing extra to add. See DEVLOG "Bug 2.9".
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


class TiingoProvider(PriceProvider):
    """Tiingo REST API for global stocks — latest-day quote only.

    Free tier: 500 requests/day. No longer usable for historical ranges (see
    module docstring); ``fetch_daily`` always fails cleanly and cheaply
    (no HTTP call) so the main refresh chain skips straight past it without
    spending any of that quota.
    """

    name = "tiingo"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._throttle = Throttle(min_interval_seconds=0.2)

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def can_serve(self, ref: InstrumentRef) -> bool:
        return bool(ref.provider_symbol)

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        """Always unavailable: Tiingo's free tier no longer serves date ranges."""
        raise ProviderUnavailable(
            "Tiingo's free tier no longer supports historical date-range queries "
            "(deprecated 2024-07-29) — only the latest day, via fetch_quote"
        )

    def fetch_quote(self, ref: InstrumentRef) -> float | None:
        """Current (latest trading day) price — the one thing Tiingo's free tier still gives."""
        # .split, not .rpartition: see DEVLOG "Bug 2.11" — provider_symbol for
        # a US ticker is already bare ("AAPL", no dot), and
        # rpartition(".")[0] on a string with no "." returns "", silently
        # sending an empty ticker rather than the intended one.
        symbol = ref.provider_symbol.split(".")[0]

        self._throttle.wait()

        try:
            client = httpx.Client(timeout=15.0)
            response = client.get(
                f"https://api.tiingo.com/tiingo/daily/{symbol}/prices",
                params={"token": self.api_key},
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimited("rate limited")
        if response.status_code in (401, 403):
            raise ProviderUnavailable(f"invalid API key: {_error_detail(response)}")
        if response.status_code == 404:
            raise SymbolNotFound(f"symbol not found: {symbol}")
        if response.status_code >= 400:
            raise ProviderUnavailable(f"HTTP {response.status_code}: {_error_detail(response)}")

        # A 200 with an empty body happens on Tiingo for a valid key with
        # nothing to return (e.g. the account lacks IEX/EOD add-on access for
        # this symbol) — not malformed JSON to report as a parse failure, just
        # "no data," the same as an empty results list below.
        if not response.text.strip():
            return None

        try:
            results = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc

        if not results:
            return None

        latest = results[-1] if isinstance(results, list) else results
        close = latest.get("close") if isinstance(latest, dict) else None
        return float(close) if close is not None else None


def _error_detail(response: httpx.Response) -> str:
    """Tiingo's error body, or the raw text if it isn't the usual JSON shape.

    Deliberately doesn't assume the body is a JSON *object* — an earlier
    version called ``.get("detail", ...)`` unconditionally and crashed with
    ``'list' object has no attribute 'get'`` the one time Tiingo's error body
    turned out to be an array instead. This is exactly the kind of assumption
    an error-reporting path can't afford: it must never itself raise, or the
    real error it was trying to report gets replaced by a worse one.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict):
        return str(body.get("detail", body))[:500]
    return str(body)[:500]
