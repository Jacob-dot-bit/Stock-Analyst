"""Decision journal: the user's own written reasoning behind a trade (or a
general/macro note), optionally tied to one instrument — never computed or
scored, same posture as the watchlist's own `note` field or Personal
Policy. See DEVLOG "Decision 3u.68".

Two separate edit endpoints on purpose: editing the original decision
(`thesis`/`review_date`) and adding an outcome reflection later are
conceptually different moments, never bundled into one form/one payload.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingest.service import get_or_create_instrument
from app.models import JournalEntry
from app.schemas import JournalEntryIn, JournalEntryOut, JournalEntryOutcomeIn, JournalEntryUpdateIn
from app.symbols.mapping import looks_like_equity

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.post("", response_model=JournalEntryOut, status_code=status.HTTP_201_CREATED)
def add_journal_entry(payload: JournalEntryIn, db: Session = Depends(get_db)) -> JournalEntry:
    """Write a new decision. `entry_date` is always set to today
    server-side — never accepted from the client, since it's a historical
    fact about when the decision was actually written."""
    instrument_id = None
    if payload.broker_symbol:
        # Same category heuristic `add_watchlist_item` uses for a manual
        # entry with no broker-supplied category — harmless either way
        # here (this instrument isn't tracked/scored just by being
        # referenced), kept for consistency if the user later
        # watches/screens the same symbol.
        category = "STOCK" if looks_like_equity(payload.broker_symbol) else None
        instrument = get_or_create_instrument(db, payload.broker_symbol, category=category)
        db.commit()
        instrument_id = instrument.id

    entry = JournalEntry(instrument_id=instrument_id, thesis=payload.thesis, review_date=payload.review_date)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("", response_model=list[JournalEntryOut])
def list_journal_entries(db: Session = Depends(get_db)) -> list[JournalEntry]:
    """Newest decision first."""
    return list(db.execute(select(JournalEntry).order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())).scalars())


@router.patch("/{entry_id}", response_model=JournalEntryOut)
def update_journal_entry(entry_id: int, payload: JournalEntryUpdateIn, db: Session = Depends(get_db)) -> JournalEntry:
    """Edits the original decision — `thesis`/`review_date` only. The
    edit form always submits both, same convention `WatchlistItemUpdateIn`
    already uses."""
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found.")

    entry.thesis = payload.thesis
    entry.review_date = payload.review_date
    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/{entry_id}/outcome", response_model=JournalEntryOut)
def update_journal_entry_outcome(entry_id: int, payload: JournalEntryOutcomeIn, db: Session = Depends(get_db)) -> JournalEntry:
    """A later, separate moment: reflecting on how the decision played
    out — never bundled into the same edit as the original `thesis`."""
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found.")

    entry.outcome_note = payload.outcome_note
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_journal_entry(entry_id: int, db: Session = Depends(get_db)) -> Response:
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found.")
    db.delete(entry)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
