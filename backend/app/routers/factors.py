"""Carhart four-factor exposure for held positions — see `app/factors/
service.py`'s module docstring for why this is descriptive, region-matched,
and held-positions-only (DEVLOG "Decision 3u.24")."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.factors.service import compute_held_position_loadings, import_factor_data
from app.schemas import FactorImportOut, FactorLoadingsOut

router = APIRouter(prefix="/api/factors", tags=["factors"])


@router.post("/import", response_model=FactorImportOut)
def import_factors_endpoint(db: Session = Depends(get_db)) -> FactorImportOut:
    """One-off (or occasional re-run) fetch of Kenneth French's daily
    US and Europe factor series. Safe to re-run — upserts by (region,
    date), never duplicates."""
    result = import_factor_data(db)
    return FactorImportOut(**result)


@router.get("", response_model=list[FactorLoadingsOut])
def get_factor_loadings(db: Session = Depends(get_db)) -> list[FactorLoadingsOut]:
    """Carhart four-factor loadings for every currently held instrument.
    Cache-only — never triggers a price or factor-data fetch. An
    instrument outside the two covered regions, or without enough
    overlapping history, reports `not_applicable_reason` rather than a
    guessed or partial regression.
    """
    return [
        FactorLoadingsOut(instrument=instrument, **loadings.as_dict())
        for instrument, loadings in compute_held_position_loadings(db)
    ]
