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

from collections.abc import Callable
from datetime import date, datetime

import httpx

from app.providers.base import (
    Bar,
    is_us_listing,
    InstrumentRef,
    PlanLimited,
    PriceProvider,
    ProviderUnavailable,
    RateLimited,
    SplitEvent,
    SymbolNotFound,
    Throttle,
)

HISTORY_URL = "https://financialmodelingprep.com/stable/historical-price-eod/full"
QUOTE_URL = "https://financialmodelingprep.com/stable/quote"
PROFILE_URL = "https://financialmodelingprep.com/stable/profile"
SEARCH_URL = "https://financialmodelingprep.com/stable/search-name"
SPLITS_URL = "https://financialmodelingprep.com/stable/splits"


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

    def can_serve(self, ref: InstrumentRef) -> bool:
        # Free tier is US-only, verified live: TTE.PA and DCAM.PA both answer HTTP 402.
        return bool(ref.provider_symbol) and is_us_listing(ref)

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

    def fetch_splits(
        self,
        ref: InstrumentRef,
        start: date,
        end: date,
        on_attempt: Callable[[str], None] | None = None,
        on_bytes: Callable[[str, int], None] | None = None,
    ) -> list[SplitEvent]:
        """Split/reverse-split history via ``/stable/splits`` — verified live
        against three known cases: NVDA's 10:1 (2024) and GOOGL's 20:1
        (2022) both came back correctly; APLD (a smaller name) answered
        ``402`` even though it is a US symbol `can_serve` would otherwise
        accept, which is why this method gates on `can_serve` itself rather
        than assuming US coverage implies split coverage — a wasted call
        against a free-tier boundary already known from `fetch_daily`'s own
        one (Europe) is one thing; this is a second, narrower boundary
        within the "US" bucket, discovered per-symbol rather than assumed.

        The endpoint returns full history with no range parameters (verified
        live — NVDA's response went back to 2000), so the `start`/`end`
        window is applied client-side. Does not itself check `can_serve` —
        callers scanning many instruments should check it first to turn a
        known-in-advance 402 into a `skipped` count rather than a wasted
        request; called directly (e.g. a future targeted single-instrument
        check), a non-US symbol still gets a definitive `PlanLimited` answer.

        Unlike `fetch_daily`, this bypasses `ProviderChain` entirely (called
        directly by `corporate_actions/service.py`), so there is no shared
        `on_attempt` hook wrapping it — `on_attempt`/`on_bytes` are accepted
        directly here instead, fired around the request the same way
        `ProviderChain.fetch_daily` fires `on_attempt` for price refreshes.
        `on_bytes` exists because this endpoint has no server-side range
        filter — every call downloads full history regardless of `start`/
        `end`, which is what actually drained FMP's 500MB/30-day bandwidth
        cap (undetected by the separate, unrelated 250 req/day counter). See
        DEVLOG "Decision 3u.41".
        """
        if not self._api_key:
            raise ProviderUnavailable("no API key configured")

        symbol = ref.provider_symbol
        if not symbol:
            raise SymbolNotFound(f"{self.name} needs a provider symbol")

        client = self._client or httpx.Client(timeout=self._timeout)
        owns_client = self._client is None

        try:
            self._throttle.wait()
            if on_attempt is not None:
                on_attempt(self.name)
            try:
                response = client.get(SPLITS_URL, params={"symbol": symbol, "apikey": self._api_key})
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if on_bytes is not None:
                on_bytes(self.name, len(response.content))

            if response.status_code == 429:
                raise RateLimited(f"{self.name} is throttling requests")
            if response.status_code == 402:
                raise PlanLimited(response.text[:200])
            if response.status_code >= 400 and response.status_code not in {401, 403}:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderUnavailable(response.text[:200]) from exc
        finally:
            if owns_client:
                client.close()

        events = _parse_splits_payload(payload)
        return sorted((e for e in events if start <= e.effective_date <= end), key=lambda e: e.effective_date)

    def fetch_quote(self, ref: InstrumentRef) -> float | None:
        """Current price via ``/stable/quote`` — same US-only free-tier limit as fetch_daily.

        Field names (``price`` on the single-object list response) are FMP's
        long-standing convention, verified against the error-body shape live;
        the success shape itself could not be checked without a real key, so
        this parses defensively and returns ``None`` rather than guessing on
        anything unexpected, same as every other quote-capable provider here.
        """
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
                    QUOTE_URL, params={"symbol": symbol, "apikey": self._api_key}
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited(f"{self.name} is throttling requests")
            if response.status_code == 402:
                raise PlanLimited(response.text[:200])
            if response.status_code >= 400 and response.status_code not in {401, 403}:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError:
                return None
        finally:
            if owns_client:
                client.close()

        if isinstance(payload, dict) and payload.get("Error Message"):
            return None
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            price = payload[0].get("price")
            return float(price) if price is not None else None
        return None

    def fetch_profile(self, ref: InstrumentRef) -> dict[str, str] | None:
        """Sector/industry/country via ``/stable/profile`` — a one-off lookup,
        not a per-refresh call: this data barely changes, so callers should
        cache it (skip instruments that already have a ``sector``) rather than
        ask again on every run.
        """
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
                    PROFILE_URL, params={"symbol": symbol, "apikey": self._api_key}
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited(f"{self.name} is throttling requests")
            if response.status_code == 402:
                raise PlanLimited(response.text[:200])
            if response.status_code >= 400 and response.status_code not in {401, 403}:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError:
                return None
        finally:
            if owns_client:
                client.close()

        if isinstance(payload, dict) and payload.get("Error Message"):
            return None
        if not (isinstance(payload, list) and payload and isinstance(payload[0], dict)):
            return None

        row = payload[0]
        return {
            "sector": row.get("sector") or None,
            "industry": row.get("industry") or None,
            "country": row.get("country") or None,
        }

    def search_by_name(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        """Company-name search via ``/stable/search-name`` — powers a symbol autocomplete."""
        if not self._api_key:
            raise ProviderUnavailable("no API key configured")

        client = self._client or httpx.Client(timeout=self._timeout)
        owns_client = self._client is None
        try:
            self._throttle.wait()
            try:
                response = client.get(
                    SEARCH_URL, params={"query": query, "apikey": self._api_key}
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited(f"{self.name} is throttling requests")
            if response.status_code >= 400 and response.status_code not in {401, 403}:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError:
                return []
        finally:
            if owns_client:
                client.close()

        if not isinstance(payload, list):
            return []

        results = []
        for row in payload[:limit]:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol")
            name = row.get("name") or row.get("companyName")
            if symbol and name:
                results.append({"symbol": str(symbol), "name": str(name)})
        return results


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


def _parse_splits_payload(payload: object) -> list[SplitEvent]:
    """Unlike `_parse_payload` (daily bars), an empty list here is a valid
    "never split" answer, not a sign the symbol is unknown — `fetch_splits`
    itself already raised on every genuine error status before parsing gets
    this far, so nothing left to interpret means nothing happened."""
    if isinstance(payload, dict) and payload.get("Error Message"):
        message = str(payload["Error Message"])
        lowered = message.lower()
        if any(word in lowered for word in ("plan", "upgrad", "exclusive", "subscription")):
            raise PlanLimited(message)
        if "limit" in lowered:
            raise RateLimited(message)
        raise ProviderUnavailable(message)

    if not isinstance(payload, list):
        return []

    events: list[SplitEvent] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        numerator = _to_float(row.get("numerator"))
        denominator = _to_float(row.get("denominator"))
        raw_date = row.get("date")
        if numerator is None or denominator is None or not raw_date:
            continue
        try:
            effective_date = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        events.append(SplitEvent(effective_date=effective_date, numerator=numerator, denominator=denominator))
    return events


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
