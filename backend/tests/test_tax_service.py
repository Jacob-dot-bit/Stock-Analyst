"""Tests for the annual tax-year reconciliation summary
(`app/tax/service.py`, `GET /api/tax/summary`).

A reconciliation aid, not a tax calculator — every test here checks a
*fact about the imported data*, never a computed tax amount. See DEVLOG
"Decision 3u.60".
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Instrument, Transaction, TxType
from app.tax.service import (
    TaxEnvelopeKind,
    _classify_envelope,
    available_tax_years,
    compute_tax_year_summary,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = TestingSession()
    yield db
    db.close()


@pytest.fixture
def client(session):
    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _instrument(session, symbol: str, currency: str = "EUR") -> Instrument:
    instrument = Instrument(broker_symbol=symbol, currency=currency)
    session.add(instrument)
    session.commit()
    session.refresh(instrument)
    return instrument


def _tx(session, **kwargs) -> Transaction:
    kwargs.setdefault("executed_at", datetime(2026, 6, 1))
    tx = Transaction(**kwargs)
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


class TestClassifyEnvelope:
    @pytest.mark.parametrize(
        "account,expected",
        [
            ("PEA", TaxEnvelopeKind.PEA),
            ("Mintos Core P2P", TaxEnvelopeKind.P2P),
            ("Mintos ETF", TaxEnvelopeKind.CTO),
            ("Amundi PEG", TaxEnvelopeKind.EMPLOYEE_SAVINGS),
            ("Amundi PERCO", TaxEnvelopeKind.EMPLOYEE_SAVINGS),
            ("My Trades", TaxEnvelopeKind.CTO),
            ("Some unknown broker account", TaxEnvelopeKind.CTO),
        ],
    )
    def test_classification(self, account, expected):
        assert _classify_envelope(account) == expected


class TestComputeTaxYearSummary:
    def test_cto_dividend_withholding_realized_and_fee(self, session):
        aapl = _instrument(session, "AAPL.US", currency="USD")
        _tx(session, type=TxType.DIVIDEND, account="My Trades", amount=125.05, instrument_id=aapl.id)
        _tx(session, type=TxType.TAX, account="My Trades", amount=-18.76, instrument_id=aapl.id)
        _tx(session, type=TxType.CLOSED_TRADE, account="My Trades", amount=465.54)
        _tx(session, type=TxType.CLOSED_TRADE, account="My Trades", amount=-50.0)
        _tx(session, type=TxType.FEE, account="My Trades", amount=-427.59)
        _tx(session, type=TxType.INTEREST, account="My Trades", amount=3.5)

        summary = compute_tax_year_summary(session, 2026)
        cto = next(e for e in summary.envelopes if e.account == "My Trades")

        assert cto.envelope_kind == TaxEnvelopeKind.CTO
        assert cto.dividends_gross == 125.05
        assert cto.dividends_withholding == -18.76
        assert cto.realized_gains == 465.54
        assert cto.realized_losses == -50.0
        assert cto.fees == -427.59
        assert cto.interest == 3.5
        assert cto.status == "to_reconcile"
        assert cto.notes == []  # no PEA/employee-savings notes, no unmatched sales

    def test_pea_with_no_withdrawal_is_flagged_not_taxed(self, session):
        _tx(session, type=TxType.BUY, account="PEA", amount=-3294.17)
        _tx(session, type=TxType.DIVIDEND, account="PEA", amount=20.20)
        _tx(session, type=TxType.DEPOSIT, account="PEA", amount=3319.0)

        summary = compute_tax_year_summary(session, 2026)
        pea = next(e for e in summary.envelopes if e.account == "PEA")

        assert pea.envelope_kind == TaxEnvelopeKind.PEA
        assert pea.dividends_gross == 20.20
        assert pea.withdrawals is None
        codes = [n.code for n in pea.notes]
        assert "taxPrep.noWithdrawalDetected" in codes
        assert "taxPrep.withdrawalDetected" not in codes

    def test_pea_with_withdrawal_is_flagged_for_review(self, session):
        _tx(session, type=TxType.WITHDRAWAL, account="PEA", amount=-5000.0)

        summary = compute_tax_year_summary(session, 2026)
        pea = next(e for e in summary.envelopes if e.account == "PEA")

        codes = [n.code for n in pea.notes]
        assert "taxPrep.withdrawalDetected" in codes
        assert "taxPrep.noWithdrawalDetected" not in codes
        # The withdrawal amount is surfaced, never a tax figure derived from it.
        note = next(n for n in pea.notes if n.code == "taxPrep.withdrawalDetected")
        assert note.params["amount"] == 5000.0

    def test_mintos_p2p_interest_and_fees(self, session):
        _tx(session, type="P2P_INTEREST", account="Mintos Core P2P", amount=1868.14)
        _tx(session, type="P2P_FEE", account="Mintos Core P2P", amount=-113.33)
        _tx(session, type="P2P_INVESTMENT", account="Mintos Core P2P", amount=10012.28)

        summary = compute_tax_year_summary(session, 2026)
        p2p = next(e for e in summary.envelopes if e.account == "Mintos Core P2P")

        assert p2p.envelope_kind == TaxEnvelopeKind.P2P
        assert p2p.interest == 1868.14
        assert p2p.fees == -113.33
        assert p2p.status == "to_reconcile"
        # P2P_INVESTMENT is an internal capital movement, never summed as income.
        assert p2p.interest != 1868.14 + 10012.28

    def test_mintos_etf_sale_without_realized_trade_is_never_estimated(self, session):
        _tx(session, type=TxType.BUY, account="Mintos ETF", amount=-5049.99)
        _tx(session, type=TxType.SELL, account="Mintos ETF", amount=5497.65)

        summary = compute_tax_year_summary(session, 2026)
        etf = next(e for e in summary.envelopes if e.account == "Mintos ETF")

        assert etf.realized_gains is None
        assert etf.realized_losses is None
        assert etf.unmatched_sales_count == 1
        assert etf.unmatched_sales_amount == 5497.65
        codes = [n.code for n in etf.notes]
        assert "taxPrep.unmatchedSales" in codes

    def test_a_closed_trade_account_never_double_counts_its_sells_as_unmatched(self, session):
        """`My Trades` legitimately has raw SELL rows *and* CLOSED_TRADE
        rows for the same closed positions — since the broker's own
        CLOSED_TRADE already carries the real gain, the raw SELL must not
        also be flagged as an "unmatched sale needing FIFO"."""
        _tx(session, type=TxType.SELL, account="My Trades", amount=17137.91)
        _tx(session, type=TxType.CLOSED_TRADE, account="My Trades", amount=465.54)

        summary = compute_tax_year_summary(session, 2026)
        cto = next(e for e in summary.envelopes if e.account == "My Trades")

        assert cto.unmatched_sales_count == 0
        assert "taxPrep.unmatchedSales" not in [n.code for n in cto.notes]

    def test_amundi_other_flows_shown_but_never_counted_as_taxable_activity(self, session):
        _tx(session, type=TxType.OTHER, account="Amundi PEG", amount=4000.0, comment="versements_volontaires")
        _tx(session, type=TxType.OTHER, account="Amundi PEG", amount=1986.6, comment="abondement_net")

        summary = compute_tax_year_summary(session, 2026)
        peg = next(e for e in summary.envelopes if e.account == "Amundi PEG")

        assert peg.envelope_kind == TaxEnvelopeKind.EMPLOYEE_SAVINGS
        assert len(peg.other_flows) == 2
        assert {f.label for f in peg.other_flows} == {"versements_volontaires", "abondement_net"}
        # Contributions are not tax-relevant activity by themselves.
        assert peg.status == "not_applicable"
        # The "no withdrawal" note already explains why nothing is
        # taxable — the generic "not applicable" note would just repeat it.
        assert [n.code for n in peg.notes] == ["taxPrep.noWithdrawalDetected"]

    def test_transactions_outside_the_year_are_excluded(self, session):
        _tx(session, type=TxType.DIVIDEND, account="My Trades", amount=100.0, executed_at=datetime(2025, 12, 31))
        _tx(session, type=TxType.DIVIDEND, account="My Trades", amount=50.0, executed_at=datetime(2026, 1, 1))

        summary_2025 = compute_tax_year_summary(session, 2025)
        summary_2026 = compute_tax_year_summary(session, 2026)

        assert next(e for e in summary_2025.envelopes if e.account == "My Trades").dividends_gross == 100.0
        assert next(e for e in summary_2026.envelopes if e.account == "My Trades").dividends_gross == 50.0

    def test_account_with_no_transactions_this_year_is_absent(self, session):
        _tx(session, type=TxType.DIVIDEND, account="My Trades", amount=10.0, executed_at=datetime(2024, 1, 1))
        summary = compute_tax_year_summary(session, 2026)
        assert summary.envelopes == []


class TestAvailableTaxYears:
    def test_returns_distinct_years_newest_first(self, session):
        _tx(session, type=TxType.DEPOSIT, account="My Trades", amount=100.0, executed_at=datetime(2024, 3, 1))
        _tx(session, type=TxType.DEPOSIT, account="My Trades", amount=100.0, executed_at=datetime(2026, 3, 1))
        _tx(session, type=TxType.DEPOSIT, account="My Trades", amount=100.0, executed_at=datetime(2025, 3, 1))
        assert available_tax_years(session) == [2026, 2025, 2024]

    def test_empty_when_no_dated_transactions(self, session):
        assert available_tax_years(session) == []


class TestTaxSummaryApi:
    def test_summary_endpoint_includes_disclaimer_and_never_a_rate(self, client, session):
        _tx(session, type=TxType.DIVIDEND, account="My Trades", amount=125.05)
        body = client.get("/api/tax/summary?year=2026").json()

        assert body["tax_year"] == 2026
        assert body["disclaimer"]["code"] == "taxPrep.disclaimer"
        envelope = body["envelopes"][0]
        assert envelope["dividends_gross"] == 125.05
        assert "rate" not in envelope
        assert "tax_due" not in envelope
        assert "pfu" not in str(body).lower()

    def test_years_endpoint(self, client, session):
        _tx(session, type=TxType.DEPOSIT, account="My Trades", amount=10.0, executed_at=datetime(2026, 1, 1))
        body = client.get("/api/tax/years").json()
        assert body["years"] == [2026]

    def test_csv_export(self, client, session):
        _tx(session, type=TxType.DIVIDEND, account="My Trades", amount=125.05)
        resp = client.get("/api/tax/summary.csv?year=2026")
        assert resp.status_code == 200
        assert "My Trades" in resp.text
        assert "125.05" in resp.text
