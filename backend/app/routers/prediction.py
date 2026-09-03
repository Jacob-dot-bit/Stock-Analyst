"""Phase 1 of a real, backtestable Discovery prediction — see `prediction/
service.py`'s module docstring for why this only touches price history
(DEVLOG "Decision 3u.22")."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.prediction.model import run_backtest
from app.prediction.service import backfill_history, get_backfill_progress
from app.providers.registry import get_provider_chain
from app.schemas import BacktestReportOut, PredictionBackfillReportOut, PredictionBackfillStatusOut

router = APIRouter(prefix="/api/prediction", tags=["prediction"])


@router.post("/backfill-history", response_model=PredictionBackfillReportOut)
def backfill_history_endpoint(db: Session = Depends(get_db)) -> PredictionBackfillReportOut:
    """Pull several years of daily price history for the already-priced
    Discovery universe, one call per instrument. Runs synchronously and
    returns when done — this call itself blocks for the duration (roughly
    one throttle interval per instrument), hence `GET .../status` below for
    a real progress bar polled from a separate request while this one is
    still working.
    """
    report = backfill_history(db, get_provider_chain())
    if report is None:
        return PredictionBackfillReportOut(already_running=True)
    return PredictionBackfillReportOut(**report.as_dict())


@router.get("/backfill-history/status", response_model=PredictionBackfillStatusOut)
def backfill_history_status() -> PredictionBackfillStatusOut:
    """Live progress of the backfill currently in flight, or the last
    completed one — same shape and reasoning as
    `GET /api/scoring/fundamentals/refresh/status`."""
    progress = get_backfill_progress()
    return PredictionBackfillStatusOut(
        running=progress.running,
        total=progress.total,
        done=progress.done,
        current_symbol=progress.current_symbol,
        started_at=progress.started_at,
        finished_at=progress.finished_at,
        report=PredictionBackfillReportOut(**progress.report.as_dict()) if progress.report else None,
    )


@router.post("/backtest", response_model=BacktestReportOut)
def backtest_endpoint(db: Session = Depends(get_db)) -> BacktestReportOut:
    """Train a walk-forward-validated logistic regression on the
    price-only feature set (`prediction/features.py`) and report honest,
    unrounded metrics on the held-out test period. Recomputed live on
    every call — the dataset is small enough (a few thousand rows) that
    this costs well under a second, matching this app's existing
    recompute-don't-persist convention for `compute_scores`. Not yet wired
    into the Discovery UI — see DEVLOG "Decision 3u.23".
    """
    report = run_backtest(db)
    return BacktestReportOut(**report.as_dict())
