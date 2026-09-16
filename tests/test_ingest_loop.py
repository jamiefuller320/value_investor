"""Tests for weekday ingest-assess loop."""

from __future__ import annotations

import json
import re
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
from value_investor.research.ingest_improvement import (
    IngestImprovementSummary,
    _invoke_with_transient_fetch_retry,
    _is_transient_http_fetch_error,
    run_ingest_improvement_pass,
)
from value_investor.summary import CompanyReport


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


def test_is_transient_http_fetch_error_matches_curl_cffi_http_error():
    class HTTPError(Exception):
        pass

    exc = HTTPError("Failed to perform, curl: (56) Recv failure")
    assert _is_transient_http_fetch_error(exc)


def test_invoke_with_transient_fetch_retry_recovers_on_second_attempt():
    calls = {"count": 0}

    def flaky_fetch():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("HTTPError: Failed to perform")
        return {"fetched": 2}

    with patch(
        "value_investor.research.ingest_improvement.time.sleep",
        return_value=None,
    ):
        result = _invoke_with_transient_fetch_retry(flaky_fetch)
    assert result == {"fetched": 2}
    assert calls["count"] == 2


@patch("value_investor.research.ingest_improvement.deepen_thin_filings_if_needed")
@patch("value_investor.research.ingest_improvement.execute_planned_alternate_sources")
@patch("value_investor.research.ingest_improvement.ingest_research_sources")
@patch("value_investor.research.ingest_improvement.sanitize_filings_index")
@patch("value_investor.research.ingest_improvement.refetch_uk_primary_filing_bodies")
@patch("value_investor.research.ingest_improvement.bootstrap_buy_tier_research")
def test_run_ingest_improvement_pass_continues_after_bootstrap_http_error(
    mock_bootstrap,
    mock_primary_refetch,
    mock_sanitize,
    mock_ingest_sources,
    mock_alternate,
    mock_deepen,
    tmp_path: Path,
):
    """Regression for ingest-loop.yml CurlError/HTTPError during bootstrap seed."""
    mock_bootstrap.side_effect = RuntimeError(
        "curl_cffi.requests.exceptions.HTTPError: Failed to perform"
    )
    output_dir = tmp_path / "output"
    sources = output_dir / "research" / "BT-A.L" / "sources" / "filings"
    sources.mkdir(parents=True)
    (sources / "filings_index.json").write_text(
        json.dumps({"summary": {"total": 2, "with_body": 0}, "filings": [{}, {}]}),
        encoding="utf-8",
    )
    mock_ingest_sources.return_value = {"filings_summary": {"with_body": 0}}
    mock_primary_refetch.return_value = {
        "fetched": 1,
        "companies_house": {"fetched": 1},
        "rns": {"investegate": {}, "ticker_rns": {}, "fetched": 0},
    }
    mock_alternate.return_value = {"fetched": 0}
    mock_deepen.return_value = {"skipped": True, "reason": "sufficient_bodies"}

    report = CompanyReport(
        ticker="BT-A.L",
        name="BT Group",
        sector="Communication Services",
        signal="buy",
        models_passed=10,
        model_count=22,
        composite_score=0.8,
        sector_composite_score=0.7,
        families_passed=4,
        passed_families="cheapness",
        data_quality_score=1.0,
        metrics_present=20,
        metrics_total=20,
        weeks_at_signal=1,
        signal_trend="new",
        conviction_score=0.5,
        stability_label="new",
        timing_signal="neutral",
        timing_score=0.0,
        rsi_14=50.0,
        price_vs_sma200_pct=0.0,
        action_note="",
        trade_plan=None,
        summary="Test",
        passed_models=[],
        key_metrics={},
    )

    summary = run_ingest_improvement_pass(
        reports=[report],
        output_dir=output_dir,
        market="ftse350",
        max_targets=1,
        suggestions_path=tmp_path / "missing.json",
        discovery_scan=False,
    )

    assert any("bootstrap:" in row for row in summary.errors)
    assert len(summary.results) == 1
    mock_primary_refetch.assert_called_once()


def test_ingest_loop_workflow_step_timeout_has_headroom_above_soft_budget() -> None:
    """Regression for ingest-loop.yml run #35066797050 (65m step vs 3600s soft budget)."""
    text = Path(".github/workflows/ingest-loop.yml").read_text(encoding="utf-8")
    default_m = re.search(
        r"max_runtime_seconds:.*?default:\s*\"(\d+)\"",
        text,
        flags=re.DOTALL,
    )
    assert default_m is not None
    soft_budget_s = int(default_m.group(1))
    step_m = re.search(
        r"name: Run weekday ingest loop\n(?:.*\n)*?\s+timeout-minutes:\s*(\d+)",
        text,
    )
    assert step_m is not None
    step_timeout_m = int(step_m.group(1))
    assert step_timeout_m >= (soft_budget_s // 60) + 15


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
