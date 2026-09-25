"""Point-in-time backtest of the composite score.

Does the score predict forward returns? `scoring.yaml`'s factor weights are a
plausible model, but "plausible" is not "verified". This module recomputes the
score *as it would have been on each past rebalance date* — using only
fundamentals whose period ended (plus a filing lag) before that date, and only
closes up to that date — then measures forward returns and reports the spread
between the top and bottom score buckets. No look-ahead: a figure is never used
before it would have been public.

Reuses `app/scoring/service.py`'s pillar/composite helpers wholesale (imported
underscore-private on purpose), so this always tests the *current* score, never
a stale re-implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fundamental, Instrument, PriceBar
from app.prices.fx_service import get_rate
from app.scoring.config import ScoringConfig
from app.scoring.metrics import AnnualValue
from app.scoring.service import _compute_pillar, _finalise_composite, _representative_currency
from app.symbols.mapping import ANALYSABLE_CATEGORIES

#: Filing lag: a figure whose period ended on D is treated as "known" only from
#: D + this many days (a Dec-31 10-K is typically filed in Feb-Mar; 120 days is
#: a conservative buffer that still admits the figure at the next rebalance).
FILING_LAG_DAYS = 120

#: Minimum price history (bars) an instrument needs to enter the backtest — ~2
#: trading years, so the technical pillar (200-day SMA, 12-1 momentum) has
#: enough of a runway to be computed without being truncated.
MIN_HISTORY_BARS = 504

#: A rebalance date is dropped unless at least this many instruments scored,
#: so a quartile split is meaningful rather than a handful of stragglers.
MIN_CROSS_SECTION = 8


@dataclass
class Bucket:
    quartile: int
    count: int
    mean_return: float | None
    median_return: float | None


@dataclass
class BacktestResult:
    horizon_months: int
    rebalance_count: int
    observations: int
    buckets: list[Bucket] = field(default_factory=list)
    top_minus_bottom: float | None = None


def run_backtest(
    db: Session,
    config: ScoringConfig,
    *,
    start: date,
    end: date,
    horizon_months: int = 12,
    filing_lag_days: int = FILING_LAG_DAYS,
    min_history_bars: int = MIN_HISTORY_BARS,
) -> BacktestResult:
    """Cross-sectional quartile backtest over monthly rebalance dates in
    `[start, end]`. Per date: rank the universe by the point-in-time composite,
    split into quartiles, record each instrument's forward `horizon_months`
    return. Returns per-quartile mean/median and the top-minus-bottom spread."""
    instruments = _universe(db)
    calendar = _trading_calendar(db, start, end)
    rebalance_dates = _monthly_dates(calendar)
    if not instruments or not rebalance_dates:
        return BacktestResult(
            horizon_months=horizon_months, rebalance_count=len(rebalance_dates), observations=0
        )

    ids = [i.id for i in instruments]
    fundamentals_by_id = _fundamentals_by_id(db, ids)
    closes_by_id = _closes_by_id(db, ids)

    observations: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    for rebalance in rebalance_dates:
        scored: list[tuple[int, float]] = []
        for instrument in instruments:
            closes = [c for (d, c) in closes_by_id.get(instrument.id, []) if d <= rebalance]
            if len(closes) < min_history_bars:
                continue
            composite = _score_at(
                db,
                instrument,
                fundamentals_by_id.get(instrument.id, {}),
                closes,
                config,
                rebalance,
                filing_lag_days,
            )
            if composite is not None:
                scored.append((instrument.id, composite))
        if len(scored) < MIN_CROSS_SECTION:
            continue

        scored.sort(key=lambda pair: pair[1])
        n = len(scored)
        for rank, (instrument_id, _composite) in enumerate(scored):
            quartile = 1 + (rank * 4) // n
            fwd = _forward_return(closes_by_id.get(instrument_id, []), rebalance, horizon_months)
            if fwd is not None:
                observations[quartile].append(fwd)

    buckets = [
        Bucket(quartile=q, count=len(returns), mean_return=_mean(returns), median_return=_median(returns))
        for q, returns in sorted(observations.items())
    ]
    top = buckets[-1].mean_return if buckets else None
    bottom = buckets[0].mean_return if buckets else None
    spread = (top - bottom) if (top is not None and bottom is not None) else None

    return BacktestResult(
        horizon_months=horizon_months,
        rebalance_count=len(rebalance_dates),
        observations=sum(len(r) for r in observations.values()),
        buckets=buckets,
        top_minus_bottom=spread,
    )


def _universe(db: Session) -> list[Instrument]:
    return list(db.execute(select(Instrument).where(Instrument.category.in_(ANALYSABLE_CATEGORIES))).scalars())


def _fundamentals_by_id(db: Session, ids: list[int]) -> dict[int, dict[str, list[tuple[date, int, float, str]]]]:
    rows = db.execute(
        select(Fundamental)
        .where(Fundamental.instrument_id.in_(ids))
        .order_by(Fundamental.instrument_id, Fundamental.concept, Fundamental.fiscal_year)
    ).scalars()
    result: dict[int, dict[str, list[tuple[date, int, float, str]]]] = {}
    for row in rows:
        result.setdefault(row.instrument_id, {}).setdefault(row.concept, []).append(
            (row.period_end, row.fiscal_year, row.value, row.currency)
        )
    return result


def _closes_by_id(db: Session, ids: list[int]) -> dict[int, list[tuple[date, float]]]:
    rows = db.execute(
        select(PriceBar.instrument_id, PriceBar.bar_date, PriceBar.close)
        .where(PriceBar.instrument_id.in_(ids), PriceBar.close.is_not(None))
        .order_by(PriceBar.instrument_id, PriceBar.bar_date)
    )
    result: dict[int, list[tuple[date, float]]] = {}
    for instrument_id, bar_date, close in rows:
        result.setdefault(instrument_id, []).append((bar_date, close))
    return result


def _trading_calendar(db: Session, start: date, end: date) -> list[date]:
    rows = db.execute(
        select(PriceBar.bar_date)
        .where(PriceBar.bar_date >= start, PriceBar.bar_date <= end)
        .distinct()
        .order_by(PriceBar.bar_date)
    ).scalars()
    return list(rows)


def _monthly_dates(calendar: list[date]) -> list[date]:
    """The first trading day of each month present in the calendar."""
    firsts: list[date] = []
    seen: set[tuple[int, int]] = set()
    for d in calendar:
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            firsts.append(d)
    return firsts


def _concepts_as_of(
    entries: dict[str, list[tuple[date, int, float, str]]], as_of: date, lag_days: int
) -> dict[str, list[AnnualValue]]:
    """Only figures whose period ended at least `lag_days` before `as_of` — the
    point-in-time rule that keeps the backtest free of look-ahead bias."""
    known: dict[str, list[AnnualValue]] = {}
    cutoff = as_of - timedelta(days=lag_days)
    for concept, series in entries.items():
        filtered = [
            AnnualValue(fiscal_year=fy, value=value, currency=currency)
            for (period_end, fy, value, currency) in series
            if period_end <= cutoff
        ]
        if filtered:
            known[concept] = filtered
    return known


def _score_at(
    db: Session,
    instrument: Instrument,
    fundamentals: dict[str, list[tuple[date, int, float, str]]],
    closes: list[float],
    config: ScoringConfig,
    as_of: date,
    lag_days: int,
) -> float | None:
    price = closes[-1] if closes else None
    if price is None:
        return None
    concepts = _concepts_as_of(fundamentals, as_of, lag_days)
    price_currency = instrument.currency or ""
    fundamentals_currency = _representative_currency(concepts)
    fx_rate = None
    if fundamentals_currency and price_currency:
        fx_rate = get_rate(db, price_currency, fundamentals_currency)
    pillars = [
        _compute_pillar(name, pillar_cfg, concepts, price, price_currency, fx_rate, closes, None)
        for name, pillar_cfg in config.pillars.items()
    ]
    return _finalise_composite(pillars, config.pillars)


def _forward_return(closes: list[tuple[date, float]], from_date: date, horizon_months: int) -> float | None:
    target = from_date + timedelta(days=30 * horizon_months)
    entry = next((c for (d, c) in closes if d >= from_date), None)
    exit_ = next((c for (d, c) in closes if d >= target), None)
    if entry is None or exit_ is None or entry <= 0:
        return None
    return exit_ / entry - 1.0


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
