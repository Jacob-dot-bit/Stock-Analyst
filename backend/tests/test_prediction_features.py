"""Tests for the price-only feature/label computation — phase 2 of a real,
backtestable Discovery prediction. See `app/prediction/features.py`'s
module docstring for why every feature here must be computable strictly
from bars at-or-before `as_of` (DEVLOG "Decision 3u.23").
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import CorporateAction, CorporateActionType, PriceBar
from app.prediction.features import (
    MAX_LOOKBACK_DAYS,
    _closes_by_date,
    build_feature_rows,
    compute_features,
    forward_return,
)


def _bars(closes: list[float], start: date | None = None) -> list[PriceBar]:
    start = start or date(2020, 1, 1)
    return [
        PriceBar(instrument_id=1, bar_date=start + timedelta(days=i), open=c, high=c, low=c, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


class TestComputeFeatures:
    def test_returns_none_without_enough_lookback_history(self):
        closes = [100.0] * (MAX_LOOKBACK_DAYS - 1)
        bars = _bars(closes)
        dates = [b.bar_date for b in bars]

        result = compute_features(bars, MAX_LOOKBACK_DAYS - 2, dates, closes)

        assert result is None

    def test_momentum_reflects_the_real_price_change(self):
        # Flat until the lookback window, then a known 10% jump right at
        # the evaluation point — momentum_20 must show exactly that jump,
        # not something derived from data that didn't exist yet.
        closes = [100.0] * (MAX_LOOKBACK_DAYS + 1)
        closes[-1] = 110.0
        bars = _bars(closes)
        dates = [b.bar_date for b in bars]
        as_of_index = len(closes) - 1

        result = compute_features(bars, as_of_index, dates, closes)

        assert result is not None
        assert result.momentum_20 == pytest.approx(0.10)

    def test_sma_ratio_is_zero_when_price_equals_its_own_average(self):
        closes = [100.0] * (MAX_LOOKBACK_DAYS + 1)
        bars = _bars(closes)
        dates = [b.bar_date for b in bars]

        result = compute_features(bars, len(closes) - 1, dates, closes)

        assert result is not None
        assert result.sma50_ratio == pytest.approx(0.0)
        assert result.sma200_ratio == pytest.approx(0.0)

    def test_volatility_is_zero_for_a_perfectly_flat_price(self):
        closes = [100.0] * (MAX_LOOKBACK_DAYS + 1)
        bars = _bars(closes)
        dates = [b.bar_date for b in bars]

        result = compute_features(bars, len(closes) - 1, dates, closes)

        assert result is not None
        assert result.volatility_20 == pytest.approx(0.0)


class TestForwardReturn:
    def test_computes_the_realized_return_to_the_horizon(self):
        closes = [100.0, 100.0, 110.0]  # index 0 -> index 2, horizon 2

        result = forward_return(0, closes, horizon_days=2)

        assert result == pytest.approx(0.10)

    def test_none_when_the_horizon_extends_past_available_bars(self):
        closes = [100.0, 100.0]

        result = forward_return(0, closes, horizon_days=5)

        assert result is None


class TestBuildFeatureRows:
    def test_produces_no_rows_without_enough_history_for_lookback_and_horizon(self):
        closes = [100.0] * 10
        bars = _bars(closes)

        rows = build_feature_rows(instrument_id=42, bars=bars)

        assert rows == []

    def test_every_row_carries_the_given_instrument_id(self):
        # Enough bars for at least one lookback+horizon-complete sample.
        closes = [100.0 + i * 0.1 for i in range(MAX_LOOKBACK_DAYS + 61)]
        bars = _bars(closes)

        rows = build_feature_rows(instrument_id=7, bars=bars)

        assert len(rows) > 0
        assert all(row.instrument_id == 7 for row in rows)
        assert all(row.forward_return is not None for row in rows)


class TestClosesByDateWithSplit:
    def test_split_adjusted_closes_have_no_discontinuity(self):
        bars = [
            PriceBar(instrument_id=1, bar_date=date(2022, 4, 11), close=2.0),
            PriceBar(instrument_id=1, bar_date=date(2022, 4, 12), close=2.0),
            PriceBar(instrument_id=1, bar_date=date(2022, 4, 13), close=12.0),  # raw 6x jump
        ]
        action = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.REVERSE_SPLIT,
            effective_date=date(2022, 4, 13), ratio_numerator=1, ratio_denominator=6,
            price_history_status="raw",
        )

        _, raw_closes = _closes_by_date(bars)
        _, adjusted_closes = _closes_by_date(bars, [action])

        assert raw_closes == [2.0, 2.0, 12.0]
        assert adjusted_closes == pytest.approx([12.0, 12.0, 12.0])

    def test_momentum_feature_is_not_fabricated_by_an_unadjusted_split(self):
        """A momentum window straddling an unadjusted split would otherwise
        read as an impossible spike — build a series where the only thing
        that changes between the adjusted and unadjusted run is the split."""
        n = MAX_LOOKBACK_DAYS + 5
        flat_closes = [10.0] * n
        bars = _bars(flat_closes)
        split_day = bars[-1].bar_date
        # Overwrite the raw series' tail with an unadjusted-looking jump.
        raw_with_jump = _bars(flat_closes[:-1] + [60.0])
        action = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.REVERSE_SPLIT,
            effective_date=split_day, ratio_numerator=1, ratio_denominator=6,
            price_history_status="raw",
        )

        dates, adjusted_closes = _closes_by_date(raw_with_jump, [action])
        features = compute_features(raw_with_jump, len(adjusted_closes) - 1, dates, adjusted_closes)

        assert features is not None
        assert features.momentum_20 == pytest.approx(0.0, abs=1e-9)
