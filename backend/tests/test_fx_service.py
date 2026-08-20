"""Tests for the historical FX range lookup backing the value-history chart."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import FxRate
from app.prices import fx_service


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def _mock_range_response(payload: dict, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


class TestGetRateRange:
    def test_forward_fills_weekend_gaps(self, db, monkeypatch):
        # Frankfurter's real response shape: weekends simply absent.
        payload = {
            "rates": {
                "2025-05-29": {"EUR": 0.88645},
                "2025-05-30": {"EUR": 0.88191},
                "2025-06-02": {"EUR": 0.87573},
            }
        }
        monkeypatch.setattr(
            httpx, "get", lambda *a, **k: httpx.Response(200, json=payload)
        )

        result = fx_service.get_rate_range(
            db, "USD", "EUR", date(2025, 5, 29), date(2025, 6, 2)
        )

        assert result[date(2025, 5, 29)] == 0.88645
        assert result[date(2025, 5, 30)] == 0.88191
        # Weekend (05-31, 06-01) carries the last known rate forward.
        assert result[date(2025, 5, 31)] == 0.88191
        assert result[date(2025, 6, 1)] == 0.88191
        assert result[date(2025, 6, 2)] == 0.87573

    def test_second_call_hits_cache_not_network(self, db, monkeypatch):
        calls = {"n": 0}

        def fake_get(*args, **kwargs):
            calls["n"] += 1
            return httpx.Response(
                200, json={"rates": {"2025-06-02": {"EUR": 0.87573}}}
            )

        monkeypatch.setattr(httpx, "get", fake_get)

        fx_service.get_rate_range(db, "USD", "EUR", date(2025, 6, 2), date(2025, 6, 2))
        assert calls["n"] == 1

        fx_service.get_rate_range(db, "USD", "EUR", date(2025, 6, 2), date(2025, 6, 2))
        assert calls["n"] == 1  # fully cached, no second network call

        assert len(db.execute(select(FxRate)).scalars().all()) == 1

    def test_out_of_coverage_range_returns_empty_rather_than_raising(self, db, monkeypatch):
        monkeypatch.setattr(
            httpx, "get", lambda *a, **k: httpx.Response(404, json={"message": "not found"})
        )

        result = fx_service.get_rate_range(
            db, "USD", "EUR", date(1990, 1, 1), date(1990, 1, 5)
        )
        assert result == {}

    def test_same_currency_needs_no_network_call(self, db, monkeypatch):
        monkeypatch.setattr(
            httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call network"))
        )

        result = fx_service.get_rate_range(db, "EUR", "EUR", date(2025, 6, 1), date(2025, 6, 3))
        assert all(rate == 1.0 for rate in result.values())
        assert len(result) == 3

    def test_unknown_from_currency_returns_empty(self, db):
        result = fx_service.get_rate_range(db, None, "EUR", date(2025, 6, 1), date(2025, 6, 3))
        assert result == {}
