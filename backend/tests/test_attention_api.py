"""End-to-end tests for `GET /api/portfolio/attention`.

Descriptive only — every item is a fact already computed elsewhere in the
app (price status, unresolved symbols, allocation targets); this endpoint
only picks out what's worth a look today and ranks it. Covers: the
all-clear empty case, price staleness/error counts, unresolved instruments,
allocation under/over, and that "not_priceable" and "no_target" never
produce an item.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AllocationTarget, Instrument, MappingStatus, Position, PriceBar


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


_UNSET = object()


def held_instrument(
    symbol: str,
    category: str,
    quantity: float,
    price: float,
    *,
    mapping_status: str = MappingStatus.VERIFIED,
    verified_at=_UNSET,
    prices_checked_at=_UNSET,
    not_priceable_reason: str | None = None,
) -> Instrument:
    """A held instrument priced today, in EUR (FX conversion is a no-op —
    same convention `test_allocation_api.py` uses). Fresh by default: mapped,
    verified, and checked today — tests override only the fields that matter
    for the case at hand. Uses a sentinel (not None) for "not overridden",
    since an explicit `verified_at=None` is itself a meaningful case (never
    verified) that a plain None-default would silently discard."""
    now = datetime.now(UTC)
    instrument = Instrument(
        broker_symbol=symbol,
        category=category,
        currency="EUR",
        country="FR",
        mapping_status=mapping_status,
        verified_at=now if verified_at is _UNSET else verified_at,
        prices_checked_at=now if prices_checked_at is _UNSET else prices_checked_at,
        not_priceable_reason=not_priceable_reason,
    )
    _seed([instrument])
    bar = PriceBar(instrument_id=instrument.id, bar_date=date.today() - timedelta(days=1), close=price, provider="test")
    position = Position(instrument_id=instrument.id, source="MANUAL", quantity=quantity, avg_price=price)
    _seed([bar, position])
    return instrument


class TestAttentionAllClear:
    def test_empty_portfolio_returns_empty_list(self, client):
        assert client.get("/api/portfolio/attention").json() == []

    def test_fresh_priced_position_with_no_target_returns_empty_list(self, client):
        held_instrument("AAA.FR", "STOCK", quantity=10, price=100.0)
        assert client.get("/api/portfolio/attention").json() == []


class TestPriceStatusItems:
    def test_stale_position_reports_warning_item(self, client):
        held_instrument(
            "AAA.FR", "STOCK", quantity=10, price=100.0,
            prices_checked_at=datetime.now(UTC) - timedelta(days=30),
        )
        items = client.get("/api/portfolio/attention").json()
        assert items == [{"severity": "warning", "kind": "price_stale", "count": 1, "category": None, "gap_pct": None}]

    def test_error_position_reports_missing_item(self, client):
        # Checked at least once, but no provider ever returned data.
        held_instrument("AAA.FR", "STOCK", quantity=10, price=100.0, verified_at=None)
        items = client.get("/api/portfolio/attention").json()
        assert items == [{"severity": "missing", "kind": "price_error", "count": 1, "category": None, "gap_pct": None}]

    def test_not_priceable_position_reports_nothing(self, client):
        held_instrument("CFD1", "CFD", quantity=10, price=100.0, not_priceable_reason="cfd")
        assert client.get("/api/portfolio/attention").json() == []

    def test_counts_multiple_stale_positions_together(self, client):
        stale_at = datetime.now(UTC) - timedelta(days=30)
        held_instrument("AAA.FR", "STOCK", quantity=10, price=100.0, prices_checked_at=stale_at)
        held_instrument("BBB.FR", "STOCK", quantity=5, price=50.0, prices_checked_at=stale_at)
        held_instrument("CCC.FR", "STOCK", quantity=1, price=10.0)  # fresh, not counted

        items = client.get("/api/portfolio/attention").json()
        assert items == [{"severity": "warning", "kind": "price_stale", "count": 2, "category": None, "gap_pct": None}]


class TestUnresolvedInstrumentItem:
    def test_unresolved_instrument_reports_missing_item(self, client):
        instrument = Instrument(broker_symbol="XYZ", category="STOCK", mapping_status=MappingStatus.UNRESOLVED)
        _seed([instrument])
        position = Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=10.0)
        _seed([position])

        items = client.get("/api/portfolio/attention").json()
        assert items == [
            {"severity": "missing", "kind": "unresolved_instruments", "count": 1, "category": None, "gap_pct": None}
        ]

    def test_unresolved_instrument_with_known_isin_is_not_counted(self, client):
        # A known ISIN means the gap is provider coverage, not missing
        # information — same exclusion `_unresolved_instruments` already
        # applies for the correction panel.
        instrument = Instrument(
            broker_symbol="XYZ", category="STOCK", mapping_status=MappingStatus.UNRESOLVED, isin="FR0000000000"
        )
        _seed([instrument])
        position = Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=10.0)
        _seed([position])

        assert client.get("/api/portfolio/attention").json() == []


class TestAllocationItems:
    def test_under_target_reports_warning_item_with_category_and_gap(self, client):
        held_instrument("AAA.FR", "STOCK", quantity=10, price=100.0)  # 1000 EUR, 100% STOCK
        _seed([AllocationTarget(category="ETF", min_pct=20.0, max_pct=30.0)])

        items = client.get("/api/portfolio/attention").json()
        assert items == [
            {"severity": "warning", "kind": "allocation_under", "count": 1, "category": "ETF", "gap_pct": 20.0}
        ]

    def test_over_target_reports_warning_item(self, client):
        held_instrument("AAA.FR", "STOCK", quantity=10, price=100.0)  # 100% STOCK
        _seed([AllocationTarget(category="STOCK", min_pct=10.0, max_pct=50.0)])

        items = client.get("/api/portfolio/attention").json()
        assert items == [
            {"severity": "warning", "kind": "allocation_over", "count": 1, "category": "STOCK", "gap_pct": 50.0}
        ]

    def test_within_target_reports_nothing(self, client):
        held_instrument("AAA.FR", "STOCK", quantity=10, price=100.0)
        _seed([AllocationTarget(category="STOCK", min_pct=50.0, max_pct=100.0)])
        assert client.get("/api/portfolio/attention").json() == []

    def test_no_target_reports_nothing(self, client):
        held_instrument("AAA.FR", "STOCK", quantity=10, price=100.0)
        assert client.get("/api/portfolio/attention").json() == []


class TestAttentionOrdering:
    def test_missing_items_sort_before_warning_items(self, client):
        held_instrument("AAA.FR", "STOCK", quantity=10, price=100.0, verified_at=None)  # price_error -> missing
        _seed([AllocationTarget(category="ETF", min_pct=20.0, max_pct=30.0)])  # allocation_under -> warning

        items = client.get("/api/portfolio/attention").json()
        assert [item["severity"] for item in items] == ["missing", "warning"]
