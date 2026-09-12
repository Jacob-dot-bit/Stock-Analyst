"""Parser for Mintos's full "account-statement" .csv export — every
individual transaction (interest, tax, principal, fees...) over a real
date range, unlike the quarterly "Periodic statement of Financial
instruments" PDF (`mintos_import.py`), which only reports Mintos Core's
aggregate opening/closing balance once per quarter.

Real structure observed on a 2026-09-08 export
(``Date,"ID de transaction :",Détails,Mouvement,Solde,Devise,"Type de
paiement"``, a large number of rows, 2025-01-01 through the export date): one row
per real transaction, with a running cash balance ("Solde") that DEVLOG
"Decision 3u.43" already established is *not* the portfolio's total
invested value — it is the free cash cycling through auto-invest
reinvestment, staying in the tens-to-low-thousands of euros even across
20 months of real activity on a much larger portfolio.

What this file *is* good for: a real, complete picture of income and cost
transactions — interest, bonuses, late fees received, platform fees, tax
withheld. Unlike a cost basis derived from deposits (which needs a
*complete* deposit history to be honest, and this file's own date range
is not guaranteed to be complete — see DEVLOG "Decision 3u.39"'s original
"`Investissement`/`Principal perçu` rows are internal loan-fragment
churn, not real bank deposits" ruling), summing real income/cost
transactions needs no such completeness assumption: interest earned in
this file's covered window is interest earned, full stop, regardless of
what happened before it. See DEVLOG "Decision 3u.47" for the full
reasoning and the live cross-check this was verified against (categorising
exactly these types gave a ~12-13% cumulative / ~5-6% annualised yield —
plausible for Mintos's own documented rates, the strongest evidence the
categorisation is right, not just plausible-looking).

``Paiement ETF entrant``/``Paiement sortant relatif au portefeuille
d'ETF`` rows belong to the *separate* Core ETF 90 sub-portfolio (already
tracked as real ``Transaction`` rows via the PDF importer) and are
deliberately excluded here — this parser is scoped to Mintos Core P2P
only.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime

from app.messages import Message, MessageCode

#: Real income credited to the lender, regardless of principal churn —
#: interest, bonuses, and late-payment compensation received.
_INCOME_TYPES = {
    "Intérêt perçu",
    "Intérêts perçus sur le rachat de prêt",
    "Intérêts perçus sur les paiements en attente",
    "Revenus des intérêts sur les obligations",
    "Delayed interest income on transit rebuy",
    "Revenus de décote des obligations",
    "Frais de retard perçus",
    "Bonus",
}

#: Real deductions from the lender — platform fees and withheld tax.
_COST_TYPES = {
    "Tax withholding",
    "Mintos Core fee",
    "Prélèvement à la source sur les obligations",
}

#: A deposit row's "Type de paiement" always starts with this — covers
#: both the plain "Dépôts" and a templated "Dépôt par carte %REFERENCE%,
#: après des frais de %FEE_AMOUNT% %FEE_ABBREVIATION%" seen live (Mintos's
#: own export left the placeholders unsubstituted). Captured for
#: visibility but not currently used in any gain calculation — a
#: *complete* deposit history isn't guaranteed within one file's date
#: range, the same completeness concern Decision 3u.39 raised for the
#: internal-churn figures.
_DEPOSIT_PREFIX = "Dépôt"


@dataclass
class ParsedMintosTransactionsExport:
    period_start: date | None = None
    period_end: date | None = None
    income_total: float = 0.0
    cost_total: float = 0.0
    deposits_total: float = 0.0
    transaction_count: int = 0
    warnings: list[Message] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.period_start is None or self.period_end is None

    @property
    def net_gain(self) -> float:
        return round(self.income_total + self.cost_total, 2)


def parse_mintos_transactions_export(content: bytes, filename: str) -> ParsedMintosTransactionsExport:
    result = ParsedMintosTransactionsExport()

    try:
        text = content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
    except Exception as exc:  # noqa: BLE001 - surfaced as a warning, not a crash
        result.warnings.append(Message(MessageCode.FILE_UNREADABLE, {"error": str(exc)}))
        return result

    try:
        idx_date = header.index("Date")
        idx_amount = header.index("Mouvement")
        idx_type = header.index("Type de paiement")
    except ValueError:
        result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
        return result

    earliest: date | None = None
    latest: date | None = None
    count = 0
    income_total = 0.0
    cost_total = 0.0
    deposits_total = 0.0

    for row in reader:
        if len(row) <= max(idx_date, idx_amount, idx_type):
            continue
        try:
            when = datetime.strptime(row[idx_date][:10], "%Y-%m-%d").date()
            amount = float(row[idx_amount])
        except (ValueError, IndexError):
            continue
        payment_type = row[idx_type]

        earliest = when if earliest is None or when < earliest else earliest
        latest = when if latest is None or when > latest else latest
        count += 1

        if payment_type in _INCOME_TYPES:
            income_total += amount
        elif payment_type in _COST_TYPES:
            cost_total += amount
        elif payment_type.startswith(_DEPOSIT_PREFIX):
            deposits_total += amount

    if count == 0:
        result.warnings.append(Message(MessageCode.NOTHING_IMPORTABLE))
        return result

    result.period_start = earliest
    result.period_end = latest
    result.income_total = round(income_total, 2)
    result.cost_total = round(cost_total, 2)
    result.deposits_total = round(deposits_total, 2)
    result.transaction_count = count
    return result
