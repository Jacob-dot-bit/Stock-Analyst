"""End-to-end tests for the watchlist endpoints.

Covers the two directions of the "watched but unheld" invariant (DEVLOG
"Decision ..."): adding an already-held symbol is rejected, and a watchlisted
symbol that later gets bought disappears from every read here — then
reappears, with its original target/note intact, once fully sold again.
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
from app.models import Instrument, Position
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
    """`POST /api/watchlist` best-effort-fetches a price on every add — without
    this, that fetch would fall through to the real, no-key-required
    Boursorama provider and hit the actual network on every test. Tests that
    want a working fetch call `use_provider` themselves, which overrides this."""
    monkeypatch.setattr("app.routers.watchlist.get_provider_chain", lambda: ProviderChain([]))


def use_provider(monkeypatch, provider):
    monkeypatch.setattr("app.routers.watchlist.get_provider_chain", lambda: ProviderChain([provider]))


def daily_bars(close: float = 100.0, count: int = 30) -> list[Bar]:
    today = date.today()
    return [
        Bar(
            bar_date=today - timedelta(days=count - 1 - i),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000,
        )
        for i in range(count)
    ]


def _seed_held_instrument_with_isin(broker_symbol: str, isin: str) -> None:
    """A held position on a given ISIN — same convention `test_allocation_api.py`
    uses for direct session seeding outside the request/response cycle."""
    session = next(app.dependency_overrides[get_db]())
    try:
        instrument = Instrument(broker_symbol=broker_symbol, isin=isin, category="STOCK", currency="EUR", country="FR")
        session.add(instrument)
        session.commit()
        session.refresh(instrument)
        session.add(Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=10.0))
        session.commit()
    finally:
        session.close()


class TestAddWatchlistItem:
    def test_create_resolves_instrument(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))

        response = client.post("/api/watchlist", json={"broker_symbol": "MC.FR"})

        assert response.status_code == 201
        body = response.json()
        assert body["instrument"]["broker_symbol"] == "MC.FR"
        assert body["instrument"]["provider_symbol"] == "MC.PA"
        assert body["target_entry_price"] is None
        assert body["note"] is None

    def test_fetches_a_price_immediately(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars(close=150.0)))

        body = client.post("/api/watchlist", json={"broker_symbol": "MC.FR"}).json()

        assert body["current_price"] == pytest.approx(150.0)
        assert body["price_source"] == "cached"

    def test_distance_to_target_computed_when_both_present(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars(close=90.0)))

        body = client.post(
            "/api/watchlist", json={"broker_symbol": "MC.FR", "target_entry_price": 100.0}
        ).json()

        # Price (90) is below target (100): a real entry signal, expressed as
        # a negative distance -- (90-100)/100*100 = -10%.
        assert body["distance_to_target_pct"] == pytest.approx(-10.0)

    def test_distance_to_target_is_none_without_a_target(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars(close=90.0)))

        body = client.post("/api/watchlist", json={"broker_symbol": "MC.FR"}).json()

        assert body["distance_to_target_pct"] is None

    def test_distance_to_target_is_none_without_a_price_yet(self, client):
        # No provider configured (the autouse fixture's default): the
        # best-effort fetch on add finds nothing, so there is genuinely no
        # price to compute a distance from.
        body = client.post(
            "/api/watchlist", json={"broker_symbol": "MC.FR", "target_entry_price": 100.0}
        ).json()

        assert body["current_price"] is None
        assert body["distance_to_target_pct"] is None

    def test_rejects_non_positive_target(self, client):
        response = client.post(
            "/api/watchlist", json={"broker_symbol": "MC.FR", "target_entry_price": 0}
        )
        assert response.status_code == 422

    def test_rejects_an_already_held_instrument(self, client):
        client.post("/api/portfolio/positions", json={"broker_symbol": "HELD.US", "quantity": 1, "avg_price": 10.0})

        response = client.post("/api/watchlist", json={"broker_symbol": "HELD.US"})

        assert response.status_code == 400

    def test_rejects_a_duplicate(self, client):
        client.post("/api/watchlist", json={"broker_symbol": "MC.FR"})

        response = client.post("/api/watchlist", json={"broker_symbol": "MC.FR"})

        assert response.status_code == 400

    def test_rejects_a_symbol_no_provider_recognizes(self, client, monkeypatch):
        """A wrong ticker format must never make it onto the watchlist — it
        would otherwise sit there forever, re-asked and re-failed on every
        future refresh for no chance of success."""
        use_provider(monkeypatch, FakeProvider("test", error=SymbolNotFound("nope")))

        response = client.post("/api/watchlist", json={"broker_symbol": "BOGUS.US"})

        assert response.status_code == 422
        assert client.get("/api/watchlist").json() == []

    def test_a_rate_limited_symbol_is_still_added(self, client, monkeypatch):
        """Today's throttling is not tomorrow's failure — unlike a genuinely
        unknown symbol, this must not block the add."""
        use_provider(monkeypatch, FakeProvider("test", error=RateLimited("slow down")))

        response = client.post("/api/watchlist", json={"broker_symbol": "MC.FR"})

        assert response.status_code == 201


class TestDuplicateWarning:
    """The real incident this guards against (DEVLOG "Decision 3u.16"): the
    same company added under several unrelated ticker strings, because
    nothing ever compared them. ISIN is the identity signal that survives a
    ticker-format change."""

    def test_no_lookup_attempted_without_a_company_name(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))

        def fail_if_called(*args, **kwargs):
            raise AssertionError("resolve_isin must not be called without a company_name")

        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", fail_if_called)

        response = client.post("/api/watchlist", json={"broker_symbol": "MC.FR"})

        assert response.status_code == 201
        assert response.json()["duplicate_warning"] is None

    def test_warns_when_the_resolved_isin_matches_an_existing_holding(self, client, monkeypatch):
        _seed_held_instrument_with_isin("EL.PA.US", "FR0000121667")
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: "FR0000121667")

        response = client.post(
            "/api/watchlist", json={"broker_symbol": "ESLOY.US", "company_name": "EssilorLuxottica"}
        )

        assert response.status_code == 201
        warning = response.json()["duplicate_warning"]
        assert warning is not None
        assert "EL.PA.US" in warning

    def test_no_warning_when_the_isin_matches_nothing_tracked(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: "FR9999999999")

        response = client.post(
            "/api/watchlist", json={"broker_symbol": "MC.FR", "company_name": "LVMH"}
        )

        assert response.status_code == 201
        assert response.json()["duplicate_warning"] is None

    def test_resolved_isin_is_stored_on_the_instrument_even_without_a_duplicate(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: "FR0000121014")

        response = client.post(
            "/api/watchlist", json={"broker_symbol": "MC.FR", "company_name": "LVMH"}
        ).json()

        assert response["instrument"]["isin"] == "FR0000121014"

    def test_company_name_is_stored_as_the_instrument_name(self, client, monkeypatch):
        """Real gap found live: typing a company name resolved the ISIN just
        fine, but the name itself was silently discarded — the row displayed
        no name at all, unlike a broker-imported instrument."""
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: None)

        response = client.post(
            "/api/watchlist", json={"broker_symbol": "NFLX.US", "company_name": "Netflix"}
        ).json()

        assert response["instrument"]["name"] == "Netflix"

    def test_patch_with_company_name_backfills_isin_retroactively(self, client, monkeypatch):
        """A row added before this feature existed (no company_name at
        creation) can still opt in later via PATCH — same mechanism, applied
        after the fact instead of at add time."""
        _seed_held_instrument_with_isin("EL.PA.US", "FR0000121667")
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: None)
        created = client.post("/api/watchlist", json={"broker_symbol": "ESLOY.US"}).json()
        assert created["instrument"]["isin"] is None

        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: "FR0000121667")
        response = client.patch(f"/api/watchlist/{created['id']}", json={"company_name": "EssilorLuxottica"})

        assert response.status_code == 200
        body = response.json()
        assert body["instrument"]["isin"] == "FR0000121667"
        assert "EL.PA.US" in body["duplicate_warning"]


class TestListUpdateDelete:
    def test_list_and_update(self, client):
        created = client.post(
            "/api/watchlist", json={"broker_symbol": "MC.FR", "note": "wait for a dip"}
        ).json()

        listed = client.get("/api/watchlist").json()
        assert len(listed) == 1
        assert listed[0]["note"] == "wait for a dip"

        updated = client.patch(
            f"/api/watchlist/{created['id']}",
            json={"target_entry_price": 120.0, "note": "still waiting"},
        ).json()
        assert updated["target_entry_price"] == pytest.approx(120.0)
        assert updated["note"] == "still waiting"

    def test_delete(self, client):
        created = client.post("/api/watchlist", json={"broker_symbol": "MC.FR"}).json()

        response = client.delete(f"/api/watchlist/{created['id']}")

        assert response.status_code == 204
        assert client.get("/api/watchlist").json() == []

    def test_delete_unknown_is_404(self, client):
        assert client.delete("/api/watchlist/999").status_code == 404

    def test_update_unknown_is_404(self, client):
        response = client.patch("/api/watchlist/999", json={"note": "x"})
        assert response.status_code == 404


class TestHeldUnheldTransition:
    def test_buying_a_watched_symbol_hides_it_then_selling_reveals_it_again(self, client):
        created = client.post(
            "/api/watchlist",
            json={"broker_symbol": "MC.FR", "target_entry_price": 100.0, "note": "a real target"},
        ).json()
        instrument_id = created["instrument"]["id"]

        position = client.post(
            "/api/portfolio/positions", json={"broker_symbol": "MC.FR", "quantity": 1, "avg_price": 100.0}
        ).json()

        assert client.get("/api/watchlist").json() == []
        assert client.get("/api/watchlist/scores").json() == []
        assert client.get("/api/watchlist/sparklines").json() == []

        client.delete(f"/api/portfolio/positions/{position['id']}")

        reappeared = client.get("/api/watchlist").json()
        assert len(reappeared) == 1
        assert reappeared[0]["instrument"]["id"] == instrument_id
        assert reappeared[0]["target_entry_price"] == pytest.approx(100.0)
        assert reappeared[0]["note"] == "a real target"

    def test_delete_still_works_on_a_currently_hidden_item(self, client):
        created = client.post("/api/watchlist", json={"broker_symbol": "MC.FR"}).json()
        client.post("/api/portfolio/positions", json={"broker_symbol": "MC.FR", "quantity": 1, "avg_price": 100.0})

        response = client.delete(f"/api/watchlist/{created['id']}")

        assert response.status_code == 204


class TestScoresAndSparklines:
    def test_scores_endpoint_returns_one_entry_per_watched_instrument(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars()))
        client.post("/api/watchlist", json={"broker_symbol": "MC.FR"})

        scores = client.get("/api/watchlist/scores").json()

        assert len(scores) == 1

    def test_sparklines_returns_closes_for_watched_instrument(self, client, monkeypatch):
        use_provider(monkeypatch, FakeProvider("yahoo", bars=daily_bars(close=42.0)))
        client.post("/api/watchlist", json={"broker_symbol": "MC.FR"})

        sparklines = client.get("/api/watchlist/sparklines").json()

        assert len(sparklines) == 1
        assert sparklines[0]["closes"][-1] == pytest.approx(42.0)

    def test_sparklines_reflect_a_confirmed_split(self, client):
        """Same adjustment as the main price chart — a watched instrument's
        mini trend chart must not show a fake cliff either."""
        from app.models import CorporateAction, PriceBar, WatchlistItem

        session = next(app.dependency_overrides[get_db]())
        try:
            instrument = Instrument(broker_symbol="SPLIT.US", category="STOCK", currency="USD", country="US")
            session.add(instrument)
            session.commit()
            session.refresh(instrument)
            since = date.today() - timedelta(days=5)
            session.add_all(
                [
                    PriceBar(instrument_id=instrument.id, bar_date=since, close=1000.0),
                    PriceBar(instrument_id=instrument.id, bar_date=since + timedelta(days=1), close=100.0),
                    WatchlistItem(instrument_id=instrument.id),
                    CorporateAction(
                        instrument_id=instrument.id, action_type="split",
                        effective_date=since + timedelta(days=1), ratio_numerator=10, ratio_denominator=1,
                        source="manual", price_history_status="raw",
                    ),
                ]
            )
            session.commit()
        finally:
            session.close()

        sparklines = client.get("/api/watchlist/sparklines").json()

        assert sparklines[0]["closes"] == pytest.approx([100.0, 100.0])
