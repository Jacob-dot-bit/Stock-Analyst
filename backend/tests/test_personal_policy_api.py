"""End-to-end tests for the personal-policy endpoints
(`GET/PUT /api/portfolio/policy`, `GET/POST/DELETE /api/portfolio/policy/limits`,
`GET /api/portfolio/policy/gaps`).

The policy itself is never inferred or scored by the app — every field is
optional and the gaps endpoint only ever reports a fact against the user's
own configured limit, never a suggestion. See DEVLOG "Decision 3u.59".
"""

from __future__ import annotations

from datetime import date, timedelta

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


def _seed(rows):
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


def held_instrument(symbol: str, *, currency: str = "EUR", sector: str | None = None, category: str = "STOCK", quantity: float = 1, price: float = 100.0) -> Instrument:
    instrument = Instrument(broker_symbol=symbol, category=category, currency=currency, sector=sector)
    _seed([instrument])
    bar = PriceBar(instrument_id=instrument.id, bar_date=date.today() - timedelta(days=1), close=price, provider="test")
    position = Position(instrument_id=instrument.id, source="MANUAL", quantity=quantity, avg_price=price)
    _seed([bar, position])
    return instrument


class TestPolicyProfile:
    def test_default_policy_is_all_unset(self, client):
        body = client.get("/api/portfolio/policy").json()
        assert body["objective_growth"] is False
        assert body["objective_income"] is False
        assert body["objective_preservation"] is False
        assert body["objective_note"] is None
        assert body["horizon"] is None
        assert body["liquidity_need_amount"] is None
        assert body["risk_tolerance_note"] is None
        assert body["loss_capacity_pct"] is None

    def test_put_then_get_reflects_every_field(self, client):
        payload = {
            "objective_growth": True,
            "objective_income": False,
            "objective_preservation": True,
            "objective_note": "Croissance long terme, un peu de préservation",
            "horizon": "long",
            "horizon_target_date": "2040-01-01",
            "liquidity_need_amount": 5000.0,
            "liquidity_need_date": "2027-06-01",
            "liquidity_note": "Apport immobilier",
            "risk_tolerance_note": "Peut supporter une baisse de 30% sans changer de stratégie",
            "loss_capacity_pct": 30.0,
        }
        put_body = client.put("/api/portfolio/policy", json=payload).json()
        for key, value in payload.items():
            assert put_body[key] == value

        get_body = client.get("/api/portfolio/policy").json()
        for key, value in payload.items():
            assert get_body[key] == value

    def test_put_is_idempotent_and_replaces_whole_policy(self, client):
        client.put("/api/portfolio/policy", json={"objective_growth": True, "risk_tolerance_note": "high"})
        second = client.put("/api/portfolio/policy", json={"objective_growth": False}).json()
        # The second PUT omitted `risk_tolerance_note` — a full replace, not
        # a merge, so it reverts to unset rather than keeping the old value.
        assert second["objective_growth"] is False
        assert second["risk_tolerance_note"] is None


class TestPolicyLimitsValidation:
    def test_line_limit_rejects_a_target(self, client):
        resp = client.post("/api/portfolio/policy/limits", json={"dimension": "line", "target": "AAPL.US", "max_pct": 10})
        assert resp.status_code == 422

    def test_sector_limit_requires_a_target(self, client):
        resp = client.post("/api/portfolio/policy/limits", json={"dimension": "sector", "max_pct": 35})
        assert resp.status_code == 422

    def test_requires_at_least_one_bound(self, client):
        resp = client.post("/api/portfolio/policy/limits", json={"dimension": "line"})
        assert resp.status_code == 422

    def test_min_greater_than_max_rejected(self, client):
        resp = client.post(
            "/api/portfolio/policy/limits", json={"dimension": "currency", "target": "USD", "min_pct": 60, "max_pct": 30}
        )
        assert resp.status_code == 422

    def test_duplicate_dimension_target_rejected(self, client):
        client.post("/api/portfolio/policy/limits", json={"dimension": "sector", "target": "Technology", "max_pct": 35})
        resp = client.post("/api/portfolio/policy/limits", json={"dimension": "sector", "target": "Technology", "max_pct": 40})
        assert resp.status_code == 409

    def test_duplicate_line_limit_rejected_even_though_target_is_null_both_times(self, client):
        client.post("/api/portfolio/policy/limits", json={"dimension": "line", "max_pct": 10})
        resp = client.post("/api/portfolio/policy/limits", json={"dimension": "line", "max_pct": 15})
        assert resp.status_code == 409


class TestPolicyLimitsCrud:
    def test_create_list_delete(self, client):
        created = client.post("/api/portfolio/policy/limits", json={"dimension": "sector", "target": "Technology", "max_pct": 35}).json()
        assert created["id"] > 0
        listed = client.get("/api/portfolio/policy/limits").json()
        assert len(listed) == 1
        client.delete(f"/api/portfolio/policy/limits/{created['id']}")
        assert client.get("/api/portfolio/policy/limits").json() == []


class TestPolicyGaps:
    def test_no_limits_configured_returns_empty(self, client):
        held_instrument("AAA.FR")
        assert client.get("/api/portfolio/policy/gaps").json() == []

    def test_line_limit_breach_reports_the_breaching_symbol(self, client):
        # One position at 100% of the portfolio — any max below 100% is breached.
        held_instrument("AAA.FR", quantity=10, price=100.0)
        client.post("/api/portfolio/policy/limits", json={"dimension": "line", "max_pct": 10})

        gaps = client.get("/api/portfolio/policy/gaps").json()
        assert len(gaps) == 1
        assert gaps[0]["dimension"] == "line"
        assert gaps[0]["target"] == "AAA.FR"
        assert gaps[0]["state"] == "over"
        assert gaps[0]["current_pct"] == 100.0
        assert gaps[0]["gap_pct"] == 90.0

    def test_line_limit_satisfied_reports_nothing(self, client):
        held_instrument("AAA.FR", quantity=10, price=100.0)
        client.post("/api/portfolio/policy/limits", json={"dimension": "line", "max_pct": 100})
        assert client.get("/api/portfolio/policy/gaps").json() == []

    def test_sector_limit_breach(self, client):
        held_instrument("AAA.FR", sector="Technology", quantity=10, price=100.0)
        held_instrument("BBB.FR", sector="Healthcare", quantity=10, price=100.0)
        client.post("/api/portfolio/policy/limits", json={"dimension": "sector", "target": "Technology", "max_pct": 35})

        gaps = client.get("/api/portfolio/policy/gaps").json()
        assert len(gaps) == 1
        assert gaps[0]["dimension"] == "sector"
        assert gaps[0]["target"] == "Technology"
        assert gaps[0]["current_pct"] == 50.0
        assert gaps[0]["state"] == "over"
        assert gaps[0]["gap_pct"] == 15.0

    def test_currency_range_breach_under(self, client):
        _seed([FxRate(currency="USD", base_currency="EUR", rate_date=date.today(), rate=1.0)])
        held_instrument("AAA.FR", currency="EUR", quantity=10, price=100.0)
        held_instrument("BBB.US", currency="USD", quantity=10, price=100.0)
        # USD is 1000 / 2000 = 50% here; ask for a 60-80% range → "under".
        client.post("/api/portfolio/policy/limits", json={"dimension": "currency", "target": "USD", "min_pct": 60, "max_pct": 80})

        gaps = client.get("/api/portfolio/policy/gaps").json()
        assert len(gaps) == 1
        assert gaps[0]["dimension"] == "currency"
        assert gaps[0]["target"] == "USD"
        assert gaps[0]["current_pct"] == 50.0
        assert gaps[0]["state"] == "under"
        assert gaps[0]["gap_pct"] == 10.0

    def test_declared_valuation_breach(self, client):
        instrument = Instrument(broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate", currency="EUR")
        _seed([instrument])
        _seed([Position(instrument_id=instrument.id, source="IMPORT", quantity=1, avg_price=300.0, broker_market_value=300.0, currency="EUR", value_as_of=date.today())])
        held_instrument("AAA.FR", quantity=7, price=100.0)  # 700 EUR market-priced

        client.post("/api/portfolio/policy/limits", json={"dimension": "declared_valuation", "max_pct": 20})

        gaps = client.get("/api/portfolio/policy/gaps").json()
        assert len(gaps) == 1
        assert gaps[0]["dimension"] == "declared_valuation"
        assert gaps[0]["target"] is None
        assert gaps[0]["current_pct"] == 30.0  # 300 / 1000
        assert gaps[0]["state"] == "over"

    def test_multiple_limits_report_multiple_independent_gaps(self, client):
        held_instrument("AAA.FR", sector="Technology", quantity=10, price=100.0)
        held_instrument("BBB.FR", sector="Healthcare", quantity=10, price=100.0)
        client.post("/api/portfolio/policy/limits", json={"dimension": "line", "max_pct": 10})
        client.post("/api/portfolio/policy/limits", json={"dimension": "sector", "target": "Technology", "max_pct": 10})

        gaps = client.get("/api/portfolio/policy/gaps").json()
        dimensions = {g["dimension"] for g in gaps}
        assert dimensions == {"line", "sector"}
        # Two positions each over the 10% line cap.
        assert len([g for g in gaps if g["dimension"] == "line"]) == 2
