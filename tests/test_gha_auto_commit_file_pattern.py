"""git-auto-commit-action file_pattern must be a single line.

The action's entrypoint reads ``file_pattern`` with ``read -r -a``, which stops at
the first newline, so later lines of a ``|`` block are silently never committed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

AUTO_COMMIT_ACTION = "stefanzweifel/git-auto-commit-action"
WORKFLOWS_DIR = Path(".github/workflows")
CHECKED_WORKFLOWS = ("t212-catalogue-refresh.yml",)


def _auto_commit_patterns(workflow: Path) -> list[str]:
    payload = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    patterns: list[str] = []
    for job in (payload.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if str(step.get("uses") or "").startswith(AUTO_COMMIT_ACTION):
                pattern = (step.get("with") or {}).get("file_pattern")
                if pattern is not None:
                    patterns.append(str(pattern))
    return patterns


def test_checked_workflows_use_single_line_file_pattern() -> None:
    for name in CHECKED_WORKFLOWS:
        patterns = _auto_commit_patterns(WORKFLOWS_DIR / name)
        assert patterns, f"{name}: no git-auto-commit file_pattern found"
        for pattern in patterns:
            assert "\n" not in pattern.strip(), f"{name}: multi-line file_pattern {pattern!r}"


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
