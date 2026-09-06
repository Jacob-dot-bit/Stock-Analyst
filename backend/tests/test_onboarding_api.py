"""End-to-end tests for `GET /api/portfolio/onboarding`.

Each field is a plain existence check against a table the app already
maintains — no new tracking, no derived state. Covers the empty-DB baseline
(unresolved_resolved trivially true, everything else false) and each step
flipping to true independently.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    AllocationTarget,
    AppMetadata,
    Fundamental,
    ImportBatch,
    Instrument,
    MappingStatus,
    WatchlistItem,
)


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


BASELINE = {
    "imported": False,
    "prices_refreshed": False,
    "unresolved_resolved": True,
    "fundamentals_fetched": False,
    "allocation_target_set": False,
    "watchlist_started": False,
}


class TestOnboardingBaseline:
    def test_empty_database_is_all_false_except_unresolved(self, client):
        assert client.get("/api/portfolio/onboarding").json() == BASELINE


class TestOnboardingSteps:
    def test_import_batch_flips_imported(self, client):
        _seed([ImportBatch(filename="statement.xlsx", file_hash="abc123")])
        assert client.get("/api/portfolio/onboarding").json() == {**BASELINE, "imported": True}

    def test_price_refresh_timestamp_flips_prices_refreshed(self, client):
        _seed([AppMetadata(id=1, last_price_refresh_time=datetime.now(UTC))])
        assert client.get("/api/portfolio/onboarding").json() == {**BASELINE, "prices_refreshed": True}

    def test_app_metadata_row_without_timestamp_stays_false(self, client):
        _seed([AppMetadata(id=1, last_price_refresh_time=None)])
        assert client.get("/api/portfolio/onboarding").json() == BASELINE

    def test_unresolved_instrument_flips_unresolved_resolved_to_false(self, client):
        _seed([Instrument(broker_symbol="XYZ", mapping_status=MappingStatus.UNRESOLVED)])
        assert client.get("/api/portfolio/onboarding").json() == {**BASELINE, "unresolved_resolved": False}

    def test_fundamental_row_flips_fundamentals_fetched(self, client):
        instrument = _seed([Instrument(broker_symbol="AAA", mapping_status=MappingStatus.VERIFIED)])[0]
        _seed(
            [
                Fundamental(
                    instrument_id=instrument.id,
                    concept="revenue",
                    fiscal_year=2025,
                    period_end=date(2025, 12, 31),
                    value=1000.0,
                    currency="USD",
                    tag="us-gaap:Revenues",
                )
            ]
        )
        assert client.get("/api/portfolio/onboarding").json() == {**BASELINE, "fundamentals_fetched": True}

    def test_allocation_target_flips_allocation_target_set(self, client):
        _seed([AllocationTarget(category="ETF", min_pct=20.0, max_pct=30.0)])
        assert client.get("/api/portfolio/onboarding").json() == {**BASELINE, "allocation_target_set": True}

    def test_watchlist_item_flips_watchlist_started(self, client):
        instrument = _seed([Instrument(broker_symbol="AAA", mapping_status=MappingStatus.VERIFIED)])[0]
        _seed([WatchlistItem(instrument_id=instrument.id)])
        assert client.get("/api/portfolio/onboarding").json() == {**BASELINE, "watchlist_started": True}
