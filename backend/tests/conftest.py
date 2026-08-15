"""Shared fixtures.

The test workbooks reproduce the real structure of 2026 xStation exports, verified
against production files: one sheet per section, a metadata preamble, then the table.
The details below are reproduced faithfully because they are exactly what breaks a
naive parser:

* ``Ticker`` holds the symbol, ``Instrument`` holds the company name;
* open positions come in two levels — one aggregate row per holding (category set,
  direction blank) followed by one row per lot (direction set, category blank);
* the ``Position ID`` of closed positions **is not unique**: a holding closed in
  several parts produces several rows sharing one id;
* cash operations contain "Total" rows that must be discarded.

Account numbers here are fictional: fixtures must never carry real personal data,
since this repository is meant to be published.
"""

from __future__ import annotations

import io
import os

import pytest
from openpyxl import Workbook

os.environ.setdefault("BASE_CURRENCY", "EUR")

#: Credentials a developer may legitimately have in their own .env.
CREDENTIAL_VARS = (
    "TWELVEDATA_API_KEY",
    "PERPLEXITY_API_KEY",
    "SEC_USER_AGENT",
)


@pytest.fixture(autouse=True)
def isolate_credentials(monkeypatch):
    """Run every test as if no API key were configured.

    Without this, the suite reads whatever is in the developer's .env: a test asserting
    "no integration is enabled" then passes or fails depending on who runs it, and a
    failure message could print a real key. Tests that need a key set one explicitly.

    Clearing the environment variables alone is not enough, and this was a real gap
    until it was caught live (see DEVLOG "Decision 3s.1"): `Settings` reads
    `SEC_USER_AGENT` and friends from the real project `.env` FILE too
    (`SettingsConfigDict(env_file=...)`), a source `monkeypatch.delenv` never
    touches — it happened to never matter only because the real `.env` had never
    actually held one of these keys before. The moment the user genuinely
    configured `SEC_USER_AGENT` through the running app's Settings page, this
    exact test suite started reading their real value. Blanking `env_file` here
    makes every `Settings()` built during a test see only explicitly-set
    environment variables, regardless of what the developer's real `.env` holds.
    """
    from app.config import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", ())

    for name in CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)

    # The benchmark instrument (config.py) defaults ON (an S&P 500 ETF, not an
    # unset API key) so it needs the opposite treatment: actively disabled here
    # rather than merely unset, or every price-refresh test written before the
    # benchmark existed would suddenly see one extra instrument in its counts.
    # A test exercising the benchmark itself enables it explicitly.
    monkeypatch.setenv("BENCHMARK_BROKER_SYMBOL", "")
    monkeypatch.setenv("BENCHMARK_PROVIDER_SYMBOL", "")

    # get_settings() is cached, so a value read before this fixture ran would survive.
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def build_xtb_workbook(sheets: list[tuple[str, list[list], list[str], list[list]]]) -> bytes:
    """Build a workbook from (sheet name, preamble, headers, rows) tuples."""
    workbook = Workbook()
    workbook.remove(workbook.active)

    for sheet_name, preamble, headers, rows in sheets:
        sheet = workbook.create_sheet(title=sheet_name)
        for line in preamble:
            sheet.append(line)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_workbook(blocks: list[tuple[str, list[str], list[list]]]) -> bytes:
    """Variant with blocks stacked on a single sheet, for edge cases."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Report"

    for section_label, headers, rows in blocks:
        sheet.append([section_label])
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        sheet.append([])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


OPEN_HEADERS = [
    "Product", "Instrument/Position", "Ticker", "Category", "Type", "Volume", "Value",
    "Current price", "Open price", "Open time (UTC)", "Stop Loss", "Take Profit",
    "Net Profit %", "Net Profit", "Gross Profit", "Margin", "Open Commission", "Swap",
]

# The 25 real columns of the "Closed Positions" sheet.
CLOSED_HEADERS = [
    "Instrument", "Ticker", "Category", "Type", "Volume", "Open Price", "Open Time (UTC)",
    "Close Price", "Close Time (UTC)", "Product", "Profit/Loss", "Gross Profit",
    "Purchase Value", "Sale Value", "Stop Loss", "Take Profit", "Commission", "Margin",
    "Swap", "Rollover", "Open Conversion Rate", "Close Conversion Rate", "Close Origin",
    "Position ID", "Comment",
]

CASH_HEADERS = [
    "Type", "Instrument", "Ticker", "Category", "Time", "Amount", "ID", "Comment",
    "Product", "Position ID",
]


def closed_row(
    name, ticker, volume, open_price, open_time, close_price, close_time, pl, position_id,
    open_fx_rate=1.0, close_fx_rate=1.0,
):
    """Build a closed-position row in the real 25-column layout.

    Conversion rates default to 1.0 (i.e. instrument currency == account
    currency) to match every existing caller's fixtures — pass real,
    divergent rates to exercise the instrument/currency P&L split (DEVLOG
    "Decision 3p.1"), which nothing hit before this defaulted to the
    identity case everywhere.
    """
    return [
        name, ticker, "STOCK", "BUY", volume, open_price, open_time, close_price, close_time,
        "My Trades", pl, pl, None, None, None, None, 0.0, None, None, None,
        open_fx_rate, close_fx_rate, "Android", position_id, None,
    ]


@pytest.fixture
def xtb_export() -> bytes:
    """A realistic brokerage-account export, structured like the real files."""
    return build_xtb_workbook(
        [
            (
                "Open Positions",
                [
                    ["Account number", 1234567],
                    ["Open Positions"],
                    ["Data as of report generated", "2026-08-11 23:16:37"],
                    # Small summary table that precedes the real one.
                    ["Product", "Metric", "Amount", "Currency"],
                    ["My Trades", "Value", 2870.08, "EUR"],
                    ["My Trades", "Profit", 1448.57, "EUR"],
                    [],
                    ["Note", "Summary values are shown as of the report generation time"],
                ],
                OPEN_HEADERS,
                [
                    # Aggregate row: category set, direction and time absent.
                    ["My Trades", "ASML", "ASML.NL", "STOCK", None, 1.0, 1558.0, None,
                     723.7, None, None, None, 115.28, 834.3, 834.3, None, None, None],
                    # Its lot: direction and time set, category absent.
                    ["My Trades", 1636247573, "ASML.NL", None, "BUY", 1.0, 1558.0, 1558.0,
                     723.7, "2025-01-31 13:33:28", None, None, 115.28, 834.3, 834.3, None, None, None],

                    ["My Trades", "Nvidia", "NVDA.US", "STOCK", None, 2.0, 1312.08, None,
                     106.53, None, None, None, 88.03, 614.27, 614.27, None, None, None],
                    ["My Trades", 1630937303, "NVDA.US", None, "BUY", 1.0, 656.04, 217.46,
                     120.2, "2025-01-28 15:06:48", None, None, 61.94, 306.13, 306.13, None, None, None],
                    ["My Trades", 1744899271, "NVDA.US", None, "BUY", 1.0, 656.04, 217.46,
                     93.75, "2025-04-04 16:31:15", None, None, 118.51, 308.14, 308.14, None, None, None],
                ],
            ),
            (
                "Closed Positions",
                [
                    ["Account number", 1234567],
                    ["Closed Positions"],
                    ["Date from (UTC)", "2006-01-01 00:00:00"],
                ],
                CLOSED_HEADERS,
                [
                    closed_row("Canadian Pacific", "CP.US", 1.0, 77.3, "2025-02-25 18:05:02",
                               90.07, "2026-05-29 16:06:15", 2.83, 1677685560.0),
                    closed_row("Nestle", "NESN.CH", 1.0, 72.18, "2025-09-22 08:10:38",
                               80.035, "2026-05-29 11:38:30", 9.78, 1677685561.0),
                    # Partial close: same "Position ID" as the row below. Seen on real
                    # exports (223 rows for 220 distinct ids).
                    closed_row("Applied Digital", "APLD.US", 1.0, 7.88, "2025-03-31 15:55:55",
                               37.25, "2026-01-16 20:57:06", 24.35, 1677685567.0),
                    closed_row("Applied Digital", "APLD.US", 1.0, 7.88, "2025-03-31 15:55:55",
                               42.33, "2026-05-15 19:51:17", 30.10, 1677685567.0),
                ],
            ),
            (
                "Cash Operations",
                [
                    ["Account number", 1234567],
                    ["Cash Operations"],
                    ["Date from (UTC)", "2006-01-01 00:00:00"],
                ],
                CASH_HEADERS,
                [
                    ["Withholding tax", "ASML", "ASML.NL", "STOCK", "2026-08-05 09:59:25",
                     -0.28, 1386991258, "ASML.NL EUR WHT 15%", "My Trades", 1636247573],
                    ["Dividend", "ASML", "ASML.NL", "STOCK", "2026-08-05 09:59:25",
                     1.88, 1386991257, "ASML.NL EUR 1.8800/ SHR", "My Trades", 1636247573],
                    ["Free funds interest", None, None, None, "2026-08-04 14:52:46",
                     0.01, 1383977734, "Free-funds Interest 2026-07", "My Trades", None],
                    ["Free funds interest tax", None, None, None, "2026-08-04 14:52:46",
                     -0.01, 1383977735, "Tax on interest", "My Trades", None],
                    ["Stock purchase", "Nvidia", "NVDA.US", "STOCK", "2025-01-28 15:06:48",
                     -120.2, 1130937303, "OPEN BUY 1 @ 120.2", "My Trades", 1630937303],
                    ["Deposit", None, None, None, "2024-01-01 00:00:00",
                     5000.0, 1000000001, "Initial transfer", "My Trades", None],
                    # Subtotal row: must not become an operation.
                    ["Total", None, None, None, None, 4881.4, None, None, None, None],
                ],
            ),
        ]
    )


@pytest.fixture
def xtb_pea_export() -> bytes:
    """The second account's export (PEA), to verify accounts stay isolated."""
    return build_xtb_workbook(
        [
            (
                "Open Positions",
                [
                    ["Account number", 7654321],
                    ["Open Positions"],
                    ["Product", "Metric", "Amount", "Currency"],
                    ["PEA", "Value", 1000.0, "EUR"],
                ],
                OPEN_HEADERS,
                [
                    ["PEA", "TotalEnergies", "TTE.FR", "STOCK", None, 10.0, 620.0, None,
                     55.0, None, None, None, 12.72, 70.0, 70.0, None, None, None],
                    ["PEA", 1914280470, "TTE.FR", None, "BUY", 10.0, 620.0, 62.0,
                     55.0, "2025-03-10 10:00:00", None, None, 12.72, 70.0, 70.0, None, None, None],
                ],
            ),
            (
                "Cash Operations",
                [["Account number", 7654321], ["Cash Operations"]],
                CASH_HEADERS,
                [
                    ["Dividend", "TotalEnergies", "TTE.FR", "STOCK", "2026-07-03 09:58:01",
                     0.85, 1341782108, "TTE.FR EUR 0.8500/ SHR", "PEA", 1914280470],
                ],
            ),
        ]
    )
