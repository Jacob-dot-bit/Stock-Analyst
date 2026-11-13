"""Compact close series for a set of instruments, in one query — the data
behind the sparklines of the portfolio, watchlist and screener tables."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.corporate_actions.service import load_actions_by_instrument, price_factor_from
from app.models import PriceBar
from app.schemas import SparklineOut


def sparklines(db: Session, instrument_ids: Select, days: int = 90) -> list[SparklineOut]:
    """Split-adjusted closes of the last `days` days for every instrument whose
    id `instrument_ids` (a one-column select) returns. Cache-only: reads
    stored bars, never fetches."""
    since = datetime.now(UTC).date() - timedelta(days=days)

    rows = db.execute(
        select(PriceBar.instrument_id, PriceBar.bar_date, PriceBar.close)
        .where(
            PriceBar.instrument_id.in_(instrument_ids),
            PriceBar.bar_date >= since,
            PriceBar.close.is_not(None),
        )
        .order_by(PriceBar.instrument_id, PriceBar.bar_date)
    ).all()

    actions_by_instrument = load_actions_by_instrument(db, list({instrument_id for instrument_id, _, _ in rows}))
    series: dict[int, list[float]] = {}
    for instrument_id, bar_date, close in rows:
        factor = price_factor_from(actions_by_instrument.get(instrument_id, []), bar_date)
        series.setdefault(instrument_id, []).append(close * factor)

    return [SparklineOut(instrument_id=instrument_id, closes=closes) for instrument_id, closes in series.items()]
