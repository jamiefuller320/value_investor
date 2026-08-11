"""CLI for observe-only exit-timing archive near-miss simulation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.exit_timing_archive_sim import (
    ExitTimingArchiveSimConfig,
    format_exit_timing_archive_text,
    run_exit_timing_archive_sim,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe-only exit-timing priors from archived weekly screens: "
            "score hold-recovery and swap paths for near-miss names below buy tier."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/data"),
        help="Data root containing history/run_*.json.gz snapshots",
    )
    parser.add_argument(
        "--min-conviction",
        type=float,
        default=0.35,
        help="Minimum conviction_score for near-miss holds (default: 0.35)",
    )
    parser.add_argument(
        "--min-data-quality",
        type=float,
        default=0.0,
        help="Minimum data_quality_score when set > 0 (default: 0)",
    )
    parser.add_argument(
        "--signals",
        type=str,
        default="hold",
        help="Comma-separated non-buy screen signals to include (default: hold)",
    )
    parser.add_argument(
        "--max-episodes-per-week",
        type=int,
        default=10,
        help="Cap near-miss episodes opened per snapshot week (default: 10)",
    )
    parser.add_argument("--json", action="store_true", help="Print full review JSON")
    args = parser.parse_args(argv)

    signal_set = frozenset(s.strip() for s in args.signals.split(",") if s.strip())
    config = ExitTimingArchiveSimConfig(
        min_conviction=float(args.min_conviction),
        min_data_quality=float(args.min_data_quality),
        near_miss_signals=signal_set or frozenset({"hold"}),
        max_episodes_per_week=int(args.max_episodes_per_week),
    )
    review = run_exit_timing_archive_sim(args.output_dir, config=config)

    if args.json:
        print(json.dumps(review, indent=2))
    else:
        print(format_exit_timing_archive_text(review))
    return 0


if __name__ == "__main__":
    sys.exit(main())
