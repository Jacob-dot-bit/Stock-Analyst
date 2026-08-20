"""Tracking how much of each provider's free-tier quota has been used.

Only providers with a *documented* limit are tracked here — the keyless
providers (Yahoo, Boursorama, Frankfurt, Eoddata, Finviz) have no
stated quota anywhere, even in their own provider files, so there is no limit
to show a "used/limit" figure against. Polygon and Alpha Vantage are
per-**minute** limits (5 req/min) rather than daily/monthly — a coarser grain
than the others, but still real, requested information (see DEVLOG "Decision
3m.2"): the minute key just rolls over sixty times an hour instead of once a
day. See DEVLOG "Decision 3m.1" for the original day/month tracking.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProviderUsage

#: Refreshes now run several instruments concurrently (DEVLOG "Decision 3n.1"),
#: each in its own DB session — without this, two threads incrementing the same
#: provider's counter at once is a classic lost-update race (both read count=5,
#: both write count=6). A blunt process-wide lock is correct here since a real
#: provider call is infrequent and never the bottleneck.
_usage_lock = threading.Lock()

#: provider name -> (limit, "day" | "month" | "minute").
QUOTA_LIMITS: dict[str, tuple[int, str]] = {
    "twelvedata": (800, "day"),
    "fmp": (250, "day"),
    "tiingo": (500, "day"),
    "barchart": (400, "day"),
    "intrinio": (500, "day"),
    "eodhd": (20, "day"),
    "marketstack": (100, "month"),
    "polygon": (5, "minute"),
    "alpha_vantage": (5, "minute"),
}


def period_key_for(period: str) -> str:
    now = datetime.now(UTC)
    if period == "month":
        return now.strftime("%Y-%m")
    if period == "minute":
        return now.strftime("%Y-%m-%d %H:%M")
    return now.strftime("%Y-%m-%d")


def record_usage(db: Session, provider_name: str) -> None:
    """Count one real request against `provider_name`'s quota, if it has one.

    Commits immediately rather than only flushing: some callers (e.g.
    `enrich_sectors`) only commit their own changes conditionally, and an
    increment that merely flushed would be silently discarded on a request
    where that condition never triggered. A provider call is infrequent
    enough that a small extra commit per call costs nothing at this app's
    scale.
    """
    limit = QUOTA_LIMITS.get(provider_name)
    if limit is None:
        return

    _, period = limit
    key = period_key_for(period)

    with _usage_lock:
        row = db.execute(
            select(ProviderUsage).where(
                ProviderUsage.provider == provider_name, ProviderUsage.period_key == key
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProviderUsage(provider=provider_name, period_key=key, count=0)
            db.add(row)
        row.count += 1
        db.commit()


def record_bytes(db: Session, provider_name: str, num_bytes: int) -> None:
    """Accumulate response bytes against `provider_name`'s current period.

    Purely descriptive — no provider here exposes a remaining-bandwidth
    balance to check against, so this cannot enforce anything the way
    `record_usage`'s request count could in principle. It exists so a
    bandwidth-based quota (FMP's free tier caps at 500MB/30 rolling days,
    entirely separate from and untracked by its 250 req/day request count —
    see DEVLOG "Decision 3u.41") is visible in `GET /api/settings/providers`
    before the next silent blackout, instead of only discoverable by a live
    `curl` after the fact. A provider that has no entry in `QUOTA_LIMITS`
    still accumulates bytes here (unlike `record_usage`, which no-ops) —
    the byte count is informational regardless of whether a request-count
    limit is documented for that provider.

    Always keyed by calendar day, independent of whatever period
    `QUOTA_LIMITS` uses for that provider's request count (e.g. FMP's own
    count resets daily, but its bandwidth cap is a 30-*rolling*-day window —
    there is no clean single counter for a rolling window without a
    scheduled reset job, so daily rows are kept instead and a caller sums
    the last 30 days' `bytes_used` on demand).
    """
    key = period_key_for("day")

    with _usage_lock:
        row = db.execute(
            select(ProviderUsage).where(
                ProviderUsage.provider == provider_name, ProviderUsage.period_key == key
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProviderUsage(provider=provider_name, period_key=key, count=0, bytes_used=0)
            db.add(row)
        row.bytes_used += num_bytes
        db.commit()
