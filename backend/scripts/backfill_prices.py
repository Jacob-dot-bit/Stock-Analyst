"""Pull several years of daily price history from the command line.

Usage (from backend/):
    python3 -m scripts.backfill_prices [--years 5] [--with-fundamentals]

`--with-fundamentals` also covers every instrument with stored
fundamentals, priced or not, so the score backtest's wide universe has
enough history to rank them. One provider call per instrument; slow by
design (each provider's own throttle paces the run).
"""

from __future__ import annotations

import argparse

from app.db import SessionLocal
from app.prediction.service import BACKFILL_YEARS, backfill_history, get_backfill_progress
from app.providers.registry import get_provider_chain


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill daily price history")
    parser.add_argument("--years", type=int, default=BACKFILL_YEARS, help="how many years back to pull")
    parser.add_argument(
        "--with-fundamentals",
        action="store_true",
        help="also include every instrument with stored fundamentals, priced or not",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = backfill_history(db, get_provider_chain(), years=args.years, with_fundamentals=args.with_fundamentals)
    finally:
        db.close()

    if report is None:
        print("A backfill is already running.")
        return
    progress = get_backfill_progress()
    print(f"Instruments: {progress.total} | updated: {report.updated} | failed: {report.failed}")
    print(f"New bars stored: {report.bars_added}")


if __name__ == "__main__":
    main()
