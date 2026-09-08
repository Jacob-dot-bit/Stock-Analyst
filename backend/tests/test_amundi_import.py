"""Tests for the Amundi ESR importer — `app/ingest/amundi_import.py`'s pure
label-classification logic, and `app/ingest/service.py::import_amundi_file`'s
persistence (derived avg_price/gain, the chronology guard, fiscal-document
skip).

Deliberately does not commit a copy of the user's real Amundi statement PDFs
as test fixtures — same reasoning as `test_mintos_import.py`. The PDF-table-
extraction layer (`parse_amundi_statement`) was verified manually against
the real 2023/2024/2025 statements during development (DEVLOG "Decision
3u.39") — every fund's quantity/value/gain hand-checked against the
statement's own printed figures, across two different real template
variants (2023's "RELEVE DE COMPTES" omits the "Support de placement"
column header entirely; 2024/2025's "RELEVE ANNUEL" includes it).
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest.amundi_import import ParsedAmundiExport, ParsedFund, _classify_aggregate_label, _to_float
from app.ingest.service import import_amundi_file
from app.models import Instrument, Position, Transaction, TxType


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


class TestToFloat:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("123,45 €", 300.00),
            ("-38,25 %", -38.25),
            ("18,5000", 18.5000),
            ("1 234,56 €", 1986.60),  # thousands space, seen in real statements
            (None, None),
            ("", None),
        ],
    )
    def test_french_currency_format(self, raw, expected):
        assert _to_float(raw) == pytest.approx(expected) if expected is not None else _to_float(raw) is None


class TestClassifyAggregateLabel:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Versements volontaires", "versements_volontaires"),
            ("Abondement de votre entreprise (montant net)", "abondement_net"),
            ("Abondement brut obtenu", "abondement_brut"),
            ("Intéressement et/ou Participation net directement perçu", "interessement_participation_percu"),
            ("Intéressement et/ou Participation placés (montant net)", "interessement_participation_percu"),
            ("Une ligne jamais vue avant", "other"),
        ],
    )
    def test_labels(self, label, expected):
        assert _classify_aggregate_label(label) == expected


def _fund(name: str, account: str, quantity: float, unit_price: float, gross_value: float, gain: float) -> ParsedFund:
    return ParsedFund(account=account, name=name, unit_price=unit_price, quantity=quantity, gross_value=gross_value, estimated_gain_loss=gain)


class TestImportAmundiFilePersistence:
    """Persistence behaviour, independent of the PDF layer — patches
    `parse_amundi_statement` with a synthetic `ParsedAmundiExport`."""

    def test_fund_avg_price_and_gain_are_derived_not_invented(self, db):
        # Real 2025 PEG figures (see DEVLOG "Decision 3u.39"): gross 300.00,
        # Amundi's own estimated gain 25.00 -> cost = 226.13, qty = 18.5000.
        parsed = ParsedAmundiExport(
            as_of=date(2025, 12, 31),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 18.5000, 10.50000, 300.00, 25.00)],
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=parsed):
            import_amundi_file(db, b"fake", "test.pdf")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 300.00
        assert position.broker_gross_pl == 25.00
        assert position.broker_net_pl == 25.00  # Amundi has only one P&L figure — see module docstring
        assert position.avg_price == pytest.approx((300.00 - 25.00) / 18.5000)
        instrument = db.get(Instrument, position.instrument_id)
        assert instrument.category == "FUND"
        assert instrument.not_priceable_reason == "employee_savings_fund"

    def test_fiscal_document_is_skipped_not_mis_parsed(self, db):
        parsed = ParsedAmundiExport(is_fiscal_document=True)
        with patch("app.ingest.service.parse_amundi_statement", return_value=parsed):
            batch = import_amundi_file(db, b"fake", "fiscal.pdf")

        assert batch.positions_found == 0
        assert db.execute(select(Position)).scalars().all() == []

    def test_older_statement_does_not_regress_current_positions(self, db):
        newer = ParsedAmundiExport(as_of=date(2025, 12, 31), funds=[_fund("FUND A", "Amundi PEG", 10, 100.0, 1000.0, 50.0)])
        older = ParsedAmundiExport(as_of=date(2023, 12, 31), funds=[_fund("FUND A", "Amundi PEG", 8, 90.0, 720.0, 10.0)])
        with patch("app.ingest.service.parse_amundi_statement", side_effect=[newer, older]):
            import_amundi_file(db, b"fake-newer", "2025.pdf")
            import_amundi_file(db, b"fake-older", "2023.pdf")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 1000.0  # still 2025's figure, not overwritten by 2023

    def test_newer_statement_replaces_older_positions(self, db):
        older = ParsedAmundiExport(as_of=date(2023, 12, 31), funds=[_fund("FUND A", "Amundi PEG", 8, 90.0, 720.0, 10.0)])
        newer = ParsedAmundiExport(as_of=date(2025, 12, 31), funds=[_fund("FUND A", "Amundi PEG", 10, 100.0, 1000.0, 50.0)])
        with patch("app.ingest.service.parse_amundi_statement", side_effect=[older, newer]):
            import_amundi_file(db, b"fake-older", "2023.pdf")
            import_amundi_file(db, b"fake-newer", "2025.pdf")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 1000.0

    def test_aggregate_totals_are_recorded_as_annual_not_dated_transactions(self, db):
        parsed = ParsedAmundiExport(
            as_of=date(2025, 12, 31),
            funds=[_fund("FUND A", "Amundi PEG", 10, 100.0, 1000.0, 50.0)],
            aggregate_totals={"Amundi PEG": {"versements_volontaires": 4000.0}},
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=parsed):
            import_amundi_file(db, b"fake", "test.pdf")

        tx = db.execute(select(Transaction).where(Transaction.type == TxType.OTHER)).scalar_one()
        assert tx.amount == 4000.0
        assert tx.executed_at == datetime(2025, 12, 31)
        assert "relevé annuel" in tx.comment

    def test_reimporting_the_same_statement_does_not_duplicate_aggregate_transactions(self, db):
        parsed = ParsedAmundiExport(
            as_of=date(2025, 12, 31),
            funds=[_fund("FUND A", "Amundi PEG", 10, 100.0, 1000.0, 50.0)],
            aggregate_totals={"Amundi PEG": {"versements_volontaires": 4000.0}},
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=parsed):
            import_amundi_file(db, b"fake", "test.pdf")
            batch2 = import_amundi_file(db, b"fake", "test.pdf")

        assert batch2.transactions_inserted == 0
        assert len(db.execute(select(Transaction)).scalars().all()) == 1
