"""Parser for Amundi's "Synthese_YYYYMMDD_HHMMSS.xlsb" export — a live
snapshot of every employee-savings fund holding, downloaded directly from
the Amundi ESR portal's own data feed, unlike the "Relevé annuel de
situation" PDF (see `amundi_import.py`'s module docstring), which is only
generated once a year and can be many months stale by the time it's
imported.

Real structure observed on a 2026-09-08 export: two sheets, `Donnees` (raw
JSON-shaped metadata — the account holder's name/login/matricule, unused
here) and `Mes avoirs par échéance` — one row per (fund, vesting maturity)
pair, since a French "Plan Epargne Groupe" allocates a new tranche with
its own 5-year lock-up maturity each year. The same fund can therefore
have several rows here (this account's real export had two maturities for
a single company-shareholding fund alone) —
summed per fund here to match `amundi_import.py`'s one-position-per-fund
model, never modelled per-tranche. Each fund's own row block is followed
by a "Ligne Total" subtotal row (blank fund name) — skipped, not
double-counted, by requiring a real fund name and numeric quantity/value.

Unlike the annual PDF, this export carries no per-fund gain/loss figure —
`ParsedFund.estimated_gain_loss` is always `None` from this source.

Live cross-checked the same day against the account's real total, as
reported directly by the user: summing every
fund's `Montant évalué` here matches closely — the small gap explained by
the two observations not being the exact same instant, not a wrong
column. The already-imported annual PDF's total for the same funds
undercounts specifically because it was missing this
account's second, more recently allocated tranche of the company-shareholding fund — not
because anything about the PDF import itself is wrong, just older. See
DEVLOG "Decision 3u.44".
"""

from __future__ import annotations

import io
import re
from datetime import datetime

from pyxlsb import open_workbook

from app.ingest.amundi_import import AMUNDI_ACCOUNTS, ParsedAmundiExport, ParsedFund
from app.messages import Message, MessageCode, SectionKind, SectionSummary

_SHEET_NAME = "Mes avoirs par échéance"
_FILENAME_DATETIME_RE = re.compile(r"(\d{8})_(\d{6})")

_HEADER_DISPOSITIF = "Libellé dispositif"
_HEADER_FUND = "Libellé FCPE"
_HEADER_QUANTITY = "nombre de parts"
_HEADER_VL = "VL"
_HEADER_VALUE = "Montant évalué"


def _account_for_dispositif(label: str) -> str:
    """"PERCO LIBRE Entreprise" -> "Amundi PERCO"; anything else (every
    real "Plan Epargne Groupe..." label seen) -> "Amundi PEG" — the same
    two-account convention `amundi_import.py` uses."""
    return AMUNDI_ACCOUNTS["PERCO"] if "PERCO" in label.upper() else AMUNDI_ACCOUNTS["PEG"]


def _extract_filename_datetime(filename: str) -> datetime | None:
    """``Synthese_20260908_104534.xlsb`` -> 2026-09-08 10:45:34 — this
    export's own download-time naming convention, the only date signal it
    carries; nothing inside the sheet itself is dated."""
    match = _FILENAME_DATETIME_RE.search(filename)
    if not match:
        return None
    date_part, time_part = match.groups()
    try:
        return datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S")
    except ValueError:
        return None


def parse_amundi_synthese_export(content: bytes, filename: str) -> ParsedAmundiExport:
    result = ParsedAmundiExport()

    as_of_dt = _extract_filename_datetime(filename)
    if as_of_dt is None:
        result.warnings.append(Message(MessageCode.FILE_UNREADABLE, {"error": "no date found in filename"}))
        return result
    result.as_of = as_of_dt.date()

    try:
        with open_workbook(io.BytesIO(content)) as wb:
            if _SHEET_NAME not in wb.sheets:
                result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
                return result
            with wb.get_sheet(_SHEET_NAME) as sheet:
                rows = [[cell.v for cell in row] for row in sheet.rows()]
    except Exception as exc:  # noqa: BLE001 - surfaced as a warning, not a crash
        result.warnings.append(Message(MessageCode.FILE_UNREADABLE, {"error": str(exc)}))
        return result

    if not rows or not rows[0]:
        result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
        return result

    header = rows[0]
    try:
        idx_dispositif = header.index(_HEADER_DISPOSITIF)
        idx_fund = header.index(_HEADER_FUND)
        idx_quantity = header.index(_HEADER_QUANTITY)
        idx_vl = header.index(_HEADER_VL)
        idx_value = header.index(_HEADER_VALUE)
    except ValueError:
        result.warnings.append(Message(MessageCode.NO_TABLE_RECOGNISED))
        return result

    # (account, fund name) -> [quantity, value, latest VL] — several rows
    # (one per vesting-maturity tranche) commonly share the same fund,
    # summed into the one position this app models per fund.
    aggregated: dict[tuple[str, str], list] = {}
    for row in rows[2:]:  # row 0 = French header, row 1 = internal field-name header
        if len(row) <= max(idx_dispositif, idx_fund, idx_quantity, idx_vl, idx_value):
            continue
        dispositif = row[idx_dispositif]
        fund_name = row[idx_fund]
        quantity = row[idx_quantity]
        vl = row[idx_vl]
        value = row[idx_value]
        # A "Ligne Total" subtotal row (blank dispositif/fund name) or a
        # blank trailing row — never a real fund line — is excluded by
        # requiring both a name and numeric quantity/value together.
        if not dispositif or not fund_name or not isinstance(quantity, (int, float)) or not isinstance(value, (int, float)):
            continue

        account = _account_for_dispositif(str(dispositif))
        key = (account, str(fund_name).strip())
        bucket = aggregated.setdefault(key, [0.0, 0.0, None])
        bucket[0] += quantity
        bucket[1] += value
        if isinstance(vl, (int, float)):
            bucket[2] = vl

    for (account, fund_name), (quantity, value, vl) in aggregated.items():
        result.funds.append(
            ParsedFund(
                account=account,
                name=fund_name,
                unit_price=vl,
                quantity=quantity,
                gross_value=round(value, 2),
                estimated_gain_loss=None,
            )
        )

    if result.funds:
        result.sections.append(
            SectionSummary(
                sheet=filename, kind=SectionKind.OPEN_POSITIONS, count=len(result.funds), source_rows=len(rows) - 2
            )
        )
    if result.is_empty:
        result.warnings.append(Message(MessageCode.NOTHING_IMPORTABLE))

    return result
