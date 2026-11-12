"""Parser for the account export of the Crédit Mutuel group's online banks
(Monabanq, and the same "Vos comptes" workbook at Crédit Mutuel and CIC).

What I take from it:

* each account's **balance** on the export date — current account and
  savings book alike are cash I hold, so they belong in the portfolio
  total and the allocation;
* the **transfers to and from my brokers** (XTB, Mintos, Amundi), seen
  from the bank side: what actually left my bank account to be invested;
* **every operation** of every account (card payments, bills, salary,
  transfers), for the budget view (`app/budget/`). They go to their own
  table, never into the transaction ledger: a card payment at the bakery
  is not a portfolio event. See DEVLOG "Step 3u.92".

Structure observed on a real 2026-11-12 Monabanq export (two accounts,
three years of operations):

* sheet ``Vos comptes``: A1 is ``Votre situation financière au DD/MM/YYYY``,
  then a header ``Compte | R.I.B. | Solde | Dev`` and one row per account
  (``PRATIQ M <holder>``, ``14690 <branch> <number>``, ``<balance>``, ``EUR``);
* one sheet per account, named ``Cpt <guichet> <compte>``, with a header
  ``Date | Valeur | Libellé | Débit | Crédit | Solde | Dev`` on row 5. Debits
  are already negative. The running balance column is left empty;
* ``hidden_data`` / ``hidden``: the bank's own template bookkeeping.

The first five digits of the R.I.B. are the bank code (14690 = Monabanq).
The account number is never stored whole: the last four digits are enough
to tell two accounts apart. See DEVLOG "Step 3u.91".
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import openpyxl

from app.messages import Message, MessageCode, SectionKind, SectionSummary

SUMMARY_SHEET = "Vos comptes"
SUMMARY_TITLE_PREFIX = "Votre situation financière au"

#: Bank code (first block of the R.I.B.) → the name shown in the app.
BANK_NAMES = {
    "14690": "Monabanq",
    "10278": "Crédit Mutuel",
    "30066": "CIC",
}

#: Where a transfer went, from its label. Checked in order. The Mintos
#: investor reference (``<8 digits> - INVESTOR``) is how early transfers
#: to Mintos appear, before the bank started showing the beneficiary's name.
BROKER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("XTB", re.compile(r"\bXTB\b|XTB\.COM")),
    # Labels are cut at a fixed width: "LV RIGA CROWDCUBE MINTO", "12345678 - INVES".
    ("Mintos", re.compile(r"MINTOS?\b|MINTOS|\b\d{8} - INVES")),
    ("Amundi", re.compile(r"AMUNDI")),
)

#: Words that start the holder's name in an account label
#: (``LIVRET A M JAKUB ...``): everything before them is the product.
_HOLDER_TITLES = (" M ", " MME ", " MLLE ", " MR ", " MM ", " M. ")

_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


@dataclass
class BankAccount:
    bank: str
    product: str  # "Pratiq", "Livret A"
    bank_code: str
    number_tail: str  # last four digits of the account number
    sheet: str  # "Cpt <branch> <number>"
    balance: float
    currency: str
    #: Oldest operation in the export: shown as "since" on the position.
    first_operation: date | None = None

    @property
    def label(self) -> str:
        """The `account` value stored on positions and transactions."""
        return f"{self.bank} {self.product}"[:40]

    @property
    def symbol(self) -> str:
        slug = re.sub(r"[^A-Z0-9]+", "-", f"{self.bank} {self.product}".upper()).strip("-")
        return f"{slug}-{self.number_tail}"


@dataclass
class BrokerTransfer:
    executed_on: date
    value_date: date | None
    account: BankAccount
    broker: str
    label: str
    #: Bank side: negative when money left for the broker, positive when it came back.
    amount: float

    @property
    def kind(self) -> str:
        """``deposit`` (sent to the broker), ``withdrawal`` (money back from
        it), or ``payout``: profit-sharing or an incentive bonus Amundi pays
        straight to the bank. A payout never was my money in the plan, so it
        does not reduce what I put in."""
        upper = self.label.upper()
        if self.amount > 0 and ("PARTICIPATION" in upper or "INTERESSEMENT" in upper):
            return "payout"
        return "deposit" if self.amount < 0 else "withdrawal"


@dataclass
class BankLine:
    """One operation of an account sheet, whatever it is."""

    executed_on: date
    value_date: date | None
    account: BankAccount
    label: str
    #: Signed: negative = money out of the account.
    amount: float
    #: The broker this line went to or came from, when it is one.
    broker: str | None = None
    #: A transfer between two of my own accounts (its label names me, or a
    #: savings book). Never spending nor income.
    own_transfer: bool = False


@dataclass
class ParsedBankExport:
    as_of: date | None = None
    accounts: list[BankAccount] = field(default_factory=list)
    transfers: list[BrokerTransfer] = field(default_factory=list)
    operations: list[BankLine] = field(default_factory=list)
    #: The account holder's name as written in the account labels, upper
    #: case. Used to recognise transfers between my own accounts; never stored.
    holders: set[str] = field(default_factory=set)
    operations_read: int = 0
    warnings: list[Message] = field(default_factory=list)
    sections: list[SectionSummary] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.accounts


def looks_like_bank_export(first_cell: object) -> bool:
    return isinstance(first_cell, str) and first_cell.strip().startswith(SUMMARY_TITLE_PREFIX)


def broker_of(label: str) -> str | None:
    upper = label.upper()
    for broker, pattern in BROKER_PATTERNS:
        if pattern.search(upper):
            return broker
    return None


def _holder(label: str) -> str | None:
    """``PRATIQ M JEAN EXEMPLE`` → ``JEAN EXEMPLE``."""
    padded = f" {label.strip().upper()} "
    cuts = [(padded.find(title), title) for title in _HOLDER_TITLES if padded.find(title) > 0]
    if not cuts:
        return None
    position, title = min(cuts)
    name = padded[position + len(title) :].strip()
    return name or None


#: Savings books: a transfer naming one is money moving between my accounts.
_OWN_ACCOUNT_RE = re.compile(r"\bLIVRET\b|\bLDDS?\b|\bLEP\b|\bCEL\b|\bPEL\b")


def is_own_transfer(label: str, holders: set[str]) -> bool:
    upper = label.upper()
    if not re.match(r"\s*(VIR|VIREMENT)\b", upper):
        return False
    if _OWN_ACCOUNT_RE.search(upper):
        return True
    return any(holder and holder in upper for holder in holders)


def _product(label: str) -> str:
    padded = f" {label.strip()} "
    cut = min((padded.find(title) for title in _HOLDER_TITLES if padded.find(title) > 0), default=-1)
    product = padded[:cut].strip() if cut > 0 else label.strip()
    # "PRATIQ" → "Pratiq", "LIVRET A" → "Livret A"
    return " ".join(word.capitalize() if len(word) > 1 else word for word in product.split())


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        match = _DATE_RE.search(value)
        if match:
            day, month, year = (int(part) for part in match.groups())
            return date(year, month, day)
    return None


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.replace(" ", "").replace(" ", "").replace(",", "."))
        except ValueError:
            return None
    return None


def _read_accounts(rows: list[tuple], result: ParsedBankExport) -> None:
    header_index = next(
        (i for i, row in enumerate(rows[:10]) if row and row[0] == "Compte" and "Solde" in row), None
    )
    if header_index is None:
        result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
        return
    header = list(rows[header_index])
    col_rib, col_balance = header.index("R.I.B."), header.index("Solde")
    col_currency = header.index("Dev") if "Dev" in header else None

    for row in rows[header_index + 1 :]:
        if not row or not row[0]:
            break
        rib = str(row[col_rib] or "").split()
        balance = _number(row[col_balance])
        if len(rib) < 3 or balance is None:
            continue
        bank_code, branch, number = rib[0], rib[1], rib[2]
        holder = _holder(str(row[0]))
        if holder:
            result.holders.add(holder)
        result.accounts.append(
            BankAccount(
                bank=BANK_NAMES.get(bank_code, f"Banque {bank_code}"),
                product=_product(str(row[0])),
                bank_code=bank_code,
                number_tail=number[-4:],
                sheet=f"Cpt {branch} {number}",
                balance=round(balance, 2),
                currency=str(row[col_currency] or "EUR").strip() if col_currency is not None else "EUR",
            )
        )


def _read_operations(rows: list[tuple], account: BankAccount, result: ParsedBankExport) -> int:
    header_index = next(
        (i for i, row in enumerate(rows[:15]) if row and row[0] == "Date" and "Libellé" in row), None
    )
    if header_index is None:
        result.warnings.append(Message(MessageCode.UNMAPPED_COLUMNS, {"sheet": account.sheet, "columns": "—"}))
        return 0
    header = list(rows[header_index])
    col = {name: header.index(name) for name in ("Date", "Valeur", "Libellé", "Débit", "Crédit") if name in header}

    count = 0
    for row in rows[header_index + 1 :]:
        executed_on = _parse_date(row[col["Date"]]) if row else None
        if executed_on is None:
            continue  # blank rows, then the closing "Solde au ..." line
        count += 1
        if account.first_operation is None or executed_on < account.first_operation:
            account.first_operation = executed_on
        label = str(row[col["Libellé"]] or "").strip()
        debit = _number(row[col["Débit"]]) if "Débit" in col else None
        credit = _number(row[col["Crédit"]]) if "Crédit" in col else None
        amount = round((credit or 0.0) - abs(debit or 0.0), 2)
        if not amount:
            continue
        value_date = _parse_date(row[col["Valeur"]]) if "Valeur" in col else None
        broker = broker_of(label)
        result.operations.append(
            BankLine(
                executed_on=executed_on,
                value_date=value_date,
                account=account,
                label=label,
                amount=amount,
                broker=broker,
                own_transfer=broker is None and is_own_transfer(label, result.holders),
            )
        )
        if broker is None:
            continue
        result.transfers.append(
            BrokerTransfer(
                executed_on=executed_on,
                value_date=value_date,
                account=account,
                broker=broker,
                label=label,
                amount=round(amount, 2),
            )
        )
    return count


def parse_bank_export(content: bytes, filename: str) -> ParsedBankExport:
    result = ParsedBankExport()
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - surfaced as a warning, not a crash
        result.warnings.append(Message(MessageCode.FILE_UNREADABLE, {"error": str(exc)}))
        return result
    try:
        if SUMMARY_SHEET not in workbook.sheetnames:
            result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
            return result
        summary = list(workbook[SUMMARY_SHEET].iter_rows(max_row=50, values_only=True))
        if not summary or not looks_like_bank_export(summary[0][0] if summary[0] else None):
            result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
            return result
        result.as_of = _parse_date(summary[0][0])
        _read_accounts(summary, result)
        result.sections.append(
            SectionSummary(
                sheet=SUMMARY_SHEET,
                kind=SectionKind.OPEN_POSITIONS,
                count=len(result.accounts),
                source_rows=len(result.accounts),
            )
        )

        for account in result.accounts:
            if account.sheet not in workbook.sheetnames:
                continue
            rows = list(workbook[account.sheet].iter_rows(values_only=True))
            before = len(result.transfers)
            read = _read_operations(rows, account, result)
            result.operations_read += read
            result.sections.append(
                SectionSummary(
                    sheet=account.sheet,
                    kind=SectionKind.CASH_OPERATIONS,
                    count=len(result.transfers) - before,
                    source_rows=read,
                )
            )
    finally:
        workbook.close()

    if result.as_of is None and result.accounts:
        result.as_of = date.today()
    if not result.accounts and not result.warnings:
        result.warnings.append(Message(MessageCode.NOTHING_IMPORTABLE))
    result.transfers.sort(key=lambda t: t.executed_on)
    result.operations.sort(key=lambda o: o.executed_on)
    return result
