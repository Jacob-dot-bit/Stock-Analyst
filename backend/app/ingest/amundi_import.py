"""Parser for Amundi ESR "Relevé annuel de situation" / "Relevé de comptes" PDFs
(French employee-savings PEG/PERCO statements).

Real structure observed on 2023-2025 annual statements: an **annual
snapshot**, not a transaction ledger — per fund (dispositif PEG or PERCO):
unit price, quantity, gross value, and Amundi's own cumulative
estimated gain/loss. Only coarse *annual* aggregate contribution totals
exist (``Versements volontaires``, ``Abondement...``) — no dated individual
operations. This module therefore never invents a dated transaction from
those aggregates; see ``aggregate_totals`` on ``ParsedAmundiExport``.

Amundi also sends a second, unrelated document type through the same portal
— a "Relevé d'information fiscale" recording profit-sharing paid directly
to the user's bank account (never touching a tracked position). This module
recognises and explicitly skips it (``is_fiscal_document``) rather than
mis-parsing it or silently dropping it.

User-facing text never appears here — see ``xtb_import.py``'s module
docstring for why.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pdfplumber

from app.messages import Message, MessageCode, SectionKind, SectionSummary

AMUNDI_ACCOUNTS = {"PEG": "Amundi PEG", "PERCO": "Amundi PERCO"}

_AU_DATE_RE = re.compile(r"AU\s+(\d{2}/\d{2}/\d{4})")
_MONEY_RE = re.compile(r"-?[\d\s ]+,\d{2}\s*€?")
_NUMBER_RE = re.compile(r"-?[\d\s ]+,\d+")

#: Recognised contribution-summary labels -> a stable key, so a wording change
#: between statement years (seen: "Intéressement et/ou Participation..."
#: sometimes includes "Prime de partage de la valeur") doesn't need an exact
#: string match. Anything not matching one of these is still preserved, never
#: dropped — see ``_classify_aggregate_label``.
_AGGREGATE_LABEL_HINTS: tuple[tuple[str, str], ...] = (
    ("versement", "versements_volontaires"),
    ("interessement", "interessement_participation_percu"),
    ("participation", "interessement_participation_percu"),
    ("abondement", "abondement"),  # net/brut distinguished separately, see below
)

#: The document lists funds (and their contribution recap) PEG-first,
#: PERCO-second, consistently across every real statement seen — but the
#: section-name marker row ("Votre épargne salariale PEG") is sometimes not
#: captured as part of any table by pdfplumber, depending on the statement's
#: exact template year (seen: absent on the 2023 "RELEVE DE COMPTES"
#: template). Positional order is therefore the reliable signal, not the
#: marker text.
_ACCOUNT_ORDER = ("Amundi PEG", "Amundi PERCO")


def _to_float(text: str | None) -> float | None:
    if not text:
        return None
    match = _NUMBER_RE.search(text.replace(" ", " "))
    if not match:
        return None
    cleaned = match.group().replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _classify_aggregate_label(label: str) -> str:
    lowered = label.lower().replace("é", "e").replace("è", "e").replace("ê", "e")
    for hint, key in _AGGREGATE_LABEL_HINTS:
        if hint in lowered:
            if key == "abondement":
                return "abondement_brut" if "brut" in lowered else "abondement_net"
            return key
    return "other"


@dataclass
class ParsedFund:
    account: str  # "Amundi PEG" | "Amundi PERCO"
    name: str
    unit_price: float | None
    quantity: float
    gross_value: float
    estimated_gain_loss: float | None


@dataclass
class ParsedAmundiExport:
    #: The statement's own "AU JJ/MM/AAAA" date — used both to date the
    #: snapshot and to guard against replacing newer positions with older ones.
    as_of: date | None = None
    funds: list[ParsedFund] = field(default_factory=list)
    #: {account: {aggregate_key: amount}} — annual totals, never converted
    #: into dated transactions (see module docstring).
    aggregate_totals: dict[str, dict[str, float]] = field(default_factory=dict)
    is_fiscal_document: bool = False
    warnings: list[Message] = field(default_factory=list)
    sections: list[SectionSummary] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.funds and not self.is_fiscal_document


def parse_amundi_statement(content: bytes, filename: str) -> ParsedAmundiExport:
    result = ParsedAmundiExport()

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            first_page_text = pdf.pages[0].extract_text() or ""
            if "information fiscale" in first_page_text.lower():
                result.is_fiscal_document = True
                result.warnings.append(Message(MessageCode.AMUNDI_FISCAL_DOCUMENT_SKIPPED, {"filename": filename}))
                return result

            date_match = _AU_DATE_RE.search(first_page_text)
            if date_match is None:
                result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
                return result
            result.as_of = datetime.strptime(date_match.group(1), "%d/%m/%Y").date()

            all_tables: list[list[list[Any]]] = []
            for page in pdf.pages:
                all_tables.extend(page.extract_tables())
    except Exception as exc:  # noqa: BLE001 - surfaced as a warning, not a crash
        result.warnings.append(Message(MessageCode.FILE_UNREADABLE, {"error": str(exc)}))
        return result

    current_account: str | None = None
    account_index = -1
    for table in all_tables:
        if not table:
            continue

        # Section marker: a row containing "►" starts a new dispositif
        # (PEG then PERCO, always in that order in every real statement
        # seen). Checked per *row*, not just table[0] — the 2023 "RELEVE DE
        # COMPTES" template puts it in its own single-row table, while
        # 2024/2025 fold it into the "Votre épargne salariale PEG" row; both
        # shapes contain "►" as a cell either way.
        if any(c == "►" for c in table[0]):
            account_index += 1
            if account_index >= len(_ACCOUNT_ORDER):
                result.warnings.append(Message(MessageCode.NOTHING_IMPORTABLE))
                current_account = None
            else:
                current_account = _ACCOUNT_ORDER[account_index]
            continue

        # Fund rows: classified per row, not per table — the 2023 template
        # splits the header and the data rows into two separate pdfplumber
        # tables (no shared "Support de placement" signature to key off),
        # while 2024/2025 keep header + scheme sub-header + fund rows +
        # total row together in one table. A row counts as fund data when
        # its first cell is a real name and two of the following cells
        # parse as numbers (quantity, gross value) — true for a fund line,
        # false for a header, a scheme sub-header (name only, no figures),
        # or the trailing total row (name is blank).
        if current_account is not None:
            for row in table:
                cells = [c for c in row if c is not None]
                if len(cells) < 5:
                    continue
                name, unit_price_text, quantity_text, gross_text, gain_text = cells[:5]
                if not name or not isinstance(name, str) or name.strip().lower() in ("total", "support de placement"):
                    continue
                quantity = _to_float(quantity_text)
                gross_value = _to_float(gross_text)
                if quantity is None or gross_value is None:
                    continue
                result.funds.append(
                    ParsedFund(
                        account=current_account,
                        name=name.strip(),
                        unit_price=_to_float(unit_price_text),
                        quantity=quantity,
                        gross_value=gross_value,
                        estimated_gain_loss=_to_float(gain_text),
                    )
                )

        # Aggregate contributions table: first row's second cell names the period.
        if len(table[0]) == 2 and table[0][0] is None and table[0][1] and "Du " in str(table[0][1]) and current_account:
            totals = result.aggregate_totals.setdefault(current_account, {})
            for row in table[1:]:
                if len(row) < 2 or not row[0]:
                    continue
                amount = _to_float(row[1])
                if amount is None:
                    continue
                key = _classify_aggregate_label(str(row[0]))
                totals[key if key != "other" else str(row[0]).strip()] = amount

    if result.funds:
        result.sections.append(
            SectionSummary(sheet=filename, kind=SectionKind.OPEN_POSITIONS, count=len(result.funds), source_rows=len(result.funds))
        )
    if result.is_empty:
        result.warnings.append(Message(MessageCode.NOTHING_IMPORTABLE))

    return result
