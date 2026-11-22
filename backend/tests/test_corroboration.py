"""Second opinions on split candidates: Yahoo splits and SEC cover-page share
counts (`app/corporate_actions/corroboration.py`, DEVLOG "Step 3u.116").

All data is made up. Providers are fakes: no test here reaches the network.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.corporate_actions import corroboration
from app.corporate_actions.corroboration import corroborate, shares_verdict
from app.corporate_actions.service import is_atypical_ratio, list_outstanding_candidates
from app.db import Base, get_db
from app.main import app
from app.models import (
    CorporateAction,
    CorporateActionConfidence,
    Instrument,
    ProviderCorporateActionCandidate,
)
from app.providers.base import RateLimited, SplitEvent, SymbolNotFound
from app.providers.edgar import SharesOutstanding, _parse_shares


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


class FakeYahoo:
    name = "yahoo"

    def __init__(self, events_by_symbol=None, rate_limit_on=()):
        self.events_by_symbol = events_by_symbol or {}
        self.rate_limit_on = set(rate_limit_on)
        self.calls: list[str] = []

    def can_serve(self, ref):
        return bool(ref.provider_symbol)

    def fetch_splits(self, ref, start, end):
        self.calls.append(ref.provider_symbol)
        if ref.provider_symbol in self.rate_limit_on:
            raise RateLimited(ref.provider_symbol)
        if ref.provider_symbol not in self.events_by_symbol:
            raise SymbolNotFound(ref.provider_symbol)
        return self.events_by_symbol[ref.provider_symbol]


class FakeEdgar:
    name = "edgar"

    def __init__(self, series_by_ticker=None, enabled=True):
        self.series_by_ticker = series_by_ticker or {}
        self.enabled = enabled
        self.calls: list[str] = []

    def is_enabled(self):
        return self.enabled

    def fetch_shares_outstanding(self, ticker, expected_name=None):
        self.calls.append(ticker)
        if ticker not in self.series_by_ticker:
            raise SymbolNotFound(ticker)
        return self.series_by_ticker[ticker]


def _patch(monkeypatch, yahoo=None, edgar=None):
    yahoo = yahoo or FakeYahoo()
    edgar = edgar or FakeEdgar(enabled=False)
    monkeypatch.setattr(corroboration, "get_yahoo_provider", lambda: yahoo)
    monkeypatch.setattr(corroboration, "get_edgar_provider", lambda: edgar)
    return yahoo, edgar


def _instrument(db, provider_symbol, country="US") -> Instrument:
    instrument = Instrument(
        broker_symbol=provider_symbol.split(".")[0] + "." + country,
        provider_symbol=provider_symbol,
        currency="EUR" if country != "US" else "USD",
        country=country,
    )
    db.add(instrument)
    db.flush()
    return instrument


def _candidate(db, instrument, provider, day, num, den):
    db.add(
        ProviderCorporateActionCandidate(
            instrument_id=instrument.id,
            provider=provider,
            event_date=day,
            event_type="split" if num > den else "reverse_split",
            numerator=num,
            denominator=den,
            economic_factor=num / den,
            provider_status="ok",
            retrieved_at=datetime.now(UTC),
        )
    )
    db.commit()


def _shares(*points):
    return [SharesOutstanding(date.fromisoformat(d), v, "10-Q", None) for d, v in points]


class TestAtypicalRatio:
    @pytest.mark.parametrize("num,den", [(2, 1), (1, 10), (3, 2), (1, 6), (999, 500), (20, 1)])
    def test_whole_number_ratios(self, num, den):
        assert not is_atypical_ratio(num, den)

    @pytest.mark.parametrize("num,den", [(1043, 1000), (1000, 1043), (1.37, 1)])
    def test_rights_issue_like_factors(self, num, den):
        assert is_atypical_ratio(num, den)


class TestSharesVerdict:
    def test_split_confirmed_by_share_count(self):
        series = _shares(("2024-03-31", 100e6), ("2024-07-15", 1000e6))
        verdict, detail = shares_verdict(series, date(2024, 6, 10), 10.0)
        assert verdict == "confirms"
        assert detail["ratio"] == 10.0

    def test_reverse_split_confirmed(self):
        series = _shares(("2022-02-01", 600e6), ("2022-05-01", 100e6))
        assert shares_verdict(series, date(2022, 4, 12), 1 / 6)[0] == "confirms"

    def test_flat_count_contradicts(self):
        series = _shares(("2026-01-31", 50e6), ("2026-04-30", 51e6))
        assert shares_verdict(series, date(2026, 2, 23), 0.1)[0] == "flat"

    def test_unrelated_move_is_inconclusive(self):
        series = _shares(("2020-01-31", 50e6), ("2020-04-30", 80e6))
        assert shares_verdict(series, date(2020, 3, 1), 4.0)[0] == "inconclusive"

    def test_counts_too_far_from_the_date(self):
        series = _shares(("2010-01-31", 50e6), ("2020-04-30", 500e6))
        assert shares_verdict(series, date(2015, 3, 1), 10.0)[0] == "no_data"

    def test_small_factor_says_nothing(self):
        series = _shares(("2020-01-31", 50e6), ("2020-04-30", 50e6))
        assert shares_verdict(series, date(2020, 3, 1), 1.05)[0] == "too_small"


class TestParseShares:
    def test_one_value_per_date_latest_filing_wins(self):
        payload = {
            "units": {
                "shares": [
                    {"end": "2024-07-15", "val": 900, "filed": "2024-08-01", "form": "10-Q"},
                    {"end": "2024-07-15", "val": 1000, "filed": "2024-09-01", "form": "10-Q/A"},
                    {"end": "2024-03-31", "val": 100, "filed": "2024-04-20", "form": "10-Q"},
                    {"end": "bad", "val": 1},
                    {"end": "2023-01-01", "val": 0},
                ]
            }
        }
        series = _parse_shares(payload)
        assert [(s.as_of.isoformat(), s.shares) for s in series] == [("2024-03-31", 100), ("2024-07-15", 1000)]

    def test_no_concept(self):
        assert _parse_shares({}) == []


class TestCorroborate:
    def test_yahoo_agreement_applies_the_candidate(self, db, monkeypatch):
        inst = _instrument(db, "ACME")
        _candidate(db, inst, "alpha_vantage", date(2024, 6, 10), 10, 1)
        _patch(monkeypatch, yahoo=FakeYahoo({"ACME": [SplitEvent(date(2024, 6, 11), 10, 1)]}))

        summary = corroborate(db)

        assert summary.applied == 1
        assert summary.targets[0].yahoo == "reported"
        assert summary.targets[0].applied_now
        action = db.execute(select(CorporateAction)).scalar_one()
        assert action.confidence == CorporateActionConfidence.VERIFIED_CROSS_SOURCE
        assert list_outstanding_candidates(db) == []

    def test_yahoo_silence_keeps_it_outstanding_and_says_so(self, db, monkeypatch):
        inst = _instrument(db, "DSY.PA", country="FR")
        _candidate(db, inst, "alpha_vantage", date(2026, 2, 23), 1, 10)
        _patch(monkeypatch, yahoo=FakeYahoo({"DSY.PA": []}))

        summary = corroborate(db)

        assert summary.applied == 0
        assert summary.targets[0].yahoo == "not_reported"
        assert summary.targets[0].sec_shares == "not_applicable"
        [left] = list_outstanding_candidates(db)
        assert left.not_reported_by == ["yahoo"]
        assert db.execute(select(CorporateAction)).first() is None

    def test_yahoo_other_ratio_is_a_conflict_not_an_apply(self, db, monkeypatch):
        inst = _instrument(db, "MT.AS", country="NL")
        _candidate(db, inst, "alpha_vantage", date(2016, 3, 14), 1043, 1000)
        _patch(monkeypatch, yahoo=FakeYahoo({"MT.AS": [SplitEvent(date(2016, 3, 14), 2, 1)]}))

        summary = corroborate(db)

        assert summary.targets[0].yahoo == "other_ratio"
        assert summary.applied == 0
        [left] = list_outstanding_candidates(db)
        assert left.confidence == CorporateActionConfidence.PROVIDER_CONFLICT

    def test_atypical_ratio_flag_on_outstanding(self, db):
        inst = _instrument(db, "MT.AS", country="NL")
        _candidate(db, inst, "alpha_vantage", date(2016, 3, 14), 1043, 1000)
        [left] = list_outstanding_candidates(db)
        assert left.atypical_ratio

    def test_sec_share_count_confirms_us_reverse_split(self, db, monkeypatch):
        inst = _instrument(db, "APLX")
        _candidate(db, inst, "polygon", date(2022, 4, 12), 1, 6)
        edgar = FakeEdgar({"APLX": _shares(("2022-02-01", 600e6), ("2022-05-01", 101e6))})
        _patch(monkeypatch, yahoo=FakeYahoo({"APLX": []}), edgar=edgar)

        summary = corroborate(db)

        assert summary.targets[0].sec_shares == "confirms"
        assert summary.applied == 1
        action = db.execute(select(CorporateAction)).scalar_one()
        assert {s["provider"] for s in action.corroborating_sources} == {"polygon", "sec_shares"}

    def test_flat_sec_count_is_listed_against_the_candidate(self, db, monkeypatch):
        inst = _instrument(db, "FLAT")
        _candidate(db, inst, "polygon", date(2026, 2, 23), 1, 10)
        edgar = FakeEdgar({"FLAT": _shares(("2026-01-31", 50e6), ("2026-04-30", 50.5e6))})
        _patch(monkeypatch, yahoo=FakeYahoo({"FLAT": []}), edgar=edgar)

        corroborate(db)

        [left] = list_outstanding_candidates(db)
        assert left.not_reported_by == ["sec_shares", "yahoo"]

    def test_sec_too_small_does_not_count_as_silence(self, db, monkeypatch):
        inst = _instrument(db, "TINY")
        _candidate(db, inst, "polygon", date(2020, 3, 1), 21, 20)
        edgar = FakeEdgar({"TINY": _shares(("2020-01-31", 50e6), ("2020-04-30", 50e6))})
        _patch(monkeypatch, yahoo=FakeYahoo({"TINY": [SplitEvent(date(2020, 3, 1), 21, 20)]}), edgar=edgar)

        summary = corroborate(db)

        assert summary.targets[0].sec_shares == "too_small"
        # Yahoo agreeing is still a second vote.
        assert summary.applied == 1

    def test_applied_single_source_action_is_reported_never_changed(self, db, monkeypatch):
        inst = _instrument(db, "MT.AS", country="NL")
        db.add(
            CorporateAction(
                instrument_id=inst.id,
                action_type="split",
                effective_date=date(2016, 3, 15),
                ratio_numerator=1043,
                ratio_denominator=1000,
                source="eodhd",
                confidence=CorporateActionConfidence.MANUAL_PROMOTION,
            )
        )
        db.commit()
        _patch(monkeypatch, yahoo=FakeYahoo({"MT.AS": [SplitEvent(date(2017, 5, 22), 1, 3)]}))

        summary = corroborate(db)

        [target] = [t for t in summary.targets if t.kind == "applied"]
        assert target.yahoo == "not_reported"
        assert db.execute(select(CorporateAction)).scalar_one().effective_date == date(2016, 3, 15)

    def test_rate_limit_stops_yahoo_for_the_rest_of_the_call(self, db, monkeypatch):
        first = _instrument(db, "AAA")
        second = _instrument(db, "BBB")
        _candidate(db, first, "polygon", date(2024, 1, 10), 2, 1)
        _candidate(db, second, "polygon", date(2024, 1, 10), 2, 1)
        yahoo, _ = _patch(monkeypatch, yahoo=FakeYahoo({"BBB": []}, rate_limit_on={"AAA"}))

        summary = corroborate(db)

        assert yahoo.calls == ["AAA"]
        assert summary.yahoo_rate_limited
        assert {t.yahoo for t in summary.targets} == {"rate_limited"}

    def test_recent_answer_is_reused_unless_forced(self, db, monkeypatch):
        inst = _instrument(db, "DSY.PA", country="FR")
        _candidate(db, inst, "alpha_vantage", date(2026, 2, 23), 1, 10)
        yahoo, _ = _patch(monkeypatch, yahoo=FakeYahoo({"DSY.PA": []}))

        corroborate(db)
        second = corroborate(db)
        assert yahoo.calls == ["DSY.PA"]
        assert second.targets[0].yahoo == "not_reported"

        corroborate(db, force=True)
        assert yahoo.calls == ["DSY.PA", "DSY.PA"]

    def test_stale_answer_is_asked_again(self, db, monkeypatch):
        inst = _instrument(db, "DSY.PA", country="FR")
        _candidate(db, inst, "alpha_vantage", date(2026, 2, 23), 1, 10)
        yahoo, _ = _patch(monkeypatch, yahoo=FakeYahoo({"DSY.PA": []}))
        corroborate(db)
        for row in db.execute(select(ProviderCorporateActionCandidate).where(
            ProviderCorporateActionCandidate.provider == "yahoo"
        )).scalars():
            row.retrieved_at = datetime.now(UTC) - timedelta(days=30)
        db.commit()

        corroborate(db)
        assert yahoo.calls == ["DSY.PA", "DSY.PA"]

    def test_limit_and_remaining(self, db, monkeypatch):
        for symbol in ("A1", "A2", "A3"):
            inst = _instrument(db, symbol)
            _candidate(db, inst, "polygon", date(2024, 1, 10), 2, 1)
        yahoo, _ = _patch(monkeypatch, yahoo=FakeYahoo({"A1": [], "A2": [], "A3": []}))

        summary = corroborate(db, limit=2)

        assert summary.instruments_checked == 2
        assert summary.instruments_remaining == 1
        assert len(yahoo.calls) == 2

    def test_yahoo_only_old_split_becomes_a_visible_candidate(self, db, monkeypatch):
        inst = _instrument(db, "MT.AS", country="NL")
        _candidate(db, inst, "alpha_vantage", date(2026, 2, 23), 1, 10)
        _patch(monkeypatch, yahoo=FakeYahoo({"MT.AS": [SplitEvent(date(2017, 5, 22), 1, 3)]}))

        corroborate(db)

        dates = sorted(c.effective_date for c in list_outstanding_candidates(db))
        assert dates == [date(2017, 5, 22), date(2026, 2, 23)]


@pytest.fixture
def client(monkeypatch):
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
        yield test_client, TestingSession
    app.dependency_overrides.clear()


def test_corroborate_endpoint(client, monkeypatch):
    test_client, Session = client
    session = Session()
    inst = _instrument(session, "ACME")
    _candidate(session, inst, "alpha_vantage", date(2024, 6, 10), 10, 1)
    session.close()
    _patch(monkeypatch, yahoo=FakeYahoo({"ACME": []}))

    response = test_client.post("/api/corporate-actions/corroborate", json={"limit": 3})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["instruments_checked"] == 1
    assert body["targets"][0]["yahoo"] == "not_reported"

    outstanding = test_client.get("/api/corporate-actions/outstanding").json()
    assert outstanding[0]["not_reported_by"] == ["yahoo"]
    assert outstanding[0]["atypical_ratio"] is False

    assert test_client.post("/api/corporate-actions/corroborate", json={"limit": 0}).status_code == 422
