"""Tests for `app/backtest/service.py` — point-in-time score backtest."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest import service as backtest_service
from app.backtest.service import _concepts_as_of, _forward_return, _HistoricalFx, run_backtest, user_universe_ids
from app.db import Base
from app.models import CorporateAction, Instrument, PriceBar, PriceHistoryStatus, ScreenerCandidate, WatchlistItem
from app.scoring.config import MetricConfig, PillarConfig, ScoringConfig

TODAY = date(2025, 1, 1)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


def _technical_config() -> ScoringConfig:
    """A one-metric config (12-1 momentum) so the backtest needs only closes,
    no fundamentals — the fastest path through the pipeline."""
    return ScoringConfig(
        version=1,
        pillars={
            "technical": PillarConfig(
                weight=1.0,
                metrics={
                    "momentum_12_1": MetricConfig(
                        weight=1.0, direction="higher_is_better", full_at=0.20, zero_at=-0.20
                    )
                },
            )
        },
    )


def _instrument(db, symbol: str) -> Instrument:
    inst = Instrument(broker_symbol=symbol, category="STOCK", currency="USD", country="US")
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _add_bars(db, instrument_id: int, n_days: int, daily_factor: float) -> None:
    """`n_days` consecutive daily closes ending TODAY, geometric trend."""
    for i in range(n_days):
        d = TODAY - timedelta(days=n_days - 1 - i)
        db.add(PriceBar(instrument_id=instrument_id, bar_date=d, close=100.0 * (daily_factor ** i)))
    db.commit()


class TestPointInTimeFiltering:
    def test_concepts_as_of_excludes_periods_after_cutoff(self):
        entries = {
            "net_income": [
                (date(2021, 12, 31), 2021, 100.0, "USD"),
                (date(2022, 12, 31), 2022, 120.0, "USD"),
                (date(2023, 12, 31), 2023, 140.0, "USD"),
            ]
        }
        # As of 2023-06-01 with a 120-day lag, only FY2021 and FY2022 are known
        # (FY2022's period ended 2022-12-31, +120d = 2023-04-30 < 2023-06-01).
        known = _concepts_as_of(entries, date(2023, 6, 1), lag_days=120)

        assert [a.fiscal_year for a in known["net_income"]] == [2021, 2022]

    def test_concepts_as_of_uses_filing_lag(self):
        entries = {"revenue": [(date(2022, 12, 31), 2022, 500.0, "USD")]}
        # On 2023-03-01 the FY2022 figure is NOT yet known with a 120-day lag.
        assert _concepts_as_of(entries, date(2023, 3, 1), lag_days=120) == {}
        # On 2023-05-01 it is.
        assert "revenue" in _concepts_as_of(entries, date(2023, 5, 1), lag_days=120)


class TestForwardReturn:
    def test_forward_return_math(self):
        closes = [
            (date(2024, 1, 2), 100.0),
            (date(2024, 2, 2), 110.0),
            (date(2024, 7, 2), 121.0),
        ]
        # From Jan 2 with a 1-month horizon: entry 100, exit 110 -> +10%.
        assert _forward_return(closes, date(2024, 1, 2), 1) == pytest.approx(0.10)

    def test_forward_return_none_when_horizon_runs_out(self):
        closes = [(date(2024, 1, 2), 100.0)]
        assert _forward_return(closes, date(2024, 1, 2), 12) is None


class TestRunBacktest:
    def test_quartiles_and_spread(self, db):
        # 6 steady up-trenders, 6 steady down-trenders, 3 years of daily bars.
        for i in range(6):
            up = _instrument(db, f"UP{i}.US")
            _add_bars(db, up.id, n_days=756, daily_factor=1.001)
            down = _instrument(db, f"DOWN{i}.US")
            _add_bars(db, down.id, n_days=756, daily_factor=0.999)

        result = run_backtest(
            db,
            _technical_config(),
            start=TODAY - timedelta(days=365),
            end=TODAY - timedelta(days=180),
            horizon_months=1,
            min_history_bars=300,
        )

        assert result.observations > 0
        assert len(result.buckets) == 4
        assert sum(b.count for b in result.buckets) == result.observations
        # Momentum sorts up-trenders into the top quartile, down-trenders into
        # the bottom, and the trends continue forward — so the spread is positive.
        assert result.top_minus_bottom is not None
        assert result.top_minus_bottom > 0
        assert result.buckets[3].mean_return > result.buckets[0].mean_return
        # Every ranked date has a positive spread, so the hit rate is 100%.
        assert result.periods
        assert all(p.scored == 12 for p in result.periods)
        assert result.hit_rate == pytest.approx(1.0)
        assert result.instruments_scored == 12

    def test_empty_universe_returns_no_periods(self, db):
        result = run_backtest(db, _technical_config(), start=date(2024, 1, 1), end=date(2024, 6, 1))

        assert result.observations == 0
        assert result.periods == []
        assert result.hit_rate is None


class TestSplitAdjustment:
    def test_raw_split_inside_horizon_is_not_a_crash(self, db):
        # 8 flat instruments; one has a RAW 10-for-1 split halfway through the
        # forward horizon (closes drop from 100 to 10). Split-adjusted, its
        # forward return is 0%, not -90%.
        instruments = [_instrument(db, f"FLAT{i}.US") for i in range(8)]
        split_day = TODAY - timedelta(days=200)
        for inst in instruments:
            for n in range(756):
                d = TODAY - timedelta(days=755 - n)
                close = 10.0 if (inst is instruments[0] and d >= split_day) else 100.0
                db.add(PriceBar(instrument_id=inst.id, bar_date=d, close=close))
        db.add(
            CorporateAction(
                instrument_id=instruments[0].id,
                action_type="split",
                effective_date=split_day,
                ratio_numerator=10,
                ratio_denominator=1,
                source="manual",
                price_history_status=PriceHistoryStatus.RAW,
            )
        )
        db.commit()

        result = run_backtest(
            db,
            _technical_config(),
            start=TODAY - timedelta(days=400),
            end=TODAY - timedelta(days=380),
            horizon_months=12,
            min_history_bars=300,
        )

        assert result.observations > 0
        for bucket in result.buckets:
            if bucket.count:
                assert bucket.mean_return == pytest.approx(0.0)


class TestHistoricalFx:
    def test_uses_the_rate_on_the_rebalance_date(self, db, monkeypatch):
        calls = []

        def fake_range(_db, from_currency, to_currency, start, end):
            calls.append((from_currency, to_currency))
            return {date(2023, 1, 2): 1.10, date(2024, 1, 2): 1.25}

        monkeypatch.setattr(backtest_service, "get_rate_range", fake_range)
        fx = _HistoricalFx(db, date(2023, 1, 1), date(2024, 12, 31))

        assert fx.rate("EUR", "USD", date(2023, 1, 2)) == pytest.approx(1.10)
        assert fx.rate("EUR", "USD", date(2024, 1, 2)) == pytest.approx(1.25)
        assert fx.rate("USD", "USD", date(2024, 1, 2)) == 1.0
        # One fetch per currency pair for the whole window.
        assert calls == [("EUR", "USD")]


class TestUserUniverse:
    def test_only_picked_instruments(self, db):
        watched = _instrument(db, "WATCH.US")
        screened = _instrument(db, "SCREEN.US")
        _instrument(db, "POOL.US")  # e.g. the automatic discovery pool
        db.add_all([WatchlistItem(instrument_id=watched.id), ScreenerCandidate(instrument_id=screened.id)])
        db.commit()

        assert user_universe_ids(db) == sorted([watched.id, screened.id])
