"""Fetching and caching company fundamentals from SEC EDGAR and ESEF.

Deliberately sequential, unlike `prices/service.py`'s thread-pooled refresh: at
this portfolio's scale (~30 filers across both sources) a full run is well
under any budget that would justify the extra concurrency machinery
`prices/service.py` needed for 38 holdings across many throttled providers.
Revisit if that stops being true. Sequential does not mean instant, though —
ESEF's first hit in a fresh process pays a one-time ~37-request entity-index
load (see `providers/esef.py`), so a cold run is tens of seconds, not the
sub-second case a bare synchronous call would suggest — hence the progress
tracking below, the same shape `prices/service.py` already has.

Same "per-instrument outcome, partial success is normal" shape as
`prices/service.py::refresh_many` — coverage genuinely varies here (only real
filers have anything to fetch; see DEVLOG "Bug 3a.2"/"Bug 3a.3" for why a bare
ticker cannot simply be assumed for non-US names).

**Two sources, additive, not a chain.** SEC EDGAR is tried first — it is the
primary source for the US filers this portfolio mostly holds. ESEF
(`providers/esef.py`) is the fallback for whatever EDGAR can't answer: not a
US filer, EDGAR disabled, or even a transient EDGAR failure — maximising this
run's actual coverage rather than leaving an instrument empty over something
the second source might still answer. See DEVLOG "Decision 3t.1". This is
deliberately two explicit steps, not a generalised N-provider chain
(`ProviderChain` already exists for prices) — a third fundamentals source was
considered and explicitly rejected as premature.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.messages import FundamentalsOutcome, Message
from app.models import Fundamental, Instrument
from app.providers.base import ProviderUnavailable, RateLimited, SymbolNotFound
from app.providers.edgar import AnnualFigure, EdgarProvider
from app.providers.esef import EsefProvider


@dataclass
class FundamentalsReport:
    outcomes: list[Message] = field(default_factory=list)
    updated: int = 0
    skipped: int = 0
    #: ETFs and CFDs — not a shortfall, a property of the instrument.
    not_applicable: int = 0
    failed: int = 0

    def as_dict(self) -> dict:
        return {
            "outcomes": [outcome.as_dict() for outcome in self.outcomes],
            "updated": self.updated,
            "skipped": self.skipped,
            "not_applicable": self.not_applicable,
            "failed": self.failed,
        }


#: Serialises fundamentals refreshes across the whole process — same reasoning
#: as `prices/service.py`'s `_refresh_lock`: two runs at once would double the
#: EDGAR/ESEF request spend for no benefit.
_fundamentals_lock = threading.Lock()


@dataclass
class FundamentalsProgress:
    """Live state of the run currently in flight (or the last completed one).

    Same shape and reasoning as `prices/service.py::RefreshProgress`: polled
    from a separate request while a refresh is in progress (FastAPI serves
    each sync endpoint on its own thread), a real settled-instrument count,
    never a simulated animation.
    """

    running: bool = False
    total: int = 0
    done: int = 0
    current_symbol: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report: "FundamentalsReport | None" = None


_progress_lock = threading.Lock()
_progress = FundamentalsProgress()


def _set_progress(**kwargs) -> None:
    with _progress_lock:
        for key, value in kwargs.items():
            setattr(_progress, key, value)


def _advance_progress(current_symbol: str | None) -> None:
    with _progress_lock:
        _progress.done += 1
        _progress.current_symbol = current_symbol


def get_fundamentals_progress() -> FundamentalsProgress:
    """A snapshot safe to read from another thread while a refresh is running."""
    with _progress_lock:
        return replace(_progress)


def _already_fresh_today(db: Session, instrument_id: int) -> bool:
    latest = db.execute(
        select(Fundamental.fetched_at)
        .where(Fundamental.instrument_id == instrument_id)
        .order_by(Fundamental.fetched_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return latest is not None and latest.date() == datetime.now(UTC).date()


def _save_fundamentals(
    db: Session,
    instrument: Instrument,
    provider_name: str,
    concepts: dict[str, list[AnnualFigure]],
    now: datetime,
) -> int:
    concept_count = 0
    for concept, figures in concepts.items():
        for figure in figures:
            row = db.execute(
                select(Fundamental).where(
                    Fundamental.instrument_id == instrument.id,
                    Fundamental.concept == concept,
                    Fundamental.fiscal_year == figure.fiscal_year,
                )
            ).scalar_one_or_none()
            if row is None:
                row = Fundamental(instrument_id=instrument.id, concept=concept, fiscal_year=figure.fiscal_year)
                db.add(row)
            row.period_end = figure.period_end
            row.value = figure.value
            row.currency = figure.currency
            row.tag = figure.tag
            row.provider = provider_name
            row.fetched_at = now
            concept_count += 1
    return concept_count


def fetch_one(
    db: Session, instrument: Instrument, edgar: EdgarProvider, esef: EsefProvider, force: bool
) -> Message:
    """Fetch and cache one instrument's fundamentals. Commits on success.

    Tries SEC EDGAR first, then ESEF — see the module docstring for why this
    is two explicit steps rather than a generalised chain. Whichever source
    actually produces a usable concept wins; a company found in an index but
    with nothing usable filed there (documented for real: Air Liquide and
    Sanofi appear in the SEC index but file no usable XBRL — DEVLOG Decision
    3a.1) does not count as success and still falls through to the next
    source.
    """
    symbol = instrument.broker_symbol

    # Only real companies file with either source — ETFs are funds, CFDs are
    # derivatives, neither has its own financial statements. See
    # `symbols/mapping.py::ANALYSABLE_CATEGORIES`/`DERIVATIVE_CATEGORIES`.
    if instrument.category != "STOCK":
        return Message(FundamentalsOutcome.NOT_APPLICABLE, {"symbol": symbol})

    if not force and _already_fresh_today(db, instrument.id):
        return Message(FundamentalsOutcome.ALREADY_FRESH, {"symbol": symbol})

    now = datetime.now(UTC)
    #: Remembered only if ESEF doesn't succeed either — a real rate-limit or
    #: failure signal from EDGAR is more informative than a blank "not found"
    #: once both sources have been tried.
    fallback_outcome: Message | None = None
    #: Whether either source was actually queried at all — distinct from
    #: "queried and came back empty". Only false when EDGAR is disabled *and*
    #: the instrument has no name to search ESEF with either.
    attempted = False

    if edgar.is_enabled():
        attempted = True
        # Bare ticker, no country suffix — EdgarProvider.resolve()'s documented
        # contract. expected_name only for non-US instruments: for a US listing
        # the broker ticker and the SEC ticker are the same namespace, and
        # demanding a name match there discards valid results (e.g. "AMD" vs
        # "Advanced Micro Devices Inc"). See DEVLOG "Bug 3a.3" for what skipping
        # this check costs.
        ticker = symbol.split(".")[0]
        expected_name = instrument.name if instrument.country != "US" else None
        try:
            fundamentals = edgar.fetch(ticker, expected_name=expected_name)
            if fundamentals.concepts:
                concept_count = _save_fundamentals(db, instrument, edgar.name, fundamentals.concepts, now)
                db.commit()
                return Message(
                    FundamentalsOutcome.UPDATED,
                    {"symbol": symbol, "concepts": concept_count, "provider": edgar.name},
                )
            # Resolved to a real company, but nothing usable was filed there —
            # still worth trying ESEF, not a failure to remember.
        except SymbolNotFound:
            pass
        except RateLimited:
            fallback_outcome = Message(FundamentalsOutcome.RATE_LIMITED, {"symbol": symbol})
        except ProviderUnavailable as exc:
            fallback_outcome = Message(FundamentalsOutcome.FAILED, {"symbol": symbol, "error": str(exc)})

    if instrument.name:
        attempted = True
        try:
            fundamentals = esef.fetch(instrument.name)
            if fundamentals.concepts:
                concept_count = _save_fundamentals(db, instrument, esef.name, fundamentals.concepts, now)
                db.commit()
                return Message(
                    FundamentalsOutcome.UPDATED,
                    {"symbol": symbol, "concepts": concept_count, "provider": esef.name},
                )
        except SymbolNotFound:
            pass
        except RateLimited:
            fallback_outcome = fallback_outcome or Message(FundamentalsOutcome.RATE_LIMITED, {"symbol": symbol})
        except ProviderUnavailable as exc:
            fallback_outcome = fallback_outcome or Message(
                FundamentalsOutcome.FAILED, {"symbol": symbol, "error": str(exc)}
            )

    if fallback_outcome is not None:
        return fallback_outcome
    if not attempted:
        return Message(FundamentalsOutcome.NO_PROVIDER, {"symbol": symbol})
    return Message(FundamentalsOutcome.SYMBOL_NOT_FOUND, {"symbol": symbol})


def _record(report: FundamentalsReport, outcome: Message) -> None:
    report.outcomes.append(outcome)
    if outcome.code == FundamentalsOutcome.UPDATED:
        report.updated += 1
    elif outcome.code == FundamentalsOutcome.ALREADY_FRESH:
        report.skipped += 1
    elif outcome.code == FundamentalsOutcome.NOT_APPLICABLE:
        report.not_applicable += 1
    else:
        # NO_PROVIDER, SYMBOL_NOT_FOUND, RATE_LIMITED, FAILED: no data is a
        # shortfall, not a skip — same posture as PriceOutcome's equivalents.
        report.failed += 1


def fetch_fundamentals(
    db: Session,
    instruments: list[Instrument],
    edgar: EdgarProvider,
    esef: EsefProvider,
    force: bool = False,
) -> FundamentalsReport:
    """Refresh every instrument's fundamentals, one after another.

    Non-blocking lock, same reasoning as `prices/service.py::refresh_many`:
    a second concurrent call while one is already running gets told so
    immediately instead of queueing behind it and doubling the request spend.
    """
    if not _fundamentals_lock.acquire(blocking=False):
        report = FundamentalsReport()
        report.outcomes.append(Message(FundamentalsOutcome.ALREADY_RUNNING))
        return report

    try:
        return _fetch_fundamentals_locked(db, instruments, edgar, esef, force)
    finally:
        _fundamentals_lock.release()


def _fetch_fundamentals_locked(
    db: Session,
    instruments: list[Instrument],
    edgar: EdgarProvider,
    esef: EsefProvider,
    force: bool,
) -> FundamentalsReport:
    report = FundamentalsReport()
    _set_progress(
        running=True,
        total=len(instruments),
        done=0,
        current_symbol=None,
        started_at=datetime.now(UTC),
        finished_at=None,
        report=None,
    )

    for instrument in instruments:
        _record(report, fetch_one(db, instrument, edgar, esef, force))
        _advance_progress(instrument.broker_symbol)

    _set_progress(running=False, current_symbol=None, finished_at=datetime.now(UTC), report=report)
    return report
