"""Supabase-backed dashboard command bridge — static page → git Actions."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
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
}


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
    limit: int = 10,
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


def process_pending_dashboard_commands(
    *,
    config: DashboardBridgeConfig | None = None,
    limit: int = 10,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Poll Supabase for pending commands and dispatch GitHub repository events."""
    cfg = config or DashboardBridgeConfig.from_env()
    if cfg is None:
        return {"ok": False, "reason": "supabase_not_configured", "processed": []}

    pending = fetch_pending_commands(cfg, limit=limit)
    processed: list[dict[str, Any]] = []
    seen_lifecycle_experiments: set[str] = set()
    for row in pending:
        command_id = str(row.get("id") or "")
        if not command_id:
            continue
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
                continue
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
            continue
        if dedupe_key:
            seen_lifecycle_experiments.add(dedupe_key)
        if dry_run:
            processed.append({"id": command_id, "action": row.get("action"), "dry_run": True})
            continue
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
