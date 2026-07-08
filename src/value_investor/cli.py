"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from value_investor.pipeline import run_screen, write_outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screen FTSE 100 companies for value signals")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for CSV/JSON artifacts (default: output/)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of companies (useful for dry runs)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Print top N signals to stdout (default: 15)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print summary JSON to stdout instead of a table",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    result = run_screen(limit=args.limit)
    paths = write_outputs(result, args.output_dir)

    top = result.signals.head(args.top)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        cols = ["ticker", "name", "signal", "models_passed", "composite_score", "trailing_pe", "dividend_yield"]
        display_cols = [c for c in cols if c in top.columns]
        print(top[display_cols].to_string(index=False))
        print(f"\nWrote {paths['latest']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
