"""Tests for pillar/composite renormalization — the "missing data is dropped,
not guessed" rule (DEVLOG "Decision 1.2") applied at both the metric level
(covered in test_scoring_metrics.py) and, here, the pillar/composite level.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import CorporateAction, CorporateActionType, Fundamental, Instrument, Lot, LotType, PriceBar, Source, Transaction, TxType
from app.scoring import metrics
from app.scoring.config import get_scoring_config
from app.scoring.service import _annual_dividend_per_share, _load_closes, _shares_held_on, compute_scores


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture
def config():
    return get_scoring_config()


def _closes(db, instrument_id, n, start=100.0, step=0.0):
    base_date = date(2024, 1, 1)
    for i in range(n):
        db.add(
            PriceBar(
                instrument_id=instrument_id,
                bar_date=base_date + timedelta(days=i),
                close=start + i * step,
                provider="test",
            )
        )


class TestPillarDropsWhenNoData:
    def test_etf_with_no_fundamentals_scores_on_technical_alone(self, db, config):
        etf = Instrument(broker_symbol="SPY.US", category="ETF", currency="USD", country="US")
        db.add(etf)
        db.flush()
        _closes(db, etf.id, 260, start=400.0, step=0.1)
        db.commit()

        scores = compute_scores(db, [etf], config)
        assert len(scores) == 1
        score = scores[0]

        by_name = {p.name: p for p in score.pillars}
        assert by_name["value"].score is None
        assert by_name["value"].weight_used == 0.0
        assert by_name["growth"].score is None
        assert by_name["quality"].score is None
        assert by_name["technical"].score is not None
        assert by_name["technical"].weight_used == 100.0
        assert score.composite == by_name["technical"].score

    def test_cfd_never_appears_in_the_results(self, db, config):
        cfd = Instrument(broker_symbol="BITCOIN", category="CFD", currency="USD", country="US")
        db.add(cfd)
        db.flush()
        _closes(db, cfd.id, 260, start=50000.0, step=1.0)
        db.commit()

        scores = compute_scores(db, [cfd], config)
        assert scores == []

    def test_stock_with_no_price_history_drops_technical_but_keeps_fundamentals(self, db, config):
        stock = Instrument(broker_symbol="AAPL.US", category="STOCK", currency="USD", country="US")
        db.add(stock)
        db.flush()
        figures = [
            ("net_income", 2023, 900.0), ("net_income", 2024, 1000.0),
            ("shares_diluted", 2023, 100.0), ("shares_diluted", 2024, 100.0),
            ("equity", 2023, 2000.0), ("equity", 2024, 2100.0),
            ("assets", 2023, 5000.0), ("assets", 2024, 5100.0),
            ("operating_cash_flow", 2023, 1100.0), ("operating_cash_flow", 2024, 1200.0),
            ("debt_long_term", 2023, 800.0), ("debt_long_term", 2024, 700.0),
        ]
        for concept, fy, value in figures:
            db.add(
                Fundamental(
                    instrument_id=stock.id, concept=concept, fiscal_year=fy,
                    period_end=date(fy, 12, 31), value=value, currency="USD", tag="x",
                )
            )
        db.commit()
        # No PriceBar rows at all: no current price -> Value's price-based
        # metrics drop too (pe/pb/fcf), but debt_to_equity needs no price.

        scores = compute_scores(db, [stock], config)
        score = scores[0]
        by_name = {p.name: p for p in score.pillars}

        assert by_name["technical"].score is None
        assert by_name["technical"].weight_used == 0.0
        # debt_to_equity alone should have survived Value (no price needed).
        value_metrics = {m.name: m for m in by_name["value"].metrics}
        assert value_metrics["debt_to_equity"].score is not None
        assert value_metrics["pe_ratio"].score is None
        assert by_name["value"].score is not None
        assert score.composite is not None


class TestFullyResolvedInstrument:
    def test_a_fully_covered_stock_scores_every_pillar(self, db, config):
        stock = Instrument(broker_symbol="AAPL.US", category="STOCK", currency="USD", country="US")
        db.add(stock)
        db.flush()
        figures = [
            ("net_income", 2021, 700.0), ("net_income", 2022, 800.0),
            ("net_income", 2023, 900.0), ("net_income", 2024, 1000.0),
            ("shares_diluted", 2023, 100.0), ("shares_diluted", 2024, 100.0),
            ("equity", 2023, 2000.0), ("equity", 2024, 2100.0),
            ("revenue", 2021, 2000.0), ("revenue", 2022, 2200.0),
            ("revenue", 2023, 2400.0), ("revenue", 2024, 2700.0),
            ("assets", 2023, 5000.0), ("assets", 2024, 5100.0),
            ("operating_cash_flow", 2023, 1100.0), ("operating_cash_flow", 2024, 1200.0),
            ("capex", 2024, 150.0),
            ("debt_long_term", 2023, 800.0), ("debt_long_term", 2024, 700.0),
        ]
        for concept, fy, value in figures:
            db.add(
                Fundamental(
                    instrument_id=stock.id, concept=concept, fiscal_year=fy,
                    period_end=date(fy, 12, 31), value=value, currency="USD", tag="x",
                )
            )
        _closes(db, stock.id, 260, start=100.0, step=0.2)
        db.commit()

        scores = compute_scores(db, [stock], config)
        score = scores[0]

        assert score.composite is not None
        total_weight_used = sum(p.weight_used for p in score.pillars)
        assert total_weight_used == pytest.approx(100.0)
        for pillar in score.pillars:
            assert pillar.score is not None


def _lot(instrument_id, quantity, open_price, opened_at, closed_at=None):
    return Lot(
        instrument_id=instrument_id,
        source=Source.IMPORT,
        lot_type=LotType.CLOSED if closed_at else LotType.OPEN,
        quantity=quantity,
        open_price=open_price,
        opened_at=opened_at,
        closed_at=closed_at,
        currency="USD",
    )


def _dividend(instrument_id, amount, executed_at):
    return Transaction(instrument_id=instrument_id, type=TxType.DIVIDEND, amount=amount, executed_at=executed_at)


class TestSharesHeldOn:
    def test_lot_spanning_the_day_counts(self):
        lots = [_lot(1, 10, 100.0, datetime(2025, 1, 1))]
        assert _shares_held_on(lots, date(2025, 6, 1)) == 10

    def test_lot_opened_after_the_day_excluded(self):
        lots = [_lot(1, 10, 100.0, datetime(2025, 7, 1))]
        assert _shares_held_on(lots, date(2025, 6, 1)) == 0

    def test_lot_closed_before_the_day_excluded(self):
        lots = [_lot(1, 10, 100.0, datetime(2025, 1, 1), closed_at=datetime(2025, 3, 1))]
        assert _shares_held_on(lots, date(2025, 6, 1)) == 0

    def test_lot_closed_on_the_day_itself_excluded(self):
        # closed_at.date() > day is required — closing *on* the day means it's
        # no longer held as of that day.
        lots = [_lot(1, 10, 100.0, datetime(2025, 1, 1), closed_at=datetime(2025, 6, 1))]
        assert _shares_held_on(lots, date(2025, 6, 1)) == 0

    def test_multiple_lots_summed(self):
        lots = [
            _lot(1, 10, 100.0, datetime(2025, 1, 1)),
            _lot(1, 5, 110.0, datetime(2025, 4, 1)),
        ]
        assert _shares_held_on(lots, date(2025, 6, 1)) == 15


class TestAnnualDividendPerShare:
    def test_no_lot_history_at_all_is_dropped_not_guessed(self):
        # Never held (as far as this replay can tell) -- nothing to divide
        # a payment by, even if a stray dividend row somehow existed.
        assert _annual_dividend_per_share([], []) is None

    def test_no_dividends_is_a_real_zero_not_a_gap(self):
        assert _annual_dividend_per_share([], [_lot(1, 10, 100.0, datetime(2025, 1, 1))]) == 0.0

    def test_single_payment_divided_by_shares_held_that_day(self):
        lots = [_lot(1, 10, 100.0, datetime(2025, 1, 1))]
        dividends = [_dividend(1, 5.0, datetime(2025, 6, 1))]
        # $5 total / 10 shares held = $0.50/share.
        assert _annual_dividend_per_share(dividends, lots) == pytest.approx(0.5)

    def test_multiple_payments_at_different_share_counts_summed(self):
        lots = [
            _lot(1, 10, 100.0, datetime(2025, 1, 1)),
            _lot(1, 10, 100.0, datetime(2025, 4, 1)),  # doubles the position
        ]
        dividends = [
            _dividend(1, 5.0, datetime(2025, 2, 1)),  # 10 shares held -> 0.50/share
            _dividend(1, 8.0, datetime(2025, 5, 1)),  # 20 shares held -> 0.40/share
        ]
        assert _annual_dividend_per_share(dividends, lots) == pytest.approx(0.9)

    def test_payment_on_a_day_with_zero_shares_held_is_unattributable(self):
        # Position was fully closed before this dividend's date -- can't
        # reconstruct a per-share figure, so the whole result is dropped.
        lots = [_lot(1, 10, 100.0, datetime(2025, 1, 1), closed_at=datetime(2025, 3, 1))]
        dividends = [_dividend(1, 5.0, datetime(2025, 6, 1))]
        assert _annual_dividend_per_share(dividends, lots) is None


class TestDividendYieldEndToEnd:
    def test_dividend_paying_stock_scores_the_value_pillars_dividend_metric(self, db, config):
        now = datetime.now(UTC).replace(tzinfo=None)
        stock = Instrument(broker_symbol="MRVL.US", category="STOCK", currency="USD", country="US")
        db.add(stock)
        db.flush()
        db.add(_lot(stock.id, 100, 50.0, now - timedelta(days=200)))
        db.add(_dividend(stock.id, 6.0, now - timedelta(days=60)))  # 100 shares -> 0.06/share
        _closes(db, stock.id, 10, start=100.0, step=0.0)  # price = 100
        db.commit()

        scores = compute_scores(db, [stock], config)
        value_metrics = {m.name: m for m in scores[0].pillars[0].metrics}
        assert value_metrics["dividend_yield"].value == pytest.approx(0.0006)
        assert value_metrics["dividend_yield"].dropped_reason is None

    def test_non_payer_scores_a_real_zero_not_missing(self, db, config):
        now = datetime.now(UTC).replace(tzinfo=None)
        stock = Instrument(broker_symbol="GOOG.US", category="STOCK", currency="USD", country="US")
        db.add(stock)
        db.flush()
        db.add(_lot(stock.id, 10, 100.0, now - timedelta(days=200)))
        _closes(db, stock.id, 10, start=100.0, step=0.0)
        db.commit()

        scores = compute_scores(db, [stock], config)
        value_metrics = {m.name: m for m in scores[0].pillars[0].metrics}
        assert value_metrics["dividend_yield"].value == pytest.approx(0.0)
        assert value_metrics["dividend_yield"].score == 0.0
        assert value_metrics["dividend_yield"].dropped_reason is None

    def test_accumulating_etf_is_excluded_not_punished(self, db, config):
        # An ETF that never distributes (accumulating/swap-based, like the
        # real SPEA.FR/DCAM.FR holdings) has real lot history but zero
        # dividend transactions -- ever. dividend_yield must be dropped for
        # ETFs entirely (a fund's distribute-vs-accumulate choice isn't a
        # valuation signal), not scored as a punishing 0%.
        etf = Instrument(broker_symbol="SPEA.FR", category="ETF", currency="EUR", country="FR")
        db.add(etf)
        db.flush()
        opened_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=200)
        db.add(_lot(etf.id, 100, 5.0, opened_at))
        _closes(db, etf.id, 260, start=6.0, step=0.001)
        db.commit()

        scores = compute_scores(db, [etf], config)
        value_metrics = {m.name: m for m in scores[0].pillars[0].metrics}
        assert value_metrics["dividend_yield"].dropped_reason == metrics.DROP_MISSING_CONCEPT
        assert value_metrics["dividend_yield"].score is None


class TestSharesHeldOnWithSplit:
    def test_lot_opened_before_the_split_is_restated(self):
        """Same worked example as DEVLOG "Decision 3u.30": a lot recorded as
        2 raw shares reads as 20 once a confirmed 10-for-1 split applies."""
        action = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.SPLIT,
            effective_date=date(2025, 3, 1), ratio_numerator=10, ratio_denominator=1,
        )
        lots = [_lot(1, 2, 1000.0, datetime(2025, 1, 1))]
        assert _shares_held_on(lots, date(2025, 6, 1), [action]) == pytest.approx(20.0)

    def test_lot_opened_after_the_split_is_unaffected(self):
        action = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.SPLIT,
            effective_date=date(2025, 3, 1), ratio_numerator=10, ratio_denominator=1,
        )
        lots = [_lot(1, 2, 100.0, datetime(2025, 4, 1))]
        assert _shares_held_on(lots, date(2025, 6, 1), [action]) == pytest.approx(2.0)


class TestAnnualDividendPerShareWithSplit:
    def test_dividend_per_share_uses_the_restated_share_count(self):
        action = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.SPLIT,
            effective_date=date(2025, 3, 1), ratio_numerator=10, ratio_denominator=1,
        )
        lots = [_lot(1, 2, 1000.0, datetime(2025, 1, 1))]  # 2 raw shares -> 20 restated
        dividends = [_dividend(1, 20.0, datetime(2025, 6, 1))]
        # $20 / 20 restated shares = $1.00/share, not $20/2 = $10 (the wrong,
        # unadjusted answer).
        assert _annual_dividend_per_share(dividends, lots, [action]) == pytest.approx(1.0)


class TestLoadClosesWithSplit:
    def test_raw_close_series_is_split_adjusted(self, db):
        instrument = Instrument(broker_symbol="APLD.US", category="STOCK", currency="USD", country="US")
        db.add(instrument)
        db.flush()
        db.add(PriceBar(instrument_id=instrument.id, bar_date=date(2025, 1, 1), close=1000.0))
        db.add(PriceBar(instrument_id=instrument.id, bar_date=date(2025, 1, 2), close=100.0))
        action = CorporateAction(
            instrument_id=instrument.id, action_type=CorporateActionType.SPLIT,
            effective_date=date(2025, 1, 2), ratio_numerator=10, ratio_denominator=1,
            source="manual", price_history_status="raw",
        )
        db.add(action)
        db.commit()

        closes = _load_closes(db, [instrument.id], {instrument.id: [action]})

        # Both restated to the same post-split basis — no 10x jump.
        assert closes[instrument.id] == pytest.approx([100.0, 100.0])

    def test_no_actions_leaves_closes_untouched(self, db):
        instrument = Instrument(broker_symbol="AAPL.US", category="STOCK", currency="USD", country="US")
        db.add(instrument)
        db.flush()
        db.add(PriceBar(instrument_id=instrument.id, bar_date=date(2025, 1, 1), close=150.0))
        db.commit()

        closes = _load_closes(db, [instrument.id])

        assert closes[instrument.id] == [150.0]
