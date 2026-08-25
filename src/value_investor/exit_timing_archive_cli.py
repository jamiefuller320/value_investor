"""CLI for observe-only exit-timing archive near-miss simulation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.exit_timing_archive_sim import (
    DEFAULT_MAX_EPISODES_PER_WEEK,
    DEFAULT_MIN_CONVICTION,
    ExitTimingArchiveSimConfig,
    format_exit_timing_archive_text,
    run_exit_timing_archive_sim,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe-only exit-timing priors from archived weekly screens and "
            "rebalance_log held-book episodes: score hold-recovery and swap paths."
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
        default=None,
        help=(
            "Minimum conviction_score for near-miss holds "
            f"(default: {DEFAULT_MIN_CONVICTION} = pre_buy floor)"
        ),
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
        default=None,
        help=(
            "Cap near-miss episodes opened per snapshot week "
            f"(default: {DEFAULT_MAX_EPISODES_PER_WEEK})"
        ),
    )
    parser.add_argument(
        "--paper-root",
        type=Path,
        default=None,
        help="Paper automation root for rebalance_log held-book episodes "
        "(default: <output-dir>/paper_automation when present)",
    )
    parser.add_argument(
        "--tracks",
        type=str,
        default="rules,ai_judgment",
        help="Comma-separated track ids for rebalance_log ingest (default: rules,ai_judgment)",
    )
    parser.add_argument(
        "--no-held-episodes",
        action="store_true",
        help="Skip rebalance_log held-book hold/swap episode ingest",
    )
    parser.add_argument("--json", action="store_true", help="Print full review JSON")
    args = parser.parse_args(argv)

    signal_set = frozenset(s.strip() for s in args.signals.split(",") if s.strip())
    track_ids = tuple(t.strip() for t in args.tracks.split(",") if t.strip()) or ("rules",)
    config = ExitTimingArchiveSimConfig(
        min_conviction=(
            float(args.min_conviction)
            if args.min_conviction is not None
            else DEFAULT_MIN_CONVICTION
        ),
        min_data_quality=float(args.min_data_quality),
        near_miss_signals=signal_set or frozenset({"hold"}),
        max_episodes_per_week=(
            int(args.max_episodes_per_week)
            if args.max_episodes_per_week is not None
            else DEFAULT_MAX_EPISODES_PER_WEEK
        ),
        include_held_episodes=not args.no_held_episodes,
        paper_root=args.paper_root,
        track_ids=track_ids,
    )
    review = run_exit_timing_archive_sim(args.output_dir, config=config)

    if args.json:
        print(json.dumps(review, indent=2))
    else:
        print(format_exit_timing_archive_text(review))
    return 0


if __name__ == "__main__":
    sys.exit(main())
