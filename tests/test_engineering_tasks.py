"""Tests for supervised engineering task compilation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from value_investor.agent_model_policy import save_policy
from value_investor.data_library import (
    MARKET_REGISTRY,
    empty_manifest,
    market_dir,
    save_manifest,
)
from value_investor.engineering_tasks import (
    AREA_ALLOWED_PATHS,
    compile_engineering_tasks,
    draft_library_ladder_engineering_tasks,
    load_engineering_tasks,
    needs_engineering_implementation,
    select_engineering_tasks,
)
from value_investor.storage import write_json


def test_ingest_allowed_paths_include_companies_house_module_tests():
    paths = AREA_ALLOWED_PATHS["ingest"]
    assert "src/value_investor/companies_house.py" in paths
    assert "tests/test_companies_house.py" in paths


def test_ingest_allowed_paths_include_research_ingest_companion_tests():
    paths = AREA_ALLOWED_PATHS["ingest"]
    assert "src/value_investor/research/ingest.py" in paths
    assert "tests/test_research_ingest.py" in paths


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


def test_suggestions_compile_respects_lookback_and_merged_skip(tmp_path: Path):
    from datetime import UTC, datetime, timedelta

    from value_investor.engineering_tasks import build_compiled_task_candidates

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "post_run_review.md").write_text(
        "PRIORITISED IMPROVEMENT PLAN\n1. [ops] Ignore — expected impact: x\n",
        encoding="utf-8",
    )
    suggestions_path = tmp_path / "suggestions.json"
    now = datetime(2026, 9, 12, tzinfo=UTC)
    old = (now - timedelta(days=30)).isoformat()
    recent = (now - timedelta(days=3)).isoformat()
    suggestions_path.write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "ticker": "OLD.L",
                        "area": "scoring",
                        "priority": "high",
                        "suggestion": "Old suggestion should be dropped by lookback",
                        "recorded_at": old,
                    },
                    {
                        "ticker": "NEW.L",
                        "area": "scoring",
                        "priority": "high",
                        "suggestion": "Fresh suggestion for compile queue",
                        "recorded_at": recent,
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
                    {
                        "id": "eng-old",
                        "title": "Fresh suggestion for compile queue",
                        "status": "merged",
                        "area": "scoring",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    candidates = build_compiled_task_candidates(
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        scope="full",
        tasks_path=tasks_path,
        compile_since=now,
    )
    suggestion_tasks = [t for t in candidates if t.source == "research_model_suggestions"]
    assert suggestion_tasks == []


def test_ensure_post_run_artifact_refreshes_when_plan_changes(tmp_path: Path):
    from value_investor.engineering_tasks import (
        ensure_post_run_review_artifact,
        post_run_plan_titles_from_text,
    )

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "run_at": "2026-09-12T10:00:00+00:00",
                "post_run_review": {"improvement_plan": "1. [scoring] First plan item"},
            }
        ),
        encoding="utf-8",
    )
    md = ensure_post_run_review_artifact(output_dir=output_dir, latest_path=latest)
    assert md is not None
    latest.write_text(
        json.dumps(
            {
                "run_at": "2026-09-12T12:00:00+00:00",
                "post_run_review": {"improvement_plan": "1. [scoring] Updated plan item"},
            }
        ),
        encoding="utf-8",
    )
    ensure_post_run_review_artifact(output_dir=output_dir, latest_path=latest)
    titles = post_run_plan_titles_from_text(md.read_text(encoding="utf-8"))
    assert titles == ["Updated plan item"]


def test_backstop_scope_omits_suggestions(tmp_path: Path):
    from value_investor.engineering_tasks import build_compiled_task_candidates

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "post_run_review.md").write_text(
        "PRIORITISED IMPROVEMENT PLAN\n1. [scoring] Plan only — expected impact: x\n",
        encoding="utf-8",
    )
    suggestions_path = tmp_path / "suggestions.json"
    suggestions_path.write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "ticker": "X.L",
                        "area": "scoring",
                        "priority": "high",
                        "suggestion": "Should not appear in backstop scope",
                        "recorded_at": "2026-09-12T08:00:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    full = build_compiled_task_candidates(
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        scope="full",
        tasks_path=tmp_path / "missing_tasks.json",
        compile_since=datetime.fromisoformat("2026-09-12T12:00:00+00:00"),
    )
    backstop = build_compiled_task_candidates(
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        scope="backstop",
    )
    assert any(t.source == "research_model_suggestions" for t in full)
    assert all(t.source != "research_model_suggestions" for t in backstop)


def test_compile_capacity_audit_flags_plan_beyond_cap(tmp_path: Path):
    from value_investor.engineering_tasks import compile_capacity_audit

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    lines = [f"{i}. [scoring] Plan item {i} — expected impact: x" for i in range(1, 11)]
    plan_body = "\n".join(lines)
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "run_at": "2026-09-12T12:00:00+00:00",
                "post_run_review": {"improvement_plan": plan_body},
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "post_run_review.md").write_text(
        "PRIORITISED IMPROVEMENT PLAN\n" + plan_body,
        encoding="utf-8",
    )
    audit = compile_capacity_audit(
        output_dir=output_dir,
        latest_path=latest,
        max_tasks=8,
        suggestions_path=tmp_path / "no_suggestions.json",
        tasks_path=tmp_path / "no_tasks.json",
    )
    assert audit["post_run_plan_count"] == 10
    assert len(audit["post_run_plan_beyond_cap"]) == 2
    assert audit["truncated_count"] >= 2


def test_clean_post_run_plan_title_strips_bold_and_em_dash_tail():
    from value_investor.engineering_tasks import clean_post_run_plan_title

    raw = (
        "Implement canonical FCF selector with divergence flag** — "
        "When filing, screen TTM, and company_adjusted disagree"
    )
    assert clean_post_run_plan_title(raw) == "Implement canonical FCF selector with divergence flag"


def test_compile_engineering_tasks_accepts_prompt_format_without_bold(tmp_path: Path):
    """Post-run prompt asks for ``N. [area] Action`` without mandatory markdown bold."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "post_run_review.md").write_text(
        """PRIORITISED IMPROVEMENT PLAN
1. [scoring] Implement canonical filing-aligned FCF as sole input for FCF Yield — expected impact: fewer overlay downgrades.

2. [ingest] Ship Yahoo quarterly cash-flow ingest into financials_annual.json — expected impact: period-aligned OCF.

DEFER
- ignore me
""",
        encoding="utf-8",
    )
    payload = compile_engineering_tasks(
        output_dir=output_dir,
        suggestions_path=tmp_path / "missing.json",
        max_tasks=5,
        tasks_path=output_dir / "engineering_tasks.json",
        committed_path=tmp_path / "committed" / "engineering_tasks.json",
    )
    assert payload["task_count"] == 2
    areas = {row["area"] for row in payload["tasks"]}
    assert areas == {"scoring", "ingest"}
    assert all(row["source"] == "post_run_review" for row in payload["tasks"])
    assert all(row["status"] == "open" for row in payload["tasks"])


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
