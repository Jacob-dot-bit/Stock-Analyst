"""Alpha Vantage daily price history and per-instrument news/sentiment (worldwide)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

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
)


@dataclass(frozen=True)
class NewsArticle:
    """One article from `NEWS_SENTIMENT`, with the per-ticker fields already
    picked out of its `ticker_sentiment` array — the caller never has to
    re-search that array itself."""

    title: str
    url: str
    source: str
    time_published: datetime
    summary: str
    overall_sentiment_label: str
    overall_sentiment_score: float
    ticker_relevance_score: float
    ticker_sentiment_score: float
    ticker_sentiment_label: str


class AlphaVantageProvider(PriceProvider):
    """Alpha Vantage REST API for global stock markets.

    Free tier: 5 requests/minute, worldwide coverage. `fetch_news_sentiment`
    shares this same account and the same `_throttle` instance as
    `fetch_daily` — it lives on this class rather than a separate client so a
    price refresh in flight and a news lookup can never together exceed the
    real 5/min server-side limit.
    """

    name = "alpha_vantage"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self._throttle = Throttle(min_interval_seconds=12.0)  # 5 req/min = ~12s per req
        self._client = client

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def can_serve(self, ref: InstrumentRef) -> bool:
        return bool(ref.provider_symbol)

    def _get(self, params: dict[str, str], on_bytes: Callable[[str, int], None] | None = None) -> dict:
        client = self._client or httpx.Client(timeout=15.0)
        owns_client = self._client is None
        try:
            try:
                response = client.get("https://www.alphavantage.co/query", params=params)
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if on_bytes is not None:
                on_bytes(self.name, len(response.content))

            if response.status_code >= 400:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                return response.json()
            except ValueError as exc:
                raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc
        finally:
            if owns_client:
                client.close()

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> list[Bar]:
        """Fetch daily bars from Alpha Vantage."""
        # .split, not .rpartition: see DEVLOG "Bug 2.11" — provider_symbol
        # for a US ticker is already bare ("AAPL", no dot), and
        # rpartition(".")[0] on a string with no "." returns "", silently
        # sending an empty ticker rather than the intended one.
        symbol = ref.provider_symbol.split(".")[0]

        self._throttle.wait()

        data = self._get(
            {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "apikey": self.api_key,
                "outputsize": "full",
            }
        )

        # Check for API errors in response. Two distinct rate-limit shapes
        # exist: "Note" is the older per-minute (5 req/min) throttle message;
        # "Information" is what the free tier now returns once the 25-per-day
        # quota is spent. Missing the second meant a daily-quota response
        # (which carries no "Time Series (Daily)" key) fell through to the
        # empty-data check below and was misreported as "symbol not found" —
        # confusing on a symbol as unambiguous as AAPL.
        if "Error Message" in data:
            raise SymbolNotFound(data["Error Message"])
        if data.get("Note"):
            raise RateLimited("rate limited (API call frequency)")
        if data.get("Information"):
            raise RateLimited(data["Information"])

        time_series = data.get("Time Series (Daily)", {})
        if not time_series:
            raise SymbolNotFound(f"no data for {symbol}")

        bars = []
        for date_str in sorted(time_series.keys()):
            day = date.fromisoformat(date_str)
            if start <= day <= end:
                values = time_series[date_str]
                bars.append(
                    Bar(
                        bar_date=day,
                        open=float(values.get("1. open", 0)),
                        high=float(values.get("2. high", 0)),
                        low=float(values.get("3. low", 0)),
                        close=float(values.get("4. close", 0)),
                        volume=float(values.get("5. volume", 0)),
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
        """Split/reverse-split history via `function=SPLITS` — verified live
        against a 7-instrument reference panel (DEVLOG "Decision 3u.41"):
        matched FMP/EODHD/Polygon exactly on AAPL (back to 2000, though not
        as far back as Polygon's 1987) and APLD's real 1:6 reverse split,
        found NVDA splits FMP/Polygon didn't (2000, 2001), but returned
        nothing at all for two real European names (MC.PA, ASML.AS) that
        EODHD proved do have real split history — worldwide coverage is
        real but uneven, never treat an empty response here as proof
        nothing happened on a non-US market.

        `data[].split_factor` is a single float rather than the numerator/
        denominator pair every other provider here returns — e.g. `"10.0000"`
        for a 10:1 split, `"0.1667"` for a 1:6 reverse split (verified
        exactly against APLD: `1/0.1667 ≈ 6`, matching FMP/EODHD/Polygon's
        own `1:6`). Converted with a factor ≥ 1 as `(factor, 1)` and a
        factor < 1 as `(1, round(1/factor))` — `round()` here corrects the
        4-decimal truncation in Alpha Vantage's own value, not a tolerance
        this app introduces.

        Unlike `fetch_daily`, this bypasses `ProviderChain` (called
        directly by `corporate_actions/service.py`) — see
        `FmpProvider.fetch_splits`'s docstring for why `on_attempt`/
        `on_bytes` are threaded through directly instead.
        """
        symbol = ref.provider_symbol.split(".")[0]

        self._throttle.wait()
        if on_attempt is not None:
            on_attempt(self.name)

        data = self._get(
            {"function": "SPLITS", "symbol": symbol, "apikey": self.api_key},
            on_bytes=on_bytes,
        )

        if data.get("Note"):
            raise RateLimited("rate limited (API call frequency)")
        if data.get("Information"):
            raise RateLimited(data["Information"])
        if "Error Message" in data:
            raise SymbolNotFound(data["Error Message"])

        events: list[SplitEvent] = []
        for row in data.get("data", []):
            try:
                effective_date = date.fromisoformat(row["effective_date"])
                factor = float(row["split_factor"])
            except (KeyError, ValueError, TypeError):
                continue
            if factor <= 0:
                continue
            numerator, denominator = (factor, 1.0) if factor >= 1 else (1.0, round(1.0 / factor))
            events.append(SplitEvent(effective_date=effective_date, numerator=numerator, denominator=denominator))

        return sorted((e for e in events if start <= e.effective_date <= end), key=lambda e: e.effective_date)

    def fetch_news_sentiment(self, ref: InstrumentRef) -> list[NewsArticle]:
        """Fetch recent news + per-article sentiment for one instrument.

        Unlike `fetch_daily`, an empty result is not `SymbolNotFound`: "no
        recent news" is a legitimate answer, not a failure — the caller
        persists it as such rather than treating it as an error to retry
        immediately.
        """
        symbol = ref.provider_symbol.split(".")[0]

        self._throttle.wait()

        data = self._get(
            {
                "function": "NEWS_SENTIMENT",
                "tickers": symbol,
                "apikey": self.api_key,
                "limit": "50",
            }
        )

        # Same two rate-limit shapes as fetch_daily — this endpoint shares
        # the same 5/min account-level quota.
        if data.get("Note"):
            raise RateLimited("rate limited (API call frequency)")
        if data.get("Information"):
            raise RateLimited(data["Information"])

        articles: list[NewsArticle] = []
        for item in data.get("feed", []):
            match = next(
                (
                    ts
                    for ts in item.get("ticker_sentiment", [])
                    if ts.get("ticker", "").upper() == symbol.upper()
                ),
                None,
            )
            if match is None:
                # Defensive: `tickers=` should guarantee relevance, but never
                # guess which ticker_sentiment entry this article is about.
                continue
            articles.append(
                NewsArticle(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    source=item.get("source", ""),
                    time_published=datetime.strptime(item["time_published"], "%Y%m%dT%H%M%S"),
                    summary=item.get("summary", ""),
                    overall_sentiment_label=item.get("overall_sentiment_label", ""),
                    overall_sentiment_score=float(item.get("overall_sentiment_score", 0.0)),
                    ticker_relevance_score=float(match.get("relevance_score", 0.0)),
                    ticker_sentiment_score=float(match.get("ticker_sentiment_score", 0.0)),
                    ticker_sentiment_label=match.get("ticker_sentiment_label", ""),
                )
            )
        return articles
