"""Record dashboard human-task ack / approval (observe-only).

Never auto-applies promotion, cron import, or capital actions — durable
decision record + board refresh only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.human_task_acks import ACK_DECISIONS, record_human_task_ack
from value_investor.human_task_cards import build_human_tasks_board, write_human_tasks_board


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

    # Prefer fingerprint from live board when caller omitted it
    fingerprint = str(finding_fingerprint or "").strip()
    if not fingerprint:
        board = build_human_tasks_board(data_dir=data_dir)
        for row in board.get("tasks") or []:
            if str(row.get("id") or "") == task_id:
                analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
                fingerprint = str(analysis.get("fingerprint") or "")
                break

    ack = record_human_task_ack(
        data_dir,
        task_id=task_id,
        decision=decision,
        note=note,
        finding_fingerprint=fingerprint,
        source=source,
        acked_by=acked_by,
    )
    board = write_human_tasks_board(data_dir=data_dir)
    return {
        "ok": True,
        "ack": ack,
        "board_path": board.get("path"),
        "counts": board.get("counts"),
        "task_id": task_id,
        "decision": decision,
    }


__all__ = ["run_human_task_ack"]
