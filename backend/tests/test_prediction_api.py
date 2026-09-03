"""Tests for phase 1 of a real, backtestable Discovery prediction: the
price-history backfill. See `app/prediction/service.py`'s module docstring
for why this only ever touches `PriceBar` (DEVLOG "Decision 3u.22").
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Instrument, PriceBar
from app.prediction import service as prediction_service
from app.prediction.service import backfill_history, get_backfill_progress
from app.providers.base import Bar, ProviderChain
from tests.test_providers import FakeProvider


@pytest.fixture
def client():
    # Sequential, not thread-pooled (unlike `prices/service.py::refresh_many`)
    # — same reasoning as `fundamentals/service.py`'s own tests — so a plain
    # StaticPool in-memory engine is safe here.
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

    # The module-level lock/progress are process-global state, not
    # per-request — reset between tests so one test's run doesn't leave the
    # lock held (or `running=True`) for the next.
    prediction_service._backfill_lock = type(prediction_service._backfill_lock)()
    prediction_service._progress = prediction_service.BackfillProgress()


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


def _bars(count: int) -> list[Bar]:
    today = date.today()
    return [
        Bar(bar_date=today - timedelta(days=count - 1 - i), open=1, high=1, low=1, close=1, volume=100)
        for i in range(count)
    ]


class TestAlreadyPricedUniverse:
    def test_only_instruments_with_at_least_one_bar_are_included(self, client, monkeypatch):
        priced = Instrument(broker_symbol="AAA.US", provider_symbol="AAA", category="STOCK", currency="USD", country="US")
        unpriced = Instrument(broker_symbol="BBB.US", provider_symbol="BBB", category="STOCK", currency="USD", country="US")
        _seed([priced, unpriced])
        _seed([PriceBar(instrument_id=priced.id, bar_date=date.today(), open=1, high=1, low=1, close=1, volume=1)])

        chain = ProviderChain([FakeProvider("test", bars=_bars(5))])
        report = backfill_history(next(app.dependency_overrides[get_db]()), chain)

        assert report.updated == 1
        assert report.failed == 0

    def test_a_universe_with_no_priced_instruments_updates_nothing(self, client):
        chain = ProviderChain([FakeProvider("test", bars=_bars(5))])
        report = backfill_history(next(app.dependency_overrides[get_db]()), chain)

        assert report == prediction_service.BackfillReport()


class TestBackfillHistory:
    def test_stores_new_bars_beyond_the_existing_window(self, client):
        instrument = Instrument(
            broker_symbol="AAA.US", provider_symbol="AAA", category="STOCK", currency="USD", country="US"
        )
        _seed([instrument])
        _seed(
            [
                PriceBar(
                    instrument_id=instrument.id,
                    bar_date=date.today(),
                    open=1,
                    high=1,
                    low=1,
                    close=1,
                    volume=1,
                )
            ]
        )

        chain = ProviderChain([FakeProvider("test", bars=_bars(10))])
        db = next(app.dependency_overrides[get_db]())
        report = backfill_history(db, chain)

        assert report.updated == 1
        # 10 fetched bars, 1 already existed (today's, re-answered by the
        # provider and upserted in place, not duplicated) -> 9 new rows.
        assert report.bars_added == 9

        total_bars = db.execute(
            select(PriceBar).where(PriceBar.instrument_id == instrument.id)
        ).scalars().all()
        assert len(total_bars) == 10

    def test_one_instrument_failing_does_not_stop_the_run(self, client):
        good = Instrument(broker_symbol="GOOD.US", provider_symbol="GOOD", category="STOCK", currency="USD", country="US")
        bad = Instrument(broker_symbol="BAD.US", provider_symbol="BAD", category="STOCK", currency="USD", country="US")
        _seed([good, bad])
        _seed(
            [
                PriceBar(instrument_id=good.id, bar_date=date.today(), open=1, high=1, low=1, close=1, volume=1),
                PriceBar(instrument_id=bad.id, bar_date=date.today(), open=1, high=1, low=1, close=1, volume=1),
            ]
        )

        class FlakyProvider(FakeProvider):
            def fetch_daily(self, ref, start, end):
                if ref.provider_symbol == "BAD":
                    raise RuntimeError("boom")
                return super().fetch_daily(ref, start, end)

        chain = ProviderChain([FlakyProvider("test", bars=_bars(10))])
        db = next(app.dependency_overrides[get_db]())
        report = backfill_history(db, chain)

        assert report.updated == 1
        assert report.failed == 1

    def test_returns_none_when_a_run_is_already_in_progress(self, client):
        assert prediction_service._backfill_lock.acquire(blocking=False)
        try:
            chain = ProviderChain([FakeProvider("test", bars=_bars(5))])
            result = backfill_history(next(app.dependency_overrides[get_db]()), chain)
            assert result is None
        finally:
            prediction_service._backfill_lock.release()

    def test_progress_reflects_the_completed_run(self, client):
        instrument = Instrument(
            broker_symbol="AAA.US", provider_symbol="AAA", category="STOCK", currency="USD", country="US"
        )
        _seed([instrument])
        _seed([PriceBar(instrument_id=instrument.id, bar_date=date.today(), open=1, high=1, low=1, close=1, volume=1)])

        chain = ProviderChain([FakeProvider("test", bars=_bars(5))])
        backfill_history(next(app.dependency_overrides[get_db]()), chain)

        progress = get_backfill_progress()
        assert progress.running is False
        assert progress.total == 1
        assert progress.done == 1
        assert progress.report is not None
        assert progress.report.updated == 1


class TestBackfillHistoryApi:
    def test_endpoint_reports_already_running(self, client):
        assert prediction_service._backfill_lock.acquire(blocking=False)
        try:
            response = client.post("/api/prediction/backfill-history")
            assert response.status_code == 200
            assert response.json()["already_running"] is True
        finally:
            prediction_service._backfill_lock.release()

    def test_status_endpoint_reflects_a_completed_run(self, client, monkeypatch):
        instrument = Instrument(
            broker_symbol="AAA.US", provider_symbol="AAA", category="STOCK", currency="USD", country="US"
        )
        _seed([instrument])
        _seed([PriceBar(instrument_id=instrument.id, bar_date=date.today(), open=1, high=1, low=1, close=1, volume=1)])

        monkeypatch.setattr(
            "app.routers.prediction.get_provider_chain",
            lambda: ProviderChain([FakeProvider("test", bars=_bars(5))]),
        )

        post_response = client.post("/api/prediction/backfill-history")
        assert post_response.status_code == 200
        assert post_response.json()["already_running"] is False
        assert post_response.json()["updated"] == 1

        status_response = client.get("/api/prediction/backfill-history/status")
        body = status_response.json()
        assert body["running"] is False
        assert body["report"]["updated"] == 1
