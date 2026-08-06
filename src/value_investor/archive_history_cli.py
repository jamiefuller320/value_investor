"""CLI for backfilling run history from dashboard archives."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from value_investor.archive_history import backfill_run_history_from_archives


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill docs/data/history run snapshots from dated dashboard archives "
            "(docs/data/archive/*.json)."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("docs/data"),
        help="Dashboard data root containing archive/ and history/",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="Override archive directory (default: <data-dir>/archive)",
    )
    parser.add_argument(
        "--no-fetch-prices",
        action="store_true",
        help="Skip yfinance price fetch (tests / offline)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List snapshots that would be written without writing",
    )
    args = parser.parse_args(argv)

    written = backfill_run_history_from_archives(
        args.data_dir,
        archive_dir=args.archive_dir,
        fetch_prices=not args.no_fetch_prices,
        dry_run=bool(args.dry_run),
    )
    if args.dry_run:
        print(f"Would write {len(written)} snapshot(s)")
    else:
        print(f"Wrote {len(written)} snapshot(s)")
        for path in written:
            print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
