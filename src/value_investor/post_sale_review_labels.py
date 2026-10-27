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

from value_investor.post_sale_review_opinion import (
    attach_opinion_fields,
    extend_dialogue_for_comment_reply,
    generate_factory_reply,
)
from value_investor.storage import read_json, write_json

LABELS_FILENAME = "post_sale_review_labels.json"
SCHEMA_VERSION = 1
EVENT_KINDS = frozenset({"accept", "comment", "reply", "duplicate"})
ACTION_KINDS = frozenset({"accept", "comment", "duplicate"})
# Labels that clear an item from the active queue (durable).
CLEARING_ACTION_KINDS = frozenset({"accept", "comment", "duplicate"})

# Legacy stub kept for tests / callers that assert the old ack string.
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


def load_post_sale_review_labels(
    data_dir: Path,
    *,
    filename: str = LABELS_FILENAME,
) -> dict[str, Any]:
    path = Path(data_dir) / str(filename or LABELS_FILENAME)
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return empty_labels_store()
    if not isinstance(raw, dict):
        return empty_labels_store()
    events = [row for row in (raw.get("events") or []) if isinstance(row, dict)]
    actioned = [
        str(item).strip() for item in (raw.get("actioned_review_ids") or []) if str(item).strip()
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


def _write_labels(
    data_dir: Path,
    store: dict[str, Any],
    *,
    filename: str = LABELS_FILENAME,
) -> Path:
    dest = Path(data_dir) / str(filename or LABELS_FILENAME)
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
    return {
        str(item).strip() for item in (store.get("actioned_review_ids") or []) if str(item).strip()
    }


def is_actioned(store: dict[str, Any] | None, review_id: str) -> bool:
    rid = str(review_id or "").strip()
    if not rid or not store:
        return False
    return rid in _actioned_set(store)


def _episode_key_from_snap(snap: dict[str, Any] | None) -> str:
    """Calendar episode_key from a snapshot (prefers explicit field)."""
    if not isinstance(snap, dict):
        return ""
    ep = str(snap.get("episode_key") or "").strip()
    if ep:
        return ep
    book = str(snap.get("book_id") or "").strip()
    if not book:
        # Display tags like N206 → n206 so reconstructed keys match queue items.
        book = str(snap.get("book_tag") or "").strip().lower()
    ticker = str(snap.get("ticker") or "").strip().upper()
    entry_day = str(snap.get("entry_at") or "").strip()[:10]
    exit_day = str(snap.get("exit_at") or "").strip()[:10]
    if book and ticker and entry_day and exit_day:
        return "|".join([book, ticker, entry_day, exit_day])
    return ""


def stamp_episode_key(snap: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure ``episode_key`` is present when identity fields allow it."""
    out = dict(snap) if isinstance(snap, dict) else {}
    if str(out.get("episode_key") or "").strip():
        return out
    ep = _episode_key_from_snap(out)
    if ep:
        out["episode_key"] = ep
    return out


def actioned_episode_keys(store: dict[str, Any] | None) -> set[str]:
    """Episode keys cleared by Accept/Comment/Duplicate (survives review_id jitter).

    ``review_id`` fingerprints full timestamps; board chips sometimes rewrite
    entry/exit seconds so a new fingerprint would re-enter active. Calendar
    ``episode_key`` on the event snapshot keeps the same exit cleared.

    Empty pre-#1189 snapshots are healed from sibling events / reply cards that
    share the same ``review_id`` (or ``parent_review_id``).
    """
    if not store:
        return set()
    identity_by_rid: dict[str, str] = {}
    for row in list(store.get("events") or []) + list(store.get("active_replies") or []):
        if not isinstance(row, dict):
            continue
        snap = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else row
        ep = _episode_key_from_snap(snap if isinstance(snap, dict) else {})
        if not ep:
            continue
        for key_name in ("review_id", "parent_review_id"):
            rid = str(row.get(key_name) or "").strip()
            if rid and rid not in identity_by_rid:
                identity_by_rid[rid] = ep
    out: set[str] = set()
    for row in store.get("events") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip().lower()
        if kind not in CLEARING_ACTION_KINDS:
            continue
        snap = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else {}
        ep = _episode_key_from_snap(snap)
        if not ep:
            rid = str(row.get("review_id") or "").strip()
            ep = identity_by_rid.get(rid, "")
        if ep:
            out.add(ep)
    return out


def _reply_card_usable(row: dict[str, Any]) -> bool:
    """Fail-closed: blank / ``?`` identity cards must not clutter the active queue."""
    ticker = str(row.get("ticker") or "").strip()
    if not ticker or ticker == "?":
        return False
    book = str(row.get("book_tag") or row.get("book_id") or "").strip()
    if book in {"", "?"}:
        return False
    return True


def heal_active_replies_file(
    data_dir: Path,
    *,
    filename: str = LABELS_FILENAME,
) -> dict[str, Any]:
    """Drop ``active_replies`` from the labels sleeve (events history untouched).

    Active queue is **uncommented exits only** — factory replies stay in
    ``events`` (durable history) and must not re-enter the attention list.
    """
    name = str(filename or LABELS_FILENAME)
    store = load_post_sale_review_labels(data_dir, filename=name)
    before = len([row for row in (store.get("active_replies") or []) if isinstance(row, dict)])
    if not before:
        return {"healed": False, "removed": 0, "path": str(Path(data_dir) / name)}
    store["active_replies"] = []
    path = _write_labels(data_dir, store, filename=name)
    return {"healed": True, "removed": before, "path": str(path)}


def prune_active_replies(store: dict[str, Any]) -> int:
    """Drop unusable / duplicate reply cards from ``active_replies``.

    Keeps the newest usable card per ``parent_review_id`` (and per review_id).
    Events history is untouched. Returns number of rows removed.
    """
    rows = [row for row in (store.get("active_replies") or []) if isinstance(row, dict)]
    before = len(rows)
    usable = [row for row in rows if _reply_card_usable(row)]
    by_parent: dict[str, dict[str, Any]] = {}
    orphan_order: list[dict[str, Any]] = []
    for row in usable:
        parent = str(row.get("parent_review_id") or "").strip()
        rid = str(row.get("review_id") or "").strip()
        if not rid:
            continue
        if not parent:
            orphan_order.append(row)
            continue
        prior = by_parent.get(parent)
        if prior is None:
            by_parent[parent] = row
            continue
        # Prefer newer created_at when both usable.
        if str(row.get("created_at") or "") >= str(prior.get("created_at") or ""):
            by_parent[parent] = row
    # Preserve stable-ish order: orphans then parents in first-seen order.
    kept: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in orphan_order + list(by_parent.values()):
        rid = str(row.get("review_id") or "").strip()
        if not rid or rid in seen_ids:
            continue
        seen_ids.add(rid)
        kept.append(row)
    store["active_replies"] = kept
    return before - len(kept)


def _mark_actioned(store: dict[str, Any], review_id: str) -> None:
    rid = str(review_id or "").strip()
    if not rid:
        return
    actioned = list(store.get("actioned_review_ids") or [])
    if rid not in actioned:
        actioned.append(rid)
    store["actioned_review_ids"] = actioned
    # Drop from active replies if this was a reply card OR its parent was cleared.
    store["active_replies"] = [
        row
        for row in (store.get("active_replies") or [])
        if isinstance(row, dict)
        and str(row.get("review_id") or "").strip() != rid
        and str(row.get("parent_review_id") or "").strip() != rid
    ]
    prune_active_replies(store)


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
    filename: str = LABELS_FILENAME,
) -> dict[str, Any]:
    """Accept framing (or a reply). Clears the item from the active queue."""
    review_id = str(review_id or "").strip()
    if not review_id:
        raise ValueError("review_id is required")
    name = str(filename or LABELS_FILENAME)
    store = load_post_sale_review_labels(data_dir, filename=name)
    event_id = str(uuid.uuid4())
    snap = stamp_episode_key(snapshot)
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
        "snapshot": snap,
    }
    events = list(store.get("events") or [])
    events.append(event)
    store["events"] = events
    _mark_actioned(store, review_id)
    path = _write_labels(data_dir, store, filename=name)
    return {**event, "path": str(path), "cleared_from_active": True}


def record_duplicate(
    data_dir: Path,
    *,
    review_id: str,
    tag_at_action: str = "new",
    note: str = "",
    source: str = "",
    acted_by: str = "dashboard",
    snapshot: dict[str, Any] | None = None,
    filename: str = LABELS_FILENAME,
) -> dict[str, Any]:
    """Mark as duplicate pattern (already commented). Clears without a reply card."""
    review_id = str(review_id or "").strip()
    if not review_id:
        raise ValueError("review_id is required")
    name = str(filename or LABELS_FILENAME)
    store = load_post_sale_review_labels(data_dir, filename=name)
    event_id = str(uuid.uuid4())
    text = str(note or "").strip() or (
        "Duplicate pattern — similar episode already commented "
        "(cross-book / repeat). Cleared from active queue."
    )
    snap = stamp_episode_key(snapshot)
    event = {
        "event_id": event_id,
        "review_id": review_id,
        "parent_event_id": None,
        "kind": "duplicate",
        "tag_at_action": str(tag_at_action or "new").strip() or "new",
        "text": text,
        "acted_at": _utcnow(),
        "acted_by": acted_by,
        "source": str(source or "").strip(),
        "influences_live": False,
        "snapshot": snap,
    }
    events = list(store.get("events") or [])
    events.append(event)
    store["events"] = events
    _mark_actioned(store, review_id)
    path = _write_labels(data_dir, store, filename=name)
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
    reply_stub_text: str | None = None,
    allow_llm_reply: bool | None = None,
    llm_complete: Any | None = None,
    filename: str = LABELS_FILENAME,
) -> dict[str, Any]:
    """Comment (missed pattern). Clears active item and spawns a factory reply.

    Reply text prefers LLM when allowed; otherwise contextual deterministic
    (or an explicit ``reply_stub_text`` override for tests).
    """
    review_id = str(review_id or "").strip()
    if not review_id:
        raise ValueError("review_id is required")
    text = str(text or "").strip()
    if not text:
        raise ValueError("comment text is required")
    name = str(filename or LABELS_FILENAME)
    store = load_post_sale_review_labels(data_dir, filename=name)
    event_id = str(uuid.uuid4())
    reply_id = reply_review_id(review_id, event_id)
    snap = stamp_episode_key(snapshot)
    # Ensure opinion fields exist so history / charts can annotate later.
    if snap and not snap.get("llm_opinion"):
        attach_opinion_fields(snap)

    if reply_stub_text is not None:
        reply_payload = {
            "text": str(reply_stub_text).strip() or REPLY_STUB_TEXT,
            "reply_kind": "deterministic_ack",
            "llm_attempted": False,
            "influences_live": False,
        }
    else:
        reply_payload = generate_factory_reply(
            owner_comment=text,
            item=snap,
            llm_complete=llm_complete,
            allow_llm=allow_llm_reply,
        )

    comment_at = _utcnow()
    comment_event = {
        "event_id": event_id,
        "review_id": review_id,
        "parent_event_id": None,
        "kind": "comment",
        "tag_at_action": str(tag_at_action or "new").strip() or "new",
        "text": text,
        "acted_at": comment_at,
        "acted_by": acted_by,
        "source": str(source or "").strip(),
        "influences_live": False,
        "reply_review_id": reply_id,
        "snapshot": snap,
    }
    reply_at = _utcnow()
    reply_event_id = str(uuid.uuid4())
    reply_kind = str(reply_payload.get("reply_kind") or "deterministic_contextual")
    acted_by_factory = "factory_llm" if reply_kind == "llm" else "factory_reply"
    reply_event = {
        "event_id": reply_event_id,
        "review_id": reply_id,
        "parent_event_id": event_id,
        "parent_review_id": review_id,
        "kind": "reply",
        "tag_at_action": "reply",
        "text": str(reply_payload.get("text") or REPLY_STUB_TEXT).strip(),
        "acted_at": reply_at,
        "acted_by": acted_by_factory,
        "source": str(source or "").strip() or "factory_reply",
        "influences_live": False,
        "reply_kind": reply_kind,
        "llm_attempted": bool(reply_payload.get("llm_attempted")),
        "llm_ok": reply_payload.get("llm_ok"),
    }
    if reply_payload.get("llm_error"):
        reply_event["llm_error"] = reply_payload.get("llm_error")

    dialogue = extend_dialogue_for_comment_reply(
        prior_dialogue=snap.get("dialogue") if isinstance(snap.get("dialogue"), list) else None,
        item=snap,
        owner_comment=text,
        reply_text=reply_event["text"],
        reply_kind=reply_kind,
        commented_at=comment_at,
        replied_at=reply_at,
    )
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
        "episode_key": snap.get("episode_key"),
        "charts": snap.get("charts"),
        "close_in": snap.get("close_in"),
        "wider_tf": snap.get("wider_tf"),
        "opened_at": snap.get("opened_at") or snap.get("entry_at"),
        "sold_at": snap.get("sold_at") or snap.get("exit_at"),
        "avg_cost": snap.get("avg_cost"),
        "exit_price": snap.get("exit_price"),
        "buy_decision": snap.get("buy_decision"),
        "sell_decision": snap.get("sell_decision"),
        "buy_reason": snap.get("buy_reason"),
        "sell_reason": snap.get("sell_reason"),
        "decision_reasons_join_ok": snap.get("decision_reasons_join_ok"),
        "llm_opinion": snap.get("llm_opinion"),
        "learning_points": snap.get("learning_points"),
        "chart_annotations": snap.get("chart_annotations"),
        "opinion_source": snap.get("opinion_source"),
        "dialogue": dialogue,
        "reply_text": reply_event["text"],
        "owner_comment": text,
        "reply_kind": reply_kind,
        "influences_live": False,
        "observe_only": True,
        "created_at": reply_event["acted_at"],
    }
    events = list(store.get("events") or [])
    events.extend([comment_event, reply_event])
    store["events"] = events
    _mark_actioned(store, review_id)
    # Active queue = uncommented exits only. Factory reply stays in events
    # history; do not re-queue a reply:* card (that looked like the commented
    # episode bouncing back).
    store["active_replies"] = [
        row
        for row in (store.get("active_replies") or [])
        if isinstance(row, dict)
        and str(row.get("review_id") or "").strip() != reply_id
        and str(row.get("parent_review_id") or "").strip() != review_id
    ]
    prune_active_replies(store)
    path = _write_labels(data_dir, store, filename=name)
    return {
        **comment_event,
        "path": str(path),
        "cleared_from_active": True,
        "reply": reply_card,
        "reply_event": reply_event,
        "reply_queued": False,
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
    "CLEARING_ACTION_KINDS",
    "EVENT_KINDS",
    "LABELS_FILENAME",
    "REPLY_STUB_TEXT",
    "SCHEMA_VERSION",
    "actioned_episode_keys",
    "comments_awaiting_reply",
    "empty_labels_store",
    "is_actioned",
    "load_post_sale_review_labels",
    "heal_active_replies_file",
    "prune_active_replies",
    "record_accept",
    "record_comment",
    "record_duplicate",
    "reply_review_id",
    "stamp_episode_key",
]
