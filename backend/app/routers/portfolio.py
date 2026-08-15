"""Portfolio endpoints: read, manual entry, mapping correction."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.corporate_actions.service import list_incomplete_instrument_ids, list_outstanding_candidates
from app.db import get_db
from app.ingest.service import get_or_create_instrument
from app.messages import Message, PerformanceNote, ValuationNote
from app.models import (
    AllocationTarget,
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
    PriceBar,
    Source,
    SymbolOverride,
    Transaction,
    TxType,
    WatchlistItem,
)
from app.prices.fx_service import get_rate as get_fx_rate
from app.prices.history_service import compute_value_history
from app.prices.provider_usage import record_usage
from app.prices.quote_service import fetch_live_quotes, get_quote_progress
from app.providers.base import InstrumentRef, ProviderError
from app.providers.fmp import FmpProvider
from app.providers.frankfurt import looks_like_isin
from app.providers.registry import get_provider_chain
from app.providers.wikidata import resolve_sector as resolve_wikidata_sector
from app.schemas import (
    AccountTotals,
    AllocationRowOut,
    AllocationTargetIn,
    AttentionItemOut,
    BackfillIsinsOut,
    BreakdownItem,
    DataHealthCorporateActionsOut,
    DataHealthOut,
    DataHealthRowOut,
    DataHealthSummaryOut,
    DataHealthValuationOut,
    EnrichSectorsOut,
    IsinIn,
    InstrumentOut,
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
    PortfolioTotals,
    PositionOut,
    PositionSignalOut,
    QuoteStatusOut,
    SymbolOverrideIn,
    SymbolSearchResult,
    ValueHistoryOut,
    ValueHistoryPointOut,
)
from app.scoring.config import get_scoring_config
from app.scoring.service import compute_scores, score_band
from app.symbols.duplicates import backfill_isins

#: One position's up-to-date value, P&L, P&L%, price (instrument currency) and
#: price_source ('live' | 'cached' | 'broker').
PositionFigures = tuple[float | None, float | None, float | None, float | None, str]

#: Dimensions the breakdown endpoint can group by, and the Instrument attribute each
#: reads. category/currency/country are populated by the XTB import; sector needs
#: POST /enrich-sectors to have been run first (FMP for US holdings, Wikidata for
#: most others — see `enrich_sectors`) — an instrument with no sector yet groups
#: under "UNKNOWN", same as any other gap (always true for ETFs and CFDs, which
#: have no single sector by nature).
BREAKDOWN_DIMENSIONS = {"category", "currency", "country", "sector"}

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

#: An instrument checked within this many days counts as "fresh" rather than "stale".
#: Wider than one day because weekends and holidays mean "checked two days ago" is
#: still the most current data available, not a sign anything is wrong.
FRESH_WINDOW_DAYS = 4

#: How old a broker-*declared* (non-market) valuation can be before it counts as
#: stale, keyed by `Instrument.not_priceable_reason`. Mintos statements arrive
#: quarterly (live "Investments" exports in between, whenever the user pulls
#: one); Amundi ESR relies on an annual PDF plus occasional live Synthese
#: snapshots. Each window is wider than the nominal cadence so a statement
#: that simply hasn't been re-imported yet by a few days isn't flagged. See
#: DEVLOG "Decision 3u.50".
DECLARED_VALUE_FRESHNESS_DAYS = {
    "p2p_aggregate": 100,
    "employee_savings_fund": 400,
}

#: Human-readable source name for `ValuationNote` params, keyed the same way.
DECLARED_VALUE_PROVIDER_NAME = {
    "p2p_aggregate": "Mintos",
    "employee_savings_fund": "Amundi ESR",
}


def _declared_valuation_note(
    instrument: Instrument, value_as_of: date | None
) -> tuple[str | None, dict | None]:
    """('fresh' | 'stale', a `ValuationNote` dict) for a position whose value
    comes from a periodically-declared broker statement rather than a live
    market quote — Mintos Core P2P, Amundi ESR. `(None, None)` for anything
    else: an ordinary priced position, or a not-priceable instrument with no
    declared-value date of its own (a CFD, a corporate-action residual) —
    those are untouched by this decision and keep their existing
    'not_priceable' treatment. See DEVLOG "Decision 3u.50".
    """
    reason = instrument.not_priceable_reason
    if value_as_of is None or reason not in DECLARED_VALUE_FRESHNESS_DAYS:
        return None, None
    age_days = (datetime.now(UTC).date() - value_as_of).days
    provider = DECLARED_VALUE_PROVIDER_NAME[reason]
    params = {"provider": provider, "date": value_as_of.isoformat()}
    if age_days <= DECLARED_VALUE_FRESHNESS_DAYS[reason]:
        return "fresh", Message(ValuationNote.DECLARED_FRESH, params).as_dict()
    return "stale", Message(ValuationNote.DECLARED_STALE, params).as_dict()


def _price_status(instrument: Instrument) -> str:
    """One of 'fresh' | 'stale' | 'error' | 'not_priceable' | 'unmapped'.

    Drives the status badge in the positions table. Computed from fields already
    written by the import and refresh pipelines — nothing new to maintain.
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


def _resolve_current_price(
    db: Session, instrument: Instrument, live_quotes: dict[int, tuple[float, str]]
) -> tuple[float | None, str | None]:
    """Best available price for one instrument, in its own currency.

    ``None`` for CFDs (quantity is a contract count, not a share count — no price
    makes sense) and anything not yet priceable. Otherwise, in order: a quote
    from *this* round's ``live_quotes`` if it just fetched one; else the
    persisted last live quote from an earlier refresh (`LastQuote`) if it is
    at least as recent as the cached daily close; else the daily close;
    else ``None`` (nothing to work with yet).
    """
    if instrument.not_priceable_reason or instrument.category == "CFD":
        return None, None

    live = live_quotes.get(instrument.id)
    if live is not None:
        return live[0], "live"

    latest_bar = db.execute(
        select(PriceBar)
        .where(PriceBar.instrument_id == instrument.id)
        .order_by(PriceBar.bar_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    # A live quote from an *earlier* refresh, still on hand because it is
    # persisted (DEVLOG "Decision 3o.1") — used only while it is not older
    # than whatever daily close is cached, so a fresher overnight bar always
    # wins over a stale intraday snapshot from before it existed.
    saved_quote = db.get(LastQuote, instrument.id)
    if saved_quote is not None and (
        latest_bar is None or saved_quote.fetched_at >= latest_bar.fetched_at
    ):
        return saved_quote.price, "live"

    if latest_bar is not None and latest_bar.close is not None:
        return latest_bar.close, "cached"
    return None, None


def _current_position_figures(
    db: Session,
    position: Position,
    base_currency: str,
    live_quotes: dict[int, tuple[float, str]],
) -> PositionFigures:
    """One position's up-to-date value/P&L/P&L%/price, replacing the old
    permanently-frozen "broker-reported totals" design (DEVLOG "Bug 2.1" /
    "Decision 2f.3"). ``price_source='broker'`` is not a failure — it is what
    CFDs always get (no live equivalent exists for a contract count) and what
    anything else falls back to when a priceable, FX-converted figure is not
    available yet (never refreshed, no FX rate cached today).
    """
    instrument = position.instrument

    # A P2P aggregate (e.g. Mintos Core) has a real, broker-declared value
    # but deliberately no *quantity-derived* cost basis: the user explicitly
    # rejected both "PRU = last declared value" (implies a real cost that
    # isn't known) and "PRU = cumulative reinvestment total" (double-counts
    # auto-invest churn) — see DEVLOG "Decision 3u.39". `avg_price` on this
    # Position stays an unused placeholder, never a basis for a gain/loss
    # figure computed *here*. `broker_net_pl`/`broker_net_pl_pct`, however,
    # may carry a real, separately-computed figure — real cumulative
    # interest/bonus income minus fees/tax, from
    # `app/ingest/service.py::import_mintos_transactions_file` — which is
    # passed through as-is rather than re-derived from `avg_price`/quantity
    # (DEVLOG "Decision 3u.47"). Checked ahead of the normal price-
    # resolution path since this category is also always `not_priceable`.
    if instrument.category == "P2P":
        value = position.broker_market_value
        pl = position.broker_net_pl
        pl_pct = position.broker_net_pl_pct
        return (
            round(value, 2) if value is not None else None,
            round(pl, 2) if pl is not None else None,
            round(pl_pct, 2) if pl_pct is not None else None,
            None,
            "broker",
        )

    price, source = _resolve_current_price(db, instrument, live_quotes)

    if price is not None:
        fx_rate = get_fx_rate(db, instrument.currency, base_currency)
        if fx_rate is not None:
            value = position.quantity * price * fx_rate
            # Cost basis, in preference order:
            #  1. broker_purchase_value — an explicit figure from the broker, when
            #     the export provides one. It used the FX rate at the time of
            #     purchase, which this app has no record of, so trust it outright.
            #  2. market_value − net_pl — the XTB export in practice never
            #     populates broker_purchase_value, but always gives both of these
            #     (already in account/base currency, no conversion needed), and
            #     algebraically they define the same thing.
            #  3. avg_price × quantity, FX-converted at today's rate — the only
            #     option for a manually entered position, which has neither of
            #     the above; an approximation, but the best available.
            invested = position.broker_purchase_value
            if invested is None and position.broker_market_value is not None and position.broker_net_pl is not None:
                invested = position.broker_market_value - position.broker_net_pl
            if invested is None and position.source == Source.MANUAL:
                invested = position.avg_price * position.quantity * fx_rate
            if invested is not None:
                pl = value - invested
                pl_pct = (pl / invested * 100) if invested else None
                return (
                    round(value, 2),
                    round(pl, 2),
                    round(pl_pct, 2) if pl_pct is not None else None,
                    round(price, 4),
                    source,
                )

    # A known value with no known P&L (e.g. an Amundi Synthese-imported fund
    # — DEVLOG "Decision 3u.44" — that export carries no gain/loss column,
    # unlike the annual PDF) must still surface its value: requiring both
    # together here was the same "value is None or pl is None" conflation
    # already fixed once for the P2P branch above (Decision 3u.42), just in
    # this generic fallback instead. `pl`/`pl_pct` are simply left `None`
    # when unknown rather than withholding `value` too.
    if position.broker_market_value is not None:
        pl = position.broker_net_pl
        pl_pct = position.broker_net_pl_pct
        return (
            round(position.broker_market_value, 2),
            round(pl, 2) if pl is not None else None,
            round(pl_pct, 2) if pl_pct is not None else None,
            position.market_price,
            "broker",
        )
    return None, None, None, None, "broker"


def _compute_figures(
    db: Session,
    positions: list[Position],
    base_currency: str,
    live_quotes: dict[int, tuple[float, str]],
) -> dict[int, PositionFigures]:
    """One `_current_position_figures` result per position, keyed by position id.

    Computed once per request and shared by totals, per-account totals, the
    positions list and the breakdown chart, instead of re-resolving the same
    price and FX rate once per consumer.
    """
    return {p.id: _current_position_figures(db, p, base_currency, live_quotes) for p in positions}


def _aggregate(
    positions: list[Position], figures: dict[int, PositionFigures]
) -> tuple[float, float | None, int, int]:
    """Sum current market value and P&L. Returns (value, P&L, counted, excluded).

    A position without a computable current *value* is **excluded** from the
    total rather than counted as zero: a wrong total that looks correct is
    worse than one that is explicitly partial. A position with a known value
    but no P&L (a P2P aggregate like Mintos Core, or an Amundi fund imported
    from the Synthese live snapshot rather than the annual PDF — see
    `_current_position_figures`'s deliberate `pl=None`, DEVLOG "Decision
    3u.39"/"3u.44") still counts toward `market_value`; only its (unknown,
    never fabricated) contribution to `unrealized` is left out.

    The returned P&L is `None`, not `0.0`, whenever *no* counted position
    contributed a known figure — real bug found live 2026-09-08: an account
    where every position's P&L is unknown (Mintos, or Amundi funds now
    updated only from the Synthese export) summed to a literal `0.0`,
    displayed as a confident "0.00 / 0.00%" that read as "no gain, no
    loss" when the honest answer is "unknown," the exact fabrication this
    project has consistently avoided elsewhere. A *mixed* group (at least
    one position with a known P&L, e.g. the global portfolio total, which
    always includes ordinary priced holdings alongside these) still sums
    only the known contributions — the same partial-information posture
    `excluded_positions` already signals for value.
    """
    market_value = 0.0
    unrealized = 0.0
    counted = 0
    excluded = 0
    any_known_pl = False

    for position in positions:
        value, pl, *_ = figures[position.id]
        if value is None:
            excluded += 1
            continue
        market_value += value
        if pl is not None:
            unrealized += pl
            any_known_pl = True
        counted += 1

    return market_value, (unrealized if any_known_pl else None), counted, excluded


def _compute_totals(
    positions: list[Position], base_currency: str, figures: dict[int, PositionFigures]
) -> PortfolioTotals:
    market_value, unrealized, counted, excluded = _aggregate(positions, figures)

    if counted == 0:
        return PortfolioTotals(
            base_currency=base_currency,
            positions_count=len(positions),
            has_incomplete_data=bool(positions),
            excluded_positions=excluded,
        )

    invested = market_value - unrealized if unrealized is not None else None

    return PortfolioTotals(
        base_currency=base_currency,
        positions_count=len(positions),
        market_value=round(market_value, 2),
        invested_value=round(invested, 2) if invested is not None else None,
        unrealized_pl=round(unrealized, 2) if unrealized is not None else None,
        unrealized_pl_pct=round(unrealized / invested * 100, 2) if unrealized is not None and invested else None,
        has_incomplete_data=excluded > 0,
        excluded_positions=excluded,
    )


def _compute_account_totals(
    positions: list[Position], figures: dict[int, PositionFigures]
) -> list[AccountTotals]:
    """Break totals down per account: one XTB export only covers a single account."""
    by_account: dict[str, list[Position]] = defaultdict(list)
    for position in positions:
        by_account[position.account or "—"].append(position)

    results: list[AccountTotals] = []
    for account, account_positions in sorted(by_account.items()):
        market_value, unrealized, counted, _ = _aggregate(account_positions, figures)
        invested = market_value - unrealized if unrealized is not None else None
        # An account can mix a real per-fund gain (Decision 3u.48) with a
        # cruder account-level approximation (Decision 3u.47) for a
        # different fund with no per-fund history to anchor to. The
        # approximation's caveat — the one that can make the *whole
        # account's* total read as overstated — always wins this pick
        # when both are present, rather than an arbitrary "whichever
        # position happens to be first".
        notes = [p.performance_note for p in account_positions if p.performance_note]
        note = next(
            (n for n in notes if n.get("code") == PerformanceNote.AMUNDI_APPROXIMATE_GAIN),
            notes[0] if notes else None,
        )

        # Independent from `performance_note` above: an account can have a
        # known value with no computable P&L at all (Mintos, until an
        # interest-income import has run for it — the account-level
        # "By account" table would otherwise show bare "—" cells with no
        # explanation of what kind of figure `market_value` even is, a real
        # gap a user flagged live 2026-09-08). A stale valuation always
        # wins this pick over a fresh one, mirroring the priority given to
        # the more consequential caveat above. See DEVLOG "Decision 3u.50".
        valuation_notes = [
            found
            for p in account_positions
            if (found := _declared_valuation_note(p.instrument, p.value_as_of)[1]) is not None
        ]
        valuation_note = next(
            (n for n in valuation_notes if n.get("code") == ValuationNote.DECLARED_STALE),
            valuation_notes[0] if valuation_notes else None,
        )

        results.append(
            AccountTotals(
                account=account,
                positions_count=len(account_positions),
                market_value=round(market_value, 2) if counted else None,
                invested_value=round(invested, 2) if counted and invested is not None else None,
                unrealized_pl=round(unrealized, 2) if counted and unrealized is not None else None,
                unrealized_pl_pct=round(unrealized / invested * 100, 2)
                if counted and unrealized is not None and invested
                else None,
                performance_note=note,
                valuation_note=MessageOut(**valuation_note) if valuation_note else None,
            )
        )

    return results


def _unresolved_instruments(db: Session) -> list[Instrument]:
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


def _build_portfolio_out(
    db: Session, positions: list[Position], live_quotes: dict[int, tuple[float, str]]
) -> PortfolioOut:
    """Shared by the cache-only ``GET`` and the budgeted ``POST /refresh-live``:
    same computation, the only difference is whether `live_quotes` has anything
    in it. Everything downstream (totals, per-account, per-position, weight%)
    picks the fresher price automatically.
    """
    base_currency = get_settings().base_currency
    figures = _compute_figures(db, positions, base_currency, live_quotes)
    totals = _compute_totals(positions, base_currency, figures)
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
        freshness, note = _declared_valuation_note(p.instrument, p.value_as_of)
        position_out.valuation_note = MessageOut(**note) if note else None
        if freshness == "stale":
            any_stale_declared_valuation = True
        positions_out.append(position_out)
    totals.has_stale_declared_valuations = any_stale_declared_valuation

    unresolved = _unresolved_instruments(db)
    last_batch = db.execute(
        select(ImportBatch).order_by(ImportBatch.imported_at.desc()).limit(1)
    ).scalar_one_or_none()
    metadata = db.execute(select(AppMetadata)).scalar_one_or_none()

    return PortfolioOut(
        totals=totals,
        accounts=_compute_account_totals(positions, figures),
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
    for CFDs and anything not yet priced) — see `_current_position_figures` and
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

    positions, figures, total_value = _positions_figures_and_total(db)
    if not total_value:
        return []

    buckets = _weight_buckets(positions, figures, by)
    items = [
        BreakdownItem(label=label, value=round(value, 2), weight_percent=round(value / total_value * 100, 2))
        for label, value in buckets.items()
    ]
    items.sort(key=lambda item: item.value, reverse=True)
    return items


def _positions_figures_and_total(db: Session) -> tuple[list[Position], dict[int, PositionFigures], float]:
    """Held positions, their computed figures, and the portfolio total —
    the shared basis for `/breakdown`, `/allocation`, and the personal-
    policy gap comparison, so each doesn't re-derive it independently."""
    positions = list(db.execute(select(Position).options(joinedload(Position.instrument))).scalars())
    base_currency = get_settings().base_currency
    figures = _compute_figures(db, positions, base_currency, live_quotes={})
    totals = _compute_totals(positions, base_currency, figures)
    return positions, figures, totals.market_value or 0.0


def _weight_buckets(
    positions: list[Position], figures: dict[int, PositionFigures], attribute: str
) -> dict[str, float]:
    """Market value grouped by one plain `Instrument` attribute's value
    (category/currency/country/sector). A position with no known value is
    excluded, same rule the portfolio totals already apply."""
    buckets: dict[str, float] = defaultdict(float)
    for p in positions:
        value, *_ = figures[p.id]
        if value is None:
            continue
        label = getattr(p.instrument, attribute, None) or "UNKNOWN"
        buckets[label] += value
    return dict(buckets)


def _current_allocation_values(db: Session) -> tuple[dict[str, float], float]:
    """Current market value per category, and the portfolio total — same
    computation `get_breakdown` already does, reused here for the target
    comparison rather than re-derived."""
    positions, figures, total_value = _positions_figures_and_total(db)
    return _weight_buckets(positions, figures, "category"), total_value


def _allocation_row(
    category: str, current_value: float, total_value: float, target: AllocationTarget | None
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

    if current_pct < target.min_pct:
        state = "under"
        gap_pct = round(target.min_pct - current_pct, 2)
        # Deliberately not solving for the new (larger) total after adding
        # this amount — a one-sentence, honestly-labeled approximation
        # (this category alone reaching min_pct of the CURRENT total) beats
        # a "more exact" number that reads as more precise than it is.
        amount_to_reach_min = round(max(0.0, target.min_pct / 100 * total_value - current_value), 2)
    elif current_pct > target.max_pct:
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


@router.get("/allocation", response_model=list[AllocationRowOut])
def get_allocation(db: Session = Depends(get_db)) -> list[AllocationRowOut]:
    """Current allocation by asset class vs. a user-configured target range,
    if any. Descriptive only — never a suggestion to buy or sell a specific
    security, just the gap against a range the user themselves set. See
    DEVLOG "Decision 3u.15".
    """
    buckets, total_value = _current_allocation_values(db)

    targets = {t.category: t for t in db.execute(select(AllocationTarget)).scalars()}

    # Union of categories actually held and categories with a configured
    # target: a target for a category currently held at 0% must still
    # appear — that's the most informative row ("you want 10% bonds, you
    # hold 0%"), not one to silently drop because no position exists. Note
    # this means a *configured* target still shows even with an entirely
    # empty portfolio (total_value == 0) — `_allocation_row` treats that as
    # current_pct=0, not a crash, unlike `get_breakdown`'s early return
    # (which is fine there: it has no analogous "show it anyway" case).
    categories = set(buckets) | set(targets)

    rows = [
        _allocation_row(category, buckets.get(category, 0.0), total_value, targets.get(category))
        for category in categories
    ]
    rows.sort(key=lambda r: r.current_value, reverse=True)
    return rows


@router.put("/allocation/{category}", response_model=AllocationRowOut)
def set_allocation_target(
    category: str, payload: AllocationTargetIn, db: Session = Depends(get_db)
) -> AllocationRowOut:
    """Set (or replace) the target range for one asset class."""
    category = category.strip().upper()

    target = db.execute(
        select(AllocationTarget).where(AllocationTarget.category == category)
    ).scalar_one_or_none()
    if target is None:
        target = AllocationTarget(category=category, min_pct=payload.min_pct, max_pct=payload.max_pct)
        db.add(target)
    else:
        target.min_pct = payload.min_pct
        target.max_pct = payload.max_pct
    db.commit()

    buckets, total_value = _current_allocation_values(db)
    return _allocation_row(category, buckets.get(category, 0.0), total_value, target)


@router.delete("/allocation/{category}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_allocation_target(category: str, db: Session = Depends(get_db)) -> Response:
    """Remove a configured target — the category reverts to "no_target" (or
    disappears from `GET /allocation` entirely if also currently unheld)."""
    db.execute(delete(AllocationTarget).where(AllocationTarget.category == category.strip().upper()))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#: Every `PersonalPolicyLimit.dimension` except "line"/"declared_valuation"
#: names a plain `Instrument` column to group
#: weight by — same shape `_weight_buckets`/`/breakdown` already use.
_POLICY_LIMIT_ATTRIBUTE = {"sector": "sector", "country": "country", "currency": "currency", "category": "category"}


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


def _limit_state(pct: float, min_pct: float | None, max_pct: float | None) -> tuple[str, float]:
    """('under'|'over'|'within', distance to the nearest breached bound)."""
    if min_pct is not None and pct < min_pct:
        return "under", round(min_pct - pct, 2)
    if max_pct is not None and pct > max_pct:
        return "over", round(pct - max_pct, 2)
    return "within", 0.0


@router.get("/policy/gaps", response_model=list[PersonalPolicyGapOut])
def get_personal_policy_gaps(db: Session = Depends(get_db)) -> list[PersonalPolicyGapOut]:
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

    positions, figures, total_value = _positions_figures_and_total(db)
    if not total_value:
        return []

    configured_dimensions = {limit.dimension for limit in limits}
    buckets_by_dimension = {
        dimension: _weight_buckets(positions, figures, attribute)
        for dimension, attribute in _POLICY_LIMIT_ATTRIBUTE.items()
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
                state, gap_pct = _limit_state(pct, limit.min_pct, limit.max_pct)
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

        state, gap_pct = _limit_state(pct, limit.min_pct, limit.max_pct)
        if state != "within":
            gaps.append(
                PersonalPolicyGapOut(
                    limit_id=limit.id, dimension=limit.dimension, target=limit.target,
                    current_pct=pct, min_pct=limit.min_pct, max_pct=limit.max_pct,
                    state=state, gap_pct=gap_pct,
                )
            )

    return gaps


@router.get("/attention", response_model=list[AttentionItemOut])
def get_attention(db: Session = Depends(get_db)) -> list[AttentionItemOut]:
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

    unresolved_count = len(_unresolved_instruments(db))
    if unresolved_count:
        items.append(
            AttentionItemOut(severity="missing", kind="unresolved_instruments", count=unresolved_count)
        )

    buckets, total_value = _current_allocation_values(db)
    if total_value:
        targets = {t.category: t for t in db.execute(select(AllocationTarget)).scalars()}
        for category, target in targets.items():
            row = _allocation_row(category, buckets.get(category, 0.0), total_value, target)
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
        freshness, _note = _declared_valuation_note(instrument, position.value_as_of)
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
    unresolved_ids = {i.id for i in _unresolved_instruments(db)}

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
    return DataHealthOut(summary=summary, rows=rows)


@router.get("/onboarding", response_model=OnboardingStatusOut)
def get_onboarding_status(db: Session = Depends(get_db)) -> OnboardingStatusOut:
    """Whether each first-run step has been done at least once — a plain
    existence check against tables the app already maintains, no new
    tracking. Backs the dismissible "getting started" checklist on the
    Portfolio page. See DEVLOG "Decision 3u.26"."""
    imported = db.execute(select(ImportBatch.id).limit(1)).first() is not None
    metadata = db.execute(select(AppMetadata)).scalar_one_or_none()
    fundamentals_fetched = db.execute(select(Fundamental.id).limit(1)).first() is not None
    allocation_target_set = db.execute(select(AllocationTarget.id).limit(1)).first() is not None
    watchlist_started = db.execute(select(WatchlistItem.id).limit(1)).first() is not None

    return OnboardingStatusOut(
        imported=imported,
        prices_refreshed=metadata is not None and metadata.last_price_refresh_time is not None,
        unresolved_resolved=len(_unresolved_instruments(db)) == 0,
        fundamentals_fetched=fundamentals_fetched,
        allocation_target_set=allocation_target_set,
        watchlist_started=watchlist_started,
    )


def _position_signal(band: str, allocation_state: str) -> str:
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


@router.get("/position-signals", response_model=list[PositionSignalOut])
def get_position_signals(db: Session = Depends(get_db)) -> list[PositionSignalOut]:
    """One signal per held instrument, derived from its own composite score
    and its asset class's allocation gap — see `_position_signal` for the
    exact rule. Descriptive by construction: it never names a trade, only
    labels a combination of indicators the app already shows separately.
    """
    positions = list(
        db.execute(select(Position).options(joinedload(Position.instrument))).scalars()
    )
    instruments = {p.instrument.id: p.instrument for p in positions}.values()

    config = get_scoring_config()
    scores = {s.instrument_id: s for s in compute_scores(db, list(instruments), config)}

    buckets, total_value = _current_allocation_values(db)
    targets = {t.category: t for t in db.execute(select(AllocationTarget)).scalars()}
    categories = set(buckets) | set(targets)
    allocation_by_category = {
        category: _allocation_row(category, buckets.get(category, 0.0), total_value, targets.get(category))
        for category in categories
    }

    signals = []
    for instrument in instruments:
        category = instrument.category or "UNKNOWN"
        allocation_row = allocation_by_category.get(category)
        allocation_state = allocation_row.state if allocation_row else "no_target"
        gap_pct = allocation_row.gap_pct if allocation_row else 0.0
        score_result = scores.get(instrument.id)
        composite = score_result.composite if score_result else None
        band = score_band(composite)

        signals.append(
            PositionSignalOut(
                instrument_id=instrument.id,
                signal=_position_signal(band, allocation_state),
                composite_score=composite,
                score_band=band,
                category=instrument.category,
                allocation_state=allocation_state,
                gap_pct=gap_pct,
            )
        )
    return signals


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
    result = compute_value_history(db, settings.base_currency, date.today())
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
