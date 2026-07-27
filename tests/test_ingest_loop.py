"""Tests for weekday ingest-assess loop."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_tasks import (
    EngineeringTask,
    compile_ingest_engineering_tasks_micro,
    task_title_key,
)
from value_investor.ingest_loop import (
    append_health_log_entry,
    ingest_health_stalled,
    reports_from_latest,
)


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
