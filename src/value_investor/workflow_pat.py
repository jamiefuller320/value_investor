"""Resolve a user PAT for GitHub Actions workflow_dispatch and related API calls."""

from __future__ import annotations

import os

WORKFLOW_DISPATCH_PAT_ENV = "WORKFLOW_DISPATCH_PAT"


def is_integration_token(token: str | None) -> bool:
    """True for Cursor/GitHub App installation tokens (ghs_…), not user PATs."""
    return bool(token and token.strip().startswith("ghs_"))


def resolve_workflow_dispatch_pat() -> str | None:
    """
    Return a user PAT suitable for workflow_dispatch.

    Uses WORKFLOW_DISPATCH_PAT only. Rejects ghs_ integration tokens so a
    Cursor-injected GH_TOKEN does not satisfy dispatch requirements.
    """
    value = (os.environ.get(WORKFLOW_DISPATCH_PAT_ENV) or "").strip()
    if not value or is_integration_token(value):
        return None
    return value


def require_workflow_dispatch_pat(*, repo: str = "jamiefuller320/value_investor") -> str:
    pat = resolve_workflow_dispatch_pat()
    if pat:
        return pat
    has_ghs = any(
        is_integration_token(os.environ.get(key))
        for key in (WORKFLOW_DISPATCH_PAT_ENV, "GH_TOKEN", "GITHUB_TOKEN")
    )
    hint = (
        " Set WORKFLOW_DISPATCH_PAT to a fine-grained PAT with Actions: Read and write."
        if has_ghs
        else " Set WORKFLOW_DISPATCH_PAT."
    )
    raise RuntimeError(
        f"WORKFLOW_DISPATCH_PAT required for {repo}.{hint}"
    )
