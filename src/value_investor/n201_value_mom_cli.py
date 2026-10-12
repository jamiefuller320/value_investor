"""CLI for sealed N201 observe-only short-horizon value+momentum."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.n201_value_mom_observe import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_STORE_PATH,
    format_n201_observe_text,
    refresh_n201_value_mom_observe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "N201 sealed observe-only: plain EY top-30% local + 12–1 mom > 0 "
            "+ financial_health; fixed-stake fair-cost episode %. Never writes "
            "live books."
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
        help="Observe store path (default: docs/data/n201_value_mom_observe.json)",
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
    payload = refresh_n201_value_mom_observe(
        output_dir=args.output_dir,
        store_path=args.store,
        persist=not args.no_persist,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_n201_observe_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
