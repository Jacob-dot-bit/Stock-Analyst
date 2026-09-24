"""Stock splits and reverse splits — descriptive detection, read-time adjustment.

See DEVLOG "Decision 3u.30" for the full audit this feature is built on. Two
findings drive every choice here:

**XTB never reports a split** (checked against every raw transaction `Type`
value in the real portfolio) — the app has no importer signal to rely on, so
splits are detected from a price provider (see `detect_splits`) or entered
by hand. Originally Yahoo; swapped to FMP (DEVLOG "Decision 3u.34") after
Yahoo's real-portfolio scan proved to rate-limit inconsistently — a raw
single-symbol check could return `200` while the actual multi-instrument
scan still hit `429` on the very first instrument.

**No price provider can be trusted to deliver split-adjusted history
uniformly.** The same provider (twelvedata) served already-adjusted history
for two real splits (NVDA 10:1, GOOGL 20:1) but raw, unadjusted history for a
third (APLD's real 1-for-6 reverse split, 2022-04-12) — same source, opposite
behaviour depending on the instrument. `detect_price_history_status` checks
this empirically per instrument rather than assuming either way.

**`PriceBar` and `Lot` are never mutated.** Same principle already applied to
imported transactions (`app/models.py`'s module docstring): raw data stays
raw and auditable. Every consumer that needs a split-aware quantity or price
calls through `cumulative_quantity_factor`/`cumulative_price_factor` instead
of reading `Lot.quantity`/`PriceBar.close` directly — see DEVLOG for the full
list of call sites this was threaded into.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AppMetadata,
    CorporateAction,
    CorporateActionConfidence,
    CorporateActionResumeRun,
    CorporateActionType,
    FmpSplitsStatus,
    Instrument,
    PriceBar,
    PriceHistoryStatus,
    ProviderCorporateActionCandidate,
    ProviderCorporateActionCandidateStatus,
    ScreenerCandidate,
    WatchlistItem,
)
from app.models import Position as PositionModel
from app.prices.provider_usage import record_bytes, record_usage
from app.providers.base import InstrumentRef, PlanLimited, ProviderUnavailable, RateLimited, SplitEvent, SymbolNotFound
from app.providers.registry import (
    get_alpha_vantage_provider,
    get_eodhd_provider,
    get_fmp_provider,
    get_polygon_provider,
)

#: How close the actual close-to-close ratio around effective_date must be to
#: the expected split ratio to call it a confirmed RAW (unadjusted) series.
#: Wide on purpose — real markets move on a split date too, this only needs
#: to distinguish "roughly matches the split" from "no jump at all".
_RATIO_MATCH_TOLERANCE = 0.35

#: How long a bulk `detect_splits()` answer for one instrument stays valid
#: before it's worth re-asking. The splits endpoints this app calls (FMP,
#: EODHD) return full unbounded history with no server-side date filter, so
#: re-scanning the same ~47 instruments on every click re-downloads their
#: entire history every time — this is what actually drained FMP's
#: 500MB/30-day bandwidth cap, a quota its own 250 req/day counter never
#: saw. `detect_one` (a deliberate, low-volume, user-triggered single check)
#: is deliberately exempt — only the bulk scan is gated. See DEVLOG
#: "Decision 3u.41".
CORPORATE_ACTIONS_RECHECK_DAYS = 7

#: How many days apart two providers' reported dates for what is otherwise
#: the same event may be before they're treated as two different events
#: rather than one, cross-source-corroborated one. Splits/reverse-splits
#: occasionally get reported against the ex-date vs. the effective date —
#: a few days' slack absorbs that without merging genuinely distinct,
#: months-or-years-apart events on the same instrument. See DEVLOG
#: "Decision 3u.41".
CROSS_SOURCE_DATE_TOLERANCE_DAYS = 3

#: How far apart two providers' numerator/denominator ratios (as
#: numerator/denominator, "economic factor") may be, relative to their own
#: size, before they're treated as a genuine disagreement rather than the
#: same event expressed as textually different but economically equivalent
#: fractions — e.g. GOOGL's 999/500 (≈1.998) and 1033/517 (≈1.998).
ECONOMIC_FACTOR_RELATIVE_TOLERANCE = 0.005

#: Cross-source providers that always count toward the 2-of-3 agreement
#: vote. FMP counts too, but only once `AppMetadata.fmp_splits_status ==
#: "active"` — see `_classify_group`. EODHD is never in this set: it stays
#: a targeted, on-demand-only source (`detect_one`), never part of the
#: automatic cross-source engine.
_ALWAYS_ACTIVE_PROVIDERS = {"alpha_vantage", "polygon"}


def detect_price_history_status(
    db: Session, instrument_id: int, effective_date: date, ratio_numerator: float, ratio_denominator: float
) -> tuple[str, float | None]:
    """Compares the last cached close before `effective_date` to the first
    on/after it. A ratio close to the split's own ratio means the stored
    history is raw and needs local correction; a ratio close to 1 means the
    provider already adjusted it — never correct that again, or NVDA/GOOGL-
    like series would be double-adjusted. Returns (status, detected_ratio).
    """
    before = db.execute(
        select(PriceBar)
        .where(PriceBar.instrument_id == instrument_id, PriceBar.bar_date < effective_date)
        .order_by(PriceBar.bar_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    after = db.execute(
        select(PriceBar)
        .where(PriceBar.instrument_id == instrument_id, PriceBar.bar_date >= effective_date)
        .order_by(PriceBar.bar_date.asc())
        .limit(1)
    ).scalar_one_or_none()

    if before is None or after is None or not before.close or not after.close:
        return PriceHistoryStatus.NOT_APPLICABLE, None

    actual_ratio = after.close / before.close
    expected_ratio = ratio_denominator / ratio_numerator  # post-split price / pre-split price

    if abs(actual_ratio - expected_ratio) <= _RATIO_MATCH_TOLERANCE * expected_ratio:
        return PriceHistoryStatus.RAW, actual_ratio
    if abs(actual_ratio - 1.0) <= _RATIO_MATCH_TOLERANCE:
        return PriceHistoryStatus.ALREADY_ADJUSTED, actual_ratio
    return PriceHistoryStatus.UNKNOWN, actual_ratio


def load_actions_by_instrument(db: Session, instrument_ids: list[int]) -> dict[int, list[CorporateAction]]:
    """One query for every `CorporateAction` on the given instruments —
    for consumers that replay many lots/bars over many days (`history_service`,
    `scoring/service.py`), so the factor lookup below never runs a query per
    (instrument, day) pair. Matches this codebase's existing batch-first
    convention (see `history_service.py`'s own module docstring)."""
    if not instrument_ids:
        return {}
    result: dict[int, list[CorporateAction]] = {i: [] for i in instrument_ids}
    for action in db.execute(
        select(CorporateAction).where(CorporateAction.instrument_id.in_(instrument_ids))
    ).scalars():
        result.setdefault(action.instrument_id, []).append(action)
    return result


def quantity_factor_from(actions: list[CorporateAction], reference_date: date) -> float:
    """What a real share count as of `reference_date` (e.g. a lot's
    `opened_at`) has grown/shrunk to today, restated on today's share-count
    basis — the product of every later split's (numerator/denominator).
    Depends only on `reference_date`, not on which day a replay is currently
    looking at: once a split has happened, it has happened for the rest of
    that holding's life. Pure function over a preloaded action list — see
    `load_actions_by_instrument` for batch consumers, `cumulative_quantity_factor`
    for a single ad-hoc lookup.
    """
    factor = 1.0
    for action in actions:
        if action.effective_date > reference_date:
            factor *= action.ratio_numerator / action.ratio_denominator
    return factor


def price_factor_from(actions: list[CorporateAction], bar_date: date) -> float:
    """The inverse of `quantity_factor_from`, applied to a raw price instead
    of a raw quantity, and only for splits whose stored price history was
    confirmed RAW — an ALREADY_ADJUSTED series must never be corrected
    again, that is exactly the double-adjustment this status exists to
    prevent."""
    factor = 1.0
    for action in actions:
        if action.effective_date > bar_date and action.price_history_status == PriceHistoryStatus.RAW:
            factor *= action.ratio_denominator / action.ratio_numerator
    return factor


def cumulative_quantity_factor(db: Session, instrument_id: int, reference_date: date) -> float:
    """Single-instrument convenience wrapper over `quantity_factor_from` —
    one query, for call sites that only ever need one instrument at a time
    (e.g. a single price-chart request). Batch replays should use
    `load_actions_by_instrument` once and call `quantity_factor_from` in
    their loop instead, to avoid a query per lookup."""
    actions = list(
        db.execute(select(CorporateAction).where(CorporateAction.instrument_id == instrument_id)).scalars()
    )
    return quantity_factor_from(actions, reference_date)


def cumulative_price_factor(db: Session, instrument_id: int, bar_date: date) -> float:
    """Single-instrument convenience wrapper over `price_factor_from` — see
    `cumulative_quantity_factor`'s docstring for when to prefer the batch
    path instead."""
    actions = list(
        db.execute(select(CorporateAction).where(CorporateAction.instrument_id == instrument_id)).scalars()
    )
    return price_factor_from(actions, bar_date)


def create_corporate_action(
    db: Session,
    instrument_id: int,
    action_type: str,
    effective_date: date,
    ratio_numerator: float,
    ratio_denominator: float,
    source: str,
    source_reference: str | None = None,
    raw_payload: dict | None = None,
    confidence: str = CorporateActionConfidence.MANUAL,
    corroborating_sources: list[dict] | None = None,
) -> CorporateAction:
    status, detected_ratio = detect_price_history_status(
        db, instrument_id, effective_date, ratio_numerator, ratio_denominator
    )
    action = CorporateAction(
        instrument_id=instrument_id,
        action_type=action_type,
        effective_date=effective_date,
        ratio_numerator=ratio_numerator,
        ratio_denominator=ratio_denominator,
        source=source,
        source_reference=source_reference,
        raw_payload=raw_payload,
        price_history_status=status,
        detected_price_ratio=detected_ratio,
        confidence=confidence,
        corroborating_sources=corroborating_sources,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


@dataclass
class DetectionSummary:
    """Result of one `detect_splits` run. `complete` is the field that
    matters most to any caller: it is only ever `true` when every eligible
    instrument was checked with a usable answer or explicitly, displayably
    excluded (no provider symbol) — never when a rate limit cut the scan
    short (`not_checked > 0`), and never when the provider structurally
    couldn't answer for one or more instruments (`failed > 0`). That second
    condition was added after swapping the source to FMP (DEVLOG "Decision
    3u.34"): Yahoo's only real failure mode was an all-or-nothing rate
    limit, so `not_checked == 0` alone was a safe proxy for "the whole
    portfolio was actually checked". FMP's failure mode is per-symbol
    structural coverage gaps instead (small-caps gated behind a paid plan,
    non-US symbols outright) — a real run against the ~47-instrument
    portfolio hit `failed: 38, not_checked: 0`, which the old rule would
    have called `complete: true` even though 38 of 47 instruments never
    got a real answer. Without `complete` accounting for both, `created ==
    0` (or, just as misleadingly, a nonzero `found` with a false sense that
    nothing else remains) is ambiguous between "checked everything, this is
    the real answer" and "the provider couldn't reach most of the
    portfolio".
    """

    candidates: int  # every tracked (held/watched/screened) instrument, before any filtering
    checked: int  # instrument attempted this round and at least one provider answered
    found: int  # distinct, cross-source-merged split/reverse-split events found across all checked instruments
    created: int  # of `found`, how many were new, auto-verified, and got persisted
    already_known: int  # of `found`, how many were already recorded (not duplicated)
    no_events: int  # checked, no provider reported any split event at all
    rate_limited: int  # instrument where every provider that could serve it was rate-limited
    not_checked: int  # never attempted at all — always 0 today; kept for API stability
    failed: int  # every provider that could serve this instrument answered with a structural error
    skipped: int  # excluded before ever calling a provider — no provider symbol to check
    recently_checked: int = 0  # skipped: already checked within CORPORATE_ACTIONS_RECHECK_DAYS, force=False
    #: Breakdown of `found` by cross-source merge classification (DEVLOG
    #: "Decision 3u.41") — only `verified_three_sources`/`verified_cross_source`
    #: ever contribute to `created`; the rest stay visible only as
    #: `ProviderCorporateActionCandidate` rows.
    verified_three_sources: int = 0
    verified_cross_source: int = 0
    candidate_single_source: int = 0
    provider_conflict: int = 0
    suspect_ticker_reuse: int = 0
    complete: bool = True
    actions: list[CorporateAction] = field(default_factory=list)


def _all_tracked_instruments(db: Session) -> list[Instrument]:
    """Every held, watchlisted, or screened instrument, regardless of
    whether it has a provider symbol — the same held+watchlist+screener
    union `routers/prices.py` refreshes. Symbol-less instruments are
    filtered by the caller, which counts them as `skipped` rather than
    silently dropping them from the candidate count."""
    held = select(Instrument.id).join(PositionModel, PositionModel.instrument_id == Instrument.id)
    watched = select(Instrument.id).join(WatchlistItem, WatchlistItem.instrument_id == Instrument.id)
    screened = select(Instrument.id).join(ScreenerCandidate, ScreenerCandidate.instrument_id == Instrument.id)
    ids = {row[0] for row in db.execute(held)} | {row[0] for row in db.execute(watched)} | {
        row[0] for row in db.execute(screened)
    }
    if not ids:
        return []
    return list(db.execute(select(Instrument).where(Instrument.id.in_(ids))).scalars())


@dataclass
class CoverageSummary:
    """A read-only, no-provider-calls snapshot of automatic corporate-action
    coverage — safe to fetch on every page load, unlike `DetectionSummary`
    (which only exists as the result of an actual scan). Backs Phase 4's
    "Couverture automatique" section (DEVLOG "Decision 3u.41"'s frontend
    follow-up). Distinguishes **instruments** from **events** throughout —
    one instrument can carry several corporate-action events (see BIVI.US's
    three separate reverse splits), so a count of one must never be
    presented as if it were the other.
    """

    eligible_instruments: int  # tracked instruments with a provider symbol to check at all
    excluded_instruments: int  # tracked but no provider symbol (P2P, Amundi ESR, unmapped, etc.) — not a problem
    checked_instruments: int  # eligible instruments with at least one recorded check (any provider, any outcome)
    unchecked_instruments: int  # eligible but never checked yet
    #: Already-applied events, straight from `CorporateAction.confidence` —
    #: exact, not recomputed.
    verified_three_sources_events: int
    verified_cross_source_events: int
    #: Still-outstanding candidate events, recomputed by re-running the same
    #: merge/classify engine `detect_splits` uses over already-persisted
    #: `ProviderCorporateActionCandidate` rows (no provider calls) — a group
    #: already promoted into a `CorporateAction` is excluded, since it is no
    #: longer "outstanding".
    candidate_single_source_events: int
    provider_conflict_events: int
    suspect_ticker_reuse_events: int


@dataclass
class OutstandingCandidate:
    """One still-outstanding (never auto-applied, never manually promoted)
    cross-source-merged event — the actual rows behind
    `CoverageSummary.candidate_single_source_events`/`provider_conflict_events`/
    `suspect_ticker_reuse_events`, for the UI's "Candidats à confirmer"
    list. Read-only in Phase 4: promoting one still goes through the
    existing raw-candidate `POST .../candidates/{id}/promote` (unchanged),
    not through this merged shape."""

    instrument_id: int
    effective_date: date
    action_type: str
    numerator: float
    denominator: float
    confidence: str
    providers: list[str]


def list_outstanding_candidates(db: Session) -> list[OutstandingCandidate]:
    """Re-runs `detect_splits`'s merge/classify engine over already-
    persisted `ProviderCorporateActionCandidate` rows — no provider calls,
    no quota spent. A group already applied or manually promoted into a
    `CorporateAction` is excluded, since it is no longer "outstanding".
    Shared by `compute_coverage_summary` (counts only) and
    `GET /api/corporate-actions/outstanding` (full detail).

    **Real gap found and closed while building this** (DEVLOG "Step
    3u.57"): `detect_splits` only ever merges observations gathered within
    *one* scan call — if Alpha Vantage confirmed an event on one day's run
    and Polygon confirmed the very same event on a *different* day's run
    (each scan seeing only one of the two, e.g. because the other provider
    was rate-limited or the instrument wasn't due for a recheck that day),
    the two observations sat in `ProviderCorporateActionCandidate` as
    genuine 2-source agreement that no single scan ever noticed — a real,
    silent cross-source-verified event stuck showing as unconfirmed. This
    function recomputes classification over *all* persisted observations
    regardless of which scan produced them, so it catches this; when a
    group now qualifies as verified but isn't in `CorporateAction` yet, it
    is applied here on the spot (the same write `detect_splits` itself
    would have done, had it seen both observations together) rather than
    displayed with a confusing "verified, please confirm" contradiction.
    """
    app_metadata = db.query(AppMetadata).first()
    fmp_active = app_metadata is not None and app_metadata.fmp_splits_status == FmpSplitsStatus.ACTIVE
    existing = {(a.instrument_id, a.effective_date, a.action_type) for a in db.execute(select(CorporateAction)).scalars()}

    rows = db.execute(
        select(ProviderCorporateActionCandidate).where(ProviderCorporateActionCandidate.event_date.is_not(None))
    ).scalars()
    by_instrument: dict[int, list[tuple[str, SplitEvent, str]]] = defaultdict(list)
    for row in rows:
        # `event_type` is `None` when the reported ratio isn't a real split
        # or reverse split (e.g. 1:1) — `detect_splits` itself never feeds
        # these into a merge either (see its own `if action_type is not
        # None` guard); skip them here the same way, rather than crashing
        # on a group with no real `action_type`.
        if row.event_type is None:
            continue
        by_instrument[row.instrument_id].append(
            (row.provider, SplitEvent(row.event_date, row.numerator, row.denominator), row.event_type)
        )

    outstanding: list[OutstandingCandidate] = []
    for instrument_id, observations in by_instrument.items():
        groups = _merge_events_for_instrument(observations)
        all_dates = [g.effective_date for g in groups]
        for group in groups:
            key = (instrument_id, group.effective_date, group.action_type)
            if key in existing:
                continue  # already applied or manually promoted — not outstanding anymore
            other_dates = [d for d in all_dates if d != group.effective_date]
            confidence, active_providers = _classify_group(group, fmp_active, other_dates)

            if confidence in (CorporateActionConfidence.VERIFIED_CROSS_SOURCE, CorporateActionConfidence.VERIFIED_THREE_SOURCES):
                # Retroactive cross-source agreement across separate scans —
                # apply it now, exactly as `detect_splits` would have if it
                # had seen both observations in the same pass. Not returned
                # as "outstanding": it no longer is.
                primary_provider = active_providers[0] if active_providers else sorted({p for p, _ in group.members})[0]
                create_corporate_action(
                    db,
                    instrument_id=instrument_id,
                    action_type=group.action_type,
                    effective_date=group.effective_date,
                    ratio_numerator=group.numerator,
                    ratio_denominator=group.denominator,
                    source=primary_provider,
                    confidence=confidence,
                    corroborating_sources=[
                        {
                            "provider": provider,
                            "event_date": event.effective_date.isoformat(),
                            "numerator": event.numerator,
                            "denominator": event.denominator,
                        }
                        for provider, event in group.members
                    ],
                )
                existing.add(key)
                continue

            outstanding.append(
                OutstandingCandidate(
                    instrument_id=instrument_id,
                    effective_date=group.effective_date,
                    action_type=group.action_type,
                    numerator=group.numerator,
                    denominator=group.denominator,
                    confidence=confidence,
                    providers=sorted({provider for provider, _ in group.members}),
                )
            )
    db.commit()
    return outstanding


def compute_coverage_summary(db: Session) -> CoverageSummary:
    """See `CoverageSummary`. Never calls a provider, never spends any
    quota — but, via `list_outstanding_candidates`, may retroactively apply
    a `CorporateAction` for a group that has genuinely achieved cross-
    source agreement across separate past scans (see that function's
    docstring). Called first, so its writes are reflected in the applied
    counts read below."""
    outstanding = list_outstanding_candidates(db)

    all_tracked = _all_tracked_instruments(db)
    eligible = [i for i in all_tracked if i.provider_symbol]
    checked = [i for i in eligible if i.corporate_actions_checked_at is not None]

    applied_counts = dict(
        db.execute(select(CorporateAction.confidence, func.count()).group_by(CorporateAction.confidence)).all()
    )

    def _count(confidence: str) -> int:
        return sum(1 for o in outstanding if o.confidence == confidence)

    return CoverageSummary(
        eligible_instruments=len(eligible),
        excluded_instruments=len(all_tracked) - len(eligible),
        checked_instruments=len(checked),
        unchecked_instruments=len(eligible) - len(checked),
        verified_three_sources_events=applied_counts.get(CorporateActionConfidence.VERIFIED_THREE_SOURCES, 0),
        verified_cross_source_events=applied_counts.get(CorporateActionConfidence.VERIFIED_CROSS_SOURCE, 0),
        candidate_single_source_events=_count(CorporateActionConfidence.CANDIDATE_SINGLE_SOURCE),
        provider_conflict_events=_count(CorporateActionConfidence.PROVIDER_CONFLICT),
        suspect_ticker_reuse_events=_count(CorporateActionConfidence.SUSPECT_TICKER_REUSE),
    )


#: Tickers useful to prioritize in a targeted resume — already understood
#: from the Phase 2 spike (a real historical event confirmed by hand), so a
#: fresh single-pass cross-source check against them is the fastest way to
#: confirm the merge/classify engine end-to-end on a known case rather than
#: an arbitrary one. Matched against the bare (pre-suffix) provider symbol.
REFERENCE_SYMBOLS_FOR_RESUME = ("APLD", "AAPL", "NVDA", "GOOGL", "NKE")


def list_incomplete_instrument_ids(
    db: Session,
    provider_name: str = "alpha_vantage",
    limit: int | None = None,
    reference_symbols: tuple[str, ...] = REFERENCE_SYMBOLS_FOR_RESUME,
) -> list[int]:
    """Eligible instruments this app has *never* gotten a real answer from
    `provider_name` for — the targeted-resume list for a source with a tight
    daily quota (Alpha Vantage's free tier: ~25/day), so a `force=True`
    recheck can spend that quota on what's actually missing instead of
    blindly re-scanning the whole portfolio and re-hitting instruments the
    source already answered days ago. See DEVLOG "Decision 3u.41".

    "Never gotten a real answer" means no `ProviderCorporateActionCandidate`
    row with `provider_status == "ok"` exists for `(instrument, provider)` —
    a rate-limited attempt leaves no such row, so it reads identically to
    never having been asked, which is exactly the point: both need a real
    retry, and a stale "ok" from days ago (even if this instrument's most
    recent attempt happened to be rate-limited) correctly counts as already
    answered — the point of this list is coverage, not freshness (the
    7-day `CORPORATE_ACTIONS_RECHECK_DAYS` cadence already handles
    freshness for instruments every source has already answered).

    Ordered by priority, each bucket sorted by instrument id for
    determinism: (1) instruments where *another* source already found a
    real event, waiting on `provider_name` to corroborate or refute it —
    the case a genuine `verified_cross_source` classification is one call
    away from; (2) `reference_symbols`, already-understood cases useful for
    end-to-end validation; (3) everything else still incomplete. `limit`
    truncates the combined, ordered list to fit one day's quota.
    """
    eligible_ids = {i.id for i in _all_tracked_instruments(db) if i.provider_symbol}
    if not eligible_ids:
        return []

    has_ok = {
        row[0]
        for row in db.execute(
            select(ProviderCorporateActionCandidate.instrument_id)
            .where(
                ProviderCorporateActionCandidate.provider == provider_name,
                ProviderCorporateActionCandidate.provider_status == ProviderCorporateActionCandidateStatus.OK,
            )
            .distinct()
        )
    }
    incomplete_ids = sorted(eligible_ids - has_ok)
    if not incomplete_ids:
        return []

    has_other_real_event = {
        row[0]
        for row in db.execute(
            select(ProviderCorporateActionCandidate.instrument_id)
            .where(
                ProviderCorporateActionCandidate.provider != provider_name,
                ProviderCorporateActionCandidate.provider_status == ProviderCorporateActionCandidateStatus.OK,
                ProviderCorporateActionCandidate.event_date.is_not(None),
            )
            .distinct()
        )
    }

    reference_ids = {
        i.id
        for i in db.execute(select(Instrument).where(Instrument.id.in_(incomplete_ids))).scalars()
        if i.provider_symbol and i.provider_symbol.split(".")[0] in reference_symbols
    }

    priority_1 = [iid for iid in incomplete_ids if iid in has_other_real_event]
    priority_2 = [iid for iid in incomplete_ids if iid in reference_ids and iid not in has_other_real_event]
    priority_3 = [iid for iid in incomplete_ids if iid not in has_other_real_event and iid not in reference_ids]

    ordered = priority_1 + priority_2 + priority_3
    return ordered[:limit] if limit is not None else ordered


#: Deliberate margin under Alpha Vantage's real ~25/day free quota — leaves
#: headroom for an ad-hoc manual check, a diagnostic, or a retest the same
#: day without the scheduled job immediately re-triggering that day's rate
#: limit. See DEVLOG "Decision 3u.41".
ALPHA_VANTAGE_RESUME_DAILY_LIMIT = 20


def resume_incomplete_scan(
    db: Session, provider_name: str = "alpha_vantage", limit: int = ALPHA_VANTAGE_RESUME_DAILY_LIMIT
) -> CorporateActionResumeRun:
    """The scheduled targeted-resume job's entry point: targets only the
    instruments `provider_name` has never answered (see
    `list_incomplete_instrument_ids`), reruns the full cross-source
    `detect_splits` on exactly those, and persists a
    `CorporateActionResumeRun` row so "last attempt / result / remaining"
    survives a restart and is queryable without re-deriving it from raw
    candidate rows. See DEVLOG "Decision 3u.41".

    Two cases end the run immediately without calling any provider, each
    recorded with its own `skipped_reason` rather than silently producing
    an all-zero result indistinguishable from "ran and found nothing":
    `AppMetadata.alpha_vantage_resume_enabled` is off (the user paused the
    job, e.g. to save the day's quota for something else), or nothing is
    left incomplete (the job effectively disables itself once this
    provider's coverage gap closes — no external scheduler needs to know
    that separately).
    """
    app_metadata = db.query(AppMetadata).first()
    if app_metadata is None:
        app_metadata = AppMetadata()
        db.add(app_metadata)
        db.flush()

    started_at = datetime.now(UTC)

    if not app_metadata.alpha_vantage_resume_enabled:
        run = CorporateActionResumeRun(
            provider=provider_name,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            skipped_reason="paused",
            remaining_incomplete=len(list_incomplete_instrument_ids(db, provider_name=provider_name)),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    targeted = list_incomplete_instrument_ids(db, provider_name=provider_name, limit=limit)
    if not targeted:
        run = CorporateActionResumeRun(
            provider=provider_name,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            skipped_reason="nothing_incomplete",
            remaining_incomplete=0,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    summary = detect_splits(db, instrument_ids=targeted, force=True)

    run = CorporateActionResumeRun(
        provider=provider_name,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        targeted_instrument_ids=targeted,
        checked=summary.checked,
        rate_limited=summary.rate_limited,
        failed=summary.failed,
        no_events=summary.no_events,
        verified_three_sources=summary.verified_three_sources,
        verified_cross_source=summary.verified_cross_source,
        candidate_single_source=summary.candidate_single_source,
        provider_conflict=summary.provider_conflict,
        suspect_ticker_reuse=summary.suspect_ticker_reuse,
        complete=summary.complete,
        remaining_incomplete=len(list_incomplete_instrument_ids(db, provider_name=provider_name)),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_resume_status(db: Session, provider_name: str = "alpha_vantage") -> tuple[bool, int, CorporateActionResumeRun | None]:
    """`(enabled, remaining_incomplete, last_run)` — what the UI's
    "Vérification automatique multi-sources" status section reads directly,
    without the caller needing to know `AppMetadata`/`CorporateActionResumeRun`
    exist. See DEVLOG "Decision 3u.41"."""
    app_metadata = db.query(AppMetadata).first()
    enabled = app_metadata.alpha_vantage_resume_enabled if app_metadata is not None else True
    remaining = len(list_incomplete_instrument_ids(db, provider_name=provider_name))
    last_run = db.execute(
        select(CorporateActionResumeRun)
        .where(CorporateActionResumeRun.provider == provider_name)
        .order_by(CorporateActionResumeRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return enabled, remaining, last_run


def set_resume_enabled(db: Session, enabled: bool) -> None:
    """Flips the scheduled resume job's pause switch — the backend for the
    UI's "Mettre en pause la reprise automatique" action. See DEVLOG
    "Decision 3u.41"."""
    app_metadata = db.query(AppMetadata).first()
    if app_metadata is None:
        app_metadata = AppMetadata()
        db.add(app_metadata)
    app_metadata.alpha_vantage_resume_enabled = enabled
    db.commit()


#: How far an event has to sit from every *other* real event found for the
#: same instrument in the same scan before it's treated as an isolated
#: outlier rather than a legitimate part of that instrument's own split
#: history. 15 years comfortably clears every real multi-decade blue-chip
#: gap seen in this app's own reference panel (AAPL 1987→2000 is the
#: widest at 13 years) while still catching the reference case this rule
#: exists for: Polygon's isolated APLD `800:1` reverse split from 2003,
#: ~19 years before APLD's real, corroborated 2022 `1:6` — the only other
#: event ever found for that instrument.
#:
#: A first design of this check compared an event's date to *this user's
#: own* earliest transaction/lot for the instrument instead — live-verified
#: against the real portfolio and found to misclassify the vast majority of
#: real, legitimate history (56 of 68 real events found, including AAPL's
#: and NVDA's genuine decades-old splits) as suspect, since a split
#: obviously predates whenever *this investor* happened to buy in. That
#: signal answered "did I own this before the split" rather than "does this
#: event belong to the same company as everything else found for this
#: ticker" — replaced by this cross-event-isolation check. See DEVLOG
#: "Decision 3u.41".
SUSPECT_ISOLATION_DAYS = 365 * 15


def _upsert_candidate(
    db: Session,
    instrument_id: int,
    provider: str,
    provider_status: str,
    event_date: date | None = None,
    event_type: str | None = None,
    numerator: float | None = None,
    denominator: float | None = None,
    raw_payload: dict | None = None,
) -> None:
    """Records one provider's raw observation for one instrument — every
    `fetch_splits` outcome becomes exactly one row here, including empty
    and error outcomes (`provider_status`), not just real events. Upserts
    on `(instrument_id, provider, event_date)` — for a real event this
    matches `ProviderCorporateActionCandidate`'s own unique constraint; for
    a status-only outcome (`event_date=None`), it keeps exactly one "latest
    check" row per (instrument, provider) instead of accumulating a new row
    every `CORPORATE_ACTIONS_RECHECK_DAYS`. See DEVLOG "Decision 3u.41"."""
    query = select(ProviderCorporateActionCandidate).where(
        ProviderCorporateActionCandidate.instrument_id == instrument_id,
        ProviderCorporateActionCandidate.provider == provider,
    )
    query = query.where(
        ProviderCorporateActionCandidate.event_date.is_(None)
        if event_date is None
        else ProviderCorporateActionCandidate.event_date == event_date
    )
    row = db.execute(query).scalar_one_or_none()
    if row is None:
        row = ProviderCorporateActionCandidate(instrument_id=instrument_id, provider=provider, event_date=event_date)
        db.add(row)
    row.event_type = event_type
    row.numerator = numerator
    row.denominator = denominator
    row.economic_factor = numerator / denominator if numerator is not None and denominator else None
    row.raw_payload = raw_payload
    row.provider_status = provider_status
    row.retrieved_at = datetime.now(UTC)


@dataclass
class _MergedGroup:
    """One real corporate-action event, as agreed on by every provider
    whose reported date fell within `CROSS_SOURCE_DATE_TOLERANCE_DAYS` of
    each other. `effective_date`/`action_type`/`numerator`/`denominator`
    are taken from whichever contributing provider sorts first
    alphabetically — arbitrary but deterministic, and harmless: every
    member's ratio already agreed within `ECONOMIC_FACTOR_RELATIVE_TOLERANCE`
    by the time a group reaches this shape (see `_classify_group`, which
    reclassifies as `provider_conflict` before this matters otherwise).
    `members` keeps every contributing (provider, event) pair for the
    `corroborating_sources` snapshot and for conflict detection."""

    effective_date: date
    action_type: str
    numerator: float
    denominator: float
    members: list[tuple[str, SplitEvent]]


def _merge_events_for_instrument(
    observations: list[tuple[str, SplitEvent, str]],
) -> list[_MergedGroup]:
    """Groups one instrument's per-provider observations into distinct
    real-world events, purely by date proximity (`CROSS_SOURCE_DATE_TOLERANCE_DAYS`)
    — economic-factor agreement is checked afterward by `_classify_group`,
    not here, so that two providers reporting the *same date* with
    *different* ratios still land in one group and surface as
    `provider_conflict` rather than two silent, unrelated single-source
    candidates."""
    if not observations:
        return []

    ordered = sorted(observations, key=lambda o: o[1].effective_date)
    groups: list[list[tuple[str, SplitEvent, str]]] = []
    for obs in ordered:
        _, event, _ = obs
        for group in groups:
            if any(
                abs((event.effective_date - member_event.effective_date).days) <= CROSS_SOURCE_DATE_TOLERANCE_DAYS
                for _, member_event, _ in group
            ):
                group.append(obs)
                break
        else:
            groups.append([obs])

    merged = []
    for group in groups:
        group_sorted = sorted(group, key=lambda o: o[0])
        _, anchor_event, anchor_type = group_sorted[0]
        merged.append(
            _MergedGroup(
                effective_date=anchor_event.effective_date,
                action_type=anchor_type,
                numerator=anchor_event.numerator,
                denominator=anchor_event.denominator,
                members=[(provider, event) for provider, event, _ in group_sorted],
            )
        )
    return merged


def _classify_group(
    group: _MergedGroup, fmp_active: bool, other_group_dates: list[date]
) -> tuple[str, list[str]]:
    """Classifies one merged event — see `CorporateActionConfidence` for
    what each outcome means and DEVLOG "Decision 3u.41" for the full
    reasoning. Returns `(confidence, active_tier_providers_counted)`;
    the latter is empty whenever the classification isn't one of the two
    auto-applied states.

    Checked in order: an event isolated by more than
    `SUSPECT_ISOLATION_DAYS` from every *other* real event found for this
    same instrument in this same scan — and older than all of them — is
    always suspect, regardless of how many sources repeat it (Polygon's
    isolated APLD 2003 `800:1`, ~19 years before APLD's real 2022 `1:6`, is
    the reference case; never corroborated by another source in practice,
    but the rule holds even if it were). `other_group_dates` empty (this is
    the only event ever found for the instrument) means there is nothing to
    compare against, so this check is skipped — it never fires from a
    single data point alone. Then a genuine ratio disagreement among the
    group's members — same date, different economic factor — is a conflict
    regardless of source count. Only once both of those are ruled out does
    source *count* (among the currently-active tier) decide between
    three-source/cross-source/single-source confidence.
    """
    if other_group_dates:
        nearest_gap_days = min(abs((group.effective_date - other).days) for other in other_group_dates)
        if nearest_gap_days > SUSPECT_ISOLATION_DAYS and all(group.effective_date < other for other in other_group_dates):
            return CorporateActionConfidence.SUSPECT_TICKER_REUSE, []

    factors = [event.numerator / event.denominator for _, event in group.members]
    reference = factors[0]
    if any(abs(f - reference) > ECONOMIC_FACTOR_RELATIVE_TOLERANCE * max(f, reference) for f in factors[1:]):
        return CorporateActionConfidence.PROVIDER_CONFLICT, []

    active_providers = sorted(
        {
            provider
            for provider, _ in group.members
            if provider in _ALWAYS_ACTIVE_PROVIDERS or (provider == "fmp" and fmp_active)
        }
    )
    if len(active_providers) >= 3:
        return CorporateActionConfidence.VERIFIED_THREE_SOURCES, active_providers
    if len(active_providers) == 2:
        return CorporateActionConfidence.VERIFIED_CROSS_SOURCE, active_providers
    return CorporateActionConfidence.CANDIDATE_SINGLE_SOURCE, active_providers


def detect_splits(db: Session, instrument_ids: list[int] | None = None, force: bool = False) -> DetectionSummary:
    """Cross-checks each tracked instrument's split history against Alpha
    Vantage, Polygon, and (while not `degraded`) FMP, merges what they
    report, and auto-creates a `CorporateAction` only for an event at least
    two of the currently-active-tier sources agree on — see
    `_classify_group`/`CorporateActionConfidence`. A single-source finding,
    a genuine cross-source disagreement, or an event isolated by more than
    `SUSPECT_ISOLATION_DAYS` from every other event this same instrument's
    scan found are all recorded as visible `ProviderCorporateActionCandidate`
    rows, never silently dropped and never auto-applied. See DEVLOG
    "Decision 3u.41".

    A `RateLimited` response from one provider no longer aborts the whole
    scan the way the original single-source (FMP-only) version did — it is
    recorded on that provider's candidate rows, and that provider is
    skipped (not called again) for the rest of *this* scan's remaining
    instruments, while the other providers keep contributing normally. A
    `PlanLimited`/`SymbolNotFound`/`ProviderUnavailable` from one provider
    for one instrument is similarly just that provider's absence for that
    instrument, not a whole-instrument failure, as long as another provider
    answers.

    Unless `force=True`, an instrument checked within
    `CORPORATE_ACTIONS_RECHECK_DAYS` is skipped without calling any
    provider at all — counted separately as `recently_checked`, not folded
    into `skipped` (which specifically means "no provider symbol to check
    in the first place"). `detect_one` has no equivalent gate: it is
    already a deliberate, low-volume, single-instrument action, not the
    repeated full-portfolio scan this cadence exists to protect provider
    bandwidth from.
    """
    app_metadata = db.query(AppMetadata).first()
    if app_metadata is None:
        app_metadata = AppMetadata()
        db.add(app_metadata)
        db.flush()
    fmp_active = app_metadata.fmp_splits_status == FmpSplitsStatus.ACTIVE
    fmp_degraded = app_metadata.fmp_splits_status == FmpSplitsStatus.DEGRADED

    providers: list[tuple[str, object]] = [
        ("alpha_vantage", get_alpha_vantage_provider()),
        ("polygon", get_polygon_provider()),
    ]
    if not fmp_degraded:
        # Still called while "recovering" so the readmission panel has
        # fresh data to review — just not counted as a vote (`fmp_active`)
        # until the user promotes it to "active" in Settings.
        providers.append(("fmp", get_fmp_provider()))

    all_tracked = (
        [i for i in _all_tracked_instruments(db) if i.id in set(instrument_ids)]
        if instrument_ids is not None
        else _all_tracked_instruments(db)
    )
    candidates = len(all_tracked)
    eligible = [i for i in all_tracked if i.provider_symbol]
    skipped = candidates - len(eligible)

    recheck_cutoff = datetime.now(UTC) - timedelta(days=CORPORATE_ACTIONS_RECHECK_DAYS)
    if force:
        instruments = eligible
        recently_checked = 0
    else:
        instruments = [
            i for i in eligible if i.corporate_actions_checked_at is None or i.corporate_actions_checked_at < recheck_cutoff
        ]
        recently_checked = len(eligible) - len(instruments)

    existing = {
        (a.instrument_id, a.effective_date, a.action_type)
        for a in db.execute(select(CorporateAction)).scalars()
    }

    checked = found = created_count = already_known = no_events = rate_limited = failed = 0
    verified_three_sources = verified_cross_source = candidate_single_source = 0
    provider_conflict = suspect_ticker_reuse = 0
    actions: list[CorporateAction] = []
    blocked_providers: set[str] = set()

    for instrument in instruments:
        ref = InstrumentRef(
            provider_symbol=instrument.provider_symbol,
            isin=instrument.isin,
            broker_symbol=instrument.broker_symbol,
            name=instrument.name,
            category=instrument.category,
        )

        observations: list[tuple[str, SplitEvent, str]] = []
        any_ok = any_rate_limited = False

        for provider_name, provider in providers:
            if not provider.can_serve(ref):
                _upsert_candidate(db, instrument.id, provider_name, ProviderCorporateActionCandidateStatus.NOT_SUPPORTED)
                continue
            if provider_name in blocked_providers:
                _upsert_candidate(db, instrument.id, provider_name, ProviderCorporateActionCandidateStatus.RATE_LIMITED)
                any_rate_limited = True
                continue
            try:
                events = provider.fetch_splits(
                    ref,
                    date(1970, 1, 1),
                    datetime.now(UTC).date(),
                    on_attempt=lambda name: record_usage(db, name),
                    on_bytes=lambda name, n: record_bytes(db, name, n),
                )
            except RateLimited:
                # Not aborting the whole scan (the original single-source
                # behavior): just this provider, skipped for the rest of
                # this scan's instruments, while the others keep going.
                blocked_providers.add(provider_name)
                _upsert_candidate(db, instrument.id, provider_name, ProviderCorporateActionCandidateStatus.RATE_LIMITED)
                any_rate_limited = True
                continue
            except PlanLimited:
                _upsert_candidate(db, instrument.id, provider_name, ProviderCorporateActionCandidateStatus.PLAN_LIMITED)
                continue
            except (SymbolNotFound, ProviderUnavailable):
                _upsert_candidate(db, instrument.id, provider_name, ProviderCorporateActionCandidateStatus.FAILED)
                continue

            any_ok = True
            if not events:
                _upsert_candidate(db, instrument.id, provider_name, ProviderCorporateActionCandidateStatus.OK)
            for event in events:
                action_type = _classify_ratio(event.numerator, event.denominator)
                _upsert_candidate(
                    db,
                    instrument.id,
                    provider_name,
                    ProviderCorporateActionCandidateStatus.OK,
                    event_date=event.effective_date,
                    event_type=action_type,
                    numerator=event.numerator,
                    denominator=event.denominator,
                    raw_payload={"numerator": event.numerator, "denominator": event.denominator},
                )
                if action_type is not None:
                    observations.append((provider_name, event, action_type))

        if any_ok:
            instrument.corporate_actions_checked_at = datetime.now(UTC)
            checked += 1
        elif any_rate_limited:
            # Deliberately not marked checked: a rate limit is transient —
            # retrying soon (the very next scan) rather than waiting out
            # the recheck window is the right response.
            rate_limited += 1
            continue
        else:
            # Every provider that could serve this instrument answered
            # with a structural, repeatable error — marking it checked
            # avoids re-querying a symbol that will keep failing the same
            # way every time.
            instrument.corporate_actions_checked_at = datetime.now(UTC)
            failed += 1
            continue

        if not observations:
            no_events += 1
            continue

        groups = _merge_events_for_instrument(observations)
        all_group_dates = [g.effective_date for g in groups]
        for group in groups:
            found += 1
            other_group_dates = [d for d in all_group_dates if d != group.effective_date]
            confidence, active_providers = _classify_group(group, fmp_active, other_group_dates)

            if confidence == CorporateActionConfidence.SUSPECT_TICKER_REUSE:
                suspect_ticker_reuse += 1
                continue
            if confidence == CorporateActionConfidence.PROVIDER_CONFLICT:
                provider_conflict += 1
                continue
            if confidence == CorporateActionConfidence.CANDIDATE_SINGLE_SOURCE:
                candidate_single_source += 1
                continue

            if confidence == CorporateActionConfidence.VERIFIED_THREE_SOURCES:
                verified_three_sources += 1
            else:
                verified_cross_source += 1

            key = (instrument.id, group.effective_date, group.action_type)
            if key in existing:
                already_known += 1
                continue

            primary_provider = active_providers[0] if active_providers else sorted({p for p, _ in group.members})[0]
            action = create_corporate_action(
                db,
                instrument_id=instrument.id,
                action_type=group.action_type,
                effective_date=group.effective_date,
                ratio_numerator=group.numerator,
                ratio_denominator=group.denominator,
                source=primary_provider,
                source_reference=instrument.provider_symbol,
                confidence=confidence,
                corroborating_sources=[
                    {
                        "provider": provider,
                        "event_date": event.effective_date.isoformat(),
                        "numerator": event.numerator,
                        "denominator": event.denominator,
                    }
                    for provider, event in group.members
                ],
            )
            existing.add(key)
            created_count += 1
            actions.append(action)

    # Every provider-level rate limit or structural failure is now scoped
    # to that provider, not the whole scan, so nothing is ever left
    # entirely unattempted the way a single-source rate limit used to
    # leave later instruments unreached. Kept in the return shape (always
    # 0 today) for API stability rather than removed outright.
    not_checked = 0

    # create_corporate_action() already committed each new action along the
    # way; this commit is for the corporate_actions_checked_at updates and
    # candidate-row upserts on instruments that had no new action to create
    # (no_events, already-known only, or a structural failure) — otherwise
    # those would be lost.
    db.commit()

    return DetectionSummary(
        candidates=candidates,
        checked=checked,
        found=found,
        created=created_count,
        already_known=already_known,
        no_events=no_events,
        rate_limited=rate_limited,
        not_checked=not_checked,
        failed=failed,
        skipped=skipped,
        recently_checked=recently_checked,
        verified_three_sources=verified_three_sources,
        verified_cross_source=verified_cross_source,
        candidate_single_source=candidate_single_source,
        provider_conflict=provider_conflict,
        suspect_ticker_reuse=suspect_ticker_reuse,
        # `not_checked` is always 0 in the multi-provider engine (a
        # provider-level rate limit no longer aborts the whole scan), so
        # `failed`/`rate_limited` are what's left to distinguish "every
        # attempted instrument got a usable answer from at least one
        # source" from "some instrument got nothing from anyone" — either
        # one means this run's `created`/`found` cannot be read as the full
        # portfolio's real split history yet.
        complete=failed == 0 and rate_limited == 0,
        actions=actions,
    )


def _classify_ratio(numerator: float, denominator: float) -> str | None:
    if numerator > denominator:
        return CorporateActionType.SPLIT
    if numerator < denominator:
        return CorporateActionType.REVERSE_SPLIT
    return None  # a 1-for-1 "split" carries no real information, ignore it


@dataclass
class DetectOneResult:
    """Result of one `detect_one` call — the targeted, single-instrument
    counterpart to `detect_splits`'s bulk scan. `status` is always one of
    "created" | "already_known" | "no_events" | "not_supported" |
    "plan_limited" | "rate_limited" | "failed" — the last four are
    distinct failure shapes, never conflated with "no_events": a failure
    must never read as "confirmed no split". See DEVLOG "Decision 3u.35".
    """

    instrument_id: int
    provider: str
    status: str
    found: int
    created: int
    already_known: int
    actions: list[CorporateAction] = field(default_factory=list)


def detect_one(db: Session, instrument_id: int, provider_name: str) -> DetectOneResult | None:
    """Checks one specific on-demand source for one specific instrument —
    deliberately never part of `detect_splits`'s bulk scan, and never
    triggered automatically from it. Built for the exact case found live:
    FMP returns `PlanLimited` for APLD (a smaller-cap US symbol its free
    plan doesn't cover), but EODHD answers correctly via a different
    endpoint. Only "eodhd" is accepted today — validated by the caller's
    schema (`DetectOneIn.provider: Literal["eodhd"]`), not re-validated
    here. Returns `None` if the instrument doesn't exist, for the router
    to turn into a 404 (same pattern `create_corporate_action_endpoint`
    already uses).
    """
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        return None

    provider = get_eodhd_provider()
    ref = InstrumentRef(
        provider_symbol=instrument.provider_symbol,
        isin=instrument.isin,
        broker_symbol=instrument.broker_symbol,
        name=instrument.name,
        category=instrument.category,
    )

    def _result(status: str) -> DetectOneResult:
        return DetectOneResult(
            instrument_id=instrument_id, provider=provider_name, status=status, found=0, created=0, already_known=0
        )

    try:
        events = provider.fetch_splits(
            ref,
            date(1970, 1, 1),
            datetime.now(UTC).date(),
            on_attempt=lambda name: record_usage(db, name),
            on_bytes=lambda name, n: record_bytes(db, name, n),
        )
    except RateLimited:
        return _result("rate_limited")
    except PlanLimited:
        return _result("plan_limited")
    except SymbolNotFound:
        return _result("not_supported")
    except ProviderUnavailable:
        return _result("failed")

    if not events:
        return _result("no_events")

    existing = {
        (a.instrument_id, a.effective_date, a.action_type)
        for a in db.execute(
            select(CorporateAction).where(CorporateAction.instrument_id == instrument_id)
        ).scalars()
    }

    found = created_count = already_known = 0
    actions: list[CorporateAction] = []
    for event in events:
        action_type = _classify_ratio(event.numerator, event.denominator)
        if action_type is None:
            continue
        found += 1
        key = (instrument_id, event.effective_date, action_type)
        if key in existing:
            already_known += 1
            continue
        action = create_corporate_action(
            db,
            instrument_id=instrument_id,
            action_type=action_type,
            effective_date=event.effective_date,
            ratio_numerator=event.numerator,
            ratio_denominator=event.denominator,
            source=provider_name,
            source_reference=instrument.provider_symbol,
        )
        existing.add(key)
        created_count += 1
        actions.append(action)

    if created_count:
        status = "created"
    elif already_known:
        status = "already_known"
    else:
        status = "no_events"  # every event was a 1:1 no-op ratio — nothing real found

    return DetectOneResult(
        instrument_id=instrument_id,
        provider=provider_name,
        status=status,
        found=found,
        created=created_count,
        already_known=already_known,
        actions=actions,
    )


def promote_candidate(db: Session, candidate_id: int) -> CorporateAction | None:
    """Manually promotes one raw provider observation
    (`ProviderCorporateActionCandidate`) into a real, applied
    `CorporateAction` — the mechanism behind the UI's "Promouvoir" button on
    a `candidate_single_source`/`provider_conflict` row the user has
    reviewed themselves (DEVLOG "Decision 3u.41"). Idempotent: promoting an
    already-applied event a second time returns the existing row rather
    than creating a duplicate. Returns `None` if the candidate doesn't
    exist or carries no real event (a status-only row, e.g. `rate_limited`,
    or an `ok` response that found nothing)."""
    candidate = db.get(ProviderCorporateActionCandidate, candidate_id)
    if candidate is None or candidate.event_date is None or candidate.numerator is None or candidate.denominator is None:
        return None

    action_type = candidate.event_type or _classify_ratio(candidate.numerator, candidate.denominator)
    if action_type is None:
        return None

    existing = db.execute(
        select(CorporateAction).where(
            CorporateAction.instrument_id == candidate.instrument_id,
            CorporateAction.effective_date == candidate.event_date,
            CorporateAction.action_type == action_type,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    return create_corporate_action(
        db,
        instrument_id=candidate.instrument_id,
        action_type=action_type,
        effective_date=candidate.event_date,
        ratio_numerator=candidate.numerator,
        ratio_denominator=candidate.denominator,
        source=candidate.provider,
        raw_payload=candidate.raw_payload,
        confidence=CorporateActionConfidence.MANUAL_PROMOTION,
        corroborating_sources=[
            {
                "provider": candidate.provider,
                "event_date": candidate.event_date.isoformat(),
                "numerator": candidate.numerator,
                "denominator": candidate.denominator,
            }
        ],
    )
