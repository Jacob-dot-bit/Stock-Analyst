"""End-to-end tests for the discovery (auto-screening) endpoints.

`compute_scores` is monkeypatched throughout (same convention as
`test_position_signals.py`): constructing real fundamentals to hit an
exact Value/Growth score would obscure what's actually under test here —
the discovery plumbing (import, anti-join, ranking, budgeted batching),
not the scoring pipeline itself (covered by `test_scoring_service.py`).
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.discovery.service import refresh_batch
from app.ingest.service import get_or_create_instrument
from app.main import app
from app.models import (
    DiscoveryCandidate,
    Instrument,
    Position,
    ProviderCorporateActionCandidate,
    ScreenerCandidate,
    WatchlistItem,
)
from app.providers.base import Bar, ProviderChain, RateLimited, SymbolNotFound
from app.scoring.service import InstrumentScore, PillarScore
from tests.test_providers import FakeProvider


@pytest.fixture
def client(tmp_path):
    # A real file, not `StaticPool`-backed `:memory:`: `POST /discovery/refresh`
    # goes through `refresh_many`, which runs several instruments concurrently,
    # each in its own DB session (DEVLOG "Decision 3n.1") — StaticPool hands
    # every session the exact same underlying sqlite3 connection object, not
    # safe to drive from multiple threads at once. Same fixture convention as
    # `test_prices_api.py`.
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


def _sp500_fixture(tmp_path, rows):
    path = tmp_path / "sp500_fixture.json"
    path.write_text(json.dumps({"source": "test", "fetched_at": "2026-01-01", "constituents": rows}))
    return path


def _mapped_instrument(broker_symbol: str) -> Instrument:
    """A bare `Instrument(...)` never gets a `provider_symbol`/resolved
    `mapping_status` — those come from `get_or_create_instrument`'s own
    XTB-symbol-to-provider-symbol conversion. `refresh_instrument` refuses
    to even attempt a fetch without one (`NOT_MAPPED`), so any test that
    needs a real `refresh_instrument` call to succeed must go through this,
    not construct the model directly."""
    session = next(app.dependency_overrides[get_db]())
    try:
        instrument = get_or_create_instrument(session, broker_symbol, currency="USD", category="STOCK")
        session.commit()
        session.refresh(instrument)
    finally:
        session.close()
    return instrument


def daily_bars(close: float = 100.0, count: int = 30) -> list[Bar]:
    today = date.today()
    return [
        Bar(bar_date=today - timedelta(days=count - 1 - i), open=close, high=close, low=close, close=close, volume=1_000)
        for i in range(count)
    ]


class FakeEdgarProvider:
    name = "edgar"

    def __init__(self, enabled=True, error=None):
        self._enabled = enabled
        self._error = error

    def is_enabled(self):
        return self._enabled

    def fetch(self, ticker, expected_name=None):
        if self._error:
            raise self._error
        raise SymbolNotFound("no fake fundamentals configured")


class FakeEsefProvider:
    def fetch(self, name):
        raise SymbolNotFound("no fake fundamentals configured")


def fake_scores(pillars_by_id: dict[int, dict]):
    """`pillars_by_id`: {instrument_id: {"value": x, "growth": y, "composite": z}}."""

    def _compute(db, instruments, config):
        results = []
        for instrument in instruments:
            fields = pillars_by_id.get(instrument.id)
            if fields is None:
                continue
            results.append(
                InstrumentScore(
                    instrument_id=instrument.id,
                    composite=fields.get("composite", 50.0),
                    pillars=[
                        PillarScore(name="value", score=fields.get("value"), weight_used=30.0),
                        PillarScore(name="growth", score=fields.get("growth"), weight_used=25.0),
                    ],
                    market_cap=fields.get("market_cap"),
                    debt_ratio=fields.get("debt_ratio"),
                    price_history_years=fields.get("price_history_years"),
                )
            )
        return results

    return _compute


class TestImportSp500:
    def test_imports_the_static_universe(self, client, monkeypatch, tmp_path):
        path = _sp500_fixture(
            tmp_path,
            [
                {"broker_symbol": "AAA.US", "name": "Company A", "sector": "Technology"},
                {"broker_symbol": "BBB.US", "name": "Company B", "sector": "Healthcare"},
            ],
        )
        monkeypatch.setattr("app.discovery.service.SP500_DATA_PATH", path)

        response = client.post("/api/discovery/import-sp500")

        assert response.status_code == 200
        assert response.json() == {"imported": 2, "already_present": 0}

    def test_reimport_is_idempotent(self, client, monkeypatch, tmp_path):
        path = _sp500_fixture(tmp_path, [{"broker_symbol": "AAA.US", "name": "Company A", "sector": "Technology"}])
        monkeypatch.setattr("app.discovery.service.SP500_DATA_PATH", path)

        client.post("/api/discovery/import-sp500")
        response = client.post("/api/discovery/import-sp500")

        assert response.json() == {"imported": 0, "already_present": 1}


class TestCandidates:
    def test_ranks_by_value_score_descending(self, client, monkeypatch):
        a = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        b = Instrument(broker_symbol="BBB.US", category="STOCK", currency="USD", country="US")
        _seed([a, b])
        _seed(
            [
                DiscoveryCandidate(instrument_id=a.id, source="sp500"),
                DiscoveryCandidate(instrument_id=b.id, source="sp500"),
            ]
        )
        monkeypatch.setattr(
            "app.discovery.service.compute_scores", fake_scores({a.id: {"value": 40}, b.id: {"value": 90}})
        )

        response = client.get("/api/discovery/candidates?rank_by=value")

        body = response.json()
        assert [c["instrument"]["broker_symbol"] for c in body] == ["BBB.US", "AAA.US"]
        assert body[0]["value_score"] == pytest.approx(90.0)
        assert body[0]["source"] == "sp500"

    def test_ranks_by_growth_when_requested(self, client, monkeypatch):
        a = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        b = Instrument(broker_symbol="BBB.US", category="STOCK", currency="USD", country="US")
        _seed([a, b])
        _seed(
            [
                DiscoveryCandidate(instrument_id=a.id, source="sp500"),
                DiscoveryCandidate(instrument_id=b.id, source="sp500"),
            ]
        )
        monkeypatch.setattr(
            "app.discovery.service.compute_scores",
            fake_scores({a.id: {"growth": 95, "value": 10}, b.id: {"growth": 20, "value": 99}}),
        )

        response = client.get("/api/discovery/candidates?rank_by=growth")

        body = response.json()
        assert body[0]["instrument"]["broker_symbol"] == "AAA.US"
        assert body[0]["growth_score"] == pytest.approx(95.0)

    def test_recommendation_derives_from_composite_score_band(self, client, monkeypatch):
        """"buy"/"hold"/"sell" is a deliberate, user-requested exception to
        this app's usual fact-based labeling — scoped to Discovery only.
        See DEVLOG "Decision 3u.21"."""
        buy = Instrument(broker_symbol="BUY.US", category="STOCK", currency="USD", country="US")
        hold = Instrument(broker_symbol="HOLD.US", category="STOCK", currency="USD", country="US")
        sell = Instrument(broker_symbol="SELL.US", category="STOCK", currency="USD", country="US")
        _seed([buy, hold, sell])
        _seed(
            [
                DiscoveryCandidate(instrument_id=buy.id, source="sp500"),
                DiscoveryCandidate(instrument_id=hold.id, source="sp500"),
                DiscoveryCandidate(instrument_id=sell.id, source="sp500"),
            ]
        )
        monkeypatch.setattr(
            "app.discovery.service.compute_scores",
            fake_scores(
                {
                    buy.id: {"value": 80, "composite": 80},
                    hold.id: {"value": 60, "composite": 50},
                    sell.id: {"value": 40, "composite": 10},
                }
            ),
        )

        response = client.get("/api/discovery/candidates?rank_by=value")

        by_symbol = {c["instrument"]["broker_symbol"]: c["recommendation"] for c in response.json()}
        assert by_symbol == {"BUY.US": "buy", "HOLD.US": "hold", "SELL.US": "sell"}

    def test_price_status_is_computed_per_candidate(self, client, monkeypatch):
        """Powers the data-quality filter's "cours récent, pas de souci de
        mapping" condition — reuses `prices/service.py::price_status`
        unchanged, same signal the positions/screener/watchlist tables
        already show. A bare `Instrument()` here never gets a
        `provider_symbol` (see `_mapped_instrument`'s own docstring), so it
        reads as "unmapped"."""
        a = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        _seed([a])
        _seed([DiscoveryCandidate(instrument_id=a.id, source="sp500")])
        monkeypatch.setattr("app.discovery.service.compute_scores", fake_scores({a.id: {"value": 90}}))

        response = client.get("/api/discovery/candidates?rank_by=value")

        assert response.json()[0]["instrument"]["price_status"] == "unmapped"

    def test_corporate_action_pending_true_when_an_outstanding_candidate_exists(self, client, monkeypatch):
        """Powers the data-quality filter's "sans corporate action en
        attente" condition — reuses
        `corporate_actions/service.py::list_outstanding_candidates`
        unchanged, the same merge/classify engine Data Health and the
        "Candidats à confirmer" list already rely on. A single provider's
        `ok` row with no corroborating source classifies as
        `candidate_single_source` — outstanding, never auto-applied."""
        a = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US", provider_symbol="AAA")
        _seed([a])
        _seed([DiscoveryCandidate(instrument_id=a.id, source="sp500")])
        _seed(
            [
                ProviderCorporateActionCandidate(
                    instrument_id=a.id, provider="alpha_vantage",
                    event_date=date(2024, 1, 1), event_type="split",
                    numerator=2, denominator=1, provider_status="ok",
                )
            ]
        )
        monkeypatch.setattr("app.discovery.service.compute_scores", fake_scores({a.id: {"value": 90}}))

        response = client.get("/api/discovery/candidates?rank_by=value")

        assert response.json()[0]["corporate_action_pending"] is True

    def test_corporate_action_pending_false_with_no_outstanding_candidate(self, client, monkeypatch):
        a = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        _seed([a])
        _seed([DiscoveryCandidate(instrument_id=a.id, source="sp500")])
        monkeypatch.setattr("app.discovery.service.compute_scores", fake_scores({a.id: {"value": 90}}))

        response = client.get("/api/discovery/candidates?rank_by=value")

        assert response.json()[0]["corporate_action_pending"] is False

    def test_excludes_a_candidate_with_no_score_for_the_requested_pillar(self, client, monkeypatch):
        a = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        _seed([a])
        _seed([DiscoveryCandidate(instrument_id=a.id, source="sp500")])
        monkeypatch.setattr("app.discovery.service.compute_scores", fake_scores({a.id: {"growth": 80}}))

        response = client.get("/api/discovery/candidates?rank_by=value")

        assert response.json() == []

    def test_excludes_an_already_held_instrument(self, client, monkeypatch):
        held = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        _seed([held])
        _seed([DiscoveryCandidate(instrument_id=held.id, source="sp500")])
        _seed([Position(instrument_id=held.id, source="MANUAL", quantity=1, avg_price=10.0)])
        monkeypatch.setattr("app.discovery.service.compute_scores", fake_scores({held.id: {"value": 90}}))

        response = client.get("/api/discovery/candidates?rank_by=value")

        assert response.json() == []

    def test_excludes_an_already_watchlisted_instrument(self, client, monkeypatch):
        watched = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        _seed([watched])
        _seed([DiscoveryCandidate(instrument_id=watched.id, source="sp500")])
        _seed([WatchlistItem(instrument_id=watched.id)])
        monkeypatch.setattr("app.discovery.service.compute_scores", fake_scores({watched.id: {"value": 90}}))

        response = client.get("/api/discovery/candidates?rank_by=value")

        assert response.json() == []

    def test_excludes_an_already_screened_instrument(self, client, monkeypatch):
        screened = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        _seed([screened])
        _seed([DiscoveryCandidate(instrument_id=screened.id, source="sp500")])
        _seed([ScreenerCandidate(instrument_id=screened.id)])
        monkeypatch.setattr("app.discovery.service.compute_scores", fake_scores({screened.id: {"value": 90}}))

        response = client.get("/api/discovery/candidates?rank_by=value")

        assert response.json() == []

    def test_market_cap_debt_ratio_and_price_history_flow_through(self, client, monkeypatch):
        """New Pépites screening fields — informational, never affect
        ranking. See DEVLOG "Decision 3u.72"."""
        a = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        _seed([a])
        _seed([DiscoveryCandidate(instrument_id=a.id, source="sp500")])
        monkeypatch.setattr(
            "app.discovery.service.compute_scores",
            fake_scores({a.id: {"value": 50, "market_cap": 1_500_000_000.0, "debt_ratio": 0.42, "price_history_years": 3.5}}),
        )

        response = client.get("/api/discovery/candidates?rank_by=value")

        body = response.json()[0]
        assert body["market_cap"] == pytest.approx(1_500_000_000.0)
        assert body["debt_ratio"] == pytest.approx(0.42)
        assert body["price_history_years"] == pytest.approx(3.5)

    def test_market_cap_debt_ratio_and_price_history_default_to_null(self, client, monkeypatch):
        a = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        _seed([a])
        _seed([DiscoveryCandidate(instrument_id=a.id, source="sp500")])
        monkeypatch.setattr("app.discovery.service.compute_scores", fake_scores({a.id: {"value": 50}}))

        response = client.get("/api/discovery/candidates?rank_by=value")

        body = response.json()[0]
        assert body["market_cap"] is None
        assert body["debt_ratio"] is None
        assert body["price_history_years"] is None


class TestRefreshBatch:
    def test_evaluates_pending_candidates_and_reports_none_remaining(self, client, monkeypatch):
        instruments = [
            _mapped_instrument(f"AAA{i}.US") for i in range(3)
        ]
        _seed([DiscoveryCandidate(instrument_id=i.id, source="sp500") for i in instruments])

        monkeypatch.setattr(
            "app.routers.discovery.get_provider_chain", lambda: ProviderChain([FakeProvider("test", bars=daily_bars())])
        )
        monkeypatch.setattr("app.routers.discovery.get_edgar_provider", lambda: FakeEdgarProvider())
        monkeypatch.setattr("app.routers.discovery.get_esef_provider", lambda: FakeEsefProvider())

        response = client.post("/api/discovery/refresh")

        assert response.status_code == 200
        body = response.json()
        assert body["evaluated"] == 3
        assert body["remaining"] == 0

    def test_a_rate_limited_instrument_is_not_marked_verified(self, client, monkeypatch):
        instrument = _mapped_instrument("AAA.US")
        _seed([DiscoveryCandidate(instrument_id=instrument.id, source="sp500")])

        monkeypatch.setattr(
            "app.routers.discovery.get_provider_chain",
            lambda: ProviderChain([FakeProvider("test", error=RateLimited("slow down"))]),
        )
        monkeypatch.setattr("app.routers.discovery.get_edgar_provider", lambda: FakeEdgarProvider())
        monkeypatch.setattr("app.routers.discovery.get_esef_provider", lambda: FakeEsefProvider())

        response = client.post("/api/discovery/refresh")

        assert response.json()["remaining"] == 1

    def test_stops_at_the_batch_size_and_reports_the_rest_as_remaining(self, monkeypatch, tmp_path):
        """Service-level, not through the router: `batch_size` isn't a
        query param (deliberately fixed, see `discovery/service.py`'s
        `BATCH_SIZE` docstring), so exercising the cutoff means calling
        `refresh_batch` directly with an explicit small value. Real file,
        not StaticPool — same threading reasoning as the `client` fixture."""
        engine = create_engine(
            f"sqlite:///{tmp_path / 'test2.db'}", connect_args={"check_same_thread": False, "timeout": 30}
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            instruments = [
                get_or_create_instrument(db, f"AAA{i}.US", currency="USD", category="STOCK") for i in range(5)
            ]
            db.commit()
            for i in instruments:
                db.refresh(i)
            db.add_all([DiscoveryCandidate(instrument_id=i.id, source="sp500") for i in instruments])
            db.commit()

            chain = ProviderChain([FakeProvider("test", bars=daily_bars())])
            result = refresh_batch(db, chain, FakeEdgarProvider(), FakeEsefProvider(), batch_size=2)

            assert result == {"evaluated": 2, "remaining": 3}
        finally:
            db.close()


class TestFinvizScan:
    def test_fetches_preset_and_creates_a_candidate(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.routers.discovery.fetch_preset",
            lambda preset: [{"ticker": "ZZZ", "name": "Zzz Corp", "country": "USA", "industry": "Software"}],
        )
        monkeypatch.setattr(
            "app.routers.discovery.get_provider_chain", lambda: ProviderChain([FakeProvider("test", bars=daily_bars())])
        )
        monkeypatch.setattr("app.routers.discovery.get_edgar_provider", lambda: FakeEdgarProvider())
        monkeypatch.setattr("app.routers.discovery.get_esef_provider", lambda: FakeEsefProvider())

        response = client.post("/api/discovery/finviz?preset=insider_buys")

        assert response.status_code == 200
        body = response.json()
        assert body["preset"] == "insider_buys"
        assert len(body["candidates"]) == 1
        assert body["candidates"][0]["instrument"]["broker_symbol"] == "ZZZ.US"
        assert body["candidates"][0]["instrument"]["name"] == "Zzz Corp"
        assert body["candidates"][0]["source"] == "finviz:insider_buys"
        assert body["candidates"][0]["current_price"] == pytest.approx(100.0)
        assert body["failed"] == 0
        # No fundamentals seeded (`FakeEdgarProvider` raises), so there is
        # no composite score to derive a recommendation from — `None`, not
        # a guessed verdict.
        assert body["candidates"][0]["recommendation"] is None

    def test_finviz_recommendation_derives_from_composite_score_band(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.routers.discovery.fetch_preset",
            lambda preset: [{"ticker": "ZZZ", "name": "Zzz Corp"}],
        )
        monkeypatch.setattr(
            "app.routers.discovery.get_provider_chain", lambda: ProviderChain([FakeProvider("test", bars=daily_bars())])
        )
        monkeypatch.setattr("app.routers.discovery.get_edgar_provider", lambda: FakeEdgarProvider())
        monkeypatch.setattr("app.routers.discovery.get_esef_provider", lambda: FakeEsefProvider())

        def fake_compute_scores(db, instruments, config):
            # `fake_scores` keys by instrument id, but the instrument is
            # created fresh inside the router — key by whatever id it got.
            return fake_scores({i.id: {"value": 90, "composite": 80} for i in instruments})(db, instruments, config)

        monkeypatch.setattr("app.routers.discovery.compute_scores", fake_compute_scores)

        response = client.post("/api/discovery/finviz?preset=insider_buys")

        assert response.json()["candidates"][0]["recommendation"] == "buy"

    def test_one_failing_candidate_is_skipped_and_counted_not_discarding_the_others(self, client, monkeypatch):
        """A `compute_scores` blowup on one candidate must not sink every
        candidate already resolved earlier in the same sequential loop —
        this is the one place several live per-instrument fetches run back
        to back in a single request, unlike the rest of the app's
        single-instrument call sites. See DEVLOG "Decision 3u.20" addendum."""
        monkeypatch.setattr(
            "app.routers.discovery.fetch_preset",
            lambda preset: [
                {"ticker": "GOOD", "name": "Good Corp"},
                {"ticker": "BAD", "name": "Bad Corp"},
            ],
        )
        monkeypatch.setattr(
            "app.routers.discovery.get_provider_chain", lambda: ProviderChain([FakeProvider("test", bars=daily_bars())])
        )
        monkeypatch.setattr("app.routers.discovery.get_edgar_provider", lambda: FakeEdgarProvider())
        monkeypatch.setattr("app.routers.discovery.get_esef_provider", lambda: FakeEsefProvider())

        def flaky_compute_scores(db, instruments, config):
            for instrument in instruments:
                if instrument.broker_symbol == "BAD.US":
                    raise RuntimeError("boom")
            return []

        monkeypatch.setattr("app.routers.discovery.compute_scores", flaky_compute_scores)

        response = client.post("/api/discovery/finviz?preset=insider_buys")

        assert response.status_code == 200
        body = response.json()
        assert body["failed"] == 1
        assert len(body["candidates"]) == 1
        assert body["candidates"][0]["instrument"]["broker_symbol"] == "GOOD.US"

    def test_rejects_an_unlisted_preset(self, client):
        response = client.post("/api/discovery/finviz?preset=custom_pe_filter")

        assert response.status_code == 422
