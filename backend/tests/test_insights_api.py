"""End-to-end tests for the insights endpoints (news/sentiment + AI
commentary). Mirrors `test_watchlist_api.py`'s structure.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.prices.provider_usage import period_key_for


class FakeAlphaVantage:
    def __init__(self, enabled=True):
        self._enabled = enabled
        self.calls = 0

    def is_enabled(self):
        return self._enabled

    def fetch_news_sentiment(self, ref):
        self.calls += 1
        return []


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


@pytest.fixture(autouse=True)
def no_real_network_by_default(monkeypatch):
    """Neither insights endpoint should ever reach the real network in a
    test run — a disabled Alpha Vantage provider by default, and
    `settings.perplexity_api_key` is already blanked by conftest's
    `isolate_credentials`, so `PerplexityClient` is naturally disabled too."""
    monkeypatch.setattr("app.routers.insights.get_alpha_vantage_provider", lambda: FakeAlphaVantage(enabled=False))


def use_alpha_vantage(monkeypatch, fake):
    monkeypatch.setattr("app.routers.insights.get_alpha_vantage_provider", lambda: fake)


def make_instrument(client) -> int:
    body = client.post(
        "/api/portfolio/positions", json={"broker_symbol": "AAPL.US", "quantity": 1, "avg_price": 100.0}
    ).json()
    return body["instrument"]["id"]


class TestNewsEndpoint:
    def test_404_on_unknown_instrument(self, client):
        assert client.post("/api/insights/999/news").status_code == 404

    def test_no_provider_outcome_when_alpha_vantage_disabled(self, client):
        instrument_id = make_instrument(client)

        response = client.post(f"/api/insights/{instrument_id}/news")

        assert response.status_code == 200
        body = response.json()
        assert body["outcome"]["code"] == "news.noProvider"
        assert body["articles"] == []

    def test_fetch_persists_and_second_call_within_ttl_is_cached(self, client, monkeypatch):
        instrument_id = make_instrument(client)
        fake = FakeAlphaVantage(enabled=True)
        use_alpha_vantage(monkeypatch, fake)

        first = client.post(f"/api/insights/{instrument_id}/news").json()
        assert first["outcome"]["code"] == "news.empty"
        assert fake.calls == 1

        second = client.post(f"/api/insights/{instrument_id}/news").json()
        assert second["outcome"]["code"] == "news.alreadyFresh"
        assert fake.calls == 1  # not called again

    def test_real_fetch_records_alpha_vantage_usage(self, client, monkeypatch):
        instrument_id = make_instrument(client)
        use_alpha_vantage(monkeypatch, FakeAlphaVantage(enabled=True))

        client.post(f"/api/insights/{instrument_id}/news")

        session = next(app.dependency_overrides[get_db]())
        try:
            from app.models import ProviderUsage

            usage = (
                session.query(ProviderUsage)
                .filter_by(provider="alpha_vantage", period_key=period_key_for("minute"))
                .one()
            )
            assert usage.count == 1
        finally:
            session.close()


class TestCommentaryEndpoint:
    def test_404_on_unknown_instrument(self, client):
        assert client.post("/api/insights/999/commentary").status_code == 404

    def test_no_provider_outcome_when_perplexity_key_unset(self, client):
        instrument_id = make_instrument(client)

        response = client.post(f"/api/insights/{instrument_id}/commentary")

        assert response.status_code == 200
        body = response.json()
        assert body["outcome"]["code"] == "commentary.noProvider"
        assert body["content"] == ""
