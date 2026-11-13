"""French income tax notice ("avis d'impôt sur les revenus", the PDF from
impots.gouv.fr): what the tax office worked out from my return.

Kept so it can be checked against what the app knows (salary, dividends,
interest, savings) and for what is still open, such as the retirement
savings ceiling. Nothing is computed here: the figures are the notice's own.

**What is read, and what is not.** The first page is an address block
(name, address, tax number, the tax office): none of it is kept. From the
following pages, every line the notice prints with dot leaders
("Revenu imposable........ 12345") is kept as label and amounts, under the
section it appears in. A handful of those lines are also picked out as
named figures (`TaxNoticeFigures`). Two figures sit on lines with no dot
leaders and are read on their own: the tax due for the year and the
withholding rate. The amount left to pay is read from the first page,
from the sentence that states it.

Amounts on these lines have no thousands separator ("12900"), and a line
with two columns ("21500 21500") is one per declarant then the total, so
the numbers are split on spaces. A leading "-", "+" or "=" belongs to the
amount after it.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import asdict, dataclass, field

import pdfplumber

#: Seen on every notice, top of each page: "Impôt sur les revenus de 2021".
_YEAR_RE = re.compile(r"Imp[oô]t sur les revenus de (\d{4})", re.IGNORECASE)
#: "Label.......... 1234", "Label........ + 400", "Label....... 21500 21500".
_LINE_RE = re.compile(r"^(?P<label>[^.]*?[^.\s])\s*\.{3,}\s*(?P<values>[-+=]?\s*\d+(?:\s+[-+=]?\s*\d+)*)\s*$")
_VALUE_RE = re.compile(r"([-+=]?)\s*(\d+)")
#: A footnote number the notice prints after some labels ("Revenu fiscal
#: de référence 25"): not part of the label.
_FOOTNOTE_RE = re.compile(r"\s+\d{1,3}:?$")
#: "Impôt sur le revenu 2021 dû 53: 0" (53 is a footnote).
_TAX_DUE_RE = re.compile(r"Imp[oô]t sur le revenu \d{4} d[uû]\s*(?:\d{1,3}\s*:)?\s*(-?\d+)\s*$", re.IGNORECASE)
#: "Impôt sur les revenus soumis au barème 14 0": the tax from the scale,
#: before reductions and credits (14 is a footnote).
_SCALE_TAX_RE = re.compile(r"^(Imp[oô]t sur les revenus soumis au bar[eè]me)\s+(?:\d{1,3}\s+)?(-?\d+)$", re.IGNORECASE)
_RATE_RE = re.compile(r"Taux pour le foyer\s+(\d+(?:,\d+)?)\s*%", re.IGNORECASE)
_NOTHING_DUE_RE = re.compile(r"n'avez rien [àa] payer", re.IGNORECASE)
_LEFT_TO_PAY_RE = re.compile(r"reste [àa] payer.*?(\d[\d ]*)\s*€", re.IGNORECASE | re.DOTALL)
_REFUND_RE = re.compile(r"(?:remboursement|vous sera rembours[ée]).*?(\d[\d ]*)\s*€", re.IGNORECASE | re.DOTALL)
#: A heading: no digits, mostly upper case ("PLAFOND EPARGNE RETRAITE"), or
#: the one mixed-case heading of the income table.
_HEADING_RE = re.compile(r"^(?:[A-ZÉÈÀÇÔ' ]{6,}:?|Détail des revenus.*)$")

#: Named figures: (key, start of the label, folded to ASCII lower case).
#: The amount kept is the last one on the line, the household total.
_FIGURES: tuple[tuple[str, str], ...] = (
    ("gross_income", "revenu brut global"),
    ("taxable_income", "revenu imposable"),
    ("net_tax", "total de l'impot sur le revenu net"),
    ("reference_income", "revenu fiscal de reference"),
    ("retirement_ceiling", "plafond pour les cotisations versees en"),
)


def _fold(text: str) -> str:
    """Lower case, no accents, single spaces: how labels are compared."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.lower().replace("’", "'").split())


@dataclass
class TaxNoticeLine:
    section: str
    label: str
    values: list[int]


@dataclass
class TaxNoticeFigures:
    gross_income: int | None = None
    taxable_income: int | None = None
    net_tax: int | None = None
    reference_income: int | None = None
    #: Tax due for the year once withholding is taken off (the "dû" line).
    tax_due: int | None = None
    #: Tax from the scale, before reductions and credits.
    scale_tax: int | None = None
    #: What the first page says is left to pay; negative when refunded.
    balance: int | None = None
    #: Withholding rate for the household, in percent.
    withholding_rate: float | None = None
    #: Retirement savings (PER) ceiling for next year's payments, per declarant.
    retirement_ceiling: list[int] = field(default_factory=list)


@dataclass
class ParsedTaxNotice:
    income_year: int | None
    figures: TaxNoticeFigures
    lines: list[TaxNoticeLine]

    @property
    def is_empty(self) -> bool:
        return self.income_year is None or not self.lines

    def figures_dict(self) -> dict:
        return asdict(self.figures)

    def lines_list(self) -> list[dict]:
        return [asdict(line) for line in self.lines]


def _values(text: str) -> list[int]:
    out = []
    for sign, digits in _VALUE_RE.findall(text):
        out.append(-int(digits) if sign == "-" else int(digits))
    return out


def _amount(text: str) -> int:
    return int(text.replace(" ", ""))


def parse_tax_notice_pages(pages: list[str]) -> ParsedTaxNotice:
    """`pages` is the text of each page, first one included (the year and the
    amount left to pay are read there; nothing else of it is kept)."""
    year_match = next((m for m in map(_YEAR_RE.search, pages) if m), None)
    figures = TaxNoticeFigures()
    lines: list[TaxNoticeLine] = []

    first = pages[0] if pages else ""
    if _NOTHING_DUE_RE.search(first):
        figures.balance = 0
    elif match := _LEFT_TO_PAY_RE.search(first):
        figures.balance = _amount(match.group(1))
    elif match := _REFUND_RE.search(first):
        figures.balance = -_amount(match.group(1))

    section = ""
    for page in pages[1:]:
        for raw in page.splitlines():
            text = " ".join(raw.split())
            if not text:
                continue
            if match := _TAX_DUE_RE.search(text):
                figures.tax_due = int(match.group(1))
                continue
            if match := _SCALE_TAX_RE.match(text):
                figures.scale_tax = int(match.group(2))
                lines.append(TaxNoticeLine(section=section, label=match.group(1), values=[figures.scale_tax]))
                continue
            if match := _RATE_RE.search(text):
                figures.withholding_rate = float(match.group(1).replace(",", "."))
                continue
            match = _LINE_RE.match(text)
            if match is None:
                if _HEADING_RE.match(text) and not _YEAR_RE.search(text):
                    # "Détail des revenus Déclar. 1 Total": the column heads go.
                    section = re.sub(r"\s+D[ée]clar\..*$", "", text).rstrip(" :")
                continue
            label = _FOOTNOTE_RE.sub("", match.group("label")).strip()
            values = _values(match.group("values"))
            lines.append(TaxNoticeLine(section=section, label=label, values=values))
            folded = _fold(label)
            for key, start in _FIGURES:
                if folded.startswith(start):
                    if key == "retirement_ceiling":
                        figures.retirement_ceiling = values
                    elif getattr(figures, key) is None:
                        setattr(figures, key, values[-1])

    return ParsedTaxNotice(
        income_year=int(year_match.group(1)) if year_match else None,
        figures=figures,
        lines=lines,
    )


def parse_tax_notice(content: bytes) -> ParsedTaxNotice:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return parse_tax_notice_pages(pages)


def looks_like_tax_notice(text: str) -> bool:
    """`text`: the first pages, lower case."""
    folded = _fold(text)
    return "avis_ir" in folded or (
        "impot sur les revenus de" in folded and "revenu fiscal de reference" in folded
    )
