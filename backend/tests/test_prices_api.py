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
        codes = [outcome["code"] for outcome in report["outcomes"]]
        assert codes.count("prices.rateLimited") == 2
        # Language-neutral, like every other message the API returns.
        assert all(" " not in outcome["code"] for outcome in report["outcomes"])

    def test_throttled_with_no_fallback_says_what_to_do(self, client, monkeypatch, xtb_export):
        """A wall of "rate limited" is not actionable; "configure a fallback" is."""
        import_statement(client, xtb_export)
        use_provider(monkeypatch, FakeProvider("yahoo", error=RateLimited("slow down")))

        report = client.post("/api/prices/refresh").json()

        codes = [outcome["code"] for outcome in report["outcomes"]]
        assert codes.count("prices.noFallbackConfigured") == 1  # once, not per instrument

    def test_no_hint_when_a_fallback_is_configured(self, client, monkeypatch, xtb_export):
        """Nothing to suggest if the user already did the thing we would suggest."""
        import_statement(client, xtb_export)
        monkeypatch.setattr(
            "app.routers.prices.get_provider_chain",
            lambda: ProviderChain(
                [
                    FakeProvider("yahoo", error=RateLimited("slow down")),
                    FakeProvider("twelvedata", error=RateLimited("slow down")),
                ]
            ),
        )

        report = client.post("/api/prices/refresh").json()

        codes = [outcome["code"] for outcome in report["outcomes"]]
        assert "prices.noFallbackConfigured" not in codes

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


class TestIsinEntry:
    """An ISIN unlocks the European source, so it is entered rather than guessed.

    No free service tested could map a broker ticker to an ISIN reliably, and a wrong
    ISIN would silently return another company's prices. A gap is recoverable; wrong
    data presented as right is not.
    """

    def test_setting_an_isin(self, client, xtb_export):
        import_statement(client, xtb_export)

        response = client.put(
            "/api/portfolio/isin", json={"broker_symbol": "ASML.NL", "isin": "NL0010273215"}
        )

        assert response.status_code == 200
        assert response.json()["isin"] == "NL0010273215"

    def test_a_ticker_is_refused(self, client, xtb_export):
        import_statement(client, xtb_export)

        response = client.put(
            "/api/portfolio/isin", json={"broker_symbol": "ASML.NL", "isin": "ASML.NLXXXX"}
        )

        assert response.status_code == 422

    def test_lowercase_is_normalised(self, client, xtb_export):
        import_statement(client, xtb_export)

        response = client.put(
            "/api/portfolio/isin", json={"broker_symbol": "ASML.NL", "isin": "nl0010273215"}
        )

        assert response.json()["isin"] == "NL0010273215"

    def test_unknown_instrument(self, client):
        response = client.put(
            "/api/portfolio/isin", json={"broker_symbol": "NOPE.XX", "isin": "NL0010273215"}
        )

        assert response.status_code == 404

    def test_setting_an_isin_reopens_the_freshness_window(self, client, monkeypatch, xtb_export):
        """A new source deserves an immediate try, not a wait until tomorrow."""
        import_statement(client, xtb_export)
        use_provider(monkeypatch, FakeProvider("yahoo", error=RateLimited("x")))
        client.post("/api/prices/refresh")

        client.put("/api/portfolio/isin", json={"broker_symbol": "ASML.NL", "isin": "NL0010273215"})
        use_provider(monkeypatch, FakeProvider("frankfurt", bars=daily_bars()))
        report = client.post("/api/prices/refresh").json()

        assert report["updated"] >= 1
