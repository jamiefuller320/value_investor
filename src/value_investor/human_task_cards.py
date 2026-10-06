"""Human-task board: enrich checklist rows with existing analysis + ack sort.

Does not invent a second data plane — snippets come from committed ops artifacts
already produced by analysis-review / project-traffic / eng queue / etc.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.cohort_selection_fitness import MIN_SCORE_GAP_FOR_PRIOR
from value_investor.experiment_acks import apply_ack_to_experiment
from value_investor.experiment_acks import load_acks as load_experiment_acks
from value_investor.human_task_acks import (
    annotate_task_ack,
    load_human_task_acks,
    matching_ack,
    record_human_task_ack,
)
from value_investor.human_tasks_checklist import doc_url_for_task, load_human_tasks_checklist
from value_investor.storage import read_json, write_json

BOARD_FILENAME = "human_tasks_board.json"
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_CHECKLIST_PATH = Path("docs/human_tasks_checklist.json")

# Observe-only review gate — never promote. Auto-ack when priors show no discrimination.
KNOB_PRIORS_REVIEW_TASK_ID = "sunday-knob-calibration-priors"
_LOW_PRIOR_CONFIDENCE = frozenset({"low", "insufficient"})

SHADOW_ENDURANCE_TASK_ID = "sunday-shadow-endurance"

# Observe-only residual triage after recover-queue — auto-ack when queue is quiet.
PARKED_BACKLOG_CLEAR_TASK_ID = "weekday-engineering-parked-backlog-clear"

# Fail closes the promote/knob path — never counts as Sunday "do now" urgency.
_SHADOW_FAIL_KINDS = frozenset({"calibration_shadow", "exclusion_shadow"})
# Recommend rows that can still mean a Sunday promote / overlay gate is open.
_SUNDAY_BLOCKING_RECOMMEND_KINDS = frozenset(
    {
        "calibration_shadow",
        "exclusion_shadow",
        "experimental_paper_track",
        "lifecycle_overlay",
    }
)
# Recommend ≠ do-now spray: eng queue / manual capacity strands.
_CAPACITY_RECOMMEND_KINDS = frozenset(
    {
        "analysis_task",
        "paper_learning_task",
        "learning_director_task",
    }
)

# Task ids that are capital / promotion gates — show Approve (observe record only).

# Task ids that are capital / promotion gates — show Approve (observe record only).
APPROVAL_GATE_IDS: dict[str, str] = {
    "sunday-phase-c-readiness-gate": "Approve Phase C start",
    "sunday-assessment-scoreboard": "Approve promotion",
    "monthly-euro-depth-parity": "Approve Phase 3 / AI gate",
    "monthly-cycle-budget-surplus": "Approve surplus bump",
    "adhoc-live-capital-pack": "Approve live capital",
}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _read(data_dir: Path, name: str) -> dict[str, Any]:
    try:
        raw = read_json(Path(data_dir) / name)
    except FileNotFoundError:
        return {}
    return _as_dict(raw)


def _fingerprint(parts: dict[str, Any]) -> str:
    """Content hash for ack-staleness. Do not include republish timestamps —
    those alone must not bounce an acked card back to new_info / live Acknowledge.
    """
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _load_knob_calibration_priors(data_dir: Path) -> dict[str, Any]:
    priors = _read(data_dir, "paper_automation/knob_calibration_priors.json")
    if not priors:
        priors = _read(data_dir, "knob_calibration_priors.json")
    return priors


def _iter_knob_prior_tracks(priors: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Yield (track_id, track_payload) for multi-track or single-track priors."""
    tracks = priors.get("tracks")
    if isinstance(tracks, dict) and tracks:
        return [(str(tid), _as_dict(payload)) for tid, payload in tracks.items()]
    if priors.get("readiness") or priors.get("recommended_prior"):
        tid = str(priors.get("track_id") or "default")
        return [(tid, priors)]
    return []


def knob_priors_ack_sufficient(priors: dict[str, Any] | None) -> dict[str, Any]:
    """True when every track has low/insufficient confidence and no score gap.

    Policy: Sunday "Review knob calibration priors" is satisfied by Acknowledge
    (observe-only) when there is nothing to discriminate — never auto-promote.
    """
    priors = _as_dict(priors)
    rows: list[dict[str, Any]] = []
    for track_id, track in _iter_knob_prior_tracks(priors):
        readiness = _as_dict(track.get("readiness"))
        recommended = _as_dict(track.get("recommended_prior"))
        confidence = str(recommended.get("confidence") or "").strip().lower()
        raw_gap = readiness.get("score_gap_vs_runner_up")
        try:
            gap = float(raw_gap) if raw_gap is not None else None
        except (TypeError, ValueError):
            gap = None
        low_conf = confidence in _LOW_PRIOR_CONFIDENCE
        no_discrimination = gap is not None and gap < float(MIN_SCORE_GAP_FOR_PRIOR)
        rows.append(
            {
                "track_id": track_id,
                "confidence": confidence or None,
                "score_gap_vs_runner_up": gap,
                "low_confidence": low_conf,
                "no_discrimination": no_discrimination,
                "ready_for_priors": readiness.get("ready_for_priors"),
                "ready_for_shadow_bootstrap": readiness.get("ready_for_shadow_bootstrap"),
            }
        )
    if not rows:
        return {
            "ack_sufficient": False,
            "reason": "no_tracks",
            "tracks": [],
            "min_score_gap_for_prior": float(MIN_SCORE_GAP_FOR_PRIOR),
        }
    ack_sufficient = all(
        bool(row.get("low_confidence")) and bool(row.get("no_discrimination")) for row in rows
    )
    return {
        "ack_sufficient": ack_sufficient,
        "reason": (
            "low_confidence_and_no_discrimination" if ack_sufficient else "needs_manual_review"
        ),
        "tracks": rows,
        "min_score_gap_for_prior": float(MIN_SCORE_GAP_FOR_PRIOR),
    }


def apply_knob_priors_observe_auto_ack(data_dir: Path) -> dict[str, Any] | None:
    """Record observe-only ack when priors show no discrimination.

    Never records approve / never touches promotion gates or live knobs.
    Idempotent when an open ack already matches the live fingerprint.
    """
    data_dir = Path(data_dir)
    priors = _load_knob_calibration_priors(data_dir)
    status = knob_priors_ack_sufficient(priors)
    if not status.get("ack_sufficient"):
        return None
    analysis = _analysis_for_task(KNOB_PRIORS_REVIEW_TASK_ID, data_dir)
    fingerprint = str(analysis.get("fingerprint") or "").strip()
    if not fingerprint:
        return None
    store = load_human_task_acks(data_dir)
    existing = matching_ack(store, task_id=KNOB_PRIORS_REVIEW_TASK_ID)
    if existing:
        decision = str(existing.get("decision") or "").strip()
        if decision == "approve":
            # Human already elevated — leave alone (still never auto-promote).
            return None
        if (
            decision == "ack_observe"
            and str(existing.get("finding_fingerprint") or "").strip() == fingerprint
        ):
            return None
    return record_human_task_ack(
        data_dir,
        task_id=KNOB_PRIORS_REVIEW_TASK_ID,
        decision="ack_observe",
        note=(
            "Auto-ack observe-only: knob priors low confidence and "
            f"score_gap_vs_runner_up < {MIN_SCORE_GAP_FOR_PRIOR} (no discrimination). "
            "Promotion remains a separate human gate."
        ),
        finding_fingerprint=fingerprint,
        source="board_auto_no_discrimination",
        acked_by="system",
    )


def _experiment_rows(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in (assessment.get("experiments") or assessment.get("rows") or [])
        if isinstance(row, dict)
    ]


def experiment_assessment_gate_status(
    assessment: dict[str, Any] | None,
    *,
    experiment_acks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify ledger rows for the Sunday unified-assessment review gate.

    Policy:
    - ``fail`` calibration/exclusion shadows close the knob promote path — not urgency.
    - Already human-acked recommend rows do not inflate "do now".
    - ``analysis_task`` / learning-task recommends are capacity/eng or observe strands,
      not this Sunday gate's blocking urgency.
    - ``ack_sufficient`` when zero *blocking* unacked recommends remain.
    - Never auto-promote.
    """
    assessment = _as_dict(assessment)
    experiments = _experiment_rows(assessment)
    annotated = [apply_ack_to_experiment(dict(row), experiment_acks) for row in experiments]

    failed_shadows: list[dict[str, Any]] = []
    recommend_raw: list[dict[str, Any]] = []
    recommend_acked: list[dict[str, Any]] = []
    recommend_blocking: list[dict[str, Any]] = []
    recommend_capacity: list[dict[str, Any]] = []

    for row in annotated:
        eid = str(row.get("experiment_id") or "").strip()
        kind = str(row.get("kind") or "").strip()
        status = str(row.get("status") or "").strip()
        slim = {
            "experiment_id": eid,
            "kind": kind,
            "status": status,
            "area": row.get("area"),
            "human_acked": bool(row.get("human_acked")),
            "acked_at": row.get("acked_at"),
        }
        if status == "fail" and kind in _SHADOW_FAIL_KINDS:
            failed_shadows.append(slim)
            continue
        if status != "recommend":
            continue
        recommend_raw.append(slim)
        if row.get("human_acked") or row.get("human_ack_required") is False:
            recommend_acked.append(slim)
            continue
        if kind in _CAPACITY_RECOMMEND_KINDS:
            recommend_capacity.append(slim)
            continue
        if kind in _SUNDAY_BLOCKING_RECOMMEND_KINDS or not kind:
            recommend_blocking.append(slim)
            continue
        # Unknown kind — treat as capacity/observe, not promote urgency.
        recommend_capacity.append(slim)

    ack_sufficient = len(recommend_blocking) == 0
    if ack_sufficient and not experiments:
        reason = "no_experiments"
        ack_sufficient = False
    elif ack_sufficient and not recommend_raw and not failed_shadows:
        reason = "empty_board_review_ok"
    elif ack_sufficient and failed_shadows and not recommend_blocking:
        reason = "failed_shadows_close_promote_no_blocking_recommend"
    elif ack_sufficient and recommend_acked and not recommend_blocking:
        reason = "acked_and_capacity_only"
    elif ack_sufficient:
        reason = "no_blocking_recommend"
    else:
        reason = "blocking_recommend_open"

    summary = _as_dict(assessment.get("summary"))
    return {
        "ack_sufficient": ack_sufficient,
        "reason": reason,
        "failed_shadows": failed_shadows,
        "recommend_raw_count": len(recommend_raw),
        "recommend_acked": recommend_acked,
        "recommend_blocking": recommend_blocking,
        "recommend_capacity": recommend_capacity,
        "human_ack_pending": int(summary.get("human_ack_pending") or 0),
        "summary_recommend": int(summary.get("recommend") or len(recommend_raw)),
        "summary_fail": int(summary.get("fail") or 0),
        "total_experiments": len(experiments),
    }


def apply_experiment_assessment_observe_auto_ack(data_dir: Path) -> dict[str, Any] | None:
    """Record observe-only ack when the Sunday assessment gate has no blocking recommends.

    Never records approve / never touches promotion gates, knobs, or experiment promote.
    Idempotent when an open ack already matches the live fingerprint.
    """
    data_dir = Path(data_dir)
    assessment = _read(data_dir, "experiment_assessment.json")
    if not assessment:
        return None
    status = experiment_assessment_gate_status(
        assessment,
        experiment_acks=load_experiment_acks(data_dir),
    )
    if not status.get("ack_sufficient"):
        return None
    analysis = _analysis_for_task(SHADOW_ENDURANCE_TASK_ID, data_dir)
    fingerprint = str(analysis.get("fingerprint") or "").strip()
    if not fingerprint:
        return None
    store = load_human_task_acks(data_dir)
    existing = matching_ack(store, task_id=SHADOW_ENDURANCE_TASK_ID)
    if existing:
        decision = str(existing.get("decision") or "").strip()
        if decision == "approve":
            return None
        if (
            decision == "ack_observe"
            and str(existing.get("finding_fingerprint") or "").strip() == fingerprint
        ):
            return None
    return record_human_task_ack(
        data_dir,
        task_id=SHADOW_ENDURANCE_TASK_ID,
        decision="ack_observe",
        note=(
            "Auto-ack observe-only: no blocking Sunday recommend "
            f"({status.get('reason')}). Failed shadows close promote; "
            "acked overlays / capacity ana-* strands are not do-now. "
            "Never auto-promote."
        ),
        finding_fingerprint=fingerprint,
        source="board_auto_assessment_gate",
        acked_by="system",
    )


def _bullet(text: str) -> str:
    return str(text or "").strip()


def _market_rows(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize market_status markets (list or id→row dict) for analysis cards."""
    raw = status.get("markets")
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict):
        rows: list[dict[str, Any]] = []
        for mid, row in raw.items():
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item.setdefault("market_id", mid)
            rows.append(item)
        return rows
    return []


def _admitted_market_rows(status: dict[str, Any]) -> list[dict[str, Any]]:
    admitted_ids = {
        str(mid).strip() for mid in (status.get("admitted_markets") or []) if str(mid or "").strip()
    }
    rows = _market_rows(status)
    if admitted_ids:
        hit = [row for row in rows if str(row.get("market_id") or "").strip() in admitted_ids]
        if hit:
            return hit
    return [row for row in rows if bool(row.get("is_admitted"))]


def parked_backlog_ack_sufficient(eng: dict[str, Any] | None) -> dict[str, Any]:
    """True when recover-queue left the parked gate quiet (nothing to triage).

    Policy: Acknowledge (observe-only) when ``attention_parked_count=0`` and
    ``queue_clearing.pause_active=false``. Human triage remains when the
    cap-8 pause / warning still fires after recover-queue. Never unparks,
    cancels, or resumes dispatch from this ack.
    """
    eng = _as_dict(eng)
    queue_clearing = _as_dict(eng.get("queue_clearing"))
    tasks = [t for t in (eng.get("tasks") or []) if isinstance(t, dict)]
    parked = [t for t in tasks if str(t.get("status") or "") == "parked"]
    attention_rows = [
        t
        for t in parked
        if str(t.get("park_kind") or t.get("attention") or "attention") != "ignore"
    ]
    raw_count = queue_clearing.get("attention_parked_count")
    try:
        attention_count = int(raw_count) if raw_count is not None else len(attention_rows)
    except (TypeError, ValueError):
        attention_count = len(attention_rows)
    pause_active = bool(queue_clearing.get("pause_active"))
    ack_sufficient = attention_count == 0 and not pause_active
    if ack_sufficient:
        reason = "quiet_zero_attention_no_pause"
    elif pause_active:
        reason = "queue_clearing_pause_active"
    else:
        reason = "attention_parked_remaining"
    return {
        "ack_sufficient": ack_sufficient,
        "reason": reason,
        "attention_parked_count": attention_count,
        "pause_active": pause_active,
        "parked_count": len(parked),
    }


def apply_parked_backlog_observe_auto_ack(data_dir: Path) -> dict[str, Any] | None:
    """Record observe-only ack when the parked-backlog gate is quiet.

    Never records approve / never unparks, cancels, or resumes the eng queue.
    Idempotent when an open ack already matches the live fingerprint.
    """
    data_dir = Path(data_dir)
    eng = _read(data_dir, "engineering_tasks.json")
    if not eng:
        return None
    status = parked_backlog_ack_sufficient(eng)
    if not status.get("ack_sufficient"):
        return None
    analysis = _analysis_for_task(PARKED_BACKLOG_CLEAR_TASK_ID, data_dir)
    fingerprint = str(analysis.get("fingerprint") or "").strip()
    if not fingerprint:
        return None
    store = load_human_task_acks(data_dir)
    existing = matching_ack(store, task_id=PARKED_BACKLOG_CLEAR_TASK_ID)
    if existing:
        decision = str(existing.get("decision") or "").strip()
        if decision == "approve":
            return None
        if (
            decision == "ack_observe"
            and str(existing.get("finding_fingerprint") or "").strip() == fingerprint
        ):
            return None
    return record_human_task_ack(
        data_dir,
        task_id=PARKED_BACKLOG_CLEAR_TASK_ID,
        decision="ack_observe",
        note=(
            "Auto-ack observe-only: attention_parked_count=0 and "
            "queue_clearing.pause_active=false after recover-queue. "
            "Human triage remains when pause/warning still fires."
        ),
        finding_fingerprint=fingerprint,
        source="board_auto_quiet_parked_backlog",
        acked_by="system",
    )


def _analysis_for_task(task_id: str, data_dir: Path) -> dict[str, Any]:
    """Slim analysis view from existing artifacts. Empty when nothing published."""
    tid = str(task_id or "").strip()

    if tid == PARKED_BACKLOG_CLEAR_TASK_ID:
        eng = _read(data_dir, "engineering_tasks.json")
        tasks = [t for t in (eng.get("tasks") or []) if isinstance(t, dict)]
        parked = [t for t in tasks if str(t.get("status") or "") == "parked"]
        attention = [
            t
            for t in parked
            if str(t.get("park_kind") or t.get("attention") or "attention") != "ignore"
        ]
        queue_clearing = _as_dict(eng.get("queue_clearing"))
        traffic = _as_dict(eng.get("traffic_control"))
        status = parked_backlog_ack_sufficient(eng)
        attention_count = int(status.get("attention_parked_count") or 0)
        pause_active = bool(status.get("pause_active"))
        bullets = [
            _bullet(f"Parked tasks: {len(parked)} (attention ~{attention_count})"),
            _bullet(
                f"Queue-clearing pause active: {pause_active}"
                + (
                    f" — evaluated {queue_clearing.get('evaluated_at')}"
                    if queue_clearing.get("evaluated_at")
                    else ""
                )
            ),
            _bullet(
                f"Traffic pause active: {bool(traffic.get('pause_active'))}"
                + (f" — {traffic.get('reason')}" if traffic.get("reason") else "")
            ),
        ]
        if status.get("ack_sufficient"):
            bullets.insert(
                0,
                _bullet(
                    "Quiet after recover-queue — observe Acknowledge is sufficient "
                    "(no list-parked triage)."
                ),
            )
        oldest = sorted(
            attention,
            key=lambda row: str(row.get("parked_at") or row.get("updated_at") or ""),
        )[:5]
        for row in oldest:
            bullets.append(
                _bullet(
                    f"{row.get('id') or '?'}: {row.get('title') or row.get('park_reason') or 'parked'}"
                )
            )
        # Fingerprint stays on parked set + queue-clearing pause (gate surface).
        # When quiet, pause is False — same hash as prior traffic-False quiet snaps.
        fp = _fingerprint(
            {
                "n": len(parked),
                "ids": [str(t.get("id")) for t in oldest],
                "pause": pause_active,
            }
        )
        if status.get("ack_sufficient"):
            headline = f"{attention_count} attention-parked eng tasks · quiet (auto-ackable)"
        else:
            headline = f"{attention_count} attention-parked eng tasks"
        return {
            "headline": headline,
            "updated_at": eng.get("updated_at")
            or eng.get("generated_at")
            or queue_clearing.get("evaluated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["engineering_tasks"],
            "ack_sufficient": bool(status.get("ack_sufficient")),
            "auto_ackable": bool(status.get("ack_sufficient")),
            "ack_reason": status.get("reason"),
        }

    if tid == "sunday-read-analysis-review":
        review = _read(data_dir, "analysis_review.json")
        chart = _read(data_dir, "chart_outcome_review.json")
        bullets = []
        if review.get("summary"):
            bullets.append(_bullet(str(review.get("summary"))[:280]))
        mix = _as_dict(chart.get("mix") or chart.get("outcome_mix"))
        if mix:
            bullets.append(
                _bullet(
                    "Chart-outcome mix: " + ", ".join(f"{k}={v}" for k, v in list(mix.items())[:6])
                )
            )
        fp = _fingerprint({"summary": review.get("summary"), "mix": mix})
        return {
            "headline": "Sunday analysis review synthesis",
            "updated_at": review.get("generated_at")
            or review.get("updated_at")
            or chart.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["analysis_review", "chart_outcome_review"],
        }

    if tid == "sunday-phase-c-readiness-gate":
        ready = _read(data_dir, "phase_c_readiness.json")
        status = str(ready.get("status") or ready.get("readiness") or "unknown")
        blockers = ready.get("blockers") or ready.get("missing") or []
        bullets = [_bullet(f"Status: {status}")]
        if isinstance(blockers, list):
            for item in blockers[:5]:
                bullets.append(_bullet(str(item)))
        elif blockers:
            bullets.append(_bullet(str(blockers)))
        fp = _fingerprint({"status": status, "blockers": blockers})
        return {
            "headline": f"Phase C readiness: {status}",
            "updated_at": ready.get("generated_at") or ready.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["phase_c_readiness"],
        }

    if tid in {"sunday-shard-epoch0-watch", "sunday-buy-cross-archive"}:
        if tid == "sunday-buy-cross-archive":
            payload = _read(data_dir, "buy_cross_archive_review.json")
            bullets = []
            if payload.get("summary"):
                bullets.append(_bullet(str(payload.get("summary"))[:280]))
            for key in ("cross_vs_level", "week_0_cash", "never_entered"):
                if payload.get(key) is not None:
                    bullets.append(_bullet(f"{key}: {payload.get(key)}"))
            fp = _fingerprint(
                {
                    "summary": payload.get("summary"),
                    "cross_vs_level": payload.get("cross_vs_level"),
                    "week_0_cash": payload.get("week_0_cash"),
                    "never_entered": payload.get("never_entered"),
                }
            )
            return {
                "headline": "Buy-cross archive review",
                "updated_at": payload.get("generated_at") or payload.get("updated_at"),
                "fingerprint": fp,
                "bullets": [b for b in bullets if b][:8],
                "source_keys": ["buy_cross_archive_review"],
            }
        # shard epoch-0 watch — market_status admitted books (markets is a list)
        status = _read(data_dir, "market_status.json")
        admitted = _admitted_market_rows(status)
        bullets = []
        snap: list[dict[str, Any]] = []
        for row in admitted[:12]:
            mid = str(row.get("market_id") or "?")
            epoch0 = _as_dict(row.get("epoch0"))
            learning = _as_dict(row.get("learning"))
            ai = epoch0.get("ai_judgment")
            knob = epoch0.get("knob_apply")
            phase = learning.get("current_phase")
            holdings = epoch0.get("holdings")
            bullets.append(
                _bullet(
                    f"{mid}: phase={phase if phase is not None else '—'} "
                    f"ai={ai} knob={knob} holdings={holdings if holdings is not None else '—'}"
                )
            )
            snap.append(
                {
                    "id": mid,
                    "ai": ai,
                    "knob": knob,
                    "acted": epoch0.get("acted"),
                    "phase": phase,
                    "blockers": learning.get("blockers"),
                }
            )
        fp = _fingerprint(
            {
                "admitted": sorted(str(x) for x in (status.get("admitted_markets") or [])),
                "snap": snap,
            }
        )
        return {
            "headline": f"Admitted shard epoch-0 watch · {len(admitted)}",
            "updated_at": status.get("generated_at") or status.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["market_status"],
        }

    if tid == KNOB_PRIORS_REVIEW_TASK_ID:
        assessment = _read(data_dir, "experiment_assessment.json")
        priors = _load_knob_calibration_priors(data_dir)
        status = knob_priors_ack_sufficient(priors)
        track_rows = list(status.get("tracks") or [])
        bullets = [
            _bullet(
                "Review gate = confirm readiness signals; Acknowledge is enough when "
                "confidence is low and score gap shows no discrimination."
            ),
            _bullet(
                f"ack_sufficient={status.get('ack_sufficient')} "
                f"reason={status.get('reason')} "
                f"(gap floor {status.get('min_score_gap_for_prior')})"
            ),
        ]
        for row in track_rows[:6]:
            bullets.append(
                _bullet(
                    f"{row.get('track_id')}: conf={row.get('confidence')} "
                    f"gap={row.get('score_gap_vs_runner_up')} "
                    f"ready_priors={row.get('ready_for_priors')} "
                    f"ready_shadow={row.get('ready_for_shadow_bootstrap')}"
                )
            )
        if status.get("ack_sufficient"):
            bullets.append(
                _bullet(
                    "No discrimination → Acknowledge (observe-only); do not promote. "
                    "Promotion is sunday-assessment-scoreboard."
                )
            )
        fp = _fingerprint(
            {
                "task": KNOB_PRIORS_REVIEW_TASK_ID,
                "ack_sufficient": bool(status.get("ack_sufficient")),
                "reason": status.get("reason"),
                "tracks": [
                    {
                        "track_id": row.get("track_id"),
                        "confidence": row.get("confidence"),
                        "gap": row.get("score_gap_vs_runner_up"),
                        "ready_priors": row.get("ready_for_priors"),
                        "ready_shadow": row.get("ready_for_shadow_bootstrap"),
                    }
                    for row in track_rows
                ],
            }
        )
        headline = (
            "Knob priors · ack sufficient (no discrimination)"
            if status.get("ack_sufficient")
            else "Knob priors · manual review"
        )
        return {
            "headline": headline,
            "updated_at": priors.get("calibrated_at")
            or priors.get("generated_at")
            or assessment.get("generated_at")
            or assessment.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["knob_calibration_priors", "experiment_assessment"],
            "ack_sufficient": bool(status.get("ack_sufficient")),
            "auto_ackable": bool(status.get("ack_sufficient")),
            "knob_priors_status": status,
        }

    if tid == SHADOW_ENDURANCE_TASK_ID:
        assessment = _read(data_dir, "experiment_assessment.json")
        status = experiment_assessment_gate_status(
            assessment,
            experiment_acks=load_experiment_acks(data_dir),
        )
        fail_ids = [str(r.get("experiment_id")) for r in (status.get("failed_shadows") or [])]
        blocking = list(status.get("recommend_blocking") or [])
        acked = list(status.get("recommend_acked") or [])
        capacity = list(status.get("recommend_capacity") or [])
        bullets = [
            _bullet(
                "Sunday gate = read fail / continue / recommend. "
                "Recommend ≠ do-now spray; failed shadows close promote; "
                "acked overlays do not inflate urgency."
            ),
            _bullet(
                f"ack_sufficient={status.get('ack_sufficient')} reason={status.get('reason')} "
                f"blocking={len(blocking)} acked_recommend={len(acked)} "
                f"capacity={len(capacity)} fail_shadows={len(fail_ids)} "
                f"raw_recommend={status.get('recommend_raw_count')}"
            ),
        ]
        if fail_ids:
            bullets.append(
                _bullet("Failed shadows (close knob path, not promote): " + ", ".join(fail_ids[:6]))
            )
        for row in blocking[:3]:
            bullets.append(_bullet(f"blocking: {row.get('experiment_id')} ({row.get('kind')})"))
        for row in acked[:2]:
            bullets.append(
                _bullet(
                    f"acked: {row.get('experiment_id')} "
                    f"at={str(row.get('acked_at') or '')[:10] or '—'}"
                )
            )
        for row in capacity[:3]:
            bullets.append(
                _bullet(
                    f"capacity/eng|manual: {row.get('experiment_id')} area={row.get('area') or '—'}"
                )
            )
        if status.get("ack_sufficient"):
            bullets.append(
                _bullet(
                    "No blocking Sunday recommend → Acknowledge (observe-only). "
                    "Never auto-promote. ana-* strands stay on eng/manual checklists."
                )
            )
        fp = _fingerprint(
            {
                "task": SHADOW_ENDURANCE_TASK_ID,
                "ack_sufficient": bool(status.get("ack_sufficient")),
                "reason": status.get("reason"),
                "blocking": [r.get("experiment_id") for r in blocking],
                "acked": [r.get("experiment_id") for r in acked],
                "capacity": [r.get("experiment_id") for r in capacity],
                "fail_shadows": fail_ids,
            }
        )
        n_block = len(blocking)
        headline = (
            "Experiment assessment · review ok (0 blocking)"
            if status.get("ack_sufficient")
            else f"Experiment assessment · {n_block} blocking recommend"
        )
        return {
            "headline": headline,
            "updated_at": assessment.get("generated_at") or assessment.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["experiment_assessment", "experiment_acks"],
            "ack_sufficient": bool(status.get("ack_sufficient")),
            "auto_ackable": bool(status.get("ack_sufficient")),
            "experiment_assessment_gate": status,
        }

    if tid == "sunday-assessment-scoreboard":
        board = _read(data_dir, "assessment_scoreboard.json")
        rows = [r for r in board.get("tracks") or [] if isinstance(r, dict)]
        primary = next((r for r in rows if r.get("role") == "primary"), {})
        stats = _as_dict(primary.get("statistics"))
        gate = _as_dict(primary.get("ai_gate"))
        comparison = _as_dict(board.get("primary_vs_control"))
        twins = [t for t in board.get("twins") or [] if isinstance(t, dict)]
        policies = [p for p in board.get("policy_changes") or [] if isinstance(p, dict)]
        bullets = [
            _bullet(str(board.get("headline") or "Scoreboard not built yet.")),
            _bullet(
                f"Primary verdict: {stats.get('verdict') or stats.get('status') or '—'} "
                f"· 90% interval {stats.get('ci90') or '—'} "
                f"· excess at 3% stress {primary.get('excess_total_return_at_stress_cost')}"
            ),
            _bullet(
                f"vs control {comparison.get('control') or '—'}: "
                f"difference {comparison.get('difference')} (common window, not significance)"
            ),
            _bullet(f"AI gate binds: {gate.get('binds')} (N189 while it never binds)"),
        ]
        for twin in twins[:2]:
            bullets.append(
                _bullet(
                    f"twin {twin.get('track_id')}: difference {twin.get('difference')} "
                    f"over {twin.get('common_days')} days"
                    + (
                        f" · CONFOUNDED by {twin.get('parent_knobs_changed')}"
                        if twin.get("parent_knobs_changed")
                        else ""
                    )
                )
            )
        if policies:
            bullets.append(
                _bullet(
                    "Policy changes: "
                    + ", ".join(
                        f"{p.get('id')} ({str(p.get('effective_at'))[:10]})" for p in policies
                    )
                )
            )
        fp = _fingerprint(
            {
                "primary": board.get("primary_track"),
                "control": board.get("control_track"),
                "verdict": stats.get("verdict") or stats.get("status"),
                "gate_binds": gate.get("binds"),
                "twins": [
                    (t.get("track_id"), t.get("status"), bool(t.get("parent_knobs_changed")))
                    for t in twins
                ],
                "policies": [p.get("id") for p in policies],
            }
        )
        return {
            "headline": f"Assessment scoreboard · primary {stats.get('verdict') or 'not scored'}",
            "updated_at": board.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["assessment_scoreboard"],
        }

    if tid == "sunday-entry-dca-cadence":
        plan = _read(data_dir, "entry_dca_adoption_plan.json")
        stage = plan.get("adoption_stage") or plan.get("stage") or "—"
        ready = _as_dict(plan.get("readiness") or plan.get("gates"))
        bullets = [
            _bullet(f"Adoption stage: {stage}"),
            _bullet(f"paper_execute_graduated ready: {ready.get('paper_execute_graduated')}"),
            _bullet("Acknowledge is observe-only — use Lifecycle Start to execute."),
        ]
        fp = _fingerprint({"stage": stage, "ready": ready})
        return {
            "headline": f"Entry DCA adoption · {stage}",
            "updated_at": plan.get("updated_at") or plan.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["entry_dca_adoption_plan"],
        }

    if tid == "sunday-sleeve-episodes-readiness":
        # Prefer learning_tracks_review sidecar fields if present under data
        review = _read(data_dir, "paper_learning_review.json")
        sleeve = _as_dict(
            review.get("sleeve_episodes") or review.get("learning_tracks_sleeve_episodes")
        )
        ready = _as_dict(sleeve.get("readiness"))
        bullets = [
            _bullet(
                f"ready_for_sleeve_timing_analysis={ready.get('ready_for_sleeve_timing_analysis')}"
            ),
            _bullet(
                f"closed cohorts: {sleeve.get('closed_counts') or sleeve.get('counts') or '—'}"
            ),
        ]
        fp = _fingerprint(
            {
                "ready": ready,
                "closed": sleeve.get("closed_counts") or sleeve.get("counts"),
            }
        )
        return {
            "headline": "Dual-path sleeve episodes readiness",
            "updated_at": review.get("generated_at") or review.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["paper_learning_review"],
        }

    if tid == "sunday-hypothesis-integrity":
        # Look for per-track hypothesis under paper automation is heavy; use review summary
        review = _read(data_dir, "paper_learning_review.json")
        hi = _as_dict(
            review.get("hypothesis_integrity") or review.get("learning_tracks_hypothesis_integrity")
        )
        bullets = [
            _bullet(f"within_tolerance={hi.get('within_tolerance')}"),
            _bullet(f"broken_loser_count={hi.get('broken_loser_count')}"),
            _bullet(f"flags={hi.get('selection_feedback_flags') or hi.get('flags') or '—'}"),
        ]
        fp = _fingerprint({"hi": hi})
        return {
            "headline": "Hypothesis integrity",
            "updated_at": review.get("generated_at") or review.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["paper_learning_review"],
        }

    if tid in {"sunday-analysis-tasks", "sunday-triage-plr-director-tasks"}:
        path = (
            "analysis_tasks.json" if tid == "sunday-analysis-tasks" else "paper_learning_tasks.json"
        )
        payload = _read(data_dir, path)
        tasks = [
            t for t in (payload.get("tasks") or payload.get("items") or []) if isinstance(t, dict)
        ]
        open_tasks = [
            t
            for t in tasks
            if str(t.get("status") or "open") in {"open", "proposed", "watch", "continue"}
        ]
        bullets = [_bullet(f"Open/proposed: {len(open_tasks)} / {len(tasks)}")]
        for row in open_tasks[:5]:
            bullets.append(
                _bullet(f"{row.get('id') or '?'}: {row.get('title') or row.get('status')}")
            )
        fp = _fingerprint({"ids": [str(t.get("id")) for t in open_tasks[:10]]})
        return {
            "headline": f"Triage queue · {len(open_tasks)} open",
            "updated_at": payload.get("updated_at") or payload.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": [path.replace(".json", "")],
        }

    if tid == "monthly-horizon-scan":
        scan = _read(data_dir, "horizon_scan.json")
        bullets = [
            _bullet(
                f"Open fragments: {scan.get('open_fragment_count') or scan.get('open_count') or '—'}"
            ),
            _bullet(f"Suggested promotes: {scan.get('promote_count') or '—'}"),
        ]
        if scan.get("summary"):
            bullets.append(_bullet(str(scan.get("summary"))[:280]))
        fp = _fingerprint(
            {
                "open": scan.get("open_fragment_count") or scan.get("open_count"),
                "promote": scan.get("promote_count"),
                "summary": scan.get("summary"),
            }
        )
        return {
            "headline": "Horizon scan + deferred fragments",
            "updated_at": scan.get("generated_at") or scan.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["horizon_scan"],
        }

    if tid == "monthly-cycle-budget-surplus":
        surplus = _read(data_dir, "cycle_budget_surplus.json")
        bullets = [
            _bullet(f"Decision: {surplus.get('decision') or surplus.get('status') or '—'}"),
            _bullet(f"Unused Ultra fraction: {surplus.get('unused_ultra_fraction') or '—'}"),
        ]
        fp = _fingerprint(
            {
                "decision": surplus.get("decision") or surplus.get("status"),
                "unused": surplus.get("unused_ultra_fraction"),
            }
        )
        return {
            "headline": "Cycle-end Cursor surplus",
            "updated_at": surplus.get("updated_at") or surplus.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["cycle_budget_surplus"],
        }

    if tid == "monthly-pr-fix-common-issues":
        occasions = _read(data_dir, "pr_fix_occasions.json")
        digest = _read(data_dir, "project_traffic_digest.json")
        common = _as_dict(occasions.get("common_issues") or digest.get("pr_fix_common_issues"))
        top = common.get("by_reason") or common.get("reasons") or common.get("top") or []
        bullets = [_bullet(f"Occasions logged: {len(occasions.get('occasions') or [])}")]
        top_snap: list[dict[str, Any]] = []
        if isinstance(top, list):
            for row in top[:5]:
                if isinstance(row, dict):
                    reason = row.get("failure_reason") or row.get("reason") or row.get("key") or "?"
                    bullets.append(_bullet(f"{reason}: {row.get('count')}"))
                    top_snap.append({"r": reason, "c": row.get("count")})
                else:
                    bullets.append(_bullet(str(row)))
                    top_snap.append({"r": str(row)})
        elif isinstance(top, dict):
            for key, val in list(top.items())[:5]:
                bullets.append(_bullet(f"{key}: {val}"))
                top_snap.append({"r": key, "c": val})
        fp = _fingerprint(
            {
                "n": len(occasions.get("occasions") or []),
                "top": top_snap,
            }
        )
        return {
            "headline": "PR fix common issues",
            "updated_at": occasions.get("updated_at") or digest.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["pr_fix_occasions", "project_traffic_digest"],
        }

    if tid == "adhoc-review-ingest-deviations":
        payload = _read(data_dir, "ingest_deviations.json")
        open_items = [
            row
            for row in (payload.get("open_items") or payload.get("items") or [])
            if isinstance(row, dict) and (not row.get("status") or row.get("status") == "open")
        ]
        bullets = [_bullet(f"Open deviations: {len(open_items)}")]
        for row in open_items[:5]:
            bullets.append(
                _bullet(f"{row.get('ticker')}: {row.get('kind')} — {row.get('summary')}")
            )
        fp = _fingerprint(
            {
                "n": len(open_items),
                "ids": [str(r.get("id") or r.get("ticker")) for r in open_items[:10]],
            }
        )
        return {
            "headline": f"Ingest deviations · {len(open_items)} open",
            "updated_at": payload.get("updated_at") or payload.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["ingest_deviations"],
        }

    if tid == "quarterly-deferred-review":
        # deferred-review.md is generated; horizon_tasks may hold promotes
        tasks = _read(data_dir, "horizon_tasks.json")
        items = [t for t in (tasks.get("tasks") or tasks.get("items") or []) if isinstance(t, dict)]
        bullets = [_bullet(f"Horizon/deferred triage items: {len(items)}")]
        for row in items[:5]:
            bullets.append(_bullet(f"{row.get('id')}: {row.get('title') or row.get('status')}"))
        fp = _fingerprint(
            {
                "n": len(items),
                "ids": [str(t.get("id")) for t in items[:10]],
            }
        )
        return {
            "headline": "Deferred ideas review",
            "updated_at": tasks.get("updated_at") or tasks.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["horizon_tasks"],
        }

    # Generic fallback — checklist summary only
    return {
        "headline": "See runbook for analysis inputs",
        "updated_at": None,
        "fingerprint": _fingerprint({"task_id": tid, "generic": True}),
        "bullets": [],
        "source_keys": [],
    }


def _sort_bucket(ack: dict[str, Any]) -> str:
    if ack.get("stale"):
        return "new_info"
    if not ack.get("acked"):
        return "unacked"
    return "acked"


_BUCKET_RANK = {"new_info": 0, "unacked": 1, "acked": 2}


def build_human_tasks_board(
    *,
    data_dir: Path | None = None,
    checklist_path: Path | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    checklist = load_human_tasks_checklist(checklist_path or DEFAULT_CHECKLIST_PATH)
    acks = load_human_task_acks(data_dir)
    repo_docs_base = str(checklist.get("repo_docs_base") or "")
    human_rows: list[dict[str, Any]] = []
    automated_rows: list[dict[str, Any]] = []

    for section in checklist.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for task in section.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                continue
            analysis = _analysis_for_task(task_id, data_dir)
            fingerprint = str(analysis.get("fingerprint") or "")
            ack = annotate_task_ack(task, acks, fingerprint=fingerprint)
            approval_label = APPROVAL_GATE_IDS.get(task_id)
            # Checklist may override
            if task.get("approval_gate") is False:
                approval_label = None
            elif task.get("approval_gate") and not approval_label:
                approval_label = str(task.get("approval_label") or "Approve")
            row = {
                "id": task_id,
                "title": task.get("title"),
                "summary": task.get("summary"),
                "automated": bool(task.get("automated")),
                "cadence": section.get("cadence"),
                "section_id": section.get("id"),
                "section_title": section.get("title"),
                "doc_path": task.get("doc_path"),
                "doc_anchor": task.get("doc_anchor"),
                "doc_url": doc_url_for_task(task, repo_docs_base=repo_docs_base),
                "approval_gate": bool(approval_label),
                "approval_label": approval_label,
                "analysis": analysis,
                "ack": ack,
                "sort_bucket": _sort_bucket(ack) if not task.get("automated") else "automated",
                "auto_ackable": bool(analysis.get("auto_ackable")),
                "ack_sufficient": bool(analysis.get("ack_sufficient")),
            }
            if row["automated"]:
                automated_rows.append(row)
            else:
                human_rows.append(row)

    open_rows = [r for r in human_rows if r.get("sort_bucket") in {"new_info", "unacked"}]
    acked_rows = [r for r in human_rows if r.get("sort_bucket") == "acked"]

    by_bucket: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in open_rows:
        by_bucket[_BUCKET_RANK.get(str(row.get("sort_bucket")), 9)].append(row)
    open_ordered: list[dict[str, Any]] = []
    for bucket in sorted(by_bucket):
        group = by_bucket[bucket]
        present = [r for r in group if _as_dict(r.get("analysis")).get("updated_at")]
        missing = [r for r in group if not _as_dict(r.get("analysis")).get("updated_at")]
        present.sort(
            key=lambda row: str(_as_dict(row.get("analysis")).get("updated_at") or ""),
            reverse=True,
        )
        missing.sort(key=lambda row: str(row.get("id") or ""))
        open_ordered.extend(present + missing)
    acked_rows.sort(
        key=lambda row: str(_as_dict(row.get("ack")).get("acked_at") or ""),
        reverse=True,
    )
    ordered = open_ordered + acked_rows

    counts = {
        "new_info": sum(1 for r in ordered if r.get("sort_bucket") == "new_info"),
        "unacked": sum(1 for r in ordered if r.get("sort_bucket") == "unacked"),
        "acked": sum(1 for r in ordered if r.get("sort_bucket") == "acked"),
        "automated": len(automated_rows),
        "human": len(ordered),
    }
    return {
        "schema_version": 1,
        "generated_at": _utcnow(),
        "title": checklist.get("title") or "Human tasks",
        "summary": checklist.get("summary"),
        "runbook_path": checklist.get("runbook_path"),
        "repo_docs_base": repo_docs_base,
        "checklist_updated_at": checklist.get("updated_at"),
        "counts": counts,
        "tasks": ordered,
        "automated_tasks": automated_rows,
    }


def write_human_tasks_board(
    *,
    data_dir: Path | None = None,
    checklist_path: Path | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    # Observe-safe: when priors show no discrimination, Satisfy the review gate
    # with ack_observe so Daily hub / Human tasks do not demand a deep weekly
    # review. Never auto-promotes knobs.
    apply_knob_priors_observe_auto_ack(data_dir)
    # Observe-safe: when Sunday assessment has no blocking recommends, ack_observe
    # the review card (failed shadows / acked overlays / capacity ana-* ≠ do-now).
    # Never auto-promotes experiments.
    apply_experiment_assessment_observe_auto_ack(data_dir)
    # Observe-safe: when recover-queue left zero attention-parked and no
    # queue_clearing pause, ack the residual triage card (no list-parked work).
    # Never unparks / cancels / resumes dispatch.
    apply_parked_backlog_observe_auto_ack(data_dir)
    board = build_human_tasks_board(data_dir=data_dir, checklist_path=checklist_path)
    dest = data_dir / BOARD_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, board, compact=False)
    board["path"] = str(dest)
    return board


__all__ = [
    "APPROVAL_GATE_IDS",
    "BOARD_FILENAME",
    "KNOB_PRIORS_REVIEW_TASK_ID",
    "apply_knob_priors_observe_auto_ack",
    "build_human_tasks_board",
    "knob_priors_ack_sufficient",
    "write_human_tasks_board",
    "SHADOW_ENDURANCE_TASK_ID",
    "apply_experiment_assessment_observe_auto_ack",
    "experiment_assessment_gate_status",
    "PARKED_BACKLOG_CLEAR_TASK_ID",
    "apply_parked_backlog_observe_auto_ack",
    "parked_backlog_ack_sufficient",
]
