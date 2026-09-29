"""Record daily-hub focus ack / recommendation accept and refresh daily_focus.json."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from value_investor.daily_focus import DEFAULT_TIMEZONE, write_daily_focus
from value_investor.daily_focus_acks import (
    append_discuss_inbox,
    record_daily_focus_ack,
)
from value_investor.ui_state_reconciliation import local_date_for_timezone


def _now_for_local_date(
    local_date: str,
    *,
    timezone: str = DEFAULT_TIMEZONE,
) -> datetime:
    """UTC instant that falls on ``local_date`` in operator TZ (midday local)."""
    year, month, day = (int(part) for part in str(local_date).split("-", 2))
    try:
        tz = ZoneInfo(timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    return datetime(year, month, day, 12, 0, tzinfo=tz).astimezone(UTC)


def run_daily_focus_ack(
    data_dir: Path,
    *,
    task_ref: str = "",
    focus_id: str = "",
    recommendation_id: str = "",
    decision: str = "ack",
    local_date: str = "",
    note: str = "",
    source: str = "dashboard_bridge",
    acked_by: str = "dashboard",
    now: datetime | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    local_date = str(local_date or "").strip() or local_date_for_timezone(now=now)
    ack = record_daily_focus_ack(
        data_dir,
        task_ref=task_ref,
        focus_id=focus_id,
        recommendation_id=recommendation_id,
        decision=decision,
        local_date=local_date,
        note=note,
        source=source,
        acked_by=acked_by,
    )
    # Rebuild against the ack session day so ``closed`` matches the recorded
    # local_date (wall-clock midnight rollover must not leave acked rows open).
    focus_now = now if now is not None else _now_for_local_date(local_date)
    focus = write_daily_focus(data_dir=data_dir, now=focus_now)
    return {
        "ok": True,
        "ack": ack,
        "local_date": local_date,
        "open_task_count": focus.get("open_task_count"),
        "focus_path": str(data_dir / "daily_focus.json"),
        "acks_path": str(data_dir / "daily_focus_acks.json"),
    }


def run_daily_discuss(
    data_dir: Path,
    *,
    recommendation_id: str = "",
    recommendation: dict[str, Any] | None = None,
    local_date: str = "",
    source: str = "dashboard_bridge",
) -> dict[str, Any]:
    """Queue a Discuss item into daily_discuss_inbox.json for Project pickup."""
    data_dir = Path(data_dir)
    local_date = str(local_date or "").strip() or local_date_for_timezone()
    rec = recommendation if isinstance(recommendation, dict) else None
    if rec is None and recommendation_id:
        focus = write_daily_focus(data_dir=data_dir)  # ensure fresh
        for row in focus.get("recommendations") or []:
            if isinstance(row, dict) and str(row.get("id") or "") == recommendation_id:
                rec = row
                break
    if not rec:
        # Minimal stub so Discuss still lands in inbox.
        rec = {
            "id": recommendation_id or "rec-unknown",
            "task_id": None,
            "summary": "Discuss requested from Daily hub (recommendation payload missing).",
            "rationale": "",
            "discuss_prompt": (
                f"Discuss daily recommendation `{recommendation_id or 'rec-unknown'}` "
                "(full payload missing — rebuild daily_focus.json)."
            ),
            "options": [],
            "priority": 99,
        }
    entry = append_discuss_inbox(
        data_dir,
        recommendation=rec,
        local_date=local_date,
        source=source,
    )
    # Also stamp a discuss ack so the hub can show "discuss queued".
    record_daily_focus_ack(
        data_dir,
        task_ref=str(rec.get("task_id") or rec.get("id") or ""),
        recommendation_id=str(rec.get("id") or ""),
        decision="discuss",
        local_date=local_date,
        note="queued for Project discuss",
        source=source,
        acked_by="dashboard",
    )
    return {
        "ok": True,
        "item": entry,
        "inbox_path": str(data_dir / "daily_discuss_inbox.json"),
        "project_pickup": entry.get("project_pickup"),
    }
