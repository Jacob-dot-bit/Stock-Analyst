"""The app's figures set against the income tax notice (Step 3u.112), and
Mintos interest split by year. Every amount here is made up."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest.mintos_transactions_import import ParsedMintosTransactionsExport
from app.ingest.service import import_mintos_transactions_file
from app.models import Instrument, TaxNotice, Transaction, TxType
from app.tax.checks import notice_checks
from app.tax.gains import CapitalGainsYear
from app.tax.service import compute_tax_year_summary


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield db
    db.close()


def _codes(messages):
    return [m.code.rsplit(".", 1)[-1] for m in messages]


class TestNoticeChecks:
    def test_loss_missing_from_the_notice(self):
        year = CapitalGainsYear(year=2024, net=-640.0)
        assert _codes(notice_checks(2024, {}, [], year, 0.0)) == ["lossNotOnNotice"]

    def test_loss_carried_on_the_notice_is_fine(self):
        year = CapitalGainsYear(year=2024, net=-640.0)
        lines = [{"section": "", "label": "Moins-value provenant de l'année 2024", "values": [640]}]
        assert _codes(notice_checks(2024, {}, lines, year, 0.0)) == ["agrees"]

    def test_gain_without_earlier_losses_set_off(self):
        year = CapitalGainsYear(year=2025, net=3000.0, losses_used=640.0, taxable_net=2360.0)
        checks = notice_checks(2025, {"capital_gains": 3000}, [], year, 0.0)
        assert _codes(checks) == ["lossesNotUsed"]
        assert checks[0].params == {"available": 640.0, "notice": 3000, "app": 2360.0}

    def test_gain_after_set_off_agrees(self):
        year = CapitalGainsYear(year=2025, net=3000.0, losses_used=640.0, taxable_net=2360.0)
        assert _codes(notice_checks(2025, {"capital_gains": 2360}, [], year, 0.0)) == ["agrees"]

    def test_income_missing_and_differing(self):
        assert _codes(notice_checks(2024, {}, [], None, 410.0)) == ["incomeNotOnNotice"]
        assert _codes(notice_checks(2025, {"investment_income": 700}, [], None, 900.0)) == ["incomeDiffers"]
        assert _codes(notice_checks(2025, {"investment_income": 895}, [], None, 900.0)) == ["agrees"]


class TestSummaryWithNotice:
    def test_cfd_loss_not_declared(self, session):
        index = Instrument(broker_symbol="IDX40", currency="EUR")
        session.add(index)
        session.commit()
        session.add(Transaction(type=TxType.CLOSED_TRADE, account="Broker A", instrument_id=index.id,
                                amount=-640.0, quantity=0.01, executed_at=datetime(2024, 8, 5)))
        session.add(TaxNotice(income_year=2024, figures={"gross_income": 15000}, lines=[]))
        session.commit()

        summary = compute_tax_year_summary(session, 2024)

        assert _codes(summary.notice_checks) == ["lossNotOnNotice"]

    def test_no_notice_no_checks(self, session):
        session.add(Transaction(type=TxType.DIVIDEND, account="Broker A", amount=50.0, executed_at=datetime(2024, 3, 1)))
        session.commit()
        assert compute_tax_year_summary(session, 2024).notice_checks == []


class TestMintosInterestByYear:
    def _import(self, session, parsed):
        with patch("app.ingest.service.parse_mintos_transactions_export", return_value=parsed):
            import_mintos_transactions_file(session, b"fake", "20260908-account-statement.csv")

    def test_one_row_per_year(self, session):
        self._import(session, ParsedMintosTransactionsExport(
            period_start=date(2025, 1, 1), period_end=date(2026, 9, 8), income_total=500.0, cost_total=-50.0,
            by_year={2025: (300.0, -30.0), 2026: (200.0, -20.0)}, transaction_count=10,
        ))

        y2025 = compute_tax_year_summary(session, 2025).envelopes[0]
        y2026 = compute_tax_year_summary(session, 2026).envelopes[0]
        assert (y2025.interest, y2025.fees) == (300.0, -30.0)
        assert (y2026.interest, y2026.fees) == (200.0, -20.0)

    def test_longer_statement_replaces_the_earlier_one(self, session):
        self._import(session, ParsedMintosTransactionsExport(
            period_start=date(2025, 1, 1), period_end=date(2025, 6, 30), income_total=150.0, cost_total=0.0,
            by_year={2025: (150.0, 0.0)}, transaction_count=5,
        ))
        self._import(session, ParsedMintosTransactionsExport(
            period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), income_total=300.0, cost_total=0.0,
            by_year={2025: (300.0, 0.0)}, transaction_count=10,
        ))

        interest = session.execute(select(Transaction).where(Transaction.type == TxType.P2P_INTEREST)).scalars().all()
        assert [t.amount for t in interest] == [300.0]

    def test_quarterly_rows_inside_the_statement_are_not_counted_twice(self, session):
        session.add(Transaction(
            type=TxType.P2P_INTEREST, account="Mintos Core P2P", amount=70.0, executed_at=datetime(2025, 3, 31),
            raw={"period_start": "2025-01-01T00:00:00", "period_end": "2025-03-31T00:00:00"},
        ))
        session.commit()
        self._import(session, ParsedMintosTransactionsExport(
            period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), income_total=300.0, cost_total=0.0,
            by_year={2025: (300.0, 0.0)}, transaction_count=10,
        ))

        assert compute_tax_year_summary(session, 2025).envelopes[0].interest == 300.0


def test_statement_split_by_year():
    from app.ingest.mintos_transactions_import import parse_mintos_transactions_export

    csv = (
        'Date,"ID de transaction :",Détails,Mouvement,Solde,Devise,"Type de paiement"\n'
        "2024-12-30 10:00:00,1,x,1.50,10,EUR,Intérêt perçu\n"
        "2024-12-30 10:00:01,2,x,-0.10,10,EUR,Tax withholding\n"
        "2025-01-02 10:00:00,3,x,2.25,10,EUR,Intérêt perçu\n"
    ).encode()
    parsed = parse_mintos_transactions_export(csv, "20250105-account-statement.csv")

    assert parsed.by_year == {2024: (1.5, -0.1), 2025: (2.25, 0.0)}
