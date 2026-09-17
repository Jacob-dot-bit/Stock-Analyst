"""Pure per-metric scoring functions — the checklist behind each pillar.

Each function takes plain data (no DB session, no ORM), so it can be
hand-verified against known numbers without any fixture setup beyond the
inputs it actually needs. `scoring/service.py` is the only caller, and it is
responsible for assembling these plain inputs from cached `Fundamental`/
`PriceBar` rows.

Every function returns a `MetricResult`. `score`/`value` are both `None` when
the inputs needed to compute the metric are missing or degenerate — never a
guessed number, the same rule this app applies everywhere else (DEVLOG
"Decision 1.2"). `dropped_reason` is one of a small, translatable vocabulary
(`DROP_MISSING_CONCEPT`, `DROP_NON_POSITIVE_VALUE`, `DROP_MISSING_FX_RATE`,
`DROP_INSUFFICIENT_HISTORY`) rather than free text, so the frontend can render
it in the user's language instead of an English debug string.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.scoring.config import MetricConfig

DROP_MISSING_CONCEPT = "missing_concept"
DROP_NON_POSITIVE_VALUE = "non_positive_value"
DROP_MISSING_FX_RATE = "missing_fx_rate"
DROP_INSUFFICIENT_HISTORY = "insufficient_history"


@dataclass(frozen=True)
class AnnualValue:
    fiscal_year: int
    value: float
    currency: str


@dataclass(frozen=True)
class MetricResult:
    score: float | None
    value: float | None
    dropped_reason: str | None


def _dropped(reason: str) -> MetricResult:
    return MetricResult(score=None, value=None, dropped_reason=reason)


def _ok(value: float, cfg: MetricConfig) -> MetricResult:
    return MetricResult(score=score_linear(value, cfg), value=value, dropped_reason=None)


def _binary(passed: bool) -> MetricResult:
    return MetricResult(score=100.0 if passed else 0.0, value=1.0 if passed else 0.0, dropped_reason=None)


def score_linear(value: float, cfg: MetricConfig) -> float:
    """100 at/past `full_at`, 0 at/past `zero_at`, linear between."""
    full_at, zero_at = cfg.full_at, cfg.zero_at
    if cfg.direction == "higher_is_better":
        if value >= full_at:
            return 100.0
        if value <= zero_at:
            return 0.0
        return (value - zero_at) / (full_at - zero_at) * 100.0
    else:
        if value <= full_at:
            return 100.0
        if value >= zero_at:
            return 0.0
        return (zero_at - value) / (zero_at - full_at) * 100.0


def _latest(concepts: dict[str, list[AnnualValue]], concept: str) -> AnnualValue | None:
    series = concepts.get(concept)
    return series[-1] if series else None


def _at_fiscal_year(series: list[AnnualValue], fiscal_year: int) -> AnnualValue | None:
    return next((f for f in series if f.fiscal_year == fiscal_year), None)


# --- Value (Graham/Buffett) -------------------------------------------------


def _price_in(target_currency: str, price: float, price_currency: str, fx_rate: float | None) -> float | None:
    if price_currency == target_currency:
        return price
    return price * fx_rate if fx_rate is not None else None


def pe_ratio(
    concepts: dict[str, list[AnnualValue]],
    price: float,
    price_currency: str,
    fx_rate: float | None,
    cfg: MetricConfig,
) -> MetricResult:
    net_income = _latest(concepts, "net_income")
    shares = _latest(concepts, "shares_diluted")
    if net_income is None or shares is None or shares.value <= 0:
        return _dropped(DROP_MISSING_CONCEPT)
    if net_income.value <= 0:
        return _dropped(DROP_NON_POSITIVE_VALUE)
    price_conv = _price_in(net_income.currency, price, price_currency, fx_rate)
    if price_conv is None:
        return _dropped(DROP_MISSING_FX_RATE)
    eps = net_income.value / shares.value
    return _ok(price_conv / eps, cfg)


def pb_ratio(
    concepts: dict[str, list[AnnualValue]],
    price: float,
    price_currency: str,
    fx_rate: float | None,
    cfg: MetricConfig,
) -> MetricResult:
    equity = _latest(concepts, "equity")
    shares = _latest(concepts, "shares_diluted")
    if equity is None or shares is None or shares.value <= 0:
        return _dropped(DROP_MISSING_CONCEPT)
    if equity.value <= 0:
        return _dropped(DROP_NON_POSITIVE_VALUE)
    price_conv = _price_in(equity.currency, price, price_currency, fx_rate)
    if price_conv is None:
        return _dropped(DROP_MISSING_FX_RATE)
    book_per_share = equity.value / shares.value
    return _ok(price_conv / book_per_share, cfg)


def fcf_yield(
    concepts: dict[str, list[AnnualValue]],
    price: float,
    price_currency: str,
    fx_rate: float | None,
    cfg: MetricConfig,
) -> MetricResult:
    ocf = _latest(concepts, "operating_cash_flow")
    capex = _latest(concepts, "capex")
    shares = _latest(concepts, "shares_diluted")
    if ocf is None or capex is None or shares is None or shares.value <= 0:
        return _dropped(DROP_MISSING_CONCEPT)
    price_conv = _price_in(ocf.currency, price, price_currency, fx_rate)
    if price_conv is None:
        return _dropped(DROP_MISSING_FX_RATE)
    market_cap = price_conv * shares.value
    if market_cap <= 0:
        return _dropped(DROP_NON_POSITIVE_VALUE)
    fcf = ocf.value - capex.value
    return _ok(fcf / market_cap, cfg)


def market_cap(
    concepts: dict[str, list[AnnualValue]], price: float | None, price_currency: str, fx_rate: float | None
) -> float | None:
    """Price × diluted shares outstanding — an approximation (weighted-
    average diluted shares, not a point-in-time count), good enough for a
    screening filter. Deliberately not a scored metric: this is
    informational only, never meant to influence the composite score, so
    it returns a plain value rather than a `MetricResult`/`score_linear`
    pair the way every other function in this file does. See DEVLOG
    "Decision 3u.72"."""
    shares = _latest(concepts, "shares_diluted")
    if shares is None or shares.value <= 0 or price is None:
        return None
    price_conv = _price_in(shares.currency, price, price_currency, fx_rate)
    if price_conv is None:
        return None
    return price_conv * shares.value


def dividend_yield_estimate(
    concepts: dict[str, list[AnnualValue]], price: float | None, price_currency: str, fx_rate: float | None
) -> float | None:
    """Filed dividends-per-share ÷ price — a company-level fundamentals
    estimate for instruments with no lot/transaction history (Discovery
    candidates). Deliberately NOT the same figure as the scored
    `dividend_yield` metric below, which replays this account's own
    holding history for held/previously-held stocks — the two measure
    different things and must never be conflated under one name. Same
    unscored, informational-only pattern as `market_cap`. See DEVLOG
    "Decision 3u.73"."""
    per_share = _latest(concepts, "dividend_per_share")
    if per_share is None or price is None:
        return None
    price_conv = _price_in(per_share.currency, price, price_currency, fx_rate)
    if price_conv is None or price_conv <= 0:
        return None
    return per_share.value / price_conv


def debt_to_equity(concepts: dict[str, list[AnnualValue]], cfg: MetricConfig) -> MetricResult:
    debt = _latest(concepts, "debt_long_term")
    equity = _latest(concepts, "equity")
    if debt is None or equity is None:
        return _dropped(DROP_MISSING_CONCEPT)
    if equity.value <= 0:
        return _dropped(DROP_NON_POSITIVE_VALUE)
    return _ok(debt.value / equity.value, cfg)


def dividend_yield(annual_per_share: float | None, price: float | None, cfg: MetricConfig) -> MetricResult:
    """`annual_per_share` comes from `scoring/service.py`'s lot-replay of the
    trailing 12 months of dividend `Transaction` rows, not from `concepts` —
    dividends aren't a `Fundamental` concept. Both values are already
    confirmed to share the instrument's own trading currency (no FX needed).
    `0.0` is a real, scoreable "no dividend paid" value; only `None` (a
    genuine replay failure) is dropped."""
    if annual_per_share is None or price is None or price <= 0:
        return _dropped(DROP_MISSING_CONCEPT)
    return _ok(annual_per_share / price, cfg)


# --- Growth (CAGR / consistency) --------------------------------------------


def _cagr(series: list[AnnualValue], min_years: int, cfg: MetricConfig) -> MetricResult:
    if len(series) < min_years:
        return _dropped(DROP_INSUFFICIENT_HISTORY)
    oldest, latest = series[0], series[-1]
    years = latest.fiscal_year - oldest.fiscal_year
    if years <= 0:
        return _dropped(DROP_INSUFFICIENT_HISTORY)
    if oldest.value <= 0 or latest.value <= 0:
        return _dropped(DROP_NON_POSITIVE_VALUE)
    cagr = (latest.value / oldest.value) ** (1 / years) - 1
    return _ok(cagr, cfg)


def revenue_cagr(concepts: dict[str, list[AnnualValue]], cfg: MetricConfig) -> MetricResult:
    return _cagr(concepts.get("revenue", []), cfg.min_years or 3, cfg)


def net_income_cagr(concepts: dict[str, list[AnnualValue]], cfg: MetricConfig) -> MetricResult:
    return _cagr(concepts.get("net_income", []), cfg.min_years or 3, cfg)


def revenue_growth_consistency(concepts: dict[str, list[AnnualValue]], cfg: MetricConfig) -> MetricResult:
    series = concepts.get("revenue", [])
    min_years = cfg.min_years or 3
    if len(series) < min_years:
        return _dropped(DROP_INSUFFICIENT_HISTORY)
    pairs = list(zip(series, series[1:]))
    if not pairs:
        return _dropped(DROP_INSUFFICIENT_HISTORY)
    positive = sum(1 for earlier, later in pairs if later.value > earlier.value)
    return _ok(positive / len(pairs), cfg)


# --- Quality (Piotroski-adapted, 5 of 9 signals) ----------------------------


def roa_positive(concepts: dict[str, list[AnnualValue]]) -> MetricResult:
    net_income = _latest(concepts, "net_income")
    assets = _latest(concepts, "assets")
    if net_income is None or assets is None or assets.value == 0:
        return _dropped(DROP_MISSING_CONCEPT)
    return _binary(net_income.value / assets.value > 0)


def cfo_positive(concepts: dict[str, list[AnnualValue]]) -> MetricResult:
    ocf = _latest(concepts, "operating_cash_flow")
    if ocf is None:
        return _dropped(DROP_MISSING_CONCEPT)
    return _binary(ocf.value > 0)


def accruals_quality(concepts: dict[str, list[AnnualValue]]) -> MetricResult:
    """Cash-backed earnings — Sloan's accrual test: CFO should exceed net
    income in the same fiscal year, or the profit is running ahead of the
    cash actually collected."""
    ocf_series = concepts.get("operating_cash_flow", [])
    ni_series = concepts.get("net_income", [])
    common_years = {f.fiscal_year for f in ocf_series} & {f.fiscal_year for f in ni_series}
    if not common_years:
        return _dropped(DROP_MISSING_CONCEPT)
    fiscal_year = max(common_years)
    ocf = _at_fiscal_year(ocf_series, fiscal_year)
    ni = _at_fiscal_year(ni_series, fiscal_year)
    return _binary(ocf.value > ni.value)


def leverage_not_increasing(concepts: dict[str, list[AnnualValue]]) -> MetricResult:
    debt_series = concepts.get("debt_long_term", [])
    assets_series = concepts.get("assets", [])
    common_years = sorted({f.fiscal_year for f in debt_series} & {f.fiscal_year for f in assets_series})
    if len(common_years) < 2:
        return _dropped(DROP_INSUFFICIENT_HISTORY)
    prior_year, latest_year = common_years[-2], common_years[-1]

    def _leverage(fiscal_year: int) -> float | None:
        debt = _at_fiscal_year(debt_series, fiscal_year)
        assets = _at_fiscal_year(assets_series, fiscal_year)
        if assets is None or assets.value == 0:
            return None
        return debt.value / assets.value

    prior_leverage, latest_leverage = _leverage(prior_year), _leverage(latest_year)
    if prior_leverage is None or latest_leverage is None:
        return _dropped(DROP_MISSING_CONCEPT)
    return _binary(latest_leverage <= prior_leverage)


def no_significant_dilution(concepts: dict[str, list[AnnualValue]]) -> MetricResult:
    series = concepts.get("shares_diluted", [])
    if len(series) < 2:
        return _dropped(DROP_INSUFFICIENT_HISTORY)
    prior, latest = series[-2], series[-1]
    return _binary(latest.value <= prior.value * 1.02)


# --- Technical (SMA / momentum, from cached daily closes) -------------------


def price_vs_sma200(closes: list[float], cfg: MetricConfig) -> MetricResult:
    if len(closes) < 200:
        return _dropped(DROP_INSUFFICIENT_HISTORY)
    sma200 = sum(closes[-200:]) / 200
    if sma200 == 0:
        return _dropped(DROP_NON_POSITIVE_VALUE)
    return _ok(closes[-1] / sma200 - 1, cfg)


def momentum_12_1(closes: list[float], cfg: MetricConfig) -> MetricResult:
    """Jegadeesh & Titman's 12-1 momentum: trailing 12-month return, skipping
    the most recent month, using ~252/~21 trading days as the standard
    academic approximation for 12 months / 1 month."""
    if len(closes) < 253:
        return _dropped(DROP_INSUFFICIENT_HISTORY)
    recent, distant = closes[-22], closes[-253]
    if distant == 0:
        return _dropped(DROP_NON_POSITIVE_VALUE)
    return _ok(recent / distant - 1, cfg)


def sma50_vs_sma200(closes: list[float], cfg: MetricConfig) -> MetricResult:
    if len(closes) < 200:
        return _dropped(DROP_INSUFFICIENT_HISTORY)
    sma50 = sum(closes[-50:]) / 50
    sma200 = sum(closes[-200:]) / 200
    if sma200 == 0:
        return _dropped(DROP_NON_POSITIVE_VALUE)
    return _ok(sma50 / sma200 - 1, cfg)
