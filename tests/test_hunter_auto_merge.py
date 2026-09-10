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
)
from value_investor.hunter_auto_merge import (
    HunterOutcome,
    analyze_hunter_pr_diff,
    evaluate_hunter_merge_gate,
    validate_hunter_diff_scope,
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
