"""Unit tests for `analysis/news_service.py::get_news`, using a fake
provider — no real network, no real AlphaVantageProvider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.news_service import NEWS_CACHE_TTL_DAYS, get_news
from app.db import Base
from app.messages import NewsOutcome
from app.models import Instrument, NewsSentiment, ProviderUsage
from app.providers.alpha_vantage import NewsArticle
from app.providers.base import ProviderUnavailable, RateLimited


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


def make_instrument(db, symbol="AAPL.US", provider_symbol="AAPL"):
    instrument = Instrument(broker_symbol=symbol, provider_symbol=provider_symbol, category="STOCK")
    db.add(instrument)
    db.commit()
    db.refresh(instrument)
    return instrument


def make_article(symbol="AAPL") -> NewsArticle:
    return NewsArticle(
        title="A headline",
        url="https://example.com/a",
        source="Example",
        time_published=datetime(2026, 8, 20, 9, 30),
        summary="A summary.",
        overall_sentiment_label="Neutral",
        overall_sentiment_score=0.05,
        ticker_relevance_score=0.8,
        ticker_sentiment_score=0.3,
        ticker_sentiment_label="Somewhat-Bullish",
    )


class FakeProvider:
    def __init__(self, enabled=True, articles=None, error=None):
        self._enabled = enabled
        self._articles = articles if articles is not None else [make_article()]
        self._error = error
        self.calls = 0

    def is_enabled(self):
        return self._enabled

    def fetch_news_sentiment(self, ref):
        self.calls += 1
        if self._error:
            raise self._error
        return self._articles


class TestGetNews:
    def test_disabled_provider_returns_no_provider_outcome(self, db):
        instrument = make_instrument(db)
        row, outcome = get_news(db, instrument, FakeProvider(enabled=False))

        assert row is None
        assert outcome.code == NewsOutcome.NO_PROVIDER

    def test_fresh_fetch_persists_a_row_and_records_usage(self, db):
        instrument = make_instrument(db)
        provider = FakeProvider()

        row, outcome = get_news(db, instrument, provider)

        assert outcome.code == NewsOutcome.UPDATED
        assert provider.calls == 1
        assert len(row.articles) == 1
        usage = db.query(ProviderUsage).filter_by(provider="alpha_vantage").one()
        assert usage.count == 1

    def test_cache_hit_within_ttl_skips_the_provider_call(self, db):
        instrument = make_instrument(db)
        provider = FakeProvider()
        get_news(db, instrument, provider)
        assert provider.calls == 1

        row, outcome = get_news(db, instrument, provider)

        assert outcome.code == NewsOutcome.ALREADY_FRESH
        assert provider.calls == 1  # not called again

    def test_stale_cache_triggers_a_new_fetch(self, db):
        instrument = make_instrument(db)
        stale = NewsSentiment(
            instrument_id=instrument.id,
            fetched_at=datetime.now(UTC) - timedelta(days=NEWS_CACHE_TTL_DAYS + 1),
            articles=[],
        )
        db.add(stale)
        db.commit()

        provider = FakeProvider()
        row, outcome = get_news(db, instrument, provider)

        assert outcome.code == NewsOutcome.UPDATED
        assert provider.calls == 1

    def test_empty_articles_still_persists_a_row(self, db):
        instrument = make_instrument(db)
        provider = FakeProvider(articles=[])

        row, outcome = get_news(db, instrument, provider)

        assert outcome.code == NewsOutcome.EMPTY
        assert row is not None
        assert row.articles == []

    def test_unmapped_instrument_is_not_mapped_outcome(self, db):
        instrument = Instrument(broker_symbol="US500", category="CFD", provider_symbol=None)
        db.add(instrument)
        db.commit()
        db.refresh(instrument)

        row, outcome = get_news(db, instrument, FakeProvider())

        assert outcome.code == NewsOutcome.NOT_MAPPED

    def test_rate_limited_returns_cached_row_if_any(self, db):
        instrument = make_instrument(db)
        get_news(db, instrument, FakeProvider())  # seed a cached row
        stale_provider = FakeProvider(error=RateLimited("throttled"))
        # Force a stale row so the TTL check doesn't short-circuit before the fetch.
        row = db.get(NewsSentiment, instrument.id)
        row.fetched_at = datetime.now(UTC) - timedelta(days=NEWS_CACHE_TTL_DAYS + 1)
        db.commit()

        result_row, outcome = get_news(db, instrument, stale_provider)

        assert outcome.code == NewsOutcome.RATE_LIMITED
        assert result_row is not None  # the stale cached row, not lost

    def test_provider_error_returns_failed_outcome(self, db):
        instrument = make_instrument(db)
        row, outcome = get_news(db, instrument, FakeProvider(error=ProviderUnavailable("down")))

        assert outcome.code == NewsOutcome.FAILED
        assert outcome.params["error"] == "down"

    def test_usage_recorded_exactly_once_even_on_error(self, db):
        instrument = make_instrument(db)
        get_news(db, instrument, FakeProvider(error=ProviderUnavailable("down")))

        usage = db.query(ProviderUsage).filter_by(provider="alpha_vantage").one()
        assert usage.count == 1

    def test_concurrent_first_fetch_does_not_crash_on_duplicate_insert(self, db):
        """Reproduces a real bug: two near-simultaneous requests for the same
        never-before-cached instrument (e.g. a table row expanded twice in a
        row under React StrictMode's double effect-invoke) both see
        `cached=None`, and both try to INSERT a `NewsSentiment` row with the
        same `instrument_id` primary key. Simulated here by having the fake
        provider itself insert the "other request's" row, from inside our own
        call, right before we try to insert ours — this session sees the
        conflict at commit time exactly like two real concurrent sessions
        would. Must be handled gracefully (row updated, no exception), not
        crash with an unhandled IntegrityError."""

        class RacingProvider(FakeProvider):
            def fetch_news_sentiment(self, ref):
                self.calls += 1
                from datetime import UTC, datetime

                from app.models import NewsSentiment

                other = NewsSentiment(
                    instrument_id=instrument.id, fetched_at=datetime.now(UTC), articles=[]
                )
                db.add(other)
                db.commit()
                return self._articles

        instrument = make_instrument(db)
        provider = RacingProvider()

        row, outcome = get_news(db, instrument, provider)

        assert outcome.code == NewsOutcome.UPDATED
        assert row is not None
        assert len(row.articles) == 1  # our fetched article, not the racing empty insert
        # Exactly one row exists for this instrument — the race didn't leave
        # a duplicate or an orphaned row behind.
        assert db.query(NewsSentiment).filter_by(instrument_id=instrument.id).count() == 1
