"""Tests for weekday ingest-assess loop."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.engineering_tasks import (
    EngineeringTask,
    compile_ingest_engineering_tasks_micro,
    task_title_key,
)
from value_investor.ingest_loop import (
    IngestLoopResult,
    append_health_log_entry,
    ingest_health_stalled,
    load_health_log_payload,
    reports_from_latest,
)
from value_investor.ingest_loop_cli import main
from value_investor.research.ingest_improvement import IngestImprovementSummary


def test_reports_from_latest_builds_company_reports(tmp_path: Path):
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "ticker": "BT-A.L",
                        "name": "BT Group",
                        "signal": "buy",
                        "models_passed": 10,
                        "model_count": 22,
                        "composite_score": 0.8,
                        "sector_composite_score": 0.7,
                        "families_passed": 4,
                        "passed_families": "cheapness",
                        "data_quality_score": 1.0,
                        "metrics_present": 20,
                        "metrics_total": 20,
                        "weeks_at_signal": 1,
                        "signal_trend": "new",
                        "conviction_score": 0.5,
                        "stability_label": "new",
                        "timing_signal": "neutral",
                        "timing_score": 0.0,
                        "action_note": "",
                        "summary": "Test",
                        "passed_models": [],
                        "key_metrics": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    reports = reports_from_latest(latest)
    assert len(reports) == 1
    assert reports[0].ticker == "BT-A.L"
    assert reports[0].signal == "buy"


def test_load_health_log_payload_recovers_from_corrupt_json(tmp_path: Path):
    log_path = tmp_path / "ingest_health_log.json"
    log_path.write_text('{"entries": [{"run_at": "old"}]\n<<<<<<< conflict\n', encoding="utf-8")

    payload = load_health_log_payload(log_path)
    assert payload == {"entries": []}
    backups = list(tmp_path.glob("ingest_health_log.corrupt.*.json"))
    assert len(backups) == 1
    assert b"<<<<<<< conflict" in backups[0].read_bytes()


def test_append_health_log_entry_appends_after_corrupt_file(tmp_path: Path):
    log_path = tmp_path / "ingest_health_log.json"
    log_path.write_text("{not valid json", encoding="utf-8")

    result = append_health_log_entry({"run_at": "2026-07-29T00:00:00+00:00"}, path=log_path)

    assert len(result["entries"]) == 1
    assert result["entries"][0]["run_at"] == "2026-07-29T00:00:00+00:00"
    restored = json.loads(log_path.read_text(encoding="utf-8"))
    assert restored["entries"] == result["entries"]


def test_restored_health_log_enables_stall_detection():
    log_path = Path("docs/data/ingest_health_log.json")
    payload = load_health_log_payload(log_path, backup_corrupt=False)
    assert len(payload.get("entries") or []) >= 2
    # Committed log may be stalled or not depending on recent ingest runs.
    assert isinstance(ingest_health_stalled(log_path, min_runs=2), bool)


def test_ingest_health_stalled_requires_flat_zero_body_window(tmp_path: Path):
    log_path = tmp_path / "ingest_health_log.json"
    append_health_log_entry(
        {
            "health_before": {"zero_body_buy_tier": 5},
            "health_after": {"zero_body_buy_tier": 5},
        },
        path=log_path,
    )
    assert ingest_health_stalled(log_path, min_runs=2) is False
    append_health_log_entry(
        {
            "health_before": {"zero_body_buy_tier": 5},
            "health_after": {"zero_body_buy_tier": 5},
        },
        path=log_path,
    )
    assert ingest_health_stalled(log_path, min_runs=2) is True


def test_ingest_health_not_stalled_when_improving(tmp_path: Path):
    log_path = tmp_path / "ingest_health_log.json"
    for before, after in ((5, 5), (5, 4)):
        append_health_log_entry(
            {
                "health_before": {"zero_body_buy_tier": before},
                "health_after": {"zero_body_buy_tier": after},
            },
            path=log_path,
        )
    assert ingest_health_stalled(log_path, min_runs=2) is False


def test_compile_ingest_engineering_tasks_micro_appends_ingest_tasks(tmp_path: Path):
    suggestions = tmp_path / "suggestions.json"
    suggestions.write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "area": "ingest",
                        "priority": "high",
                        "suggestion": "Implement Companies House filed-accounts PDF fetch pipeline",
                        "ticker": "ITV.L",
                    },
                    {
                        "area": "scoring",
                        "priority": "high",
                        "suggestion": "Add healthcare overlay flag for negative FCF",
                        "ticker": "HIK.L",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    EngineeringTask(
                        id="eng-20260726-01",
                        area="scoring",
                        title="Old merged task",
                        summary="x",
                        priority="high",
                        priority_score=50.0,
                        source="post_run_review",
                        status="merged",
                    ).to_dict()
                ]
            }
        ),
        encoding="utf-8",
    )
    result = compile_ingest_engineering_tasks_micro(
        suggestions_path=suggestions,
        max_tasks=2,
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    assert result["compiled_count"] == 1
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    open_tasks = [row for row in payload["tasks"] if row.get("status") == "open"]
    assert len(open_tasks) == 1
    assert open_tasks[0]["area"] == "ingest"
    assert task_title_key(open_tasks[0]["title"]).startswith("implement companies house")


def test_compile_ingest_engineering_tasks_micro_ignores_open_hunter(tmp_path: Path):
    from value_investor.engineering_tasks import (
        PARKED_SOURCE_HUNTER_PRIORITY_SCORE,
        PARKED_SOURCE_HUNTER_SOURCE,
    )
    from value_investor.ingest_loop import has_open_ingest_engineering_tasks

    suggestions = tmp_path / "suggestions.json"
    suggestions.write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "area": "ingest",
                        "priority": "high",
                        "suggestion": "Implement Companies House filed-accounts PDF fetch pipeline",
                        "ticker": "ITV.L",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    EngineeringTask(
                        id="eng-20260906-01",
                        area="ingest",
                        title="Hunt fetchable IR source for parked sp500 leftover FICO",
                        summary="low priority hunter",
                        priority="low",
                        priority_score=PARKED_SOURCE_HUNTER_PRIORITY_SCORE,
                        source=PARKED_SOURCE_HUNTER_SOURCE,
                        status="open",
                    ).to_dict()
                ]
            }
        ),
        encoding="utf-8",
    )
    assert has_open_ingest_engineering_tasks(tasks_path) is False
    result = compile_ingest_engineering_tasks_micro(
        suggestions_path=suggestions,
        max_tasks=2,
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    assert result["compiled_count"] == 1


def test_compile_ingest_engineering_tasks_micro_skips_already_merged(tmp_path: Path):
    suggestions = tmp_path / "suggestions.json"
    suggestions.write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "area": "ingest",
                        "priority": "high",
                        "suggestion": "Implement Companies House filed-accounts PDF fetch pipeline",
                        "ticker": "ITV.L",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    merged_title = "Implement Companies House filed-accounts PDF fetch pipeline"
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    EngineeringTask(
                        id="eng-20260728-01",
                        area="ingest",
                        title=merged_title,
                        summary="done",
                        priority="high",
                        priority_score=99.0,
                        source="post_run_review",
                        status="merged",
                    ).to_dict()
                ]
            }
        ),
        encoding="utf-8",
    )
    result = compile_ingest_engineering_tasks_micro(
        suggestions_path=suggestions,
        max_tasks=2,
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    assert result["compiled_count"] == 0


def test_ingest_loop_cli_run_json_flag_parsing():
    result = IngestLoopResult(
        health_before={"zero_body_buy_tier": 2},
        health_after={"zero_body_buy_tier": 1},
        ingest_summary=None,
        micro_compiled=False,
    )
    with patch("value_investor.ingest_loop_cli.run_weekday_ingest_loop", return_value=result):
        assert main(["run", "--json", "--max-targets", "2"]) == 0


def test_ingest_loop_cli_writes_json_path(tmp_path: Path):
    out_path = tmp_path / "ingest_loop.json"
    result = IngestLoopResult(
        health_before={"zero_body_buy_tier": 2},
        health_after={"zero_body_buy_tier": 1},
        ingest_summary=None,
        micro_compiled=False,
        partial=True,
    )
    with patch("value_investor.ingest_loop_cli.run_weekday_ingest_loop", return_value=result):
        assert main(["run", "--json-path", str(out_path)]) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["partial"] is True
    assert payload["micro_compiled"] is False


def test_ingest_loop_cli_writes_json_path_on_failure(tmp_path: Path):
    out_path = tmp_path / "ingest_loop.json"
    with patch(
        "value_investor.ingest_loop_cli.run_weekday_ingest_loop",
        side_effect=RuntimeError("boom"),
    ):
        assert main(["run", "--json-path", str(out_path)]) == 1
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["error"] == "boom"


def test_run_weekday_ingest_loop_logs_book_deltas(tmp_path: Path, monkeypatch):
    from value_investor.ingest_loop import run_weekday_ingest_loop

    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "ticker": "BT-A.L",
                        "name": "BT",
                        "signal": "buy",
                        "models_passed": 10,
                        "model_count": 22,
                        "composite_score": 0.8,
                        "sector_composite_score": 0.7,
                        "families_passed": 4,
                        "passed_families": "cheapness",
                        "data_quality_score": 1.0,
                        "metrics_present": 20,
                        "metrics_total": 20,
                        "weeks_at_signal": 1,
                        "signal_trend": "new",
                        "conviction_score": 0.5,
                        "stability_label": "new",
                        "timing_signal": "neutral",
                        "timing_score": 0.0,
                        "action_note": "",
                        "summary": "Test",
                        "passed_models": [],
                        "key_metrics": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    health_log = tmp_path / "ingest_health_log.json"
    monkeypatch.setattr(
        "value_investor.ingest_loop.snapshot_ingest_health",
        lambda **kwargs: {
            "zero_body_buy_tier": 0,
            "indexed_without_body": 100,
            "filings_with_body": 500,
        },
    )
    monkeypatch.setattr(
        "value_investor.ingest_loop.run_ingest_improvement_pass",
        lambda **kwargs: IngestImprovementSummary(targets=[]),
    )
    monkeypatch.setattr("value_investor.ingest_loop.ingest_health_stalled", lambda *a, **k: False)

    run_weekday_ingest_loop(
        latest_path=latest,
        data_dir=tmp_path,
        health_log_path=health_log,
        tasks_path=tmp_path / "engineering_tasks.json",
    )
    entry = json.loads(health_log.read_text(encoding="utf-8"))["entries"][-1]
    assert entry["delta_indexed_without_body"] == 0
    assert entry["delta_filings_with_body"] == 0
