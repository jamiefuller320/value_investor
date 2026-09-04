"""Tests for library ingest stall/slowdown gap-closure follow-up."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from value_investor.data_library_cli import main as library_main
from value_investor.ingest_gap_closure import (
    evaluate_library_ingest_gap_closure_followup,
    evaluate_library_ingest_gap_closure_followups,
    has_recent_intensive_gap_closure_run,
    library_ingest_followup_dispatch_rows,
    library_ingest_followup_loop_payloads,
    select_library_gap_closure_candidate,
)
from value_investor.storage import write_json
from value_investor.summary import CompanyReport


def _report(ticker: str, signal: str = "buy", conviction: float = 0.5) -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=f"{ticker} Co",
        sector="X",
        signal=signal,
        models_passed=5,
        model_count=10,
        composite_score=0.6,
        sector_composite_score=0.55,
        families_passed=3,
        passed_families="cheapness",
        data_quality_score=0.8,
        metrics_present=10,
        metrics_total=12,
        weeks_at_signal=1,
        signal_trend="stable",
        conviction_score=conviction,
        stability_label="stable",
        timing_signal="hold",
        timing_score=0.0,
        rsi_14=None,
        price_vs_sma200_pct=None,
        action_note="",
        trade_plan=None,
        summary="",
        passed_models=[],
        key_metrics={},
    )


def _write_index(root: Path, market: str, ticker: str, *, total: int, with_body: int) -> None:
    filings_dir = root / "markets" / market / "screen" / "research" / ticker / "sources" / "filings"
    filings_dir.mkdir(parents=True)
    write_json(
        filings_dir / "filings_index.json",
        {"summary": {"total": total, "with_body": with_body}, "filings": []},
        compact=False,
    )


def _euro_fixture(tmp_path: Path) -> tuple[Path, list[CompanyReport]]:
    root = tmp_path / "library"
    market = "euro_depth"
    _write_index(root, market, "RAND.AS", total=3, with_body=0)
    _write_index(root, market, "ABI.BR", total=5, with_body=2)
    reports = [_report("RAND.AS"), _report("ABI.BR", conviction=0.9)]
    return root, reports


def _health(*, iwb: int = 3, zero_body: int = 1, unmeasured: int = 0) -> dict:
    return {
        "indexed_without_body": iwb,
        "zero_body_buy_tier": zero_body,
        "unmeasured_buy_tier": unmeasured,
        "zero_body_tickers": ["RAND.AS"] if zero_body else [],
        "unmeasured_tickers": [],
    }


def test_select_library_candidate_prefers_zero_body(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    result = select_library_gap_closure_candidate(
        market_id="euro_depth",
        library_root=root,
        reports=reports,
    )
    assert result["should_dispatch"] is True
    assert result["pin_ticker"] == "RAND.AS"


def test_slowdown_dispatches_intensive_for_sticky_name(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    result = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(),
        was_gap_closure_run=False,
        stalled=False,
        improved=[],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=tmp_path / "ingest_gap_closure_runs.json",
    )
    assert result["should_dispatch"] is True
    assert result["trigger"] == "stall_slowdown"
    assert result["pin_ticker"] == "RAND.AS"
    assert "slowdown" in result["title"].lower()


def test_stall_dispatches_when_no_open_library_task(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    result = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(),
        was_gap_closure_run=False,
        stalled=True,
        improved=["ABI.BR"],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=tmp_path / "ingest_gap_closure_runs.json",
    )
    assert result["should_dispatch"] is True
    assert result["trigger"] == "stall_slowdown"
    assert "stall" in result["title"].lower()


def test_skips_partial_or_runtime_cutoff_when_deepen_never_started(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    for kwargs in ({"partial": True}, {"runtime_cutoff": True}):
        result = evaluate_library_ingest_gap_closure_followup(
            market_id="euro_depth",
            health_after=_health(),
            was_gap_closure_run=False,
            improved=[],
            library_root=root,
            reports=reports,
            tasks_path=tmp_path / "engineering_tasks.json",
            runs_path=tmp_path / "ingest_gap_closure_runs.json",
            **kwargs,
        )
        assert result["should_dispatch"] is False
        assert "deepen never started" in result["reason"]


def test_skips_cutoff_when_discovery_did_not_finish(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    result = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(),
        was_gap_closure_run=False,
        improved=[],
        partial=True,
        runtime_cutoff=True,
        discovery_scan={"runtime_cutoff": True, "scanned": 12},
        deepen_results=[],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=tmp_path / "ingest_gap_closure_runs.json",
    )
    assert result["should_dispatch"] is False
    assert "discovery did not finish" in result["reason"]


def test_cutoff_dispatches_when_discovery_finished_and_deepen_ran(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    result = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(),
        was_gap_closure_run=False,
        stalled=False,
        improved=[],
        partial=True,
        runtime_cutoff=True,
        discovery_scan={"runtime_cutoff": False, "scanned": 44, "budget_seconds": 675},
        deepen_results=[
            {"ticker": "BOL.ST", "improved": False},
            {"ticker": "DG.PA", "improved": False},
        ],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=tmp_path / "ingest_gap_closure_runs.json",
    )
    assert result["should_dispatch"] is True
    assert result["trigger"] == "stall_slowdown"
    assert result["pin_ticker"] == "RAND.AS"
    assert "runtime cutoff" in result["summary"]


def test_cutoff_skips_when_deepen_already_improved(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    result = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(zero_body=0),
        was_gap_closure_run=False,
        stalled=False,
        improved=["DG.PA"],
        partial=True,
        runtime_cutoff=True,
        discovery_scan={"runtime_cutoff": False, "scanned": 44},
        deepen_results=[{"ticker": "DG.PA", "improved": True}],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=tmp_path / "ingest_gap_closure_runs.json",
    )
    assert result["should_dispatch"] is False
    assert "improved coverage" in result["reason"]


def test_skips_productive_run_with_leftover_iwb(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    result = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(zero_body=0),
        was_gap_closure_run=False,
        stalled=False,
        improved=["DG.PA"],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=tmp_path / "ingest_gap_closure_runs.json",
    )
    assert result["should_dispatch"] is False
    assert "improved coverage" in result["reason"]


def test_skips_when_already_gap_closure_or_no_gaps(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    already = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(),
        was_gap_closure_run=True,
        improved=[],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=tmp_path / "ingest_gap_closure_runs.json",
    )
    assert already["should_dispatch"] is False
    assert "already gap closure" in already["reason"]

    clear = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(iwb=0, zero_body=0, unmeasured=0),
        was_gap_closure_run=False,
        improved=[],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=tmp_path / "ingest_gap_closure_runs.json",
    )
    assert clear["should_dispatch"] is False
    assert "no outstanding" in clear["reason"]


def test_recent_intensive_is_scoped_by_market(tmp_path: Path):
    runs_path = tmp_path / "ingest_gap_closure_runs.json"
    now = datetime.now(UTC)
    write_json(
        runs_path,
        {
            "runs": [
                {
                    "id": "igc-ftse",
                    "recorded_at": now.isoformat(),
                    "params": {"intensive_gap_closure": True},
                },
                {
                    "id": "igc-sp500",
                    "recorded_at": now.isoformat(),
                    "params": {
                        "intensive_gap_closure": True,
                        "market_id": "sp500",
                        "universe": "library",
                    },
                },
            ]
        },
        compact=False,
    )
    assert has_recent_intensive_gap_closure_run(runs_path=runs_path) is True
    assert (
        has_recent_intensive_gap_closure_run(runs_path=runs_path, market_id="euro_depth") is False
    )
    assert has_recent_intensive_gap_closure_run(runs_path=runs_path, market_id="sp500") is True

    root, reports = _euro_fixture(tmp_path)
    result = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(),
        was_gap_closure_run=False,
        improved=[],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=runs_path,
    )
    assert result["should_dispatch"] is True


def test_skips_recent_same_market_intensive_and_open_task(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    runs_path = tmp_path / "ingest_gap_closure_runs.json"
    write_json(
        runs_path,
        {
            "runs": [
                {
                    "id": "igc-euro",
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "params": {
                        "intensive_gap_closure": True,
                        "market_id": "euro_depth",
                        "universe": "library",
                    },
                }
            ]
        },
        compact=False,
    )
    recent = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(),
        was_gap_closure_run=False,
        improved=[],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=runs_path,
    )
    assert recent["should_dispatch"] is False
    assert "within 6h" in recent["reason"]

    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(
        tasks_path,
        {
            "tasks": [
                {
                    "id": "eng-20260903-01",
                    "area": "ingest",
                    "status": "open",
                    "source": "library_ingest_stall",
                    "evidence": {"market_id": "euro_depth"},
                }
            ]
        },
        compact=False,
    )
    stale_runs = tmp_path / "stale_runs.json"
    write_json(
        stale_runs,
        {
            "runs": [
                {
                    "id": "igc-old",
                    "recorded_at": (datetime.now(UTC) - timedelta(hours=8)).isoformat(),
                    "params": {
                        "intensive_gap_closure": True,
                        "market_id": "euro_depth",
                        "universe": "library",
                    },
                }
            ]
        },
        compact=False,
    )
    blocked = evaluate_library_ingest_gap_closure_followup(
        market_id="euro_depth",
        health_after=_health(),
        was_gap_closure_run=False,
        improved=[],
        library_root=root,
        reports=reports,
        tasks_path=tasks_path,
        runs_path=stale_runs,
    )
    assert blocked["should_dispatch"] is False
    assert "open library ingest" in blocked["reason"]


def test_followup_cli_writes_json_path(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    loop_path = tmp_path / "euro_ingest_loop.json"
    out_path = tmp_path / "gap_followup.json"
    write_json(
        loop_path,
        {
            "market_id": "euro_depth",
            "health_after": _health(),
            "recorded_gap_closure": False,
            "stalled": False,
            "improved": [],
            "partial": False,
            "runtime_cutoff": False,
        },
        compact=False,
    )
    with patch(
        "value_investor.library_ingest_loop.load_library_buy_tier_reports",
        return_value=reports,
    ):
        assert (
            library_main(
                [
                    "ingest-gap-closure-followup",
                    "--market",
                    "euro_depth",
                    "--loop-json",
                    str(loop_path),
                    "--root",
                    str(root),
                    "--tasks-path",
                    str(tmp_path / "engineering_tasks.json"),
                    "--runs-path",
                    str(tmp_path / "ingest_gap_closure_runs.json"),
                    "--json-path",
                    str(out_path),
                ]
            )
            == 0
        )
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["should_dispatch"] is True
    assert payload["pin_ticker"] == "RAND.AS"
    assert payload["trigger"] == "stall_slowdown"


def test_followup_cli_dispatches_after_cutoff_deepen(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    loop_path = tmp_path / "euro_ingest_loop.json"
    out_path = tmp_path / "gap_followup.json"
    write_json(
        loop_path,
        {
            "market_id": "euro_depth",
            "health_after": _health(),
            "recorded_gap_closure": False,
            "stalled": False,
            "improved": [],
            "partial": True,
            "runtime_cutoff": True,
            "discovery_scan": {"runtime_cutoff": False, "scanned": 44},
            "results": [
                {"ticker": "BOL.ST", "improved": False},
                {"ticker": "DG.PA", "improved": False},
            ],
        },
        compact=False,
    )
    with patch(
        "value_investor.library_ingest_loop.load_library_buy_tier_reports",
        return_value=reports,
    ):
        assert (
            library_main(
                [
                    "ingest-gap-closure-followup",
                    "--market",
                    "euro_depth",
                    "--loop-json",
                    str(loop_path),
                    "--root",
                    str(root),
                    "--tasks-path",
                    str(tmp_path / "engineering_tasks.json"),
                    "--runs-path",
                    str(tmp_path / "ingest_gap_closure_runs.json"),
                    "--json-path",
                    str(out_path),
                ]
            )
            == 0
        )
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["should_dispatch"] is True
    assert payload["pin_ticker"] == "RAND.AS"
    assert "runtime cutoff" in payload["summary"]


def test_batch_followup_dispatches_only_stalled_or_slowdown_markets(tmp_path: Path):
    root, reports = _euro_fixture(tmp_path)
    sprint = {
        "markets": ["euro_depth", "sp500"],
        "results": [
            {
                "market_id": "euro_depth",
                "health_after": _health(),
                "recorded_gap_closure": False,
                "stalled": False,
                "improved": [],
                "partial": False,
                "runtime_cutoff": False,
            },
            {
                "market_id": "sp500",
                "health_after": _health(zero_body=0),
                "recorded_gap_closure": False,
                "stalled": False,
                "improved": ["AAPL"],
                "partial": False,
                "runtime_cutoff": False,
            },
        ],
    }
    assert [row["market_id"] for row in library_ingest_followup_loop_payloads(sprint)] == [
        "euro_depth",
        "sp500",
    ]
    with patch(
        "value_investor.library_ingest_loop.load_library_buy_tier_reports",
        return_value=reports,
    ):
        result = evaluate_library_ingest_gap_closure_followups(
            sprint,
            library_root=root,
            tasks_path=tmp_path / "engineering_tasks.json",
            runs_path=tmp_path / "ingest_gap_closure_runs.json",
        )
    assert result["should_dispatch"] is True
    rows = library_ingest_followup_dispatch_rows(result)
    assert [row["market_id"] for row in rows] == ["euro_depth"]
    assert rows[0]["pin_ticker"] == "RAND.AS"
    reasons = {row["market_id"]: row.get("reason") for row in result["evaluations"]}
    assert "improved coverage" in str(reasons["sp500"])


def test_single_loop_payload_is_not_treated_as_sprint_batch():
    payload = {
        "market_id": "euro_depth",
        "health_after": {"indexed_without_body": 1},
        "results": [{"ticker": "DG.PA", "improved": False}],
    }
    loops = library_ingest_followup_loop_payloads(payload)
    assert len(loops) == 1
    assert loops[0]["market_id"] == "euro_depth"
