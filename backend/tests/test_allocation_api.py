"""End-to-end tests for the target-allocation endpoints.

Descriptive only — covers the union-of-held-and-targeted invariant (a
configured target for a category currently held at 0% must still appear),
the under/over/within/no_target state machine, and that a sell is never
suggested for an over-target category.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import FxRate, Instrument, Position, PriceBar


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


def _seed(client, rows):
    session = next(app.dependency_overrides[get_db]())
    try:
        for row in rows:
            session.add(row)
        session.commit()
        for row in rows:
            session.refresh(row)
    finally:
        session.close()
    return rows


def held_instrument(client, symbol: str, category: str, quantity: float, price: float) -> Instrument:
    """A held instrument priced today, in EUR (so FX conversion is a no-op —
    same convention `test_scoring_api.py` uses)."""
    instrument = Instrument(broker_symbol=symbol, category=category, currency="EUR", country="FR")
    _seed(client, [instrument])
    bar = PriceBar(instrument_id=instrument.id, bar_date=date.today() - timedelta(days=1), close=price, provider="test")
    position = Position(instrument_id=instrument.id, source="MANUAL", quantity=quantity, avg_price=price)
    _seed(client, [bar, position])
    return instrument


class TestGetAllocation:
    def test_empty_portfolio_returns_empty_list(self, client):
        assert client.get("/api/portfolio/allocation").json() == []

    def test_held_category_with_no_target_reports_no_target(self, client):
        held_instrument(client, "AAA.FR", "STOCK", quantity=10, price=100.0)  # 1000 EUR

        rows = client.get("/api/portfolio/allocation").json()

        assert len(rows) == 1
        assert rows[0]["category"] == "STOCK"
        assert rows[0]["current_value"] == pytest.approx(1000.0)
        assert rows[0]["current_pct"] == pytest.approx(100.0)
        assert rows[0]["state"] == "no_target"
        assert rows[0]["min_pct"] is None
        assert rows[0]["amount_to_reach_min"] is None

    def test_under_target_reports_gap_and_amount(self, client):
        # STOCK 1000, ETF 0 — total 1000. Target ETF 30-40%.
        held_instrument(client, "AAA.FR", "STOCK", quantity=10, price=100.0)
        client.put("/api/portfolio/allocation/ETF", json={"min_pct": 30, "max_pct": 40})

        rows = {r["category"]: r for r in client.get("/api/portfolio/allocation").json()}

        assert "ETF" in rows  # configured target for an unheld category still appears
        etf = rows["ETF"]
        assert etf["current_value"] == pytest.approx(0.0)
        assert etf["current_pct"] == pytest.approx(0.0)
        assert etf["state"] == "under"
        assert etf["gap_pct"] == pytest.approx(30.0)
        # 30% of the 1000 EUR total, since ETF currently holds nothing.
        assert etf["amount_to_reach_min"] == pytest.approx(300.0)

    def test_over_target_reports_gap_with_no_amount_suggested(self, client):
        held_instrument(client, "AAA.FR", "STOCK", quantity=10, price=100.0)  # 100% STOCK
        client.put("/api/portfolio/allocation/STOCK", json={"min_pct": 20, "max_pct": 50})

        row = client.get("/api/portfolio/allocation").json()[0]

        assert row["state"] == "over"
        assert row["gap_pct"] == pytest.approx(50.0)
        assert row["amount_to_reach_min"] is None  # never a sell suggestion

    def test_within_target_reports_zero_gap(self, client):
        held_instrument(client, "AAA.FR", "STOCK", quantity=10, price=100.0)  # 100% STOCK
        client.put("/api/portfolio/allocation/STOCK", json={"min_pct": 50, "max_pct": 100})

        row = client.get("/api/portfolio/allocation").json()[0]

        assert row["state"] == "within"
        assert row["gap_pct"] == 0
        assert row["amount_to_reach_min"] is None

    def test_foreign_currency_position_is_fx_converted(self, client):
        """Confirms the allocation calc actually goes through the same
        FX-conversion path `get_breakdown` uses, not just something that
        happens to work when everything is coincidentally in EUR (every
        other test in this file uses EUR instruments for simplicity)."""
        # A known, non-1.0 rate seeded directly — FX providers are never
        # called in tests (no real network), same convention
        # `test_history_service.py` already uses for this.
        session = next(app.dependency_overrides[get_db]())
        try:
            session.add(FxRate(currency="USD", base_currency="EUR", rate_date=datetime.now(UTC).date(), rate=0.5))
            session.commit()
        finally:
            session.close()

        instrument = Instrument(broker_symbol="BBB.US", category="STOCK", currency="USD", country="US")
        _seed(client, [instrument])
        bar = PriceBar(instrument_id=instrument.id, bar_date=date.today() - timedelta(days=1), close=100.0, provider="test")
        position = Position(instrument_id=instrument.id, source="MANUAL", quantity=10, avg_price=100.0)
        _seed(client, [bar, position])

        row = client.get("/api/portfolio/allocation").json()[0]

        # 10 shares * 100 USD * 0.5 EUR/USD = 500 EUR, not 1000.
        assert row["current_value"] == pytest.approx(500.0)


class TestSetAllocationTarget:
    def test_rejects_min_greater_than_max(self, client):
        response = client.put("/api/portfolio/allocation/ETF", json={"min_pct": 50, "max_pct": 30})
        assert response.status_code == 422

    def test_upsert_replaces_existing_target(self, client):
        client.put("/api/portfolio/allocation/ETF", json={"min_pct": 20, "max_pct": 30})
        response = client.put("/api/portfolio/allocation/ETF", json={"min_pct": 25, "max_pct": 35})

        assert response.status_code == 200
        body = response.json()
        assert body["min_pct"] == pytest.approx(25.0)
        assert body["max_pct"] == pytest.approx(35.0)

        rows = client.get("/api/portfolio/allocation").json()
        assert len([r for r in rows if r["category"] == "ETF"]) == 1

    def test_category_is_uppercased(self, client):
        client.put("/api/portfolio/allocation/etf", json={"min_pct": 20, "max_pct": 30})

        rows = {r["category"]: r for r in client.get("/api/portfolio/allocation").json()}
        assert "ETF" in rows


class TestDeleteAllocationTarget:
    def test_delete_reverts_held_category_to_no_target(self, client):
        held_instrument(client, "AAA.FR", "STOCK", quantity=10, price=100.0)
        client.put("/api/portfolio/allocation/STOCK", json={"min_pct": 50, "max_pct": 100})

        response = client.delete("/api/portfolio/allocation/STOCK")
        assert response.status_code == 204

        row = client.get("/api/portfolio/allocation").json()[0]
        assert row["state"] == "no_target"

    def test_delete_removes_an_unheld_targeted_category_entirely(self, client):
        held_instrument(client, "AAA.FR", "STOCK", quantity=10, price=100.0)
        client.put("/api/portfolio/allocation/ETF", json={"min_pct": 20, "max_pct": 30})

        client.delete("/api/portfolio/allocation/ETF")

        rows = client.get("/api/portfolio/allocation").json()
        assert "ETF" not in [r["category"] for r in rows]

    def test_delete_unknown_category_is_a_no_op(self, client):
        assert client.delete("/api/portfolio/allocation/BONDS").status_code == 204
