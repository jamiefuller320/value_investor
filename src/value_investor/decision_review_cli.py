"""CLI for decision-review learning on the automated paper book."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.decision_review import (
    compare_learning_tracks,
    format_review_text,
    run_decision_review,
)
from value_investor.paper_automation import (
    AI_JUDGMENT_TRACK_ID,
    DEFAULT_AUTOMATION_DIR,
    RULES_TRACK_ID,
    learning_track_dirs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Review automated paper-fund outcomes after costs and propose "
            "(or apply) small clamped trading-knob updates. "
            "Default --tracks all reviews the primary AI-judgment track and "
            "rules control against the market benchmark."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_AUTOMATION_DIR,
        help="Paper automation root (rules at root, ai_judgment/ subdir)",
    )
    parser.add_argument(
        "--tracks",
        default="all",
        choices=["all", "rules", "ai_judgment"],
        help="Which learning track(s) to review (default: all)",
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

    if args.tracks == "all":
        summary = compare_learning_tracks(
            base_dir=Path(args.output_dir),
            apply=bool(args.apply),
            force=bool(args.force),
            fetch_benchmark=not args.no_benchmark,
        )
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print("Learning-track review")
            print(f"  Primary: {summary.get('primary_learning_track')}")
            print(f"  Success: {summary.get('success_criterion')}")
            print(
                f"  Verdict: {summary.get('verdict')} "
                f"(beat_market={summary.get('beat_market')} "
                f"beat_control={summary.get('beat_control')})"
            )
            print(
                f"  Excess primary/control: "
                f"{summary.get('primary_excess_after_costs')} / "
                f"{summary.get('control_excess_after_costs')}"
            )
            for track_id, review in (summary.get("reviews") or {}).items():
                print()
                print(f"--- {track_id} ---")
                m = review.get("metrics") or {}
                print(f"  primary={review.get('is_primary_learning_track')}")
                print(f"  note={review.get('note')}")
                print(
                    f"  return={m.get('total_return')} excess={m.get('excess_after_costs')} "
                    f"marks={m.get('equity_marks')} trades={m.get('trade_count')}"
                )
                for reason in (review.get("reasons") or [])[:4]:
                    print(f"  - {reason}")
            print(f"\nWrote {Path(args.output_dir) / 'learning_tracks_review.json'}")
        return 0

    track_id = RULES_TRACK_ID if args.tracks == "rules" else AI_JUDGMENT_TRACK_ID
    track_dir = learning_track_dirs(Path(args.output_dir))[track_id]
    result = run_decision_review(
        output_dir=track_dir,
        apply=bool(args.apply),
        force=bool(args.force),
        fetch_benchmark=not args.no_benchmark,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_review_text(result))
        print(f"\nWrote {track_dir / 'decision_review.json'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
