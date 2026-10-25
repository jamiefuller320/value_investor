"""CLI for cue-consumer MFT observe lab (super book) — ad-hoc drill-down."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.cue_consumer_mft import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_START_GATE_PATH,
    DEFAULT_STORE_PATH,
    format_cue_consumer_mft_text,
    refresh_cue_consumer_mft,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Cue-consumer MFT observe lab (super book): declared-incomparable "
            "fixed-stake mid-flight-tune sleeve skeleton. Never writes live books "
            "(influences_live=false)."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Data root (default: docs/data)",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="Observe store path (default: docs/data/cue_consumer_mft_observe.json)",
    )
    parser.add_argument(
        "--start-gate",
        type=Path,
        default=DEFAULT_START_GATE_PATH,
        help="Start-gate store (default: docs/data/cue_consumer_mft_start_gate.json)",
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
    payload = refresh_cue_consumer_mft(
        output_dir=args.output_dir,
        store_path=args.store,
        start_gate_path=args.start_gate,
        persist=not args.no_persist,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_cue_consumer_mft_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
