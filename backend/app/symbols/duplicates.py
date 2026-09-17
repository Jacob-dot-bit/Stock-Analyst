"""Cross-instrument identity checks — same company, different ticker.

`WatchlistItem`/`ScreenerCandidate` adds are typed by hand, one ticker at a
time, with no cross-check against what's already tracked under a different
symbol. Real incident (DEVLOG "Decision 3u.16"): the same company sat on the
watchlist four times, three of them under wrong/OTC ticker variants, because
nothing ever compared them. ISIN is the one identifier that survives a
ticker-format change, so this is the cheapest identity signal available —
matching on company *name* would need fuzzy logic and still be unreliable
across languages, abbreviations and legal-suffix variants ("S.A." vs "SA").
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DiscoveryCandidate, Instrument, Position, ScreenerCandidate, WatchlistItem
from app.providers.openfigi import FigiJob, map_instruments
from app.providers.wikidata import resolve_isin

#: Same constant discovery/service.py's own BATCH_SIZE uses — one click's
#: worth of sequential provider calls, "click again to continue" rather
#: than a background job. See DEVLOG "Decision 3u.76".
FIGI_BATCH_SIZE = 20


def check_for_duplicate(db: Session, instrument: Instrument, company_name: str | None) -> str | None:
    """Best-effort duplicate warning for a symbol just added to the watchlist
    or screener. `None` whenever there is nothing to say — no name given, no
    ISIN resolvable, or no existing match — never raises: a Wikidata hiccup
    must not fail the add itself, only skip the warning.

    Side effects: stores `company_name` on `instrument.name` when it didn't
    have one (a manually-typed symbol otherwise never gets a name from
    anywhere — real gap found live: typing "Netflix" resolved its ISIN just
    fine, but the name itself was silently discarded, so the row displayed
    no name at all while a broker-imported one like `NKE.US` did), and
    stores the resolved ISIN when it didn't have one either — worth keeping
    even absent a duplicate, since it also unlocks ISIN-only providers
    (Frankfurt) and `resolve_wikidata_sector` (which needs a name) later.
    Both happen regardless of whether an ISIN or a duplicate is found.
    """
    if not company_name:
        return None

    if not instrument.name:
        instrument.name = company_name
        db.commit()

    isin = resolve_isin(company_name)
    if not isin:
        return None

    if not instrument.isin:
        instrument.isin = isin
        db.commit()

    duplicate = find_tracked_duplicate(db, isin, exclude_instrument_id=instrument.id)
    if duplicate is None:
        return None

    return (
        f"'{company_name}' looks like it might already be tracked as "
        f"'{duplicate.broker_symbol}' (same ISIN {isin}) — check before keeping both."
    )


def backfill_isins(db: Session) -> dict[str, int]:
    """One-off catch-up for instruments that already carry a company name but
    never got an ISIN resolved.

    `check_for_duplicate` only ever runs at add time, so anything tracked
    before this feature existed — or added since without a `company_name` —
    never went through it. Some of those already have a `name` regardless:
    a broker CSV import supplies one directly, and it survives even after
    the position that carried it is fully sold and the same instrument gets
    re-tracked on the watchlist (real example: `NKE.US`/`CELH.US`). For those,
    nothing needs to be typed — the name was always there, just never fed
    through `resolve_isin`. Instruments with no name at all (most
    manually-typed watchlist/screener adds, e.g. `EL.PA.US`) can't be
    resolved this way; those need a `company_name` supplied once, by hand,
    via `check_for_duplicate` itself (the create or update endpoints).

    Scoped to instruments actually referenced somewhere — an orphan instrument
    isn't worth spending a Wikidata request on.
    """
    query = select(Instrument).where(Instrument.isin.is_(None), Instrument.name.is_not(None)).where(
        select(Position.id).where(Position.instrument_id == Instrument.id).exists()
        | select(WatchlistItem.id).where(WatchlistItem.instrument_id == Instrument.id).exists()
        | select(ScreenerCandidate.id).where(ScreenerCandidate.instrument_id == Instrument.id).exists()
    )
    candidates = list(db.execute(query).scalars())

    updated = 0
    for instrument in candidates:
        isin = resolve_isin(instrument.name)
        if isin:
            instrument.isin = isin
            updated += 1
    db.commit()

    return {"checked": len(candidates), "updated": updated}


def find_tracked_duplicate(db: Session, isin: str, exclude_instrument_id: int) -> Instrument | None:
    """Another instrument with the same ISIN that is actually tracked
    somewhere — held, watchlisted, or screened.

    Deliberately not "any instrument row with this ISIN": a past add that got
    rejected by `prices/service.py::is_permanently_unresolvable` (or one that
    simply never had anything reference it) is an orphan, not a real
    duplicate worth warning about.
    """
    query = (
        select(Instrument)
        .where(Instrument.isin == isin, Instrument.id != exclude_instrument_id)
        .where(
            select(Position.id).where(Position.instrument_id == Instrument.id).exists()
            | select(WatchlistItem.id).where(WatchlistItem.instrument_id == Instrument.id).exists()
            | select(ScreenerCandidate.id).where(ScreenerCandidate.instrument_id == Instrument.id).exists()
        )
        .limit(1)
    )
    return db.execute(query).scalar_one_or_none()


def _root_ticker(broker_symbol: str) -> str:
    """Strips the XTB exchange suffix, e.g. `"AAPL.US"` -> `"AAPL"` — same
    split `symbols/mapping.py::resolve` already uses, kept local here since
    that function's own suffix-to-Yahoo-code table isn't relevant to this
    identity-only lookup."""
    root, _, suffix = broker_symbol.rpartition(".")
    return root or broker_symbol


def _figi_candidate_query():
    """Instruments worth spending an OpenFIGI request on: held, watchlisted,
    or screened unconditionally, plus Discovery-sourced ones only once
    already evaluated (`verified_at` set) — same cost gate
    `discovery/service.py::_unchecked_dividend_candidates_query` established
    (Decision 3u.73/3u.74): Discovery's raw pool is ~500 S&P tickers, and
    querying OpenFIGI for every one of them before they've even been scored
    once would be a real quota burn for candidates the user may never see.

    Gated on `figi_checked_at IS NULL` — "have we tried", not "did we find
    a value" — same reasoning as `dividend_checked_at`: a real non-match is
    permanent and must not be retried on every click.
    """
    return select(Instrument).where(Instrument.figi_checked_at.is_(None)).where(
        select(Position.id).where(Position.instrument_id == Instrument.id).exists()
        | select(WatchlistItem.id).where(WatchlistItem.instrument_id == Instrument.id).exists()
        | select(ScreenerCandidate.id).where(ScreenerCandidate.instrument_id == Instrument.id).exists()
        | (
            select(DiscoveryCandidate.id).where(DiscoveryCandidate.instrument_id == Instrument.id).exists()
            & Instrument.verified_at.is_not(None)
        )
    )


def backfill_figis(
    db: Session, api_key: str | None, max_jobs_per_request: int, batch_size: int = FIGI_BATCH_SIZE
) -> dict[str, int]:
    """One-off catch-up: resolve a FIGI/share-class FIGI for the next
    `batch_size` never-attempted tracked instruments via OpenFIGI. Same
    "batch, resumable, click again" shape as `backfill_isins` and
    `discovery/service.py::backfill_dividend_concept`. See DEVLOG
    "Decision 3u.76"."""
    instruments = list(db.execute(_figi_candidate_query().limit(batch_size)).scalars())

    jobs = [
        FigiJob(isin=i.isin, ticker=None if i.isin else _root_ticker(i.broker_symbol), currency=i.currency)
        for i in instruments
    ]
    matches = map_instruments(jobs, api_key, max_jobs_per_request) if jobs else []

    now = datetime.now(UTC)
    resolved = 0
    for instrument, match in zip(instruments, matches):
        instrument.figi_checked_at = now
        if match:
            instrument.figi = match.figi
            instrument.share_class_figi = match.share_class_figi
            if not instrument.name and match.name:
                instrument.name = match.name
            resolved += 1
    db.commit()

    remaining = db.execute(select(func.count()).select_from(_figi_candidate_query().subquery())).scalar_one()
    return {"checked": len(instruments), "resolved": resolved, "remaining": remaining}


def find_figi_duplicates(db: Session) -> list[tuple[Instrument, Instrument]]:
    """Every pair of *actually tracked* instruments (held, watchlisted, or
    screened — same scope as `find_tracked_duplicate`, deliberately NOT
    extended to bare Discovery rows: `DiscoveryCandidate`'s own docstring
    says its pool is "never shown to the user directly", and surfacing an
    uncurated ticker as a "possible duplicate" would break that invariant)
    that share a `share_class_figi`. Cache-only — never calls OpenFIGI
    itself, only reads whatever `backfill_figis` already stored, so it's
    cheap enough to call on every Data Health page load. A pure fact, like
    `find_tracked_duplicate` — surfaced, never merged or blocked.
    """
    tracked = select(Instrument).where(Instrument.share_class_figi.is_not(None)).where(
        select(Position.id).where(Position.instrument_id == Instrument.id).exists()
        | select(WatchlistItem.id).where(WatchlistItem.instrument_id == Instrument.id).exists()
        | select(ScreenerCandidate.id).where(ScreenerCandidate.instrument_id == Instrument.id).exists()
    )
    by_share_class: dict[str, list[Instrument]] = defaultdict(list)
    for instrument in db.execute(tracked).scalars():
        by_share_class[instrument.share_class_figi].append(instrument)

    pairs: list[tuple[Instrument, Instrument]] = []
    for group in by_share_class.values():
        if len(group) > 1:
            pairs.extend(combinations(group, 2))
    return pairs
