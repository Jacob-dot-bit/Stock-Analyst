"""Tests for `AlphaVantageProvider`'s daily bars and news/sentiment.

All network calls are mocked, mirroring `test_providers.py`'s pattern. This
closes a pre-existing gap: `AlphaVantageProvider` had zero direct test
coverage before Phase 6.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.providers.alpha_vantage import AlphaVantageProvider
from app.providers.base import InstrumentRef, RateLimited, Throttle
from tests.test_providers import client_returning


def news_payload(feed: list[dict]) -> dict:
    return {"items": str(len(feed)), "feed": feed}


def article(
    symbol: str = "AAPL",
    title: str = "Apple announces something",
    relevance: float = 0.8,
    sentiment_score: float = 0.3,
    sentiment_label: str = "Somewhat-Bullish",
) -> dict:
    return {
        "title": title,
        "url": "https://example.com/article",
        "source": "Example News",
        "time_published": "20260820T093000",
        "summary": "A summary.",
        "overall_sentiment_label": "Neutral",
        "overall_sentiment_score": 0.05,
        "ticker_sentiment": [
            {
                "ticker": symbol,
                "relevance_score": str(relevance),
                "ticker_sentiment_score": str(sentiment_score),
                "ticker_sentiment_label": sentiment_label,
            }
        ],
    }


class TestFetchDaily:
    def test_parses_bars(self):
        payload = {
            "Time Series (Daily)": {
                "2023-11-01": {"1. open": "10", "2. high": "11", "3. low": "9", "4. close": "10.5", "5. volume": "100"},
            }
        }
        provider = AlphaVantageProvider(api_key="key", client=client_returning(lambda r: httpx.Response(200, json=payload)))
        provider._throttle = Throttle(0)

        bars = provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2023, 11, 1), date(2023, 11, 30))

        assert len(bars) == 1
        assert bars[0].close == pytest.approx(10.5)


class TestFetchNewsSentiment:
    def test_parses_articles_matching_our_ticker(self):
        provider = AlphaVantageProvider(
            api_key="key",
            client=client_returning(lambda r: httpx.Response(200, json=news_payload([article(symbol="AAPL")]))),
        )
        provider._throttle = Throttle(0)

        articles = provider.fetch_news_sentiment(InstrumentRef(provider_symbol="AAPL"))

        assert len(articles) == 1
        assert articles[0].title == "Apple announces something"
        assert articles[0].ticker_sentiment_label == "Somewhat-Bullish"
        assert articles[0].ticker_relevance_score == pytest.approx(0.8)

    def test_article_with_no_matching_ticker_sentiment_is_skipped(self):
        provider = AlphaVantageProvider(
            api_key="key",
            client=client_returning(lambda r: httpx.Response(200, json=news_payload([article(symbol="MSFT")]))),
        )
        provider._throttle = Throttle(0)

        articles = provider.fetch_news_sentiment(InstrumentRef(provider_symbol="AAPL"))

        assert articles == []

    def test_empty_feed_returns_empty_list_not_an_error(self):
        provider = AlphaVantageProvider(
            api_key="key", client=client_returning(lambda r: httpx.Response(200, json=news_payload([])))
        )
        provider._throttle = Throttle(0)

        articles = provider.fetch_news_sentiment(InstrumentRef(provider_symbol="AAPL"))

        assert articles == []

    def test_information_field_raises_rate_limited(self):
        provider = AlphaVantageProvider(
            api_key="key",
            client=client_returning(lambda r: httpx.Response(200, json={"Information": "quota exceeded"})),
        )
        provider._throttle = Throttle(0)

        with pytest.raises(RateLimited):
            provider.fetch_news_sentiment(InstrumentRef(provider_symbol="AAPL"))

    def test_note_field_raises_rate_limited(self):
        provider = AlphaVantageProvider(
            api_key="key",
            client=client_returning(lambda r: httpx.Response(200, json={"Note": "5 calls per minute"})),
        )
        provider._throttle = Throttle(0)

        with pytest.raises(RateLimited):
            provider.fetch_news_sentiment(InstrumentRef(provider_symbol="AAPL"))


class _CountingThrottle:
    """A fake standing in for `Throttle`, just to prove both methods call
    `.wait()` on the exact same object rather than two independent ones."""

    def __init__(self) -> None:
        self.calls = 0

    def wait(self) -> None:
        self.calls += 1


class TestSharedThrottle:
    def test_fetch_daily_and_fetch_news_sentiment_use_the_same_throttle_object(self):
        """Both methods must go through `self._throttle` so a price call and
        a news call together never exceed the real 5/min server-side limit —
        proven by swapping in one fake and confirming both methods record
        their wait() call on it."""
        provider = AlphaVantageProvider(
            api_key="key",
            client=client_returning(
                lambda r: httpx.Response(200, json={"Time Series (Daily)": {}, "feed": []})
            ),
        )
        fake = _CountingThrottle()
        provider._throttle = fake

        with pytest.raises(Exception):
            provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2023, 1, 1), date(2023, 1, 2))
        assert fake.calls == 1

        provider.fetch_news_sentiment(InstrumentRef(provider_symbol="AAPL"))
        assert fake.calls == 2
