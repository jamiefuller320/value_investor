"""Dashboard / CLI actions for entry_blind Accept / Comment / Duplicate.

Observe-only write path into ``docs/data/entry_blind_review_labels.json``.
Refreshes ``entry_blind_review_queue.json`` after each action.
Never influences fills (``influences_live=false``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.entry_blind_review import (
    DEFAULT_DATA_DIR,
    refresh_entry_blind_review_queue,
    strip_outcome_fields,
)
from value_investor.entry_blind_review_labels import (
    ACTION_KINDS,
    load_entry_blind_review_labels,
    record_entry_blind_accept,
    record_entry_blind_comment,
    record_entry_blind_duplicate,
)
from value_investor.storage import read_json

_SNAPSHOT_KEYS = (
    "book_id",
    "book_tag",
    "model_id",
    "ticker",
    "name",
    "entry_at",
    "opened_at",
    "days_since_entry",
    "framing",
    "charts",
    "population",
    "registration_id",
    "buy_decision",
    "buy_reason",
    "decision_reasons_join_ok",
    "entry_news_polarity",
    "entry_reason",
    "entry_detail",
    "llm_opinion",
    "learning_points",
    "chart_annotations",
    "opinion_source",
    "dialogue",
    "family_id",
    "episode_key",
    "stage",
    "parent_review_id",
    "buy_strengths",
    "buy_weaknesses",
    "learning_point_forward",
    "lens_side",
    "outcome_fields_stripped",
)


def _safe_queue(data_dir: Path) -> dict[str, Any] | None:
    path = Path(data_dir) / "entry_blind_review_queue.json"
    try:
        raw = read_json(path)
    except (OSError, FileNotFoundError, ValueError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


def _snapshot_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    merged: dict[str, Any] = dict(nested)
    for key in _SNAPSHOT_KEYS:
        if key in payload and payload[key] is not None:
            merged[key] = payload[key]
    slim = {key: merged[key] for key in _SNAPSHOT_KEYS if key in merged}
    return strip_outcome_fields(slim)


def _identity_ok(snap: dict[str, Any]) -> bool:
    ticker = str(snap.get("ticker") or "").strip()
    book = str(snap.get("book_tag") or snap.get("book_id") or "").strip()
    return bool(ticker and ticker != "?" and book and book != "?")


def _fill_from_row(snap: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    filled = {key: row[key] for key in _SNAPSHOT_KEYS if key in row}
    filled.update({k: v for k, v in snap.items() if v is not None})
    return strip_outcome_fields(filled)


def _resolve_snapshot(
    data_dir: Path,
    review_id: str,
    snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    snap = strip_outcome_fields(dict(snapshot) if isinstance(snapshot, dict) else {})
    if _identity_ok(snap) and str(snap.get("family_id") or snap.get("episode_key") or "").strip():
        return snap
    rid = str(review_id or "").strip()
    queue = _safe_queue(data_dir)
    if queue and rid:
        for row in queue.get("active") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("review_id") or "").strip() != rid:
                continue
            filled = _fill_from_row(snap, row)
            if _identity_ok(filled):
                return filled
    if rid:
        labels = load_entry_blind_review_labels(data_dir)
        for row in labels.get("events") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("review_id") or "").strip() != rid:
                continue
            prior = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else {}
            if not prior:
                continue
            filled = _fill_from_row(snap, prior)
            if _identity_ok(filled):
                return filled
        for row in labels.get("active_replies") or []:
            if not isinstance(row, dict):
                continue
            if (
                str(row.get("review_id") or "").strip() != rid
                and str(row.get("parent_review_id") or "").strip() != rid
            ):
                continue
            filled = _fill_from_row(snap, row)
            if _identity_ok(filled):
                return filled
    return snap


def run_entry_blind_review_action(
    data_dir: Path,
    *,
    review_id: str,
    decision: str,
    text: str = "",
    tag_at_action: str = "new",
    source: str = "dashboard_bridge",
    acted_by: str = "dashboard",
    snapshot: dict[str, Any] | None = None,
    post_hoc_human_geometry: Any | None = None,
    refresh_queue: bool = True,
) -> dict[str, Any]:
    """Record Accept, Comment, or Duplicate on an entry_blind card."""
    review_id = str(review_id or "").strip()
    if not review_id:
        raise ValueError("review_id is required")
    decision = str(decision or "").strip().lower()
    if decision in {"ack", "accept", "match"}:
        decision = "accept"
    elif decision in {"comment", "note"}:
        decision = "comment"
    elif decision in {"duplicate", "dupe", "already_commented"}:
        decision = "duplicate"
    if decision not in ACTION_KINDS:
        raise ValueError(f"Unknown decision {decision!r}; allowed: accept, comment, duplicate")

    snap = _resolve_snapshot(data_dir, review_id, snapshot)
    if decision == "accept":
        event = record_entry_blind_accept(
            data_dir,
            review_id=review_id,
            tag_at_action=tag_at_action,
            note=text,
            source=source,
            acted_by=acted_by,
            snapshot=snap,
        )
    elif decision == "duplicate":
        event = record_entry_blind_duplicate(
            data_dir,
            review_id=review_id,
            tag_at_action=tag_at_action,
            note=text,
            source=source,
            acted_by=acted_by,
            snapshot=snap,
        )
    else:
        event = record_entry_blind_comment(
            data_dir,
            review_id=review_id,
            text=text,
            tag_at_action=tag_at_action,
            source=source,
            acted_by=acted_by,
            snapshot=snap,
            post_hoc_human_geometry=post_hoc_human_geometry,
        )

    queue_path = None
    if refresh_queue:
        queue = refresh_entry_blind_review_queue(data_dir=data_dir, persist=True)
        queue_path = queue.get("path")
    return {
        "ok": True,
        "decision": decision,
        "review_id": review_id,
        "stage": "entry_blind",
        "event": event,
        "queue_path": queue_path,
        "influences_live": False,
    }


def run_entry_blind_review_action_batch(
    data_dir: Path,
    items: list[dict[str, Any]],
    *,
    source: str = "dashboard_bridge",
    acted_by: str = "dashboard",
) -> dict[str, Any]:
    """Apply a batch of Accept/Comment/Duplicate payloads (one GHA workflow)."""
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        review_id = str(raw.get("review_id") or "").strip()
        decision = str(raw.get("decision") or raw.get("action_kind") or "").strip()
        bridge_action = str(raw.get("bridge_action") or "").strip()
        if not decision:
            if bridge_action.endswith("comment") or "comment" in bridge_action:
                decision = "comment"
            elif bridge_action.endswith("duplicate") or "duplicate" in bridge_action:
                decision = "duplicate"
            else:
                decision = "accept"
        try:
            result = run_entry_blind_review_action(
                data_dir,
                review_id=review_id,
                decision=decision,
                text=str(raw.get("text") or raw.get("note") or raw.get("comment") or ""),
                tag_at_action=str(raw.get("tag") or raw.get("tag_at_action") or "new"),
                source=source,
                acted_by=acted_by,
                snapshot=_snapshot_from_payload(raw),
                post_hoc_human_geometry=raw.get("post_hoc_human_geometry"),
                refresh_queue=False,
            )
            results.append(
                {
                    "review_id": review_id,
                    "decision": result["decision"],
                    "command_id": raw.get("command_id"),
                    "ok": True,
                }
            )
        except (ValueError, TypeError, OSError) as exc:
            errors.append(
                {
                    "review_id": review_id,
                    "command_id": raw.get("command_id"),
                    "error": str(exc),
                }
            )
    queue = refresh_entry_blind_review_queue(data_dir=data_dir, persist=True)
    return {
        "ok": not errors,
        "recorded": len(results),
        "results": results,
        "errors": errors,
        "queue_path": queue.get("path"),
        "active_count": queue.get("active_count"),
        "influences_live": False,
        "stage": "entry_blind",
        "data_dir": str(data_dir or DEFAULT_DATA_DIR),
    }


__all__ = [
    "run_entry_blind_review_action",
    "run_entry_blind_review_action_batch",
]
