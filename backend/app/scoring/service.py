"""Computing composite scores from cached fundamentals + price history.

Batch-first, same shape as `prices/history_service.py`: one query for every
relevant `Fundamental` row, one for every relevant `PriceBar` close, grouped in
memory, every instrument's pillars and composite computed with no further
queries. A score is a cheap derivation over already-cached data — computed
live on every request, never itself persisted (same posture as
`routers/portfolio.py::_resolve_current_price`), so there is nothing here to
go stale.

Missing data is dropped, never guessed, at two nested levels: a metric with
missing inputs is dropped and the rest of its pillar's metric weights
renormalize to still sum to 100%; a pillar with nothing scorable is itself
dropped and the composite's pillar weights renormalize the same way. This is
Decision 1.2's rule ("a pillar without data is dropped and the weights
renormalised") applied recursively. See DEVLOG "Decision 3r.1".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.corporate_actions.service import load_actions_by_instrument, price_factor_from, quantity_factor_from
from app.models import CorporateAction, Fundamental, Instrument, Lot, PriceBar, Transaction, TxType
from app.prices.fx_service import get_rate
from app.scoring import metrics
from app.scoring.config import PillarConfig, ScoringConfig
from app.scoring.metrics import AnnualValue, MetricResult
from app.symbols.mapping import ANALYSABLE_CATEGORIES

#: Dividend yield looks back this far from "now" for its trailing annualised
#: per-share figure — a moving window recomputed fresh on every request, same
#: as the rest of this module (never persisted, see module docstring).
DIVIDEND_LOOKBACK_DAYS = 365


@dataclass
class MetricScore:
    name: str
    weight: float
    score: float | None
    value: float | None
    dropped_reason: str | None


@dataclass
class PillarScore:
    name: str
    score: float | None
    #: This pillar's weight, renormalized against sibling pillars that also
    #: scored — the share of the composite it actually contributed. 0 when
    #: this pillar itself has no score.
    weight_used: float
    metrics: list[MetricScore] = field(default_factory=list)


@dataclass
class InstrumentScore:
    instrument_id: int
    composite: float | None
    pillars: list[PillarScore] = field(default_factory=list)
    #: Three fields for Discovery/Pépites screening filters — informational
    #: only, never fed back into `composite`. `debt_ratio` is read out of
    #: the Value pillar's own already-computed `debt_to_equity` metric
    #: (never recomputed); `market_cap` and `price_history_years` are new,
    #: unscored derivations over the same per-instrument data this
    #: function already loads. See DEVLOG "Decision 3u.72".
    market_cap: float | None = None
    debt_ratio: float | None = None
    price_history_years: float | None = None


def score_band(composite: float | None) -> str:
    """"high" | "mid" | "low" | "none" — same thresholds as the frontend's
    own `scoreBand` (`components/ScoreBadge.tsx`). Kept in sync deliberately
    rather than shared across the Python/TypeScript boundary; used wherever
    a composite score needs to be combined with another indicator into a
    single label (see `routers/portfolio.py::_position_signal`).
    """
    if composite is None:
        return "none"
    if composite >= 66:
        return "high"
    if composite >= 33:
        return "mid"
    return "low"


def _weighted_average(pairs: list[tuple[float, float]]) -> float | None:
    """`pairs` of (weight, score), already filtered to real scores. `None`
    when every weight is zero/negative (nothing survived to average)."""
    total_weight = sum(w for w, _ in pairs)
    if total_weight <= 0:
        return None
    return sum(w * s for w, s in pairs) / total_weight


def _shares_held_on(lots: list[Lot], day: date, actions: list[CorporateAction] | None = None) -> float:
    """Same replay rule as `prices/history_service.py::compute_value_history`'s
    per-day loop: a lot counts if it was opened on/before `day` and (if ever
    closed) closed strictly after `day`. `actions` restates each lot's real
    quantity on today's post-split basis — see
    `app/corporate_actions/service.py::quantity_factor_from`."""
    return sum(
        lot.quantity * quantity_factor_from(actions or [], lot.opened_at.date())
        for lot in lots
        if lot.opened_at is not None
        and lot.opened_at.date() <= day
        and (lot.closed_at is None or lot.closed_at.date() > day)
    )


def _annual_dividend_per_share(
    dividends: list[Transaction], lots: list[Lot], actions: list[CorporateAction] | None = None
) -> float | None:
    """Sum of `amount / shares_held_at_that_date` over the trailing-12mo
    dividend payments already confirmed to share the instrument's own trading
    currency with its price (no FX needed). `0.0` (not `None`) when the
    instrument was actually held (it has lot history) but simply paid no
    dividends — a real, known fact about a non-payer, not a data gap. `None`
    when there is no lot history at all (nothing to replay against, so no
    rate can be attributed even if dividends exist) or when every payment
    landed on a day this replay reconstructs as zero shares held — never
    guessed."""
    if not lots:
        return None
    if not dividends:
        return 0.0
    total = 0.0
    matched_any = False
    for tx in dividends:
        if tx.executed_at is None or tx.amount is None:
            continue
        shares = _shares_held_on(lots, tx.executed_at.date(), actions)
        if shares <= 0:
            continue
        total += tx.amount / shares
        matched_any = True
    return total if matched_any else None


def _load_lots(db: Session, instrument_ids: list[int]) -> dict[int, list[Lot]]:
    rows = db.execute(select(Lot).where(Lot.instrument_id.in_(instrument_ids))).scalars()
    result: dict[int, list[Lot]] = defaultdict(list)
    for lot in rows:
        result[lot.instrument_id].append(lot)
    return result


def _load_dividends(db: Session, instrument_ids: list[int], since: datetime) -> dict[int, list[Transaction]]:
    rows = db.execute(
        select(Transaction).where(
            Transaction.instrument_id.in_(instrument_ids),
            Transaction.type == TxType.DIVIDEND,
            Transaction.executed_at >= since,
        )
    ).scalars()
    result: dict[int, list[Transaction]] = defaultdict(list)
    for tx in rows:
        result[tx.instrument_id].append(tx)
    return result


def _call_metric(
    name: str,
    concepts: dict[str, list[AnnualValue]],
    price: float | None,
    price_currency: str,
    fx_rate: float | None,
    closes: list[float],
    annual_dividend_per_share: float | None,
    cfg,
) -> MetricResult:
    if name in ("pe_ratio", "pb_ratio", "fcf_yield") and price is None:
        return MetricResult(score=None, value=None, dropped_reason=metrics.DROP_MISSING_CONCEPT)

    if name == "pe_ratio":
        return metrics.pe_ratio(concepts, price, price_currency, fx_rate, cfg)
    if name == "pb_ratio":
        return metrics.pb_ratio(concepts, price, price_currency, fx_rate, cfg)
    if name == "fcf_yield":
        return metrics.fcf_yield(concepts, price, price_currency, fx_rate, cfg)
    if name == "debt_to_equity":
        return metrics.debt_to_equity(concepts, cfg)
    if name == "dividend_yield":
        return metrics.dividend_yield(annual_dividend_per_share, price, cfg)
    if name == "revenue_cagr":
        return metrics.revenue_cagr(concepts, cfg)
    if name == "net_income_cagr":
        return metrics.net_income_cagr(concepts, cfg)
    if name == "revenue_growth_consistency":
        return metrics.revenue_growth_consistency(concepts, cfg)
    if name == "roa_positive":
        return metrics.roa_positive(concepts)
    if name == "cfo_positive":
        return metrics.cfo_positive(concepts)
    if name == "accruals_quality":
        return metrics.accruals_quality(concepts)
    if name == "leverage_not_increasing":
        return metrics.leverage_not_increasing(concepts)
    if name == "no_significant_dilution":
        return metrics.no_significant_dilution(concepts)
    if name == "price_vs_sma200":
        return metrics.price_vs_sma200(closes, cfg)
    if name == "momentum_12_1":
        return metrics.momentum_12_1(closes, cfg)
    if name == "sma50_vs_sma200":
        return metrics.sma50_vs_sma200(closes, cfg)
    raise ValueError(f"unknown metric: {name!r} — not implemented in scoring/metrics.py")


def _compute_pillar(
    name: str,
    pillar_cfg: PillarConfig,
    concepts: dict[str, list[AnnualValue]],
    price: float | None,
    price_currency: str,
    fx_rate: float | None,
    closes: list[float],
    annual_dividend_per_share: float | None,
) -> PillarScore:
    metric_scores = []
    for metric_name, metric_cfg in pillar_cfg.metrics.items():
        result = _call_metric(
            metric_name, concepts, price, price_currency, fx_rate, closes, annual_dividend_per_share, metric_cfg
        )
        metric_scores.append(
            MetricScore(
                name=metric_name,
                weight=metric_cfg.weight,
                score=result.score,
                value=result.value,
                dropped_reason=result.dropped_reason,
            )
        )
    scored = [(m.weight, m.score) for m in metric_scores if m.score is not None]
    return PillarScore(name=name, score=_weighted_average(scored), weight_used=0.0, metrics=metric_scores)


def _finalise_composite(pillars: list[PillarScore], pillar_configs: dict[str, PillarConfig]) -> float | None:
    scored = [(pillar_configs[p.name].weight, p.score) for p in pillars if p.score is not None]
    total_weight = sum(w for w, _ in scored)
    for pillar in pillars:
        if pillar.score is not None and total_weight > 0:
            pillar.weight_used = round(pillar_configs[pillar.name].weight / total_weight * 100, 2)
    return _weighted_average(scored)


def _metric_value(pillars: list[PillarScore], pillar_name: str, metric_name: str) -> float | None:
    """The raw (unscored) `.value` of one already-computed metric, e.g. the
    Value pillar's `debt_to_equity` ratio — never recomputed, and `None`
    when the pillar/metric isn't configured or was dropped for missing
    data, same as everywhere else in this app."""
    pillar = next((p for p in pillars if p.name == pillar_name), None)
    if pillar is None:
        return None
    metric = next((m for m in pillar.metrics if m.name == metric_name), None)
    return metric.value if metric else None


def _representative_currency(concepts: dict[str, list[AnnualValue]]) -> str | None:
    """One filing's figures all share one reporting currency in practice (it
    is one 10-K/20-F). Any concept's latest value is representative."""
    for series in concepts.values():
        if series:
            return series[-1].currency
    return None


def _load_fundamentals(db: Session, instrument_ids: list[int]) -> dict[int, dict[str, list[AnnualValue]]]:
    rows = db.execute(
        select(Fundamental)
        .where(Fundamental.instrument_id.in_(instrument_ids))
        .order_by(Fundamental.instrument_id, Fundamental.concept, Fundamental.fiscal_year)
    ).scalars()
    result: dict[int, dict[str, list[AnnualValue]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        result[row.instrument_id][row.concept].append(
            AnnualValue(fiscal_year=row.fiscal_year, value=row.value, currency=row.currency)
        )
    return result


def _load_closes(
    db: Session, instrument_ids: list[int], actions_by_instrument: dict[int, list[CorporateAction]] | None = None
) -> dict[int, list[float]]:
    """Split-adjusted closes, oldest first — every technical metric downstream
    (SMA/momentum ratios) reads consecutive values from this list, so an
    unadjusted split would show up as an impossible one-bar jump. See
    `app/corporate_actions/service.py::price_factor_from`."""
    actions_by_instrument = actions_by_instrument or {}
    rows = db.execute(
        select(PriceBar.instrument_id, PriceBar.bar_date, PriceBar.close)
        .where(PriceBar.instrument_id.in_(instrument_ids), PriceBar.close.is_not(None))
        .order_by(PriceBar.instrument_id, PriceBar.bar_date)
    )
    result: dict[int, list[float]] = defaultdict(list)
    for instrument_id, bar_date, close in rows:
        factor = price_factor_from(actions_by_instrument.get(instrument_id, []), bar_date)
        result[instrument_id].append(close * factor)
    return result


def compute_scores(db: Session, instruments: list[Instrument], config: ScoringConfig) -> list[InstrumentScore]:
    """One score per instrument in `ANALYSABLE_CATEGORIES` (STOCK, ETF) —
    CFDs are excluded entirely, same exclusion `history_service.py` and
    `_resolve_current_price` already apply (a contract count has no
    fundamentals and no meaningful long-term trend the way a share does).
    """
    scorable = [i for i in instruments if i.category in ANALYSABLE_CATEGORIES]
    if not scorable:
        return []

    ids = [i.id for i in scorable]
    concepts_by_instrument = _load_fundamentals(db, ids)
    actions_by_instrument = load_actions_by_instrument(db, ids)
    closes_by_instrument = _load_closes(db, ids, actions_by_instrument)

    # Dividend yield is scoped to individual stocks, not ETFs: whether a fund
    # distributes or accumulates internally is a structural design choice of
    # the fund, not a valuation signal the way a company's shareholder yield
    # is — scoring an accumulating ETF's real 0% payout as "bad value" would
    # misread that choice as cheapness. Restricting the query itself (not
    # just the metric call below) avoids querying lots/dividends for
    # instruments that will never use them.
    stock_ids = [i.id for i in scorable if i.category == "STOCK"]
    lots_by_instrument = _load_lots(db, stock_ids)
    # `Transaction.executed_at` is stored naive (parsed straight from the
    # broker export, see `ingest/xtb_import.py::parse_datetime`) — strip
    # tzinfo so this compares correctly, same convention that column already
    # follows everywhere else.
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=DIVIDEND_LOOKBACK_DAYS)
    dividends_by_instrument = _load_dividends(db, stock_ids, since)

    results = []
    for instrument in scorable:
        concepts = concepts_by_instrument.get(instrument.id, {})
        closes = closes_by_instrument.get(instrument.id, [])
        price = closes[-1] if closes else None
        price_currency = instrument.currency or ""

        fundamentals_currency = _representative_currency(concepts)
        fx_rate = None
        if fundamentals_currency and price_currency:
            fx_rate = get_rate(db, price_currency, fundamentals_currency)

        annual_dividend_per_share = (
            _annual_dividend_per_share(
                dividends_by_instrument.get(instrument.id, []),
                lots_by_instrument.get(instrument.id, []),
                actions_by_instrument.get(instrument.id, []),
            )
            if instrument.category == "STOCK"
            else None
        )

        pillars = [
            _compute_pillar(
                name, pillar_cfg, concepts, price, price_currency, fx_rate, closes, annual_dividend_per_share
            )
            for name, pillar_cfg in config.pillars.items()
        ]
        composite = _finalise_composite(pillars, config.pillars)
        results.append(
            InstrumentScore(
                instrument_id=instrument.id,
                composite=composite,
                pillars=pillars,
                market_cap=metrics.market_cap(concepts, price, price_currency, fx_rate),
                debt_ratio=_metric_value(pillars, "value", "debt_to_equity"),
                price_history_years=round(len(closes) / 252, 1) if closes else None,
            )
        )

    return results
