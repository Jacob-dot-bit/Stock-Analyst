"""Dividends by year and account — descriptive only, never a tax calculation.

Requested to close a real gap: `GET /api/transactions` already sums
dividends/withholding globally, but not broken down by account (PEA vs a
brokerage account have entirely different French tax treatment) or by
calendar year (what a declaration needs). See DEVLOG "Decision 3u.28".

**Reconciliation, not aggregation, is the hard part.** A dividend and its
withholding tax are two separate `Transaction` rows (`DIVIDEND` and `TAX`),
linked by nothing more than usually sharing an account, an instrument and a
timestamp. Verified against this portfolio's real data before writing any
matching logic: paired rows share the exact same `executed_at` down to the
microsecond in the overwhelming majority of cases, but not always (one
real pair was 1ms apart) — so matching is same-account + same-instrument +
nearest timestamp within a window, not an exact-equality join. See
`_reconcile_instrument_account_group` for the algorithm.

**Absence of a withholding is not an anomaly.** Many dividends legitimately
carry no tax row at all (0% treaty rate, French domestic stock, PEA
wrapper) — a `DIVIDEND` with nothing to match is reported `no_withholding`,
never flagged as a problem. Only a `TAX` row that *cannot* be attributed to
any dividend is a genuine data anomaly (`unmatched_tax`) — a withholding
that was recorded but whose dividend either doesn't exist, is for a
different account/instrument, or falls outside the matching window.

**Summary totals are always computed from raw transactions, never by
summing matched pairs.** A reconciliation miss must never silently shrink
the year's real total — see `dividend_summary`.

**`TxType.TAX` is not all withholding tax.** Found live, checking why real
"unmatched" rows looked wrong before this filter existed: the importer's
`classify_cash_type` buckets French financial-transaction tax ("Tax IFTT")
and UK stamp duty on *trades* into the same `TxType.TAX` as dividend
withholding — all three match its "tax" keyword family. Those two have
nothing to do with a dividend and would never find one to match, showing
up as spurious "unattributed withholding" rows. `_is_dividend_withholding`
re-reads the row's own `raw["Type"]` (the specific operation label XTB
gave it — "Withholding tax" vs. "Stamp duty" vs. "Tax IFTT") to exclude
them, rather than trust the coarser `TxType.TAX` bucket alone.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.ingest.xtb_import import _normalize
from app.models import Instrument, Transaction, TxType

#: Substrings of the normalised `raw["Type"]` label that positively identify
#: a `TAX` row as a transaction tax on a *trade* (French FTT, UK stamp
#: duty) rather than dividend withholding — both share `TxType.TAX` with
#: genuine withholding, found live while building this feature (a real
#: portfolio's PEA account had far more FTT than withholding, which had
#: been silently inflating "withholding tax" totals everywhere).
_TRADE_TAX_KEYWORDS = ("stampduty", "ifft", "iftt")


def _is_dividend_withholding(tax: Transaction) -> bool:
    """True unless `raw["Type"]` positively identifies this as a trade tax.
    Defaults to True — including for manually-entered rows with no `raw` at
    all — since a hand-typed `TAX` transaction has nothing else to go on
    besides the user's own choice to record it as a withholding; only an
    *imported* row whose own label says otherwise is excluded."""
    if not tax.raw:
        return True
    label = _normalize(tax.raw.get("Type"))
    if not label:
        return True
    return not any(keyword in label for keyword in _TRADE_TAX_KEYWORDS)

#: Paired rows share the same instant in every real case checked except one
#: (1ms apart) — same calendar day covers that with room to spare. Widened
#: only when no same-day candidate exists at all, for the rarer case of a
#: dividend and its withholding landing in the broker's ledger on different
#: days (e.g. a weekend settlement lag).
RECONCILIATION_WINDOW_DAYS = 3


@dataclass
class DividendDetailRow:
    id: int
    executed_at: object
    instrument: Instrument | None
    account: str | None
    currency: str | None
    gross: float | None
    withholding_tax: float | None
    net: float | None
    comment: str | None
    #: "matched" | "no_withholding" | "unmatched_tax"
    reconciliation_status: str


@dataclass
class DividendSummaryRow:
    year: int
    account: str | None
    gross: float
    withholding_tax: float
    net: float
    payment_count: int


def _currency_for(tx: Transaction) -> str | None:
    """The instrument's own currency — never stored on `Transaction` itself
    for cash operations (see DEVLOG "Decision 3u.28"), but always available
    this way once the instrument is resolved."""
    return tx.instrument.currency if tx.instrument else tx.currency


def _reconcile_instrument_account_group(
    dividends: list[Transaction], taxes: list[Transaction]
) -> tuple[dict[int, Transaction], list[Transaction]]:
    """Greedy nearest-timestamp matching within one (account, instrument)
    group. Returns (dividend_id -> matched tax row, unmatched tax rows).

    Each dividend claims the closest still-unclaimed tax row within
    `RECONCILIATION_WINDOW_DAYS`, processed in chronological order — this
    handles multiple same-day pairs for the same instrument (seen in real
    data: partial lots paying separately) correctly, since a dividend never
    claims a tax row already spoken for by an earlier, closer dividend.
    """
    unclaimed = list(taxes)
    matches: dict[int, Transaction] = {}

    for dividend in sorted(dividends, key=lambda t: t.executed_at):
        if dividend.executed_at is None:
            continue
        best: Transaction | None = None
        best_delta: timedelta | None = None
        for tax in unclaimed:
            if tax.executed_at is None:
                continue
            delta = abs(tax.executed_at - dividend.executed_at)
            if delta > timedelta(days=RECONCILIATION_WINDOW_DAYS):
                continue
            if best_delta is None or delta < best_delta:
                best, best_delta = tax, delta
        if best is not None:
            matches[dividend.id] = best
            unclaimed.remove(best)

    return matches, unclaimed


def _all_dividend_and_tax_rows(db: Session) -> list[Transaction]:
    """Every `DIVIDEND` row, plus only the `TAX` rows that are genuinely
    dividend withholding (`_is_dividend_withholding`) — trade taxes sharing
    the same `TxType.TAX` bucket (French FTT, UK stamp duty) are excluded
    here so neither `dividend_detail` nor `dividend_summary` needs to
    filter them out separately.
    """
    rows = list(
        db.execute(
            select(Transaction)
            .options(joinedload(Transaction.instrument))
            .where(Transaction.type.in_([TxType.DIVIDEND, TxType.TAX]))
        ).scalars()
    )
    return [r for r in rows if r.type == TxType.DIVIDEND or _is_dividend_withholding(r)]


def dividend_detail(db: Session) -> list[DividendDetailRow]:
    """One row per dividend payment (reconciled with its withholding tax
    when one can be attributed), plus one row per orphan withholding that
    couldn't be attributed to any dividend. Reconciliation is scoped to
    (account, instrument) groups — a `DIVIDEND`/`TAX` row with no
    instrument at all (a manual entry with no symbol given) is never
    matched, rather than risk pairing it with an unrelated row on account
    and date alone.
    """
    rows = _all_dividend_and_tax_rows(db)

    groups: dict[tuple[str | None, int | None], list[Transaction]] = defaultdict(list)
    for row in rows:
        groups[(row.account, row.instrument_id)].append(row)

    result: list[DividendDetailRow] = []
    for (account, instrument_id), group_rows in groups.items():
        dividends = [r for r in group_rows if r.type == TxType.DIVIDEND]
        taxes = [r for r in group_rows if r.type == TxType.TAX]

        if instrument_id is None:
            # Never matched — see docstring. Every row still appears,
            # just always as its own unreconciled line.
            matches: dict[int, Transaction] = {}
            unmatched_taxes = taxes
        else:
            matches, unmatched_taxes = _reconcile_instrument_account_group(dividends, taxes)

        for dividend in dividends:
            tax = matches.get(dividend.id)
            gross = dividend.amount or 0.0
            withholding = tax.amount if tax else None
            result.append(
                DividendDetailRow(
                    id=dividend.id,
                    executed_at=dividend.executed_at,
                    instrument=dividend.instrument,
                    account=account,
                    currency=_currency_for(dividend),
                    gross=gross,
                    withholding_tax=withholding,
                    net=round(gross + (withholding or 0.0), 2),
                    comment=dividend.comment,
                    reconciliation_status="matched" if tax else "no_withholding",
                )
            )

        for tax in unmatched_taxes:
            result.append(
                DividendDetailRow(
                    id=tax.id,
                    executed_at=tax.executed_at,
                    instrument=tax.instrument,
                    account=account,
                    currency=_currency_for(tax),
                    gross=None,
                    withholding_tax=tax.amount,
                    net=tax.amount,
                    comment=tax.comment,
                    reconciliation_status="unmatched_tax",
                )
            )

    result.sort(key=lambda r: r.executed_at or datetime.min, reverse=True)
    return result


def dividend_summary(db: Session) -> list[DividendSummaryRow]:
    """Gross/withholding/net by calendar year and account, computed
    directly from `DIVIDEND`/`TAX` transactions — never by summing
    `dividend_detail`'s matched pairs, so a reconciliation miss can never
    silently shrink a year's real total. `payment_count` counts dividend
    payments only (a `TAX` row is a deduction against one, not a payment of
    its own).
    """
    rows = _all_dividend_and_tax_rows(db)

    totals: dict[tuple[int, str | None], dict[str, float]] = defaultdict(
        lambda: {"gross": 0.0, "withholding_tax": 0.0, "payment_count": 0}
    )
    for row in rows:
        if row.executed_at is None:
            continue
        key = (row.executed_at.year, row.account)
        if row.type == TxType.DIVIDEND:
            totals[key]["gross"] += row.amount or 0.0
            totals[key]["payment_count"] += 1
        else:
            totals[key]["withholding_tax"] += row.amount or 0.0

    summary = [
        DividendSummaryRow(
            year=year,
            account=account,
            gross=round(t["gross"], 2),
            withholding_tax=round(t["withholding_tax"], 2),
            net=round(t["gross"] + t["withholding_tax"], 2),
            payment_count=int(t["payment_count"]),
        )
        for (year, account), t in totals.items()
    ]
    summary.sort(key=lambda r: (r.year, r.account or ""), reverse=True)
    return summary
