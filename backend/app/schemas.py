"""Pydantic schemas exposed by the API.

The API is language-neutral: it never returns prose. Anything meant to be read by a
human is a ``MessageOut`` — a code plus its parameters — which the client renders in
the user's language. See ``app/messages.py``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MessageOut(BaseModel):
    """A translatable message. The client owns the wording."""

    code: str
    params: dict[str, Any] = Field(default_factory=dict)


class SectionOut(BaseModel):
    """What one sheet of the imported workbook contained."""

    sheet: str
    kind: str
    count: int
    #: Raw row count before aggregation. Larger than ``count`` on open positions,
    #: where the export lists one aggregate row per holding plus one row per lot.
    source_rows: int


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    broker_symbol: str
    provider_symbol: str | None
    mapping_status: str
    name: str | None
    category: str | None
    currency: str | None
    country: str | None
    sector: str | None
    isin: str | None = None
    #: Set once a provider actually returned data for this symbol. Until then the
    #: mapping is only a plausible conversion, and the UI says so.
    verified_at: datetime | None = None
    verified_provider: str | None = None
    not_priceable_reason: str | None = None
    #: Computed server-side: 'fresh' | 'stale' | 'error' | 'not_priceable' | 'unmapped'.
    #: See prices/service.py:price_status for the rule.
    price_status: str | None = None


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument: InstrumentOut
    source: str
    account: str | None
    quantity: float
    avg_price: float
    currency: str | None
    opened_at: datetime | None
    lots_count: int

    # Values reported by the broker, in the account currency.
    broker_market_value: float | None
    broker_net_pl: float | None
    broker_net_pl_pct: float | None
    broker_gross_pl: float | None
    broker_purchase_value: float | None
    market_price: float | None
    commission: float | None
    swap: float | None
    comment: str | None
    #: A translatable caveat on `broker_net_pl`/`broker_net_pl_pct` when
    #: they were derived from an approximation rather than a true cost
    #: basis — see `app/models.py::Position.performance_note` and
    #: `app/messages.py::PerformanceNote`. `None` for an ordinary priced
    #: position.
    performance_note: MessageOut | None = None
    #: The date this position's *value* (not P&L) was declared by its
    #: source — set only for a broker-declared valuation (Mintos Core P2P,
    #: Amundi ESR), `None` for an ordinary priced position. See
    #: `app/models.py::Position.value_as_of`.
    value_as_of: date | None = None
    #: A translatable caveat pairing with `value_as_of`: whether that
    #: declared value is within its source's expected update cadence or
    #: predates it. `None` for an ordinary priced position. See
    #: `app/messages.py::ValuationNote` and DEVLOG "Decision 3u.50".
    valuation_note: MessageOut | None = None
    weight_percent: float | None = None

    # Up-to-date figures, computed server-side from whatever pricing is
    # currently available — see `_current_position_figures` in
    # `routers/portfolio.py` and DEVLOG "Decision 2f.3". None until the backend
    # populates it (immediately after `POST /positions`, before the next
    # `GET /portfolio`).
    current_value: float | None = None
    current_unrealized_pl: float | None = None
    current_unrealized_pl_pct: float | None = None
    current_price: float | None = None
    #: 'live' (this refresh fetched a fresh quote), 'cached' (latest daily
    #: close), or 'broker' (the broker's own frozen import figure — CFDs,
    #: which have no live equivalent, or anything not priceable yet).
    price_source: str | None = None


class LotOut(BaseModel):
    """One actual buy fill for a single instrument — see
    `app/models.py::Lot`. Both open (still held) and closed (a complete
    round trip) lots are returned; the caller distinguishes them via
    `lot_type`. Read-only: nothing here is ever edited directly, a lot is
    only ever created/closed by an import or a manual position edit."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    quantity: float
    open_price: float
    opened_at: datetime | None
    close_price: float | None
    closed_at: datetime | None
    currency: str | None
    account: str | None
    lot_type: str
    source: str


class QuoteStatusOut(BaseModel):
    """Live progress of a "recalculate with fresh prices" round in flight."""

    running: bool
    total: int
    done: int
    current_symbol: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class BreakdownItem(BaseModel):
    """One slice of the portfolio, grouped by category, currency, country or sector."""

    label: str
    value: float
    weight_percent: float


class AllocationTargetIn(BaseModel):
    min_pct: float = Field(ge=0, le=100)
    max_pct: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def check_range(self) -> "AllocationTargetIn":
        if self.min_pct > self.max_pct:
            raise ValueError("min_pct must not be greater than max_pct")
        return self


class AllocationRowOut(BaseModel):
    """One asset class's current allocation vs. its configured target range —
    descriptive only. The app never suggests buying or selling a specific
    security; this is a gap against a range the user themselves set."""

    category: str
    current_value: float
    current_pct: float
    min_pct: float | None
    max_pct: float | None
    #: "within" | "under" | "over" | "no_target" — "no_target" means the user
    #: hasn't configured a range for this category yet; it still appears
    #: (with current_value/current_pct) so the table isn't misleadingly
    #: incomplete.
    state: str
    #: 0 when within range or no_target. Positive distance to the nearest
    #: breached bound otherwise (min_pct - current_pct when under,
    #: current_pct - max_pct when over).
    gap_pct: float
    #: Only set when state == "under". The euro amount this category alone
    #: would need — via new contributions, nothing sold — to reach min_pct
    #: *of the portfolio's current total value*. Deliberately not solving for
    #: the new (larger) total after adding this amount: a one-sentence,
    #: honestly-labeled approximation beats a "more exact" number that reads
    #: as more precise than it is. Never shown for "over" — no sale suggested.
    amount_to_reach_min: float | None


class PersonalPolicyIn(BaseModel):
    """The user's own, self-declared investment policy — every field
    optional, since an incomplete policy is a normal, permanent state, not
    a form to be pushed to completion. See DEVLOG "Decision 3u.59"."""

    objective_growth: bool = False
    objective_income: bool = False
    objective_preservation: bool = False
    objective_note: str | None = Field(default=None, max_length=500)
    #: "short" | "medium" | "long", or unset — a qualitative horizon and a
    #: target date are independent; either, both, or neither may be set.
    horizon: str | None = None
    horizon_target_date: date | None = None
    liquidity_need_amount: float | None = Field(default=None, ge=0)
    liquidity_need_date: date | None = None
    liquidity_note: str | None = Field(default=None, max_length=500)
    #: Deliberately free text, not a forced "prudent/balanced/dynamic"
    #: scale — the app never assigns the user a risk profile.
    risk_tolerance_note: str | None = Field(default=None, max_length=500)
    loss_capacity_pct: float | None = Field(default=None, ge=0, le=100)


class PersonalPolicyOut(PersonalPolicyIn):
    updated_at: datetime


class PersonalPolicyLimitIn(BaseModel):
    """One personal concentration rule to compare the portfolio against —
    see `PersonalPolicyLimitDimension` for what `target` means per
    dimension. At least one of `min_pct`/`max_pct` must be set."""

    #: "line" | "sector" | "country" | "currency" | "category" | "declared_valuation"
    dimension: str
    #: The specific value being limited (a sector name, currency code...).
    #: Must be unset for "line" (applies uniformly to every position) and
    #: "declared_valuation" (a fixed pseudo-dimension); required otherwise.
    target: str | None = Field(default=None, max_length=80)
    min_pct: float | None = Field(default=None, ge=0, le=100)
    max_pct: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def check_shape(self) -> "PersonalPolicyLimitIn":
        if self.min_pct is None and self.max_pct is None:
            raise ValueError("at least one of min_pct/max_pct is required")
        if self.min_pct is not None and self.max_pct is not None and self.min_pct > self.max_pct:
            raise ValueError("min_pct must not be greater than max_pct")
        no_target_dimensions = {"line", "declared_valuation"}
        if self.dimension in no_target_dimensions and self.target is not None:
            raise ValueError(f"'{self.dimension}' does not take a target")
        if self.dimension not in no_target_dimensions and not self.target:
            raise ValueError(f"'{self.dimension}' requires a target")
        return self


class PersonalPolicyLimitOut(BaseModel):
    id: int
    dimension: str
    target: str | None
    min_pct: float | None
    max_pct: float | None


class PersonalPolicyGapOut(BaseModel):
    """One factual comparison between a configured limit and the current
    portfolio — never a suggestion, just what is and isn't within the
    user's own stated range. Only breaches are returned (same "nothing to
    report" posture as `/attention`); a limit currently satisfied doesn't
    appear here at all."""

    limit_id: int
    dimension: str
    #: The instrument's own broker symbol for "line" (one row per breaching
    #: position); the configured `PersonalPolicyLimit.target` otherwise.
    target: str | None
    current_pct: float
    min_pct: float | None
    max_pct: float | None
    #: "under" | "over" — "within" rows are never returned.
    state: str
    #: Positive distance to the nearest breached bound.
    gap_pct: float


class AttentionItemOut(BaseModel):
    """One fact worth a look today, surfaced on the Portfolio page's summary
    card — never a suggestion to act, only what's currently true and where
    to go check it. Every field is derived from data the app already
    computes elsewhere (price status, allocation targets, unresolved
    symbols); this endpoint only picks out what deserves attention and
    ranks it. See DEVLOG "Decision 3u.25"."""

    #: "missing" (data absent or unreliable) | "warning" (a configured gap
    #: or an out-of-date figure, worth a look but not broken).
    severity: str
    #: "unresolved_instruments" | "price_error" | "price_stale" |
    #: "allocation_under" | "allocation_over" — the frontend picks its i18n
    #: message template from this.
    kind: str
    #: How many positions/instruments this item covers. Always >= 1.
    count: int
    #: Set only for "allocation_under"/"allocation_over" — the asset class
    #: the gap applies to.
    category: str | None = None
    #: Set only for "allocation_under"/"allocation_over" — same figure as
    #: `AllocationRowOut.gap_pct`.
    gap_pct: float | None = None


class DataHealthValuationOut(BaseModel):
    """How one instrument's current value is derived — see DEVLOG "Decision
    3u.58". Never conflates a stale market quote with a merely-dated but
    still-valid declared valuation (DEVLOG "Decision 3u.50")."""

    #: "market_price" (a live/cached quote) | "declared_value" (a Mintos/
    #: Amundi broker-declared figure) | "unavailable" (no value at all —
    #: e.g. a corporate-action residual).
    kind: str
    #: Provider name for a market price (e.g. "FMP"), broker name for a
    #: declared value (e.g. "Mintos"), `None` if unavailable or never
    #: checked.
    source: str | None = None
    as_of: date | None = None
    #: "fresh" | "stale" | "unknown" (no date to judge freshness from at
    #: all — distinct from "stale", which means a date exists and it's old).
    freshness: str


class DataHealthCorporateActionsOut(BaseModel):
    """One instrument's corporate-action trust state — see DEVLOG "Decision
    3u.58". `confirmed_events`/`outstanding_events` are **event** counts,
    never to be read as instrument counts (one instrument can carry several
    corporate-action events)."""

    #: "verified" (>=1 applied, nothing outstanding) | "no_events" (checked,
    #: genuinely nothing found) | "candidate_single_source" |
    #: "provider_conflict" | "suspect_ticker_reuse" | "incomplete_coverage"
    #: (still on Alpha Vantage's resume queue) | "never_checked" |
    #: "not_applicable" (no provider symbol to check at all).
    status: str
    confirmed_events: int
    outstanding_events: int


class DataHealthRowOut(BaseModel):
    """One held instrument's full trust report: what value is used, where it
    comes from, how fresh it is, and whether its corporate-action history is
    confirmed — the per-instrument counterpart to `DataHealthSummaryOut`'s
    rollup. See DEVLOG "Decision 3u.58"."""

    instrument_id: int
    symbol: str
    name: str | None
    valuation: DataHealthValuationOut
    corporate_actions: DataHealthCorporateActionsOut
    #: "info" (nothing to do) | "attention" (usable, worth a look) |
    #: "action_required" (a number may be wrong or missing) |
    #: "not_applicable" (not a market-priced/CA-eligible asset by design —
    #: never a problem). The single most severe of the valuation and
    #: corporate-actions signals above.
    severity: str
    #: Single dominant explanation code for `severity`, `None` when "info".
    #: e.g. "unresolved_symbol" | "price_error" | "price_stale" |
    #: "never_refreshed" | "declared_stale" | "declared_value_missing_date"
    #: | "corporate_action_candidate" | "corporate_action_conflict" |
    #: "corporate_action_suspect" | "corporate_action_incomplete_coverage".
    reason: str | None = None
    #: One suggested next step, `None` when nothing to do.
    #: "fix_symbol" | "refresh_quotes" | "import_recent_statement" |
    #: "resume_alpha_vantage" | "verify_eodhd".
    recommended_action: str | None = None


class DataHealthSummaryOut(BaseModel):
    """Portfolio-wide rollup of `DataHealthRowOut.severity` — the at-a-glance
    counterpart to the full row table."""

    total_instruments: int
    info_count: int
    attention_count: int
    action_required_count: int
    not_applicable_count: int


class DataHealthOut(BaseModel):
    """Per-instrument data-quality and corporate-action trust report for
    held (open) positions only — never Watchlist or Screener. See DEVLOG
    "Decision 3u.58", superseding the category-only v1 shape ("Decision
    3u.33"/"3u.50")."""

    summary: DataHealthSummaryOut
    rows: list[DataHealthRowOut]


class OnboardingStatusOut(BaseModel):
    """Whether each first-run step has been done at least once — backs the
    dismissible "getting started" checklist shown on the Portfolio page
    until every step is complete (or the user dismisses it). Each field is
    a plain existence check against data the app already stores; nothing
    here is computed or inferred. See DEVLOG "Decision 3u.26"."""

    #: At least one XTB statement has been imported (an `ImportBatch` row
    #: exists) — a manually entered position does not count, since this
    #: step is specifically about reconstructing real broker history.
    imported: bool
    #: `POST /refresh-live` (or the history refresh it wraps) has completed
    #: at least once.
    prices_refreshed: bool
    #: No instrument currently needs a symbol correction. Trivially true
    #: with an empty portfolio — nothing to check is not a failure.
    unresolved_resolved: bool
    #: At least one fundamentals figure has ever been fetched for any
    #: instrument (a `Fundamental` row exists).
    fundamentals_fetched: bool
    #: At least one asset-class target range has been configured.
    allocation_target_set: bool
    #: At least one instrument has been added to the watchlist.
    watchlist_started: bool


class PositionSignalOut(BaseModel):
    """A held instrument's score combined with its asset class's allocation
    gap — a transparent, rule-based derivation of two indicators the app
    already shows separately, not a new analysis. Every field the rule reads
    is included so the UI never has to present the outcome as a black box.
    """

    instrument_id: int
    #: "reinforce" | "reduce" | "hold" | "not_applicable" — see
    #: `routers/portfolio.py::_position_signal` for the exact rule.
    signal: str
    composite_score: float | None
    #: "high" | "mid" | "low" | "none" — same thresholds (66/33) as the
    #: frontend's own `scoreBand` (`components/ScoreBadge.tsx`).
    score_band: str
    category: str | None
    #: This instrument's asset class's state from `GET /allocation` —
    #: "within" | "under" | "over" | "no_target".
    allocation_state: str
    #: Same value as `AllocationRowOut.gap_pct` for this category — 0 when
    #: within range or no_target. Exposed so the UI can show the exact
    #: magnitude ("8.1 pts over"), not just the word.
    gap_pct: float


class WatchlistSignalOut(BaseModel):
    """A watched instrument's score combined with its distance to the
    user-set target entry price — same transparent derivation as
    `PositionSignalOut`, scoped to what's meaningful for something not yet
    held: only ever "reinforce" (a real entry opportunity — price at/below
    target and a high score), "hold" (wait), or "not_applicable" (no target
    price set, or no computable score). Never "reduce" — there is nothing
    to reduce.
    """

    instrument_id: int
    signal: str
    composite_score: float | None
    score_band: str
    distance_to_target_pct: float | None


class EnrichSectorsOut(BaseModel):
    """Result of a POST /enrich-sectors run."""

    enriched: int
    skipped: int
    failed: int


class BackfillIsinsOut(BaseModel):
    """Result of a POST /backfill-isins run — see `symbols/duplicates.py::backfill_isins`."""

    checked: int
    updated: int


class BackfillAccountsOut(BaseModel):
    """Result of a POST /api/transactions/backfill-accounts run — see
    `routers/transactions.py::backfill_accounts`."""

    checked: int
    updated: int


class CorporateActionIn(BaseModel):
    """A manually-entered split or reverse split — see
    `app/corporate_actions/service.py`. `ratio_numerator`/`ratio_denominator`
    are new shares per old share: a 10-for-1 split is numerator=10,
    denominator=1; a 1-for-10 reverse split is numerator=1, denominator=10.
    """

    instrument_id: int
    action_type: str
    effective_date: date
    ratio_numerator: float = Field(gt=0)
    ratio_denominator: float = Field(gt=0)

    @model_validator(mode="after")
    def check_action_type(self) -> "CorporateActionIn":
        if self.action_type not in ("split", "reverse_split"):
            raise ValueError("action_type must be 'split' or 'reverse_split'")
        return self


class CorporateActionOut(BaseModel):
    """See `app/models.py::CorporateAction`. `price_history_status` records
    whether the cached price history for this instrument was found to
    already reflect the split (never corrected again) or confirmed raw
    (corrected at read time) — see `detect_price_history_status`.
    `confidence`/`corroborating_sources` (DEVLOG "Decision 3u.41") record
    how a cross-source-verified row came to be applied — `"manual"` for
    every hand-entered or pre-existing row."""

    id: int
    instrument: InstrumentOut | None
    action_type: str
    effective_date: date
    ratio_numerator: float
    ratio_denominator: float
    source: str
    price_history_status: str
    confidence: str
    corroborating_sources: list[dict] | None
    created_at: datetime


class CorporateActionDetectionOut(BaseModel):
    """Result of one `POST /api/corporate-actions/detect` run — see
    `app/corporate_actions/service.py::DetectionSummary`. `complete` is the
    field a caller should check before trusting `created`/`found`: a
    provider rate limit can leave one or more instruments unresolved, and
    `created == 0` reads identically whether nothing was found or nothing
    was checked. Never display "no splits found" without also checking
    this flag.

    `verified_three_sources`/`verified_cross_source`/
    `candidate_single_source`/`provider_conflict`/`suspect_ticker_reuse`
    (DEVLOG "Decision 3u.41") break `found` down by how the cross-source
    merge classified each event — only the first two are ever auto-applied
    into `created`; the rest stay visible only as
    `ProviderCorporateActionCandidate` rows (`GET
    /api/corporate-actions/candidates`)."""

    candidates: int
    checked: int
    found: int
    created: int
    already_known: int
    no_events: int
    rate_limited: int
    not_checked: int
    failed: int
    skipped: int
    recently_checked: int
    verified_three_sources: int
    verified_cross_source: int
    candidate_single_source: int
    provider_conflict: int
    suspect_ticker_reuse: int
    complete: bool
    actions: list[CorporateActionOut]


class CorporateActionCandidateOut(BaseModel):
    """One provider's raw, per-event observation — see
    `app/models.py::ProviderCorporateActionCandidate`. Only rows carrying a
    real event (`event_date` set) are ever listed; a status-only row
    (`rate_limited`/`plan_limited`/`not_supported`/`failed`/an `ok` with no
    event) exists purely for internal quota/coverage bookkeeping and is
    never shown to the user directly."""

    id: int
    instrument_id: int
    provider: str
    event_date: date
    event_type: str
    numerator: float
    denominator: float
    retrieved_at: datetime


class CorporateActionResumeRunOut(BaseModel):
    """One execution of the targeted Alpha Vantage resume job — see
    `app/models.py::CorporateActionResumeRun`. `skipped_reason` is set
    (and every count stays 0) when the run did no real work at all:
    `"paused"` (the user's pause toggle was off) or
    `"nothing_incomplete"` (this provider's coverage gap was already
    closed) — distinct from a genuine run that happened to target nothing
    for some other reason, which shouldn't occur. See DEVLOG "Decision
    3u.41"."""

    id: int
    provider: str
    started_at: datetime
    finished_at: datetime | None
    skipped_reason: str | None
    targeted_instrument_ids: list[int]
    checked: int
    rate_limited: int
    failed: int
    no_events: int
    verified_three_sources: int
    verified_cross_source: int
    candidate_single_source: int
    provider_conflict: int
    suspect_ticker_reuse: int
    complete: bool
    remaining_incomplete: int


class CorporateActionResumeStatusOut(BaseModel):
    """What the UI's "Vérification automatique multi-sources" status
    section reads directly — see `app/corporate_actions/service.py::
    get_resume_status`. `last_run` is `None` only if the job has never run
    yet."""

    enabled: bool
    remaining_incomplete: int
    last_run: CorporateActionResumeRunOut | None


class CoverageSummaryOut(BaseModel):
    """See `app/corporate_actions/service.py::CoverageSummary` — a
    read-only, no-provider-calls snapshot backing Phase 4's "Couverture
    automatique" section. Instrument counts and event counts are always
    kept separate: one instrument can carry several events (see DEVLOG
    "Step 3u.57")."""

    eligible_instruments: int
    excluded_instruments: int
    checked_instruments: int
    unchecked_instruments: int
    verified_three_sources_events: int
    verified_cross_source_events: int
    candidate_single_source_events: int
    provider_conflict_events: int
    suspect_ticker_reuse_events: int


class OutstandingCandidateOut(BaseModel):
    """One still-outstanding, never-applied cross-source-merged event — see
    `app/corporate_actions/service.py::OutstandingCandidate`. Read-only in
    Phase 4: promoting one goes through the existing raw-candidate
    `POST .../candidates/{id}/promote`, not through this merged shape."""

    instrument: InstrumentOut
    effective_date: date
    action_type: str
    ratio_numerator: float
    ratio_denominator: float
    #: "candidate_single_source" | "provider_conflict" | "suspect_ticker_reuse"
    #: (or, in the anomalous case an auto-apply was missed, one of the
    #: verified confidences — surfaced rather than hidden).
    confidence: str
    providers: list[str]


class DetectOneIn(BaseModel):
    """A targeted, single-instrument corporate-action check against one
    specific on-demand source — see `app/corporate_actions/service.py::
    detect_one`. Never part of the bulk `/detect` scan. `provider` is a
    field (not a path segment) so a second on-demand source can be added
    later without a new endpoint — only `"eodhd"` is accepted today,
    enforced by this `Literal` before the request ever reaches the
    service. See DEVLOG "Decision 3u.35"."""

    instrument_id: int
    provider: Literal["eodhd"]


class DetectOneOut(BaseModel):
    """Result of one `POST /api/corporate-actions/detect-one` call.
    `status` distinguishes a genuine "no split" answer (`no_events`) from
    every failure shape (`not_supported`/`plan_limited`/`rate_limited`/
    `failed`) — a failure must never be presented as a confirmed absence
    of split."""

    instrument_id: int
    provider: str
    status: Literal["created", "already_known", "no_events", "not_supported", "plan_limited", "rate_limited", "failed"]
    found: int
    created: int
    already_known: int
    actions: list[CorporateActionOut]


class BackupOut(BaseModel):
    """One timestamped snapshot of the live database — see
    `backup/service.py`."""

    filename: str
    created_at: datetime
    size_bytes: int


class SymbolSearchResult(BaseModel):
    symbol: str
    name: str


class AccountTotals(BaseModel):
    """Totals for one account ("My Trades", "PEA"...)."""

    account: str
    positions_count: int
    market_value: float | None = None
    invested_value: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_pct: float | None = None
    #: Set when at least one position in this account carries a
    #: `performance_note` (Mintos Core P2P, or an Amundi fund whose gain
    #: is approximated from known contributions) — the first such note
    #: found, since every position in one of these accounts shares the
    #: same caveat today.
    performance_note: MessageOut | None = None
    #: Set when at least one position in this account is a broker-declared
    #: valuation (Mintos Core P2P, Amundi ESR) — pairs with, and is
    #: independent from, `performance_note`: an account can have a known,
    #: fresh/stale declared *value* with no computable P&L at all (Mintos,
    #: until an interest-income import has run for it), or a P&L caveat
    #: with a perfectly fresh value (an Amundi account re-imported today).
    #: See `app/messages.py::ValuationNote` and DEVLOG "Decision 3u.50".
    valuation_note: MessageOut | None = None


class PortfolioTotals(BaseModel):
    """Portfolio totals, in ``base_currency``.

    ``market_value``, ``unrealized_pl`` and ``unrealized_pl_pct`` are computed
    from the best pricing currently available per position — a live quote, the
    latest cached daily close, or (CFDs, anything not yet priced) the broker's
    own frozen import figure — FX-converted to ``base_currency``. This used to
    be a permanent, never-recomputed copy of the broker's own figures (DEVLOG
    "Bug 2.1"); see "Decision 2f.3" for why that changed. ``invested_value`` is
    the one figure still sourced from the broker import (or, for manually
    entered positions, approximated from the entered quantity and average
    price): cost basis does not move with the market, and the broker's own
    number used the FX rate at the time of purchase, which this app has no
    record of.
    """

    base_currency: str
    positions_count: int
    market_value: float | None = None
    invested_value: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_pct: float | None = None
    #: Sum of every CLOSED_TRADE transaction's net P&L — independent of the
    #: figures above (a completed round trip, not a currently-held position).
    #: None only when there is no closed-trade history at all, never a zero
    #: standing in for "not computed yet."
    realized_pl: float | None = None
    has_incomplete_data: bool = Field(
        default=False,
        description="True when at least one position lacks the values needed for the totals.",
    )
    excluded_positions: int = Field(
        default=0, description="Positions left out of the totals for lack of valuation."
    )
    #: True when at least one position counted above carries a
    #: `ValuationNote.DECLARED_STALE` (a broker-declared valuation older
    #: than its source's expected update cadence, e.g. a Mintos statement
    #: or Amundi ESR relevé). The position is still fully included in
    #: `market_value` — this only means the total isn't uniformly as
    #: fresh as it looks. See DEVLOG "Decision 3u.50".
    has_stale_declared_valuations: bool = Field(default=False)


class PortfolioOut(BaseModel):
    totals: PortfolioTotals
    accounts: list[AccountTotals]
    positions: list[PositionOut]
    unresolved_symbols: list[InstrumentOut]
    last_import_at: datetime | None
    last_price_refresh_at: datetime | None = None


class ValueHistoryPointOut(BaseModel):
    date: str
    #: None when nothing held that day could be priced at all — never a
    #: guessed/zero value in place of missing data.
    value: float | None
    invested: float | None
    #: "If the same cash had bought the benchmark instead" — see DEVLOG
    #: "Decision 3e.1". None when no benchmark is configured or priceable.
    benchmark: float | None = None


class ValueHistoryOut(BaseModel):
    """Real historical portfolio value, replaying actual buys/sells from the
    `Lot` ledger — not a backtest of today's holdings. See DEVLOG "Decision 3b.1".
    """

    points: list[ValueHistoryPointOut]
    start_date: str | None
    #: True when the earliest lot predates the available price history and the
    #: range had to be cut short.
    capped_by_history: bool
    benchmark_available: bool = False
    benchmark_name: str | None = None


class PositionConcentrationOut(BaseModel):
    """One held position's share of total portfolio value — the
    unconditional, always-visible counterpart to Personal Policy's `line`
    limit (`/policy/gaps` only reports a *breach* of a *configured* line
    limit). See DEVLOG "Decision 3u.67"."""

    instrument_id: int
    symbol: str
    name: str | None
    category: str | None
    value: float
    weight_percent: float


class DeclaredValuationSourceOut(BaseModel):
    #: `Instrument.not_priceable_reason` — "p2p_aggregate" | "employee_savings_fund".
    reason: str
    provider_name: str
    value: float
    weight_percent: float
    positions_count: int
    freshest_as_of: date | None
    stalest_as_of: date | None
    #: True when any position in this source is stale per
    #: `DECLARED_VALUE_FRESHNESS_DAYS` — see `_declared_valuation_note`.
    has_stale: bool


class LiquidityOut(BaseModel):
    """Share of the portfolio priced from a periodically-declared broker
    statement rather than a live market quote — the unconditional
    counterpart to Personal Policy's `declared_valuation` limit. Excludes
    structurally non-priceable residuals (corporate-action leftovers): that
    is a data-trust fact already covered by `/data-health`, not a liquidity
    fact. See DEVLOG "Decision 3u.67"."""

    total_declared_value: float
    total_declared_weight_percent: float
    sources: list[DeclaredValuationSourceOut]


class DrawdownOut(BaseModel):
    """Largest peak-to-trough decline in real historical portfolio value —
    from the same `Lot`-replay series `/value-history` already returns.
    Nowhere else in this codebase computes this. See DEVLOG "Decision
    3u.67"."""

    insufficient_history: bool
    max_drawdown_pct: float | None
    peak_date: str | None
    peak_value: float | None
    trough_date: str | None
    trough_value: float | None
    #: None when `insufficient_history`. Otherwise: did `value` reach back
    #: to >= `peak_value` at any point strictly after the trough? A real
    #: historical fact ("it did recover, on this date") — not "is it at
    #: that peak right now," which can differ if it has since dropped again.
    recovered: bool | None
    recovered_date: str | None


class ImportPreviewOut(BaseModel):
    """What `POST /api/imports/xtb/preview` would do, without persisting anything.

    Same shape as `ImportBatchOut` minus the identity fields (`id`, `imported_at`)
    that only make sense once a batch is actually committed.
    """

    filename: str
    positions_found: int
    transactions_found: int
    transactions_inserted: int
    warnings: list[MessageOut]
    sections: list[SectionOut]
    accounts: list[str]


class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    imported_at: datetime
    positions_found: int
    transactions_found: int
    transactions_inserted: int
    warnings: list[MessageOut]
    sections: list[SectionOut]
    accounts: list[str]


class ManualPositionIn(BaseModel):
    broker_symbol: str = Field(min_length=1, max_length=40)
    quantity: float
    avg_price: float
    currency: str | None = None
    account: str | None = None
    opened_at: datetime | None = None
    comment: str | None = None


class WatchlistItemIn(BaseModel):
    broker_symbol: str = Field(min_length=1, max_length=40)
    currency: str | None = None
    target_entry_price: float | None = Field(default=None, gt=0)
    note: str | None = None
    #: Optional — powers a best-effort ISIN lookup (Wikidata) so a same-company
    #: duplicate added under a different ticker gets flagged. Auto-filled by
    #: the frontend when picking a symbol-search suggestion; left for the
    #: user to type when entering a raw ticker by hand instead.
    company_name: str | None = None


class WatchlistItemUpdateIn(BaseModel):
    target_entry_price: float | None = Field(default=None, gt=0)
    note: str | None = None
    #: Not persisted on the item itself — see `WatchlistItemIn.company_name`.
    #: Lets an existing row (added before this field existed, or without it)
    #: opt into ISIN duplicate detection retroactively.
    company_name: str | None = None


class WatchlistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument: InstrumentOut
    added_at: datetime
    target_entry_price: float | None
    note: str | None
    current_price: float | None
    price_source: str | None
    #: Negative or zero = current price is AT OR BELOW the target — a real entry
    #: signal — the inverse of how "distance" normally reads. `None` whenever
    #: either `current_price` or `target_entry_price` is missing: never guessed.
    distance_to_target_pct: float | None
    #: Set only right after a successful add, when the resolved ISIN matches
    #: an instrument already held/watchlisted/screened elsewhere — a soft
    #: signal, never blocks the add. `None` on every other read.
    duplicate_warning: str | None = None


class JournalEntryIn(BaseModel):
    #: Optional — reuses `get_or_create_instrument` exactly as
    #: `WatchlistItemIn.broker_symbol` does, so typing/picking a symbol
    #: works the same way it does everywhere else in this app.
    broker_symbol: str | None = Field(default=None, max_length=40)
    thesis: str = Field(min_length=1)
    review_date: date | None = None


class JournalEntryUpdateIn(BaseModel):
    #: The original decision, edited as one unit — same "the edit form
    #: always submits every field it owns" convention as
    #: `WatchlistItemUpdateIn`. `entry_date` is deliberately not editable
    #: here: it's a historical fact, set once at creation. `outcome_note`
    #: is a separate, later moment (reflection, not the original
    #: decision) — edited via its own endpoint below, never bundled here.
    thesis: str = Field(min_length=1)
    review_date: date | None = None


class JournalEntryOutcomeIn(BaseModel):
    outcome_note: str | None = None


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument: InstrumentOut | None
    thesis: str
    entry_date: date
    review_date: date | None
    outcome_note: str | None


class ScreenerCandidateIn(BaseModel):
    broker_symbol: str = Field(min_length=1, max_length=40)
    currency: str | None = None
    #: See `WatchlistItemIn.company_name`.
    company_name: str | None = None


class ScreenerCandidateUpdateIn(BaseModel):
    #: The only editable thing about a candidate — see
    #: `WatchlistItemUpdateIn.company_name` for why this exists.
    company_name: str | None = None


class ScreenerCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument: InstrumentOut
    added_at: datetime
    current_price: float | None
    price_source: str | None
    #: See `WatchlistItemOut.duplicate_warning`.
    duplicate_warning: str | None = None


class DiscoveryImportOut(BaseModel):
    """Result of `POST /api/discovery/import-sp500`."""

    imported: int
    already_present: int


class DiscoveryRefreshOut(BaseModel):
    """Result of one `POST /api/discovery/refresh` batch."""

    evaluated: int
    remaining: int


class DiscoveryCandidateOut(BaseModel):
    """One automatically-surfaced candidate — never a real, tracked
    "hidden gem" until explicitly added via `POST /api/screener`. Ranked by
    `value_score` or `growth_score`, the app's own existing scoring
    pillars — never a new "potential" metric.

    `recommendation` is an explicit "buy"/"hold"/"sell" verdict derived from
    `composite_score` via `scoring.service.score_band` — a deliberate,
    user-requested exception to this app's usual descriptive-only labeling
    (see DEVLOG "Decision 3u.21"). Scoped to Discovery only: position and
    watchlist signals elsewhere in the app stay fact-based."""

    model_config = ConfigDict(from_attributes=True)

    instrument: InstrumentOut
    #: "sp500" | "finviz:insider_buys" | "finviz:oversold" — where this
    #: candidate came from, always shown, never blended into one
    #: undifferentiated pool.
    source: str
    composite_score: float | None
    value_score: float | None
    growth_score: float | None
    current_price: float | None = None
    price_source: str | None = None
    #: "buy" | "hold" | "sell" | None (None when there's no composite score
    #: to derive it from — never guessed).
    recommendation: str | None = None
    #: True when this instrument has an unresolved corporate-action
    #: candidate (single-source, conflicting, or suspect-ticker-reuse) that
    #: hasn't been confirmed or dismissed yet — see
    #: `corporate_actions/service.py::list_outstanding_candidates`. Powers
    #: the data-quality filter's "no pending corporate action" condition.
    corporate_action_pending: bool = False
    #: Price × diluted shares outstanding — an approximation, informational
    #: only, never fed into `composite_score`. `None` when the fundamentals
    #: needed (diluted shares) or a price aren't available.
    market_cap: float | None = None
    #: Debt-to-equity — the same raw ratio already computed for the Value
    #: pillar's `debt_to_equity` metric, just surfaced here too. `None` when
    #: the underlying fundamentals aren't available.
    debt_ratio: float | None = None
    #: Roughly how many years of cached daily price history exist for this
    #: instrument (`len(price bars) / 252`) — a data-sufficiency fact, not a
    #: score. `None` when there's no priced history at all.
    price_history_years: float | None = None
    #: Filed dividends-per-share ÷ price — a company-level fundamentals
    #: estimate, deliberately separate from the scored `dividend_yield`
    #: metric (held-stock lot replay). `None` until the `dividend_per_share`
    #: concept has been fetched for this instrument. See DEVLOG
    #: "Decision 3u.73".
    dividend_yield_estimate: float | None = None


class DiscoveryFinvizOut(BaseModel):
    """Result of `POST /api/discovery/finviz` — one whitelisted preset scan."""

    preset: str
    candidates: list[DiscoveryCandidateOut]
    #: A candidate whose refresh/scoring raised is skipped, not left to sink
    #: the whole scan — this counts how many were dropped that way, so the
    #: gap is visible rather than silently absorbed. See DEVLOG "Decision 3u.20" addendum.
    failed: int = 0


class PredictionBackfillReportOut(BaseModel):
    """Result of `POST /api/prediction/backfill-history` — phase 1 of a
    real, backtestable Discovery prediction (DEVLOG "Decision 3u.22")."""

    updated: int = 0
    failed: int = 0
    bars_added: int = 0
    #: True when a run was already in progress and this call did nothing —
    #: distinct from a run that genuinely touched 0 instruments.
    already_running: bool = False


class PredictionBackfillStatusOut(BaseModel):
    """Live progress of the backfill currently in flight, or the last
    completed one — same shape as `FundamentalsRefreshStatusOut`."""

    running: bool
    total: int
    done: int
    current_symbol: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report: PredictionBackfillReportOut | None = None


class BacktestReportOut(BaseModel):
    """Result of `POST /api/prediction/backtest` — phase 2 of a real,
    backtestable Discovery prediction (DEVLOG "Decision 3u.23"). Every
    field here is an honest, unrounded metric from a strictly chronological
    train/test split — never a guessed or smoothed number."""

    instruments_used: int
    train_samples: int
    test_samples: int
    train_start: str | None = None
    train_end: str | None = None
    test_start: str | None = None
    test_end: str | None = None
    test_accuracy: float | None = None
    avg_return_predicted_up: float | None = None
    avg_return_predicted_down: float | None = None
    #: True when `test_samples` is too small to trust the accuracy above —
    #: must be surfaced alongside it, never silently dropped.
    low_sample_warning: bool
    #: True when the training period had only one label class (e.g. a pure
    #: uptrend) — no classifier could be fit, so `test_accuracy` is `None`.
    single_class_warning: bool = False


class IsinIn(BaseModel):
    broker_symbol: str = Field(min_length=1, max_length=40)
    isin: str = Field(min_length=12, max_length=12)


class SymbolOverrideIn(BaseModel):
    broker_symbol: str = Field(min_length=1, max_length=40)
    provider_symbol: str = Field(min_length=1, max_length=40)
    note: str | None = None


class ManualTransactionIn(BaseModel):
    """A hand-entered cash-flow row. Deliberately cannot be a trade type
    (BUY/SELL/CLOSED_TRADE) — see `routers/transactions.py::MANUAL_TX_TYPES`.
    """

    type: str
    executed_at: datetime | None = None
    amount: float
    currency: str | None = None
    account: str | None = None
    #: Ties the row to an instrument (e.g. which holding paid this dividend) —
    #: optional, since most cash-flow types (deposits, interest...) have none.
    broker_symbol: str | None = None
    comment: str | None = None


class TransactionUpdateIn(BaseModel):
    """Every field optional — only what is provided gets changed. Correcting
    an imported row never touches its `raw` audit trail beyond the `account`
    sub-key, so the original source data survives the correction.
    """

    type: str | None = None
    executed_at: datetime | None = None
    amount: float | None = None
    currency: str | None = None
    account: str | None = None
    comment: str | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str | None
    type: str
    executed_at: datetime | None
    quantity: float | None
    price: float | None
    amount: float | None
    currency: str | None
    commission: float | None
    swap: float | None
    comment: str | None
    instrument: InstrumentOut | None
    #: A real column since DEVLOG "Decision 3u.28" (previously recovered from
    #: `raw` at serve time — Alembic didn't exist yet when that was written).
    #: Rows imported before the column existed are backfilled from `raw`
    #: rather than left null; new imports write it directly.
    account: str | None = None
    #: Only for CLOSED_TRADE rows with a resolvable matching Lot and a
    #: parseable FX rate — see DEVLOG "Decision 3p.1". None (never a guessed
    #: zero) whenever the split can't be computed.
    instrument_effect: float | None = None
    #: Residual against `amount` — also absorbs commission/swap/rounding,
    #: not a pure FX figure. See DEVLOG "Decision 3p.1".
    currency_effect: float | None = None


class TransactionSummaryOut(BaseModel):
    """Cheap aggregates over the same rows the list already loaded — no
    separate computation engine. Honours whatever filters the list request
    used, so "this year's dividends" summarises this year, not all time.
    """

    total_dividends: float
    total_withholding_tax: float
    net_dividends: float
    total_fees: float
    total_realized_pl: float
    #: Sum of resolvable closed trades' instrument/currency-and-fees split —
    #: see DEVLOG "Decision 3p.1". 0.0 when nothing in scope was resolvable,
    #: same "sum over what's available" convention as the other totals here.
    total_instrument_effect: float = 0.0
    total_currency_effect: float = 0.0
    #: How many CLOSED_TRADE rows in scope contributed to the two totals
    #: above, out of how many CLOSED_TRADE rows exist in scope — CFDs in
    #: particular often have neither a matching Lot nor conversion-rate
    #: columns, so this is routinely a strict subset. Lets the UI warn
    #: instead of implying the split totals reconcile to total_realized_pl,
    #: which they only do when this is a full count. See DEVLOG "Decision 3p.1".
    closed_trades_with_effect: int = 0
    closed_trades_total: int = 0


class TransactionListOut(BaseModel):
    transactions: list[TransactionOut]
    summary: TransactionSummaryOut


class TaxOtherFlowOut(BaseModel):
    """One `OTHER`-typed transaction shown as-is, never bucketed into a
    guessed tax category. See `app/tax/service.py`."""

    label: str
    amount: float


class TaxEnvelopeSummaryOut(BaseModel):
    """One account's tax-relevant activity for one calendar year — a
    reconciliation aid, never a tax calculation. No rate is ever applied
    here; every figure is a plain sum of already-imported transactions.
    See DEVLOG "Decision 3u.60"."""

    account: str
    #: "cto" | "pea" | "p2p" | "employee_savings"
    envelope_kind: str
    dividends_gross: float | None
    dividends_withholding: float | None
    interest: float | None
    realized_gains: float | None
    realized_losses: float | None
    fees: float | None
    deposits: float | None
    withdrawals: float | None
    #: Real `SELL` transactions with no matching `CLOSED_TRADE` figure —
    #: their gain/loss is never estimated (needs a validated FIFO engine
    #: this app does not have yet).
    unmatched_sales_count: int
    unmatched_sales_amount: float | None
    other_flows: list[TaxOtherFlowOut]
    #: "to_reconcile" | "not_applicable"
    status: str
    notes: list[MessageOut]


class TaxYearSummaryOut(BaseModel):
    tax_year: int
    envelopes: list[TaxEnvelopeSummaryOut]
    #: Always present — the permanent, non-dismissible boundary statement
    #: this feature must never let the user forget.
    disclaimer: MessageOut


class TaxYearsAvailableOut(BaseModel):
    years: list[int]


class DividendSummaryRowOut(BaseModel):
    """One calendar year × account's dividend totals — see
    `dividends/service.py::dividend_summary`. Computed directly from
    `DIVIDEND`/`TAX` transactions, never by summing `DividendDetailRowOut`
    rows, so a reconciliation miss can never silently shrink a real total.
    Descriptive only: no tax liability is computed, only what was actually
    received and withheld.
    """

    year: int
    account: str | None
    currency: str | None
    gross: float
    withholding_tax: float
    net: float
    payment_count: int


class DividendDetailRowOut(BaseModel):
    """One dividend payment (or one orphan withholding that couldn't be
    attributed to a dividend) — see `dividends/service.py::dividend_detail`.
    """

    id: int
    executed_at: datetime | None
    instrument: InstrumentOut | None
    account: str | None
    currency: str | None
    #: None only for an "unmatched_tax" row — an orphan withholding with no
    #: dividend payment of its own.
    gross: float | None
    #: None when no withholding was found for this dividend — not an error,
    #: most dividends legitimately carry none (0% treaty rate, PEA wrapper).
    withholding_tax: float | None
    net: float | None
    comment: str | None
    #: "matched" | "no_withholding" | "unmatched_tax" — see the service
    #: module's docstring for what each means.
    reconciliation_status: str


class RefreshReportOut(BaseModel):
    """Outcome of a price refresh.

    Partial success is the normal case: free providers throttle, so a run reports what
    it achieved and how many instruments are still waiting.
    """

    outcomes: list[MessageOut]
    updated: int
    skipped: int
    failed: int
    #: Instruments with no possible market price, counted apart from failures.
    not_priceable: int = 0
    remaining: int


class RefreshStatusOut(BaseModel):
    """Live progress of the refresh currently in flight, or the last completed one.

    Polled separately from the ``POST /refresh`` call that is doing the work, so the
    UI can show a real (not simulated) progress bar while that call is still blocked.
    """

    running: bool
    total: int
    done: int
    current_symbol: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report: RefreshReportOut | None = None


class PricePoint(BaseModel):
    date: str
    close: float | None


class PriceHistoryOut(BaseModel):
    instrument_id: int
    broker_symbol: str
    #: Which provider served the most recent bar — surfaced so a number on screen can
    #: always be traced back to its source.
    provider: str | None
    points: list[PricePoint]


class SparklineOut(BaseModel):
    """Closes only, for drawing a small trend line next to a position."""

    instrument_id: int
    closes: list[float]


class ProviderStatusOut(BaseModel):
    """What one price source can do right now.

    Redundancy that cannot be inspected is a claim, not a property.
    """

    name: str
    enabled: bool
    #: True while backing off after a rate limit.
    cooling_down: bool
    #: How many held instruments this source could serve, out of the total.
    serves_holdings: int
    total_holdings: int
    #: None for a provider with no documented quota (see DEVLOG "Decision 3m.1")
    #: — not "zero", which would falsely claim a known, exhausted limit.
    quota_limit: int | None = None
    quota_period: str | None = None
    quota_used: int | None = None


class FundamentalsRefreshReportOut(BaseModel):
    """Outcome of a fundamentals fetch — same shape as `RefreshReportOut`,
    since coverage is just as partial by nature (only US filers have
    anything to fetch). See DEVLOG "Decision 3r.1"."""

    outcomes: list[MessageOut]
    updated: int
    skipped: int
    #: ETFs and CFDs — not a shortfall, a property of the instrument.
    not_applicable: int = 0
    failed: int


class FundamentalsRefreshStatusOut(BaseModel):
    """Live progress of the fundamentals refresh currently in flight, or the
    last completed one — same shape as `RefreshStatusOut`."""

    running: bool
    total: int
    done: int
    current_symbol: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report: FundamentalsRefreshReportOut | None = None


class MetricScoreOut(BaseModel):
    """One metric's contribution to its pillar — raw value included so a
    surprising score is always traceable to what produced it."""

    name: str
    weight: float
    score: float | None
    value: float | None
    #: One of a small translatable vocabulary (e.g. "missing_concept",
    #: "insufficient_history") — `None` means the metric was scored.
    dropped_reason: str | None


class PillarScoreOut(BaseModel):
    name: str
    score: float | None
    #: This pillar's weight, renormalized against sibling pillars that also
    #: scored — the share of the composite it actually contributed.
    weight_used: float
    metrics: list[MetricScoreOut]


class ScoreOut(BaseModel):
    """A holding's composite score plus the full per-pillar/per-metric
    breakdown behind it — never just the number."""

    instrument_id: int
    composite: float | None
    pillars: list[PillarScoreOut]


class NewsArticleOut(BaseModel):
    title: str
    url: str
    source: str
    time_published: datetime
    summary: str
    overall_sentiment_label: str
    overall_sentiment_score: float
    ticker_relevance_score: float
    ticker_sentiment_score: float
    ticker_sentiment_label: str


class NewsSentimentOut(BaseModel):
    instrument_id: int
    fetched_at: datetime | None
    articles: list[NewsArticleOut]
    outcome: MessageOut


class CitationOut(BaseModel):
    url: str
    title: str | None = None


class InstrumentCommentaryOut(BaseModel):
    instrument_id: int
    fetched_at: datetime | None
    model: str
    content: str
    citations: list[CitationOut]
    outcome: MessageOut


class FactorImportOut(BaseModel):
    """Result of `POST /api/factors/import` — a one-off (or occasional
    re-run) fetch of Kenneth French's daily factor series. See DEVLOG
    "Decision 3u.24"."""

    imported: int
    already_present: int


class FactorLoadingsOut(BaseModel):
    """One held position's Carhart four-factor exposure — an explanatory,
    descriptive indicator (what has historically driven this holding's
    returns), never a prediction. See DEVLOG "Decision 3u.24"."""

    instrument: InstrumentOut
    #: "US" | "EUROPE" | `None` when `not_applicable_reason` is set.
    region: str | None
    n_observations: int
    start_date: str | None = None
    end_date: str | None = None
    alpha: float | None = None
    beta_mkt: float | None = None
    beta_smb: float | None = None
    beta_hml: float | None = None
    beta_mom: float | None = None
    r_squared: float | None = None
    alpha_p_value: float | None = None
    #: "no_region_match" | "insufficient_history" | `None` (regression ran).
    not_applicable_reason: str | None = None
