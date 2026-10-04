"""Per-instrument qualitative insights: free news/sentiment (Alpha Vantage),
on explicit request only.

New resource area, keyed purely by `instrument_id` — meaningful for a held
position, a watchlist item, or a screener candidate alike, same reasoning
`prices.py`'s `GET /{id}/history` already established for not duplicating
per-instrument endpoints into every table's own router.

The endpoint is a POST, not a GET: this codebase's convention is a GET never
fetches, while a POST is where fetching happens. It does a real network call
on a cache miss — expanding a table row is itself the explicit request.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.analysis.news_service import get_news
from app.db import get_db
from app.messages import Message
from app.models import Instrument
from app.providers.registry import get_alpha_vantage_provider
from app.schemas import (
    MessageOut,
    NewsArticleOut,
    NewsSentimentOut,
)

router = APIRouter(prefix="/api/insights", tags=["insights"])


def _outcome_out(outcome: Message) -> MessageOut:
    return MessageOut(**outcome.as_dict())


def _get_instrument_or_404(db: Session, instrument_id: int) -> Instrument:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found.")
    return instrument


@router.post("/{instrument_id}/news", response_model=NewsSentimentOut)
def get_instrument_news(instrument_id: int, db: Session = Depends(get_db)) -> NewsSentimentOut:
    instrument = _get_instrument_or_404(db, instrument_id)
    row, outcome = get_news(db, instrument, get_alpha_vantage_provider())

    return NewsSentimentOut(
        instrument_id=instrument_id,
        fetched_at=row.fetched_at if row else None,
        articles=[NewsArticleOut(**article) for article in row.articles] if row else [],
        outcome=_outcome_out(outcome),
    )

