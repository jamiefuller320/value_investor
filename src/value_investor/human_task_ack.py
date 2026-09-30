"""Record dashboard human-task ack / approval (observe-only).

Never auto-applies promotion, cron import, or capital actions — durable
decision record + board refresh only.

Also refreshes Cap C ``daily_focus.json`` so Automation → Daily
``open_task_count`` tracks the durable board (Daily Accept for human cards
routes here, not through ``daily-focus-ack``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.human_task_acks import ACK_DECISIONS, record_human_task_ack
from value_investor.human_task_cards import build_human_tasks_board, write_human_tasks_board


def _refresh_daily_hub_after_board(data_dir: Path) -> dict[str, Any] | None:
    """Rebuild Daily hub from the just-written human_tasks_board.

    Best-effort: hub refresh must not fail a durable observe-ack.
    """
    try:
        from value_investor.daily_focus import write_daily_focus
        from value_investor.daily_hub_history import write_daily_hub_history

        focus = write_daily_focus(data_dir=data_dir)
        try:
            write_daily_hub_history(data_dir=data_dir)
        except Exception:  # noqa: BLE001 — history must not block ack
            pass
        return focus if isinstance(focus, dict) else None
    except Exception:  # noqa: BLE001 — hub must not block ack
        return None


def _resolve_fingerprint(data_dir: Path, task_id: str, finding_fingerprint: str) -> str:
    fingerprint = str(finding_fingerprint or "").strip()
    if fingerprint:
        return fingerprint
    board = build_human_tasks_board(data_dir=data_dir)
    for row in board.get("tasks") or []:
        if str(row.get("id") or "") == task_id:
            analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
            return str(analysis.get("fingerprint") or "")
    return ""


def _live_fingerprint(data_dir: Path, task_id: str) -> str:
    live_board = build_human_tasks_board(data_dir=data_dir)
    for row in live_board.get("tasks") or []:
        if str(row.get("id") or "") != task_id:
            continue
        analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
        return str(analysis.get("fingerprint") or "").strip()
    return ""


def _record_one(
    data_dir: Path,
    *,
    task_id: str,
    decision: str,
    note: str,
    finding_fingerprint: str,
    source: str,
    acked_by: str,
) -> dict[str, Any]:
    fingerprint = _resolve_fingerprint(data_dir, task_id, finding_fingerprint)
    ack = record_human_task_ack(
        data_dir,
        task_id=task_id,
        decision=decision,
        note=note,
        finding_fingerprint=fingerprint,
        source=source,
        acked_by=acked_by,
    )
    # Rebind fingerprint to live analysis before board write so the committed
    # board marks the task acked (not immediately stale) when the UI sent a
    # fingerprint from a lagging published board slice.
    live_fp = _live_fingerprint(data_dir, task_id)
    if live_fp and live_fp != str(ack.get("finding_fingerprint") or "").strip():
        ack = record_human_task_ack(
            data_dir,
            task_id=task_id,
            decision=decision,
            note=note,
            finding_fingerprint=live_fp,
            source=source,
            acked_by=acked_by,
        )
    return ack


def run_human_task_ack(
    data_dir: Path,
    *,
    task_id: str,
    decision: str = "ack_observe",
    note: str = "",
    finding_fingerprint: str = "",
    source: str = "dashboard",
    acked_by: str = "human",
) -> dict[str, Any]:
    task_id = str(task_id or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    decision = str(decision or "ack_observe").strip()
    if decision not in ACK_DECISIONS:
        raise ValueError(f"Unknown decision {decision!r}; allowed: {sorted(ACK_DECISIONS)}")

    ack = _record_one(
        data_dir,
        task_id=task_id,
        decision=decision,
        note=note,
        finding_fingerprint=finding_fingerprint,
        source=source,
        acked_by=acked_by,
    )
    board = write_human_tasks_board(data_dir=data_dir)
    focus = _refresh_daily_hub_after_board(data_dir)
    return {
        "ok": True,
        "ack": ack,
        "board_path": board.get("path"),
        "counts": board.get("counts"),
        "task_id": task_id,
        "decision": decision,
        "daily_focus_open_task_count": (focus or {}).get("open_task_count"),
    }


def run_human_task_ack_batch(
    data_dir: Path,
    items: list[dict[str, Any]],
    *,
    source: str = "dashboard_bridge",
    acked_by: str = "dashboard",
) -> dict[str, Any]:
    """Record many observe-acks then refresh the board + Daily hub once."""
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        task_id = str(raw.get("task_id") or "").strip()
        command_id = str(raw.get("command_id") or "").strip()
        if not task_id:
            errors.append({"command_id": command_id, "error": "task_id is required"})
            continue
        decision = str(raw.get("decision") or "ack_observe").strip() or "ack_observe"
        try:
            if decision not in ACK_DECISIONS:
                raise ValueError(f"Unknown decision {decision!r}")
            ack = _record_one(
                data_dir,
                task_id=task_id,
                decision=decision,
                note=str(raw.get("note") or ""),
                finding_fingerprint=str(raw.get("finding_fingerprint") or ""),
                source=str(raw.get("source") or source),
                acked_by=str(raw.get("acked_by") or acked_by),
            )
            results.append(
                {
                    "ok": True,
                    "task_id": task_id,
                    "command_id": command_id or None,
                    "decision": decision,
                    "ack": ack,
                }
            )
        except Exception as exc:  # noqa: BLE001 — continue remaining acks
            errors.append(
                {
                    "task_id": task_id,
                    "command_id": command_id or None,
                    "error": str(exc),
                }
            )
    board = write_human_tasks_board(data_dir=data_dir)
    focus = _refresh_daily_hub_after_board(data_dir)
    return {
        "ok": not errors,
        "acked": results,
        "errors": errors,
        "counts": board.get("counts"),
        "board_path": board.get("path"),
        "command_ids": [str(row.get("command_id")) for row in results if row.get("command_id")],
        "daily_focus_open_task_count": (focus or {}).get("open_task_count"),
    }


__all__ = ["run_human_task_ack", "run_human_task_ack_batch"]
