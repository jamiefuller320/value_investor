"""Tests for supervised engineering task compilation."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_tasks import (
    compile_engineering_tasks,
    needs_engineering_implementation,
    select_engineering_tasks,
)


def test_needs_engineering_implementation_filters_ingest_retry_only():
    assert needs_engineering_implementation(
        area="ingest",
        suggestion="Fetch Hikma IR results presentation PDF from hikma.com",
        source_ids=["company_ir_presentation"],
    ) is False
    assert needs_engineering_implementation(
        area="ingest",
        suggestion="Replace Google News wrapper URLs with Investegate direct HTML fetch",
    ) is True
    assert needs_engineering_implementation(
        area="scoring",
        suggestion="Export failed_models into screening_snapshot.json",
    ) is True


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
    payload = compile_engineering_tasks(
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        max_tasks=5,
        tasks_path=tasks_path,
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
