"""Supabase-backed dashboard command bridge — static page → git Actions."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from value_investor.experiment_acks import canonical_experiment_id

DEFAULT_COMMANDS_TABLE = "dashboard_commands"
DEFAULT_CHANNEL = "ftse-dashboard"
SUPPORTED_ACTIONS = frozenset(
    {
        "progress-report",
        "engineering-queue",
        "ops-monitor",
        "refresh-queue-ui",
        "lifecycle-experiment-ack",
        "lifecycle-experiment-start",
        "human-task-ack",
        "daily-focus-ack",
        "daily-discuss",
    }
)

ACTION_REPOSITORY_DISPATCH: dict[str, str] = {
    "progress-report": "progress-report",
    "engineering-queue": "engineering-queue",
    "ops-monitor": "ops-monitor",
    "refresh-queue-ui": "refresh-queue-ui",
    "lifecycle-experiment-ack": "lifecycle-experiment-ack",
    "lifecycle-experiment-start": "lifecycle-experiment-start",
    "human-task-ack": "human-task-ack",
    "daily-focus-ack": "daily-focus-ack",
    "daily-discuss": "daily-discuss",
}

# Git-writing ack/discuss actions: one repository_dispatch per poll batch.
# GitHub concurrency cancels *pending* siblings even when cancel-in-progress is
# false — burst-dispatching one event per click drops most acks. Batch + leave
# status=processing until the workflow marks done after a successful push.
BATCHABLE_ACK_ACTIONS = frozenset(
    {
        "human-task-ack",
        "daily-focus-ack",
        "daily-discuss",
    }
)

DEFAULT_PROCESS_LIMIT = 40


@dataclass(frozen=True)
class DashboardBridgeConfig:
    supabase_url: str
    service_role_key: str
    commands_table: str = DEFAULT_COMMANDS_TABLE
    github_repo: str | None = None
    github_token: str | None = None

    @classmethod
    def from_env(cls) -> DashboardBridgeConfig | None:
        url = (os.environ.get("SUPABASE_URL") or os.environ.get("FTSE_SUPABASE_URL") or "").strip()
        key = (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("FTSE_SUPABASE_SERVICE_ROLE_KEY")
            or ""
        ).strip()
        if not url or not key:
            return None
        return cls(
            supabase_url=url.rstrip("/"),
            service_role_key=key,
            commands_table=(
                os.environ.get("FTSE_DASHBOARD_COMMANDS_TABLE") or DEFAULT_COMMANDS_TABLE
            ).strip(),
            github_repo=(os.environ.get("GITHUB_REPOSITORY") or "").strip() or None,
            github_token=(
                os.environ.get("WORKFLOW_DISPATCH_PAT")
                or os.environ.get("GITHUB_TOKEN")
                or os.environ.get("GH_TOKEN")
                or ""
            ).strip()
            or None,
        )


def _http_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {detail}") from exc


def fetch_pending_commands(
    config: DashboardBridgeConfig,
    *,
    limit: int = DEFAULT_PROCESS_LIMIT,
) -> list[dict[str, Any]]:
    url = (
        f"{config.supabase_url}/rest/v1/{config.commands_table}"
        f"?status=eq.pending&order=created_at.asc&limit={limit}"
    )
    rows = _http_json(
        method="GET",
        url=url,
        headers={
            "apikey": config.service_role_key,
            "Authorization": f"Bearer {config.service_role_key}",
        },
    )
    return list(rows) if isinstance(rows, list) else []


def update_command_status(
    config: DashboardBridgeConfig,
    command_id: str,
    *,
    status: str,
    message: str | None = None,
    github_run_url: str | None = None,
) -> None:
    url = f"{config.supabase_url}/rest/v1/{config.commands_table}?id=eq.{command_id}"
    payload: dict[str, Any] = {
        "status": status,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if message is not None:
        payload["message"] = message
    if github_run_url is not None:
        payload["github_run_url"] = github_run_url
    _http_json(
        method="PATCH",
        url=url,
        headers={
            "apikey": config.service_role_key,
            "Authorization": f"Bearer {config.service_role_key}",
            "Prefer": "return=minimal",
        },
        body=payload,
    )


def complete_dashboard_commands(
    command_ids: list[str],
    *,
    status: str,
    message: str | None = None,
    github_run_url: str | None = None,
    config: DashboardBridgeConfig | None = None,
) -> dict[str, Any]:
    """Mark one or more command rows done/failed after the git workflow finishes."""
    status = str(status or "").strip()
    if status not in {"done", "failed"}:
        raise ValueError("status must be 'done' or 'failed'")
    cfg = config or DashboardBridgeConfig.from_env()
    if cfg is None:
        return {"ok": False, "reason": "supabase_not_configured", "updated": []}
    updated: list[str] = []
    for raw_id in command_ids:
        command_id = str(raw_id or "").strip()
        if not command_id:
            continue
        update_command_status(
            cfg,
            command_id,
            status=status,
            message=message,
            github_run_url=github_run_url,
        )
        updated.append(command_id)
    return {"ok": True, "status": status, "updated": updated}


def dispatch_repository_event(
    *,
    event_type: str,
    repo: str,
    token: str,
    client_payload: dict[str, Any] | None = None,
) -> None:
    url = f"https://api.github.com/repos/{repo}/dispatches"
    body: dict[str, Any] = {"event_type": event_type}
    if client_payload:
        body["client_payload"] = client_payload
    _http_json(
        method="POST",
        url=url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        body=body,
    )


def _command_payload_item(row: dict[str, Any]) -> dict[str, Any]:
    command_id = str(row.get("id") or "").strip()
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    item = dict(payload)
    item["command_id"] = command_id
    return item


def execute_dashboard_command(
    row: dict[str, Any],
    *,
    config: DashboardBridgeConfig,
) -> dict[str, Any]:
    action = str(row.get("action") or "").strip()
    command_id = str(row.get("id") or "")
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}

    if action not in SUPPORTED_ACTIONS:
        raise ValueError(f"Unsupported dashboard action: {action}")

    repo = config.github_repo
    token = config.github_token
    if not repo or not token:
        raise RuntimeError("GITHUB_REPOSITORY and dispatch token required for dashboard bridge")

    event_type = ACTION_REPOSITORY_DISPATCH[action]
    dispatch_repository_event(
        event_type=event_type,
        repo=repo,
        token=token,
        client_payload={"command_id": command_id, **payload},
    )
    return {"action": action, "event_type": event_type, "command_id": command_id}


def execute_batched_ack_commands(
    rows: list[dict[str, Any]],
    *,
    config: DashboardBridgeConfig,
) -> dict[str, Any]:
    """Dispatch one repository event carrying every pending ack in ``rows``."""
    if not rows:
        raise ValueError("rows required")
    action = str(rows[0].get("action") or "").strip()
    if action not in BATCHABLE_ACK_ACTIONS:
        raise ValueError(f"Action {action!r} is not batchable")
    for row in rows:
        if str(row.get("action") or "").strip() != action:
            raise ValueError("batched rows must share one action")

    repo = config.github_repo
    token = config.github_token
    if not repo or not token:
        raise RuntimeError("GITHUB_REPOSITORY and dispatch token required for dashboard bridge")

    commands = [_command_payload_item(row) for row in rows]
    command_ids = [str(item.get("command_id") or "") for item in commands if item.get("command_id")]
    client_payload: dict[str, Any] = {
        "commands": commands,
        "command_ids": command_ids,
        "batch": True,
        "batch_size": len(commands),
    }
    # Keep legacy single-command fields for workflow_dispatch / older runners.
    if len(commands) == 1:
        for key, value in commands[0].items():
            if key not in client_payload:
                client_payload[key] = value

    event_type = ACTION_REPOSITORY_DISPATCH[action]
    dispatch_repository_event(
        event_type=event_type,
        repo=repo,
        token=token,
        client_payload=client_payload,
    )
    return {
        "action": action,
        "event_type": event_type,
        "command_ids": command_ids,
        "batch_size": len(commands),
    }


def commands_from_client_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize repository_dispatch client_payload into per-command dicts."""
    if not isinstance(payload, dict):
        return []
    commands = payload.get("commands")
    if isinstance(commands, list):
        out = [dict(item) for item in commands if isinstance(item, dict)]
        if out:
            return out
    # Legacy single-command payload (pre-batch) or workflow_dispatch mirror.
    single = {
        key: value
        for key, value in payload.items()
        if key not in {"commands", "command_ids", "batch", "batch_size"}
    }
    if single.get("command_id") or single.get("task_id") or single.get("task_ref") or single.get(
        "recommendation_id"
    ):
        return [single]
    return []


_LIFECYCLE_EXPERIMENT_ACTIONS = frozenset(
    {
        "lifecycle-experiment-ack",
        "lifecycle-experiment-start",
    }
)


def _lifecycle_experiment_dedupe_key(row: dict[str, Any]) -> str | None:
    """Collapse catalog factor chips that share one experiment id.

    Acknowledge and Start both authorize by ``experiment_id`` (not ``factor_id``).
    Parallel clicks on ``add_cadence`` + ``entry_kind_tag`` both carry
    ``entry_dca_overlay`` — dispatch once per action+experiment in a poll batch.
    """
    action = str(row.get("action") or "").strip()
    if action not in _LIFECYCLE_EXPERIMENT_ACTIONS:
        return None
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    experiment_id = canonical_experiment_id(str(payload.get("experiment_id") or ""))
    if not experiment_id:
        return None
    return f"{action}:{experiment_id}"


def _duplicate_lifecycle_skip_meta(action: str) -> tuple[str, str]:
    """Return ``(skipped_code, status_message)`` for a same-experiment duplicate."""
    if action == "lifecycle-experiment-start":
        return (
            "duplicate_lifecycle_start",
            "Skipped duplicate lifecycle-experiment-start (same experiment)",
        )
    return (
        "duplicate_lifecycle_ack",
        "Skipped duplicate lifecycle-experiment-ack (same experiment)",
    )


def _process_single_command(
    row: dict[str, Any],
    *,
    cfg: DashboardBridgeConfig,
    dry_run: bool,
    processed: list[dict[str, Any]],
    seen_lifecycle_experiments: set[str],
) -> None:
    command_id = str(row.get("id") or "")
    if not command_id:
        return
    action = str(row.get("action") or "").strip()
    dedupe_key = _lifecycle_experiment_dedupe_key(row)
    if dedupe_key and dedupe_key in seen_lifecycle_experiments:
        skipped_code, skip_message = _duplicate_lifecycle_skip_meta(action)
        if dry_run:
            processed.append(
                {
                    "id": command_id,
                    "action": action or row.get("action"),
                    "dry_run": True,
                    "skipped": skipped_code,
                }
            )
            return
        update_command_status(
            cfg,
            command_id,
            status="done",
            message=skip_message,
        )
        processed.append(
            {
                "id": command_id,
                "action": action or row.get("action"),
                "status": "done",
                "skipped": skipped_code,
            }
        )
        return
    if dedupe_key:
        seen_lifecycle_experiments.add(dedupe_key)
    if dry_run:
        processed.append({"id": command_id, "action": row.get("action"), "dry_run": True})
        return
    update_command_status(
        cfg, command_id, status="processing", message="Dispatching GitHub event"
    )
    try:
        result = execute_dashboard_command(row, config=cfg)
        update_command_status(
            cfg,
            command_id,
            status="done",
            message=f"Dispatched {result['event_type']}",
        )
        processed.append({"id": command_id, **result, "status": "done"})
    except Exception as exc:  # noqa: BLE001 — record per-command failure
        update_command_status(cfg, command_id, status="failed", message=str(exc))
        processed.append(
            {
                "id": command_id,
                "action": row.get("action"),
                "status": "failed",
                "error": str(exc),
            }
        )


def _process_ack_batch(
    action: str,
    rows: list[dict[str, Any]],
    *,
    cfg: DashboardBridgeConfig,
    dry_run: bool,
    processed: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    command_ids = [str(row.get("id") or "") for row in rows if row.get("id")]
    if dry_run:
        for command_id in command_ids:
            processed.append(
                {
                    "id": command_id,
                    "action": action,
                    "dry_run": True,
                    "batched": True,
                }
            )
        return

    for command_id in command_ids:
        update_command_status(
            cfg,
            command_id,
            status="processing",
            message=f"Batched {action} dispatch ({len(command_ids)} commands)",
        )
    try:
        result = execute_batched_ack_commands(rows, config=cfg)
        # Stay in processing until the workflow push succeeds and calls
        # complete_dashboard_commands(..., status="done").
        for command_id in command_ids:
            update_command_status(
                cfg,
                command_id,
                status="processing",
                message=(
                    f"Dispatched batched {result['event_type']} "
                    f"({result['batch_size']} commands); awaiting workflow"
                ),
            )
            processed.append(
                {
                    "id": command_id,
                    "action": action,
                    "event_type": result["event_type"],
                    "status": "processing",
                    "batched": True,
                    "batch_size": result["batch_size"],
                }
            )
    except Exception as exc:  # noqa: BLE001 — fail the whole batch
        for command_id in command_ids:
            update_command_status(cfg, command_id, status="failed", message=str(exc))
            processed.append(
                {
                    "id": command_id,
                    "action": action,
                    "status": "failed",
                    "error": str(exc),
                    "batched": True,
                }
            )


def process_pending_dashboard_commands(
    *,
    config: DashboardBridgeConfig | None = None,
    limit: int = DEFAULT_PROCESS_LIMIT,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Poll Supabase for pending commands and dispatch GitHub repository events."""
    cfg = config or DashboardBridgeConfig.from_env()
    if cfg is None:
        return {"ok": False, "reason": "supabase_not_configured", "processed": []}

    pending = fetch_pending_commands(cfg, limit=limit)
    processed: list[dict[str, Any]] = []
    seen_lifecycle_experiments: set[str] = set()
    batch_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    singles: list[dict[str, Any]] = []

    for row in pending:
        action = str(row.get("action") or "").strip()
        if action in BATCHABLE_ACK_ACTIONS:
            batch_groups[action].append(row)
        else:
            singles.append(row)

    # Preserve roughly created_at order: emit batch groups in first-seen order,
    # interleaved with singles by walking the original pending list.
    emitted_batches: set[str] = set()
    for row in pending:
        action = str(row.get("action") or "").strip()
        if action in BATCHABLE_ACK_ACTIONS:
            if action in emitted_batches:
                continue
            emitted_batches.add(action)
            _process_ack_batch(
                action,
                batch_groups[action],
                cfg=cfg,
                dry_run=dry_run,
                processed=processed,
            )
        else:
            _process_single_command(
                row,
                cfg=cfg,
                dry_run=dry_run,
                processed=processed,
                seen_lifecycle_experiments=seen_lifecycle_experiments,
            )

    return {"ok": True, "processed": processed, "pending_count": len(pending)}


def broadcast_dashboard_update(
    *,
    event: str,
    payload: dict[str, Any],
    config: DashboardBridgeConfig | None = None,
) -> dict[str, Any]:
    """Optional Realtime broadcast after CI refreshes dashboard artifacts."""
    cfg = config or DashboardBridgeConfig.from_env()
    if cfg is None:
        return {"ok": False, "reason": "supabase_not_configured"}
    channel = (os.environ.get("FTSE_DASHBOARD_CHANNEL") or DEFAULT_CHANNEL).strip()
    url = f"{cfg.supabase_url}/realtime/v1/api/broadcast"
    body = {
        "messages": [
            {
                "topic": f"realtime:{channel}",
                "event": event,
                "payload": payload,
            }
        ]
    }
    _http_json(
        method="POST",
        url=url,
        headers={
            "apikey": cfg.service_role_key,
            "Authorization": f"Bearer {cfg.service_role_key}",
        },
        body=body,
    )
    return {"ok": True, "channel": channel, "event": event}


def new_command_id() -> str:
    return str(uuid.uuid4())
