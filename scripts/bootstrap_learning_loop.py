#!/usr/bin/env python3
"""Refresh research overlay, bootstrap paper tracks, and publish dashboard data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from value_investor.decision_review import compare_learning_tracks
from value_investor.paper_automation import run_learning_tracks
from value_investor.publish import publish_dashboard
from value_investor.research.overlay import apply_research_overlay, enrich_signals_with_research
from value_investor.research.store import ResearchStore
from value_investor.storage import write_json
from value_investor.summary import build_company_reports

DEFAULT_OUTPUT = Path("output")
DEFAULT_PAPER = Path("docs/data/paper_automation")
DEFAULT_DASHBOARD = Path("docs")


def refresh_research_overlay(output_dir: Path = DEFAULT_OUTPUT) -> int:
    """Re-apply point-in-time research fields to signals CSV and email reports."""
    signals_path = output_dir / "latest_signals.csv"
    models_path = output_dir / "latest_model_results.csv"
    if not signals_path.exists() or not models_path.exists():
        raise SystemExit(f"Missing screen outputs under {output_dir}")

    signals = pd.read_csv(signals_path)
    signals = enrich_signals_with_research(signals, output_dir)
    signals.to_csv(signals_path, index=False)

    model_results = pd.read_csv(models_path)
    reports = build_company_reports(signals, model_results)
    documents = ResearchStore(output_dir).list_documents()
    reports = apply_research_overlay(reports, documents)
    write_json(output_dir / "email_reports.json", [r.to_dict() for r in reports], compact=True)
    return len(documents)


def main() -> int:
    doc_count = refresh_research_overlay()
    print(f"Refreshed research overlay for {doc_count} memos")

    paper_dir = DEFAULT_PAPER
    paper_dir.mkdir(parents=True, exist_ok=True)
    summary = run_learning_tracks(
        base_dir=paper_dir,
        reports_path=DEFAULT_OUTPUT / "email_reports.json",
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
