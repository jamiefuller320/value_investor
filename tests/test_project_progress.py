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
        decision_input_path=data_dir / "decision_input_inventory.json",
    )

    assert payload["current_focus"] == "stage_2b"
    assert len(payload["stages"]) >= 5
    assert payload["ingest_bottleneck"]["stalled"] is True
    assert payload["ingest_bottleneck"]["zero_body_buy_tier"] == 1
    assert any("AI-judgment" in row for row in payload["appraisal"]["strengths"])
    assert any("buy-tier filing depth" in row for row in payload["appraisal"]["next_actions"])


def test_build_project_progress_prefers_memo_recent_when_bodies_green(tmp_path: Path):
    """L483: policy-green bodies must not keep 'prioritise filing depth' as next action."""
    data_dir = tmp_path / "docs/data"
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True)

    write_json(
        data_dir / "latest.json",
        {
            "run_at": "2026-09-27T18:20:46+00:00",
            "meta": {"company_count": 248, "strong_buy_count": 16},
        },
    )
    write_json(data_dir / "automation.json", {"settings": {"library": {"graduated_count": 12}}})
    write_json(
        paper / "ai_judgment/decision_review.json",
        {"applied": True, "metrics": {"excess_after_costs": -0.01, "total_return": 0.0}},
    )
    write_json(
        paper / "decision_review.json",
        {"applied": True, "metrics": {"excess_after_costs": -0.02, "total_return": -0.01}},
    )
    write_json(
        data_dir / "ingest_health_log.json",
        {"entries": [{"delta_zero_body": 0, "health_after": {"zero_body_buy_tier": 0}}]},
    )
    write_json(
        data_dir / "decision_input_inventory.json",
        {
            "summary": {
                "gap_counts": {
                    "key_filing_bodies": 0,
                    "fcf_basis_bound": 0,
                    "overlay_bound": 1,
                    "memo_recent": 49,
                },
                "verdict": "memo_recent",
                "sunday_bind_field": "memo_recent",
            }
        },
    )

    payload = build_project_progress(
        latest_path=data_dir / "latest.json",
        automation_path=data_dir / "automation.json",
        ops_path=data_dir / "ops_status.json",
        ai_review_path=paper / "ai_judgment/decision_review.json",
        rules_review_path=paper / "decision_review.json",
        ingest_log_path=data_dir / "ingest_health_log.json",
        decision_input_path=data_dir / "decision_input_inventory.json",
    )

    assert payload["evidence"]["bodies_green"] is True
    assert payload["evidence"]["memo_recent_gaps"] == 49
    actions = payload["appraisal"]["next_actions"]
    assert any("memo_recent" in row for row in actions)
    assert not any("filing depth" in row for row in actions)
    assert any("memo_recent" in row for row in payload["appraisal"]["gaps"])


def test_write_project_progress(tmp_path: Path):
    out = tmp_path / "project_progress.json"
    payload = write_project_progress(path=out)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["schema_version"] == payload["schema_version"]
    assert saved["headline"]
