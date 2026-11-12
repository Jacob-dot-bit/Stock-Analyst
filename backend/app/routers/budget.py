"""My bank accounts as a budget: income, spending by category, what goes
to the brokers. Read-only; the lines come from the bank export imported in
the single upload slot. See `app/budget/service.py` and DEVLOG "Step 3u.92".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.budget.service import CATEGORIES, budget_operations, budget_summary
from app.db import get_db
from app.schemas import BudgetOperationsOut, BudgetSummaryOut

router = APIRouter(prefix="/api/budget", tags=["budget"])


@router.get("/summary", response_model=BudgetSummaryOut)
def get_budget_summary(
    months: int = Query(12, ge=1, le=60), db: Session = Depends(get_db)
) -> BudgetSummaryOut:
    return BudgetSummaryOut.model_validate(budget_summary(db, months=months))


@router.get("/operations", response_model=BudgetOperationsOut)
def get_budget_operations(
    days: int = Query(90, ge=1, le=1100),
    category: str | None = None,
    account: str | None = None,
    db: Session = Depends(get_db),
) -> BudgetOperationsOut:
    if category is not None and category not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f"unknown category: {category}")
    return BudgetOperationsOut.model_validate(
        budget_operations(db, days=days, category=category, account=account)
    )


@router.get("/categories", response_model=list[str])
def get_budget_categories() -> list[str]:
    return CATEGORIES
