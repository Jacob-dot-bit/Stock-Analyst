"""Current value of held positions: price, FX conversion, P&L and totals.

Shared by the portfolio routes, the weekly summary, watchlist, gems and
discovery. It used to live in `routers/portfolio.py`, whose private helpers
other routers imported (DEVLOG "Step 3u.103"). No route here: plain
functions over a `Session`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.messages import Message, PerformanceNote, ValuationNote
from app.models import Instrument, LastQuote, Position, PriceBar, Source
from app.prices.fx_service import get_rate as get_fx_rate
from app.schemas import AccountTotals, MessageOut, PortfolioTotals

#: One position's up-to-date value, P&L, P&L%, price (instrument currency) and
#: price_source ('live' | 'cached' | 'broker').
PositionFigures = tuple[float | None, float | None, float | None, float | None, str]

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


def declared_valuation_note(
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


def resolve_current_price(
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


def position_figures(
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

    price, source = resolve_current_price(db, instrument, live_quotes)

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


def compute_figures(
    db: Session,
    positions: list[Position],
    base_currency: str,
    live_quotes: dict[int, tuple[float, str]],
) -> dict[int, PositionFigures]:
    """One `position_figures` result per position, keyed by position id.

    Computed once per request and shared by totals, per-account totals, the
    positions list and the breakdown chart, instead of re-resolving the same
    price and FX rate once per consumer.
    """
    return {p.id: position_figures(db, p, base_currency, live_quotes) for p in positions}


def aggregate(
    positions: list[Position], figures: dict[int, PositionFigures]
) -> tuple[float, float | None, int, int]:
    """Sum current market value and P&L. Returns (value, P&L, counted, excluded).

    A position without a computable current *value* is **excluded** from the
    total rather than counted as zero: a wrong total that looks correct is
    worse than one that is explicitly partial. A position with a known value
    but no P&L (a P2P aggregate like Mintos Core, or an Amundi fund imported
    from the Synthese live snapshot rather than the annual PDF — see
    `position_figures`'s deliberate `pl=None`, DEVLOG "Decision
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


def compute_totals(
    positions: list[Position], base_currency: str, figures: dict[int, PositionFigures]
) -> PortfolioTotals:
    market_value, unrealized, counted, excluded = aggregate(positions, figures)

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


def compute_account_totals(
    positions: list[Position], figures: dict[int, PositionFigures]
) -> list[AccountTotals]:
    """Break totals down per account: one XTB export only covers a single account."""
    by_account: dict[str, list[Position]] = defaultdict(list)
    for position in positions:
        by_account[position.account or "—"].append(position)

    results: list[AccountTotals] = []
    for account, account_positions in sorted(by_account.items()):
        market_value, unrealized, counted, _ = aggregate(account_positions, figures)
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
            if (found := declared_valuation_note(p.instrument, p.value_as_of)[1]) is not None
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


#: `Session.info` key for a request-scoped `positions_figures_and_total` result.
FIGURES_SNAPSHOT_KEY = "positions_figures_snapshot"


def positions_figures_and_total(db: Session) -> tuple[list[Position], dict[int, PositionFigures], float]:
    """Held positions, their computed figures, and the portfolio total —
    the shared basis for `/breakdown`, `/allocation`, and the personal-
    policy gap comparison, so each doesn't re-derive it independently.

    A caller composing several of those endpoints in one request (the weekly
    summary) can store this result under `db.info[FIGURES_SNAPSHOT_KEY]` so
    every section reuses one valuation instead of recomputing it."""
    snapshot = db.info.get(FIGURES_SNAPSHOT_KEY)
    if snapshot is not None:
        return snapshot
    positions = list(db.execute(select(Position).options(joinedload(Position.instrument))).scalars())
    base_currency = get_settings().base_currency
    figures = compute_figures(db, positions, base_currency, live_quotes={})
    totals = compute_totals(positions, base_currency, figures)
    return positions, figures, totals.market_value or 0.0


def weight_buckets(
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
