"""Tests for price refreshing and caching."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.messages import PriceOutcome
from app.models import Instrument, MappingStatus, PriceBar
from app.prices.service import refresh_instrument, refresh_many
from app.providers.base import Bar, ProviderChain, RateLimited, SymbolNotFound
from tests.test_providers import FakeProvider


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def make_instrument(db, symbol="AAPL.US", provider_symbol="AAPL", status=MappingStatus.RESOLVED):
    instrument = Instrument(
        broker_symbol=symbol, provider_symbol=provider_symbol, mapping_status=status
    )
    db.add(instrument)
    db.commit()
    return instrument


def bars_ending(end: date, count: int = 3) -> list[Bar]:
    return [
        Bar(
            bar_date=end - timedelta(days=count - 1 - i),
            open=10.0 + i,
            high=11.0 + i,
            low=9.0 + i,
            close=10.5 + i,
            volume=1000,
        )
        for i in range(count)
    ]


class TestRefreshInstrument:
    def test_stores_bars_and_records_the_provider(self, db):
        instrument = make_instrument(db)
        chain = ProviderChain([FakeProvider("yahoo", bars=bars_ending(date.today()))])

        outcome = refresh_instrument(db, instrument, chain)
        db.commit()

        assert outcome.code == PriceOutcome.UPDATED
        stored = db.execute(select(PriceBar)).scalars().all()
        assert len(stored) == 3
        # "Where did this number come from" must always have an answer.
        assert {bar.provider for bar in stored} == {"yahoo"}

    def test_successful_fetch_verifies_the_symbol_mapping(self, db):
        """A provider returning data is the only real proof the mapping is right."""
        instrument = make_instrument(db)
        assert instrument.mapping_status == MappingStatus.RESOLVED

        refresh_instrument(db, instrument, ProviderChain([FakeProvider("yahoo", bars=bars_ending(date.today()))]))
        db.commit()

        assert instrument.mapping_status == MappingStatus.VERIFIED
        assert instrument.verified_provider == "yahoo"
        assert instrument.verified_at is not None

    def test_manual_mapping_stays_manual_but_gets_verified(self, db):
        """Verification and provenance are separate facts; neither should erase the other."""
        instrument = make_instrument(db, status=MappingStatus.MANUAL)

        refresh_instrument(db, instrument, ProviderChain([FakeProvider("yahoo", bars=bars_ending(date.today()))]))
        db.commit()

        assert instrument.mapping_status == MappingStatus.MANUAL
        assert instrument.verified_at is not None

    def test_failed_fetch_does_not_verify(self, db):
        instrument = make_instrument(db)
        chain = ProviderChain([FakeProvider("yahoo", error=SymbolNotFound("AAPL"))])

        outcome = refresh_instrument(db, instrument, chain)

        assert outcome.code == PriceOutcome.SYMBOL_NOT_FOUND
        assert instrument.verified_at is None
        assert instrument.mapping_status == MappingStatus.RESOLVED

    def test_unmapped_instrument_is_not_fetched(self, db):
        instrument = make_instrument(db, "US500", None, MappingStatus.UNRESOLVED)
        provider = FakeProvider("yahoo", bars=bars_ending(date.today()))

        outcome = refresh_instrument(db, instrument, ProviderChain([provider]))

        assert outcome.code == PriceOutcome.NOT_MAPPED
        assert provider.calls == 0  # no rate-limit budget wasted on it

    def test_rate_limited_is_distinct_from_failure(self, db):
        """The user must be able to tell "come back later" from "this will never work"."""
        instrument = make_instrument(db)
        chain = ProviderChain([FakeProvider("yahoo", error=RateLimited("slow down"))])

        outcome = refresh_instrument(db, instrument, chain)

        assert outcome.code == PriceOutcome.RATE_LIMITED
        assert outcome.params["provider"] == "yahoo"

    def test_no_enabled_provider(self, db):
        instrument = make_instrument(db)
        chain = ProviderChain([FakeProvider("off", bars=bars_ending(date.today()), enabled=False)])

        assert refresh_instrument(db, instrument, chain).code == PriceOutcome.NO_PROVIDER


class TestCaching:
    def test_fresh_instrument_is_skipped(self, db):
        """The cache is what keeps a refresh inside free-tier rate limits."""
        instrument = make_instrument(db)
        provider = FakeProvider("yahoo", bars=bars_ending(date.today()))
        chain = ProviderChain([provider])

        refresh_instrument(db, instrument, chain)
        db.commit()
        second = refresh_instrument(db, instrument, chain)

        assert second.code == PriceOutcome.ALREADY_FRESH
        assert provider.calls == 1  # no second network call

    def test_force_refetches_even_when_fresh(self, db):
        instrument = make_instrument(db)
        provider = FakeProvider("yahoo", bars=bars_ending(date.today()))
        chain = ProviderChain([provider])

        refresh_instrument(db, instrument, chain)
        db.commit()
        refresh_instrument(db, instrument, chain, force=True)

        assert provider.calls == 2

    def test_existing_bars_are_updated_not_duplicated(self, db):
        """Providers revise recent closes; a second fetch must not duplicate the row."""
        instrument = make_instrument(db)
        today = date.today()

        refresh_instrument(db, instrument, ProviderChain([FakeProvider("yahoo", bars=bars_ending(today))]))
        db.commit()

        revised = [Bar(bar_date=today, open=1, high=1, low=1, close=99.0, volume=1)]
        refresh_instrument(db, instrument, ProviderChain([FakeProvider("yahoo", bars=revised)]), force=True)
        db.commit()

        rows = db.execute(select(PriceBar).where(PriceBar.bar_date == today)).scalars().all()
        assert len(rows) == 1
        assert rows[0].close == 99.0

    def test_stale_data_triggers_a_refetch(self, db):
        instrument = make_instrument(db)
        old = date.today() - timedelta(days=30)
        db.add(
            PriceBar(instrument_id=instrument.id, bar_date=old, close=10.0, provider="yahoo")
        )
        db.commit()

        provider = FakeProvider("yahoo", bars=bars_ending(date.today()))
        outcome = refresh_instrument(db, instrument, ProviderChain([provider]))

        assert outcome.code == PriceOutcome.UPDATED
        assert provider.calls == 1


class TestRefreshMany:
    def test_counts_each_kind_of_outcome(self, db):
        good = make_instrument(db, "AAPL.US", "AAPL")
        unmapped = make_instrument(db, "US500", None, MappingStatus.UNRESOLVED)
        chain = ProviderChain([FakeProvider("yahoo", bars=bars_ending(date.today()))])

        report = refresh_many(db, [good, unmapped], chain)

        assert report.updated == 1
        assert report.failed == 1
        assert len(report.outcomes) == 2

    def test_budget_stops_the_run_and_reports_what_is_left(self, db, monkeypatch):
        """Partial progress must be visible, not hidden behind a hang or a half-failure."""
        instruments = [make_instrument(db, f"S{i}.US", f"S{i}") for i in range(5)]
        chain = ProviderChain([FakeProvider("yahoo", bars=bars_ending(date.today()))])

        # A clock that jumps past the budget after the first instrument.
        ticks = iter([datetime.now(UTC) + timedelta(seconds=t) for t in (0, 0, 999, 999, 999, 999)])
        monkeypatch.setattr("app.prices.service.datetime", _FrozenClock(ticks))

        report = refresh_many(db, instruments, chain, budget_seconds=10)

        assert report.remaining == 4
        assert report.outcomes[-1].code == PriceOutcome.BUDGET_REACHED
        assert report.outcomes[-1].params["remaining"] == 4

    def test_work_is_kept_when_a_later_instrument_is_rate_limited(self, db):
        """A limit hit halfway through must not discard what already succeeded."""
        first = make_instrument(db, "AAPL.US", "AAPL")
        second = make_instrument(db, "MSFT.US", "MSFT")

        class Flaky(FakeProvider):
            def fetch_daily(self, symbol, start, end):
                self.calls += 1
                if symbol == "MSFT":
                    raise RateLimited("slow down")
                return bars_ending(date.today())

        report = refresh_many(db, [first, second], ProviderChain([Flaky("yahoo")]))

        assert report.updated == 1
        assert report.failed == 1
        assert db.execute(select(PriceBar)).scalars().all()  # first instrument's bars survived


class _FrozenClock:
    """Minimal stand-in for the datetime module, driving refresh_many's budget."""

    def __init__(self, ticks):
        self._ticks = ticks

    def now(self, tz=None):
        return next(self._ticks)
