"""Weekly summary: one descriptive "what to look at this week" view.

Composes indicators the app already computes and shows elsewhere — personal
policy gaps, allocation gaps, position/watchlist signals, journal review
dates, price freshness — into a single read. No new computation and no
trade suggestion: every row is a fact the user can already find on its own
page, gathered here so a weekly check-in starts in one place. See DEVLOG
"Decision 3u.79".

Calls the other routers' endpoint functions directly rather than duplicating
their logic, so this view can never drift from the pages it summarises.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Instrument, JournalEntry, WatchlistItem
from app.routers.portfolio import (
    _positions_figures_and_total,
    get_allocation,
    get_attention,
    get_personal_policy_gaps,
    get_position_signals,
)
from app.routers.watchlist import get_watchlist_signals
from app.schemas import (
    WeeklyJournalDueOut,
    WeeklyPositionFlagOut,
    WeeklySummaryOut,
    WeeklyWatchlistFlagOut,
)

router = APIRouter(prefix="/api/weekly-summary", tags=["weekly-summary"])

#: Journal entries due within this many days (or already overdue) appear.
WINDOW_DAYS = 7

#: A high-score watchlist item this close above its target entry price (in
#: percent) is surfaced alongside the ones already at/below target.
NEAR_TARGET_PCT = 5.0

#: `GET /attention` kinds that describe data quality rather than a gap.
_DATA_RELIABILITY_KINDS = {"price_error", "price_stale", "unresolved_instruments"}


def _instrument_weights(db: Session) -> dict[int, float]:
    """Share of total portfolio value per instrument, summed across accounts
    — same figures as `GET /risk/concentration`, keyed by instrument."""
    positions, figures, total_value = _positions_figures_and_total(db)
    if not total_value:
        return {}
    values: dict[int, float] = defaultdict(float)
    for p in positions:
        value, *_ = figures[p.id]
        if value is not None:
            values[p.instrument_id] += value
    return {instrument_id: round(value / total_value * 100, 2) for instrument_id, value in values.items()}


@router.get("", response_model=WeeklySummaryOut)
def get_weekly_summary(db: Session = Depends(get_db)) -> WeeklySummaryOut:
    """Cache-only, never triggers a fetch. Every section is empty when
    nothing in it currently warrants a look."""
    today = datetime.now(UTC).date()
    window_end = today + timedelta(days=WINDOW_DAYS)

    allocation_gaps = [row for row in get_allocation(db) if row.state in ("under", "over")]

    weights = _instrument_weights(db)
    signals = [s for s in get_position_signals(db) if s.signal in ("reinforce", "reduce")]
    instruments = {
        i.id: i
        for i in db.execute(select(Instrument).where(Instrument.id.in_([s.instrument_id for s in signals]))).scalars()
    }
    position_flags = [
        WeeklyPositionFlagOut(
            instrument_id=s.instrument_id,
            symbol=instruments[s.instrument_id].broker_symbol,
            name=instruments[s.instrument_id].name,
            signal=s.signal,
            composite_score=s.composite_score,
            score_band=s.score_band,
            category=s.category,
            allocation_state=s.allocation_state,
            gap_pct=s.gap_pct,
            weight_percent=weights.get(s.instrument_id),
        )
        for s in signals
    ]
    position_flags.sort(key=lambda f: f.weight_percent or 0.0, reverse=True)

    watch_items = {
        item.instrument_id: item
        for item in db.execute(select(WatchlistItem).options(joinedload(WatchlistItem.instrument))).scalars()
    }
    watchlist_flags = []
    for s in get_watchlist_signals(db):
        distance = s.distance_to_target_pct
        if distance is None:
            continue
        if distance <= 0:
            kind = "target_reached"
        elif distance <= NEAR_TARGET_PCT and s.score_band == "high":
            kind = "near_target_high_score"
        else:
            continue
        item = watch_items[s.instrument_id]
        watchlist_flags.append(
            WeeklyWatchlistFlagOut(
                instrument_id=s.instrument_id,
                symbol=item.instrument.broker_symbol,
                name=item.instrument.name,
                kind=kind,
                composite_score=s.composite_score,
                score_band=s.score_band,
                distance_to_target_pct=round(distance, 2),
                target_entry_price=item.target_entry_price,
            )
        )
    watchlist_flags.sort(key=lambda f: f.distance_to_target_pct)

    entries = db.execute(
        select(JournalEntry)
        .options(joinedload(JournalEntry.instrument))
        .where(
            JournalEntry.review_date.is_not(None),
            JournalEntry.review_date <= window_end,
            JournalEntry.outcome_note.is_(None),
        )
        .order_by(JournalEntry.review_date, JournalEntry.id)
    ).scalars()
    journal_due = [
        WeeklyJournalDueOut(
            id=e.id,
            symbol=e.instrument.broker_symbol if e.instrument else None,
            thesis=e.thesis,
            entry_date=e.entry_date,
            review_date=e.review_date,
            overdue=e.review_date < today,
        )
        for e in entries
    ]

    data_reliability = [item for item in get_attention(db) if item.kind in _DATA_RELIABILITY_KINDS]

    return WeeklySummaryOut(
        as_of=today,
        window_end=window_end,
        policy_gaps=get_personal_policy_gaps(db),
        allocation_gaps=allocation_gaps,
        position_flags=position_flags,
        watchlist_flags=watchlist_flags,
        journal_due=journal_due,
        data_reliability=data_reliability,
    )
