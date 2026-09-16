"""Tests for ingest_narrow / scoring_narrow independent verify + scoped auto-merge."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from value_investor.engineering_auto_merge import evaluate_auto_merge
from value_investor.engineering_narrow_merge import (
    evaluate_ingest_narrow_verify,
    evaluate_narrow_verify,
    evaluate_scoring_narrow_verify,
    ingest_narrow_merge_allowed,
    list_todays_engineering_merges,
    scoring_narrow_merge_allowed,
    task_narrow_merge_class,
)
from value_investor.engineering_tasks import AREA_ALLOWED_PATHS, BLOCKED_PATHS, EngineeringTask
from value_investor.project_traffic import build_daily_digest, format_daily_digest_markdown
from value_investor.storage import write_json


def _ingest_task(**overrides) -> EngineeringTask:
    payload = dict(
        id="eng-20260915-01",
        area="ingest",
        title="Investegate direct fetch",
        summary="x",
        priority="high",
        priority_score=90.0,
        source="post_run_review",
        allowed_paths=list(AREA_ALLOWED_PATHS["ingest"]),
        blocked_paths=list(BLOCKED_PATHS),
        auto_merge=False,
        status="pr_open",
    )
    payload.update(overrides)
    return EngineeringTask(**payload)


def _scoring_task(**overrides) -> EngineeringTask:
    payload = dict(
        id="eng-20260915-09",
        area="scoring",
        title="Peer model pass table",
        summary="x",
        priority="high",
        priority_score=88.0,
        source="post_run_review",
        allowed_paths=list(AREA_ALLOWED_PATHS["scoring"]),
        blocked_paths=list(BLOCKED_PATHS),
        auto_merge=False,
        status="pr_open",
    )
    payload.update(overrides)
    return EngineeringTask(**payload)


def _write_task(path: Path, task: EngineeringTask, **extra: object) -> None:
    row = task.to_dict()
    row.update(extra)
    write_json(path, {"tasks": [row]}, compact=False)


def test_ingest_narrow_verify_approves_651_shaped_diff():
    task = _ingest_task()
    changed = [
        "src/value_investor/research/filings.py",
        "tests/test_research_filings.py",
    ]
    result = evaluate_ingest_narrow_verify(task=task, changed_files=changed, policy="merge")
    assert result.ok
    assert result.verdict == "approve"
    assert result.merge_class == "ingest_narrow"
    allowed, reason = ingest_narrow_merge_allowed(task=task, changed_files=changed, policy="merge")
    assert allowed
    assert "ingest_narrow" in reason


def test_compile_cap_drain_source_is_narrow_merge_class():
    task = _scoring_task(source="compile_cap_drain", area="prompt", auto_merge=False)
    assert task_narrow_merge_class(task) == "compile_cap_drain"
    changed = [
        "src/value_investor/research/format.py",
        "tests/test_research_format.py",
    ]
    # Use a tight allowlist so the diff stays in-bounds for prompt-area paths.
    task = _scoring_task(
        source="compile_cap_drain",
        area="prompt",
        auto_merge=False,
        allowed_paths=[
            "src/value_investor/research/format.py",
            "tests/test_research_format.py",
        ],
    )
    result = evaluate_narrow_verify(task=task, changed_files=changed, policy="merge")
    assert result.ok
    assert result.verdict == "approve"
    assert result.merge_class == "compile_cap_drain"


def test_scoring_narrow_verify_approves_653_shaped_diff():
    task = _scoring_task()
    changed = [
        "src/value_investor/scoring/peer_model_pass_table.py",
        "src/value_investor/summary.py",
        "tests/test_summary.py",
    ]
    result = evaluate_scoring_narrow_verify(task=task, changed_files=changed, policy="merge")
    assert result.ok
    assert result.verdict == "approve"
    assert result.merge_class == "scoring_narrow"
    allowed, reason = scoring_narrow_merge_allowed(task=task, changed_files=changed, policy="merge")
    assert allowed
    assert "scoring_narrow" in reason


def test_ingest_narrow_rejects_wide_area_allowlist_as_changed_set():
    task = _ingest_task()
    result = evaluate_ingest_narrow_verify(
        task=task, changed_files=list(task.allowed_paths), policy="merge"
    )
    assert not result.ok
    assert result.verdict == "reject"


def test_scoring_narrow_observe_does_not_merge():
    task = _scoring_task()
    changed = [
        "src/value_investor/summary.py",
        "tests/test_summary.py",
    ]
    allowed, reason = scoring_narrow_merge_allowed(
        task=task, changed_files=changed, policy="observe"
    )
    assert not allowed
    assert "observe" in reason


def test_evaluate_auto_merge_allows_ingest_narrow_when_policy_merge(tmp_path: Path):
    task = _ingest_task()
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_task(tasks_path, task, branch_name="cursor/eng-20260915-01-1de3")
    changed = [
        "src/value_investor/research/filings.py",
        "tests/test_research_filings.py",
    ]
    with (
        patch(
            "value_investor.engineering_auto_merge.find_open_pr_for_branch",
            return_value={"number": 651, "isDraft": True},
        ),
        patch(
            "value_investor.engineering_auto_merge.pr_checks_successful",
            return_value=(True, "all checks green"),
        ),
        patch(
            "value_investor.engineering_auto_merge.changed_files_for_pr",
            return_value=changed,
        ),
        patch(
            "value_investor.engineering_narrow_merge.narrow_policy",
            return_value="merge",
        ),
    ):
        decision = evaluate_auto_merge(
            branch="cursor/eng-20260915-01-1de3",
            tasks_path=tasks_path,
        )
    assert decision.should_merge
    assert decision.merge_class == "ingest_narrow"
    assert decision.pr_number == 651


def test_evaluate_auto_merge_allows_scoring_narrow_when_policy_merge(tmp_path: Path):
    task = _scoring_task()
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_task(tasks_path, task, branch_name="cursor/eng-20260915-09-1de3")
    changed = [
        "src/value_investor/scoring/peer_model_pass_table.py",
        "src/value_investor/pipeline.py",
        "src/value_investor/summary.py",
        "tests/test_summary.py",
    ]
    with (
        patch(
            "value_investor.engineering_auto_merge.find_open_pr_for_branch",
            return_value={"number": 653, "isDraft": True},
        ),
        patch(
            "value_investor.engineering_auto_merge.pr_checks_successful",
            return_value=(True, "all checks green"),
        ),
        patch(
            "value_investor.engineering_auto_merge.changed_files_for_pr",
            return_value=changed,
        ),
        patch(
            "value_investor.engineering_narrow_merge.narrow_policy",
            return_value="merge",
        ),
    ):
        decision = evaluate_auto_merge(
            branch="cursor/eng-20260915-09-1de3",
            tasks_path=tasks_path,
        )
    assert decision.should_merge
    assert decision.merge_class == "scoring_narrow"
    assert decision.pr_number == 653


def test_evaluate_auto_merge_allows_compile_cap_drain_when_policy_merge(tmp_path: Path):
    task = _scoring_task(
        id="eng-20260916-11",
        source="compile_cap_drain",
        area="prompt",
        auto_merge=False,
        allowed_paths=[
            "src/value_investor/research/format.py",
            "tests/test_research_format.py",
        ],
    )
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_task(tasks_path, task, branch_name="cursor/eng-20260916-11-1de3")
    changed = [
        "src/value_investor/research/format.py",
        "tests/test_research_format.py",
    ]
    with (
        patch(
            "value_investor.engineering_auto_merge.find_open_pr_for_branch",
            return_value={"number": 680, "isDraft": True},
        ),
        patch(
            "value_investor.engineering_auto_merge.pr_checks_successful",
            return_value=(True, "all checks green"),
        ),
        patch(
            "value_investor.engineering_auto_merge.changed_files_for_pr",
            return_value=changed,
        ),
        patch(
            "value_investor.engineering_narrow_merge.narrow_policy",
            return_value="merge",
        ),
    ):
        decision = evaluate_auto_merge(
            branch="cursor/eng-20260916-11-1de3",
            tasks_path=tasks_path,
        )
    assert decision.should_merge
    assert decision.merge_class == "compile_cap_drain"
    assert decision.pr_number == 680


def test_evaluate_auto_merge_stamps_compile_cap_drain_when_auto_merge_flag(tmp_path: Path):
    """auto_merge=true still labels merge_class compile_cap_drain for EOD digest."""
    task = _scoring_task(
        id="eng-20260916-12",
        source="compile_cap_drain",
        area="prompt",
        auto_merge=True,
        allowed_paths=[
            "src/value_investor/research/format.py",
            "tests/test_research_format.py",
        ],
    )
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_task(tasks_path, task, branch_name="cursor/eng-20260916-12-1de3")
    changed = [
        "src/value_investor/research/format.py",
        "tests/test_research_format.py",
    ]
    with (
        patch(
            "value_investor.engineering_auto_merge.find_open_pr_for_branch",
            return_value={"number": 681, "isDraft": True},
        ),
        patch(
            "value_investor.engineering_auto_merge.pr_checks_successful",
            return_value=(True, "all checks green"),
        ),
        patch(
            "value_investor.engineering_auto_merge.changed_files_for_pr",
            return_value=changed,
        ),
    ):
        decision = evaluate_auto_merge(
            branch="cursor/eng-20260916-12-1de3",
            tasks_path=tasks_path,
        )
    assert decision.should_merge
    assert decision.merge_class == "compile_cap_drain"
    assert decision.pr_number == 681


def test_list_todays_merges_and_digest_section(tmp_path: Path):
    now = datetime(2026, 9, 15, 18, 0, tzinfo=UTC)
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(
        tasks_path,
        {
            "tasks": [
                {
                    "id": "eng-20260915-01",
                    "area": "ingest",
                    "title": "Investegate direct fetch",
                    "status": "merged",
                    "merged_at": "2026-09-15T13:00:00+00:00",
                    "pr_number": 651,
                    "pr_url": "https://github.com/example/pull/651",
                    "auto_merge": False,
                    "evidence": {"merge_class": "ingest_narrow"},
                },
                {
                    "id": "eng-20260915-09",
                    "area": "scoring",
                    "title": "Peer model pass table",
                    "status": "merged",
                    "merged_at": "2026-09-15T14:00:00+00:00",
                    "pr_number": 653,
                    "pr_url": "https://github.com/example/pull/653",
                    "auto_merge": False,
                    "evidence": {"merge_class": "scoring_narrow"},
                },
                {
                    "id": "eng-20260914-01",
                    "area": "ingest",
                    "title": "yesterday",
                    "status": "merged",
                    "merged_at": "2026-09-14T13:00:00+00:00",
                    "pr_number": 640,
                    "evidence": {"merge_class": "human"},
                },
            ]
        },
        compact=False,
    )
    rows = list_todays_engineering_merges(tasks_path=tasks_path, now=now)
    assert len(rows) == 2
    assert {row["pr_number"] for row in rows} == {651, 653}
    assert all(row["independently_verified"] for row in rows)

    with patch(
        "value_investor.project_traffic.COMMITTED_TASKS_PATH",
        tasks_path,
    ):
        digest = build_daily_digest(
            stuck_prs=[],
            traffic_state={"pause_active": False},
            actions=[],
            progress_report_path=tmp_path / "missing_progress.json",
            project_progress_path=tmp_path / "missing_project.json",
            queue_health_path=tmp_path / "missing_qh.json",
            ops_status_path=tmp_path / "missing_ops.json",
            now=now,
        )
    assert {row["pr_number"] for row in digest["merges_today"]} == {651, 653}
    assert digest["merge_authority"]["status"] == "scoped_auto_merge"
    md = format_daily_digest_markdown(digest)
    assert "Merges today" in md
    assert "ingest_narrow" in md
    assert "scoring_narrow" in md
    assert "651" in md
    assert "653" in md


def test_eng_narrow_gate_cli_reject_does_not_fail_ci(tmp_path: Path, monkeypatch, capsys):
    """Wide scoring diffs must stay human-mergeable — reject is informational."""
    import argparse

    from value_investor.engineering_cli import _cmd_eng_narrow_gate

    task = _scoring_task(id="eng-20260916-01")
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_task(tasks_path, task, branch_name="cursor/eng-20260916-01-1de3")
    changed_path = tmp_path / "changed.txt"
    changed_path.write_text(
        "\n".join(
            [
                "src/value_investor/pipeline.py",
                "src/value_investor/scoring/fcf.py",
                "src/value_investor/scoring/fcf_basis_overlay.py",
                "src/value_investor/scoring/healthcare_overlay.py",
                "src/value_investor/scoring/healthcare_price_erosion_overlay.py",
                "src/value_investor/scoring/healthcare_reimbursement_overlay.py",
                "src/value_investor/scoring/screening_export_guard.py",
                "src/value_investor/scoring/snapshot.py",
                "src/value_investor/summary.py",
                "tests/test_pipeline.py",
                "tests/test_summary.py",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "value_investor.engineering_cli._resolve_tasks_path",
        lambda _path=None: tasks_path,
    )
    args = argparse.Namespace(
        branch="cursor/eng-20260916-01-1de3",
        tasks_path=tasks_path,
        changed_files=str(changed_path),
        base_ref="origin/main",
        head_ref="HEAD",
        json=True,
    )
    rc = _cmd_eng_narrow_gate(args)
    assert rc == 0
    payload = __import__("json").loads(capsys.readouterr().out)
    assert payload["verdict"] == "reject"
    assert "too many changed files" in payload["reason"]
    assert payload["ok"] is False


def test_eng_narrow_gate_cli_approve_stays_green(tmp_path: Path, monkeypatch, capsys):
    import argparse

    from value_investor.engineering_cli import _cmd_eng_narrow_gate

    task = _scoring_task()
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_task(tasks_path, task, branch_name="cursor/eng-20260915-09-1de3")
    changed_path = tmp_path / "changed.txt"
    changed_path.write_text(
        "src/value_investor/summary.py\ntests/test_summary.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "value_investor.engineering_cli._resolve_tasks_path",
        lambda _path=None: tasks_path,
    )
    args = argparse.Namespace(
        branch="cursor/eng-20260915-09-1de3",
        tasks_path=tasks_path,
        changed_files=str(changed_path),
        base_ref="origin/main",
        head_ref="HEAD",
        json=True,
    )
    with patch(
        "value_investor.engineering_narrow_merge.narrow_policy",
        return_value="merge",
    ):
        rc = _cmd_eng_narrow_gate(args)
    assert rc == 0
    payload = __import__("json").loads(capsys.readouterr().out)
    assert payload["verdict"] == "approve"
    assert payload["ok"] is True
