"""Durable daily-hub acks (focus lines + recommendation accept for local_date)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

ACKS_FILENAME = "daily_focus_acks.json"
ACK_DECISIONS = frozenset({"ack", "accept", "dismiss", "discuss"})


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def load_daily_focus_acks(data_dir: Path) -> dict[str, Any]:
    path = Path(data_dir) / ACKS_FILENAME
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return {"schema_version": 1, "acks": []}
    if not isinstance(raw, dict):
        return {"schema_version": 1, "acks": []}
    acks = [row for row in (raw.get("acks") or []) if isinstance(row, dict)]
    return {
        "schema_version": 1,
        "acks": acks,
        "updated_at": raw.get("updated_at"),
    }


def record_daily_focus_ack(
    data_dir: Path,
    *,
    task_ref: str = "",
    focus_id: str = "",
    recommendation_id: str = "",
    decision: str = "ack",
    local_date: str = "",
    note: str = "",
    source: str = "",
    acked_by: str = "human",
) -> dict[str, Any]:
    """Append or refresh an open daily-hub ack for ``local_date``."""
    task_ref = str(task_ref or focus_id or "").strip()
    focus_id = str(focus_id or "").strip()
    if not task_ref and not focus_id:
        raise ValueError("task_ref or focus_id is required")
    if not task_ref:
        task_ref = focus_id
    decision = str(decision or "ack").strip()
    if decision not in ACK_DECISIONS:
        raise ValueError(f"Unknown decision {decision!r}; allowed: {sorted(ACK_DECISIONS)}")
    local_date = str(local_date or "").strip()
    if not local_date:
        from value_investor.ui_state_reconciliation import local_date_for_timezone

        local_date = local_date_for_timezone()

    store = load_daily_focus_acks(data_dir)
    now = _utcnow()
    existing = None
    for row in store.get("acks") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "open") != "open":
            continue
        if str(row.get("local_date") or "") != local_date:
            continue
        ref = str(row.get("task_ref") or row.get("focus_id") or "")
        if ref == task_ref:
            existing = row
            break

    row = {
        "task_ref": task_ref,
        "focus_id": focus_id or task_ref,
        "recommendation_id": str(recommendation_id or "").strip() or None,
        "decision": decision,
        "status": "open",
        "local_date": local_date,
        "acked_at": now,
        "acked_by": acked_by,
        "note": str(note or "").strip(),
        "source": str(source or "").strip(),
    }
    acks = [a for a in (store.get("acks") or []) if a is not existing]
    acks.append(row)
    payload = {
        "schema_version": 1,
        "updated_at": now,
        "acks": acks,
    }
    write_json(Path(data_dir) / ACKS_FILENAME, payload, compact=False)
    return row


def append_discuss_inbox(
    data_dir: Path,
    *,
    recommendation: dict[str, Any],
    local_date: str = "",
    source: str = "dashboard",
) -> dict[str, Any]:
    """Append a Discuss item to ``daily_discuss_inbox.json`` for Project pickup."""
    path = Path(data_dir) / "daily_discuss_inbox.json"
    try:
        raw = read_json(path)
    except FileNotFoundError:
        raw = {"schema_version": 1, "items": []}
    if not isinstance(raw, dict):
        raw = {"schema_version": 1, "items": []}
    items = [x for x in (raw.get("items") or []) if isinstance(x, dict)]
    local_date = str(local_date or "").strip()
    if not local_date:
        from value_investor.ui_state_reconciliation import local_date_for_timezone

        local_date = local_date_for_timezone()
    rid = str(recommendation.get("id") or "").strip()
    # Dedupe open items by recommendation id + local_date.
    items = [
        x
        for x in items
        if not (
            str(x.get("recommendation_id") or "") == rid
            and str(x.get("local_date") or "") == local_date
            and str(x.get("status") or "open") == "open"
        )
    ]
    now = _utcnow()
    entry = {
        "recommendation_id": rid,
        "task_id": recommendation.get("task_id"),
        "local_date": local_date,
        "status": "open",
        "summary": recommendation.get("summary"),
        "rationale": recommendation.get("rationale"),
        "discuss_prompt": recommendation.get("discuss_prompt"),
        "options": recommendation.get("options") or [],
        "priority": recommendation.get("priority"),
        "accept_action": recommendation.get("accept_action"),
        "queued_at": now,
        "source": source,
        "project_pickup": (
            f"In Project chat (bc-01a0d034-3cd4-71bc-88ad-5088afa3424a) say: "
            f"discuss daily recommendation `{rid}`"
        ),
    }
    items.append(entry)
    # Keep last 50
    payload = {
        "schema_version": 1,
        "updated_at": now,
        "items": items[-50:],
    }
    write_json(path, payload, compact=False)
    return entry
