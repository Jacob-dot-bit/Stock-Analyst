"""Financial Modeling Prep daily history — the candidate for Euronext coverage.

Why another provider: the four French PEA ETFs in this portfolio have no source at all
today. Frankfurt does not list them (`s=no_data` on every candidate ISIN), Twelve Data's
free tier is US-only, and Yahoo — which does cover them — blocks by IP.

FMP advertises a free tier of 250 requests/day spanning Euronext among other venues, and
uses the same venue-suffixed symbols this application already derives (``DCAM.PA``), so
no new identifier is needed.

**Unverified until a key exists.** The response shape below follows their documented
format and is covered by unit tests, but free-tier *coverage* cannot be checked without a
key — and that is precisely what went wrong with Twelve Data, whose implementation was
correct while its free plan turned out to exclude Europe. Treat the first live call as
the real test, and read ``prices.planLimited`` in the refresh report as the answer.
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

HISTORY_URL = "https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}"


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
                    HISTORY_URL.format(symbol=symbol),
                    params={
                        "from": start.isoformat(),
                        "to": end.isoformat(),
                        "apikey": self._api_key,
                    },
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited(f"{self.name} is throttling requests")
            # 401/403 carry a body explaining whether the key is wrong or the plan does
            # not include this data, which are very different things for the user.
            if response.status_code >= 400 and response.status_code not in {401, 403}:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderUnavailable("malformed JSON response") from exc
        finally:
            if owns_client:
                client.close()

        return _parse_payload(payload, symbol)


def _parse_payload(payload: object, symbol: str) -> list[Bar]:
    if isinstance(payload, dict) and payload.get("Error Message"):
        message = str(payload["Error Message"])
        lowered = message.lower()
        # "Exclusive endpoint", "upgrade your plan", "not available under your plan"...
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
