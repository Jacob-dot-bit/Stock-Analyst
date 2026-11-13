"""Composite scores in API shape (`ScoreOut`), shared by the `/scores`
routes of the portfolio, watchlist and gems. Lived in `routers/scoring.py`,
which the other two routers then had to import (DEVLOG "Step 3u.104")."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Instrument
from app.schemas import MetricScoreOut, PillarScoreOut, ScoreOut
from app.scoring.config import get_scoring_config
from app.scoring.service import InstrumentScore, compute_scores


def scores_for(db: Session, instruments: list[Instrument]) -> list[ScoreOut]:
    """Composite scores of `instruments` with the current `scoring.yaml`, in
    API shape — behind the `/scores` of the portfolio, watchlist and
    screener."""
    return [score_to_out(result) for result in compute_scores(db, instruments, get_scoring_config())]


def score_to_out(result: InstrumentScore) -> ScoreOut:
    """One `compute_scores` result in API shape."""
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
