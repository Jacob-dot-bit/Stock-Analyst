"""Tests for reconstructing real historical portfolio value from the Lot ledger."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base
from app.models import CorporateAction, CorporateActionType, FxRate, Instrument, Lot, LotType, PriceBar, Source
from app.prices import history_service
from app.prices.history_service import compute_value_history


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def _instrument(db, symbol="AAPL.US", currency="EUR", category="STOCK") -> Instrument:
    instrument = Instrument(broker_symbol=symbol, currency=currency, category=category)
    db.add(instrument)
    db.flush()
    return instrument


class TestComputeValueHistory:
    def test_no_lots_returns_empty(self, db):
        result = compute_value_history(db, "EUR", date(2026, 1, 10))
        assert result.points == []
        assert result.start_date is None
        assert result.capped_by_history is False

    def test_single_never_sold_lot_same_currency(self, db):
        instrument = _instrument(db)
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                lot_type=LotType.OPEN,
                quantity=2,
                open_price=100.0,
                opened_at=datetime(2026, 1, 5),
                currency="EUR",
            )
        )
        db.add(PriceBar(instrument_id=instrument.id, bar_date=date(2026, 1, 5), close=110.0))
        db.add(PriceBar(instrument_id=instrument.id, bar_date=date(2026, 1, 7), close=120.0))
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 8))

        by_day = {p.day: p for p in result.points}
        # Before the lot opened: not held at all yet.
        assert date(2026, 1, 4) not in by_day
        assert result.start_date == date(2026, 1, 5)
        # Opening day: priced.
        assert by_day[date(2026, 1, 5)].value == pytest.approx(220.0)
        assert by_day[date(2026, 1, 5)].invested == pytest.approx(200.0)
        # Gap day (no new bar): forward-fills the last known close.
        assert by_day[date(2026, 1, 6)].value == pytest.approx(220.0)
        # New bar lands: value updates, invested (cost basis) never moves.
        assert by_day[date(2026, 1, 7)].value == pytest.approx(240.0)
        assert by_day[date(2026, 1, 7)].invested == pytest.approx(200.0)
        # No bar cached this far yet — still forward-filled from 01-07, not the
        # earlier 01-05 price.
        assert by_day[date(2026, 1, 8)].value == pytest.approx(240.0)

    def test_no_price_data_yields_none_not_zero(self, db):
        instrument = _instrument(db)
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                lot_type=LotType.OPEN,
                quantity=1,
                open_price=50.0,
                opened_at=datetime(2026, 1, 1),
                currency="EUR",
            )
        )
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 3))

        for point in result.points:
            assert point.value is None  # never a guessed/zero value
            assert point.invested == pytest.approx(50.0)  # cost basis needs no price

    def test_closed_lot_drops_out_after_close_date(self, db):
        instrument = _instrument(db)
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                lot_type=LotType.CLOSED,
                quantity=3,
                open_price=10.0,
                opened_at=datetime(2026, 1, 1),
                close_price=12.0,
                closed_at=datetime(2026, 1, 3),
                currency="EUR",
            )
        )
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 5))
        by_day = {p.day: p for p in result.points}

        # Held (though unpriced, no PriceBar in this test) from open through the
        # day before it closed...
        assert by_day[date(2026, 1, 1)].invested == pytest.approx(30.0)
        assert by_day[date(2026, 1, 2)].invested == pytest.approx(30.0)
        # ...gone entirely from the close date onward — a true zero, not missing
        # data, since nothing is held anymore.
        assert by_day[date(2026, 1, 3)].value == 0.0
        assert by_day[date(2026, 1, 3)].invested == 0.0
        assert by_day[date(2026, 1, 5)].value == 0.0

    def test_cfd_is_excluded(self, db):
        cfd = _instrument(db, symbol="US500.CFD", category="CFD")
        db.add(
            Lot(
                instrument_id=cfd.id,
                source=Source.IMPORT,
                lot_type=LotType.OPEN,
                quantity=1,
                open_price=5000.0,
                opened_at=datetime(2026, 1, 1),
                currency="EUR",
            )
        )
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 3))
        assert result.points == []  # the only lot is a CFD, so nothing to replay

    def test_manual_position_lot_is_included(self, db):
        instrument = _instrument(db)
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.MANUAL,
                lot_type=LotType.OPEN,
                quantity=1,
                open_price=42.0,
                opened_at=datetime(2026, 1, 1),
                currency="EUR",
            )
        )
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 2))
        assert result.points[0].invested == pytest.approx(42.0)

    def test_capped_by_history_flag(self, db):
        instrument = _instrument(db)
        very_old = datetime(2020, 1, 1)
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                lot_type=LotType.OPEN,
                quantity=1,
                open_price=10.0,
                opened_at=very_old,
                currency="EUR",
            )
        )
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 1))
        assert result.capped_by_history is True
        assert result.start_date is not None
        assert result.start_date > very_old.date()


def _enable_benchmark(monkeypatch, broker_symbol="SPY.US", provider_symbol="SPY", name="S&P 500 (SPY)"):
    """The autouse `isolate_credentials` fixture (conftest.py) disables the
    benchmark for every test by default — pre-existing price-refresh tests
    were written before it existed and would otherwise see one extra
    instrument in their counts. Bypasses the `get_settings()` cache entirely
    (a fresh `Settings(...)` instance) rather than juggling env vars + cache
    clears, so there is no risk of leaking into another test's cached state.
    """
    monkeypatch.setattr(
        history_service,
        "get_settings",
        lambda: Settings(
            benchmark_broker_symbol=broker_symbol,
            benchmark_provider_symbol=provider_symbol,
            benchmark_name=name,
        ),
    )


class TestBenchmarkOverlay:
    """"If the same cash had bought the benchmark instead, on the same days" —
    see DEVLOG "Decision 3e.1"."""

    def test_no_benchmark_configured_leaves_it_out_entirely(self, db):
        instrument = _instrument(db)
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                lot_type=LotType.OPEN,
                quantity=1,
                open_price=10.0,
                opened_at=datetime(2026, 1, 1),
                currency="EUR",
            )
        )
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 2))
        assert result.benchmark_available is False
        assert all(p.benchmark is None for p in result.points)

    def test_shadow_quantity_same_currency(self, db, monkeypatch):
        _enable_benchmark(monkeypatch)
        instrument = _instrument(db, symbol="AAPL.US")
        benchmark = _instrument(db, symbol="SPY.US")
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                lot_type=LotType.OPEN,
                quantity=2,
                open_price=100.0,
                opened_at=datetime(2026, 1, 1),
                currency="EUR",
            )
        )
        db.add(PriceBar(instrument_id=benchmark.id, bar_date=date(2026, 1, 1), close=50.0))
        db.add(PriceBar(instrument_id=benchmark.id, bar_date=date(2026, 1, 2), close=60.0))
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 2))
        assert result.benchmark_available is True
        by_day = {p.day: p for p in result.points}

        # Shadow quantity = lot cost (200) / benchmark price on the lot's real
        # open day (50) = 4 units — so on that same day, the shadow value
        # exactly equals what was actually spent.
        assert by_day[date(2026, 1, 1)].benchmark == pytest.approx(200.0)
        # A new benchmark close lands the next day: 4 units × 60.
        assert by_day[date(2026, 1, 2)].benchmark == pytest.approx(240.0)

    def test_shadow_quantity_cross_currency(self, db, monkeypatch):
        """The lot is in USD, the benchmark in EUR (= base) — exercises the
        lot-side FX leg specifically."""
        _enable_benchmark(monkeypatch)
        instrument = _instrument(db, symbol="AAPL.US", currency="USD")
        benchmark = _instrument(db, symbol="SPY.US", currency="EUR")
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                lot_type=LotType.OPEN,
                quantity=1,
                open_price=100.0,
                opened_at=datetime(2026, 1, 1),
                currency="USD",
            )
        )
        db.add(FxRate(currency="USD", base_currency="EUR", rate_date=date(2026, 1, 1), rate=0.9))
        db.add(PriceBar(instrument_id=benchmark.id, bar_date=date(2026, 1, 1), close=50.0))
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 1))

        # Cost in EUR: 1 × 100 USD × 0.9 = 90. Benchmark price is already EUR
        # (= base), no conversion needed there. Shadow qty = 90 / 50 = 1.8,
        # priced back at 50 → 90: the shadow value on its own open day always
        # equals the real cost that funded it, in any currency combination.
        assert result.points[0].benchmark == pytest.approx(90.0)

    def test_benchmark_configured_but_unpriced_stays_null_not_zero(self, db, monkeypatch):
        """A benchmark instrument that exists but has no cached price at all
        must not silently read as a 0 — `benchmark_available` says a
        benchmark exists; each point's own `benchmark` says whether that
        specific day could actually be priced."""
        _enable_benchmark(monkeypatch)
        instrument = _instrument(db)
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                lot_type=LotType.OPEN,
                quantity=1,
                open_price=10.0,
                opened_at=datetime(2026, 1, 1),
                currency="EUR",
            )
        )
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 2))
        assert result.benchmark_available is True
        assert all(p.benchmark is None for p in result.points)


class TestSplitAdjustment:
    """The worked example from DEVLOG "Decision 3u.30": 2 shares bought at
    1000 becoming 20 at 100 after a 10-for-1 split — the replay must show a
    flat, continuous value across the split, not a fake 90% cliff (or, if
    the wiring were backwards, a fake 10x jump)."""

    def test_value_stays_continuous_across_a_confirmed_split(self, db):
        instrument = _instrument(db)
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                lot_type=LotType.OPEN,
                quantity=2,
                open_price=1000.0,
                opened_at=datetime(2026, 1, 1),
                currency="EUR",
            )
        )
        # Raw, unadjusted price history: 1000 pre-split, 100 post-split — a
        # real ~10x-scale jump that a naive reading would take as a genuine
        # price move.
        db.add(PriceBar(instrument_id=instrument.id, bar_date=date(2026, 1, 1), close=1000.0))
        db.add(PriceBar(instrument_id=instrument.id, bar_date=date(2026, 1, 3), close=100.0))
        db.add(
            CorporateAction(
                instrument_id=instrument.id,
                action_type=CorporateActionType.SPLIT,
                effective_date=date(2026, 1, 3),
                ratio_numerator=10,
                ratio_denominator=1,
                source="manual",
                price_history_status="raw",
            )
        )
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 3))

        by_day = {p.day: p for p in result.points}
        # Same economic value both sides of the split — no artificial 10x
        # jump on the split date, no fake 90% collapse either.
        assert by_day[date(2026, 1, 1)].value == pytest.approx(2000.0)
        assert by_day[date(2026, 1, 3)].value == pytest.approx(2000.0)
        # Cost basis (total money invested) is split-invariant by construction.
        assert by_day[date(2026, 1, 1)].invested == pytest.approx(2000.0)
        assert by_day[date(2026, 1, 3)].invested == pytest.approx(2000.0)

    def test_already_adjusted_status_is_never_corrected_again(self, db):
        """The double-adjustment this status exists to prevent: a provider
        that already restated its history must not be scaled a second time."""
        instrument = _instrument(db)
        db.add(
            Lot(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                lot_type=LotType.OPEN,
                quantity=1,
                open_price=130.0,
                opened_at=datetime(2026, 1, 1),
                currency="EUR",
            )
        )
        # Already split-adjusted by the provider: no discontinuity at all.
        db.add(PriceBar(instrument_id=instrument.id, bar_date=date(2026, 1, 1), close=130.0))
        db.add(PriceBar(instrument_id=instrument.id, bar_date=date(2026, 1, 3), close=131.0))
        db.add(
            CorporateAction(
                instrument_id=instrument.id,
                action_type=CorporateActionType.SPLIT,
                effective_date=date(2026, 1, 3),
                ratio_numerator=10,
                ratio_denominator=1,
                source="manual",
                price_history_status="already_adjusted",
            )
        )
        db.commit()

        result = compute_value_history(db, "EUR", date(2026, 1, 3))

        by_day = {p.day: p for p in result.points}
        # quantity IS restated (a real share count change), but price is left
        # exactly as the provider gave it — no 10x correction on top.
        assert by_day[date(2026, 1, 1)].value == pytest.approx(10 * 130.0)
        assert by_day[date(2026, 1, 3)].value == pytest.approx(10 * 131.0)
