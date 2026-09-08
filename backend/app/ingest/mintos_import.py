"""Parser for Mintos "Periodic statement of Financial instruments" PDFs.

Real structure observed on 2024-2025 quarterly statements — one PDF per
calendar quarter, no cumulative export exists, so the caller is expected to
import every quarterly file it has (in any order — everything here is
deduplicated downstream on a content-derived key).

Each statement has two portfolios of genuinely different nature:

* **Core ETF 90** — real ETFs, real ISINs (e.g. ``IE0009DRDY20``), a
  chronological buy/sell ledger. Parsed into individual ``Transaction`` rows,
  exactly like an XTB export — see ``etf_transactions``.
* **Mintos Core** — auto-invested fragments of individual loan notes
  (internal ISINs like ``LVX0000O17D9``, EUR 1-50 each, dozens per month).
  Mintos itself never values a single fragment — only the portfolio as a
  whole, once per statement period (``Opening balance | Investments |
  Repayments | Sale | Closing balance``). Modelled as one aggregate
  position, never as individual instruments — see ``p2p_period``.

Both portfolios' transaction tables commonly span a page break with no
repeated header on the continuation page — ``_extract_transaction_rows``
merges those back into one logical table by column-count signature.

User-facing text never appears here — see ``xtb_import.py``'s module
docstring for why: diagnostics are ``Message`` codes, rendered by the client.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pdfplumber

from app.messages import Message, MessageCode, SectionKind, SectionSummary

#: Account names used consistently across the importer, the P2P aggregate
#: instrument, and Position/Transaction rows — the same mechanism XTB uses
#: to isolate "My Trades" from "PEA" isolates Mintos from XTB and from
#: itself (ETF sub-portfolio vs. P2P aggregate never share a Position row).
MINTOS_ETF_ACCOUNT = "Mintos ETF"
MINTOS_CORE_ACCOUNT = "Mintos Core P2P"
MINTOS_CORE_BROKER_SYMBOL = "MINTOS-CORE-P2P"

_TXN_COLUMN_COUNT = 11
_TXN_HEADER_FIRST_CELL = "Date and time"

_MONEY_RE = re.compile(r"-?[\d,]+\.\d+")
_DATETIME_RE = re.compile(r"(\d{2}:\d{2}:\d{2}) EET (\d{2}\.\d{2}\.\d{4})")


def _to_float(text: str | None) -> float | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _parse_datetime(text: str) -> datetime | None:
    match = _DATETIME_RE.search(text or "")
    if not match:
        return None
    time_part, date_part = match.groups()
    return datetime.strptime(f"{date_part} {time_part}", "%d.%m.%Y %H:%M:%S")


def _join_wrapped_cell(value: Any) -> str:
    """Undo pdfplumber's newline-wrapped cells (e.g. an ISIN split across two
    lines because the column is narrow: ``"LVX0000MGME\\n7"`` -> ``"LVX0000MGME7"``)."""
    if value is None:
        return ""
    return str(value).replace("\n", "")


@dataclass
class ParsedPeriod:
    """One quarter's aggregate figures for the Mintos Core (P2P) portfolio."""

    period_start: datetime
    period_end: datetime
    opening_balance: float
    investments: float
    repayments: float
    sale: float
    closing_balance: float
    interest_received: float | None = None
    tax_withheld: float | None = None
    fee_charged: float | None = None


@dataclass
class ParsedMintosExport:
    #: One entry per Core ETF 90 buy/sell fill, shaped like ``xtb_import``'s
    #: ``open_lots``/``cash_operations`` dicts — consumed the same way.
    etf_transactions: list[dict[str, Any]] = field(default_factory=list)
    #: None if this statement had no Mintos Core activity to report.
    p2p_period: ParsedPeriod | None = None
    warnings: list[Message] = field(default_factory=list)
    sections: list[SectionSummary] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.etf_transactions and self.p2p_period is None


def _external_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _extract_statement_period(text: str) -> tuple[datetime, datetime] | None:
    match = re.search(r"Statement period:\s*(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})", text)
    if not match:
        return None
    start, end = match.groups()
    return datetime.strptime(start, "%d.%m.%Y"), datetime.strptime(end, "%d.%m.%Y")


def _find_portfolio_summary(all_tables: list[list[list[Any]]], portfolio_name: str) -> list[list[Any]] | None:
    """A portfolio's summary block is the small table whose first row is
    ``['Portfolio', <name>, ...]`` — distinct from the (much longer)
    transaction table that repeats the same marker row further down."""
    for table in all_tables:
        if not table:
            continue
        first_row = [c for c in table[0] if c]
        if len(first_row) >= 2 and first_row[0] == "Portfolio" and first_row[1] == portfolio_name:
            # A summary block ends with the 5-column opening/closing balance
            # row; a transaction table's second row is the 11-column header
            # instead — distinguish by row length.
            if len(table) >= 2 and len(table[1]) <= 5:
                return table
    return None


def _parse_summary_block(rows: list[list[Any]], is_p2p: bool) -> dict[str, float | None]:
    figures: dict[str, float | None] = {
        "interest_received": None,
        "tax_withheld": None,
        "fee_charged": None,
    }
    balance_header: list[str] = []
    balance_row: list[str] = []
    for row in rows:
        cells = [c for c in row if c is not None]
        if not cells:
            continue
        label = str(cells[0]) if len(cells) == 1 else str(row[1]) if len(row) > 1 and row[1] else ""
        if "Total interest received" in label:
            figures["interest_received"] = _to_float((_MONEY_RE.search(label) or [None]).group() if _MONEY_RE.search(label) else None)
        elif "Total tax withheld" in label:
            figures["tax_withheld"] = _to_float((_MONEY_RE.search(label) or [None]).group() if _MONEY_RE.search(label) else None)
        elif "Total fee charged" in label:
            figures["fee_charged"] = _to_float((_MONEY_RE.search(label) or [None]).group() if _MONEY_RE.search(label) else None)
        elif row[0] in ("Opening balance",):
            balance_header = [str(c) for c in row]
        elif balance_header and not balance_row and all(_to_float(str(c)) is not None for c in row if c not in (None, "")):
            balance_row = [str(c) for c in row]
    figures["balance_header"] = balance_header  # type: ignore[assignment]
    figures["balance_row"] = balance_row  # type: ignore[assignment]
    return figures


def _extract_transaction_rows(pages_tables: list[list[list[list[Any]]]], portfolio_name: str) -> list[list[Any]]:
    """Collect every row of one portfolio's "Purchases and sales" ledger,
    stitching together the continuation table pdfplumber returns on the next
    page when a table runs past a page break (no repeated header there)."""
    rows: list[list[Any]] = []
    capturing = False
    for page_tables in pages_tables:
        for table in page_tables:
            if not table:
                continue
            first_row = [c for c in table[0] if c]
            is_marker = len(first_row) >= 2 and first_row[0] == "Portfolio"
            if is_marker and first_row[1] == portfolio_name and len(table) >= 2 and len(table[1]) == _TXN_COLUMN_COUNT:
                capturing = True
                rows.extend(table[2:])  # skip the ['Portfolio', name, ...] and header rows
                continue
            if is_marker:
                # A different portfolio's marker — stop capturing continuations.
                capturing = False
                continue
            if capturing and len(table[0]) == _TXN_COLUMN_COUNT and table[0][0] != _TXN_HEADER_FIRST_CELL:
                rows.extend(table)
            elif capturing:
                capturing = False
    return rows


def parse_mintos_statement(content: bytes, filename: str) -> ParsedMintosExport:
    result = ParsedMintosExport()

    try:
        import io

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            first_page_text = pdf.pages[0].extract_text() or ""
            period = _extract_statement_period(first_page_text)
            if period is None:
                result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
                return result

            pages_tables = [page.extract_tables() for page in pdf.pages]
    except Exception as exc:  # noqa: BLE001 - surfaced as a warning, not a crash
        result.warnings.append(Message(MessageCode.FILE_UNREADABLE, {"error": str(exc)}))
        return result

    period_start, period_end = period

    # --- Core ETF 90: real transactions ---
    etf_rows = _extract_transaction_rows(pages_tables, "Core ETF 90")
    for row in etf_rows:
        if len(row) < _TXN_COLUMN_COUNT or not row[3]:
            continue
        dt = _parse_datetime(str(row[0]))
        isin = _join_wrapped_cell(row[3]).strip()
        side = str(row[4]).strip().upper() if row[4] else None
        units = _to_float(row[5])
        unit_price = _to_float(row[6])
        total = _to_float(row[10])
        if dt is None or not isin or side not in ("BUY", "SELL") or units is None:
            continue
        result.etf_transactions.append(
            {
                "external_id": _external_id(isin, str(dt), str(units), str(unit_price)),
                "broker_symbol": isin,
                "executed_at": dt,
                "side": side,
                "units": units,
                "unit_price": unit_price,
                "total_consideration": total,
                "gain_loss": _to_float(row[9]),
                "currency": str(row[1]) if row[1] else "EUR",
                "raw": {"row": [_join_wrapped_cell(c) for c in row]},
            }
        )
    if etf_rows:
        result.sections.append(
            SectionSummary(sheet=filename, kind=SectionKind.CASH_OPERATIONS, count=len(result.etf_transactions), source_rows=len(etf_rows))
        )

    # --- Mintos Core: aggregate period figures only ---
    summary = _find_portfolio_summary(pages_tables and [t for tables in pages_tables for t in tables] or [], "Mintos Core")
    if summary is not None:
        figures = _parse_summary_block(summary, is_p2p=True)
        balance_row = figures.get("balance_row") or []  # type: ignore[assignment]
        if len(balance_row) == 5:
            result.p2p_period = ParsedPeriod(
                period_start=period_start,
                period_end=period_end,
                opening_balance=_to_float(balance_row[0]) or 0.0,
                investments=_to_float(balance_row[1]) or 0.0,
                repayments=_to_float(balance_row[2]) or 0.0,
                sale=_to_float(balance_row[3]) or 0.0,
                closing_balance=_to_float(balance_row[4]) or 0.0,
                interest_received=figures.get("interest_received"),
                tax_withheld=figures.get("tax_withheld"),
                fee_charged=figures.get("fee_charged"),
            )
            result.sections.append(
                SectionSummary(sheet=filename, kind=SectionKind.CASH_OPERATIONS, count=1, source_rows=1)
            )

    if result.is_empty:
        result.warnings.append(Message(MessageCode.NOTHING_IMPORTABLE))

    return result


@dataclass
class ComputedEtfHoldings:
    """Result of replaying every Core ETF 90 fill across every statement
    file provided so far. Unlike XTB, Mintos never hands us a pre-aggregated
    position — only the chronological ledger — so this replay is what
    ``open_positions``/``open_lots`` are for every other importer."""

    #: One still-open holding per ISIN, keyed exactly like an XTB
    #: ``open_positions`` item — consumed the same way by ``ingest/service.py``.
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: One entry per fill, OPEN or CLOSED — same shape as XTB's ``open_lots``/
    #: the lot half of ``closed_positions``, feeding the historical value chart.
    lots: list[dict[str, Any]] = field(default_factory=list)


def compute_average_cost_positions(transactions: list[dict[str, Any]]) -> ComputedEtfHoldings:
    """Weighted-average-cost replay of Core ETF 90's buy/sell ledger.

    Sells reduce quantity by FIFO against still-open lots (closing the
    oldest first, splitting a lot if the sale is smaller than it) without
    changing the running average cost — a sale realises a gain/loss against
    the existing average, it does not itself change what remains was paid
    for. ``transactions`` must be sorted chronologically by the caller
    (``executed_at``) — this function does not sort, so that replaying a
    subset for a test is deterministic and explicit about ordering.
    """
    result = ComputedEtfHoldings()
    open_lots_by_isin: dict[str, list[dict[str, Any]]] = {}
    running: dict[str, dict[str, float]] = {}

    for tx in transactions:
        isin = tx["broker_symbol"]
        units = tx["units"]
        price = tx["unit_price"] or 0.0
        currency = tx.get("currency", "EUR")
        state = running.setdefault(isin, {"quantity": 0.0, "avg_price": 0.0})
        lots = open_lots_by_isin.setdefault(isin, [])

        if tx["side"] == "BUY":
            new_quantity = state["quantity"] + units
            if new_quantity > 0:
                state["avg_price"] = (state["quantity"] * state["avg_price"] + units * price) / new_quantity
            state["quantity"] = new_quantity
            lots.append(
                {
                    "external_id": tx["external_id"],
                    "broker_symbol": isin,
                    "quantity": units,
                    "open_price": price,
                    "opened_at": tx["executed_at"],
                    "currency": currency,
                    "raw": tx.get("raw"),
                }
            )
        elif tx["side"] == "SELL":
            state["quantity"] -= units
            remaining_to_close = units
            while remaining_to_close > 1e-6 and lots:
                lot = lots[0]
                if lot["quantity"] <= remaining_to_close + 1e-9:
                    remaining_to_close -= lot["quantity"]
                    lots.pop(0)
                    result.lots.append(
                        {
                            **lot,
                            "external_id": f"{lot['external_id']}-close-{tx['external_id']}",
                            "close_price": price,
                            "closed_at": tx["executed_at"],
                        }
                    )
                else:
                    lot["quantity"] -= remaining_to_close
                    result.lots.append(
                        {
                            **lot,
                            "external_id": f"{lot['external_id']}-close-{tx['external_id']}",
                            "quantity": remaining_to_close,
                            "close_price": price,
                            "closed_at": tx["executed_at"],
                        }
                    )
                    remaining_to_close = 0.0
            # A sale larger than everything on record (e.g. this replay didn't
            # see the opening statement) still updates the running quantity —
            # never silently dropped — but has nothing left to close as a lot.

    for isin, lots in open_lots_by_isin.items():
        result.lots.extend(lots)

    for isin, state in running.items():
        if state["quantity"] > 1e-4:
            result.positions[isin] = {
                "broker_symbol": isin,
                "quantity": state["quantity"],
                "avg_price": state["avg_price"],
            }

    return result
