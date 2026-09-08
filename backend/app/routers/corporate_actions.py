"""Stock splits and reverse splits — see `app/corporate_actions/service.py`
for detection and the read-time adjustment this data drives. Manual entry
plus an automatic cross-source detector (Alpha Vantage + Polygon, joined
conditionally by FMP once readmitted — DEVLOG "Decision 3u.41"; originally
Yahoo, then FMP alone — DEVLOG "Decision 3u.34") plus a targeted, on-demand
EODHD check (`detect-one`); `PriceBar`/`Lot` are never mutated by anything
here. See DEVLOG "Decision 3u.30".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.corporate_actions.service import (
    ALPHA_VANTAGE_RESUME_DAILY_LIMIT,
    compute_coverage_summary,
    create_corporate_action,
    detect_one,
    detect_splits,
    get_resume_status,
    list_incomplete_instrument_ids,
    list_outstanding_candidates,
    promote_candidate,
    resume_incomplete_scan,
    set_resume_enabled,
)
from app.db import get_db
from app.models import CorporateAction, CorporateActionResumeRun, Instrument, ProviderCorporateActionCandidate
from app.schemas import (
    CorporateActionCandidateOut,
    CorporateActionDetectionOut,
    CorporateActionIn,
    CorporateActionOut,
    CorporateActionResumeRunOut,
    CorporateActionResumeStatusOut,
    CoverageSummaryOut,
    DetectOneIn,
    DetectOneOut,
    OutstandingCandidateOut,
)

router = APIRouter(prefix="/api/corporate-actions", tags=["corporate-actions"])


def _out(action: CorporateAction) -> CorporateActionOut:
    return CorporateActionOut(
        id=action.id,
        instrument=action.instrument,
        action_type=action.action_type,
        effective_date=action.effective_date,
        ratio_numerator=action.ratio_numerator,
        ratio_denominator=action.ratio_denominator,
        source=action.source,
        price_history_status=action.price_history_status,
        confidence=action.confidence,
        corroborating_sources=action.corroborating_sources,
        created_at=action.created_at,
    )


def _candidate_out(candidate: ProviderCorporateActionCandidate) -> CorporateActionCandidateOut:
    return CorporateActionCandidateOut(
        id=candidate.id,
        instrument_id=candidate.instrument_id,
        provider=candidate.provider,
        event_date=candidate.event_date,
        event_type=candidate.event_type,
        numerator=candidate.numerator,
        denominator=candidate.denominator,
        retrieved_at=candidate.retrieved_at,
    )


def _run_out(run: CorporateActionResumeRun) -> CorporateActionResumeRunOut:
    return CorporateActionResumeRunOut(
        id=run.id,
        provider=run.provider,
        started_at=run.started_at,
        finished_at=run.finished_at,
        skipped_reason=run.skipped_reason,
        targeted_instrument_ids=run.targeted_instrument_ids,
        checked=run.checked,
        rate_limited=run.rate_limited,
        failed=run.failed,
        no_events=run.no_events,
        verified_three_sources=run.verified_three_sources,
        verified_cross_source=run.verified_cross_source,
        candidate_single_source=run.candidate_single_source,
        provider_conflict=run.provider_conflict,
        suspect_ticker_reuse=run.suspect_ticker_reuse,
        complete=run.complete,
        remaining_incomplete=run.remaining_incomplete,
    )


@router.get("", response_model=list[CorporateActionOut])
def list_corporate_actions(
    instrument_id: int | None = Query(None), db: Session = Depends(get_db)
) -> list[CorporateActionOut]:
    query = select(CorporateAction).options(joinedload(CorporateAction.instrument)).order_by(
        CorporateAction.effective_date.desc()
    )
    if instrument_id is not None:
        query = query.where(CorporateAction.instrument_id == instrument_id)
    return [_out(a) for a in db.execute(query).scalars()]


@router.post("", response_model=CorporateActionOut, status_code=201)
def create_corporate_action_endpoint(payload: CorporateActionIn, db: Session = Depends(get_db)) -> CorporateActionOut:
    instrument = db.get(Instrument, payload.instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found.")
    action = create_corporate_action(
        db,
        instrument_id=payload.instrument_id,
        action_type=payload.action_type,
        effective_date=payload.effective_date,
        ratio_numerator=payload.ratio_numerator,
        ratio_denominator=payload.ratio_denominator,
        source="manual",
    )
    return _out(action)


@router.delete("/{action_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_corporate_action(action_id: int, db: Session = Depends(get_db)) -> Response:
    action = db.get(CorporateAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Corporate action not found.")
    db.delete(action)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/detect", response_model=CorporateActionDetectionOut)
def detect_corporate_actions(
    force: bool = Query(False), db: Session = Depends(get_db)
) -> CorporateActionDetectionOut:
    """Cross-checks every held/watchlisted/screened instrument's split
    history against Alpha Vantage, Polygon, and (once readmitted) FMP, and
    auto-records any event at least two of the currently-active sources
    agree on — see `app/corporate_actions/service.py::detect_splits` for
    the full merge/classify engine. Idempotent — safe to call repeatedly,
    already-recorded splits are never duplicated. A single-source finding
    or a genuine cross-source disagreement is never auto-applied; it stays
    visible via `GET /api/corporate-actions/candidates` for manual review
    or promotion. `complete` in the response is `false` when at least one
    instrument got no usable answer from any source at all (rate-limited or
    structurally failed everywhere) — always check it before treating any
    result, zero or not, as "this is the whole portfolio's real split
    history".

    An instrument checked within the last
    `CORPORATE_ACTIONS_RECHECK_DAYS` days is skipped without a real
    provider call (counted separately as `recently_checked`) — the splits
    endpoints this app calls return full unbounded history with no
    server-side date filter, so re-scanning the same portfolio repeatedly
    is what drained FMP's separate bandwidth quota (DEVLOG "Decision
    3u.41"). Pass `force=true` to re-check everything regardless of when it
    was last checked.
    """
    summary = detect_splits(db, force=force)
    return CorporateActionDetectionOut(
        candidates=summary.candidates,
        checked=summary.checked,
        found=summary.found,
        created=summary.created,
        already_known=summary.already_known,
        no_events=summary.no_events,
        rate_limited=summary.rate_limited,
        not_checked=summary.not_checked,
        failed=summary.failed,
        skipped=summary.skipped,
        recently_checked=summary.recently_checked,
        verified_three_sources=summary.verified_three_sources,
        verified_cross_source=summary.verified_cross_source,
        candidate_single_source=summary.candidate_single_source,
        provider_conflict=summary.provider_conflict,
        suspect_ticker_reuse=summary.suspect_ticker_reuse,
        complete=summary.complete,
        actions=[_out(a) for a in summary.actions],
    )


@router.get("/coverage", response_model=CoverageSummaryOut)
def get_coverage_summary(db: Session = Depends(get_db)) -> CoverageSummaryOut:
    """Read-only automatic-coverage snapshot for Phase 4's "Couverture
    automatique" section — never calls a provider, safe on every page
    load. See `app/corporate_actions/service.py::compute_coverage_summary`.
    """
    summary = compute_coverage_summary(db)
    return CoverageSummaryOut(
        eligible_instruments=summary.eligible_instruments,
        excluded_instruments=summary.excluded_instruments,
        checked_instruments=summary.checked_instruments,
        unchecked_instruments=summary.unchecked_instruments,
        verified_three_sources_events=summary.verified_three_sources_events,
        verified_cross_source_events=summary.verified_cross_source_events,
        candidate_single_source_events=summary.candidate_single_source_events,
        provider_conflict_events=summary.provider_conflict_events,
        suspect_ticker_reuse_events=summary.suspect_ticker_reuse_events,
    )


@router.get("/outstanding", response_model=list[OutstandingCandidateOut])
def get_outstanding_candidates(db: Session = Depends(get_db)) -> list[OutstandingCandidateOut]:
    """Every still-outstanding (never auto-applied, never manually
    promoted) cross-source-merged event — read-only, no provider calls.
    Backs Phase 4's "Candidats à confirmer" list: a `candidate_single_source`
    row must be visible as such, not hidden inside a bare count. See
    `app/corporate_actions/service.py::list_outstanding_candidates`."""
    outstanding = list_outstanding_candidates(db)
    instruments = {
        i.id: i for i in db.execute(
            select(Instrument).where(Instrument.id.in_({o.instrument_id for o in outstanding}))
        ).scalars()
    } if outstanding else {}
    return [
        OutstandingCandidateOut(
            instrument=instruments[o.instrument_id],
            effective_date=o.effective_date,
            action_type=o.action_type,
            ratio_numerator=o.numerator,
            ratio_denominator=o.denominator,
            confidence=o.confidence,
            providers=o.providers,
        )
        for o in sorted(outstanding, key=lambda o: o.effective_date, reverse=True)
    ]


@router.get("/incomplete", response_model=list[int])
def list_incomplete_instruments(
    provider: str = Query("alpha_vantage"),
    limit: int = Query(ALPHA_VANTAGE_RESUME_DAILY_LIMIT),
    db: Session = Depends(get_db),
) -> list[int]:
    """Which instruments a targeted resume (`POST .../detect/resume`) would
    actually target right now, for inspection before spending real quota —
    see `app/corporate_actions/service.py::list_incomplete_instrument_ids`."""
    return list_incomplete_instrument_ids(db, provider_name=provider, limit=limit)


@router.post("/detect/resume", response_model=CorporateActionResumeRunOut)
def resume_corporate_actions_detection(
    provider: str = Query("alpha_vantage"),
    limit: int = Query(ALPHA_VANTAGE_RESUME_DAILY_LIMIT),
    db: Session = Depends(get_db),
) -> CorporateActionResumeRunOut:
    """The scheduled daily targeted-resume job's entry point (meant to be
    called by a cron/scheduler, not just interactively): instead of
    rescanning every eligible instrument (which just re-spends `provider`'s
    daily quota on instruments it already answered), targets only the
    instruments `provider` has never gotten a real answer from —
    prioritizing ones where another source already found a real event
    waiting on corroboration. `limit` defaults to a deliberate margin under
    Alpha Vantage's real ~25/day free quota, leaving headroom for a manual
    check the same day. Does nothing (recorded with a `skipped_reason`,
    not silently) if the job is paused (`POST .../resume/pause`) or if
    nothing is left incomplete. See DEVLOG "Decision 3u.41" and
    `app/corporate_actions/service.py::resume_incomplete_scan`.

    Always uses `force=True` internally on the targeted instruments — the
    point is to force a fresh answer from `provider` regardless of whether
    another source already marked the instrument "recently checked".
    """
    return _run_out(resume_incomplete_scan(db, provider_name=provider, limit=limit))


@router.get("/resume/status", response_model=CorporateActionResumeStatusOut)
def get_corporate_actions_resume_status(
    provider: str = Query("alpha_vantage"), db: Session = Depends(get_db)
) -> CorporateActionResumeStatusOut:
    """What the "Vérification automatique multi-sources" status section
    shows: whether the scheduled job is paused, how many instruments are
    still incomplete for `provider`, and its last run. See DEVLOG "Decision
    3u.41"."""
    enabled, remaining, last_run = get_resume_status(db, provider_name=provider)
    return CorporateActionResumeStatusOut(
        enabled=enabled, remaining_incomplete=remaining, last_run=_run_out(last_run) if last_run else None
    )


@router.post("/resume/pause", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def pause_corporate_actions_resume(db: Session = Depends(get_db)) -> Response:
    """Pauses the scheduled daily targeted-resume job — e.g. to save the
    day's Alpha Vantage quota for a manual check instead. The job itself
    checks this before spending any quota; see
    `app/corporate_actions/service.py::resume_incomplete_scan`."""
    set_resume_enabled(db, False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/resume/unpause", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def unpause_corporate_actions_resume(db: Session = Depends(get_db)) -> Response:
    """Re-enables the scheduled daily targeted-resume job after a pause."""
    set_resume_enabled(db, True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/candidates", response_model=list[CorporateActionCandidateOut])
def list_corporate_action_candidates(
    instrument_id: int | None = Query(None), db: Session = Depends(get_db)
) -> list[CorporateActionCandidateOut]:
    """Every real-event candidate observation `detect_splits`'s cross-source
    engine has recorded — the raw material behind the UI's "Candidats à
    vérifier" section. Status-only rows (`rate_limited`/`plan_limited`/
    `not_supported`/`failed`/an `ok` with no event) are internal quota and
    coverage bookkeeping, never listed here. See DEVLOG "Decision 3u.41"."""
    query = select(ProviderCorporateActionCandidate).where(
        ProviderCorporateActionCandidate.event_date.is_not(None)
    ).order_by(ProviderCorporateActionCandidate.event_date.desc())
    if instrument_id is not None:
        query = query.where(ProviderCorporateActionCandidate.instrument_id == instrument_id)
    return [_candidate_out(c) for c in db.execute(query).scalars()]


@router.post("/candidates/{candidate_id}/promote", response_model=CorporateActionOut)
def promote_corporate_action_candidate(candidate_id: int, db: Session = Depends(get_db)) -> CorporateActionOut:
    """Manually promotes one candidate observation into a real, applied
    `CorporateAction` — for a `candidate_single_source` or
    `provider_conflict` row the user has reviewed themselves and confirmed
    is real (e.g. via a targeted `detect-one` check against EODHD). See
    `app/corporate_actions/service.py::promote_candidate`."""
    action = promote_candidate(db, candidate_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Candidate not found or carries no real event.")
    return _out(action)


@router.post("/detect-one", response_model=DetectOneOut)
def detect_corporate_action_one(payload: DetectOneIn, db: Session = Depends(get_db)) -> DetectOneOut:
    """Targeted, single-instrument check against one specific on-demand
    source — never part of the bulk `/detect` scan above, never triggered
    automatically by it. Built for the exact case found live: FMP gates
    some smaller-cap US symbols (`plan_limited`) that a different source
    can still answer. `status` distinguishes a genuine `no_events` answer
    from every failure shape — never present a failure as a confirmed
    absence of split. See DEVLOG "Decision 3u.35"."""
    result = detect_one(db, payload.instrument_id, payload.provider)
    if result is None:
        raise HTTPException(status_code=404, detail="Instrument not found.")
    return DetectOneOut(
        instrument_id=result.instrument_id,
        provider=result.provider,
        status=result.status,
        found=result.found,
        created=result.created,
        already_known=result.already_known,
        actions=[_out(a) for a in result.actions],
    )
