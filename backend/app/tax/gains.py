"""Capital gains on sales of securities held in ordinary brokerage accounts,
by the French rule: the weighted average acquisition price ("prix moyen
pondéré d'acquisition", PMP), not FIFO.

How the rule works. For one security, the cost of the units held is the
sum of what was paid for every unit bought, fees included. A sale takes
units out at the average cost of all units held just before it: the gain
is the sale proceeds (net of fees) minus `units sold × average cost`, and
what is left keeps the same average. The average runs over every ordinary
account holding that security, not one account at a time, because the tax
office counts them as one holding: the same security is recognised across
brokers by its ISIN when the instrument has one, by the instrument itself
otherwise. PEA, employee savings and P2P are left
out: their sales are not taxed as they happen.

Where the figures come from. Every importer that knows the units of a
trade writes them on the BUY/SELL transaction (Mintos ETF portfolios). An
XTB cash operation has no unit column, but its comment says
"OPEN BUY 2 @ 175.08" / "CLOSE BUY 2/5 @ 180.00" (lately with the symbol:
"CLOSE BUY ABC.US 1/2 @ 98.40"): the units are read from there. Amounts
are the cash that moved in the account, so fees are in, and
a trade in a foreign currency is already in the account's currency on the
day.

What is never guessed. A sale is "matched" only when every unit sold can
be traced to a purchase on file. A sale before the first purchase on file
(a holding bought before the oldest export), a sale with no unit count or
no security, or a purchase with no unit count before it leaves the sale
unmatched, with the reason. It is then up to the broker's tax summary (IFU).

Derivatives. A CFD (index, commodity, crypto, or a share traded as a
CFD) has no purchase or sale of units: only the broker's closed position
gives its result. Since 2014 such gains and losses follow the same regime
as sales of securities and are netted with them, so the closed positions
of an instrument never bought or sold as units count in the year's total
(`derivative_gains`). XTB writes each of them twice: once in its closed
positions sheet (result after swap and rollover, with a volume) and once
as a cash operation "Profit of position #…" (before them, no volume).
Only the first is kept (`broker_closed_trades`).

Losses. A net loss for a year can be set against net gains of the next ten
years (article 150-0 D, 11 du CGI); `capital_gains_by_year` carries them
forward in that order, oldest first. See DEVLOG "Step 3u.110".
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, TxType

#: "OPEN BUY 2 @ 175.08", "CLOSE BUY 2/5 @ 180.00", "OPEN BUY 0.5 @ 1 234.5",
#: and the newer "CLOSE BUY ABC.US 1/2 @ 98.40" with the symbol in it.
_XTB_TRADE_RE = re.compile(r"\b(?:OPEN|CLOSE)\s+(?:BUY|SELL)\s+(?:[A-Z][A-Z0-9.\-]*\s+)?(\d+(?:[.,]\d+)?)(?:\s*/\s*\d+(?:[.,]\d+)?)?\s*@", re.IGNORECASE)
_EPS = 1e-6
#: Years a net loss can be carried forward.
LOSS_CARRY_YEARS = 10


class Unmatched:
    NO_UNITS = "no_units"
    NO_PURCHASE = "no_purchase"
    INCOMPLETE_HISTORY = "incomplete_history"
    NO_INSTRUMENT = "no_instrument"


@dataclass
class SaleGain:
    transaction_id: int
    account: str
    instrument_id: int | None
    symbol: str | None
    executed_at: datetime
    units: float | None
    proceeds: float
    #: None when unmatched.
    cost: float | None = None
    gain: float | None = None
    unmatched_reason: str | None = None

    @property
    def matched(self) -> bool:
        return self.gain is not None


def trade_units(tx: Transaction) -> float | None:
    """Units of a BUY/SELL, positive: the stored quantity, or what the
    broker's comment says."""
    if tx.quantity is not None and abs(tx.quantity) > _EPS:
        return abs(tx.quantity)
    match = _XTB_TRADE_RE.search(tx.comment or "")
    if match:
        return float(match.group(1).replace(",", "."))
    return None


def _security_key(tx: Transaction) -> str:
    """One key per security, whichever broker symbol it was bought under."""
    isin = tx.instrument.isin if tx.instrument else None
    return f"isin:{isin.upper()}" if isin else f"id:{tx.instrument_id}"


@dataclass
class _Holding:
    units: float = 0.0
    cost: float = 0.0
    #: A purchase with no unit count: from there on the average is unknown.
    broken: bool = False


def compute_sale_gains(db: Session, include_account: Callable[[str], bool]) -> list[SaleGain]:
    """Every SELL of an account `include_account` accepts, in date order,
    with its gain by the weighted average cost, or the reason it has none."""
    rows = db.execute(
        select(Transaction)
        .where(
            Transaction.type.in_([TxType.BUY, TxType.SELL]),
            Transaction.account.is_not(None),
            Transaction.executed_at.is_not(None),
            Transaction.amount.is_not(None),
        )
        .order_by(Transaction.executed_at, Transaction.id)
    ).scalars().all()

    holdings: dict[str, _Holding] = defaultdict(_Holding)
    out: list[SaleGain] = []
    for tx in rows:
        if not include_account(tx.account):
            continue
        units = trade_units(tx)
        if tx.instrument_id is None:
            # No security on the row: nothing to average against.
            if tx.type == TxType.SELL:
                out.append(SaleGain(
                    transaction_id=tx.id,
                    account=tx.account,
                    instrument_id=None,
                    symbol=None,
                    executed_at=tx.executed_at,
                    units=units,
                    proceeds=round(abs(tx.amount), 2),
                    unmatched_reason=Unmatched.NO_INSTRUMENT,
                ))
            continue
        holding = holdings[_security_key(tx)]
        if tx.type == TxType.BUY:
            if units is None:
                holding.broken = True
                continue
            holding.units += units
            holding.cost += abs(tx.amount)
            continue

        sale = SaleGain(
            transaction_id=tx.id,
            account=tx.account,
            instrument_id=tx.instrument_id,
            symbol=tx.instrument.broker_symbol if tx.instrument else None,
            executed_at=tx.executed_at,
            units=units,
            proceeds=round(abs(tx.amount), 2),
        )
        out.append(sale)
        if units is None:
            sale.unmatched_reason = Unmatched.NO_UNITS
            holding.broken = True
        elif holding.broken:
            sale.unmatched_reason = Unmatched.INCOMPLETE_HISTORY
        elif holding.units < units - _EPS:
            # Units sold that were bought before the oldest file on record.
            sale.unmatched_reason = Unmatched.NO_PURCHASE if holding.units <= _EPS else Unmatched.INCOMPLETE_HISTORY
            holding.broken = True
        else:
            cost = holding.cost * units / holding.units
            sale.cost = round(cost, 2)
            sale.gain = round(abs(tx.amount) - cost, 2)
            holding.units -= units
            holding.cost -= cost
            if holding.units <= _EPS:
                holding.units, holding.cost = 0.0, 0.0
    return out


def broker_closed_trades(rows: list[Transaction]) -> list[Transaction]:
    """`rows`' CLOSED_TRADE transactions, each closed position once: the
    cash-operation copy (no volume) is dropped when the same account and
    instrument also have closed-position rows (with a volume)."""
    closed = [tx for tx in rows if tx.type == TxType.CLOSED_TRADE and tx.amount is not None]
    with_volume = {(tx.account, tx.instrument_id) for tx in closed if tx.quantity is not None}
    return [
        tx for tx in closed
        if tx.quantity is not None or (tx.account, tx.instrument_id) not in with_volume
    ]


@dataclass
class DerivativeGain:
    transaction_id: int
    account: str
    symbol: str | None
    executed_at: datetime
    gain: float


def derivative_gains(db: Session, include_account: Callable[[str], bool]) -> list[DerivativeGain]:
    """Closed positions, in accounts `include_account` accepts, of
    instruments never bought or sold as units there: CFDs."""
    rows = db.execute(
        select(Transaction)
        .where(
            Transaction.type.in_([TxType.BUY, TxType.SELL, TxType.CLOSED_TRADE]),
            Transaction.instrument_id.is_not(None),
            Transaction.account.is_not(None),
            Transaction.executed_at.is_not(None),
        )
        .order_by(Transaction.executed_at, Transaction.id)
    ).scalars().all()
    rows = [tx for tx in rows if include_account(tx.account)]
    traded = {tx.instrument_id for tx in rows if tx.type in (TxType.BUY, TxType.SELL)}
    return [
        DerivativeGain(
            transaction_id=tx.id,
            account=tx.account,
            symbol=tx.instrument.broker_symbol if tx.instrument else None,
            executed_at=tx.executed_at,
            gain=round(tx.amount, 2),
        )
        for tx in broker_closed_trades(rows)
        if tx.instrument_id not in traded
    ]


@dataclass
class CapitalGainsYear:
    year: int
    gains: float = 0.0
    losses: float = 0.0
    matched_sales: int = 0
    unmatched_sales: int = 0
    #: Net result of closed CFD positions, already in gains/losses.
    derivatives: float = 0.0
    #: gains + losses of the year.
    net: float = 0.0
    #: Earlier losses still usable at the start of the year, by year of origin.
    losses_carried_in: dict[int, float] = field(default_factory=dict)
    losses_used: float = 0.0
    #: Gain left after the carried losses (0 when the year is a net loss).
    taxable_net: float = 0.0
    #: Losses still usable after this year, by year of origin.
    losses_carried_out: dict[int, float] = field(default_factory=dict)


def capital_gains_by_year(
    sales: list[SaleGain], derivatives: list[DerivativeGain] = ()
) -> dict[int, CapitalGainsYear]:
    """Matched sales and closed CFD positions summed per calendar year, with
    losses carried forward up to `LOSS_CARRY_YEARS` years, the oldest used
    first."""
    years: dict[int, CapitalGainsYear] = {}
    for d in derivatives:
        year = years.setdefault(d.executed_at.year, CapitalGainsYear(year=d.executed_at.year))
        year.derivatives += d.gain
        if d.gain >= 0:
            year.gains += d.gain
        else:
            year.losses += d.gain
    for sale in sales:
        year = years.setdefault(sale.executed_at.year, CapitalGainsYear(year=sale.executed_at.year))
        if not sale.matched:
            year.unmatched_sales += 1
            continue
        year.matched_sales += 1
        if sale.gain >= 0:
            year.gains += sale.gain
        else:
            year.losses += sale.gain

    if not years:
        return {}
    pool: dict[int, float] = {}
    for y in range(min(years), max(years) + 1):
        year = years.setdefault(y, CapitalGainsYear(year=y))
        pool = {origin: left for origin, left in pool.items() if y - origin <= LOSS_CARRY_YEARS and left > _EPS}
        year.gains, year.losses = round(year.gains, 2), round(year.losses, 2)
        year.derivatives = round(year.derivatives, 2)
        year.net = round(year.gains + year.losses, 2)
        year.losses_carried_in = {k: round(v, 2) for k, v in pool.items()}
        if year.net < 0:
            pool[y] = -year.net
        else:
            remaining = year.net
            for origin in sorted(pool):
                used = min(pool[origin], remaining)
                pool[origin] -= used
                remaining -= used
                year.losses_used += used
            year.losses_used = round(year.losses_used, 2)
            year.taxable_net = round(remaining, 2)
        year.losses_carried_out = {k: round(v, 2) for k, v in pool.items() if v > _EPS}
    return years
