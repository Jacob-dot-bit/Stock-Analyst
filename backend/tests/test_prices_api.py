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

from app.db import Base, get_db
from app.main import app
from app.providers.base import Bar, ProviderChain, RateLimited
from tests.test_providers import FakeProvider


@pytest.fixture
def client(monkeypatch, tmp_path):
    # A real file, not `StaticPool`-backed `:memory:`: the price refresh now
    # runs several instruments concurrently, each in its own DB session
    # (DEVLOG "Decision 3n.1") — StaticPool hands every session the exact same
    # underlying sqlite3 connection object, which is not safe to drive from
    # multiple threads at once (unlike a real file, where each session gets
    # its own pooled connection, exactly as production already works).
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

    def test_a_watchlisted_instrument_is_included_in_a_general_refresh(self, client, monkeypatch):
        # The watchlist add flow best-effort-fetches on its own -- pin it to
        # no providers so that fetch is a no-op and doesn't consume the
        # FakeProvider's call count set up below for the refresh under test.
        monkeypatch.setattr("app.routers.watchlist.get_provider_chain", lambda: ProviderChain([]))
        client.post("/api/watchlist", json={"broker_symbol": "MC.FR"})

        provider = FakeProvider("yahoo", bars=daily_bars())
        use_provider(monkeypatch, provider)
        client.post("/api/prices/refresh")

        assert provider.calls == 1
        watched = client.get("/api/watchlist").json()
        assert watched[0]["current_price"] is not None

    def test_a_watchlisted_instrument_is_excluded_from_a_targeted_retry(self, client, monkeypatch):
        monkeypatch.setattr("app.routers.watchlist.get_provider_chain", lambda: ProviderChain([]))
        client.post(
            "/api/portfolio/positions", json={"broker_symbol": "AAPL.US", "quantity": 1, "avg_price": 100.0}
        )
        client.post("/api/watchlist", json={"broker_symbol": "MC.FR"})

        provider = FakeProvider("yahoo", bars=daily_bars())
        use_provider(monkeypatch, provider)
        client.post("/api/prices/refresh?symbols=AAPL.US")

        assert provider.calls == 1
        watched = client.get("/api/watchlist").json()
        assert watched[0]["current_price"] is None

    def test_a_screener_candidate_is_included_in_a_general_refresh(self, client, monkeypatch):
        monkeypatch.setattr("app.routers.screener.get_provider_chain", lambda: ProviderChain([]))
        client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        provider = FakeProvider("yahoo", bars=daily_bars())
        use_provider(monkeypatch, provider)
        client.post("/api/prices/refresh")

        assert provider.calls == 1
        candidates = client.get("/api/screener").json()
        assert candidates[0]["current_price"] is not None

    def test_a_screener_candidate_is_excluded_from_a_targeted_retry(self, client, monkeypatch):
        monkeypatch.setattr("app.routers.screener.get_provider_chain", lambda: ProviderChain([]))
        client.post(
            "/api/portfolio/positions", json={"broker_symbol": "AAPL.US", "quantity": 1, "avg_price": 100.0}
        )
        client.post("/api/screener", json={"broker_symbol": "MC.FR"})

        provider = FakeProvider("yahoo", bars=daily_bars())
        use_provider(monkeypatch, provider)
        client.post("/api/prices/refresh?symbols=AAPL.US")

        assert provider.calls == 1
        candidates = client.get("/api/screener").json()
        assert candidates[0]["current_price"] is None


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

    def test_reflects_a_confirmed_split(self, client, monkeypatch, xtb_export):
        """A raw, unadjusted 10-for-1 split (real pre-split price ~10x the
        post-split one) must not show as a fake cliff once recorded — this
        is the chart the user actually looks at."""
        import_statement(client, xtb_export)
        split_day = date.today() - timedelta(days=2)
        bars = [
            Bar(bar_date=split_day - timedelta(days=1), open=1000, high=1000, low=1000, close=1000.0, volume=100),
            Bar(bar_date=split_day, open=100, high=100, low=100, close=100.0, volume=100),
            Bar(bar_date=split_day + timedelta(days=1), open=101, high=101, low=101, close=101.0, volume=100),
        ]
        use_provider(monkeypatch, FakeProvider("yahoo", bars=bars))
        client.post("/api/prices/refresh")

        instrument_id = client.get("/api/portfolio").json()["positions"][0]["instrument"]["id"]
        before = client.get(f"/api/prices/{instrument_id}/history").json()
        raw_by_date = {p["date"]: p["close"] for p in before["points"]}
        assert raw_by_date[split_day.isoformat()] == pytest.approx(100.0)

        created = client.post(
            "/api/corporate-actions",
            json={
                "instrument_id": instrument_id,
                "action_type": "split",
                "effective_date": split_day.isoformat(),
                "ratio_numerator": 10,
                "ratio_denominator": 1,
            },
        )
        assert created.status_code == 201
        assert created.json()["price_history_status"] == "raw"

        after = client.get(f"/api/prices/{instrument_id}/history").json()
        adjusted_by_date = {p["date"]: p["close"] for p in after["points"]}

        # The pre-split close is restated to the post-split basis — smooth
        # across the split date instead of a fake 10x cliff.
        assert adjusted_by_date[(split_day - timedelta(days=1)).isoformat()] == pytest.approx(100.0)
        assert adjusted_by_date[split_day.isoformat()] == pytest.approx(100.0)
        assert adjusted_by_date[(split_day + timedelta(days=1)).isoformat()] == pytest.approx(101.0)


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


class TestUnresolvedPanelOnlyAsksAnswerableQuestions:
    """The panel tells the user to correct things, so it must only list correctable ones.

    A CVR whose broker symbol *is* its ISIN has no ticker to supply. Listing it sends
    the user hunting for something that does not exist.
    """

    def test_an_instrument_carrying_an_isin_is_not_listed(self, client):
        client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "US592CVR0133", "quantity": 1, "avg_price": 10},
        )
        client.put(
            "/api/portfolio/isin",
            json={"broker_symbol": "US592CVR0133", "isin": "US592CVR0133"},
        )

        unresolved = client.get("/api/portfolio").json()["unresolved_symbols"]

        assert [i["broker_symbol"] for i in unresolved] == []

    def test_a_genuinely_unidentified_symbol_is_still_listed(self, client):
        """The panel must keep working for cases the user really can fix."""
        client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "WEIRD.ZZ", "quantity": 1, "avg_price": 10},
        )

        unresolved = client.get("/api/portfolio").json()["unresolved_symbols"]

        assert [i["broker_symbol"] for i in unresolved] == ["WEIRD.ZZ"]
