"""Tests for `symbols/duplicates.py`'s FIGI backfill and duplicate
detection — see DEVLOG "Decision 3u.76"."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import DiscoveryCandidate, Instrument, Position, ScreenerCandidate, WatchlistItem
from app.providers.openfigi import FIGI_LOOKUP_FAILED, FigiMatch
from app.symbols.duplicates import backfill_figis, find_figi_duplicates


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


def _instrument(db, symbol, **kwargs) -> Instrument:
    instrument = Instrument(broker_symbol=symbol, category="STOCK", currency="USD", country="US", **kwargs)
    db.add(instrument)
    db.commit()
    db.refresh(instrument)
    return instrument


class TestBackfillFigisCandidateSelection:
    def test_held_watchlisted_and_screened_instruments_are_always_eligible(self, db, monkeypatch):
        held = _instrument(db, "AAA.US")
        watched = _instrument(db, "BBB.US")
        screened = _instrument(db, "CCC.US")
        db.add(Position(instrument_id=held.id, source="MANUAL", quantity=1, avg_price=1.0))
        db.add(WatchlistItem(instrument_id=watched.id))
        db.add(ScreenerCandidate(instrument_id=screened.id))
        db.commit()
        monkeypatch.setattr("app.symbols.duplicates.map_instruments", lambda jobs, *a, **k: [None] * len(jobs))

        result = backfill_figis(db, api_key=None, max_jobs_per_request=10)

        assert result["checked"] == 3

    def test_never_evaluated_discovery_candidates_are_excluded(self, db, monkeypatch):
        pending = _instrument(db, "AAA.US")  # verified_at is None
        db.add(DiscoveryCandidate(instrument_id=pending.id, source="sp500"))
        db.commit()
        monkeypatch.setattr("app.symbols.duplicates.map_instruments", lambda jobs, *a, **k: [None] * len(jobs))

        result = backfill_figis(db, api_key=None, max_jobs_per_request=10)

        assert result["checked"] == 0

    def test_already_evaluated_discovery_candidates_are_included(self, db, monkeypatch):
        evaluated = _instrument(db, "AAA.US", verified_at=datetime.now(UTC))
        db.add(DiscoveryCandidate(instrument_id=evaluated.id, source="sp500"))
        db.commit()
        monkeypatch.setattr("app.symbols.duplicates.map_instruments", lambda jobs, *a, **k: [None] * len(jobs))

        result = backfill_figis(db, api_key=None, max_jobs_per_request=10)

        assert result["checked"] == 1

    def test_already_checked_instruments_are_excluded(self, db, monkeypatch):
        watched = _instrument(db, "AAA.US", figi_checked_at=datetime.now(UTC))
        db.add(WatchlistItem(instrument_id=watched.id))
        db.commit()
        monkeypatch.setattr("app.symbols.duplicates.map_instruments", lambda jobs, *a, **k: [None] * len(jobs))

        result = backfill_figis(db, api_key=None, max_jobs_per_request=10)

        assert result["checked"] == 0


class TestBackfillFigisChecksAreMarkedRegardlessOfOutcome:
    def test_a_genuine_non_match_is_marked_checked_and_never_retried(self, db, monkeypatch):
        watched = _instrument(db, "AAA.US")
        db.add(WatchlistItem(instrument_id=watched.id))
        db.commit()
        monkeypatch.setattr("app.symbols.duplicates.map_instruments", lambda jobs, *a, **k: [None] * len(jobs))

        first = backfill_figis(db, api_key=None, max_jobs_per_request=10)
        second = backfill_figis(db, api_key=None, max_jobs_per_request=10)

        assert first == {"checked": 1, "resolved": 0, "remaining": 0}
        # If this were keyed on "has a figi", a non-payer-shaped miss would
        # be re-selected forever — same bug class as Decision 3u.74.
        assert second == {"checked": 0, "resolved": 0, "remaining": 0}
        db.refresh(watched)
        assert watched.figi_checked_at is not None
        assert watched.figi is None

    def test_a_real_match_is_stored(self, db, monkeypatch):
        watched = _instrument(db, "AAA.US")
        db.add(WatchlistItem(instrument_id=watched.id))
        db.commit()
        monkeypatch.setattr(
            "app.symbols.duplicates.map_instruments",
            lambda jobs, *a, **k: [FigiMatch(figi="X", share_class_figi="Y", name="Real Name")],
        )

        result = backfill_figis(db, api_key=None, max_jobs_per_request=10)

        assert result == {"checked": 1, "resolved": 1, "remaining": 0}
        db.refresh(watched)
        assert watched.figi == "X"
        assert watched.share_class_figi == "Y"
        assert watched.name == "Real Name"  # backfilled since it had none

    def test_a_transient_lookup_failure_is_not_marked_checked_and_is_retried(self, db, monkeypatch):
        """A rate-limited/network-failed request is `FIGI_LOOKUP_FAILED`,
        not a genuine non-match — unlike the real-non-match case above,
        this one must stay eligible for the very next backfill call."""
        watched = _instrument(db, "AAA.US")
        db.add(WatchlistItem(instrument_id=watched.id))
        db.commit()
        monkeypatch.setattr(
            "app.symbols.duplicates.map_instruments", lambda jobs, *a, **k: [FIGI_LOOKUP_FAILED] * len(jobs)
        )

        result = backfill_figis(db, api_key=None, max_jobs_per_request=10)

        assert result == {"checked": 1, "resolved": 0, "remaining": 1}
        db.refresh(watched)
        assert watched.figi_checked_at is None

    def test_an_existing_name_is_not_overwritten(self, db, monkeypatch):
        watched = _instrument(db, "AAA.US", name="Original Name")
        db.add(WatchlistItem(instrument_id=watched.id))
        db.commit()
        monkeypatch.setattr(
            "app.symbols.duplicates.map_instruments",
            lambda jobs, *a, **k: [FigiMatch(figi="X", share_class_figi="Y", name="Different Name")],
        )

        backfill_figis(db, api_key=None, max_jobs_per_request=10)

        db.refresh(watched)
        assert watched.name == "Original Name"


class TestFindFigiDuplicates:
    def test_two_tracked_instruments_sharing_a_share_class_figi_are_paired(self, db):
        a = _instrument(db, "AAA.US", share_class_figi="SAME")
        b = _instrument(db, "BBB.L", share_class_figi="SAME")
        db.add(WatchlistItem(instrument_id=a.id))
        db.add(WatchlistItem(instrument_id=b.id))
        db.commit()

        pairs = find_figi_duplicates(db)

        assert len(pairs) == 1
        assert {pairs[0][0].id, pairs[0][1].id} == {a.id, b.id}

    def test_an_untracked_orphan_sharing_the_figi_is_excluded(self, db):
        a = _instrument(db, "AAA.US", share_class_figi="SAME")
        orphan = _instrument(db, "ORPHAN.US", share_class_figi="SAME")  # no Position/Watchlist/Screener row
        db.add(WatchlistItem(instrument_id=a.id))
        db.commit()

        assert find_figi_duplicates(db) == []

    def test_a_bare_unpromoted_discovery_row_sharing_the_figi_is_excluded(self, db):
        """`DiscoveryCandidate`'s own docstring says its pool is "never
        shown to the user directly" — a FIGI match against one must not
        break that invariant."""
        held = _instrument(db, "AAA.US", share_class_figi="SAME")
        db.add(Position(instrument_id=held.id, source="MANUAL", quantity=1, avg_price=1.0))
        discovery_only = _instrument(db, "BBB.L", share_class_figi="SAME", verified_at=datetime.now(UTC))
        db.add(DiscoveryCandidate(instrument_id=discovery_only.id, source="sp500"))
        db.commit()

        assert find_figi_duplicates(db) == []

    def test_no_shared_figi_produces_no_pairs(self, db):
        a = _instrument(db, "AAA.US", share_class_figi="ONE")
        b = _instrument(db, "BBB.US", share_class_figi="TWO")
        db.add(WatchlistItem(instrument_id=a.id))
        db.add(WatchlistItem(instrument_id=b.id))
        db.commit()

        assert find_figi_duplicates(db) == []
