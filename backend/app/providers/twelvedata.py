"""Twelve Data daily history — the keyed fallback when Yahoo throttles.

Chosen after Stooq, the original fallback, became unusable: it now answers with a
JavaScript proof-of-work challenge instead of CSV. Defeating that would mean
circumventing a bot-detection mechanism, so Stooq was dropped rather than worked
around.

Twelve Data's free tier (email signup, no card) allows a documented 800 requests per
day and 8 per minute, and covers non-US venues — which matters here, since the
portfolio spans several European markets.

Honest caveat: this provider is written against the documented response shape and is
covered by unit tests using recorded-shape fixtures, but it has **not** been exercised
against the live API, because no key was available while writing it. The first real
call is the one to watch.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from app.providers.base import (
    Bar,
    PlanLimited,
    PriceProvider,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    Throttle,
)

TIME_SERIES_URL = "https://api.twelvedata.com/time_series"


class TwelveDataProvider(PriceProvider):
    name = "twelvedata"

    def __init__(
        self,
        api_key: str | None,
        # 8 requests/minute on the free tier: 8s spacing keeps us just inside it
        # without needing to track a sliding window.
        min_interval_seconds: float = 8.0,
        timeout_seconds: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._throttle = Throttle(min_interval_seconds)
        self._timeout = timeout_seconds
        self._client = client

    def is_enabled(self) -> bool:
        return bool(self._api_key)

    def fetch_daily(self, symbol: str, start: date, end: date) -> list[Bar]:
        if not self._api_key:
            raise ProviderUnavailable("no API key configured")

        client = self._client or httpx.Client(timeout=self._timeout)
        owns_client = self._client is None

        try:
            self._throttle.wait()
            try:
                response = client.get(
                    TIME_SERIES_URL,
                    params={
                        "symbol": symbol,
                        "interval": "1day",
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                        "format": "JSON",
                        "apikey": self._api_key,
                    },
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited(f"{self.name} is throttling requests")

            # A 404 carries a JSON body explaining *why* — an unknown symbol and a
            # symbol excluded from the current plan look identical at the status code,
            # so the body has to be read before deciding.
            if response.status_code >= 400 and response.status_code != 404:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderUnavailable("malformed JSON response") from exc

        finally:
            if owns_client:
                client.close()

        return _parse_payload(payload, symbol, self.name)


def _parse_payload(payload: dict, symbol: str, provider_name: str) -> list[Bar]:
    """Twelve Data reports errors in the body, sometimes even under a 200 status."""
    if payload.get("status") == "error":
        code = payload.get("code")
        message = str(payload.get("message", ""))
        lowered = message.lower()

        # Checked before the rate-limit rule: the plan message also contains "plan",
        # and mis-reading it as throttling would have the user retry forever.
        if "plan" in lowered or "upgrad" in lowered:
            raise PlanLimited(message)
        if code == 429 or "api credits" in lowered or "limit reached" in lowered:
            raise RateLimited(message or "rate limit reached")
        if code == 404 or "not found" in lowered or "invalid" in lowered:
            raise SymbolNotFound(symbol)
        raise ProviderUnavailable(message or f"{provider_name} error")

    values = payload.get("values") or []
    bars: list[Bar] = []

    for row in values:
        close = _to_float(row.get("close"))
        if close is None:
            continue
        try:
            bar_date = datetime.strptime(row["datetime"][:10], "%Y-%m-%d").date()
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

    # The API returns newest-first; everything downstream assumes chronological order.
    bars.sort(key=lambda bar: bar.bar_date)
    return bars


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
