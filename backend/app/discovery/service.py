"""Automated candidate discovery for the Screener ("Pépites") page.

Two independent sources feed `DiscoveryCandidate` — a much larger, uncurated
pool than `ScreenerCandidate` (see that model's docstring):

* A static S&P 500 constituent list (`app/data/sp500_constituents.json`,
  fetched once from Wikipedia, 2026-08-28). Not a live API: FMP's actual
  stock-screener endpoint returned HTTP 402 on this app's free-tier key
  (confirmed live), and scanning the whole S&P 500 by fetching every
  instrument's fundamentals ourselves would need a live per-company data
  source anyway — Wikipedia's constituent list is the free, unrestricted
  way to get the ticker universe itself.
* Finviz's robots.txt-whitelisted preset scans
  (`providers/finviz_screener.py`) — a live, small (~10 rows) result set.

Neither source is ranked or filtered by anything beyond the app's own
existing composite scoring engine, once fundamentals/price data has been
fetched for a candidate: this module never invents a new notion of
"undervalued" or "high potential", it reuses the Value/Growth pillars
exactly as `GET /api/scoring/scores` already does. See DEVLOG
"Decision 3u.20".
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.fundamentals.service import fetch_fundamentals
from app.ingest.service import get_or_create_instrument
from app.models import DiscoveryCandidate, Instrument, Position, ScreenerCandidate, WatchlistItem
from app.prices.service import refresh_many
from app.providers.base import ProviderChain
from app.providers.edgar import EdgarProvider
from app.providers.esef import EsefProvider
from app.scoring.config import ScoringConfig
from app.scoring.service import InstrumentScore, compute_scores, score_band

SP500_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "sp500_constituents.json"

#: How many not-yet-evaluated candidates one `refresh_batch` call processes.
#: `fetch_fundamentals` has no internal time budget (unlike `refresh_many`),
#: so this app-level cap is what keeps one HTTP request bounded — small
#: enough that ~20 sequential EDGAR/price calls finish in a normal request
#: lifetime, matching the existing "click again to continue" pattern
#: everywhere else in this app rather than adding a new background-job
#: mechanism for what's an occasional, not-time-critical scan.
BATCH_SIZE = 20


def import_sp500_universe(db: Session) -> dict[str, int]:
    """One-off, idempotent import of the static S&P 500 list into
    `DiscoveryCandidate` rows. Safe to re-run: an instrument that already
    has one is simply counted as `already_present`, not duplicated (the
    model's own unique index on `instrument_id` would reject a duplicate
    anyway, but checking first avoids the failed-insert-then-rollback
    dance)."""
    with open(SP500_DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    imported = 0
    already_present = 0
    for row in data["constituents"]:
        instrument = get_or_create_instrument(
            db, row["broker_symbol"], currency="USD", category="STOCK", name=row["name"]
        )
        if not instrument.sector:
            instrument.sector = row.get("sector")

        already = db.execute(
            select(DiscoveryCandidate.id).where(DiscoveryCandidate.instrument_id == instrument.id)
        ).first()
        if already:
            already_present += 1
            continue

        db.add(DiscoveryCandidate(instrument_id=instrument.id, source="sp500"))
        imported += 1

    db.commit()
    return {"imported": imported, "already_present": already_present}


def _unevaluated_query():
    return (
        select(Instrument)
        .join(DiscoveryCandidate, DiscoveryCandidate.instrument_id == Instrument.id)
        .where(Instrument.verified_at.is_(None))
    )


def refresh_batch(
    db: Session,
    chain: ProviderChain,
    edgar: EdgarProvider,
    esef: EsefProvider,
    batch_size: int = BATCH_SIZE,
) -> dict[str, int]:
    """Fetch price history + fundamentals for the next `batch_size`
    never-resolved discovery candidates. A candidate only needs this ONCE —
    unlike a held or watched instrument, nothing here needs to stay fresh
    daily, since the point is a first-pass "does this even score" filter,
    not a live tracked position."""
    instruments = list(db.execute(_unevaluated_query().limit(batch_size)).scalars())

    if instruments:
        refresh_many(db, instruments, chain, budget_seconds=30.0)
        fetch_fundamentals(db, instruments, edgar, esef)

    remaining = db.execute(
        select(func.count()).select_from(_unevaluated_query().subquery())
    ).scalar_one()

    return {"evaluated": len(instruments), "remaining": remaining}


def pillar_score(score: InstrumentScore, name: str) -> float | None:
    return next((p.score for p in score.pillars if p.name == name), None)


#: composite score band -> explicit verdict, requested by the user
#: specifically for Discovery (DEVLOG "Decision 3u.21") — a deliberate
#: exception to this app's usual fact-based labeling elsewhere.
_RECOMMENDATION_BY_BAND = {"high": "buy", "mid": "hold", "low": "sell"}


def recommendation_from_composite(composite: float | None) -> str | None:
    return _RECOMMENDATION_BY_BAND.get(score_band(composite))


def ranked_candidates(db: Session, rank_by: str, limit: int, config: ScoringConfig) -> list[dict]:
    """Discovery candidates not already tracked elsewhere (held, watched,
    or already a real screener candidate), ranked by one scoring pillar.
    Cache-only — never triggers a fetch, safe to call on every page load.
    """
    instruments = list(
        db.execute(
            select(Instrument)
            .join(DiscoveryCandidate, DiscoveryCandidate.instrument_id == Instrument.id)
            .where(
                ~select(Position.id).where(Position.instrument_id == Instrument.id).exists(),
                ~select(WatchlistItem.id).where(WatchlistItem.instrument_id == Instrument.id).exists(),
                ~select(ScreenerCandidate.id).where(ScreenerCandidate.instrument_id == Instrument.id).exists(),
            )
        ).scalars()
    )
    if not instruments:
        return []

    sources = {
        row.instrument_id: row.source
        for row in db.execute(
            select(DiscoveryCandidate).where(
                DiscoveryCandidate.instrument_id.in_([i.id for i in instruments])
            )
        ).scalars()
    }
    instruments_by_id = {i.id: i for i in instruments}

    rows = []
    for score in compute_scores(db, instruments, config):
        value = pillar_score(score, "value")
        growth = pillar_score(score, "growth")
        rank_value = value if rank_by == "value" else growth
        if rank_value is None:
            continue
        rows.append(
            {
                "instrument": instruments_by_id[score.instrument_id],
                "source": sources.get(score.instrument_id, "sp500"),
                "composite_score": score.composite,
                "value_score": value,
                "growth_score": growth,
                "recommendation": recommendation_from_composite(score.composite),
                "_rank_value": rank_value,
            }
        )

    rows.sort(key=lambda r: r["_rank_value"], reverse=True)
    return rows[:limit]
