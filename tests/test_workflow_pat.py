"""Tests for workflow dispatch PAT resolution."""

from __future__ import annotations

import pytest

from value_investor.workflow_pat import (
    is_integration_token,
    require_workflow_dispatch_pat,
    resolve_workflow_dispatch_pat,
)


def test_resolve_uses_workflow_dispatch_pat(monkeypatch):
    monkeypatch.setenv("WORKFLOW_DISPATCH_PAT", "github_pat_preferred")
    assert resolve_workflow_dispatch_pat() == "github_pat_preferred"


def test_resolve_ignores_gh_pat_env(monkeypatch):
    monkeypatch.delenv("WORKFLOW_DISPATCH_PAT", raising=False)
    monkeypatch.setenv("GH_PAT", "github_pat_legacy")
    assert resolve_workflow_dispatch_pat() is None


def test_resolve_skips_integration_token(monkeypatch):
    monkeypatch.setenv("WORKFLOW_DISPATCH_PAT", "ghs_integration_token")
    assert resolve_workflow_dispatch_pat() is None


def test_require_raises_when_missing(monkeypatch):
    monkeypatch.delenv("WORKFLOW_DISPATCH_PAT", raising=False)
    with pytest.raises(RuntimeError, match="WORKFLOW_DISPATCH_PAT"):
        require_workflow_dispatch_pat()


def test_is_integration_token():
    assert is_integration_token("ghs_abc")
    assert not is_integration_token("github_pat_abc")
