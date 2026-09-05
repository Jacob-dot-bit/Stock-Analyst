"""Loads and validates ``scoring.yaml`` — the scoring engine's tunable weights.

The first YAML consumer in this app (`pyyaml` was already a dependency, added
ahead of this feature). Validated into Pydantic models rather than read as a raw
dict so a typo in the file fails loudly at the first request that needs it, not
silently mid-computation. See DEVLOG "Decision 3r.1".
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from app.config import get_settings


class MetricConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight: float
    kind: Literal["linear", "binary"] = "linear"
    #: Required (and only meaningful) for `kind: linear`.
    direction: Literal["higher_is_better", "lower_is_better"] | None = None
    full_at: float | None = None
    zero_at: float | None = None
    #: Minimum fiscal years of history required before this metric is attempted
    #: at all (growth metrics only) — below this, dropped, not scored on a thin
    #: series.
    min_years: int | None = None

    @model_validator(mode="after")
    def _linear_metrics_need_their_band(self) -> "MetricConfig":
        if self.kind == "linear" and (
            self.direction is None or self.full_at is None or self.zero_at is None
        ):
            raise ValueError("a linear metric needs direction, full_at and zero_at")
        return self


class PillarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight: float
    metrics: dict[str, MetricConfig]


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    pillars: dict[str, PillarConfig]


@lru_cache
def get_scoring_config() -> ScoringConfig:
    path = get_settings().scoring_config_path
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return ScoringConfig.model_validate(raw)
