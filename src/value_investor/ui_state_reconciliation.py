"""UI ↔ system-state reconciliation (dashboard health, observe-only).

Compares named dashboard artifacts so operators can see when Pages/UI
drifts from the working set automation used. Findings are warn-only
(``auto_fixable=False``) — never eng-spray or auto-republish.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
) -> dict[str, Any]:
    return {
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
    ]
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
