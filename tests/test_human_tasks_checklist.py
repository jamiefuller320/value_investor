"""Tests for human tasks checklist manifest."""

from __future__ import annotations

from pathlib import Path

import pytest

from value_investor.human_tasks_checklist import (
    DEFAULT_CHECKLIST_PATH,
    doc_url_for_task,
    load_human_tasks_checklist,
    validate_human_tasks_checklist,
)


def test_default_checklist_loads_and_validates():
    payload = load_human_tasks_checklist()
    assert payload["version"] >= 1
    assert payload["sections"]
    assert validate_human_tasks_checklist(payload) == []


def test_doc_url_for_task_with_anchor():
    task = {
        "doc_path": "docs/ops/knob-calibration.md",
        "doc_anchor": "promoting-a-prior-human-gate",
    }
    url = doc_url_for_task(task, repo_docs_base="https://example.com/blob/main")
    assert url.endswith("docs/ops/knob-calibration.md#promoting-a-prior-human-gate")


def test_validate_rejects_duplicate_task_ids():
    payload = load_human_tasks_checklist()
    broken = dict(payload)
    first_task = dict(broken["sections"][0]["tasks"][0])
    broken["sections"] = [
        {
            "id": "dup",
            "title": "Dup",
            "cadence": "test",
            "tasks": [first_task, dict(first_task)],
        }
    ]
    errors = validate_human_tasks_checklist(broken)
    assert any("duplicate task id" in err for err in errors)


def test_checklist_file_exists():
    assert DEFAULT_CHECKLIST_PATH.is_file()


@pytest.mark.parametrize("section", load_human_tasks_checklist()["sections"])
def test_each_section_has_human_or_automated_tasks(section):
    tasks = section.get("tasks") or []
    assert tasks
    for task in tasks:
        assert task.get("title")
        assert "automated" in task
        assert task.get("doc_path")


def test_sunday_analysis_tasks_locks_thin_memo_promotion():
    payload = load_human_tasks_checklist()
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == "sunday-analysis-tasks")
    assert "thin_memo_counted_as_coverage" in row["summary"]
    assert "rememo-eligibility widening" in row["summary"]


def test_sunday_entry_dca_follows_adoption_plan():
    payload = load_human_tasks_checklist()
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == "sunday-entry-dca-cadence")
    assert "entry_dca_adoption_plan" in row["summary"]
    assert "Do not execute DCA from ack" in row["summary"]
    assert "Lifecycle Start" in row["summary"]
    assert "graduated_allocation" in row["summary"]


def test_l694_observe_ceiling_review_is_a_human_task():
    payload = load_human_tasks_checklist()
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == "adhoc-l694-observe-memo-ceiling-review")
    assert row["automated"] is False
    assert row["doc_path"] == "docs/ops/strategy-book-observe.md"
    assert row["doc_anchor"] == "ceiling-review"
    assert "2026-11-30" in row["summary"]
    assert "Europe/London" in row["summary"]
    assert "$640" in row["summary"]
    assert "1600" in row["summary"]
    assert "Composer credit is spare" in row["summary"]
    assert "$40" in row["summary"]
    assert "above $640" in row["summary"]
    assert "influences_live" in row["summary"]
    assert "forward_live" in row["summary"]


def test_sunday_shadow_endurance_urgency_policy():
    payload = load_human_tasks_checklist()
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == "sunday-shadow-endurance")
    summary = row["summary"]
    assert "do-now" in summary
    assert "Failed" in summary
    assert "entry_dca_overlay" in summary
    assert "ana-*" in summary
    assert "auto-promote" in summary.lower()
    assert "N58" in summary or "N59" in summary


def test_weekday_parked_backlog_quiet_auto_ack_policy():
    payload = load_human_tasks_checklist()
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == "weekday-engineering-parked-backlog-clear")
    assert row["automated"] is False
    summary = row["summary"]
    assert "attention_parked_count=0" in summary
    assert "queue_clearing.pause_active=false" in summary
    assert "auto-acks" in summary.lower() or "auto-ack" in summary.lower()
    assert "list-parked" in summary
    assert "recover-queue" in summary


def test_version_review_reads_post_sale_notes():
    payload = load_human_tasks_checklist()
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == "adhoc-strategy-version-review")
    assert row["automated"] is False
    summary = row["summary"]
    assert "strategy_book_post_sale_notes.json" in summary
    assert "learning point" in summary
    assert "do not change the registered exit" in summary
    md = (Path(__file__).resolve().parents[1] / "docs/ops/human-tasks-checklist.md").read_text(
        encoding="utf-8"
    )
    assert "strategy_book_post_sale_notes.json" in md
    assert "learning point grounded in the rule that fired" in md


def test_sprint2_workflow_pat_is_a_human_task():
    payload = load_human_tasks_checklist()
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == "weekday-workflow-dispatch-pat-sprint-2")
    assert row["automated"] is True
    assert row["doc_path"] == "docs/ops/engineering-sync.md"
    assert row["doc_anchor"] == "pat-setup-one-time"
    summary = row["summary"]
    assert "eng-20261112-02" in summary
    assert "library-ingest-sprint-2.yml" in summary
    assert "43460958952" in summary
    assert "library_ingest_sprint_2.json" in summary
    assert "Do not grant another PAT scope" in summary
    assert "WORKFLOW_DISPATCH_PAT already has Workflows" in summary
