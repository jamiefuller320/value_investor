"""Daily focus hub builder — collated morning task board (Cap C).

Composes Project focus lines, market-warning triage (deepen/dismiss/park),
human-task open buckets, progress actionable items, and UI reconciliation
ambers into ``docs/data/daily_focus.json``.
Operator timezone: Europe/London. Refresh target: before 04:00 local.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from value_investor.storage import read_json, write_json
from value_investor.ui_state_reconciliation import (
    local_date_for_timezone,
)

DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/daily_focus.json")
DEFAULT_SEED_PATH = Path("docs/data/project_daily_seed.json")
DEFAULT_TIMEZONE = "Europe/London"
REFRESH_DEADLINE_LOCAL = "04:00"
SCHEMA_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _safe_read(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _stable_id(*parts: str) -> str:
    raw = "|".join(str(p or "").strip() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _content_fingerprint(parts: dict[str, Any]) -> str:
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


_NEXT_RE = re.compile(r"^\s*(?:-\s*)?(?:\*\*)?Next:\s*(?:\*\*)?\s*(.+?)\s*$", re.IGNORECASE)
_WAITING_RE = re.compile(
    r"^\s*(?:-\s*)?(?:\*\*)?Waiting on:\s*(?:\*\*)?\s*(.+?)\s*$",
    re.IGNORECASE,
)
_TODAY_RE = re.compile(
    r"^\s*(?:-\s*(?:\[[ xX]\]\s*)?)?(?:\*\*)?Today\s*[—–-]\s*(?:\*\*)?\s*(.+?)\s*$",
    re.IGNORECASE,
)


def parse_status_conventions(
    *,
    title: str = "",
    summary: str = "",
    notes_block: str = "",
    seed_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse ``Next:`` / ``Waiting on:`` conventions into a status block.

    Seed structured fields win over prose. Empty input yields a soft proposed
    status so Phase 1 clients ignore unknowns safely.
    """
    seed_row = seed_row or {}
    next_steps: list[str] = []
    waiting_on: list[dict[str, Any]] = []

    seed_next = seed_row.get("next_steps")
    if isinstance(seed_next, list):
        next_steps.extend(str(x).strip() for x in seed_next if str(x).strip())
    elif isinstance(seed_next, str) and seed_next.strip():
        next_steps.append(seed_next.strip())

    seed_waiting = seed_row.get("waiting_on")
    if isinstance(seed_waiting, list):
        for item in seed_waiting:
            if isinstance(item, dict):
                waiting_on.append(
                    {
                        "kind": str(item.get("kind") or "external"),
                        "ref": item.get("ref"),
                        "detail": str(item.get("detail") or item.get("text") or "").strip(),
                    }
                )
            elif str(item).strip():
                waiting_on.append({"kind": "external", "ref": None, "detail": str(item).strip()})
    elif isinstance(seed_waiting, str) and seed_waiting.strip():
        waiting_on.append({"kind": "external", "ref": None, "detail": seed_waiting.strip()})

    prose_bits = [notes_block or "", summary or "", title or ""]
    for block in prose_bits:
        for raw in str(block).splitlines():
            line = raw.strip()
            m_next = _NEXT_RE.match(line)
            if m_next:
                text = m_next.group(1).strip()
                if text and text not in next_steps:
                    next_steps.append(text)
                continue
            m_wait = _WAITING_RE.match(line)
            if m_wait:
                text = m_wait.group(1).strip()
                if text and not any(w.get("detail") == text for w in waiting_on):
                    waiting_on.append({"kind": "external", "ref": None, "detail": text})

    # Also split inline "Next:" / "Waiting on:" inside a single summary line.
    for blob in (summary, title):
        text = str(blob or "")
        if "Next:" in text and not next_steps:
            after = text.split("Next:", 1)[1]
            cut = re.split(r"\s+Waiting on:", after, maxsplit=1, flags=re.IGNORECASE)[0]
            bit = cut.strip(" .;")
            if bit:
                next_steps.append(bit)
        if re.search(r"Waiting on:", text, re.IGNORECASE) and not waiting_on:
            after = re.split(r"Waiting on:", text, maxsplit=1, flags=re.IGNORECASE)[1]
            cut = re.split(r"\s+Next:", after, maxsplit=1, flags=re.IGNORECASE)[0]
            bit = cut.strip(" .;")
            if bit:
                waiting_on.append({"kind": "external", "ref": None, "detail": bit})

    seed_status = seed_row.get("status") if isinstance(seed_row.get("status"), dict) else {}
    state = str(seed_status.get("state") or "").strip()
    if not state:
        if waiting_on:
            state = "waiting"
        elif next_steps:
            state = "in_progress"
        else:
            state = "proposed"

    ready = bool(seed_status.get("ready")) if "ready" in seed_status else False
    # ready derivation applied by caller once recommendation presence is known.
    label = str(seed_status.get("label") or "").strip()
    if not label:
        if state == "waiting" and waiting_on:
            label = f"Waiting on {waiting_on[0].get('detail') or 'blocker'}"
        elif state == "ready":
            label = "Ready to progress"
        elif next_steps:
            label = next_steps[0]
        else:
            label = state.replace("_", " ").title()

    return {
        "state": state,
        "label": label,
        "next_steps": next_steps[:3],
        "waiting_on": waiting_on[:5],
        "ready": ready,
        "ready_reason": seed_status.get("ready_reason"),
        "blocked_reason": seed_status.get("blocked_reason")
        or (waiting_on[0]["detail"] if waiting_on else None),
        "updated_at": seed_status.get("updated_at"),
        "updated_by": seed_status.get("updated_by") or "morning_builder",
    }


def derive_ready_status(
    status: dict[str, Any],
    *,
    recommendation_present: bool,
    closed: bool,
) -> dict[str, Any]:
    """Apply Phase A ready derivation onto a status block."""
    out = dict(status)
    waiting = out.get("waiting_on") or []
    state = str(out.get("state") or "proposed")
    ready = (
        bool(recommendation_present)
        and not waiting
        and state in {"proposed", "ready"}
        and not closed
    )
    out["ready"] = ready
    if ready:
        out["state"] = "ready"
        out["label"] = out.get("label") or "Ready to progress"
        out["ready_reason"] = out.get("ready_reason") or "proposal present · no blockers"
        out["blocked_reason"] = None
    elif waiting and state in {"proposed", "ready", "in_progress"}:
        out["state"] = "waiting"
    return out


def work_class_for_source(source: str, *, tags: list[str] | None = None) -> str:
    tags = [str(t) for t in (tags or [])]
    for tag in tags:
        if tag.startswith("work_class:"):
            return tag.split(":", 1)[1] or "dev"
    if "ops_gate" in tags:
        return "ops_gate"
    source = str(source or "")
    if source in {"daily_focus", "project_notes", "project_notes_sync"}:
        return "dev"
    if source == "human_tasks":
        return "ops_gate"
    if source in {"progress_actionable", "ui_reconcile", "market_warning_triage"}:
        return "surface"
    return "routine_auto"


def task_family_for_row(row: dict[str, Any], *, fallback: str) -> str:
    explicit = str(row.get("task_family") or "").strip()
    if explicit:
        return explicit
    tags = [str(t) for t in (row.get("tags") or []) if str(t).strip()]
    for tag in tags:
        if tag.startswith("family:"):
            return tag.split(":", 1)[1]
    for tag in tags:
        if tag not in {"project_notes", "work_class:dev", "work_class:ops_gate"}:
            return tag
    return fallback


def compute_stale_for_local_date(
    artifact_local_date: str,
    *,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> bool:
    """True when wall-clock operator date differs from the hub artifact date."""
    now = now or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    today = local_date_for_timezone(now=now, timezone=timezone)
    return str(artifact_local_date or "").strip() != today


def parse_today_bullets_from_notes(notes_text: str) -> list[dict[str, Any]]:
    """Extract ``Today — …`` bullets plus following ``Next:`` / ``Waiting on:`` lines."""
    lines: list[dict[str, Any]] = []
    if not notes_text:
        return lines
    raw_lines = notes_text.splitlines()
    i = 0
    while i < len(raw_lines):
        m = _TODAY_RE.match(raw_lines[i].strip())
        if not m:
            i += 1
            continue
        title = m.group(1).strip().rstrip(".")
        i += 1
        block_lines: list[str] = []
        while i < len(raw_lines):
            nxt = raw_lines[i]
            if _TODAY_RE.match(nxt.strip()):
                break
            if _NEXT_RE.match(nxt.strip()) or _WAITING_RE.match(nxt.strip()):
                block_lines.append(nxt)
                i += 1
                continue
            # Stop at next top-level bullet that is not Next/Waiting.
            if re.match(r"^\s*-\s+", nxt) and not (
                _NEXT_RE.match(nxt.strip()) or _WAITING_RE.match(nxt.strip())
            ):
                break
            if nxt.strip() == "":
                i += 1
                break
            i += 1
        if not title:
            continue
        notes_block = "\n".join(block_lines)
        status = parse_status_conventions(title=title, summary=title, notes_block=notes_block)
        lines.append(
            {
                "id": f"focus-{_stable_id('notes', title)}",
                "title": title,
                "summary": title,
                "source": "project_notes",
                "href": None,
                "tags": ["project_notes"],
                "next_steps": status.get("next_steps") or [],
                "waiting_on": status.get("waiting_on") or [],
                "status": status,
            }
        )
    return lines


def load_focus_seed(
    *,
    seed_path: Path | None = None,
    notes_text: str | None = None,
    data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Prefer seed JSON focus_lines; fall back to notes Today bullets."""
    if seed_path is None:
        seed_path = Path(data_dir or DEFAULT_DATA_DIR) / "project_daily_seed.json"
    else:
        seed_path = Path(seed_path)
    seed = _safe_read(seed_path)
    if seed and isinstance(seed.get("focus_lines"), list) and seed["focus_lines"]:
        out: list[dict[str, Any]] = []
        for i, row in enumerate(seed["focus_lines"], start=1):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("summary") or "").strip()
            if not title:
                continue
            fid = str(row.get("id") or f"focus-{i}").strip()
            summary = str(row.get("summary") or title).strip()
            status = parse_status_conventions(
                title=title,
                summary=summary,
                notes_block=str(row.get("notes_block") or ""),
                seed_row=row,
            )
            out.append(
                {
                    "id": fid,
                    "priority": int(row.get("priority") or i),
                    "title": title,
                    "summary": summary,
                    "source": str(row.get("source") or "project_notes_sync"),
                    "href": row.get("href"),
                    "tags": list(row.get("tags") or ["project_notes"]),
                    "task_family": task_family_for_row(row, fallback=fid),
                    "work_class": str(row.get("work_class") or "").strip()
                    or work_class_for_source(
                        str(row.get("source") or "project_notes_sync"),
                        tags=list(row.get("tags") or []),
                    ),
                    "next_steps": status.get("next_steps") or [],
                    "waiting_on": status.get("waiting_on") or [],
                    "status": status,
                }
            )
        if out:
            return out
    if notes_text:
        bullets = parse_today_bullets_from_notes(notes_text)
        for i, row in enumerate(bullets, start=1):
            row["priority"] = i
        return bullets
    return []


def _recommendation_for_focus(line: dict[str, Any]) -> dict[str, Any]:
    rid = f"rec-{_stable_id('focus', str(line.get('id') or ''), str(line.get('title') or ''))}"
    title = str(line.get("title") or "Focus line")
    summary = (
        f"Keep this as today's north star: {title}. "
        "Do not treat Suite A stress green or graduated badges as adoption."
    )
    rationale = (
        "Project notes / daily seed pinned this line under the Europe/London "
        "handoff. Policy green ≠ utility — action should advance P1 live-path "
        "utilization or clear a registered human gate."
    )
    discuss_prompt = (
        f"Discuss daily recommendation `{rid}` (focus `{line.get('id')}`):\n"
        f"Summary: {summary}\n"
        f"Rationale: {rationale}\n"
        "Suggested options:\n"
        "1) Accept — ack focus line for local_date and proceed\n"
        "2) Narrow scope — rewrite the focus bullet to a smaller P1 step\n"
        "3) Park — move to deferred / later coordinator pass\n"
        "Context: Project store notes Today block + docs/data/daily_focus.json"
    )
    return {
        "id": rid,
        "task_id": str(line.get("id") or ""),
        "summary": summary,
        "rationale": rationale,
        "accept_action": {
            "kind": "focus-ack",
            "payload": {
                "focus_id": line.get("id"),
                "decision": "accept",
            },
        },
        "discuss_prompt": discuss_prompt,
        "priority": int(line.get("priority") or 1),
        "options": [
            "Accept and ack for today",
            "Rewrite focus bullet (narrower P1)",
            "Park / discuss later",
        ],
    }


def _recommendation_for_human_task(task: dict[str, Any], *, priority: int) -> dict[str, Any]:
    tid = str(task.get("id") or "")
    title = str(task.get("title") or tid or "Human task")
    bucket = str(task.get("sort_bucket") or "unacked")
    analysis = task.get("analysis") or {}
    headline = str(analysis.get("headline") or "").strip()
    rid = f"rec-{_stable_id('human', tid, str(analysis.get('fingerprint') or ''))}"
    if bucket == "new_info":
        summary = f"Review new analysis on “{title}”, then Acknowledge (observe-only)."
    else:
        summary = f"Open human gate “{title}” — ack when reviewed; Approve only on promotion gates."
    rationale_bits = [
        f"sort_bucket={bucket}",
        "Ack / Approve never auto-apply knobs, crons, or capital.",
    ]
    if headline:
        rationale_bits.append(f"analysis: {headline}")
    rationale = " ".join(rationale_bits)
    fp = str(analysis.get("fingerprint") or "")
    discuss_prompt = (
        f"Discuss daily recommendation `{rid}` (human task `{tid}`):\n"
        f"Title: {title}\n"
        f"Summary: {summary}\n"
        f"Rationale: {rationale}\n"
        "Suggested options:\n"
        "1) Accept — Acknowledge via human-task-ack (observe-only)\n"
        "2) Approve gate if this is a promotion checklist item (still observe-only)\n"
        "3) Defer / rewrite runbook expectation\n"
        "Say: discuss daily recommendation "
        f"`{rid}` — coordinator reads docs/data/daily_discuss_inbox.json "
        "and Project store docs/daily-discuss-inbox.md"
    )
    return {
        "id": rid,
        "task_id": f"human:{tid}" if tid else tid,
        "summary": summary,
        "rationale": rationale,
        "accept_action": {
            "kind": "human-task-ack",
            "payload": {
                "task_id": tid,
                "decision": "ack_observe",
                "finding_fingerprint": fp,
            },
        },
        "discuss_prompt": discuss_prompt,
        "priority": priority,
        "options": [
            "Accept → Acknowledge (observe-only)",
            "Open runbook / defer",
            "Discuss in Project chat",
        ],
    }


def _recommendation_for_progress_item(item: dict[str, Any], *, priority: int) -> dict[str, Any]:
    title = str(item.get("title") or item.get("id") or "Progress item")
    iid = str(item.get("id") or _stable_id("progress", title))
    rid = f"rec-{_stable_id('progress', iid)}"
    summary = (
        f"Progress actionable (defer_now / human_gate): {title} — deep-link only; no fake complete."
    )
    rationale = (
        "Sourced from progress_report actionable. Closing requires the underlying "
        "so-what / deferred-idea disposition — Daily hub does not invent a second truth."
    )
    href = item.get("href") or item.get("doc_path") or "#overview"
    discuss_prompt = (
        f"Discuss daily recommendation `{rid}` (progress `{iid}`):\n"
        f"Summary: {summary}\n"
        f"Rationale: {rationale}\n"
        "Suggested options:\n"
        "1) Act on the linked progress / so-what item\n"
        "2) Snooze for today (session only)\n"
        "3) Park with ftse-defer if not relevant now"
    )
    return {
        "id": rid,
        "task_id": f"progress:{iid}",
        "summary": summary,
        "rationale": rationale,
        "accept_action": {
            "kind": "link_only",
            "payload": {"href": href},
        },
        "discuss_prompt": discuss_prompt,
        "priority": priority,
        "options": ["Open progress link", "Snooze today", "Discuss / park"],
    }


def _recommendation_for_reconcile(check: dict[str, Any], *, priority: int) -> dict[str, Any]:
    cid = str(check.get("id") or "reconcile")
    title = str(check.get("title") or cid)
    rid = f"rec-{_stable_id('reconcile', cid, str(check.get('detail') or ''))}"
    summary = f"UI reconcile warn: {title}."
    rationale = str(check.get("detail") or "Dashboard health drift — observe-only.")
    runbook = str(check.get("runbook") or "docs/ops/ops-monitor.md")
    discuss_prompt = (
        f"Discuss daily recommendation `{rid}` (reconcile `{cid}`):\n"
        f"Summary: {summary}\n"
        f"Rationale: {rationale}\n"
        f"Runbook: {runbook}\n"
        "Suggested options:\n"
        "1) Hard-refresh Pages / regenerate the named artifact\n"
        "2) Force republish if publish_lag (supervised)\n"
        "3) Confirm false positive and dismiss after condition clears"
    )
    return {
        "id": rid,
        "task_id": f"reconcile:{cid}",
        "summary": summary,
        "rationale": rationale,
        "accept_action": {
            "kind": "link_only",
            "payload": {"href": "#automation/ops", "runbook": runbook},
        },
        "discuss_prompt": discuss_prompt,
        "priority": priority,
        "options": ["Open runbook", "Supervised republish", "Discuss"],
    }


def _closed_ids(acks: dict[str, Any] | None, *, local_date: str) -> set[str]:
    out: set[str] = set()
    for row in (acks or {}).get("acks") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("local_date") or "") != local_date:
            continue
        if str(row.get("status") or "open") != "open":
            continue
        decision = str(row.get("decision") or "ack")
        if decision in {"ack", "accept", "dismiss", "ack_observe"}:
            ref = str(row.get("task_ref") or row.get("focus_id") or row.get("task_id") or "")
            if ref:
                out.add(ref)
    return out


def build_daily_focus(
    *,
    data_dir: Path | None = None,
    seed_path: Path | None = None,
    notes_text: str | None = None,
    acks: dict[str, Any] | None = None,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    refresh_deadline_local: str = REFRESH_DEADLINE_LOCAL,
) -> dict[str, Any]:
    """Compose daily hub payload (pure)."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    now = now or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    local_date = local_date_for_timezone(now=now, timezone=timezone)

    try:
        tz = ZoneInfo(timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    local_now = now.astimezone(tz)
    try:
        hh, mm = (int(x) for x in str(refresh_deadline_local).split(":", 1))
        deadline = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        past_deadline = local_now >= deadline
    except ValueError:
        past_deadline = False

    focus_lines = load_focus_seed(seed_path=seed_path, notes_text=notes_text, data_dir=data_dir)
    # Cap to 3 pinned focus lines.
    focus_lines = focus_lines[:3]

    board = _safe_read(data_dir / "human_tasks_board.json") or {}
    progress = _safe_read(data_dir / "progress_report.json") or {}
    reconcile = _safe_read(data_dir / "ui_state_reconciliation.json") or {}
    market_status = _safe_read(data_dir / "market_status.json") or {}
    ingest_deviations = _safe_read(data_dir / "ingest_deviations.json") or {}
    closed_ids = _closed_ids(acks, local_date=local_date)
    generated_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")

    tasks: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    # 1) Focus lines (pinned)
    for line in focus_lines:
        task_ref = str(line.get("id") or "")
        rec = _recommendation_for_focus(line)
        recommendations.append(rec)
        is_closed = task_ref in closed_ids
        status = derive_ready_status(
            dict(
                line.get("status")
                or parse_status_conventions(
                    title=str(line.get("title") or ""),
                    summary=str(line.get("summary") or ""),
                    seed_row=line,
                )
            ),
            recommendation_present=True,
            closed=is_closed,
        )
        status["updated_at"] = status.get("updated_at") or generated_at
        work_class = str(
            line.get("work_class")
            or work_class_for_source(
                str(line.get("source") or "daily_focus"),
                tags=list(line.get("tags") or []),
            )
        )
        family = str(line.get("task_family") or task_family_for_row(line, fallback=task_ref))
        tasks.append(
            {
                "task_ref": task_ref,
                "source": "daily_focus",
                "work_class": work_class,
                "task_family": family,
                "priority": int(line.get("priority") or 1),
                "title": line.get("title"),
                "summary": line.get("summary"),
                "sort_bucket": "focus",
                "closeable": True,
                "close_action": "daily-focus-ack",
                "close_payload": {"focus_id": task_ref, "decision": "ack"},
                "href": line.get("href"),
                "recommendation_id": rec["id"],
                "status": status,
                "closed": is_closed,
            }
        )

    # 1b) Market warning triage (deepen / dismiss / park) — after focus, before gates
    from value_investor.market_warning_triage import build_market_warning_triage_items

    mwarn_tasks, mwarn_recs = build_market_warning_triage_items(
        market_status=market_status,
        ingest_deviations=ingest_deviations,
        closed_ids=closed_ids,
        priority_start=5,
        generated_at=generated_at,
    )
    for task in mwarn_tasks:
        status = derive_ready_status(
            dict(task.get("status") or {}),
            recommendation_present=True,
            closed=False,
        )
        # Prefer-discuss deepen rows stay waiting even when recommendation present.
        if task.get("prefer_discuss"):
            status["ready"] = False
            if status.get("state") in {"proposed", "ready"}:
                status["state"] = "waiting"
            status["label"] = status.get("label") or "Discuss preferred"
        task["status"] = status
        tasks.append(task)
    recommendations.extend(mwarn_recs)

    # 2–3) Human tasks new_info then unacked
    human_tasks = [t for t in (board.get("tasks") or []) if isinstance(t, dict)]
    priority = 10 + len(mwarn_tasks)
    for bucket in ("new_info", "unacked"):
        for task in human_tasks:
            if str(task.get("sort_bucket") or "") != bucket:
                continue
            tid = str(task.get("id") or "")
            task_ref = f"human:{tid}"
            if task_ref in closed_ids or tid in closed_ids:
                continue
            rec = _recommendation_for_human_task(task, priority=priority)
            recommendations.append(rec)
            status = derive_ready_status(
                parse_status_conventions(
                    title=str(task.get("title") or ""),
                    summary=str(task.get("summary") or ""),
                    seed_row=task,
                ),
                recommendation_present=True,
                closed=False,
            )
            status["updated_at"] = status.get("updated_at") or generated_at
            tasks.append(
                {
                    "task_ref": task_ref,
                    "source": "human_tasks",
                    "work_class": "ops_gate",
                    "task_family": tid or task_ref,
                    "priority": priority,
                    "title": task.get("title"),
                    "summary": task.get("summary"),
                    "sort_bucket": bucket,
                    "closeable": True,
                    "close_action": "human-task-ack",
                    "close_payload": {
                        "task_id": tid,
                        "decision": "ack_observe",
                        "finding_fingerprint": (task.get("analysis") or {}).get("fingerprint")
                        or "",
                    },
                    "href": "#automation/human",
                    "recommendation_id": rec["id"],
                    "status": status,
                    "human_task": {
                        "id": tid,
                        "sort_bucket": bucket,
                        "analysis": task.get("analysis") or {},
                        "ack": task.get("ack") or {},
                        "approval_gate": task.get("approval_gate"),
                        "doc_url": task.get("doc_url"),
                        "cadence": task.get("cadence"),
                    },
                    "closed": False,
                }
            )
            priority += 1

    # 4) Progress actionable defer_now (read-only close → deep link)
    actionable = (progress.get("actionable") or {}) if isinstance(progress, dict) else {}
    defer_now = [x for x in (actionable.get("defer_now") or []) if isinstance(x, dict)]
    for item in defer_now[:5]:
        iid = str(item.get("id") or _stable_id("progress", str(item.get("title") or "")))
        task_ref = f"progress:{iid}"
        if task_ref in closed_ids:
            continue
        rec = _recommendation_for_progress_item(item, priority=priority)
        recommendations.append(rec)
        status = derive_ready_status(
            parse_status_conventions(
                title=str(item.get("title") or ""),
                summary=str(item.get("summary") or item.get("detail") or ""),
                seed_row=item,
            ),
            recommendation_present=True,
            closed=False,
        )
        status["updated_at"] = status.get("updated_at") or generated_at
        tasks.append(
            {
                "task_ref": task_ref,
                "source": "progress_actionable",
                "work_class": "surface",
                "task_family": iid,
                "priority": priority,
                "title": item.get("title") or iid,
                "summary": item.get("summary") or item.get("detail") or "",
                "sort_bucket": "defer_now",
                "closeable": False,
                "close_action": "link_only",
                "close_payload": {"href": "#overview"},
                "href": "#overview",
                "recommendation_id": rec["id"],
                "status": status,
                "closed": False,
            }
        )
        priority += 1

    # 7) Reconcile ambers
    if str(reconcile.get("overall") or "ok") != "ok":
        for check in reconcile.get("checks") or []:
            if not isinstance(check, dict) or check.get("status") not in {"warn", "fail"}:
                continue
            cid = str(check.get("id") or "")
            task_ref = f"reconcile:{cid}"
            if task_ref in closed_ids:
                continue
            rec = _recommendation_for_reconcile(check, priority=priority)
            recommendations.append(rec)
            status = derive_ready_status(
                {
                    "state": "blocked",
                    "label": "Reconcile amber",
                    "next_steps": ["Open Automation → Ops"],
                    "waiting_on": [
                        {
                            "kind": "artifact",
                            "ref": cid,
                            "detail": str(check.get("detail") or cid),
                        }
                    ],
                    "ready": False,
                    "ready_reason": None,
                    "blocked_reason": str(check.get("detail") or "reconcile warn"),
                    "updated_at": generated_at,
                    "updated_by": "morning_builder",
                },
                recommendation_present=True,
                closed=False,
            )
            tasks.append(
                {
                    "task_ref": task_ref,
                    "source": "ui_reconcile",
                    "work_class": "surface",
                    "task_family": cid,
                    "priority": priority,
                    "title": check.get("title") or cid,
                    "summary": check.get("detail") or "",
                    "sort_bucket": "reconcile",
                    "closeable": False,
                    "close_action": "link_only",
                    "close_payload": {"href": "#automation/ops"},
                    "href": "#automation/ops",
                    "recommendation_id": rec["id"],
                    "status": status,
                    "closed": False,
                }
            )
            priority += 1

    # Stale when wall-clock operator date ≠ artifact local_date (always false at
    # a correct morning write; clients recompute against wall clock too).
    stale = compute_stale_for_local_date(local_date, now=now, timezone=timezone)
    if past_deadline and not focus_lines and not tasks:
        stale = True

    notes_fp = None
    if notes_text:
        notes_fp = _content_fingerprint({"notes": notes_text.strip()[:4000]})
    elif seed_path and Path(seed_path or DEFAULT_SEED_PATH).exists():
        seed = _safe_read(Path(seed_path or DEFAULT_SEED_PATH)) or {}
        notes_fp = str(seed.get("notes_fingerprint") or "") or None

    rec_by_id = {r["id"]: r for r in recommendations}
    for task in tasks:
        rid = task.get("recommendation_id")
        if rid and rid in rec_by_id:
            task["recommendation"] = rec_by_id[rid]

    open_tasks = [t for t in tasks if not t.get("closed")]
    latest = _safe_read(data_dir / "latest.json") or {}
    dual_suite = latest.get("learning_tracks_dual_suite")
    observe = _safe_read(data_dir / "observe_utilization.json") or {}
    observe_fresh = str(observe.get("surface_freshness") or "")
    board_counts = board.get("counts") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "local_date": local_date,
        "timezone": timezone,
        "generated_at": generated_at,
        "refresh_deadline_local": refresh_deadline_local,
        "stale_for_local_date": bool(stale),
        "focus_lines": focus_lines,
        "tasks": tasks,
        "open_task_count": len(open_tasks),
        "recommendations": recommendations,
        "closed_today": sorted(closed_ids),
        "counts": {
            "focus": sum(1 for t in open_tasks if t.get("source") == "daily_focus"),
            "market_warnings": sum(
                1 for t in open_tasks if t.get("source") == "market_warning_triage"
            ),
            "human_new_info": sum(1 for t in open_tasks if t.get("sort_bucket") == "new_info"),
            "human_unacked": sum(1 for t in open_tasks if t.get("sort_bucket") == "unacked"),
            "progress": sum(1 for t in open_tasks if t.get("source") == "progress_actionable"),
            "reconcile": sum(1 for t in open_tasks if t.get("source") == "ui_reconcile"),
        },
        "project_sync": {
            "notes_fingerprint": notes_fp,
            "synced_at": generated_at,
            "method": "morning_builder_reads_committed_export_or_manual",
        },
        "illumination_hints": {
            "automation.daily": {
                "attention": bool(open_tasks) or bool(stale),
                "new_info": bool(
                    any(t.get("sort_bucket") == "new_info" for t in open_tasks) or focus_lines
                ),
                "reasons": [
                    *(["daily_hub.stale"] if stale else []),
                    *([f"open_tasks={len(open_tasks)}"] if open_tasks else []),
                ],
            },
            "automation.human": {
                "attention": bool(board_counts.get("new_info") or board_counts.get("unacked")),
                "new_info": bool(board_counts.get("new_info")),
                "reasons": [
                    f"human_tasks.new_info={board_counts.get('new_info', 0)}",
                    f"human_tasks.unacked={board_counts.get('unacked', 0)}",
                ],
            },
            "automation.tracks": {
                "attention": not bool(dual_suite),
                "new_info": False,
                "reasons": ["dual_suite_null"] if not dual_suite else [],
            },
            "automation.queue": {
                "attention": observe_fresh in {"stale", "degraded", "missing", "lagging"},
                "new_info": False,
                "reasons": [f"observe.surface_freshness={observe_fresh or 'unknown'}"],
            },
        },
    }


def write_daily_focus(
    *,
    data_dir: Path | None = None,
    store_path: Path | None = None,
    seed_path: Path | None = None,
    notes_text: str | None = None,
    acks_path: Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    store_path = Path(store_path or (data_dir / "daily_focus.json"))
    acks = None
    if acks_path is not None or (data_dir / "daily_focus_acks.json").exists():
        from value_investor.daily_focus_acks import load_daily_focus_acks

        acks = load_daily_focus_acks(data_dir if acks_path is None else Path(acks_path).parent)
    payload = build_daily_focus(
        data_dir=data_dir,
        seed_path=seed_path,
        notes_text=notes_text,
        acks=acks,
        **kwargs,
    )
    write_json(store_path, payload, compact=False)
    return payload
