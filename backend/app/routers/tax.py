"""Annual tax-year reconciliation summary, by account/envelope — see
`app/tax/service.py` for the computation this only exposes. A
reconciliation aid, not a tax calculator: never applies a rate, never
computes a final liability. See DEVLOG "Decision 3u.60".
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.messages import Message, TaxPrepNote
from app.schemas import (
    MessageOut,
    TaxEnvelopeSummaryOut,
    TaxOtherFlowOut,
    TaxYearSummaryOut,
    TaxYearsAvailableOut,
)
from app.tax.service import TaxEnvelopeSummary, available_tax_years, compute_tax_year_summary

router = APIRouter(prefix="/api/tax", tags=["tax"])


def _envelope_out(envelope: TaxEnvelopeSummary) -> TaxEnvelopeSummaryOut:
    return TaxEnvelopeSummaryOut(
        account=envelope.account,
        envelope_kind=envelope.envelope_kind,
        dividends_gross=envelope.dividends_gross,
        dividends_withholding=envelope.dividends_withholding,
        interest=envelope.interest,
        realized_gains=envelope.realized_gains,
        realized_losses=envelope.realized_losses,
        fees=envelope.fees,
        deposits=envelope.deposits,
        withdrawals=envelope.withdrawals,
        unmatched_sales_count=envelope.unmatched_sales_count,
        unmatched_sales_amount=envelope.unmatched_sales_amount,
        other_flows=[TaxOtherFlowOut(label=f.label, amount=f.amount) for f in envelope.other_flows],
        status=envelope.status,
        notes=[MessageOut(**m.as_dict()) for m in envelope.notes],
    )


@router.get("/years", response_model=TaxYearsAvailableOut)
def get_tax_years(db: Session = Depends(get_db)) -> TaxYearsAvailableOut:
    return TaxYearsAvailableOut(years=available_tax_years(db))


@router.get("/summary", response_model=TaxYearSummaryOut)
def get_tax_summary(
    year: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> TaxYearSummaryOut:
    """Every account's tax-relevant activity for one calendar year, summed
    directly from already-imported transactions — no rate applied, no
    liability computed. See this module's own docstring and DEVLOG
    "Decision 3u.60"."""
    summary = compute_tax_year_summary(db, year or datetime.now().year)
    return TaxYearSummaryOut(
        tax_year=summary.tax_year,
        envelopes=[_envelope_out(e) for e in summary.envelopes],
        disclaimer=MessageOut(**Message(TaxPrepNote.DISCLAIMER).as_dict()),
    )


@router.get("/summary.csv")
def get_tax_summary_csv(
    year: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    year = year or datetime.now().year
    summary = compute_tax_year_summary(db, year)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "account",
            "envelope_kind",
            "dividends_gross",
            "dividends_withholding",
            "interest",
            "realized_gains",
            "realized_losses",
            "fees",
            "deposits",
            "withdrawals",
            "unmatched_sales_count",
            "unmatched_sales_amount",
            "status",
        ]
    )
    for e in summary.envelopes:
        writer.writerow(
            [
                e.account,
                e.envelope_kind,
                e.dividends_gross if e.dividends_gross is not None else "",
                e.dividends_withholding if e.dividends_withholding is not None else "",
                e.interest if e.interest is not None else "",
                e.realized_gains if e.realized_gains is not None else "",
                e.realized_losses if e.realized_losses is not None else "",
                e.fees if e.fees is not None else "",
                e.deposits if e.deposits is not None else "",
                e.withdrawals if e.withdrawals is not None else "",
                e.unmatched_sales_count,
                e.unmatched_sales_amount if e.unmatched_sales_amount is not None else "",
                e.status,
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=preparation_fiscale_{year}.csv"},
    )
