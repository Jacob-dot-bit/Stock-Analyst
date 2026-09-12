"""Tests for `app/ingest/mintos_investments_import.py`'s pure parsing and
`app/ingest/service.py::import_mintos_investments_file`'s persistence.

Deliberately does not commit a copy of the user's real Mintos "Investments"
export as a test fixture — like the quarterly PDF (see
`test_mintos_import.py`'s module docstring), it carries real personal loan
data. The real file was instead cross-checked manually during development
(see DEVLOG "Decision 3u.43"): summing its `Montant investi` column matched
the account's real total (reported by the user directly from the Mintos
site) closely — the small remaining gap explained by interest/repayments
settling continuously between the two observations. Tests here use a
small synthetic workbook built in-memory
with openpyxl instead.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from unittest.mock import patch

import openpyxl
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest.mintos_import import ParsedMintosExport
from app.ingest.mintos_investments_import import (
    ParsedMintosInvestmentsSnapshot,
    parse_mintos_investments_export,
)
from app.ingest.service import import_mintos_file, import_mintos_investments_file
from app.models import Instrument, Position, Transaction, TxType

from tests.test_mintos_import import _p2p_period


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


def _workbook(header: list[str], rows: list[list[object]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


_REAL_HEADER = [
    "ID", "ISIN", "Date d'échéance prévue", "Taux d'intérêt", "Durée restante", "Type",
    "Obligation de rachat", "Date d'inscription", "Principal initial",
    "Montant du principal restant dû de la Note", "Amount Available for Investment", "Notes",
    "Mintos Risk Score", "Devise", "Principal restant", "Montant investi", "Date d'achat",
    "Pays", "Société de prêt", "Origine de l'investissement", "ID de stratégie", "Max. LTV",
    "Average LTV", "Exposition aux prêts en souffrance", "Paiements en attente", "Underlying loans",
]


def _real_shaped_row(montant_investi: float) -> list[object]:
    return [
        "id-1", "LVX0000TEST1", "30.04.2031", 12.0, 56, "Prêt personnel", "yes", "16.10.2023",
        0.01, 0.01, 1.0, 123456, 5.1, "EUR", 2.0, montant_investi, "30.04.2024", "Kenya",
        "Lender", "MS investment", 999999, None, None, 0.0, 0.0, "12345-01",
    ]


class TestParseMintosInvestmentsExport:
    def test_sums_montant_investi_across_all_rows(self):
        content = _workbook(_REAL_HEADER, [_real_shaped_row(100.0), _real_shaped_row(50.5)])

        result = parse_mintos_investments_export(content, "Investments-08-09-2026.xlsx")

        assert result.total_invested == pytest.approx(150.5)
        assert result.positions_found == 2
        assert result.as_of == date(2026, 9, 8)

    def test_a_non_numeric_row_is_skipped_not_a_crash(self):
        rows = [_real_shaped_row(100.0), _real_shaped_row(None)]
        content = _workbook(_REAL_HEADER, rows)

        result = parse_mintos_investments_export(content, "Investments-08-09-2026.xlsx")

        assert result.total_invested == pytest.approx(100.0)
        assert result.positions_found == 1

    def test_no_date_in_filename_is_a_warning_not_a_crash(self):
        content = _workbook(_REAL_HEADER, [_real_shaped_row(100.0)])

        result = parse_mintos_investments_export(content, "export.xlsx")

        assert result.is_empty
        assert result.warnings

    def test_missing_expected_column_is_a_warning_not_a_crash(self):
        content = _workbook(["Some", "Other", "Header"], [[1, 2, 3]])

        result = parse_mintos_investments_export(content, "Investments-08-09-2026.xlsx")

        assert result.is_empty
        assert result.warnings

    def test_unreadable_content_is_a_warning_not_a_crash(self):
        result = parse_mintos_investments_export(b"not an xlsx file", "Investments-08-09-2026.xlsx")

        assert result.is_empty
        assert result.warnings

    def test_no_rows_at_all_is_a_warning(self):
        content = _workbook(_REAL_HEADER, [])

        result = parse_mintos_investments_export(content, "Investments-08-09-2026.xlsx")

        assert result.is_empty
        assert result.warnings


class TestImportMintosInvestmentsFilePersistence:
    """Persistence behaviour, independent of the .xlsx layer — patches
    `parse_mintos_investments_export` with a synthetic snapshot, matching
    `test_mintos_import.py::TestImportMintosFilePersistence`'s convention."""

    def test_creates_a_p2p_snapshot_and_position(self, db):
        parsed = ParsedMintosInvestmentsSnapshot(as_of=date(2026, 9, 8), total_invested=8000.00, positions_found=500)
        with patch("app.ingest.service.parse_mintos_investments_export", return_value=parsed):
            import_mintos_investments_file(db, b"fake", "Investments-08-09-2026.xlsx")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 8000.00
        assert position.account == "Mintos Core P2P"
        # The date *this* declared balance is as of — distinct from
        # `opened_at` ("since held"), drives the freshness caveat in
        # `routers/portfolio.py`. See DEVLOG "Decision 3u.50".
        assert position.value_as_of == date(2026, 9, 8)
        instrument = db.get(Instrument, position.instrument_id)
        assert instrument.category == "P2P"
        assert instrument.not_priceable_reason == "p2p_aggregate"
        snapshot = db.execute(select(Transaction).where(Transaction.type == TxType.P2P_SNAPSHOT)).scalar_one()
        assert snapshot.amount == 8000.00

    def test_reimporting_the_same_file_does_not_duplicate(self, db):
        parsed = ParsedMintosInvestmentsSnapshot(as_of=date(2026, 9, 8), total_invested=8000.00, positions_found=500)
        with patch("app.ingest.service.parse_mintos_investments_export", return_value=parsed):
            import_mintos_investments_file(db, b"fake", "Investments-08-09-2026.xlsx")
            batch2 = import_mintos_investments_file(db, b"fake", "Investments-08-09-2026.xlsx")

        assert batch2.transactions_inserted == 0
        assert len(db.execute(select(Transaction)).scalars().all()) == 1
        assert len(db.execute(select(Position)).scalars().all()) == 1

    def test_an_empty_parse_result_creates_nothing(self, db):
        parsed = ParsedMintosInvestmentsSnapshot()  # no date/total — e.g. bad filename
        with patch("app.ingest.service.parse_mintos_investments_export", return_value=parsed):
            batch = import_mintos_investments_file(db, b"fake", "export.xlsx")

        assert batch.positions_found == 0
        assert batch.transactions_inserted == 0
        assert db.execute(select(Position)).scalars().all() == []

    def test_a_more_recent_investments_snapshot_supersedes_an_older_pdf_period(self, db):
        """The whole point of this new import path: a stale quarterly PDF
        must not keep winning once a fresher live snapshot exists."""
        pdf_parsed = ParsedMintosExport(
            p2p_period=_p2p_period("2025-07-01", "2025-09-30", 0.0, 4000.0, -63.0, 4500.00)
        )
        with patch("app.ingest.service.parse_mintos_statement", return_value=pdf_parsed):
            import_mintos_file(db, b"fake-pdf", "q3-2025.pdf")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 4500.00
        assert position.value_as_of == date(2025, 9, 30)  # the PDF period's own end date

        xlsx_parsed = ParsedMintosInvestmentsSnapshot(as_of=date(2026, 9, 8), total_invested=8000.00, positions_found=500)
        with patch("app.ingest.service.parse_mintos_investments_export", return_value=xlsx_parsed):
            import_mintos_investments_file(db, b"fake-xlsx", "Investments-08-09-2026.xlsx")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 8000.00
        assert position.value_as_of == date(2026, 9, 8)

    def test_an_older_investments_snapshot_does_not_regress_a_newer_pdf_period(self, db):
        xlsx_parsed = ParsedMintosInvestmentsSnapshot(as_of=date(2024, 1, 1), total_invested=1000.0, positions_found=10)
        with patch("app.ingest.service.parse_mintos_investments_export", return_value=xlsx_parsed):
            import_mintos_investments_file(db, b"fake-xlsx", "Investments-01-01-2024.xlsx")

        pdf_parsed = ParsedMintosExport(
            p2p_period=_p2p_period("2025-07-01", "2025-09-30", 0.0, 4000.0, -63.0, 4500.00)
        )
        with patch("app.ingest.service.parse_mintos_statement", return_value=pdf_parsed):
            import_mintos_file(db, b"fake-pdf", "q3-2025.pdf")

        assert db.execute(select(Position)).scalar_one().broker_market_value == 4500.00

    def test_a_fresh_live_snapshot_does_not_reset_since_to_today(self, db):
        """`opened_at` ("Depuis" in the UI) must reflect the account's real
        history, not this import's own as-of date -- a fresh live snapshot
        making it look like the position was just opened today was a real,
        user-caught bug. See DEVLOG "Decision 3u.49"."""
        pdf_parsed = ParsedMintosExport(
            p2p_period=_p2p_period("2024-04-01", "2024-06-30", 0.0, 4000.0, -63.0, 4500.00)
        )
        with patch("app.ingest.service.parse_mintos_statement", return_value=pdf_parsed):
            import_mintos_file(db, b"fake-pdf", "q2-2024.pdf")

        xlsx_parsed = ParsedMintosInvestmentsSnapshot(as_of=date(2026, 9, 8), total_invested=8000.00, positions_found=500)
        with patch("app.ingest.service.parse_mintos_investments_export", return_value=xlsx_parsed):
            import_mintos_investments_file(db, b"fake-xlsx", "Investments-08-09-2026.xlsx")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 8000.00  # the fresh value still wins
        assert position.opened_at == datetime(2024, 4, 1)  # but "since" stays the real start
        assert position.value_as_of == date(2026, 9, 8)  # value_as_of tracks the winning snapshot, not "since"
