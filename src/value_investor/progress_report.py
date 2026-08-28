"""Standardised progress report: north-star appraisal, actionable deferred items, join-up checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from value_investor.committed_data_json import check_paths
from value_investor.deferred_ideas import DEFAULT_STORE, list_open_fragments, load_store
from value_investor.engineering_sync import audit_compile_drop_risk
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    TERMINAL_TASK_STATUSES,
    load_engineering_tasks,
)
from value_investor.ops_monitor import (
    DEFAULT_LATEST_PATH,
    DEFAULT_STATUS_PATH,
    OpsFinding,
    check_committed_json,
    check_engineering_queue,
    check_engineering_sync,
    check_ingest_health_log,
    check_latest_bundle,
)
from value_investor.project_progress import DEFAULT_PROGRESS_PATH, build_project_progress
from value_investor.storage import read_json

DEFAULT_REPORT_PATH = Path("docs/data/progress_report.json")
DEFAULT_MARKDOWN_PATH = Path("docs/data/progress_report.md")

DATA_DIR = Path("docs/data")

Severity = Literal["ok", "info", "warn", "fail"]


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


def _overall_status(checks: list[dict[str, Any]]) -> Severity:
    severities = [str(row.get("severity") or "ok") for row in checks]
    if "fail" in severities:
        return "fail"
    if "warn" in severities:
        return "warn"
    if "info" in severities:
        return "info"
    return "ok"


def _finding_rows(findings: list[OpsFinding], *, prefix: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for finding in findings:
        check_id = prefix + finding.title.lower().replace(" ", "_")[:48]
        rows.append(
            {
                "id": check_id,
                "severity": finding.severity,
                "category": finding.category,
                "title": finding.title,
                "summary": finding.summary,
            }
        )
    return rows


def _active_deferred_ideas(store: dict[str, Any]) -> list[dict[str, Any]]:
    """Open ideas plus those explicitly marked for immediate action (`now`)."""
    return [
        row
        for row in store.get("ideas") or []
        if str(row.get("status") or "open") in {"open", "now"}
    ]


def _proposed_tasks(path: Path) -> list[dict[str, Any]]:
    raw = _safe_read(path)
    if not raw:
        return []
    return [
        row
        for row in raw.get("tasks") or []
        if isinstance(row, dict) and str(row.get("status") or "proposed") == "proposed"
    ]


def _proposed_task_paths(data_dir: Path) -> tuple[tuple[str, Path], ...]:
    return (
        ("analysis", data_dir / "analysis_tasks.json"),
        ("horizon", data_dir / "horizon_tasks.json"),
        ("learning_director", data_dir / "learning_director_tasks.json"),
    )


def _open_engineering_tasks(tasks_path: Path = COMMITTED_TASKS_PATH) -> list[dict[str, Any]]:
    rows = list(load_engineering_tasks(tasks_path).get("tasks") or [])
    return [row for row in rows if str(row.get("status") or "") not in TERMINAL_TASK_STATUSES]


def _compact_deferred(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "summary": row.get("summary"),
        "category": row.get("category"),
        "section": row.get("section"),
        "revisit_when": row.get("revisit_when"),
        "tags": row.get("tags") or [],
        "status": row.get("status"),
    }


def _compact_task(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "source": source,
        "title": row.get("title") or row.get("summary") or row.get("experiment"),
        "summary": row.get("summary") or row.get("rationale") or "",
        "status": row.get("status"),
        "added_at": row.get("added_at") or row.get("created_at"),
        "area": row.get("area"),
    }


def build_actionable_items(
    *,
    store_path: Path = DEFAULT_STORE,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    data_dir: Path = DATA_DIR,
) -> dict[str, Any]:
    """Deferred items and review queues that humans or agents can act on now."""
    store = load_store(store_path)
    ideas = _active_deferred_ideas(store)
    fragments = list_open_fragments(store)

    defer_now = [_compact_deferred(row) for row in ideas if str(row.get("status")) == "now"]
    defer_not_now = [
        _compact_deferred(row)
        for row in ideas
        if row.get("category") == "not_now" or row.get("section") == "not_now"
    ]
    defer_later = [
        _compact_deferred(row)
        for row in ideas
        if row.get("category") in {"later", "both", "security"}
        and row.get("section") != "not_now"
        and row.get("category") != "security"
    ]
    defer_security = [
        _compact_deferred(row)
        for row in ideas
        if row.get("category") == "security" or row.get("section") == "security"
    ]

    proposed: dict[str, list[dict[str, Any]]] = {}
    for source, path in _proposed_task_paths(data_dir):
        proposed[source] = [_compact_task(row, source=source) for row in _proposed_tasks(path)]

    engineering_open = [
        _compact_task(row, source="engineering") for row in _open_engineering_tasks(tasks_path)
    ]

    return {
        "defer_now": defer_now,
        "defer_not_now": defer_not_now,
        "defer_later": defer_later,
        "defer_security": defer_security,
        "open_fragments": [
            {
                "id": row.get("id"),
                "text": row.get("text"),
                "tags": row.get("tags") or [],
                "status": row.get("status"),
            }
            for row in fragments
        ],
        "proposed_tasks": proposed,
        "engineering_open": engineering_open,
        "counts": {
            "defer_now": len(defer_now),
            "defer_not_now": len(defer_not_now),
            "defer_later": len(defer_later),
            "defer_security": len(defer_security),
            "open_fragments": len(fragments),
            "proposed_total": sum(len(rows) for rows in proposed.values()),
            "engineering_open": len(engineering_open),
        },
    }


def build_role_coherence(
    *,
    progress: dict[str, Any],
    actionable: dict[str, Any],
    tasks_path: Path = COMMITTED_TASKS_PATH,
    analysis_review_path: Path = DATA_DIR / "analysis_review.json",
    horizon_scan_path: Path = DATA_DIR / "horizon_scan.json",
    stale_proposed_days: int = 14,
) -> list[dict[str, Any]]:
    """Check that built components connect and each plays a logical role."""
    checks: list[dict[str, Any]] = []
    evidence = progress.get("evidence") or {}
    current_focus = str(progress.get("current_focus") or "")

    if current_focus == "stage_2b":
        ai_excess = evidence.get("ai_excess_after_costs")
        if ai_excess is not None and float(ai_excess) < 0:
            checks.append(
                {
                    "id": "stage_2b_learning_edge",
                    "severity": "info",
                    "category": "doctrine",
                    "title": "Stage 2b focus aligned with primary learning gap",
                    "summary": (
                        "North-star focus is stage 2b while AI-judgment excess after costs is "
                        f"still negative ({float(ai_excess) * 100:+.1f}%). "
                        "Breadth expansion and new tracks should stay deferred."
                    ),
                }
            )

    library_count = int(evidence.get("library_graduated_count") or 0)
    if library_count >= 10 and current_focus == "stage_2b":
        checks.append(
            {
                "id": "library_ahead_of_live",
                "severity": "info",
                "category": "doctrine",
                "title": "Offline library ahead of live learning edge",
                "summary": (
                    f"{library_count} graduated library markets vs stage 2b still in progress — "
                    "library growth is correctly offline; live universe expansion remains gated."
                ),
            }
        )

    now_items = actionable.get("defer_now") or []
    if now_items:
        candidate_titles = [
            str(row.get("title") or "")
            for rows in (actionable.get("proposed_tasks") or {}).values()
            for row in rows
        ] + [str(row.get("title") or "") for row in (actionable.get("engineering_open") or [])]
        unlinked = [
            row
            for row in now_items
            if not _title_linked(str(row.get("title") or ""), candidate_titles)
        ]
        if unlinked:
            titles = ", ".join(str(row.get("id")) for row in unlinked[:5])
            checks.append(
                {
                    "id": "defer_now_without_queue_link",
                    "severity": "warn",
                    "category": "join_up",
                    "title": "Deferred now items without matching queue work",
                    "summary": (
                        f"{len(unlinked)} item(s) marked `now` have no obvious engineering or "
                        f"review-task counterpart ({titles}). Promote via ftse-defer status or "
                        "draft a supervised task."
                    ),
                }
            )

    cutoff = datetime.now(UTC) - timedelta(days=stale_proposed_days)
    stale_proposed: list[str] = []
    for source, rows in (actionable.get("proposed_tasks") or {}).items():
        for row in rows:
            added = _parse_time(str(row.get("added_at") or ""))
            if added and added < cutoff:
                stale_proposed.append(f"{source}:{row.get('id')}")
    if stale_proposed:
        checks.append(
            {
                "id": "stale_proposed_review_tasks",
                "severity": "warn",
                "category": "join_up",
                "title": "Stale proposed review tasks",
                "summary": (
                    f"{len(stale_proposed)} proposed task(s) older than {stale_proposed_days}d: "
                    f"{', '.join(stale_proposed[:6])}. Promote, drop, or re-compile."
                ),
            }
        )

    analysis_review = _safe_read(analysis_review_path)
    if analysis_review:
        reviewed_at = _parse_time(str(analysis_review.get("reviewed_at") or ""))
        if reviewed_at:
            age_days = (datetime.now(UTC) - reviewed_at).days
            if age_days > 10:
                checks.append(
                    {
                        "id": "analysis_review_stale",
                        "severity": "warn",
                        "category": "join_up",
                        "title": "Analysis review artifact is stale",
                        "summary": (
                            f"Last analysis review {reviewed_at.date().isoformat()} "
                            f"({age_days}d ago). Confirm Sunday analysis-review ran and dashboard "
                            "conclusions match merged code."
                        ),
                    }
                )
    elif (actionable.get("proposed_tasks") or {}).get("analysis"):
        checks.append(
            {
                "id": "analysis_review_missing",
                "severity": "warn",
                "category": "join_up",
                "title": "Proposed analysis tasks without review artifact",
                "summary": (
                    "analysis_tasks.json has proposed rows but analysis_review.json is missing."
                ),
            }
        )

    horizon = _safe_read(horizon_scan_path)
    if horizon is None and (actionable.get("proposed_tasks") or {}).get("horizon"):
        checks.append(
            {
                "id": "horizon_scan_missing",
                "severity": "info",
                "category": "join_up",
                "title": "Proposed horizon tasks without horizon scan artifact",
                "summary": (
                    "horizon_tasks.json has proposed rows but horizon_scan.json is missing — "
                    "run ftse-horizon-scan run on the monthly cadence."
                ),
            }
        )

    eng_rows = _open_engineering_tasks(tasks_path)
    missing_paths = [str(row.get("id")) for row in eng_rows if not (row.get("allowed_paths") or [])]
    if missing_paths:
        checks.append(
            {
                "id": "engineering_tasks_missing_paths",
                "severity": "warn",
                "category": "join_up",
                "title": "Open engineering tasks missing allowed_paths",
                "summary": f"Tasks {', '.join(missing_paths[:5])} cannot be safely dispatched.",
            }
        )

    dropped = audit_compile_drop_risk(tasks_path=tasks_path)
    if dropped:
        checks.append(
            {
                "id": "engineering_compile_drop_risk",
                "severity": "fail",
                "category": "join_up",
                "title": "Engineering compile would drop open tasks",
                "summary": (
                    f"{len(dropped)} open task(s) would be removed by compile: "
                    f"{', '.join(dropped[:5])}."
                ),
            }
        )

    if not checks:
        checks.append(
            {
                "id": "role_coherence_ok",
                "severity": "ok",
                "category": "join_up",
                "title": "Built components appear joined up",
                "summary": (
                    "Stage focus, deferred now items, review queues, and engineering tasks "
                    "show no obvious desync."
                ),
            }
        )
    return checks


def _norm_title(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _title_linked(title: str, candidates: list[str]) -> bool:
    needle = _norm_title(title)
    if not needle:
        return True
    for candidate in candidates:
        hay = _norm_title(candidate)
        if not hay:
            continue
        if needle in hay or hay in needle:
            return True
    return False


def build_integration_checks(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    ops_path: Path = DEFAULT_STATUS_PATH,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    progress_path: Path = DEFAULT_PROGRESS_PATH,
    progress: dict[str, Any] | None = None,
    ops_stale_hours: int = 30,
) -> dict[str, Any]:
    """Read-only health and artifact freshness checks (no auto-fixes)."""
    checks: list[dict[str, Any]] = []

    json_errors = check_paths(
        [
            "docs/data/library/policy.json",
            "docs/data/ops_status.json",
            "docs/data/engineering_tasks.json",
            "docs/data/ingest_health_log.json",
            "docs/data/latest.json",
        ]
    )
    for error in json_errors:
        checks.append(
            {
                "id": "committed_json_invalid",
                "severity": "fail",
                "category": "artifacts",
                "title": "Committed JSON validation failed",
                "summary": error,
            }
        )

    ops_findings: list[OpsFinding] = []
    ops_findings.extend(check_committed_json())
    ops_findings.extend(check_ingest_health_log())
    ops_findings.extend(check_latest_bundle(latest_path))
    eng_findings, queue_status = check_engineering_queue(tasks_path=tasks_path)
    sync_findings, _sync = check_engineering_sync(tasks_path=tasks_path)
    ops_findings.extend(eng_findings)
    ops_findings.extend(sync_findings)
    checks.extend(_finding_rows(ops_findings))

    progress_payload = progress if progress is not None else (_safe_read(progress_path) or {})

    ops_payload = _safe_read(ops_path)
    if ops_payload:
        ops_run = _parse_time(str(ops_payload.get("run_at") or ""))
        if ops_run:
            age_hours = (datetime.now(UTC) - ops_run).total_seconds() / 3600
            if age_hours > ops_stale_hours:
                checks.append(
                    {
                        "id": "ops_status_stale",
                        "severity": "warn",
                        "category": "artifacts",
                        "title": "Ops status snapshot is stale",
                        "summary": (
                            f"ops_status.json dated {ops_run.isoformat()} "
                            f"({int(age_hours)}h ago). Run ftse-ops-monitor run."
                        ),
                    }
                )
        saved_overall = str(ops_payload.get("overall") or "")
        evidence_overall = str((progress_payload.get("evidence") or {}).get("ops_overall") or "")
        if evidence_overall and saved_overall and evidence_overall != saved_overall:
            checks.append(
                {
                    "id": "ops_overall_mismatch",
                    "severity": "warn",
                    "category": "artifacts",
                    "title": "Ops overall mismatch between progress and ops_status",
                    "summary": (
                        f"project_progress evidence.ops_overall={evidence_overall!r} "
                        f"but ops_status.overall={saved_overall!r}. Re-run publish or ops monitor."
                    ),
                }
            )
    else:
        checks.append(
            {
                "id": "ops_status_missing",
                "severity": "warn",
                "category": "artifacts",
                "title": "Ops status missing",
                "summary": "docs/data/ops_status.json not found — run ftse-ops-monitor run.",
            }
        )

    latest = _safe_read(latest_path)
    if latest:
        run_at = _parse_time(str(latest.get("run_at") or latest.get("updated_at") or ""))
        progress_generated = _parse_time(str(progress_payload.get("generated_at") or ""))
        if run_at and progress_generated and progress_generated < run_at - timedelta(hours=1):
            checks.append(
                {
                    "id": "project_progress_behind_latest",
                    "severity": "warn",
                    "category": "artifacts",
                    "title": "Project progress older than latest screen bundle",
                    "summary": (
                        "project_progress.json was generated before the latest published screen — "
                        "re-run ftse-publish or ftse-progress-report build --write."
                    ),
                }
            )

    overall = _overall_status(checks)
    return {
        "overall": overall,
        "checks": checks,
        "queue_status": queue_status,
    }


def build_progress_report(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    ops_path: Path = DEFAULT_STATUS_PATH,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    store_path: Path = DEFAULT_STORE,
    progress_path: Path = DEFAULT_PROGRESS_PATH,
    data_dir: Path = DATA_DIR,
) -> dict[str, Any]:
    progress = build_project_progress(
        latest_path=latest_path,
        ops_path=ops_path,
    )
    actionable = build_actionable_items(
        store_path=store_path,
        tasks_path=tasks_path,
        data_dir=data_dir,
    )
    integration = build_integration_checks(
        latest_path=latest_path,
        ops_path=ops_path,
        tasks_path=tasks_path,
        progress_path=progress_path,
        progress=progress,
    )
    role_coherence = build_role_coherence(
        progress=progress,
        actionable=actionable,
        tasks_path=tasks_path,
        analysis_review_path=data_dir / "analysis_review.json",
        horizon_scan_path=data_dir / "horizon_scan.json",
    )

    severities = [
        str(integration.get("overall") or "ok"),
        _overall_status(role_coherence),
    ]
    report_overall: Severity = "ok"
    if "fail" in severities:
        report_overall = "fail"
    elif "warn" in severities:
        report_overall = "warn"
    elif "info" in severities:
        report_overall = "info"

    return {
        "schema_version": 1,
        "generated_at": _utcnow(),
        "overall": report_overall,
        "progress": progress,
        "actionable": actionable,
        "integration": integration,
        "role_coherence": {
            "overall": _overall_status(role_coherence),
            "checks": role_coherence,
        },
        "references": {
            "deferred_review": "docs/deferred-review.md",
            "ops_cadence": "docs/ops/ops-review-cadence.md",
            "human_tasks": "docs/ops/human-tasks-checklist.md",
        },
    }


def format_progress_report_markdown(report: dict[str, Any]) -> str:
    progress = report.get("progress") or {}
    actionable = report.get("actionable") or {}
    integration = report.get("integration") or {}
    role = report.get("role_coherence") or {}
    counts = actionable.get("counts") or {}

    lines: list[str] = [
        "# FTSE progress report",
        "",
        f"Generated `{report.get('generated_at')}` · overall **{str(report.get('overall')).upper()}**",
        "",
        progress.get("headline", ""),
        "",
        f"**Current focus:** {progress.get('current_focus')} · "
        f"**Screen companies:** {(progress.get('evidence') or {}).get('screen_company_count', '—')}",
        "",
        "## Overall progress",
        "",
        "| Stage | Status | Focus |",
        "|-------|--------|-------|",
    ]
    for stage in progress.get("stages") or []:
        lines.append(
            f"| {stage.get('id')} {stage.get('name')} | {stage.get('status')} | "
            f"{stage.get('focus')} |"
        )

    appraisal = progress.get("appraisal") or {}
    lines.extend(["", "### Strengths", ""])
    lines.extend(f"- {row}" for row in appraisal.get("strengths") or ["—"])
    lines.extend(["", "### Gaps", ""])
    lines.extend(f"- {row}" for row in appraisal.get("gaps") or ["—"])
    lines.extend(["", "### Suggested next actions", ""])
    lines.extend(f"- {row}" for row in appraisal.get("next_actions") or ["—"])

    lines.extend(
        [
            "",
            "## Actionable now",
            "",
            f"- Deferred `now`: **{counts.get('defer_now', 0)}**",
            f"- Open fragments: **{counts.get('open_fragments', 0)}**",
            f"- Proposed review tasks: **{counts.get('proposed_total', 0)}**",
            f"- Open engineering tasks: **{counts.get('engineering_open', 0)}**",
            "",
        ]
    )

    def _bullet_deferred(rows: list[dict[str, Any]]) -> list[str]:
        if not rows:
            return ["_None._"]
        out: list[str] = []
        for row in rows:
            revisit = row.get("revisit_when") or "—"
            out.append(
                f"- **{row.get('id')}** {row.get('title')} — {row.get('summary')} "
                f"_(revisit: {revisit})_"
            )
        return out

    lines.extend(["### Deferred — act now (`ftse-defer status … now`)", ""])
    lines.extend(_bullet_deferred(actionable.get("defer_now") or []))

    lines.extend(["", "### Deferred — not now (review triggers)", ""])
    lines.extend(_bullet_deferred(actionable.get("defer_not_now") or []))

    fragments = actionable.get("open_fragments") or []
    lines.extend(["", "### Open fragments (monthly horizon triage)", ""])
    if fragments:
        for row in fragments[:12]:
            lines.append(f"- **{row.get('id')}** {row.get('text')}")
        if len(fragments) > 12:
            lines.append(f"- … and {len(fragments) - 12} more")
    else:
        lines.append("_None._")

    proposed = actionable.get("proposed_tasks") or {}
    lines.extend(["", "### Proposed review tasks", ""])
    any_proposed = False
    for source, rows in proposed.items():
        if not rows:
            continue
        any_proposed = True
        lines.append(f"**{source}**")
        for row in rows[:8]:
            lines.append(f"- {row.get('id')}: {row.get('title')}")
        if len(rows) > 8:
            lines.append(f"- … and {len(rows) - 8} more")
        lines.append("")
    if not any_proposed:
        lines.append("_None._")

    eng = actionable.get("engineering_open") or []
    lines.extend(["", "### Open engineering queue", ""])
    if eng:
        for row in eng[:10]:
            lines.append(f"- **{row.get('id')}** [{row.get('status')}] {row.get('title')}")
    else:
        lines.append("_None._")

    lines.extend(
        [
            "",
            "## Integration health",
            "",
            f"Overall: **{str(integration.get('overall')).upper()}**",
            "",
        ]
    )
    for row in integration.get("checks") or []:
        lines.append(
            f"- **[{str(row.get('severity')).upper()}]** {row.get('title')}: {row.get('summary')}"
        )

    lines.extend(
        [
            "",
            "## Role coherence (join-up)",
            "",
            f"Overall: **{str(role.get('overall')).upper()}**",
            "",
        ]
    )
    for row in role.get("checks") or []:
        lines.append(
            f"- **[{str(row.get('severity')).upper()}]** {row.get('title')}: {row.get('summary')}"
        )

    refs = report.get("references") or {}
    lines.extend(
        [
            "",
            "## References",
            "",
            f"- Deferred review: `{refs.get('deferred_review')}`",
            f"- Ops cadence: `{refs.get('ops_cadence')}`",
            f"- Human tasks: `{refs.get('human_tasks')}`",
            "",
            "Regenerate: `ftse-progress-report build --write`",
            "",
        ]
    )
    return "\n".join(lines)


def write_progress_report(
    *,
    json_path: Path = DEFAULT_REPORT_PATH,
    markdown_path: Path = DEFAULT_MARKDOWN_PATH,
    sync_project_progress: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    payload = build_progress_report(**kwargs)
    json_path = Path(json_path)
    markdown_path = Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    from value_investor.storage import write_json

    write_json(json_path, payload, compact=False)
    markdown_path.write_text(format_progress_report_markdown(payload), encoding="utf-8")
    if sync_project_progress:
        progress_path = Path(kwargs.get("progress_path") or DEFAULT_PROGRESS_PATH)
        write_json(progress_path, payload.get("progress") or {}, compact=False)
    return payload
