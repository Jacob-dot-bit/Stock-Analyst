"""Cache-check-then-fetch-then-persist for Alpha Vantage news/sentiment.

Same shape as `prices/fx_service.py::get_rate`, but an N-day TTL instead of
today-only — free source, no cost pressure, so a shorter TTL than
Perplexity's is fine.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.messages import Message, NewsOutcome
from app.models import Instrument, NewsSentiment
from app.prices.provider_usage import record_usage
from app.providers.alpha_vantage import AlphaVantageProvider
from app.providers.base import InstrumentRef, ProviderError, RateLimited

#: Free source, no cost pressure — worth refetching daily, unlike
#: Perplexity's 7-day cost-driven TTL.
NEWS_CACHE_TTL_DAYS = 1


def get_news(
    db: Session, instrument: Instrument, provider: AlphaVantageProvider
) -> tuple[NewsSentiment | None, Message]:
    """Cached row (if any) plus what happened, same tuple shape every caller
    in this codebase's newer endpoints already expects."""
    cached = db.get(NewsSentiment, instrument.id)

    if not provider.is_enabled():
        return cached, Message(NewsOutcome.NO_PROVIDER, {"symbol": instrument.broker_symbol})

    # Date-granularity comparison, not a full datetime one: a DateTime column
    # round-trips through SQLite as naive (tzinfo is not preserved), while
    # `datetime.now(UTC)` is aware — comparing them directly raises
    # TypeError. `.date()` on both sides sidesteps the mismatch entirely,
    # same idiom `fundamentals/service.py::_already_fresh_today` and
    # `prices/service.py::_asked_today` already use for their own freshness
    # checks.
    if cached is not None and cached.fetched_at.date() >= datetime.now(UTC).date() - timedelta(
        days=NEWS_CACHE_TTL_DAYS
    ):
        return cached, Message(
            NewsOutcome.ALREADY_FRESH, {"symbol": instrument.broker_symbol, "days": NEWS_CACHE_TTL_DAYS}
        )

    if not instrument.provider_symbol:
        return cached, Message(NewsOutcome.NOT_MAPPED, {"symbol": instrument.broker_symbol})

    ref = InstrumentRef(
        provider_symbol=instrument.provider_symbol,
        broker_symbol=instrument.broker_symbol,
        name=instrument.name,
        category=instrument.category,
    )

    try:
        articles = provider.fetch_news_sentiment(ref)
    except RateLimited:
        return cached, Message(NewsOutcome.RATE_LIMITED, {"symbol": instrument.broker_symbol})
    except ProviderError as exc:
        return cached, Message(NewsOutcome.FAILED, {"symbol": instrument.broker_symbol, "error": str(exc)})
    finally:
        # Only counted here — the one point a real network call actually
        # happened — same account/quota bucket as price fetches.
        record_usage(db, "alpha_vantage")

    payload = [{**asdict(a), "time_published": a.time_published.isoformat()} for a in articles]
    now = datetime.now(UTC)
    if cached is None:
        row = NewsSentiment(instrument_id=instrument.id, fetched_at=now, articles=payload)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # Two requests for the same instrument raced (e.g. a table row
            # expanded twice in quick succession) and both saw no cached row
            # — the other one already inserted first. Roll back this insert
            # and update its row instead of crashing on the duplicate key.
            db.rollback()
            row = db.get(NewsSentiment, instrument.id)
            row.fetched_at, row.articles = now, payload
            db.commit()
    else:
        row = cached
        row.fetched_at, row.articles = now, payload
        db.commit()

    if not articles:
        return row, Message(NewsOutcome.EMPTY, {"symbol": instrument.broker_symbol})
    return row, Message(NewsOutcome.UPDATED, {"symbol": instrument.broker_symbol, "articles": len(articles)})
