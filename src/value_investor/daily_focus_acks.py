"""Durable daily-hub acks (focus lines + recommendation accept for local_date)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

ACKS_FILENAME = "daily_focus_acks.json"
DISCUSS_FILENAME = "daily_discuss_inbox.json"
ACK_DECISIONS = frozenset({"ack", "accept", "dismiss", "discuss"})
ACCEPT_DECISIONS = frozenset({"ack", "accept"})


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


def _load_discuss_inbox(data_dir: Path) -> dict[str, Any]:
    path = Path(data_dir) / DISCUSS_FILENAME
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return {"schema_version": 1, "items": []}
    if not isinstance(raw, dict):
        return {"schema_version": 1, "items": []}
    items = [x for x in (raw.get("items") or []) if isinstance(x, dict)]
    return {
        "schema_version": 1,
        "items": items,
        "updated_at": raw.get("updated_at"),
    }


def _lookup_task_enrichment(
    data_dir: Path,
    *,
    task_ref: str,
    recommendation_id: str,
) -> dict[str, Any]:
    """Pull title/work_class/family from current daily_focus when available."""
    path = Path(data_dir) / "daily_focus.json"
    try:
        hub = read_json(path)
    except FileNotFoundError:
        return {}
    if not isinstance(hub, dict):
        return {}
    for task in hub.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        ref = str(task.get("task_ref") or "")
        rid = str(task.get("recommendation_id") or "")
        if task_ref and ref == task_ref:
            return task
        if recommendation_id and rid == recommendation_id:
            return task
    for line in hub.get("focus_lines") or []:
        if not isinstance(line, dict):
            continue
        if task_ref and str(line.get("id") or "") == task_ref:
            return {
                "title": line.get("title"),
                "summary": line.get("summary"),
                "work_class": line.get("work_class") or "dev",
                "task_family": line.get("task_family") or task_ref,
                "tags": line.get("tags") or [],
            }
    return {}


def _had_discuss(
    data_dir: Path,
    *,
    task_ref: str,
    recommendation_id: str,
    local_date: str,
) -> bool:
    inbox = _load_discuss_inbox(data_dir)
    for item in inbox.get("items") or []:
        if str(item.get("local_date") or "") != local_date:
            continue
        rid = str(item.get("recommendation_id") or "")
        tid = str(item.get("task_id") or "")
        if recommendation_id and rid == recommendation_id:
            return True
        if task_ref and tid == task_ref:
            return True
    store = load_daily_focus_acks(data_dir)
    for row in store.get("acks") or []:
        if str(row.get("local_date") or "") != local_date:
            continue
        if str(row.get("decision") or "") != "discuss":
            continue
        ref = str(row.get("task_ref") or row.get("focus_id") or "")
        rid = str(row.get("recommendation_id") or "")
        if task_ref and ref == task_ref:
            return True
        if recommendation_id and rid == recommendation_id:
            return True
    return False


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
    title: str = "",
    summary: str = "",
    work_class: str = "",
    task_family: str = "",
    had_discuss: bool | None = None,
    outcome: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Append or refresh an open daily-hub ack for ``local_date``.

    Phase A enrichment stores title / work_class / outcome so History does not
    need git archaeology.
    """
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

    enrichment = _lookup_task_enrichment(
        data_dir,
        task_ref=task_ref,
        recommendation_id=str(recommendation_id or "").strip(),
    )
    title = str(title or enrichment.get("title") or task_ref).strip()
    summary = str(summary or enrichment.get("summary") or title).strip()
    work_class = str(
        work_class or enrichment.get("work_class") or ("dev" if not task_ref.startswith("human:") else "ops_gate")
    ).strip()
    task_family = str(
        task_family
        or enrichment.get("task_family")
        or (task_ref.split(":", 1)[-1] if ":" in task_ref else task_ref)
    ).strip()
    tag_list = list(tags or enrichment.get("tags") or [])

    discuss_flag = (
        bool(had_discuss)
        if had_discuss is not None
        else _had_discuss(
            data_dir,
            task_ref=task_ref,
            recommendation_id=str(recommendation_id or "").strip(),
            local_date=local_date,
        )
    )
    if outcome:
        resolved_outcome = str(outcome).strip()
    elif decision == "discuss":
        resolved_outcome = "discuss_open"
    elif decision == "dismiss":
        resolved_outcome = "dismissed"
    elif decision in ACCEPT_DECISIONS:
        resolved_outcome = "accept_followed"
    else:
        resolved_outcome = decision

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
        "title": title,
        "summary": summary,
        "work_class": work_class,
        "task_family": task_family,
        "had_discuss": discuss_flag,
        "outcome": resolved_outcome,
        "tags": tag_list,
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
    work_class: str = "",
    task_family: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Append a Discuss item to ``daily_discuss_inbox.json`` for Project pickup."""
    path = Path(data_dir) / DISCUSS_FILENAME
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
    task_id = str(recommendation.get("task_id") or "").strip()
    enrichment = _lookup_task_enrichment(
        data_dir, task_ref=task_id, recommendation_id=rid
    )
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
        "task_id": task_id or enrichment.get("task_ref"),
        "local_date": local_date,
        "status": "open",
        "summary": recommendation.get("summary") or enrichment.get("summary"),
        "title": title or enrichment.get("title") or recommendation.get("summary"),
        "rationale": recommendation.get("rationale"),
        "discuss_prompt": recommendation.get("discuss_prompt"),
        "options": recommendation.get("options") or [],
        "priority": recommendation.get("priority"),
        "accept_action": recommendation.get("accept_action"),
        "work_class": work_class
        or enrichment.get("work_class")
        or ("dev" if not str(task_id).startswith("human:") else "ops_gate"),
        "task_family": task_family
        or enrichment.get("task_family")
        or task_id
        or rid,
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


def resolve_discuss_inbox_item(
    data_dir: Path,
    *,
    recommendation_id: str = "",
    task_id: str = "",
    local_date: str = "",
    resolution_summary: str = "",
    resolved_by: str = "human",
) -> dict[str, Any] | None:
    """Mark a Discuss inbox item resolved (Phase A1 bridge/coordinator write)."""
    path = Path(data_dir) / DISCUSS_FILENAME
    store = _load_discuss_inbox(data_dir)
    items = list(store.get("items") or [])
    target = None
    recommendation_id = str(recommendation_id or "").strip()
    task_id = str(task_id or "").strip()
    local_date = str(local_date or "").strip()
    for item in items:
        if str(item.get("status") or "open") != "open":
            continue
        if local_date and str(item.get("local_date") or "") != local_date:
            continue
        rid = str(item.get("recommendation_id") or "")
        tid = str(item.get("task_id") or "")
        if recommendation_id and rid == recommendation_id:
            target = item
            break
        if task_id and tid == task_id:
            target = item
            break
    if target is None:
        return None
    now = _utcnow()
    target["status"] = "resolved"
    target["resolved_at"] = now
    target["resolved_by"] = resolved_by
    target["resolution_summary"] = str(resolution_summary or "").strip() or (
        "Resolved after Project discuss"
    )
    if not local_date:
        local_date = str(target.get("local_date") or "")
    target["resolved_local_date"] = local_date
    payload = {
        "schema_version": 1,
        "updated_at": now,
        "items": items,
    }
    write_json(path, payload, compact=False)
    return target
