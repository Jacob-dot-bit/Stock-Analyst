"""The shared file readers behind every import parser."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import openpyxl

from app.ingest.readers import (
    header_cells,
    looks_like_xlsx,
    text_rows,
    xlsb_sheet,
    xlsb_sheet_names,
    xlsx_first_sheet,
    xlsx_sheets,
)


def _xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        worksheet = workbook.create_sheet(title)
        for row in rows:
            worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _fake_xlsb(sheets: dict[str, list[list[object]]]) -> MagicMock:
    def get_sheet(name: str) -> MagicMock:
        sheet = MagicMock()
        sheet.rows.return_value = [[MagicMock(v=v) for v in row] for row in sheets[name]]
        sheet.__enter__ = MagicMock(return_value=sheet)
        sheet.__exit__ = MagicMock(return_value=False)
        return sheet

    workbook = MagicMock()
    workbook.sheets = list(sheets)
    workbook.get_sheet.side_effect = get_sheet
    workbook.__enter__ = MagicMock(return_value=workbook)
    workbook.__exit__ = MagicMock(return_value=False)
    return workbook


class TestXlsx:
    def test_every_sheet_in_order(self):
        content = _xlsx({"Résumé": [["a", 1]], "Détail": [["b", 2], ["c", 3]]})

        sheets = xlsx_sheets(content)

        assert list(sheets) == ["Résumé", "Détail"]
        assert sheets["Détail"] == [["b", 2], ["c", 3]]

    def test_full_mode_reads_the_same_rows(self):
        content = _xlsx({"Feuille": [["x", 1.5]]})

        assert xlsx_sheets(content, trust_dimensions=False) == {"Feuille": [["x", 1.5]]}

    def test_first_sheet_can_stop_early(self):
        content = _xlsx({"Un": [["h"], ["1"], ["2"]], "Deux": [["autre"]]})

        assert xlsx_first_sheet(content) == [["h"], ["1"], ["2"]]
        assert xlsx_first_sheet(content, max_row=1) == [["h"]]

    def test_recognised_by_extension_or_magic_bytes(self):
        assert looks_like_xlsx(b"", "releve.XLSX")
        assert looks_like_xlsx(b"PK\x03\x04", "releve")
        assert not looks_like_xlsx(b"Date,Montant", "releve.csv")


class TestXlsb:
    def test_named_sheet_as_plain_values(self):
        fake = _fake_xlsb({"Donnees": [["ignored"]], "OpeJournal": [["h1", "h2"], [1.0, "x"]]})
        with patch("app.ingest.readers.open_xlsb", return_value=fake):
            assert xlsb_sheet(b"fake", "OpeJournal") == [["h1", "h2"], [1.0, "x"]]

    def test_missing_sheet_is_none(self):
        fake = _fake_xlsb({"Donnees": [["ignored"]]})
        with patch("app.ingest.readers.open_xlsb", return_value=fake):
            assert xlsb_sheet(b"fake", "OpeJournal") is None
            assert xlsb_sheet_names(b"fake") == ["Donnees"]


class TestText:
    def test_comma_separated_with_bom(self):
        content = "﻿Date,Mouvement\n2025-01-01,12.5\n".encode()

        assert text_rows(content) == [["Date", "Mouvement"], ["2025-01-01", "12.5"]]

    def test_semicolons_are_sniffed(self):
        content = b"Symbol;Volume\nAAPL.US;1,5\n"

        assert text_rows(content, sniff_delimiter=True) == [["Symbol", "Volume"], ["AAPL.US", "1,5"]]

    def test_strict_decoding_by_default(self):
        content = b"Date\n\xff\n"

        try:
            text_rows(content)
        except UnicodeDecodeError:
            pass
        else:  # pragma: no cover - the assertion is the point
            raise AssertionError("expected a decode error")
        assert text_rows(content, errors="replace")[1] == ["�"]


def test_header_cells_are_trimmed_strings():
    assert header_cells((" Date ", None, 3)) == ["Date", "", "3"]
    assert header_cells(None) == []
