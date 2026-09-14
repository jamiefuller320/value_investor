"""Tests for ftse-progress-report."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.progress_report import (
    build_actionable_items,
    build_integration_checks,
    build_progress_report,
    build_role_coherence,
    format_progress_report_markdown,
    write_progress_report,
)
from value_investor.storage import write_json


def _seed_minimal(tmp_path: Path) -> dict[str, Path]:
    data_dir = tmp_path / "docs/data"
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True)

    write_json(
        data_dir / "latest.json",
        {
            "run_at": "2026-08-27T18:00:00+00:00",
            "meta": {"company_count": 240, "strong_buy_count": 12},
        },
    )
    write_json(
        data_dir / "automation.json",
        {"settings": {"library": {"focus_market": "smi", "graduated_count": 12}}},
    )
    write_json(
        paper / "ai_judgment/decision_review.json",
        {"applied": True, "metrics": {"excess_after_costs": -0.02}},
    )
    write_json(
        paper / "decision_review.json",
        {"applied": True, "metrics": {"excess_after_costs": -0.05}},
    )
    write_json(
        data_dir / "ops_status.json",
        {"run_at": "2026-08-27T12:00:00+00:00", "overall": "ok"},
    )
    write_json(
        data_dir / "engineering_tasks.json",
        {
            "tasks": [
                {
                    "id": "eng-test-01",
                    "title": "Fix ingest stall",
                    "status": "open",
                    "allowed_paths": ["src/value_investor/ingest_loop.py"],
                }
            ]
        },
    )
    write_json(
        data_dir / "analysis_tasks.json",
        {
            "tasks": [
                {
                    "id": "ana-01",
                    "title": "Shadow knob trial",
                    "status": "proposed",
                    "added_at": "2026-08-20T10:00:00+00:00",
                }
            ]
        },
    )
    write_json(
        data_dir / "analysis_review.json",
        {"reviewed_at": "2026-08-27T10:35:00+00:00"},
    )
    write_json(
        tmp_path / "docs/deferred-ideas.json",
        {
            "version": 1,
            "updated_at": "2026-08-27T00:00:00+00:00",
            "ideas": [
                {
                    "id": "N1",
                    "category": "not_now",
                    "section": "not_now",
                    "title": "Expand to US live screen",
                    "summary": "Wait for stage 2b edge.",
                    "revisit_when": "AI excess > 0 for 8 weeks",
                    "status": "open",
                },
                {
                    "id": "L1",
                    "category": "later",
                    "section": "learning",
                    "title": "Walk-forward evolution",
                    "summary": "Stage 5 work.",
                    "status": "now",
                },
            ],
            "fragments": [{"id": "frag-20260827-01", "text": "Try sector caps", "status": "open"}],
        },
    )
    return {
        "data_dir": data_dir,
        "store": tmp_path / "docs/deferred-ideas.json",
        "tasks": data_dir / "engineering_tasks.json",
    }


def test_build_actionable_items_groups_deferred_and_queues(tmp_path: Path):
    paths = _seed_minimal(tmp_path)
    payload = build_actionable_items(
        store_path=paths["store"],
        tasks_path=paths["tasks"],
        data_dir=paths["data_dir"],
    )
    assert payload["counts"]["defer_now"] == 1
    assert payload["counts"]["defer_not_now"] == 1
    assert payload["counts"]["open_fragments"] == 1
    assert payload["counts"]["proposed_total"] == 1
    assert payload["counts"]["engineering_open"] == 1


def test_build_progress_report_schema(tmp_path: Path, monkeypatch):
    paths = _seed_minimal(tmp_path)
    monkeypatch.chdir(tmp_path)

    payload = build_progress_report(
        latest_path=paths["data_dir"] / "latest.json",
        ops_path=paths["data_dir"] / "ops_status.json",
        tasks_path=paths["tasks"],
        store_path=paths["store"],
        data_dir=paths["data_dir"],
    )

    assert payload["schema_version"] == 1
    assert payload["progress"]["current_focus"] == "stage_2b"
    assert "actionable" in payload
    assert "integration" in payload
    assert "role_coherence" in payload
    assert payload["overall"] in {"ok", "info", "warn", "fail"}


def test_role_coherence_flags_post_run_plan_without_queue_link(tmp_path: Path):
    paths = _seed_minimal(tmp_path)
    latest = paths["data_dir"] / "latest.json"
    payload = json.loads(latest.read_text(encoding="utf-8"))
    payload["post_run_review"] = {
        "improvement_plan": (
            "1. [scoring] Implement unique overlay export never in queue — expected impact: test"
        ),
    }
    latest.write_text(json.dumps(payload), encoding="utf-8")
    checks = build_role_coherence(
        progress={"current_focus": "stage_2b", "evidence": {}},
        actionable={"defer_now": [], "proposed_tasks": {}, "engineering_open": []},
        tasks_path=paths["tasks"],
        latest_path=latest,
    )
    assert any(row["id"] == "post_run_plan_without_queue_link" for row in checks)


def test_role_coherence_post_run_terminal_only_is_info(tmp_path: Path):
    paths = _seed_minimal(tmp_path)
    latest = paths["data_dir"] / "latest.json"
    plan_line = "Implement unique overlay export never in queue — expected impact: test"
    payload = json.loads(latest.read_text(encoding="utf-8"))
    payload["post_run_review"] = {"improvement_plan": f"1. [scoring] {plan_line}"}
    latest.write_text(json.dumps(payload), encoding="utf-8")
    tasks = paths["tasks"]
    task_payload = json.loads(tasks.read_text(encoding="utf-8"))
    task_payload["tasks"] = [
        {
            "id": "eng-parked-01",
            "title": plan_line,
            "status": "parked",
            "allowed_paths": ["src/value_investor/pipeline.py"],
        }
    ]
    tasks.write_text(json.dumps(task_payload), encoding="utf-8")
    checks = build_role_coherence(
        progress={"current_focus": "stage_2b", "evidence": {}},
        actionable={"defer_now": [], "proposed_tasks": {}, "engineering_open": []},
        tasks_path=tasks,
        latest_path=latest,
    )
    row = next(row for row in checks if row["id"] == "post_run_plan_without_queue_link")
    assert row["severity"] == "info"


def test_build_integration_checks_passes_open_prs(tmp_path: Path, monkeypatch):
    paths = _seed_minimal(tmp_path)
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def fake_check_engineering_queue(*, tasks_path, open_prs=None):
        captured["open_prs"] = open_prs
        return [], {"open_count": 0}

    def fake_check_engineering_sync(*, tasks_path, open_prs=None):
        captured["sync_open_prs"] = open_prs
        return [], None

    monkeypatch.setattr(
        "value_investor.progress_report.check_engineering_queue",
        fake_check_engineering_queue,
    )
    monkeypatch.setattr(
        "value_investor.progress_report.check_engineering_sync",
        fake_check_engineering_sync,
    )
    monkeypatch.setattr(
        "value_investor.progress_report._github_token",
        lambda: "token",
    )
    monkeypatch.setattr(
        "value_investor.progress_report.list_open_pull_requests",
        lambda: [{"headRefName": "cursor/eng-test-01"}],
    )
    build_integration_checks(
        latest_path=paths["data_dir"] / "latest.json",
        ops_path=paths["data_dir"] / "ops_status.json",
        tasks_path=paths["tasks"],
    )
    assert captured["open_prs"] == [{"headRefName": "cursor/eng-test-01"}]
    assert captured["sync_open_prs"] == [{"headRefName": "cursor/eng-test-01"}]


def test_role_coherence_flags_unlinked_defer_now(tmp_path: Path):
    paths = _seed_minimal(tmp_path)
    progress = {"current_focus": "stage_2b", "evidence": {"ai_excess_after_costs": -0.02}}
    actionable = build_actionable_items(
        store_path=paths["store"],
        tasks_path=paths["tasks"],
        data_dir=paths["data_dir"],
    )
    checks = build_role_coherence(
        progress=progress,
        actionable=actionable,
        tasks_path=paths["tasks"],
        latest_path=paths["data_dir"] / "latest.json",
        analysis_review_path=paths["data_dir"] / "analysis_review.json",
    )
    assert any(row["id"] == "defer_now_without_queue_link" for row in checks)


def test_write_progress_report_and_markdown(tmp_path: Path, monkeypatch):
    paths = _seed_minimal(tmp_path)
    monkeypatch.chdir(tmp_path)

    out_json = tmp_path / "docs/data/progress_report.json"
    out_md = tmp_path / "docs/data/progress_report.md"
    payload = write_progress_report(
        json_path=out_json,
        markdown_path=out_md,
        latest_path=paths["data_dir"] / "latest.json",
        ops_path=paths["data_dir"] / "ops_status.json",
        tasks_path=paths["tasks"],
        store_path=paths["store"],
        data_dir=paths["data_dir"],
    )
    saved = json.loads(out_json.read_text(encoding="utf-8"))
    assert saved["schema_version"] == payload["schema_version"]
    md = out_md.read_text(encoding="utf-8")
    assert "# FTSE progress report" in md
    assert "Overall progress" in format_progress_report_markdown(payload)
