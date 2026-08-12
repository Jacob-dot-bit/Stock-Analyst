"""Pydantic schemas exposed by the API.

The API is language-neutral: it never returns prose. Anything meant to be read by a
human is a ``MessageOut`` — a code plus its parameters — which the client renders in
the user's language. See ``app/messages.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MessageOut(BaseModel):
    """A translatable message. The client owns the wording."""

    code: str
    params: dict[str, Any] = Field(default_factory=dict)


class SectionOut(BaseModel):
    """What one sheet of the imported workbook contained."""

    sheet: str
    kind: str
    count: int
    #: Raw row count before aggregation. Larger than ``count`` on open positions,
    #: where the export lists one aggregate row per holding plus one row per lot.
    source_rows: int


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
    #: Set once a provider actually returned data for this symbol. Until then the
    #: mapping is only a plausible conversion, and the UI says so.
    verified_at: datetime | None = None
    verified_provider: str | None = None


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

    # Values reported by the broker, in the account currency.
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
    """Totals for one account ("My Trades", "PEA"...)."""

    account: str
    positions_count: int
    market_value: float | None = None
    invested_value: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_pct: float | None = None


class PortfolioTotals(BaseModel):
    """Portfolio totals.

    Amounts come from the values reported by the broker, already expressed in the
    account currency. No FX conversion is applied: converting without a trustworthy
    rate would produce wrong totals.

    The export provides no "purchase value" for open positions, so it is derived
    exactly as ``market value − unrealised P&L``, both being in the same currency.
    """

    base_currency: str
    positions_count: int
    market_value: float | None = None
    invested_value: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_pct: float | None = None
    has_incomplete_data: bool = Field(
        default=False,
        description="True when at least one position lacks the values needed for the totals.",
    )
    excluded_positions: int = Field(
        default=0, description="Positions left out of the totals for lack of valuation."
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
    warnings: list[MessageOut]
    sections: list[SectionOut]
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


class RefreshReportOut(BaseModel):
    """Outcome of a price refresh.

    Partial success is the normal case: free providers throttle, so a run reports what
    it achieved and how many instruments are still waiting.
    """

    outcomes: list[MessageOut]
    updated: int
    skipped: int
    failed: int
    remaining: int


class PricePoint(BaseModel):
    date: str
    close: float | None


class PriceHistoryOut(BaseModel):
    instrument_id: int
    broker_symbol: str
    #: Which provider served the most recent bar — surfaced so a number on screen can
    #: always be traced back to its source.
    provider: str | None
    points: list[PricePoint]


class SparklineOut(BaseModel):
    """Closes only, for drawing a small trend line next to a position."""

    instrument_id: int
    closes: list[float]
