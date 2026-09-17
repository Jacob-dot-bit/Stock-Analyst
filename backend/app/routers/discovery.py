"""Automated candidate discovery for the Screener ("Pépites") page.

See `discovery/service.py`'s module docstring for the full design and the
robots.txt research behind the Finviz half of it (DEVLOG "Decision 3u.20").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.corporate_actions.service import list_outstanding_candidates
from app.db import get_db
from app.discovery.service import (
    import_sp500_universe,
    pillar_score,
    ranked_candidates,
    recommendation_from_composite,
    refresh_batch,
)
from app.fundamentals.service import fetch_fundamentals
from app.ingest.service import get_or_create_instrument
from app.models import DiscoveryCandidate
from app.prices.service import price_status as _price_status, refresh_instrument
from app.providers.finviz_screener import fetch_preset
from app.providers.registry import get_edgar_provider, get_esef_provider, get_provider_chain
from app.routers.portfolio import _resolve_current_price
from app.schemas import (
    DiscoveryCandidateOut,
    DiscoveryFinvizOut,
    DiscoveryImportOut,
    DiscoveryRefreshOut,
    InstrumentOut,
)
from app.scoring.config import get_scoring_config
from app.scoring.service import compute_scores

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.post("/import-sp500", response_model=DiscoveryImportOut)
def import_sp500(db: Session = Depends(get_db)) -> DiscoveryImportOut:
    """One-off, idempotent import of the static S&P 500 list — safe to call
    repeatedly (already-imported instruments are just counted, never
    duplicated)."""
    result = import_sp500_universe(db)
    return DiscoveryImportOut(**result)


@router.post("/refresh", response_model=DiscoveryRefreshOut)
def refresh(db: Session = Depends(get_db)) -> DiscoveryRefreshOut:
    """Fetch price + fundamentals for the next batch of never-resolved
    discovery candidates. Best-effort and resumable, same "click again to
    continue" pattern as the price/fundamentals refresh buttons — see
    `discovery/service.py::BATCH_SIZE` for why this is a fixed batch size
    rather than a time budget."""
    result = refresh_batch(db, get_provider_chain(), get_edgar_provider(), get_esef_provider())
    return DiscoveryRefreshOut(**result)


def _pending_instrument_ids(db: Session) -> set[int]:
    """Instruments with an unresolved corporate-action candidate — computed
    once per request (cache-only, no provider calls, same query Data Health
    reuses) rather than per candidate row."""
    return {c.instrument_id for c in list_outstanding_candidates(db)}


def _to_out(db: Session, row: dict, pending_ids: set[int]) -> DiscoveryCandidateOut:
    instrument = row["instrument"]
    instrument_out = InstrumentOut.model_validate(instrument)
    instrument_out.price_status = _price_status(instrument)
    price, source = _resolve_current_price(db, instrument, {})
    return DiscoveryCandidateOut(
        instrument=instrument_out,
        source=row["source"],
        composite_score=row["composite_score"],
        value_score=row["value_score"],
        growth_score=row["growth_score"],
        current_price=price,
        price_source=source,
        recommendation=row["recommendation"],
        corporate_action_pending=instrument.id in pending_ids,
        market_cap=row["market_cap"],
        debt_ratio=row["debt_ratio"],
        price_history_years=row["price_history_years"],
    )


@router.get("/candidates", response_model=list[DiscoveryCandidateOut])
def get_candidates(
    rank_by: str = Query("value", pattern="^(value|growth)$"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[DiscoveryCandidateOut]:
    """Discovery candidates not already held/watched/screened, ranked by
    the Value or Growth pillar score — cache-only, never triggers a fetch.
    """
    config = get_scoring_config()
    rows = ranked_candidates(db, rank_by, limit, config)
    pending_ids = _pending_instrument_ids(db)
    return [_to_out(db, row, pending_ids) for row in rows]


@router.post("/finviz", response_model=DiscoveryFinvizOut)
def finviz_scan(
    preset: str = Query(..., pattern="^(insider_buys|oversold)$"),
    db: Session = Depends(get_db),
) -> DiscoveryFinvizOut:
    """Live fetch of one Finviz preset scan (robots.txt-whitelisted only —
    see `providers/finviz_screener.py`). Small result set (~10), so unlike
    the S&P 500 batch this resolves price *and* fundamentals immediately,
    same "fetch right away" convention `add_watchlist_item` already uses.
    """
    entries = fetch_preset(preset)
    config = get_scoring_config()
    pending_ids = _pending_instrument_ids(db)

    candidates = []
    failed = 0
    for entry in entries:
        try:
            broker_symbol = f"{entry['ticker']}.US"
            instrument = get_or_create_instrument(
                db, broker_symbol, currency="USD", category="STOCK", name=entry.get("name")
            )
            if not instrument.country and entry.get("country"):
                instrument.country = entry["country"]

            already = db.execute(
                select(DiscoveryCandidate.id).where(DiscoveryCandidate.instrument_id == instrument.id)
            ).first()
            if not already:
                db.add(DiscoveryCandidate(instrument_id=instrument.id, source=f"finviz:{preset}"))
            db.commit()

            refresh_instrument(db, instrument, get_provider_chain(), force=False)
            db.commit()
            fetch_fundamentals(db, [instrument], get_edgar_provider(), get_esef_provider())
            db.commit()

            scores = compute_scores(db, [instrument], config)
            score = scores[0] if scores else None

            price, price_source = _resolve_current_price(db, instrument, {})
            composite = score.composite if score else None
            instrument_out = InstrumentOut.model_validate(instrument)
            instrument_out.price_status = _price_status(instrument)
            candidates.append(
                DiscoveryCandidateOut(
                    instrument=instrument_out,
                    source=f"finviz:{preset}",
                    composite_score=composite,
                    value_score=pillar_score(score, "value") if score else None,
                    growth_score=pillar_score(score, "growth") if score else None,
                    current_price=price,
                    price_source=price_source,
                    recommendation=recommendation_from_composite(composite),
                    corporate_action_pending=instrument.id in pending_ids,
                    market_cap=score.market_cap if score else None,
                    debt_ratio=score.debt_ratio if score else None,
                    price_history_years=score.price_history_years if score else None,
                )
            )
        except Exception:
            # One candidate's refresh/fundamentals/scoring failing must not
            # discard every candidate already resolved before it in this same
            # sequential loop (unlike the rest of the app's single-instrument
            # call sites, this is the first place several live refreshes run
            # back to back in one request). Roll back this candidate's partial
            # writes and keep going — `failed` makes the gap visible instead
            # of silently shrinking the result set.
            db.rollback()
            failed += 1

    return DiscoveryFinvizOut(preset=preset, candidates=candidates, failed=failed)
