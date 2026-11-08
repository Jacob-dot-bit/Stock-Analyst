"""Write a fictional XTB export, to try the app without a broker account.

Usage (from backend/):
    python -m scripts.make_demo_export [--out PATH]

The file has the same layout as a real xStation "Export to Excel" (one sheet
per section, a short preamble, then the table), so it goes through the normal
import on the Portfolio page. Every figure, date and id in it is made up.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import Workbook

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data" / "imports" / "demo-xtb-export.xlsx"
ACCOUNT = "My Trades"
ACCOUNT_NUMBER = 1000000

OPEN_HEADERS = [
    "Product", "Instrument/Position", "Ticker", "Category", "Type", "Volume", "Value",
    "Current price", "Open price", "Open time (UTC)", "Stop Loss", "Take Profit",
    "Net Profit %", "Net Profit", "Gross Profit", "Margin", "Open Commission", "Swap",
]
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

# (name, ticker, [(volume, open price, open time)], current price), amounts in EUR.
HOLDINGS = [
    ("Apple", "AAPL.US", [(3.0, 150.0, "2024-02-12 15:30:00")], 205.0),
    ("Microsoft", "MSFT.US", [(2.0, 310.0, "2024-03-04 16:10:00")], 410.0),
    ("ASML", "ASML.NL", [(1.0, 640.0, "2024-05-21 09:15:00"), (1.0, 700.0, "2025-01-14 10:02:00")], 690.0),
    ("TotalEnergies", "TTE.FR", [(10.0, 58.0, "2024-06-03 09:05:00")], 56.5),
    ("iShares Core MSCI World", "IWDA.NL", [(12.0, 82.0, "2024-01-08 09:30:00")], 98.0),
]


def _open_rows() -> list[list]:
    rows: list[list] = []
    position_id = 3000000001
    for name, ticker, lots, price in HOLDINGS:
        volume = sum(lot[0] for lot in lots)
        cost = sum(lot[0] * lot[1] for lot in lots)
        value = round(volume * price, 2)
        profit = round(value - cost, 2)
        rows.append([
            ACCOUNT, name, ticker, "STOCK", None, volume, value, None, round(cost / volume, 2),
            None, None, None, round(profit / cost * 100, 2), profit, profit, None, None, None,
        ])
        for lot_volume, lot_price, opened in lots:
            lot_value = round(lot_volume * price, 2)
            lot_profit = round(lot_value - lot_volume * lot_price, 2)
            rows.append([
                ACCOUNT, position_id, ticker, None, "BUY", lot_volume, lot_value, price, lot_price,
                opened, None, None, round(lot_profit / (lot_volume * lot_price) * 100, 2),
                lot_profit, lot_profit, None, None, None,
            ])
            position_id += 1
    return rows


def _closed_rows() -> list[list]:
    def row(name, ticker, volume, open_price, open_time, close_price, close_time, position_id):
        pl = round((close_price - open_price) * volume, 2)
        return [
            name, ticker, "STOCK", "BUY", volume, open_price, open_time, close_price, close_time,
            ACCOUNT, pl, pl, None, None, None, None, 0.0, None, None, None, 1.0, 1.0, "Web",
            position_id, None,
        ]

    return [
        row("Nike", "NKE.US", 4.0, 95.0, "2024-02-20 15:45:00", 78.0, "2025-03-11 16:20:00", 3000000101),
        row("Nvidia", "NVDA.US", 2.0, 70.0, "2024-04-02 15:31:00", 128.0, "2025-06-17 17:05:00", 3000000102),
    ]


def _cash_rows() -> list[list]:
    return [
        ["Deposit", None, None, None, "2024-01-05 08:00:00", 5000.0, 3000000201, "Transfer", ACCOUNT, None],
        ["Deposit", None, None, None, "2024-05-02 08:00:00", 1500.0, 3000000202, "Transfer", ACCOUNT, None],
        ["Dividend", "Apple", "AAPL.US", "STOCK", "2025-02-14 09:00:00", 0.72, 3000000203,
         "AAPL.US USD 0.2400/ SHR", ACCOUNT, 3000000001],
        ["Withholding tax", "Apple", "AAPL.US", "STOCK", "2025-02-14 09:00:00", -0.11, 3000000204,
         "AAPL.US USD WHT 15%", ACCOUNT, 3000000001],
        ["Dividend", "TotalEnergies", "TTE.FR", "STOCK", "2025-07-01 09:00:00", 7.9, 3000000205,
         "TTE.FR EUR 0.7900/ SHR", ACCOUNT, 3000000004],
        ["Total", None, None, None, None, 6508.51, None, None, None, None],
    ]


def build_demo_workbook() -> Workbook:
    workbook = Workbook()
    workbook.remove(workbook.active)
    sections = [
        ("Open Positions", OPEN_HEADERS, _open_rows()),
        ("Closed Positions", CLOSED_HEADERS, _closed_rows()),
        ("Cash Operations", CASH_HEADERS, _cash_rows()),
    ]
    for title, headers, rows in sections:
        sheet = workbook.create_sheet(title=title)
        sheet.append(["Account number", ACCOUNT_NUMBER])
        sheet.append([title])
        sheet.append(["Date from (UTC)", "2024-01-01 00:00:00"])
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
    return workbook


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a fictional XTB export")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output file (default: {DEFAULT_OUT})")
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    build_demo_workbook().save(args.out)
    print(f"Demo export written to {args.out}")
    print("Import it from the Portfolio page (Import an XTB statement).")


if __name__ == "__main__":
    main()
