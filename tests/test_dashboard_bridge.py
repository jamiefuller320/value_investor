"""Tests for Supabase dashboard bridge helpers."""

from __future__ import annotations

from value_investor.dashboard_bridge import (
    ACTION_REPOSITORY_DISPATCH,
    BATCHABLE_ACK_ACTIONS,
    SUPPORTED_ACTIONS,
    DashboardBridgeConfig,
    commands_from_client_payload,
    complete_dashboard_commands,
    process_pending_dashboard_commands,
)


def test_supported_actions_map_to_repository_dispatch() -> None:
    assert "progress-report" in SUPPORTED_ACTIONS
    assert "human-task-ack" in SUPPORTED_ACTIONS
    assert "daily-focus-ack" in SUPPORTED_ACTIONS
    assert "daily-discuss" in SUPPORTED_ACTIONS
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


def test_process_pending_batches_human_task_acks_and_leaves_processing(monkeypatch) -> None:
    """Burst acks → one dispatch; status stays processing until workflow completes."""
    cfg = DashboardBridgeConfig(
        supabase_url="https://example.supabase.co",
        service_role_key="service-key",
        github_repo="owner/repo",
        github_token="token",
    )
    rows = [
        {
            "id": "h1",
            "action": "human-task-ack",
            "payload": {"task_id": "sunday-a", "decision": "ack_observe"},
            "status": "pending",
        },
        {
            "id": "h2",
            "action": "human-task-ack",
            "payload": {"task_id": "sunday-b", "finding_fingerprint": "abc"},
            "status": "pending",
        },
        {
            "id": "p1",
            "action": "progress-report",
            "payload": {},
            "status": "pending",
        },
    ]
    updates: list[tuple[str, str, str | None]] = []
    batch_dispatches: list[list[str]] = []
    single_dispatches: list[str] = []

    monkeypatch.setattr(
        "value_investor.dashboard_bridge.fetch_pending_commands",
        lambda config, limit=40: rows,
    )

    def _update(config, command_id, *, status, message=None, github_run_url=None):
        updates.append((command_id, status, message))

    def _batch(batch_rows, *, config):
        batch_dispatches.append([str(row.get("id")) for row in batch_rows])
        return {
            "action": "human-task-ack",
            "event_type": "human-task-ack",
            "command_ids": [str(row.get("id")) for row in batch_rows],
            "batch_size": len(batch_rows),
        }

    def _execute(row, *, config):
        single_dispatches.append(str(row.get("id")))
        return {
            "action": row.get("action"),
            "event_type": ACTION_REPOSITORY_DISPATCH[str(row.get("action"))],
            "command_id": str(row.get("id")),
        }

    monkeypatch.setattr("value_investor.dashboard_bridge.update_command_status", _update)
    monkeypatch.setattr("value_investor.dashboard_bridge.execute_batched_ack_commands", _batch)
    monkeypatch.setattr("value_investor.dashboard_bridge.execute_dashboard_command", _execute)

    result = process_pending_dashboard_commands(config=cfg)
    assert result["ok"] is True
    assert batch_dispatches == [["h1", "h2"]]
    assert single_dispatches == ["p1"]
    # Human-task rows must not be marked done at dispatch time.
    terminal = {(cid, status) for cid, status, _msg in updates}
    assert ("h1", "done") not in terminal
    assert ("h2", "done") not in terminal
    assert ("h1", "processing") in terminal
    assert ("h2", "processing") in terminal
    assert ("p1", "done") in terminal
    batched = [row for row in result["processed"] if row.get("batched")]
    assert len(batched) == 2
    assert all(row.get("status") == "processing" for row in batched)


def test_process_pending_batches_each_ack_action_separately(monkeypatch) -> None:
    cfg = DashboardBridgeConfig(
        supabase_url="https://example.supabase.co",
        service_role_key="service-key",
        github_repo="owner/repo",
        github_token="token",
    )
    rows = [
        {
            "id": "d1",
            "action": "daily-focus-ack",
            "payload": {"task_ref": "focus-1", "decision": "ack"},
            "status": "pending",
        },
        {
            "id": "h1",
            "action": "human-task-ack",
            "payload": {"task_id": "sunday-a"},
            "status": "pending",
        },
        {
            "id": "d2",
            "action": "daily-focus-ack",
            "payload": {"task_ref": "focus-2", "decision": "accept"},
            "status": "pending",
        },
    ]
    batch_actions: list[str] = []
    monkeypatch.setattr(
        "value_investor.dashboard_bridge.fetch_pending_commands",
        lambda config, limit=40: rows,
    )
    monkeypatch.setattr(
        "value_investor.dashboard_bridge.update_command_status",
        lambda *args, **kwargs: None,
    )

    def _batch(batch_rows, *, config):
        action = str(batch_rows[0].get("action"))
        batch_actions.append(action)
        return {
            "action": action,
            "event_type": action,
            "command_ids": [str(r.get("id")) for r in batch_rows],
            "batch_size": len(batch_rows),
        }

    monkeypatch.setattr("value_investor.dashboard_bridge.execute_batched_ack_commands", _batch)
    result = process_pending_dashboard_commands(config=cfg)
    assert result["ok"] is True
    assert batch_actions == ["daily-focus-ack", "human-task-ack"]
    assert BATCHABLE_ACK_ACTIONS == {
        "human-task-ack",
        "daily-focus-ack",
        "daily-discuss",
    }


def test_commands_from_client_payload_prefers_batch() -> None:
    payload = {
        "commands": [
            {"command_id": "c1", "task_id": "t1"},
            {"command_id": "c2", "task_id": "t2"},
        ],
        "task_id": "ignored",
    }
    items = commands_from_client_payload(payload)
    assert [row["task_id"] for row in items] == ["t1", "t2"]


def test_commands_from_client_payload_legacy_single() -> None:
    items = commands_from_client_payload(
        {"command_id": "c1", "task_id": "sunday-a", "decision": "ack_observe"}
    )
    assert len(items) == 1
    assert items[0]["task_id"] == "sunday-a"


def test_complete_dashboard_commands(monkeypatch) -> None:
    cfg = DashboardBridgeConfig(
        supabase_url="https://example.supabase.co",
        service_role_key="service-key",
    )
    updates: list[tuple[str, str]] = []

    def _update(config, command_id, *, status, message=None, github_run_url=None):
        updates.append((command_id, status))

    monkeypatch.setattr("value_investor.dashboard_bridge.update_command_status", _update)
    result = complete_dashboard_commands(
        ["a", "b", ""],
        status="done",
        message="ok",
        config=cfg,
    )
    assert result["ok"] is True
    assert result["updated"] == ["a", "b"]
    assert updates == [("a", "done"), ("b", "done")]
