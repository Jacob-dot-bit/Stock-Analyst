"""What the watchlist and the gems (screener) list share: adding an instrument
the user follows without holding it, and the anti-joins that keep a followed
instrument off a list once it is held (or, for the gems, once watched).

Both lists keep their own table and router (`routers/watchlist.py`,
`routers/screener.py`); only the mechanics live here, along with the two
lists of instruments that prices and scoring also read. See DEVLOG "Step 3u.98".
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.ingest.service import get_or_create_instrument
from app.models import Instrument, Position, ScreenerCandidate, WatchlistItem
from app.prices.service import is_permanently_unresolvable, latest_bar_date, refresh_instrument
from app.providers.registry import get_provider_chain
from app.symbols.mapping import looks_like_equity

HELD_DETAIL = "This instrument is currently a live position — track it from the Portfolio page instead."


def not_held(instrument_id: InstrumentedAttribute) -> ColumnElement[bool]:
    """No open position on that instrument — a followed instrument that gets
    bought drops off the list without losing its row."""
    return ~select(Position.id).where(Position.instrument_id == instrument_id).exists()


def not_watched(instrument_id: InstrumentedAttribute) -> ColumnElement[bool]:
    return ~select(WatchlistItem.id).where(WatchlistItem.instrument_id == instrument_id).exists()


def watched_instruments(db: Session) -> list[Instrument]:
    """Instruments on the watchlist and not held."""
    query = (
        select(Instrument)
        .join(WatchlistItem, WatchlistItem.instrument_id == Instrument.id)
        .where(not_held(Instrument.id))
        .distinct()
    )
    return list(db.execute(query).scalars())


def gem_instruments(db: Session) -> list[Instrument]:
    """Instruments on the gems list, neither held nor watched."""
    query = (
        select(Instrument)
        .join(ScreenerCandidate, ScreenerCandidate.instrument_id == Instrument.id)
        .where(not_held(Instrument.id), not_watched(Instrument.id))
        .distinct()
    )
    return list(db.execute(query).scalars())


def instrument_to_follow(
    db: Session,
    broker_symbol: str,
    currency: str | None,
    already_on: list[tuple[type, str]],
) -> Instrument:
    """The instrument for a new watchlist/gems row, or an HTTP error.

    Refused (400) when it is held, or already has a row in one of the
    `already_on` tables (each with its own message). Refused (422) when no
    price provider recognizes the symbol — checked before the row exists, or
    it would sit on the list forever, re-asked and re-failed on every refresh.
    Best-effort fetches its price history right away (not budget-limited like
    the batch refresh), so the new row shows a real price immediately.
    """
    # No broker-supplied category here (unlike an import row): without one,
    # `compute_scores` would silently leave the instrument out of every pillar.
    # `looks_like_equity` is the existing heuristic for manual entries.
    category = "STOCK" if looks_like_equity(broker_symbol) else None
    instrument = get_or_create_instrument(db, broker_symbol, currency=currency, category=category)

    if db.execute(select(Position.id).where(Position.instrument_id == instrument.id).limit(1)).first():
        raise HTTPException(status_code=400, detail=HELD_DETAIL)
    for model, detail in already_on:
        if db.execute(select(model.id).where(model.instrument_id == instrument.id).limit(1)).first():
            raise HTTPException(status_code=400, detail=detail)

    message = refresh_instrument(db, instrument, get_provider_chain(), force=False)
    db.commit()
    if is_permanently_unresolvable(message) and latest_bar_date(db, instrument.id) is None:
        raise HTTPException(
            status_code=422,
            detail=f"No price provider recognizes '{broker_symbol}' — check the "
            "symbol format, or use the search suggestions instead of typing it by hand.",
        )
    return instrument
