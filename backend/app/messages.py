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
    FAILED = "prices.failed"  # {symbol, provider, error}
    BUDGET_REACHED = "prices.budgetReached"  # {remaining}
    #: Every provider throttled and no keyed fallback is configured. Emitted once per
    #: run, because "rate limited" repeated 38 times tells the user nothing they can act
    #: on, whereas "configure a fallback" does.
    NO_FALLBACK_CONFIGURED = "prices.noFallbackConfigured"


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
