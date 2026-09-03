"""Tests for Carhart four-factor exposure — held positions only, region-
matched, price-only, descriptive (never predictive). See `app/factors/
service.py`'s module docstring (DEVLOG "Decision 3u.24")."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.factors.service import (
    MIN_OBSERVATIONS,
    _daily_returns,
    compute_factor_loadings,
    region_for_instrument,
)
from app.main import app
from app.models import CorporateAction, CorporateActionType, FactorReturn, Instrument, Position, PriceBar


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestRegionForInstrument:
    def test_us_maps_to_us(self):
        instrument = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
        assert region_for_instrument(instrument) == "US"

    def test_france_maps_to_europe(self):
        instrument = Instrument(broker_symbol="AAA.PA", category="STOCK", currency="EUR", country="FR")
        assert region_for_instrument(instrument) == "EUROPE"

    def test_uncovered_country_is_none(self):
        instrument = Instrument(broker_symbol="AAA.T", category="STOCK", currency="JPY", country="JP")
        assert region_for_instrument(instrument) is None

    def test_no_country_at_all_is_none(self):
        instrument = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country=None)
        assert region_for_instrument(instrument) is None


def _seed_bars_and_factors(db, region: str, n: int, beta_mkt: float = 1.0):
    """A synthetic instrument whose daily return is *exactly*
    `beta_mkt * mkt_rf + rf` (zero SMB/HML/Mom exposure, zero alpha) — the
    regression must recover `beta_mkt` and an alpha near zero."""
    instrument = Instrument(broker_symbol="AAA.US", category="STOCK", currency="USD", country="US")
    db.add(instrument)
    db.commit()
    db.refresh(instrument)

    start = date(2020, 1, 1)
    close = 100.0
    for i in range(n):
        day = start + timedelta(days=i)
        mkt_rf = 0.001 * ((i % 7) - 3)
        # Real variation in SMB/HML/Mom, uncorrelated with mkt_rf and never
        # read by the instrument's own return below — a design matrix of
        # all-zero columns is degenerate (rank-deficient), which real
        # factor data never is.
        smb = 0.0005 * ((i % 5) - 2)
        hml = 0.0004 * ((i % 3) - 1)
        mom = 0.0006 * ((i % 11) - 5)
        rf = 0.0001
        db.add(FactorReturn(region=region, return_date=day, mkt_rf=mkt_rf, smb=smb, hml=hml, mom=mom, rf=rf))
        if i > 0:
            instrument_return = beta_mkt * mkt_rf + rf
            close = close * (1 + instrument_return)
        db.add(
            PriceBar(instrument_id=instrument.id, bar_date=day, open=close, high=close, low=close, close=close, volume=100)
        )
    db.commit()
    return instrument


class TestComputeFactorLoadings:
    def test_not_applicable_for_an_uncovered_region(self, db):
        instrument = Instrument(broker_symbol="AAA.T", category="STOCK", currency="JPY", country="JP")
        db.add(instrument)
        db.commit()
        db.refresh(instrument)

        result = compute_factor_loadings(db, instrument)

        assert result.not_applicable_reason == "no_region_match"
        assert result.alpha is None

    def test_not_applicable_with_too_little_overlapping_history(self, db):
        instrument = _seed_bars_and_factors(db, "US", n=MIN_OBSERVATIONS - 10)

        result = compute_factor_loadings(db, instrument)

        assert result.not_applicable_reason == "insufficient_history"
        assert result.alpha is None

    def test_recovers_the_true_market_beta_from_a_synthetic_series(self, db):
        instrument = _seed_bars_and_factors(db, "US", n=300, beta_mkt=1.5)

        result = compute_factor_loadings(db, instrument)

        assert result.not_applicable_reason is None
        assert result.region == "US"
        assert result.beta_mkt == pytest.approx(1.5, abs=0.05)
        assert result.beta_smb == pytest.approx(0.0, abs=0.05)
        assert result.alpha == pytest.approx(0.0, abs=0.01)
        assert result.r_squared > 0.9
        assert result.n_observations >= MIN_OBSERVATIONS

    def test_never_mixes_regions(self, db):
        # A France-domiciled instrument with only US factor data cached —
        # the regression must refuse rather than fall back to the wrong
        # region's factors.
        instrument = Instrument(broker_symbol="AAA.PA", category="STOCK", currency="EUR", country="FR")
        db.add(instrument)
        db.commit()
        db.refresh(instrument)
        start = date(2020, 1, 1)
        for i in range(200):
            day = start + timedelta(days=i)
            db.add(FactorReturn(region="US", return_date=day, mkt_rf=0.001, smb=0.0, hml=0.0, mom=0.0, rf=0.0001))
            db.add(
                PriceBar(instrument_id=instrument.id, bar_date=day, open=100, high=100, low=100, close=100 + i * 0.1, volume=100)
            )
        db.commit()

        result = compute_factor_loadings(db, instrument)

        # No EUROPE factor rows were seeded, so a France instrument must
        # report insufficient history, never silently regress against US.
        assert result.not_applicable_reason == "insufficient_history"


class TestDailyReturnsWithSplit:
    def test_unadjusted_split_would_otherwise_dominate_the_regression(self):
        """The exact bug this feature fixes: an unadjusted reverse split
        reads as one impossible daily return dwarfing every real one. Flat
        prices either side of the split isolate the split's own effect from
        any real price movement."""
        bars = [
            PriceBar(instrument_id=1, bar_date=date(2022, 4, 11), close=2.0),
            PriceBar(instrument_id=1, bar_date=date(2022, 4, 12), close=2.0),
            PriceBar(instrument_id=1, bar_date=date(2022, 4, 13), close=12.0),  # raw 6x jump, unadjusted
            PriceBar(instrument_id=1, bar_date=date(2022, 4, 14), close=12.0),
        ]
        action = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.REVERSE_SPLIT,
            effective_date=date(2022, 4, 13), ratio_numerator=1, ratio_denominator=6,
            price_history_status="raw",
        )

        without_adjustment = _daily_returns(bars)
        with_adjustment = _daily_returns(bars, [action])

        # The raw series really does show a fabricated 500% one-day return...
        assert without_adjustment[date(2022, 4, 13)] == pytest.approx(5.0)
        # ...which the adjustment removes entirely.
        assert all(r == pytest.approx(0.0, abs=1e-9) for r in with_adjustment.values())

    def test_no_actions_behaves_exactly_as_before(self):
        bars = [
            PriceBar(instrument_id=1, bar_date=date(2024, 1, 1), close=100.0),
            PriceBar(instrument_id=1, bar_date=date(2024, 1, 2), close=110.0),
        ]
        assert _daily_returns(bars) == {date(2024, 1, 2): pytest.approx(0.1)}


class TestFactorsApi:
    def test_import_endpoint_returns_counts(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.factors.service.kenneth_french.fetch_region",
            lambda region: [
                {"return_date": date(2020, 1, 1), "mkt_rf": 0.01, "smb": 0.0, "hml": 0.0, "rf": 0.0001, "mom": 0.0}
            ],
        )

        response = client.post("/api/factors/import")

        assert response.status_code == 200
        body = response.json()
        assert body["imported"] == 2  # one row for each of US and EUROPE
        assert body["already_present"] == 0

    def test_get_factors_returns_one_row_per_held_position(self, client, db):
        held = _seed_bars_and_factors(db, "US", n=300)
        db.add(Position(instrument_id=held.id, source="MANUAL", quantity=1, avg_price=10.0))
        db.commit()

        response = client.get("/api/factors")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["instrument"]["broker_symbol"] == "AAA.US"
        assert body[0]["not_applicable_reason"] is None
        assert isinstance(body[0]["beta_mkt"], float)

    def test_get_factors_excludes_unheld_instruments(self, client, db):
        _seed_bars_and_factors(db, "US", n=300)  # no Position row

        response = client.get("/api/factors")

        assert response.json() == []
