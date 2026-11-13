"""Shared cell readers: what the bank and Mintos parsers now get from them
on top of what the XTB tests already cover."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.ingest.cells import cell_date, parse_number


class TestParseNumber:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1 234,56", 1234.56),  # narrow no-break space (French exports)
            ("1\xa0234,56", 1234.56),
            ("-12,50", -12.5),
            ("-0.0123", -0.0123),
            (42, 42.0),
        ],
    )
    def test_cells_from_bank_and_mintos(self, raw, expected):
        assert parse_number(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", [None, "", "  ", "n/a", True])
    def test_not_a_number(self, raw):
        assert parse_number(raw) is None


class TestCellDate:
    def test_typed_cells_pass_through(self):
        assert cell_date(datetime(2025, 1, 1, 10, 0)) == date(2025, 1, 1)
        assert cell_date(date(2025, 1, 1)) == date(2025, 1, 1)

    @pytest.mark.parametrize(
        "raw",
        ["2025-01-01 10:00:00", "2025-01-01", "01/01/2025", "2025-01-01T10:00:00+02:00", " 2025-01-01 "],
    )
    def test_text_cells(self, raw):
        assert cell_date(raw) == date(2025, 1, 1)

    @pytest.mark.parametrize("raw", [None, "", "pas une date", 12.5])
    def test_not_a_date(self, raw):
        assert cell_date(raw) is None
