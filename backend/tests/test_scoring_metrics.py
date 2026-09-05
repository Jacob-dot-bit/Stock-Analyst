"""Tests for the individual scoring metric functions.

Hand-checked numbers throughout — a metric whose formula is subtly wrong
would still "look like a score," so every case here has an expected value
computed by hand, not just an assertion that *something* came back.
"""

from __future__ import annotations

import pytest

from app.scoring import metrics
from app.scoring.config import MetricConfig
from app.scoring.metrics import AnnualValue

LOWER_CFG = MetricConfig(weight=30, direction="lower_is_better", full_at=15, zero_at=30)
HIGHER_CFG = MetricConfig(weight=30, direction="higher_is_better", full_at=0.15, zero_at=0.0)


class TestScoreLinear:
    def test_higher_is_better_full_at_or_past(self):
        assert metrics.score_linear(0.20, HIGHER_CFG) == 100.0
        assert metrics.score_linear(0.15, HIGHER_CFG) == 100.0

    def test_higher_is_better_zero_at_or_below(self):
        assert metrics.score_linear(0.0, HIGHER_CFG) == 0.0
        assert metrics.score_linear(-0.05, HIGHER_CFG) == 0.0

    def test_higher_is_better_midpoint_is_fifty(self):
        assert metrics.score_linear(0.075, HIGHER_CFG) == pytest.approx(50.0)

    def test_lower_is_better_full_at_or_below(self):
        assert metrics.score_linear(15, LOWER_CFG) == 100.0
        assert metrics.score_linear(10, LOWER_CFG) == 100.0

    def test_lower_is_better_zero_at_or_past(self):
        assert metrics.score_linear(30, LOWER_CFG) == 0.0
        assert metrics.score_linear(40, LOWER_CFG) == 0.0

    def test_lower_is_better_midpoint_is_fifty(self):
        assert metrics.score_linear(22.5, LOWER_CFG) == pytest.approx(50.0)


class TestPeRatio:
    def test_exact_threshold_scores_full(self):
        # EPS = 1100/100 = 11, price 165 -> P/E = 15 exactly -> full score.
        concepts = {
            "net_income": [AnnualValue(2024, 1100.0, "USD")],
            "shares_diluted": [AnnualValue(2024, 100.0, "USD")],
        }
        result = metrics.pe_ratio(concepts, price=165.0, price_currency="USD", fx_rate=None, cfg=LOWER_CFG)
        assert result.value == pytest.approx(15.0)
        assert result.score == 100.0

    def test_negative_earnings_are_dropped_not_scored_favourably(self):
        concepts = {
            "net_income": [AnnualValue(2024, -50.0, "USD")],
            "shares_diluted": [AnnualValue(2024, 100.0, "USD")],
        }
        result = metrics.pe_ratio(concepts, price=10.0, price_currency="USD", fx_rate=None, cfg=LOWER_CFG)
        assert result.score is None
        assert result.dropped_reason == metrics.DROP_NON_POSITIVE_VALUE

    def test_missing_concept_is_dropped(self):
        result = metrics.pe_ratio({}, price=10.0, price_currency="USD", fx_rate=None, cfg=LOWER_CFG)
        assert result.dropped_reason == metrics.DROP_MISSING_CONCEPT

    def test_currency_mismatch_without_an_fx_rate_is_dropped(self):
        concepts = {
            "net_income": [AnnualValue(2024, 1100.0, "EUR")],
            "shares_diluted": [AnnualValue(2024, 100.0, "EUR")],
        }
        result = metrics.pe_ratio(concepts, price=165.0, price_currency="USD", fx_rate=None, cfg=LOWER_CFG)
        assert result.dropped_reason == metrics.DROP_MISSING_FX_RATE

    def test_currency_mismatch_converts_with_the_supplied_rate(self):
        # Price in USD, fundamentals in EUR, fx_rate USD->EUR = 0.9:
        # price_conv = 165 * 0.9 = 148.5, EPS = 11, P/E = 13.5.
        concepts = {
            "net_income": [AnnualValue(2024, 1100.0, "EUR")],
            "shares_diluted": [AnnualValue(2024, 100.0, "EUR")],
        }
        result = metrics.pe_ratio(concepts, price=165.0, price_currency="USD", fx_rate=0.9, cfg=LOWER_CFG)
        assert result.value == pytest.approx(13.5)


class TestDebtToEquity:
    def test_needs_no_fx_at_all(self):
        concepts = {
            "debt_long_term": [AnnualValue(2024, 500.0, "USD")],
            "equity": [AnnualValue(2024, 1000.0, "USD")],
        }
        result = metrics.debt_to_equity(concepts, LOWER_CFG)
        assert result.value == pytest.approx(0.5)

    def test_non_positive_equity_is_dropped(self):
        concepts = {
            "debt_long_term": [AnnualValue(2024, 500.0, "USD")],
            "equity": [AnnualValue(2024, -10.0, "USD")],
        }
        result = metrics.debt_to_equity(concepts, LOWER_CFG)
        assert result.dropped_reason == metrics.DROP_NON_POSITIVE_VALUE


class TestDividendYield:
    YIELD_CFG = MetricConfig(weight=15, direction="higher_is_better", full_at=0.04, zero_at=0.0)

    def test_known_yield(self):
        # 2.00 annual per-share / 100 price = 2%.
        result = metrics.dividend_yield(2.0, 100.0, self.YIELD_CFG)
        assert result.value == pytest.approx(0.02)
        assert result.score == pytest.approx(50.0)

    def test_zero_dividend_scores_zero_not_dropped(self):
        # A real non-payer: 0.0 (not None) still yields a genuine 0% score.
        result = metrics.dividend_yield(0.0, 100.0, self.YIELD_CFG)
        assert result.dropped_reason is None
        assert result.value == pytest.approx(0.0)
        assert result.score == 0.0

    def test_missing_replay_result_is_dropped(self):
        result = metrics.dividend_yield(None, 100.0, self.YIELD_CFG)
        assert result.dropped_reason == metrics.DROP_MISSING_CONCEPT

    def test_missing_price_is_dropped(self):
        result = metrics.dividend_yield(2.0, None, self.YIELD_CFG)
        assert result.dropped_reason == metrics.DROP_MISSING_CONCEPT

    def test_non_positive_price_is_dropped(self):
        result = metrics.dividend_yield(2.0, 0.0, self.YIELD_CFG)
        assert result.dropped_reason == metrics.DROP_MISSING_CONCEPT


class TestRevenueCagr:
    def test_known_cagr(self):
        # 100 -> 133.1 over 3 years = 10% CAGR exactly.
        series = [
            AnnualValue(2021, 100.0, "USD"),
            AnnualValue(2022, 110.0, "USD"),
            AnnualValue(2023, 121.0, "USD"),
            AnnualValue(2024, 133.1, "USD"),
        ]
        result = metrics.revenue_cagr({"revenue": series}, HIGHER_CFG)
        assert result.value == pytest.approx(0.10, abs=1e-6)

    def test_fewer_than_min_years_is_dropped(self):
        series = [AnnualValue(2023, 100.0, "USD"), AnnualValue(2024, 110.0, "USD")]
        cfg = MetricConfig(weight=30, direction="higher_is_better", full_at=0.15, zero_at=0.0, min_years=3)
        result = metrics.revenue_cagr({"revenue": series}, cfg)
        assert result.dropped_reason == metrics.DROP_INSUFFICIENT_HISTORY

    def test_only_the_endpoints_matter_not_a_loss_year_in_between(self):
        # Endpoints (100, 50) are both positive, even though the middle year
        # dipped negative — CAGR only looks at the first and last values.
        series = [
            AnnualValue(2021, 100.0, "USD"),
            AnnualValue(2022, -20.0, "USD"),
            AnnualValue(2023, 50.0, "USD"),
        ]
        result = metrics.revenue_cagr({"revenue": series}, HIGHER_CFG)
        assert result.dropped_reason is None
        assert result.value == pytest.approx((50 / 100) ** (1 / 2) - 1)

    def test_negative_endpoint_value_is_dropped(self):
        series = [AnnualValue(2021, -100.0, "USD"), AnnualValue(2022, 10.0, "USD"), AnnualValue(2023, 50.0, "USD")]
        result = metrics.revenue_cagr({"revenue": series}, HIGHER_CFG)
        assert result.dropped_reason == metrics.DROP_NON_POSITIVE_VALUE


class TestRevenueGrowthConsistency:
    def test_all_positive_years_score_full_ratio(self):
        series = [AnnualValue(y, v, "USD") for y, v in zip(range(2021, 2025), [100, 110, 120, 130])]
        result = metrics.revenue_growth_consistency({"revenue": series}, HIGHER_CFG)
        assert result.value == pytest.approx(1.0)

    def test_one_down_year_out_of_three_periods(self):
        series = [AnnualValue(y, v, "USD") for y, v in zip(range(2021, 2025), [100, 90, 120, 130])]
        result = metrics.revenue_growth_consistency({"revenue": series}, HIGHER_CFG)
        assert result.value == pytest.approx(2 / 3)


class TestQualityBinaryChecks:
    def test_roa_positive_pass(self):
        concepts = {"net_income": [AnnualValue(2024, 100.0, "USD")], "assets": [AnnualValue(2024, 1000.0, "USD")]}
        assert metrics.roa_positive(concepts).score == 100.0

    def test_roa_positive_fail(self):
        concepts = {"net_income": [AnnualValue(2024, -10.0, "USD")], "assets": [AnnualValue(2024, 1000.0, "USD")]}
        assert metrics.roa_positive(concepts).score == 0.0

    def test_roa_positive_missing_concept_is_dropped(self):
        assert metrics.roa_positive({}).dropped_reason == metrics.DROP_MISSING_CONCEPT

    def test_cfo_positive(self):
        assert metrics.cfo_positive({"operating_cash_flow": [AnnualValue(2024, 5.0, "USD")]}).score == 100.0
        assert metrics.cfo_positive({"operating_cash_flow": [AnnualValue(2024, -5.0, "USD")]}).score == 0.0

    def test_accruals_quality_uses_the_latest_common_fiscal_year(self):
        concepts = {
            "operating_cash_flow": [AnnualValue(2023, 80.0, "USD"), AnnualValue(2024, 120.0, "USD")],
            "net_income": [AnnualValue(2023, 90.0, "USD"), AnnualValue(2024, 100.0, "USD")],
        }
        # 2024: OCF 120 > NI 100 -> pass, even though 2023 alone would fail.
        assert metrics.accruals_quality(concepts).score == 100.0

    def test_leverage_not_increasing_pass(self):
        concepts = {
            "debt_long_term": [AnnualValue(2023, 500.0, "USD"), AnnualValue(2024, 400.0, "USD")],
            "assets": [AnnualValue(2023, 1000.0, "USD"), AnnualValue(2024, 1000.0, "USD")],
        }
        # leverage 0.5 -> 0.4: not increasing -> pass.
        assert metrics.leverage_not_increasing(concepts).score == 100.0

    def test_leverage_not_increasing_fail(self):
        concepts = {
            "debt_long_term": [AnnualValue(2023, 400.0, "USD"), AnnualValue(2024, 500.0, "USD")],
            "assets": [AnnualValue(2023, 1000.0, "USD"), AnnualValue(2024, 1000.0, "USD")],
        }
        assert metrics.leverage_not_increasing(concepts).score == 0.0

    def test_no_significant_dilution_pass(self):
        series = [AnnualValue(2023, 100.0, "USD"), AnnualValue(2024, 101.0, "USD")]
        assert metrics.no_significant_dilution({"shares_diluted": series}).score == 100.0

    def test_no_significant_dilution_fail(self):
        series = [AnnualValue(2023, 100.0, "USD"), AnnualValue(2024, 110.0, "USD")]
        assert metrics.no_significant_dilution({"shares_diluted": series}).score == 0.0


class TestTechnical:
    TECH_CFG = MetricConfig(weight=40, direction="higher_is_better", full_at=0.10, zero_at=-0.20)

    def test_price_vs_sma200_needs_two_hundred_closes(self):
        closes = [100.0] * 199
        result = metrics.price_vs_sma200(closes, self.TECH_CFG)
        assert result.dropped_reason == metrics.DROP_INSUFFICIENT_HISTORY

    def test_price_vs_sma200_known_value(self):
        closes = [100.0] * 199 + [120.0]
        # SMA200 = (199*100 + 120)/200 = 100.1; last/sma - 1 = 120/100.1 - 1
        result = metrics.price_vs_sma200(closes, self.TECH_CFG)
        assert result.value == pytest.approx(120 / 100.1 - 1)

    def test_momentum_12_1_needs_253_closes(self):
        closes = [100.0] * 252
        result = metrics.momentum_12_1(closes, self.TECH_CFG)
        assert result.dropped_reason == metrics.DROP_INSUFFICIENT_HISTORY

    def test_momentum_12_1_known_value(self):
        closes = [0.0] * 253
        closes[-253] = 100.0
        closes[-22] = 150.0
        result = metrics.momentum_12_1(closes, self.TECH_CFG)
        assert result.value == pytest.approx(0.5)

    def test_sma50_vs_sma200_known_value(self):
        closes = [100.0] * 150 + [200.0] * 50
        # SMA200 = (150*100 + 50*200)/200 = 125; SMA50 = 200.
        result = metrics.sma50_vs_sma200(closes, self.TECH_CFG)
        assert result.value == pytest.approx(200 / 125 - 1)
