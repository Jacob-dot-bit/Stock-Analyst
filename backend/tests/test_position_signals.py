"""End-to-end tests for `GET /api/portfolio/position-signals` and
`GET /api/watchlist/signals`.

Both are a transparent, rule-based combination of two indicators the app
already shows separately — never a new analysis, only a label for their
combination (see `routers/portfolio.py::_position_signal`'s docstring).
`compute_scores` is monkeypatched throughout: constructing real fundamentals
data to hit an exact composite score would obscure what's actually under
test (the combination rule, not the scoring pipeline itself — that's
`test_scoring_service.py`'s job).
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
from app.models import Instrument, Position, WatchlistItem
from app.scoring.service import InstrumentScore


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


def held_instrument(symbol: str, category: str, quantity: float, price: float) -> Instrument:
    from app.models import PriceBar

    instrument = Instrument(broker_symbol=symbol, category=category, currency="EUR", country="FR")
    _seed([instrument])
    bar = PriceBar(instrument_id=instrument.id, bar_date=date.today() - timedelta(days=1), close=price, provider="test")
    position = Position(instrument_id=instrument.id, source="MANUAL", quantity=quantity, avg_price=price)
    _seed([bar, position])
    return instrument


def fake_scores(composites: dict[int, float | None]):
    def _compute(db, instruments, config):
        return [InstrumentScore(instrument_id=i.id, composite=composites.get(i.id), pillars=[]) for i in instruments]

    return _compute


class TestPositionSignals:
    def test_reinforce_when_high_score_and_under_allocated(self, client, monkeypatch):
        # ETF held at 10% of the portfolio, target range 50-100% -> "under".
        stock = held_instrument("AAA.FR", "STOCK", quantity=9, price=100.0)  # 900 EUR
        etf = held_instrument("BBB.FR", "ETF", quantity=1, price=100.0)  # 100 EUR
        client.put("/api/portfolio/allocation/ETF", json={"min_pct": 50, "max_pct": 100})
        monkeypatch.setattr(
            "app.routers.portfolio.compute_scores", fake_scores({stock.id: 50.0, etf.id: 80.0})
        )

        rows = {r["instrument_id"]: r for r in client.get("/api/portfolio/position-signals").json()}

        assert rows[etf.id]["signal"] == "reinforce"
        assert rows[etf.id]["score_band"] == "high"
        assert rows[etf.id]["allocation_state"] == "under"
        # 10% held vs. a 50% minimum -> 40 points short.
        assert rows[etf.id]["gap_pct"] == pytest.approx(40.0)

    def test_reduce_when_low_score_and_over_allocated(self, client, monkeypatch):
        stock = held_instrument("AAA.FR", "STOCK", quantity=9, price=100.0)  # 900 EUR, 90%
        etf = held_instrument("BBB.FR", "ETF", quantity=1, price=100.0)  # 100 EUR, 10%
        client.put("/api/portfolio/allocation/STOCK", json={"min_pct": 0, "max_pct": 50})
        monkeypatch.setattr(
            "app.routers.portfolio.compute_scores", fake_scores({stock.id: 20.0, etf.id: 50.0})
        )

        rows = {r["instrument_id"]: r for r in client.get("/api/portfolio/position-signals").json()}

        assert rows[stock.id]["signal"] == "reduce"
        assert rows[stock.id]["score_band"] == "low"
        assert rows[stock.id]["allocation_state"] == "over"

    def test_not_applicable_without_a_configured_target(self, client, monkeypatch):
        stock = held_instrument("AAA.FR", "STOCK", quantity=1, price=100.0)
        monkeypatch.setattr("app.routers.portfolio.compute_scores", fake_scores({stock.id: 90.0}))

        row = client.get("/api/portfolio/position-signals").json()[0]

        assert row["allocation_state"] == "no_target"
        assert row["signal"] == "not_applicable"

    def test_not_applicable_without_a_score(self, client, monkeypatch):
        stock = held_instrument("AAA.FR", "STOCK", quantity=1, price=100.0)
        client.put("/api/portfolio/allocation/STOCK", json={"min_pct": 0, "max_pct": 100})
        monkeypatch.setattr("app.routers.portfolio.compute_scores", fake_scores({stock.id: None}))

        row = client.get("/api/portfolio/position-signals").json()[0]

        assert row["score_band"] == "none"
        assert row["signal"] == "not_applicable"

    def test_hold_when_signals_do_not_line_up(self, client, monkeypatch):
        # High score but within range (not under) -> no reinforce case applies.
        stock = held_instrument("AAA.FR", "STOCK", quantity=1, price=100.0)
        client.put("/api/portfolio/allocation/STOCK", json={"min_pct": 0, "max_pct": 100})
        monkeypatch.setattr("app.routers.portfolio.compute_scores", fake_scores({stock.id: 90.0}))

        row = client.get("/api/portfolio/position-signals").json()[0]

        assert row["allocation_state"] == "within"
        assert row["signal"] == "hold"


class TestWatchlistSignals:
    def _watch(self, broker_symbol: str, price: float, target_entry_price: float | None) -> Instrument:
        from app.models import PriceBar

        instrument = Instrument(broker_symbol=broker_symbol, category="STOCK", currency="EUR", country="FR")
        _seed([instrument])
        bar = PriceBar(instrument_id=instrument.id, bar_date=date.today() - timedelta(days=1), close=price, provider="test")
        item = WatchlistItem(instrument_id=instrument.id, target_entry_price=target_entry_price)
        _seed([bar, item])
        return instrument

    def test_reinforce_when_price_at_or_below_target_and_high_score(self, client, monkeypatch):
        instrument = self._watch("AAA.FR", price=90.0, target_entry_price=100.0)
        monkeypatch.setattr("app.routers.watchlist.compute_scores", fake_scores({instrument.id: 80.0}))

        row = client.get("/api/watchlist/signals").json()[0]

        assert row["signal"] == "reinforce"

    def test_hold_when_price_above_target(self, client, monkeypatch):
        instrument = self._watch("AAA.FR", price=110.0, target_entry_price=100.0)
        monkeypatch.setattr("app.routers.watchlist.compute_scores", fake_scores({instrument.id: 80.0}))

        row = client.get("/api/watchlist/signals").json()[0]

        assert row["signal"] == "hold"

    def test_not_applicable_without_a_target_price(self, client, monkeypatch):
        instrument = self._watch("AAA.FR", price=90.0, target_entry_price=None)
        monkeypatch.setattr("app.routers.watchlist.compute_scores", fake_scores({instrument.id: 80.0}))

        row = client.get("/api/watchlist/signals").json()[0]

        assert row["signal"] == "not_applicable"

    def test_not_applicable_without_a_score(self, client, monkeypatch):
        instrument = self._watch("AAA.FR", price=90.0, target_entry_price=100.0)
        monkeypatch.setattr("app.routers.watchlist.compute_scores", fake_scores({instrument.id: None}))

        row = client.get("/api/watchlist/signals").json()[0]

        assert row["signal"] == "not_applicable"

    def test_never_reduce(self, client, monkeypatch):
        """Nothing here is held — a low score at or below target must never
        read as "reduce", since there is nothing to reduce."""
        instrument = self._watch("AAA.FR", price=80.0, target_entry_price=100.0)
        monkeypatch.setattr("app.routers.watchlist.compute_scores", fake_scores({instrument.id: 10.0}))

        row = client.get("/api/watchlist/signals").json()[0]

        assert row["signal"] != "reduce"
