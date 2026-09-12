"""Tests for idle-queue compile backstop."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_tasks import compile_engineering_tasks, ensure_post_run_review_artifact
from value_investor.idle_compile_backstop import (
    evaluate_idle_compile_backstop,
    run_idle_compile_backstop,
)
from value_investor.storage import write_json


def test_ensure_post_run_artifact_from_latest(tmp_path: Path):
    latest = tmp_path / "latest.json"
    write_json(
        latest,
        {
            "post_run_review": {
                "improvement_plan": "1. [scoring] Export failed_models — expected impact: tests",
            }
        },
    )
    output_dir = tmp_path / "output"
    path = ensure_post_run_review_artifact(output_dir=output_dir, latest_path=latest)
    assert path is not None
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "[scoring]" in text


def test_idle_backstop_compiles_when_plan_unlinked(tmp_path: Path):
    data_dir = tmp_path / "docs/data"
    data_dir.mkdir(parents=True)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    latest = data_dir / "latest.json"
    write_json(
        latest,
        {
            "run_at": "2026-09-12T08:00:00+00:00",
            "post_run_review": {
                "improvement_plan": (
                    "1. [scoring] Wire overlay export for tests — expected impact: quality"
                ),
            },
        },
    )
    tasks_path = data_dir / "engineering_tasks.json"
    write_json(tasks_path, {"tasks": []})

    missing_suggestions = tmp_path / "no_suggestions.json"
    decision = evaluate_idle_compile_backstop(
        tasks_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest,
        suggestions_path=missing_suggestions,
    )
    assert decision.should_compile is True

    result = run_idle_compile_backstop(
        apply=True,
        tasks_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest,
        suggestions_path=missing_suggestions,
    )
    assert result["applied"] is True
    assert int((result.get("compile") or {}).get("added_open_count") or 0) == 1
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert any(row.get("status") == "open" for row in payload.get("tasks") or [])


def test_idle_backstop_skips_when_tasks_already_merged(tmp_path: Path):
    data_dir = tmp_path / "docs/data"
    data_dir.mkdir(parents=True)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    plan_line = "1. [scoring] Wire overlay export for tests — expected impact: quality"
    latest = data_dir / "latest.json"
    write_json(
        latest,
        {
            "run_at": "2026-09-12T08:00:00+00:00",
            "post_run_review": {"improvement_plan": plan_line},
        },
    )
    (output_dir / "post_run_review.md").write_text(
        f"PRIORITISED IMPROVEMENT PLAN\n{plan_line}",
        encoding="utf-8",
    )
    tasks_path = data_dir / "engineering_tasks.json"
    missing_suggestions = tmp_path / "no_suggestions.json"
    compile_engineering_tasks(
        output_dir=output_dir,
        max_tasks=5,
        tasks_path=tasks_path,
        committed_path=tasks_path,
        suggestions_path=missing_suggestions,
    )
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    for row in payload["tasks"]:
        row["status"] = "merged"

    write_json(tasks_path, payload)

    decision = evaluate_idle_compile_backstop(
        tasks_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest,
        suggestions_path=missing_suggestions,
    )
    assert decision.should_compile is False
    assert "would not add open" in decision.reason
