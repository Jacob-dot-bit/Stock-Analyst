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


class TestFreshness:
    """Regression tests for a bug that silently defeated the whole cache.

    Freshness used to be "is the newest bar from the last trading day". Free feeds lag —
    Twelve Data's newest bar was two days old — so every instrument looked stale forever
    and every run re-fetched the entire portfolio, burning the daily quota.
    """

    def test_provider_lagging_behind_today_is_still_fresh(self, db):
        instrument = make_instrument(db)
        # Bars stop two days ago, as a real free provider's do.
        stale_looking = bars_ending(date.today() - timedelta(days=2))
        provider = FakeProvider("yahoo", bars=stale_looking)
        chain = ProviderChain([provider])

        refresh_instrument(db, instrument, chain)
        db.commit()
        second = refresh_instrument(db, instrument, chain)

        assert second.code == PriceOutcome.ALREADY_FRESH
        assert provider.calls == 1  # the whole point: no second request

    def test_asking_is_recorded_even_when_the_symbol_is_wrong(self, db):
        """A bad symbol will not fix itself today; stop asking until tomorrow.

        But it must not be reported as "fresh" either: nothing was ever stored, and a
        reassuring label over an empty series is worse than an honest gap.
        """
        instrument = make_instrument(db)
        provider = FakeProvider("yahoo", error=SymbolNotFound("X"))
        chain = ProviderChain([provider])

        refresh_instrument(db, instrument, chain)
        db.commit()
        second = refresh_instrument(db, instrument, chain)

        # What matters here is that no second request went out. The exact wording of
        # the shortfall is covered by TestWhyThereIsNoData.
        assert provider.calls == 1
        assert second.code in {PriceOutcome.NEEDS_ISIN, PriceOutcome.STILL_UNAVAILABLE}

    def test_throttling_does_not_count_as_asked(self, db):
        """Rate limiting is temporary, so the instrument must be retried next run."""
        instrument = make_instrument(db)
        provider = FakeProvider("yahoo", error=RateLimited("slow down"))
        chain = ProviderChain([provider])

        refresh_instrument(db, instrument, chain)
        db.commit()
        second = refresh_instrument(db, instrument, chain)

        assert second.code == PriceOutcome.RATE_LIMITED
        assert provider.calls == 2

    def test_yesterdays_check_does_not_count(self, db):
        instrument = make_instrument(db)
        instrument.prices_checked_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
        provider = FakeProvider("yahoo", bars=bars_ending(date.today()))

        outcome = refresh_instrument(db, instrument, ProviderChain([provider]))

        assert outcome.code == PriceOutcome.UPDATED


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

        # A clock that advances on every read, so the budget is crossed part-way.
        # Asserting on an exact tick count would break whenever the implementation
        # reads the clock one more or one fewer time.
        monkeypatch.setattr("app.prices.service.datetime", _AdvancingClock(seconds_per_call=6))

        report = refresh_many(db, instruments, chain, budget_seconds=10)

        assert report.remaining > 0
        assert report.outcomes[-1].code == PriceOutcome.BUDGET_REACHED
        assert report.outcomes[-1].params["remaining"] == report.remaining
        # Whatever was reached is settled, and what was not is still owed.
        assert report.updated + report.remaining == len(instruments)

    def test_fresh_instruments_do_not_consume_the_budget(self, db, monkeypatch):
        """Skipping costs nothing, so it must not push real work past the deadline.

        Otherwise a run reports "8 updated, 0 already fresh, 29 remaining" while nearly
        all of those 29 would have been skipped instantly.
        """
        chain = ProviderChain([FakeProvider("yahoo", bars=bars_ending(date.today()))])

        # Genuinely fresh means asked today *and* holding data, so fetch them once.
        fresh = [make_instrument(db, f"F{i}.US", f"F{i}") for i in range(5)]
        for instrument in fresh:
            refresh_instrument(db, instrument, chain)
        db.commit()

        pending = make_instrument(db, "NEW.US", "NEW")
        report = refresh_many(db, [*fresh, pending], chain, budget_seconds=60)

        assert report.skipped == 5
        assert report.updated == 1
        assert report.remaining == 0

    def test_work_is_kept_when_a_later_instrument_is_rate_limited(self, db):
        """A limit hit halfway through must not discard what already succeeded."""
        first = make_instrument(db, "AAPL.US", "AAPL")
        second = make_instrument(db, "MSFT.US", "MSFT")

        class Flaky(FakeProvider):
            def fetch_daily(self, ref, start, end):
                self.calls += 1
                if ref.provider_symbol == "MSFT":
                    raise RateLimited("slow down")
                return bars_ending(date.today())

        report = refresh_many(db, [first, second], ProviderChain([Flaky("yahoo")]))

        assert report.updated == 1
        assert report.failed == 1
        assert db.execute(select(PriceBar)).scalars().all()  # first instrument's bars survived


class _AdvancingClock:
    """Stand-in for the datetime module whose clock moves on every read.

    Lets a test cross a time budget deterministically without depending on how many
    times the implementation happens to look at the clock.
    """

    def __init__(self, seconds_per_call: int):
        self._step = seconds_per_call
        self._calls = 0
        self._origin = datetime.now(UTC)

    def now(self, tz=None):
        moment = self._origin + timedelta(seconds=self._step * self._calls)
        self._calls += 1
        return moment


class TestConcurrency:
    """Two refreshes at once double the quota spent and gain nothing.

    Observed for real: a click in the browser and a call from a terminal overlapped,
    re-fetching six instruments whose bars had just been stored seconds earlier.
    """

    def test_second_concurrent_run_is_refused(self, db):
        from app.prices import service

        instrument = make_instrument(db)
        chain = ProviderChain([FakeProvider("yahoo", bars=bars_ending(date.today()))])

        service._refresh_lock.acquire()
        try:
            report = refresh_many(db, [instrument], chain)
        finally:
            service._refresh_lock.release()

        assert report.outcomes[0].code == PriceOutcome.ALREADY_RUNNING
        assert report.remaining == 1

    def test_the_lock_is_released_afterwards(self, db):
        """A refused run must not leave the lock held and block every later refresh."""
        from app.prices import service

        instrument = make_instrument(db)
        chain = ProviderChain([FakeProvider("yahoo", bars=bars_ending(date.today()))])

        refresh_many(db, [instrument], chain)

        assert service._refresh_lock.acquire(blocking=False)
        service._refresh_lock.release()


class TestWhyThereIsNoData:
    """"No source covers this" and "we never had an identifier to try" are different.

    Reporting the first when it is really the second sends the user hunting for a
    problem that is not there, when a 12-character field would fix it.
    """

    def test_missing_isin_is_reported_as_such(self, db):
        instrument = make_instrument(db, "CAC.FR", "CAC.PA")
        chain = ProviderChain([FakeProvider("frankfurt", error=SymbolNotFound("needs ISIN"))])

        refresh_instrument(db, instrument, chain)
        db.commit()
        second = refresh_instrument(db, instrument, chain)

        assert second.code == PriceOutcome.NEEDS_ISIN

    def test_with_an_isin_it_is_a_genuine_coverage_gap(self, db):
        instrument = make_instrument(db, "CAC.FR", "CAC.PA")
        instrument.isin = "FR0007052782"
        db.commit()
        chain = ProviderChain([FakeProvider("frankfurt", error=SymbolNotFound("not listed"))])

        refresh_instrument(db, instrument, chain)
        db.commit()
        second = refresh_instrument(db, instrument, chain)

        assert second.code == PriceOutcome.STILL_UNAVAILABLE
