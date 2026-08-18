"""The transaction ledger — dividends, fees, trades, cash movements. See
DEVLOG "Decision 3d.1" for why this exists (item #10 of the user's original
UI list), "Decision 3g.1" for manual entry/correction/deletion, "Decision
3p.1" for the instrument/currency P&L split on closed trades, and "Decision
3u.28" for `account` becoming a real column (it was recovered from `raw`
at serve time until then — Alembic didn't exist yet when 3d.1 was written,
which was the whole reason not to ALTER TABLE a table already holding real
rows; that constraint no longer applies). `_recover_account_from_raw`
survives only to backfill rows imported before the column existed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.dividends.service import _is_dividend_withholding
from app.ingest.service import get_or_create_instrument
from app.ingest.xtb_import import _match_column
from app.models import Lot, LotType, Transaction, TxType
from app.schemas import (
    BackfillAccountsOut,
    ManualTransactionIn,
    TransactionListOut,
    TransactionOut,
    TransactionSummaryOut,
    TransactionUpdateIn,
)

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

#: Types creatable/editable through this manual path. BUY/SELL/CLOSED_TRADE
#: are deliberately excluded: those are what the `Lot` ledger (and the
#: historical value chart built on it) actually reasons about, and a manual
#: Transaction row with no matching Lot would just be a convincing-looking
#: phantom trade in the ledger — invisible to the chart, visible everywhere
#: else. Add or correct a holding through `POST /api/portfolio/positions`
#: instead: it creates both the Position and the matching Lot together.
MANUAL_TX_TYPES = {
    TxType.DIVIDEND,
    TxType.TAX,
    TxType.FEE,
    TxType.DEPOSIT,
    TxType.WITHDRAWAL,
    TxType.INTEREST,
    TxType.OTHER,
}


def _recover_account_from_raw(raw: dict | None) -> str | None:
    """Recovers `account` from a row's verbatim source data — used only by
    `POST /backfill-accounts` for rows imported before `account` was a real
    column (DEVLOG "Decision 3u.28"). Scans by normalised alias match
    ("Product" in English, "Produit"/"Compte" in French), the same table the
    parser itself used to build `raw` in the first place, rather than a
    literal `raw.get("Product")` that would silently return nothing for a
    French export.
    """
    if not raw:
        return None
    for header, value in raw.items():
        if _match_column(header) == "account" and value:
            return str(value).strip()
    return None


def _fx_rates_from_raw(raw: dict | None) -> tuple[float | None, float | None]:
    """The open/close FX rates XTB applies to convert a closed trade's price
    (instrument currency) into its P&L (account currency) — parsed by the
    importer (`xtb_import.py`'s `COLUMN_ALIASES`) but, like `account`, never
    added as a column: it already sits in `raw` under whatever header the
    export used, recovered the same normalised-alias way. See DEVLOG
    "Decision 3p.1".
    """
    if not raw:
        return None, None
    open_rate = close_rate = None
    for header, value in raw.items():
        key = _match_column(header)
        if key == "open_fx_rate" and value not in (None, ""):
            open_rate = float(value)
        elif key == "close_fx_rate" and value not in (None, ""):
            close_rate = float(value)
    return open_rate, close_rate


def _closed_trade_effects(
    transaction: Transaction, lot: Lot | None
) -> tuple[float | None, float | None]:
    """Split a closed trade's realised P&L into instrument effect (the stock's
    own price move, in account currency, FX held fixed at the open-day rate)
    and a currency-effect residual against the real, broker-reported P&L.

    The residual is deliberate, not a second independent FX computation: it
    guarantees the two figures always reconcile exactly to
    ``transaction.amount`` (the same number already shown as "Realised
    P&L"), at the cost of also absorbing commission/swap/rounding — there is
    no verified mapping of exactly how XTB nets those into ``net_pl`` in this
    codebase today, so it is surfaced honestly as "currency & fees", not
    oversold as a pure FX figure. ``None`` (never a guessed zero) whenever
    the inputs needed are missing: no matching closed lot, no parseable
    conversion rate, or an open rate of exactly 0. See DEVLOG "Decision 3p.1".
    """
    if lot is None or transaction.amount is None or transaction.quantity is None:
        return None, None
    if transaction.price is None or lot.open_price is None:
        return None, None

    open_rate, _close_rate = _fx_rates_from_raw(transaction.raw)
    if not open_rate:
        return None, None

    instrument_effect = (transaction.price - lot.open_price) * transaction.quantity * open_rate
    currency_effect = transaction.amount - instrument_effect
    return round(instrument_effect, 2), round(currency_effect, 2)


def _out(transaction: Transaction, lot: Lot | None = None) -> TransactionOut:
    out = TransactionOut.model_validate(transaction)
    if transaction.type == TxType.CLOSED_TRADE:
        out.instrument_effect, out.currency_effect = _closed_trade_effects(transaction, lot)
    return out


def _closed_lots_by_external_id(db: Session, rows: list[Transaction]) -> dict[str, Lot]:
    """Batch-fetch the closed lots matching this page's closed trades, once —
    not a query per row. `external_id` is how a `CLOSED_TRADE` `Transaction`
    and its corresponding `CLOSED` `Lot` correlate (see DEVLOG "Decision 3d.1"
    on why they are two separate records in the first place).
    """
    external_ids = [
        row.external_id for row in rows if row.type == TxType.CLOSED_TRADE and row.external_id
    ]
    if not external_ids:
        return {}
    lots = db.execute(
        select(Lot).where(Lot.lot_type == LotType.CLOSED, Lot.external_id.in_(external_ids))
    ).scalars()
    return {lot.external_id: lot for lot in lots}


@router.get("", response_model=TransactionListOut)
def list_transactions(
    type: list[str] | None = Query(None, description="One or more TxType values."),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    account: str | None = Query(None),
    instrument_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> TransactionListOut:
    """The full ledger, newest first."""
    query = (
        select(Transaction)
        .options(joinedload(Transaction.instrument))
        .order_by(Transaction.executed_at.desc())
    )
    if type:
        query = query.where(Transaction.type.in_(type))
    if start_date:
        query = query.where(Transaction.executed_at >= start_date)
    if end_date:
        query = query.where(Transaction.executed_at <= end_date)
    if account:
        query = query.where(Transaction.account == account)
    if instrument_id:
        query = query.where(Transaction.instrument_id == instrument_id)

    rows = list(db.execute(query).scalars())

    lots_by_external_id = _closed_lots_by_external_id(db, rows)
    transactions = [_out(row, lots_by_external_id.get(row.external_id)) for row in rows]
    summary = _compute_summary(rows, lots_by_external_id)
    return TransactionListOut(transactions=transactions, summary=summary)


def _compute_summary(
    rows: list[Transaction], lots_by_external_id: dict[str, Lot] | None = None
) -> TransactionSummaryOut:
    """Sums over whatever rows the caller already filtered to — so a summary
    scoped to "this year" summarises this year, not all time. Cheap either
    way: these are the same rows the list response is already building from,
    not a second query.

    `TAX` here means dividend withholding specifically, same distinction
    `dividends/service.py::_is_dividend_withholding` makes and for the same
    reason: this bucket also holds French FTT and UK stamp duty on trades,
    which have nothing to do with a dividend — found live while building
    the Dividends view (DEVLOG "Decision 3u.28"), fixed here too so this
    page's "Retenue à la source" doesn't disagree with that one's.
    """
    lots_by_external_id = lots_by_external_id or {}
    totals: dict[str, float] = defaultdict(float)
    instrument_total = currency_total = 0.0
    closed_trades_total = closed_trades_with_effect = 0
    for row in rows:
        if row.type == TxType.TAX and not _is_dividend_withholding(row):
            continue
        if row.type in (TxType.DIVIDEND, TxType.TAX, TxType.FEE, TxType.CLOSED_TRADE) and row.amount:
            totals[row.type] += row.amount
        if row.type == TxType.CLOSED_TRADE:
            closed_trades_total += 1
            instrument_effect, currency_effect = _closed_trade_effects(
                row, lots_by_external_id.get(row.external_id)
            )
            if instrument_effect is not None:
                closed_trades_with_effect += 1
                instrument_total += instrument_effect
                currency_total += currency_effect

    dividends = totals.get(TxType.DIVIDEND, 0.0)
    tax = totals.get(TxType.TAX, 0.0)  # already negative in the ledger
    return TransactionSummaryOut(
        total_dividends=round(dividends, 2),
        total_withholding_tax=round(tax, 2),
        net_dividends=round(dividends + tax, 2),
        total_fees=round(totals.get(TxType.FEE, 0.0), 2),
        total_realized_pl=round(totals.get(TxType.CLOSED_TRADE, 0.0), 2),
        total_instrument_effect=round(instrument_total, 2),
        total_currency_effect=round(currency_total, 2),
        closed_trades_with_effect=closed_trades_with_effect,
        closed_trades_total=closed_trades_total,
    )


@router.post("/backfill-accounts", response_model=BackfillAccountsOut)
def backfill_accounts(db: Session = Depends(get_db)) -> BackfillAccountsOut:
    """One-off catch-up for rows imported before `account` was a real column
    (DEVLOG "Decision 3u.28") — recovers the value from each row's own `raw`
    JSON rather than leaving it null forever. Safe to re-run: only ever
    touches rows where `account` is still unset, and a row whose `raw` has
    no recoverable value (manual entries with no account given, or no `raw`
    at all) is simply left null rather than guessed.
    """
    rows = list(db.execute(select(Transaction).where(Transaction.account.is_(None))).scalars())
    updated = 0
    for row in rows:
        recovered = _recover_account_from_raw(row.raw)
        if recovered:
            row.account = recovered
            updated += 1
    db.commit()
    return BackfillAccountsOut(checked=len(rows), updated=updated)


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_manual_transaction(
    payload: ManualTransactionIn, db: Session = Depends(get_db)
) -> TransactionOut:
    """A hand-entered cash-flow row — a dividend received outside the tracked
    accounts, a fee correction, a deposit the export never captured.
    """
    if payload.type not in MANUAL_TX_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"type must be one of {sorted(MANUAL_TX_TYPES)}",
        )

    instrument = get_or_create_instrument(db, payload.broker_symbol) if payload.broker_symbol else None

    transaction = Transaction(
        type=payload.type,
        instrument_id=instrument.id if instrument else None,
        executed_at=payload.executed_at or datetime.now(UTC),
        account=payload.account,
        amount=payload.amount,
        currency=payload.currency,
        comment=payload.comment,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return _out(transaction)


@router.patch("/{transaction_id}", response_model=TransactionOut)
def update_transaction(
    transaction_id: int, payload: TransactionUpdateIn, db: Session = Depends(get_db)
) -> TransactionOut:
    """Correct a transaction — imported or manual. Only the fields provided
    change; `raw` (the verbatim source row, when there is one) is left
    untouched, so the original import data survives as an audit trail even
    after a correction.
    """
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")

    if payload.type is not None:
        if payload.type not in MANUAL_TX_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"type must be one of {sorted(MANUAL_TX_TYPES)}",
            )
        transaction.type = payload.type
    if payload.executed_at is not None:
        transaction.executed_at = payload.executed_at
    if payload.amount is not None:
        transaction.amount = payload.amount
    if payload.currency is not None:
        transaction.currency = payload.currency
    if payload.comment is not None:
        transaction.comment = payload.comment
    if payload.account is not None:
        transaction.account = payload.account

    db.commit()
    db.refresh(transaction)
    return _out(transaction)


@router.delete(
    "/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)) -> Response:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    db.delete(transaction)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
