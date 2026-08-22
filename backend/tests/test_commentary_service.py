"""Unit tests for `analysis/commentary_service.py::get_commentary`, using a
fake Perplexity client — no real network, no real API key."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.commentary_service import get_commentary
from app.db import Base
from app.messages import CommentaryOutcome
from app.models import Instrument, InstrumentCommentary
from app.providers.base import ProviderUnavailable, RateLimited
from app.providers.perplexity import Citation, Commentary


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


def make_instrument(db):
    instrument = Instrument(broker_symbol="AAPL.US", provider_symbol="AAPL", category="STOCK", name="Apple Inc.")
    db.add(instrument)
    db.commit()
    db.refresh(instrument)
    return instrument


class FakeClient:
    def __init__(self, enabled=True, commentary=None, error=None):
        self._enabled = enabled
        self._commentary = commentary or Commentary(
            content="A summary.", citations=[Citation(url="https://example.com")], model="sonar"
        )
        self._error = error
        self.calls = 0

    def is_enabled(self):
        return self._enabled

    def ask_about(self, symbol, name=None, sector=None, *, max_tokens=None):
        self.calls += 1
        if self._error:
            raise self._error
        return self._commentary


class TestGetCommentary:
    def test_disabled_client_returns_no_provider_outcome(self, db):
        instrument = make_instrument(db)
        row, outcome = get_commentary(db, instrument, FakeClient(enabled=False), ttl_days=7)

        assert row is None
        assert outcome.code == CommentaryOutcome.NO_PROVIDER

    def test_fresh_fetch_persists_a_row(self, db):
        instrument = make_instrument(db)
        client = FakeClient()

        row, outcome = get_commentary(db, instrument, client, ttl_days=7)

        assert outcome.code == CommentaryOutcome.UPDATED
        assert client.calls == 1
        assert row.content == "A summary."
        assert row.model == "sonar"
        assert row.citations == [{"url": "https://example.com", "title": None}]

    def test_cache_hit_within_ttl_skips_the_client_call(self, db):
        instrument = make_instrument(db)
        client = FakeClient()
        get_commentary(db, instrument, client, ttl_days=7)
        assert client.calls == 1

        row, outcome = get_commentary(db, instrument, client, ttl_days=7)

        assert outcome.code == CommentaryOutcome.ALREADY_FRESH
        assert client.calls == 1

    def test_ttl_days_is_actually_read_from_the_argument_not_hardcoded(self, db):
        instrument = make_instrument(db)
        stale = InstrumentCommentary(
            instrument_id=instrument.id,
            fetched_at=datetime.now(UTC) - timedelta(days=2),
            model="sonar",
            content="old",
            citations=[],
        )
        db.add(stale)
        db.commit()

        # ttl_days=1: a 2-day-old row is stale under this TTL, must refetch.
        client = FakeClient()
        row, outcome = get_commentary(db, instrument, client, ttl_days=1)
        assert outcome.code == CommentaryOutcome.UPDATED
        assert client.calls == 1

    def test_rate_limited_returns_cached_row_if_any(self, db):
        instrument = make_instrument(db)
        get_commentary(db, instrument, FakeClient(), ttl_days=7)
        row = db.get(InstrumentCommentary, instrument.id)
        row.fetched_at = datetime.now(UTC) - timedelta(days=8)
        db.commit()

        result_row, outcome = get_commentary(
            db, instrument, FakeClient(error=RateLimited("throttled")), ttl_days=7
        )

        assert outcome.code == CommentaryOutcome.RATE_LIMITED
        assert result_row is not None

    def test_provider_error_returns_failed_outcome(self, db):
        instrument = make_instrument(db)
        row, outcome = get_commentary(
            db, instrument, FakeClient(error=ProviderUnavailable("down")), ttl_days=7
        )

        assert outcome.code == CommentaryOutcome.FAILED
        assert outcome.params["error"] == "down"

    def test_concurrent_first_fetch_does_not_crash_on_duplicate_insert(self, db):
        """Same race as `test_news_service.py`'s equivalent test: two
        near-simultaneous requests for the same never-before-cached
        instrument (e.g. the "Get AI commentary" button double-clicked) both
        see `cached=None` and both try to INSERT a row with the same
        `instrument_id` primary key. Simulated by having the fake client
        itself insert the "other request's" row from inside our own call."""

        class RacingClient(FakeClient):
            def ask_about(self, symbol, name=None, sector=None, *, max_tokens=None):
                self.calls += 1
                other = InstrumentCommentary(
                    instrument_id=instrument.id,
                    fetched_at=datetime.now(UTC),
                    model="sonar",
                    content="a racing insert",
                    citations=[],
                )
                db.add(other)
                db.commit()
                return self._commentary

        instrument = make_instrument(db)
        client = RacingClient()

        row, outcome = get_commentary(db, instrument, client, ttl_days=7)

        assert outcome.code == CommentaryOutcome.UPDATED
        assert row is not None
        assert row.content == "A summary."  # our fetched content, not the racing insert's
        assert db.query(InstrumentCommentary).filter_by(instrument_id=instrument.id).count() == 1
