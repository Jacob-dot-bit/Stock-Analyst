"""Tests for stock split/reverse split detection and the read-time
quantity/price adjustment it drives — see `app/corporate_actions/service.py`.

Core invariants covered: `PriceBar`/`Lot` are never mutated by recording a
split; the quantity and price factors are inverses of each other and only
apply after their split's effective date; a provider's price history that
already reflects a split (ALREADY_ADJUSTED) is never corrected a second
time; detection tells RAW (needs correction) apart from ALREADY_ADJUSTED
using the same discontinuity check that found the real APLD/NVDA/GOOGL
discrepancy this feature was built to fix (DEVLOG "Decision 3u.30").
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.corporate_actions.service import (
    CORPORATE_ACTIONS_RECHECK_DAYS,
    compute_coverage_summary,
    cumulative_price_factor,
    cumulative_quantity_factor,
    detect_one,
    detect_splits,
    detect_price_history_status,
    get_resume_status,
    list_incomplete_instrument_ids,
    list_outstanding_candidates,
    load_actions_by_instrument,
    price_factor_from,
    promote_candidate,
    quantity_factor_from,
    resume_incomplete_scan,
    set_resume_enabled,
)
from app.db import Base, get_db
from app.main import app
from app.models import (
    AppMetadata,
    CorporateAction,
    CorporateActionConfidence,
    CorporateActionResumeRun,
    CorporateActionType,
    FmpSplitsStatus,
    Instrument,
    Lot,
    PriceHistoryStatus,
    PriceBar,
    ProviderCorporateActionCandidate,
)
from app.providers.base import SplitEvent, SymbolNotFound


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


def _instrument(db, symbol="AAPL.US") -> Instrument:
    instrument = Instrument(broker_symbol=symbol, provider_symbol=symbol.split(".")[0], currency="USD", country="US")
    db.add(instrument)
    db.flush()
    return instrument


def _bar(db, instrument_id, day: date, close: float) -> None:
    db.add(PriceBar(instrument_id=instrument_id, bar_date=day, close=close, open=close, high=close, low=close))
    db.flush()


class TestQuantityFactor:
    def test_split_multiplies_quantity(self):
        action = CorporateAction(
            instrument_id=1,
            action_type=CorporateActionType.SPLIT,
            effective_date=date(2024, 6, 10),
            ratio_numerator=10,
            ratio_denominator=1,
        )
        assert quantity_factor_from([action], date(2024, 1, 1)) == 10.0

    def test_reverse_split_divides_quantity(self):
        action = CorporateAction(
            instrument_id=1,
            action_type=CorporateActionType.REVERSE_SPLIT,
            effective_date=date(2022, 4, 12),
            ratio_numerator=1,
            ratio_denominator=6,
        )
        assert quantity_factor_from([action], date(2022, 1, 1)) == pytest.approx(1 / 6)

    def test_reference_date_after_effective_date_gets_no_factor(self):
        """A lot opened after the split already happened needs no correction —
        its recorded quantity is already on the post-split basis."""
        action = CorporateAction(
            instrument_id=1,
            action_type=CorporateActionType.SPLIT,
            effective_date=date(2024, 6, 10),
            ratio_numerator=10,
            ratio_denominator=1,
        )
        assert quantity_factor_from([action], date(2024, 7, 1)) == 1.0

    def test_reference_date_on_effective_date_gets_no_factor(self):
        """Boundary: effective_date itself is already post-split."""
        action = CorporateAction(
            instrument_id=1,
            action_type=CorporateActionType.SPLIT,
            effective_date=date(2024, 6, 10),
            ratio_numerator=10,
            ratio_denominator=1,
        )
        assert quantity_factor_from([action], date(2024, 6, 10)) == 1.0

    def test_two_splits_compound(self):
        first = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.SPLIT,
            effective_date=date(2023, 1, 1), ratio_numerator=2, ratio_denominator=1,
        )
        second = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.SPLIT,
            effective_date=date(2024, 1, 1), ratio_numerator=3, ratio_denominator=1,
        )
        assert quantity_factor_from([first, second], date(2022, 1, 1)) == pytest.approx(6.0)
        # Only the second split is still ahead of a reference date between them.
        assert quantity_factor_from([first, second], date(2023, 6, 1)) == pytest.approx(3.0)

    def test_fractional_ratio(self):
        action = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.SPLIT,
            effective_date=date(2024, 1, 1), ratio_numerator=3, ratio_denominator=2,
        )
        assert quantity_factor_from([action], date(2023, 1, 1)) == pytest.approx(1.5)


class TestPriceFactor:
    def test_is_inverse_of_quantity_factor_when_raw(self):
        action = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.SPLIT,
            effective_date=date(2024, 6, 10), ratio_numerator=10, ratio_denominator=1,
            price_history_status=PriceHistoryStatus.RAW,
        )
        qty = quantity_factor_from([action], date(2024, 1, 1))
        price = price_factor_from([action], date(2024, 1, 1))
        assert qty * price == pytest.approx(1.0)

    def test_never_applied_when_already_adjusted(self):
        """The exact double-adjustment this status exists to prevent: a
        provider that already restated its history must never be corrected
        again."""
        action = CorporateAction(
            instrument_id=1, action_type=CorporateActionType.SPLIT,
            effective_date=date(2024, 6, 10), ratio_numerator=10, ratio_denominator=1,
            price_history_status=PriceHistoryStatus.ALREADY_ADJUSTED,
        )
        assert price_factor_from([action], date(2024, 1, 1)) == 1.0

    def test_not_applied_when_unknown_or_not_applicable(self):
        for status in (PriceHistoryStatus.UNKNOWN, PriceHistoryStatus.NOT_APPLICABLE):
            action = CorporateAction(
                instrument_id=1, action_type=CorporateActionType.SPLIT,
                effective_date=date(2024, 6, 10), ratio_numerator=10, ratio_denominator=1,
                price_history_status=status,
            )
            assert price_factor_from([action], date(2024, 1, 1)) == 1.0


class TestDetectPriceHistoryStatus:
    def test_raw_history_shows_the_expected_discontinuity(self, db):
        """Shaped like the real APLD case: a genuine 1-for-6 reverse split
        whose stored history was never adjusted by the provider."""
        instrument = _instrument(db, "APLD.US")
        _bar(db, instrument.id, date(2022, 4, 11), 2.35)
        _bar(db, instrument.id, date(2022, 4, 12), 1.75)
        _bar(db, instrument.id, date(2022, 4, 13), 10.5)  # ~6x jump, matches the 1:6 ratio
        db.commit()

        status, ratio = detect_price_history_status(db, instrument.id, date(2022, 4, 13), 1, 6)

        assert status == PriceHistoryStatus.RAW
        assert ratio == pytest.approx(6.0)

    def test_already_adjusted_history_shows_no_discontinuity(self, db):
        """Shaped like the real NVDA case: a genuine 10-for-1 split whose
        stored history was already smoothed by the provider."""
        instrument = _instrument(db, "NVDA.US")
        _bar(db, instrument.id, date(2024, 6, 7), 120.0)
        _bar(db, instrument.id, date(2024, 6, 10), 121.0)  # smooth, no jump
        db.commit()

        status, ratio = detect_price_history_status(db, instrument.id, date(2024, 6, 10), 10, 1)

        assert status == PriceHistoryStatus.ALREADY_ADJUSTED
        assert ratio == pytest.approx(121.0 / 120.0)

    def test_not_applicable_when_no_bars_span_the_date(self, db):
        instrument = _instrument(db, "NEW.US")
        _bar(db, instrument.id, date(2025, 1, 1), 100.0)
        db.commit()

        status, ratio = detect_price_history_status(db, instrument.id, date(2020, 1, 1), 2, 1)

        assert status == PriceHistoryStatus.NOT_APPLICABLE
        assert ratio is None


class TestNonMutation:
    def test_creating_a_corporate_action_never_touches_price_bar_or_lot(self, db):
        from app.models import Lot, LotType, Source

        instrument = _instrument(db)
        _bar(db, instrument.id, date(2024, 6, 7), 1300.0)
        _bar(db, instrument.id, date(2024, 6, 10), 130.0)
        lot = Lot(
            instrument_id=instrument.id, source=Source.IMPORT, lot_type=LotType.OPEN,
            quantity=2.0, open_price=1000.0, opened_at=datetime(2024, 1, 1), currency="USD",
        )
        db.add(lot)
        db.commit()

        bars_before = [(b.bar_date, b.close) for b in db.query(PriceBar).all()]
        lot_before = (lot.quantity, lot.open_price)

        from app.corporate_actions.service import create_corporate_action

        create_corporate_action(
            db, instrument.id, CorporateActionType.SPLIT, date(2024, 6, 10), 10, 1, source="manual",
        )

        bars_after = [(b.bar_date, b.close) for b in db.query(PriceBar).all()]
        db.refresh(lot)
        assert bars_after == bars_before
        assert (lot.quantity, lot.open_price) == lot_before


class TestLoadActionsByInstrument:
    def test_groups_by_instrument_and_only_returns_requested_ids(self, db):
        a = _instrument(db, "A.US")
        b = _instrument(db, "B.US")
        db.add_all(
            [
                CorporateAction(instrument_id=a.id, action_type=CorporateActionType.SPLIT,
                                 effective_date=date(2024, 1, 1), ratio_numerator=2, ratio_denominator=1, source="manual"),
                CorporateAction(instrument_id=b.id, action_type=CorporateActionType.REVERSE_SPLIT,
                                 effective_date=date(2023, 1, 1), ratio_numerator=1, ratio_denominator=4, source="manual"),
            ]
        )
        db.commit()

        loaded = load_actions_by_instrument(db, [a.id])

        assert len(loaded[a.id]) == 1
        assert a.id in loaded and b.id not in loaded


class TestCumulativeConvenienceWrappers:
    def test_single_instrument_lookup_matches_batch_path(self, db):
        instrument = _instrument(db)
        db.add(
            CorporateAction(
                instrument_id=instrument.id, action_type=CorporateActionType.SPLIT,
                effective_date=date(2024, 1, 1), ratio_numerator=4, ratio_denominator=1, source="manual",
            )
        )
        db.commit()

        assert cumulative_quantity_factor(db, instrument.id, date(2023, 1, 1)) == pytest.approx(4.0)
        assert cumulative_price_factor(db, instrument.id, date(2023, 1, 1)) == 1.0  # UNKNOWN status by default, not RAW


#: Sentinel values for `FakeSplitsProvider`: raise the matching error for
#: this symbol instead of returning a (possibly empty) event list.
RATE_LIMITED = object()
PLAN_LIMITED = object()


class FakeSplitsProvider:
    """Controllable stand-in for one of `get_fmp_provider()`/
    `get_alpha_vantage_provider()`/`get_polygon_provider()`/
    `get_eodhd_provider()` — the real provider makes an HTTP call, which no
    unit test here should depend on. `provider_name` defaults to "fmp"
    since that's what most existing tests patch; a test standing in for a
    different source passes its own name so the `on_attempt`/`on_bytes`
    callbacks (and `CorporateAction.source`/`corroborating_sources`) stay
    accurate. `can_serve` always returns `True` — these fakes don't model
    per-provider market restrictions, only what `fetch_splits` itself
    returns or raises."""

    def __init__(self, events_by_symbol: dict[str, list[SplitEvent] | object], provider_name: str = "fmp"):
        self._events_by_symbol = events_by_symbol
        self._provider_name = provider_name
        self.attempts: list[str] = []
        self.bytes_calls: list[tuple[str, int]] = []

    def can_serve(self, ref) -> bool:
        return True

    def fetch_splits(self, ref, start, end, on_attempt=None, on_bytes=None):
        if on_attempt is not None:
            on_attempt(self._provider_name)
            self.attempts.append(ref.provider_symbol or "?")
        if on_bytes is not None:
            on_bytes(self._provider_name, 128)
            self.bytes_calls.append((ref.provider_symbol or "?", 128))
        if ref.provider_symbol not in self._events_by_symbol:
            raise SymbolNotFound(ref.provider_symbol or "?")
        result = self._events_by_symbol[ref.provider_symbol]
        if result is RATE_LIMITED:
            from app.providers.base import RateLimited

            raise RateLimited(ref.provider_symbol or "?")
        if result is PLAN_LIMITED:
            from app.providers.base import PlanLimited

            raise PlanLimited(ref.provider_symbol or "?")
        return result


class NullSplitsProvider:
    """Stands in for whichever of the three cross-source providers a given
    test isn't exercising — always reachable, always answers "no events" —
    so `detect_splits`'s multi-provider engine never falls through to the
    *real* registry (and a real network call) for a source the test doesn't
    care about."""

    def __init__(self, provider_name: str):
        self.name = provider_name

    def can_serve(self, ref) -> bool:
        return True

    def fetch_splits(self, ref, start, end, on_attempt=None, on_bytes=None):
        if on_attempt is not None:
            on_attempt(self.name)
        if on_bytes is not None:
            on_bytes(self.name, 0)
        return []


def _patch_providers(monkeypatch, alpha_vantage=None, polygon=None, fmp=None):
    """Patches all three of `detect_splits`'s cross-source registry lookups
    at once — any source not passed explicitly gets a `NullSplitsProvider`
    (reachable, contributes nothing), so a test can focus on just the
    source(s) it cares about without risking a real network call through an
    unpatched registry function."""
    monkeypatch.setattr(
        "app.corporate_actions.service.get_alpha_vantage_provider",
        lambda: alpha_vantage or NullSplitsProvider("alpha_vantage"),
    )
    monkeypatch.setattr(
        "app.corporate_actions.service.get_polygon_provider", lambda: polygon or NullSplitsProvider("polygon")
    )
    monkeypatch.setattr("app.corporate_actions.service.get_fmp_provider", lambda: fmp or NullSplitsProvider("fmp"))


def _held(db, instrument):
    from app.models import Position, Source

    db.add(Position(instrument_id=instrument.id, source=Source.IMPORT, quantity=1, avg_price=10.0))


class TestDetectSplits:
    """`detect_splits` cross-checks Alpha Vantage, Polygon, and
    (conditionally) FMP and only auto-creates a `CorporateAction` for an
    event at least two of the currently-active-tier sources agree on — see
    `app/corporate_actions/service.py::_classify_group` and DEVLOG
    "Decision 3u.41". Every test here patches all three registry functions
    via `_patch_providers`, so a source not under test contributes a
    harmless empty answer (`NullSplitsProvider`) rather than reaching the
    real network."""

    def test_zero_events_from_every_source_is_complete_no_events(self, db, monkeypatch):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        _patch_providers(monkeypatch)  # all three null — nobody finds anything

        summary = detect_splits(db)

        assert summary.candidates == 1
        assert summary.checked == 1
        assert summary.no_events == 1
        assert summary.created == 0
        assert summary.complete is True
        assert summary.actions == []

    def test_three_source_agreement_is_auto_created_with_full_confidence(self, db, monkeypatch):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        event = SplitEvent(effective_date=date(2020, 8, 31), numerator=4, denominator=1)
        av = FakeSplitsProvider({"AAPL": [event]}, provider_name="alpha_vantage")
        polygon = FakeSplitsProvider({"AAPL": [event]}, provider_name="polygon")
        fmp = FakeSplitsProvider({"AAPL": [event]}, provider_name="fmp")
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon, fmp=fmp)

        metadata = AppMetadata(fmp_splits_status=FmpSplitsStatus.ACTIVE)
        db.add(metadata)
        db.commit()

        summary = detect_splits(db)

        assert summary.found == 1
        assert summary.verified_three_sources == 1
        assert summary.created == 1
        assert summary.complete is True
        assert len(summary.actions) == 1
        assert summary.actions[0].confidence == CorporateActionConfidence.VERIFIED_THREE_SOURCES
        assert {s["provider"] for s in summary.actions[0].corroborating_sources} == {
            "alpha_vantage", "polygon", "fmp",
        }

    def test_two_source_agreement_ignores_fmp_while_recovering(self, db, monkeypatch):
        """FMP's own result is still recorded (visible for the readmission
        panel) but doesn't count as a vote while `fmp_splits_status` is the
        default "recovering" — 2-of-3 (Alpha Vantage + Polygon alone) is
        still enough to auto-apply."""
        instrument = _instrument(db, "APLD.US")
        _held(db, instrument)
        db.commit()

        event = SplitEvent(effective_date=date(2022, 4, 13), numerator=1, denominator=6)
        av = FakeSplitsProvider({"APLD": [event]}, provider_name="alpha_vantage")
        polygon = FakeSplitsProvider({"APLD": [event]}, provider_name="polygon")
        fmp = FakeSplitsProvider({"APLD": [event]}, provider_name="fmp")
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon, fmp=fmp)
        # No AppMetadata row seeded — detect_splits creates one defaulting
        # to "recovering" (FmpSplitsStatus's own default).

        summary = detect_splits(db)

        assert summary.verified_cross_source == 1
        assert summary.created == 1
        assert summary.actions[0].confidence == CorporateActionConfidence.VERIFIED_CROSS_SOURCE
        assert summary.actions[0].action_type == CorporateActionType.REVERSE_SPLIT
        # FMP's own matching result is still recorded as corroboration...
        assert {s["provider"] for s in summary.actions[0].corroborating_sources} == {
            "alpha_vantage", "polygon", "fmp",
        }
        # ...but only Alpha Vantage + Polygon were the counted vote.
        assert summary.actions[0].source in ("alpha_vantage", "polygon")

    def test_single_source_finding_becomes_a_visible_candidate_not_applied(self, db, monkeypatch):
        instrument = _instrument(db, "NKE.US")
        _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider(
            {"NKE": [SplitEvent(effective_date=date(2012, 12, 24), numerator=2, denominator=1)]},
            provider_name="alpha_vantage",
        )
        _patch_providers(monkeypatch, alpha_vantage=av)

        summary = detect_splits(db)

        assert summary.found == 1
        assert summary.candidate_single_source == 1
        assert summary.created == 0
        assert summary.actions == []
        # Never silently dropped: a real candidate row exists to review or promote.
        from app.models import ProviderCorporateActionCandidate

        candidate = db.query(ProviderCorporateActionCandidate).filter(
            ProviderCorporateActionCandidate.instrument_id == instrument.id,
            ProviderCorporateActionCandidate.provider == "alpha_vantage",
        ).one()
        assert candidate.event_date == date(2012, 12, 24)

    def test_a_lone_fmp_result_is_a_single_source_candidate_while_recovering(self, db, monkeypatch):
        """FMP alone (recovering, so it doesn't vote) is exactly as
        uncorroborated as any other single source — never silently applied,
        never silently dropped either."""
        instrument = _instrument(db, "APLD.US")
        _held(db, instrument)
        db.commit()

        fmp = FakeSplitsProvider(
            {"APLD": [SplitEvent(effective_date=date(2022, 4, 13), numerator=1, denominator=6)]}, provider_name="fmp"
        )
        _patch_providers(monkeypatch, fmp=fmp)

        summary = detect_splits(db)

        assert summary.candidate_single_source == 1
        assert summary.created == 0

    def test_conflicting_ratios_on_the_same_date_are_flagged_not_applied(self, db, monkeypatch):
        """A genuine disagreement — two sources, same date, different
        ratio — must never resolve itself by majority or by picking
        whichever provider ran first. Flagged for a human, not guessed at."""
        instrument = _instrument(db, "CONFLICT.US")
        _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider(
            {"CONFLICT": [SplitEvent(effective_date=date(2021, 6, 1), numerator=4, denominator=1)]},
            provider_name="alpha_vantage",
        )
        polygon = FakeSplitsProvider(
            {"CONFLICT": [SplitEvent(effective_date=date(2021, 6, 2), numerator=2, denominator=1)]},
            provider_name="polygon",
        )
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon)

        summary = detect_splits(db)

        assert summary.provider_conflict == 1
        assert summary.created == 0
        assert summary.actions == []

    def test_an_isolated_decades_old_event_is_suspect_ticker_reuse_even_if_corroborated(self, db, monkeypatch):
        """The exact APLD reference case: an isolated event from ~19 years
        before the instrument's only other known event — never auto-applied,
        no matter how many sources happen to repeat it. The real, recent
        event alongside it is unaffected and still gets applied normally."""
        instrument = _instrument(db, "APLD.US")
        _held(db, instrument)
        db.commit()

        old_event = SplitEvent(effective_date=date(2003, 12, 16), numerator=1, denominator=800)
        real_event = SplitEvent(effective_date=date(2022, 4, 13), numerator=1, denominator=6)
        # Both events reported by Polygon *and* FMP — deliberately testing
        # that corroboration alone does not rescue the isolated old one.
        polygon = FakeSplitsProvider({"APLD": [old_event, real_event]}, provider_name="polygon")
        fmp = FakeSplitsProvider({"APLD": [old_event, real_event]}, provider_name="fmp")
        _patch_providers(monkeypatch, polygon=polygon, fmp=fmp)
        db.add(AppMetadata(fmp_splits_status=FmpSplitsStatus.ACTIVE))
        db.commit()

        summary = detect_splits(db)

        # The isolated 2003 event is flagged, never applied...
        assert summary.suspect_ticker_reuse == 1
        # ...while the real, recent 2022 event (corroborated by 2 sources)
        # is unaffected and applied normally.
        assert summary.verified_cross_source == 1
        assert summary.created == 1
        assert summary.actions[0].effective_date == date(2022, 4, 13)

    def test_a_single_old_event_with_nothing_to_compare_against_is_not_flagged(self, db, monkeypatch):
        """The isolation check needs another event on the same instrument to
        compare against — a single old split, with no other history found
        for that instrument this scan, has no basis for suspicion and is
        classified purely by source count like any other event."""
        instrument = _instrument(db, "OLD.US")
        _held(db, instrument)
        db.commit()

        old_event = SplitEvent(effective_date=date(1990, 1, 1), numerator=2, denominator=1)
        av = FakeSplitsProvider({"OLD": [old_event]}, provider_name="alpha_vantage")
        polygon = FakeSplitsProvider({"OLD": [old_event]}, provider_name="polygon")
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon)

        summary = detect_splits(db)

        assert summary.suspect_ticker_reuse == 0
        assert summary.verified_cross_source == 1
        assert summary.created == 1

    def test_one_provider_erroring_does_not_block_the_others(self, db, monkeypatch):
        """A `SymbolNotFound`/`ProviderUnavailable` from one source is just
        that source's absence for this instrument, not a whole-instrument
        failure, as long as another source answers."""
        instrument = _instrument(db, "APLD.US")
        _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider({}, provider_name="alpha_vantage")  # APLD absent -> SymbolNotFound
        polygon = FakeSplitsProvider(
            {"APLD": [SplitEvent(effective_date=date(2022, 4, 13), numerator=1, denominator=6)]}, provider_name="polygon"
        )
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon)

        summary = detect_splits(db)

        assert summary.checked == 1  # Polygon answered, so the instrument was checked
        assert summary.failed == 0  # not every provider failed
        assert summary.candidate_single_source == 1  # Polygon alone, uncorroborated
        assert summary.complete is True

    def test_every_provider_failing_marks_the_instrument_failed(self, db, monkeypatch):
        instrument = _instrument(db, "BROKEN.US")
        _held(db, instrument)
        db.commit()

        broken = FakeSplitsProvider({}, provider_name="alpha_vantage")
        also_broken = FakeSplitsProvider({}, provider_name="polygon")
        also_broken_fmp = FakeSplitsProvider({}, provider_name="fmp")
        _patch_providers(monkeypatch, alpha_vantage=broken, polygon=also_broken, fmp=also_broken_fmp)

        summary = detect_splits(db)

        assert summary.failed == 1
        assert summary.checked == 0
        assert summary.complete is False

    def test_every_provider_rate_limited_marks_the_instrument_rate_limited_not_failed(self, db, monkeypatch):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider({"AAPL": RATE_LIMITED}, provider_name="alpha_vantage")
        polygon = FakeSplitsProvider({"AAPL": RATE_LIMITED}, provider_name="polygon")
        fmp = FakeSplitsProvider({"AAPL": RATE_LIMITED}, provider_name="fmp")
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon, fmp=fmp)

        summary = detect_splits(db)

        assert summary.rate_limited == 1
        assert summary.failed == 0
        assert summary.checked == 0
        assert summary.complete is False

    def test_a_rate_limited_provider_is_not_called_again_this_scan(self, db, monkeypatch):
        """Once a provider is rate-limited, it's skipped (not called again)
        for the rest of this scan's instruments — not hammered further —
        while the other providers keep contributing normally."""
        first = _instrument(db, "FIRST.US")
        second = _instrument(db, "SECOND.US")
        for instrument in (first, second):
            _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider({"FIRST": RATE_LIMITED, "SECOND": []}, provider_name="alpha_vantage")
        _patch_providers(monkeypatch, alpha_vantage=av)

        detect_splits(db)

        # Only one real attempt against Alpha Vantage — FIRST triggered the
        # rate limit, SECOND was skipped without a second real call.
        assert av.attempts == ["FIRST"]

    def test_an_instrument_with_no_provider_symbol_is_skipped_without_a_call(self, db, monkeypatch):
        instrument = Instrument(broker_symbol="NOPROV.US", provider_symbol=None, currency="USD", country="US")
        db.add(instrument)
        db.flush()
        _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider({})
        _patch_providers(monkeypatch, alpha_vantage=av)

        summary = detect_splits(db)

        assert summary.candidates == 1
        assert summary.skipped == 1
        assert summary.checked == 0
        assert av.attempts == []  # no provider was ever called for this instrument
        assert summary.complete is True

    def test_ignores_instruments_not_held_watched_or_screened(self, db, monkeypatch):
        _instrument(db, "IGNORED.US")
        db.commit()
        _patch_providers(monkeypatch)

        summary = detect_splits(db)

        assert summary.candidates == 0
        assert summary.actions == []
        assert summary.complete is True

    def test_a_second_run_never_duplicates_a_split_it_already_created(self, db, monkeypatch):
        """Idempotency across two full runs, not just a pre-seeded row —
        the exact case a user clicking 'Check for new splits' twice hits.
        `force=True` on the second call, since a plain back-to-back call
        would now hit the DEVLOG "Decision 3u.41" recheck-cadence gate
        instead (covered separately by `TestRecheckCadenceGate`) — this
        test is specifically about the dedup logic, not the gate."""
        instrument = _instrument(db, "APLD.US")
        _held(db, instrument)
        db.commit()

        event = SplitEvent(effective_date=date(2022, 4, 12), numerator=1, denominator=6)
        av = FakeSplitsProvider({"APLD": [event]}, provider_name="alpha_vantage")
        polygon = FakeSplitsProvider({"APLD": [event]}, provider_name="polygon")
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon)

        first = detect_splits(db)
        second = detect_splits(db, force=True)

        assert first.created == 1
        assert second.created == 0
        assert second.already_known == 1


class TestListIncompleteInstrumentIds:
    """A source with a tight daily quota (Alpha Vantage's free tier, ~25/day)
    can't cross-check a whole portfolio in one sitting — a targeted resume
    the next day should spend that quota on what's actually missing, not
    blindly re-scan everything (DEVLOG "Decision 3u.41"). Live-verified: a
    real scan's `alpha_vantage`/APLD "ok" row from an early, successful call
    stayed untouched by a *later* rate-limited attempt for the same
    instrument (a separate `event_date=None` row), which is exactly the
    "already answered, even if the most recent attempt failed" case this
    selection logic must get right."""

    def test_an_instrument_the_provider_never_answered_is_incomplete(self, db):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        assert list_incomplete_instrument_ids(db, provider_name="alpha_vantage") == [instrument.id]

    def test_an_instrument_with_a_real_ok_row_is_not_incomplete_even_if_a_later_attempt_failed(self, db):
        instrument = _instrument(db, "APLD.US")
        _held(db, instrument)
        db.add(
            ProviderCorporateActionCandidate(
                instrument_id=instrument.id, provider="alpha_vantage",
                event_date=date(2022, 4, 13), event_type="reverse_split",
                numerator=1, denominator=6, provider_status="ok",
            )
        )
        # A later attempt failed — this is a *separate* row (event_date=None),
        # and must not make the earlier real answer disappear.
        db.add(
            ProviderCorporateActionCandidate(
                instrument_id=instrument.id, provider="alpha_vantage", event_date=None, provider_status="rate_limited",
            )
        )
        db.commit()

        assert list_incomplete_instrument_ids(db, provider_name="alpha_vantage") == []

    def test_an_ok_no_events_row_also_counts_as_answered(self, db):
        instrument = _instrument(db, "NEVER.US")
        _held(db, instrument)
        db.add(
            ProviderCorporateActionCandidate(
                instrument_id=instrument.id, provider="alpha_vantage", event_date=None, provider_status="ok",
            )
        )
        db.commit()

        assert list_incomplete_instrument_ids(db, provider_name="alpha_vantage") == []

    def test_an_instrument_with_another_sources_real_event_is_prioritized_first(self, db):
        waiting = _instrument(db, "WAITING.US")
        plain = _instrument(db, "ZZZZ.US")
        for instrument in (waiting, plain):
            _held(db, instrument)
        db.add(
            ProviderCorporateActionCandidate(
                instrument_id=waiting.id, provider="polygon",
                event_date=date(2022, 1, 1), event_type="split", numerator=2, denominator=1, provider_status="ok",
            )
        )
        db.commit()

        result = list_incomplete_instrument_ids(db, provider_name="alpha_vantage")

        assert result[0] == waiting.id
        assert plain.id in result

    def test_reference_symbols_are_prioritized_over_plain_unknowns(self, db):
        reference = _instrument(db, "AAPL.US")
        plain = _instrument(db, "ZZZZ.US")
        for instrument in (reference, plain):
            _held(db, instrument)
        db.commit()

        result = list_incomplete_instrument_ids(db, provider_name="alpha_vantage")

        assert result.index(reference.id) < result.index(plain.id)

    def test_limit_truncates_the_ordered_list(self, db):
        for i in range(5):
            instrument = _instrument(db, f"SYM{i}.US")
            _held(db, instrument)
        db.commit()

        assert len(list_incomplete_instrument_ids(db, provider_name="alpha_vantage", limit=2)) == 2

    def test_a_fully_answered_portfolio_is_empty(self, db):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.add(
            ProviderCorporateActionCandidate(
                instrument_id=instrument.id, provider="alpha_vantage", event_date=None, provider_status="ok",
            )
        )
        db.commit()

        assert list_incomplete_instrument_ids(db, provider_name="alpha_vantage") == []


class TestPromoteCandidate:
    def test_promotes_a_single_source_candidate_into_a_real_action(self, db):
        instrument = _instrument(db, "NKE.US")
        candidate = ProviderCorporateActionCandidate(
            instrument_id=instrument.id, provider="alpha_vantage",
            event_date=date(2012, 12, 24), event_type=CorporateActionType.SPLIT,
            numerator=2, denominator=1, provider_status="ok",
        )
        db.add(candidate)
        db.commit()

        action = promote_candidate(db, candidate.id)

        assert action is not None
        assert action.action_type == CorporateActionType.SPLIT
        assert action.effective_date == date(2012, 12, 24)
        assert action.source == "alpha_vantage"
        assert action.confidence == CorporateActionConfidence.MANUAL_PROMOTION
        assert action.corroborating_sources == [
            {"provider": "alpha_vantage", "event_date": "2012-12-24", "numerator": 2.0, "denominator": 1.0}
        ]

    def test_promoting_twice_returns_the_same_row_not_a_duplicate(self, db):
        instrument = _instrument(db, "NKE.US")
        candidate = ProviderCorporateActionCandidate(
            instrument_id=instrument.id, provider="polygon",
            event_date=date(2012, 12, 24), event_type=CorporateActionType.SPLIT,
            numerator=2, denominator=1, provider_status="ok",
        )
        db.add(candidate)
        db.commit()

        first = promote_candidate(db, candidate.id)
        second = promote_candidate(db, candidate.id)

        assert first.id == second.id
        assert db.query(CorporateAction).count() == 1

    def test_a_status_only_candidate_cannot_be_promoted(self, db):
        instrument = _instrument(db, "NKE.US")
        candidate = ProviderCorporateActionCandidate(
            instrument_id=instrument.id, provider="alpha_vantage", event_date=None, provider_status="rate_limited",
        )
        db.add(candidate)
        db.commit()

        assert promote_candidate(db, candidate.id) is None

    def test_unknown_candidate_returns_none(self, db):
        assert promote_candidate(db, 999999) is None


class TestResumeIncompleteScan:
    """The scheduled daily targeted-resume job — see DEVLOG "Decision
    3u.41". Persists a `CorporateActionResumeRun` every time it's called,
    including when it does nothing at all (paused, or nothing incomplete),
    so "last attempt / result" is always something concrete to show, never
    silently absent."""

    def test_a_real_run_persists_its_results(self, db, monkeypatch):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider({"AAPL": []}, provider_name="alpha_vantage")
        _patch_providers(monkeypatch, alpha_vantage=av)

        run = resume_incomplete_scan(db, provider_name="alpha_vantage", limit=10)

        assert run.skipped_reason is None
        assert run.targeted_instrument_ids == [instrument.id]
        assert run.checked == 1
        assert run.finished_at is not None
        assert db.query(CorporateActionResumeRun).count() == 1

    def test_paused_run_calls_no_provider_and_records_why(self, db, monkeypatch):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider({"AAPL": []}, provider_name="alpha_vantage")
        _patch_providers(monkeypatch, alpha_vantage=av)
        set_resume_enabled(db, False)

        run = resume_incomplete_scan(db, provider_name="alpha_vantage")

        assert run.skipped_reason == "paused"
        assert run.targeted_instrument_ids == []
        assert av.attempts == []  # never called

    def test_nothing_incomplete_is_recorded_distinctly_from_a_real_zero_run(self, db, monkeypatch):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.add(
            ProviderCorporateActionCandidate(
                instrument_id=instrument.id, provider="alpha_vantage", event_date=None, provider_status="ok",
            )
        )
        db.commit()

        av = FakeSplitsProvider({"AAPL": []}, provider_name="alpha_vantage")
        _patch_providers(monkeypatch, alpha_vantage=av)

        run = resume_incomplete_scan(db, provider_name="alpha_vantage")

        assert run.skipped_reason == "nothing_incomplete"
        assert av.attempts == []  # never called — already fully answered

    def test_remaining_incomplete_reflects_what_is_left_after_the_run(self, db, monkeypatch):
        done_soon = _instrument(db, "AAPL.US")
        still_incomplete = _instrument(db, "NVDA.US")
        for instrument in (done_soon, still_incomplete):
            _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider({"AAPL": []}, provider_name="alpha_vantage")
        _patch_providers(monkeypatch, alpha_vantage=av)

        # limit=1 -> only one of the two eligible instruments gets targeted this run.
        run = resume_incomplete_scan(db, provider_name="alpha_vantage", limit=1)

        assert run.remaining_incomplete == 1


class TestResumeStatusAndToggle:
    def test_default_status_before_any_run(self, db):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        enabled, remaining, last_run = get_resume_status(db, provider_name="alpha_vantage")

        assert enabled is True
        assert remaining == 1
        assert last_run is None

    def test_pausing_is_reflected_in_status(self, db):
        set_resume_enabled(db, False)

        enabled, _, _ = get_resume_status(db)

        assert enabled is False

    def test_status_reflects_the_most_recent_run(self, db, monkeypatch):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider({"AAPL": []}, provider_name="alpha_vantage")
        _patch_providers(monkeypatch, alpha_vantage=av)
        run = resume_incomplete_scan(db, provider_name="alpha_vantage")

        _, _, last_run = get_resume_status(db, provider_name="alpha_vantage")

        assert last_run.id == run.id


class TestQuotaTrackingWiring:
    """`fetch_splits` bypasses `ProviderChain` entirely, so unlike price
    refresh it had zero quota tracking until DEVLOG "Decision 3u.41" wired
    `on_attempt`/`on_bytes` directly from `detect_splits`/`detect_one`. This
    is what actually makes a bandwidth drain like FMP's visible next time,
    instead of only discoverable by a live `curl` after the blackout."""

    def test_detect_splits_records_usage_and_bytes(self, db, monkeypatch):
        from app.models import ProviderUsage

        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        fake = FakeSplitsProvider({"AAPL": []})
        _patch_providers(monkeypatch, fmp=fake)

        detect_splits(db)

        row = db.query(ProviderUsage).filter(ProviderUsage.provider == "fmp").one()
        assert row.count == 1
        assert row.bytes_used == 128

    def test_detect_one_records_usage_and_bytes(self, db, monkeypatch):
        from app.models import ProviderUsage

        instrument = _instrument(db, "APLD.US")
        db.commit()

        fake = FakeSplitsProvider({"APLD": []}, provider_name="eodhd")
        monkeypatch.setattr("app.corporate_actions.service.get_eodhd_provider", lambda: fake)

        detect_one(db, instrument.id, "eodhd")

        row = db.query(ProviderUsage).filter(ProviderUsage.provider == "eodhd").one()
        assert row.count == 1
        assert row.bytes_used == 128


class TestRecheckCadenceGate:
    """DEVLOG "Decision 3u.41" — the splits endpoints return full unbounded
    history with no server-side range filter, so re-scanning the same
    portfolio repeatedly is what drained FMP's bandwidth quota. A bulk
    `detect_splits()` call now skips an instrument checked within
    `CORPORATE_ACTIONS_RECHECK_DAYS`, unless `force=True`. `detect_one` has
    no such gate — deliberate, see its own docstring."""

    def test_a_freshly_checked_instrument_is_skipped_on_the_next_call(self, db, monkeypatch):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        fake = FakeSplitsProvider({"AAPL": []})
        _patch_providers(monkeypatch, fmp=fake)

        first = detect_splits(db)
        second = detect_splits(db)

        assert first.checked == 1
        assert first.recently_checked == 0
        assert second.checked == 0
        assert second.recently_checked == 1
        assert len(fake.attempts) == 1  # the provider was only ever actually called once

    def test_force_true_rechecks_regardless_of_recency(self, db, monkeypatch):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        fake = FakeSplitsProvider({"AAPL": []})
        _patch_providers(monkeypatch, fmp=fake)

        detect_splits(db)
        second = detect_splits(db, force=True)

        assert second.checked == 1
        assert second.recently_checked == 0
        assert len(fake.attempts) == 2

    def test_an_instrument_checked_long_ago_is_rechecked(self, db, monkeypatch):
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        instrument.corporate_actions_checked_at = datetime.now(UTC) - timedelta(days=CORPORATE_ACTIONS_RECHECK_DAYS + 1)
        db.commit()

        fake = FakeSplitsProvider({"AAPL": []})
        _patch_providers(monkeypatch, fmp=fake)

        summary = detect_splits(db)

        assert summary.checked == 1
        assert summary.recently_checked == 0

    def test_a_structural_failure_still_counts_as_checked_for_the_gate(self, db, monkeypatch):
        """A `PlanLimited`/`SymbolNotFound` answer is stable and repeatable
        — marking it checked avoids re-querying a symbol that will keep
        failing the same way every time, unlike a transient rate limit.
        Every source must fail for this to apply — see
        `TestDetectSplits.test_every_provider_failing_marks_the_instrument_failed`."""
        instrument = _instrument(db, "GATED.US")
        _held(db, instrument)
        db.commit()

        fmp = FakeSplitsProvider({"GATED": PLAN_LIMITED}, provider_name="fmp")
        av = FakeSplitsProvider({}, provider_name="alpha_vantage")  # absent -> SymbolNotFound
        polygon = FakeSplitsProvider({}, provider_name="polygon")
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon, fmp=fmp)

        first = detect_splits(db)
        second = detect_splits(db)

        assert first.failed == 1
        assert second.recently_checked == 1
        assert second.failed == 0

    def test_a_rate_limit_does_not_count_as_checked_for_the_gate(self, db, monkeypatch):
        """The opposite of the structural-failure case: a rate limit is
        transient, so the instrument must be retried on the very next scan,
        not held back for the full recheck window. Every source must be
        rate-limited for this to apply."""
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider({"AAPL": RATE_LIMITED}, provider_name="alpha_vantage")
        polygon = FakeSplitsProvider({"AAPL": RATE_LIMITED}, provider_name="polygon")
        fmp = FakeSplitsProvider({"AAPL": RATE_LIMITED}, provider_name="fmp")
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon, fmp=fmp)

        first = detect_splits(db)
        second = detect_splits(db)

        assert first.rate_limited == 1
        assert second.recently_checked == 0
        assert second.rate_limited == 1


class TestDetectOne:
    """The targeted, single-instrument fallback (DEVLOG "Decision 3u.35"),
    built for the exact case found live: FMP returns `plan_limited` for
    APLD, but EODHD answers correctly via a different endpoint. Never part
    of `detect_splits`'s bulk scan — always exactly one instrument,
    triggered explicitly. Every failure shape must stay distinct from
    `no_events`: a failure must never read as a confirmed absence of split."""

    def test_creates_a_new_event(self, db, monkeypatch):
        instrument = _instrument(db, "APLD.US")
        db.commit()

        fake = FakeSplitsProvider({"APLD": [SplitEvent(effective_date=date(2022, 4, 13), numerator=1, denominator=6)]})
        monkeypatch.setattr("app.corporate_actions.service.get_eodhd_provider", lambda: fake)

        result = detect_one(db, instrument.id, "eodhd")

        assert result.status == "created"
        assert result.created == 1
        assert result.found == 1
        assert result.already_known == 0
        assert len(result.actions) == 1
        assert result.actions[0].source == "eodhd"
        assert result.actions[0].action_type == CorporateActionType.REVERSE_SPLIT

    def test_recognizes_an_already_known_event_without_duplicating(self, db, monkeypatch):
        instrument = _instrument(db, "APLD.US")
        db.add(
            CorporateAction(
                instrument_id=instrument.id, action_type=CorporateActionType.REVERSE_SPLIT,
                effective_date=date(2022, 4, 13), ratio_numerator=1, ratio_denominator=6, source="eodhd",
            )
        )
        db.commit()

        fake = FakeSplitsProvider({"APLD": [SplitEvent(effective_date=date(2022, 4, 13), numerator=1, denominator=6)]})
        monkeypatch.setattr("app.corporate_actions.service.get_eodhd_provider", lambda: fake)

        result = detect_one(db, instrument.id, "eodhd")

        assert result.status == "already_known"
        assert result.created == 0
        assert result.already_known == 1
        assert result.actions == []
        assert db.query(CorporateAction).count() == 1  # no duplicate

    def test_a_genuine_empty_response_is_no_events_not_a_failure(self, db, monkeypatch):
        instrument = _instrument(db, "ASML.NL")
        db.commit()

        fake = FakeSplitsProvider({"ASML": []})
        monkeypatch.setattr("app.corporate_actions.service.get_eodhd_provider", lambda: fake)

        result = detect_one(db, instrument.id, "eodhd")

        assert result.status == "no_events"
        assert result.created == 0
        assert result.actions == []

    def test_rate_limited_is_its_own_status_never_no_events(self, db, monkeypatch):
        instrument = _instrument(db, "APLD.US")
        db.commit()

        fake = FakeSplitsProvider({"APLD": RATE_LIMITED})
        monkeypatch.setattr("app.corporate_actions.service.get_eodhd_provider", lambda: fake)

        result = detect_one(db, instrument.id, "eodhd")

        assert result.status == "rate_limited"
        assert result.created == 0

    def test_unknown_symbol_is_not_supported_never_no_events(self, db, monkeypatch):
        instrument = _instrument(db, "APLD.US")
        db.commit()

        fake = FakeSplitsProvider({})  # APLD not in the dict -> SymbolNotFound
        monkeypatch.setattr("app.corporate_actions.service.get_eodhd_provider", lambda: fake)

        result = detect_one(db, instrument.id, "eodhd")

        assert result.status == "not_supported"
        assert result.created == 0

    def test_provider_error_is_failed_never_no_events(self, db, monkeypatch):
        instrument = _instrument(db, "APLD.US")
        db.commit()

        class BrokenProvider:
            def fetch_splits(self, ref, start, end, on_attempt=None, on_bytes=None):
                from app.providers.base import ProviderUnavailable

                raise ProviderUnavailable("network error")

        monkeypatch.setattr("app.corporate_actions.service.get_eodhd_provider", lambda: BrokenProvider())

        result = detect_one(db, instrument.id, "eodhd")

        assert result.status == "failed"
        assert result.created == 0

    def test_unknown_instrument_returns_none(self, db, monkeypatch):
        fake = FakeSplitsProvider({})
        monkeypatch.setattr("app.corporate_actions.service.get_eodhd_provider", lambda: fake)

        assert detect_one(db, 999999, "eodhd") is None

    def test_does_not_mutate_price_bars_or_lots(self, db, monkeypatch):
        from app.models import Lot, LotType, Source

        instrument = _instrument(db, "APLD.US")
        _bar(db, instrument.id, date(2022, 4, 10), 6.0)
        _bar(db, instrument.id, date(2022, 4, 14), 1.0)
        db.add(
            Lot(
                instrument_id=instrument.id, quantity=10, open_price=6.0, opened_at=datetime(2022, 1, 1),
                currency="USD", account="Test", lot_type=LotType.OPEN, source=Source.IMPORT,
            )
        )
        db.commit()

        bars_before = [(b.bar_date, b.close) for b in db.query(PriceBar).all()]
        lots_before = [(lot.quantity, lot.open_price) for lot in db.query(Lot).all()]

        fake = FakeSplitsProvider({"APLD": [SplitEvent(effective_date=date(2022, 4, 13), numerator=1, denominator=6)]})
        monkeypatch.setattr("app.corporate_actions.service.get_eodhd_provider", lambda: fake)
        detect_one(db, instrument.id, "eodhd")

        bars_after = [(b.bar_date, b.close) for b in db.query(PriceBar).all()]
        lots_after = [(lot.quantity, lot.open_price) for lot in db.query(Lot).all()]
        assert bars_after == bars_before
        assert lots_after == lots_before


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


class TestCorporateActionsApi:
    def test_create_and_list(self, client):
        instrument = Instrument(broker_symbol="AAPL.US", currency="USD", country="US")
        _seed([instrument])

        response = client.post(
            "/api/corporate-actions",
            json={
                "instrument_id": instrument.id,
                "action_type": "split",
                "effective_date": "2024-06-10",
                "ratio_numerator": 10,
                "ratio_denominator": 1,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["action_type"] == "split"
        assert body["source"] == "manual"
        assert body["instrument"]["broker_symbol"] == "AAPL.US"

        listed = client.get("/api/corporate-actions").json()
        assert len(listed) == 1

    def test_rejects_invalid_action_type(self, client):
        instrument = Instrument(broker_symbol="AAPL.US", currency="USD", country="US")
        _seed([instrument])

        response = client.post(
            "/api/corporate-actions",
            json={
                "instrument_id": instrument.id,
                "action_type": "merger",
                "effective_date": "2024-06-10",
                "ratio_numerator": 10,
                "ratio_denominator": 1,
            },
        )
        assert response.status_code == 422

    def test_rejects_unknown_instrument(self, client):
        response = client.post(
            "/api/corporate-actions",
            json={
                "instrument_id": 999,
                "action_type": "split",
                "effective_date": "2024-06-10",
                "ratio_numerator": 10,
                "ratio_denominator": 1,
            },
        )
        assert response.status_code == 404

    def test_delete(self, client):
        instrument = Instrument(broker_symbol="AAPL.US", currency="USD", country="US")
        _seed([instrument])
        created = client.post(
            "/api/corporate-actions",
            json={
                "instrument_id": instrument.id,
                "action_type": "split",
                "effective_date": "2024-06-10",
                "ratio_numerator": 10,
                "ratio_denominator": 1,
            },
        ).json()

        response = client.delete(f"/api/corporate-actions/{created['id']}")
        assert response.status_code == 204
        assert client.get("/api/corporate-actions").json() == []

    def test_delete_unknown_returns_404(self, client):
        response = client.delete("/api/corporate-actions/999")
        assert response.status_code == 404

    def test_filter_by_instrument_id(self, client):
        a = Instrument(broker_symbol="A.US", currency="USD", country="US")
        b = Instrument(broker_symbol="B.US", currency="USD", country="US")
        _seed([a, b])
        for instrument in (a, b):
            client.post(
                "/api/corporate-actions",
                json={
                    "instrument_id": instrument.id,
                    "action_type": "split",
                    "effective_date": "2024-06-10",
                    "ratio_numerator": 2,
                    "ratio_denominator": 1,
                },
            )

        response = client.get("/api/corporate-actions", params={"instrument_id": a.id})

        assert len(response.json()) == 1
        assert response.json()[0]["instrument"]["broker_symbol"] == "A.US"

    def test_detect_endpoint_returns_the_full_summary_shape(self, client, monkeypatch):
        """Case 8 of the plan: the API must expose `complete` alongside the
        counts, not just a bare list — a caller (or the UI) that only reads
        `actions`/`created` has no way to tell a real zero from a partial scan."""
        from app.models import Position, Source

        instrument = Instrument(broker_symbol="APLD.US", provider_symbol="APLD", currency="USD", country="US")
        _seed([instrument])
        session = next(app.dependency_overrides[get_db]())
        try:
            session.add(Position(instrument_id=instrument.id, source=Source.IMPORT, quantity=1, avg_price=10.0))
            session.commit()
        finally:
            session.close()

        event = SplitEvent(effective_date=date(2022, 4, 12), numerator=1, denominator=6)
        av = FakeSplitsProvider({"APLD": [event]}, provider_name="alpha_vantage")
        polygon = FakeSplitsProvider({"APLD": [event]}, provider_name="polygon")
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon)

        response = client.post("/api/corporate-actions/detect")

        assert response.status_code == 200
        body = response.json()
        assert body["complete"] is True
        assert body["created"] == 1
        assert body["checked"] == 1
        assert body["verified_cross_source"] == 1
        assert len(body["actions"]) == 1
        assert body["actions"][0]["source"] in ("alpha_vantage", "polygon")
        assert body["actions"][0]["confidence"] == "verified_cross_source"


class TestComputeCoverageSummary:
    """`compute_coverage_summary` — the read-only, no-provider-calls
    snapshot backing Phase 4's "Couverture automatique" section. Never
    calls a provider itself; every scenario here first runs `detect_splits`
    (with fake providers) to produce realistic persisted state, then checks
    what the summary reads back from it. See DEVLOG "Step 3u.57"."""

    def test_excluded_and_unchecked_instrument_counts(self, db, monkeypatch):
        no_symbol = Instrument(broker_symbol="MINTOS-CORE-P2P", category="P2P", currency="EUR")
        db.add(no_symbol)
        db.flush()
        _held(db, no_symbol)
        checked = _instrument(db, "AAPL.US")
        _held(db, checked)
        unchecked = _instrument(db, "NKE.US")
        _held(db, unchecked)
        db.commit()

        _patch_providers(monkeypatch)  # all null
        detect_splits(db, instrument_ids=[checked.id])  # only AAPL gets checked

        summary = compute_coverage_summary(db)

        assert summary.eligible_instruments == 2  # AAPL + NKE, not the P2P aggregate
        assert summary.excluded_instruments == 1
        assert summary.checked_instruments == 1
        assert summary.unchecked_instruments == 1

    def test_verified_event_counts_as_an_event_not_an_instrument(self, db, monkeypatch):
        """BIVI.US-shaped case: one instrument, several distinct verified
        events — the summary must count events, never conflate with the
        single instrument they both belong to."""
        instrument = _instrument(db, "BIVI.US")
        _held(db, instrument)
        db.commit()

        first = SplitEvent(effective_date=date(2019, 11, 22), numerator=1, denominator=125)
        second = SplitEvent(effective_date=date(2024, 8, 6), numerator=1, denominator=10)
        av = FakeSplitsProvider({"BIVI": [first, second]}, provider_name="alpha_vantage")
        polygon = FakeSplitsProvider({"BIVI": [first, second]}, provider_name="polygon")
        _patch_providers(monkeypatch, alpha_vantage=av, polygon=polygon)

        detect_splits(db)
        summary = compute_coverage_summary(db)

        assert summary.verified_cross_source_events == 2
        assert summary.checked_instruments == 1

    def test_single_source_candidate_stays_outstanding_until_promoted(self, db, monkeypatch):
        instrument = _instrument(db, "NKE.US")
        _held(db, instrument)
        db.commit()

        av = FakeSplitsProvider(
            {"NKE": [SplitEvent(effective_date=date(2012, 12, 24), numerator=2, denominator=1)]},
            provider_name="alpha_vantage",
        )
        _patch_providers(monkeypatch, alpha_vantage=av)
        detect_splits(db)

        before = compute_coverage_summary(db)
        assert before.candidate_single_source_events == 1

        candidate = db.query(ProviderCorporateActionCandidate).filter(
            ProviderCorporateActionCandidate.instrument_id == instrument.id,
            ProviderCorporateActionCandidate.provider == "alpha_vantage",
        ).one()
        promote_candidate(db, candidate.id)

        after = compute_coverage_summary(db)
        assert after.candidate_single_source_events == 0  # promoted — no longer outstanding
        assert after.verified_cross_source_events == 0  # promotion isn't a cross-source event either

    def test_a_candidate_row_with_no_real_split_ratio_is_skipped_not_crashed_on(self, db):
        """Real bug found live 2026-09-08: a `ProviderCorporateActionCandidate`
        row with `event_type=None` (a provider-reported ratio that isn't
        actually a split, e.g. 1:1 — `detect_splits` itself never merges
        these either) made `list_outstanding_candidates` build a group with
        no `action_type` at all, which crashed the `/outstanding` endpoint's
        response validation (`action_type: str`, not `str | None`). Must be
        skipped the same way `detect_splits` already skips it when
        building `observations`, not merged into a broken group."""
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.add(
            ProviderCorporateActionCandidate(
                instrument_id=instrument.id,
                provider="alpha_vantage",
                provider_status="ok",
                event_date=date(2007, 10, 1),
                event_type=None,
                numerator=1.0,
                denominator=1.0,
            )
        )
        db.commit()

        outstanding = list_outstanding_candidates(db)  # must not raise
        assert outstanding == []

        summary = compute_coverage_summary(db)
        assert summary.candidate_single_source_events == 0

    def test_cross_scan_agreement_is_retroactively_applied_not_left_outstanding(self, db, monkeypatch):
        """Real gap found live 2026-09-08: `detect_splits` only merges
        observations gathered within *one* scan — if Alpha Vantage found an
        event on one day's run and Polygon found the identical event on a
        *different* day's run (each scan seeing only one of the two), the
        two observations sat as genuine 2-source agreement that no single
        scan ever noticed, showing as an unconfirmed candidate forever.
        `list_outstanding_candidates` must recognize this across scans and
        apply the event, not just re-report it as still outstanding."""
        instrument = _instrument(db, "AAPL.US")
        _held(db, instrument)
        db.commit()

        event = SplitEvent(effective_date=date(2020, 8, 31), numerator=4, denominator=1)

        # Day 1: only Alpha Vantage sees it (Polygon rate-limited that day).
        av = FakeSplitsProvider({"AAPL": [event]}, provider_name="alpha_vantage")
        _patch_providers(monkeypatch, alpha_vantage=av)
        detect_splits(db)
        assert db.query(CorporateAction).count() == 0  # single-source only so far

        # Day 2: only Polygon sees it (a separate scan, Alpha Vantage skipped
        # this time — e.g. already recently-checked).
        polygon = FakeSplitsProvider({"AAPL": [event]}, provider_name="polygon")
        _patch_providers(monkeypatch, polygon=polygon)
        detect_splits(db, instrument_ids=[instrument.id], force=True)
        # detect_splits itself still only sees Polygon's own observation this
        # run — genuinely single-source *from its own point of view* — so it
        # still doesn't auto-apply anything by itself.
        assert db.query(CorporateAction).count() == 0

        outstanding = list_outstanding_candidates(db)
        assert outstanding == []  # applied, not left dangling as "outstanding"

        action = db.query(CorporateAction).one()
        assert action.confidence == CorporateActionConfidence.VERIFIED_CROSS_SOURCE
        assert {s["provider"] for s in action.corroborating_sources} == {"alpha_vantage", "polygon"}

        summary = compute_coverage_summary(db)
        assert summary.verified_cross_source_events == 1
        assert summary.candidate_single_source_events == 0
