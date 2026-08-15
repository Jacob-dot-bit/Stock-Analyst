"""Language-neutral message codes returned by the API.

The backend never returns prose meant for humans. It returns a ``code`` plus the
parameters needed to render it, and the client turns that into a sentence in the
user's language.

This matters because import diagnostics are the most useful thing this backend
produces — they tell the user which rows were skipped and why. Hardcoding them in
one language would make them useless to everyone else, and no amount of frontend
work could recover the meaning from a translated string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class MessageCode:
    """Codes emitted during an import.

    Adding a code here means adding its translation to every locale catalogue in
    ``frontend/src/i18n/``. An untranslated code is rendered as the raw code, which
    is ugly but never silently blank.
    """

    # --- File-level failures -------------------------------------------------
    UNSUPPORTED_FILE_TYPE = "import.unsupportedFileType"  # {extension}
    FILE_UNREADABLE = "import.fileUnreadable"  # {error}
    NO_TABLE_RECOGNISED = "import.noTableRecognised"
    NOTHING_IMPORTABLE = "import.nothingImportable"

    # --- Row-level and column-level issues -----------------------------------
    UNMAPPED_COLUMNS = "import.unmappedColumns"  # {sheet, columns}
    POSITION_SKIPPED = "import.positionSkipped"  # {symbol}
    CLOSED_POSITION_SKIPPED = "import.closedPositionSkipped"  # {symbol}

    # --- Post-import findings ------------------------------------------------
    UNRESOLVED_SYMBOLS = "import.unresolvedSymbols"  # {count, symbols}

    # --- Amundi-specific ------------------------------------------------------
    #: Amundi also sends a "Relevé d'information fiscale" (profit-sharing paid
    #: directly to the user's bank account) through the same portal — it never
    #: touches a tracked position, so it is recognised and skipped rather than
    #: mis-parsed or silently dropped. See DEVLOG "Decision 3u.39".
    AMUNDI_FISCAL_DOCUMENT_SKIPPED = "import.amundiFiscalDocumentSkipped"  # {filename}


class PriceOutcome:
    """Result of trying to refresh one instrument's price history.

    Refreshing is best-effort by nature: free providers rate-limit, symbols can be
    wrong, and networks fail. Each instrument therefore reports its own outcome
    rather than the whole refresh succeeding or failing as one.
    """

    UPDATED = "prices.updated"  # {symbol, bars, provider}
    ALREADY_FRESH = "prices.alreadyFresh"  # {symbol}
    NOT_MAPPED = "prices.notMapped"  # {symbol}
    SYMBOL_NOT_FOUND = "prices.symbolNotFound"  # {symbol, provider}
    RATE_LIMITED = "prices.rateLimited"  # {symbol, provider}
    NO_PROVIDER = "prices.noProvider"  # {symbol}
    #: The symbol is fine; the provider's plan simply does not include this market.
    PLAN_LIMITED = "prices.planLimited"  # {symbol, provider}
    #: A refresh was already running. Two concurrent runs double the quota spent for
    #: no benefit — observed for real when a browser click and a terminal call overlapped.
    ALREADY_RUNNING = "prices.alreadyRunning"
    #: Asked today, but still nothing stored. Reporting these as "already fresh" would
    #: dress an instrument with no data at all as one that is up to date.
    STILL_UNAVAILABLE = "prices.stillUnavailable"  # {symbol}
    #: No provider could even try, because the identifiers they need are missing.
    #: Distinct from "no source covers this market": here there is something the user
    #: can actually do, and telling them the wrong reason sends them nowhere.
    NEEDS_ISIN = "prices.needsIsin"  # {symbol}
    #: The instrument has no market price to find — not a gap, a property of it.
    NOT_PRICEABLE = "prices.notPriceable"  # {symbol}
    FAILED = "prices.failed"  # {symbol, provider, error}
    BUDGET_REACHED = "prices.budgetReached"  # {remaining}
    #: Every provider throttled and no keyed fallback is configured. Emitted once per
    #: run, because "rate limited" repeated 38 times tells the user nothing they can act
    #: on, whereas "configure a fallback" does.
    NO_FALLBACK_CONFIGURED = "prices.noFallbackConfigured"


class FundamentalsOutcome:
    """Result of trying to fetch one instrument's fundamentals from SEC EDGAR
    or ESEF (`fundamentals/service.py` tries EDGAR first, ESEF as the
    fallback — DEVLOG "Decision 3t.1"), whichever actually answers.

    Mirrors `PriceOutcome`'s reasoning: best-effort per instrument, not a single
    pass/fail for the whole batch, since coverage genuinely varies (`provider`
    on `UPDATED` says which of the two sources actually supplied the data).
    """

    UPDATED = "fundamentals.updated"  # {symbol, concepts, provider}
    ALREADY_FRESH = "fundamentals.alreadyFresh"  # {symbol}
    #: ETFs and CFDs have no company financials — not a failure, a property of
    #: the instrument. See `symbols/mapping.py::ANALYSABLE_CATEGORIES`.
    NOT_APPLICABLE = "fundamentals.notApplicable"  # {symbol}
    #: Neither source was even queried — EDGAR disabled (no SEC_USER_AGENT)
    #: *and* the instrument has no name to search ESEF with either. Distinct
    #: from SYMBOL_NOT_FOUND, which means at least one source was actually
    #: asked and came back empty.
    NO_PROVIDER = "fundamentals.noProvider"  # {symbol}
    SYMBOL_NOT_FOUND = "fundamentals.symbolNotFound"  # {symbol}
    RATE_LIMITED = "fundamentals.rateLimited"  # {symbol}
    FAILED = "fundamentals.failed"  # {symbol, error}
    ALREADY_RUNNING = "fundamentals.alreadyRunning"


class NewsOutcome:
    """Result of trying to fetch one instrument's Alpha Vantage news +
    sentiment (`analysis/news_service.py`). Free but quota-shared with price
    fetches — see `providers/registry.py::get_alpha_vantage_provider`.
    """

    UPDATED = "news.updated"  # {symbol, articles}
    ALREADY_FRESH = "news.alreadyFresh"  # {symbol, days}
    #: A legitimate answer, not a failure — persisted so the next call within
    #: the TTL window is ALREADY_FRESH, not a repeat empty fetch.
    EMPTY = "news.empty"  # {symbol}
    NOT_MAPPED = "news.notMapped"  # {symbol}
    NO_PROVIDER = "news.noProvider"  # {symbol}
    RATE_LIMITED = "news.rateLimited"  # {symbol}
    FAILED = "news.failed"  # {symbol, error}


class CommentaryOutcome:
    """Result of trying to fetch one instrument's Perplexity commentary
    (`analysis/commentary_service.py`). See DEVLOG "Decision 0.3": one
    instrument at a time, on explicit request, cached — never mass screening.
    """

    UPDATED = "commentary.updated"  # {symbol}
    ALREADY_FRESH = "commentary.alreadyFresh"  # {symbol, days}
    NO_PROVIDER = "commentary.noProvider"  # {symbol}
    RATE_LIMITED = "commentary.rateLimited"  # {symbol}
    FAILED = "commentary.failed"  # {symbol, error}


class PerformanceNote:
    """A caveat on a position's `broker_net_pl`/`broker_net_pl_pct` when
    they come from an approximation rather than a true cost basis — stored
    on `Position.performance_note` via `Message.as_dict()`, the same
    language-neutral shape as an import diagnostic. See DEVLOG "Decision
    3u.47" and `app/models.py::Position.performance_note`.
    """

    #: Mintos Core P2P's gain is real cumulative interest/bonus income
    #: minus fees/tax (`app/ingest/mintos_transactions_import.py`), not a
    #: price-appreciation P&L like an ordinary security.
    MINTOS_INTEREST_INCOME = "performance.mintosInterestIncome"  # {since}
    #: An Amundi fund's gain, when its source didn't disclose one (the
    #: Synthese export never does — Decision 3u.44), pro-rated from the
    #: account's known contributions — incomplete if any year was never
    #: imported, which can overstate this figure.
    AMUNDI_APPROXIMATE_GAIN = "performance.amundiApproximateGain"  # {account, since}
    #: A real (not pro-rated) gain for one Amundi fund whose current
    #: source discloses none, computed from that fund's own last known
    #: disclosed figure (a prior import's real gain) — used only when the
    #: fund's quantity hasn't changed since then, i.e. no new contribution
    #: to *this* fund muddies the comparison. See DEVLOG "Decision 3u.48".
    AMUNDI_REAL_GAIN_SINCE_SNAPSHOT = "performance.amundiRealGainSinceSnapshot"  # {since}


class ValuationNote:
    """A caveat on a position's *value* (not its P&L) when that value is a
    broker-declared valuation from a periodic statement rather than a live
    market quote — Mintos Core P2P, Amundi ESR funds. Stored on
    `Position.valuation_note`, the same `{code, params}` shape as
    `PerformanceNote`. Distinct from `PerformanceNote`: a position can have
    a perfectly fresh value and still no computable P&L (that's
    `PerformanceNote`'s job), or a stale value and a real P&L (Amundi's
    annual PDF discloses a gain even though the statement itself is a
    year old). See DEVLOG "Decision 3u.50".
    """

    #: The declared value is within this source's expected update cadence
    #: (see `routers/portfolio.py::DECLARED_VALUE_FRESHNESS_DAYS`).
    DECLARED_FRESH = "valuation.declaredFresh"  # {provider, date}
    #: The declared value predates this source's expected update cadence —
    #: still included in every total (a known value is never dropped for
    #: being old), just flagged so it isn't mistaken for a live quote.
    DECLARED_STALE = "valuation.declaredStale"  # {provider, date}


class SymbolReason:
    """Why a broker symbol could or could not be mapped to a data provider."""

    MANUAL_OVERRIDE = "symbol.manualOverride"
    SUFFIX_CONVERTED = "symbol.suffixConverted"  # {suffix, providerSuffix}
    DERIVATIVE = "symbol.derivative"  # {category}
    UNKNOWN_FORMAT = "symbol.unknownFormat"
    NOT_AN_EQUITY = "symbol.notAnEquity"


class SectionKind:
    """What a detected table in the workbook turned out to contain."""

    OPEN_POSITIONS = "open_positions"
    CLOSED_POSITIONS = "closed_positions"
    CASH_OPERATIONS = "cash_operations"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Message:
    """A translatable message: a code plus whatever it needs to be rendered."""

    code: str
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "params": self.params}


@dataclass(frozen=True)
class SectionSummary:
    """What was found in one sheet of the workbook.

    Surfaced so the user can confirm the file contained what they expected —
    a report with zero open positions is a valid file but rarely what was wanted.
    """

    sheet: str
    kind: str
    count: int
    #: Raw row count before aggregation. Differs from ``count`` on open positions,
    #: where the export lists one aggregate row per holding plus one row per lot.
    source_rows: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "kind": self.kind,
            "count": self.count,
            "source_rows": self.source_rows,
        }
