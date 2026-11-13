"""Recognise which broker export a file is from its content, so a single
upload slot can take any of them.

Nine files are supported, and each one has an unambiguous signature:

- Mintos quarterly "Periodic statement" — a PDF mentioning Mintos;
- Amundi ESR annual statement — a PDF mentioning Amundi;
- Amundi "Synthese" — an .xlsb (a zip holding ``xl/workbook.bin``) with a
  ``Mes avoirs par échéance`` sheet;
- Amundi operations journal — an .xlsb with an ``OpeJournal`` sheet;
- Mintos "My investments" — a sheet whose header has ``Montant investi``;
- Mintos account statement — a sheet or csv whose header has
  ``Mouvement`` and ``Type de paiement``;
- income tax notice from impots.gouv.fr — a PDF titled "Impôt sur les
  revenus de <year>" that gives a "Revenu fiscal de référence";
- bank "Vos comptes" export (Monabanq and the rest of the Crédit Mutuel
  group) — an .xlsx whose first cell is ``Votre situation financière au``;
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

import pdfplumber

from app.ingest.amundi_operations_import import SHEET_NAME as _AMUNDI_OPERATIONS_SHEET
from app.ingest.amundi_synthese_import import _SHEET_NAME as _AMUNDI_SYNTHESE_SHEET
from app.ingest.bank_import import looks_like_bank_export
from app.ingest.tax_notice_import import looks_like_tax_notice
from app.ingest.readers import header_cells, xlsb_sheet_names, xlsx_first_sheet


class FileKind(str, Enum):
    XTB = "xtb"
    MINTOS_STATEMENT = "mintos_statement"
    MINTOS_INVESTMENTS = "mintos_investments"
    MINTOS_ACCOUNT_STATEMENT = "mintos_account_statement"
    AMUNDI_STATEMENT = "amundi_statement"
    AMUNDI_SYNTHESE = "amundi_synthese"
    AMUNDI_OPERATIONS = "amundi_operations"
    BANK_STATEMENT = "bank_statement"
    TAX_NOTICE = "tax_notice"

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
    # First: a notice mentions savings plans, never a broker by name.
    if looks_like_tax_notice(text):
        return FileKind.TAX_NOTICE
    if "mintos" in text:
        return FileKind.MINTOS_STATEMENT
    if any(hint in text for hint in _AMUNDI_PDF_HINTS):
        return FileKind.AMUNDI_STATEMENT
    return None


def _zip_kind(content: bytes) -> FileKind | None:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
    if "xl/workbook.bin" in names:
        sheets = set(xlsb_sheet_names(content))
        if _AMUNDI_OPERATIONS_SHEET in sheets:
            return FileKind.AMUNDI_OPERATIONS
        if _AMUNDI_SYNTHESE_SHEET in sheets:
            return FileKind.AMUNDI_SYNTHESE
        return None
    if "xl/workbook.xml" not in names:
        return None
    first = next(iter(xlsx_first_sheet(content, max_row=1)), [])
    if first and looks_like_bank_export(first[0]):
        return FileKind.BANK_STATEMENT
    return _classify_header(header_cells(first))


def _text_kind(content: bytes) -> FileKind | None:
    head = content[: 64 * 1024].decode("utf-8-sig", errors="replace")
    row = next(csv.reader(head.splitlines()[:1]), [])
    return _classify_header([cell.strip() for cell in row])


def detect_file(content: bytes) -> FileKind | None:
    """None when the file is none of the eight — the caller says so rather
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
