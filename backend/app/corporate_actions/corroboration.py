"""Second opinions for split candidates that only one source reported.

The automatic scan (`service.detect_splits`) votes with Alpha Vantage, Polygon
and, once readmitted, FMP. None of the three covers Euronext on a free plan,
so every European candidate is single-source by construction, and EODHD — the
one source that does answer for them — is limited to 20 calls a day and has
already been wrong twice on this portfolio (ArcelorMittal's 2016 rights issue
booked as a split, a Dassault Systèmes reverse split that never happened).

Two independent checks, asked only for instruments that already carry an
outstanding candidate (or an applied action no second source ever backed):

* **Yahoo** splits (`events=split` on the chart endpoint). Free, worldwide,
  Euronext included. Its rate limit is why it left the bulk scan (DEVLOG
  "Decision 3u.34"); a handful of calls, through the shared throttle, is
  what it tolerates.
* **SEC cover-page share counts** for US filers. Not a vendor's reading of
  the event but the company's own number: a real 1-for-10 reverse split
  divides the next cover page's count by ten.

What they find is written as ordinary `ProviderCorporateActionCandidate`
rows (`yahoo`, `sec_shares`), so the existing merge/classify engine decides
the rest: a candidate a second voting source agrees with is applied, exactly
like a two-source result of the bulk scan. Nothing is ever deleted or
rejected here. A source that answered without the event only shows up in
`OutstandingCandidate.not_reported_by` for the user to judge.

Quota: at most `limit` instruments per call, Yahoo skipped for an instrument
it answered within `CORPORATE_ACTIONS_RECHECK_DAYS`, and dropped for the rest
of the call on its first rate limit. EDGAR keeps each filer's series in
memory for a day. See DEVLOG "Step 3u.116".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.corporate_actions.service import (
    CORPORATE_ACTIONS_RECHECK_DAYS,
    CROSS_SOURCE_DATE_TOLERANCE_DAYS,
    ECONOMIC_FACTOR_RELATIVE_TOLERANCE,
    _classify_ratio,
    _upsert_candidate,
    list_outstanding_candidates,
)
from app.models import (
    CorporateAction,
    CorporateActionConfidence,
    Instrument,
    ProviderCorporateActionCandidate,
    ProviderCorporateActionCandidateStatus,
)
from app.prices.provider_usage import record_usage
from app.providers.base import InstrumentRef, PlanLimited, ProviderUnavailable, RateLimited, SplitEvent, SymbolNotFound
from app.providers.registry import get_edgar_provider, get_yahoo_provider

#: Instruments looked at per call. Yahoo's throttle (10 s by default) makes
#: this the length of the request in tens of seconds.
DEFAULT_LIMIT = 8
MAX_LIMIT = 25

#: A cover-page count may sit up to this far from the event on either side
#: (a 10-K cover is yearly for some filers) and still be compared.
SHARES_MAX_GAP_DAYS = 400
#: Moved by the ratio, within this share of it: the split is confirmed.
SHARES_MATCH_TOLERANCE = 0.25
#: Stayed within this of flat: the split did not happen at that date.
SHARES_FLAT_TOLERANCE = 0.15
#: Below this size (e.g. a 5% stock dividend) normal buybacks and issuance
#: drown the signal, so the share count says nothing either way.
SHARES_MIN_FACTOR = 1.25

_APPLIED_UNCORROBORATED = {CorporateActionConfidence.MANUAL_PROMOTION, "manual"}


@dataclass
class TargetResult:
    instrument_id: int
    symbol: str | None
    effective_date: date
    action_type: str
    numerator: float
    denominator: float
    #: "outstanding" (a candidate) or "applied" (already applied, never
    #: backed by a second source — reported, never changed).
    kind: str
    #: "reported" | "other_ratio" | "not_reported" | "rate_limited" |
    #: "not_found" | "failed" | "not_checked"
    yahoo: str = "not_checked"
    #: "confirms" | "flat" | "inconclusive" | "no_data" | "not_applicable" |
    #: "too_small" | "rate_limited" | "failed"
    sec_shares: str = "not_applicable"
    sec_detail: dict | None = None
    applied_now: bool = False


@dataclass
class CorroborationSummary:
    instruments_checked: int
    instruments_remaining: int
    applied: int
    still_outstanding: int
    yahoo_rate_limited: bool
    edgar_enabled: bool
    targets: list[TargetResult] = field(default_factory=list)


def _same_event(event: SplitEvent, effective_date: date) -> bool:
    return abs((event.effective_date - effective_date).days) <= CROSS_SOURCE_DATE_TOLERANCE_DAYS


def _same_factor(a: float, b: float) -> bool:
    return abs(a - b) <= ECONOMIC_FACTOR_RELATIVE_TOLERANCE * max(a, b)


def shares_verdict(series, effective_date: date, factor: float) -> tuple[str, dict | None]:
    """Compares the last cover-page count before the event with the first
    one on or after it. Returns (verdict, detail)."""
    if max(factor, 1 / factor) < SHARES_MIN_FACTOR:
        return "too_small", None
    before = [s for s in series if s.as_of < effective_date and (effective_date - s.as_of).days <= SHARES_MAX_GAP_DAYS]
    after = [s for s in series if s.as_of >= effective_date and (s.as_of - effective_date).days <= SHARES_MAX_GAP_DAYS]
    if not before or not after:
        return "no_data", None
    b, a = before[-1], after[0]
    ratio = a.shares / b.shares
    detail = {
        "before_date": b.as_of.isoformat(),
        "before": b.shares,
        "after_date": a.as_of.isoformat(),
        "after": a.shares,
        "ratio": round(ratio, 4),
    }
    if abs(ratio - factor) <= SHARES_MATCH_TOLERANCE * factor:
        return "confirms", detail
    if abs(ratio - 1.0) <= SHARES_FLAT_TOLERANCE:
        return "flat", detail
    return "inconclusive", detail


def _targets(db: Session) -> dict[int, list[TargetResult]]:
    by_instrument: dict[int, list[TargetResult]] = {}
    for c in list_outstanding_candidates(db):
        by_instrument.setdefault(c.instrument_id, []).append(
            TargetResult(c.instrument_id, None, c.effective_date, c.action_type, c.numerator, c.denominator, "outstanding")
        )
    for a in db.execute(select(CorporateAction).where(CorporateAction.confidence.in_(_APPLIED_UNCORROBORATED))).scalars():
        by_instrument.setdefault(a.instrument_id, []).append(
            TargetResult(
                a.instrument_id, None, a.effective_date, a.action_type, a.ratio_numerator, a.ratio_denominator, "applied"
            )
        )
    return by_instrument


def _recent_yahoo(db: Session, instrument_id: int, cutoff: datetime) -> bool:
    last = db.execute(
        select(func.max(ProviderCorporateActionCandidate.retrieved_at)).where(
            ProviderCorporateActionCandidate.instrument_id == instrument_id,
            ProviderCorporateActionCandidate.provider == "yahoo",
            ProviderCorporateActionCandidate.provider_status == ProviderCorporateActionCandidateStatus.OK,
        )
    ).scalar_one_or_none()
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return last >= cutoff


def _yahoo_events(db: Session, instrument_id: int) -> list[SplitEvent]:
    rows = db.execute(
        select(ProviderCorporateActionCandidate).where(
            ProviderCorporateActionCandidate.instrument_id == instrument_id,
            ProviderCorporateActionCandidate.provider == "yahoo",
            ProviderCorporateActionCandidate.event_date.is_not(None),
        )
    ).scalars()
    return [SplitEvent(r.event_date, r.numerator, r.denominator) for r in rows]


def _yahoo_verdict(events: list[SplitEvent], target: TargetResult) -> str:
    near = [e for e in events if _same_event(e, target.effective_date)]
    if not near:
        return "not_reported"
    factor = target.numerator / target.denominator
    if any(_same_factor(e.numerator / e.denominator, factor) for e in near):
        return "reported"
    return "other_ratio"


def corroborate(
    db: Session, limit: int = DEFAULT_LIMIT, force: bool = False, instrument_ids: list[int] | None = None
) -> CorroborationSummary:
    targets = _targets(db)
    if instrument_ids is not None:
        targets = {k: v for k, v in targets.items() if k in set(instrument_ids)}
    limit = max(1, min(limit, MAX_LIMIT))
    # Candidates first (they can still change), then the oldest-applied ones.
    order = sorted(targets, key=lambda i: (all(t.kind == "applied" for t in targets[i]), i))
    chosen, remaining = order[:limit], order[limit:]

    applied_before = db.execute(select(func.count(CorporateAction.id))).scalar_one()
    yahoo = get_yahoo_provider()
    edgar = get_edgar_provider()
    yahoo_blocked = False
    cutoff = datetime.now(UTC) - timedelta(days=CORPORATE_ACTIONS_RECHECK_DAYS)
    today = datetime.now(UTC).date()
    results: list[TargetResult] = []

    for instrument_id in chosen:
        instrument = db.get(Instrument, instrument_id)
        if instrument is None:
            continue
        group = targets[instrument_id]
        for t in group:
            t.symbol = instrument.provider_symbol or instrument.broker_symbol
        ref = InstrumentRef(
            provider_symbol=instrument.provider_symbol,
            isin=instrument.isin,
            broker_symbol=instrument.broker_symbol,
            name=instrument.name,
            category=instrument.category,
        )

        # --- Yahoo -----------------------------------------------------
        # None means "Yahoo's stored answer is current, judge from it".
        yahoo_status: str | None = None
        if not yahoo.can_serve(ref):
            yahoo_status = "not_found"
        elif yahoo_blocked:
            yahoo_status = "rate_limited"
        elif force or not _recent_yahoo(db, instrument_id, cutoff):
            record_usage(db, "yahoo")
            try:
                events = yahoo.fetch_splits(ref, date(1970, 1, 1), today)
            except RateLimited:
                yahoo_blocked = True
                yahoo_status = "rate_limited"
                _upsert_candidate(db, instrument_id, "yahoo", ProviderCorporateActionCandidateStatus.RATE_LIMITED)
            except SymbolNotFound:
                yahoo_status = "not_found"
                _upsert_candidate(db, instrument_id, "yahoo", ProviderCorporateActionCandidateStatus.NOT_SUPPORTED)
            except (PlanLimited, ProviderUnavailable):
                yahoo_status = "failed"
                _upsert_candidate(db, instrument_id, "yahoo", ProviderCorporateActionCandidateStatus.FAILED)
            else:
                # Status row kept OK alongside the event rows: it is what
                # marks "Yahoo answered" when it has no event at all.
                _upsert_candidate(db, instrument_id, "yahoo", ProviderCorporateActionCandidateStatus.OK)
                for event in events:
                    _upsert_candidate(
                        db,
                        instrument_id,
                        "yahoo",
                        ProviderCorporateActionCandidateStatus.OK,
                        event_date=event.effective_date,
                        event_type=_classify_ratio(event.numerator, event.denominator),
                        numerator=event.numerator,
                        denominator=event.denominator,
                        raw_payload={"numerator": event.numerator, "denominator": event.denominator},
                    )
                db.flush()
        if yahoo_status is None:
            stored = _yahoo_events(db, instrument_id)
            for t in group:
                t.yahoo = _yahoo_verdict(stored, t)
        else:
            for t in group:
                t.yahoo = yahoo_status

        # --- SEC cover-page share counts (US filers) --------------------
        if instrument.country == "US" and edgar.is_enabled() and instrument.provider_symbol:
            ticker = instrument.provider_symbol.split(".")[0]
            try:
                series = edgar.fetch_shares_outstanding(ticker)
            except RateLimited:
                series = None
                for t in group:
                    t.sec_shares = "rate_limited"
            except SymbolNotFound:
                series = []
            except ProviderUnavailable:
                series = None
                for t in group:
                    t.sec_shares = "failed"
            if series is not None:
                flat: list[dict] = []
                for t in group:
                    verdict, detail = shares_verdict(series, t.effective_date, t.numerator / t.denominator)
                    t.sec_shares, t.sec_detail = verdict, detail
                    if verdict == "confirms":
                        _upsert_candidate(
                            db,
                            instrument_id,
                            "sec_shares",
                            ProviderCorporateActionCandidateStatus.OK,
                            event_date=t.effective_date,
                            event_type=t.action_type,
                            numerator=t.numerator,
                            denominator=t.denominator,
                            raw_payload=detail,
                        )
                    elif verdict == "flat":
                        flat.append({"event_date": t.effective_date.isoformat(), **(detail or {})})
                _upsert_candidate(
                    db,
                    instrument_id,
                    "sec_shares",
                    # Not OK on purpose: a status row marked OK would make the
                    # SEC look like a source that "answered without the
                    # event" for every candidate, including ones too small to
                    # judge. Flat dates are listed explicitly instead.
                    ProviderCorporateActionCandidateStatus.FAILED
                    if not series
                    else ProviderCorporateActionCandidateStatus.CHECKED,
                    raw_payload={"flat": flat},
                )
                db.flush()

        results.extend(group)

    db.commit()
    outstanding = list_outstanding_candidates(db)  # applies anything two voting sources now agree on
    still = {(c.instrument_id, c.effective_date, c.action_type) for c in outstanding}
    for t in results:
        if t.kind == "outstanding" and (t.instrument_id, t.effective_date, t.action_type) not in still:
            t.applied_now = True
    applied_after = db.execute(select(func.count(CorporateAction.id))).scalar_one()

    return CorroborationSummary(
        instruments_checked=len(chosen),
        instruments_remaining=len(remaining),
        applied=applied_after - applied_before,
        still_outstanding=len(outstanding),
        yahoo_rate_limited=yahoo_blocked,
        edgar_enabled=edgar.is_enabled(),
        targets=results,
    )
