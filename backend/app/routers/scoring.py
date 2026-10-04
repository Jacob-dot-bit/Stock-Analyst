"""Fundamentals refresh and scoring endpoints."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtest.service import run_backtest, user_universe_ids
from app.db import get_db
from app.fundamentals.service import fetch_fundamentals, get_fundamentals_progress
from app.models import Instrument, Position, PriceBar
from app.providers.registry import get_edgar_provider, get_esef_provider
from app.schemas import (
    FundamentalsRefreshReportOut,
    FundamentalsRefreshStatusOut,
    MetricScoreOut,
    PillarScoreOut,
    ScoreBacktestBucketOut,
    ScoreBacktestOut,
    ScoreBacktestPeriodOut,
    ScoreOut,
)
from app.scoring.config import get_scoring_config
from app.scoring.service import InstrumentScore, compute_scores

router = APIRouter(prefix="/api/scoring", tags=["scoring"])


def _held_instruments(db: Session) -> list[Instrument]:
    query = select(Instrument).join(Position, Position.instrument_id == Instrument.id).distinct()
    return list(db.execute(query).scalars())


def score_to_out(result: InstrumentScore) -> ScoreOut:
    """Shared by this router's `/scores` and `routers/watchlist.py`'s
    equivalent — both convert the same `compute_scores` result shape."""
    return ScoreOut(
        instrument_id=result.instrument_id,
        composite=result.composite,
        pillars=[
            PillarScoreOut(
                name=pillar.name,
                score=pillar.score,
                weight_used=pillar.weight_used,
                metrics=[
                    MetricScoreOut(
                        name=metric.name,
                        weight=metric.weight,
                        score=metric.score,
                        value=metric.value,
                        dropped_reason=metric.dropped_reason,
                    )
                    for metric in pillar.metrics
                ],
            )
            for pillar in result.pillars
        ],
    )


@router.post("/fundamentals/refresh", response_model=FundamentalsRefreshReportOut)
def refresh_fundamentals(
    force: bool = Query(False, description="Re-fetch even instruments already fetched today."),
    db: Session = Depends(get_db),
) -> FundamentalsRefreshReportOut:
    """Bring held, watchlisted, and screener-candidate STOCK instruments'
    fundamentals up to date.

    Tries SEC EDGAR first, then ESEF for whatever it can't answer — see
    `fundamentals/service.py`'s module docstring (DEVLOG "Decision 3t.1").
    Every instrument gathered is passed through — ETFs and CFDs report
    `not_applicable` rather than being silently excluded, so the report
    reflects the whole set, not just the subset that could work. Runs
    sequentially and returns synchronously — this call itself blocks until
    done — but a cold run (ESEF's first entity-index load in a fresh process)
    is tens of seconds, not the sub-second case that might suggest, hence
    `GET /fundamentals/refresh/status` below for a real progress bar polled
    from a separate request while this one is still working.
    """
    # Deferred import: `routers/watchlist.py` and `routers/screener.py` both
    # import `score_to_out` from this module, so importing them back at
    # module load time would be circular. By call time both are already
    # fully loaded, so a local import here is safe.
    from app.routers.screener import _screener_instruments
    from app.routers.watchlist import _watchlist_instruments

    instruments = _held_instruments(db)
    seen = {i.id for i in instruments}
    instruments.extend(w for w in _watchlist_instruments(db) if w.id not in seen)
    seen = {i.id for i in instruments}
    instruments.extend(c for c in _screener_instruments(db) if c.id not in seen)

    report = fetch_fundamentals(db, instruments, get_edgar_provider(), get_esef_provider(), force=force)
    return FundamentalsRefreshReportOut(**report.as_dict())


@router.get("/fundamentals/refresh/status", response_model=FundamentalsRefreshStatusOut)
def fundamentals_refresh_status() -> FundamentalsRefreshStatusOut:
    """Live progress of the fundamentals refresh currently in flight, or the
    last completed one — same shape and reasoning as
    `GET /api/prices/refresh/status`."""
    progress = get_fundamentals_progress()
    return FundamentalsRefreshStatusOut(
        running=progress.running,
        total=progress.total,
        done=progress.done,
        current_symbol=progress.current_symbol,
        started_at=progress.started_at,
        finished_at=progress.finished_at,
        report=FundamentalsRefreshReportOut(**progress.report.as_dict()) if progress.report else None,
    )


@router.get("/scores", response_model=list[ScoreOut])
def get_scores(db: Session = Depends(get_db)) -> list[ScoreOut]:
    """Every held STOCK/ETF instrument's composite score, computed live from
    whatever `Fundamental`/`PriceBar` data is already cached — no network
    calls (aside from `fx_service.get_rate`'s own today-only cache, the same
    live-but-cached path the portfolio's current value already uses). CFDs
    never appear: see `scoring/service.py::compute_scores`.
    """
    instruments = _held_instruments(db)
    config = get_scoring_config()
    results = compute_scores(db, instruments, config)

    return [score_to_out(result) for result in results]


@router.post("/backtest", response_model=ScoreBacktestOut)
def score_backtest(
    horizon_months: int = Query(12, ge=1, le=36, description="Forward-return horizon in months."),
    years: int = Query(5, ge=1, le=20, description="How many years of rebalance dates to test."),
    db: Session = Depends(get_db),
) -> ScoreBacktestOut:
    """The composite score's track record: recompute it point-in-time on each
    monthly rebalance date (`app/backtest/service.py`) and compare forward
    returns across score quartiles. The window ends `horizon_months` before
    the latest stored bar, so every rebalance date has a forward return to
    measure. The universe is the user's own instruments (held, watchlisted,
    screened), matching the panel's selection-bias disclaimer. Recomputed
    live, like `/scores` — nothing is persisted."""
    latest = db.execute(select(func.max(PriceBar.bar_date))).scalar()
    if latest is None:
        latest = date.today()
    end = latest - timedelta(days=30 * horizon_months)
    start = end - timedelta(days=365 * years)
    result = run_backtest(
        db,
        get_scoring_config(),
        start=start,
        end=end,
        horizon_months=horizon_months,
        instrument_ids=user_universe_ids(db),
    )
    return ScoreBacktestOut(
        start=start,
        end=end,
        horizon_months=result.horizon_months,
        rebalance_count=result.rebalance_count,
        observations=result.observations,
        instruments_scored=result.instruments_scored,
        buckets=[ScoreBacktestBucketOut(**vars(b)) for b in result.buckets],
        top_minus_bottom=result.top_minus_bottom,
        hit_rate=result.hit_rate,
        periods=[ScoreBacktestPeriodOut(**vars(p)) for p in result.periods],
    )
