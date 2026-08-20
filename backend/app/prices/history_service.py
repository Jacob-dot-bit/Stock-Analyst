"""Reconstructing real historical portfolio value from the ``Lot`` ledger.

Deliberately not a backtest of today's holdings: it replays actual buys and
sells over time, because that is what makes an eventual benchmark comparison
meaningful — a reshuffled "today's basket, rewound" wouldn't reflect real
timing decisions. See DEVLOG "Decision 3b.1".

Batch-first by design: one query for every lot ever held, one query for every
cached daily close in range, one FX-range fetch per distinct currency — never
one query per day. The per-day loop itself is pure in-memory arithmetic.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.corporate_actions.service import load_actions_by_instrument, price_factor_from, quantity_factor_from
from app.models import Instrument, Lot, MappingStatus, PriceBar
from app.prices.fx_service import get_rate_range
from app.prices.service import INITIAL_HISTORY_DAYS


@dataclass
class ValueHistoryPoint:
    day: date
    #: Total market value that day, or ``None`` if nothing held that day could
    #: be priced at all (never a guessed/zero value when data is simply missing).
    value: float | None
    #: Cost basis of whatever was held that day (sum of quantity × open_price,
    #: FX-converted) — the historical analogue of `PortfolioTotals.invested_value`.
    invested: float | None
    #: "If the same cash had bought the benchmark instead, on the same days" —
    #: see `_precompute_shadow_quantities`. ``None`` when no benchmark is
    #: configured, or when it could not be priced that day.
    benchmark: float | None = None


@dataclass
class ValueHistoryResult:
    points: list[ValueHistoryPoint]
    start_date: date | None
    #: True when the real earliest lot predates the price-history depth
    #: (`INITIAL_HISTORY_DAYS`) and the range had to be cut short — an honest
    #: caption instead of a silently truncated chart.
    capped_by_history: bool
    benchmark_available: bool = False


def get_or_create_benchmark_instrument(db: Session) -> Instrument | None:
    """The reference instrument the chart compares against — not a held
    position, so it never appears in `Position`/`Lot` on its own initiative.
    Built directly from config rather than resolved via `symbols.mapping`:
    this is not an import, there is no broker row to resolve from, both
    symbols come straight from settings. See DEVLOG "Decision 3e.1" for the
    live verification that led to the default (an S&P 500 ETF, not a raw
    index ticker — it needs to flow through the same provider machinery as
    any other holding, with no new resolution code).
    """
    settings = get_settings()
    if not settings.benchmark_enabled:
        return None

    instrument = db.execute(
        select(Instrument).where(Instrument.broker_symbol == settings.benchmark_broker_symbol)
    ).scalar_one_or_none()
    if instrument is not None:
        return instrument

    instrument = Instrument(
        broker_symbol=settings.benchmark_broker_symbol,
        provider_symbol=settings.benchmark_provider_symbol,
        mapping_status=MappingStatus.MANUAL,
        name=settings.benchmark_name,
        category="ETF",
    )
    db.add(instrument)
    db.flush()
    return instrument


def compute_value_history(db: Session, base_currency: str, today: date) -> ValueHistoryResult:
    lots = list(db.execute(select(Lot).options(joinedload(Lot.instrument))).scalars())

    # Same exclusion as the live "current value" path (`_resolve_current_price`
    # in routers/portfolio.py): a CFD's quantity is a contract count, not a share
    # count, and anything never priceable has nothing to replay.
    lots = [
        lot
        for lot in lots
        if lot.instrument is not None
        and not lot.instrument.not_priceable_reason
        and lot.instrument.category != "CFD"
        and lot.opened_at is not None
    ]

    if not lots:
        return ValueHistoryResult(points=[], start_date=None, capped_by_history=False)

    earliest_lot = min(lot.opened_at for lot in lots).date()
    floor_date = today - timedelta(days=INITIAL_HISTORY_DAYS)
    start = max(earliest_lot, floor_date)
    capped_by_history = start > earliest_lot

    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    instrument_by_id = {lot.instrument_id: lot.instrument for lot in lots}

    benchmark = get_or_create_benchmark_instrument(db)
    benchmark_id = benchmark.id if benchmark is not None else None

    # Widened to `earliest_lot`, not just the display-capped `start` — a lot
    # opened before the display window still needs a real benchmark price on
    # its true open date for the shadow-quantity precompute below. One query,
    # covering both the real holdings and (if configured) the benchmark.
    instrument_ids = set(instrument_by_id)
    if benchmark_id is not None:
        instrument_ids.add(benchmark_id)

    # One query for every corporate action across every instrument in scope —
    # see app/corporate_actions/service.py's module docstring for why PriceBar
    # and Lot are never mutated: this replay corrects for splits at read time
    # instead, applied per-day/per-lot below via quantity_factor_from/price_factor_from.
    actions_by_instrument = load_actions_by_instrument(db, list(instrument_ids))

    bars_by_instrument: dict[int, dict[date, float]] = defaultdict(dict)
    for instrument_id, bar_date, close in db.execute(
        select(PriceBar.instrument_id, PriceBar.bar_date, PriceBar.close)
        .where(PriceBar.instrument_id.in_(instrument_ids), PriceBar.bar_date >= earliest_lot)
        .order_by(PriceBar.instrument_id, PriceBar.bar_date)
    ):
        if close is not None:
            bars_by_instrument[instrument_id][bar_date] = close

    currencies = {i.currency for i in instrument_by_id.values() if i.currency}
    if benchmark is not None and benchmark.currency:
        currencies.add(benchmark.currency)
    # Same widening as the PriceBar query, same reason.
    fx_by_currency = {
        currency: get_rate_range(db, currency, base_currency, earliest_lot, today)
        for currency in currencies
    }

    def _fx_on(currency: str | None, day: date) -> float | None:
        if not currency or currency == base_currency:
            return 1.0
        return fx_by_currency.get(currency, {}).get(day)

    shadow_qty_by_lot = (
        _precompute_shadow_quantities(
            lots, instrument_by_id, benchmark, bars_by_instrument, _fx_on, actions_by_instrument
        )
        if benchmark is not None and benchmark_id is not None
        else {}
    )

    last_close: dict[int, float] = {}
    # The bar_date each cached close actually came from, not the display day
    # it's forward-filled onto — a stale close carried over a weekend/holiday
    # that happens to span a split's effective_date must keep its own pre-
    # split factor, not the post-split factor of the display day it's shown on.
    last_close_date: dict[int, date] = {}
    points: list[ValueHistoryPoint] = []

    for day in days:
        holdings: dict[int, float] = defaultdict(float)
        cost: dict[int, float] = defaultdict(float)
        benchmark_qty = 0.0

        for lot in lots:
            if lot.opened_at.date() > day:
                continue
            if lot.closed_at is not None and lot.closed_at.date() <= day:
                continue
            qty_factor = quantity_factor_from(actions_by_instrument.get(lot.instrument_id, []), lot.opened_at.date())
            holdings[lot.instrument_id] += lot.quantity * qty_factor
            # Cost basis is left unscaled: total money invested is split-invariant
            # (2 shares @ 1000 = 20 @ 100, same 2000 total), only the per-share
            # figures above need correcting.
            cost[lot.instrument_id] += lot.quantity * lot.open_price
            if benchmark_id is not None:
                benchmark_qty += shadow_qty_by_lot.get(lot.id, 0.0)

        if not holdings:
            # Genuinely zero — nothing existed in the portfolio yet, or
            # everything held by then was later fully liquidated. Distinct
            # from "held something, could not price it" below. The benchmark
            # follows the same rule: no real lots active means no shadow
            # position either (they are accumulated from the same lots).
            points.append(
                ValueHistoryPoint(
                    day=day,
                    value=0.0,
                    invested=0.0,
                    benchmark=0.0 if benchmark_id is not None else None,
                )
            )
            continue

        day_value = 0.0
        day_invested = 0.0
        any_value = False
        any_invested = False

        for instrument_id, quantity in holdings.items():
            if quantity == 0:
                continue
            instrument = instrument_by_id[instrument_id]

            close = bars_by_instrument.get(instrument_id, {}).get(day)
            if close is not None:
                last_close[instrument_id] = close
                last_close_date[instrument_id] = day
            raw_price = last_close.get(instrument_id)
            price = (
                raw_price
                * price_factor_from(actions_by_instrument.get(instrument_id, []), last_close_date[instrument_id])
                if raw_price is not None
                else None
            )
            fx = _fx_on(instrument.currency, day)

            if price is not None and fx is not None:
                day_value += quantity * price * fx
                any_value = True
            if fx is not None:
                day_invested += cost[instrument_id] * fx
                any_invested = True

        day_benchmark = None
        if benchmark_id is not None and benchmark_qty:
            bench_close = bars_by_instrument.get(benchmark_id, {}).get(day)
            if bench_close is not None:
                last_close[benchmark_id] = bench_close
                last_close_date[benchmark_id] = day
            raw_bench_price = last_close.get(benchmark_id)
            bench_price = (
                raw_bench_price * price_factor_from(actions_by_instrument.get(benchmark_id, []), last_close_date[benchmark_id])
                if raw_bench_price is not None
                else None
            )
            bench_fx = _fx_on(benchmark.currency, day)
            if bench_price is not None and bench_fx is not None:
                day_benchmark = round(benchmark_qty * bench_price * bench_fx, 2)

        points.append(
            ValueHistoryPoint(
                day=day,
                value=round(day_value, 2) if any_value else None,
                invested=round(day_invested, 2) if any_invested else None,
                benchmark=day_benchmark,
            )
        )

    return ValueHistoryResult(
        points=points,
        start_date=start,
        capped_by_history=capped_by_history,
        benchmark_available=benchmark_id is not None,
    )


def _precompute_shadow_quantities(
    lots: list[Lot],
    instrument_by_id: dict[int, Instrument],
    benchmark: Instrument,
    bars_by_instrument: dict[int, dict[date, float]],
    fx_on,
    actions_by_instrument: dict[int, list],
) -> dict[int, float]:
    """"If the same cash had bought the benchmark instead, on the same day":
    for each lot, how many benchmark units its cost (in base currency, at its
    real open date) would have bought. A closed lot's shadow position closes
    on the same day too — the real `value` series only ever counts currently
    active lots, so a shadow series that kept compounding sold-off cash
    forever would be answering a different, inconsistent question. See
    DEVLOG "Decision 3e.1".

    Missing benchmark price or FX at a lot's exact open date → that lot
    contributes nothing to the shadow series, same "never a guessed number"
    rule as the real `value`/`invested` series.
    """
    quantities: dict[int, float] = {}
    benchmark_actions = actions_by_instrument.get(benchmark.id, [])

    def _nearest_benchmark_price(day: date) -> float | None:
        # Forward search bounded to a week: bridges weekends/holidays only,
        # never silently guesses across a real data gap. Adjusted using the
        # bar's own date, same reasoning as the main day-loop above.
        for offset in range(8):
            bar_date = day - timedelta(days=offset)
            price = bars_by_instrument.get(benchmark.id, {}).get(bar_date)
            if price is not None:
                return price * price_factor_from(benchmark_actions, bar_date)
        return None

    for lot in lots:
        open_day = lot.opened_at.date()
        bench_price = _nearest_benchmark_price(open_day)
        if bench_price is None:
            continue

        lot_currency = lot.currency or instrument_by_id[lot.instrument_id].currency
        lot_fx = fx_on(lot_currency, open_day)
        bench_fx = fx_on(benchmark.currency, open_day)
        if lot_fx is None or bench_fx is None:
            continue

        bench_price_base = bench_price * bench_fx
        if not bench_price_base:
            continue

        lot_cost_base = lot.quantity * lot.open_price * lot_fx
        quantities[lot.id] = lot_cost_base / bench_price_base

    return quantities
