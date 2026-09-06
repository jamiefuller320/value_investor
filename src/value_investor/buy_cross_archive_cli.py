"""CLI for observe-only buy-cross archive simulation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.buy_cross_archive_sim import (
    BuyCrossArchiveConfig,
    format_buy_cross_archive_text,
    run_buy_cross_archive_sim,
)
from value_investor.paper_automation import BUY_TIER_LEVEL_MAX_POSITIONS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe-only buy-cross archive lab: buy names only when they newly "
            "enter raw screen buy-tier vs the prior weekly snapshot. Also scores "
            "a level-book comparison (hold the full buy-tier each week)."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/data"),
        help="Data root containing history/run_*.json.gz snapshots",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=BUY_TIER_LEVEL_MAX_POSITIONS,
        help=f"Position cap (default: {BUY_TIER_LEVEL_MAX_POSITIONS})",
    )
    parser.add_argument(
        "--include-timing-wait",
        action="store_true",
        help="Allow timing=wait buy-tier names (default: skip them, same as live book)",
    )
    parser.add_argument("--json", action="store_true", help="Print full review JSON")
    args = parser.parse_args(argv)

    config = BuyCrossArchiveConfig(
        max_positions=int(args.max_positions),
        skip_timing_wait=not bool(args.include_timing_wait),
    )
    review = run_buy_cross_archive_sim(args.output_dir, config=config)

    if args.json:
        slim = {
            key: value
            for key, value in review.items()
            if key not in {"cross", "level"}
        }
        slim["cross_summary"] = (review.get("cross") or {}).get("summary")
        slim["level_summary"] = (review.get("level") or {}).get("summary")
        print(json.dumps(slim, indent=2))
    else:
        print(format_buy_cross_archive_text(review))
    return 0


if __name__ == "__main__":
    sys.exit(main())
