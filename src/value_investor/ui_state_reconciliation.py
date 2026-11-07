"""UI ↔ system-state reconciliation (dashboard health, observe-only).

Compares named dashboard artifacts so operators can see when Pages/UI
drifts from the working set automation used. Findings are warn-only
(``auto_fixable=False``) — never eng-spray or auto-republish.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from value_investor.storage import read_json, write_json

DEFAULT_STORE_PATH = Path("docs/data/ui_state_reconciliation.json")
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_TIMEZONE = "Europe/London"
SCHEMA_VERSION = 1
FINDING_TITLE = "UI state reconciliation drift"
DEFAULT_LIFECYCLE_STALE_HOURS = 30.0
# Mass-stale heuristic: if this fraction of open acks are stale, FP may be noisy.
MASS_STALE_WARN_RATIO = 0.5
MASS_STALE_MIN_ACKS = 3

# Strategy dashboard v2 (`docs/v2/`) — mirrors `OPTIONAL_DATA_FILES` / `optionalDataFiles`
# in `docs/v2/v2.js` and tab registrations (forward status + observe book).
DASHBOARD_V2_OPTIONAL_STORE_BASENAMES = frozenset(
    {
        "strategy_book_forward_status.json",
        "strategy_book_observe.json",
    }
)

# Daily freshness for v2 Today tab: must mirror `freshnessDailyStore` in `docs/v2/v2.js`
# (fresh ≤36h, stale ≤72h; we warn past the fresh band only).
DASHBOARD_V2_DAILY_FRESH_HOURS = 36.0
CheckStatus = str  # ok | warn | fail


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
        # Date-only `as_of` (gate stores)
        try:
            day = date.fromisoformat(text)
        except ValueError:
            return None
        dt = datetime(day.year, day.month, day.day, tzinfo=UTC)
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


def _check(
    *,
    check_id: str,
    title: str,
    status: CheckStatus,
    drift_class: str | None = None,
    detail: str = "",
    ui_path: str | None = None,
    ui_generated_at: str | None = None,
    authority_path: str | None = None,
    authority_generated_at: str | None = None,
    runbook: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": check_id,
        "title": title,
        "status": status,
        "drift_class": drift_class,
        "ui_path": ui_path,
        "ui_generated_at": ui_generated_at,
        "authority_path": authority_path,
        "authority_generated_at": authority_generated_at,
        "detail": detail,
        "runbook": runbook,
    }
    if details:
        out["details"] = details
    return out


def _check_progress_report_vs_overlay(data_dir: Path) -> dict[str, Any]:
    """Progress sidecar present with a parseable generated_at (clobber guard)."""
    path = data_dir / "progress_report.json"
    payload = _safe_read(path)
    generated = _parse_dt((payload or {}).get("generated_at")) if payload else None
    if payload is None:
        return _check(
            check_id="progress_report_vs_email_overlay",
            title="Progress report not clobbered",
            status="warn",
            drift_class="missing_required",
            detail="progress_report.json missing — Overview progress strip may be empty",
            ui_path="docs/data/progress_report.json",
            runbook="docs/ops/progress-report.md",
        )
    if generated is None:
        return _check(
            check_id="progress_report_vs_email_overlay",
            title="Progress report not clobbered",
            status="warn",
            drift_class="fingerprint_noise",
            detail="progress_report.json present but generated_at unparseable",
            ui_path="docs/data/progress_report.json",
            runbook="docs/ops/progress-report.md",
        )
    # Monotonic vs a sidecar "last_write" marker if present; otherwise ok when fresh.
    return _check(
        check_id="progress_report_vs_email_overlay",
        title="Progress report not clobbered",
        status="ok",
        detail="ui matches authority (sidecar present with generated_at)",
        ui_path="docs/data/progress_report.json",
        ui_generated_at=generated.isoformat(),
        authority_path="docs/data/progress_report.json",
        authority_generated_at=generated.isoformat(),
        runbook="docs/ops/progress-report.md",
    )


def _check_dual_suite_present(data_dir: Path) -> dict[str, Any]:
    latest = _safe_read(data_dir / "latest.json") or {}
    dual = latest.get("learning_tracks_dual_suite")
    review = ((latest.get("paper_automation") or {}).get("learning_tracks_review")) or latest.get(
        "learning_tracks_review"
    )
    if isinstance(dual, dict) and dual:
        return _check(
            check_id="learning_tracks_dual_suite_present",
            title="Dual-suite scoreboard published",
            status="ok",
            detail="learning_tracks_dual_suite present in latest.json",
            ui_path="latest.json#learning_tracks_dual_suite",
            runbook="docs/ops/primary-learning-track.md",
        )
    if review:
        return _check(
            check_id="learning_tracks_dual_suite_present",
            title="Dual-suite scoreboard published",
            status="warn",
            drift_class="publish_lag",
            detail=(
                "null — UI falling back to client classify; suite headlines may be "
                "incomplete until next publish"
            ),
            ui_path="latest.json#learning_tracks_dual_suite",
            runbook="docs/ops/primary-learning-track.md",
        )
    return _check(
        check_id="learning_tracks_dual_suite_present",
        title="Dual-suite scoreboard published",
        status="warn",
        drift_class="missing_required",
        detail="dual-suite and learning_tracks_review both absent",
        ui_path="latest.json#learning_tracks_dual_suite",
        runbook="docs/ops/primary-learning-track.md",
    )


def _check_human_task_ack_fp_stable(data_dir: Path) -> dict[str, Any]:
    board = _safe_read(data_dir / "human_tasks_board.json") or {}
    acks_store = _safe_read(data_dir / "human_task_acks.json") or {}
    tasks = [t for t in (board.get("tasks") or []) if isinstance(t, dict)]
    open_acks = [
        a
        for a in (acks_store.get("acks") or [])
        if isinstance(a, dict) and str(a.get("status") or "open") == "open"
    ]
    if not open_acks:
        return _check(
            check_id="human_task_ack_fp_stable",
            title="Human-task ack fingerprints content-stable",
            status="ok",
            detail="no open acks to evaluate",
            runbook="docs/ops/human-tasks-checklist.md",
        )
    by_id = {str(t.get("id") or ""): t for t in tasks}
    stale = 0
    compared = 0
    for ack in open_acks:
        tid = str(ack.get("task_id") or "").strip()
        task = by_id.get(tid)
        if not task:
            continue
        compared += 1
        live_fp = str((task.get("analysis") or {}).get("fingerprint") or "")
        ack_fp = str(ack.get("finding_fingerprint") or "")
        if live_fp and ack_fp and live_fp != ack_fp:
            stale += 1
        elif (task.get("ack") or {}).get("stale"):
            stale += 1
    if compared < MASS_STALE_MIN_ACKS:
        return _check(
            check_id="human_task_ack_fp_stable",
            title="Human-task ack fingerprints content-stable",
            status="ok",
            detail=f"compared {compared} open ack(s); below mass-stale sample size",
            runbook="docs/ops/human-tasks-checklist.md",
        )
    ratio = stale / compared if compared else 0.0
    if ratio >= MASS_STALE_WARN_RATIO:
        return _check(
            check_id="human_task_ack_fp_stable",
            title="Human-task ack fingerprints content-stable",
            status="warn",
            drift_class="fingerprint_noise",
            detail=(
                f"{stale}/{compared} open acks look stale ({ratio:.0%}) — "
                "possible timestamp-only fingerprint churn"
            ),
            runbook="docs/ops/human-tasks-checklist.md",
        )
    return _check(
        check_id="human_task_ack_fp_stable",
        title="Human-task ack fingerprints content-stable",
        status="ok",
        detail=f"{stale}/{compared} open acks stale (under mass-stale threshold)",
        runbook="docs/ops/human-tasks-checklist.md",
    )


def _check_lifecycle_board_age(
    data_dir: Path,
    *,
    now: datetime,
    stale_after_hours: float,
) -> dict[str, Any]:
    path = data_dir / "lifecycle_board.json"
    board = _safe_read(path)
    if board is None:
        return _check(
            check_id="lifecycle_board_age",
            title="Lifecycle board within content window",
            status="warn",
            drift_class="missing_required",
            detail="lifecycle_board.json missing",
            ui_path="docs/data/lifecycle_board.json",
            runbook="docs/ops/position-lifecycle.md",
        )
    generated = _parse_dt(board.get("generated_at") or board.get("updated_at"))
    if generated is None:
        return _check(
            check_id="lifecycle_board_age",
            title="Lifecycle board within content window",
            status="warn",
            drift_class="fingerprint_noise",
            detail="lifecycle_board present but no usable generated_at",
            ui_path="docs/data/lifecycle_board.json",
            runbook="docs/ops/position-lifecycle.md",
        )
    age_h = (now - generated).total_seconds() / 3600.0
    if age_h >= stale_after_hours:
        return _check(
            check_id="lifecycle_board_age",
            title="Lifecycle board within content window",
            status="warn",
            drift_class="publish_lag",
            detail=f"board age {age_h:.1f}h ≥ {stale_after_hours:.0f}h content window",
            ui_path="docs/data/lifecycle_board.json",
            ui_generated_at=generated.isoformat(),
            runbook="docs/ops/position-lifecycle.md",
        )
    return _check(
        check_id="lifecycle_board_age",
        title="Lifecycle board within content window",
        status="ok",
        detail=f"board age {age_h:.1f}h (limit {stale_after_hours:.0f}h)",
        ui_path="docs/data/lifecycle_board.json",
        ui_generated_at=generated.isoformat(),
        runbook="docs/ops/position-lifecycle.md",
    )


def _surface_freshness(checks: list[dict[str, Any]]) -> str:
    statuses = {str(c.get("status") or "ok") for c in checks}
    if "fail" in statuses:
        return "degraded"
    warn_classes = {c.get("drift_class") for c in checks if c.get("status") == "warn"}
    if "missing_required" in warn_classes:
        return "missing"
    if "publish_lag" in warn_classes:
        return "lagging"
    if any(c.get("status") == "warn" for c in checks):
        return "stale"
    return "fresh"


def _overall(checks: list[dict[str, Any]]) -> str:
    statuses = [str(c.get("status") or "ok") for c in checks]
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _check_daily_hub_local_date(
    data_dir: Path,
    *,
    now: datetime,
    timezone: str,
    refresh_deadline_local: str = "04:00",
) -> dict[str, Any]:
    """After the London refresh deadline, hub local_date must match today."""
    path = data_dir / "daily_focus.json"
    payload = _safe_read(path)
    today = local_date_for_timezone(now=now, timezone=timezone)
    hours = hours_until_deadline(now=now, timezone=timezone, deadline_local=refresh_deadline_local)
    past_deadline = hours is not None and hours <= 0
    if payload is None:
        return _check(
            check_id="daily_hub_local_date_matches_today",
            title="Daily hub local_date matches today",
            status="warn" if past_deadline else "ok",
            drift_class="missing_required" if past_deadline else None,
            detail=(
                "daily_focus.json missing after refresh deadline"
                if past_deadline
                else "daily_focus.json not published yet (before deadline)"
            ),
            ui_path="docs/data/daily_focus.json",
            runbook="docs/ops/ops-monitor.md#daily-hub",
        )
    hub_date = str(payload.get("local_date") or "").strip()
    generated = _parse_dt(payload.get("generated_at"))
    if hub_date == today:
        return _check(
            check_id="daily_hub_local_date_matches_today",
            title="Daily hub local_date matches today",
            status="ok",
            detail=f"hub local_date={hub_date} matches {timezone} today",
            ui_path="docs/data/daily_focus.json",
            ui_generated_at=payload.get("generated_at"),
            runbook="docs/ops/ops-monitor.md#daily-hub",
        )
    if not past_deadline:
        return _check(
            check_id="daily_hub_local_date_matches_today",
            title="Daily hub local_date matches today",
            status="ok",
            detail=(
                f"hub local_date={hub_date or '—'} ≠ today {today}; "
                f"before {refresh_deadline_local} {timezone} refresh deadline"
            ),
            ui_path="docs/data/daily_focus.json",
            ui_generated_at=payload.get("generated_at"),
            runbook="docs/ops/ops-monitor.md#daily-hub",
        )
    age = ""
    if generated is not None:
        age_h = (now - generated).total_seconds() / 3600.0
        age = f"; artifact age {age_h:.1f}h"
    return _check(
        check_id="daily_hub_local_date_matches_today",
        title="Daily hub local_date matches today",
        status="warn",
        drift_class="stale_surface",
        detail=(
            f"hub local_date={hub_date or '—'} ≠ today {today} after "
            f"{refresh_deadline_local} {timezone}{age}"
        ),
        ui_path="docs/data/daily_focus.json",
        ui_generated_at=payload.get("generated_at"),
        runbook="docs/ops/ops-monitor.md#daily-hub",
    )


def _repo_root_for_data_dir(data_dir: Path) -> Path | None:
    """`<root>/docs/data` → `<root>`; None when the data dir is not a published docs tree."""
    resolved = data_dir.resolve()
    if resolved.parent.name != "docs":
        return None
    return resolved.parent.parent


_V2_JS_PATH_LITERAL_RE = re.compile(
    r"""["'](\.\./(?:data/)?[^'"\s]+\.(?:json|json\.gz))["']""",
    re.IGNORECASE,
)
_V2_OPTIONAL_ARRAY_RE = re.compile(
    r"optionalDataFiles\s*:\s*\[([^\]]*)\]",
    re.MULTILINE,
)


def _strip_asset_query(uri: str) -> str:
    base = str(uri).strip()
    if "?" in base:
        base = base.split("?", 1)[0]
    return base


def _parse_index_html_assets(index_html: str) -> tuple[list[str], list[str]]:
    """Return (stylesheet hrefs, script srcs) from v2 index.html."""
    styles: list[str] = []
    scripts: list[str] = []
    for m in re.finditer(r"<link([^>]+)>", index_html, flags=re.IGNORECASE):
        tag = m.group(1)
        if "stylesheet" not in tag.lower():
            continue
        hm = re.search(r"""href\s*=\s*["']([^"']+)["']""", tag, flags=re.IGNORECASE)
        if hm:
            styles.append(_strip_asset_query(hm.group(1)))
    for m in re.finditer(r"<script([^>]+)>", index_html, flags=re.IGNORECASE):
        tag = m.group(1)
        if "src=" not in tag.lower():
            continue
        sm = re.search(r"""src\s*=\s*["']([^"']+)["']""", tag, flags=re.IGNORECASE)
        if sm:
            scripts.append(_strip_asset_query(sm.group(1)))
    return styles, scripts


def _resolve_v2_relative(ref: str, *, v2_dir: Path, repo_root: Path) -> Path:
    rel = _strip_asset_query(ref)
    if rel.startswith("/"):
        return (repo_root / rel.lstrip("/")).resolve()
    return (v2_dir / rel).resolve()


def _collect_dashboard_v2_json_refs(v2_dir: Path) -> tuple[set[str], set[str]]:
    """Return (path literals, optional basenames) scraped from docs/v2/*.js."""
    literals: set[str] = set()
    optional_names: set[str] = set(DASHBOARD_V2_OPTIONAL_STORE_BASENAMES)
    for js_path in sorted(v2_dir.glob("*.js")):
        try:
            text = js_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _V2_JS_PATH_LITERAL_RE.finditer(text):
            literals.add(m.group(1))
        for block in _V2_OPTIONAL_ARRAY_RE.finditer(text):
            inner = block.group(1)
            for qm in re.finditer(r"""["']([^"']+\.json)["']""", inner):
                optional_names.add(qm.group(1))
    return literals, optional_names


def _freshness_dt_for_core_store(
    name: str, payload: dict[str, Any] | None
) -> tuple[datetime | None, str]:
    """Return (timestamp, field_used) for v2 Today core stores."""
    if payload is None:
        return None, ""
    order: tuple[str, ...]
    if name == "strategy_book_memo_job.json":
        order = ("generated_at", "last_run_at", "as_of", "run_at")
    elif name in {"operating_decline_gate.json", "sector_headwind_gate.json"}:
        order = ("as_of", "generated_at", "run_at")
    elif name in {"decision_input_inventory.json", "library_decision_input_inventory.json"}:
        order = ("generated_at", "as_of", "run_at")
    elif name == "human_tasks_board.json":
        order = ("generated_at", "checklist_updated_at", "as_of", "run_at")
    elif name == "daily_focus.json":
        order = ("generated_at", "as_of", "run_at")
    else:
        order = ("generated_at", "as_of", "run_at")
    for field in order:
        dt = _parse_dt(payload.get(field))
        if dt is not None:
            return dt, field
    return None, ""


def _check_dashboard_v2_stores_present_and_fresh(
    *,
    data_dir: Path,
    repo_root: Path,
    now: datetime,
) -> dict[str, Any]:
    """Page integrity + required JSON sidecars for `docs/v2/` (observe-only)."""
    v2_dir = repo_root / "docs" / "v2"
    index_path = v2_dir / "index.html"
    check_id = "dashboard_v2_stores_present_and_fresh"
    title = "Strategy dashboard v2 present and fresh"
    runbook = "docs/ops/ops-monitor.md#daily-hub--ui-reconciliation"

    missing_page_assets: list[str] = []
    missing_stores: list[str] = []
    stale_stores: list[dict[str, Any]] = []

    core_daily = (
        "strategy_book_memo_job.json",
        "operating_decline_gate.json",
        "sector_headwind_gate.json",
        "decision_input_inventory.json",
        "library_decision_input_inventory.json",
        "human_tasks_board.json",
        "daily_focus.json",
    )

    if not index_path.is_file():
        detail = "docs/v2/index.html missing — strategy dashboard v2 not ship-shaped"
        return _check(
            check_id=check_id,
            title=title,
            status="warn",
            drift_class="missing_required",
            detail=detail,
            ui_path="docs/v2/index.html",
            runbook=runbook,
            details={
                "v2_path": "docs/v2/",
                "missing_page_assets": [],
                "missing_stores": ["docs/v2/index.html"],
                "stale_stores": [],
                "freshness_threshold_hours": DASHBOARD_V2_DAILY_FRESH_HOURS,
                "freshness_rule": "freshnessDailyStore in docs/v2/v2.js",
            },
        )

    try:
        index_html = index_path.read_text(encoding="utf-8")
    except OSError as exc:
        return _check(
            check_id=check_id,
            title=title,
            status="warn",
            drift_class="missing_required",
            detail=f"could not read docs/v2/index.html: {exc}",
            ui_path="docs/v2/index.html",
            runbook=runbook,
        )

    styles, scripts = _parse_index_html_assets(index_html)
    for href in styles + scripts:
        resolved = _resolve_v2_relative(href, v2_dir=v2_dir, repo_root=repo_root)
        if not resolved.is_file():
            missing_page_assets.append(href)

    literals, optional_names = _collect_dashboard_v2_json_refs(v2_dir)
    for lit in sorted(literals):
        if lit.endswith(".json.gz"):
            resolved = _resolve_v2_relative(lit, v2_dir=v2_dir, repo_root=repo_root)
            if not resolved.is_file():
                missing_stores.append(lit)
            continue
        base = Path(lit).name
        if base in optional_names:
            continue
        resolved = _resolve_v2_relative(lit, v2_dir=v2_dir, repo_root=repo_root)
        if not resolved.is_file():
            missing_stores.append(lit)

    data_dir = Path(data_dir)
    for store in core_daily:
        path = data_dir / store
        if not path.is_file():
            stale_stores.append({"store": store, "reason": "missing file"})
            continue
        try:
            payload_any = read_json(path)
        except (OSError, ValueError, TypeError):
            stale_stores.append({"store": store, "reason": "unreadable JSON"})
            continue
        payload = payload_any if isinstance(payload_any, dict) else None
        if payload is None:
            stale_stores.append({"store": store, "reason": "date missing"})
            continue
        ts, field = _freshness_dt_for_core_store(store, payload)
        if ts is None:
            stale_stores.append({"store": store, "reason": "date missing"})
            continue
        age_h = (now - ts).total_seconds() / 3600.0
        if age_h > DASHBOARD_V2_DAILY_FRESH_HOURS:
            stale_stores.append(
                {
                    "store": store,
                    "reason": "stale",
                    "field": field,
                    "age_hours": round(age_h, 2),
                    "timestamp": ts.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                }
            )

    has_missing = bool(missing_page_assets or missing_stores)
    has_issue = has_missing or bool(stale_stores)
    parts: list[str] = []
    if missing_page_assets:
        parts.append(f"missing page assets ({len(missing_page_assets)})")
    if missing_stores:
        parts.append(f"missing stores ({len(missing_stores)})")
    if stale_stores:
        parts.append(f"stale or unreadable stores ({len(stale_stores)})")
    detail = "; ".join(parts) if parts else "v2 page + Today stores look fresh"

    if not has_issue:
        drift: str | None = None
    elif has_missing or any(s.get("reason") == "missing file" for s in stale_stores):
        drift = "missing_required"
    elif any(s.get("reason") in {"date missing", "unreadable JSON"} for s in stale_stores):
        drift = "fingerprint_noise"
    else:
        drift = "publish_lag"

    status: CheckStatus = "warn" if has_issue else "ok"

    return _check(
        check_id=check_id,
        title=title,
        status=status,
        drift_class=drift,
        detail=detail,
        ui_path="docs/v2/index.html",
        runbook=runbook,
        details={
            "v2_path": "docs/v2/",
            "missing_page_assets": missing_page_assets,
            "missing_stores": missing_stores,
            "stale_stores": stale_stores,
            "freshness_threshold_hours": DASHBOARD_V2_DAILY_FRESH_HOURS,
            "freshness_rule": "freshnessDailyStore in docs/v2/v2.js (warn past 36h fresh band)",
        },
    )


def build_ui_state_reconciliation(
    *,
    data_dir: Path | None = None,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    lifecycle_stale_hours: float = DEFAULT_LIFECYCLE_STALE_HOURS,
) -> dict[str, Any]:
    """Build Cap B reconciliation snapshot (pure; does not write)."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    now = now or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    checks = [
        _check_progress_report_vs_overlay(data_dir),
        _check_dual_suite_present(data_dir),
        _check_human_task_ack_fp_stable(data_dir),
        _check_lifecycle_board_age(
            data_dir, now=now, stale_after_hours=float(lifecycle_stale_hours)
        ),
        _check_daily_hub_local_date(data_dir, now=now, timezone=timezone),
    ]
    v2_repo_root = _repo_root_for_data_dir(data_dir)
    if v2_repo_root is not None:
        checks.append(
            _check_dashboard_v2_stores_present_and_fresh(
                data_dir=data_dir, repo_root=v2_repo_root, now=now
            )
        )
    summary = {
        "ok": sum(1 for c in checks if c.get("status") == "ok"),
        "warn": sum(1 for c in checks if c.get("status") == "warn"),
        "fail": sum(1 for c in checks if c.get("status") == "fail"),
    }
    overall = _overall(checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "timezone": timezone,
        "overall": overall,
        "surface_freshness": _surface_freshness(checks),
        "checks": checks,
        "summary": summary,
        "observe_only": True,
        "auto_fixable": False,
    }


def write_ui_state_reconciliation(
    *,
    data_dir: Path | None = None,
    store_path: Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    store_path = Path(store_path or (data_dir / "ui_state_reconciliation.json"))
    payload = build_ui_state_reconciliation(data_dir=data_dir, **kwargs)
    write_json(store_path, payload, compact=False)
    return payload


def ops_finding_from_reconciliation(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map snapshot → ops finding dict when overall is warn/fail."""
    if not payload or not isinstance(payload, dict):
        return None
    overall = str(payload.get("overall") or "ok")
    if overall == "ok":
        return None
    summary_counts = payload.get("summary") or {}
    warn_ids = [
        str(c.get("id") or "")
        for c in (payload.get("checks") or [])
        if isinstance(c, dict) and c.get("status") in {"warn", "fail"}
    ]
    detail = ", ".join(w for w in warn_ids if w) or "drift detected"
    return {
        "severity": "fail" if overall == "fail" else "warn",
        "category": "dashboard_health",
        "title": FINDING_TITLE,
        "summary": (
            f"UI state reconciliation {overall}: "
            f"{summary_counts.get('warn', 0)} warn / {summary_counts.get('fail', 0)} fail "
            f"({detail}). Observe-only — do not eng-spray."
        ),
        "auto_fixable": False,
    }


def check_ui_state_reconciliation(
    *,
    data_dir: Path | None = None,
    store_path: Path | None = None,
    persist: bool = True,
) -> list[dict[str, Any]]:
    """Build (+ optionally persist) reconciliation; return finding dicts."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    store_path = Path(store_path or (data_dir / "ui_state_reconciliation.json"))
    try:
        if persist:
            payload = write_ui_state_reconciliation(data_dir=data_dir, store_path=store_path)
        else:
            payload = build_ui_state_reconciliation(data_dir=data_dir)
    except (OSError, ValueError, TypeError) as exc:
        return [
            {
                "severity": "warn",
                "category": "dashboard_health",
                "title": FINDING_TITLE,
                "summary": str(exc),
                "auto_fixable": False,
            }
        ]
    finding = ops_finding_from_reconciliation(payload)
    return [finding] if finding else []


def local_date_for_timezone(
    *,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> str:
    """Calendar date in operator TZ (YYYY-MM-DD)."""
    now = now or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    try:
        tz = ZoneInfo(timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    return now.astimezone(tz).date().isoformat()


def hours_until_deadline(
    *,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    deadline_local: str = "04:00",
) -> float | None:
    """Hours until today's deadline in operator TZ (negative if past)."""
    now = now or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    try:
        tz = ZoneInfo(timezone)
    except Exception:  # noqa: BLE001
        return None
    local = now.astimezone(tz)
    try:
        hh, mm = (int(x) for x in str(deadline_local).split(":", 1))
    except ValueError:
        return None
    deadline = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return (deadline - local).total_seconds() / 3600.0


# Re-export timedelta for tests that may stub clocks.
__all__ = [
    "DEFAULT_STORE_PATH",
    "FINDING_TITLE",
    "build_ui_state_reconciliation",
    "check_ui_state_reconciliation",
    "hours_until_deadline",
    "local_date_for_timezone",
    "ops_finding_from_reconciliation",
    "write_ui_state_reconciliation",
    "timedelta",
]
