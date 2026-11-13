"""Mintos annual tax report: reading it, importing it, and the tax summary
using it for its year. See DEVLOG "Step 3u.113". Every figure here is
invented."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest.detect import FileKind, detect_file
from app.ingest.mintos_tax_report_import import (
    parse_mintos_tax_report,
    parse_mintos_tax_report_pages,
)
from app.ingest.service import import_mintos_tax_report_file
from app.models import ImportBatch, MintosTaxReport, Transaction, TxType
from app.tax.gains import capital_gains_by_year
from app.tax.service import available_tax_years, compute_tax_year_summary
from tests.test_tax_notice import _pdf

FIRST_PAGE = [
    "AS Mintos Marketplace Registration Nr.: 00000000000",
    "Investor: Test Investor",
    "Investor ID: 12345678",
    "Reporting year: 2023",
    "IInnvveessttoorr aaccccoouunntt ssttaatteemmeenntt",
    "ETF EUR 1 000.00 - - - -",
    "IInntteerreesstt",
    "The investor in the period from 01.01.2023 to 31.12.2023 has received the below interest:",
    "Notes backed by",
    "EUR 1 100.00 55.00 5% 1 045.00 1 045.00",
    "loans",
    "Notes backed by",
    "EUR 40.00 2.00 5% 38.00 38.00",
    "bonds",
    "Smart Cash EUR 1.50 - - 1.50 1.50",
    "For Interest earned from investments in Claims detailed please see Annex No.3",
]
SECOND_PAGE = [
    "The investor in the period from 01.01.2023 to 31.12.2023 has received the below capital gains:",
    "Notes backed by bonds EUR -3.00 -3.00",
    "See detailed information about Capital gains in Annex No.5",
    "The investor in the period from 01.01.2023 to 31.12.2023 has received the below other income:",
    "Bonuses and campaigns EUR 20.00 20.00",
    "Discount income from bonds EUR 10.50 10.50",
    "EExxppeennsseess",
    "The investor in the period from 01.01.2023 to 31.12.2023 has the below expenses:",
    "Core Loans fee EUR 1.25 1.25",
    "Amounts below have been written-off in the period from 01.01.2023 to 31.12.2023:",
    "-- -- -- --",
]
REPORT = _pdf([FIRST_PAGE, SECOND_PAGE])


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield db
    db.close()


class TestParse:
    def test_every_section(self):
        parsed = parse_mintos_tax_report(REPORT)
        assert parsed.year == 2023
        assert parsed.interest == 1141.5
        assert parsed.withholding_tax == 57.0
        assert parsed.capital_gains == {"Notes backed by bonds": -3.0}
        assert parsed.other_income == {"Bonuses and campaigns": 20.0, "Discount income from bonds": 10.5}
        assert parsed.expenses == {"Core Loans fee": 1.25}
        assert parsed.income_total == 1172.0
        assert parsed.cost_total == -58.25

    def test_nothing_about_the_investor_is_kept(self):
        figures = parse_mintos_tax_report(REPORT).figures()
        text = repr(figures)
        assert "Test Investor" not in text and "12345678" not in text

    def test_without_a_year_it_is_empty(self):
        assert parse_mintos_tax_report_pages(["Mintos", "nothing here"]).is_empty

    def test_detected_before_the_quarterly_statement(self):
        assert detect_file(REPORT) == FileKind.MINTOS_TAX_REPORT
        assert detect_file(_pdf([["Mintos investor statement", "Mintos Core"]])) == FileKind.MINTOS_STATEMENT


class TestImport:
    def test_kept_then_replaced(self, session):
        batch = import_mintos_tax_report_file(session, REPORT, "tax_report.pdf")
        assert [w["code"] for w in batch.warnings] == ["import.mintosTaxReportKept"]
        assert batch.warnings[0]["params"] == {"year": 2023, "income": 1172.0, "costs": 58.25}

        corrected = _pdf([FIRST_PAGE, [l.replace("20.00", "25.00") for l in SECOND_PAGE]])
        batch = import_mintos_tax_report_file(session, corrected, "tax_report.pdf")
        assert [w["code"] for w in batch.warnings] == ["import.mintosTaxReportReplaced"]
        reports = session.query(MintosTaxReport).all()
        assert len(reports) == 1
        assert reports[0].figures["income_total"] == 1177.0

    def test_unreadable(self, session):
        batch = import_mintos_tax_report_file(session, _pdf([["Mintos", "Reporting year: soon"]]), "x.pdf")
        assert [w["code"] for w in batch.warnings] == ["import.mintosTaxReportUnreadable"]
        assert session.query(MintosTaxReport).count() == 0

    def test_preview_keeps_nothing(self, session):
        import_mintos_tax_report_file(session, REPORT, "tax_report.pdf", commit=False)
        assert session.query(MintosTaxReport).count() == 0
        assert session.query(ImportBatch).count() == 0


class TestTaxSummary:
    def test_report_replaces_the_statements_for_its_year(self, session):
        # A quarterly statement gives loan interest only.
        session.add(Transaction(type=TxType.P2P_INTEREST, account="Mintos Core P2P", amount=300.0,
                                executed_at=datetime(2023, 6, 30)))
        session.add(Transaction(type=TxType.P2P_FEE, account="Mintos Core P2P", amount=-0.5,
                                executed_at=datetime(2023, 6, 30)))
        session.commit()
        import_mintos_tax_report_file(session, REPORT, "tax_report.pdf")

        summary = compute_tax_year_summary(session, 2023)
        (p2p,) = [e for e in summary.envelopes if e.account == "Mintos Core P2P"]
        assert p2p.interest == 1172.0
        assert p2p.fees == -58.25
        assert p2p.notes[-1].code == "taxPrep.mintosTaxReportUsed"
        assert p2p.notes[-1].params == {"interest": 1141.5, "other": 30.5, "withholding": 57.0}
        assert summary.capital_gains is not None
        assert summary.capital_gains.platform == -3.0
        assert summary.capital_gains.losses == -3.0

    def test_envelope_added_when_nothing_else_brought_it(self, session):
        import_mintos_tax_report_file(session, REPORT, "tax_report.pdf")
        assert available_tax_years(session) == [2023]
        summary = compute_tax_year_summary(session, 2023)
        assert [e.account for e in summary.envelopes] == ["Mintos Core P2P"]
        assert summary.envelopes[0].status == "to_reconcile"

    def test_other_years_untouched(self, session):
        session.add(Transaction(type=TxType.P2P_INTEREST, account="Mintos Core P2P", amount=300.0,
                                executed_at=datetime(2024, 6, 30)))
        session.commit()
        import_mintos_tax_report_file(session, REPORT, "tax_report.pdf")
        summary = compute_tax_year_summary(session, 2024)
        (p2p,) = summary.envelopes
        assert p2p.interest == 300.0
        assert p2p.notes == []


def test_platform_results_join_the_yearly_net():
    years = capital_gains_by_year([], [], {2022: -10.0, 2023: 4.0})
    assert years[2022].platform == -10.0 and years[2022].net == -10.0
    assert years[2023].losses_used == 4.0 and years[2023].taxable_net == 0.0
