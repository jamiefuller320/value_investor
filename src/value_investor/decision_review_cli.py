"""CLI for decision-review learning on the automated paper book."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.decision_review import (
    format_review_text,
    run_decision_review,
)
from value_investor.paper_automation import DEFAULT_AUTOMATION_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Review automated paper-fund outcomes after costs and propose "
            "(or apply) small clamped trading-knob updates"
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_AUTOMATION_DIR,
        help="Paper automation directory (fund + config)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write clamped knob updates to config.json when history is thick enough",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Propose/apply even when equity marks or trades are below the minimum",
    )
    parser.add_argument(
        "--no-benchmark",
        action="store_true",
        help="Skip FTSE benchmark fetch (excess_after_costs omitted)",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON result")
    args = parser.parse_args(argv)

    result = run_decision_review(
        output_dir=Path(args.output_dir),
        apply=bool(args.apply),
        force=bool(args.force),
        fetch_benchmark=not args.no_benchmark,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_review_text(result))
        print(f"\nWrote {Path(args.output_dir) / 'decision_review.json'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
