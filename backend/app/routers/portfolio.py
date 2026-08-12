"""Endpoints du portefeuille : consultation, saisie manuelle, correction de mapping."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import get_db
from app.ingest.service import get_or_create_instrument
from app.models import ImportBatch, Instrument, MappingStatus, Position, Source, SymbolOverride
from app.schemas import (
    AccountTotals,
    InstrumentOut,
    ManualPositionIn,
    PortfolioOut,
    PortfolioTotals,
    PositionOut,
    SymbolOverrideIn,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _aggregate(positions: list[Position]) -> tuple[float, float, int, int]:
    """Somme valeur de marché et résultat latent. Retourne (valeur, P&L, comptées, exclues).

    Une position dépourvue de valorisation est **exclue** du total plutôt que comptée
    à zéro : un total faux ayant l'apparence d'un total juste est pire qu'un total
    explicitement partiel.
    """
    market_value = 0.0
    unrealized = 0.0
    counted = 0
    excluded = 0

    for position in positions:
        if position.broker_market_value is None or position.broker_net_pl is None:
            excluded += 1
            continue
        market_value += position.broker_market_value
        unrealized += position.broker_net_pl
        counted += 1

    return market_value, unrealized, counted, excluded


def _compute_totals(positions: list[Position], base_currency: str) -> PortfolioTotals:
    market_value, unrealized, counted, excluded = _aggregate(positions)

    if counted == 0:
        return PortfolioTotals(
            base_currency=base_currency,
            positions_count=len(positions),
            has_incomplete_data=bool(positions),
            excluded_positions=excluded,
        )

    # L'export ne donne pas de valeur d'achat pour les positions ouvertes : elle se
    # déduit exactement de la valeur de marché et du résultat latent, tous deux
    # exprimés dans la devise du compte.
    invested = market_value - unrealized

    return PortfolioTotals(
        base_currency=base_currency,
        positions_count=len(positions),
        market_value=round(market_value, 2),
        invested_value=round(invested, 2),
        unrealized_pl=round(unrealized, 2),
        unrealized_pl_pct=round(unrealized / invested * 100, 2) if invested else None,
        has_incomplete_data=excluded > 0,
        excluded_positions=excluded,
    )


def _compute_account_totals(positions: list[Position]) -> list[AccountTotals]:
    """Détaille les totaux par compte : un export XTB ne couvre qu'un compte à la fois."""
    by_account: dict[str, list[Position]] = defaultdict(list)
    for position in positions:
        by_account[position.account or "—"].append(position)

    results: list[AccountTotals] = []
    for account, account_positions in sorted(by_account.items()):
        market_value, unrealized, counted, _ = _aggregate(account_positions)
        invested = market_value - unrealized

        results.append(
            AccountTotals(
                account=account,
                positions_count=len(account_positions),
                market_value=round(market_value, 2) if counted else None,
                invested_value=round(invested, 2) if counted else None,
                unrealized_pl=round(unrealized, 2) if counted else None,
                unrealized_pl_pct=round(unrealized / invested * 100, 2)
                if counted and invested
                else None,
            )
        )

    return results


@router.get("", response_model=PortfolioOut)
def get_portfolio(db: Session = Depends(get_db)) -> PortfolioOut:
    positions = list(
        db.execute(
            select(Position).options(joinedload(Position.instrument))
        ).scalars()
    )

    # Les CFD sont volontairement exclus : ils n'ont pas de fondamentaux, leur
    # absence de correspondance est normale et les lister serait du bruit.
    unresolved = list(
        db.execute(
            select(Instrument).where(
                Instrument.mapping_status == MappingStatus.UNRESOLVED,
                Instrument.category.is_distinct_from("CFD"),
            )
        ).scalars()
    )

    last_batch = db.execute(
        select(ImportBatch).order_by(ImportBatch.imported_at.desc()).limit(1)
    ).scalar_one_or_none()

    return PortfolioOut(
        totals=_compute_totals(positions, get_settings().base_currency),
        accounts=_compute_account_totals(positions),
        positions=[PositionOut.model_validate(p) for p in positions],
        unresolved_symbols=[InstrumentOut.model_validate(i) for i in unresolved],
        last_import_at=last_batch.imported_at if last_batch else None,
    )


@router.post("/positions", response_model=PositionOut, status_code=status.HTTP_201_CREATED)
def create_manual_position(payload: ManualPositionIn, db: Session = Depends(get_db)) -> PositionOut:
    """Ajoute une position saisie à la main (titre absent de l'export, ou autre courtier)."""
    instrument = get_or_create_instrument(db, payload.broker_symbol, currency=payload.currency)

    position = Position(
        instrument_id=instrument.id,
        source=Source.MANUAL,
        account=payload.account,
        quantity=payload.quantity,
        avg_price=payload.avg_price,
        currency=payload.currency or instrument.currency,
        opened_at=payload.opened_at,
        comment=payload.comment,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return PositionOut.model_validate(position)


@router.delete(
    "/positions/{position_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_position(position_id: int, db: Session = Depends(get_db)) -> Response:
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Position introuvable.")
    db.delete(position)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/symbol-overrides", response_model=InstrumentOut)
def set_symbol_override(payload: SymbolOverrideIn, db: Session = Depends(get_db)) -> InstrumentOut:
    """Corrige à la main la correspondance entre un symbole XTB et celui des fournisseurs.

    Nécessaire pour les cas que la conversion de suffixe ne peut pas deviner,
    typiquement les actions à classes multiples (``ERICB.SE`` → ``ERIC-B.ST``).
    """
    broker_symbol = payload.broker_symbol.strip().upper()
    provider_symbol = payload.provider_symbol.strip().upper()

    override = db.execute(
        select(SymbolOverride).where(SymbolOverride.broker_symbol == broker_symbol)
    ).scalar_one_or_none()

    if override is None:
        override = SymbolOverride(broker_symbol=broker_symbol, provider_symbol=provider_symbol)
        db.add(override)
    else:
        override.provider_symbol = provider_symbol
    override.note = payload.note

    instrument = db.execute(
        select(Instrument).where(Instrument.broker_symbol == broker_symbol)
    ).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun instrument connu pour le symbole « {broker_symbol} ».",
        )

    instrument.provider_symbol = provider_symbol
    instrument.mapping_status = MappingStatus.MANUAL

    db.commit()
    db.refresh(instrument)
    return InstrumentOut.model_validate(instrument)
