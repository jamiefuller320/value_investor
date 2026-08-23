"""CLI for exclusion-ladder rebalance_log replay and shadow spawn."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.exclusion_ladder_replay import (
    DEFAULT_PARENT_TRACK,
    DEFAULT_TRACKS,
    format_exclusion_ladder_replay_text,
    run_exclusion_ladder_replay,
    spawn_exclusion_shadow,
    warm_start_exclusion_shadow,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay exclusion ladder priors on paper rebalance_log with costs; "
            "optionally spawn a frozen exclusion shadow track."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Replay ladder across paper tracks")
    run_p.add_argument(
        "--paper-root",
        type=Path,
        default=Path("docs/data/paper_automation"),
    )
    run_p.add_argument(
        "--data-dir",
        type=Path,
        default=Path("docs/data"),
        help="Root containing exclusion_universe_review.json",
    )
    run_p.add_argument(
        "--tracks",
        type=str,
        default=",".join(DEFAULT_TRACKS),
        help="Comma-separated track ids (default: ai_judgment,rules)",
    )
    run_p.add_argument("--json", action="store_true")

    spawn_p = sub.add_parser("spawn-shadow", help="Create exclusion shadow track from recommended step")
    spawn_p.add_argument("--paper-root", type=Path, default=Path("docs/data/paper_automation"))
    spawn_p.add_argument("--data-dir", type=Path, default=Path("docs/data"))
    spawn_p.add_argument("--parent-track", type=str, default=DEFAULT_PARENT_TRACK)
    spawn_p.add_argument("--step-id", type=str, default=None)
    spawn_p.add_argument("--no-warm-start", action="store_true")
    spawn_p.add_argument("--force", action="store_true")
    spawn_p.add_argument("--json", action="store_true")

    warm_p = sub.add_parser("warm-start", help="Replay parent log into existing exclusion shadow")
    warm_p.add_argument("--paper-root", type=Path, default=Path("docs/data/paper_automation"))
    warm_p.add_argument("--step-id", type=str, required=True)
    warm_p.add_argument("--parent-track", type=str, default=DEFAULT_PARENT_TRACK)
    warm_p.add_argument("--force", action="store_true")
    warm_p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "run":
        tracks = tuple(t.strip() for t in args.tracks.split(",") if t.strip()) or DEFAULT_TRACKS
        review = run_exclusion_ladder_replay(
            args.paper_root,
            data_dir=args.data_dir,
            tracks=tracks,
        )
        if args.json:
            print(json.dumps(review, indent=2))
        else:
            print(format_exclusion_ladder_replay_text(review))
        return 0

    if args.command == "spawn-shadow":
        result = spawn_exclusion_shadow(
            args.paper_root,
            data_dir=args.data_dir,
            parent_track_id=args.parent_track,
            step_id=args.step_id,
            warm_start=not args.no_warm_start,
            force=args.force,
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(result, indent=2))
        return 0 if result.get("spawned") else 1

    if args.command == "warm-start":
        result = warm_start_exclusion_shadow(
            args.paper_root,
            step_id=args.step_id,
            parent_track_id=args.parent_track,
            force=args.force,
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(result, indent=2))
        return 0 if result.get("warm_started") else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
