"""End-to-end tests of the price endpoints, with the provider chain injected.

These cover everything except the live HTTP call: import a statement, refresh prices,
read back sparklines and history, and confirm the symbol mapping graduates to verified.
The real network call is exercised by `@pytest.mark.network` tests, which are excluded
by default so the suite never fails because a third party is throttling.
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
from app.providers.base import Bar, ProviderChain, RateLimited
from tests.test_providers import FakeProvider


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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


def use_provider(monkeypatch, provider):
    """Point the prices router at a given provider chain."""
    monkeypatch.setattr("app.routers.prices.get_provider_chain", lambda: ProviderChain([provider]))


def daily_bars(count: int = 30) -> list[Bar]:
    today = date.today()
    return [
        Bar(
            bar_date=today - timedelta(days=count - 1 - i),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=1_000 + i,
        )
        for i in range(count)
    ]


def import_statement(client, content, name="EUR_1234567.xlsx"):
    return client.post(
        "/api/imports/xtb", files={"file": (name, content, "application/octet-stream")}
    )


class TestRefreshEndpoint:
    def test_refresh_stores_prices_and_verifies_mappings(self, client, monkeypatch, xtb_export):
        import_statement(client, xtb_export)
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))

        report = client.post("/api/prices/refresh").json()

        assert report["updated"] == 2  # ASML and NVDA
        assert report["failed"] == 0
        assert report["remaining"] == 0

        # The mapping is only proven right once a provider answers with real data.
        positions = client.get("/api/portfolio").json()["positions"]
        assert all(p["instrument"]["mapping_status"] == "VERIFIED" for p in positions)
        assert all(p["instrument"]["verified_provider"] == "yahoo" for p in positions)

    def test_second_refresh_hits_the_cache(self, client, monkeypatch, xtb_export):
        """Caching is what keeps a refresh inside free-tier rate limits."""
        import_statement(client, xtb_export)
        provider = FakeProvider("yahoo", bars=daily_bars())
        use_provider(monkeypatch, provider)

        client.post("/api/prices/refresh")
        second = client.post("/api/prices/refresh").json()

        assert second["updated"] == 0
        assert second["skipped"] == 2
        assert provider.calls == 2  # only the first run went to the provider

    def test_rate_limiting_is_reported_per_instrument(self, client, monkeypatch, xtb_export):
        import_statement(client, xtb_export)
        use_provider(monkeypatch, FakeProvider("yahoo", error=RateLimited("slow down")))

        report = client.post("/api/prices/refresh").json()

        assert report["updated"] == 0
        assert report["failed"] == 2
        codes = {outcome["code"] for outcome in report["outcomes"]}
        assert codes == {"prices.rateLimited"}
        # Language-neutral, like every other message the API returns.
        assert all(" " not in outcome["code"] for outcome in report["outcomes"])

    def test_unmapped_instruments_are_not_fetched(self, client, monkeypatch):
        """CFDs and unmappable codes must not consume the rate-limit budget."""
        client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "US500", "quantity": 1, "avg_price": 5000},
        )
        provider = FakeProvider("yahoo", bars=daily_bars())
        use_provider(monkeypatch, provider)

        client.post("/api/prices/refresh")

        assert provider.calls == 0


class TestSparklines:
    def test_empty_before_any_refresh(self, client, xtb_export):
        import_statement(client, xtb_export)

        assert client.get("/api/prices/sparklines").json() == []

    def test_returns_closes_per_instrument(self, client, monkeypatch, xtb_export):
        import_statement(client, xtb_export)
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars(30)))
        client.post("/api/prices/refresh")

        series = client.get("/api/prices/sparklines").json()

        assert len(series) == 2
        assert all(len(s["closes"]) == 30 for s in series)
        # Chronological order: a sparkline drawn backwards would invert every trend.
        assert all(s["closes"] == sorted(s["closes"]) for s in series)


class TestHistory:
    def test_returns_points_and_the_serving_provider(self, client, monkeypatch, xtb_export):
        import_statement(client, xtb_export)
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars(10)))
        client.post("/api/prices/refresh")

        instrument_id = client.get("/api/portfolio").json()["positions"][0]["instrument"]["id"]
        history = client.get(f"/api/prices/{instrument_id}/history").json()

        assert len(history["points"]) == 10
        assert history["provider"] == "yahoo"
        assert history["points"][0]["date"] < history["points"][-1]["date"]

    def test_history_never_triggers_a_fetch(self, client, monkeypatch, xtb_export):
        """Drawing a chart must not be able to burn the rate-limit budget."""
        import_statement(client, xtb_export)
        provider = FakeProvider("yahoo", bars=daily_bars())
        use_provider(monkeypatch, provider)

        instrument_id = client.get("/api/portfolio").json()["positions"][0]["instrument"]["id"]
        client.get(f"/api/prices/{instrument_id}/history")

        assert provider.calls == 0

    def test_unknown_instrument(self, client):
        assert client.get("/api/prices/9999/history").status_code == 404
