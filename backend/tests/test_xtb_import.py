"""Tests for the xStation export parser."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.ingest.xtb_import import (
    classify_cash_type,
    is_total_row,
    parse_datetime,
    parse_number,
    parse_xtb_export,
)
from app.messages import MessageCode, SectionKind
from app.models import TxType
from tests.conftest import CASH_HEADERS, OPEN_HEADERS, build_workbook, build_xtb_workbook


def codes(result) -> list[str]:
    """Message codes emitted by a parse, in order.

    Tests assert on codes rather than sentences: the API is language-neutral, so
    there is no prose to match against.
    """
    return [warning.code for warning in result.warnings]


class TestParseNumber:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (1234.56, 1234.56),
            ("1234.56", 1234.56),
            ("1 234,56", 1234.56),  # French, with a thousands space
            ("1\xa0234,56", 1234.56),  # non-breaking space, common in exports
            ("1,234.56", 1234.56),  # English
            ("1,234", 1234.0),  # comma as thousands separator
            ("12,5", 12.5),  # comma as decimal separator
            ("-58,70", -58.70),
            ("(1 234,56)", -1234.56),  # accounting notation
            ("0,00", 0.0),
            ("", None),
            (None, None),
            ("n/a", None),
        ],
    )
    def test_formats(self, raw, expected):
        assert parse_number(raw) == expected

    def test_currency_symbol_is_stripped(self):
        assert parse_number("1 234,56 EUR") == 1234.56

    def test_boolean_is_not_a_number(self):
        assert parse_number(True) is None


class TestParseDatetime:
    @pytest.mark.parametrize(
        "raw",
        [
            "2025-02-25 18:05:02.266000",  # the real XTB export format
            "2025-02-25 18:05:02",
            "12.01.2024 10:30:00",
            "12/01/2024 10:30",
            "12.01.2024",
        ],
    )
    def test_known_formats(self, raw):
        assert parse_datetime(raw) is not None

    def test_passthrough_datetime(self):
        moment = datetime(2024, 1, 12, 10, 30)
        assert parse_datetime(moment) is moment

    def test_unknown_format_returns_none(self):
        assert parse_datetime("pas une date") is None


class TestClassifyCashType:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            # Labels observed in real exports
            ("Dividend", TxType.DIVIDEND),
            ("Dividend equivalent", TxType.DIVIDEND),
            ("Withholding tax", TxType.TAX),
            ("Stamp duty", TxType.TAX),
            ("Tax IFTT", TxType.TAX),
            ("SEC fee", TxType.FEE),
            ("Adjustment fee", TxType.FEE),
            ("Swap", TxType.FEE),
            ("Rollover", TxType.FEE),
            ("Stock purchase", TxType.BUY),
            ("Stock sell", TxType.SELL),
            ("Free funds interest", TxType.INTEREST),
            ("Deposit", TxType.DEPOSIT),
            ("PEA deposit", TxType.DEPOSIT),
            ("Withdrawal", TxType.WITHDRAWAL),
            ("Close trade", TxType.CLOSED_TRADE),
            ("Correction", TxType.OTHER),
            ("Fractional shares", TxType.OTHER),
            # French
            ("Dividende", TxType.DIVIDEND),
            ("Retrait", TxType.WITHDRAWAL),
        ],
    )
    def test_keywords(self, label, expected):
        assert classify_cash_type(label) == expected

    def test_interest_tax_is_a_tax_not_an_interest(self):
        """"Free funds interest tax" contains "interest": rule order matters."""
        assert classify_cash_type("Free funds interest tax") == TxType.TAX


class TestTotalRows:
    @pytest.mark.parametrize("label", ["Total", "total", "Profit/loss", "Somme"])
    def test_detected(self, label):
        assert is_total_row(label)

    @pytest.mark.parametrize("label", ["Dividend", "Deposit", None])
    def test_not_detected(self, label):
        assert not is_total_row(label)


class TestRealFormat:
    """Structure verified against real 2026 xStation exports."""

    def test_all_sections_are_detected(self, xtb_export):
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")

        assert result.warnings == []
        assert len(result.open_positions) == 2  # ASML + NVDA, lots exclus
        assert len(result.closed_positions) == 4
        # 6 operations: the "Total" row is discarded
        assert len(result.cash_operations) == 6

    def test_ticker_is_the_symbol_not_the_company_name(self, xtb_export):
        """"Ticker" holds the symbol, "Instrument" holds the company name."""
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")
        asml = next(p for p in result.open_positions if p["broker_symbol"] == "ASML.NL")

        assert asml["broker_symbol"] == "ASML.NL"
        assert asml["name"] == "ASML"

    def test_lots_are_not_counted_as_positions(self, xtb_export):
        """Nvidia has two lots: exactly one position must result."""
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")
        nvidia = [p for p in result.open_positions if p["broker_symbol"] == "NVDA.US"]

        assert len(nvidia) == 1
        assert nvidia[0]["quantity"] == 2.0  # aggregate value, not 1 + 1 counted twice
        assert nvidia[0]["lots_count"] == 2

    def test_position_uses_aggregate_values(self, xtb_export):
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")
        nvidia = next(p for p in result.open_positions if p["broker_symbol"] == "NVDA.US")

        assert nvidia["avg_price"] == 106.53  # average cost
        assert nvidia["market_value"] == 1312.08
        assert nvidia["net_pl"] == 614.27
        assert nvidia["net_pl_pct"] == 88.03

    def test_current_price_comes_from_the_lots(self, xtb_export):
        """The aggregate row carries no price: it is taken from the lots."""
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")
        nvidia = next(p for p in result.open_positions if p["broker_symbol"] == "NVDA.US")

        # Price in the instrument currency (USD), not value / quantity in EUR.
        assert nvidia["market_price"] == 217.46

    def test_open_date_comes_from_earliest_lot(self, xtb_export):
        """The aggregate row has no date: take the earliest lot's."""
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")
        nvidia = next(p for p in result.open_positions if p["broker_symbol"] == "NVDA.US")

        assert nvidia["opened_at"] == datetime(2025, 1, 28, 15, 6, 48)

    def test_category_is_captured(self, xtb_export):
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")

        assert all(p["category"] == "STOCK" for p in result.open_positions)

    def test_account_is_captured(self, xtb_export):
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")

        assert result.accounts == ["My Trades"]
        assert all(p["account"] == "My Trades" for p in result.open_positions)

    def test_summary_table_is_not_mistaken_for_data(self, xtb_export):
        """The "Product | Metric | Amount | Currency" block is not a data table."""
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")

        assert all(op["type"] != TxType.OTHER or op["raw_type"] for op in result.cash_operations)
        assert not any(p["broker_symbol"] == "VALUE" for p in result.open_positions)

    def test_total_row_is_excluded(self, xtb_export):
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")

        assert not any(op["raw_type"] == "Total" for op in result.cash_operations)

    def test_closed_positions_get_a_unique_stable_key(self, xtb_export):
        """"Position ID" is not enough: partial closes share it."""
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")

        ids = [c["external_id"] for c in result.closed_positions]
        assert len(set(ids)) == len(ids) == 4

    def test_partial_closes_sharing_a_position_id_stay_distinct(self, xtb_export):
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")
        apld = [c for c in result.closed_positions if c["broker_symbol"] == "APLD.US"]

        assert len(apld) == 2
        assert apld[0]["position_id"] == apld[1]["position_id"] == "1677685567"
        assert apld[0]["external_id"] != apld[1]["external_id"]

    def test_numeric_ids_are_not_rendered_as_floats(self, xtb_export):
        """openpyxl returns integers as floats: expect "1677685567", not "1677685567.0"."""
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")

        assert all(not c["position_id"].endswith(".0") for c in result.closed_positions)

    def test_synthetic_id_is_stable_across_parses(self, xtb_export):
        first = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")
        second = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")

        assert [c["external_id"] for c in first.closed_positions] == [
            c["external_id"] for c in second.closed_positions
        ]

    def test_cash_operation_ids_come_from_the_broker(self, xtb_export):
        result = parse_xtb_export(xtb_export, "EUR_1234567.xlsx")
        dividend = next(op for op in result.cash_operations if op["type"] == TxType.DIVIDEND)

        assert dividend["external_id"] == "1386991257"
        assert dividend["broker_symbol"] == "ASML.NL"


class TestSecondAccount:
    def test_pea_export_is_scoped_to_its_own_account(self, xtb_pea_export):
        result = parse_xtb_export(xtb_pea_export, "PEA_7654321.xlsx")

        assert result.accounts == ["PEA"]
        assert len(result.open_positions) == 1
        assert result.open_positions[0]["broker_symbol"] == "TTE.FR"


class TestShortPositions:
    def test_all_sell_lots_yield_a_negative_quantity(self):
        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", "Tesla", "TSLA.US", "STOCK", None, 5.0, 900.0, None,
                         180.0, None, None, None, 10.0, 20.0, 20.0, None, None, None],
                        ["My Trades", 999, "TSLA.US", None, "SELL", 5.0, 900.0, 180.0,
                         180.0, "2025-06-01 12:00:00", None, None, 10.0, 20.0, 20.0, None, None, None],
                    ],
                )
            ]
        )
        result = parse_xtb_export(content, "short.xlsx")

        assert result.open_positions[0]["quantity"] == -5.0


class TestFallbackWithoutAggregateRows:
    def test_lots_become_positions_when_no_aggregate_level_exists(self):
        """Some exports have no aggregate level: the lots must not be lost."""
        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", 111, "AAPL.US", None, "BUY", 3.0, 600.0, 200.0,
                         185.0, "2025-01-05 10:00:00", None, None, 8.1, 45.0, 45.0, None, None, None],
                        ["My Trades", 112, "AAPL.US", None, "BUY", 2.0, 400.0, 200.0,
                         190.0, "2025-02-05 10:00:00", None, None, 5.2, 20.0, 20.0, None, None, None],
                    ],
                )
            ]
        )
        result = parse_xtb_export(content, "lots.xlsx")

        assert len(result.open_positions) == 2
        assert {p["quantity"] for p in result.open_positions} == {3.0, 2.0}


class TestFailureModes:
    """Un fichier inattendu doit produire un diagnostic, jamais une exception."""

    def test_unsupported_extension(self):
        result = parse_xtb_export(b"whatever", "report.pdf")

        assert result.is_empty
        assert codes(result) == [MessageCode.UNSUPPORTED_FILE_TYPE]
        assert result.warnings[0].params["extension"] == ".pdf"

    def test_corrupt_file_is_reported(self):
        result = parse_xtb_export(b"ceci n'est pas un xlsx", "report.xlsx")

        assert result.is_empty
        assert result.warnings

    def test_unrecognised_content_is_reported_not_silently_dropped(self):
        content = build_workbook(
            [("BLOC INCONNU", ["Colonne A", "Colonne B", "Colonne C"], [[1, 2, 3]])]
        )
        result = parse_xtb_export(content, "inconnu.xlsx")

        assert result.is_empty
        assert result.warnings

    def test_row_with_unreadable_price_is_reported(self):
        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", "OK", "OK.US", "STOCK", None, 1.0, 10.0, None,
                         10.0, None, None, None, 1.0, 1.0, 1.0, None, None, None],
                        ["My Trades", "KO", "KO.US", "STOCK", None, 1.0, 10.0, None,
                         "illisible", None, None, None, 1.0, 1.0, 1.0, None, None, None],
                    ],
                )
            ]
        )
        result = parse_xtb_export(content, "partiel.xlsx")

        assert len(result.open_positions) == 1
        assert MessageCode.POSITION_SKIPPED in codes(result)
        assert any(w.params.get("symbol") == "KO.US" for w in result.warnings)


class TestCsvExport:
    def test_semicolon_csv_is_parsed(self):
        csv_content = (
            ";".join(CASH_HEADERS) + "\n"
            "Dividend;ASML;ASML.NL;STOCK;2026-08-05 09:59:25;1,88;1386991257;DIV;My Trades;123\n"
        ).encode("utf-8")

        result = parse_xtb_export(csv_content, "cash.csv")

        assert len(result.cash_operations) == 1
        assert result.cash_operations[0]["type"] == TxType.DIVIDEND
        assert result.cash_operations[0]["amount"] == 1.88
        assert result.cash_operations[0]["broker_symbol"] == "ASML.NL"
