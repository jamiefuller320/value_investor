#!/usr/bin/env python3
"""Refresh research overlay, bootstrap paper tracks, and publish dashboard data."""

from __future__ import annotations

from pathlib import Path

from value_investor.decision_review import compare_learning_tracks
from value_investor.paper_automation import run_learning_tracks
from value_investor.publish import publish_dashboard
from value_investor.research.overlay_refresh import refresh_paper_auto_reports

DEFAULT_OUTPUT = Path("output")
DEFAULT_PAPER = Path("docs/data/paper_automation")
DEFAULT_DASHBOARD = Path("docs")


def main() -> int:
    reports_path = refresh_paper_auto_reports(
        bundle_path=DEFAULT_DASHBOARD / "data" / "latest.json",
        output_dir=DEFAULT_OUTPUT,
    )
    print(f"Refreshed research overlay (reports: {reports_path})")

    paper_dir = DEFAULT_PAPER
    paper_dir.mkdir(parents=True, exist_ok=True)
    summary = run_learning_tracks(
        base_dir=paper_dir,
        reports_path=reports_path,
        force=True,
    )
    for track_id, row in (summary.get("tracks") or {}).items():
        print(
            f"paper-auto [{track_id}]: acted={row.get('acted')} "
            f"trades={row.get('trades')} — {row.get('note')}"
        )

    review = compare_learning_tracks(
        base_dir=paper_dir,
        force=True,
        apply=False,
    )
    print(f"decision-review verdict: {review.get('verdict')}")

    publish_path = publish_dashboard(output_dir=DEFAULT_OUTPUT, dest_dir=DEFAULT_DASHBOARD)
    print(f"Published dashboard to {publish_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
