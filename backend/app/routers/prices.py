"""Price refresh and history endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.corporate_actions.service import load_actions_by_instrument, price_factor_from
from app.db import get_db
from app.models import AppMetadata, Instrument, MappingStatus, Position, PriceBar, ProviderUsage
from app.prices.history_service import get_or_create_benchmark_instrument
from app.prices.provider_usage import QUOTA_LIMITS, period_key_for
from app.prices.service import get_refresh_progress, refresh_many
from app.providers.registry import get_provider_chain
from app.providers.base import InstrumentRef
from app.routers.screener import _screener_instruments
from app.routers.watchlist import _watchlist_instruments
from app.schemas import (
    PriceHistoryOut,
    ProviderStatusOut,
    RefreshReportOut,
    RefreshStatusOut,
    SparklineOut,
)

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.post("/refresh", response_model=RefreshReportOut)
def refresh_prices(
    force: bool = Query(False, description="Re-fetch even instruments already up to date."),
    symbols: str | None = Query(
        None,
        description=(
            "Comma-separated broker symbols to restrict this run to, e.g. a targeted "
            "retry of instruments that just failed. Omit to refresh the whole portfolio."
        ),
    ),
    db: Session = Depends(get_db),
) -> RefreshReportOut:
    """Bring held instruments' price history up to date.

    Best-effort by design. Free providers throttle, so this works through the list
    within a time budget and reports what is left. Calling it again continues where it
    stopped — instruments already refreshed are skipped as fresh.
    """
    settings = get_settings()

    # Only instruments actually held: refreshing the whole catalogue would burn the
    # rate-limit budget on symbols nobody is looking at.
    query = (
        select(Instrument)
        .join(Position, Position.instrument_id == Instrument.id)
        # Unresolved instruments are included when they are known to be
        # unpriceable, so the report can say so instead of omitting them.
        .where(
            (Instrument.mapping_status != MappingStatus.UNRESOLVED)
            | Instrument.not_priceable_reason.is_not(None)
        )
        .distinct()
    )
    if symbols:
        wanted = [s.strip() for s in symbols.split(",") if s.strip()]
        query = query.where(Instrument.broker_symbol.in_(wanted))

    instruments = list(db.execute(query).scalars())

    # The value-history chart's comparison benchmark is not a held position —
    # the query above (joined on Position) never sees it — so a general
    # refresh adds it explicitly. A targeted retry (`symbols` set) is scoped
    # to specific failed holdings on purpose; the benchmark stays out of that.
    if not symbols:
        benchmark = get_or_create_benchmark_instrument(db)
        if benchmark is not None and benchmark.id not in {i.id for i in instruments}:
            instruments.append(benchmark)

        # Same reasoning as the benchmark above: a watchlisted instrument is
        # never held, so it never appears in the Position-joined query either
        # — without this, the watchlist's prices would only ever update from
        # the one-off fetch on `POST /api/watchlist`, never from this button.
        seen = {i.id for i in instruments}
        instruments.extend(w for w in _watchlist_instruments(db) if w.id not in seen)

        # Same reasoning again for screener candidates: they're never held or
        # watchlisted either (see `routers/screener.py`'s module docstring),
        # so without this a candidate's price would only ever update from the
        # one-off fetch on `POST /api/screener`, never from this button.
        seen = {i.id for i in instruments}
        instruments.extend(c for c in _screener_instruments(db) if c.id not in seen)

    report = refresh_many(
        db,
        instruments,
        get_provider_chain(),
        budget_seconds=settings.refresh_budget_seconds,
        force=force,
    )

    # Update last refresh timestamp
    metadata = db.query(AppMetadata).first()
    if not metadata:
        metadata = AppMetadata(last_price_refresh_time=datetime.now(UTC))
        db.add(metadata)
    else:
        metadata.last_price_refresh_time = datetime.now(UTC)
    db.commit()

    return RefreshReportOut(**report.as_dict())


@router.get("/refresh/status", response_model=RefreshStatusOut)
def refresh_status() -> RefreshStatusOut:
    """Live progress of the refresh currently in flight, or the last completed one.

    Meant to be polled every second or so while a ``POST /refresh`` is still
    running: FastAPI serves each sync endpoint on its own thread, so this read
    happens concurrently with that call rather than waiting behind it.
    """
    progress = get_refresh_progress()
    return RefreshStatusOut(
        running=progress.running,
        total=progress.total,
        done=progress.done,
        current_symbol=progress.current_symbol,
        started_at=progress.started_at,
        finished_at=progress.finished_at,
        report=RefreshReportOut(**progress.report.as_dict()) if progress.report else None,
    )


@router.get("/providers", response_model=list[ProviderStatusOut])
def list_providers(db: Session = Depends(get_db)) -> list[ProviderStatusOut]:
    """Which price sources are configured, and how much of the portfolio each can serve.

    Redundancy is only real if you can see it. This answers "what happens if one of
    them stops" without having to break one to find out.
    """
    chain = get_provider_chain()
    instruments = list(
        db.execute(
            select(Instrument).join(Position, Position.instrument_id == Instrument.id).distinct()
        ).scalars()
    )
    refs = [
        InstrumentRef(
            provider_symbol=i.provider_symbol,
            isin=i.isin,
            broker_symbol=i.broker_symbol,
            name=i.name,
            category=i.category,
        )
        for i in instruments
        if not i.not_priceable_reason
    ]

    out = []
    for provider in chain.providers:
        quota_limit = quota_period = quota_used = None
        limit = QUOTA_LIMITS.get(provider.name)
        if limit is not None:
            quota_limit, quota_period = limit
            row = db.execute(
                select(ProviderUsage).where(
                    ProviderUsage.provider == provider.name,
                    ProviderUsage.period_key == period_key_for(quota_period),
                )
            ).scalar_one_or_none()
            quota_used = row.count if row is not None else 0

        out.append(
            ProviderStatusOut(
                name=provider.name,
                enabled=provider.is_enabled(),
                cooling_down=chain.cooldown.is_active(provider.name),
                serves_holdings=sum(1 for ref in refs if provider.can_serve(ref)),
                total_holdings=len(refs),
                quota_limit=quota_limit,
                quota_period=quota_period,
                quota_used=quota_used,
            )
        )
    return out


@router.get("/sparklines", response_model=list[SparklineOut])
def get_sparklines(
    days: int = Query(90, ge=10, le=400),
    db: Session = Depends(get_db),
) -> list[SparklineOut]:
    """Compact close series for every held instrument, in one call.

    One request rather than one per row: the payload is closes only, and the table
    needs all of them at once to draw its sparklines.
    """
    since = datetime.now(UTC).date() - timedelta(days=days)

    rows = db.execute(
        select(PriceBar.instrument_id, PriceBar.bar_date, PriceBar.close)
        .join(Position, Position.instrument_id == PriceBar.instrument_id)
        .where(PriceBar.bar_date >= since, PriceBar.close.is_not(None))
        .order_by(PriceBar.instrument_id, PriceBar.bar_date)
        .distinct()
    ).all()

    instrument_ids = {instrument_id for instrument_id, _, _ in rows}
    actions_by_instrument = load_actions_by_instrument(db, list(instrument_ids))

    series: dict[int, list[float]] = {}
    for instrument_id, bar_date, close in rows:
        factor = price_factor_from(actions_by_instrument.get(instrument_id, []), bar_date)
        series.setdefault(instrument_id, []).append(close * factor)

    return [
        SparklineOut(instrument_id=instrument_id, closes=closes)
        for instrument_id, closes in series.items()
    ]


@router.get("/{instrument_id}/history", response_model=PriceHistoryOut)
def get_history(
    instrument_id: int,
    days: int = Query(365, ge=5, le=2000),
    db: Session = Depends(get_db),
) -> PriceHistoryOut:
    """Daily closes held locally for one instrument.

    Reads the cache only — never triggers a fetch. Drawing a chart must not be able to
    consume the rate-limit budget.
    """
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found.")

    since = datetime.now(UTC).date() - timedelta(days=days)
    bars = list(
        db.execute(
            select(PriceBar)
            .where(PriceBar.instrument_id == instrument_id, PriceBar.bar_date >= since)
            .order_by(PriceBar.bar_date)
        ).scalars()
    )

    actions = load_actions_by_instrument(db, [instrument_id]).get(instrument_id, [])
    return PriceHistoryOut(
        instrument_id=instrument_id,
        broker_symbol=instrument.broker_symbol,
        provider=bars[-1].provider if bars else None,
        points=[
            {
                "date": bar.bar_date.isoformat(),
                "close": bar.close * price_factor_from(actions, bar.bar_date) if bar.close is not None else None,
            }
            for bar in bars
        ],
    )
