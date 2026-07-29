"""Tests for dashboard project progress appraisal."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.project_progress import build_project_progress, write_project_progress
from value_investor.storage import write_json


def test_build_project_progress_includes_stages_and_ingest(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "docs/data"
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True)

    write_json(
        data_dir / "latest.json",
        {
            "run_at": "2026-07-26T18:20:46+00:00",
            "meta": {"company_count": 248, "strong_buy_count": 16},
        },
    )
    write_json(
        data_dir / "automation.json",
        {
            "settings": {
                "library": {
                    "focus_market": "smi",
                    "graduated_count": 18,
                    "graduated_markets": [{"market": "sp500"}],
                }
            }
        },
    )
    write_json(
        paper / "ai_judgment/decision_review.json",
        {
            "applied": True,
            "metrics": {"excess_after_costs": -0.038, "total_return": -0.029},
        },
    )
    write_json(
        paper / "decision_review.json",
        {
            "applied": True,
            "metrics": {"excess_after_costs": -0.13, "total_return": -0.11},
        },
    )
    write_json(
        data_dir / "ingest_health_log.json",
        {
            "entries": [
                {
                    "delta_zero_body": 0,
                    "health_after": {"zero_body_buy_tier": 1},
                }
            ]
        },
    )

    payload = build_project_progress(
        latest_path=data_dir / "latest.json",
        automation_path=data_dir / "automation.json",
        ops_path=data_dir / "ops_status.json",
        ai_review_path=paper / "ai_judgment/decision_review.json",
        rules_review_path=paper / "decision_review.json",
        ingest_log_path=data_dir / "ingest_health_log.json",
    )

    assert payload["current_focus"] == "stage_2b"
    assert len(payload["stages"]) >= 5
    assert payload["ingest_bottleneck"]["stalled"] is True
    assert payload["ingest_bottleneck"]["zero_body_buy_tier"] == 1
    assert any("AI-judgment" in row for row in payload["appraisal"]["strengths"])


def test_write_project_progress(tmp_path: Path):
    out = tmp_path / "project_progress.json"
    payload = write_project_progress(path=out)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["schema_version"] == payload["schema_version"]
    assert saved["headline"]
