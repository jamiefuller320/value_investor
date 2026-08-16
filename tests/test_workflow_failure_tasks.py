"""Tests for workflow failure signature matching and task drafting."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_tasks import load_engineering_tasks
from value_investor.workflow_failure_tasks import (
    draft_workflow_failure_task,
    match_workflow_failure_signature,
)

INGEST_LOG = """
ftse-ingest-loop run failed
curl_cffi.requests.exceptions.HTTPError: Failed to perform
"""


def test_match_ingest_loop_signature():
    spec = match_workflow_failure_signature("ingest-loop.yml", INGEST_LOG)
    assert spec is not None
    assert spec["area"] == "ingest"


def test_match_library_grow_json_error():
    log = "json.decoder.JSONDecodeError: Expecting ':' delimiter while reading last_ladder.json"
    spec = match_workflow_failure_signature("library-grow.yml", log)
    assert spec is not None
    assert "library-grow.yml" in spec["allowed_paths"][0]


def test_no_match_returns_none():
    assert match_workflow_failure_signature("ingest-loop.yml", "everything ok") is None


def test_draft_workflow_failure_task_appends_open_task(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    drafted = draft_workflow_failure_task(
        workflow_file="ingest-loop.yml",
        log_text=INGEST_LOG,
        run_id=99,
        tasks_path=tasks_path,
    )
    assert drafted
    payload = load_engineering_tasks(tasks_path)
    task = payload["tasks"][0]
    assert task["source"] == "workflow_failure"
    assert task["evidence"]["workflow"] == "ingest-loop.yml"
