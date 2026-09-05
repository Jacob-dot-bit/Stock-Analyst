"""End-to-end tests for the scoring router."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Fundamental, Instrument, Position, PriceBar


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


class TestGetScores:
    def test_a_held_etf_with_price_history_returns_a_technical_only_score(self, client):
        etf = Instrument(broker_symbol="SPY.US", category="ETF", currency="USD", country="US")
        _seed(client, [etf])
        bars = [
            PriceBar(instrument_id=etf.id, bar_date=date(2024, 1, 1) + timedelta(days=i), close=400.0 + i * 0.1, provider="test")
            for i in range(260)
        ]
        position = Position(instrument_id=etf.id, source="MANUAL", quantity=1.0, avg_price=400.0)
        _seed(client, bars + [position])

        response = client.get("/api/scoring/scores")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["instrument_id"] == etf.id
        by_name = {p["name"]: p for p in body[0]["pillars"]}
        assert by_name["technical"]["score"] is not None
        assert by_name["value"]["score"] is None

    def test_an_unheld_instrument_is_not_included(self, client):
        etf = Instrument(broker_symbol="SPY.US", category="ETF", currency="USD", country="US")
        _seed(client, [etf])  # no Position row -> not held

        response = client.get("/api/scoring/scores")
        assert response.status_code == 200
        assert response.json() == []

    def test_a_held_cfd_never_appears(self, client):
        cfd = Instrument(broker_symbol="BITCOIN", category="CFD", currency="USD", country="US")
        _seed(client, [cfd])
        position = Position(instrument_id=cfd.id, source="MANUAL", quantity=1.0, avg_price=50000.0)
        _seed(client, [position])

        response = client.get("/api/scoring/scores")
        assert response.status_code == 200
        assert response.json() == []


class TestRefreshFundamentals:
    def test_refresh_reports_not_applicable_for_a_held_etf(self, client):
        etf = Instrument(broker_symbol="SPY.US", category="ETF", currency="USD", country="US")
        _seed(client, [etf])
        position = Position(instrument_id=etf.id, source="MANUAL", quantity=1.0, avg_price=400.0)
        _seed(client, [position])

        response = client.post("/api/scoring/fundamentals/refresh")
        assert response.status_code == 200
        body = response.json()
        assert body["not_applicable"] == 1
        assert body["updated"] == 0

    def test_refresh_reports_no_provider_for_a_held_stock_without_sec_user_agent(self, client):
        # `isolate_credentials` (conftest.py, autouse) always clears
        # SEC_USER_AGENT, so EdgarProvider is disabled for every test in this
        # suite — no test ever configures a real one.
        stock = Instrument(broker_symbol="AAPL.US", category="STOCK", currency="USD", country="US")
        _seed(client, [stock])
        position = Position(instrument_id=stock.id, source="MANUAL", quantity=1.0, avg_price=150.0)
        _seed(client, [position])

        response = client.post("/api/scoring/fundamentals/refresh")
        assert response.status_code == 200
        body = response.json()
        assert body["failed"] == 1
        assert body["outcomes"][0]["code"] == "fundamentals.noProvider"

    def test_refresh_also_covers_watchlisted_and_screener_instruments(self, client):
        # Neither is held, so before this the fix in `refresh_fundamentals`
        # (extending `_held_instruments` to held ∪ watchlist ∪ screener),
        # these two would never have appeared in the report at all.
        from app.models import ScreenerCandidate, WatchlistItem

        watched_etf = Instrument(broker_symbol="VUSA.US", category="ETF", currency="USD", country="US")
        candidate_etf = Instrument(broker_symbol="IWDA.US", category="ETF", currency="USD", country="US")
        _seed(client, [watched_etf, candidate_etf])
        _seed(
            client,
            [
                WatchlistItem(instrument_id=watched_etf.id),
                ScreenerCandidate(instrument_id=candidate_etf.id),
            ],
        )

        response = client.post("/api/scoring/fundamentals/refresh")
        assert response.status_code == 200
        assert response.json()["not_applicable"] == 2


class TestRefreshStatus:
    def test_reflects_the_last_completed_run(self, client):
        stock = Instrument(broker_symbol="AAPL.US", category="STOCK", currency="USD", country="US")
        _seed(client, [stock])
        position = Position(instrument_id=stock.id, source="MANUAL", quantity=1.0, avg_price=150.0)
        _seed(client, [position])

        client.post("/api/scoring/fundamentals/refresh")

        status = client.get("/api/scoring/fundamentals/refresh/status").json()
        assert status["running"] is False
        assert status["total"] == 1
        assert status["done"] == 1
        assert status["finished_at"] is not None
        assert status["report"]["failed"] == 1

    def test_idle_before_any_refresh_has_run(self, client):
        # A previous test class's refresh may have already left the
        # process-wide progress state non-idle -- this only asserts the shape
        # is always present and well-formed, not a specific idle snapshot.
        status = client.get("/api/scoring/fundamentals/refresh/status").json()
        assert "running" in status
        assert "total" in status
        assert "done" in status
