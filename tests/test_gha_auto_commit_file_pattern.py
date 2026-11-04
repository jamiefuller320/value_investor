"""git-auto-commit-action file_pattern must be one line of always-present paths.

The action's entrypoint reads ``file_pattern`` with ``read -r -a``, which stops at
the first newline, so later lines of a ``|`` block are silently never committed.
It then runs ``git add <file_pattern>``, which fails the step when any pathspec
matches nothing — conditional outputs belong in ``scripts/gha_commit_artifacts.sh``,
which skips missing paths.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

AUTO_COMMIT_ACTION = "stefanzweifel/git-auto-commit-action"
WORKFLOWS_DIR = Path(".github/workflows")
COMMIT_HELPER = "bash scripts/gha_commit_artifacts.sh"


def _steps(workflow: Path) -> list[dict]:
    payload = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    steps: list[dict] = []
    for job in (payload.get("jobs") or {}).values():
        steps.extend(step for step in job.get("steps") or [] if isinstance(step, dict))
    return steps


def _auto_commit_patterns(workflow: Path) -> list[str]:
    patterns: list[str] = []
    for step in _steps(workflow):
        if str(step.get("uses") or "").startswith(AUTO_COMMIT_ACTION):
            pattern = (step.get("with") or {}).get("file_pattern")
            if pattern is not None:
                patterns.append(str(pattern))
    return patterns


def _all_patterns() -> list[tuple[str, str]]:
    return [
        (workflow.name, pattern)
        for workflow in sorted(WORKFLOWS_DIR.glob("*.yml"))
        for pattern in _auto_commit_patterns(workflow)
    ]


def _helper_step(workflow: str, name: str) -> dict:
    for step in _steps(WORKFLOWS_DIR / workflow):
        if step.get("name") == name:
            return step
    raise AssertionError(f"{workflow}: no step named {name!r}")


def test_auto_commit_workflows_found() -> None:
    assert len(_all_patterns()) >= 10


@pytest.mark.parametrize(("workflow", "pattern"), _all_patterns())
def test_file_pattern_is_single_line(workflow: str, pattern: str) -> None:
    assert "\n" not in pattern.strip(), f"{workflow}: multi-line file_pattern {pattern!r}"


@pytest.mark.parametrize(("workflow", "pattern"), _all_patterns())
def test_file_pattern_paths_are_tracked(workflow: str, pattern: str) -> None:
    missing = []
    for spec in pattern.split():
        found = subprocess.run(
            ["git", "ls-files", "--", spec],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if not found:
            missing.append(spec)
    assert not missing, (
        f"{workflow}: git add fails on pathspecs with no tracked file {missing}; "
        f"use {COMMIT_HELPER} for conditional outputs"
    )


def test_t212_refresh_commits_overlay_files() -> None:
    (pattern,) = _auto_commit_patterns(WORKFLOWS_DIR / "t212-catalogue-refresh.yml")
    tokens = pattern.split()
    for expected in (
        "docs/data/library/t212_coverage/catalogue/**",
        "docs/data/library/t212_coverage/by_market/**",
        "docs/data/library/t212_coverage/summary.json",
        "docs/data/library/t212_coverage/README.md",
    ):
        assert expected in tokens


@pytest.mark.parametrize(
    ("workflow", "step_name", "expected"),
    [
        (
            "analysis-review.yml",
            "Commit knob bootstrap artifacts",
            {
                "docs/data/history/run_*.json.gz",
                "docs/data/news_event_journal.json",
                "docs/data/filing_event_unknowns.json",
                "docs/data/exit_timing_reconciliation.json",
            },
        ),
        (
            "analysis-review.yml",
            "Commit system-gap snapshot",
            {"docs/data/system_gaps.json", "docs/data/phase_c_readiness.json"},
        ),
        (
            "lifecycle-experiment-start.yml",
            "Commit dashboard slices",
            {
                "docs/data/experiment_starts.json",
                "docs/data/paper_automation/graduated_allocation/entry_dca_pending.json",
            },
        ),
        (
            "workflow-failure-responder.yml",
            "Commit drafted workflow-failure task",
            {"docs/data/engineering_tasks.json", "docs/data/gha_failure_triage.json"},
        ),
        (
            "library-ladder-responder.yml",
            "Commit drafted engineering tasks",
            {"docs/data/engineering_tasks.json", "docs/data/library/ladder_responder_log.json"},
        ),
    ],
)
def test_conditional_outputs_use_commit_helper(
    workflow: str, step_name: str, expected: set[str]
) -> None:
    step = _helper_step(workflow, step_name)
    assert step.get("run", "").strip() == COMMIT_HELPER
    env = step.get("env") or {}
    assert env.get("COMMIT_MESSAGE")
    owned = set(str(env.get("GHA_COMMIT_OWNED") or "").split())
    assert expected <= owned


def test_knob_commit_only_overlays_task_stores_when_main_unchanged() -> None:
    env = _helper_step("analysis-review.yml", "Commit knob bootstrap artifacts")["env"]
    optional = set(str(env.get("GHA_COMMIT_OPTIONAL") or "").split())
    assert optional == {"docs/data/analysis_tasks.json", "docs/data/engineering_tasks.json"}
    assert not optional & set(str(env["GHA_COMMIT_OWNED"]).split())
