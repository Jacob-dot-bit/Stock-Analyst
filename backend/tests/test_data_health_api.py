"""End-to-end tests for `GET /api/portfolio/data-health`.

The per-instrument trust report for held (open) positions only — same
underlying facts (`_price_status`, `_unresolved_instruments`,
`list_outstanding_candidates`) as before v2, but combined into one row per
instrument with an explicit valuation signal and corporate-actions signal,
resolved into a single overall severity. See DEVLOG "Decision 3u.58".
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
from app.models import (
    CorporateAction,
    Instrument,
    MappingStatus,
    Position,
    PriceBar,
    ProviderCorporateActionCandidate,
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


_UNSET = object()


def held_instrument(
    symbol: str,
    category: str,
    *,
    mapping_status: str = MappingStatus.VERIFIED,
    verified_at=_UNSET,
    prices_checked_at=_UNSET,
    not_priceable_reason: str | None = None,
    provider_symbol: str | None = _UNSET,
    corporate_actions_checked_at: datetime | None = None,
) -> Instrument:
    """A held instrument, fresh and CA-checked by default."""
    now = datetime.now(UTC)
    instrument = Instrument(
        broker_symbol=symbol,
        category=category,
        currency="EUR",
        country="FR",
        mapping_status=mapping_status,
        verified_at=now if verified_at is _UNSET else verified_at,
        verified_provider="FMP",
        prices_checked_at=now if prices_checked_at is _UNSET else prices_checked_at,
        not_priceable_reason=not_priceable_reason,
        provider_symbol=(symbol if provider_symbol is _UNSET else provider_symbol),
        corporate_actions_checked_at=corporate_actions_checked_at,
    )
    _seed([instrument])
    bar = PriceBar(instrument_id=instrument.id, bar_date=date.today() - timedelta(days=1), close=10.0, provider="test")
    position = Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=10.0)
    _seed([bar, position])
    return instrument


def _row(response_json, symbol):
    return next((r for r in response_json["rows"] if r["symbol"] == symbol), None)


def _seed_candidate(
    instrument_id: int,
    provider: str,
    event_date: date,
    numerator: float,
    denominator: float,
) -> None:
    _seed(
        [
            ProviderCorporateActionCandidate(
                instrument_id=instrument_id,
                provider=provider,
                event_date=event_date,
                event_type="split" if numerator >= denominator else "reverse_split",
                numerator=numerator,
                denominator=denominator,
                economic_factor=numerator / denominator,
                provider_status="ok",
                retrieved_at=datetime.now(UTC),
            )
        ]
    )


def _seed_checked_no_event(instrument_id: int, provider: str = "alpha_vantage") -> None:
    """A provider was asked and genuinely found nothing — the real shape of
    an "ok" `ProviderCorporateActionCandidate` row with no event (see
    `_upsert_candidate`'s `event_date=None` convention). Needed so an
    instrument counts as answered by `provider` (not "incomplete_coverage")
    without any real split to report."""
    _seed(
        [
            ProviderCorporateActionCandidate(
                instrument_id=instrument_id,
                provider=provider,
                event_date=None,
                provider_status="ok",
                retrieved_at=datetime.now(UTC),
            )
        ]
    )


class TestEmptyAndAllFresh:
    def test_empty_portfolio(self, client):
        body = client.get("/api/portfolio/data-health").json()
        assert body == {
            "summary": {
                "total_instruments": 0,
                "info_count": 0,
                "attention_count": 0,
                "action_required_count": 0,
                "not_applicable_count": 0,
            },
            "rows": [],
            "figi_duplicates": [],
        }

    def test_all_fresh_portfolio_is_all_info(self, client):
        a = held_instrument("AAA.FR", "STOCK", corporate_actions_checked_at=datetime.now(UTC))
        b = held_instrument("BBB.FR", "STOCK", corporate_actions_checked_at=datetime.now(UTC))
        _seed_checked_no_event(a.id)
        _seed_checked_no_event(b.id)
        body = client.get("/api/portfolio/data-health").json()
        assert body["summary"]["total_instruments"] == 2
        assert body["summary"]["info_count"] == 2
        for row in body["rows"]:
            assert row["severity"] == "info"
            assert row["reason"] is None
            assert row["valuation"] == {"kind": "market_price", "source": "FMP", "as_of": row["valuation"]["as_of"], "freshness": "fresh"}


class TestValuationSignal:
    def test_unresolved_instrument(self, client):
        held_instrument("XYZ", "STOCK", mapping_status=MappingStatus.UNRESOLVED)
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "XYZ")
        assert row["severity"] == "action_required"
        assert row["reason"] == "unresolved_symbol"
        assert row["recommended_action"] == "fix_symbol"
        assert row["valuation"]["kind"] == "unavailable"
        assert row["corporate_actions"]["status"] == "not_applicable"

    def test_unresolved_with_known_isin_falls_through_to_never_refreshed_not_unresolved(self, client):
        # Same exclusion `_unresolved_instruments()` already applies for
        # UnresolvedPanel: a known ISIN means the gap is provider coverage,
        # not missing information, so this must not be flagged as
        # "unresolved_symbol" — it still can't produce a real price though.
        instrument = Instrument(
            broker_symbol="XYZ", category="STOCK", mapping_status=MappingStatus.UNRESOLVED, isin="FR0000000000"
        )
        _seed([instrument])
        _seed([Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=10.0)])

        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "XYZ")
        assert row["reason"] != "unresolved_symbol"
        assert row["severity"] == "attention"

    def test_stale_price(self, client):
        checked = datetime(2026, 8, 1, tzinfo=UTC)
        held_instrument("AAA.FR", "STOCK", prices_checked_at=checked, corporate_actions_checked_at=datetime.now(UTC))
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AAA.FR")
        assert row["severity"] == "attention"
        assert row["reason"] == "price_stale"
        assert row["recommended_action"] == "refresh_quotes"
        assert row["valuation"]["as_of"] == "2026-08-01"
        assert row["valuation"]["freshness"] == "stale"

    def test_price_error(self, client):
        held_instrument("AAA.FR", "STOCK", verified_at=None)
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AAA.FR")
        assert row["severity"] == "action_required"
        assert row["reason"] == "price_error"
        assert row["valuation"]["freshness"] == "unknown"

    def test_not_priceable_non_declared_reason_is_not_applicable(self, client):
        held_instrument("CVR1", "STOCK", not_priceable_reason="corporate_action")
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "CVR1")
        assert row["severity"] == "not_applicable"
        assert row["reason"] is None
        assert row["valuation"] == {"kind": "unavailable", "source": None, "as_of": None, "freshness": "unknown"}
        assert row["corporate_actions"]["status"] == "not_applicable"


class TestDeclaredValuationSignal:
    """A Mintos/Amundi position with a known declared value is never
    lumped into "unavailable" — see DEVLOG "Decision 3u.50"."""

    def test_fresh_declared_valuation_is_info(self, client):
        instrument = Instrument(
            broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate", currency="EUR"
        )
        _seed([instrument])
        _seed(
            [
                Position(
                    instrument_id=instrument.id, source="IMPORT", account="Mintos Core P2P",
                    quantity=1, avg_price=8000.00, broker_market_value=8000.00, currency="EUR",
                    value_as_of=date.today() - timedelta(days=5),
                )
            ]
        )

        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "MINTOS-CORE-P2P")
        assert row["severity"] == "info"
        assert row["valuation"]["kind"] == "declared_value"
        assert row["valuation"]["source"] == "Mintos"
        assert row["valuation"]["freshness"] == "fresh"
        assert row["corporate_actions"]["status"] == "not_applicable"

    def test_stale_declared_valuation_is_attention(self, client):
        instrument = Instrument(
            broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate", currency="EUR"
        )
        _seed([instrument])
        _seed(
            [
                Position(
                    instrument_id=instrument.id, source="IMPORT", account="Mintos Core P2P",
                    quantity=1, avg_price=4500.00, broker_market_value=4500.00, currency="EUR",
                    value_as_of=date(2025, 9, 30),
                )
            ]
        )

        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "MINTOS-CORE-P2P")
        assert row["severity"] == "attention"
        assert row["reason"] == "declared_stale"
        assert row["recommended_action"] == "import_recent_statement"
        assert row["valuation"]["as_of"] == "2025-09-30"

    def test_declared_valuation_with_no_date_is_attention(self, client):
        instrument = Instrument(
            broker_symbol="AMUNDI-ESR", category="FUND", not_priceable_reason="employee_savings_fund", currency="EUR"
        )
        _seed([instrument])
        _seed(
            [
                Position(
                    instrument_id=instrument.id, source="IMPORT", account="Amundi ESR",
                    quantity=1, avg_price=1000.0, broker_market_value=1000.0, currency="EUR", value_as_of=None,
                )
            ]
        )

        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AMUNDI-ESR")
        assert row["severity"] == "attention"
        assert row["reason"] == "declared_value_missing_date"
        assert row["valuation"]["source"] == "Amundi ESR"
        assert row["valuation"]["freshness"] == "unknown"


class TestCorporateActionsSignal:
    def test_never_checked_is_attention_even_though_price_is_fresh(self, client):
        held_instrument("AAA.US", "STOCK", corporate_actions_checked_at=None)
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AAA.US")
        assert row["corporate_actions"]["status"] == "never_checked"
        assert row["severity"] == "attention"
        assert row["reason"] == "corporate_action_never_checked"

    def test_checked_with_no_events_found_is_info(self, client):
        instrument = held_instrument("AAA.US", "STOCK", corporate_actions_checked_at=datetime.now(UTC))
        _seed_checked_no_event(instrument.id)
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AAA.US")
        assert row["corporate_actions"] == {"status": "no_events", "confirmed_events": 0, "outstanding_events": 0}
        assert row["severity"] == "info"

    def test_incomplete_alpha_vantage_coverage_is_attention(self, client):
        # Checked (by some provider) but Alpha Vantage in particular has
        # never answered for it — still on the targeted-resume queue.
        held_instrument("AAA.US", "STOCK", corporate_actions_checked_at=datetime.now(UTC))
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AAA.US")
        assert row["corporate_actions"]["status"] == "incomplete_coverage"
        assert row["severity"] == "attention"
        assert row["reason"] == "corporate_action_incomplete_coverage"
        assert row["recommended_action"] == "resume_alpha_vantage"

    def test_verified_applied_event_is_info(self, client):
        instrument = held_instrument("AAA.US", "STOCK", corporate_actions_checked_at=datetime.now(UTC))
        _seed_candidate(instrument.id, "alpha_vantage", date(2020, 1, 1), 2, 1)
        _seed_candidate(instrument.id, "polygon", date(2020, 1, 1), 2, 1)
        _seed(
            [
                CorporateAction(
                    instrument_id=instrument.id, action_type="split", effective_date=date(2020, 1, 1),
                    ratio_numerator=2, ratio_denominator=1, source="alpha_vantage", confidence="verified_cross_source",
                )
            ]
        )
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AAA.US")
        assert row["corporate_actions"] == {"status": "verified", "confirmed_events": 1, "outstanding_events": 0}
        assert row["severity"] == "info"

    def test_candidate_single_source_is_attention(self, client):
        instrument = held_instrument("AAA.US", "STOCK", corporate_actions_checked_at=datetime.now(UTC))
        _seed_candidate(instrument.id, "alpha_vantage", date(2020, 1, 1), 2, 1)
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AAA.US")
        assert row["corporate_actions"]["status"] == "candidate_single_source"
        assert row["corporate_actions"]["outstanding_events"] == 1
        assert row["severity"] == "attention"
        assert row["reason"] == "corporate_action_candidate"
        assert row["recommended_action"] == "verify_eodhd"

    def test_provider_conflict_is_attention(self, client):
        instrument = held_instrument("AAA.US", "STOCK", corporate_actions_checked_at=datetime.now(UTC))
        _seed_candidate(instrument.id, "alpha_vantage", date(2020, 1, 1), 2, 1)
        _seed_candidate(instrument.id, "polygon", date(2020, 1, 1), 3, 1)
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AAA.US")
        assert row["corporate_actions"]["status"] == "provider_conflict"
        assert row["severity"] == "attention"
        assert row["reason"] == "corporate_action_conflict"

    def test_suspect_ticker_reuse_wins_over_a_same_instrument_candidate(self, client):
        # A single provider reporting two far-apart events on the same
        # instrument: the older, isolated one is a suspect ticker-reuse
        # case (APLD-shaped — see DEVLOG "Decision 3u.41"), the newer one
        # is a genuine (if still single-source) candidate. The worse of
        # the two must win the row's overall status.
        instrument = held_instrument("APLD.US", "STOCK", corporate_actions_checked_at=datetime.now(UTC))
        _seed_candidate(instrument.id, "alpha_vantage", date(2003, 1, 1), 1, 800)
        _seed_candidate(instrument.id, "alpha_vantage", date(2022, 1, 1), 1, 6)
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "APLD.US")
        assert row["corporate_actions"]["status"] == "suspect_ticker_reuse"
        assert row["corporate_actions"]["outstanding_events"] == 2
        assert row["reason"] == "corporate_action_suspect"

    def test_not_applicable_for_a_declared_value_instrument_even_with_a_provider_symbol(self, client):
        instrument = Instrument(
            broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate",
            currency="EUR", provider_symbol="MINTOS-CORE-P2P",
        )
        _seed([instrument])
        _seed(
            [
                Position(
                    instrument_id=instrument.id, source="IMPORT", account="Mintos Core P2P",
                    quantity=1, avg_price=1.0, broker_market_value=1.0, currency="EUR", value_as_of=date.today(),
                )
            ]
        )
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "MINTOS-CORE-P2P")
        assert row["corporate_actions"]["status"] == "not_applicable"


class TestSeverityCombination:
    def test_corporate_actions_attention_overrides_a_fresh_price(self, client):
        held_instrument("AAA.US", "STOCK", corporate_actions_checked_at=None)
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AAA.US")
        assert row["valuation"]["freshness"] == "fresh"  # the price signal alone would be "info"
        assert row["severity"] == "attention"  # corporate actions is the more severe signal

    def test_price_error_outranks_a_corporate_actions_attention(self, client):
        held_instrument("AAA.US", "STOCK", verified_at=None, corporate_actions_checked_at=None)
        body = client.get("/api/portfolio/data-health").json()
        row = _row(body, "AAA.US")
        assert row["severity"] == "action_required"
        assert row["reason"] == "price_error"  # the more fundamental (value) signal wins the tie-break/higher rank


class TestSummaryAndOrdering:
    def test_summary_counts_and_severity_first_ordering(self, client):
        fresh = held_instrument("FRESH.FR", "STOCK", corporate_actions_checked_at=datetime.now(UTC))  # info
        _seed_checked_no_event(fresh.id)
        held_instrument("STALE.FR", "STOCK", prices_checked_at=datetime.now(UTC) - timedelta(days=30), corporate_actions_checked_at=datetime.now(UTC))  # attention
        held_instrument("ERROR.FR", "STOCK", verified_at=None, corporate_actions_checked_at=datetime.now(UTC))  # action_required
        held_instrument("CVR1", "STOCK", not_priceable_reason="corporate_action")  # not_applicable

        body = client.get("/api/portfolio/data-health").json()
        assert body["summary"] == {
            "total_instruments": 4,
            "info_count": 1,
            "attention_count": 1,
            "action_required_count": 1,
            "not_applicable_count": 1,
        }
        severities = [row["severity"] for row in body["rows"]]
        assert severities == ["action_required", "attention", "info", "not_applicable"]


class TestPositionsOnlyScope:
    def test_watchlist_only_unresolved_instrument_is_excluded(self, client):
        instrument = Instrument(broker_symbol="ZZZ", category="STOCK", mapping_status=MappingStatus.UNRESOLVED)
        _seed([instrument])
        _seed([WatchlistItem(instrument_id=instrument.id)])

        body = client.get("/api/portfolio/data-health").json()
        assert body["summary"]["total_instruments"] == 0
        assert body["rows"] == []


def _set_share_class_figi(instrument_id: int, value: str) -> None:
    session = next(app.dependency_overrides[get_db]())
    try:
        session.get(Instrument, instrument_id).share_class_figi = value
        session.commit()
    finally:
        session.close()


class TestFigiDuplicates:
    """`figi_duplicates` — additive, never affects `rows`/`summary`'s
    "held positions only" scope. See DEVLOG "Decision 3u.76"."""

    def test_a_held_and_a_watchlisted_instrument_sharing_a_figi_are_paired(self, client):
        held = held_instrument("AAA.US", "STOCK")
        _set_share_class_figi(held.id, "SAME")
        watched = Instrument(broker_symbol="BBB.L", category="STOCK", share_class_figi="SAME")
        _seed([watched])
        _seed([WatchlistItem(instrument_id=watched.id)])

        body = client.get("/api/portfolio/data-health").json()

        assert len(body["figi_duplicates"]) == 1
        pair = body["figi_duplicates"][0]
        assert {pair["a_symbol"], pair["b_symbol"]} == {"AAA.US", "BBB.L"}
        symbol_to_sources = {pair["a_symbol"]: pair["a_sources"], pair["b_symbol"]: pair["b_sources"]}
        assert symbol_to_sources["AAA.US"] == ["held"]
        assert symbol_to_sources["BBB.L"] == ["watchlist"]
        assert pair["share_class_figi"] == "SAME"

    def test_no_shared_figi_is_an_empty_list(self, client):
        held_instrument("AAA.US", "STOCK")

        body = client.get("/api/portfolio/data-health").json()

        assert body["figi_duplicates"] == []
