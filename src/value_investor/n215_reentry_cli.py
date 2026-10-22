"""CLI for sealed N215 soft-veto → MONITOR reentry observe."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.n215_reentry_observe import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_STORE_PATH,
    format_n215_reentry_text,
    refresh_n215_reentry_observe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "N215 sealed observe-only: WARN+ soft-band × R1 breakout-wait "
            "reentry replay on N200 closed episodes (thickened full-gate) "
            "+ optional N206 holdout + design-locked WARN+×R4 RSI-reset twin. "
            "Never writes live books."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Data root containing n200/n206/n215 stores and charts/",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="Observe store path (default: docs/data/n215_reentry_observe.json)",
    )
    parser.add_argument(
        "--no-n206-holdout",
        action="store_true",
        help="Skip N206 report-only holdout (default: include when store present)",
    )
    parser.add_argument(
        "--no-twin",
        action="store_true",
        help="Skip WARN+×R4 clear-signal twin companion (default: include)",
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
    payload = refresh_n215_reentry_observe(
        output_dir=args.output_dir,
        store_path=args.store,
        include_n206_holdout=not args.no_n206_holdout,
        include_clear_signal_twin=not args.no_twin,
        persist=not args.no_persist,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_n215_reentry_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
