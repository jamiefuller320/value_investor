"""Instrument-specific observe-utilization dashboard rollup (L461).

Surfaces buy-tier flip-lag and FTSE decision-input inventory beyond ops-monitor
overall status: warn state, cohort / gap counts, freshness, and trajectory
deltas vs the prior cycle.

Observe-only — does not rememo, deepen ingest, or dispatch engineering.
Persists a slim history series in ``docs/data/observe_utilization.json``
(committed via ops-monitor / queue-health refresh). Full day-over-day of the
raw instrument stores remains optional (L460).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

DEFAULT_STORE_PATH = Path("docs/data/observe_utilization.json")
DEFAULT_OPS_STATUS_PATH = Path("docs/data/ops_status.json")
DEFAULT_FLIP_LAG_PATH = Path("docs/data/buy_tier_flip_lag.json")
DEFAULT_DECISION_INPUT_PATH = Path("docs/data/decision_input_inventory.json")

SCHEMA_VERSION = 1
# Ops-monitor runs ~2×/day; past this the surface is obviously stale.
DEFAULT_STALE_AFTER_HOURS = 30.0
# Store lag vs ops run_at (L460 gap: runner refresh not committed).
DEFAULT_STORE_LAG_WARN_HOURS = 2.0
HISTORY_KEEP = 28
# Min gap between history points when metrics are unchanged.
HISTORY_MIN_INTERVAL_HOURS = 6.0

FLIP_LAG_FINDING_TITLE = "New buy-tier not yet usable"
DECISION_INPUT_FINDING_TITLE = "FTSE decision-input utilization gap"

_WARN_COUNT_RE = re.compile(r"^(\d+)\s+recent buy-tier flip", re.I)
_GAP_COUNT_RE = re.compile(r"(\d+)\s+of\s+\d+\s+names", re.I)


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


def _hours_since(then: datetime | None, *, now: datetime) -> float | None:
    if then is None:
        return None
    return round((now - then).total_seconds() / 3600.0, 2)


def _safe_read(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _findings_by_title(ops_status: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not ops_status:
        return out
    for row in ops_status.get("findings") or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if title:
            out[title] = row
    return out


def _freshness_block(
    *,
    as_of: datetime | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
    present: bool,
) -> dict[str, Any]:
    age_h = _hours_since(as_of, now=now)
    store_lag_h = None
    if as_of is not None and ops_run_at is not None and ops_run_at > as_of:
        store_lag_h = round((ops_run_at - as_of).total_seconds() / 3600.0, 2)

    if not present:
        state = "missing"
        label = "Missing"
        detail = "Instrument store not published yet."
    elif age_h is None:
        state = "unknown"
        label = "Unknown"
        detail = "Store present but no usable timestamp."
    elif age_h >= stale_after_hours:
        state = "stale"
        label = "Stale"
        detail = f"Last refresh {age_h:.1f}h ago (limit {stale_after_hours:.0f}h)."
    elif store_lag_h is not None and store_lag_h >= store_lag_warn_hours:
        state = "lagging"
        label = "Lagging ops"
        detail = (
            f"Store trails ops_status by {store_lag_h:.1f}h "
            f"(ops-monitor may not commit instrument JSON — L460)."
        )
    else:
        state = "fresh"
        label = "Fresh"
        detail = f"Last refresh {age_h:.1f}h ago."

    return {
        "state": state,
        "label": label,
        "detail": detail,
        "as_of": as_of.isoformat() if as_of else None,
        "age_hours": age_h,
        "store_lag_hours": store_lag_h,
        "stale_after_hours": float(stale_after_hours),
    }


def _delta(current: int | float | None, previous: int | float | None) -> dict[str, Any]:
    if current is None or previous is None:
        return {
            "delta": None,
            "direction": "unknown",
            "label": "No prior cycle",
        }
    try:
        cur_f = float(current)
        prev_f = float(previous)
    except (TypeError, ValueError):
        return {"delta": None, "direction": "unknown", "label": "No prior cycle"}
    delta = cur_f - prev_f
    # Lower warn/gap counts = improving for these instruments.
    if abs(delta) < 1e-9:
        direction = "flat"
        label = "Unchanged vs last cycle"
    elif delta < 0:
        direction = "improving"
        label = "Better since last cycle"
    else:
        direction = "worsening"
        label = "Worse since last cycle"
    # Prefer int display when whole numbers.
    if float(delta).is_integer():
        delta_out: int | float = int(delta)
    else:
        delta_out = round(delta, 2)
    return {"delta": delta_out, "direction": direction, "label": label}


def _flip_lag_instrument(
    *,
    store: dict[str, Any] | None,
    finding: dict[str, Any] | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
) -> dict[str, Any]:
    summary = (store or {}).get("summary") or {}
    warn_count = summary.get("warn_not_usable")
    open_count = summary.get("open_not_usable")
    cohort_count = summary.get("cohort_count")
    if warn_count is None and finding:
        match = _WARN_COUNT_RE.match(str(finding.get("summary") or ""))
        if match:
            warn_count = int(match.group(1))
    as_of = _parse_dt((store or {}).get("updated_at"))
    freshness = _freshness_block(
        as_of=as_of,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=store is not None,
    )
    warn_active = finding is not None or (
        isinstance(warn_count, (int, float)) and int(warn_count) > 0
    )
    return {
        "id": "buy_tier_flip_lag",
        "title": "Buy-tier flip → usable",
        "finding_title": FLIP_LAG_FINDING_TITLE,
        "observe_only": True,
        "warn_active": bool(warn_active),
        "severity": (finding or {}).get("severity")
        if finding
        else ("warn" if warn_active else "ok"),
        "finding_summary": (finding or {}).get("summary"),
        "metrics": {
            "warn_not_usable": int(warn_count) if warn_count is not None else None,
            "open_not_usable": int(open_count) if open_count is not None else None,
            "cohort_count": int(cohort_count) if cohort_count is not None else None,
            "usable_in_window": summary.get("usable_in_window"),
            "market_count": summary.get("market_count"),
            "blocking_stage_counts": summary.get("blocking_stage_counts") or {},
        },
        "primary_metric": "warn_not_usable",
        "primary_value": int(warn_count) if warn_count is not None else None,
        "primary_label": "Warn cohort (≥24h path-incomplete)",
        "freshness": freshness,
    }


def _decision_input_instrument(
    *,
    store: dict[str, Any] | None,
    finding: dict[str, Any] | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
) -> dict[str, Any]:
    summary = (store or {}).get("summary") or {}
    rollup = (store or {}).get("rollup") or {}
    gap_counts = dict(summary.get("gap_counts") or rollup.get("gap_counts") or {})
    dominant = str(
        rollup.get("dominant_gap_field")
        or summary.get("verdict")
        or summary.get("sunday_bind_field")
        or ""
    )
    if dominant in {"", "P1 green-enough"}:
        dominant_count = 0
    else:
        dominant_count = gap_counts.get(dominant)
        if dominant_count is None and finding:
            match = _GAP_COUNT_RE.search(str(finding.get("summary") or ""))
            if match:
                dominant_count = int(match.group(1))
    as_of = _parse_dt((store or {}).get("generated_at") or (store or {}).get("updated_at"))
    freshness = _freshness_block(
        as_of=as_of,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=store is not None,
    )
    verdict = str(summary.get("verdict") or rollup.get("verdict") or "—")
    warn_active = finding is not None or (
        verdict not in {"P1 green-enough", "—", ""}
        and isinstance(dominant_count, (int, float))
        and int(dominant_count) >= 3
    )
    return {
        "id": "decision_input_inventory",
        "title": "FTSE decision-input inventory",
        "finding_title": DECISION_INPUT_FINDING_TITLE,
        "observe_only": True,
        "warn_active": bool(warn_active),
        "severity": (finding or {}).get("severity")
        if finding
        else ("warn" if warn_active else "ok"),
        "finding_summary": (finding or {}).get("summary"),
        "metrics": {
            "inventory_count": summary.get("inventory_count") or rollup.get("inventory_count"),
            "fully_ready_count": summary.get("fully_ready_count")
            or rollup.get("fully_ready_count"),
            "names_with_any_gap": summary.get("names_with_any_gap")
            or rollup.get("names_with_any_gap"),
            "dominant_gap_field": dominant or None,
            "dominant_gap_count": int(dominant_count) if dominant_count is not None else None,
            "gap_counts": gap_counts,
            "verdict": verdict,
        },
        "primary_metric": "dominant_gap_count",
        "primary_value": int(dominant_count) if dominant_count is not None else None,
        "primary_label": (
            f"Dominant gap ({dominant})"
            if dominant and dominant != "P1 green-enough"
            else "Dominant gap"
        ),
        "freshness": freshness,
    }


def _history_point(instruments: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    point: dict[str, Any] = {"at": now.isoformat()}
    for inst in instruments:
        point[inst["id"]] = {
            "primary_value": inst.get("primary_value"),
            "warn_active": bool(inst.get("warn_active")),
            "freshness_state": (inst.get("freshness") or {}).get("state"),
        }
    return point


def _append_history(
    prior: dict[str, Any] | None,
    point: dict[str, Any],
    *,
    now: datetime,
    keep: int = HISTORY_KEEP,
    min_interval_hours: float = HISTORY_MIN_INTERVAL_HOURS,
) -> list[dict[str, Any]]:
    history = list((prior or {}).get("history") or [])
    if history:
        last = history[-1]
        last_at = _parse_dt(last.get("at"))
        same_metrics = all(last.get(key) == point.get(key) for key in point if key != "at")
        if (
            same_metrics
            and last_at is not None
            and (now - last_at) < timedelta(hours=min_interval_hours)
        ):
            return history[-keep:]
    history.append(point)
    return history[-keep:]


def _attach_trajectory(
    instruments: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> None:
    prior_point = history[-2] if len(history) >= 2 else None
    for inst in instruments:
        iid = inst["id"]
        prev_row = (prior_point or {}).get(iid) if prior_point else None
        prev_val = (prev_row or {}).get("primary_value") if isinstance(prev_row, dict) else None
        traj = _delta(inst.get("primary_value"), prev_val)
        traj["prior_value"] = prev_val
        traj["prior_at"] = (prior_point or {}).get("at")
        inst["trajectory"] = traj


def build_observe_utilization_snapshot(
    *,
    flip_lag_path: Path = DEFAULT_FLIP_LAG_PATH,
    decision_input_path: Path = DEFAULT_DECISION_INPUT_PATH,
    ops_status_path: Path = DEFAULT_OPS_STATUS_PATH,
    prior_path: Path = DEFAULT_STORE_PATH,
    now: datetime | None = None,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    store_lag_warn_hours: float = DEFAULT_STORE_LAG_WARN_HOURS,
) -> dict[str, Any]:
    """Build instrument cards + freshness + trajectory for the dashboard."""
    clock = now or datetime.now(UTC)
    ops_status = _safe_read(Path(ops_status_path))
    findings = _findings_by_title(ops_status)
    ops_run_at = _parse_dt((ops_status or {}).get("run_at"))
    flip_store = _safe_read(Path(flip_lag_path))
    decision_store = _safe_read(Path(decision_input_path))
    prior = _safe_read(Path(prior_path))

    instruments = [
        _flip_lag_instrument(
            store=flip_store,
            finding=findings.get(FLIP_LAG_FINDING_TITLE),
            now=clock,
            ops_run_at=ops_run_at,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
        ),
        _decision_input_instrument(
            store=decision_store,
            finding=findings.get(DECISION_INPUT_FINDING_TITLE),
            now=clock,
            ops_run_at=ops_run_at,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
        ),
    ]

    history = _append_history(prior, _history_point(instruments, now=clock), now=clock)
    _attach_trajectory(instruments, history)

    freshness_states = [(inst.get("freshness") or {}).get("state") for inst in instruments]
    if "missing" in freshness_states:
        surface_freshness = "degraded"
    elif "stale" in freshness_states:
        surface_freshness = "stale"
    elif "lagging" in freshness_states:
        surface_freshness = "lagging"
    elif all(s == "fresh" for s in freshness_states):
        surface_freshness = "fresh"
    else:
        surface_freshness = "unknown"

    warn_count = sum(1 for inst in instruments if inst.get("warn_active"))
    improving = sum(
        1 for inst in instruments if (inst.get("trajectory") or {}).get("direction") == "improving"
    )
    worsening = sum(
        1 for inst in instruments if (inst.get("trajectory") or {}).get("direction") == "worsening"
    )

    if surface_freshness in {"stale", "degraded"}:
        headline = "Observe utilization surface is stale/incomplete — do not trust absolute counts."
    elif surface_freshness == "lagging":
        headline = (
            "Instrument stores lag ops_status (likely uncommitted runner JSON) — "
            "trajectory uses this dashboard series."
        )
    elif warn_count and worsening:
        headline = f"{warn_count} warn instrument(s); trajectory worsening on {worsening}."
    elif warn_count and improving:
        headline = f"{warn_count} warn instrument(s); improving vs last cycle on {improving}."
    elif warn_count:
        headline = f"{warn_count} observe utilization warn(s) — cohorts need attention."
    elif improving:
        headline = "Observe utilization quiet; trajectory improving."
    else:
        headline = "Observe utilization quiet (P1 path looks green-enough)."

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "observe_only": True,
        "headline": headline,
        "surface_freshness": surface_freshness,
        "ops_run_at": ops_run_at.isoformat() if ops_run_at else None,
        "warn_instrument_count": warn_count,
        "trajectory_summary": {
            "improving": improving,
            "worsening": worsening,
            "flat": sum(
                1
                for inst in instruments
                if (inst.get("trajectory") or {}).get("direction") == "flat"
            ),
            "unknown": sum(
                1
                for inst in instruments
                if (inst.get("trajectory") or {}).get("direction") == "unknown"
            ),
            "history_points": len(history),
            "note": (
                "Deltas vs prior dashboard cycle (warn/gap counts; lower is better). "
                "Full instrument-store git history is optional (L460)."
            ),
        },
        "instruments": instruments,
        "history": history,
    }


def refresh_observe_utilization(
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    flip_lag_path: Path = DEFAULT_FLIP_LAG_PATH,
    decision_input_path: Path = DEFAULT_DECISION_INPUT_PATH,
    ops_status_path: Path = DEFAULT_OPS_STATUS_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write ``observe_utilization.json`` and return the snapshot."""
    store_path = Path(store_path)
    snapshot = build_observe_utilization_snapshot(
        flip_lag_path=flip_lag_path,
        decision_input_path=decision_input_path,
        ops_status_path=ops_status_path,
        prior_path=store_path,
        now=now,
    )
    store_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(store_path, snapshot, compact=False)
    return snapshot


__all__ = [
    "DECISION_INPUT_FINDING_TITLE",
    "DEFAULT_DECISION_INPUT_PATH",
    "DEFAULT_FLIP_LAG_PATH",
    "DEFAULT_OPS_STATUS_PATH",
    "DEFAULT_STALE_AFTER_HOURS",
    "DEFAULT_STORE_LAG_WARN_HOURS",
    "DEFAULT_STORE_PATH",
    "FLIP_LAG_FINDING_TITLE",
    "SCHEMA_VERSION",
    "build_observe_utilization_snapshot",
    "refresh_observe_utilization",
]
