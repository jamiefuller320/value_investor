"""Tests for Supabase dashboard bridge helpers."""

from __future__ import annotations

from value_investor.dashboard_bridge import (
    ACTION_REPOSITORY_DISPATCH,
    SUPPORTED_ACTIONS,
    DashboardBridgeConfig,
    process_pending_dashboard_commands,
)


def test_supported_actions_map_to_repository_dispatch() -> None:
    assert "progress-report" in SUPPORTED_ACTIONS
    for action in SUPPORTED_ACTIONS:
        assert action in ACTION_REPOSITORY_DISPATCH


def test_process_pending_without_supabase_env(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    result = process_pending_dashboard_commands()
    assert result["ok"] is False
    assert result["reason"] == "supabase_not_configured"


def test_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    cfg = DashboardBridgeConfig.from_env()
    assert cfg is not None
    assert cfg.supabase_url == "https://example.supabase.co"
    assert cfg.github_repo == "owner/repo"
