"""Kenneth French's Data Library — free, no API key, daily factor returns
for the Carhart four-factor model (the three Fama-French factors plus
Momentum). Source: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/
data_library.html, updated monthly there. Fetched here as an occasional,
explicit pull into `FactorReturn` — not a live per-request dependency,
same "static external data, refreshed occasionally" shape as the bundled
S&P 500 constituent list. See DEVLOG "Decision 3u.24".

Two regions are supported — the two daily series Kenneth French's library
actually publishes *with* a matching daily momentum factor: "US" and
"EUROPE". A US stock's returns must be region-matched against the US
factors, never against Europe's (and vice versa) — applying one region's
risk-factor premia to another region's returns would misattribute the
loadings to something that was never actually driving them.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

import httpx

_BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"

_FILES = {
    "US": {
        "factors": f"{_BASE_URL}/F-F_Research_Data_Factors_daily_CSV.zip",
        "momentum": f"{_BASE_URL}/F-F_Momentum_Factor_daily_CSV.zip",
        "momentum_column": "Mom",
    },
    "EUROPE": {
        "factors": f"{_BASE_URL}/Europe_3_Factors_Daily_CSV.zip",
        "momentum": f"{_BASE_URL}/Europe_Mom_Factor_Daily_CSV.zip",
        "momentum_column": "WML",
    },
}

#: Kenneth French's documented sentinel for a missing observation — never
#: coerced to 0, the row is dropped instead ("never guess a number").
_MISSING_SENTINEL = -99.99


def _looks_like_label(cell: str) -> bool:
    try:
        float(cell)
        return False
    except ValueError:
        return bool(cell)


def _parse_csv_rows(text: str) -> dict[date, dict[str, float]]:
    """Every one of Kenneth French's daily CSVs shares this shape: a few
    lines of prose, then a header row whose own first cell is empty
    (",Mkt-RF,SMB,HML,RF"), then daily rows keyed by an 8-digit YYYYMMDD
    date, then a trailing copyright footer. Values are in percent (0.09
    means 0.09%) — converted to decimal by the caller, not here, so this
    function's output matches the file's own units."""
    rows: dict[date, dict[str, float]] = {}
    header: list[str] | None = None
    for raw_row in csv.reader(io.StringIO(text)):
        cells = [c.strip() for c in raw_row]
        if not cells:
            continue
        first = cells[0]
        if header is None:
            if first == "" and len(cells) > 1 and all(_looks_like_label(c) for c in cells[1:]):
                header = cells[1:]
            continue
        if not (first.isdigit() and len(first) == 8):
            # Past the data block — Kenneth French's files never resume
            # data rows after the first non-date line (the footer).
            break
        try:
            values = [float(v) for v in cells[1 : len(header) + 1]]
        except ValueError:
            continue
        if any(v == _MISSING_SENTINEL for v in values):
            continue
        year, month, day = int(first[:4]), int(first[4:6]), int(first[6:8])
        rows[date(year, month, day)] = dict(zip(header, values))
    return rows


def _fetch_zip_csv(url: str, timeout: float = 30.0) -> str:
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        name = zf.namelist()[0]
        return zf.read(name).decode("utf-8", errors="replace")


def fetch_region(region: str) -> list[dict]:
    """One region's merged factor+momentum daily rows as **decimal**
    returns (the source CSVs are in percent). Only dates present in both
    the factor file and the momentum file are returned — a day missing
    from either can't produce a complete row."""
    config = _FILES[region]
    factors = _parse_csv_rows(_fetch_zip_csv(config["factors"]))
    momentum = _parse_csv_rows(_fetch_zip_csv(config["momentum"]))
    momentum_column = config["momentum_column"]

    rows = []
    for day, values in factors.items():
        mom_values = momentum.get(day)
        if mom_values is None or momentum_column not in mom_values:
            continue
        rows.append(
            {
                "return_date": day,
                "mkt_rf": values["Mkt-RF"] / 100.0,
                "smb": values["SMB"] / 100.0,
                "hml": values["HML"] / 100.0,
                "rf": values["RF"] / 100.0,
                "mom": mom_values[momentum_column] / 100.0,
            }
        )
    return rows
