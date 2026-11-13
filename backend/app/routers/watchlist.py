"""Watchlist endpoints: instruments followed without being held.

A `WatchlistItem` (`app/models.py`) is meant to be for an *unheld* instrument —
see its own docstring. Nothing at the database level enforces that, so this
router enforces both directions of it: adding an already-held instrument is
rejected outright, and every read here anti-joins against `Position` so a
watchlisted symbol that later gets bought simply disappears from the
watchlist (without losing its row — `target_entry_price`/`note` survive and
reappear if it's ever fully sold again).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Instrument, WatchlistItem
from app.portfolio.valuation import resolve_current_price
from app.prices.sparklines import sparklines
from app.prices.service import price_status as _price_status
from app.routers.scoring import scores_for
from app.schemas import (
    InstrumentOut,
    ScoreOut,
    SparklineOut,
    WatchlistItemIn,
    WatchlistItemOut,
    WatchlistItemUpdateIn,
    WatchlistSignalOut,
)
from app.scoring.config import get_scoring_config
from app.scoring.service import compute_scores, score_band
from app.symbols.duplicates import check_for_duplicate
from app.tracking import instrument_to_follow, not_held

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

#: A high-score item this close above its target entry price (in percent) is
#: flagged alongside the ones already at/below target.
NEAR_TARGET_PCT = 5.0


def distance_to_target(price: float | None, target: float | None) -> float | None:
    """Percent above (+) or below (-) the target entry price; None when
    either side is missing, never guessed."""
    if price is None or not target:
        return None
    return (price - target) / target * 100


def target_flag(distance: float | None, band: str) -> str | None:
    """The one definition of "worth a look" for a watched item, read by the
    weekly summary and the nav bell alike: "target_reached" (at or below
    target, any score) or "near_target_high_score" (within `NEAR_TARGET_PCT`
    above, with a high score). None otherwise."""
    if distance is None:
        return None
    if distance <= 0:
        return "target_reached"
    if distance <= NEAR_TARGET_PCT and band == "high":
        return "near_target_high_score"
    return None


def _unheld_items(db: Session) -> list[WatchlistItem]:
    """Watchlist rows whose instrument is not currently held."""
    return list(db.execute(select(WatchlistItem).where(not_held(WatchlistItem.instrument_id))).scalars())


def _watchlist_instruments(db: Session) -> list[Instrument]:
    """Watched instruments, excluding anything currently held — see module
    docstring. Same anti-join used by every endpoint below."""
    query = (
        select(Instrument)
        .join(WatchlistItem, WatchlistItem.instrument_id == Instrument.id)
        .where(not_held(Instrument.id))
        .distinct()
    )
    return list(db.execute(query).scalars())


def _watchlist_item_out(db: Session, item: WatchlistItem) -> WatchlistItemOut:
    instrument = item.instrument
    instrument_out = InstrumentOut.model_validate(instrument)
    instrument_out.price_status = _price_status(instrument)

    price, source = resolve_current_price(db, instrument, {})
    distance = distance_to_target(price, item.target_entry_price)

    return WatchlistItemOut(
        id=item.id,
        instrument=instrument_out,
        added_at=item.added_at,
        target_entry_price=item.target_entry_price,
        note=item.note,
        current_price=price,
        price_source=source,
        distance_to_target_pct=distance,
    )


@router.post("", response_model=WatchlistItemOut, status_code=status.HTTP_201_CREATED)
def add_watchlist_item(payload: WatchlistItemIn, db: Session = Depends(get_db)) -> WatchlistItemOut:
    """Add a symbol to the watchlist — refusals and the immediate price
    fetch are `tracking.instrument_to_follow`'s."""
    instrument = instrument_to_follow(
        db,
        payload.broker_symbol,
        payload.currency,
        [(WatchlistItem, "Already on your watchlist — edit it from the table instead of re-adding it.")],
    )

    item = WatchlistItem(
        instrument_id=instrument.id,
        target_entry_price=payload.target_entry_price,
        note=payload.note,
    )
    db.add(item)
    db.commit()

    db.refresh(item)
    duplicate_warning = check_for_duplicate(db, instrument, payload.company_name)
    out = _watchlist_item_out(db, item)
    out.duplicate_warning = duplicate_warning
    return out


@router.get("", response_model=list[WatchlistItemOut])
def list_watchlist(db: Session = Depends(get_db)) -> list[WatchlistItemOut]:
    """Cache-only — never triggers a fetch, same convention as
    `GET /api/prices/{id}/history`."""
    items = _unheld_items(db)
    return [_watchlist_item_out(db, item) for item in items]


@router.patch("/{item_id}", response_model=WatchlistItemOut)
def update_watchlist_item(
    item_id: int, payload: WatchlistItemUpdateIn, db: Session = Depends(get_db)
) -> WatchlistItemOut:
    item = db.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")

    item.target_entry_price = payload.target_entry_price
    item.note = payload.note
    db.commit()
    db.refresh(item)

    duplicate_warning = check_for_duplicate(db, item.instrument, payload.company_name)
    out = _watchlist_item_out(db, item)
    out.duplicate_warning = duplicate_warning
    return out


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_watchlist_item(item_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/scores", response_model=list[ScoreOut])
def get_watchlist_scores(db: Session = Depends(get_db)) -> list[ScoreOut]:
    return scores_for(db, _watchlist_instruments(db))


@router.get("/signals", response_model=list[WatchlistSignalOut])
def get_watchlist_signals(db: Session = Depends(get_db)) -> list[WatchlistSignalOut]:
    """One signal per watched instrument, derived from its own composite
    score and its distance to the target entry price — same transparent,
    rule-based combination as `routers/portfolio.py::_position_signal`
    (see its docstring). Only ever "reinforce" | "hold" | "not_applicable":
    nothing here is held, so "reduce" never applies.
    """
    items = _unheld_items(db)
    instruments = [item.instrument for item in items]
    config = get_scoring_config()
    scores = {s.instrument_id: s for s in compute_scores(db, instruments, config)}

    out = []
    for item in items:
        instrument = item.instrument
        price, _source = resolve_current_price(db, instrument, {})
        distance = distance_to_target(price, item.target_entry_price)

        score_result = scores.get(instrument.id)
        composite = score_result.composite if score_result else None
        band = score_band(composite)

        if distance is None or band == "none":
            signal = "not_applicable"
        elif distance <= 0 and band == "high":
            signal = "reinforce"
        else:
            signal = "hold"

        out.append(
            WatchlistSignalOut(
                instrument_id=instrument.id,
                signal=signal,
                composite_score=composite,
                score_band=band,
                distance_to_target_pct=distance,
                target_flag=target_flag(distance, band),
            )
        )
    return out


@router.get("/sparklines", response_model=list[SparklineOut])
def get_watchlist_sparklines(db: Session = Depends(get_db)) -> list[SparklineOut]:
    """Same shape as `GET /api/prices/sparklines`, for watched, unheld instruments."""
    return sparklines(
        db,
        select(WatchlistItem.instrument_id).where(not_held(WatchlistItem.instrument_id)),
    )
