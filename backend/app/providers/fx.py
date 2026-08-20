"""Currency conversion rates via Frankfurter.

Free, keyless, and sourced from the ECB's daily reference rates — chosen for the
live portfolio value estimate specifically because it needs no signup and stays
within the project's "free sources only" constraint. Frankfurter covers the
currencies the ECB publishes (major world currencies); anything else raises
``FxUnavailable`` rather than guessing.

The service moved from ``frankfurter.app`` to ``frankfurter.dev`` (with a
``/v1`` prefix) at some point after this integration was first written — the old
host now 301-redirects there. ``httpx.get`` does not follow redirects by
default, so pointing at the old host silently turned every lookup into an
"unavailable" (a 301 is not 200) rather than an error loud enough to notice
immediately. Point at the current host directly rather than relying on redirect
-following, so a future move fails loudly instead of quietly returning nothing.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"


class FxUnavailable(Exception):
    """The rate could not be determined. Never guessed, never assumed 1:1."""


def fetch_rate(from_currency: str, to_currency: str, timeout: float = 10.0) -> float:
    """1 unit of ``from_currency`` expressed in ``to_currency``, as of today's ECB fixing."""
    try:
        response = httpx.get(
            FRANKFURTER_URL,
            params={"from": from_currency, "to": to_currency},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise FxUnavailable(str(exc)) from exc

    if response.status_code != 200:
        raise FxUnavailable(f"HTTP {response.status_code}")

    try:
        data = response.json()
        return float(data["rates"][to_currency])
    except (ValueError, KeyError, TypeError) as exc:
        raise FxUnavailable(f"unexpected response: {exc}") from exc


def fetch_rate_range(
    from_currency: str, to_currency: str, start: date, end: date, timeout: float = 15.0
) -> dict[date, float]:
    """1 unit of ``from_currency`` in ``to_currency`` for every ECB trading day in
    ``[start, end]`` — one HTTP call for the whole span, backing the historical
    value chart (see DEVLOG "Decision 3b.2").

    Live-verified against the real API, not just the docs: weekend/holiday dates
    are simply **absent** from the response (no forward-fill from Frankfurter
    itself) — the caller must forward-fill, same as ``PriceBar`` gaps. A span
    entirely outside ECB coverage (too old, or starting in the future) returns
    HTTP 404, not 200 with empty rates.
    """
    try:
        response = httpx.get(
            f"{FRANKFURTER_BASE_URL}/{start.isoformat()}..{end.isoformat()}",
            params={"from": from_currency, "to": to_currency},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise FxUnavailable(str(exc)) from exc

    if response.status_code != 200:
        raise FxUnavailable(f"HTTP {response.status_code}")

    try:
        data = response.json()
        return {
            datetime.strptime(day, "%Y-%m-%d").date(): float(rates[to_currency])
            for day, rates in data["rates"].items()
        }
    except (ValueError, KeyError, TypeError) as exc:
        raise FxUnavailable(f"unexpected response: {exc}") from exc
