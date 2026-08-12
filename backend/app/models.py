"""Modèles ORM.

Choix structurant : les transactions importées sont conservées telles quelles
(table `transactions`, avec la ligne source brute en JSON). Les positions sont
stockées séparément car l'export XTB les fournit déjà consolidées et fiables —
on préfère la valeur du courtier à une reconstitution potentiellement fausse
(splits, frais, multidevise). La ligne brute permet de tout recalculer plus tard
sans redemander le fichier.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- Constantes de domaine (chaînes plutôt qu'Enum SQL, pour rester souple sur SQLite) ---


class TxType:
    BUY = "BUY"
    SELL = "SELL"
    # Position fermée telle que rapportée par le courtier (aller-retour complet).
    # Conservée comme un type distinct plutôt que forcée en BUY/SELL, car l'export
    # ne fournit qu'une ligne agrégée avec son P&L réalisé.
    CLOSED_TRADE = "CLOSED_TRADE"
    DIVIDEND = "DIVIDEND"
    TAX = "TAX"
    FEE = "FEE"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    INTEREST = "INTEREST"
    OTHER = "OTHER"


class MappingStatus:
    RESOLVED = "RESOLVED"  # symbole fournisseur déterminé automatiquement
    MANUAL = "MANUAL"  # corrigé à la main par l'utilisateur
    UNRESOLVED = "UNRESOLVED"  # à corriger — signalé dans l'UI, jamais ignoré


class Source:
    IMPORT = "IMPORT"
    MANUAL = "MANUAL"


class Instrument(Base):
    """Un titre. Pivot entre le symbole du courtier et celui des fournisseurs de données."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Symbole tel qu'il apparaît chez XTB, ex. "AAPL.US", "BMW.DE"
    broker_symbol: Mapped[str] = mapped_column(String(40), unique=True, index=True)

    # Symbole résolu pour les fournisseurs (Yahoo & co), ex. "AAPL", "BMW.DE", "TTE.PA"
    provider_symbol: Mapped[str | None] = mapped_column(String(40), index=True)
    mapping_status: Mapped[str] = mapped_column(String(20), default=MappingStatus.UNRESOLVED)

    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    name: Mapped[str | None] = mapped_column(String(200))

    # Catégorie fournie par le courtier : STOCK, ETF, CFD…
    # Fiable, contrairement à une heuristique sur le symbole : un CFD n'a pas de
    # fondamentaux et ne doit jamais recevoir de score.
    category: Mapped[str | None] = mapped_column(String(20), index=True)

    exchange: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str | None] = mapped_column(String(8))
    country: Mapped[str | None] = mapped_column(String(40))
    sector: Mapped[str | None] = mapped_column(String(80))
    industry: Mapped[str | None] = mapped_column(String(120))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    positions: Mapped[list[Position]] = relationship(back_populates="instrument", cascade="all, delete-orphan")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="instrument")

    def __repr__(self) -> str:  # pragma: no cover - confort de debug
        return f"<Instrument {self.broker_symbol} -> {self.provider_symbol}>"


class ImportBatch(Base):
    """Trace d'un import de fichier courtier — permet l'idempotence et l'audit."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    positions_found: Mapped[int] = mapped_column(Integer, default=0)
    transactions_found: Mapped[int] = mapped_column(Integer, default=0)
    transactions_inserted: Mapped[int] = mapped_column(Integer, default=0)

    # Tout ce que le parser n'a pas su interpréter est remonté ici, jamais avalé en silence.
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    detected_sections: Mapped[list] = mapped_column(JSON, default=list)
    #: Comptes dont l'instantané de positions a été remplacé par cet import.
    accounts: Mapped[list] = mapped_column(JSON, default=list)


class Transaction(Base):
    """Une ligne du journal du courtier, conservée fidèlement."""

    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("external_id", "type", name="uq_tx_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    # Identifiant de l'opération chez le courtier, sert de clé de déduplication
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)

    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    instrument: Mapped[Instrument | None] = relationship(back_populates="transactions")

    type: Mapped[str] = mapped_column(String(20), index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)

    quantity: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)  # montant net dans la devise du compte
    currency: Mapped[str | None] = mapped_column(String(8))
    commission: Mapped[float | None] = mapped_column(Float)
    swap: Mapped[float | None] = mapped_column(Float)

    comment: Mapped[str | None] = mapped_column(Text)

    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    # Ligne d'origine du fichier, pour pouvoir tout rejouer sans réimporter
    raw: Mapped[dict | None] = mapped_column(JSON)


class Position(Base):
    """Une position ouverte. Provient de l'export courtier ou d'une saisie manuelle."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    instrument: Mapped[Instrument] = relationship(back_populates="positions")

    external_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(20), default=Source.IMPORT)

    # Compte d'origine (colonne « Product » de l'export : « My Trades », « PEA »…).
    # Un export ne couvre qu'un compte : le remplacement de l'instantané est donc
    # limité aux comptes présents dans le fichier, sinon importer le relevé PEA
    # effacerait les positions du compte titres.
    account: Mapped[str | None] = mapped_column(String(40), index=True)

    quantity: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)  # prix de revient, devise de l'instrument
    currency: Mapped[str | None] = mapped_column(String(8))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Nombre de lots agrégés dans cette position (l'export les détaille ligne à ligne).
    lots_count: Mapped[int] = mapped_column(Integer, default=1)

    # Valeurs telles que rapportées par le courtier (devise du compte).
    # On les affiche comme référence plutôt que de les recalculer à l'aveugle.
    broker_gross_pl: Mapped[float | None] = mapped_column(Float)
    broker_net_pl: Mapped[float | None] = mapped_column(Float)
    broker_net_pl_pct: Mapped[float | None] = mapped_column(Float)
    broker_purchase_value: Mapped[float | None] = mapped_column(Float)
    broker_market_value: Mapped[float | None] = mapped_column(Float)
    market_price: Mapped[float | None] = mapped_column(Float)
    commission: Mapped[float | None] = mapped_column(Float)
    swap: Mapped[float | None] = mapped_column(Float)

    comment: Mapped[str | None] = mapped_column(Text)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    raw: Mapped[dict | None] = mapped_column(JSON)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class WatchlistItem(Base):
    """Un titre suivi mais non détenu — l'équivalent local des favoris xStation.

    L'API XTB ayant été supprimée le 14/03/2025, les favoris ne peuvent pas être
    récupérés automatiquement : cette liste est tenue dans l'application.
    """

    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), unique=True, index=True)
    instrument: Mapped[Instrument] = relationship()

    added_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    target_entry_price: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)


class SymbolOverride(Base):
    """Correction manuelle d'une correspondance symbole courtier -> symbole fournisseur."""

    __tablename__ = "symbol_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    broker_symbol: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    provider_symbol: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PriceBar(Base):
    """Chandelier journalier mis en cache localement (phase 2)."""

    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("instrument_id", "bar_date", name="uq_bar"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    bar_date: Mapped[date] = mapped_column(Date, index=True)

    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)

    # Fournisseur ayant réellement servi la donnée — affiché dans l'UI
    provider: Mapped[str | None] = mapped_column(String(30))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
