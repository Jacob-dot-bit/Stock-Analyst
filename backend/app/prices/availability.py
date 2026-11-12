"""What each price source can do right now: cooldown, quota used, and how
much of the held portfolio it could serve. Shown next to each provider on
the Settings page (`GET /api/settings/providers`)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Instrument, Position, ProviderUsage
from app.prices.provider_usage import QUOTA_LIMITS, period_key_for
from app.providers.base import InstrumentRef
from app.providers.registry import get_provider_chain
from app.schemas import ProviderStatusOut


def provider_availability(db: Session) -> list[ProviderStatusOut]:
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
