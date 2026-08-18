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
