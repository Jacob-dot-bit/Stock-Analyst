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
    Boolean,
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

    # --- Mintos Core (P2P) aggregate flows — deliberately distinct from
    # DEPOSIT/WITHDRAWAL/INTEREST above. These are internal portfolio
    # movements (auto-invest reinvesting repayments into new loan fragments),
    # not investor cash moving in or out — conflating them with real
    # bank-verified cash flows (e.g. the Dividends view's INTEREST sum) would
    # overstate how much money the investor actually deposited/received. See
    # DEVLOG "Decision 3u.39".
    P2P_INVESTMENT = "P2P_INVESTMENT"
    P2P_PRINCIPAL_REPAYMENT = "P2P_PRINCIPAL_REPAYMENT"
    P2P_INTEREST = "P2P_INTEREST"
    P2P_FEE = "P2P_FEE"
    #: Not a cash flow — one per statement period, preserving the historical
    #: valuation point (`amount` = closing balance) since `Position` only
    #: ever holds the current snapshot, replaced wholesale on each import.
    P2P_SNAPSHOT = "P2P_SNAPSHOT"


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

    # Category supplied by the broker: STOCK, ETF, CFD... Also "P2P" (the
    # single Mintos Core aggregate — see DEVLOG "Decision 3u.39") and "FUND"
    # (Amundi PEG/PERCO employee-savings funds, no public ticker). Reliable,
    # unlike a heuristic on the symbol: a CFD has no fundamentals and must
    # never be scored, and neither should P2P/FUND.
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

    # When `detect_splits`'s bulk scan last checked this instrument — not
    # set by `detect_one`, which is a deliberate, low-volume, user-triggered
    # action meant to always be fresh. Gates a re-check within
    # `CORPORATE_ACTIONS_RECHECK_DAYS` (see `corporate_actions/service.py`):
    # the splits endpoints this app calls return full unbounded history with
    # no server-side range filter, so re-scanning the same ~47 instruments
    # repeatedly is what actually drained FMP's 500MB/30-day bandwidth cap
    # (undetected by its separate, unrelated 250 req/day counter) — see
    # DEVLOG "Decision 3u.41".
    corporate_actions_checked_at: Mapped[datetime | None] = mapped_column(DateTime)

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

    # The export's "Product" column ("My Trades", "PEA"...) — same field Position
    # and Lot already carry. Added for the dividends-by-account view (DEVLOG
    # "Decision 3u.28"); rows imported before this existed are backfilled from
    # `raw` rather than left null, since the account was always present in the
    # source file, just previously discarded on the way in.
    account: Mapped[str | None] = mapped_column(String(40), index=True)

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

    # A short, honest caveat on this position's `broker_net_pl`/
    # `broker_net_pl_pct` when they were derived from an approximation
    # rather than a true, complete cost basis — e.g. Mintos Core P2P's
    # "gain" is real cumulative interest earned, not a price-appreciation
    # P&L; an Amundi fund's is pro-rated from the account's known
    # contributions, which may be missing years never imported. Stored as a
    # `{code, params}` dict, the same language-neutral shape as an import
    # `Message` (see `app/messages.py`'s module docstring) — never prose in
    # one language baked into the database — rendered by the client via
    # `t(note.code, note.params)`. `None` for every ordinary priced
    # position. See DEVLOG "Decision 3u.47".
    performance_note: Mapped[dict | None] = mapped_column(JSON)

    # The date this position's *value* was declared by its source, for a
    # position priced by a periodic broker statement rather than a live
    # market quote — Mintos Core P2P (the latest live-snapshot/PDF import)
    # and Amundi ESR funds (`AmundiFundSnapshot.as_of` of the import that
    # currently wins). `None` for every ordinary priced position, where
    # freshness is instead judged from `Instrument.prices_checked_at`.
    # Drives `routers/portfolio.py::_declared_valuation_note` — separate
    # from `opened_at` ("since held", Decision 3u.49), which answers a
    # different question and must not be reused for this one. See DEVLOG
    # "Decision 3u.50".
    value_as_of: Mapped[date | None] = mapped_column(Date)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class AmundiFundSnapshot(Base):
    """Every fund's disclosed figures from every Amundi import, regardless
    of whether that import's `as_of` ended up superseding the currently
    displayed `Position` for its account.

    Deliberately decoupled from `Position`, which only ever holds one
    current snapshot per account — wholesale-replaced on each newer import
    (DEVLOG "Decision 3u.39"), meaning an *older* statement's fund-level
    detail is otherwise discarded the moment a newer one is imported (only
    `ImportBatch`'s aggregate counts survive it). This table exists so a
    later import that itself carries no gain/loss figure (the Synthese
    export never does — Decision 3u.44) can still compute a fund's real
    gain since its own last known disclosed figure — see DEVLOG "Decision
    3u.48" — instead of only ever falling back to the cruder account-level
    pro-rata approximation (Decision 3u.47).

    Not linked to `Instrument` by foreign key on purpose: a snapshot must
    survive even if the instrument's `broker_symbol` mapping is later
    corrected, and this table is a pure historical log, never joined into
    a live query the way `Position` is.
    """

    __tablename__ = "amundi_fund_snapshots"
    __table_args__ = (UniqueConstraint("broker_symbol", "as_of", name="uq_amundi_fund_snapshot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    broker_symbol: Mapped[str] = mapped_column(String(40), index=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    quantity: Mapped[float] = mapped_column(Float)
    gross_value: Mapped[float] = mapped_column(Float)
    #: `None` when the source import didn't disclose one (the Synthese
    #: export) — this snapshot still records quantity/value for that date,
    #: just isn't itself usable as a "real gain" anchor for a later import.
    estimated_gain_loss: Mapped[float | None] = mapped_column(Float)


class LotType:
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Lot(Base):
    """One actual buy fill — the atomic unit the historical value chart replays.

    Unlike ``Position`` (a broker-reported aggregate, replaced wholesale on each
    import) or ``Transaction`` (a cash-flow ledger), ``Lot`` is an append-only
    record of what was actually bought and when: quantity/open_price/opened_at
    for a still-held lot, plus close_price/closed_at once it is sold. Reusing
    the export's own per-lot rows — already parsed to compute ``Position.opened_at``
    and ``lots_count`` but discarded afterward — is what makes reconstructing a
    real historical portfolio value possible at all (see DEVLOG "Decision 3b.1").

    Never bulk-deleted on re-import the way ``Position`` is: a lot that closed
    between two imports must remain in history even though its ``Position`` row
    is gone. Deduplicated the same way ``Transaction`` is, via ``external_id``.
    """

    __tablename__ = "lots"
    __table_args__ = (UniqueConstraint("external_id", "lot_type", name="uq_lot_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    # No back_populates/cascade from Instrument on purpose: deleting an instrument
    # must not silently erase historical lot data.
    instrument: Mapped[Instrument] = relationship()

    account: Mapped[str | None] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(20), default=Source.IMPORT)

    # OPEN (still held, close_price/closed_at null) or CLOSED (a complete round
    # trip, both populated). A separate column rather than inferred from
    # nullability, so the unique constraint can key on it the same way
    # Transaction keys on (external_id, type): an open lot and its eventual
    # close share the same broker Position ID and would otherwise collide.
    lot_type: Mapped[str] = mapped_column(String(10), index=True)
    # The broker's Position ID (or a synthetic fallback); the deduplication key.
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)

    quantity: Mapped[float] = mapped_column(Float)  # signed — short positions included
    open_price: Mapped[float] = mapped_column(Float)  # instrument currency
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    close_price: Mapped[float | None] = mapped_column(Float)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    currency: Mapped[str | None] = mapped_column(String(8))

    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    raw: Mapped[dict | None] = mapped_column(JSON)


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


class JournalEntry(Base):
    """A user-written investment decision — the reasoning behind a trade
    (or a general/macro note), optionally tied to one instrument. Never
    computed or scored, same posture as `WatchlistItem.note`/
    `PersonalPolicy`. See DEVLOG "Decision 3u.68"."""

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Nullable — an entry can stand alone (a general/macro note) or tie
    #: to a specific holding. No cascade delete, same convention as
    #: `Lot.instrument_id`: losing the entry's context must never silently
    #: delete real history.
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    instrument: Mapped[Instrument | None] = relationship()

    #: The decision's own reasoning — required, this is the entry's whole
    #: point.
    thesis: Mapped[str] = mapped_column(Text)
    #: When the decision was made — set once at creation, never edited
    #: afterward (a historical fact, same "never silently rewritten"
    #: principle DEVLOG itself follows, applied here to user data).
    entry_date: Mapped[date] = mapped_column(Date, default=date.today)
    #: Optional — "revisit this by/on." Drives the "due for review" tag
    #: in the UI; no scheduled reminder/notification in v1.
    review_date: Mapped[date | None] = mapped_column(Date)
    #: Filled in later, once there's something to say about how the
    #: decision played out — nullable, editable independently of `thesis`.
    outcome_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class ScreenerCandidate(Base):
    """A hand-picked candidate to screen for hidden gems — ranked by the same
    composite score as held/watched instruments, but excluded from the
    ranking once it stops being hidden (bought, or moved to the watchlist).
    """

    __tablename__ = "screener_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), unique=True, index=True)
    instrument: Mapped[Instrument] = relationship()

    added_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class DiscoveryCandidate(Base):
    """A candidate surfaced by an automated screening source — the static
    S&P 500 universe, or a Finviz preset scan — a much larger, uncurated
    pool than `ScreenerCandidate`. Never shown to the user directly: only
    the ranked top few (by Value or Growth pillar score) surface in the
    "Découverte" UI, and only once explicitly added via `POST /api/screener`
    does one become a real, tracked hidden gem. See DEVLOG "Decision 3u.20".
    """

    __tablename__ = "discovery_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), unique=True, index=True)
    instrument: Mapped[Instrument] = relationship()

    #: "sp500" | "finviz:insider_buys" | "finviz:oversold" — where this
    #: candidate came from, kept visible rather than blended into one
    #: undifferentiated pool.
    source: Mapped[str] = mapped_column(String(40))
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SymbolOverride(Base):
    """A manual correction of a broker-symbol to provider-symbol mapping."""

    __tablename__ = "symbol_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    broker_symbol: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    provider_symbol: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AllocationTarget(Base):
    """A user-configured target allocation range for one asset class.

    Descriptive only — the app never suggests buying or selling a specific
    security to close a gap, only shows the gap itself (DEVLOG "Decision
    0.3"'s "comments on the score, does not give a second opinion", extended
    to this feature too).
    """

    __tablename__ = "allocation_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    min_pct: Mapped[float] = mapped_column(Float)
    max_pct: Mapped[float] = mapped_column(Float)


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


class CorporateActionType:
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"


class PriceHistoryStatus:
    """Whether a provider's stored PriceBar history for one instrument already
    reflects a given split, decided empirically at creation time — see
    app/corporate_actions/service.py::detect_price_history_status. Found necessary
    because the same provider (twelvedata) delivered already-adjusted history for
    NVDA/GOOGL's real splits but raw, unadjusted history for APLD's — nothing here
    can be assumed uniform across instruments."""

    RAW = "raw"
    ALREADY_ADJUSTED = "already_adjusted"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class CorporateAction(Base):
    """A confirmed stock split or reverse split for one instrument.

    Deliberately does not touch `PriceBar` or `Lot` — both stay raw and
    immutable, same principle already applied to imported transactions
    (module docstring above). All quantity/price correction happens at read
    time, derived from this table, in app/corporate_actions/service.py.
    """

    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    instrument: Mapped[Instrument] = relationship()
    action_type: Mapped[str] = mapped_column(String(20))
    effective_date: Mapped[date] = mapped_column(Date, index=True)

    # New shares per old share: split 10-for-1 -> numerator=10, denominator=1;
    # reverse split 1-for-10 -> numerator=1, denominator=10.
    ratio_numerator: Mapped[float] = mapped_column(Float)
    ratio_denominator: Mapped[float] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(20))  # "yahoo" | "fmp" | "alpha_vantage" | "polygon" | "eodhd" | "manual"
    source_reference: Mapped[str | None] = mapped_column(String(200))
    raw_payload: Mapped[dict | None] = mapped_column(JSON)

    price_history_status: Mapped[str] = mapped_column(String(20), default=PriceHistoryStatus.UNKNOWN)
    detected_price_ratio: Mapped[float | None] = mapped_column(Float)

    # How this row came to be applied — one of `CorporateActionConfidence`'s
    # values, or "manual" for a hand-entered row (the pre-existing default,
    # backfilled onto every row that predates cross-source verification —
    # DEVLOG "Decision 3u.41"). Never itself a gate on anything: only
    # `verified_cross_source`/`verified_three_sources`/`manual`/
    # `manual_promotion` rows ever reach this table at all — a row existing
    # here already means it was either confirmed or entered by hand.
    confidence: Mapped[str] = mapped_column(String(24), default="manual")

    # A denormalized snapshot of which providers/dates/ratios corroborated
    # this event, taken at creation time — e.g.
    # `[{"provider": "alpha_vantage", "event_date": "2022-04-13",
    # "numerator": 1.0, "denominator": 6.0}, ...]`. Lets the history table
    # render "Confirmé par 2 sources" without re-joining
    # `provider_corporate_action_candidates` later; null for rows created
    # before this existed or entered manually with no provider backing.
    corroborating_sources: Mapped[list | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ProviderCorporateActionCandidateStatus:
    """What a single provider answered when asked for one instrument's
    split history — distinct from the *merged*, cross-source
    `CorporateActionConfidence` classification below. A `RATE_LIMITED`/
    `PLAN_LIMITED`/`NOT_SUPPORTED` row carries no real event data (`event_date`
    is null) and exists purely so "this provider didn't answer" is visible
    and distinguishable from "this provider found nothing" (`OK` with no
    matching rows) — see DEVLOG "Decision 3u.41"."""

    OK = "ok"
    RATE_LIMITED = "rate_limited"
    PLAN_LIMITED = "plan_limited"
    NOT_SUPPORTED = "not_supported"  # e.g. Polygon on a non-US listing, never even asked
    FAILED = "failed"


class CorporateActionConfidence:
    """How a merged, cross-source split event was classified —
    `corporate_actions/service.py`'s merge/classify engine (DEVLOG "Decision
    3u.41"). Only `VERIFIED_THREE_SOURCES`/`VERIFIED_CROSS_SOURCE` are ever
    auto-applied into `CorporateAction`; the rest stay visible only as
    `ProviderCorporateActionCandidate` rows until a human promotes one via
    `POST /api/corporate-actions/candidates/{id}/promote` (→ `MANUAL_PROMOTION`)
    or a targeted `detect_one` check confirms it directly."""

    VERIFIED_THREE_SOURCES = "verified_three_sources"
    VERIFIED_CROSS_SOURCE = "verified_cross_source"
    CANDIDATE_SINGLE_SOURCE = "candidate_single_source"
    PROVIDER_CONFLICT = "provider_conflict"
    SUSPECT_TICKER_REUSE = "suspect_ticker_reuse"
    MANUAL_PROMOTION = "manual_promotion"
    MANUAL = "manual"


class ProviderCorporateActionCandidate(Base):
    """One provider's raw, per-event observation for one instrument — the
    unfiltered log every `fetch_splits` call feeds, before any cross-source
    merging happens. Separate from `CorporateAction` (the applied table):
    this is what powers "Sources de vérification" / "Candidats à vérifier"
    in the UI, and lets a single-source or conflicting event stay visible
    without ever being auto-applied. See DEVLOG "Decision 3u.41".

    Not unique-constrained beyond `(instrument_id, provider, event_date)` —
    re-scanning the same event updates `retrieved_at` in place rather than
    accumulating duplicate rows every 7 days.
    """

    __tablename__ = "provider_corporate_action_candidates"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "provider", "event_date", name="uq_candidate_instrument_provider_date"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    instrument: Mapped[Instrument] = relationship()

    provider: Mapped[str] = mapped_column(String(30), index=True)

    # Null when `provider_status` isn't OK — a rate-limited/plan-limited/
    # not-supported/failed attempt found no event at all, so there is
    # nothing to date, type or ratio.
    event_date: Mapped[date | None] = mapped_column(Date, index=True)
    event_type: Mapped[str | None] = mapped_column(String(20))  # CorporateActionType.SPLIT/REVERSE_SPLIT
    numerator: Mapped[float | None] = mapped_column(Float)
    denominator: Mapped[float | None] = mapped_column(Float)
    # numerator/denominator, precomputed — comparing this float across
    # providers (within a small tolerance) is what lets economically
    # identical but textually different ratios (e.g. GOOGL's 999/500 and
    # 1033/517, both ≈ 1.998) merge instead of registering as a false
    # `provider_conflict`.
    economic_factor: Mapped[float | None] = mapped_column(Float)

    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    provider_status: Mapped[str] = mapped_column(String(20), default=ProviderCorporateActionCandidateStatus.OK)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class LastQuote(Base):
    """Most recent live quote per instrument — one row each, no history.

    Deliberately separate from `PriceBar`: a live quote is an intraday
    snapshot, not a daily close, and writing it into `PriceBar` would corrupt
    the daily-bar semantics the trend charts rely on (see
    `prices/quote_service.py`'s module docstring — that principle predates
    this table and still holds). Without this, a live quote fetched by
    `POST /portfolio/refresh-live` only ever existed in that one response
    body — reloading the page reverted the displayed price to whatever daily
    close was cached, even seconds after a successful live refresh. See
    DEVLOG "Decision 3o.1".
    """

    __tablename__ = "last_quotes"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    price: Mapped[float] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(30))
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class FmpSplitsStatus:
    """FMP's readmission state as a third automatic corporate-actions source
    (DEVLOG "Decision 3u.41") — its original bandwidth-quota block was an
    operational problem, not proof its split data is unreliable, so it gets
    a controlled path back in rather than staying permanently excluded.
    A manual Settings toggle only, deliberately: automating the judgment
    call of "does FMP's readmission-panel data look right" is out of scope
    for this phase.

    While `RECOVERING` (the default — matches the real state at the time
    this was introduced), FMP is still called during `detect_splits` so its
    results are visible for review, but does not count as a vote in the
    2-of-3 cross-source agreement. `ACTIVE` counts fully. `DEGRADED` is
    available for the user to set by hand if FMP looks unreliable again
    after being marked active — nothing here auto-demotes it.
    """

    RECOVERING = "recovering"
    ACTIVE = "active"
    DEGRADED = "degraded"


class AppMetadata(Base):
    """Global application metadata (timestamps, stats, etc.)."""

    __tablename__ = "app_metadata"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)  # Only one row
    last_price_refresh_time: Mapped[datetime | None] = mapped_column(DateTime)
    fmp_splits_status: Mapped[str] = mapped_column(String(20), default=FmpSplitsStatus.RECOVERING)

    # Whether the scheduled daily targeted-resume job (`POST
    # /api/corporate-actions/detect/resume`) is allowed to run — a real
    # pause switch, not just a UI preference: the job itself checks this
    # before spending any of Alpha Vantage's tight daily quota. Defaults to
    # on; the user can pause it (e.g. to save the day's quota for a manual
    # check instead) from Settings. See DEVLOG "Decision 3u.41".
    alpha_vantage_resume_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CorporateActionResumeRun(Base):
    """One execution of the targeted Alpha Vantage resume job — persisted so
    "last attempt / result / next attempt" survives a restart and is
    actually visible to the user, not just implied by log lines. A run is
    recorded whether it did real work or was skipped (paused, or nothing
    left incomplete) — `skipped_reason` distinguishes those from a genuine
    zero-instrument outcome. See DEVLOG "Decision 3u.41" and
    `app/corporate_actions/service.py::resume_incomplete_scan`.
    """

    __tablename__ = "corporate_action_resume_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Null unless the run did nothing at all — "paused" (the toggle above
    # was off) or "nothing_incomplete" (the portfolio's coverage gap for
    # this provider was already closed). A real run with zero targeted
    # instruments for any other reason shouldn't happen, but is recorded
    # the same way as a genuine run rather than silently coerced into one
    # of these.
    skipped_reason: Mapped[str | None] = mapped_column(String(30))

    targeted_instrument_ids: Mapped[list] = mapped_column(JSON, default=list)
    checked: Mapped[int] = mapped_column(Integer, default=0)
    rate_limited: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    no_events: Mapped[int] = mapped_column(Integer, default=0)
    verified_three_sources: Mapped[int] = mapped_column(Integer, default=0)
    verified_cross_source: Mapped[int] = mapped_column(Integer, default=0)
    candidate_single_source: Mapped[int] = mapped_column(Integer, default=0)
    provider_conflict: Mapped[int] = mapped_column(Integer, default=0)
    suspect_ticker_reuse: Mapped[int] = mapped_column(Integer, default=0)
    complete: Mapped[bool] = mapped_column(Boolean, default=True)

    # `list_incomplete_instrument_ids`'s count *after* this run — what the
    # UI's "Instruments restant à vérifier" reads directly, without
    # recomputing the selection query itself.
    remaining_incomplete: Mapped[int] = mapped_column(Integer, default=0)


class ProviderUsage(Base):
    """How many requests a quota-tracked provider has used in the current period.

    Only providers with a documented free-tier limit get a row here — see
    `prices/provider_usage.py`'s ``QUOTA_LIMITS``. ``period_key`` is a calendar
    key ("2026-08-19" for a daily limit, "2026-08" for Marketstack's monthly
    one): a new period simply has no row yet, so nothing needs pruning or
    resetting on a schedule. See DEVLOG "Decision 3m.1".

    ``bytes_used`` (added in DEVLOG "Decision 3u.41") is populated by
    `record_bytes()`, always under a *daily* ``period_key`` regardless of
    what period this provider's own ``count`` uses — it exists to catch a
    bandwidth-based quota (undocumented in ``QUOTA_LIMITS``, which only
    tracks request counts) before it silently blocks a provider the way
    FMP's did.
    """

    __tablename__ = "provider_usage"
    __table_args__ = (UniqueConstraint("provider", "period_key", name="uq_provider_usage_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    #: "2026-08-19" (day), "2026-08" (month), or "2026-08-19 22:34" (minute).
    period_key: Mapped[str] = mapped_column(String(16))
    count: Mapped[int] = mapped_column(Integer, default=0)
    bytes_used: Mapped[int] = mapped_column(Integer, default=0)


class FxRate(Base):
    """A daily-cached currency conversion rate, backing the live value estimate.

    Frankfurter publishes one reference rate per day (the ECB fixing), so asking
    again the same day buys nothing — cached here the same way daily price bars
    are cached in ``PriceBar``.
    """

    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("currency", "base_currency", "rate_date", name="uq_fx_rate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(8), index=True)
    base_currency: Mapped[str] = mapped_column(String(8))
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    #: 1 unit of ``currency`` expressed in ``base_currency``.
    rate: Mapped[float] = mapped_column(Float)
    #: The real on-disk table has always had this column (`NOT NULL`) even
    #: though this model never declared it — a pre-existing drift that only
    #: surfaced once something requested a currency pair never fetched
    #: before (USD→CNY, for NTES/DOYU's fundamentals in the scoring engine —
    #: see DEVLOG "Decision 3s.1"). No migration needed: the column already
    #: exists, only the model was missing it.
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Fundamental(Base):
    """One filed annual figure for one instrument, cached locally.

    Mirrors `PriceBar`'s caching shape (fetching SEC EDGAR is slow and
    throttled, same reasoning as daily price bars) and carries the same
    per-figure traceability `providers/edgar.py`'s `AnnualFigure` already
    established: which XBRL tag produced the value and what currency it was
    filed in, since a wrong tag or an assumed currency is exactly how this
    project's Phase 3a bugs happened (see DEVLOG "Bug 3a.1"/"Bug 3a.2"). See
    DEVLOG "Decision 3r.1" for the scoring engine this feeds.
    """

    __tablename__ = "fundamentals"
    __table_args__ = (
        UniqueConstraint("instrument_id", "concept", "fiscal_year", name="uq_fundamental"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    #: "revenue", "net_income", "equity"... — see `providers/edgar.py::CONCEPT_TAGS`.
    concept: Mapped[str] = mapped_column(String(40), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    period_end: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)
    #: Filing currency — never assumed USD (ASML files in EUR).
    currency: Mapped[str] = mapped_column(String(8))
    #: Which XBRL tag produced this figure — see `AnnualFigure.tag`'s docstring.
    tag: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(30), default="edgar")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class NewsSentiment(Base):
    """Cached Alpha Vantage `NEWS_SENTIMENT` snapshot, one row per instrument.

    Free but quota-shared with price fetches — same API key/account, same
    `Throttle` (see `providers/registry.py::get_alpha_vantage_provider`).
    Deliberately its own table, not merged with `InstrumentCommentary`:
    different shape (structured articles vs. freeform prose) and a much
    softer TTL, since this source costs nothing to refetch. Never read by
    `scoring/service.py` — commentary, not a scoring input, same principle
    as DEVLOG "Decision 0.3".
    """

    __tablename__ = "news_sentiments"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    #: [{title, url, source, time_published, summary, overall_sentiment_label,
    #: overall_sentiment_score, ticker_relevance_score, ticker_sentiment_score,
    #: ticker_sentiment_label}], one per article, Alpha Vantage's own order.
    #: No synthetic aggregate score stored here — "never guess a number":
    #: any average is computed at read time, if ever needed.
    articles: Mapped[list] = mapped_column(JSON, default=list)


class InstrumentCommentary(Base):
    """Cached Perplexity Sonar qualitative synthesis, one row per instrument.

    7-day default TTL (`settings.perplexity_cache_ttl_days`) is DEVLOG
    "Decision 0.3"'s hard cost-control choice, not a freshness judgment.
    Comments on the score; `scoring/service.py` never reads this table.
    """

    __tablename__ = "instrument_commentaries"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    #: Which Sonar variant produced this — same "where did this come from"
    #: reasoning as PriceBar.provider.
    model: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    #: [{url, title}], Perplexity's own order.
    citations: Mapped[list] = mapped_column(JSON, default=list)


class FactorReturn(Base):
    """One day's Carhart four-factor return series (Fama-French three
    factors plus Momentum), fetched from Kenneth French's public Data
    Library — free, no API key, refreshed monthly at the source. Stored as
    decimal returns (source CSVs are in percent — divided by 100 on
    import), one row per (region, date). `region` is "US" or "EUROPE":
    the two region-matched daily series with a momentum factor actually
    published there. See DEVLOG "Decision 3u.24" for why factor regressions
    are always region-matched, never a US factor applied to a European
    stock's returns."""

    __tablename__ = "factor_returns"
    __table_args__ = (UniqueConstraint("region", "return_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    region: Mapped[str] = mapped_column(String(10), index=True)
    return_date: Mapped[date] = mapped_column(Date, index=True)
    mkt_rf: Mapped[float] = mapped_column(Float)
    smb: Mapped[float] = mapped_column(Float)
    hml: Mapped[float] = mapped_column(Float)
    mom: Mapped[float] = mapped_column(Float)
    rf: Mapped[float] = mapped_column(Float)


class PersonalPolicyHorizon:
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class PersonalPolicyLimitDimension:
    """What one `PersonalPolicyLimit` row constrains. `LINE` and
    `DECLARED_VALUATION` are the two dimensions with no `target` value —
    `LINE` applies uniformly to every individual position (no single
    holding above X%), `DECLARED_VALUATION` is a fixed pseudo-dimension
    (total weight of positions valued from a declared broker statement
    rather than a market quote — Mintos/Amundi). The other four name a
    specific value of the corresponding `Instrument` column as `target`
    (e.g. dimension="sector", target="Technology")."""

    LINE = "line"
    SECTOR = "sector"
    COUNTRY = "country"
    CURRENCY = "currency"
    CATEGORY = "category"
    DECLARED_VALUATION = "declared_valuation"


class PersonalPolicy(Base):
    """The user's own, self-declared investment policy — never inferred,
    scored or imposed by the app. Every field is optional: an incomplete
    policy is a normal, permanent state, not a form to be pushed to
    completion. Used only to compare the current portfolio against the
    user's own stated rules (`PersonalPolicyLimit`) and report the result
    as a plain fact, never as a buy/sell instruction or a "profile"
    verdict. Singleton (id=1), same pattern as `AppMetadata`. See DEVLOG
    "Decision 3u.59".
    """

    __tablename__ = "personal_policy"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    # Objective: a free, non-exclusive combination — the app never forces a
    # single "growth/income/preservation" label, per the user's own
    # explicit instruction that no profile should be imposed.
    objective_growth: Mapped[bool] = mapped_column(Boolean, default=False)
    objective_income: Mapped[bool] = mapped_column(Boolean, default=False)
    objective_preservation: Mapped[bool] = mapped_column(Boolean, default=False)
    objective_note: Mapped[str | None] = mapped_column(String(500))

    # Horizon: a qualitative bucket, an explicit target date, or both.
    horizon: Mapped[str | None] = mapped_column(String(20))
    horizon_target_date: Mapped[date | None] = mapped_column(Date)

    liquidity_need_amount: Mapped[float | None] = mapped_column(Float)
    liquidity_need_date: Mapped[date | None] = mapped_column(Date)
    liquidity_note: Mapped[str | None] = mapped_column(String(500))

    # Deliberately qualitative text, not a forced "prudent/balanced/dynamic"
    # scale — see this model's own docstring.
    risk_tolerance_note: Mapped[str | None] = mapped_column(String(500))
    loss_capacity_pct: Mapped[float | None] = mapped_column(Float)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PersonalPolicyLimit(Base):
    """One personal concentration rule — "no more than X%" or a min/max
    range — see `PersonalPolicyLimitDimension` for what `target` means per
    dimension. Purely descriptive: `corporate_actions/service.py`-style
    read-only comparison only, never a trigger for any automatic action.
    See DEVLOG "Decision 3u.59"."""

    __tablename__ = "personal_policy_limits"
    __table_args__ = (
        UniqueConstraint("dimension", "target", name="uq_policy_limit_dimension_target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dimension: Mapped[str] = mapped_column(String(20))
    target: Mapped[str | None] = mapped_column(String(80))
    min_pct: Mapped[float | None] = mapped_column(Float)
    max_pct: Mapped[float | None] = mapped_column(Float)
