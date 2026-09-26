"""Durable human acks / approvals for checklist tasks on the dashboard.

Acks live in ``docs/data/human_task_acks.json`` so a read/ack survives
checklist republish. Matching is by ``task_id``. A new analysis fingerprint
marks the ack stale so the task rises to the top again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

ACKS_FILENAME = "human_task_acks.json"
ACK_DECISIONS = frozenset({"ack_observe", "approve", "defer"})


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def load_human_task_acks(data_dir: Path) -> dict[str, Any]:
    path = Path(data_dir) / ACKS_FILENAME
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return {"schema_version": 1, "acks": []}
    if not isinstance(raw, dict):
        return {"schema_version": 1, "acks": []}
    acks = [row for row in (raw.get("acks") or []) if isinstance(row, dict)]
    return {"schema_version": 1, "acks": acks, "updated_at": raw.get("updated_at")}


def matching_ack(
    acks: dict[str, Any] | None,
    *,
    task_id: str,
) -> dict[str, Any] | None:
    task_id = str(task_id or "").strip()
    if not task_id:
        return None
    for row in (acks or {}).get("acks") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("task_id") or "").strip() != task_id:
            continue
        if str(row.get("status") or "open") != "open":
            continue
        return row
    return None


def record_human_task_ack(
    data_dir: Path,
    *,
    task_id: str,
    decision: str = "ack_observe",
    note: str = "",
    finding_fingerprint: str = "",
    source: str = "",
    acked_by: str = "human",
) -> dict[str, Any]:
    """Append or refresh an open ack. Returns the stored ack row."""
    task_id = str(task_id or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    decision = str(decision or "ack_observe").strip()
    if decision not in ACK_DECISIONS:
        raise ValueError(f"Unknown ack decision {decision!r}; allowed: {sorted(ACK_DECISIONS)}")
    store = load_human_task_acks(data_dir)
    existing = matching_ack(store, task_id=task_id)
    now = _utcnow()
    row = {
        "task_id": task_id,
        "decision": decision,
        "status": "open",
        "acked_at": now,
        "acked_by": acked_by,
        "note": str(note or "").strip(),
        "finding_fingerprint": str(finding_fingerprint or "").strip(),
        "source": str(source or "").strip(),
    }
    acks = list(store.get("acks") or [])
    if existing:
        acks = [item for item in acks if item is not existing]
    acks.append(row)
    payload = {"schema_version": 1, "updated_at": now, "acks": acks}
    dest = Path(data_dir) / ACKS_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, payload, compact=False)
    row["path"] = str(dest)
    return row


def annotate_task_ack(
    task: dict[str, Any],
    acks: dict[str, Any] | None,
    *,
    fingerprint: str = "",
) -> dict[str, Any]:
    """Attach ack / stale flags for dashboard sort. Never auto-applies work."""
    hit = matching_ack(acks, task_id=str(task.get("id") or ""))
    if not hit:
        return {
            "acked": False,
            "stale": False,
            "acked_at": None,
            "decision": None,
            "finding_fingerprint": None,
        }
    ack_fp = str(hit.get("finding_fingerprint") or "").strip()
    current = str(fingerprint or "").strip()
    stale = bool(current and ack_fp and current != ack_fp)
    return {
        "acked": True,
        "stale": stale,
        "acked_at": hit.get("acked_at"),
        "decision": hit.get("decision"),
        "finding_fingerprint": ack_fp or None,
    }


__all__ = [
    "ACKS_FILENAME",
    "ACK_DECISIONS",
    "annotate_task_ack",
    "load_human_task_acks",
    "matching_ack",
    "record_human_task_ack",
]
