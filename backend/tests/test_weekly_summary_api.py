"""End-to-end tests for `GET /api/weekly-summary`.

The endpoint only composes indicators other endpoints already compute, so
these tests check the composition — which rows reach each section and which
don't — not the underlying rules (`test_position_signals.py`,
`test_personal_policy_api.py`, `test_attention_api.py` own those).
`compute_scores` is monkeypatched the same way `test_position_signals.py`
does it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Instrument, JournalEntry, Position, PriceBar, WatchlistItem
from app.scoring.service import InstrumentScore

TODAY = datetime.now(UTC).date()


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


def _instrument(symbol: str, category: str, price: float) -> Instrument:
    instrument = Instrument(broker_symbol=symbol, name=f"{symbol} name", category=category, currency="EUR", country="FR")
    _seed([instrument])
    _seed([PriceBar(instrument_id=instrument.id, bar_date=TODAY - timedelta(days=1), close=price, provider="test")])
    return instrument


def held(symbol: str, category: str, quantity: float, price: float) -> Instrument:
    instrument = _instrument(symbol, category, price)
    _seed([Position(instrument_id=instrument.id, source="MANUAL", quantity=quantity, avg_price=price)])
    return instrument


def watched(symbol: str, price: float, target: float | None) -> Instrument:
    instrument = _instrument(symbol, "STOCK", price)
    _seed([WatchlistItem(instrument_id=instrument.id, target_entry_price=target)])
    return instrument


def fake_scores(composites: dict[int, float | None]):
    def _compute(db, instruments, config):
        return [InstrumentScore(instrument_id=i.id, composite=composites.get(i.id), pillars=[]) for i in instruments]

    return _compute


def patch_scores(monkeypatch, composites):
    monkeypatch.setattr("app.routers.portfolio.compute_scores", fake_scores(composites))
    monkeypatch.setattr("app.routers.watchlist.compute_scores", fake_scores(composites))


def test_empty_database_returns_every_section_empty(client):
    body = client.get("/api/weekly-summary").json()

    assert body["as_of"] == TODAY.isoformat()
    assert body["window_end"] == (TODAY + timedelta(days=7)).isoformat()
    for section in (
        "policy_gaps", "allocation_gaps", "position_flags", "watchlist_flags", "journal_due", "data_reliability",
    ):
        assert body[section] == []


def test_policy_and_allocation_gaps_are_included_and_within_rows_are_not(client, monkeypatch):
    held("AAA.FR", "STOCK", quantity=9, price=100.0)  # 90%
    held("BBB.FR", "ETF", quantity=1, price=100.0)  # 10%
    client.put("/api/portfolio/allocation/STOCK", json={"min_pct": 0, "max_pct": 50})  # over
    client.put("/api/portfolio/allocation/ETF", json={"min_pct": 0, "max_pct": 100})  # within
    client.post("/api/portfolio/policy/limits", json={"dimension": "line", "max_pct": 50})
    patch_scores(monkeypatch, {})

    body = client.get("/api/weekly-summary").json()

    assert [(r["category"], r["state"]) for r in body["allocation_gaps"]] == [("STOCK", "over")]
    assert body["allocation_gaps"][0]["gap_pct"] == pytest.approx(40.0)
    assert [(g["dimension"], g["target"], g["state"]) for g in body["policy_gaps"]] == [("line", "AAA.FR", "over")]


def test_position_flags_keep_only_aligned_signals_with_weight(client, monkeypatch):
    stock = held("AAA.FR", "STOCK", quantity=9, price=100.0)  # 90%, over a 50% max
    etf = held("BBB.FR", "ETF", quantity=1, price=100.0)  # 10%, no target
    client.put("/api/portfolio/allocation/STOCK", json={"min_pct": 0, "max_pct": 50})
    patch_scores(monkeypatch, {stock.id: 20.0, etf.id: 90.0})

    flags = client.get("/api/weekly-summary").json()["position_flags"]

    # ETF has no target -> not_applicable -> not surfaced.
    assert len(flags) == 1
    flag = flags[0]
    assert flag["instrument_id"] == stock.id
    assert flag["symbol"] == "AAA.FR"
    assert flag["name"] == "AAA.FR name"
    assert flag["signal"] == "reduce"
    assert flag["score_band"] == "low"
    assert flag["allocation_state"] == "over"
    assert flag["weight_percent"] == pytest.approx(90.0)


def test_position_weight_sums_the_same_instrument_across_accounts(client, monkeypatch):
    etf = held("BBB.FR", "ETF", quantity=1, price=100.0)
    _seed([Position(instrument_id=etf.id, source="MANUAL", account="Other", quantity=1, avg_price=100.0)])
    held("AAA.FR", "STOCK", quantity=8, price=100.0)
    client.put("/api/portfolio/allocation/ETF", json={"min_pct": 50, "max_pct": 100})  # 20% -> under
    patch_scores(monkeypatch, {etf.id: 90.0})

    flags = client.get("/api/weekly-summary").json()["position_flags"]

    assert [(f["symbol"], f["signal"]) for f in flags] == [("BBB.FR", "reinforce")]
    assert flags[0]["weight_percent"] == pytest.approx(20.0)


def test_watchlist_flags_target_reached_and_near_target_high_score(client, monkeypatch):
    reached = watched("REACH.FR", price=95.0, target=100.0)  # -5%, low score: still reached
    near_high = watched("NEAR.FR", price=103.0, target=100.0)  # +3%, high score
    near_mid = watched("MID.FR", price=103.0, target=100.0)  # +3%, mid score: not surfaced
    far = watched("FAR.FR", price=120.0, target=100.0)  # +20%: not surfaced
    no_target = watched("NONE.FR", price=50.0, target=None)
    patch_scores(
        monkeypatch,
        {reached.id: 10.0, near_high.id: 80.0, near_mid.id: 50.0, far.id: 90.0, no_target.id: 90.0},
    )

    flags = client.get("/api/weekly-summary").json()["watchlist_flags"]

    assert [(f["symbol"], f["kind"]) for f in flags] == [
        ("REACH.FR", "target_reached"),
        ("NEAR.FR", "near_target_high_score"),
    ]
    assert flags[0]["distance_to_target_pct"] == pytest.approx(-5.0)
    assert flags[0]["target_entry_price"] == 100.0


def test_journal_due_covers_overdue_and_the_next_seven_days_only(client):
    instrument = _instrument("AAA.FR", "STOCK", 100.0)
    _seed([
        JournalEntry(thesis="overdue", entry_date=TODAY - timedelta(days=30), review_date=TODAY - timedelta(days=2),
                     instrument_id=instrument.id),
        JournalEntry(thesis="this week", entry_date=TODAY, review_date=TODAY + timedelta(days=7)),
        JournalEntry(thesis="later", entry_date=TODAY, review_date=TODAY + timedelta(days=8)),
        JournalEntry(thesis="no date", entry_date=TODAY),
        JournalEntry(thesis="reviewed", entry_date=TODAY, review_date=TODAY - timedelta(days=1), outcome_note="done"),
    ])

    due = client.get("/api/weekly-summary").json()["journal_due"]

    assert [(d["thesis"], d["overdue"], d["symbol"]) for d in due] == [
        ("overdue", True, "AAA.FR"),
        ("this week", False, None),
    ]


def test_data_reliability_keeps_data_kinds_only(client, monkeypatch):
    held("AAA.FR", "STOCK", quantity=9, price=100.0)
    client.put("/api/portfolio/allocation/STOCK", json={"min_pct": 0, "max_pct": 50})
    stale = Instrument(broker_symbol="OLD.FR", category="STOCK", currency="EUR", country="FR")
    _seed([stale])
    _seed([
        PriceBar(instrument_id=stale.id, bar_date=TODAY - timedelta(days=60), close=10.0, provider="test"),
        Position(instrument_id=stale.id, source="MANUAL", quantity=1, avg_price=10.0),
    ])
    patch_scores(monkeypatch, {})

    kinds = [i["kind"] for i in client.get("/api/weekly-summary").json()["data_reliability"]]

    # The STOCK allocation gap belongs to its own section, not this one.
    assert "allocation_over" not in kinds
    assert kinds  # the 60-day-old price is flagged one way or another
    assert set(kinds) <= {"price_error", "price_stale", "unresolved_instruments"}


def test_portfolio_valuation_is_computed_once_per_request(client, monkeypatch):
    held("AAA.FR", "STOCK", quantity=9, price=100.0)
    client.put("/api/portfolio/allocation/STOCK", json={"min_pct": 0, "max_pct": 50})
    client.post("/api/portfolio/policy/limits", json={"dimension": "line", "max_pct": 50})
    patch_scores(monkeypatch, {})

    import app.routers.portfolio as portfolio

    calls = []
    original = portfolio._compute_figures

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(portfolio, "_compute_figures", counting)

    body = client.get("/api/weekly-summary").json()

    assert body["allocation_gaps"] and body["policy_gaps"]
    assert len(calls) == 1
