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

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.corporate_actions.service import load_actions_by_instrument, price_factor_from
from app.db import get_db
from app.ingest.service import get_or_create_instrument
from app.models import Instrument, Position, PriceBar, WatchlistItem
from app.prices.service import is_permanently_unresolvable, latest_bar_date, price_status as _price_status, refresh_instrument
from app.providers.registry import get_provider_chain
from app.routers.portfolio import _resolve_current_price
from app.routers.scoring import score_to_out
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
from app.symbols.mapping import looks_like_equity

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _watchlist_instruments(db: Session) -> list[Instrument]:
    """Watched instruments, excluding anything currently held — see module
    docstring. Same anti-join used by every endpoint below."""
    query = (
        select(Instrument)
        .join(WatchlistItem, WatchlistItem.instrument_id == Instrument.id)
        .where(~select(Position.id).where(Position.instrument_id == Instrument.id).exists())
        .distinct()
    )
    return list(db.execute(query).scalars())


def _watchlist_item_out(db: Session, item: WatchlistItem) -> WatchlistItemOut:
    instrument = item.instrument
    instrument_out = InstrumentOut.model_validate(instrument)
    instrument_out.price_status = _price_status(instrument)

    price, source = _resolve_current_price(db, instrument, {})
    distance = None
    if price is not None and item.target_entry_price:
        distance = (price - item.target_entry_price) / item.target_entry_price * 100

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
    """Add a symbol to the watchlist.

    Best-effort fetches this one instrument's price history right away (not
    budget-limited like the batch refresh, so a slow/throttled provider chain
    can make this take a few seconds) so the new row shows a real price
    immediately rather than waiting for the next global refresh.
    """
    # A watchlist add has no broker-supplied category (unlike an import row),
    # same gap `create_manual_position` already has — without this, `category`
    # stays `None` and `compute_scores` silently excludes the instrument from
    # every pillar, defeating the whole point of watching it. `looks_like_equity`
    # is this codebase's own existing heuristic for exactly this situation
    # ("manual entries, where no category exists" — its own docstring).
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
            detail="Already on your watchlist — edit it from the table instead of "
            "re-adding it.",
        )

    # Checked before the row exists, not after: a symbol no provider recognizes
    # would otherwise sit on the watchlist forever, silently re-asked and
    # re-failed on every future refresh for zero chance of success.
    message = refresh_instrument(db, instrument, get_provider_chain(), force=False)
    db.commit()
    if is_permanently_unresolvable(message) and latest_bar_date(db, instrument.id) is None:
        raise HTTPException(
            status_code=422,
            detail=f"No price provider recognizes '{payload.broker_symbol}' — check the "
            "symbol format, or use the search suggestions instead of typing it by hand.",
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
    items = list(
        db.execute(
            select(WatchlistItem).where(
                ~select(Position.id).where(Position.instrument_id == WatchlistItem.instrument_id).exists()
            )
        ).scalars()
    )
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
    instruments = _watchlist_instruments(db)
    config = get_scoring_config()
    results = compute_scores(db, instruments, config)
    return [score_to_out(result) for result in results]


@router.get("/signals", response_model=list[WatchlistSignalOut])
def get_watchlist_signals(db: Session = Depends(get_db)) -> list[WatchlistSignalOut]:
    """One signal per watched instrument, derived from its own composite
    score and its distance to the target entry price — same transparent,
    rule-based combination as `routers/portfolio.py::_position_signal`
    (see its docstring). Only ever "reinforce" | "hold" | "not_applicable":
    nothing here is held, so "reduce" never applies.
    """
    items = list(
        db.execute(
            select(WatchlistItem).where(
                ~select(Position.id).where(Position.instrument_id == WatchlistItem.instrument_id).exists()
            )
        ).scalars()
    )
    instruments = [item.instrument for item in items]
    config = get_scoring_config()
    scores = {s.instrument_id: s for s in compute_scores(db, instruments, config)}

    out = []
    for item in items:
        instrument = item.instrument
        price, _source = _resolve_current_price(db, instrument, {})
        distance = None
        if price is not None and item.target_entry_price:
            distance = (price - item.target_entry_price) / item.target_entry_price * 100

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
            )
        )
    return out


@router.get("/sparklines", response_model=list[SparklineOut])
def get_watchlist_sparklines(db: Session = Depends(get_db)) -> list[SparklineOut]:
    """Same shape as `GET /api/prices/sparklines`, joined against
    `WatchlistItem` instead of `Position`."""
    since = datetime.now(UTC).date() - timedelta(days=90)

    rows = db.execute(
        select(PriceBar.instrument_id, PriceBar.bar_date, PriceBar.close)
        .join(WatchlistItem, WatchlistItem.instrument_id == PriceBar.instrument_id)
        .where(
            PriceBar.bar_date >= since,
            PriceBar.close.is_not(None),
            ~select(Position.id).where(Position.instrument_id == PriceBar.instrument_id).exists(),
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
