"""Free cash at a broker (Step 3u.115): the running "Solde" of a Mintos
account statement and the free-funds figure of an XTB summary table, kept
as CASH positions. Every amount here is made up."""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest.mintos_transactions_import import parse_mintos_transactions_export
from app.ingest.service import import_export_file, import_mintos_transactions_file
from app.ingest.xtb_import import parse_xtb_export
from app.messages import MessageCode
from app.models import Instrument, Position
from tests.conftest import OPEN_HEADERS, build_xtb_workbook


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


def _cash_positions(db) -> dict[str, Position]:
    rows = db.execute(
        select(Position).join(Instrument).where(Instrument.not_priceable_reason == "broker_cash")
    ).scalars()
    return {p.instrument.broker_symbol: p for p in rows}


def _codes(batch) -> list[str]:
    return [w["code"] for w in batch.warnings]


# --- Mintos ----------------------------------------------------------------

_HEADER = ["Date", "ID de transaction :", "Détails", "Mouvement", "Solde", "Devise", "Type de paiement"]


def _statement(rows: list[tuple[str, float, float, str, str]], header: list[str] = _HEADER) -> bytes:
    buffer = io.StringIO()
    buffer.write(",".join(header) + "\n")
    for when, amount, balance, currency, kind in rows:
        cells = [when, "id", "détail", str(amount), str(balance), currency, kind]
        buffer.write(",".join(cells[: len(header)]) + "\n")
    return buffer.getvalue().encode("utf-8")


NEWEST_FIRST = [
    ("2026-11-02 08:00:03", -10.0, 12.34, "EUR", "Investissement"),
    ("2026-11-02 08:00:03", 0.05, 22.34, "EUR", "Intérêt perçu"),
    ("2026-11-01 09:00:00", 0.10, 22.29, "EUR", "Intérêt perçu"),
    ("2026-10-30 09:00:00", 50.00, 22.19, "EUR", "Dépôts"),
]


class TestMintosParse:
    def test_newest_row_gives_the_free_cash(self):
        parsed = parse_mintos_transactions_export(_statement(NEWEST_FIRST), "20261102-account-statement.csv")

        # Two rows share the newest second: in a newest-first file the
        # first one is the balance after both.
        assert parsed.free_cash == {"EUR": 12.34}

    def test_oldest_first_file_reads_the_same(self):
        rows = list(reversed(NEWEST_FIRST))
        parsed = parse_mintos_transactions_export(_statement(rows), "20261102-account-statement.csv")

        assert parsed.free_cash == {"EUR": 12.34}

    def test_one_figure_per_currency(self):
        rows = [*NEWEST_FIRST, ("2026-10-01 09:00:00", 1.0, 3.21, "KZT", "Intérêt perçu")]
        parsed = parse_mintos_transactions_export(_statement(rows), "20261102-account-statement.csv")

        assert parsed.free_cash == {"EUR": 12.34, "KZT": 3.21}

    def test_no_balance_column_means_no_figure(self):
        header = ["Date", "ID de transaction :", "Détails", "Mouvement"]
        content = "\n".join(
            [",".join([*header, "Type de paiement"]), "2026-11-01 09:00:00,id,d,0.10,Intérêt perçu"]
        ).encode()
        parsed = parse_mintos_transactions_export(content, "20261102-account-statement.csv")

        assert parsed.income_total == pytest.approx(0.10)
        assert parsed.free_cash == {}


class TestMintosImport:
    def test_free_cash_becomes_a_cash_position(self, db):
        batch = import_mintos_transactions_file(db, _statement(NEWEST_FIRST), "20261102-account-statement.csv")

        position = _cash_positions(db)["MINTOS-CASH-EUR"]
        assert position.broker_market_value == pytest.approx(12.34)
        assert position.account == "Mintos"
        assert position.value_as_of == date(2026, 11, 2)
        assert position.instrument.category == "CASH"
        assert position.instrument.name == "Mintos — fonds libres"
        message = next(w for w in batch.warnings if w["code"] == MessageCode.BROKER_FREE_CASH)
        assert message["params"]["accounts"] == "Mintos 12.34 EUR"

    def test_a_newer_statement_replaces_it(self, db):
        import_mintos_transactions_file(db, _statement(NEWEST_FIRST[2:]), "20261101-account-statement.csv")
        import_mintos_transactions_file(db, _statement(NEWEST_FIRST), "20261102-account-statement.csv")

        cash = _cash_positions(db)
        assert len(cash) == 1
        assert cash["MINTOS-CASH-EUR"].broker_market_value == pytest.approx(12.34)

    def test_an_older_statement_keeps_the_newer_figure(self, db):
        import_mintos_transactions_file(db, _statement(NEWEST_FIRST), "20261102-account-statement.csv")
        batch = import_mintos_transactions_file(db, _statement(NEWEST_FIRST[2:]), "20261101-account-statement.csv")

        assert _cash_positions(db)["MINTOS-CASH-EUR"].broker_market_value == pytest.approx(12.34)
        assert MessageCode.BANK_BALANCE_KEPT in _codes(batch)

    def test_a_preview_writes_nothing(self, db):
        summary = import_mintos_transactions_file(
            db, _statement(NEWEST_FIRST), "20261102-account-statement.csv", commit=False
        )

        assert MessageCode.BROKER_FREE_CASH in [w["code"] for w in summary["warnings"]]
        assert _cash_positions(db) == {}


# --- XTB -------------------------------------------------------------------

def _xtb(summary: list[list], *, stock_value: float = 100.0) -> bytes:
    return build_xtb_workbook(
        [
            (
                "Open Positions",
                [
                    ["Account number", 1234567],
                    ["Open Positions"],
                    ["Data as of report generated", "2026-11-17 20:00:00"],
                    ["Product", "Metric", "Amount", "Currency"],
                    *summary,
                    [],
                ],
                OPEN_HEADERS,
                [
                    ["My Trades", "ASML", "ASML.NL", "STOCK", None, 1.0, stock_value, None,
                     700.0, None, None, None, 1.0, 1.0, 1.0, None, None, None],
                    ["My Trades", 1900000201, "ASML.NL", None, "BUY", 1.0, stock_value, stock_value,
                     700.0, "2025-01-31 13:33:28", None, None, 1.0, 1.0, 1.0, None, None, None],
                ],
            )
        ]
    )


class TestXtbParse:
    def test_free_funds_metric_is_read(self):
        parsed = parse_xtb_export(
            _xtb([["My Trades", "Value", 100.0, "EUR"], ["My Trades", "Free funds", 45.67, "EUR"]]),
            "EUR_1234567.xlsx",
        )

        assert parsed.free_cash == [{"account": "My Trades", "amount": 45.67, "currency": "EUR"}]
        assert parsed.report_time is not None and parsed.report_time.date() == date(2026, 11, 17)

    def test_free_funds_win_over_a_plain_balance(self):
        parsed = parse_xtb_export(
            _xtb([["My Trades", "Balance", 99.0, "EUR"], ["My Trades", "Free margin", 45.67, "EUR"]]),
            "EUR_1234567.xlsx",
        )

        assert [item["amount"] for item in parsed.free_cash] == [45.67]

    def test_a_balance_alone_is_the_fallback(self):
        parsed = parse_xtb_export(_xtb([["My Trades", "Balance", 99.0, "EUR"]]), "EUR_1234567.xlsx")

        assert [item["amount"] for item in parsed.free_cash] == [99.0]

    def test_metrics_are_listed_and_the_table_after_is_not_a_summary(self):
        parsed = parse_xtb_export(
            build_xtb_workbook(
                [
                    (
                        "Open Positions",
                        # No blank row between the summary and the real table.
                        [["Product", "Metric", "Amount", "Currency"], ["PEA", "Value", 1000.0, "EUR"]],
                        OPEN_HEADERS,
                        [["PEA", "TotalEnergies", "TTE.FR", "STOCK", None, 10.0, 620.0, None,
                          55.0, None, None, None, 12.72, 70.0, 70.0, None, None, None]],
                    )
                ]
            ),
            "EUR_7654321.xlsx",
        )

        assert parsed.summary_metrics == ["Value"]
        assert parsed.free_cash == []
        assert len(parsed.open_positions) == 1


class TestXtbImport:
    def test_free_funds_become_a_cash_position(self, db):
        batch = import_export_file(
            db, _xtb([["My Trades", "Free funds", 45.67, "EUR"]]), "EUR_1234567.xlsx"
        )

        position = _cash_positions(db)["XTB-MY-TRADES-CASH-EUR"]
        assert position.broker_market_value == pytest.approx(45.67)
        assert position.account == "My Trades"
        assert position.value_as_of == date(2026, 11, 17)
        assert position.instrument.name == "XTB My Trades — fonds libres"
        assert MessageCode.BROKER_FREE_CASH in _codes(batch)
        # Cash is not a symbol waiting for a ticker.
        assert MessageCode.UNRESOLVED_SYMBOLS not in _codes(batch)

    def test_reimport_replaces_holdings_and_cash(self, db):
        import_export_file(db, _xtb([["My Trades", "Free funds", 45.67, "EUR"]]), "EUR_1234567.xlsx")
        import_export_file(db, _xtb([["My Trades", "Free funds", 5.00, "EUR"]], stock_value=140.0), "EUR_1234567.xlsx")

        cash = _cash_positions(db)
        assert len(cash) == 1
        assert cash["XTB-MY-TRADES-CASH-EUR"].broker_market_value == pytest.approx(5.00)
        assert db.execute(select(Position).join(Instrument).where(Instrument.broker_symbol == "ASML.NL")).scalar_one()

    def test_an_export_without_the_figure_keeps_it_and_says_so(self, db):
        import_export_file(db, _xtb([["My Trades", "Free funds", 45.67, "EUR"]]), "EUR_1234567.xlsx")
        batch = import_export_file(db, _xtb([["My Trades", "Value", 100.0, "EUR"]]), "EUR_1234567.xlsx")

        assert _cash_positions(db)["XTB-MY-TRADES-CASH-EUR"].broker_market_value == pytest.approx(45.67)
        missing = next(w for w in batch.warnings if w["code"] == MessageCode.XTB_FREE_CASH_MISSING)
        assert missing["params"]["metrics"] == "Value"

    def test_xtb_import_leaves_mintos_cash_alone(self, db):
        import_mintos_transactions_file(db, _statement(NEWEST_FIRST), "20261102-account-statement.csv")
        import_export_file(db, _xtb([["My Trades", "Free funds", 45.67, "EUR"]]), "EUR_1234567.xlsx")

        assert set(_cash_positions(db)) == {"MINTOS-CASH-EUR", "XTB-MY-TRADES-CASH-EUR"}
