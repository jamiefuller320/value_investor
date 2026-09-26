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
    assert "human-task-ack" in SUPPORTED_ACTIONS
    for action in SUPPORTED_ACTIONS:
        assert action in ACTION_REPOSITORY_DISPATCH


def test_process_pending_without_supabase_env(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    result = process_pending_dashboard_commands()
    assert result["ok"] is False
    assert result["reason"] == "supabase_not_configured"


def test_process_pending_dedupes_lifecycle_ack_aliases(monkeypatch) -> None:
    cfg = DashboardBridgeConfig(
        supabase_url="https://example.supabase.co",
        service_role_key="service-key",
        github_repo="owner/repo",
        github_token="token",
    )
    rows = [
        {
            "id": "a1",
            "action": "lifecycle-experiment-ack",
            "payload": {
                "experiment_id": "graduated_allocation_track",
                "factor_id": "entry_appetite",
            },
            "status": "pending",
        },
        {
            "id": "a2",
            "action": "lifecycle-experiment-ack",
            "payload": {"experiment_id": "graduated_allocation", "factor_id": "starter_fraction"},
            "status": "pending",
        },
        {
            "id": "b1",
            "action": "progress-report",
            "payload": {},
            "status": "pending",
        },
    ]
    updates: list[tuple[str, str]] = []
    dispatches: list[str] = []

    monkeypatch.setattr(
        "value_investor.dashboard_bridge.fetch_pending_commands",
        lambda config, limit=10: rows,
    )

    def _update(config, command_id, *, status, message=None, github_run_url=None):
        updates.append((command_id, status, message))

    def _execute(row, *, config):
        dispatches.append(str(row.get("id")))
        return {
            "action": row.get("action"),
            "event_type": ACTION_REPOSITORY_DISPATCH[str(row.get("action"))],
            "command_id": str(row.get("id")),
        }

    monkeypatch.setattr("value_investor.dashboard_bridge.update_command_status", _update)
    monkeypatch.setattr("value_investor.dashboard_bridge.execute_dashboard_command", _execute)

    result = process_pending_dashboard_commands(config=cfg)
    assert result["ok"] is True
    assert dispatches == ["a1", "b1"]
    skipped = [
        row for row in result["processed"] if row.get("skipped") == "duplicate_lifecycle_ack"
    ]
    assert len(skipped) == 1
    assert skipped[0]["id"] == "a2"


def test_process_pending_dedupes_lifecycle_start_by_experiment(monkeypatch) -> None:
    """Two factor chips → one experiment Start: dispatch once, ack the duplicate."""
    cfg = DashboardBridgeConfig(
        supabase_url="https://example.supabase.co",
        service_role_key="service-key",
        github_repo="owner/repo",
        github_token="token",
    )
    rows = [
        {
            "id": "51806d10",
            "action": "lifecycle-experiment-start",
            "payload": {
                "experiment_id": "entry_dca_overlay",
                "factor_id": "add_cadence",
                "kind": "optional_execute",
                "decision": "start_execute_graduated",
            },
            "status": "pending",
        },
        {
            "id": "a1f1b0c8",
            "action": "lifecycle-experiment-start",
            "payload": {
                "experiment_id": "entry_dca_overlay",
                "factor_id": "entry_kind_tag",
                "kind": "optional_execute",
                "decision": "start_execute_graduated",
            },
            "status": "pending",
        },
    ]
    updates: list[tuple[str, str | None]] = []
    dispatches: list[str] = []

    monkeypatch.setattr(
        "value_investor.dashboard_bridge.fetch_pending_commands",
        lambda config, limit=10: rows,
    )

    def _update(config, command_id, *, status, message=None, github_run_url=None):
        updates.append((command_id, status, message))

    def _execute(row, *, config):
        dispatches.append(str(row.get("id")))
        return {
            "action": row.get("action"),
            "event_type": ACTION_REPOSITORY_DISPATCH[str(row.get("action"))],
            "command_id": str(row.get("id")),
        }

    monkeypatch.setattr("value_investor.dashboard_bridge.update_command_status", _update)
    monkeypatch.setattr("value_investor.dashboard_bridge.execute_dashboard_command", _execute)

    result = process_pending_dashboard_commands(config=cfg)
    assert result["ok"] is True
    assert dispatches == ["51806d10"]
    skipped = [
        row for row in result["processed"] if row.get("skipped") == "duplicate_lifecycle_start"
    ]
    assert len(skipped) == 1
    assert skipped[0]["id"] == "a1f1b0c8"
    assert any(
        command_id == "a1f1b0c8"
        and status == "done"
        and message
        and "duplicate lifecycle-experiment-start" in message
        for command_id, status, message in updates
    )


def test_process_pending_keeps_ack_and_start_separate(monkeypatch) -> None:
    """Ack and Start for the same experiment are different actions — both may dispatch."""
    cfg = DashboardBridgeConfig(
        supabase_url="https://example.supabase.co",
        service_role_key="service-key",
        github_repo="owner/repo",
        github_token="token",
    )
    rows = [
        {
            "id": "ack1",
            "action": "lifecycle-experiment-ack",
            "payload": {"experiment_id": "entry_dca_overlay", "factor_id": "add_cadence"},
            "status": "pending",
        },
        {
            "id": "start1",
            "action": "lifecycle-experiment-start",
            "payload": {"experiment_id": "entry_dca_overlay", "factor_id": "add_cadence"},
            "status": "pending",
        },
    ]
    dispatches: list[str] = []
    monkeypatch.setattr(
        "value_investor.dashboard_bridge.fetch_pending_commands",
        lambda config, limit=10: rows,
    )
    monkeypatch.setattr(
        "value_investor.dashboard_bridge.update_command_status",
        lambda *args, **kwargs: None,
    )

    def _execute(row, *, config):
        dispatches.append(str(row.get("id")))
        return {
            "action": row.get("action"),
            "event_type": ACTION_REPOSITORY_DISPATCH[str(row.get("action"))],
            "command_id": str(row.get("id")),
        }

    monkeypatch.setattr("value_investor.dashboard_bridge.execute_dashboard_command", _execute)
    result = process_pending_dashboard_commands(config=cfg)
    assert result["ok"] is True
    assert dispatches == ["ack1", "start1"]
