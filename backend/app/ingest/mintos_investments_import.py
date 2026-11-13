"""Parser for Mintos's "Investments" .xlsx export — a live, point-in-time
snapshot of every active loan-note fragment ("My investments" page),
distinct from the quarterly "Periodic statement of Financial instruments"
PDF (see `mintos_import.py`'s module docstring), which only reports the
Mintos Core portfolio's opening/closing balance once per calendar quarter
— weeks or months stale by the time it gets imported.

Real structure observed on a 2026-09-08 export: one row per active note
fragment (several hundred rows for the account this was built against),
no "as of" date inside the file's own content — the filename
(``Investments-DD-MM-YYYY.xlsx``, day-month-year, Mintos's own download
naming convention) is the only date signal this format carries.

Live cross-checked the same day against the account's real total, as
reported directly by the user from the Mintos site: summing
this file's ``Montant investi`` column matches closely — the small
remaining gap explained by interest/repayments settling continuously
between the two observations, not a wrong column. ``Principal restant``
(the outstanding note balance net of amortization already received) was
checked too and does *not* match — evidently some narrower
figure than "this investment's current value" — deliberately left unused.
See DEVLOG "Decision 3u.43".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.ingest.readers import header_cells, xlsx_first_sheet
from app.messages import Message, MessageCode

#: ``Investments-08-09-2026.xlsx`` (day-month-year, the 2026-09 naming).
_FILENAME_DMY_RE = re.compile(r"(?<!\d)(\d{2})-(\d{2})-(\d{4})(?!\d)")
#: ``20261112-...xlsx`` or ``2026-11-12...`` — the year-first prefix Mintos
#: already uses for the account statement (``20260908-account-statement.csv``).
#: Accepted here too so a site-side rename doesn't block the import again.
_FILENAME_YMD_RE = re.compile(r"(?<!\d)(\d{4})-?(\d{2})-?(\d{2})(?!\d)")

_VALUE_COLUMN = "Montant investi"

#: Columns of the "account-statement" export (every transaction, see
#: `mintos_transactions_import.py`). Both exports are .xlsx and sit next to
#: each other on the Mintos site, so picking the wrong one is easy — this
#: lets the import say so instead of a generic "no table recognised".
_ACCOUNT_STATEMENT_COLUMNS = {"Mouvement", "Type de paiement", "Turnover", "Payment Type"}


@dataclass
class ParsedMintosInvestmentsSnapshot:
    as_of: date | None = None
    total_invested: float | None = None
    positions_found: int = 0
    warnings: list[Message] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.total_invested is None


def _extract_filename_date(filename: str) -> date | None:
    """``Investments-08-09-2026.xlsx`` -> 2026-09-08, ``20261112-investments.xlsx``
    -> 2026-11-12. The filename is the only "as of" signal this format
    carries — there is no date printed inside the sheet itself. Year-first
    is tried first: a run of 8 digits can't be mistaken for day-month-year,
    while the dashed form can only be read one way."""
    for pattern, order in ((_FILENAME_YMD_RE, "ymd"), (_FILENAME_DMY_RE, "dmy")):
        for match in pattern.finditer(filename):
            a, b, c = match.groups()
            year, month, day = (a, b, c) if order == "ymd" else (c, b, a)
            try:
                return date(int(year), int(month), int(day))
            except ValueError:
                continue
    return None


def parse_mintos_investments_export(content: bytes, filename: str) -> ParsedMintosInvestmentsSnapshot:
    """Sums the ``Montant investi`` column across every row of the first
    worksheet — that total is this account's current Mintos Core P2P
    portfolio value as of the filename's date. A row missing or non-numeric
    in that column is silently skipped (never crashes the whole import over
    one malformed row), and simply doesn't contribute to the total."""
    result = ParsedMintosInvestmentsSnapshot()

    try:
        header, *rows = xlsx_first_sheet(content)
    except Exception as exc:  # noqa: BLE001 - surfaced as a warning, not a crash
        result.warnings.append(Message(MessageCode.FILE_UNREADABLE, {"error": str(exc)}))
        return result

    header = header_cells(header)
    if _VALUE_COLUMN not in header:
        if _ACCOUNT_STATEMENT_COLUMNS & set(header):
            result.warnings.append(Message(MessageCode.MINTOS_ACCOUNT_STATEMENT_NOT_INVESTMENTS, {"filename": filename}))
        else:
            result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
        return result

    as_of = _extract_filename_date(filename)
    if as_of is None:
        result.warnings.append(Message(MessageCode.FILE_UNREADABLE, {"error": "no date found in filename"}))
        return result
    result.as_of = as_of

    idx = header.index(_VALUE_COLUMN)
    total = 0.0
    count = 0
    for row in rows:
        if len(row) <= idx:
            continue
        value = row[idx]
        if isinstance(value, (int, float)):
            total += value
            count += 1

    if count == 0:
        result.warnings.append(Message(MessageCode.NOTHING_IMPORTABLE))
        return result

    result.total_invested = round(total, 2)
    result.positions_found = count
    return result
