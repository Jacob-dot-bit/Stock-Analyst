"""Cache-check-then-fetch-then-persist for Perplexity qualitative commentary.

Same shape as `news_service.py::get_news`, but `ttl_days` is a hard
cost-control decision (`settings.perplexity_cache_ttl_days`, default 7 — see
DEVLOG "Decision 0.3"), not a freshness question, and there is no shared
quota to record: every call here is one explicit user action, never a batch.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.messages import CommentaryOutcome, Message
from app.models import Instrument, InstrumentCommentary
from app.providers.base import ProviderError, RateLimited
from app.providers.llm import CommentaryClient


def get_commentary(
    db: Session, instrument: Instrument, client: CommentaryClient, ttl_days: int
) -> tuple[InstrumentCommentary | None, Message]:
    cached = db.get(InstrumentCommentary, instrument.id)

    if not client.is_enabled():
        return cached, Message(CommentaryOutcome.NO_PROVIDER, {"symbol": instrument.broker_symbol})

    # Date-granularity comparison — see news_service.py::get_news for why:
    # a DateTime column round-trips through SQLite as naive, while
    # datetime.now(UTC) is aware, and comparing them directly raises
    # TypeError.
    if cached is not None and cached.fetched_at.date() >= datetime.now(UTC).date() - timedelta(days=ttl_days):
        return cached, Message(
            CommentaryOutcome.ALREADY_FRESH, {"symbol": instrument.broker_symbol, "days": ttl_days}
        )

    try:
        commentary = client.ask_about(
            instrument.provider_symbol or instrument.broker_symbol,
            name=instrument.name,
            sector=instrument.sector,
        )
    except RateLimited:
        return cached, Message(CommentaryOutcome.RATE_LIMITED, {"symbol": instrument.broker_symbol})
    except ProviderError as exc:
        return cached, Message(
            CommentaryOutcome.FAILED, {"symbol": instrument.broker_symbol, "error": str(exc)}
        )

    now = datetime.now(UTC)
    citations = [asdict(c) for c in commentary.citations]
    if cached is None:
        row = InstrumentCommentary(
            instrument_id=instrument.id,
            fetched_at=now,
            model=commentary.model,
            content=commentary.content,
            citations=citations,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # Two requests for the same instrument raced (e.g. the "Get AI
            # commentary" button double-clicked) and both saw no cached row
            # — the other one already inserted first. Roll back this insert
            # and update its row instead of crashing on the duplicate key.
            db.rollback()
            row = db.get(InstrumentCommentary, instrument.id)
            row.fetched_at = now
            row.model = commentary.model
            row.content = commentary.content
            row.citations = citations
            db.commit()
    else:
        row = cached
        row.fetched_at = now
        row.model = commentary.model
        row.content = commentary.content
        row.citations = citations
        db.commit()

    return row, Message(CommentaryOutcome.UPDATED, {"symbol": instrument.broker_symbol})
