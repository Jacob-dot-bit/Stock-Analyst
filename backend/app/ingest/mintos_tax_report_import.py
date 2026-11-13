"""Mintos's annual tax report ("tax_report_<investor id>-<date>.pdf",
Statements → Tax report): what the platform says an investor earned in
one calendar year. See DEVLOG "Step 3u.113".

Why it matters. The quarterly statement (`mintos_import.py`) only gives
the interest of loan-backed notes, and the account statement
(`mintos_transactions_import.py`) covers what one export's dates cover.
This report gives the whole year at once, in every category: interest by
kind with the Latvian withholding tax, other income (bonuses, discount on
bonds, interest on pending payments), gains or losses on notes sold, and
fees. It is what a French return is filled from (2TR through the 2047,
2AB/8VL for the withholding).

How it is read. pdfplumber gives each page as text. Headings are drawn
twice over themselves and come out doubled ("IInntteerreesstt"), so sections
are found by their plain sentences instead: "has received the below
interest", "…below capital gains", "…below other income", "…below
expenses". In each, a row ends with the currency and its amounts, with a
space as the thousands separator ("1 234.56"). A label can wrap over
the amounts line ("Notes backed by" / "EUR 100.00 …" / "loans"); only the
amounts are needed, so the label is not rebuilt for interest rows.

Nothing about the investor (name, address, tax number, date of birth) is
kept; only the year and the amounts.
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field

import pdfplumber

_YEAR_RE = re.compile(r"Reporting year:\s*(\d{4})")
_AMOUNT = r"-?\d{1,3}(?: \d{3})*\.\d{2}"
#: "EUR 100.00 5.00 5% 95.00 95.00" or "EUR 1.00 - - 1.00 1.00".
_INTEREST_ROW_RE = re.compile(rf"\bEUR ({_AMOUNT}) ({_AMOUNT}|-) (?:\d+(?:\.\d+)?%|-) ({_AMOUNT}) ({_AMOUNT})")
#: "Bonuses and campaigns EUR 10.00 10.00".
_LABELLED_ROW_RE = re.compile(rf"^(?P<label>.+?) EUR (?P<amount>{_AMOUNT}) (?P<eur>{_AMOUNT})$")


def _amount(text: str) -> float:
    return float(text.replace(" ", ""))


def _section(text: str, start: str, end: str) -> str:
    begin = text.find(start)
    if begin < 0:
        return ""
    stop = text.find(end, begin)
    return text[begin : stop if stop >= 0 else len(text)]


@dataclass
class ParsedMintosTaxReport:
    year: int | None = None
    #: Interest before the Latvian withholding tax, in euros.
    interest: float = 0.0
    withholding_tax: float = 0.0
    #: Bonuses, discount income from bonds, interest on pending payments…
    other_income: dict[str, float] = field(default_factory=dict)
    #: Gains (or losses) on notes sold, by kind.
    capital_gains: dict[str, float] = field(default_factory=dict)
    #: Platform fees, positive.
    expenses: dict[str, float] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return self.year is None

    @property
    def income_total(self) -> float:
        """Everything taxed as investment income: interest plus other income."""
        return round(self.interest + sum(self.other_income.values()), 2)

    @property
    def cost_total(self) -> float:
        """Withholding and fees, as a negative amount."""
        return -round(self.withholding_tax + sum(self.expenses.values()), 2)

    def figures(self) -> dict:
        return asdict(self) | {"income_total": self.income_total, "cost_total": self.cost_total}


def _labelled(section: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for raw in section.splitlines():
        line = " ".join(raw.split())
        if match := _LABELLED_ROW_RE.match(line):
            out[match["label"]] = round(out.get(match["label"], 0.0) + _amount(match["eur"]), 2)
    return out


def parse_mintos_tax_report_pages(pages: list[str]) -> ParsedMintosTaxReport:
    text = "\n".join(pages)
    result = ParsedMintosTaxReport()
    if year := _YEAR_RE.search(text):
        result.year = int(year.group(1))

    interest = _section(text, "has received the below interest", "For Interest earned")
    for match in _INTEREST_ROW_RE.finditer(" ".join(interest.split())):
        result.interest += _amount(match.group(1))
        if match.group(2) != "-":
            result.withholding_tax += _amount(match.group(2))
    result.interest = round(result.interest, 2)
    result.withholding_tax = round(result.withholding_tax, 2)

    result.capital_gains = _labelled(_section(text, "has received the below capital gains", "See detailed information"))
    result.other_income = _labelled(_section(text, "has received the below other income", "has the below expenses"))
    result.expenses = {
        label: abs(amount)
        for label, amount in _labelled(_section(text, "has the below expenses", "have been written-off")).items()
    }
    return result


def parse_mintos_tax_report(content: bytes) -> ParsedMintosTaxReport:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages[:3]]
    return parse_mintos_tax_report_pages(pages)


def looks_like_mintos_tax_report(text: str) -> bool:
    """`text`: the first pages, lower case."""
    return "mintos" in text and "reporting year:" in text
