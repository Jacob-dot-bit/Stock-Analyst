"""Tests for the quota-usage counter. See DEVLOG "Decision 3m.1"."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ProviderUsage
from app.prices.provider_usage import QUOTA_LIMITS, period_key_for, record_bytes, record_usage


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


@pytest.fixture
def file_engine(tmp_path):
    """A real file, not the `StaticPool` `db` fixture above: the concurrency
    test below needs each thread to hold its own DB session/connection, the
    same shape production and the parallel refresh actually use (DEVLOG
    "Decision 3n.1") — a single shared StaticPool connection isn't safe to
    drive from multiple threads at once regardless of the app-level lock
    this test is trying to prove correct.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    return engine


class TestPeriodKey:
    def test_daily_key_is_a_calendar_date(self):
        key = period_key_for("day")
        assert len(key) == 10  # "2026-08-19"

    def test_monthly_key_has_no_day_component(self):
        key = period_key_for("month")
        assert len(key) == 7  # "2026-08"

    def test_minute_key_includes_hour_and_minute(self):
        key = period_key_for("minute")
        assert len(key) == 16  # "2026-08-19 22:34"


class TestRecordUsage:
    def test_creates_a_row_on_first_use(self, db):
        record_usage(db, "fmp")

        rows = db.execute(select(ProviderUsage)).scalars().all()
        assert len(rows) == 1
        assert rows[0].provider == "fmp"
        assert rows[0].count == 1

    def test_accumulates_within_the_same_period(self, db):
        record_usage(db, "fmp")
        record_usage(db, "fmp")
        record_usage(db, "fmp")

        row = db.execute(select(ProviderUsage).where(ProviderUsage.provider == "fmp")).scalar_one()
        assert row.count == 3

    def test_a_per_minute_provider_keys_by_minute(self, db):
        assert QUOTA_LIMITS["polygon"][1] == "minute"

        record_usage(db, "polygon")

        row = db.execute(select(ProviderUsage).where(ProviderUsage.provider == "polygon")).scalar_one()
        assert row.period_key == period_key_for("minute")

    def test_an_untracked_provider_is_a_no_op(self, db):
        record_usage(db, "yahoo")  # no documented quota — not in QUOTA_LIMITS

        assert db.execute(select(ProviderUsage)).scalars().all() == []

    def test_a_monthly_provider_keys_by_month_not_day(self, db):
        assert QUOTA_LIMITS["marketstack"][1] == "month"

        record_usage(db, "marketstack")

        row = db.execute(select(ProviderUsage).where(ProviderUsage.provider == "marketstack")).scalar_one()
        assert row.period_key == period_key_for("month")
        assert len(row.period_key) == 7

    def test_different_providers_get_independent_counts(self, db):
        record_usage(db, "fmp")
        record_usage(db, "fmp")
        record_usage(db, "tiingo")

        fmp_row = db.execute(select(ProviderUsage).where(ProviderUsage.provider == "fmp")).scalar_one()
        tiingo_row = db.execute(select(ProviderUsage).where(ProviderUsage.provider == "tiingo")).scalar_one()
        assert fmp_row.count == 2
        assert tiingo_row.count == 1


class TestRecordBytes:
    """See DEVLOG "Decision 3u.41" — FMP's 500MB/30-day bandwidth cap has no
    request-count signature at all, so this is purely descriptive: nothing
    here blocks a call, it only makes a drift visible before the next
    blackout."""

    def test_creates_a_row_on_first_use(self, db):
        record_bytes(db, "fmp", 1200)

        row = db.execute(select(ProviderUsage).where(ProviderUsage.provider == "fmp")).scalar_one()
        assert row.bytes_used == 1200
        assert row.count == 0  # record_bytes never touches the request count

    def test_accumulates_within_the_same_day(self, db):
        record_bytes(db, "fmp", 1000)
        record_bytes(db, "fmp", 500)

        row = db.execute(select(ProviderUsage).where(ProviderUsage.provider == "fmp")).scalar_one()
        assert row.bytes_used == 1500

    def test_always_keyed_by_day_even_for_a_per_minute_provider(self, db):
        assert QUOTA_LIMITS["alpha_vantage"][1] == "minute"

        record_bytes(db, "alpha_vantage", 800)

        row = db.execute(select(ProviderUsage).where(ProviderUsage.provider == "alpha_vantage")).scalar_one()
        assert row.period_key == period_key_for("day")

    def test_an_untracked_provider_still_accumulates_bytes(self, db):
        # Unlike record_usage, there's no QUOTA_LIMITS gate here — a
        # provider with no documented request-count limit can still have an
        # undocumented bandwidth one (this is exactly FMP's situation).
        record_bytes(db, "yahoo", 300)

        row = db.execute(select(ProviderUsage).where(ProviderUsage.provider == "yahoo")).scalar_one()
        assert row.bytes_used == 300

    def test_shares_the_same_row_as_record_usage_for_a_daily_provider(self, db):
        record_usage(db, "fmp")
        record_bytes(db, "fmp", 2000)

        row = db.execute(select(ProviderUsage).where(ProviderUsage.provider == "fmp")).scalar_one()
        assert row.count == 1
        assert row.bytes_used == 2000


class TestConcurrentRecordUsage:
    """A parallel refresh (DEVLOG "Decision 3n.1") means several worker
    threads — each with its own DB session — can call `record_usage` for the
    same provider at nearly the same instant. Without `_usage_lock`, this is
    a textbook lost-update race: both threads read count=N, both write N+1,
    one increment vanishes."""

    def test_n_concurrent_increments_produce_exactly_n(self, file_engine):
        session_factory = sessionmaker(bind=file_engine, autoflush=False, expire_on_commit=False)
        thread_count = 20

        def worker():
            db = session_factory()
            try:
                record_usage(db, "fmp")
            finally:
                db.close()

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        verify = session_factory()
        try:
            row = verify.execute(select(ProviderUsage).where(ProviderUsage.provider == "fmp")).scalar_one()
            assert row.count == thread_count
        finally:
            verify.close()
