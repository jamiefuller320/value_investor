"""CLI for hypothesis outcome linker (thesis-at-start vs cohort outcomes)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from value_investor.hypothesis_outcome_linker import (
    ROLLUP_FILENAME,
    run_hypothesis_outcome_link_pass,
    summarize_learning_tracks_hypothesis_outcomes,
)
from value_investor.paper_automation import (
    DEFAULT_AUTOMATION_DIR,
    learning_track_dirs,
    load_screen_candidates,
)

DEFAULT_REPORTS = Path("docs/data/latest.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Link thesis_status_at_start on exit_timing cohorts to hold-recovery and "
            "swap outcomes (observe-only learning loop)."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_AUTOMATION_DIR)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--tracks", default="all")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    base_dir = Path(args.output_dir)
    dirs = learning_track_dirs(base_dir)
    selected = (
        list(dirs.keys())
        if str(args.tracks).strip().lower() == "all"
        else [t.strip() for t in str(args.tracks).split(",") if t.strip()]
    )
    candidates = load_screen_candidates(Path(args.reports))
    reviews: dict[str, Any] = {}
    for track_id in selected:
        track_dir = dirs.get(track_id) or (base_dir / track_id)
        if not track_dir.exists():
            continue
        reviews[track_id] = run_hypothesis_outcome_link_pass(
            output_dir=track_dir,
            track_id=track_id,
            candidates=candidates,
        )

    rollup = summarize_learning_tracks_hypothesis_outcomes(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / ROLLUP_FILENAME).write_text(json.dumps(rollup, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps({"tracks": reviews, "rollup": rollup}, indent=2))
    else:
        print(f"Linked outcomes for {len(reviews)} track(s)")
        print(f"Rollup: {base_dir / ROLLUP_FILENAME}")
        for track_id, review in reviews.items():
            readiness = review.get("readiness") or {}
            hold = review.get("hold_recovery_by_thesis") or {}
            print(
                f"  {track_id}: closed={hold.get('closed_total')} "
                f"ready={readiness.get('ready_for_thesis_outcome_analysis')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
