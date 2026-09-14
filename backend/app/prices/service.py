"""Fetching and caching daily price history.

Design driven by one measured constraint: free providers rate-limit hard. Yahoo
returned 429 after four rapid requests and stayed blocked for over a minute. With 38
holdings, a naive "refresh everything now" would fail most of the way through and
leave the user with no idea what did or did not update.

So the rules here are:

* **Cache first.** Bars already stored are never re-fetched. A refresh only asks for
  the days that are missing, which after the initial load is usually a handful.
* **Skip what is already fresh.** An instrument updated today is left alone.
* **A handful of instruments in flight at once, with a time budget.** Different
  instruments usually land on different providers, so processing several at a time
  shortens the wait without spending any more quota than a sequential run would
  (see DEVLOG "Decision 3n.1") — work still stops cleanly when the budget runs out
  and says how many instruments remain, instead of hanging or half-failing.
* **Per-instrument outcomes.** Every instrument reports what happened to it. Partial
  success is the normal case, not an error.
"""

from __future__ import annotations

import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.messages import Message, PriceOutcome
from app.models import Instrument, MappingStatus, PriceBar
from app.prices.provider_usage import record_usage
from app.providers.base import FetchResult, InstrumentRef, ProviderChain

#: An instrument checked within this many days counts as "fresh" rather than "stale".
#: Wider than one day because weekends and holidays mean "checked two days ago" is
#: still the most current data available, not a sign anything is wrong.
FRESH_WINDOW_DAYS = 4

#: Serialises refreshes across the whole process. Two runs at once double the quota
#: spent and gain nothing — which happened for real when a click in the browser and a
#: call from a terminal overlapped, re-fetching six instruments that had just landed.
_refresh_lock = threading.Lock()


def price_status(instrument: Instrument) -> str:
    """One of 'fresh' | 'stale' | 'error' | 'not_priceable' | 'unmapped'.

    Drives the price-status badge wherever an instrument's market price is
    shown (positions, screener, watchlist, discovery). Computed from fields
    already written by the import and refresh pipelines — nothing new to
    maintain.
    """
    if instrument.not_priceable_reason:
        return "not_priceable"
    if instrument.mapping_status == MappingStatus.UNRESOLVED:
        return "unmapped"
    if instrument.verified_at is None:
        # Mapped and priceable, but no provider has ever returned data for it —
        # distinct from "never asked" (checked_at is also None in that case, which
        # only happens right after import, before any refresh has run).
        return "error" if instrument.prices_checked_at else "unmapped"

    checked = instrument.prices_checked_at
    if checked is not None and (datetime.now(UTC).date() - checked.date()).days <= FRESH_WINDOW_DAYS:
        return "fresh"
    return "stale"

#: How much history to load the first time. 400 calendar days leaves enough trading
#: days for a 200-day moving average plus a margin, which phase 3 will need.
INITIAL_HISTORY_DAYS = 400

#: How many instruments to refresh concurrently. Each provider's own Throttle still
#: paces calls to *itself* regardless of this number — raising it only lets more
#: *different* providers make progress at once instead of queueing for a free slot.
#: Doubled from the original 4 on request (DEVLOG "Decision 3n.2") after 3n.1's live
#: run showed the slow, heavily-throttled providers (Polygon/Alpha Vantage, 12s/call)
#: were naturally self-limiting regardless of pool size, while faster ones sat waiting
#: for a slot. Traded off against being a less "polite" API client — more
#: simultaneous connections to free tiers, a bit more SQLite write contention — not
#: raised further than this without more evidence it is still worth it.
MAX_CONCURRENT_REFRESHES = 8


@dataclass
class RefreshProgress:
    """Live state of the run currently in flight (or the last completed one).

    Polled from a separate request while a refresh is in progress. FastAPI serves
    each sync endpoint on its own thread, so a GET here runs concurrently with the
    POST that is still working through the instrument list — no background task or
    second DB session required. This is a *real* progress count (instruments
    actually settled so far out of the total this run has to process), not a
    simulated animation: the codebase deliberately rejected a fake progress bar
    before, and this keeps that principle while still giving the user live feedback.
    """

    running: bool = False
    total: int = 0
    done: int = 0
    current_symbol: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report: "RefreshReport | None" = None


_progress_lock = threading.Lock()
_progress = RefreshProgress()


def _set_progress(**kwargs) -> None:
    with _progress_lock:
        for key, value in kwargs.items():
            setattr(_progress, key, value)


def _advance_progress(current_symbol: str | None) -> None:
    with _progress_lock:
        _progress.done += 1
        _progress.current_symbol = current_symbol


def get_refresh_progress() -> RefreshProgress:
    """A snapshot safe to read from another thread while a refresh is running."""
    with _progress_lock:
        return replace(_progress)


@dataclass
class RefreshReport:
    outcomes: list[Message] = field(default_factory=list)
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    #: Instruments that cannot have a price at all. Counted apart from failures: a
    #: non-transferable right is not something that went wrong.
    not_priceable: int = 0
    remaining: int = 0

    def as_dict(self) -> dict:
        return {
            "outcomes": [outcome.as_dict() for outcome in self.outcomes],
            "updated": self.updated,
            "skipped": self.skipped,
            "failed": self.failed,
            "not_priceable": self.not_priceable,
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


#: Outcomes that will never change on their own: a wrong ticker format, a
#: symbol no provider's mapping heuristics could even attempt, or an
#: instrument already flagged as having no market. Deliberately excludes
#: NO_PROVIDER (a local config gap, not the symbol's fault) and RATE_LIMITED
#: (today's throttling, not tomorrow's) — both can still resolve later.
_UNRESOLVABLE_PRICE_CODES = {
    PriceOutcome.SYMBOL_NOT_FOUND,
    PriceOutcome.NOT_MAPPED,
    PriceOutcome.NOT_PRICEABLE,
}


def is_permanently_unresolvable(message: Message) -> bool:
    """True when no price provider will ever answer for this exact symbol.

    Meant for add-time checks (watchlist, screener): a symbol this comes back
    true for would otherwise sit forever, re-asked and re-failed on every
    future batch refresh for no chance of success.
    """
    return message.code in _UNRESOLVABLE_PRICE_CODES


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

    # An ISIN alone is enough for Frankfurt, so an instrument with one is worth trying
    # even when no provider symbol could be derived.
    # Asking providers about something that has no market wastes requests and reports
    # a failure that can never be fixed.
    if instrument.not_priceable_reason:
        return Message(PriceOutcome.NOT_PRICEABLE, {"symbol": symbol})

    if instrument.mapping_status == MappingStatus.UNRESOLVED and not instrument.isin:
        return Message(PriceOutcome.NOT_MAPPED, {"symbol": symbol})
    if not instrument.provider_symbol and not instrument.isin:
        return Message(PriceOutcome.NOT_MAPPED, {"symbol": symbol})

    if not chain.enabled_providers():
        return Message(PriceOutcome.NO_PROVIDER, {"symbol": symbol})

    today = _today()
    last = latest_bar_date(db, instrument.id)

    # Freshness is "did we already ask today", not "is the newest bar from today".
    # Free providers lag: Twelve Data's most recent bar was two days old, so a
    # bar-date test marks every instrument stale forever and re-fetches the whole
    # portfolio on every run — exactly what the cache exists to prevent.
    if not force and _asked_today(instrument, today):
        # "Fresh" must mean "we have current data", not merely "we asked". An
        # instrument no provider covers has nothing stored, and calling that up to
        # date would hide the gap behind a reassuring label.
        if last is None:
            return Message(_no_data_reason(instrument), {"symbol": symbol})
        return Message(PriceOutcome.ALREADY_FRESH, {"symbol": symbol})

    # Re-fetch a short overlap so revised closes are picked up, instead of trusting
    # that a bar never changes once written.
    start = today - timedelta(days=INITIAL_HISTORY_DAYS) if last is None else last - timedelta(days=5)

    result = chain.fetch_daily(
        InstrumentRef(
            provider_symbol=instrument.provider_symbol,
            isin=instrument.isin,
            broker_symbol=instrument.broker_symbol,
            name=instrument.name,
            category=instrument.category,
        ),
        start,
        today,
        on_attempt=lambda name: record_usage(db, name),
    )

    if not result.succeeded:
        provider = result.attempts[-1].provider if result.attempts else None
        if result.rate_limited:
            # Deliberately not marked as checked: throttling is temporary, and this
            # instrument must be retried on the next run rather than skipped for a day.
            return Message(PriceOutcome.RATE_LIMITED, {"symbol": symbol, "provider": provider})

        # A wrong symbol or an excluded market will not change before tomorrow, so
        # record the attempt and stop asking for the rest of the day.
        instrument.prices_checked_at = datetime.now(UTC)
        reason = result.attempts[-1].reason if result.attempts else None
        if reason == "plan_limited":
            return Message(PriceOutcome.PLAN_LIMITED, {"symbol": symbol, "provider": provider})
        if reason == "symbol_not_found":
            return Message(PriceOutcome.SYMBOL_NOT_FOUND, {"symbol": symbol, "provider": provider})
        return Message(PriceOutcome.FAILED, {"symbol": symbol, "provider": provider})

    inserted = _store_bars(db, instrument, result)
    instrument.prices_checked_at = datetime.now(UTC)

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


def _refresh_instrument_threaded(
    session_factory: sessionmaker, instrument_id: int, chain: ProviderChain, force: bool
) -> Message:
    """Runs one instrument's refresh in its own DB session.

    A worker thread must never touch the session (or any ORM object) that
    belongs to the thread orchestrating the refresh — SQLAlchemy Sessions are
    not thread-safe, and neither are the ORM instances bound to them. So this
    opens a fresh session, re-fetches the instrument by id in it, and commits
    before handing back — the same "commit per instrument" durability the
    sequential version had, just from a session that is this thread's alone.

    `session_factory` is built from the *caller's* session's own engine
    (`sessionmaker(bind=db.get_bind())`), not a hardcoded import of the
    production `SessionLocal` — tests override `get_db` to point at an
    in-memory database via `app.dependency_overrides`, and a worker that
    quietly reconnected to the real on-disk database instead would silently
    write everywhere except where the test (or the rest of the request) is
    actually looking. See DEVLOG "Decision 3n.1".
    """
    db = session_factory()
    try:
        instrument = db.get(Instrument, instrument_id)
        outcome = refresh_instrument(db, instrument, chain, force=force)
        db.commit()
        return outcome
    finally:
        db.close()


def _record(report: RefreshReport, outcome: Message) -> None:
    report.outcomes.append(outcome)
    if outcome.code == PriceOutcome.UPDATED:
        report.updated += 1
    elif outcome.code == PriceOutcome.ALREADY_FRESH:
        report.skipped += 1
    elif outcome.code == PriceOutcome.NOT_PRICEABLE:
        # Not a shortfall: there is nothing to retrieve and never will be.
        report.not_priceable += 1
    else:
        # STILL_UNAVAILABLE and NEEDS_ISIN count here: no data is a shortfall, not a skip.
        report.failed += 1


def _needs_network(instrument: Instrument, today: date, force: bool) -> bool:
    """Whether settling this instrument requires contacting a provider.

    Used to keep the time budget for work that actually costs something.
    """
    if instrument.not_priceable_reason:
        return False
    if not instrument.provider_symbol and not instrument.isin:
        return False
    return force or not _asked_today(instrument, today)


def _no_data_reason(instrument: Instrument) -> str:
    """Say *why* there is still no data, in terms the user can act on.

    An instrument with no ISIN was never offered to the European source at all, which
    is a different situation from one every provider declined. Reporting the second
    when it is really the first sends the user looking for a problem elsewhere.
    """
    if not instrument.isin:
        return PriceOutcome.NEEDS_ISIN
    return PriceOutcome.STILL_UNAVAILABLE


def _asked_today(instrument: Instrument, today: date) -> bool:
    """Whether a provider has already been queried about this instrument today.

    One question per instrument per day is the rule that keeps a portfolio of this
    size inside free-tier quotas. Asking again the same day cannot yield anything
    new: daily bars are published once.
    """
    checked = instrument.prices_checked_at
    return checked is not None and checked.date() >= today


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
    # Non-blocking on purpose: making the second caller wait would hide the problem
    # behind a slow response. Saying "one is already running" is more useful.
    if not _refresh_lock.acquire(blocking=False):
        report = RefreshReport(remaining=len(instruments))
        report.outcomes.append(Message(PriceOutcome.ALREADY_RUNNING))
        return report

    try:
        return _refresh_many_locked(db, instruments, chain, budget_seconds, force)
    finally:
        _refresh_lock.release()


def _refresh_many_locked(
    db: Session,
    instruments: list[Instrument],
    chain: ProviderChain,
    budget_seconds: float,
    force: bool,
) -> RefreshReport:
    report = RefreshReport()
    started = datetime.now(UTC)
    today = _today()

    # Settle everything that needs no network call first. Otherwise the budget expires
    # among instruments that would have been skipped instantly, and the report claims
    # dozens are "remaining" when nearly all of them are already done — which is what
    # made a run read "8 updated, 0 already fresh, 29 remaining".
    free, costly = [], []
    for instrument in instruments:
        if _needs_network(instrument, today, force):
            costly.append(instrument)
        else:
            free.append(instrument)

    _set_progress(
        running=True,
        total=len(free) + len(costly),
        done=0,
        current_symbol=None,
        started_at=started,
        finished_at=None,
        report=None,
    )

    for instrument in free:
        _record(report, refresh_instrument(db, instrument, chain, force=force))
        _advance_progress(instrument.broker_symbol)
    db.commit()

    # A handful of instruments in flight at once — different instruments usually
    # land on different providers, so this shortens the wait without spending any
    # more quota than a sequential run would (see DEVLOG "Decision 3n.1"). Each
    # worker gets its own DB session (_refresh_instrument_threaded); this thread
    # only ever touches `report`/`_progress`, same single-writer shape as before.
    #
    # A bounded pool that refills as each slot frees up, rather than submitting
    # everything up front: `executor.submit` returns instantly, so checking the
    # budget in a plain submit loop would barely ever trigger — nearly everything
    # would be queued before any real time had passed. Checking again each time a
    # future actually *completes* (real work, real elapsed time) keeps the same
    # "budget bounds what starts, not what's already running" character the
    # sequential version had, just refilling up to MAX_CONCURRENT_REFRESHES slots
    # instead of one.
    pending = list(costly)
    symbols_by_id = {instrument.id: instrument.broker_symbol for instrument in costly}
    # Bound to the caller's own engine — see _refresh_instrument_threaded's
    # docstring for why this can't be the production SessionLocal directly.
    worker_sessions = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)

    def _budget_left() -> bool:
        return (datetime.now(UTC) - started).total_seconds() <= budget_seconds

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REFRESHES) as executor:
        futures: dict = {}

        def _fill() -> None:
            while pending and len(futures) < MAX_CONCURRENT_REFRESHES and _budget_left():
                instrument = pending.pop(0)
                future = executor.submit(
                    _refresh_instrument_threaded, worker_sessions, instrument.id, chain, force
                )
                futures[future] = instrument.id

        _fill()
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                instrument_id = futures.pop(future)
                _record(report, future.result())
                _advance_progress(symbols_by_id[instrument_id])
            _fill()

    report.remaining = len(pending)
    if report.remaining > 0:
        report.outcomes.append(Message(PriceOutcome.BUDGET_REACHED, {"remaining": report.remaining}))

    _add_fallback_hint(report, chain)
    _set_progress(running=False, current_symbol=None, finished_at=datetime.now(UTC), report=report)
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
    keyless = {"yahoo", "frankfurt"}
    has_keyed_fallback = any(
        provider.is_enabled() for provider in chain.providers if provider.name not in keyless
    )
    if not has_keyed_fallback:
        report.outcomes.append(Message(PriceOutcome.NO_FALLBACK_CONFIGURED))
