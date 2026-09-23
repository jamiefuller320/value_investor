"""Library maintenance capacity: crowded-slot width + automated review (L454).

Default when three-plus books share ``library-ingest-maintenance`` is **two**
markets per cron slot (sequential, full FTSE volume each). A small reviewer
looks at recent slot samples and can:

- **step_down** (auto-apply on ``--apply`` / post-run apply) if cutoffs or
  errors show the job is clipping
- **step_up** sequential width (2→3, capped) when headroom stays green
- **propose_matrix** (flag only — does not wire a second workflow) when
  sequential width is already at the cap and the roster is still crowded

The 62-name ``max_targets`` cap is separate and is usually *not* binding on
maintenance books (few unparked gaps). Binding limit is market rotation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

CAPACITY_FILENAME = "maintenance_capacity.json"
DEFAULT_MAX_MARKETS_WHEN_CROWDED = 2
MIN_MAX_MARKETS_WHEN_CROWDED = 1
MAX_SEQUENTIAL_MARKETS_WHEN_CROWDED = 3
SAMPLE_LIMIT = 24
REVIEW_MIN_SAMPLES = 4
# Soft wall vs workflow timeout-minutes: 120. Leave room for checkout / rememo.
STEP_DOWN_USED_SECONDS = 50 * 60
STEP_UP_USED_SECONDS = 35 * 60
PROPOSE_MATRIX_USED_SECONDS = 40 * 60
PROPOSE_MATRIX_MIN_CONFIGURED = 6


def capacity_path(library_root: Path) -> Path:
    return Path(library_root) / CAPACITY_FILENAME


def empty_capacity(*, now: datetime | None = None) -> dict[str, Any]:
    stamp = (now or datetime.now(UTC)).isoformat()
    return {
        "schema_version": 1,
        "updated_at": stamp,
        "max_markets_when_crowded": DEFAULT_MAX_MARKETS_WHEN_CROWDED,
        "matrix_parallel": {
            "enabled": False,
            "proposed": False,
            "proposed_at": None,
            "reason": None,
        },
        "samples": [],
        "last_review": None,
        "note": (
            "Crowded maintenance slot width (L323/L454). Default 2 markets per "
            "cron; reviewer may step 1–3 sequential or propose matrix (flag only)."
        ),
    }


def load_maintenance_capacity(
    library_root: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    path = capacity_path(library_root)
    base = empty_capacity(now=now)
    if not path.exists():
        return base
    try:
        raw = read_json(path)
    except (OSError, ValueError, TypeError):
        return base
    if not isinstance(raw, dict):
        return base
    width = int(raw.get("max_markets_when_crowded") or DEFAULT_MAX_MARKETS_WHEN_CROWDED)
    width = max(MIN_MAX_MARKETS_WHEN_CROWDED, min(MAX_SEQUENTIAL_MARKETS_WHEN_CROWDED, width))
    matrix = raw.get("matrix_parallel") if isinstance(raw.get("matrix_parallel"), dict) else {}
    samples = [row for row in (raw.get("samples") or []) if isinstance(row, dict)]
    return {
        **base,
        **{k: v for k, v in raw.items() if k not in {"samples", "matrix_parallel"}},
        "max_markets_when_crowded": width,
        "matrix_parallel": {
            "enabled": bool(matrix.get("enabled")),
            "proposed": bool(matrix.get("proposed")),
            "proposed_at": matrix.get("proposed_at"),
            "reason": matrix.get("reason"),
        },
        "samples": samples[-SAMPLE_LIMIT:],
        "last_review": raw.get("last_review"),
    }


def save_maintenance_capacity(library_root: Path, payload: dict[str, Any]) -> Path:
    path = capacity_path(library_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)
    return path


def resolve_max_markets_when_crowded(library_root: Path | None) -> int:
    if library_root is None:
        return DEFAULT_MAX_MARKETS_WHEN_CROWDED
    capacity = load_maintenance_capacity(Path(library_root))
    return int(capacity.get("max_markets_when_crowded") or DEFAULT_MAX_MARKETS_WHEN_CROWDED)


def sample_from_maintenance_outcome(outcome: dict[str, Any] | Any) -> dict[str, Any]:
    """Build one capacity sample from a maintenance run payload / result dict."""
    if hasattr(outcome, "to_dict"):
        payload = outcome.to_dict()
    elif isinstance(outcome, dict):
        payload = outcome
    else:
        payload = {}
    results = [row for row in (payload.get("results") or []) if isinstance(row, dict)]
    used = [
        float(row.get("used_seconds") or 0.0)
        for row in results
        if row.get("used_seconds") is not None
    ]
    cutoffs = sum(1 for row in results if row.get("runtime_cutoff"))
    target_counts = [len(row.get("targets") or []) for row in results]
    return {
        "run_at": payload.get("run_at") or datetime.now(UTC).isoformat(),
        "configured_count": len(payload.get("configured_markets") or []),
        "selected": list(payload.get("markets") or []),
        "selected_count": len(payload.get("markets") or []),
        "deferred_count": len(payload.get("deferred_markets") or []),
        "width": int(
            (payload.get("stagger") or {}).get("max_markets_when_crowded")
            or len(payload.get("markets") or [])
            or 0
        ),
        "staggered": bool((payload.get("stagger") or {}).get("staggered")),
        "error_count": len(payload.get("errors") or []),
        "runtime_cutoff_count": cutoffs,
        "used_seconds_total": round(sum(used), 1) if used else 0.0,
        "used_seconds_max": round(max(used), 1) if used else 0.0,
        "target_count_total": int(sum(target_counts)),
        "target_count_max": int(max(target_counts) if target_counts else 0),
        "name_cap_hit": any(n >= 62 for n in target_counts),
    }


def record_maintenance_capacity_sample(
    library_root: Path,
    outcome: dict[str, Any] | Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append a slot sample and persist capacity state."""
    library_root = Path(library_root)
    stamp = now or datetime.now(UTC)
    capacity = load_maintenance_capacity(library_root, now=stamp)
    sample = sample_from_maintenance_outcome(outcome)
    sample["width"] = int(capacity.get("max_markets_when_crowded") or sample.get("width") or 0)
    samples = list(capacity.get("samples") or [])
    samples.append(sample)
    capacity["samples"] = samples[-SAMPLE_LIMIT:]
    capacity["updated_at"] = stamp.isoformat()
    save_maintenance_capacity(library_root, capacity)
    return {"path": str(capacity_path(library_root)), "sample": sample, "capacity": capacity}


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def assess_maintenance_capacity(
    library_root: Path,
    *,
    now: datetime | None = None,
    min_samples: int = REVIEW_MIN_SAMPLES,
) -> dict[str, Any]:
    """Propose hold / step_down / step_up / propose_matrix from recent samples."""
    library_root = Path(library_root)
    stamp = now or datetime.now(UTC)
    capacity = load_maintenance_capacity(library_root, now=stamp)
    width = int(capacity.get("max_markets_when_crowded") or DEFAULT_MAX_MARKETS_WHEN_CROWDED)
    samples = [row for row in (capacity.get("samples") or []) if isinstance(row, dict)]
    # Prefer samples recorded at the current width.
    at_width = [row for row in samples if int(row.get("width") or 0) == width] or samples
    recent = at_width[-min_samples:] if at_width else []
    used_totals = [float(row.get("used_seconds_total") or 0.0) for row in recent]
    median_used = _median(used_totals)
    cutoff_count = sum(int(row.get("runtime_cutoff_count") or 0) for row in recent)
    error_count = sum(int(row.get("error_count") or 0) for row in recent)
    name_cap_hits = sum(1 for row in recent if row.get("name_cap_hit"))
    configured = max((int(row.get("configured_count") or 0) for row in recent), default=0)
    matrix = dict(capacity.get("matrix_parallel") or {})

    decision = "hold"
    reason = "insufficient_samples" if len(recent) < min_samples else "headroom_stable"
    proposed_width = width
    propose_matrix = bool(matrix.get("proposed"))

    if recent and (cutoff_count > 0 or error_count >= max(2, len(recent))):
        decision = "step_down"
        proposed_width = max(MIN_MAX_MARKETS_WHEN_CROWDED, width - 1)
        reason = "runtime_cutoff_or_errors"
    elif recent and median_used is not None and median_used >= STEP_DOWN_USED_SECONDS:
        decision = "step_down"
        proposed_width = max(MIN_MAX_MARKETS_WHEN_CROWDED, width - 1)
        reason = "median_used_seconds_high"
    elif len(recent) >= min_samples and median_used is not None:
        if (
            width < MAX_SEQUENTIAL_MARKETS_WHEN_CROWDED
            and configured >= 3
            and median_used <= STEP_UP_USED_SECONDS
            and cutoff_count == 0
            and error_count == 0
        ):
            decision = "step_up"
            proposed_width = width + 1
            reason = "sequential_headroom"
        elif (
            width >= MAX_SEQUENTIAL_MARKETS_WHEN_CROWDED
            and configured >= PROPOSE_MATRIX_MIN_CONFIGURED
            and median_used <= PROPOSE_MATRIX_USED_SECONDS
            and cutoff_count == 0
            and error_count == 0
            and not matrix.get("enabled")
        ):
            decision = "propose_matrix"
            proposed_width = width
            propose_matrix = True
            reason = "sequential_cap_still_crowded"
        else:
            decision = "hold"
            reason = "headroom_stable"

    return {
        "schema_version": 1,
        "assessed_at": stamp.isoformat(),
        "path": str(capacity_path(library_root)),
        "current_width": width,
        "proposed_width": proposed_width,
        "decision": decision,
        "reason": reason,
        "sample_count": len(recent),
        "sample_count_total": len(samples),
        "median_used_seconds": median_used,
        "runtime_cutoff_count": cutoff_count,
        "error_count": error_count,
        "name_cap_hits": name_cap_hits,
        "configured_markets_peak": configured,
        "matrix_parallel_proposed": propose_matrix,
        "matrix_parallel_enabled": bool(matrix.get("enabled")),
        "thresholds": {
            "min_samples": min_samples,
            "step_down_used_seconds": STEP_DOWN_USED_SECONDS,
            "step_up_used_seconds": STEP_UP_USED_SECONDS,
            "propose_matrix_used_seconds": PROPOSE_MATRIX_USED_SECONDS,
            "max_sequential": MAX_SEQUENTIAL_MARKETS_WHEN_CROWDED,
            "min_configured_for_matrix": PROPOSE_MATRIX_MIN_CONFIGURED,
        },
        "apply_safe": decision in {"step_down", "step_up", "propose_matrix", "hold"},
        "note": (
            "Name cap (62 targets) hits are informational — usually not binding. "
            "Matrix stays a proposal flag until a separate workflow is wired."
        ),
    }


def apply_maintenance_capacity_review(
    assessment: dict[str, Any],
    *,
    library_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist width / matrix proposal from an assessment."""
    library_root = Path(library_root)
    stamp = now or datetime.now(UTC)
    capacity = load_maintenance_capacity(library_root, now=stamp)
    decision = str(assessment.get("decision") or "hold")
    before = int(capacity.get("max_markets_when_crowded") or DEFAULT_MAX_MARKETS_WHEN_CROWDED)
    after = before
    matrix = dict(capacity.get("matrix_parallel") or {})

    if decision == "step_down":
        after = max(
            MIN_MAX_MARKETS_WHEN_CROWDED,
            int(assessment.get("proposed_width") or before - 1),
        )
    elif decision == "step_up":
        after = min(
            MAX_SEQUENTIAL_MARKETS_WHEN_CROWDED,
            int(assessment.get("proposed_width") or before + 1),
        )
    elif decision == "propose_matrix":
        matrix["proposed"] = True
        matrix["proposed_at"] = stamp.isoformat()
        matrix["reason"] = assessment.get("reason")
        matrix["enabled"] = False

    after = max(MIN_MAX_MARKETS_WHEN_CROWDED, min(MAX_SEQUENTIAL_MARKETS_WHEN_CROWDED, after))
    capacity["max_markets_when_crowded"] = after
    capacity["matrix_parallel"] = matrix
    capacity["last_review"] = {
        **assessment,
        "applied_at": stamp.isoformat(),
        "width_before": before,
        "width_after": after,
    }
    capacity["updated_at"] = stamp.isoformat()
    save_maintenance_capacity(library_root, capacity)
    return {
        "applied": True,
        "decision": decision,
        "width_before": before,
        "width_after": after,
        "matrix_parallel": matrix,
        "path": str(capacity_path(library_root)),
        "capacity": capacity,
    }


def review_maintenance_capacity(
    library_root: Path,
    *,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assess capacity and optionally apply step_up / step_down / matrix proposal."""
    assessment = assess_maintenance_capacity(library_root, now=now)
    result = {"assessment": assessment, "applied": False}
    if apply and assessment.get("decision") in {"step_down", "step_up", "propose_matrix"}:
        result.update(
            apply_maintenance_capacity_review(assessment, library_root=library_root, now=now)
        )
    elif apply:
        # Still stamp last_review on hold so ops can see the check ran.
        capacity = load_maintenance_capacity(Path(library_root), now=now)
        capacity["last_review"] = {**assessment, "applied_at": None}
        capacity["updated_at"] = (now or datetime.now(UTC)).isoformat()
        save_maintenance_capacity(Path(library_root), capacity)
        result["capacity"] = capacity
        result["applied"] = False
    return result


__all__ = [
    "CAPACITY_FILENAME",
    "DEFAULT_MAX_MARKETS_WHEN_CROWDED",
    "MAX_SEQUENTIAL_MARKETS_WHEN_CROWDED",
    "MIN_MAX_MARKETS_WHEN_CROWDED",
    "apply_maintenance_capacity_review",
    "assess_maintenance_capacity",
    "capacity_path",
    "empty_capacity",
    "load_maintenance_capacity",
    "record_maintenance_capacity_sample",
    "resolve_max_markets_when_crowded",
    "review_maintenance_capacity",
    "sample_from_maintenance_outcome",
    "save_maintenance_capacity",
]
