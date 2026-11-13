"""Shared cell readers for the import parsers.

Spreadsheet and CSV cells reach the parsers either already typed (a float,
a datetime) or as text written by whoever produced the export: "1 234,56",
"1,234.56", "13/11/2026", "2025-01-01 10:00:00". These helpers turn one cell
into a number or a date, returning ``None`` rather than raising: one
unreadable cell must not fail the whole import.

Numbers and dates pulled out of free PDF text (Amundi and Mintos statements)
stay in their own parsers: there the job is finding the figure in a sentence,
not reading a cell.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

#: Isolates the first number in a string, thousands separators included.
#: Extracting beats character filtering: otherwise "1 234,56 EUR" leaves the "E"
#: of the currency behind and the conversion fails.
_NUMBER_TOKEN = re.compile(r"[-+]?\d[\d\s.,]*")


def parse_number(value: Any) -> float | None:
    """Parse a number tolerating both English and French conventions.

    Handles "1 234,56", "1,234.56", non-breaking spaces, trailing currency codes and
    accounting parentheses. Returns ``None`` rather than raising: one unreadable cell
    must not fail the whole import.

    Scientific notation is deliberately unsupported — absent from broker exports, it
    would make trailing-currency detection ambiguous.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).replace("\xa0", " ").replace("\u202f", " ").strip()
    if not text:
        return None

    # Accounting notation: "(1 234,56)" means -1234.56
    negated = text.startswith("(") and text.endswith(")")
    if negated:
        text = text[1:-1].strip()

    match = _NUMBER_TOKEN.search(text)
    if match is None:
        return None

    text = match.group(0).replace(" ", "").rstrip(".,")
    if not text or text in {"-", "+"}:
        return None

    has_comma, has_dot = "," in text, "." in text
    if has_comma and has_dot:
        # The decimal separator is whichever appears last.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        # Comma alone: decimal ("12,5") or thousands separator ("1,234")?
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text):
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")

    try:
        number = float(text)
    except ValueError:
        return None

    return -number if negated else number


_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
)


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def cell_date(value: Any) -> date | None:
    """A date cell: a real date/datetime, or text in one of the formats
    above. Text with a trailing time part that is not listed (``T`` separator,
    time zone) still gives its ``YYYY-MM-DD`` prefix."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = parse_datetime(value)
    if parsed is None and isinstance(value, str):
        parsed = parse_datetime(value.strip()[:10])
    return parsed.date() if parsed is not None else None
