"""Price refresh and history endpoints."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Instrument, MappingStatus, Position, PriceBar
from app.prices.service import refresh_many
from app.providers.registry import get_provider_chain
from app.providers.base import InstrumentRef
from app.schemas import (
    PriceHistoryOut,
    ProviderStatusOut,
    RefreshReportOut,
    SparklineOut,
)

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.post("/refresh", response_model=RefreshReportOut)
def refresh_prices(
    force: bool = Query(False, description="Re-fetch even instruments already up to date."),
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
    instruments = list(
        db.execute(
            select(Instrument)
            .join(Position, Position.instrument_id == Instrument.id)
            # Unresolved instruments are included when they are known to be
            # unpriceable, so the report can say so instead of omitting them.
            .where(
                (Instrument.mapping_status != MappingStatus.UNRESOLVED)
                | Instrument.not_priceable_reason.is_not(None)
            )
            .distinct()
        ).scalars()
    )

    report = refresh_many(
        db,
        instruments,
        get_provider_chain(),
        budget_seconds=settings.refresh_budget_seconds,
        force=force,
    )
    return RefreshReportOut(**report.as_dict())


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

    return [
        ProviderStatusOut(
            name=provider.name,
            enabled=provider.is_enabled(),
            cooling_down=chain.cooldown.is_active(provider.name),
            serves_holdings=sum(1 for ref in refs if provider.can_serve(ref)),
            total_holdings=len(refs),
        )
        for provider in chain.providers
    ]


@router.get("/sparklines", response_model=list[SparklineOut])
def get_sparklines(
    days: int = Query(90, ge=10, le=400),
    db: Session = Depends(get_db),
) -> list[SparklineOut]:
    """Compact close series for every held instrument, in one call.

    One request rather than one per row: the payload is closes only, and the table
    needs all of them at once to draw its sparklines.
    """
    since = date.today() - timedelta(days=days)

    rows = db.execute(
        select(PriceBar.instrument_id, PriceBar.close)
        .join(Position, Position.instrument_id == PriceBar.instrument_id)
        .where(PriceBar.bar_date >= since, PriceBar.close.is_not(None))
        .order_by(PriceBar.instrument_id, PriceBar.bar_date)
        .distinct()
    ).all()

    series: dict[int, list[float]] = {}
    for instrument_id, close in rows:
        series.setdefault(instrument_id, []).append(close)

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

    since = date.today() - timedelta(days=days)
    bars = list(
        db.execute(
            select(PriceBar)
            .where(PriceBar.instrument_id == instrument_id, PriceBar.bar_date >= since)
            .order_by(PriceBar.bar_date)
        ).scalars()
    )

    return PriceHistoryOut(
        instrument_id=instrument_id,
        broker_symbol=instrument.broker_symbol,
        provider=bars[-1].provider if bars else None,
        points=[{"date": bar.bar_date.isoformat(), "close": bar.close} for bar in bars],
    )
