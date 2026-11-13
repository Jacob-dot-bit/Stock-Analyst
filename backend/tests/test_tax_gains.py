"""Gains on sales by the weighted average acquisition price (Step 3u.110).
Every symbol, account and amount here is made up."""

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
from app.tax.gains import Unmatched, capital_gains_by_year, compute_sale_gains, trade_units
from app.tax.service import compute_tax_year_summary


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield db
    db.close()


def _instrument(session, symbol: str, isin: str | None = None) -> Instrument:
    instrument = Instrument(broker_symbol=symbol, isin=isin, currency="EUR")
    session.add(instrument)
    session.commit()
    return instrument


def _trade(session, instrument, kind, amount, when, account="Broker A", quantity=None, comment=None):
    tx = Transaction(
        type=kind,
        account=account,
        instrument_id=instrument.id if instrument else None,
        amount=amount,
        quantity=quantity,
        comment=comment,
        executed_at=when,
    )
    session.add(tx)
    session.commit()
    return tx


def _all_cto(_account: str) -> bool:
    return True


class TestUnits:
    @pytest.mark.parametrize(
        "comment,expected",
        [
            ("OPEN BUY 2 @ 175.08", 2.0),
            ("CLOSE BUY 2/5 @ 180.00", 2.0),
            ("OPEN BUY 0,5 @ 99.10", 0.5),
            ("Some other comment", None),
        ],
    )
    def test_from_comment(self, comment, expected):
        assert trade_units(Transaction(type=TxType.BUY, comment=comment)) == expected

    def test_stored_quantity_wins(self):
        assert trade_units(Transaction(type=TxType.SELL, quantity=-3.0, comment="CLOSE BUY 2 @ 1")) == 3.0


class TestWeightedAverage:
    def test_average_runs_over_both_purchases(self, session):
        etf = _instrument(session, "ETF1")
        _trade(session, etf, TxType.BUY, -1000.0, datetime(2024, 1, 10), quantity=10)
        _trade(session, etf, TxType.BUY, -1300.0, datetime(2024, 3, 10), quantity=10)
        # Average 115 a unit: 5 units sold for 700 → gain 125.
        _trade(session, etf, TxType.SELL, 700.0, datetime(2024, 6, 1), quantity=-5)
        # 15 units left at 115 → 1725; 15 sold for 1500 → loss 225.
        _trade(session, etf, TxType.SELL, 1500.0, datetime(2025, 2, 1), quantity=-15)

        sales = compute_sale_gains(session, _all_cto)

        assert [(s.cost, s.gain) for s in sales] == [(575.0, 125.0), (1725.0, -225.0)]

    def test_units_read_from_the_broker_comment(self, session):
        share = _instrument(session, "ABC.US")
        _trade(session, share, TxType.BUY, -350.0, datetime(2024, 1, 5), comment="OPEN BUY 2 @ 175.00")
        _trade(session, share, TxType.BUY, -540.0, datetime(2024, 2, 5), comment="OPEN BUY 3 @ 180.00")
        _trade(session, share, TxType.SELL, 400.0, datetime(2024, 4, 5), comment="CLOSE BUY 2/5 @ 200.00")

        (sale,) = compute_sale_gains(session, _all_cto)

        assert sale.units == 2.0
        assert sale.cost == 356.0  # 890 / 5 × 2
        assert sale.gain == 44.0

    def test_same_isin_at_two_brokers_is_one_holding(self, session):
        at_a = _instrument(session, "WRLD.DE", isin="XX0000000001")
        at_b = _instrument(session, "WRLD-B", isin="XX0000000001")
        _trade(session, at_a, TxType.BUY, -1000.0, datetime(2024, 1, 1), account="Broker A", quantity=10)
        _trade(session, at_b, TxType.BUY, -2000.0, datetime(2024, 2, 1), account="Broker B", quantity=10)
        _trade(session, at_b, TxType.SELL, 1800.0, datetime(2024, 5, 1), account="Broker B", quantity=-10)

        (sale,) = compute_sale_gains(session, _all_cto)

        # Average over both accounts: 150 a unit, not Broker B's own 200.
        assert sale.cost == 1500.0
        assert sale.gain == 300.0

    def test_excluded_accounts_are_left_out(self, session):
        etf = _instrument(session, "ETF1")
        _trade(session, etf, TxType.BUY, -500.0, datetime(2024, 1, 1), account="PEA", quantity=5)
        _trade(session, etf, TxType.SELL, 600.0, datetime(2024, 2, 1), account="PEA", quantity=-5)

        assert compute_sale_gains(session, lambda a: a != "PEA") == []


class TestNeverGuessed:
    def test_sale_before_any_purchase_on_file(self, session):
        etf = _instrument(session, "ETF1")
        _trade(session, etf, TxType.SELL, 500.0, datetime(2024, 1, 1), quantity=-5)

        (sale,) = compute_sale_gains(session, _all_cto)

        assert not sale.matched
        assert sale.unmatched_reason == Unmatched.NO_PURCHASE

    def test_selling_more_than_bought_breaks_the_holding(self, session):
        etf = _instrument(session, "ETF1")
        _trade(session, etf, TxType.BUY, -100.0, datetime(2024, 1, 1), quantity=1)
        _trade(session, etf, TxType.SELL, 600.0, datetime(2024, 2, 1), quantity=-5)
        _trade(session, etf, TxType.BUY, -100.0, datetime(2024, 3, 1), quantity=1)
        _trade(session, etf, TxType.SELL, 110.0, datetime(2024, 4, 1), quantity=-1)

        reasons = [s.unmatched_reason for s in compute_sale_gains(session, _all_cto)]

        assert reasons == [Unmatched.INCOMPLETE_HISTORY, Unmatched.INCOMPLETE_HISTORY]

    def test_purchase_without_units(self, session):
        etf = _instrument(session, "ETF1")
        _trade(session, etf, TxType.BUY, -100.0, datetime(2024, 1, 1))
        _trade(session, etf, TxType.SELL, 120.0, datetime(2024, 2, 1), quantity=-1)

        (sale,) = compute_sale_gains(session, _all_cto)
        assert sale.unmatched_reason == Unmatched.INCOMPLETE_HISTORY

    def test_sale_without_units_or_security(self, session):
        etf = _instrument(session, "ETF1")
        _trade(session, etf, TxType.BUY, -100.0, datetime(2024, 1, 1), quantity=1)
        _trade(session, etf, TxType.SELL, 120.0, datetime(2024, 2, 1))
        _trade(session, None, TxType.SELL, 50.0, datetime(2024, 3, 1))

        reasons = [s.unmatched_reason for s in compute_sale_gains(session, _all_cto)]
        assert reasons == [Unmatched.NO_UNITS, Unmatched.NO_INSTRUMENT]


class TestYears:
    def test_loss_carried_forward_oldest_first(self, session):
        etf = _instrument(session, "ETF1")
        _trade(session, etf, TxType.BUY, -3000.0, datetime(2021, 1, 1), quantity=30)
        _trade(session, etf, TxType.SELL, 800.0, datetime(2021, 6, 1), quantity=-10)  # −200
        _trade(session, etf, TxType.SELL, 900.0, datetime(2022, 6, 1), quantity=-10)  # −100
        _trade(session, etf, TxType.SELL, 1250.0, datetime(2024, 6, 1), quantity=-10)  # +250

        years = capital_gains_by_year(compute_sale_gains(session, _all_cto))

        assert years[2021].net == -200.0
        assert years[2022].losses_carried_in == {2021: 200.0}
        assert years[2023].losses_carried_out == {2021: 200.0, 2022: 100.0}
        assert years[2024].losses_used == 250.0
        assert years[2024].taxable_net == 0.0
        assert years[2024].losses_carried_out == {2022: 50.0}

    def test_loss_expires_after_ten_years(self, session):
        etf = _instrument(session, "ETF1")
        _trade(session, etf, TxType.BUY, -2000.0, datetime(2010, 1, 1), quantity=20)
        _trade(session, etf, TxType.SELL, 900.0, datetime(2010, 6, 1), quantity=-10)  # −100
        _trade(session, etf, TxType.SELL, 1100.0, datetime(2021, 6, 1), quantity=-10)  # +100

        years = capital_gains_by_year(compute_sale_gains(session, _all_cto))

        assert years[2020].losses_carried_out == {2010: 100.0}
        assert years[2021].losses_carried_in == {}
        assert years[2021].taxable_net == 100.0

    def test_unmatched_sales_are_counted_not_summed(self, session):
        etf = _instrument(session, "ETF1")
        _trade(session, etf, TxType.SELL, 500.0, datetime(2024, 1, 1), quantity=-5)

        year = capital_gains_by_year(compute_sale_gains(session, _all_cto))[2024]
        assert (year.unmatched_sales, year.matched_sales, year.net) == (1, 0, 0.0)


class TestSummary:
    def _history(self, session):
        etf = _instrument(session, "ETF1")
        _trade(session, etf, TxType.BUY, -1000.0, datetime(2023, 1, 1), account="Broker A", quantity=10)
        _trade(session, etf, TxType.SELL, 600.0, datetime(2024, 3, 1), account="Broker A", quantity=-5)
        _trade(session, etf, TxType.SELL, 300.0, datetime(2024, 4, 1), account="Broker A", quantity=-3)
        other = _instrument(session, "OTHER")
        _trade(session, other, TxType.SELL, 250.0, datetime(2024, 5, 1), account="Broker A", quantity=-1)
        _trade(session, etf, TxType.SELL, 900.0, datetime(2024, 6, 1), account="PEA", quantity=-9)

    def test_envelope_carries_average_price_gains(self, session):
        self._history(session)

        summary = compute_tax_year_summary(session, 2024)
        broker = next(e for e in summary.envelopes if e.account == "Broker A")

        assert broker.pmp_gains == 100.0
        assert broker.pmp_losses is None
        assert broker.pmp_matched_sales == 2
        assert broker.unmatched_sales_count == 1
        assert broker.unmatched_sales_amount == 250.0
        assert broker.unmatched_reasons == {Unmatched.NO_PURCHASE: 1}
        # A PEA sale is not taxed as it happens: nothing missing there.
        pea = next(e for e in summary.envelopes if e.account == "PEA")
        assert pea.unmatched_sales_count == 0

    def test_year_block(self, session):
        self._history(session)

        gains = compute_tax_year_summary(session, 2024).capital_gains

        assert gains.net == 100.0
        assert gains.matched_sales == 2
        assert gains.unmatched_sales == 1
        assert gains.taxable_net == 100.0

    def test_endpoint(self, session):
        self._history(session)

        def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as client:
                body = client.get("/api/tax/summary?year=2024").json()
        finally:
            app.dependency_overrides.clear()

        assert body["capital_gains"]["taxable_net"] == 100.0
        assert [s["gain"] for s in body["sales"]] == [100.0, 0.0, None]
        assert body["sales"][2]["unmatched_reason"] == "no_purchase"
        broker = next(e for e in body["envelopes"] if e["account"] == "Broker A")
        assert broker["pmp_gains"] == 100.0
