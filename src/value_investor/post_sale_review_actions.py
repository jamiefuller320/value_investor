"""Dashboard / CLI actions for post-sale review Accept + Comment.

Observe-only write path into ``docs/data/post_sale_review_labels.json``.
Refreshes ``post_sale_review_queue.json`` after each action.
Never influences fills (``influences_live=false``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.post_sale_review import (
    DEFAULT_DATA_DIR,
    refresh_post_sale_review_queue,
)
from value_investor.post_sale_review_labels import (
    ACTION_KINDS,
    record_accept,
    record_comment,
)


def _snapshot_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "book_id",
        "book_tag",
        "model_id",
        "ticker",
        "entry_at",
        "exit_at",
        "hold_days",
        "exit_kind",
        "return_pct",
        "basis_label",
        "framing",
        "charts",
        "close_in",
        "wider_tf",
        "opened_at",
        "sold_at",
        "avg_cost",
        "exit_price",
        "registration_id",
        "population",
    )
    return {key: payload.get(key) for key in keys if key in payload}


def run_post_sale_review_action(
    data_dir: Path,
    *,
    review_id: str,
    decision: str,
    text: str = "",
    tag_at_action: str = "new",
    source: str = "dashboard_bridge",
    acted_by: str = "dashboard",
    snapshot: dict[str, Any] | None = None,
    refresh_queue: bool = True,
) -> dict[str, Any]:
    """Record Accept or Comment. Comment always spawns a reply stub."""
    review_id = str(review_id or "").strip()
    if not review_id:
        raise ValueError("review_id is required")
    decision = str(decision or "").strip().lower()
    if decision in {"ack", "accept", "match"}:
        decision = "accept"
    elif decision in {"comment", "note"}:
        decision = "comment"
    if decision not in ACTION_KINDS:
        raise ValueError(f"Unknown decision {decision!r}; allowed: accept, comment")

    snap = dict(snapshot) if isinstance(snapshot, dict) else {}
    if decision == "accept":
        event = record_accept(
            data_dir,
            review_id=review_id,
            tag_at_action=tag_at_action,
            note=text,
            source=source,
            acted_by=acted_by,
            snapshot=snap,
        )
    else:
        event = record_comment(
            data_dir,
            review_id=review_id,
            text=text,
            tag_at_action=tag_at_action,
            source=source,
            acted_by=acted_by,
            snapshot=snap,
        )

    queue_path = None
    if refresh_queue:
        queue = refresh_post_sale_review_queue(data_dir=data_dir, persist=True)
        queue_path = queue.get("path")
    return {
        "ok": True,
        "decision": decision,
        "review_id": review_id,
        "event": event,
        "queue_path": queue_path,
        "influences_live": False,
    }


def run_post_sale_review_action_batch(
    data_dir: Path,
    items: list[dict[str, Any]],
    *,
    source: str = "dashboard_bridge",
    acted_by: str = "dashboard",
) -> dict[str, Any]:
    """Apply a batch of Accept/Comment payloads (one GHA workflow)."""
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        review_id = str(raw.get("review_id") or "").strip()
        decision = str(raw.get("decision") or raw.get("action_kind") or "").strip()
        # Map bridge action names onto decisions when decision omitted.
        bridge_action = str(raw.get("bridge_action") or "").strip()
        if not decision:
            if bridge_action.endswith("comment") or "comment" in bridge_action:
                decision = "comment"
            else:
                decision = "accept"
        try:
            result = run_post_sale_review_action(
                data_dir,
                review_id=review_id,
                decision=decision,
                text=str(raw.get("text") or raw.get("note") or raw.get("comment") or ""),
                tag_at_action=str(raw.get("tag") or raw.get("tag_at_action") or "new"),
                source=source,
                acted_by=acted_by,
                snapshot=_snapshot_from_payload(raw),
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
    queue = refresh_post_sale_review_queue(data_dir=data_dir, persist=True)
    return {
        "ok": not errors,
        "recorded": len(results),
        "results": results,
        "errors": errors,
        "queue_path": queue.get("path"),
        "active_count": queue.get("active_count"),
        "influences_live": False,
        "data_dir": str(data_dir or DEFAULT_DATA_DIR),
    }


__all__ = [
    "run_post_sale_review_action",
    "run_post_sale_review_action_batch",
]
