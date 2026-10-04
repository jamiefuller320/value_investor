"""One Daily-hub task for unmatched GHA/CI failures (observe-only).

Allowlisted signatures (including dispatch HTTP 403 / missing ``actions: write``)
still draft supervised engineering tasks. Failures that are **not** autofixable
append onto a **single** open Daily-hub item for the Europe/London local date
until that item is acked — never one discuss rec per flake.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json
from value_investor.ui_state_reconciliation import local_date_for_timezone

STORE_FILENAME = "gha_failure_triage.json"
SCHEMA_VERSION = 1
SOURCE = "gha_failure_triage"
TASK_REF = "gha:workflow-ci-failures"
TASK_FAMILY = "workflow-ci-failures"
TITLE = "Workflow/CI failures needing a proposed fix"
FINDING_TITLE = "GHA failure needs Daily-hub triage"
DEFAULT_TIMEZONE = "Europe/London"
MAX_FAILURES = 12


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _stable_id(*parts: str) -> str:
    raw = "|".join(str(p or "").strip() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def load_gha_failure_triage(data_dir: Path | None = None) -> dict[str, Any]:
    path = Path(data_dir or "docs/data") / STORE_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def open_bundle_for_local_date(
    store: dict[str, Any] | None,
    *,
    local_date: str,
) -> dict[str, Any] | None:
    open_item = _as_dict((store or {}).get("open"))
    if not open_item:
        return None
    if str(open_item.get("local_date") or "") != str(local_date):
        return None
    if str(open_item.get("task_ref") or TASK_REF) != TASK_REF:
        return None
    return open_item


def record_gha_failure_triage(
    *,
    workflow_file: str,
    kind: str,
    proposed_solution: str,
    run_id: int | str | None = None,
    run_url: str | None = None,
    data_dir: Path | None = None,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """Append a distinct failure type onto the open local-date hub bundle."""
    data_dir = Path(data_dir or "docs/data")
    now = now or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    local_date = local_date_for_timezone(now=now, timezone=timezone)
    stamp = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    workflow_file = str(workflow_file or "").strip()
    kind = str(kind or "").strip() or f"unmatched:{workflow_file or 'unknown'}"
    solution = str(proposed_solution or "").strip()
    store = load_gha_failure_triage(data_dir)
    open_item = open_bundle_for_local_date(store, local_date=local_date)
    if open_item is None:
        open_item = {
            "task_ref": TASK_REF,
            "local_date": local_date,
            "title": TITLE,
            "failures": [],
            "opened_at": stamp,
        }
    failures = [row for row in _as_list(open_item.get("failures")) if isinstance(row, dict)]
    existing_kinds = {str(row.get("kind") or "") for row in failures}
    appended = False
    if kind not in existing_kinds:
        failures.append(
            {
                "kind": kind,
                "workflow": workflow_file,
                "run_id": str(run_id) if run_id is not None else None,
                "run_url": run_url,
                "proposed_solution": solution,
                "first_seen_at": stamp,
            }
        )
        appended = True
        if len(failures) > MAX_FAILURES:
            failures = failures[-MAX_FAILURES:]
    open_item["failures"] = failures
    open_item["updated_at"] = stamp
    open_item["title"] = TITLE
    open_item["task_ref"] = TASK_REF
    open_item["local_date"] = local_date
    payload = {
        "schema_version": SCHEMA_VERSION,
        "timezone": timezone,
        "updated_at": stamp,
        "open": open_item,
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    write_json(data_dir / STORE_FILENAME, payload, compact=False)
    return {"recorded": True, "appended": appended, "kind": kind, "local_date": local_date}


def _failure_kind_key(row: dict[str, Any]) -> str:
    return str(row.get("kind") or "")


def _bundle_summary(open_item: dict[str, Any]) -> str:
    failures = [row for row in _as_list(open_item.get("failures")) if isinstance(row, dict)]
    if not failures:
        return TITLE
    lines = [f"{len(failures)} distinct failure type(s) this local date:"]
    for row in failures:
        kind = _failure_kind_key(row) or "unknown"
        wf = str(row.get("workflow") or "").strip()
        sol = str(row.get("proposed_solution") or "").strip()
        prefix = f"{kind}" + (f" ({wf})" if wf else "")
        if sol:
            lines.append(f"- {prefix}: {sol}")
        else:
            lines.append(f"- {prefix}")
    return "\n".join(lines)


def _recommendation_for_bundle(open_item: dict[str, Any], *, priority: int) -> dict[str, Any]:
    rid = f"rec-{_stable_id('gha', TASK_REF)}"
    summary = (
        "Triage unmatched workflow/CI failures in this one Daily-hub item. "
        "Accept observes for today; Discuss if the proposed fix is wrong."
    )
    rationale = _bundle_summary(open_item)
    options = [
        "Accept — observe-ack this bundle for today (does not patch CI)",
        "Discuss — proposed solution looks wrong or needs a signature",
        "Do not open a second Daily-hub rec for the same local date",
    ]
    discuss_lines = [
        f"Discuss daily recommendation `{rid}` (`{TASK_REF}`):",
        "Single open workflow/CI failure bundle for this local date.",
        rationale,
        "Suggested options:",
    ]
    for i, opt in enumerate(options, start=1):
        discuss_lines.append(f"{i}) {opt}")
    discuss_lines.append("Context: docs/data/gha_failure_triage.json + Daily hub")
    return {
        "id": rid,
        "task_id": TASK_REF,
        "summary": summary,
        "rationale": rationale,
        "accept_action": {
            "kind": "focus-ack",
            "payload": {"focus_id": TASK_REF, "decision": "accept"},
        },
        "discuss_prompt": "\n".join(discuss_lines),
        "priority": priority,
        "options": options,
        "work_class": "surface",
        "task_family": TASK_FAMILY,
    }


def build_gha_failure_hub_items(
    *,
    data_dir: Path | None = None,
    closed_ids: set[str] | None = None,
    local_date: str,
    priority_start: int = 8,
    generated_at: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return at most one Daily-hub task for the open local-date bundle."""
    closed_ids = closed_ids or set()
    store = load_gha_failure_triage(data_dir)
    open_item = open_bundle_for_local_date(store, local_date=local_date)
    if open_item is None:
        return [], []
    failures = [row for row in _as_list(open_item.get("failures")) if isinstance(row, dict)]
    if not failures:
        return [], []
    if TASK_REF in closed_ids:
        return [], []
    rec = _recommendation_for_bundle(open_item, priority=priority_start)
    n = len(failures)
    title = TITLE if n == 1 else f"{TITLE} ({n} types)"
    status = {
        "state": "waiting",
        "label": "Discuss or observe-ack this failure bundle",
        "next_steps": ["Review proposed solutions in the card", "Discuss if the fix is unclear"],
        "waiting_on": [
            {
                "kind": "human",
                "ref": "gha-triage",
                "detail": "one Daily-hub bundle until acked for local_date",
            }
        ],
        "ready": False,
        "ready_reason": None,
        "blocked_reason": "unmatched GHA/CI failure — not on the ci-fix allowlist",
        "updated_at": generated_at,
        "updated_by": "morning_builder",
    }
    task = {
        "task_ref": TASK_REF,
        "source": SOURCE,
        "work_class": "surface",
        "task_family": TASK_FAMILY,
        "priority": priority_start,
        "title": title,
        "summary": rec["rationale"],
        "sort_bucket": "gha_triage",
        "closeable": True,
        "close_action": "daily-focus-ack",
        "close_payload": {"focus_id": TASK_REF, "decision": "accept"},
        "href": "#automation/daily",
        "recommendation_id": rec["id"],
        "status": status,
        "closed": False,
        "prefer_discuss": True,
        "gha_failure": {
            "local_date": local_date,
            "failure_count": n,
            "kinds": [_failure_kind_key(row) for row in failures],
            "failures": failures,
        },
    }
    return [task], [rec]


def ops_findings_from_gha_failure_triage(
    *,
    data_dir: Path | None = None,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> list[dict[str, Any]]:
    """Warn-only finding when an unmatched GHA bundle is open for today."""
    now = now or _utcnow()
    local_date = local_date_for_timezone(now=now, timezone=timezone)
    store = load_gha_failure_triage(data_dir)
    open_item = open_bundle_for_local_date(store, local_date=local_date)
    if open_item is None:
        return []
    failures = [row for row in _as_list(open_item.get("failures")) if isinstance(row, dict)]
    if not failures:
        return []
    kinds = ", ".join(_failure_kind_key(row) or "?" for row in failures[:6])
    extra = f" (+{len(failures) - 6})" if len(failures) > 6 else ""
    return [
        {
            "severity": "warn",
            "category": "workflows",
            "title": FINDING_TITLE,
            "summary": (
                f"{len(failures)} distinct unmatched workflow/CI failure type(s) "
                f"on {local_date}: {kinds}{extra}. "
                "Daily hub shows one bundled task with proposed solutions "
                "(auto_fixable=False)."
            ),
            "auto_fixable": False,
        }
    ]


__all__ = [
    "FINDING_TITLE",
    "SOURCE",
    "STORE_FILENAME",
    "TASK_FAMILY",
    "TASK_REF",
    "TITLE",
    "build_gha_failure_hub_items",
    "load_gha_failure_triage",
    "ops_findings_from_gha_failure_triage",
    "record_gha_failure_triage",
]
