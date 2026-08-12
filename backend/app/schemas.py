"""Schémas Pydantic exposés par l'API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    broker_symbol: str
    provider_symbol: str | None
    mapping_status: str
    name: str | None
    category: str | None
    currency: str | None
    country: str | None
    sector: str | None


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument: InstrumentOut
    source: str
    account: str | None
    quantity: float
    avg_price: float
    currency: str | None
    opened_at: datetime | None
    lots_count: int

    # Valeurs rapportées par le courtier, dans la devise du compte.
    broker_market_value: float | None
    broker_net_pl: float | None
    broker_net_pl_pct: float | None
    broker_gross_pl: float | None
    broker_purchase_value: float | None
    market_price: float | None
    commission: float | None
    swap: float | None
    comment: str | None


class AccountTotals(BaseModel):
    """Totaux d'un compte (« My Trades », « PEA »…)."""

    account: str
    positions_count: int
    market_value: float | None = None
    invested_value: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_pct: float | None = None


class PortfolioTotals(BaseModel):
    """Totaux du portefeuille.

    Les montants proviennent des valeurs rapportées par le courtier, déjà exprimées
    dans la devise du compte. Aucune conversion de change n'est appliquée : convertir
    sans taux fiable produirait des totaux faux.

    L'export ne fournit pas de « valeur d'achat » pour les positions ouvertes ; elle
    est donc déduite exactement par ``valeur de marché − résultat latent``, les deux
    étant dans la même devise.
    """

    base_currency: str
    positions_count: int
    market_value: float | None = None
    invested_value: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_pct: float | None = None
    has_incomplete_data: bool = Field(
        default=False,
        description="Vrai si au moins une position ne fournit pas les valeurs nécessaires au total.",
    )
    excluded_positions: int = Field(
        default=0, description="Positions exclues des totaux faute de valorisation."
    )


class PortfolioOut(BaseModel):
    totals: PortfolioTotals
    accounts: list[AccountTotals]
    positions: list[PositionOut]
    unresolved_symbols: list[InstrumentOut]
    last_import_at: datetime | None


class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    imported_at: datetime
    positions_found: int
    transactions_found: int
    transactions_inserted: int
    warnings: list[str]
    detected_sections: list[str]
    accounts: list[str]


class ManualPositionIn(BaseModel):
    broker_symbol: str = Field(min_length=1, max_length=40)
    quantity: float
    avg_price: float
    currency: str | None = None
    account: str | None = None
    opened_at: datetime | None = None
    comment: str | None = None


class SymbolOverrideIn(BaseModel):
    broker_symbol: str = Field(min_length=1, max_length=40)
    provider_symbol: str = Field(min_length=1, max_length=40)
    note: str | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str | None
    type: str
    executed_at: datetime | None
    quantity: float | None
    price: float | None
    amount: float | None
    currency: str | None
    comment: str | None
    instrument: InstrumentOut | None
