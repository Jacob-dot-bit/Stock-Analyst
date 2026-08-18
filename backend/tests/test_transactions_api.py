"""Tests for GET /api/transactions."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Instrument, Lot, LotType, Transaction, TxType
from app.routers.transactions import _closed_trade_effects, _fx_rates_from_raw


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


def _seed(client, rows):
    """Insert Transaction rows through the same overridden session the app
    uses — simplest way to seed data without a second engine that would not
    see the same in-memory database.
    """
    session = next(app.dependency_overrides[get_db]())
    try:
        for row in rows:
            session.add(row)
        session.commit()
    finally:
        session.close()


class TestListTransactions:
    def test_filters_by_type(self, client):
        _seed(
            client,
            [
                Transaction(type=TxType.DIVIDEND, amount=12.5, executed_at=datetime(2026, 3, 1)),
                Transaction(type=TxType.FEE, amount=-1.0, executed_at=datetime(2026, 3, 2)),
            ],
        )

        response = client.get("/api/transactions", params={"type": "DIVIDEND"})
        assert response.status_code == 200
        body = response.json()
        assert len(body["transactions"]) == 1
        assert body["transactions"][0]["type"] == "DIVIDEND"

    def test_summary_nets_dividends_against_withholding_tax(self, client):
        _seed(
            client,
            [
                Transaction(type=TxType.DIVIDEND, amount=100.0, executed_at=datetime(2026, 3, 1)),
                Transaction(type=TxType.TAX, amount=-15.0, executed_at=datetime(2026, 3, 1)),
                Transaction(type=TxType.FEE, amount=-2.0, executed_at=datetime(2026, 3, 1)),
                Transaction(type=TxType.CLOSED_TRADE, amount=42.0, executed_at=datetime(2026, 3, 1)),
            ],
        )

        summary = client.get("/api/transactions").json()["summary"]
        assert summary["total_dividends"] == 100.0
        assert summary["total_withholding_tax"] == -15.0
        assert summary["net_dividends"] == 85.0
        assert summary["total_fees"] == -2.0
        assert summary["total_realized_pl"] == 42.0

    def test_summary_excludes_trade_taxes_from_withholding(self, client):
        """A French FTT or UK stamp duty on a *trade* shares `TxType.TAX`
        with genuine dividend withholding but must not inflate this total —
        found live while building the Dividends view (DEVLOG "Decision
        3u.28"); this page's total must agree with that one's."""
        _seed(
            client,
            [
                Transaction(type=TxType.DIVIDEND, amount=100.0, executed_at=datetime(2026, 3, 1)),
                Transaction(type=TxType.TAX, amount=-15.0, executed_at=datetime(2026, 3, 1), raw={"Type": "Withholding tax"}),
                Transaction(type=TxType.TAX, amount=-0.5, executed_at=datetime(2026, 3, 2), raw={"Type": "Tax IFTT"}),
            ],
        )
        summary = client.get("/api/transactions").json()["summary"]
        assert summary["total_withholding_tax"] == -15.0
        assert summary["net_dividends"] == 85.0

    def test_summary_respects_the_same_filters_as_the_list(self, client):
        _seed(
            client,
            [
                Transaction(type=TxType.DIVIDEND, amount=100.0, executed_at=datetime(2025, 3, 1)),
                Transaction(type=TxType.DIVIDEND, amount=50.0, executed_at=datetime(2026, 3, 1)),
            ],
        )

        summary = client.get(
            "/api/transactions", params={"start_date": "2026-01-01"}
        ).json()["summary"]
        assert summary["total_dividends"] == 50.0

    def test_account_column_is_returned_as_is(self, client):
        """`account` is a real column (DEVLOG "Decision 3u.28") — no
        recovery from `raw` needed on the live read path."""
        _seed(
            client,
            [Transaction(type=TxType.DIVIDEND, amount=10.0, account="My Trades")],
        )
        body = client.get("/api/transactions").json()
        assert body["transactions"][0]["account"] == "My Trades"

    def test_account_filter_narrows_results(self, client):
        _seed(
            client,
            [
                Transaction(type=TxType.DIVIDEND, amount=10.0, account="My Trades"),
                Transaction(type=TxType.DIVIDEND, amount=20.0, account="PEA"),
            ],
        )
        body = client.get("/api/transactions", params={"account": "PEA"}).json()
        assert len(body["transactions"]) == 1
        assert body["transactions"][0]["amount"] == 20.0

    def test_no_account_yields_none_rather_than_erroring(self, client):
        _seed(client, [Transaction(type=TxType.DEPOSIT, amount=500.0, account=None)])
        body = client.get("/api/transactions").json()
        assert body["transactions"][0]["account"] is None

    def test_instrument_id_filter_narrows_results(self, client):
        """The per-position detail panel's "related transactions" section
        scopes this endpoint to one instrument — the same `instrument_id`
        query-param convention `/api/dividends/detail` and
        `/api/corporate-actions` already use."""
        aapl = Instrument(broker_symbol="AAPL.US", currency="USD", country="US")
        msft = Instrument(broker_symbol="MSFT.US", currency="USD", country="US")
        _seed(client, [aapl, msft])
        _seed(
            client,
            [
                Transaction(type=TxType.DIVIDEND, amount=10.0, instrument_id=aapl.id),
                Transaction(type=TxType.DIVIDEND, amount=20.0, instrument_id=msft.id),
                Transaction(type=TxType.DEPOSIT, amount=500.0, instrument_id=None),
            ],
        )
        body = client.get("/api/transactions", params={"instrument_id": aapl.id}).json()
        assert len(body["transactions"]) == 1
        assert body["transactions"][0]["amount"] == 10.0


class TestCreateManualTransaction:
    def test_creates_a_dividend_with_account_recoverable_afterward(self, client):
        response = client.post(
            "/api/transactions",
            json={
                "type": "DIVIDEND",
                "amount": 12.5,
                "currency": "EUR",
                "account": "My Trades",
                "comment": "Manual entry",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["type"] == "DIVIDEND"
        assert body["amount"] == 12.5
        assert body["account"] == "My Trades"

        listed = client.get("/api/transactions").json()["transactions"]
        assert len(listed) == 1
        assert listed[0]["account"] == "My Trades"

    def test_links_to_an_instrument_by_symbol(self, client):
        response = client.post(
            "/api/transactions",
            json={"type": "DIVIDEND", "amount": 1.5, "broker_symbol": "AAPL.US"},
        )
        assert response.status_code == 201
        assert response.json()["instrument"]["broker_symbol"] == "AAPL.US"

    def test_trade_types_are_rejected(self, client):
        for tx_type in ("BUY", "SELL", "CLOSED_TRADE"):
            response = client.post("/api/transactions", json={"type": tx_type, "amount": 1.0})
            assert response.status_code == 400, tx_type

    def test_defaults_executed_at_to_now_when_not_given(self, client):
        response = client.post("/api/transactions", json={"type": "OTHER", "amount": 1.0})
        assert response.status_code == 201
        assert response.json()["executed_at"] is not None


class TestUpdateTransaction:
    def test_updates_only_the_provided_fields(self, client):
        _seed(client, [Transaction(id=1, type=TxType.FEE, amount=-2.0, comment="original")])

        response = client.patch("/api/transactions/1", json={"amount": -3.5})
        assert response.status_code == 200
        body = response.json()
        assert body["amount"] == -3.5
        assert body["comment"] == "original"  # untouched

    def test_updates_account_without_losing_other_raw_keys(self, client):
        _seed(
            client,
            [
                Transaction(
                    id=1,
                    type=TxType.DIVIDEND,
                    amount=1.0,
                    raw={"Product": "My Trades", "Comment": "ASML.NL EUR 1.00/ SHR"},
                )
            ],
        )

        response = client.patch("/api/transactions/1", json={"account": "PEA"})
        assert response.status_code == 200
        body = response.json()
        assert body["account"] == "PEA"

        listed = client.get("/api/transactions").json()["transactions"][0]
        assert listed["account"] == "PEA"

    def test_rejects_retyping_into_a_trade_type(self, client):
        _seed(client, [Transaction(id=1, type=TxType.FEE, amount=-2.0)])
        response = client.patch("/api/transactions/1", json={"type": "BUY"})
        assert response.status_code == 400

    def test_editing_an_existing_trade_row_still_works_for_other_fields(self, client):
        """The type restriction only blocks *retyping into* a trade type — an
        existing CLOSED_TRADE row (from import) can still have its amount or
        comment corrected."""
        _seed(client, [Transaction(id=1, type=TxType.CLOSED_TRADE, amount=42.0)])
        response = client.patch("/api/transactions/1", json={"amount": 45.0})
        assert response.status_code == 200
        assert response.json()["amount"] == 45.0

    def test_404_for_unknown_id(self, client):
        response = client.patch("/api/transactions/999", json={"amount": 1.0})
        assert response.status_code == 404


class TestDeleteTransaction:
    def test_deletes_a_transaction(self, client):
        _seed(client, [Transaction(id=1, type=TxType.FEE, amount=-2.0)])

        response = client.delete("/api/transactions/1")
        assert response.status_code == 204

        assert client.get("/api/transactions").json()["transactions"] == []

    def test_404_for_unknown_id(self, client):
        response = client.delete("/api/transactions/999")
        assert response.status_code == 404


class TestFxRatesFromRaw:
    """See DEVLOG "Decision 3p.1"."""

    def test_parses_english_headers(self):
        raw = {"Open Conversion Rate": 0.9, "Close Conversion Rate": 0.95}
        assert _fx_rates_from_raw(raw) == (0.9, 0.95)

    def test_parses_french_headers(self):
        raw = {"Taux de change ouverture": 0.9, "Taux de change fermeture": 0.95}
        assert _fx_rates_from_raw(raw) == (0.9, 0.95)

    def test_no_raw_yields_none_rather_than_erroring(self):
        assert _fx_rates_from_raw(None) == (None, None)

    def test_raw_without_conversion_columns_yields_none(self):
        assert _fx_rates_from_raw({"Product": "My Trades"}) == (None, None)


class TestClosedTradeEffects:
    """See DEVLOG "Decision 3p.1"."""

    def test_reconciles_exactly_against_the_real_amount(self):
        transaction = Transaction(
            type=TxType.CLOSED_TRADE,
            quantity=10.0,
            price=110.0,
            amount=120.0,
            raw={"Open Conversion Rate": 0.9, "Close Conversion Rate": 0.95},
        )
        lot = Lot(instrument_id=1, lot_type=LotType.CLOSED, quantity=10.0, open_price=100.0)

        instrument_effect, currency_effect = _closed_trade_effects(transaction, lot)

        # (110 - 100) * 10 * 0.9
        assert instrument_effect == 90.0
        assert currency_effect == 30.0
        assert instrument_effect + currency_effect == transaction.amount

    def test_none_when_no_matching_lot(self):
        transaction = Transaction(type=TxType.CLOSED_TRADE, quantity=10.0, price=110.0, amount=120.0)
        assert _closed_trade_effects(transaction, None) == (None, None)

    def test_none_when_raw_has_no_conversion_rate(self):
        transaction = Transaction(
            type=TxType.CLOSED_TRADE, quantity=10.0, price=110.0, amount=120.0, raw={}
        )
        lot = Lot(instrument_id=1, lot_type=LotType.CLOSED, quantity=10.0, open_price=100.0)
        assert _closed_trade_effects(transaction, lot) == (None, None)

    def test_none_when_open_rate_is_zero(self):
        transaction = Transaction(
            type=TxType.CLOSED_TRADE,
            quantity=10.0,
            price=110.0,
            amount=120.0,
            raw={"Open Conversion Rate": 0.0, "Close Conversion Rate": 0.95},
        )
        lot = Lot(instrument_id=1, lot_type=LotType.CLOSED, quantity=10.0, open_price=100.0)
        assert _closed_trade_effects(transaction, lot) == (None, None)


class TestClosedTradeEffectsEndToEnd:
    """The same split, through the real `GET /api/transactions` response."""

    def test_a_closed_trade_shows_the_split_a_dividend_does_not(self, client):
        session = next(app.dependency_overrides[get_db]())
        try:
            instrument = Instrument(broker_symbol="AAPL.US")
            session.add(instrument)
            session.flush()
            session.add(
                Transaction(
                    id=1,
                    type=TxType.CLOSED_TRADE,
                    instrument_id=instrument.id,
                    external_id="pos-1",
                    quantity=10.0,
                    price=110.0,
                    amount=120.0,
                    raw={"Open Conversion Rate": 0.9, "Close Conversion Rate": 0.95},
                )
            )
            session.add(
                Lot(
                    instrument_id=instrument.id,
                    lot_type=LotType.CLOSED,
                    external_id="pos-1",
                    quantity=10.0,
                    open_price=100.0,
                )
            )
            session.add(Transaction(id=2, type=TxType.DIVIDEND, amount=5.0))
            # A CFD close: XTB leaves both conversion-rate columns blank for
            # these, so it stays unresolved even though it's a real closed
            # trade — must count toward closed_trades_total but not
            # closed_trades_with_effect. See DEVLOG "Decision 3p.1".
            session.add(
                Transaction(
                    id=3,
                    type=TxType.CLOSED_TRADE,
                    external_id="pos-cfd",
                    quantity=1.0,
                    price=50.0,
                    amount=10.0,
                    raw={"Open Conversion Rate": "", "Close Conversion Rate": ""},
                )
            )
            session.commit()
        finally:
            session.close()

        body = client.get("/api/transactions").json()
        by_id = {t["id"]: t for t in body["transactions"]}

        assert by_id[1]["instrument_effect"] == 90.0
        assert by_id[1]["currency_effect"] == 30.0
        assert by_id[2]["instrument_effect"] is None
        assert by_id[2]["currency_effect"] is None
        assert by_id[3]["instrument_effect"] is None
        assert by_id[3]["currency_effect"] is None

        assert body["summary"]["total_instrument_effect"] == 90.0
        assert body["summary"]["total_currency_effect"] == 30.0
        assert body["summary"]["closed_trades_with_effect"] == 1
        assert body["summary"]["closed_trades_total"] == 2


class TestBackfillAccounts:
    def test_recovers_account_from_raw_english_header(self, client):
        _seed(
            client,
            [Transaction(type=TxType.DIVIDEND, amount=10.0, raw={"Product": "My Trades"})],
        )
        response = client.post("/api/transactions/backfill-accounts")
        assert response.status_code == 200
        assert response.json() == {"checked": 1, "updated": 1}

        listed = client.get("/api/transactions").json()["transactions"]
        assert listed[0]["account"] == "My Trades"

    def test_recovers_account_from_raw_french_header(self, client):
        """The literal header text varies by export language — "Produit" on a
        French export must resolve the same way "Product" does on an English
        one, via normalised alias matching, not a hardcoded key."""
        _seed(
            client,
            [Transaction(type=TxType.DIVIDEND, amount=10.0, raw={"Produit": "PEA"})],
        )
        client.post("/api/transactions/backfill-accounts")
        listed = client.get("/api/transactions").json()["transactions"]
        assert listed[0]["account"] == "PEA"

    def test_row_with_no_recoverable_value_stays_null_not_guessed(self, client):
        _seed(client, [Transaction(type=TxType.DEPOSIT, amount=500.0, raw=None)])
        response = client.post("/api/transactions/backfill-accounts")
        assert response.json() == {"checked": 1, "updated": 0}
        assert client.get("/api/transactions").json()["transactions"][0]["account"] is None

    def test_rows_that_already_have_an_account_are_not_recounted(self, client):
        _seed(
            client,
            [
                Transaction(type=TxType.DIVIDEND, amount=10.0, account="My Trades"),
                Transaction(type=TxType.DIVIDEND, amount=20.0, raw={"Product": "PEA"}),
            ],
        )
        response = client.post("/api/transactions/backfill-accounts")
        assert response.json() == {"checked": 1, "updated": 1}

    def test_is_safe_to_run_twice(self, client):
        _seed(
            client,
            [Transaction(type=TxType.DIVIDEND, amount=10.0, raw={"Product": "My Trades"})],
        )
        client.post("/api/transactions/backfill-accounts")
        second = client.post("/api/transactions/backfill-accounts")
        assert second.json() == {"checked": 0, "updated": 0}
