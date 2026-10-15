"""CLI for sealed N210 observe-only fixed-stake AI/filter judgment (B3)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.n210_ai_judgment_observe import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_STORE_PATH,
    format_n210_observe_text,
    refresh_n210_ai_judgment_observe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "N210 sealed observe-only (B3): fixed-stake AI/filter judgment; "
            "progressive episode walker; fair-cost episode % primary. "
            "Never writes live books (influences_live=false)."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Data root with archived weekly screens (default: docs/data)",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="Observe store path (default: docs/data/n210_ai_judgment_observe.json)",
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
    payload = refresh_n210_ai_judgment_observe(
        output_dir=args.output_dir,
        store_path=args.store,
        persist=not args.no_persist,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_n210_observe_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
