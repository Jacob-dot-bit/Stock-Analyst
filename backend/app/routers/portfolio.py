"""Portfolio endpoints: read, manual entry, mapping correction."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.corporate_actions.service import list_incomplete_instrument_ids, list_outstanding_candidates
from app.db import get_db
from app.ingest.service import get_or_create_instrument
from app.models import (
    AppMetadata,
    CorporateAction,
    CorporateActionConfidence,
    Fundamental,
    ImportBatch,
    Instrument,
    LastQuote,
    Lot,
    LotType,
    MappingStatus,
    PersonalPolicy,
    PersonalPolicyLimit,
    Position,
    ScreenerCandidate,
    Source,
    SymbolOverride,
    Transaction,
    TxType,
    WatchlistItem,
)
from app.portfolio.review import (
    allocation_row,
    allocation_rows,
    attention_items,
    category_limits,
    current_allocation_values,
    policy_gaps,
    position_signals,
    unresolved_instruments,
)
from app.portfolio.valuation import (
    DECLARED_VALUE_FRESHNESS_DAYS,
    DECLARED_VALUE_PROVIDER_NAME,
    compute_account_totals,
    compute_figures,
    compute_totals,
    declared_valuation_note,
    positions_figures_and_total,
    weight_buckets,
)
from app.prices.history_service import compute_max_drawdown, compute_value_history
from app.prices.provider_usage import record_usage
from app.prices.quote_service import fetch_live_quotes, get_quote_progress
from app.prices.service import FRESH_WINDOW_DAYS, price_status as _price_status
from app.providers.base import InstrumentRef, ProviderError
from app.providers.fmp import FmpProvider
from app.providers.frankfurt import looks_like_isin
from app.providers.registry import get_provider_chain
from app.providers.wikidata import resolve_sector as resolve_wikidata_sector
from app.schemas import (
    AllocationRowOut,
    AllocationTargetIn,
    AttentionItemOut,
    BackfillFigisOut,
    BackfillIsinsOut,
    BreakdownItem,
    DataHealthCorporateActionsOut,
    DataHealthOut,
    DataHealthRowOut,
    DataHealthSummaryOut,
    DataHealthValuationOut,
    DeclaredValuationSourceOut,
    DrawdownOut,
    EnrichSectorsOut,
    FigiDuplicatePairOut,
    IsinIn,
    InstrumentOut,
    LiquidityOut,
    LotOut,
    ManualPositionIn,
    MessageOut,
    OnboardingStatusOut,
    PersonalPolicyGapOut,
    PersonalPolicyIn,
    PersonalPolicyLimitIn,
    PersonalPolicyLimitOut,
    PersonalPolicyOut,
    PortfolioOut,
    PositionConcentrationOut,
    PositionOut,
    PositionSignalOut,
    QuoteStatusOut,
    SymbolOverrideIn,
    SymbolSearchResult,
    ValueHistoryOut,
    ValueHistoryPointOut,
)
from app.symbols.duplicates import backfill_figis, backfill_isins, find_figi_duplicates

#: Dimensions the breakdown endpoint can group by, and the Instrument attribute each
#: reads. category/currency/country are populated by the XTB import; sector needs
#: POST /enrich-sectors to have been run first (FMP for US holdings, Wikidata for
#: most others — see `enrich_sectors`) — an instrument with no sector yet groups
#: under "UNKNOWN", same as any other gap (always true for ETFs and CFDs, which
#: have no single sector by nature).
BREAKDOWN_DIMENSIONS = {"category", "currency", "country", "sector"}

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

def _build_portfolio_out(
    db: Session, positions: list[Position], live_quotes: dict[int, tuple[float, str]]
) -> PortfolioOut:
    """Shared by the cache-only ``GET`` and the budgeted ``POST /refresh-live``:
    same computation, the only difference is whether `live_quotes` has anything
    in it. Everything downstream (totals, per-account, per-position, weight%)
    picks the fresher price automatically.
    """
    base_currency = get_settings().base_currency
    figures = compute_figures(db, positions, base_currency, live_quotes)
    totals = compute_totals(positions, base_currency, figures)
    totals.realized_pl = db.execute(
        select(func.sum(Transaction.amount)).where(Transaction.type == TxType.CLOSED_TRADE)
    ).scalar()

    positions_out = []
    any_stale_declared_valuation = False
    for p in positions:
        position_out = PositionOut.model_validate(p)
        value, pl, pl_pct, price, source = figures[p.id]
        position_out.current_value = value
        position_out.current_unrealized_pl = pl
        position_out.current_unrealized_pl_pct = pl_pct
        position_out.current_price = price
        position_out.price_source = source
        if totals.market_value and value is not None:
            position_out.weight_percent = round(value / totals.market_value * 100, 2)
        position_out.instrument.price_status = _price_status(p.instrument)
        freshness, note = declared_valuation_note(p.instrument, p.value_as_of)
        position_out.valuation_note = MessageOut(**note) if note else None
        if freshness == "stale":
            any_stale_declared_valuation = True
        positions_out.append(position_out)
    totals.has_stale_declared_valuations = any_stale_declared_valuation

    unresolved = unresolved_instruments(db)
    last_batch = db.execute(
        select(ImportBatch).order_by(ImportBatch.imported_at.desc()).limit(1)
    ).scalar_one_or_none()
    metadata = db.execute(select(AppMetadata)).scalar_one_or_none()

    return PortfolioOut(
        totals=totals,
        accounts=compute_account_totals(positions, figures),
        positions=positions_out,
        unresolved_symbols=[InstrumentOut.model_validate(i) for i in unresolved],
        last_import_at=last_batch.imported_at if last_batch else None,
        last_price_refresh_at=metadata.last_price_refresh_time if metadata else None,
    )


@router.get("", response_model=PortfolioOut)
def get_portfolio(db: Session = Depends(get_db)) -> PortfolioOut:
    """Current portfolio state: cache-only, never calls a price provider.

    Market value, unrealised P&L and performance are computed from whatever is
    already cached (today's live quote if `POST /refresh-live` fetched one this
    session, else the latest daily close, else the broker's own frozen figure
    for CFDs and anything not yet priced) — see `position_figures` and
    DEVLOG "Decision 2f.3". Cost basis (invested value) still comes from the
    broker import, since that is the one figure this app cannot recompute
    better than the broker already did.
    """
    positions = list(
        db.execute(
            select(Position).options(joinedload(Position.instrument))
        ).scalars()
    )
    return _build_portfolio_out(db, positions, live_quotes={})


@router.get("/breakdown", response_model=list[BreakdownItem])
def get_breakdown(
    by: str = Query(..., description="One of: category, currency, country, sector."),
    db: Session = Depends(get_db),
) -> list[BreakdownItem]:
    """Portfolio market value grouped by category, currency, country or sector.

    category/currency/country use data already captured at import time — no new
    provider or API key required. sector needs POST /enrich-sectors to have been
    run at least once (FMP for US holdings, Wikidata for most others — DEVLOG
    "Decision 3c.1"); until then, or for ETFs/CFDs (no single sector by nature),
    it groups under "UNKNOWN", same as any instrument this endpoint has no data for.
    A position with no valuation is excluded, same rule as the totals: a slice
    count that silently treated missing data as zero would misstate the split
    without looking wrong.
    """
    if by not in BREAKDOWN_DIMENSIONS:
        raise HTTPException(status_code=400, detail=f"'by' must be one of {sorted(BREAKDOWN_DIMENSIONS)}")

    positions, figures, total_value = positions_figures_and_total(db)
    if not total_value:
        return []

    buckets = weight_buckets(positions, figures, by)
    items = [
        BreakdownItem(label=label, value=round(value, 2), weight_percent=round(value / total_value * 100, 2))
        for label, value in buckets.items()
    ]
    items.sort(key=lambda item: item.value, reverse=True)
    return items


@router.get("/allocation", response_model=list[AllocationRowOut])
def get_allocation(db: Session = Depends(get_db)) -> list[AllocationRowOut]:
    return allocation_rows(db)


@router.put("/allocation/{category}", response_model=AllocationRowOut)
def set_allocation_target(
    category: str, payload: AllocationTargetIn, db: Session = Depends(get_db)
) -> AllocationRowOut:
    """Set (or replace) the target range for one asset class."""
    category = category.strip().upper()

    target = category_limits(db).get(category)
    if target is None:
        target = PersonalPolicyLimit(
            dimension="category", target=category, min_pct=payload.min_pct, max_pct=payload.max_pct
        )
        db.add(target)
    else:
        target.min_pct = payload.min_pct
        target.max_pct = payload.max_pct
    db.commit()

    buckets, total_value = current_allocation_values(db)
    return allocation_row(category, buckets.get(category, 0.0), total_value, target)


@router.delete("/allocation/{category}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_allocation_target(category: str, db: Session = Depends(get_db)) -> Response:
    """Remove a configured target — the category reverts to "no_target" (or
    disappears from `GET /allocation` entirely if also currently unheld)."""
    db.execute(
        delete(PersonalPolicyLimit).where(
            PersonalPolicyLimit.dimension == "category", PersonalPolicyLimit.target == category.strip().upper()
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _get_or_create_policy(db: Session) -> PersonalPolicy:
    policy = db.execute(select(PersonalPolicy)).scalar_one_or_none()
    if policy is None:
        policy = PersonalPolicy()
        db.add(policy)
        db.commit()
        db.refresh(policy)
    return policy


@router.get("/policy", response_model=PersonalPolicyOut)
def get_personal_policy(db: Session = Depends(get_db)) -> PersonalPolicy:
    """The user's own, self-declared investment policy — every field
    optional. Never inferred or scored by the app; see DEVLOG "Decision
    3u.59"."""
    return _get_or_create_policy(db)


@router.put("/policy", response_model=PersonalPolicyOut)
def set_personal_policy(payload: PersonalPolicyIn, db: Session = Depends(get_db)) -> PersonalPolicy:
    """Replaces the whole policy in one call — the edit form always submits
    every field, so there is no partial-update ambiguity to resolve."""
    policy = _get_or_create_policy(db)
    for field, value in payload.model_dump().items():
        setattr(policy, field, value)
    db.commit()
    db.refresh(policy)
    return policy


@router.get("/policy/limits", response_model=list[PersonalPolicyLimitOut])
def get_personal_policy_limits(db: Session = Depends(get_db)) -> list[PersonalPolicyLimit]:
    return list(db.execute(select(PersonalPolicyLimit).order_by(PersonalPolicyLimit.id)).scalars())


@router.post("/policy/limits", response_model=PersonalPolicyLimitOut, status_code=status.HTTP_201_CREATED)
def create_personal_policy_limit(
    payload: PersonalPolicyLimitIn, db: Session = Depends(get_db)
) -> PersonalPolicyLimit:
    """One personal concentration rule. `(dimension, target)` is unique — a
    second "line" or "declared_valuation" rule (both have `target=None`,
    which SQLite's unique index would not by itself catch) is rejected
    here explicitly, same as a duplicate named target."""
    existing = db.execute(
        select(PersonalPolicyLimit).where(
            PersonalPolicyLimit.dimension == payload.dimension, PersonalPolicyLimit.target == payload.target
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="a limit for this dimension/target already exists")

    limit = PersonalPolicyLimit(**payload.model_dump())
    db.add(limit)
    db.commit()
    db.refresh(limit)
    return limit


@router.delete("/policy/limits/{limit_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_personal_policy_limit(limit_id: int, db: Session = Depends(get_db)) -> Response:
    db.execute(delete(PersonalPolicyLimit).where(PersonalPolicyLimit.id == limit_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/policy/gaps", response_model=list[PersonalPolicyGapOut])
def get_personal_policy_gaps(db: Session = Depends(get_db)) -> list[PersonalPolicyGapOut]:
    return policy_gaps(db)


@router.get("/risk/concentration", response_model=list[PositionConcentrationOut])
def get_risk_concentration(
    limit: int = Query(10, ge=1, le=100), db: Session = Depends(get_db)
) -> list[PositionConcentrationOut]:
    """Every held position's share of total portfolio value, largest first,
    capped at `limit` — the unconditional, always-visible counterpart to
    Personal Policy's `line` limit (`/policy/gaps` only reports a *breach*
    of a *configured* line limit; this reports the top N regardless of
    whether any limit exists). See DEVLOG "Decision 3u.67".
    """
    positions, figures, total_value = positions_figures_and_total(db)
    if not total_value:
        return []

    rows = []
    for p in positions:
        value, *_ = figures[p.id]
        if value is None:
            continue
        rows.append(
            PositionConcentrationOut(
                instrument_id=p.instrument.id,
                symbol=p.instrument.broker_symbol,
                name=p.instrument.name,
                category=p.instrument.category,
                value=round(value, 2),
                weight_percent=round(value / total_value * 100, 2),
            )
        )
    rows.sort(key=lambda r: r.weight_percent, reverse=True)
    return rows[:limit]


@router.get("/risk/liquidity", response_model=LiquidityOut)
def get_risk_liquidity(db: Session = Depends(get_db)) -> LiquidityOut:
    """Share of the portfolio priced from a periodically-declared broker
    statement rather than a live market quote (Mintos Core P2P, Amundi
    ESR), broken down by source and freshness — the unconditional
    counterpart to Personal Policy's `declared_valuation` limit
    (`/policy/gaps` only reports this when a limit is configured, and only
    the aggregate percentage). Deliberately excludes structurally
    non-priceable residuals (corporate-action leftovers): that is a
    data-trust fact already covered by `/data-health`, not a liquidity
    fact. See DEVLOG "Decision 3u.67".
    """
    positions, figures, total_value = positions_figures_and_total(db)
    if not total_value:
        return LiquidityOut(total_declared_value=0.0, total_declared_weight_percent=0.0, sources=[])

    by_reason: dict[str, list[tuple[Position, float]]] = defaultdict(list)
    for p in positions:
        value, *_ = figures[p.id]
        reason = p.instrument.not_priceable_reason
        if value is not None and reason in DECLARED_VALUE_FRESHNESS_DAYS:
            by_reason[reason].append((p, value))

    sources = []
    total_declared = 0.0
    for reason, rows in by_reason.items():
        source_value = sum(v for _, v in rows)
        total_declared += source_value
        as_of_dates = [p.value_as_of for p, _ in rows if p.value_as_of is not None]
        has_stale = any(declared_valuation_note(p.instrument, p.value_as_of)[0] == "stale" for p, _ in rows)
        sources.append(
            DeclaredValuationSourceOut(
                reason=reason,
                provider_name=DECLARED_VALUE_PROVIDER_NAME[reason],
                value=round(source_value, 2),
                weight_percent=round(source_value / total_value * 100, 2),
                positions_count=len(rows),
                freshest_as_of=max(as_of_dates) if as_of_dates else None,
                stalest_as_of=min(as_of_dates) if as_of_dates else None,
                has_stale=has_stale,
            )
        )
    sources.sort(key=lambda s: s.weight_percent, reverse=True)
    return LiquidityOut(
        total_declared_value=round(total_declared, 2),
        total_declared_weight_percent=round(total_declared / total_value * 100, 2),
        sources=sources,
    )


@router.get("/risk/drawdown", response_model=DrawdownOut)
def get_risk_drawdown(db: Session = Depends(get_db)) -> DrawdownOut:
    """Largest peak-to-trough decline in real historical portfolio value —
    the same `Lot`-replay series `/value-history` already returns
    (`compute_value_history`), never a new data source. See DEVLOG
    "Decision 3u.67".
    """
    settings = get_settings()
    result = compute_value_history(db, settings.base_currency, datetime.now(UTC).date())
    dd = compute_max_drawdown(result.points)
    return DrawdownOut(
        insufficient_history=dd.insufficient_history,
        max_drawdown_pct=dd.max_drawdown_pct,
        peak_date=dd.peak_date.isoformat() if dd.peak_date else None,
        peak_value=dd.peak_value,
        trough_date=dd.trough_date.isoformat() if dd.trough_date else None,
        trough_value=dd.trough_value,
        recovered=dd.recovered,
        recovered_date=dd.recovered_date.isoformat() if dd.recovered_date else None,
    )


@router.get("/attention", response_model=list[AttentionItemOut])
def get_attention(db: Session = Depends(get_db)) -> list[AttentionItemOut]:
    return attention_items(db)


#: severity -> sortable rank, most severe first. "not_applicable" ranks
#: below "info" (-1): a not-applicable row is never a problem, so it
#: belongs at the very bottom of a fix-it console, after even the fully
#: healthy rows.
_SEVERITY_RANK = {"action_required": 2, "attention": 1, "info": 0, "not_applicable": -1}

#: `OutstandingCandidate.confidence` values that can reach this endpoint,
#: ordered worst-first — a `verified_*` group is never "outstanding" (see
#: `list_outstanding_candidates`), so those two states never appear here.
_OUTSTANDING_SEVERITY_ORDER = (
    CorporateActionConfidence.SUSPECT_TICKER_REUSE,
    CorporateActionConfidence.PROVIDER_CONFLICT,
    CorporateActionConfidence.CANDIDATE_SINGLE_SOURCE,
)


def _valuation_report(
    instrument: Instrument, position: Position
) -> tuple[DataHealthValuationOut, str, str | None, str | None]:
    """(valuation, severity, reason, recommended_action) for one position's
    current value. See DEVLOG "Decision 3u.58"."""
    reason_code = instrument.not_priceable_reason
    if reason_code and reason_code not in DECLARED_VALUE_FRESHNESS_DAYS:
        # A structural non-value (e.g. a corporate-action residual, CVR) —
        # not a problem to fix, just not a priceable asset by nature.
        return DataHealthValuationOut(kind="unavailable", freshness="unknown"), "not_applicable", None, None

    if reason_code:
        # A periodically-declared broker valuation (Mintos, Amundi ESR).
        provider = DECLARED_VALUE_PROVIDER_NAME[reason_code]
        freshness, _note = declared_valuation_note(instrument, position.value_as_of)
        if freshness is None:
            valuation = DataHealthValuationOut(kind="declared_value", source=provider, freshness="unknown")
            return valuation, "attention", "declared_value_missing_date", "import_recent_statement"
        valuation = DataHealthValuationOut(
            kind="declared_value", source=provider, as_of=position.value_as_of, freshness=freshness
        )
        if freshness == "stale":
            return valuation, "attention", "declared_stale", "import_recent_statement"
        return valuation, "info", None, None

    # An ordinary market-priced instrument — mapping is already resolved and
    # `not_priceable_reason` unset by this point, so `_price_status()` can
    # only answer "error" (checked, never verified), "unmapped" (not yet
    # refreshed once since import — a transient just-imported state, not a
    # mapping gap), "stale" or "fresh".
    status = _price_status(instrument)
    as_of = instrument.prices_checked_at.date() if instrument.prices_checked_at else None
    source = instrument.verified_provider
    if status == "unmapped":
        return DataHealthValuationOut(kind="market_price", freshness="unknown"), "attention", "never_refreshed", "refresh_quotes"
    if status == "error":
        valuation = DataHealthValuationOut(kind="market_price", source=source, as_of=as_of, freshness="unknown")
        return valuation, "action_required", "price_error", "refresh_quotes"
    if status == "stale":
        valuation = DataHealthValuationOut(kind="market_price", source=source, as_of=as_of, freshness="stale")
        return valuation, "attention", "price_stale", "refresh_quotes"
    valuation = DataHealthValuationOut(kind="market_price", source=source, as_of=as_of, freshness="fresh")
    return valuation, "info", None, None


def _corporate_action_report(
    instrument: Instrument,
    valuation_kind: str,
    confirmed_counts: dict[int, int],
    outstanding_by_instrument: dict[int, list],
    incomplete_ids: set[int],
) -> tuple[DataHealthCorporateActionsOut, str, str | None, str | None]:
    """(corporate_actions, severity, reason, recommended_action) for one
    instrument. Corporate actions only ever apply to a market-priced,
    provider-mapped instrument — a declared-value asset (Mintos/Amundi), an
    unavailable one, or a still-unresolved symbol is "not_applicable" here
    by construction, never a problem. See DEVLOG "Decision 3u.58"."""
    if valuation_kind != "market_price" or not instrument.provider_symbol:
        ca = DataHealthCorporateActionsOut(status="not_applicable", confirmed_events=0, outstanding_events=0)
        return ca, "not_applicable", None, None

    confirmed = confirmed_counts.get(instrument.id, 0)
    outstanding = outstanding_by_instrument.get(instrument.id, [])

    if instrument.corporate_actions_checked_at is None:
        ca = DataHealthCorporateActionsOut(status="never_checked", confirmed_events=confirmed, outstanding_events=len(outstanding))
        return ca, "attention", "corporate_action_never_checked", None

    if outstanding:
        worst = next(c for c in _OUTSTANDING_SEVERITY_ORDER if any(o.confidence == c for o in outstanding))
        reason = {
            CorporateActionConfidence.SUSPECT_TICKER_REUSE: "corporate_action_suspect",
            CorporateActionConfidence.PROVIDER_CONFLICT: "corporate_action_conflict",
            CorporateActionConfidence.CANDIDATE_SINGLE_SOURCE: "corporate_action_candidate",
        }[worst]
        ca = DataHealthCorporateActionsOut(status=worst, confirmed_events=confirmed, outstanding_events=len(outstanding))
        return ca, "attention", reason, "verify_eodhd"

    if instrument.id in incomplete_ids:
        ca = DataHealthCorporateActionsOut(status="incomplete_coverage", confirmed_events=confirmed, outstanding_events=0)
        return ca, "attention", "corporate_action_incomplete_coverage", "resume_alpha_vantage"

    status = "verified" if confirmed else "no_events"
    ca = DataHealthCorporateActionsOut(status=status, confirmed_events=confirmed, outstanding_events=0)
    return ca, "info", None, None


def _combine_severity(
    valuation_part: tuple[str, str | None, str | None],
    ca_part: tuple[str, str | None, str | None],
) -> tuple[str, str | None, str | None]:
    """The overall row severity/reason/action is whichever of the valuation
    or corporate-actions signal is more severe — ties keep the valuation
    side, since a value problem is the more fundamental one."""
    v_sev, v_reason, v_action = valuation_part
    ca_sev, ca_reason, ca_action = ca_part
    if _SEVERITY_RANK[v_sev] >= _SEVERITY_RANK[ca_sev]:
        return v_sev, v_reason, v_action
    return ca_sev, ca_reason, ca_action


@router.get("/data-health", response_model=DataHealthOut)
def get_data_health(db: Session = Depends(get_db)) -> DataHealthOut:
    """Per-instrument trust report for held (open) positions only, never
    Watchlist/Screener — this answers "can I trust the numbers valuing what
    I actually own", not "is every known ticker documented". The detailed
    counterpart to `/attention`'s compact counts.

    Every row carries two independent signals — where its *value* comes
    from and how fresh it is, and whether its *corporate-action* history is
    confirmed — combined into one overall severity, so a beginner never has
    to reconcile two separate panels to know whether a number can be
    trusted. See DEVLOG "Decision 3u.58", superseding the category-only v1
    shape ("Decision 3u.33"/"3u.50", still the source of the freshness and
    declared-valuation rules reused here unchanged).
    """
    positions = list(db.execute(select(Position).options(joinedload(Position.instrument))).scalars())
    unresolved_ids = {i.id for i in unresolved_instruments(db)}

    confirmed_counts = dict(
        db.execute(select(CorporateAction.instrument_id, func.count()).group_by(CorporateAction.instrument_id)).all()
    )
    outstanding_by_instrument: dict[int, list] = defaultdict(list)
    for candidate in list_outstanding_candidates(db):
        outstanding_by_instrument[candidate.instrument_id].append(candidate)
    incomplete_ids = set(list_incomplete_instrument_ids(db, "alpha_vantage"))

    rows: list[DataHealthRowOut] = []
    counts = {"info": 0, "attention": 0, "action_required": 0, "not_applicable": 0}
    for position in positions:
        instrument = position.instrument

        if instrument.id in unresolved_ids:
            valuation = DataHealthValuationOut(kind="unavailable", freshness="unknown")
            valuation_part: tuple[str, str | None, str | None] = ("action_required", "unresolved_symbol", "fix_symbol")
        else:
            valuation, v_sev, v_reason, v_action = _valuation_report(instrument, position)
            valuation_part = (v_sev, v_reason, v_action)

        corporate_actions, ca_sev, ca_reason, ca_action = _corporate_action_report(
            instrument, valuation.kind, confirmed_counts, outstanding_by_instrument, incomplete_ids
        )
        severity, reason, action = _combine_severity(valuation_part, (ca_sev, ca_reason, ca_action))
        counts[severity] += 1

        rows.append(
            DataHealthRowOut(
                instrument_id=instrument.id,
                symbol=instrument.broker_symbol,
                name=instrument.name,
                valuation=valuation,
                corporate_actions=corporate_actions,
                severity=severity,
                reason=reason,
                recommended_action=action,
            )
        )

    rows.sort(key=lambda r: (-_SEVERITY_RANK[r.severity], r.symbol))
    summary = DataHealthSummaryOut(
        total_instruments=len(rows),
        info_count=counts["info"],
        attention_count=counts["attention"],
        action_required_count=counts["action_required"],
        not_applicable_count=counts["not_applicable"],
    )

    held_ids = {p.instrument_id for p in positions}
    watchlist_ids = set(db.execute(select(WatchlistItem.instrument_id)).scalars())
    screener_ids = set(db.execute(select(ScreenerCandidate.instrument_id)).scalars())

    def _sources(instrument_id: int) -> list[str]:
        sources = []
        if instrument_id in held_ids:
            sources.append("held")
        if instrument_id in watchlist_ids:
            sources.append("watchlist")
        if instrument_id in screener_ids:
            sources.append("screener")
        return sources

    figi_duplicates = [
        FigiDuplicatePairOut(
            a_instrument_id=a.id,
            a_symbol=a.broker_symbol,
            a_name=a.name,
            a_sources=_sources(a.id),
            b_instrument_id=b.id,
            b_symbol=b.broker_symbol,
            b_name=b.name,
            b_sources=_sources(b.id),
            share_class_figi=a.share_class_figi,
        )
        for a, b in find_figi_duplicates(db)
    ]

    return DataHealthOut(summary=summary, rows=rows, figi_duplicates=figi_duplicates)


@router.get("/onboarding", response_model=OnboardingStatusOut)
def get_onboarding_status(db: Session = Depends(get_db)) -> OnboardingStatusOut:
    """Whether each first-run step has been done at least once — a plain
    existence check against tables the app already maintains, no new
    tracking. Backs the dismissible "getting started" checklist on the
    Portfolio page. See DEVLOG "Decision 3u.26"."""
    imported = db.execute(select(ImportBatch.id).limit(1)).first() is not None
    metadata = db.execute(select(AppMetadata)).scalar_one_or_none()
    fundamentals_fetched = db.execute(select(Fundamental.id).limit(1)).first() is not None
    allocation_target_set = (
        db.execute(select(PersonalPolicyLimit.id).where(PersonalPolicyLimit.dimension == "category").limit(1)).first()
        is not None
    )
    watchlist_started = db.execute(select(WatchlistItem.id).limit(1)).first() is not None

    return OnboardingStatusOut(
        imported=imported,
        prices_refreshed=metadata is not None and metadata.last_price_refresh_time is not None,
        unresolved_resolved=len(unresolved_instruments(db)) == 0,
        fundamentals_fetched=fundamentals_fetched,
        allocation_target_set=allocation_target_set,
        watchlist_started=watchlist_started,
    )


@router.get("/position-signals", response_model=list[PositionSignalOut])
def get_position_signals(db: Session = Depends(get_db)) -> list[PositionSignalOut]:
    return position_signals(db)


@router.get("/value-history", response_model=ValueHistoryOut)
def get_value_history(db: Session = Depends(get_db)) -> ValueHistoryOut:
    """Real historical portfolio value, replaying actual buys/sells from the
    `Lot` ledger day by day — not a backtest of today's holdings (see DEVLOG
    "Decision 3b.1"). Cache-only: never calls a price provider, only Frankfurter
    for FX date ranges not already cached, so this is safe on every page load.

    The range is capped by whatever price history actually exists
    (`capped_by_history`), and a day with holdings that could not be priced at
    all reports `value: null` rather than a guessed number — never zero for
    missing data.
    """
    settings = get_settings()
    result = compute_value_history(db, settings.base_currency, datetime.now(UTC).date())
    return ValueHistoryOut(
        points=[
            ValueHistoryPointOut(
                date=point.day.isoformat(),
                value=point.value,
                invested=point.invested,
                benchmark=point.benchmark,
            )
            for point in result.points
        ],
        start_date=result.start_date.isoformat() if result.start_date else None,
        capped_by_history=result.capped_by_history,
        benchmark_available=result.benchmark_available,
        benchmark_name=settings.benchmark_name if result.benchmark_available else None,
    )


@router.get("/lots", response_model=list[LotOut])
def get_lots(instrument_id: int = Query(...), db: Session = Depends(get_db)) -> list[LotOut]:
    """Every actual buy fill for one instrument, open and closed alike,
    newest first — the per-position detail panel's "Historique" section.
    No endpoint returned individual `Lot` rows before this; everything
    else that touches `Lot` only ever writes it (imports, manual position
    edits) or replays it in aggregate (the value-history chart, the
    dividend-yield score metric)."""
    lots = db.execute(
        select(Lot).where(Lot.instrument_id == instrument_id).order_by(Lot.opened_at.desc())
    ).scalars()
    return [LotOut.model_validate(lot) for lot in lots]


@router.post("/enrich-sectors", response_model=EnrichSectorsOut)
def enrich_sectors(db: Session = Depends(get_db)) -> EnrichSectorsOut:
    """One-off lookup of sector/industry for held instruments — two independent
    sources, tried in order per instrument.

    FMP's `/profile` endpoint first, when a key is configured — but it is
    US-only on the free tier (verified live: TTE.PA and DCAM.PA both answer
    HTTP 402). Wikidata second, for whatever FMP couldn't or wouldn't serve:
    free, keyless, and it carries the data for most large, well-known
    non-US companies (see DEVLOG "Decision 3c.1"). A Wikidata sector is only
    used after passing through its own normalisation table, so the breakdown
    chart never mixes two different sector vocabularies.

    Not part of the daily price refresh on purpose: sector barely changes, so
    asking again every day would spend FMP's 250-request/day free-tier quota
    on data that was already correct. An instrument that already has a
    `sector` (from a previous run) is skipped, making repeated calls to this
    endpoint cheap — it only ever asks about what it doesn't know yet.

    ETFs and CFDs are left out entirely, not just unenriched: an ETF holds a
    basket, it doesn't have *one* sector, so "Inconnu" is the only honest
    answer regardless of data source; a CFD has no fundamentals by nature.
    """
    settings = get_settings()
    fmp = FmpProvider(api_key=settings.fmp_api_key) if settings.fmp_api_key else None

    positions = list(
        db.execute(select(Position).options(joinedload(Position.instrument))).scalars()
    )
    candidates: dict[int, Instrument] = {}
    for p in positions:
        instrument = p.instrument
        if instrument.sector or instrument.not_priceable_reason:
            continue
        if instrument.category in ("ETF", "CFD"):
            continue
        candidates[instrument.id] = instrument

    enriched = skipped = failed = 0
    for instrument in candidates.values():
        sector: str | None = None
        industry: str | None = None

        if fmp is not None:
            ref = InstrumentRef(
                provider_symbol=instrument.provider_symbol,
                isin=instrument.isin,
                broker_symbol=instrument.broker_symbol,
                name=instrument.name,
                category=instrument.category,
            )
            if fmp.can_serve(ref):
                try:
                    profile = fmp.fetch_profile(ref)
                except ProviderError:
                    profile = None
                finally:
                    record_usage(db, "fmp")
                if profile and profile.get("sector"):
                    sector = profile["sector"]
                    industry = profile.get("industry")

        if sector is None and instrument.name:
            sector = resolve_wikidata_sector(instrument.name)

        if sector is None:
            skipped += 1
            continue

        instrument.sector = sector
        instrument.industry = industry
        enriched += 1
        db.commit()

    return EnrichSectorsOut(enriched=enriched, skipped=skipped, failed=failed)


@router.post("/backfill-isins", response_model=BackfillIsinsOut)
def backfill_isins_endpoint(db: Session = Depends(get_db)) -> BackfillIsinsOut:
    """One-off catch-up run of `symbols/duplicates.py::backfill_isins` — see
    its docstring. Only reaches instruments that already have a `name` on
    file; anything manually typed with no name still needs one supplied by
    hand (the create/update endpoints' `company_name` field).
    """
    result = backfill_isins(db)
    return BackfillIsinsOut(**result)


@router.post("/backfill-figis", response_model=BackfillFigisOut)
def backfill_figis_endpoint(db: Session = Depends(get_db)) -> BackfillFigisOut:
    """One-off catch-up run of `symbols/duplicates.py::backfill_figis` —
    resolves a canonical OpenFIGI identity for tracked instruments that
    don't have one yet, same "click again to continue" batching as
    `/backfill-isins`. See DEVLOG "Decision 3u.76"."""
    settings = get_settings()
    result = backfill_figis(db, settings.openfigi_api_key, settings.openfigi_max_jobs_per_request)
    return BackfillFigisOut(**result)


@router.get("/symbol-search", response_model=list[SymbolSearchResult])
def symbol_search(
    q: str = Query(..., min_length=1, description="Company name or partial name to search."),
    db: Session = Depends(get_db),
) -> list[SymbolSearchResult]:
    """Company-name lookup for the manual-position form's autocomplete.

    Just proxies FMP's search-by-name so the frontend never handles the API
    key — the only reason this now takes `db` is to record the request
    against FMP's shared daily quota (see `prices/provider_usage.py`), the
    same bucket `fetch_profile`/`fetch_daily`/`fetch_quote` all draw from.
    US-only on FMP's free tier, like everything else FMP serves here.
    """
    settings = get_settings()
    if not settings.fmp_api_key:
        raise HTTPException(
            status_code=400, detail="FMP_API_KEY is not configured — symbol search needs it."
        )

    fmp = FmpProvider(api_key=settings.fmp_api_key)
    try:
        results = fmp.search_by_name(q)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        record_usage(db, "fmp")

    return [SymbolSearchResult(**r) for r in results]


@router.post("/refresh-live", response_model=PortfolioOut)
def refresh_live_prices(db: Session = Depends(get_db)) -> PortfolioOut:
    """Budgeted live-quote round, then the whole portfolio recomputed with it.

    The second phase of the single "Actualiser" action (see DEVLOG "Decision
    2f.2" / "2f.3"): the first phase, ``POST /api/prices/refresh``, brings the
    daily-bar cache up to date; this one spends real provider quota on one
    lightweight quote per held instrument, budgeted the same way, because free
    quote sources throttle to a few seconds per request. Whatever the budget
    does not reach falls back to the cached daily close, same as the plain GET
    — this never returns a *worse* result than ``GET /portfolio``, only a
    fresher one wherever the budget allowed.
    """
    settings = get_settings()

    positions = list(
        db.execute(select(Position).options(joinedload(Position.instrument))).scalars()
    )
    # De-duplicate: the same instrument can be held across multiple accounts,
    # and a quote is per-instrument, not per-position.
    instruments = {
        p.instrument.id: p.instrument
        for p in positions
        if not p.instrument.not_priceable_reason and p.instrument.category != "CFD"
    }

    live_quotes = fetch_live_quotes(
        list(instruments.values()),
        get_provider_chain(),
        budget_seconds=settings.refresh_budget_seconds,
        on_attempt=lambda name: record_usage(db, name),
    )
    _save_last_quotes(db, live_quotes)
    return _build_portfolio_out(db, positions, live_quotes)


def _save_last_quotes(db: Session, live_quotes: dict[int, tuple[float, str]]) -> None:
    """Persist this round's quotes so they outlive the one response body they
    used to only exist in — reloading the page right after a refresh no
    longer reverts the price to whatever daily close happened to be cached.
    See DEVLOG "Decision 3o.1".
    """
    if not live_quotes:
        return
    now = datetime.now(UTC)
    for instrument_id, (price, provider) in live_quotes.items():
        row = db.get(LastQuote, instrument_id)
        if row is None:
            db.add(LastQuote(instrument_id=instrument_id, price=price, provider=provider, fetched_at=now))
        else:
            row.price, row.provider, row.fetched_at = price, provider, now
    db.commit()


@router.get("/refresh-live/status", response_model=QuoteStatusOut)
def refresh_live_status() -> QuoteStatusOut:
    """Live progress of a live-quote round in flight."""
    progress = get_quote_progress()
    return QuoteStatusOut(
        running=progress.running,
        total=progress.total,
        done=progress.done,
        current_symbol=progress.current_symbol,
        started_at=progress.started_at,
        finished_at=progress.finished_at,
    )


@router.post("/positions", response_model=PositionOut, status_code=status.HTTP_201_CREATED)
def create_manual_position(payload: ManualPositionIn, db: Session = Depends(get_db)) -> PositionOut:
    """Add a hand-entered position (instrument missing from the export, or another broker)."""
    instrument = get_or_create_instrument(db, payload.broker_symbol, currency=payload.currency)

    position = Position(
        instrument_id=instrument.id,
        source=Source.MANUAL,
        account=payload.account,
        quantity=payload.quantity,
        avg_price=payload.avg_price,
        currency=payload.currency or instrument.currency,
        opened_at=payload.opened_at,
        comment=payload.comment,
    )
    db.add(position)
    # A single synthetic lot, so the historical value chart's reconstruction
    # ledger has exactly one source of truth for both imported and hand-entered
    # holdings — see DEVLOG "Decision 3b.1". No external_id: a manual entry has
    # nothing to re-import against, so there is no deduplication to do.
    db.add(
        Lot(
            instrument_id=instrument.id,
            account=payload.account,
            source=Source.MANUAL,
            lot_type=LotType.OPEN,
            quantity=payload.quantity,
            open_price=payload.avg_price,
            opened_at=payload.opened_at or datetime.now(UTC),
            currency=payload.currency or instrument.currency,
        )
    )
    db.commit()
    db.refresh(position)
    return PositionOut.model_validate(position)


@router.delete(
    "/positions/{position_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_position(position_id: int, db: Session = Depends(get_db)) -> Response:
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found.")
    # Only the still-open lots that make up *this* position — never closed lots,
    # which are settled history independent of whether the position still exists.
    db.execute(
        delete(Lot).where(
            Lot.instrument_id == position.instrument_id,
            Lot.account == position.account,
            Lot.source == position.source,
            Lot.lot_type == LotType.OPEN,
            Lot.closed_at.is_(None),
        )
    )
    db.delete(position)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/instruments/{instrument_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_instrument(instrument_id: int, db: Session = Depends(get_db)) -> Response:
    """Remove an instrument that turned out not to be a real, trackable holding
    (a parsing artefact, a bad manual entry) — without forcing a correction
    first. Refuses whenever the instrument is still tied to real data (a
    position, a lot, a transaction, a watchlist entry): those must be deleted
    individually first, since silently erasing them here would be exactly the
    kind of data loss `Lot`'s design deliberately guards against.
    """
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found.")

    in_use = (
        db.execute(select(Position.id).where(Position.instrument_id == instrument_id).limit(1)).first()
        or db.execute(select(Lot.id).where(Lot.instrument_id == instrument_id).limit(1)).first()
        or db.execute(select(Transaction.id).where(Transaction.instrument_id == instrument_id).limit(1)).first()
        or db.execute(
            select(WatchlistItem.id).where(WatchlistItem.instrument_id == instrument_id).limit(1)
        ).first()
    )
    if in_use:
        raise HTTPException(
            status_code=400,
            detail="This instrument still has positions, lots, transactions, or a "
            "watchlist entry — remove those first.",
        )

    db.execute(delete(SymbolOverride).where(SymbolOverride.broker_symbol == instrument.broker_symbol))
    db.delete(instrument)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/symbol-overrides", response_model=InstrumentOut)
def set_symbol_override(payload: SymbolOverrideIn, db: Session = Depends(get_db)) -> InstrumentOut:
    """Manually fix the mapping between an XTB symbol and the provider symbol.

    Needed for cases suffix conversion cannot guess, typically multi-class shares
    (``ERICB.SE`` → ``ERIC-B.ST``).
    """
    broker_symbol = payload.broker_symbol.strip().upper()
    provider_symbol = payload.provider_symbol.strip().upper()

    override = db.execute(
        select(SymbolOverride).where(SymbolOverride.broker_symbol == broker_symbol)
    ).scalar_one_or_none()

    if override is None:
        override = SymbolOverride(broker_symbol=broker_symbol, provider_symbol=provider_symbol)
        db.add(override)
    else:
        override.provider_symbol = provider_symbol
    override.note = payload.note

    instrument = db.execute(
        select(Instrument).where(Instrument.broker_symbol == broker_symbol)
    ).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(
            status_code=404,
            detail=f"No known instrument for symbol '{broker_symbol}'.",
        )

    instrument.provider_symbol = provider_symbol
    instrument.mapping_status = MappingStatus.MANUAL

    db.commit()
    db.refresh(instrument)
    return InstrumentOut.model_validate(instrument)


@router.put("/isin", response_model=InstrumentOut)
def set_isin(payload: IsinIn, db: Session = Depends(get_db)) -> InstrumentOut:
    """Record an instrument's ISIN, which unlocks the European price source.

    Supplied by hand rather than looked up: no free service tested could map a broker
    ticker to an ISIN reliably, and a wrong ISIN would silently return **another
    company's** prices. A gap is recoverable; wrong data presented as right is not.
    """
    broker_symbol = payload.broker_symbol.strip().upper()
    isin = payload.isin.strip().upper()

    if not looks_like_isin(isin):
        raise HTTPException(
            status_code=422,
            detail="An ISIN is 12 characters: two letters, nine alphanumerics, one digit.",
        )

    instrument = db.execute(
        select(Instrument).where(Instrument.broker_symbol == broker_symbol)
    ).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"No known instrument for '{broker_symbol}'.")

    instrument.isin = isin
    # The ISIN opens a new source, so let the next refresh try it rather than waiting
    # for tomorrow's freshness window.
    instrument.prices_checked_at = None

    db.commit()
    db.refresh(instrument)
    return InstrumentOut.model_validate(instrument)
