"""End-to-end tests for the screener endpoints.

Covers the "hidden" invariant (DEVLOG "Decision 3u.11"): a candidate that gets
bought or moved to the watchlist stops being hidden and disappears from every
read here, then reappears if both of those are later undone. Also covers the
one real behavioral difference from the watchlist's `/scores`: this endpoint
ranks by composite score descending.
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
from app.providers.base import Bar, ProviderChain, RateLimited, SymbolNotFound
from tests.test_providers import FakeProvider


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
    """`POST /api/screener` best-effort-fetches a price on every add — without
    this, that fetch would fall through to the real, no-key-required
    Boursorama provider and hit the actual network on every test."""
    monkeypatch.setattr("app.routers.screener.get_provider_chain", lambda: ProviderChain([]))


def use_provider(monkeypatch, provider):
    monkeypatch.setattr("app.routers.screener.get_provider_chain", lambda: ProviderChain([provider]))


def daily_bars(close: float = 100.0, count: int = 30) -> list[Bar]:
    today = date.today()
    return [
        Bar(bar_date=today - timedelta(days=count - 1 - i), open=close, high=close, low=close, close=close, volume=1_000)
        for i in range(count)
    ]


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


class TestAddScreenerCandidate:
    def test_create_resolves_instrument(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))

        response = client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        assert response.status_code == 201
        body = response.json()
        assert body["instrument"]["broker_symbol"] == "MC.FR"
        assert body["instrument"]["provider_symbol"] == "MC.PA"

    def test_fetches_a_price_immediately(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars(close=150.0)))

        body = client.post("/api/screener", json={"broker_symbol": "MC.FR"}).json()

        assert body["current_price"] == pytest.approx(150.0)
        assert body["price_source"] == "cached"

    def test_rejects_an_already_held_instrument(self, client):
        client.post("/api/portfolio/positions", json={"broker_symbol": "HELD.US", "quantity": 1, "avg_price": 10.0})

        response = client.post("/api/screener", json={"broker_symbol": "HELD.US"})

        assert response.status_code == 400

    def test_rejects_an_already_watchlisted_instrument(self, client):
        client.post("/api/watchlist", json={"broker_symbol": "MC.FR"})

        response = client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        assert response.status_code == 400

    def test_rejects_a_duplicate(self, client):
        client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        response = client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        assert response.status_code == 400

    def test_rejects_a_symbol_no_provider_recognizes(self, client, monkeypatch):
        """Same guardrail as `add_watchlist_item` — see
        `test_watchlist_api.py`'s equivalent test for the full reasoning."""
        use_provider(monkeypatch, FakeProvider("test", error=SymbolNotFound("nope")))

        response = client.post("/api/screener", json={"broker_symbol": "BOGUS.US"})

        assert response.status_code == 422
        assert client.get("/api/screener").json() == []

    def test_a_rate_limited_symbol_is_still_added(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("test", error=RateLimited("slow down")))

        response = client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        assert response.status_code == 201


class TestDuplicateWarning:
    """Same guardrail as `test_watchlist_api.py`'s equivalent class — see
    there for the full reasoning (DEVLOG "Decision 3u.16")."""

    def test_no_lookup_attempted_without_a_company_name(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))

        def fail_if_called(*args, **kwargs):
            raise AssertionError("resolve_isin must not be called without a company_name")

        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", fail_if_called)

        response = client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        assert response.status_code == 201
        assert response.json()["duplicate_warning"] is None

    def test_warns_when_the_resolved_isin_matches_an_existing_holding(self, client, monkeypatch):
        instrument = Instrument(broker_symbol="EL.PA.US", isin="FR0000121667", category="STOCK", currency="EUR", country="FR")
        _seed(client, [instrument])
        _seed(client, [Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=10.0)])
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: "FR0000121667")

        response = client.post(
            "/api/screener", json={"broker_symbol": "ESLOY.US", "company_name": "EssilorLuxottica"}
        )

        assert response.status_code == 201
        warning = response.json()["duplicate_warning"]
        assert warning is not None
        assert "EL.PA.US" in warning

    def test_no_warning_when_the_isin_matches_nothing_tracked(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: "FR9999999999")

        response = client.post("/api/screener", json={"broker_symbol": "MC.FR", "company_name": "LVMH"})

        assert response.status_code == 201
        assert response.json()["duplicate_warning"] is None

    def test_company_name_is_stored_as_the_instrument_name(self, client, monkeypatch):
        """Same gap as `test_watchlist_api.py`'s equivalent test — see there
        for the full reasoning."""
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: None)

        response = client.post(
            "/api/screener", json={"broker_symbol": "NFLX.US", "company_name": "Netflix"}
        ).json()

        assert response["instrument"]["name"] == "Netflix"

    def test_patch_with_company_name_backfills_isin_retroactively(self, client, monkeypatch):
        instrument = Instrument(broker_symbol="EL.PA.US", isin="FR0000121667", category="STOCK", currency="EUR", country="FR")
        _seed(client, [instrument])
        _seed(client, [Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=10.0)])
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        created = client.post("/api/screener", json={"broker_symbol": "ESLOY.US"}).json()
        assert created["instrument"]["isin"] is None

        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: "FR0000121667")
        response = client.patch(f"/api/screener/{created['id']}", json={"company_name": "EssilorLuxottica"})

        assert response.status_code == 200
        body = response.json()
        assert body["instrument"]["isin"] == "FR0000121667"
        assert "EL.PA.US" in body["duplicate_warning"]


class TestUpdateScreenerCandidate:
    def test_no_company_name_is_a_no_op(self, client):
        created = client.post("/api/screener", json={"broker_symbol": "MC.FR"}).json()

        response = client.patch(f"/api/screener/{created['id']}", json={})

        assert response.status_code == 200
        assert response.json()["duplicate_warning"] is None

    def test_404_for_unknown_id(self, client):
        assert client.patch("/api/screener/999", json={}).status_code == 404


class TestListAndDelete:
    def test_list(self, client):
        client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        listed = client.get("/api/screener").json()

        assert len(listed) == 1
        assert listed[0]["instrument"]["broker_symbol"] == "MC.FR"

    def test_delete(self, client):
        created = client.post("/api/screener", json={"broker_symbol": "MC.FR"}).json()

        response = client.delete(f"/api/screener/{created['id']}")

        assert response.status_code == 204
        assert client.get("/api/screener").json() == []

    def test_delete_unknown_is_404(self, client):
        assert client.delete("/api/screener/999").status_code == 404


class TestHiddenInvariant:
    def test_buying_a_candidate_hides_it_then_selling_reveals_it_again(self, client):
        created = client.post("/api/screener", json={"broker_symbol": "MC.FR"}).json()
        instrument_id = created["instrument"]["id"]

        position = client.post(
            "/api/portfolio/positions", json={"broker_symbol": "MC.FR", "quantity": 1, "avg_price": 100.0}
        ).json()

        assert client.get("/api/screener").json() == []
        assert client.get("/api/screener/scores").json() == []
        assert client.get("/api/screener/sparklines").json() == []

        client.delete(f"/api/portfolio/positions/{position['id']}")

        reappeared = client.get("/api/screener").json()
        assert len(reappeared) == 1
        assert reappeared[0]["instrument"]["id"] == instrument_id

    def test_watchlisting_a_candidate_hides_it_then_removing_reveals_it_again(self, client):
        created = client.post("/api/screener", json={"broker_symbol": "MC.FR"}).json()
        instrument_id = created["instrument"]["id"]

        item = client.post("/api/watchlist", json={"broker_symbol": "MC.FR"}).json()

        assert client.get("/api/screener").json() == []

        client.delete(f"/api/watchlist/{item['id']}")

        reappeared = client.get("/api/screener").json()
        assert len(reappeared) == 1
        assert reappeared[0]["instrument"]["id"] == instrument_id

    def test_delete_still_works_on_a_currently_hidden_candidate(self, client):
        created = client.post("/api/screener", json={"broker_symbol": "MC.FR"}).json()
        client.post("/api/portfolio/positions", json={"broker_symbol": "MC.FR", "quantity": 1, "avg_price": 100.0})

        response = client.delete(f"/api/screener/{created['id']}")

        assert response.status_code == 204


class TestScoresAndSparklines:
    def test_scores_endpoint_returns_one_entry_per_candidate(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        scores = client.get("/api/screener/scores").json()

        assert len(scores) == 1

    def test_scores_are_sorted_composite_descending_with_none_last(self, client):
        from app.models import ScreenerCandidate

        # A candidate with 260 days of stable-ish price history gets a real
        # technical score (no fundamentals needed for the technical pillar,
        # same setup `test_scoring_api.py` uses); a candidate with too little
        # history to score anything gets `composite=None` and must still sort
        # last, not be dropped from the list.
        strong = Instrument(broker_symbol="STRONG.US", category="STOCK", currency="USD", country="US")
        weak = Instrument(broker_symbol="WEAK.US", category="STOCK", currency="USD", country="US")
        no_score = Instrument(broker_symbol="NOSCORE.US", category="STOCK", currency="USD", country="US")
        _seed(client, [strong, weak, no_score])

        bars = []
        for i in range(260):
            d = date(2024, 1, 1) + timedelta(days=i)
            bars.append(PriceBar(instrument_id=strong.id, bar_date=d, close=100.0 + i * 0.5, provider="test"))
            bars.append(PriceBar(instrument_id=weak.id, bar_date=d, close=100.0 - i * 0.2, provider="test"))
        _seed(client, bars)
        _seed(
            client,
            [
                ScreenerCandidate(instrument_id=strong.id),
                ScreenerCandidate(instrument_id=weak.id),
                ScreenerCandidate(instrument_id=no_score.id),
            ],
        )

        scores = client.get("/api/screener/scores").json()

        assert len(scores) == 3
        assert scores[-1]["instrument_id"] == no_score.id
        assert scores[-1]["composite"] is None
        composites = [s["composite"] for s in scores[:2]]
        assert composites == sorted(composites, reverse=True)

    def test_sparklines_returns_closes_for_candidate(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars(close=42.0)))
        client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        sparklines = client.get("/api/screener/sparklines").json()

        assert len(sparklines) == 1
        assert sparklines[0]["closes"][-1] == pytest.approx(42.0)

    def test_sparklines_reflect_a_confirmed_split(self, client):
        """The mini trend chart must not show a fake cliff either — same
        adjustment as the main price chart."""
        from app.models import CorporateAction, ScreenerCandidate

        instrument = Instrument(broker_symbol="SPLIT.US", category="STOCK", currency="USD", country="US")
        _seed(client, [instrument])
        since = date.today() - timedelta(days=5)
        _seed(
            client,
            [
                PriceBar(instrument_id=instrument.id, bar_date=since, close=1000.0),
                PriceBar(instrument_id=instrument.id, bar_date=since + timedelta(days=1), close=100.0),
                ScreenerCandidate(instrument_id=instrument.id),
                CorporateAction(
                    instrument_id=instrument.id, action_type="split",
                    effective_date=since + timedelta(days=1), ratio_numerator=10, ratio_denominator=1,
                    source="manual", price_history_status="raw",
                ),
            ],
        )

        sparklines = client.get("/api/screener/sparklines").json()

        assert sparklines[0]["closes"] == pytest.approx([100.0, 100.0])
