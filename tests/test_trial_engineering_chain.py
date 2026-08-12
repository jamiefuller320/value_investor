"""Tests for ingest trial → engineering → rerun chain."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_queue import ingest_trial_rerun_dispatch
from value_investor.engineering_tasks import compile_ingest_engineering_task_from_trial
from value_investor.ingest_trials import (
    finalize_pending_ingest_trial,
    record_ingest_trial,
    trial_needs_gap_engineering,
    trial_refetch_stats,
)
from value_investor.research.ingest_improvement import select_ingest_improvement_targets
from tests.test_ingest_improvement import _report


def _failed_gap_trial(tmp_path: Path) -> dict:
    path = tmp_path / "ingest_trials.json"
    trial = record_ingest_trial(
        title="Gap trial",
        summary="",
        ticker="VCT.L",
        params={"require_outstanding_gaps": True},
        path=path,
    )
    finalize_pending_ingest_trial(
        health_before={"filings_with_body": 100, "indexed_without_body": 14, "zero_body_buy_tier": 0},
        health_after={"filings_with_body": 100, "indexed_without_body": 14, "zero_body_buy_tier": 0},
        ingest_summary=None,
        path=path,
    )
    trial["outcome"] = {
        "delta_filings_with_body": 0,
        "per_ticker": [{"ticker": "VCT.L", "improved": False, "with_body_before": 67, "with_body_after": 67}],
        "results": [
            {
                "ch_refetch": {"attempted": 1, "fetched": 0},
                "investegate_refetch": {"attempted": 2, "fetched": 0},
            }
        ],
    }
    path.write_text(json.dumps({"trials": [trial]}), encoding="utf-8")
    return trial


def test_trial_needs_gap_engineering_detects_zero_yield_refetch(tmp_path: Path):
    trial = _failed_gap_trial(tmp_path)
    assert trial_needs_gap_engineering(trial)
    stats = trial_refetch_stats(trial)
    assert stats["attempted"] == 3
    assert stats["fetched"] == 0


def test_compile_ingest_engineering_task_from_trial(tmp_path: Path):
    trial = _failed_gap_trial(tmp_path)
    eng_path = tmp_path / "engineering_tasks.json"
    eng_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    result = compile_ingest_engineering_task_from_trial(
        trial,
        tasks_path=eng_path,
        committed_path=eng_path,
    )
    assert result["compiled_count"] == 1
    payload = json.loads(eng_path.read_text(encoding="utf-8"))
    task = payload["tasks"][0]
    assert task["area"] == "ingest"
    assert task["evidence"]["rerun_ingest_trial"] is True
    assert task["evidence"]["trial_id"] == trial["id"]
    assert task["evidence"]["ticker"] == "VCT.L"


def test_ingest_trial_rerun_dispatch_after_merge(tmp_path: Path):
    eng_path = tmp_path / "engineering_tasks.json"
    eng_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-20260812-01",
                        "area": "ingest",
                        "status": "merged",
                        "evidence": {
                            "trial_id": "trial-20260812-02",
                            "ticker": "VCT.L",
                            "rerun_ingest_trial": True,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    dispatch = ingest_trial_rerun_dispatch("eng-20260812-01", tasks_path=eng_path)
    assert dispatch["should_dispatch"] is True
    assert dispatch["pin_ticker"] == "VCT.L"
    assert dispatch["trial_parent_id"] == "trial-20260812-02"


def test_select_targets_pin_ticker(tmp_path: Path):
    output_dir = tmp_path / "output"
    for ticker in ("MEGP.L", "VCT.L"):
        sources = output_dir / "research" / ticker / "sources" / "filings"
        sources.mkdir(parents=True)
        (sources / "filings_index.json").write_text(
            json.dumps(
                {
                    "summary": {"total": 2, "annual": 1, "interim": 1, "with_body": 1},
                    "filings": [
                        {"period": "annual", "has_body": True},
                        {"period": "interim", "has_body": False},
                    ],
                }
            ),
            encoding="utf-8",
        )
    targets = select_ingest_improvement_targets(
        [_report("MEGP.L", "ME Group"), _report("VCT.L", "Victrex", signal="buy")],
        output_dir=output_dir,
        suggestions_path=tmp_path / "missing.json",
        max_targets=1,
        pin_tickers=["VCT.L"],
        require_outstanding_gaps=True,
    )
    assert len(targets) == 1
    assert targets[0].ticker == "VCT.L"
