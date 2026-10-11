"""CLI for sealed N200 observe-only tech-timing brackets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.n200_tech_timing_observe import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_STORE_PATH,
    format_n200_observe_text,
    refresh_n200_tech_timing_observe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "N200 sealed observe-only: score raw_buy_tier entry/exit ±14d "
            "brackets from archive history. Never writes live books."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Data root containing history/run_*.json.gz",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="Observe store path (default: docs/data/n200_tech_timing_observe.json)",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Compute without writing store files",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full payload JSON",
    )
    args = parser.parse_args(argv)
    payload = refresh_n200_tech_timing_observe(
        output_dir=args.output_dir,
        store_path=args.store,
        persist=not args.no_persist,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_n200_observe_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
