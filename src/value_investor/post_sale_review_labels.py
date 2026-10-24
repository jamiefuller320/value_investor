"""Durable Accept / Comment / reply labels for the post-sale review queue.

Observe / alignment only. Never influences fills, knobs, or live capital
(``influences_live=false``). Package M attention — not Package L auto-tune.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

LABELS_FILENAME = "post_sale_review_labels.json"
SCHEMA_VERSION = 1
EVENT_KINDS = frozenset({"accept", "comment", "reply"})
ACTION_KINDS = frozenset({"accept", "comment"})

# Deterministic factory ack when owner Comments (LLM prose optional later).
REPLY_STUB_TEXT = (
    "Acknowledged. Owner comment recorded for the development loop "
    "(observe / alignment only). No knobs or fills applied "
    "(influences_live=false; Package M — not Package L auto-tune)."
)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def empty_labels_store() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": None,
        "influences_live": False,
        "observe_only": True,
        "package": "M",
        "events": [],
        "actioned_review_ids": [],
        "active_replies": [],
    }


def load_post_sale_review_labels(data_dir: Path) -> dict[str, Any]:
    path = Path(data_dir) / LABELS_FILENAME
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return empty_labels_store()
    if not isinstance(raw, dict):
        return empty_labels_store()
    events = [row for row in (raw.get("events") or []) if isinstance(row, dict)]
    actioned = [
        str(item).strip()
        for item in (raw.get("actioned_review_ids") or [])
        if str(item).strip()
    ]
    replies = [row for row in (raw.get("active_replies") or []) if isinstance(row, dict)]
    return {
        "schema_version": int(raw.get("schema_version") or SCHEMA_VERSION),
        "updated_at": raw.get("updated_at"),
        "influences_live": False,
        "observe_only": True,
        "package": "M",
        "events": events,
        "actioned_review_ids": actioned,
        "active_replies": replies,
    }


def _write_labels(data_dir: Path, store: dict[str, Any]) -> Path:
    dest = Path(data_dir) / LABELS_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(store)
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _utcnow()
    payload["influences_live"] = False
    payload["observe_only"] = True
    payload["package"] = "M"
    write_json(dest, payload, compact=False)
    return dest


def _actioned_set(store: dict[str, Any]) -> set[str]:
    return {str(item).strip() for item in (store.get("actioned_review_ids") or []) if str(item).strip()}


def is_actioned(store: dict[str, Any] | None, review_id: str) -> bool:
    rid = str(review_id or "").strip()
    if not rid or not store:
        return False
    return rid in _actioned_set(store)


def _mark_actioned(store: dict[str, Any], review_id: str) -> None:
    rid = str(review_id or "").strip()
    if not rid:
        return
    actioned = list(store.get("actioned_review_ids") or [])
    if rid not in actioned:
        actioned.append(rid)
    store["actioned_review_ids"] = actioned
    # Drop from active replies if this was a reply card.
    store["active_replies"] = [
        row
        for row in (store.get("active_replies") or [])
        if isinstance(row, dict) and str(row.get("review_id") or "").strip() != rid
    ]


def reply_review_id(parent_review_id: str, event_id: str) -> str:
    digest = hashlib.sha256(f"{parent_review_id}|{event_id}".encode()).hexdigest()[:16]
    return f"reply:{digest}"


def record_accept(
    data_dir: Path,
    *,
    review_id: str,
    tag_at_action: str = "new",
    note: str = "",
    source: str = "",
    acted_by: str = "dashboard",
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept framing (or a reply). Clears the item from the active queue."""
    review_id = str(review_id or "").strip()
    if not review_id:
        raise ValueError("review_id is required")
    store = load_post_sale_review_labels(data_dir)
    event_id = str(uuid.uuid4())
    event = {
        "event_id": event_id,
        "review_id": review_id,
        "parent_event_id": None,
        "kind": "accept",
        "tag_at_action": str(tag_at_action or "new").strip() or "new",
        "text": str(note or "").strip(),
        "acted_at": _utcnow(),
        "acted_by": acted_by,
        "source": str(source or "").strip(),
        "influences_live": False,
        "snapshot": dict(snapshot) if isinstance(snapshot, dict) else {},
    }
    events = list(store.get("events") or [])
    events.append(event)
    store["events"] = events
    _mark_actioned(store, review_id)
    path = _write_labels(data_dir, store)
    return {**event, "path": str(path), "cleared_from_active": True}


def record_comment(
    data_dir: Path,
    *,
    review_id: str,
    text: str,
    tag_at_action: str = "new",
    source: str = "",
    acted_by: str = "dashboard",
    snapshot: dict[str, Any] | None = None,
    reply_stub_text: str = REPLY_STUB_TEXT,
) -> dict[str, Any]:
    """Comment (missed pattern). Clears active item and spawns a reply stub."""
    review_id = str(review_id or "").strip()
    if not review_id:
        raise ValueError("review_id is required")
    text = str(text or "").strip()
    if not text:
        raise ValueError("comment text is required")
    store = load_post_sale_review_labels(data_dir)
    event_id = str(uuid.uuid4())
    reply_id = reply_review_id(review_id, event_id)
    comment_event = {
        "event_id": event_id,
        "review_id": review_id,
        "parent_event_id": None,
        "kind": "comment",
        "tag_at_action": str(tag_at_action or "new").strip() or "new",
        "text": text,
        "acted_at": _utcnow(),
        "acted_by": acted_by,
        "source": str(source or "").strip(),
        "influences_live": False,
        "reply_review_id": reply_id,
        "snapshot": dict(snapshot) if isinstance(snapshot, dict) else {},
    }
    reply_event_id = str(uuid.uuid4())
    reply_event = {
        "event_id": reply_event_id,
        "review_id": reply_id,
        "parent_event_id": event_id,
        "parent_review_id": review_id,
        "kind": "reply",
        "tag_at_action": "reply",
        "text": str(reply_stub_text or REPLY_STUB_TEXT).strip(),
        "acted_at": _utcnow(),
        "acted_by": "factory_stub",
        "source": str(source or "").strip() or "factory_reply_stub",
        "influences_live": False,
        "reply_kind": "deterministic_ack",
    }
    snap = dict(snapshot) if isinstance(snapshot, dict) else {}
    reply_card = {
        "review_id": reply_id,
        "parent_review_id": review_id,
        "parent_event_id": event_id,
        "tag": "reply",
        "book_id": snap.get("book_id"),
        "book_tag": snap.get("book_tag"),
        "model_id": snap.get("model_id"),
        "ticker": snap.get("ticker"),
        "entry_at": snap.get("entry_at"),
        "exit_at": snap.get("exit_at"),
        "hold_days": snap.get("hold_days"),
        "exit_kind": snap.get("exit_kind"),
        "return_pct": snap.get("return_pct"),
        "basis_label": snap.get("basis_label"),
        "framing": snap.get("framing"),
        "charts": snap.get("charts"),
        "close_in": snap.get("close_in"),
        "wider_tf": snap.get("wider_tf"),
        "opened_at": snap.get("opened_at") or snap.get("entry_at"),
        "sold_at": snap.get("sold_at") or snap.get("exit_at"),
        "avg_cost": snap.get("avg_cost"),
        "exit_price": snap.get("exit_price"),
        "reply_text": reply_event["text"],
        "owner_comment": text,
        "influences_live": False,
        "observe_only": True,
        "created_at": reply_event["acted_at"],
    }
    events = list(store.get("events") or [])
    events.extend([comment_event, reply_event])
    store["events"] = events
    _mark_actioned(store, review_id)
    replies = [
        row
        for row in (store.get("active_replies") or [])
        if isinstance(row, dict) and str(row.get("review_id") or "").strip() != reply_id
    ]
    replies.append(reply_card)
    store["active_replies"] = replies
    path = _write_labels(data_dir, store)
    return {
        **comment_event,
        "path": str(path),
        "cleared_from_active": True,
        "reply": reply_card,
        "reply_event": reply_event,
    }


def comments_awaiting_reply(store: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Comments that never received a factory reply event (should be empty with stub)."""
    if not store:
        return []
    events = [row for row in (store.get("events") or []) if isinstance(row, dict)]
    replied_parents = {
        str(row.get("parent_event_id") or "").strip()
        for row in events
        if str(row.get("kind") or "") == "reply" and str(row.get("parent_event_id") or "").strip()
    }
    out: list[dict[str, Any]] = []
    for row in events:
        if str(row.get("kind") or "") != "comment":
            continue
        eid = str(row.get("event_id") or "").strip()
        if eid and eid not in replied_parents:
            out.append(row)
    return out


__all__ = [
    "ACTION_KINDS",
    "EVENT_KINDS",
    "LABELS_FILENAME",
    "REPLY_STUB_TEXT",
    "SCHEMA_VERSION",
    "comments_awaiting_reply",
    "empty_labels_store",
    "is_actioned",
    "load_post_sale_review_labels",
    "record_accept",
    "record_comment",
    "reply_review_id",
]
