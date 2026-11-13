"""Screener endpoints: a hand-picked candidate list ranked by composite score.

A `ScreenerCandidate` (`app/models.py`) is meant to surface instruments the
user doesn't already know about — if one gets bought or moved to the
watchlist, it stops being "hidden" and should disappear from the ranking, the
same self-healing invariant `routers/watchlist.py` already established for
held instruments. Every read here anti-joins against both `Position` and
`WatchlistItem`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Instrument, ScreenerCandidate, WatchlistItem
from app.prices.sparklines import sparklines
from app.prices.service import price_status as _price_status
from app.routers.portfolio import _resolve_current_price
from app.routers.scoring import scores_for
from app.schemas import (
    InstrumentOut,
    ScreenerCandidateIn,
    ScreenerCandidateOut,
    ScreenerCandidateUpdateIn,
    ScoreOut,
    SparklineOut,
)
from app.symbols.duplicates import check_for_duplicate
from app.tracking import instrument_to_follow, not_held, not_watched

router = APIRouter(prefix="/api/screener", tags=["screener"])


def _screener_instruments(db: Session) -> list[Instrument]:
    """Candidates, excluding anything currently held or already watchlisted —
    see module docstring. Same anti-join used by every endpoint below."""
    query = (
        select(Instrument)
        .join(ScreenerCandidate, ScreenerCandidate.instrument_id == Instrument.id)
        .where(
            not_held(Instrument.id),
            not_watched(Instrument.id),
        )
        .distinct()
    )
    return list(db.execute(query).scalars())


def _screener_candidate_out(db: Session, item: ScreenerCandidate) -> ScreenerCandidateOut:
    instrument = item.instrument
    instrument_out = InstrumentOut.model_validate(instrument)
    instrument_out.price_status = _price_status(instrument)

    price, source = _resolve_current_price(db, instrument, {})

    return ScreenerCandidateOut(
        id=item.id,
        instrument=instrument_out,
        added_at=item.added_at,
        current_price=price,
        price_source=source,
    )


@router.post("", response_model=ScreenerCandidateOut, status_code=status.HTTP_201_CREATED)
def add_screener_candidate(payload: ScreenerCandidateIn, db: Session = Depends(get_db)) -> ScreenerCandidateOut:
    """Add a symbol to the screener candidate list — refusals and the
    immediate price fetch are `tracking.instrument_to_follow`'s."""
    instrument = instrument_to_follow(
        db,
        payload.broker_symbol,
        payload.currency,
        [
            (WatchlistItem, "Already on your watchlist — it's already known, not hidden."),
            (ScreenerCandidate, "Already on your screener list."),
        ],
    )

    item = ScreenerCandidate(instrument_id=instrument.id)
    db.add(item)
    db.commit()

    db.refresh(item)
    duplicate_warning = check_for_duplicate(db, instrument, payload.company_name)
    out = _screener_candidate_out(db, item)
    out.duplicate_warning = duplicate_warning
    return out


@router.get("", response_model=list[ScreenerCandidateOut])
def list_screener_candidates(db: Session = Depends(get_db)) -> list[ScreenerCandidateOut]:
    """Cache-only — never triggers a fetch, same convention as
    `GET /api/watchlist`."""
    items = list(
        db.execute(
            select(ScreenerCandidate).where(
                not_held(ScreenerCandidate.instrument_id),
                not_watched(ScreenerCandidate.instrument_id),
            )
        ).scalars()
    )
    return [_screener_candidate_out(db, item) for item in items]


@router.patch("/{item_id}", response_model=ScreenerCandidateOut)
def update_screener_candidate(
    item_id: int, payload: ScreenerCandidateUpdateIn, db: Session = Depends(get_db)
) -> ScreenerCandidateOut:
    """A candidate has nothing else editable — this exists purely to let a
    row added before `company_name` existed (or without it) opt into ISIN
    duplicate detection retroactively, same as `update_watchlist_item`."""
    item = db.get(ScreenerCandidate, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Screener candidate not found.")

    duplicate_warning = check_for_duplicate(db, item.instrument, payload.company_name)
    out = _screener_candidate_out(db, item)
    out.duplicate_warning = duplicate_warning
    return out


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_screener_candidate(item_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(ScreenerCandidate, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Screener candidate not found.")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/scores", response_model=list[ScoreOut])
def get_screener_scores(db: Session = Depends(get_db)) -> list[ScoreOut]:
    """Every screenable candidate's composite score, ranked highest first —
    unlike `/api/watchlist/scores`, order is the whole point here. A
    candidate with no computable score (`composite=None`, e.g. fundamentals
    not fetched yet) sorts last rather than being dropped, so it's still
    visible as "needs a fundamentals refresh" instead of silently vanishing.
    """
    scores = scores_for(db, _screener_instruments(db))
    scores.sort(key=lambda s: (s.composite is None, -(s.composite or 0)))
    return scores


@router.get("/sparklines", response_model=list[SparklineOut])
def get_screener_sparklines(db: Session = Depends(get_db)) -> list[SparklineOut]:
    """Same shape as `GET /api/watchlist/sparklines`, for candidates that are
    neither held nor watched."""
    return sparklines(
        db,
        select(ScreenerCandidate.instrument_id).where(
            not_held(ScreenerCandidate.instrument_id),
            not_watched(ScreenerCandidate.instrument_id),
        ),
    )
