"""Guards against reintroducing GHA secret-exposure patterns."""

from __future__ import annotations

from pathlib import Path

from value_investor.gha_secret_hygiene import (
    decide_schedule_gate,
    extract_run_blocks,
    scan_workflow_text,
    scan_workflows,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_scan_workflows_clean_on_repo() -> None:
    report = scan_workflows(WORKFLOWS)
    errors = [item for item in report.findings if item.severity == "error"]
    assert errors == [], errors
    assert report.ok


def test_pr_autofix_requires_same_repo_and_trusted_install() -> None:
    text = (WORKFLOWS / "ci-pr-autofix.yml").read_text(encoding="utf-8")
    findings = scan_workflow_text("ci-pr-autofix.yml", text)
    assert not any(item.severity == "error" for item in findings)
    assert "head_repository.full_name == github.repository" in text
    assert 'pip install ".[dev]"' in text
    assert "pip install -e" not in text
    assert "cp scripts/ci_pr_autofix.py /tmp/ci_pr_autofix.py" in text
    assert "ref: main" in text
    assert "skip_verify_pytest" in text
    assert "path_guard_revert" in text
    assert "path_guard_effective_changed_paths" in text
    assert "reverted_paths" in text
    assert "git diff --name-only origin/main" not in text


def test_auto_merge_requires_same_repo_and_env_branch() -> None:
    text = (WORKFLOWS / "engineering-auto-merge.yml").read_text(encoding="utf-8")
    findings = scan_workflow_text("engineering-auto-merge.yml", text)
    assert not any(item.severity == "error" for item in findings)
    assert "BRANCH: ${{ github.event.workflow_run.head_branch }}" in text
    assert '--branch "${{ github.event.workflow_run.head_branch }}"' not in text
    assert r"^cursor/eng-[0-9]{8}-[0-9]{2}-1de3$" in text
    # Job if must skip meta eng branches (eng-narrow-gate-*) before the step runs.
    assert "endsWith(github.event.workflow_run.head_branch, '-1de3')" in text
    # Regex miss must skip (exit 0), not fail the workflow (2026-09-16 #35069856035).
    assert "Skipping non-queue engineering branch" in text
    assert "Rejecting non-engineering or unsafe branch name" not in text
    assert 'echo "merged=false" >> "$GITHUB_OUTPUT"' in text


def test_ingest_loop_step_timeout_has_headroom_above_soft_budget() -> None:
    """Soft 3600s cutoff must not race the GHA step hard timeout.

    Regression for 2026-09-16 runs #35066797050 / #35018323617: partial JSON
    was written then the 65m step timed out before commit/chain.
    """
    import re

    text = (WORKFLOWS / "ingest-loop.yml").read_text(encoding="utf-8")
    # Dispatch default soft budget.
    default_m = re.search(
        r"max_runtime_seconds:.*?default:\s*\"(\d+)\"",
        text,
        flags=re.DOTALL,
    )
    assert default_m is not None
    soft_budget_s = int(default_m.group(1))
    assert soft_budget_s == 3600

    job_m = re.search(
        r"ingest-loop:\s*\n(?:.*\n)*?\s+timeout-minutes:\s*(\d+)",
        text,
    )
    assert job_m is not None
    job_timeout_m = int(job_m.group(1))

    step_m = re.search(
        r"name: Run weekday ingest loop\n(?:.*\n)*?\s+timeout-minutes:\s*(\d+)",
        text,
    )
    assert step_m is not None
    step_timeout_m = int(step_m.group(1))

    # At least 15 minutes of wall headroom after soft budget for JSON/outputs.
    min_step_m = (soft_budget_s // 60) + 15
    assert step_timeout_m >= min_step_m, (
        f"step timeout {step_timeout_m}m < soft budget headroom {min_step_m}m"
    )
    assert job_timeout_m > step_timeout_m
    # Leave room for commit + chain dispatch after the loop step.
    assert job_timeout_m >= step_timeout_m + 15


def test_detects_untrusted_expr_in_run_block() -> None:
    evil = """
name: Evil
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
jobs:
  x:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ github.event.workflow_run.head_branch }}"
"""
    findings = scan_workflow_text("evil.yml", evil)
    assert any(item.rule == "untrusted_expr_in_run" for item in findings)


def test_detects_dispatch_input_in_run_block() -> None:
    evil = """
name: Evil
on:
  workflow_dispatch:
    inputs:
      task_id:
        type: string
jobs:
  x:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ github.event.inputs.task_id }}"
"""
    findings = scan_workflow_text("evil.yml", evil)
    assert any(item.rule == "dispatch_input_in_run" for item in findings)


def test_dispatch_input_via_env_is_allowed() -> None:
    ok = """
name: Ok
on:
  workflow_dispatch:
    inputs:
      task_id:
        type: string
jobs:
  x:
    runs-on: ubuntu-latest
    steps:
      - env:
          TASK_ID: ${{ github.event.inputs.task_id }}
        run: |
          echo "$TASK_ID"
"""
    findings = scan_workflow_text("ok.yml", ok)
    assert not any(item.rule == "dispatch_input_in_run" for item in findings)


def test_detects_missing_same_repo_gate_on_head_checkout() -> None:
    evil = """
name: Evil
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
jobs:
  x:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event.workflow_run.head_sha }}
"""
    findings = scan_workflow_text("evil.yml", evil)
    assert any(item.rule == "workflow_run_missing_same_repo_gate" for item in findings)


def test_schedule_gate_force_and_recent_changes() -> None:
    forced = decide_schedule_gate(force=True)
    assert forced.should_run and forced.reason == "force"

    skip = decide_schedule_gate(
        force=False,
        merged_pr_count=0,
        workflow_touch_count=0,
        lookback_hours=36,
    )
    assert not skip.should_run
    assert skip.reason == "no_recent_merges_or_workflow_changes"

    run = decide_schedule_gate(
        force=False,
        merged_pr_count=2,
        workflow_touch_count=0,
        lookback_hours=36,
    )
    assert run.should_run and run.reason == "recent_main_changes"


def test_extract_run_blocks_ignores_env() -> None:
    text = """
jobs:
  x:
    steps:
      - env:
          BRANCH: ${{ github.event.workflow_run.head_branch }}
        run: |
          echo "$BRANCH"
"""
    blocks = extract_run_blocks(text)
    assert len(blocks) == 1
    assert "$BRANCH" in blocks[0]
    assert "github.event" not in blocks[0]


def test_cursor_agent_workflows_prefer_api_key_v2() -> None:
    """GHA must prefer CURSOR_API_KEY_V2 so a dead legacy secret does not brick agents."""
    prefer = "secrets.CURSOR_API_KEY_V2 || secrets.CURSOR_API_KEY"
    for name in (
        "analysis-review.yml",
        "email-report.yml",
        "engineering-agent.yml",
        "horizon-scan.yml",
        "ingest-loop.yml",
        "learning-director-review.yml",
        "library-grow.yml",
        "library-model-review.yml",
        "memo-backfill.yml",
        "paper-learning-review.yml",
    ):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert prefer in text, f"{name} missing V2-preferring CURSOR_API_KEY injection"
        for i, line in enumerate(text.splitlines(), 1):
            if "secrets.CURSOR_API_KEY" not in line or line.lstrip().startswith("#"):
                continue
            assert "CURSOR_API_KEY_V2" in line, f"{name}:{i} bare CURSOR_API_KEY secret"
