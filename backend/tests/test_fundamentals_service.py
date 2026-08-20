"""Tests for the fundamentals fetch/cache service.

Uses fake EDGAR/ESEF providers (mirrors `test_providers.py::FakeProvider`'s
pattern) rather than mocked HTTP transports: each provider's own parsing is
covered by its own test file (`test_edgar.py`, `test_esef_provider.py`), so
this exercises only the orchestration `fundamentals/service.py` owns —
category eligibility, the ticker/expected_name calling convention, the
EDGAR-then-ESEF fallback (DEVLOG "Decision 3t.1"), outcome mapping, and the
upsert.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.fundamentals.service import fetch_fundamentals, fetch_one, get_fundamentals_progress
from app.messages import FundamentalsOutcome
from app.models import Fundamental, Instrument
from app.providers.base import ProviderUnavailable, RateLimited, SymbolNotFound
from app.providers.edgar import AnnualFigure, Fundamentals
from app.providers.esef import EsefFundamentals


class FakeEdgarProvider:
    name = "edgar"

    def __init__(self, enabled=True, fundamentals=None, error=None):
        self._enabled = enabled
        self._fundamentals = fundamentals
        self._error = error
        self.calls: list[tuple[str, str | None]] = []

    def is_enabled(self) -> bool:
        return self._enabled

    def fetch(self, ticker: str, expected_name: str | None = None) -> Fundamentals:
        self.calls.append((ticker, expected_name))
        if self._error:
            raise self._error
        return self._fundamentals


class FakeEsefProvider:
    name = "esef"

    def __init__(self, fundamentals=None, error=None):
        self._fundamentals = fundamentals
        self._error = error
        self.calls: list[str] = []

    def fetch(self, name: str) -> EsefFundamentals:
        self.calls.append(name)
        if self._error:
            raise self._error
        return self._fundamentals


class ProgressCapturingEdgarProvider(FakeEdgarProvider):
    """Captures a progress snapshot from *inside* the sequential loop, right
    before returning each instrument's result -- lets a test observe
    mid-run state without any real threading, since `fetch_fundamentals`
    processes one instrument at a time."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.snapshots = []

    def fetch(self, ticker: str, expected_name: str | None = None) -> Fundamentals:
        self.snapshots.append(get_fundamentals_progress())
        return super().fetch(ticker, expected_name)


#: An EDGAR fake with nothing configured — never enabled, never called
#: successfully — for tests that only care about the ESEF path.
def _no_edgar() -> FakeEdgarProvider:
    return FakeEdgarProvider(enabled=False)


#: An ESEF fake that always reports "not found" — for tests that only care
#: about the EDGAR path and want ESEF's fallback attempt to cleanly fail.
def _no_esef() -> FakeEsefProvider:
    return FakeEsefProvider(error=SymbolNotFound("not found"))


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


def _fundamentals(cik="0000320193", name="Apple Inc.") -> Fundamentals:
    return Fundamentals(
        cik=cik,
        company_name=name,
        concepts={
            "net_income": [AnnualFigure(2023, date(2023, 9, 30), 1000.0, "NetIncomeLoss", "USD")],
            "revenue": [AnnualFigure(2023, date(2023, 9, 30), 5000.0, "Revenues", "USD")],
        },
    )


def _esef_fundamentals(lei="969500MMPQVHK671GT54", name="L'AIR LIQUIDE SA") -> EsefFundamentals:
    return EsefFundamentals(
        lei=lei,
        company_name=name,
        concepts={
            "net_income": [AnnualFigure(2024, date(2024, 12, 31), 3440000000.0, "ProfitLoss", "EUR")],
            "revenue": [AnnualFigure(2024, date(2024, 12, 31), 27057800000.0, "Revenue", "EUR")],
        },
    )


class TestEligibility:
    def test_etf_is_not_applicable_and_makes_no_call(self, db):
        instrument = Instrument(broker_symbol="SPY.US", category="ETF", country="US")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.NOT_APPLICABLE
        assert edgar.calls == []
        assert esef.calls == []

    def test_cfd_is_not_applicable_and_makes_no_call(self, db):
        instrument = Instrument(broker_symbol="BITCOIN", category="CFD", country="US")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.NOT_APPLICABLE
        assert edgar.calls == []
        assert esef.calls == []


class TestTickerConvention:
    """See DEVLOG "Bug 3a.3": a non-US ticker's registrant must be verified
    against the broker's own name, or the fetch can attach a different
    company's financials. A US ticker must NOT demand a name match, or valid
    results (e.g. "AMD" vs "Advanced Micro Devices Inc") get discarded.
    """

    def test_us_instrument_passes_no_expected_name(self, db):
        instrument = Instrument(broker_symbol="AMD.US", category="STOCK", country="US", name="AMD")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())

        fetch_one(db, instrument, edgar, _no_esef(), force=False)

        assert edgar.calls == [("AMD", None)]

    def test_non_us_instrument_passes_its_broker_name(self, db):
        instrument = Instrument(broker_symbol="ORA.FR", category="STOCK", country="FR", name="Orange")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())

        fetch_one(db, instrument, edgar, _no_esef(), force=False)

        assert edgar.calls == [("ORA", "Orange")]


class TestEdgarThenEsefFallback:
    """DEVLOG "Decision 3t.1": ESEF is tried only when EDGAR didn't produce
    usable data — never a replacement, never tried when EDGAR already
    succeeded."""

    def test_edgar_success_never_calls_esef(self, db):
        instrument = Instrument(broker_symbol="AAPL.US", category="STOCK", country="US")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.UPDATED
        assert outcome.params["provider"] == "edgar"
        assert esef.calls == []

    def test_edgar_symbol_not_found_falls_through_to_esef(self, db):
        instrument = Instrument(broker_symbol="AI.FR", category="STOCK", country="FR", name="Air Liquide")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(error=SymbolNotFound("no match"))
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.UPDATED
        assert outcome.params["provider"] == "esef"
        assert esef.calls == ["Air Liquide"]

    def test_edgar_found_the_company_but_nothing_usable_still_tries_esef(self, db):
        """Real, documented case (Decision 3a.1): Air Liquide and Sanofi are
        found in the SEC index but file no usable XBRL there."""
        instrument = Instrument(broker_symbol="AI.FR", category="STOCK", country="FR", name="Air Liquide")
        db.add(instrument)
        db.flush()
        empty = Fundamentals(cik="0001234567", company_name="Air Liquide SA", concepts={})
        edgar = FakeEdgarProvider(fundamentals=empty)
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.UPDATED
        assert outcome.params["provider"] == "esef"

    def test_edgar_disabled_still_tries_esef(self, db):
        instrument = Instrument(broker_symbol="AI.FR", category="STOCK", country="FR", name="Air Liquide")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(enabled=False)
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.UPDATED
        assert outcome.params["provider"] == "esef"
        assert edgar.calls == []

    def test_edgar_rate_limited_still_tries_esef_and_uses_it_on_success(self, db):
        instrument = Instrument(broker_symbol="XYZ.FR", category="STOCK", country="FR", name="Xyz")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(error=RateLimited("throttled"))
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.UPDATED
        assert outcome.params["provider"] == "esef"

    def test_both_sources_failing_reports_symbol_not_found(self, db):
        instrument = Instrument(broker_symbol="XYZ.FR", category="STOCK", country="FR", name="Xyz")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(error=SymbolNotFound("no match"))
        esef = FakeEsefProvider(error=SymbolNotFound("no match"))

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.SYMBOL_NOT_FOUND

    def test_edgar_rate_limited_and_esef_also_failing_reports_edgars_rate_limit(self, db):
        """A real failure signal from the first source is more informative
        than the second source's generic "not found" once both are tried."""
        instrument = Instrument(broker_symbol="XYZ.FR", category="STOCK", country="FR", name="Xyz")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(error=RateLimited("throttled"))
        esef = FakeEsefProvider(error=SymbolNotFound("no match"))

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.RATE_LIMITED

    def test_no_instrument_name_skips_esef_entirely(self, db):
        instrument = Instrument(broker_symbol="XYZ.US", category="STOCK", country="US", name=None)
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(error=SymbolNotFound("no match"))
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.SYMBOL_NOT_FOUND
        assert esef.calls == []

    def test_edgar_disabled_and_no_name_reports_no_provider(self, db):
        """Distinct from SYMBOL_NOT_FOUND: neither source was even asked."""
        instrument = Instrument(broker_symbol="XYZ.US", category="STOCK", country="US", name=None)
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(enabled=False)
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        outcome = fetch_one(db, instrument, edgar, esef, force=False)

        assert outcome.code == FundamentalsOutcome.NO_PROVIDER
        assert esef.calls == []


class TestOutcomeMapping:
    def test_symbol_not_found_maps_to_its_own_outcome(self, db):
        instrument = Instrument(broker_symbol="XYZ.US", category="STOCK", country="US")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(error=SymbolNotFound("not found"))

        outcome = fetch_one(db, instrument, edgar, _no_esef(), force=False)

        assert outcome.code == FundamentalsOutcome.SYMBOL_NOT_FOUND

    def test_provider_unavailable_maps_to_failed(self, db):
        instrument = Instrument(broker_symbol="XYZ.US", category="STOCK", country="US")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(error=ProviderUnavailable("network error"))

        outcome = fetch_one(db, instrument, edgar, _no_esef(), force=False)

        assert outcome.code == FundamentalsOutcome.FAILED
        assert outcome.params["error"] == "network error"


class TestCachingAndUpsert:
    def test_success_persists_fundamental_rows(self, db):
        instrument = Instrument(broker_symbol="AAPL.US", category="STOCK", country="US")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())

        outcome = fetch_one(db, instrument, edgar, _no_esef(), force=False)

        assert outcome.code == FundamentalsOutcome.UPDATED
        assert outcome.params["concepts"] == 2
        rows = list(db.execute(select(Fundamental).where(Fundamental.instrument_id == instrument.id)).scalars())
        assert {r.concept for r in rows} == {"net_income", "revenue"}
        assert all(r.currency == "USD" for r in rows)
        assert all(r.provider == "edgar" for r in rows)

    def test_esef_rows_are_tagged_with_their_own_provider(self, db):
        instrument = Instrument(broker_symbol="AI.FR", category="STOCK", country="FR", name="Air Liquide")
        db.add(instrument)
        db.flush()
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        fetch_one(db, instrument, _no_edgar(), esef, force=False)

        rows = list(db.execute(select(Fundamental).where(Fundamental.instrument_id == instrument.id)).scalars())
        assert rows
        assert all(r.provider == "esef" for r in rows)
        assert all(r.currency == "EUR" for r in rows)

    def test_already_fetched_today_is_skipped_without_a_call(self, db):
        instrument = Instrument(broker_symbol="AAPL.US", category="STOCK", country="US")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())
        fetch_one(db, instrument, edgar, _no_esef(), force=False)

        outcome = fetch_one(db, instrument, edgar, _no_esef(), force=False)

        assert outcome.code == FundamentalsOutcome.ALREADY_FRESH
        assert len(edgar.calls) == 1

    def test_force_refetches_even_when_already_fresh(self, db):
        instrument = Instrument(broker_symbol="AAPL.US", category="STOCK", country="US")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())
        fetch_one(db, instrument, edgar, _no_esef(), force=False)

        outcome = fetch_one(db, instrument, edgar, _no_esef(), force=True)

        assert outcome.code == FundamentalsOutcome.UPDATED
        assert len(edgar.calls) == 2

    def test_a_second_run_updates_in_place_without_duplicating_rows(self, db):
        instrument = Instrument(broker_symbol="AAPL.US", category="STOCK", country="US")
        db.add(instrument)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())
        fetch_one(db, instrument, edgar, _no_esef(), force=False)

        revised = Fundamentals(
            cik="0000320193",
            company_name="Apple Inc.",
            concepts={
                "net_income": [AnnualFigure(2023, date(2023, 9, 30), 1050.0, "NetIncomeLoss", "USD")],
                "revenue": [AnnualFigure(2023, date(2023, 9, 30), 5000.0, "Revenues", "USD")],
            },
        )
        edgar2 = FakeEdgarProvider(fundamentals=revised)
        fetch_one(db, instrument, edgar2, _no_esef(), force=True)

        rows = list(
            db.execute(
                select(Fundamental).where(
                    Fundamental.instrument_id == instrument.id, Fundamental.concept == "net_income"
                )
            ).scalars()
        )
        assert len(rows) == 1
        assert rows[0].value == 1050.0


class TestBatchReport:
    def test_report_buckets_each_outcome_correctly(self, db):
        stock = Instrument(broker_symbol="AAPL.US", category="STOCK", country="US")
        etf = Instrument(broker_symbol="SPY.US", category="ETF", country="US")
        db.add_all([stock, etf])
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        report = fetch_fundamentals(db, [stock, etf], edgar, esef, force=False)

        assert report.updated == 1
        assert report.not_applicable == 1
        assert report.skipped == 0
        assert report.failed == 0
        assert len(report.outcomes) == 2


class TestProgress:
    """Live progress tracking, same shape as `prices/service.py::RefreshProgress`
    — see DEVLOG "Decision 3u.9"."""

    def test_advances_during_the_run_and_settles_after(self, db):
        stock1 = Instrument(broker_symbol="AAPL.US", category="STOCK", country="US")
        stock2 = Instrument(broker_symbol="MSFT.US", category="STOCK", country="US")
        db.add_all([stock1, stock2])
        db.flush()
        edgar = ProgressCapturingEdgarProvider(fundamentals=_fundamentals())
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        report = fetch_fundamentals(db, [stock1, stock2], edgar, esef, force=False)

        assert len(edgar.snapshots) == 2
        # Snapshot taken *during* the first instrument's fetch: nothing has
        # been recorded as done yet, but the run is already marked running.
        assert edgar.snapshots[0].running is True
        assert edgar.snapshots[0].total == 2
        assert edgar.snapshots[0].done == 0
        # Snapshot taken during the second instrument's fetch: the first has
        # advanced by then.
        assert edgar.snapshots[1].done == 1
        assert edgar.snapshots[1].current_symbol == "AAPL.US"

        final = get_fundamentals_progress()
        assert final.running is False
        assert final.total == 2
        assert final.done == 2
        assert final.finished_at is not None
        assert final.report is report
        assert final.report.updated == 2

    def test_no_instruments_still_settles_to_a_clean_idle_state(self, db):
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        fetch_fundamentals(db, [], edgar, esef, force=False)

        final = get_fundamentals_progress()
        assert final.running is False
        assert final.total == 0
        assert final.done == 0


class TestConcurrency:
    """Two fundamentals refreshes at once would double the EDGAR/ESEF request
    spend for no benefit -- same reasoning as `prices/service.py`'s
    `_refresh_lock`."""

    def test_second_concurrent_run_is_refused(self, db):
        from app.fundamentals import service

        stock = Instrument(broker_symbol="AAPL.US", category="STOCK", country="US")
        db.add(stock)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        service._fundamentals_lock.acquire()
        try:
            report = fetch_fundamentals(db, [stock], edgar, esef, force=False)
        finally:
            service._fundamentals_lock.release()

        assert report.outcomes[0].code == FundamentalsOutcome.ALREADY_RUNNING
        assert edgar.calls == []

    def test_the_lock_is_released_afterwards(self, db):
        from app.fundamentals import service

        stock = Instrument(broker_symbol="AAPL.US", category="STOCK", country="US")
        db.add(stock)
        db.flush()
        edgar = FakeEdgarProvider(fundamentals=_fundamentals())
        esef = FakeEsefProvider(fundamentals=_esef_fundamentals())

        fetch_fundamentals(db, [stock], edgar, esef, force=False)

        assert service._fundamentals_lock.acquire(blocking=False)
        service._fundamentals_lock.release()
