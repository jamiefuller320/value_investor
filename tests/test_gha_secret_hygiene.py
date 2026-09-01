"""Guards against reintroducing GHA secret-exposure patterns."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

_INTERP = re.compile(
    r"\$\{\{\s*github\.event\."
    r"(?:pull_request\.head\.ref|workflow_run\.head_branch|workflow_run\.name)"
    r"\s*\}\}"
)


def _workflow_text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _run_blocks(text: str) -> list[str]:
    """Return bodies of `run: |` / `run: >` steps (shell scripts only)."""
    blocks: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = re.match(r"^(\s*)run:\s*[|>]", lines[i])
        if not match:
            i += 1
            continue
        indent = len(match.group(1))
        i += 1
        body: list[str] = []
        while i < len(lines):
            line = lines[i]
            if line.strip() == "":
                body.append(line)
                i += 1
                continue
            leading = len(line) - len(line.lstrip(" "))
            if leading <= indent:
                break
            body.append(line)
            i += 1
        blocks.append("\n".join(body))
    return blocks


def test_pr_autofix_requires_same_repo_and_trusted_install() -> None:
    text = _workflow_text("ci-pr-autofix.yml")
    assert "head_repository.full_name == github.repository" in text
    assert 'pip install ".[dev]"' in text
    assert "pip install -e" not in text
    assert "cp scripts/ci_pr_autofix.py /tmp/ci_pr_autofix.py" in text
    assert "ref: main" in text


def test_auto_merge_requires_same_repo_and_env_branch() -> None:
    text = _workflow_text("engineering-auto-merge.yml")
    assert "head_repository.full_name == github.repository" in text
    assert "BRANCH: ${{ github.event.workflow_run.head_branch }}" in text
    assert '--branch "${{ github.event.workflow_run.head_branch }}"' not in text
    assert r"^cursor/eng-[0-9]{8}-[0-9]{2}-1de3$" in text


def test_no_untrusted_expr_inside_run_scripts() -> None:
    for name in (
        "ci-pr-autofix.yml",
        "engineering-auto-merge.yml",
        "engineering-queue.yml",
        "workflow-failure-responder.yml",
        "ci-fix-responder.yml",
        "library-ladder-responder.yml",
    ):
        for block in _run_blocks(_workflow_text(name)):
            hit = _INTERP.search(block)
            assert hit is None, f"{name} run script interpolates untrusted field: {hit.group(0)}"
