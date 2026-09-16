"""End-to-end tests for the portfolio-risk endpoints
(`GET /api/portfolio/risk/concentration`, `/risk/liquidity`, `/risk/drawdown`).

Unconditional exposure facts, split from Personal Policy (which only ever
reports a *breach* of a *configured* limit): these endpoints answer "what is
my portfolio actually exposed to," never gated behind a user-set rule and
never a suggestion. See DEVLOG "Decision 3u.67".

`compute_max_drawdown`'s own edge cases (peak/trough/recovery/gaps) are
covered exhaustively as pure-function unit tests in `test_history_service.py`
— `/risk/drawdown` here only checks the endpoint wiring itself.
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
from app.models import Instrument, Position, PriceBar


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


def held_instrument(
    symbol: str, *, currency: str = "EUR", category: str = "STOCK", quantity: float = 1, price: float = 100.0
) -> Instrument:
    instrument = Instrument(broker_symbol=symbol, category=category, currency=currency)
    _seed([instrument])
    bar = PriceBar(instrument_id=instrument.id, bar_date=date.today() - timedelta(days=1), close=price, provider="test")
    position = Position(instrument_id=instrument.id, source="MANUAL", quantity=quantity, avg_price=price)
    _seed([bar, position])
    return instrument


def declared_value_instrument(
    symbol: str, *, reason: str, value: float, value_as_of: date | None, category: str = "P2P"
) -> Instrument:
    instrument = Instrument(broker_symbol=symbol, category=category, not_priceable_reason=reason, currency="EUR")
    _seed([instrument])
    position = Position(
        instrument_id=instrument.id, source="IMPORT", quantity=1, avg_price=value,
        broker_market_value=value, currency="EUR", value_as_of=value_as_of,
    )
    _seed([position])
    return instrument


class TestRiskConcentration:
    def test_empty_portfolio_returns_empty_list(self, client):
        assert client.get("/api/portfolio/risk/concentration").json() == []

    def test_ranked_largest_first_with_exact_weights(self, client):
        held_instrument("AAA.US", quantity=10, price=100.0)  # value 1000
        held_instrument("BBB.US", quantity=10, price=300.0)  # value 3000
        held_instrument("CCC.US", quantity=10, price=100.0)  # value 1000
        # total = 5000

        body = client.get("/api/portfolio/risk/concentration").json()

        assert [row["symbol"] for row in body] == ["BBB.US", "AAA.US", "CCC.US"]
        assert body[0]["weight_percent"] == pytest.approx(60.0)
        assert body[1]["weight_percent"] == pytest.approx(20.0)
        assert body[2]["weight_percent"] == pytest.approx(20.0)
        assert body[0]["value"] == pytest.approx(3000.0)

    def test_limit_truncates_the_ranked_list(self, client):
        for i in range(5):
            held_instrument(f"SYM{i}.US", quantity=1, price=100.0 + i)

        body = client.get("/api/portfolio/risk/concentration?limit=2").json()

        assert len(body) == 2
        assert body[0]["weight_percent"] >= body[1]["weight_percent"]

    def test_an_unpriced_position_is_excluded_not_shown_as_zero(self, client):
        held_instrument("AAA.US", quantity=10, price=100.0)
        # No PriceBar and no broker_market_value/not_priceable_reason —
        # genuinely unpriced, must not appear at all.
        unpriced = Instrument(broker_symbol="BBB.US", category="STOCK", currency="EUR")
        _seed([unpriced])
        _seed([Position(instrument_id=unpriced.id, source="MANUAL", quantity=5, avg_price=50.0)])

        body = client.get("/api/portfolio/risk/concentration").json()

        assert [row["symbol"] for row in body] == ["AAA.US"]
        assert body[0]["weight_percent"] == pytest.approx(100.0)


class TestRiskLiquidity:
    def test_empty_portfolio_returns_zeroed_response(self, client):
        body = client.get("/api/portfolio/risk/liquidity").json()

        assert body == {"total_declared_value": 0.0, "total_declared_weight_percent": 0.0, "sources": []}

    def test_a_mintos_shaped_position_appears_under_its_own_source(self, client):
        held_instrument("AAA.US", quantity=10, price=100.0)  # value 1000, market-priced
        declared_value_instrument(
            "MINTOS-CORE-P2P", reason="p2p_aggregate", value=1000.0, value_as_of=date.today() - timedelta(days=5)
        )
        # total = 2000, declared = 1000 -> 50%

        body = client.get("/api/portfolio/risk/liquidity").json()

        assert body["total_declared_weight_percent"] == pytest.approx(50.0)
        assert len(body["sources"]) == 1
        source = body["sources"][0]
        assert source["reason"] == "p2p_aggregate"
        assert source["provider_name"] == "Mintos"
        assert source["weight_percent"] == pytest.approx(50.0)
        assert source["positions_count"] == 1
        assert source["has_stale"] is False

    def test_an_amundi_shaped_position_gets_its_own_separate_source(self, client):
        declared_value_instrument(
            "MINTOS-CORE-P2P", reason="p2p_aggregate", value=1000.0, value_as_of=date.today(), category="P2P"
        )
        declared_value_instrument(
            "AMUNDI-ESR", reason="employee_savings_fund", value=1000.0, value_as_of=date.today(), category="FUND"
        )

        body = client.get("/api/portfolio/risk/liquidity").json()

        reasons = {s["reason"] for s in body["sources"]}
        assert reasons == {"p2p_aggregate", "employee_savings_fund"}
        assert body["total_declared_weight_percent"] == pytest.approx(100.0)

    def test_a_corporate_action_residual_is_excluded_entirely(self, client):
        """A structurally non-priceable residual (CVR) is a data-trust fact
        for /data-health, never a liquidity fact here — this is a
        regression guard for that exact design decision."""
        held_instrument("AAA.US", quantity=10, price=100.0)  # value 1000, market-priced
        declared_value_instrument(
            "MINTOS-CORE-P2P", reason="p2p_aggregate", value=1000.0, value_as_of=date.today()
        )
        cvr = Instrument(broker_symbol="CVR1", category="STOCK", not_priceable_reason="corporate_action", currency="EUR")
        _seed([cvr])
        _seed([Position(instrument_id=cvr.id, source="IMPORT", quantity=1, avg_price=0.01, broker_market_value=0.01, currency="EUR")])

        body = client.get("/api/portfolio/risk/liquidity").json()

        assert len(body["sources"]) == 1
        assert body["sources"][0]["reason"] == "p2p_aggregate"
        # total_value includes the CVR's own market value, but declared
        # totals must never include it.
        assert body["total_declared_value"] == pytest.approx(1000.0)

    def test_stale_vs_fresh_in_the_same_source(self, client):
        declared_value_instrument(
            "MINTOS-CORE-P2P", reason="p2p_aggregate", value=1000.0, value_as_of=date.today() - timedelta(days=200)
        )

        body = client.get("/api/portfolio/risk/liquidity").json()

        assert body["sources"][0]["has_stale"] is True

    def test_fresh_only_reports_not_stale(self, client):
        declared_value_instrument(
            "MINTOS-CORE-P2P", reason="p2p_aggregate", value=1000.0, value_as_of=date.today() - timedelta(days=1)
        )

        body = client.get("/api/portfolio/risk/liquidity").json()

        assert body["sources"][0]["has_stale"] is False


class TestRiskDrawdown:
    def test_no_lots_is_insufficient_history(self, client):
        body = client.get("/api/portfolio/risk/drawdown").json()

        assert body["insufficient_history"] is True
        assert body["max_drawdown_pct"] is None
        assert body["recovered"] is None
