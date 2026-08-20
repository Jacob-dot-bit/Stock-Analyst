"""Daily-cached FX rates, backing the live portfolio value estimate and the
historical value chart."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FxRate
from app.providers.fx import FxUnavailable, fetch_rate, fetch_rate_range


def get_rate(db: Session, from_currency: str | None, to_currency: str) -> float | None:
    """1 unit of ``from_currency`` in ``to_currency``, or ``None`` if it cannot be found.

    ``None`` on any failure — an unknown currency, a network error, an ECB gap —
    rather than a guess. A wrong FX rate would produce an estimate that looks
    right and isn't, which is exactly what this app avoids everywhere else.
    """
    if not from_currency:
        return None
    if from_currency == to_currency:
        return 1.0

    today = datetime.now(UTC).date()
    cached = db.execute(
        select(FxRate).where(
            FxRate.currency == from_currency,
            FxRate.base_currency == to_currency,
            FxRate.rate_date == today,
        )
    ).scalar_one_or_none()
    if cached is not None:
        return cached.rate

    try:
        rate = fetch_rate(from_currency, to_currency)
    except FxUnavailable:
        return None

    db.add(
        FxRate(currency=from_currency, base_currency=to_currency, rate_date=today, rate=rate)
    )
    db.commit()
    return rate


def get_rate_range(
    db: Session, from_currency: str | None, to_currency: str, start: date, end: date
) -> dict[date, float]:
    """Cached historical rate per day over ``[start, end]``, forward-filled across
    weekends/holidays. One HTTP call per currency pair for the whole span (not one
    per day) — backs the historical value chart. This is a separate, parallel path
    from ``get_rate`` above (today-only): the live portfolio value does not use it.

    ``{}`` if ``from_currency`` is unknown; every day maps to 1.0 when the two
    currencies are the same.
    """
    all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if not from_currency:
        return {}
    if from_currency == to_currency:
        return {d: 1.0 for d in all_days}

    cached = {
        row.rate_date: row.rate
        for row in db.execute(
            select(FxRate).where(
                FxRate.currency == from_currency,
                FxRate.base_currency == to_currency,
                FxRate.rate_date >= start,
                FxRate.rate_date <= end,
            )
        ).scalars()
    }

    # Frankfurter omits weekends/holidays from its own response (live-verified,
    # see providers/fx.py), so "fully cached" means every business day, not
    # every calendar day.
    expected = [d for d in all_days if d.weekday() < 5]
    if any(d not in cached for d in expected):
        try:
            fetched = fetch_rate_range(from_currency, to_currency, start, end)
        except FxUnavailable:
            fetched = {}
        new = False
        for d, rate in fetched.items():
            if d not in cached:
                db.add(FxRate(currency=from_currency, base_currency=to_currency, rate_date=d, rate=rate))
                cached[d] = rate
                new = True
        if new:
            db.commit()

    return _forward_fill(cached, all_days)


def _forward_fill(cached: dict[date, float], days: list[date]) -> dict[date, float]:
    """Carry the last known rate forward through gap days (weekends, holidays,
    provider lag) — never interpolated or guessed, just the most recent value
    already seen, same posture as the price-history forward-fill in
    `history_service.py`."""
    result: dict[date, float] = {}
    last: float | None = None
    for d in days:
        if d in cached:
            last = cached[d]
        if last is not None:
            result[d] = last
    return result
