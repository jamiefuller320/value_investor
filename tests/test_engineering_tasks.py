"""Tests for supervised engineering task compilation."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.agent_model_policy import save_policy
from value_investor.data_library import (
    MARKET_REGISTRY,
    empty_manifest,
    market_dir,
    save_manifest,
)
from value_investor.engineering_tasks import (
    compile_engineering_tasks,
    draft_library_ladder_engineering_tasks,
    load_engineering_tasks,
    needs_engineering_implementation,
    select_engineering_tasks,
)
from value_investor.storage import write_json


def test_needs_engineering_implementation_filters_ingest_retry_only():
    assert (
        needs_engineering_implementation(
            area="ingest",
            suggestion="Fetch Hikma IR results presentation PDF from hikma.com",
            source_ids=["company_ir_presentation"],
        )
        is False
    )
    assert (
        needs_engineering_implementation(
            area="ingest",
            suggestion="Replace Google News wrapper URLs with Investegate direct HTML fetch",
        )
        is True
    )
    assert (
        needs_engineering_implementation(
            area="scoring",
            suggestion="Export failed_models into screening_snapshot.json",
        )
        is True
    )


def test_draft_library_ladder_engineering_tasks(tmp_path: Path):
    root = tmp_path / "lib"
    policy = tmp_path / "policy.json"
    tasks_path = tmp_path / "engineering_tasks.json"
    market = "omxs30"
    manifest = empty_manifest(MARKET_REGISTRY[market])
    manifest["tickers"] = ["ABB.ST", "VOLV-B.ST"]
    manifest["ticker_count"] = 2
    manifest["coverage_count"] = 2
    save_manifest(root, market, manifest)

    metrics_dir = market_dir(root, market) / "metrics"
    metrics_dir.mkdir(parents=True)
    write_json(
        metrics_dir / "latest.json",
        [
            {"ticker": "ABB.ST", "errors": "yahoo 401", "trailing_pe": None},
            {"ticker": "VOLV-B.ST", "errors": "stooq fail", "trailing_pe": None},
        ],
        compact=False,
    )
    save_policy(
        {
            "focus_market": market,
            "ladder": {"min_metrics_for_screen": 25},
        },
        policy,
    )

    ladder_result = {
        "focus_market": market,
        "run_at": "2026-08-10T00:00:00+00:00",
        "layers": {
            "fundamentals": {"status": [{"coverage_count": 2}]},
            "screen_lite": {
                "skipped": True,
                "reason": "need>=25 usable metrics rows, have 0",
                "usable_metrics_rows": 0,
            },
        },
    }

    drafted = draft_library_ladder_engineering_tasks(
        ladder_result,
        root=root,
        policy_path=policy,
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    assert drafted["drafted_count"] == 1
    payload = load_engineering_tasks(tasks_path)
    task = next(row for row in payload["tasks"] if row["id"] in drafted["task_ids"])
    assert task["source"] == "library_ladder"
    assert task["area"] == "coverage"
    assert any("providers.py" in path for path in task["allowed_paths"])

    redraft = draft_library_ladder_engineering_tasks(
        ladder_result,
        root=root,
        policy_path=policy,
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    assert redraft["drafted_count"] == 0


def test_compile_engineering_tasks_from_post_run_review(tmp_path: Path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "post_run_review.md").write_text(
        """PRIORITISED IMPROVEMENT PLAN
1. **[ingest] Build universal Companies House filed-accounts PDF fetch + text extract for UK-listed buy-tier names when `filings_with_body` is zero — expected impact: unlocks pension evidence for BT-A.L.**

2. **[scoring] Export `failed_models` and Piotroski component scores into `screening_snapshot.json` — expected impact: gap-fill can reconcile contradictions.**

DEFER
- ignore me
""",
        encoding="utf-8",
    )
    suggestions_path = tmp_path / "suggestions.json"
    suggestions_path.write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "ticker": "HIK.L",
                        "area": "ingest",
                        "priority": "high",
                        "suggestion": "Fetch Hikma IR results presentation PDF from hikma.com",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    tasks_path = output_dir / "engineering_tasks.json"
    committed_path = tmp_path / "committed" / "engineering_tasks.json"
    payload = compile_engineering_tasks(
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        max_tasks=5,
        tasks_path=tasks_path,
        committed_path=committed_path,
    )
    assert payload["task_count"] >= 2
    areas = {row["area"] for row in payload["tasks"]}
    assert "ingest" in areas
    assert "scoring" in areas
    selected = select_engineering_tasks(payload, max_tasks=1)
    assert len(selected) == 1
    assert selected[0].allowed_paths
    assert "paper_fund.py" in "".join(selected[0].blocked_paths)


def test_compile_preserves_merged_task_status(tmp_path: Path):
    committed = tmp_path / "committed.json"
    committed.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-20260726-01",
                        "area": "ingest",
                        "title": "Build universal Companies House filed-accounts PDF fetch + text extract for UK-listed buy-tier names when `filings_with_body` is zero",
                        "summary": "x",
                        "priority": "high",
                        "priority_score": 99.0,
                        "source": "post_run_review",
                        "status": "merged",
                        "evidence": {},
                        "acceptance_criteria": [],
                        "allowed_paths": [],
                        "blocked_paths": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "post_run_review.md").write_text(
        """PRIORITISED IMPROVEMENT PLAN
1. **[ingest] Build universal Companies House filed-accounts PDF fetch + text extract for UK-listed buy-tier names when `filings_with_body` is zero — expected impact: unlocks pension evidence.**
""",
        encoding="utf-8",
    )
    payload = compile_engineering_tasks(
        output_dir=output_dir,
        suggestions_path=tmp_path / "missing.json",
        max_tasks=5,
        tasks_path=output_dir / "engineering_tasks.json",
        committed_path=committed,
    )
    assert payload["tasks"][0]["status"] == "merged"
