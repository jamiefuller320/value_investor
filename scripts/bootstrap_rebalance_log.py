#!/usr/bin/env python3
"""Bootstrap rebalance_log.json for tracks that traded before logging existed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.paper_automation import learning_track_dirs
from value_investor.rebalance_log import bootstrap_rebalance_log

DEFAULT_BOOTSTRAP_BASE = Path("docs/data/paper_automation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct rebalance_log.json from automated_fund trades and "
            "nearest docs/data/archive screen snapshots."
        )
    )
    parser.add_argument(
        "--track-dir",
        type=Path,
        default=None,
        help="Single track directory (default: rules control at paper_automation root)",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=DEFAULT_BOOTSTRAP_BASE,
        help="Paper automation root when bootstrapping all tracks",
    )
    parser.add_argument(
        "--tracks",
        choices=["rules", "ai_judgment", "all"],
        default="rules",
        help="Which track(s) to bootstrap (default: rules only; ai_judgment uses PIT research)",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=Path("docs/data/archive"),
        help="Dashboard archive directory",
    )
    parser.add_argument(
        "--fetch-prices",
        action="store_true",
        help="Fetch missing prices via yfinance (slow; off by default)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing rebalance_log.json",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result(s)")
    args = parser.parse_args(argv)

    if args.track_dir is not None:
        targets = [("custom", Path(args.track_dir))]
    elif args.tracks == "all":
        targets = list(learning_track_dirs(Path(args.base_dir)).items())
    elif args.tracks == "ai_judgment":
        dirs = learning_track_dirs(Path(args.base_dir))
        targets = [("ai_judgment", dirs["ai_judgment"])]
    else:
        targets = [("rules", Path(args.base_dir))]

    results: dict[str, dict] = {}
    for track_id, track_dir in targets:
        results[track_id] = bootstrap_rebalance_log(
            track_dir,
            archive_dir=args.archive_dir,
            fetch_prices=bool(args.fetch_prices),
            overwrite=bool(args.overwrite),
        )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for track_id, result in results.items():
            print(f"{track_id}: {result}")
    return 0 if any(r.get("ok") for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
