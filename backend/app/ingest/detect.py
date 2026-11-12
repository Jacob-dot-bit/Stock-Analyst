"""Recognise which broker export a file is from its content, so a single
upload slot can take any of them.

Six files are supported, and each one has an unambiguous signature:

- Mintos quarterly "Periodic statement" — a PDF mentioning Mintos;
- Amundi ESR annual statement — a PDF mentioning Amundi;
- Amundi "Synthese" — an .xlsb (a zip holding ``xl/workbook.bin``);
- Mintos "My investments" — a sheet whose header has ``Montant investi``;
- Mintos account statement — a sheet or csv whose header has
  ``Mouvement`` and ``Type de paiement``;
- XTB xStation report — any other .xlsx/.csv. Its tables do not start on
  the first row, so it is the fallback and its own parser says whether it
  found anything.

The filename is never used to decide: Mintos already changed its naming
once, and a renamed file is still the same export.
"""

from __future__ import annotations

import csv
import io
import zipfile
from enum import Enum

import openpyxl
import pdfplumber


class FileKind(str, Enum):
    XTB = "xtb"
    MINTOS_STATEMENT = "mintos_statement"
    MINTOS_INVESTMENTS = "mintos_investments"
    MINTOS_ACCOUNT_STATEMENT = "mintos_account_statement"
    AMUNDI_STATEMENT = "amundi_statement"
    AMUNDI_SYNTHESE = "amundi_synthese"

    @property
    def broker(self) -> str:
        return self.value.split("_", 1)[0]


_INVESTMENTS_COLUMN = "Montant investi"
_AMUNDI_PDF_HINTS = ("amundi", "épargne salariale", "epargne salariale", "perco", "relevé annuel de situation")
_ACCOUNT_STATEMENT_COLUMNS = {"Mouvement", "Type de paiement"}


def _classify_header(header: list[str]) -> FileKind:
    if _INVESTMENTS_COLUMN in header:
        return FileKind.MINTOS_INVESTMENTS
    if _ACCOUNT_STATEMENT_COLUMNS <= set(header):
        return FileKind.MINTOS_ACCOUNT_STATEMENT
    return FileKind.XTB


def _pdf_kind(content: bytes) -> FileKind | None:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = " ".join((page.extract_text() or "") for page in pdf.pages[:2]).lower()
    if "mintos" in text:
        return FileKind.MINTOS_STATEMENT
    if any(hint in text for hint in _AMUNDI_PDF_HINTS):
        return FileKind.AMUNDI_STATEMENT
    return None


def _zip_kind(content: bytes) -> FileKind | None:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
    if "xl/workbook.bin" in names:
        return FileKind.AMUNDI_SYNTHESE
    if "xl/workbook.xml" not in names:
        return None
    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        first = next(workbook.worksheets[0].iter_rows(max_row=1, values_only=True), ())
    finally:
        workbook.close()
    return _classify_header([str(cell).strip() if cell is not None else "" for cell in first])


def _text_kind(content: bytes) -> FileKind | None:
    head = content[: 64 * 1024].decode("utf-8-sig", errors="replace")
    row = next(csv.reader(head.splitlines()[:1]), [])
    return _classify_header([cell.strip() for cell in row])


def detect_file(content: bytes) -> FileKind | None:
    """None when the file is none of the six — the caller says so rather
    than guessing."""
    try:
        if content.startswith(b"%PDF"):
            return _pdf_kind(content)
        if content.startswith(b"PK"):
            return _zip_kind(content)
        if b"\x00" in content[:1024]:
            return None
        return _text_kind(content)
    except Exception:  # noqa: BLE001 - an unreadable file is simply "not recognised"
        return None
