"""Compact UI status for the universe filing archive pack lane (thin L521).

Derives a low-distraction Ops panel payload from the last pack run + bottleneck
review. Observe-only — does not eng-spray, deepen, or widen caps.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 1
DEFAULT_PACK_RUN_PATH = Path("docs/data/universe_filing_archive_pack_run.json")
DEFAULT_BOTTLENECK_PATH = Path("docs/data/universe_filing_archive_bottleneck_review.json")
DEFAULT_STATUS_PATH = Path("docs/data/universe_filing_archive_status.json")

# Pilot caps from docs/ops/universe-filing-archive-pack.md — scale only after
# several quiet nights with isolation_ok.
PILOT_CAPS = {
    "max_units": 2,
    "max_tickers_per_unit": 2,
    "max_bodies_per_ticker": 1,
    "max_http_fetches": 8,
}

WIDEN_CRITERIA = (
    "Several quiet apply nights with capacity_isolation.isolation_ok=true "
    "and no shared 429/runner collision vs euro maintenance or spare sprints"
)

RUNBOOK = "docs/ops/universe-filing-archive-pack.md"


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _safe_read(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _hours_since(as_of: datetime | None, *, now: datetime) -> float | None:
    if as_of is None:
        return None
    return round(max(0.0, (now - as_of).total_seconds() / 3600.0), 2)


def _outcome_badge(outcome: str, *, dry_run: bool, errors: list[Any]) -> str:
    key = str(outcome or "").strip().lower()
    if key == "error" or errors:
        return "fail"
    if key in {"suspend", "quiet_only"}:
        return "warn"
    if key in {"apply_complete", "dry_complete"}:
        return "ok"
    if dry_run:
        return "ok"
    return "warn" if key else "missing"


def _next_widen_step(
    *,
    outcome: str,
    dry_run: bool,
    isolation: dict[str, Any],
    gate: dict[str, Any],
    errors: list[Any],
    caps: dict[str, Any],
) -> dict[str, Any]:
    """Return actionable next-widen guidance (observe-only; never auto-widens)."""
    max_units = caps.get("max_units", PILOT_CAPS["max_units"])
    max_fetches = caps.get("max_http_fetches", PILOT_CAPS["max_http_fetches"])
    caps_label = f"max_units={max_units}, max_http_fetches={max_fetches}"

    key = str(outcome or "").strip().lower()
    pressure = list(gate.get("focus_pressure_reasons") or [])
    isolation_ok = isolation.get("isolation_ok")
    shared = bool(isolation.get("shared_critical_path"))
    fourth = bool(isolation.get("fourth_equal_sprint_stream"))

    if key in {"suspend", "quiet_only"} or gate.get("allowed") is False:
        reason = ", ".join(str(r) for r in pressure) if pressure else key or "gate_block"
        return {
            "id": "wait_gate",
            "label": "Hold widen — wait for archive_lane_gate allow",
            "detail": (
                f"Last outcome={key or 'unknown'} ({reason}). "
                "Do not raise caps until quiet allow nights resume."
            ),
            "current_caps": caps,
            "widen_criteria": WIDEN_CRITERIA,
        }

    if errors or key == "error":
        first = str(errors[0]) if errors else "see bottleneck review"
        return {
            "id": "fix_failures",
            "label": "Hold widen — fix last-run failures first",
            "detail": f"Errors on last pass (first={first[:160]}). Keep {caps_label}.",
            "current_caps": caps,
            "widen_criteria": WIDEN_CRITERIA,
        }

    if shared or fourth or isolation_ok is False:
        return {
            "id": "hold_isolation",
            "label": "Hold widen — capacity isolation not clean",
            "detail": (
                f"isolation_ok={isolation_ok}, shared_critical_path={shared}, "
                f"fourth_equal_sprint_stream={fourth}. Keep {caps_label}."
            ),
            "current_caps": caps,
            "widen_criteria": WIDEN_CRITERIA,
        }

    if dry_run or key == "dry_complete":
        return {
            "id": "need_apply_nights",
            "label": "Next: quiet --apply nights (still hold scale)",
            "detail": (
                "Last pass was dry/plan-only. Cron should run thin --apply; "
                f"accumulate several isolation_ok apply nights before raising {caps_label}."
            ),
            "current_caps": caps,
            "widen_criteria": WIDEN_CRITERIA,
        }

    if isolation_ok is True and not dry_run:
        return {
            "id": "accumulate_quiet_nights",
            "label": "Next widen: after several quiet isolation_ok nights",
            "detail": (
                f"Last apply looked isolated. Keep {caps_label} until "
                f"{WIDEN_CRITERIA.lower()}; then raise max_units / fetch caps gradually."
            ),
            "current_caps": caps,
            "widen_criteria": WIDEN_CRITERIA,
        }

    return {
        "id": "observe",
        "label": "Observe — hold pilot caps",
        "detail": f"Keep {caps_label}. {WIDEN_CRITERIA}.",
        "current_caps": caps,
        "widen_criteria": WIDEN_CRITERIA,
    }


def build_universe_filing_archive_status(
    *,
    pack_run: dict[str, Any] | None = None,
    bottleneck: dict[str, Any] | None = None,
    pack_run_path: Path = DEFAULT_PACK_RUN_PATH,
    bottleneck_path: Path = DEFAULT_BOTTLENECK_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble compact Ops status from last pack run + bottleneck review."""
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    else:
        clock = clock.astimezone(UTC)

    run = _as_dict(pack_run if pack_run is not None else _safe_read(Path(pack_run_path)))
    review = _as_dict(bottleneck if bottleneck is not None else _safe_read(Path(bottleneck_path)))

    present = bool(run)
    generated_at = _parse_dt(run.get("generated_at"))
    outcome = str(run.get("outcome") or "")
    dry_run = bool(run.get("dry_run", True)) if present else True
    gate = _as_dict(run.get("gate"))
    isolation = _as_dict(run.get("capacity_isolation") or review.get("capacity_isolation"))
    errors = [str(e) for e in _as_list(review.get("errors"))]
    if not errors and outcome == "error":
        errors = ["pack_run outcome=error"]

    caps = dict(PILOT_CAPS)
    assemble_caps = _as_dict(run.get("assemble_caps"))
    if run.get("max_units") is not None:
        caps["max_units"] = run.get("max_units")
    for key in ("max_tickers_per_unit", "max_bodies_per_ticker", "max_http_fetches"):
        if assemble_caps.get(key) is not None:
            caps[key] = assemble_caps.get(key)
        elif run.get(key) is not None:
            caps[key] = run.get(key)

    clash_flags = {
        "isolation_ok": isolation.get("isolation_ok"),
        "shared_critical_path": bool(isolation.get("shared_critical_path")) if isolation else None,
        "fourth_equal_sprint_stream": bool(
            run.get("fourth_equal_sprint_stream")
            if run.get("fourth_equal_sprint_stream") is not None
            else isolation.get("fourth_equal_sprint_stream")
        )
        if present
        else None,
        "preemptible": bool(run.get("preemptible", True)) if present else None,
        "focus_pressure": bool(_as_list(gate.get("focus_pressure_reasons"))),
        "gate_decision": gate.get("decision"),
        "in_quiet_window": gate.get("in_quiet_window"),
    }

    next_widen = _next_widen_step(
        outcome=outcome,
        dry_run=dry_run,
        isolation=isolation,
        gate=gate,
        errors=errors,
        caps=caps,
    )

    badge = _outcome_badge(outcome, dry_run=dry_run, errors=errors) if present else "missing"
    throughput = _as_dict(review.get("throughput"))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "id": "universe_filing_archive_pack",
        "title": "Cold-store archive pack",
        "observe_only": True,
        "auto_fixable": False,
        "present": present,
        "runbook": RUNBOOK,
        "last_run": {
            "at": run.get("generated_at"),
            "hours_since": _hours_since(generated_at, now=clock),
            "run_id": run.get("run_id"),
            "outcome": outcome or None,
            "dry_run": dry_run if present else None,
            "mode": ("dry" if dry_run else "apply") if present else None,
            "badge": badge,
            "pack_order": run.get("pack_order"),
            "units_attempted": run.get("units_attempted", throughput.get("units_attempted")),
            "units_completed": run.get("units_completed", throughput.get("units_completed")),
            "objects_written": run.get("objects_written", throughput.get("objects_written")),
            "plan_unit_count": run.get("plan_unit_count"),
            "errors": errors[:5],
            "error_count": len(errors),
            "dominant_stage": (_as_dict(review.get("dominant_stage")).get("id")),
            "bottleneck_count": len(_as_list(review.get("bottlenecks"))),
        },
        "capacity_isolation": isolation or None,
        "clash_flags": clash_flags,
        "current_caps": caps,
        "next_widen_step": next_widen,
        "note": (
            "Thin Ops status from last pack_run + bottleneck review. "
            "Does not eng-spray or auto-widen (N180/N181)."
            if present
            else "No pack_run artifact yet — weekday 22:00 UTC workflow writes it."
        ),
    }


def write_universe_filing_archive_status(
    *,
    pack_run: dict[str, Any] | None = None,
    bottleneck: dict[str, Any] | None = None,
    pack_run_path: Path = DEFAULT_PACK_RUN_PATH,
    bottleneck_path: Path = DEFAULT_BOTTLENECK_PATH,
    status_path: Path = DEFAULT_STATUS_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist ``universe_filing_archive_status.json`` and return the payload."""
    payload = build_universe_filing_archive_status(
        pack_run=pack_run,
        bottleneck=bottleneck,
        pack_run_path=pack_run_path,
        bottleneck_path=bottleneck_path,
        now=now,
    )
    write_json(Path(status_path), payload)
    return payload


__all__ = [
    "DEFAULT_BOTTLENECK_PATH",
    "DEFAULT_PACK_RUN_PATH",
    "DEFAULT_STATUS_PATH",
    "PILOT_CAPS",
    "WIDEN_CRITERIA",
    "build_universe_filing_archive_status",
    "write_universe_filing_archive_status",
]
