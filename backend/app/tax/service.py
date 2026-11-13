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
from app.ingest.mintos_import import MINTOS_CORE_ACCOUNT
from app.messages import Message, TaxPrepNote
from app.models import MintosTaxReport, TaxNotice, Transaction, TxType
from app.tax.checks import notice_checks
from app.tax.gains import (
    CapitalGainsYear,
    DerivativeGain,
    SaleGain,
    broker_closed_trades,
    capital_gains_by_year,
    compute_sale_gains,
    derivative_gains,
)


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
    #: Closed CFD positions of the year (CTO), counted in `capital_gains`.
    derivatives: list[DerivativeGain] = field(default_factory=list)
    #: Set against the year's income tax notice, when one is imported.
    notice_checks: list[Message] = field(default_factory=list)
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

    realized = [tx.amount for tx in broker_closed_trades(txs)]
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

    rows = _without_superseded_p2p_rows(db, rows)
    by_account: dict[str, list[Transaction]] = defaultdict(list)
    for tx in rows:
        by_account[tx.account].append(tx)

    # One row per account *and currency* comes back: an account paid in
    # several currencies is summed, not overwritten by its last row.
    dividend_rows_by_account: dict[str, tuple[float, float]] = {}
    for row in dividend_summary(db):
        if row.year == tax_year and row.account is not None:
            gross, withholding = dividend_rows_by_account.get(row.account, (0.0, 0.0))
            dividend_rows_by_account[row.account] = (gross + row.gross, withholding + row.withholding_tax)
    # An account with dividends this year but no other transaction type
    # still needs its own envelope row.
    for account in dividend_rows_by_account:
        by_account.setdefault(account, [])

    # Gains on sales need every year on file, not just this one: the
    # average price comes from purchases made before it, and losses carry
    # forward from earlier years.
    def is_cto(account: str) -> bool:
        return _classify_envelope(account) == TaxEnvelopeKind.CTO

    all_sales = compute_sale_gains(db, include_account=is_cto)
    all_derivatives = derivative_gains(db, include_account=is_cto)
    year_sales = [sale for sale in all_sales if sale.executed_at.year == tax_year]
    sales_by_account: dict[str, list[SaleGain]] = defaultdict(list)
    for sale in year_sales:
        sales_by_account[sale.account].append(sale)

    envelopes = [
        _summarize_envelope(account, txs, dividend_rows_by_account, sales_by_account.get(account, []))
        for account, txs in sorted(by_account.items())
    ]
    reports = {report.year: report.figures or {} for report in db.execute(select(MintosTaxReport)).scalars()}
    if tax_year in reports:
        envelopes = _with_mintos_tax_report(envelopes, reports[tax_year])
    platform = {year: _platform_net(figures) for year, figures in reports.items()}

    year_derivatives = [d for d in all_derivatives if d.executed_at.year == tax_year]
    capital_gains = capital_gains_by_year(all_sales, all_derivatives, platform).get(tax_year)
    if (
        capital_gains is not None
        and not year_sales
        and not year_derivatives
        and not platform.get(tax_year)
        and not capital_gains.losses_carried_in
    ):
        capital_gains = None
    checks: list[Message] = []
    notice = db.execute(select(TaxNotice).where(TaxNotice.income_year == tax_year)).scalar_one_or_none()
    if notice is not None:
        investment_income = sum(
            (e.dividends_gross or 0.0) + max(e.interest or 0.0, 0.0)
            for e in envelopes
            if e.envelope_kind in (TaxEnvelopeKind.CTO, TaxEnvelopeKind.P2P)
        )
        checks = notice_checks(tax_year, notice.figures or {}, notice.lines or [], capital_gains, investment_income)

    return TaxYearSummary(
        tax_year=tax_year,
        envelopes=envelopes,
        notice_checks=checks,
        sales=year_sales,
        derivatives=year_derivatives,
        capital_gains=capital_gains,
    )


def _platform_net(figures: dict) -> float:
    """Gains or losses on notes sold, from a Mintos tax report. A row about
    ETFs is left out: ETF sales are in the "Mintos ETF" account, priced by
    the weighted average with the other securities, and would count twice."""
    return round(
        sum(amount for label, amount in (figures.get("capital_gains") or {}).items() if "etf" not in label.lower()),
        2,
    )


def _with_mintos_tax_report(envelopes: list[TaxEnvelopeSummary], figures: dict) -> list[TaxEnvelopeSummary]:
    """The P2P envelope's interest and fees for the year, as Mintos's annual
    tax report gives them: the whole year, in every category (interest,
    bonuses, discount on bonds, interest on pending payments), where the
    quarterly statements give only loan interest and the account statement
    only the dates it covers. The envelope is added when nothing else
    brought it. See DEVLOG "Step 3u.113"."""
    envelope = next((e for e in envelopes if e.account == MINTOS_CORE_ACCOUNT), None)
    if envelope is None:
        envelope = TaxEnvelopeSummary(account=MINTOS_CORE_ACCOUNT, envelope_kind=_classify_envelope(MINTOS_CORE_ACCOUNT))
        envelopes = sorted([*envelopes, envelope], key=lambda e: e.account)
    other = round(sum((figures.get("other_income") or {}).values()), 2)
    envelope.interest = figures.get("income_total") or None
    envelope.fees = figures.get("cost_total") or None
    envelope.status = "to_reconcile"
    envelope.notes = [note for note in envelope.notes if note.code != TaxPrepNote.NOT_APPLICABLE]
    envelope.notes.append(
        Message(
            TaxPrepNote.MINTOS_TAX_REPORT_USED,
            {
                "interest": figures.get("interest") or 0.0,
                "other": other,
                "withholding": figures.get("withholding_tax") or 0.0,
            },
        )
    )
    return envelopes


def _period(tx: Transaction) -> tuple[datetime, datetime] | None:
    raw = tx.raw or {}
    try:
        return datetime.fromisoformat(raw["period_start"]), datetime.fromisoformat(raw["period_end"])
    except (KeyError, TypeError, ValueError):
        return None


def _without_superseded_p2p_rows(db: Session, rows: list[Transaction]) -> list[Transaction]:
    """Mintos interest comes from two sources that overlap: the quarterly
    statement (one row per quarter) and the full account statement (one row
    per year it covers). Where the account statement covers a quarter, the
    quarterly row is left out, so the interest is not counted twice. See
    DEVLOG "Step 3u.112"."""
    p2p = ("P2P_INTEREST", "P2P_FEE")
    covered: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for tx in db.execute(select(Transaction).where(Transaction.type.in_(p2p))).scalars():
        if (tx.raw or {}).get("source") == "transactions_export" and (period := _period(tx)):
            covered[tx.account].append(period)
    if not covered:
        return rows

    def superseded(tx: Transaction) -> bool:
        if tx.type not in p2p or (tx.raw or {}).get("source") == "transactions_export":
            return False
        period = _period(tx)
        return period is not None and any(
            start <= period[0] and period[1] <= end for start, end in covered.get(tx.account, [])
        )

    return [tx for tx in rows if not superseded(tx)]


def available_tax_years(db: Session) -> list[int]:
    """Every calendar year with at least one dated transaction — backs the
    year picker so it never offers a year with nothing to show."""
    years = {
        executed_at.year
        for executed_at in db.execute(
            select(Transaction.executed_at).where(Transaction.executed_at.is_not(None))
        ).scalars()
    }
    years |= set(db.execute(select(MintosTaxReport.year)).scalars())
    return sorted(years, reverse=True)
