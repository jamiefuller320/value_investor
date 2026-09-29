"""Escalation when unmeasured/zero-body stalls with empty IR allowlist."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.ingest_gap_closure import (
    _gap_closure_eng_compile_sort_key,
    compile_pending_gap_closure_engineering,
    stuck_coverage_tickers_missing_ir,
)
from value_investor.market_warning_triage import propose_triage
from value_investor.ops_monitor import check_missing_ir_allowlist_stall
from value_investor.storage import write_json


def _zero_yield_run(
    *,
    run_id: str,
    ticker: str,
    market_id: str,
    completed_at: str,
    reason: str = "unmeasured",
) -> dict:
    return {
        "id": run_id,
        "status": "pending_review",
        "ticker": ticker,
        "completed_at": completed_at,
        "recorded_at": completed_at,
        "review_trigger": "horizon_scan",
        "params": {
            "require_outstanding_gaps": True,
            "intensive_gap_closure": True,
            "market_id": market_id,
            "universe": "library",
            "critical_path_blocker": reason,
        },
        "outcome": {
            "delta_filings_with_body": 0,
            "results": [
                {
                    "ticker": ticker,
                    "reason": reason,
                    "improved": False,
                    "ir_refetch": {
                        "attempted": 0,
                        "fetched": 0,
                        "merge": {"total_allowlist": 0, "note": "no allowlist urls for ticker"},
                    },
                }
            ],
            "per_ticker": [{"ticker": ticker, "improved": False}],
        },
    }


def test_gap_closure_eng_compile_prefers_unmeasured_empty_allowlist():
    stale_iwb = _zero_yield_run(
        run_id="igc-old",
        ticker="ZZZ.PA",
        market_id="euro_depth",
        completed_at="2026-09-01T10:00:00+00:00",
        reason="indexed_without_body",
    )
    stale_iwb["params"]["critical_path_blocker"] = "indexed_without_body"
    fresh_unmeasured = _zero_yield_run(
        run_id="igc-new",
        ticker="AAA.IR",
        market_id="euro_depth",
        completed_at="2026-09-29T10:00:00+00:00",
        reason="unmeasured",
    )
    ordered = sorted([stale_iwb, fresh_unmeasured], key=_gap_closure_eng_compile_sort_key)
    assert ordered[0]["id"] == "igc-new"


def test_stuck_coverage_tickers_missing_ir_after_n_zero_yields(tmp_path: Path, monkeypatch):
    runs_path = tmp_path / "ingest_gap_closure_runs.json"
    write_json(
        runs_path,
        {
            "runs": [
                _zero_yield_run(
                    run_id="igc-1",
                    ticker="MISS.IR",
                    market_id="euro_depth",
                    completed_at="2026-09-28T10:00:00+00:00",
                ),
                _zero_yield_run(
                    run_id="igc-2",
                    ticker="MISS.IR",
                    market_id="euro_depth",
                    completed_at="2026-09-29T10:00:00+00:00",
                ),
            ]
        },
    )
    monkeypatch.setattr(
        "value_investor.ingest_gap_closure.ticker_ir_allowlist_count",
        lambda ticker: 0,
    )
    status = {
        "focus_market": "euro_depth",
        "markets": [
            {
                "market_id": "euro_depth",
                "is_focus": True,
                "filing_health": {"unmeasured_tickers": ["MISS.IR"], "zero_body_tickers": []},
                "sprint_progress": {
                    "admission_warnings": [
                        {
                            "id": "unmeasured_stuck",
                            "severity": "high",
                            "summary": "1 unmeasured",
                        }
                    ]
                },
            }
        ],
    }
    rows = stuck_coverage_tickers_missing_ir(
        market_status=status,
        runs_path=runs_path,
        min_zero_yield=2,
    )
    assert len(rows) == 1
    assert rows[0]["ticker"] == "MISS.IR"
    assert rows[0]["zero_yield_intensives"] >= 2


def test_check_missing_ir_allowlist_stall_emits_finding(tmp_path: Path, monkeypatch):
    runs_path = tmp_path / "ingest_gap_closure_runs.json"
    write_json(
        runs_path,
        {
            "runs": [
                _zero_yield_run(
                    run_id="igc-1",
                    ticker="MISS.IR",
                    market_id="euro_depth",
                    completed_at="2026-09-28T10:00:00+00:00",
                ),
                _zero_yield_run(
                    run_id="igc-2",
                    ticker="MISS.IR",
                    market_id="euro_depth",
                    completed_at="2026-09-29T10:00:00+00:00",
                ),
            ]
        },
    )
    status_path = tmp_path / "market_status.json"
    write_json(
        status_path,
        {
            "focus_market": "euro_depth",
            "markets": [
                {
                    "market_id": "euro_depth",
                    "is_focus": True,
                    "filing_health": {
                        "unmeasured_tickers": ["MISS.IR"],
                        "zero_body_tickers": [],
                    },
                    "sprint_progress": {
                        "admission_warnings": [
                            {
                                "id": "unmeasured_stuck",
                                "severity": "high",
                                "summary": "1 unmeasured",
                            }
                        ]
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        "value_investor.ingest_gap_closure.ticker_ir_allowlist_count",
        lambda ticker: 0,
    )
    findings = check_missing_ir_allowlist_stall(
        market_status_path=status_path,
        runs_path=runs_path,
        min_zero_yield=2,
    )
    assert len(findings) == 1
    assert findings[0].auto_fixable is False
    assert findings[0].severity == "high"
    assert "MISS.IR" in findings[0].summary
    assert "IR allowlist" in findings[0].title


def test_propose_triage_names_empty_ir_allowlist(monkeypatch):
    monkeypatch.setattr(
        "value_investor.ingest_gap_closure.ticker_ir_allowlist_count",
        lambda ticker: 0,
    )
    proposal = propose_triage(
        {
            "flag_id": "unmeasured_stuck",
            "kind": "admission_warning",
            "market_id": "euro_depth",
            "is_focus": True,
            "is_spare": False,
            "tickers": "GHOST.IR",
        }
    )
    assert proposal["action"] == "deepen"
    assert proposal["dismissable"] is False
    assert proposal["parkable"] is False
    assert proposal.get("missing_ir_allowlist") is True
    assert "IR allowlist is empty" in proposal["rationale"]
    assert "Do not auto-park" in proposal["rationale"]


def test_compile_pending_prefers_fresh_unmeasured_over_stale(
    tmp_path: Path, monkeypatch
):
    data_dir = tmp_path / "docs" / "data"
    data_dir.mkdir(parents=True)
    runs_path = data_dir / "ingest_gap_closure_runs.json"
    tasks_path = data_dir / "engineering_tasks.json"
    write_json(tasks_path, {"tasks": []})
    write_json(
        runs_path,
        {
            "runs": [
                _zero_yield_run(
                    run_id="igc-stale",
                    ticker="ZZZ.PA",
                    market_id="euro_depth",
                    completed_at="2026-09-01T10:00:00+00:00",
                    reason="indexed_without_body",
                ),
                _zero_yield_run(
                    run_id="igc-fresh",
                    ticker="AAA.IR",
                    market_id="euro_depth",
                    completed_at="2026-09-29T10:00:00+00:00",
                    reason="unmeasured",
                ),
            ]
        },
    )
    seen: list[str] = []

    def _fake_should(run, **kwargs):
        seen.append(str(run.get("id") or ""))
        return True, "gaps_remain_without_allowlist"

    def _fake_compile(run, **kwargs):
        return {
            "compiled_count": 1,
            "task_ids": [f"eng-test-{run.get('id')}"],
            "task_id": f"eng-test-{run.get('id')}",
        }

    monkeypatch.setattr(
        "value_investor.ingest_gap_closure.should_auto_compile_gap_engineering",
        _fake_should,
    )
    monkeypatch.setattr(
        "value_investor.engineering_tasks.compile_ingest_engineering_task_from_trial",
        _fake_compile,
    )
    monkeypatch.setattr(
        "value_investor.engineering_queue.refresh_engineering_queue_ui",
        lambda **kwargs: None,
    )
    out = compile_pending_gap_closure_engineering(
        market_id="euro_depth",
        limit=1,
        tasks_path=tasks_path,
        runs_path=runs_path,
        data_dir=data_dir,
    )
    assert seen[0] == "igc-fresh"
    assert out["compiled_count"] == 1
    assert out["compiled"][0]["run_id"] == "igc-fresh"
    assert out["compiled"][0]["task_id"] == "eng-test-igc-fresh"
    assert out["compiled"][0]["compile_reason"] == "gaps_remain_without_allowlist"
