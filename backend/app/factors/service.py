"""Carhart four-factor exposure for held positions — an explanatory,
descriptive indicator (what has historically driven a holding's returns),
never a prediction. Consistent with this app's fact-based design: a factor
loading states what has been true of the past, it does not forecast
anything. See DEVLOG "Decision 3u.24".

**Held positions only** (not Watchlist/Screener/Discovery) and **daily
returns** (not monthly) — both by explicit user choice, given the 5-year
daily price history `prediction/service.py::backfill_history` already
built for phase 1/2 of the (separate) Discovery prediction work.

**Region-matched, always.** A US stock's returns are regressed against
Kenneth French's US factor series; a European stock's against the Europe
series. Never mixed — applying one region's risk-factor premia to another
region's returns would misattribute the loadings to something that was
never actually driving them. An instrument whose country isn't covered by
either published daily series reports `not_applicable_reason`, never a
guessed region.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import statsmodels.api as sm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.corporate_actions.service import load_actions_by_instrument, price_factor_from
from app.models import CorporateAction, FactorReturn, Instrument, Position, PriceBar
from app.providers import kenneth_french

#: ISO country codes covered by Kenneth French's "Europe" daily series —
#: the developed European markets his construction actually draws from.
EUROPEAN_COUNTRIES = {
    "FR", "DE", "NL", "BE", "IT", "ES", "PT", "IE", "AT", "FI",
    "SE", "DK", "NO", "CH", "GB", "LU", "GR", "PL", "CZ",
}

#: Below this many overlapping (instrument return, factor return) days, a
#: four-parameter regression is more noise than signal — reported as
#: `not_applicable`, never fit anyway.
MIN_OBSERVATIONS = 60


def region_for_instrument(instrument: Instrument) -> str | None:
    """"US" | "EUROPE" | `None` — `None` means no published daily factor
    series covers this instrument's country, not that one wasn't checked."""
    if instrument.country == "US":
        return "US"
    if instrument.country in EUROPEAN_COUNTRIES:
        return "EUROPE"
    return None


def import_factor_data(db: Session) -> dict[str, int]:
    """One-off (or occasional re-run) fetch of both regions' daily factor
    series from Kenneth French's Data Library into `FactorReturn`. Safe to
    re-run: upserts by (region, date), never duplicates."""
    imported = 0
    already_present = 0
    for region in ("US", "EUROPE"):
        existing_dates = {
            row.return_date
            for row in db.execute(select(FactorReturn).where(FactorReturn.region == region)).scalars()
        }
        for row in kenneth_french.fetch_region(region):
            if row["return_date"] in existing_dates:
                already_present += 1
                continue
            db.add(FactorReturn(region=region, **row))
            imported += 1
    db.commit()
    return {"imported": imported, "already_present": already_present}


@dataclass
class FactorLoadings:
    instrument_id: int
    region: str | None
    n_observations: int
    start_date: date | None
    end_date: date | None
    alpha: float | None
    beta_mkt: float | None
    beta_smb: float | None
    beta_hml: float | None
    beta_mom: float | None
    r_squared: float | None
    alpha_p_value: float | None
    #: "no_region_match" | "insufficient_history" | `None` (regression ran).
    not_applicable_reason: str | None

    def as_dict(self) -> dict:
        return {
            "instrument_id": self.instrument_id,
            "region": self.region,
            "n_observations": self.n_observations,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "alpha": self.alpha,
            "beta_mkt": self.beta_mkt,
            "beta_smb": self.beta_smb,
            "beta_hml": self.beta_hml,
            "beta_mom": self.beta_mom,
            "r_squared": self.r_squared,
            "alpha_p_value": self.alpha_p_value,
            "not_applicable_reason": self.not_applicable_reason,
        }


def _not_applicable(instrument_id: int, region: str | None, reason: str) -> FactorLoadings:
    return FactorLoadings(
        instrument_id=instrument_id,
        region=region,
        n_observations=0,
        start_date=None,
        end_date=None,
        alpha=None,
        beta_mkt=None,
        beta_smb=None,
        beta_hml=None,
        beta_mom=None,
        r_squared=None,
        alpha_p_value=None,
        not_applicable_reason=reason,
    )


def _daily_returns(bars: list[PriceBar], actions: list[CorporateAction] | None = None) -> dict[date, float]:
    """Split-adjusted day-over-day returns — the single most split-sensitive
    computation in this feature: an unadjusted split reads as one impossible
    daily return that would dominate the whole regression. See
    `app/corporate_actions/service.py::price_factor_from`."""
    ordered = sorted(bars, key=lambda b: b.bar_date)
    actions = actions or []
    adjusted = [(b.bar_date, b.close * price_factor_from(actions, b.bar_date)) for b in ordered if b.close]
    returns: dict[date, float] = {}
    for (_, prev_close), (curr_date, curr_close) in zip(adjusted, adjusted[1:]):
        if prev_close:
            returns[curr_date] = (curr_close / prev_close) - 1.0
    return returns


def _load_region_factors(db: Session, region: str) -> dict[date, FactorReturn]:
    return {
        row.return_date: row
        for row in db.execute(select(FactorReturn).where(FactorReturn.region == region)).scalars()
    }


def compute_factor_loadings(
    db: Session,
    instrument: Instrument,
    region_factors: dict[str, dict[date, FactorReturn]] | None = None,
    corporate_actions: list[CorporateAction] | None = None,
) -> FactorLoadings:
    """Carhart four-factor OLS regression of `instrument`'s daily excess
    returns against its region-matched factor series. Cache-only — never
    triggers a price or factor-data fetch.

    `region_factors`, when given, must map region -> {date: FactorReturn}
    (see `_load_region_factors`) — passed in by `compute_held_position_
    loadings` so a region's ~17,500 rows are loaded from the database
    once and reused across every instrument that region covers, rather
    than reloaded from scratch per instrument (a real N+1 that made the
    full-portfolio endpoint hang for tens of seconds — found live).
    `corporate_actions`, when given, is this instrument's own split history
    (see `load_actions_by_instrument`) — an unadjusted split would otherwise
    dominate the regression as one impossible daily return."""
    region = region_for_instrument(instrument)
    if region is None:
        return _not_applicable(instrument.id, None, "no_region_match")

    bars = list(db.execute(select(PriceBar).where(PriceBar.instrument_id == instrument.id)).scalars())
    instrument_returns = _daily_returns(bars, corporate_actions)

    factor_rows = (region_factors or {}).get(region) or _load_region_factors(db, region)

    dates = sorted(set(instrument_returns) & set(factor_rows))
    if len(dates) < MIN_OBSERVATIONS:
        return _not_applicable(instrument.id, region, "insufficient_history")

    y = np.array([instrument_returns[d] - factor_rows[d].rf for d in dates])
    X = np.array([[factor_rows[d].mkt_rf, factor_rows[d].smb, factor_rows[d].hml, factor_rows[d].mom] for d in dates])
    X = sm.add_constant(X)
    fitted = sm.OLS(y, X).fit()

    return FactorLoadings(
        instrument_id=instrument.id,
        region=region,
        n_observations=len(dates),
        start_date=dates[0],
        end_date=dates[-1],
        alpha=float(fitted.params[0]),
        beta_mkt=float(fitted.params[1]),
        beta_smb=float(fitted.params[2]),
        beta_hml=float(fitted.params[3]),
        beta_mom=float(fitted.params[4]),
        r_squared=float(fitted.rsquared),
        alpha_p_value=float(fitted.pvalues[0]),
        not_applicable_reason=None,
    )


def compute_held_position_loadings(db: Session) -> list[tuple[Instrument, FactorLoadings]]:
    """Carhart four-factor loadings for every currently held instrument —
    the scope explicitly chosen for this feature (not Watchlist/Screener/
    Discovery). Each region's factor series is loaded from the database
    exactly once and shared across every instrument in that region — see
    `compute_factor_loadings`'s docstring for the N+1 this replaced."""
    instruments = list(
        db.execute(
            select(Instrument).join(Position, Position.instrument_id == Instrument.id).distinct()
        ).scalars()
    )
    region_factors = {region: _load_region_factors(db, region) for region in ("US", "EUROPE")}
    actions_by_instrument = load_actions_by_instrument(db, [i.id for i in instruments])
    return [
        (instrument, compute_factor_loadings(db, instrument, region_factors, actions_by_instrument.get(instrument.id)))
        for instrument in instruments
    ]
