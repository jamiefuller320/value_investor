"""Daily hub History session builder — completed development memory + Accept streaks.

Observe-only. Never flips checklist ``automated: true`` (N169). History defaults to
``work_class=dev``; routine ops_gate / surface / routine_auto stay out unless tagged.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json
from value_investor.ui_state_reconciliation import local_date_for_timezone

DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/daily_hub_history.json")
DEFAULT_TIMEZONE = "Europe/London"
SCHEMA_VERSION = 1
RETENTION_DAYS = 90
ACCEPT_STREAK_THRESHOLD = 5
ACCEPT_STREAK_WINDOW_DAYS = 30
ACCEPT_OUTCOMES = frozenset({"ack", "accept", "ack_observe"})
HISTORY_WORK_CLASSES = frozenset({"dev"})
CANDIDATE_WORK_CLASSES = frozenset({"dev", "ops_gate"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_read(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _had_discuss_for(
    *,
    task_ref: str,
    recommendation_id: str,
    local_date: str,
    discuss_items: list[dict[str, Any]],
    acks: list[dict[str, Any]],
) -> bool:
    for item in discuss_items:
        if str(item.get("local_date") or "") != local_date:
            continue
        rid = str(item.get("recommendation_id") or "")
        tid = str(item.get("task_id") or "")
        if recommendation_id and rid == recommendation_id:
            return True
        if task_ref and tid == task_ref:
            return True
    for row in acks:
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


def _work_class_for_ack(row: dict[str, Any]) -> str:
    explicit = str(row.get("work_class") or "").strip()
    if explicit:
        return explicit
    ref = str(row.get("task_ref") or row.get("focus_id") or "")
    if ref.startswith("human:"):
        return "ops_gate"
    if ref.startswith("progress:") or ref.startswith("reconcile:"):
        return "surface"
    if ref.startswith("focus-") or row.get("focus_id"):
        return "dev"
    source = str(row.get("source") or "")
    if "human" in source:
        return "ops_gate"
    return "dev"


def _task_family_for(row: dict[str, Any], *, work_class: str) -> str:
    family = str(row.get("task_family") or "").strip()
    if family:
        return family
    tags = row.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            text = str(tag or "").strip()
            if text and text not in {"project_notes", "p1", "dashboard"}:
                return text
            if text in {"p1", "dashboard"}:
                return text
    ref = str(row.get("task_ref") or row.get("focus_id") or row.get("recommendation_id") or "")
    if ref.startswith("human:"):
        return ref.split(":", 1)[1] or ref
    if ref:
        return ref
    return f"{work_class}:unknown"


def _entry_from_ack(
    row: dict[str, Any],
    *,
    discuss_items: list[dict[str, Any]],
    all_acks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    decision = str(row.get("decision") or "ack")
    if decision not in ACCEPT_OUTCOMES and decision != "dismiss":
        return None
    local_date = str(row.get("local_date") or "").strip()
    if not local_date:
        return None
    task_ref = str(row.get("task_ref") or row.get("focus_id") or "").strip()
    if not task_ref:
        return None
    work_class = _work_class_for_ack(row)
    recommendation_id = str(row.get("recommendation_id") or "").strip()
    had_discuss = bool(row.get("had_discuss")) or _had_discuss_for(
        task_ref=task_ref,
        recommendation_id=recommendation_id,
        local_date=local_date,
        discuss_items=discuss_items,
        acks=all_acks,
    )
    if decision == "dismiss":
        outcome = "dismissed"
    elif had_discuss and decision in ACCEPT_OUTCOMES:
        # Accept after Discuss still records discuss happened; candidacy keys off
        # accept with had_discuss=false. Outcome stays accept_followed when Accept
        # closed the loop; discuss_resolved is used when inbox status is resolved
        # without a plain Accept path.
        outcome = str(row.get("outcome") or "accept_followed")
        if outcome not in {"accept_followed", "discuss_resolved"}:
            outcome = "accept_followed"
    else:
        outcome = str(row.get("outcome") or "accept_followed")
        if decision in ACCEPT_OUTCOMES and outcome not in {
            "accept_followed",
            "discuss_resolved",
        }:
            outcome = "accept_followed"

    eligible = work_class in CANDIDATE_WORK_CLASSES and bool(
        row.get("automation_candidate_eligible", work_class == "dev")
    )
    title = str(row.get("title") or task_ref).strip()
    summary = str(row.get("summary") or title).strip()
    family = _task_family_for(row, work_class=work_class)
    closed_at = str(row.get("acked_at") or row.get("closed_at") or "")
    return {
        "id": f"hist-{local_date}-{task_ref}",
        "local_date": local_date,
        "task_ref": task_ref,
        "task_family": family,
        "work_class": work_class,
        "title": title,
        "summary": summary,
        "recommendation_id": recommendation_id or None,
        "outcome": outcome,
        "had_discuss": had_discuss,
        "closed_at": closed_at,
        "closed_by": str(row.get("acked_by") or row.get("closed_by") or "human"),
        "accept_action_kind": "focus-ack" if not task_ref.startswith("human:") else "human-task-ack",
        "pr_urls": list(row.get("pr_urls") or []),
        "notes_archive_ref": row.get("notes_archive_ref"),
        "automation_signal": {
            "eligible": eligible and outcome == "accept_followed" and not had_discuss,
            "family_accept_streak": 0,
            "family_discuss_count_30d": 0,
        },
    }


def _entry_from_resolved_discuss(item: dict[str, Any]) -> dict[str, Any] | None:
    if str(item.get("status") or "") != "resolved":
        return None
    local_date = str(item.get("local_date") or item.get("resolved_local_date") or "").strip()
    if not local_date:
        return None
    task_ref = str(item.get("task_id") or item.get("task_ref") or "").strip()
    rid = str(item.get("recommendation_id") or "").strip()
    if not task_ref and not rid:
        return None
    if not task_ref:
        task_ref = rid
    work_class = str(item.get("work_class") or "dev").strip() or "dev"
    family = _task_family_for(item, work_class=work_class)
    title = str(item.get("title") or item.get("summary") or task_ref).strip()
    return {
        "id": f"hist-{local_date}-discuss-{rid or task_ref}",
        "local_date": local_date,
        "task_ref": task_ref,
        "task_family": family,
        "work_class": work_class,
        "title": title,
        "summary": str(item.get("resolution_summary") or item.get("summary") or title).strip(),
        "recommendation_id": rid or None,
        "outcome": "discuss_resolved",
        "had_discuss": True,
        "closed_at": str(item.get("resolved_at") or item.get("queued_at") or ""),
        "closed_by": str(item.get("resolved_by") or "human"),
        "accept_action_kind": "discuss-resolve",
        "pr_urls": list(item.get("pr_urls") or []),
        "notes_archive_ref": item.get("notes_archive_ref"),
        "automation_signal": {
            "eligible": False,
            "family_accept_streak": 0,
            "family_discuss_count_30d": 0,
        },
    }


def _rollup_candidates(
    entries: list[dict[str, Any]],
    *,
    as_of: date,
) -> list[dict[str, Any]]:
    window_start = as_of - timedelta(days=ACCEPT_STREAK_WINDOW_DAYS - 1)
    by_family: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        family = str(entry.get("task_family") or "").strip()
        if not family:
            continue
        d = _parse_date(entry.get("local_date"))
        if d is None or d < window_start or d > as_of:
            continue
        by_family.setdefault(family, []).append(entry)

    candidates: list[dict[str, Any]] = []
    for family, rows in sorted(by_family.items()):
        accepts = [
            r
            for r in rows
            if r.get("outcome") == "accept_followed" and not r.get("had_discuss")
        ]
        discusses = [r for r in rows if r.get("had_discuss") or r.get("outcome") == "discuss_resolved"]
        work_class = str(rows[0].get("work_class") or "dev")
        eligible_rows = [
            r
            for r in accepts
            if (r.get("automation_signal") or {}).get("eligible")
            or work_class in HISTORY_WORK_CLASSES
        ]
        if work_class not in CANDIDATE_WORK_CLASSES:
            continue
        streak = len(eligible_rows) if eligible_rows else len(accepts)
        discuss_n = len(discusses)
        if streak >= ACCEPT_STREAK_THRESHOLD and discuss_n == 0:
            candidates.append(
                {
                    "task_family": family,
                    "work_class": work_class,
                    "accept_streak": streak,
                    "discuss_count_30d": discuss_n,
                    "signal": "accept_streak_no_discuss",
                    "suggested_action": "review_for_automated_true_or_builder_step",
                    "revisit_when": (
                        f"After {ACCEPT_STREAK_THRESHOLD} Accepts with no Discuss in "
                        f"{ACCEPT_STREAK_WINDOW_DAYS}d — human checklist audit"
                    ),
                    "auto_fixable": False,
                }
            )
        # Annotate entry streaks for UI.
        for r in rows:
            signal = r.setdefault("automation_signal", {})
            signal["family_accept_streak"] = streak
            signal["family_discuss_count_30d"] = discuss_n
    candidates.sort(key=lambda c: (-int(c.get("accept_streak") or 0), c.get("task_family") or ""))
    return candidates


def build_daily_hub_history(
    *,
    data_dir: Path | None = None,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    retention_days: int = RETENTION_DAYS,
    include_work_classes: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Compose History session payload from acks + resolved discuss items."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    now = now or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    include = frozenset(include_work_classes or HISTORY_WORK_CLASSES)
    as_of = date.fromisoformat(local_date_for_timezone(now=now, timezone=timezone))
    cutoff = as_of - timedelta(days=max(1, int(retention_days)) - 1)

    acks_store = _safe_read(data_dir / "daily_focus_acks.json") or {}
    discuss_store = _safe_read(data_dir / "daily_discuss_inbox.json") or {}
    all_acks = [a for a in (acks_store.get("acks") or []) if isinstance(a, dict)]
    discuss_items = [i for i in (discuss_store.get("items") or []) if isinstance(i, dict)]

    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in all_acks:
        entry = _entry_from_ack(row, discuss_items=discuss_items, all_acks=all_acks)
        if entry is None:
            continue
        d = _parse_date(entry.get("local_date"))
        if d is None or d < cutoff or d > as_of:
            continue
        if entry["work_class"] not in include:
            continue
        if entry["id"] in seen_ids:
            continue
        seen_ids.add(entry["id"])
        entries.append(entry)

    for item in discuss_items:
        entry = _entry_from_resolved_discuss(item)
        if entry is None:
            continue
        d = _parse_date(entry.get("local_date"))
        if d is None or d < cutoff or d > as_of:
            continue
        if entry["work_class"] not in include:
            continue
        # Prefer discuss_resolved over a duplicate accept entry for same id.
        if entry["id"] in seen_ids:
            entries = [e for e in entries if e["id"] != entry["id"]]
        seen_ids.add(entry["id"])
        entries.append(entry)

    candidates = _rollup_candidates(entries, as_of=as_of)

    sessions_map: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        sessions_map.setdefault(str(entry["local_date"]), []).append(entry)

    sessions: list[dict[str, Any]] = []
    for local_date in sorted(sessions_map.keys(), reverse=True):
        day_entries = sorted(
            sessions_map[local_date],
            key=lambda e: (str(e.get("closed_at") or ""), str(e.get("id") or "")),
            reverse=True,
        )
        sessions.append(
            {
                "local_date": local_date,
                "closed_dev_count": sum(1 for e in day_entries if e.get("work_class") == "dev"),
                "accept_followed_count": sum(
                    1 for e in day_entries if e.get("outcome") == "accept_followed"
                ),
                "discuss_resolved_count": sum(
                    1 for e in day_entries if e.get("outcome") == "discuss_resolved"
                ),
                "entries": day_entries,
            }
        )

    week_start = as_of - timedelta(days=6)
    recent = [e for e in entries if (d := _parse_date(e.get("local_date"))) and d >= week_start]
    generated_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": SCHEMA_VERSION,
        "timezone": timezone,
        "generated_at": generated_at,
        "retention_days": int(retention_days),
        "sessions": sessions,
        "automation_candidates": candidates,
        "summary": {
            "sessions_retained": len(sessions),
            "dev_closed_7d": sum(1 for e in recent if e.get("work_class") == "dev"),
            "accept_followed_7d": sum(
                1 for e in recent if e.get("outcome") == "accept_followed"
            ),
            "discuss_resolved_7d": sum(
                1 for e in recent if e.get("outcome") == "discuss_resolved"
            ),
            "candidate_count": len(candidates),
            "accept_streak_threshold": ACCEPT_STREAK_THRESHOLD,
            "accept_streak_window_days": ACCEPT_STREAK_WINDOW_DAYS,
        },
        "filters": {
            "default_work_class": "dev",
            "hide_routine_auto": True,
        },
        "observe_only": True,
        "auto_fixable": False,
    }


def write_daily_hub_history(
    *,
    data_dir: Path | None = None,
    store_path: Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    store_path = Path(store_path or (data_dir / "daily_hub_history.json"))
    payload = build_daily_hub_history(data_dir=data_dir, **kwargs)
    write_json(store_path, payload, compact=False)
    return payload


__all__ = [
    "ACCEPT_STREAK_THRESHOLD",
    "ACCEPT_STREAK_WINDOW_DAYS",
    "DEFAULT_STORE_PATH",
    "build_daily_hub_history",
    "write_daily_hub_history",
]
