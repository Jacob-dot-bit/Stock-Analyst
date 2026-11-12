"""Budget: where the money of my bank accounts goes, month by month.

Reads `bank_operations` (every line of the bank exports, Step 3u.92) and
puts each line in a category (`categories.py`). Three kinds of line are
kept apart from spending and income, because the money stays mine:

* transfers to and from a broker (``investment``), shown as their own total
  next to the budget;
* transfers between my own accounts (``internal``): the parser recognises
  the ones naming me or a savings book; here, a debit on one account and a
  credit of the same amount on another within a few days are paired too;
* nothing else: a refund lowers its category, it is not income.

Two things are worked out from the history rather than from a keyword:
the salary (the same payer crediting at least 500 in three different
months, when its label says nothing) and the recurring payments (same
merchant, similar amount, at least three of the last four full months).

Everything is relative to the last operation on file, not to today: an
export is a snapshot and the month it stops in is partial.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.budget.categories import CATEGORY_KIND, INCOME, INTERNAL, INVESTMENT, SPENDING, categorize
from app.models import BankOperation

#: Days apart a debit and its matching credit can be to count as one
#: transfer between my accounts (a Friday transfer lands on Monday).
PAIR_WINDOW_DAYS = 3
#: A payer crediting at least this much in `SALARY_MIN_MONTHS` different
#: months is my salary, whatever its label says.
SALARY_MIN_AMOUNT = 500.0
SALARY_MIN_MONTHS = 3
#: A recurring payment: seen in this many of the last `RECURRING_LOOKBACK`
#: full months, each amount within `RECURRING_TOLERANCE` of their median.
RECURRING_MIN_MONTHS = 3
RECURRING_LOOKBACK = 4
RECURRING_TOLERANCE = 0.2


@dataclass
class Line:
    id: int
    executed_on: date
    account: str
    amount: float
    currency: str
    merchant: str
    category: str
    kind: str


def _month(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _month_start(day: date, back: int = 0) -> date:
    index = day.year * 12 + day.month - 1 - back
    return date(index // 12, index % 12 + 1, 1)


def last_operation_date(db: Session) -> date | None:
    return db.execute(select(func.max(BankOperation.executed_on))).scalar()


def _load(db: Session, start: date, end: date) -> list[Line]:
    """Lines between `start` and `end`, categorised. Reads a few days on
    each side so a transfer between my accounts across the edge still pairs."""
    margin = timedelta(days=PAIR_WINDOW_DAYS)
    rows = db.execute(
        select(BankOperation)
        .where(BankOperation.executed_on >= start - margin, BankOperation.executed_on <= end + margin)
        .order_by(BankOperation.executed_on, BankOperation.id)
    ).scalars().all()
    lines = []
    for row in rows:
        found = categorize(row.label, row.amount, broker=row.broker, own_transfer=row.own_transfer)
        lines.append(
            Line(
                id=row.id,
                executed_on=row.executed_on,
                account=row.account,
                amount=row.amount,
                currency=row.currency,
                merchant=found.merchant,
                category=found.category,
                kind=found.kind,
            )
        )
    _pair_own_transfers(lines)
    _spot_salary(db, lines)
    return [line for line in lines if start <= line.executed_on <= end]


def _pair_own_transfers(lines: list[Line]) -> None:
    """A debit on one of my accounts and a credit of the same amount on
    another, a few days apart, with neither recognised as anything else."""
    loose = {"transfers_out", "other_income", "other"}
    credits = [line for line in lines if line.amount > 0 and line.category in loose]
    used: set[int] = set()
    for debit in lines:
        if debit.amount >= 0 or debit.category not in loose:
            continue
        for credit in credits:
            if (
                credit.id not in used
                and credit.account != debit.account
                and abs(credit.amount + debit.amount) < 0.005
                and abs((credit.executed_on - debit.executed_on).days) <= PAIR_WINDOW_DAYS
            ):
                used.add(credit.id)
                for line in (debit, credit):
                    line.category, line.kind = "internal", INTERNAL
                break


def _spot_salary(db: Session, lines: list[Line]) -> None:
    """Credits nobody recognised, from a payer that pays me at least
    `SALARY_MIN_AMOUNT` in `SALARY_MIN_MONTHS` different months (over the
    whole history, not just the period shown)."""
    candidates = {line.merchant for line in lines if line.category == "other_income"}
    if not candidates:
        return
    months: dict[str, set[str]] = defaultdict(set)
    rows = db.execute(
        select(BankOperation.label, BankOperation.amount, BankOperation.executed_on).where(
            BankOperation.amount >= SALARY_MIN_AMOUNT, BankOperation.broker.is_(None)
        )
    ).all()
    for label, amount, executed_on in rows:
        found = categorize(label, amount)
        if found.category == "other_income" and found.merchant in candidates:
            months[found.merchant].add(_month(executed_on))
    payers = {name for name, seen in months.items() if len(seen) >= SALARY_MIN_MONTHS}
    for line in lines:
        if line.category == "other_income" and line.merchant in payers and line.amount >= SALARY_MIN_AMOUNT:
            line.category = "salary"


def _round(value: float) -> float:
    return round(value + 0.0, 2)


def budget_summary(db: Session, months: int = 12) -> dict:
    as_of = last_operation_date(db)
    accounts = sorted(db.execute(select(BankOperation.account).distinct()).scalars())
    if as_of is None:
        return {"as_of": None, "accounts": [], "months": [], "averages": None, "recurring": [],
                "top_merchants": [], "to_sort": []}

    first = db.execute(select(func.min(BankOperation.executed_on))).scalar()
    start = max(_month_start(as_of, months - 1), _month_start(first))
    lines = _load(db, start, as_of)
    month_end = date(as_of.year, as_of.month, calendar.monthrange(as_of.year, as_of.month)[1])

    by_month: dict[str, dict] = {}
    cursor = start
    while cursor <= as_of:
        key = _month(cursor)
        by_month[key] = {
            "month": key,
            # The month the export stops in, and the one it starts in when
            # the history does not reach its first day.
            "partial": (key == _month(as_of) and as_of < month_end) or (cursor == _month_start(first) and first.day > 1),
            "income": 0.0,
            "spending": 0.0,
            "invested": 0.0,
            "categories": defaultdict(float),
        }
        cursor = _month_start(cursor, -1)

    for line in lines:
        bucket = by_month[_month(line.executed_on)]
        if line.kind == INCOME:
            bucket["income"] += line.amount
            bucket["categories"][line.category] += line.amount
        elif line.kind == SPENDING:
            bucket["spending"] -= line.amount
            bucket["categories"][line.category] -= line.amount
        elif line.kind == INVESTMENT:
            bucket["invested"] -= line.amount

    out_months = []
    for bucket in by_month.values():
        out_months.append(
            {
                "month": bucket["month"],
                "partial": bucket["partial"],
                "income": _round(bucket["income"]),
                "spending": _round(bucket["spending"]),
                "net": _round(bucket["income"] - bucket["spending"]),
                "invested": _round(bucket["invested"]),
                "categories": {
                    name: _round(value)
                    for name, value in sorted(bucket["categories"].items(), key=lambda kv: -abs(kv[1]))
                    if abs(value) >= 0.005
                },
            }
        )

    full = [m for m in out_months if not m["partial"]]
    averages = None
    if full:
        per_category: dict[str, float] = defaultdict(float)
        for m in full:
            for name, value in m["categories"].items():
                per_category[name] += value
        averages = {
            "months": len(full),
            "income": _round(sum(m["income"] for m in full) / len(full)),
            "spending": _round(sum(m["spending"] for m in full) / len(full)),
            "net": _round(sum(m["net"] for m in full) / len(full)),
            "invested": _round(sum(m["invested"] for m in full) / len(full)),
            "categories": {
                name: _round(value / len(full))
                for name, value in sorted(per_category.items(), key=lambda kv: -abs(kv[1]))
            },
        }

    return {
        "as_of": as_of,
        "accounts": accounts,
        "months": out_months,
        "averages": averages,
        "recurring": _recurring(lines, as_of),
        "top_merchants": _top_merchants(lines, as_of - timedelta(days=90)),
        "to_sort": _top_merchants([line for line in lines if line.category == "other"], start, limit=15),
    }


def _top_merchants(lines: list[Line], since: date, limit: int = 15) -> list[dict]:
    totals: dict[str, list] = {}
    for line in lines:
        if line.kind != SPENDING or line.executed_on < since or line.amount >= 0:
            continue
        entry = totals.setdefault(line.merchant, [0.0, 0, line.category, line.executed_on])
        entry[0] -= line.amount
        entry[1] += 1
        entry[3] = max(entry[3], line.executed_on)
    ranked = sorted(totals.items(), key=lambda kv: -kv[1][0])[:limit]
    return [
        {"merchant": name, "total": _round(total), "count": count, "category": category, "last": last}
        for name, (total, count, category, last) in ranked
    ]


def _recurring(lines: list[Line], as_of: date) -> list[dict]:
    """Same merchant, similar amount, in at least `RECURRING_MIN_MONTHS` of
    the last `RECURRING_LOOKBACK` full months: subscriptions, bills, rent."""
    window = {_month(_month_start(as_of, back)) for back in range(1, RECURRING_LOOKBACK + 1)}
    if as_of.day == calendar.monthrange(as_of.year, as_of.month)[1]:
        window = {_month(_month_start(as_of, back)) for back in range(0, RECURRING_LOOKBACK)}
    seen: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    meta: dict[str, tuple[str, date]] = {}
    for line in lines:
        if line.kind != SPENDING or line.amount >= 0 or line.category in ("cash", "transfers_out"):
            continue
        key = _month(line.executed_on)
        if key not in window and key != _month(as_of):
            continue
        if key in window:
            seen[line.merchant][key] -= line.amount
        previous = meta.get(line.merchant)
        meta[line.merchant] = (line.category, max(previous[1], line.executed_on) if previous else line.executed_on)
    out = []
    for name, per_month in seen.items():
        if len(per_month) < RECURRING_MIN_MONTHS:
            continue
        typical = median(per_month.values())
        if typical <= 0 or any(abs(v - typical) > RECURRING_TOLERANCE * typical for v in per_month.values()):
            continue
        category, last = meta[name]
        out.append({"merchant": name, "monthly": _round(typical), "category": category,
                    "months": len(per_month), "last": last})
    return sorted(out, key=lambda r: -r["monthly"])


def budget_operations(
    db: Session, days: int = 90, category: str | None = None, account: str | None = None
) -> dict:
    as_of = last_operation_date(db)
    if as_of is None:
        return {"as_of": None, "since": None, "operations": []}
    since = as_of - timedelta(days=days - 1)
    lines = _load(db, since, as_of)
    if category:
        lines = [line for line in lines if line.category == category]
    if account:
        lines = [line for line in lines if line.account == account]
    return {
        "as_of": as_of,
        "since": since,
        "operations": [
            {
                "id": line.id,
                "date": line.executed_on,
                "account": line.account,
                "merchant": line.merchant,
                "category": line.category,
                "kind": line.kind,
                "amount": line.amount,
                "currency": line.currency,
            }
            for line in reversed(lines)
        ],
    }


CATEGORIES = sorted(CATEGORY_KIND)
