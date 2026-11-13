"""Shared file readers for the import parsers.

Every export reaches the app as raw bytes in one of three shapes: an .xlsx
workbook (XTB, Mintos, Monabanq), an .xlsb workbook (Amundi) or delimited
text (XTB, Mintos). Each parser used to open them its own way; these helpers
only turn the bytes into plain lists of cell values. What a row *means*
(columns, kinds, dedup ids) stays in each parser.

Errors are left to raise: every parser already wraps the read in a
``try`` that turns any failure into a ``FILE_UNREADABLE`` warning.
"""

from __future__ import annotations

import csv
import io
from typing import Any

import openpyxl
from pyxlsb import open_workbook as open_xlsb

Rows = list[list[Any]]


def looks_like_xlsx(content: bytes, filename: str) -> bool:
    """An .xlsx is a zip archive; checking the magic bytes too covers a file
    renamed (or saved by a browser) without its extension."""
    return filename.lower().endswith((".xlsx", ".xlsm")) or content[:2] == b"PK"


def xlsx_sheets(content: bytes, *, trust_dimensions: bool = True) -> dict[str, Rows]:
    """Every worksheet, in workbook order, as ``{title: rows}``.

    ``trust_dimensions=False`` opens the workbook in full mode: some exports
    (XTB) declare a wrong ``A1:A1`` dimension, which read-only mode trusts,
    making the sheet look empty."""
    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=trust_dimensions, data_only=True)
    try:
        return {
            worksheet.title: [list(row) for row in worksheet.iter_rows(values_only=True)]
            for worksheet in workbook.worksheets
        }
    finally:
        workbook.close()


def xlsx_first_sheet(content: bytes, *, max_row: int | None = None) -> Rows:
    """The first worksheet only, optionally cut at ``max_row`` rows."""
    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        return [list(row) for row in workbook.worksheets[0].iter_rows(max_row=max_row, values_only=True)]
    finally:
        workbook.close()


def xlsb_sheet_names(content: bytes) -> list[str]:
    with open_xlsb(io.BytesIO(content)) as workbook:
        return list(workbook.sheets)


def xlsb_sheet(content: bytes, name: str) -> Rows | None:
    """One sheet of an .xlsb workbook, or ``None`` when it has no such sheet."""
    with open_xlsb(io.BytesIO(content)) as workbook:
        if name not in workbook.sheets:
            return None
        with workbook.get_sheet(name) as sheet:
            return [[cell.v for cell in row] for row in sheet.rows()]


def text_rows(content: bytes, *, sniff_delimiter: bool = False, errors: str = "strict") -> Rows:
    """Delimited text (BOM tolerated). Comma-separated unless
    ``sniff_delimiter`` asks to guess between ``; , tab |``."""
    text = content.decode("utf-8-sig", errors=errors)
    delimiter = ","
    if sniff_delimiter:
        sample = text[:4096]
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
        except csv.Error:
            delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def header_cells(row: Any) -> list[str]:
    """A header row as trimmed strings, empty cells as ``""``."""
    return [str(cell).strip() if cell is not None else "" for cell in (row or ())]
