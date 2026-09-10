"""Tests for parked-source hunter auto-merge gates."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from value_investor.engineering_auto_merge import evaluate_auto_merge
from value_investor.engineering_tasks import (
    BLOCKED_PATHS,
    PARKED_SOURCE_HUNTER_SOURCE,
    EngineeringTask,
    load_engineering_tasks,
)
from value_investor.engineering_verify import verify_merged_task
from value_investor.hunter_auto_merge import (
    HunterFixKind,
    HunterOutcome,
    analyze_hunter_pr_diff,
    classify_hunter_fix_kind,
    evaluate_hunter_merge_gate,
    hunter_fix_eligible,
    live_fetch_hunter_urls,
    validate_hunter_diff_scope,
    verify_merged_hunter_allowlist_urls,
)
from value_investor.hunter_fix_agent import (
    ci_log_shows_hunter_gate_failure,
    record_hunter_fix_attempt,
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def _commit_all(path: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


SKIP_SNIPPET = """
PARKED_SOURCE_HUNTER_SKIP: dict[str, str] = {{
    "ABI.BR": (
        "Leftover indexed-without-body rows are SEC 6-K cover HTML primaries below the "
        "substantiveness gate."
    ),
    "{ticker}": (
        "{reason}"
    ),
}}
"""

ALLOWLIST_SNIPPET = """
_BUILTIN_IR_URLS: dict[str, list[str]] = {{
    "ANDR.VI": [
        "https://www.andritz.com/resource/blob/520884/annual-report-2025-en.pdf",
    ],
    "{ticker}": [
        "{url}",
    ],
}}
"""

TEST_SNIPPET = """
def test_parked_source_hunter_{slug}_euro_depth_skip():
    assert "{ticker}" in PARKED_SOURCE_HUNTER_SKIP
"""


def _write_min_filings(
    path: Path, *, ticker: str = "ABI.BR", skip_reason: str | None = None, url: str | None = None
) -> None:
    filings = path / "src/value_investor/research"
    filings.mkdir(parents=True, exist_ok=True)
    content = "from __future__ import annotations\n\n"
    if skip_reason:
        content += SKIP_SNIPPET.format(ticker=ticker, reason=skip_reason)
    else:
        content += "PARKED_SOURCE_HUNTER_SKIP: dict[str, str] = {}\n\n"
    if url:
        content += ALLOWLIST_SNIPPET.format(ticker=ticker, url=url)
    else:
        content += '_BUILTIN_IR_URLS: dict[str, list[str]] = {\n    "ANDR.VI": [\n        "https://example.com/a.pdf",\n    ],\n}\n'
    (filings / "filings.py").write_text(content, encoding="utf-8")


def _write_min_tests(path: Path, *, ticker: str = "ABI.BR", slug: str = "abi_br") -> None:
    tests = path / "tests"
    tests.mkdir(parents=True)
    (tests / "test_research_filings.py").write_text(
        TEST_SNIPPET.format(ticker=ticker, slug=slug),
        encoding="utf-8",
    )


def _hunter_task(ticker: str = "ABI.BR") -> EngineeringTask:
    return EngineeringTask(
        id="eng-20260910-01",
        area="ingest",
        title=f"Hunt fetchable IR source for parked euro_depth leftover {ticker}",
        summary="x",
        priority="low",
        priority_score=12.0,
        source=PARKED_SOURCE_HUNTER_SOURCE,
        auto_merge=False,
        status="pr_open",
        allowed_paths=[
            "src/value_investor/research/filings.py",
            "tests/test_research_filings.py",
        ],
        blocked_paths=list(BLOCKED_PATHS),
        evidence={"hunter_ticker": ticker, "market_id": "euro_depth"},
    )


def test_validate_hunter_diff_scope_rejects_extra_files():
    ok, reason = validate_hunter_diff_scope(
        ["src/value_investor/research/filings.py", "src/value_investor/research/ingest.py"]
    )
    assert not ok
    assert "unexpected changed files" in reason


def test_analyze_hunter_pr_diff_detects_skip(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    _write_min_filings(repo)
    _commit_all(repo, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    _write_min_filings(
        repo,
        ticker="ABI.BR",
        skip_reason="No fetchable IR after exhaustive search on issuer site and exchange.",
    )
    _write_min_tests(repo, ticker="ABI.BR", slug="abi_br")
    head = _commit_all(repo, "skip")

    analysis = analyze_hunter_pr_diff(
        base_ref=base,
        head_ref=head,
        hunter_ticker="ABI.BR",
        cwd=repo,
    )
    assert analysis.outcome == HunterOutcome.SKIP
    assert analysis.new_skip_reason


def test_analyze_hunter_pr_diff_detects_allowlist(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    _write_min_filings(repo)
    _commit_all(repo, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    _write_min_filings(
        repo,
        ticker="AZE.BR",
        url="https://www.aze.example/annual-report-2025.pdf",
    )
    _write_min_tests(repo, ticker="AZE.BR", slug="aze_br")
    head = _commit_all(repo, "allowlist")

    analysis = analyze_hunter_pr_diff(
        base_ref=base,
        head_ref=head,
        hunter_ticker="AZE.BR",
        cwd=repo,
    )
    assert analysis.outcome == HunterOutcome.ALLOWLIST
    assert analysis.new_urls == ["https://www.aze.example/annual-report-2025.pdf"]


def test_evaluate_hunter_merge_gate_skip_passes(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    _write_min_filings(repo)
    _commit_all(repo, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    _write_min_filings(
        repo,
        ticker="ABI.BR",
        skip_reason="No fetchable IR after exhaustive search on issuer site and exchange.",
    )
    _write_min_tests(repo, ticker="ABI.BR", slug="abi_br")
    head = _commit_all(repo, "skip")
    changed = [
        "src/value_investor/research/filings.py",
        "tests/test_research_filings.py",
    ]

    monkeypatch.setattr(
        "value_investor.hunter_auto_merge.hunter_auto_merge_policy_tier",
        lambda: "allowlist",
    )
    gate = evaluate_hunter_merge_gate(
        task=_hunter_task("ABI.BR"),
        changed_files=changed,
        base_ref=base,
        head_ref=head,
        cwd=repo,
        tier="allowlist",
        skip_live_fetch=True,
    )
    assert gate.ok
    assert gate.analysis is not None
    assert gate.analysis.outcome == HunterOutcome.SKIP


def test_evaluate_hunter_merge_gate_allowlist_requires_live_fetch(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    _write_min_filings(repo)
    _commit_all(repo, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    url = "https://www.aze.example/annual-report-2025.pdf"
    _write_min_filings(repo, ticker="AZE.BR", url=url)
    _write_min_tests(repo, ticker="AZE.BR", slug="aze_br")
    head = _commit_all(repo, "allowlist")
    changed = [
        "src/value_investor/research/filings.py",
        "tests/test_research_filings.py",
    ]

    monkeypatch.setattr(
        "value_investor.hunter_auto_merge.live_fetch_hunter_urls",
        lambda urls, ticker: (True, "mock live-fetch ok"),
    )
    gate = evaluate_hunter_merge_gate(
        task=_hunter_task("AZE.BR"),
        changed_files=changed,
        base_ref=base,
        head_ref=head,
        cwd=repo,
        tier="allowlist",
    )
    assert gate.ok
    assert gate.analysis is not None
    assert gate.analysis.outcome == HunterOutcome.ALLOWLIST


def test_evaluate_auto_merge_accepts_hunter_when_policy_and_scope_ok(tmp_path):
    task = _hunter_task("ABI.BR")
    path = tmp_path / "engineering_tasks.json"
    path.write_text(
        json.dumps({"tasks": [task.to_dict() | {"branch_name": "cursor/eng-20260910-01-1de3"}]}),
        encoding="utf-8",
    )
    branch = "cursor/eng-20260910-01-1de3"
    changed = [
        "src/value_investor/research/filings.py",
        "tests/test_research_filings.py",
    ]
    with (
        patch(
            "value_investor.engineering_auto_merge.hunter_auto_merge_policy_tier",
            return_value="allowlist",
        ),
        patch(
            "value_investor.engineering_auto_merge.find_open_pr_for_branch",
            return_value={"number": 99, "isDraft": False},
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
        decision = evaluate_auto_merge(branch=branch, tasks_path=path)
    assert decision.should_merge
    assert "hunter auto-merge eligible" in decision.reason


def test_hunter_verify_observer_skips_without_api_key(tmp_path, monkeypatch):
    from value_investor.hunter_verify_agent import run_hunter_verify_observer

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    _write_min_filings(repo)
    base = _commit_all(repo, "base")
    _write_min_filings(
        repo,
        ticker="ABI.BR",
        skip_reason="No fetchable IR after exhaustive search on issuer site and exchange.",
    )
    _write_min_tests(repo, ticker="ABI.BR", slug="abi_br")
    head = _commit_all(repo, "skip")
    changed = [
        "src/value_investor/research/filings.py",
        "tests/test_research_filings.py",
    ]

    monkeypatch.setattr(
        "value_investor.hunter_auto_merge.hunter_auto_merge_policy_tier",
        lambda: "allowlist",
    )
    result = run_hunter_verify_observer(
        task=_hunter_task("ABI.BR"),
        changed_files=changed,
        base_ref=base,
        head_ref=head,
        api_key=None,
        output_dir=tmp_path / "out",
        cwd=str(repo),
    )
    assert result.skipped
    assert result.deterministic_gate is not None


def test_classify_hunter_fix_kind_for_gate_failures():
    from value_investor.hunter_auto_merge import HunterGateResult

    missing = HunterGateResult(False, "missing new test_parked_source_hunter_* regression test")
    assert classify_hunter_fix_kind(missing) == HunterFixKind.MISSING_TEST

    short = HunterGateResult(False, "SKIP reason too short (need >= 20 chars)")
    assert classify_hunter_fix_kind(short) == HunterFixKind.SHORT_SKIP

    fetch = HunterGateResult(
        False, "live-fetch failed or body too short for https://x.example/a.pdf"
    )
    assert classify_hunter_fix_kind(fetch) == HunterFixKind.LIVE_FETCH_FAILED

    scope = HunterGateResult(False, "unexpected changed files: foo.py")
    assert classify_hunter_fix_kind(scope) is None


def test_hunter_fix_eligible_respects_max_rounds(monkeypatch):
    monkeypatch.setattr("value_investor.hunter_auto_merge.hunter_fix_max_rounds", lambda: 1)
    task = _hunter_task("AZE.BR")
    task.evidence = dict(task.evidence or {})
    task.evidence["hunter_fix_attempts"] = 1
    from value_investor.hunter_auto_merge import HunterGateResult

    gate = HunterGateResult(
        ok=False,
        reason="missing new test_parked_source_hunter_* regression test",
        tier="allowlist",
    )
    eligible, reason, fix_kind = hunter_fix_eligible(task=task, gate=gate)
    assert not eligible
    assert fix_kind == HunterFixKind.MISSING_TEST
    assert "exhausted" in reason


def test_live_fetch_hunter_urls_retries_before_failure(monkeypatch):
    calls = {"count": 0}

    def fake_fetch(row, ticker):
        calls["count"] += 1
        if calls["count"] < 2:
            return None, "fail"
        return "x" * 250, "ok"

    monkeypatch.setattr(
        "value_investor.research.filings._fetch_ir_allowlist_body",
        fake_fetch,
    )
    monkeypatch.setattr(
        "value_investor.hunter_auto_merge.hunter_live_fetch_retry_config",
        lambda: (3, (0.0, 0.0)),
    )
    ok, reason = live_fetch_hunter_urls(["https://issuer.example/report.pdf"], ticker="AZE.BR")
    assert ok
    assert calls["count"] == 2
    assert "live-fetch ok" in reason


def test_verify_merged_hunter_allowlist_urls_skips_non_allowlist(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    _write_min_filings(
        repo,
        ticker="ABI.BR",
        skip_reason="No fetchable IR after exhaustive search on issuer site and exchange.",
    )
    _write_min_tests(repo, ticker="ABI.BR", slug="abi_br")
    _commit_all(repo, "skip merge")
    task = _hunter_task("ABI.BR")
    ok, reason = verify_merged_hunter_allowlist_urls(
        task,
        merge_base_ref="HEAD^",
        merge_head_ref="HEAD",
        cwd=repo,
    )
    assert ok
    assert "not ALLOWLIST" in reason


def test_verify_merged_task_queues_rework_on_post_merge_url_failure(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    task = _hunter_task("AZE.BR")
    task_dict = task.to_dict() | {
        "status": "merged",
        "branch_name": "cursor/eng-20260910-01-1de3",
    }
    tasks_path.write_text(json.dumps({"tasks": [task_dict]}), encoding="utf-8")

    monkeypatch.setattr(
        "value_investor.engineering_verify.verify_merged_hunter_allowlist_urls",
        lambda row, cwd=None, merge_base_ref="HEAD^", merge_head_ref="HEAD": (
            False,
            "post-merge hunter URL verify failed: live-fetch failed",
        ),
    )

    def fake_pytest(paths, cwd):
        return {"ok": True, "returncode": 0, "paths": paths, "existing_paths": paths, "output": ""}

    result = verify_merged_task(
        task.id,
        tasks_path=tasks_path,
        pytest_runner=fake_pytest,
        apply=True,
    )
    assert result["should_rework"]
    assert result["reason"] == "post_merge_hunter_url_verify_failed"


def test_record_hunter_fix_attempt_merges_evidence(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    task = _hunter_task("ABI.BR")
    row = task.to_dict() | {
        "status": "pr_open",
        "evidence": {"hunter_ticker": "ABI.BR", "market_id": "euro_depth"},
    }
    tasks_path.write_text(json.dumps({"tasks": [row]}), encoding="utf-8")
    attempts = record_hunter_fix_attempt(task.id, tasks_path=tasks_path)
    assert attempts == 1
    payload = load_engineering_tasks(tasks_path)
    evidence = payload["tasks"][0]["evidence"]
    assert evidence["hunter_fix_attempts"] == 1
    assert evidence["market_id"] == "euro_depth"


def test_ci_log_shows_hunter_gate_failure():
    assert ci_log_shows_hunter_gate_failure("hunter-merge-gate: fail — missing test")
    assert not ci_log_shows_hunter_gate_failure("pytest failed: assert False")
