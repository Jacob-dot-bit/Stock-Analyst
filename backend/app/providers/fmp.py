"""Financial Modeling Prep daily history — the candidate for Euronext coverage.

Why another provider: the four French PEA ETFs in this portfolio have no source at all
today. Frankfurt does not list them (`s=no_data` on every candidate ISIN), Twelve Data's
free tier is US-only, and Yahoo — which does cover them — blocks by IP.

**Verified live, and the answer is no for Europe.** The free tier serves US symbols and
rejects everything else with HTTP 402 — ``TTE.PA`` and ``DCAM.PA`` both return *"This value
set for 'symbol' is not available under your current subscription"*. It is kept as a
third US source, not as the European answer we were looking for.

That makes two commercial free tiers checked and two that stop at the US border, Twelve
Data being the first. Excluding non-US venues appears to be how these plans are
monetised, so a third signup is unlikely to end differently.

Note on the endpoint: the ``/api/v3/`` path is retired — it answers *"Legacy Endpoint:
no longer supported"* — so this uses the ``/stable/`` API.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from app.providers.base import (
    Bar,
    InstrumentRef,
    PlanLimited,
    PriceProvider,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    Throttle,
)

HISTORY_URL = "https://financialmodelingprep.com/stable/historical-price-eod/full"


class FmpProvider(PriceProvider):
    name = "fmp"

    def __init__(
        self,
        api_key: str | None,
        # 250 requests/day on the free tier with no documented per-minute cap; a
        # second between calls is politeness, not a constraint.
        min_interval_seconds: float = 1.0,
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._throttle = Throttle(min_interval_seconds)
        self._timeout = timeout_seconds
        self._client = client

    def is_enabled(self) -> bool:
        return bool(self._api_key)

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        if not self._api_key:
            raise ProviderUnavailable("no API key configured")

        symbol = ref.provider_symbol
        if not symbol:
            raise SymbolNotFound(f"{self.name} needs a provider symbol")

        client = self._client or httpx.Client(timeout=self._timeout)
        owns_client = self._client is None

        try:
            self._throttle.wait()
            try:
                response = client.get(
                    HISTORY_URL,
                    params={
                        "symbol": symbol,
                        "from": start.isoformat(),
                        "to": end.isoformat(),
                        "apikey": self._api_key,
                    },
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited(f"{self.name} is throttling requests")

            # 402 is how the free tier refuses a symbol outside its coverage. Saying so
            # plainly matters: the symbol is right and there is nothing to fix locally.
            if response.status_code == 402:
                raise PlanLimited(response.text[:200])

            if response.status_code >= 400 and response.status_code not in {401, 403}:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError as exc:
                # A retired endpoint answers with prose, not JSON.
                raise ProviderUnavailable(response.text[:200]) from exc
        finally:
            if owns_client:
                client.close()

        return _parse_payload(payload, symbol)


def _parse_payload(payload: object, symbol: str) -> list[Bar]:
    if isinstance(payload, dict) and payload.get("Error Message"):
        message = str(payload["Error Message"])
        lowered = message.lower()
        # A retired endpoint is not a plan boundary: nothing the user buys fixes it,
        # and calling it "plan limited" would send them to a pricing page for a bug.
        if "legacy" in lowered or "no longer supported" in lowered:
            raise ProviderUnavailable(message)
        if any(word in lowered for word in ("plan", "upgrad", "exclusive", "subscription")):
            raise PlanLimited(message)
        if "limit" in lowered:
            raise RateLimited(message)
        raise ProviderUnavailable(message)

    # The endpoint answers either {"symbol": ..., "historical": [...]} or, for some
    # symbols, a bare list. Accept both rather than assume one.
    rows: list = []
    if isinstance(payload, dict):
        rows = payload.get("historical") or []
    elif isinstance(payload, list):
        rows = payload

    if not rows:
        raise SymbolNotFound(symbol)

    bars: list[Bar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        close = _to_float(row.get("close"))
        if close is None:
            continue
        try:
            bar_date = datetime.strptime(str(row["date"])[:10], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue

        bars.append(
            Bar(
                bar_date=bar_date,
                open=_to_float(row.get("open")),
                high=_to_float(row.get("high")),
                low=_to_float(row.get("low")),
                close=close,
                volume=_to_float(row.get("volume")),
            )
        )

    # Returned newest-first; everything downstream assumes chronological order.
    bars.sort(key=lambda bar: bar.bar_date)
    return bars


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
