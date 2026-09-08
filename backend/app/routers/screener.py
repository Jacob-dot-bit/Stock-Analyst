"""Screener endpoints: a hand-picked candidate list ranked by composite score.

A `ScreenerCandidate` (`app/models.py`) is meant to surface instruments the
user doesn't already know about — if one gets bought or moved to the
watchlist, it stops being "hidden" and should disappear from the ranking, the
same self-healing invariant `routers/watchlist.py` already established for
held instruments. Every read here anti-joins against both `Position` and
`WatchlistItem`.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.corporate_actions.service import load_actions_by_instrument, price_factor_from
from app.db import get_db
from app.ingest.service import get_or_create_instrument
from app.models import Instrument, Position, PriceBar, ScreenerCandidate, WatchlistItem
from app.prices.service import is_permanently_unresolvable, latest_bar_date, refresh_instrument
from app.providers.registry import get_provider_chain
from app.routers.portfolio import _price_status, _resolve_current_price
from app.routers.scoring import score_to_out
from app.schemas import (
    InstrumentOut,
    ScreenerCandidateIn,
    ScreenerCandidateOut,
    ScreenerCandidateUpdateIn,
    ScoreOut,
    SparklineOut,
)
from app.scoring.config import get_scoring_config
from app.scoring.service import compute_scores
from app.symbols.duplicates import check_for_duplicate
from app.symbols.mapping import looks_like_equity

router = APIRouter(prefix="/api/screener", tags=["screener"])


def _screener_instruments(db: Session) -> list[Instrument]:
    """Candidates, excluding anything currently held or already watchlisted —
    see module docstring. Same anti-join used by every endpoint below."""
    query = (
        select(Instrument)
        .join(ScreenerCandidate, ScreenerCandidate.instrument_id == Instrument.id)
        .where(
            ~select(Position.id).where(Position.instrument_id == Instrument.id).exists(),
            ~select(WatchlistItem.id).where(WatchlistItem.instrument_id == Instrument.id).exists(),
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
    """Add a symbol to the screener candidate list.

    Best-effort fetches this one instrument's price history right away, same
    reasoning as `add_watchlist_item` (`routers/watchlist.py`).
    """
    category = "STOCK" if looks_like_equity(payload.broker_symbol) else None
    instrument = get_or_create_instrument(db, payload.broker_symbol, currency=payload.currency, category=category)

    already_held = db.execute(
        select(Position.id).where(Position.instrument_id == instrument.id).limit(1)
    ).first()
    if already_held:
        raise HTTPException(
            status_code=400,
            detail="This instrument is currently a live position — track it from the "
            "Portfolio page instead.",
        )

    already_watched = db.execute(
        select(WatchlistItem.id).where(WatchlistItem.instrument_id == instrument.id).limit(1)
    ).first()
    if already_watched:
        raise HTTPException(
            status_code=400,
            detail="Already on your watchlist — it's already known, not hidden.",
        )

    already_candidate = db.execute(
        select(ScreenerCandidate.id).where(ScreenerCandidate.instrument_id == instrument.id).limit(1)
    ).first()
    if already_candidate:
        raise HTTPException(status_code=400, detail="Already on your screener list.")

    # Checked before the row exists, not after — see `add_watchlist_item`
    # (`routers/watchlist.py`) for why: a symbol no provider recognizes must
    # never be persisted, or it silently re-fails on every future refresh.
    message = refresh_instrument(db, instrument, get_provider_chain(), force=False)
    db.commit()
    if is_permanently_unresolvable(message) and latest_bar_date(db, instrument.id) is None:
        raise HTTPException(
            status_code=422,
            detail=f"No price provider recognizes '{payload.broker_symbol}' — check the "
            "symbol format, or use the search suggestions instead of typing it by hand.",
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
                ~select(Position.id).where(Position.instrument_id == ScreenerCandidate.instrument_id).exists(),
                ~select(WatchlistItem.id).where(WatchlistItem.instrument_id == ScreenerCandidate.instrument_id).exists(),
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
    instruments = _screener_instruments(db)
    config = get_scoring_config()
    results = compute_scores(db, instruments, config)
    results.sort(key=lambda r: (r.composite is None, -(r.composite or 0)))
    return [score_to_out(result) for result in results]


@router.get("/sparklines", response_model=list[SparklineOut])
def get_screener_sparklines(db: Session = Depends(get_db)) -> list[SparklineOut]:
    """Same shape as `GET /api/watchlist/sparklines`, joined against
    `ScreenerCandidate` instead."""
    since = date.today() - timedelta(days=90)

    rows = db.execute(
        select(PriceBar.instrument_id, PriceBar.bar_date, PriceBar.close)
        .join(ScreenerCandidate, ScreenerCandidate.instrument_id == PriceBar.instrument_id)
        .where(
            PriceBar.bar_date >= since,
            PriceBar.close.is_not(None),
            ~select(Position.id).where(Position.instrument_id == PriceBar.instrument_id).exists(),
            ~select(WatchlistItem.id).where(WatchlistItem.instrument_id == PriceBar.instrument_id).exists(),
        )
        .order_by(PriceBar.instrument_id, PriceBar.bar_date)
        .distinct()
    ).all()

    actions_by_instrument = load_actions_by_instrument(db, list({instrument_id for instrument_id, _, _ in rows}))
    series: dict[int, list[float]] = {}
    for instrument_id, bar_date, close in rows:
        factor = price_factor_from(actions_by_instrument.get(instrument_id, []), bar_date)
        series.setdefault(instrument_id, []).append(close * factor)

    return [SparklineOut(instrument_id=instrument_id, closes=closes) for instrument_id, closes in series.items()]
