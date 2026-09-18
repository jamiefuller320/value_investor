"""Hunter-fix tip pushes must use WORKFLOW_DISPATCH_PAT to avoid action_required CI."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/engineering-hunter-fix.yml")


def test_hunter_fix_commit_step_uses_workflow_dispatch_pat() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "name: Commit and push hunter-fix" in text
    assert "WORKFLOW_DISPATCH_PAT: ${{ secrets.WORKFLOW_DISPATCH_PAT }}" in text
    assert "gh auth setup-git" in text
    assert "WORKFLOW_DISPATCH_PAT not set" in text
    # Push must follow PAT wiring (not a bare default-token push only).
    commit_idx = text.index("name: Commit and push hunter-fix")
    push_idx = text.index('git push origin "HEAD:$BRANCH"', commit_idx)
    setup_idx = text.index("gh auth setup-git", commit_idx)
    assert setup_idx < push_idx
