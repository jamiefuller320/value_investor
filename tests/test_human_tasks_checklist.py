"""Tests for human tasks checklist manifest."""

from __future__ import annotations

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
