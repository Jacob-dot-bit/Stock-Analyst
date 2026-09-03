"""Phase 2 of a real, backtestable Discovery prediction: price-only
features, a forward-return label, and a walk-forward-validated logistic
regression. See `app/prediction/service.py`'s module docstring for why
this is price-only (fundamentals aren't stored with a dated history, so
using today's score to "predict" a past return would be lookahead bias).
See DEVLOG "Decision 3u.23".

Every feature here is computed strictly from bars dated on or before
`as_of` — none look forward. The label is the only thing that looks
forward, and only at `as_of + horizon_days`, which is exactly what a real
trade would have waited to find out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.corporate_actions.service import price_factor_from
from app.models import CorporateAction, PriceBar

#: Trading-day lookback windows for momentum features. Calendar days would
#: drift with weekends/holidays; these are counts of *bars*, not days.
MOMENTUM_WINDOWS = (20, 60, 120)
SMA_WINDOWS = (50, 200)
VOLATILITY_WINDOW = 20
#: How far forward the label looks. ~3 months of trading days — long
#: enough that day-to-day noise doesn't dominate, short enough that the
#: 5-year backfill gives several non-overlapping labeled periods.
LABEL_HORIZON_DAYS = 60
#: Longest lookback any feature needs, used to know how much history must
#: exist before `as_of` for a row to be computable at all.
MAX_LOOKBACK_DAYS = max(max(MOMENTUM_WINDOWS), max(SMA_WINDOWS))


@dataclass(frozen=True)
class FeatureRow:
    instrument_id: int
    as_of: date
    momentum_20: float
    momentum_60: float
    momentum_120: float
    sma50_ratio: float
    sma200_ratio: float
    volatility_20: float
    #: None until the label is filled in by `label_forward_return` — kept
    #: on the same row rather than a parallel list so a feature row and its
    #: label can never accidentally desync.
    forward_return: float | None = None


def _closes_by_date(
    bars: list[PriceBar], actions: list[CorporateAction] | None = None
) -> tuple[list[date], list[float]]:
    """Split-adjusted closes, oldest first — every feature below (momentum,
    SMA ratios, volatility) and the forward-return label are ratios of
    consecutive/nearby closes, so an unadjusted split would otherwise read
    as an impossible momentum spike and a fabricated label. See
    `app/corporate_actions/service.py::price_factor_from`."""
    ordered = sorted(bars, key=lambda b: b.bar_date)
    actions = actions or []
    return (
        [b.bar_date for b in ordered],
        [b.close * price_factor_from(actions, b.bar_date) for b in ordered],
    )


def compute_features(bars: list[PriceBar], as_of_index: int, dates: list[date], closes: list[float]) -> FeatureRow | None:
    """Features for one instrument at `dates[as_of_index]`, using only
    `closes[:as_of_index + 1]`. Returns `None` if there isn't enough history
    yet (fewer than `MAX_LOOKBACK_DAYS` prior bars) — never a guessed or
    zero-filled feature."""
    if as_of_index < MAX_LOOKBACK_DAYS:
        return None

    current = closes[as_of_index]

    def momentum(window: int) -> float:
        past = closes[as_of_index - window]
        return (current / past) - 1.0 if past else 0.0

    def sma_ratio(window: int) -> float:
        window_closes = closes[as_of_index - window + 1 : as_of_index + 1]
        sma = sum(window_closes) / len(window_closes)
        return (current / sma) - 1.0 if sma else 0.0

    vol_window = closes[as_of_index - VOLATILITY_WINDOW + 1 : as_of_index + 1]
    daily_returns = [
        (vol_window[i] / vol_window[i - 1]) - 1.0 for i in range(1, len(vol_window)) if vol_window[i - 1]
    ]
    mean_r = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns) if daily_returns else 0.0
    volatility = variance**0.5

    return FeatureRow(
        instrument_id=0,  # filled in by the caller, which knows the instrument
        as_of=dates[as_of_index],
        momentum_20=momentum(MOMENTUM_WINDOWS[0]),
        momentum_60=momentum(MOMENTUM_WINDOWS[1]),
        momentum_120=momentum(MOMENTUM_WINDOWS[2]),
        sma50_ratio=sma_ratio(SMA_WINDOWS[0]),
        sma200_ratio=sma_ratio(SMA_WINDOWS[1]),
        volatility_20=volatility,
    )


def forward_return(as_of_index: int, closes: list[float], horizon_days: int = LABEL_HORIZON_DAYS) -> float | None:
    """The actual realized return from `as_of_index` to `horizon_days`
    bars later. `None` when that many future bars don't exist yet — the
    honest answer, not a guess."""
    target_index = as_of_index + horizon_days
    if target_index >= len(closes):
        return None
    base = closes[as_of_index]
    if not base:
        return None
    return (closes[target_index] / base) - 1.0


#: How many bars apart consecutive sampled rows are, per instrument. Daily
#: sampling would make adjacent rows share ~all of their lookback window
#: and label horizon — heavily autocorrelated, inflating the apparent
#: sample size without adding real information. Sampling every 20 bars
#: (~1 month) keeps windows substantially non-overlapping.
SAMPLE_STRIDE_DAYS = 20


def build_feature_rows(
    instrument_id: int, bars: list[PriceBar], actions: list[CorporateAction] | None = None
) -> list[FeatureRow]:
    """Every computable, labeled sample for one instrument's bar history."""
    dates, closes = _closes_by_date(bars, actions)
    rows = []
    for i in range(MAX_LOOKBACK_DAYS, len(closes), SAMPLE_STRIDE_DAYS):
        features = compute_features(bars, i, dates, closes)
        if features is None:
            continue
        label = forward_return(i, closes)
        if label is None:
            continue
        rows.append(
            FeatureRow(
                instrument_id=instrument_id,
                as_of=features.as_of,
                momentum_20=features.momentum_20,
                momentum_60=features.momentum_60,
                momentum_120=features.momentum_120,
                sma50_ratio=features.sma50_ratio,
                sma200_ratio=features.sma200_ratio,
                volatility_20=features.volatility_20,
                forward_return=label,
            )
        )
    return rows


FEATURE_NAMES = ("momentum_20", "momentum_60", "momentum_120", "sma50_ratio", "sma200_ratio", "volatility_20")


def row_as_vector(row: FeatureRow) -> list[float]:
    return [getattr(row, name) for name in FEATURE_NAMES]
