"""Resolve a user PAT for GitHub Actions workflow_dispatch and related API calls."""

from __future__ import annotations

import os

WORKFLOW_DISPATCH_PAT_ENV = "WORKFLOW_DISPATCH_PAT"
GH_PAT_ENV = "GH_PAT"


def is_integration_token(token: str | None) -> bool:
    """True for Cursor/GitHub App installation tokens (ghs_…), not user PATs."""
    return bool(token and token.strip().startswith("ghs_"))


def resolve_workflow_dispatch_pat() -> str | None:
    """
    Return a user PAT suitable for workflow_dispatch.

    Prefers WORKFLOW_DISPATCH_PAT over GH_PAT. Skips ghs_ integration tokens
    so Cursor-injected GH_PAT does not mask a missing fine-grained PAT.
    """
    for key in (WORKFLOW_DISPATCH_PAT_ENV, GH_PAT_ENV):
        value = (os.environ.get(key) or "").strip()
        if not value or is_integration_token(value):
            continue
        return value
    return None


def require_workflow_dispatch_pat(*, repo: str = "jamiefuller320/value_investor") -> str:
    pat = resolve_workflow_dispatch_pat()
    if pat:
        return pat
    has_ghs = any(
        is_integration_token(os.environ.get(key))
        for key in (WORKFLOW_DISPATCH_PAT_ENV, GH_PAT_ENV, "GH_TOKEN", "GITHUB_TOKEN")
    )
    hint = (
        " Set WORKFLOW_DISPATCH_PAT to a fine-grained PAT with Actions: Read and write."
        if has_ghs
        else " Set WORKFLOW_DISPATCH_PAT (preferred) or GH_PAT."
    )
    raise RuntimeError(
        f"Workflow dispatch PAT required for {repo}.{hint}"
    )
