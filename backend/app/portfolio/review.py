"""What deserves a look in the portfolio: allocation against the target
ranges, gaps against the personal policy, the "look at today" list and the
per-position signals.

Plain functions over a `Session`. The `/api/portfolio` routes return them
as is, and the weekly summary composes them without going through another
router (DEVLOG "Step 3u.105").
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Instrument, MappingStatus, PersonalPolicyLimit, Position
from app.portfolio.valuation import (
    DECLARED_VALUE_FRESHNESS_DAYS,
    positions_figures_and_total,
    weight_buckets,
)
from app.prices.service import price_status as _price_status
from app.schemas import AllocationRowOut, AttentionItemOut, PersonalPolicyGapOut, PositionSignalOut
from app.scoring.config import get_scoring_config
from app.scoring.service import compute_scores, score_band


def unresolved_instruments(db: Session) -> list[Instrument]:
    """Instruments still needing a symbol correction before they can join any
    analysis. Excluded:
      - CFDs, which have no fundamentals by nature;
      - anything that already carries an ISIN, since the identifier is known and the
        gap is provider coverage, not missing information;
      - anything with a `not_priceable_reason` already set (P2P/FUND aggregates,
        corporate-action residuals) — a permanent, structural non-price, not a
        correctable mapping gap. See DEVLOG "Decision 3u.39".
    A CVR whose broker symbol *is* its ISIN falls in the second case: there is no
    ticker to supply, and asking for one would send the user hunting for nothing.
    """
    return list(
        db.execute(
            select(Instrument).where(
                Instrument.mapping_status == MappingStatus.UNRESOLVED,
                Instrument.category.is_distinct_from("CFD"),
                Instrument.isin.is_(None),
                Instrument.not_priceable_reason.is_(None),
            )
        ).scalars()
    )


def current_allocation_values(db: Session) -> tuple[dict[str, float], float]:
    """Current market value per category, and the portfolio total — same
    computation `get_breakdown` already does, reused here for the target
    comparison rather than re-derived."""
    positions, figures, total_value = positions_figures_and_total(db)
    return weight_buckets(positions, figures, "category"), total_value


def category_limits(db: Session) -> dict[str, PersonalPolicyLimit]:
    """Asset-class target ranges, keyed by category. They are the policy's
    `dimension="category"` limits — one table for every rule (DEVLOG
    "Step 3u.101")."""
    return {
        limit.target: limit
        for limit in db.execute(
            select(PersonalPolicyLimit).where(
                PersonalPolicyLimit.dimension == "category", PersonalPolicyLimit.target.is_not(None)
            )
        ).scalars()
    }


def allocation_row(
    category: str, current_value: float, total_value: float, target: PersonalPolicyLimit | None
) -> AllocationRowOut:
    current_pct = round(current_value / total_value * 100, 2) if total_value else 0.0

    if target is None:
        return AllocationRowOut(
            category=category,
            current_value=round(current_value, 2),
            current_pct=current_pct,
            min_pct=None,
            max_pct=None,
            state="no_target",
            gap_pct=0.0,
            amount_to_reach_min=None,
        )

    # A policy limit may set only one bound ("at most 30 %"); the missing one
    # never triggers.
    if target.min_pct is not None and current_pct < target.min_pct:
        state = "under"
        gap_pct = round(target.min_pct - current_pct, 2)
        # Deliberately not solving for the new (larger) total after adding
        # this amount — a one-sentence, honestly-labeled approximation
        # (this category alone reaching min_pct of the CURRENT total) beats
        # a "more exact" number that reads as more precise than it is.
        amount_to_reach_min = round(max(0.0, target.min_pct / 100 * total_value - current_value), 2)
    elif target.max_pct is not None and current_pct > target.max_pct:
        state = "over"
        gap_pct = round(current_pct - target.max_pct, 2)
        amount_to_reach_min = None  # never a sell suggestion
    else:
        state = "within"
        gap_pct = 0.0
        amount_to_reach_min = None

    return AllocationRowOut(
        category=category,
        current_value=round(current_value, 2),
        current_pct=current_pct,
        min_pct=target.min_pct,
        max_pct=target.max_pct,
        state=state,
        gap_pct=gap_pct,
        amount_to_reach_min=amount_to_reach_min,
    )


def allocation_rows(db: Session) -> list[AllocationRowOut]:
    """Current allocation by asset class vs. a user-configured target range,
    if any. Descriptive only — never a suggestion to buy or sell a specific
    security, just the gap against a range the user themselves set. See
    DEVLOG "Decision 3u.15".
    """
    buckets, total_value = current_allocation_values(db)

    targets = category_limits(db)

    # Union of categories actually held and categories with a configured
    # target: a target for a category currently held at 0% must still
    # appear — that's the most informative row ("you want 10% bonds, you
    # hold 0%"), not one to silently drop because no position exists. Note
    # this means a *configured* target still shows even with an entirely
    # empty portfolio (total_value == 0) — `allocation_row` treats that as
    # current_pct=0, not a crash, unlike `get_breakdown`'s early return
    # (which is fine there: it has no analogous "show it anyway" case).
    categories = set(buckets) | set(targets)

    rows = [
        allocation_row(category, buckets.get(category, 0.0), total_value, targets.get(category))
        for category in categories
    ]
    rows.sort(key=lambda r: r.current_value, reverse=True)
    return rows


#: Every `PersonalPolicyLimit.dimension` except "line"/"declared_valuation"
#: names a plain `Instrument` column to group
#: weight by — same shape `weight_buckets`/`/breakdown` already use.
POLICY_LIMIT_ATTRIBUTE = {"sector": "sector", "country": "country", "currency": "currency", "category": "category"}


def limit_state(pct: float, min_pct: float | None, max_pct: float | None) -> tuple[str, float]:
    """('under'|'over'|'within', distance to the nearest breached bound)."""
    if min_pct is not None and pct < min_pct:
        return "under", round(min_pct - pct, 2)
    if max_pct is not None and pct > max_pct:
        return "over", round(pct - max_pct, 2)
    return "within", 0.0


def policy_gaps(db: Session) -> list[PersonalPolicyGapOut]:
    """Compares the current portfolio against every configured
    `PersonalPolicyLimit` and returns the breaches only — same "nothing to
    report when nothing needs a look" posture as `/attention`. Purely
    descriptive: a gap here is a fact about the user's own stated rule,
    never a suggestion to buy or sell anything. See DEVLOG "Decision
    3u.59".
    """
    limits = list(db.execute(select(PersonalPolicyLimit)).scalars())
    if not limits:
        return []

    positions, figures, total_value = positions_figures_and_total(db)
    if not total_value:
        return []

    configured_dimensions = {limit.dimension for limit in limits}
    buckets_by_dimension = {
        dimension: weight_buckets(positions, figures, attribute)
        for dimension, attribute in POLICY_LIMIT_ATTRIBUTE.items()
        if dimension in configured_dimensions
    }
    declared_value = 0.0
    if "declared_valuation" in configured_dimensions:
        for p in positions:
            value, *_ = figures[p.id]
            if value is not None and p.instrument.not_priceable_reason in DECLARED_VALUE_FRESHNESS_DAYS:
                declared_value += value

    gaps: list[PersonalPolicyGapOut] = []
    for limit in limits:
        if limit.dimension == "line":
            for p in positions:
                value, *_ = figures[p.id]
                if value is None:
                    continue
                pct = round(value / total_value * 100, 2)
                state, gap_pct = limit_state(pct, limit.min_pct, limit.max_pct)
                if state != "within":
                    gaps.append(
                        PersonalPolicyGapOut(
                            limit_id=limit.id, dimension=limit.dimension, target=p.instrument.broker_symbol,
                            current_pct=pct, min_pct=limit.min_pct, max_pct=limit.max_pct,
                            state=state, gap_pct=gap_pct,
                        )
                    )
            continue

        if limit.dimension == "declared_valuation":
            pct = round(declared_value / total_value * 100, 2)
        else:
            bucket_value = buckets_by_dimension.get(limit.dimension, {}).get(limit.target or "", 0.0)
            pct = round(bucket_value / total_value * 100, 2)

        state, gap_pct = limit_state(pct, limit.min_pct, limit.max_pct)
        if state != "within":
            gaps.append(
                PersonalPolicyGapOut(
                    limit_id=limit.id, dimension=limit.dimension, target=limit.target,
                    current_pct=pct, min_pct=limit.min_pct, max_pct=limit.max_pct,
                    state=state, gap_pct=gap_pct,
                )
            )

    return gaps


def attention_items(db: Session) -> list[AttentionItemOut]:
    """A short, ranked list of facts worth checking today — cache-only, never
    triggers a fetch. Built entirely from indicators the app already
    computes elsewhere: price freshness (`_price_status`), unresolved
    symbols, and configured allocation targets. Empty whenever nothing
    currently warrants a look; the frontend shows a reassuring "all clear"
    state in that case rather than this endpoint fabricating one.

    Deliberately excludes 'not_priceable' instruments (CFDs and anything
    else permanently outside pricing by design — not a problem to fix) and
    "no_target" allocation rows (nothing configured means nothing to flag).
    """
    items: list[AttentionItemOut] = []

    positions = list(db.execute(select(Position).options(joinedload(Position.instrument))).scalars())
    stale_count = 0
    error_count = 0
    for position in positions:
        status = _price_status(position.instrument)
        if status == "stale":
            stale_count += 1
        elif status == "error":
            error_count += 1
    if error_count:
        items.append(AttentionItemOut(severity="missing", kind="price_error", count=error_count))
    if stale_count:
        items.append(AttentionItemOut(severity="warning", kind="price_stale", count=stale_count))

    unresolved_count = len(unresolved_instruments(db))
    if unresolved_count:
        items.append(
            AttentionItemOut(severity="missing", kind="unresolved_instruments", count=unresolved_count)
        )

    buckets, total_value = current_allocation_values(db)
    if total_value:
        targets = category_limits(db)
        for category, target in targets.items():
            row = allocation_row(category, buckets.get(category, 0.0), total_value, target)
            if row.state in ("under", "over"):
                items.append(
                    AttentionItemOut(
                        severity="warning",
                        kind=f"allocation_{row.state}",
                        count=1,
                        category=category,
                        gap_pct=row.gap_pct,
                    )
                )

    severity_order = {"missing": 0, "warning": 1}
    items.sort(key=lambda item: severity_order[item.severity])
    return items


def position_signal(band: str, allocation_state: str) -> str:
    """Combines two indicators the app already shows separately — the
    composite score and the asset class's allocation gap — into one label,
    by a fixed, fully transparent rule. Not a new analysis: every input is
    already visible elsewhere in the app (`GET /scoring/scores`,
    `GET /allocation`); this only names the combination.

    "not_applicable" whenever either input can't support a direction: no
    configured allocation target for the category (no_target — nothing to
    compare against), or no computable score (none — an ETF/CFD/stock
    missing fundamentals). Deliberately not defaulting either case to
    "hold": that would read as a confident "no action needed" when the
    honest answer is "not enough data to say".
    """
    if allocation_state == "no_target" or band == "none":
        return "not_applicable"
    if band == "high" and allocation_state == "under":
        return "reinforce"
    if band == "low" and allocation_state == "over":
        return "reduce"
    return "hold"


def position_signals(db: Session) -> list[PositionSignalOut]:
    """One signal per held instrument, derived from its own composite score
    and its asset class's allocation gap — see `position_signal` for the
    exact rule. Descriptive by construction: it never names a trade, only
    labels a combination of indicators the app already shows separately.
    """
    positions = list(
        db.execute(select(Position).options(joinedload(Position.instrument))).scalars()
    )
    instruments = {p.instrument.id: p.instrument for p in positions}.values()

    config = get_scoring_config()
    scores = {s.instrument_id: s for s in compute_scores(db, list(instruments), config)}

    buckets, total_value = current_allocation_values(db)
    targets = category_limits(db)
    categories = set(buckets) | set(targets)
    allocation_by_category = {
        category: allocation_row(category, buckets.get(category, 0.0), total_value, targets.get(category))
        for category in categories
    }

    signals = []
    for instrument in instruments:
        category = instrument.category or "UNKNOWN"
        category_row = allocation_by_category.get(category)
        allocation_state = category_row.state if category_row else "no_target"
        gap_pct = category_row.gap_pct if category_row else 0.0
        score_result = scores.get(instrument.id)
        composite = score_result.composite if score_result else None
        band = score_band(composite)

        signals.append(
            PositionSignalOut(
                instrument_id=instrument.id,
                signal=position_signal(band, allocation_state),
                composite_score=composite,
                score_band=band,
                category=instrument.category,
                allocation_state=allocation_state,
                gap_pct=gap_pct,
            )
        )
    return signals
