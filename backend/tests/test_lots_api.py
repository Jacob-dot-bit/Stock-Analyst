"""Tests for `GET /api/portfolio/lots` — the per-position detail panel's
"Historique" section. No endpoint returned individual `Lot` rows before
this; everything else that touches `Lot` only ever writes it or replays it
in aggregate. Read-only, scoped to one instrument.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Instrument, Lot, LotType, Source


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


class TestGetLots:
    def test_returns_open_and_closed_lots_for_the_instrument(self, client):
        instrument = Instrument(broker_symbol="AAPL.US", currency="USD", country="US")
        _seed([instrument])
        _seed(
            [
                Lot(
                    instrument_id=instrument.id, source=Source.IMPORT, lot_type=LotType.OPEN,
                    quantity=2, open_price=100.0, opened_at=datetime(2025, 1, 1), currency="USD",
                ),
                Lot(
                    instrument_id=instrument.id, source=Source.IMPORT, lot_type=LotType.CLOSED,
                    quantity=1, open_price=90.0, opened_at=datetime(2024, 1, 1),
                    close_price=110.0, closed_at=datetime(2024, 6, 1), currency="USD",
                ),
            ]
        )

        response = client.get("/api/portfolio/lots", params={"instrument_id": instrument.id})

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        lot_types = {row["lot_type"] for row in body}
        assert lot_types == {"OPEN", "CLOSED"}

    def test_excludes_lots_from_other_instruments(self, client):
        aapl = Instrument(broker_symbol="AAPL.US", currency="USD", country="US")
        msft = Instrument(broker_symbol="MSFT.US", currency="USD", country="US")
        _seed([aapl, msft])
        _seed(
            [
                Lot(
                    instrument_id=aapl.id, source=Source.IMPORT, lot_type=LotType.OPEN,
                    quantity=1, open_price=100.0, opened_at=datetime(2025, 1, 1), currency="USD",
                ),
                Lot(
                    instrument_id=msft.id, source=Source.IMPORT, lot_type=LotType.OPEN,
                    quantity=1, open_price=200.0, opened_at=datetime(2025, 1, 1), currency="USD",
                ),
            ]
        )

        response = client.get("/api/portfolio/lots", params={"instrument_id": aapl.id})

        body = response.json()
        assert len(body) == 1
        assert body[0]["open_price"] == 100.0

    def test_empty_for_an_instrument_with_no_lots(self, client):
        instrument = Instrument(broker_symbol="AAPL.US", currency="USD", country="US")
        _seed([instrument])

        response = client.get("/api/portfolio/lots", params={"instrument_id": instrument.id})

        assert response.json() == []

    def test_requires_instrument_id(self, client):
        response = client.get("/api/portfolio/lots")
        assert response.status_code == 422
