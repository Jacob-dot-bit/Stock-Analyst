"""Tests for the walk-forward-validated backtest — phase 2 of a real,
backtestable Discovery prediction. See `app/prediction/model.py`'s module
docstring for why the split must be strictly chronological, never random
(DEVLOG "Decision 3u.23").
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Instrument, PriceBar
from app.prediction.model import MIN_RELIABLE_TEST_SAMPLES, build_dataset, run_backtest


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


def _seed_instrument_with_bars(db, broker_symbol: str, closes: list[float]):
    instrument = Instrument(broker_symbol=broker_symbol, category="STOCK", currency="USD", country="US")
    db.add(instrument)
    db.commit()
    db.refresh(instrument)

    start = date(2020, 1, 1)
    db.add_all(
        [
            PriceBar(
                instrument_id=instrument.id,
                bar_date=start + timedelta(days=i),
                open=c,
                high=c,
                low=c,
                close=c,
                volume=100,
            )
            for i, c in enumerate(closes)
        ]
    )
    db.commit()
    return instrument


class TestBuildDataset:
    def test_pools_rows_across_every_priced_instrument(self, db):
        closes = [100.0 + i * 0.05 for i in range(400)]
        _seed_instrument_with_bars(db, "AAA.US", closes)
        _seed_instrument_with_bars(db, "BBB.US", closes)

        rows = build_dataset(db)

        instrument_ids = {row.instrument_id for row in rows}
        assert len(instrument_ids) == 2
        assert len(rows) > 0

    def test_empty_when_no_instrument_has_price_history(self, db):
        rows = build_dataset(db)

        assert rows == []


class TestRunBacktest:
    def test_reports_zero_and_a_low_sample_warning_with_too_little_data(self, db):
        _seed_instrument_with_bars(db, "AAA.US", [100.0] * 50)

        report = run_backtest(db)

        assert report.train_samples == 0
        assert report.test_samples == 0
        assert report.low_sample_warning is True

    def test_splits_strictly_by_date_not_randomly(self, db):
        # Oscillating (not monotonic) closes so both up and down labels
        # occur — a straight uptrend/downtrend has only one label class,
        # which is covered separately below.
        closes = [100.0 + ((i % 40) - 20) * 0.5 for i in range(500)]
        _seed_instrument_with_bars(db, "AAA.US", closes)
        _seed_instrument_with_bars(db, "BBB.US", closes)
        _seed_instrument_with_bars(db, "CCC.US", closes)

        report = run_backtest(db)

        assert report.train_samples > 0
        assert report.test_samples > 0
        # The whole point of a walk-forward split: every train row's date
        # must be no later than every test row's date.
        assert report.train_end <= report.test_start
        assert report.instruments_used == 3

    def test_accuracy_and_returns_are_present_when_the_split_succeeds(self, db):
        closes = [100.0 + ((i % 40) - 20) * 0.5 for i in range(500)]
        _seed_instrument_with_bars(db, "AAA.US", closes)
        _seed_instrument_with_bars(db, "BBB.US", closes)

        report = run_backtest(db)

        assert report.single_class_warning is False
        assert report.test_accuracy is not None
        assert 0.0 <= report.test_accuracy <= 1.0

    def test_single_class_training_period_reports_no_accuracy(self, db):
        closes = [100.0 * (1.001**i) for i in range(500)]  # pure, unbroken uptrend
        _seed_instrument_with_bars(db, "AAA.US", closes)
        _seed_instrument_with_bars(db, "BBB.US", closes)

        report = run_backtest(db)

        assert report.single_class_warning is True
        assert report.test_accuracy is None
        assert report.avg_return_predicted_up is None
        assert report.avg_return_predicted_down is None
        # The split itself still happened — dates/counts are real, only
        # the model-derived metrics are withheld.
        assert report.train_samples > 0
        assert report.test_samples > 0

    def test_low_sample_warning_reflects_the_threshold(self, db):
        closes = [100.0 + i * 0.05 for i in range(500)]
        _seed_instrument_with_bars(db, "AAA.US", closes)

        report = run_backtest(db)

        if report.test_samples < MIN_RELIABLE_TEST_SAMPLES:
            assert report.low_sample_warning is True
