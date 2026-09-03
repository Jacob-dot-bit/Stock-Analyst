"""Phase 1 of a real, backtestable Discovery prediction: deepening price
history for the already-priced universe so a technical/momentum model can
later be trained and validated. See DEVLOG "Decision 3u.22".

Deliberately price-only, not fundamentals-driven. `Fundamental` rows only
ever hold each concept's *latest* known figure (`fetch_fundamentals`
overwrites in place), not a history keyed by filing date. Using today's
Value/Growth score to "predict" a return from years ago would be lookahead
bias — the model would be using information that did not exist yet at the
date being tested. `PriceBar`, by contrast, is naturally point-in-time
safe: a bar dated 2024-03-01 is exactly what was known on that date. So
this phase — and the model phase after it — only ever touches price
history.

A one-off, occasional pull, not folded into `prices/service.py::
refresh_instrument`: that function deliberately only asks for a handful of
recent days once an instrument's initial history is loaded (`INITIAL_
HISTORY_DAYS = 400`), matching what the live app itself actually needs
(a 200-day moving average, a year-long chart). Backtesting needs a much
longer window than the live app ever will, so it gets its own explicit,
rarely-run pull instead of changing that constant for everyone.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Instrument, PriceBar
from app.prices.provider_usage import record_usage
from app.prices.service import _store_bars
from app.providers.base import InstrumentRef, ProviderChain

#: How far back to pull. A provider's own throttle already paces one call
#: per instrument, and the range costs the same one call regardless of how
#: many years it spans — so this is chosen for backtest quality (several
#: distinct market periods to walk-forward across), not request budget.
BACKFILL_YEARS = 5


@dataclass
class BackfillReport:
    updated: int = 0
    failed: int = 0
    #: New rows actually inserted — distinct from `updated`, since a
    #: provider commonly re-answers with bars already stored (the requested
    #: window and what's cached overlap for anything fetched before).
    bars_added: int = 0

    def as_dict(self) -> dict:
        return {"updated": self.updated, "failed": self.failed, "bars_added": self.bars_added}


#: Serialises runs across the process — same reasoning as `prices/
#: service.py`'s `_refresh_lock`: two runs at once would double the request
#: spend for no benefit, and this pull is long enough (~87 instruments *
#: an 8s per-call throttle ≈ 12 minutes) that overlap is a real risk.
_backfill_lock = threading.Lock()


@dataclass
class BackfillProgress:
    """Same shape and reasoning as `prices/service.py::RefreshProgress` —
    polled from a separate request while a run is in progress, a real
    settled-instrument count, never a simulated animation."""

    running: bool = False
    total: int = 0
    done: int = 0
    current_symbol: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report: BackfillReport | None = None


_progress_lock = threading.Lock()
_progress = BackfillProgress()


def _set_progress(**kwargs) -> None:
    with _progress_lock:
        for key, value in kwargs.items():
            setattr(_progress, key, value)


def get_backfill_progress() -> BackfillProgress:
    """A snapshot safe to read from another thread while a run is in progress."""
    with _progress_lock:
        return replace(_progress)


def _already_priced_instruments(db: Session) -> list[Instrument]:
    """The phase-1 universe: instruments that already have at least one
    cached bar — not the full, much larger Discovery candidate pool, to
    keep this a bounded, quick-to-run pull rather than an hours-long one."""
    ids = list(db.execute(select(PriceBar.instrument_id).distinct()).scalars())
    if not ids:
        return []
    return list(db.execute(select(Instrument).where(Instrument.id.in_(ids))).scalars())


def backfill_history(db: Session, chain: ProviderChain, years: int = BACKFILL_YEARS) -> BackfillReport | None:
    """Fetch `years` of daily history for every already-priced instrument,
    one call per instrument covering the whole window (the provider accepts
    an arbitrary start/end range — this isn't "one call per day"). Returns
    `None` instead of running if a pull is already in progress."""
    if not _backfill_lock.acquire(blocking=False):
        return None

    try:
        instruments = _already_priced_instruments(db)
        _set_progress(
            running=True,
            total=len(instruments),
            done=0,
            current_symbol=None,
            started_at=datetime.now(UTC),
            finished_at=None,
            report=None,
        )

        today = date.today()
        start = today - timedelta(days=years * 365)
        report = BackfillReport()

        for instrument in instruments:
            _set_progress(current_symbol=instrument.broker_symbol)
            try:
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
                if result.succeeded:
                    report.bars_added += _store_bars(db, instrument, result)
                    report.updated += 1
                    db.commit()
                else:
                    report.failed += 1
            except Exception:
                db.rollback()
                report.failed += 1
            finally:
                with _progress_lock:
                    _progress.done += 1

        _set_progress(running=False, finished_at=datetime.now(UTC), report=report, current_symbol=None)
        return report
    finally:
        _backfill_lock.release()
