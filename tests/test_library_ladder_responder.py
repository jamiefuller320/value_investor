"""Tests for library ladder failure classification and recovery decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.library_ladder_responder import (
    ACTION_RERUN,
    CLASS_CORRUPT_LAST_LADDER,
    CLASS_PARTIAL_SUCCESS,
    CLASS_TRANSIENT,
    classify_library_ladder_failure,
    evaluate_library_ladder_response,
    rerun_cooldown_active,
    respond_to_library_ladder_failure,
    workflow_fix_present,
)

SUNDAY_LOG = """
Run offline ladder
Graduated market: iseq20
Wrote: docs/data/automation.json
json.decoder.JSONDecodeError: Expecting ':' delimiter: line 4 column 22 (char 99)
##[error]Process completed with exit code 1.
"""

CORRUPT_LOG = """
json.decoder.JSONDecodeError: Expecting ':' delimiter: line 4 column 22 (char 99)
open('$ROOT/last_ladder.json')
"""


def test_classify_partial_success_after_graduation():
    result = classify_library_ladder_failure(SUNDAY_LOG)
    assert result.kind == CLASS_PARTIAL_SUCCESS


def test_classify_corrupt_last_ladder():
    result = classify_library_ladder_failure(CORRUPT_LOG)
    assert result.kind == CLASS_CORRUPT_LAST_LADDER


def test_classify_transient_network():
    result = classify_library_ladder_failure("curl: (28) Operation timed out after 30000ms")
    assert result.kind == CLASS_TRANSIENT


def test_workflow_fix_present_on_current_workflow():
    assert workflow_fix_present(Path(".github/workflows/library-grow.yml"))


def test_evaluate_partial_success_requests_rerun(tmp_path: Path):
    log_path = tmp_path / "ladder_responder_log.json"
    classification = classify_library_ladder_failure(SUNDAY_LOG)
    decision = evaluate_library_ladder_response(classification, log_path=log_path)
    assert decision.should_rerun is True
    assert decision.action == ACTION_RERUN


def test_rerun_cooldown_blocks_second_dispatch(tmp_path: Path):
    log_path = tmp_path / "ladder_responder_log.json"
    now = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
    respond_to_library_ladder_failure(
        SUNDAY_LOG,
        run_id=1,
        log_path=log_path,
        now=now,
    )
    active, reason = rerun_cooldown_active(log_path=log_path, now=now + timedelta(hours=1))
    assert active is True
    assert "cooldown" in reason


def test_valid_last_ladder_json_on_disk(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    ladder_path = library / "last_ladder.json"
    ladder_path.write_text(json.dumps({"run_at": "2026-08-16T08:00:00+00:00"}), encoding="utf-8")
    workflow = tmp_path / "library-grow.yml"
    workflow.write_text(
        "# run_library_ladder already writes\njson.load(open('$ROOT/last_ladder.json'))\n",
        encoding="utf-8",
    )
    result = classify_library_ladder_failure(
        "Process completed with exit code 1",
        ladder_json_path=ladder_path,
        workflow_path=workflow,
    )
    assert result.kind == CLASS_PARTIAL_SUCCESS
    assert result.ladder_json_valid is True
