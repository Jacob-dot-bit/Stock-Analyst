"""Run the point-in-time scoring backtest from the command line.

Usage (from backend/):
    python3 -m scripts.backtest --start 2021-01-01 --end 2025-01-01 --horizon 12 [--universe wide]
"""

from __future__ import annotations

import argparse
from datetime import date

from app.backtest.service import run_backtest, user_universe_ids, wide_universe_ids
from app.db import SessionLocal
from app.scoring.config import get_scoring_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Point-in-time backtest of the composite score")
    parser.add_argument("--start", required=True, help="ISO date, e.g. 2021-01-01")
    parser.add_argument("--end", required=True, help="ISO date")
    parser.add_argument("--horizon", type=int, default=12, help="forward-return horizon in months")
    parser.add_argument(
        "--universe",
        choices=["mine", "wide"],
        default="mine",
        help="mine: held/watchlisted/screened; wide: also every instrument with fundamentals",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = run_backtest(
            db,
            get_scoring_config(),
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            horizon_months=args.horizon,
            instrument_ids=wide_universe_ids(db) if args.universe == "wide" else user_universe_ids(db),
        )
    finally:
        db.close()

    print(f"Horizon: {result.horizon_months} months")
    print(f"Universe: {args.universe} | instruments scored: {result.instruments_scored}")
    print(f"Rebalance dates: {result.rebalance_count} | ranked: {len(result.periods)} | observations: {result.observations}")
    print(f"{'Quartile':>9} {'Count':>6} {'Mean fwd return':>16} {'Median':>10}")
    for bucket in result.buckets:
        mean = f"{bucket.mean_return:.2%}" if bucket.mean_return is not None else "n/a"
        median = f"{bucket.median_return:.2%}" if bucket.median_return is not None else "n/a"
        print(f"Q{bucket.quartile:<8} {bucket.count:>6} {mean:>16} {median:>10}")
    spread = f"{result.top_minus_bottom:.2%}" if result.top_minus_bottom is not None else "n/a"
    print(f"\nTop-minus-bottom spread: {spread}")
    hit = f"{result.hit_rate:.0%}" if result.hit_rate is not None else "n/a"
    print(f"Months where the top quartile beat the bottom: {hit}")


if __name__ == "__main__":
    main()
