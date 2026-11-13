"""Annual tax-year reconciliation summary, by account/envelope.

**This is a reconciliation aid, not a tax calculator.** It never applies a
tax rate, never nets a final liability, and never claims a number is what
you owe. Every figure here is a plain sum of already-imported transactions,
grouped by calendar year and by account, so it can be compared against the
official documents a broker/platform issues (an IFU, a Mintos tax report,
etc.) — the reconciliation itself, and the tax-rule versioning needed to go
further, are separate, later chantiers. See DEVLOG "Decision 3u.60".

**Why account, not just category.** French tax treatment differs entirely
by wrapper (PEA vs. a plain brokerage account vs. employee savings vs. P2P
lending), and that distinction lives on `Transaction.account`, not on the
instrument. Getting the wrapper wrong would misclassify every figure
downstream, so `_classify_envelope` is deliberately conservative: an
account name it doesn't recognise falls back to "cto" (the most commonly
applicable, least special-cased regime) rather than guessing at something
more specific.

**Why dividends are delegated, not recomputed.** `dividends/service.py`
already solved the hard part — matching a `DIVIDEND` row to its
withholding `TAX` row, and excluding `TAX` rows that are actually French
FTT or UK stamp duty on a trade (which share `TxType.TAX` with genuine
withholding but have nothing to do with a dividend). Recomputing that here
would risk silently reintroducing the exact bug that module's own docstring
describes having found and fixed live. `dividend_summary` is reused as-is.

**Gains on sales.** A sale on an ordinary account (CTO) gets its gain by
the weighted average acquisition price, over every ordinary account
holding the same security (`app/tax/gains.py`, DEVLOG "Step 3u.110"). A
sale whose purchase is not on file is never estimated: it is counted as
unmatched, with the reason. The broker's own closed-trade figures
(`CLOSED_TRADE`) are still shown as they are, beside it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dividends.service import dividend_summary
from app.messages import Message, TaxPrepNote
from app.models import Transaction, TxType
from app.tax.gains import CapitalGainsYear, SaleGain, capital_gains_by_year, compute_sale_gains


class TaxEnvelopeKind:
    CTO = "cto"
    PEA = "pea"
    P2P = "p2p"
    EMPLOYEE_SAVINGS = "employee_savings"
    #: Real sales exist (`SELL`) whose gain neither the weighted average
    #: price nor a `CLOSED_TRADE` row gives. See DEVLOG "Step 3u.110".
    UNMATCHED_SALE_ENVELOPE = "unmatched_sale_envelope"


#: Account-name substrings (matched case-insensitively) that identify a
#: wrapper with its own tax regime. Checked in this order — "mintos core"/
#: "mintos p2p" before the generic "mintos" catch, so "Mintos ETF" (a real
#: brokerage sub-account, not the P2P pool) doesn't get misclassified as P2P.
_ENVELOPE_HINTS: tuple[tuple[str, str], ...] = (
    ("pea", TaxEnvelopeKind.PEA),
    ("mintos core", TaxEnvelopeKind.P2P),
    ("mintos p2p", TaxEnvelopeKind.P2P),
    ("amundi", TaxEnvelopeKind.EMPLOYEE_SAVINGS),
    ("peg", TaxEnvelopeKind.EMPLOYEE_SAVINGS),
    ("perco", TaxEnvelopeKind.EMPLOYEE_SAVINGS),
    ("pee", TaxEnvelopeKind.EMPLOYEE_SAVINGS),
)


def _classify_envelope(account: str) -> str:
    lowered = account.lower()
    for hint, kind in _ENVELOPE_HINTS:
        if hint in lowered:
            return kind
    return TaxEnvelopeKind.CTO


@dataclass
class TaxOtherFlow:
    """One `OTHER`-typed transaction, shown as-is rather than bucketed into
    a guessed category — e.g. an Amundi annual statement's own aggregate
    lines ("versements_volontaires", "abondement_net"...). These are
    contribution-side flows, never taxable on their own; surfaced for
    transparency, not summed into any tax-relevant total."""

    label: str
    amount: float


@dataclass
class TaxEnvelopeSummary:
    account: str
    envelope_kind: str
    dividends_gross: float | None = None
    dividends_withholding: float | None = None
    interest: float | None = None
    realized_gains: float | None = None
    realized_losses: float | None = None
    fees: float | None = None
    deposits: float | None = None
    withdrawals: float | None = None
    #: Gains and losses of this account's sales by the weighted average
    #: price (CTO only); None when no sale of the year could be matched.
    pmp_gains: float | None = None
    pmp_losses: float | None = None
    pmp_matched_sales: int = 0
    unmatched_sales_count: int = 0
    unmatched_sales_amount: float | None = None
    #: Unmatched sales by reason (`gains.Unmatched`).
    unmatched_reasons: dict[str, int] = field(default_factory=dict)
    other_flows: list[TaxOtherFlow] = field(default_factory=list)
    #: "to_reconcile" (some tax-relevant activity found, nothing to compare
    #: it against yet) | "not_applicable" (no tax-relevant activity this
    #: year at all).
    status: str = "not_applicable"
    notes: list[Message] = field(default_factory=list)


@dataclass
class TaxYearSummary:
    tax_year: int
    envelopes: list[TaxEnvelopeSummary]
    #: Every CTO sale of the year, matched or not.
    sales: list[SaleGain] = field(default_factory=list)
    #: The year's net gain by the weighted average price, with losses
    #: carried in from earlier years; None when the year has no CTO sale
    #: and no loss to carry.
    capital_gains: CapitalGainsYear | None = None


#: Types genuinely tax-relevant for the "does this envelope have anything
#: to report" check below — deliberately excludes DEPOSIT (an investor's own
#: cash movement, never a tax event) and the P2P/OTHER internal-movement
#: types, which are shown for transparency but never counted as activity.
_TAX_RELEVANT_TYPES = {
    TxType.DIVIDEND,
    TxType.INTEREST,
    TxType.CLOSED_TRADE,
    TxType.FEE,
    TxType.WITHDRAWAL,
    "P2P_INTEREST",
    "P2P_FEE",
}


def _sum_amounts(txs: list[Transaction], *types: str) -> float | None:
    values = [tx.amount for tx in txs if tx.type in types and tx.amount is not None]
    return round(sum(values), 2) if values else None


def _summarize_envelope(
    account: str,
    txs: list[Transaction],
    dividend_rows_by_account: dict[str, tuple[float, float]],
    sales: list[SaleGain],
) -> TaxEnvelopeSummary:
    kind = _classify_envelope(account)

    gross, withholding = dividend_rows_by_account.get(account, (0.0, 0.0))
    dividends_gross = round(gross, 2) if gross else None
    dividends_withholding = round(withholding, 2) if withholding else None

    interest = _sum_amounts(txs, TxType.INTEREST, "P2P_INTEREST")
    fees = _sum_amounts(txs, TxType.FEE, "P2P_FEE")
    deposits = _sum_amounts(txs, TxType.DEPOSIT)
    withdrawals = _sum_amounts(txs, TxType.WITHDRAWAL)

    realized = [tx.amount for tx in txs if tx.type == TxType.CLOSED_TRADE and tx.amount is not None]
    gains = [a for a in realized if a > 0]
    losses = [a for a in realized if a < 0]
    realized_gains = round(sum(gains), 2) if gains else None
    realized_losses = round(sum(losses), 2) if losses else None

    other_flows = [
        TaxOtherFlow(label=tx.comment or tx.type, amount=tx.amount)
        for tx in txs
        if tx.type == TxType.OTHER and tx.amount is not None
    ]

    # Gains by the weighted average price (CTO sales only, see `gains.py`).
    matched = [sale for sale in sales if sale.matched]
    pmp_gains_list = [sale.gain for sale in matched if sale.gain >= 0]
    pmp_losses_list = [sale.gain for sale in matched if sale.gain < 0]
    pmp_gains = round(sum(pmp_gains_list), 2) if pmp_gains_list else None
    pmp_losses = round(sum(pmp_losses_list), 2) if pmp_losses_list else None

    # A sale is left unmatched only when neither the average price nor the
    # broker's own closed trade gives its gain. Sales inside PEA, employee
    # savings or P2P are not taxed as they happen: nothing is missing there.
    unmatched = [sale for sale in sales if not sale.matched] if not realized else []
    unmatched_sales_count = len(unmatched)
    unmatched_sales_amount = round(sum(sale.proceeds for sale in unmatched), 2) if unmatched else None
    unmatched_reasons: dict[str, int] = {}
    for sale in unmatched:
        unmatched_reasons[sale.unmatched_reason] = unmatched_reasons.get(sale.unmatched_reason, 0) + 1

    notes: list[Message] = []
    if kind in (TaxEnvelopeKind.PEA, TaxEnvelopeKind.EMPLOYEE_SAVINGS):
        if withdrawals:
            notes.append(Message(TaxPrepNote.WITHDRAWAL_DETECTED, {"amount": abs(withdrawals)}))
        else:
            notes.append(Message(TaxPrepNote.NO_WITHDRAWAL_DETECTED, {}))
    if unmatched_sales_count:
        notes.append(Message(TaxPrepNote.UNMATCHED_SALES, {"count": unmatched_sales_count}))

    has_activity = any(
        tx.type in _TAX_RELEVANT_TYPES and tx.amount is not None for tx in txs
    ) or unmatched_sales_count > 0 or bool(matched)
    status = "to_reconcile" if has_activity else "not_applicable"
    # The PEA/employee-savings "no withdrawal" note above already explains
    # why nothing is taxable here — adding the generic NOT_APPLICABLE note
    # on top of it would just repeat the same fact in different words.
    if not has_activity and not notes:
        notes.append(Message(TaxPrepNote.NOT_APPLICABLE, {}))

    return TaxEnvelopeSummary(
        account=account,
        envelope_kind=kind,
        dividends_gross=dividends_gross,
        dividends_withholding=dividends_withholding,
        interest=interest,
        realized_gains=realized_gains,
        realized_losses=realized_losses,
        pmp_gains=pmp_gains,
        pmp_losses=pmp_losses,
        pmp_matched_sales=len(matched),
        fees=fees,
        deposits=deposits,
        withdrawals=withdrawals,
        unmatched_sales_count=unmatched_sales_count,
        unmatched_sales_amount=unmatched_sales_amount,
        unmatched_reasons=unmatched_reasons,
        other_flows=other_flows,
        status=status,
        notes=notes,
    )


def compute_tax_year_summary(db: Session, tax_year: int) -> TaxYearSummary:
    """One `TaxEnvelopeSummary` per account with any transaction in
    `tax_year`, sourced entirely from already-imported data. No tax rate is
    ever applied; see this module's own docstring."""
    start = datetime(tax_year, 1, 1)
    end = datetime(tax_year, 12, 31, 23, 59, 59, 999999)

    rows = list(
        db.execute(
            select(Transaction).where(
                Transaction.executed_at >= start,
                Transaction.executed_at <= end,
                Transaction.account.is_not(None),
            )
        ).scalars()
    )

    by_account: dict[str, list[Transaction]] = defaultdict(list)
    for tx in rows:
        by_account[tx.account].append(tx)

    dividend_rows_by_account: dict[str, tuple[float, float]] = {
        row.account: (row.gross, row.withholding_tax)
        for row in dividend_summary(db)
        if row.year == tax_year and row.account is not None
    }
    # An account with dividends this year but no other transaction type
    # still needs its own envelope row.
    for account in dividend_rows_by_account:
        by_account.setdefault(account, [])

    # Gains on sales need every year on file, not just this one: the
    # average price comes from purchases made before it, and losses carry
    # forward from earlier years.
    all_sales = compute_sale_gains(db, include_account=lambda a: _classify_envelope(a) == TaxEnvelopeKind.CTO)
    year_sales = [sale for sale in all_sales if sale.executed_at.year == tax_year]
    sales_by_account: dict[str, list[SaleGain]] = defaultdict(list)
    for sale in year_sales:
        sales_by_account[sale.account].append(sale)

    envelopes = [
        _summarize_envelope(account, txs, dividend_rows_by_account, sales_by_account.get(account, []))
        for account, txs in sorted(by_account.items())
    ]
    capital_gains = capital_gains_by_year(all_sales).get(tax_year)
    if capital_gains is not None and not year_sales and not capital_gains.losses_carried_in:
        capital_gains = None
    return TaxYearSummary(
        tax_year=tax_year, envelopes=envelopes, sales=year_sales, capital_gains=capital_gains
    )


def available_tax_years(db: Session) -> list[int]:
    """Every calendar year with at least one dated transaction — backs the
    year picker so it never offers a year with nothing to show."""
    years = {
        executed_at.year
        for executed_at in db.execute(
            select(Transaction.executed_at).where(Transaction.executed_at.is_not(None))
        ).scalars()
    }
    return sorted(years, reverse=True)
