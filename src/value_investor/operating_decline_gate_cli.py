"""CLI for the observe-only operating-decline gate (deferred N250)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.operating_decline_gate import (
    DEFAULT_LATEST_PATH,
    DEFAULT_LIBRARY_ROOT,
    DEFAULT_RESEARCH_ROOT,
    DEFAULT_STORE_PATH,
    format_operating_decline_text,
    refresh_operating_decline_gate,
)

DEFAULT_OUTPUT_DIR = Path("docs/data")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Operating-decline gate v0 (observe-only): clear / declining / "
            "insufficient_data per name from committed annual statements, screen "
            "row flags and filings headlines. Never writes live books."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Data root holding latest.json, research/ and library/ (default: docs/data)",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=None,
        help="Store path (default: <output-dir>/operating_decline_gate.json)",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Point-in-time date YYYY-MM-DD (default: today UTC); later-dated items are ignored",
    )
    parser.add_argument(
        "--ticker",
        default=None,
        help="Print one name's reasons and checks (read-only; does not write the store)",
    )
    parser.add_argument("--no-persist", action="store_true", help="Score without writing the store")
    parser.add_argument("--json", action="store_true", help="Print the store JSON")
    args = parser.parse_args(argv)

    output_dir = args.output_dir
    payload = refresh_operating_decline_gate(
        latest_path=output_dir / DEFAULT_LATEST_PATH.name,
        research_root=output_dir / DEFAULT_RESEARCH_ROOT.name,
        library_root=output_dir / DEFAULT_LIBRARY_ROOT.name,
        store_path=args.store or output_dir / DEFAULT_STORE_PATH.name,
        persist=not args.no_persist and args.ticker is None,
        as_of=args.as_of,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_operating_decline_text(payload, ticker=args.ticker))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
