"""Parser for Amundi ESR's operations journal —
``ExportOperations-DD_MM_YYYY-DD_MM_YYYY.xlsb``, from the portal's
"Mes opérations" page.

Unlike the "Synthese" export (`amundi_synthese_import.py`, current holdings
only) and the annual PDF (one gain figure per fund, once a year), this file
lists every individual operation over the chosen period: voluntary
payments, employer match (abondement), profit-sharing, arbitrages and
reallocations between funds, capitalised dividends and fees. Summing what
went into each fund gives its real cost basis, so its gain no longer has to
be estimated.

Real structure observed on a 2026-11-12 export (46 operations, May 2023 to
November 2026): three sheets. `Donnees` holds the account holder's identity
and address — never read here. `Page1` is the printable layout.
`OpeJournal` is the raw table: row 0 numbers the columns, row 1 has the
portal's internal field names (``instDateComptabilisation``,
``instNomFonds``, ``instEchMontantBrut``...), data from row 2. Dates are
Excel serial numbers. Each operation on a fund is one row, and a payment
with employer match is two rows (origin ``VV`` then ``ABD``). See DEVLOG
"Step 3u.88".
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, timedelta

from pyxlsb import open_workbook

from app.ingest.amundi_synthese_import import _account_for_dispositif
from app.messages import Message, MessageCode, SectionKind, SectionSummary

SHEET_NAME = "OpeJournal"

_EXCEL_EPOCH = date(1899, 12, 30)

_FIELD_DATE = "instDateComptabilisation"
_FIELD_LABEL = "opeIndLibelleCommunication"
_FIELD_ORIGIN = "instOrigineAvoirs"
_FIELD_DISPOSITIF = "instNomDispositif"
_FIELD_FUND = "instNomFonds"
_FIELD_NAV = "instVlReel"
_FIELD_UNITS = "instEchNombreDeParts"
_FIELD_AMOUNT = "instEchMontantBrut"
_FIELD_TYPE = "opeColType"
_FIELD_SUBTYPE = "opeColSousType"
_REQUIRED = (_FIELD_DATE, _FIELD_DISPOSITIF, _FIELD_FUND, _FIELD_UNITS, _FIELD_AMOUNT, _FIELD_TYPE)


@dataclass
class AmundiOperation:
    executed_on: date
    account: str  # "Amundi PEG" | "Amundi PERCO"
    dispositif: str
    fund: str
    label: str
    origin: str | None
    op_type: str  # SOUS, ARB, OST, RACH...
    op_subtype: str | None
    nav: float | None
    units: float
    amount: float


@dataclass
class ParsedAmundiOperations:
    operations: list[AmundiOperation] = field(default_factory=list)
    warnings: list[Message] = field(default_factory=list)
    sections: list[SectionSummary] = field(default_factory=list)
    source_rows: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.operations


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _read_rows(rows: list[list], result: ParsedAmundiOperations) -> None:
    header_index = next((i for i, row in enumerate(rows[:10]) if _FIELD_DATE in row), None)
    if header_index is None or not all(name in rows[header_index] for name in _REQUIRED):
        result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
        return
    header = rows[header_index]
    col = {name: header.index(name) for name in header if isinstance(name, str)}

    def cell(row: list, name: str) -> object:
        index = col.get(name)
        return row[index] if index is not None and index < len(row) else None

    data_rows = rows[header_index + 1 :]
    for row in data_rows:
        serial = cell(row, _FIELD_DATE)
        units = cell(row, _FIELD_UNITS)
        amount = cell(row, _FIELD_AMOUNT)
        dispositif = _text(cell(row, _FIELD_DISPOSITIF))
        fund = _text(cell(row, _FIELD_FUND))
        op_type = _text(cell(row, _FIELD_TYPE))
        # Trailing blank rows, or anything not shaped like an operation.
        if not isinstance(serial, (int, float)) or not dispositif or not fund or not op_type:
            continue
        if not isinstance(units, (int, float)) or not isinstance(amount, (int, float)):
            continue
        nav = cell(row, _FIELD_NAV)
        result.operations.append(
            AmundiOperation(
                executed_on=_EXCEL_EPOCH + timedelta(days=int(serial)),
                account=_account_for_dispositif(dispositif),
                dispositif=dispositif,
                fund=fund,
                label=_text(cell(row, _FIELD_LABEL)) or "",
                origin=_text(cell(row, _FIELD_ORIGIN)),
                op_type=op_type,
                op_subtype=_text(cell(row, _FIELD_SUBTYPE)),
                nav=float(nav) if isinstance(nav, (int, float)) else None,
                units=float(units),
                amount=round(float(amount), 2),
            )
        )

    result.source_rows = len(data_rows)


def parse_amundi_operations_export(content: bytes, filename: str) -> ParsedAmundiOperations:
    try:
        with open_workbook(io.BytesIO(content)) as wb:
            if SHEET_NAME not in wb.sheets:
                return ParsedAmundiOperations(warnings=[Message(MessageCode.NO_TABLE_RECOGNISED)])
            with wb.get_sheet(SHEET_NAME) as sheet:
                rows = [[cell.v for cell in row] for row in sheet.rows()]
    except Exception as exc:  # noqa: BLE001 - surfaced as a warning, not a crash
        return ParsedAmundiOperations(warnings=[Message(MessageCode.FILE_UNREADABLE, {"error": str(exc)})])
    return parse_operations_rows(rows)


def parse_operations_rows(rows: list[list]) -> ParsedAmundiOperations:
    """The `OpeJournal` table, already read into plain lists. Public so tests
    can feed rows directly: no library writes .xlsb files."""
    result = ParsedAmundiOperations()
    _read_rows(rows, result)
    if result.warnings:
        return result

    if not result.operations:
        result.warnings.append(Message(MessageCode.NOTHING_IMPORTABLE))
        return result

    result.operations.sort(key=lambda op: op.executed_on)
    result.sections.append(
        SectionSummary(
            sheet=SHEET_NAME,
            kind=SectionKind.CASH_OPERATIONS,
            count=len(result.operations),
            source_rows=result.source_rows,
        )
    )
    return result


def counts_toward_cost(op_type: str, op_subtype: str | None) -> bool:
    """Whether an operation's amount is money put into (or taken out of) a
    fund, as opposed to a result of holding it.

    - ``SOUS`` (payments, employer match, profit-sharing): money in.
    - ``ARB`` (arbitrage, reallocation): money moved between funds — out of
      one at its value that day, into another. The source fund's gain up to
      then is realised and no longer shows; the destination's cost is what
      actually arrived in it.
    - ``RACH`` (redemption): money out, except fees (``NPAI``, charged for
      an invalid postal address), which are a loss, not a withdrawal — they
      stay out of the cost so the gain reflects them.
    - ``OST`` (capitalised dividends, readjustments): what holding the fund
      produced, never new money.
    """
    if op_type in {"SOUS", "ARB"}:
        return True
    if op_type == "RACH":
        return op_subtype != "NPAI"
    return False
