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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Instrument, Position, ScreenerCandidate, WatchlistItem
from app.providers.wikidata import resolve_isin


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
