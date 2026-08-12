"""Fetching and caching daily price history.

Design driven by one measured constraint: free providers rate-limit hard. Yahoo
returned 429 after four rapid requests and stayed blocked for over a minute. With 38
holdings, a naive "refresh everything now" would fail most of the way through and
leave the user with no idea what did or did not update.

So the rules here are:

* **Cache first.** Bars already stored are never re-fetched. A refresh only asks for
  the days that are missing, which after the initial load is usually a handful.
* **Skip what is already fresh.** An instrument updated today is left alone.
* **Serialised, with a time budget.** Work stops cleanly when the budget runs out and
  says how many instruments remain, instead of hanging or half-failing.
* **Per-instrument outcomes.** Every instrument reports what happened to it. Partial
  success is the normal case, not an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.messages import Message, PriceOutcome
from app.models import Instrument, MappingStatus, PriceBar
from app.providers.base import FetchResult, ProviderChain

#: How much history to load the first time. 400 calendar days leaves enough trading
#: days for a 200-day moving average plus a margin, which phase 3 will need.
INITIAL_HISTORY_DAYS = 400


@dataclass
class RefreshReport:
    outcomes: list[Message] = field(default_factory=list)
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    remaining: int = 0

    def as_dict(self) -> dict:
        return {
            "outcomes": [outcome.as_dict() for outcome in self.outcomes],
            "updated": self.updated,
            "skipped": self.skipped,
            "failed": self.failed,
            "remaining": self.remaining,
        }


def _today() -> date:
    return datetime.now(UTC).date()


def latest_bar_date(db: Session, instrument_id: int) -> date | None:
    return db.execute(
        select(PriceBar.bar_date)
        .where(PriceBar.instrument_id == instrument_id)
        .order_by(PriceBar.bar_date.desc())
        .limit(1)
    ).scalar_one_or_none()


def _store_bars(db: Session, instrument: Instrument, result: FetchResult) -> int:
    """Upsert bars. Returns how many rows were newly inserted.

    Existing dates are updated rather than duplicated: providers revise recent bars
    (a close can be adjusted after hours), and the unique constraint would otherwise
    reject the whole batch.
    """
    existing = {
        row.bar_date: row
        for row in db.execute(
            select(PriceBar).where(PriceBar.instrument_id == instrument.id)
        ).scalars()
    }

    inserted = 0
    for bar in result.bars:
        row = existing.get(bar.bar_date)
        if row is None:
            db.add(
                PriceBar(
                    instrument_id=instrument.id,
                    bar_date=bar.bar_date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    provider=result.provider,
                )
            )
            inserted += 1
        else:
            row.open, row.high, row.low = bar.open, bar.high, bar.low
            row.close, row.volume = bar.close, bar.volume
            row.provider = result.provider
            row.fetched_at = datetime.now(UTC)

    return inserted


def refresh_instrument(
    db: Session, instrument: Instrument, chain: ProviderChain, force: bool = False
) -> Message:
    """Bring one instrument's history up to date. Returns what happened."""
    symbol = instrument.broker_symbol

    if not instrument.provider_symbol or instrument.mapping_status == MappingStatus.UNRESOLVED:
        return Message(PriceOutcome.NOT_MAPPED, {"symbol": symbol})

    if not chain.enabled_providers():
        return Message(PriceOutcome.NO_PROVIDER, {"symbol": symbol})

    today = _today()
    last = latest_bar_date(db, instrument.id)

    if not force and last is not None and last >= _last_expected_trading_day(today):
        return Message(PriceOutcome.ALREADY_FRESH, {"symbol": symbol})

    # Re-fetch a short overlap so revised closes are picked up, instead of trusting
    # that a bar never changes once written.
    start = today - timedelta(days=INITIAL_HISTORY_DAYS) if last is None else last - timedelta(days=5)

    result = chain.fetch_daily(instrument.provider_symbol, start, today)

    if not result.succeeded:
        provider = result.attempts[-1].provider if result.attempts else None
        if result.rate_limited:
            return Message(PriceOutcome.RATE_LIMITED, {"symbol": symbol, "provider": provider})
        reason = result.attempts[-1].reason if result.attempts else None
        if reason == "symbol_not_found":
            return Message(PriceOutcome.SYMBOL_NOT_FOUND, {"symbol": symbol, "provider": provider})
        return Message(PriceOutcome.FAILED, {"symbol": symbol, "provider": provider})

    inserted = _store_bars(db, instrument, result)

    # A provider answering with real data is the only honest proof that the symbol
    # mapping is right. Until this point it was only a plausible conversion.
    instrument.verified_at = datetime.now(UTC)
    instrument.verified_provider = result.provider
    if instrument.mapping_status == MappingStatus.RESOLVED:
        instrument.mapping_status = MappingStatus.VERIFIED

    return Message(
        PriceOutcome.UPDATED,
        {"symbol": symbol, "bars": inserted, "provider": result.provider},
    )


def _last_expected_trading_day(today: date) -> date:
    """The most recent weekday, used to decide whether stored data is current.

    Ignores public holidays on purpose: treating a holiday as stale costs one
    request that returns nothing new, whereas treating a real gap as fresh would
    silently serve outdated prices.
    """
    day = today
    while day.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        day -= timedelta(days=1)
    return day


def refresh_many(
    db: Session,
    instruments: list[Instrument],
    chain: ProviderChain,
    budget_seconds: float = 60.0,
    force: bool = False,
) -> RefreshReport:
    """Refresh instruments one by one until done or out of time.

    The budget exists because providers force us to space requests out: refreshing
    every holding can take minutes. Rather than block that long or fake progress, the
    caller gets what was achieved plus a count of what is left, and can simply ask
    again.
    """
    report = RefreshReport()
    started = datetime.now(UTC)

    for index, instrument in enumerate(instruments):
        elapsed = (datetime.now(UTC) - started).total_seconds()
        if elapsed > budget_seconds and index < len(instruments):
            report.remaining = len(instruments) - index
            report.outcomes.append(
                Message(PriceOutcome.BUDGET_REACHED, {"remaining": report.remaining})
            )
            break

        outcome = refresh_instrument(db, instrument, chain, force=force)
        report.outcomes.append(outcome)

        if outcome.code == PriceOutcome.UPDATED:
            report.updated += 1
        elif outcome.code == PriceOutcome.ALREADY_FRESH:
            report.skipped += 1
        else:
            report.failed += 1

        # Committing per instrument means a rate limit halfway through does not
        # discard the work already done.
        db.commit()

    _add_fallback_hint(report, chain)
    return report


def _add_fallback_hint(report: RefreshReport, chain: ProviderChain) -> None:
    """Turn a wall of "rate limited" into something the user can act on.

    When every instrument was throttled and no keyed provider is configured, repeating
    "rate limited" 38 times says nothing useful. What the user needs to know is that a
    free fallback key would unblock them.
    """
    throttled = [o for o in report.outcomes if o.code == PriceOutcome.RATE_LIMITED]
    if not throttled or report.updated:
        return

    # A keyed provider is one that is disabled without configuration.
    has_keyed_fallback = any(
        provider.is_enabled() for provider in chain.providers if provider.name != "yahoo"
    )
    if not has_keyed_fallback:
        report.outcomes.append(Message(PriceOutcome.NO_FALLBACK_CONFIGURED))
