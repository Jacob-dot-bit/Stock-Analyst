"""Tests for persisting the last live quote. See DEVLOG "Decision 3o.1"."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models import LastQuote, PriceBar
from app.providers.base import Bar, ProviderChain
from tests.test_providers import FakeProvider


@pytest.fixture
def client(monkeypatch, tmp_path):
    # A real file, not `StaticPool`-backed `:memory:` — same reasoning as
    # test_prices_api.py's fixture: the live-quote round now runs several
    # instruments concurrently (DEVLOG "Decision 3n.1").
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
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


def use_quote_provider(monkeypatch, provider):
    monkeypatch.setattr("app.routers.portfolio.get_provider_chain", lambda: ProviderChain([provider]))


def _db(client):
    return next(app.dependency_overrides[get_db]())


class TestLastQuotePersistence:
    def test_a_live_quote_survives_a_later_plain_get(self, client, monkeypatch):
        created = client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "AAPL.US", "quantity": 1, "avg_price": 100.0},
        )
        assert created.status_code == 201

        provider = FakeProvider("yahoo", bars=[Bar(date.today(), 1, 1, 1, 305.5, 1)])
        use_quote_provider(monkeypatch, provider)

        refreshed = client.post("/api/portfolio/refresh-live")
        assert refreshed.status_code == 200
        assert refreshed.json()["positions"][0]["price_source"] == "live"

        # A brand-new request, no live_quotes of its own — must still see the
        # quote the previous request persisted, not fall back to "broker".
        again = client.get("/api/portfolio")
        position = again.json()["positions"][0]
        assert position["price_source"] == "live"
        assert position["current_price"] == 305.5

    def test_a_persisted_quote_row_is_updated_not_duplicated(self, client, monkeypatch):
        client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "AAPL.US", "quantity": 1, "avg_price": 100.0},
        )

        use_quote_provider(monkeypatch, FakeProvider("yahoo", bars=[Bar(date.today(), 1, 1, 1, 100.0, 1)]))
        client.post("/api/portfolio/refresh-live")
        use_quote_provider(monkeypatch, FakeProvider("yahoo", bars=[Bar(date.today(), 1, 1, 1, 150.0, 1)]))
        client.post("/api/portfolio/refresh-live")

        db = _db(client)
        rows = db.execute(select(LastQuote)).scalars().all()
        assert len(rows) == 1
        assert rows[0].price == 150.0

    def test_a_fresher_daily_bar_supersedes_a_stale_saved_quote(self, client, monkeypatch):
        created = client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "AAPL.US", "quantity": 1, "avg_price": 100.0},
        ).json()
        instrument_id = created["instrument"]["id"]

        use_quote_provider(monkeypatch, FakeProvider("yahoo", bars=[Bar(date.today(), 1, 1, 1, 200.0, 1)]))
        client.post("/api/portfolio/refresh-live")

        db = _db(client)
        saved = db.get(LastQuote, instrument_id)
        # Backdate the saved quote so a bar fetched *after* it must win.
        saved.fetched_at = datetime.now(UTC) - timedelta(days=1)
        db.add(
            PriceBar(
                instrument_id=instrument_id,
                bar_date=date.today(),
                close=250.0,
                provider="yahoo",
                fetched_at=datetime.now(UTC),
            )
        )
        db.commit()

        body = client.get("/api/portfolio").json()
        position = body["positions"][0]
        assert position["price_source"] == "cached"
        assert position["current_price"] == 250.0

    def test_no_quotes_fetched_leaves_nothing_to_save(self, client, monkeypatch):
        client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "AAPL.US", "quantity": 1, "avg_price": 100.0},
        )
        use_quote_provider(monkeypatch, FakeProvider("yahoo", enabled=False))

        client.post("/api/portfolio/refresh-live")

        db = _db(client)
        assert db.execute(__import__("sqlalchemy").select(LastQuote)).scalars().all() == []
