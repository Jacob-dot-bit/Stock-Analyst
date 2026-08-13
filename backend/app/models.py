"""ORM models.

Structural choice: imported transactions are kept verbatim (``transactions`` table,
with the raw source row stored as JSON). Positions live in their own table because
the XTB export already provides them consolidated and reliable — the broker's own
figures beat a reconstruction that could go wrong on splits, fees or multi-currency
holdings. Keeping the raw row means everything can be recomputed later without
asking the user for the file again.
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


# --- Domain constants (plain strings rather than SQL enums, to stay flexible on SQLite) ---


class TxType:
    BUY = "BUY"
    SELL = "SELL"
    # A closed position as reported by the broker (a complete round trip). Kept as its
    # own type rather than forced into BUY/SELL, because the export only provides one
    # aggregate row carrying the realised P&L.
    CLOSED_TRADE = "CLOSED_TRADE"
    DIVIDEND = "DIVIDEND"
    TAX = "TAX"
    FEE = "FEE"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    INTEREST = "INTEREST"
    OTHER = "OTHER"


class MappingStatus:
    RESOLVED = "RESOLVED"  # provider symbol derived automatically, never yet tested
    VERIFIED = "VERIFIED"  # a provider actually returned data for this symbol
    MANUAL = "MANUAL"  # corrected by hand by the user
    UNRESOLVED = "UNRESOLVED"  # needs fixing — surfaced in the UI, never ignored


class Source:
    IMPORT = "IMPORT"
    MANUAL = "MANUAL"


class Instrument(Base):
    """A tradable instrument. The pivot between broker symbol and provider symbol."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Symbol as it appears at XTB, e.g. "AAPL.US", "BMW.DE"
    broker_symbol: Mapped[str] = mapped_column(String(40), unique=True, index=True)

    # Symbol resolved for data providers (Yahoo & co), e.g. "AAPL", "BMW.DE", "TTE.PA"
    provider_symbol: Mapped[str | None] = mapped_column(String(40), index=True)
    mapping_status: Mapped[str] = mapped_column(String(20), default=MappingStatus.UNRESOLVED)

    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    name: Mapped[str | None] = mapped_column(String(200))

    # Category supplied by the broker: STOCK, ETF, CFD...
    # Reliable, unlike a heuristic on the symbol: a CFD has no fundamentals and must
    # never be scored.
    category: Mapped[str | None] = mapped_column(String(20), index=True)

    exchange: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str | None] = mapped_column(String(8))
    country: Mapped[str | None] = mapped_column(String(40))
    sector: Mapped[str | None] = mapped_column(String(80))
    industry: Mapped[str | None] = mapped_column(String(120))

    # Set the first time a provider actually returns data for this symbol. Until
    # then the mapping is only a plausible suffix conversion, and is shown as such.
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_provider: Mapped[str | None] = mapped_column(String(30))

    # Set when the instrument cannot have a market price at all — not "no source
    # found it" but "no price exists". A non-transferable CVR is the case that
    # prompted this: it has no ticker, no listing and no market by construction, so
    # counting it as a retrieval failure would be permanently misleading.
    not_priceable_reason: Mapped[str | None] = mapped_column(String(40))

    # When a provider was last *asked* about this instrument — which is not the same
    # as the date of the newest bar. Free feeds lag by a day or more, so "newest bar
    # is older than today" is permanently true and cannot be used to decide freshness:
    # doing so re-fetches everything on every run and burns the daily quota.
    prices_checked_at: Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    positions: Mapped[list[Position]] = relationship(back_populates="instrument", cascade="all, delete-orphan")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="instrument")

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return f"<Instrument {self.broker_symbol} -> {self.provider_symbol}>"


class ImportBatch(Base):
    """Record of one broker-file import — enables idempotency and auditing."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    positions_found: Mapped[int] = mapped_column(Integer, default=0)
    transactions_found: Mapped[int] = mapped_column(Integer, default=0)
    transactions_inserted: Mapped[int] = mapped_column(Integer, default=0)

    #: Anything the parser could not interpret, as {code, params} message objects.
    #: Never swallowed silently, and never pre-translated: the client renders them.
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    #: What each sheet turned out to contain, as {sheet, kind, count, source_rows}.
    sections: Mapped[list] = mapped_column(JSON, default=list)
    #: Accounts whose position snapshot this import replaced.
    accounts: Mapped[list] = mapped_column(JSON, default=list)


class Transaction(Base):
    """One line of the broker ledger, preserved faithfully."""

    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("external_id", "type", name="uq_tx_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    # The broker's operation id; used as the deduplication key
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)

    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    instrument: Mapped[Instrument | None] = relationship(back_populates="transactions")

    type: Mapped[str] = mapped_column(String(20), index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)

    quantity: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)  # net amount in the account currency
    currency: Mapped[str | None] = mapped_column(String(8))
    commission: Mapped[float | None] = mapped_column(Float)
    swap: Mapped[float | None] = mapped_column(Float)

    comment: Mapped[str | None] = mapped_column(Text)

    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    # The original file row, so everything can be replayed without re-importing
    raw: Mapped[dict | None] = mapped_column(JSON)


class Position(Base):
    """An open holding. Comes from a broker export or from manual entry."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    instrument: Mapped[Instrument] = relationship(back_populates="positions")

    external_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(20), default=Source.IMPORT)

    # Originating account (the export's "Product" column: "My Trades", "PEA"...).
    # One export only covers one account, so snapshot replacement is limited to the
    # accounts present in the file — otherwise importing the PEA statement would wipe
    # the brokerage account's holdings.
    account: Mapped[str | None] = mapped_column(String(40), index=True)

    quantity: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)  # average cost, instrument currency
    currency: Mapped[str | None] = mapped_column(String(8))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)

    # How many lots this holding aggregates (the export lists them row by row).
    lots_count: Mapped[int] = mapped_column(Integer, default=1)

    # Values as reported by the broker (account currency). Shown as the reference
    # rather than recomputed blindly.
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
    """A watched but unheld instrument — the local equivalent of xStation favourites.

    Since the XTB API was shut down on 2025-03-14, favourites cannot be fetched
    automatically: this list is maintained inside the application.
    """

    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), unique=True, index=True)
    instrument: Mapped[Instrument] = relationship()

    added_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    target_entry_price: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)


class SymbolOverride(Base):
    """A manual correction of a broker-symbol to provider-symbol mapping."""

    __tablename__ = "symbol_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    broker_symbol: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    provider_symbol: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PriceBar(Base):
    """A daily candle cached locally.

    Cached so a refresh only asks providers for the days it does not already have —
    the difference between a handful of requests and one per instrument per run,
    which is what keeps us under free-tier rate limits.
    """

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

    # Which provider actually served this data — surfaced in the UI
    provider: Mapped[str | None] = mapped_column(String(30))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
