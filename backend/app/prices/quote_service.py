"""Budgeted live-quote fetching for the "recalculate with fresh prices" action.

Deliberately separate from ``service.py``'s daily price-history refresh: a live
quote is a snapshot, not a daily close, and writing it into ``PriceBar`` would
corrupt the daily-bar semantics the trend charts (and later, scoring) rely on.
Results here are kept in memory only, for the lifetime of one estimate
computation, and never persisted.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from app.models import Instrument
from app.prices.service import MAX_CONCURRENT_REFRESHES
from app.providers.base import InstrumentRef, ProviderChain

#: Serialises quote rounds the same way ``prices.service`` serialises the
#: history refresh — two rounds at once would double the quota spent for the
#: same portfolio and gain nothing.
_quote_lock = threading.Lock()


@dataclass
class QuoteProgress:
    running: bool = False
    total: int = 0
    done: int = 0
    current_symbol: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


_progress_lock = threading.Lock()
_progress = QuoteProgress()


def _set_progress(**kwargs) -> None:
    with _progress_lock:
        for key, value in kwargs.items():
            setattr(_progress, key, value)


def _advance_progress(current_symbol: str | None) -> None:
    with _progress_lock:
        _progress.done += 1
        _progress.current_symbol = current_symbol


def get_quote_progress() -> QuoteProgress:
    """A snapshot safe to read from another thread while a round is running."""
    with _progress_lock:
        return replace(_progress)


def _fetch_quote_threaded(
    instrument_id: int,
    ref: InstrumentRef,
    chain: ProviderChain,
    on_attempt: Callable[[str], None] | None,
) -> tuple[int, tuple[float, str] | None]:
    """No DB session needed here, unlike the daily-history refresh's worker —
    a live quote is never persisted (see this module's docstring), so a
    worker thread only ever touches `chain` (already lock-protected, DEVLOG
    "Decision 3n.1") and `on_attempt`. Returns the instrument id alongside the
    result so the orchestrating thread — not this one — is the only thing
    that ever writes into the shared `results` dict.
    """
    return instrument_id, chain.fetch_quote(ref, on_attempt=on_attempt)


def fetch_live_quotes(
    instruments: list[Instrument],
    chain: ProviderChain,
    budget_seconds: float = 30.0,
    on_attempt: Callable[[str], None] | None = None,
) -> dict[int, tuple[float, str]]:
    """Best-effort live quote per instrument, within a time budget.

    Returns ``{instrument_id: (price, provider_name)}`` for whichever
    instruments were reached before the budget ran out. Callers fall back to
    the cached daily close for anything missing — the same "partial success is
    the normal case" shape as the price-history refresh, for the same reason:
    free quote sources throttle, and a fixed few seconds per symbol makes a
    large portfolio genuinely take minutes to cover in full. Several
    instruments are attempted at once (DEVLOG "Decision 3n.1"), same
    bounded-pool shape as `prices/service.py::refresh_many`.
    """
    if not _quote_lock.acquire(blocking=False):
        return {}

    try:
        started = datetime.now(UTC)
        results: dict[int, tuple[float, str]] = {}

        _set_progress(
            running=True,
            total=len(instruments),
            done=0,
            current_symbol=None,
            started_at=started,
            finished_at=None,
        )

        pending = list(instruments)
        refs_by_id = {
            instrument.id: InstrumentRef(
                provider_symbol=instrument.provider_symbol,
                isin=instrument.isin,
                broker_symbol=instrument.broker_symbol,
                name=instrument.name,
                category=instrument.category,
            )
            for instrument in instruments
        }
        symbols_by_id = {instrument.id: instrument.broker_symbol for instrument in instruments}

        def _budget_left() -> bool:
            return (datetime.now(UTC) - started).total_seconds() <= budget_seconds

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REFRESHES) as executor:
            futures: dict = {}

            def _fill() -> None:
                while pending and len(futures) < MAX_CONCURRENT_REFRESHES and _budget_left():
                    instrument = pending.pop(0)
                    future = executor.submit(
                        _fetch_quote_threaded,
                        instrument.id,
                        refs_by_id[instrument.id],
                        chain,
                        on_attempt,
                    )
                    futures[future] = instrument.id

            _fill()
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    instrument_id = futures.pop(future)
                    _, quote = future.result()
                    if quote is not None:
                        results[instrument_id] = quote
                    _advance_progress(symbols_by_id[instrument_id])
                _fill()

        _set_progress(running=False, current_symbol=None, finished_at=datetime.now(UTC))
        return results
    finally:
        _quote_lock.release()
