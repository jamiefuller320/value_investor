"""Tests for ingest trial → engineering → rerun chain."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_queue import ingest_trial_rerun_dispatch
from value_investor.engineering_tasks import compile_ingest_engineering_task_from_trial
from value_investor.ingest_trials import (
    MAX_TRIAL_GAP_CHAIN_ROUNDS,
    finalize_pending_ingest_trial,
    record_ingest_trial,
    should_auto_compile_gap_engineering,
    trial_needs_gap_engineering,
    trial_refetch_stats,
)
from value_investor.research.ingest_improvement import select_ingest_improvement_targets
from value_investor.summary import CompanyReport


def _report(ticker: str, name: str, signal: str = "strong_buy") -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=name,
        sector="Industrials",
        signal=signal,
        models_passed=5,
        model_count=10,
        composite_score=0.7,
        sector_composite_score=0.8,
        families_passed=4,
        passed_families="cheapness,quality",
        data_quality_score=0.9,
        metrics_present=18,
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
        summary="test",
        passed_models=[],
        key_metrics={},
    )


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
        health_before={
            "filings_with_body": 100,
            "indexed_without_body": 14,
            "zero_body_buy_tier": 0,
        },
        health_after={
            "filings_with_body": 100,
            "indexed_without_body": 14,
            "zero_body_buy_tier": 0,
        },
        ingest_summary=None,
        path=path,
    )
    trial["outcome"] = {
        "delta_filings_with_body": 0,
        "per_ticker": [
            {"ticker": "VCT.L", "improved": False, "with_body_before": 67, "with_body_after": 67}
        ],
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


def _vct_gap_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "docs" / "data"
    filings = data_dir / "research" / "VCT.L" / "sources" / "filings"
    filings.mkdir(parents=True)
    (filings / "filings_index.json").write_text(
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
    return data_dir


def test_compile_ingest_engineering_task_from_trial(tmp_path: Path):
    trial = _failed_gap_trial(tmp_path)
    eng_path = tmp_path / "engineering_tasks.json"
    eng_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    result = compile_ingest_engineering_task_from_trial(
        trial,
        tasks_path=eng_path,
        committed_path=eng_path,
        data_dir=_vct_gap_data_dir(tmp_path),
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


def test_should_auto_compile_after_verification_gaps_remain(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    filings = data_dir / "research" / "VCT.L" / "sources" / "filings"
    filings.mkdir(parents=True)
    (filings / "filings_index.json").write_text(
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
    trials_path = data_dir / "ingest_trials.json"
    trials_path.write_text(
        json.dumps(
            {
                "trials": [
                    {
                        "id": "trial-root",
                        "chain_root_id": "trial-root",
                        "status": "pending_review",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    eng_path = data_dir / "engineering_tasks.json"
    eng_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    verification = {
        "id": "trial-verify",
        "status": "pending_review",
        "ticker": "VCT.L",
        "parent_trial_id": "trial-root",
        "chain_root_id": "trial-root",
        "params": {"require_outstanding_gaps": True},
        "outcome": {
            "delta_filings_with_body": 0,
            "per_ticker": [{"ticker": "VCT.L", "improved": False}],
            "results": [{"ch_refetch": {"attempted": 1, "fetched": 0}}],
        },
    }
    should, reason = should_auto_compile_gap_engineering(
        verification,
        data_dir=data_dir,
        tasks_path=eng_path,
        trials_path=trials_path,
    )
    assert should is True
    assert reason in {"verification_gaps_remain", "zero_yield_refetch"}


def test_should_auto_compile_when_partial_improvement_leaves_gaps(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    filings = data_dir / "research" / "JD.L" / "sources" / "filings"
    filings.mkdir(parents=True)
    (filings / "filings_index.json").write_text(
        json.dumps(
            {
                "summary": {"total": 3, "with_body": 2},
                "filings": [
                    {"period": "annual", "has_body": True},
                    {"period": "interim", "has_body": True},
                    {"period": "other", "has_body": False, "url": "https://example.com/a"},
                ],
            }
        ),
        encoding="utf-8",
    )
    trials_path = data_dir / "ingest_trials.json"
    trials_path.write_text(json.dumps({"trials": []}), encoding="utf-8")
    eng_path = data_dir / "engineering_tasks.json"
    eng_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    trial = {
        "id": "trial-partial",
        "status": "pending_review",
        "ticker": "JD.L",
        "chain_root_id": "trial-partial",
        "params": {"require_outstanding_gaps": True},
        "outcome": {
            "delta_filings_with_body": 2,
            "per_ticker": [{"ticker": "JD.L", "improved": False}],
            "results": [
                {
                    "residual_refetch": {"attempted": 1, "fetched": 0},
                }
            ],
        },
    }
    should, reason = should_auto_compile_gap_engineering(
        trial,
        data_dir=data_dir,
        tasks_path=eng_path,
        trials_path=trials_path,
    )
    assert should is True
    assert reason == "zero_yield_refetch"


def test_chain_exhausted_after_max_engineering_rounds(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    filings = data_dir / "research" / "VCT.L" / "sources" / "filings"
    filings.mkdir(parents=True)
    (filings / "filings_index.json").write_text(
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
    trials_path = data_dir / "ingest_trials.json"
    trials_path.write_text(
        json.dumps({"trials": [{"id": "trial-root", "chain_root_id": "trial-root"}]}),
        encoding="utf-8",
    )
    eng_path = data_dir / "engineering_tasks.json"
    eng_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": f"eng-{idx}",
                        "source": "ingest_trial",
                        "status": "merged",
                        "evidence": {"chain_root_id": "trial-root"},
                    }
                    for idx in range(MAX_TRIAL_GAP_CHAIN_ROUNDS)
                ]
            }
        ),
        encoding="utf-8",
    )
    trial = {
        "id": "trial-verify",
        "status": "pending_review",
        "ticker": "VCT.L",
        "parent_trial_id": "trial-root",
        "chain_root_id": "trial-root",
        "params": {"require_outstanding_gaps": True},
        "outcome": {
            "per_ticker": [{"improved": False}],
            "results": [{"ch_refetch": {"attempted": 1, "fetched": 0}}],
        },
    }
    should, reason = should_auto_compile_gap_engineering(
        trial,
        data_dir=data_dir,
        tasks_path=eng_path,
        trials_path=trials_path,
    )
    assert should is False
    assert reason == "chain_exhausted"
    store = json.loads(trials_path.read_text(encoding="utf-8"))
    rows = store.get("runs") or store.get("trials") or []
    assert rows[0]["chain_status"] == "exhausted"
