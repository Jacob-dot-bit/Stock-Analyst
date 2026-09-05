"""Dividends by year and account — see `app/dividends/service.py` for the
reconciliation and aggregation logic this only exposes. Descriptive only:
no tax liability is computed here, just what was actually received and
withheld, broken down the way a French tax declaration needs (PEA and a
brokerage account are taxed completely differently). See DEVLOG "Decision
3u.28".
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dividends.service import dividend_detail, dividend_summary
from app.schemas import DividendDetailRowOut, DividendSummaryRowOut, InstrumentOut

router = APIRouter(prefix="/api/dividends", tags=["dividends"])


def _detail_out(row) -> DividendDetailRowOut:
    return DividendDetailRowOut(
        id=row.id,
        executed_at=row.executed_at,
        instrument=InstrumentOut.model_validate(row.instrument) if row.instrument else None,
        account=row.account,
        currency=row.currency,
        gross=row.gross,
        withholding_tax=row.withholding_tax,
        net=row.net,
        comment=row.comment,
        reconciliation_status=row.reconciliation_status,
    )


@router.get("/summary", response_model=list[DividendSummaryRowOut])
def get_dividend_summary(db: Session = Depends(get_db)) -> list[DividendSummaryRowOut]:
    """Gross/withholding/net by calendar year and account, newest first."""
    return [DividendSummaryRowOut(**vars(row)) for row in dividend_summary(db)]


def _filtered_detail(
    db: Session, year: int | None, account: str | None, instrument_id: int | None
) -> list:
    rows = dividend_detail(db)
    if year is not None:
        rows = [r for r in rows if r.executed_at is not None and r.executed_at.year == year]
    if account is not None:
        rows = [r for r in rows if r.account == account]
    if instrument_id is not None:
        rows = [r for r in rows if r.instrument is not None and r.instrument.id == instrument_id]
    return rows


@router.get("/detail", response_model=list[DividendDetailRowOut])
def get_dividend_detail(
    year: int | None = Query(None),
    account: str | None = Query(None),
    instrument_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> list[DividendDetailRowOut]:
    """Every dividend payment and orphan withholding, newest first —
    filtered in memory (this app's transaction volume never justifies a
    dedicated indexed query for a filter combination this rarely used)."""
    return [_detail_out(row) for row in _filtered_detail(db, year, account, instrument_id)]


@router.get("/summary.csv")
def get_dividend_summary_csv(db: Session = Depends(get_db)) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["year", "account", "gross", "withholding_tax", "net", "payment_count"])
    for row in dividend_summary(db):
        writer.writerow([row.year, row.account or "", row.gross, row.withholding_tax, row.net, row.payment_count])
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dividendes_par_compte_par_annee.csv"},
    )


@router.get("/detail.csv")
def get_dividend_detail_csv(
    year: int | None = Query(None),
    account: str | None = Query(None),
    instrument_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "executed_at",
            "instrument",
            "account",
            "currency",
            "gross",
            "withholding_tax",
            "net",
            "reconciliation_status",
            "comment",
        ]
    )
    for row in _filtered_detail(db, year, account, instrument_id):
        writer.writerow(
            [
                row.executed_at.isoformat() if row.executed_at else "",
                row.instrument.broker_symbol if row.instrument else "",
                row.account or "",
                row.currency or "",
                row.gross if row.gross is not None else "",
                row.withholding_tax if row.withholding_tax is not None else "",
                row.net if row.net is not None else "",
                row.reconciliation_status,
                row.comment or "",
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dividendes_detail_transactions.csv"},
    )
