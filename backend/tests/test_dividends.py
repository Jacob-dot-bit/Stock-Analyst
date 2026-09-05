"""Tests for the dividends feature: reconciliation service and API.

Descriptive only — covers the reconciliation hierarchy (account, instrument,
nearest timestamp within a window), the "absence of withholding is not an
anomaly" rule, the trade-tax exclusion (French FTT / UK stamp duty share
`TxType.TAX` with genuine dividend withholding but must never appear here),
and that summary totals are computed from raw transactions rather than by
summing matched pairs.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dividends.service import dividend_detail, dividend_summary
from app.main import app
from app.models import Instrument, Transaction, TxType


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = TestingSession()
    yield db
    db.close()


def _instrument(session, symbol: str, currency: str = "USD") -> Instrument:
    instrument = Instrument(broker_symbol=symbol, currency=currency, country="US")
    session.add(instrument)
    session.commit()
    session.refresh(instrument)
    return instrument


WHT_RAW = {"Type": "Withholding tax"}


class TestReconciliation:
    def test_same_instant_pair_is_matched(self, session):
        aapl = _instrument(session, "AAPL.US")
        when = datetime(2026, 1, 15, 9, 0, 0)
        session.add_all(
            [
                Transaction(type=TxType.DIVIDEND, instrument_id=aapl.id, account="My Trades", executed_at=when, amount=10.0),
                Transaction(type=TxType.TAX, instrument_id=aapl.id, account="My Trades", executed_at=when, amount=-1.5, raw=WHT_RAW),
            ]
        )
        session.commit()

        rows = dividend_detail(session)
        assert len(rows) == 1
        assert rows[0].reconciliation_status == "matched"
        assert rows[0].gross == 10.0
        assert rows[0].withholding_tax == -1.5
        assert rows[0].net == 8.5

    def test_dividend_with_no_tax_is_no_withholding_not_flagged(self, session):
        aapl = _instrument(session, "AAPL.US")
        session.add(
            Transaction(type=TxType.DIVIDEND, instrument_id=aapl.id, account="PEA", executed_at=datetime(2026, 1, 1), amount=5.0)
        )
        session.commit()

        rows = dividend_detail(session)
        assert len(rows) == 1
        assert rows[0].reconciliation_status == "no_withholding"
        assert rows[0].gross == 5.0
        assert rows[0].withholding_tax is None
        assert rows[0].net == 5.0

    def test_orphan_tax_is_unmatched(self, session):
        aapl = _instrument(session, "AAPL.US")
        session.add(
            Transaction(type=TxType.TAX, instrument_id=aapl.id, account="My Trades", executed_at=datetime(2026, 1, 1), amount=-0.5, raw=WHT_RAW)
        )
        session.commit()

        rows = dividend_detail(session)
        assert len(rows) == 1
        assert rows[0].reconciliation_status == "unmatched_tax"
        assert rows[0].gross is None
        assert rows[0].withholding_tax == -0.5
        assert rows[0].net == -0.5

    def test_pair_within_window_matches_despite_different_days(self, session):
        aapl = _instrument(session, "AAPL.US")
        session.add_all(
            [
                Transaction(type=TxType.DIVIDEND, instrument_id=aapl.id, account="My Trades", executed_at=datetime(2026, 1, 1, 9, 0), amount=10.0),
                Transaction(type=TxType.TAX, instrument_id=aapl.id, account="My Trades", executed_at=datetime(2026, 1, 3, 9, 0), amount=-1.5, raw=WHT_RAW),
            ]
        )
        session.commit()

        rows = dividend_detail(session)
        matched = [r for r in rows if r.reconciliation_status == "matched"]
        assert len(matched) == 1
        assert matched[0].withholding_tax == -1.5

    def test_pair_outside_window_does_not_match(self, session):
        aapl = _instrument(session, "AAPL.US")
        session.add_all(
            [
                Transaction(type=TxType.DIVIDEND, instrument_id=aapl.id, account="My Trades", executed_at=datetime(2026, 1, 1, 9, 0), amount=10.0),
                Transaction(type=TxType.TAX, instrument_id=aapl.id, account="My Trades", executed_at=datetime(2026, 1, 10, 9, 0), amount=-1.5, raw=WHT_RAW),
            ]
        )
        session.commit()

        rows = dividend_detail(session)
        by_status = {r.reconciliation_status for r in rows}
        assert by_status == {"no_withholding", "unmatched_tax"}

    def test_multiple_same_day_pairs_match_nearest_not_first(self, session):
        """Real data has this exact shape: two dividend/tax pairs for the
        same instrument on the same day, a few seconds apart each. A naive
        "first available" match would pair the wrong tax to the wrong
        dividend; nearest-timestamp must not."""
        vici = _instrument(session, "VICI.US")
        t0 = datetime(2026, 7, 9, 9, 59, 5)
        session.add_all(
            [
                Transaction(type=TxType.TAX, instrument_id=vici.id, account="My Trades", executed_at=t0, amount=-0.06, raw=WHT_RAW),
                Transaction(type=TxType.DIVIDEND, instrument_id=vici.id, account="My Trades", executed_at=t0, amount=0.39),
                Transaction(type=TxType.TAX, instrument_id=vici.id, account="My Trades", executed_at=t0 + timedelta(seconds=2), amount=-0.07, raw=WHT_RAW),
                Transaction(type=TxType.DIVIDEND, instrument_id=vici.id, account="My Trades", executed_at=t0 + timedelta(seconds=2), amount=0.40),
            ]
        )
        session.commit()

        rows = dividend_detail(session)
        matched = {r.gross: r.withholding_tax for r in rows if r.reconciliation_status == "matched"}
        assert matched == {0.39: -0.06, 0.40: -0.07}

    def test_different_accounts_are_never_cross_matched(self, session):
        aapl = _instrument(session, "AAPL.US")
        when = datetime(2026, 1, 1, 9, 0)
        session.add_all(
            [
                Transaction(type=TxType.DIVIDEND, instrument_id=aapl.id, account="My Trades", executed_at=when, amount=10.0),
                Transaction(type=TxType.TAX, instrument_id=aapl.id, account="PEA", executed_at=when, amount=-1.5, raw=WHT_RAW),
            ]
        )
        session.commit()

        rows = dividend_detail(session)
        by_status = {r.reconciliation_status for r in rows}
        assert by_status == {"no_withholding", "unmatched_tax"}

    def test_no_instrument_rows_are_never_matched(self, session):
        """A manual entry with no symbol given is never paired, rather than
        risk matching it to an unrelated row purely on account and date."""
        when = datetime(2026, 1, 1, 9, 0)
        session.add_all(
            [
                Transaction(type=TxType.DIVIDEND, instrument_id=None, account="My Trades", executed_at=when, amount=10.0),
                Transaction(type=TxType.TAX, instrument_id=None, account="My Trades", executed_at=when, amount=-1.5, raw=WHT_RAW),
            ]
        )
        session.commit()

        rows = dividend_detail(session)
        by_status = {r.reconciliation_status for r in rows}
        assert by_status == {"no_withholding", "unmatched_tax"}


class TestTradeTaxExclusion:
    def test_french_ftt_never_appears(self, session):
        dsy = _instrument(session, "DSY.FR", currency="EUR")
        session.add(
            Transaction(
                type=TxType.TAX, instrument_id=dsy.id, account="PEA",
                executed_at=datetime(2026, 1, 1), amount=-0.08,
                raw={"Type": "Tax IFTT"},
            )
        )
        session.commit()
        assert dividend_detail(session) == []
        assert dividend_summary(session) == []

    def test_uk_stamp_duty_never_appears(self, session):
        bta = _instrument(session, "BTA.UK", currency="GBP")
        session.add(
            Transaction(
                type=TxType.TAX, instrument_id=bta.id, account="My Trades",
                executed_at=datetime(2026, 1, 1), amount=-0.07,
                raw={"Type": "Stamp duty"},
            )
        )
        session.commit()
        assert dividend_detail(session) == []
        assert dividend_summary(session) == []

    def test_manual_tax_row_with_no_raw_defaults_to_withholding(self, session):
        """A hand-entered TAX transaction (no `raw` at all — see
        `create_manual_transaction`) has no `Type` label to check against.
        It must default to counting as withholding rather than being
        silently dropped: the user's own choice to type it as TAX is the
        only signal available, and there is no manual-entry path for a
        trade tax (FTT/stamp duty only ever come from an import)."""
        aapl = _instrument(session, "AAPL.US")
        session.add(
            Transaction(type=TxType.TAX, instrument_id=aapl.id, account="My Trades", executed_at=datetime(2026, 1, 1), amount=-1.0, raw=None)
        )
        session.commit()
        rows = dividend_detail(session)
        assert len(rows) == 1
        assert rows[0].reconciliation_status == "unmatched_tax"

    def test_reclassification_withholding_still_counts(self, session):
        """Not tied to one specific dividend, but genuinely dividend-related
        (its own raw Type says so) — must still show up as an orphan
        withholding, not be silently dropped like a trade tax."""
        arcc = _instrument(session, "ARCC.US")
        session.add(
            Transaction(
                type=TxType.TAX, instrument_id=arcc.id, account="My Trades",
                executed_at=datetime(2026, 1, 1), amount=0.67,
                raw={"Type": "Withholding tax"},
            )
        )
        session.commit()
        rows = dividend_detail(session)
        assert len(rows) == 1
        assert rows[0].reconciliation_status == "unmatched_tax"


class TestSummaryAggregation:
    def test_totals_come_from_raw_rows_not_matched_pairs(self, session):
        """An orphan tax with no dividend in scope must still contribute to
        the year's withholding total — the summary must never be computed
        by summing only successfully-matched pairs."""
        aapl = _instrument(session, "AAPL.US")
        session.add(
            Transaction(type=TxType.TAX, instrument_id=aapl.id, account="My Trades", executed_at=datetime(2026, 3, 1), amount=-0.5, raw=WHT_RAW)
        )
        session.commit()

        summary = dividend_summary(session)
        assert len(summary) == 1
        assert summary[0].year == 2026
        assert summary[0].account == "My Trades"
        assert summary[0].gross == 0.0
        assert summary[0].withholding_tax == -0.5
        assert summary[0].payment_count == 0

    def test_grouped_by_year_and_account_separately(self, session):
        aapl = _instrument(session, "AAPL.US")
        session.add_all(
            [
                Transaction(type=TxType.DIVIDEND, instrument_id=aapl.id, account="My Trades", executed_at=datetime(2025, 6, 1), amount=10.0),
                Transaction(type=TxType.DIVIDEND, instrument_id=aapl.id, account="PEA", executed_at=datetime(2025, 6, 1), amount=20.0),
                Transaction(type=TxType.DIVIDEND, instrument_id=aapl.id, account="My Trades", executed_at=datetime(2026, 6, 1), amount=30.0),
            ]
        )
        session.commit()

        summary = {(r.year, r.account): r for r in dividend_summary(session)}
        assert summary[(2025, "My Trades")].gross == 10.0
        assert summary[(2025, "PEA")].gross == 20.0
        assert summary[(2026, "My Trades")].gross == 30.0
        assert summary[(2025, "My Trades")].payment_count == 1


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _seed(rows):
    session = next(app.dependency_overrides[get_db]())
    try:
        for row in rows:
            session.add(row)
        session.commit()
    finally:
        session.close()


class TestDividendsApi:
    def test_summary_endpoint(self, client):
        instrument = Instrument(broker_symbol="AAPL.US", currency="USD", country="US")
        _seed([instrument])
        _seed(
            [
                Transaction(
                    type=TxType.DIVIDEND, instrument_id=instrument.id, account="My Trades",
                    executed_at=datetime(2026, 1, 1), amount=10.0,
                )
            ]
        )
        body = client.get("/api/dividends/summary").json()
        assert body == [
            {"year": 2026, "account": "My Trades", "gross": 10.0, "withholding_tax": 0.0, "net": 10.0, "payment_count": 1}
        ]

    def test_detail_endpoint_filters_by_year_and_account(self, client):
        instrument = Instrument(broker_symbol="AAPL.US", currency="USD", country="US")
        _seed([instrument])
        _seed(
            [
                Transaction(type=TxType.DIVIDEND, instrument_id=instrument.id, account="My Trades", executed_at=datetime(2026, 1, 1), amount=10.0),
                Transaction(type=TxType.DIVIDEND, instrument_id=instrument.id, account="PEA", executed_at=datetime(2025, 1, 1), amount=20.0),
            ]
        )
        body = client.get("/api/dividends/detail", params={"year": 2026, "account": "My Trades"}).json()
        assert len(body) == 1
        assert body[0]["gross"] == 10.0
        assert body[0]["instrument"]["broker_symbol"] == "AAPL.US"

    def test_summary_csv_has_header_and_content_type(self, client):
        instrument = Instrument(broker_symbol="AAPL.US", currency="USD", country="US")
        _seed([instrument])
        _seed(
            [Transaction(type=TxType.DIVIDEND, instrument_id=instrument.id, account="My Trades", executed_at=datetime(2026, 1, 1), amount=10.0)]
        )
        response = client.get("/api/dividends/summary.csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "year,account,gross,withholding_tax,net,payment_count" in response.text

    def test_detail_csv_has_header_and_content_type(self, client):
        response = client.get("/api/dividends/detail.csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "executed_at,instrument,account,currency,gross,withholding_tax,net,reconciliation_status,comment" in response.text
