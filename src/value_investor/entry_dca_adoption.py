"""Deliberate review / implementation plan for the entry-DCA overlay.

Ack is not adopt. This module scores the next gates from the overlay rollup,
human ack sidecar, and paper-track metrics. It never executes DCA or edits
paper-book config.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.experiment_acks import load_acks, matching_ack
from value_investor.storage import read_json, write_json

PLAN_FILENAME = "entry_dca_adoption_plan.json"
TARGET_CADENCE = "dca_4x_weekly"
GRADUATED_MARKS_MIN = 8
AI_JUDGMENT_FIRST_ENTRY_MIN = 3
RULES_FIRST_ENTRY_MIN = 1
FAIR_TRACKS = ("ai_judgment_fair", "rules_fair")
LIVE_BOOKS = ("ai_judgment", "rules")


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _safe_read(path: Path) -> dict[str, Any]:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return {}
    return raw if isinstance(raw, dict) else {}


def first_entry_by_track(rollup: dict[str, Any] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    tracks = _as_dict(_as_dict(rollup).get("tracks"))
    for track_id, row in tracks.items():
        if not isinstance(row, dict):
            continue
        kinds = _as_dict(row.get("entry_kind_counts"))
        out[str(track_id)] = int(kinds.get("first_entry") or 0)
    return out


def winning_cadence_by_track(rollup: dict[str, Any] | None) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    tracks = _as_dict(_as_dict(rollup).get("tracks"))
    for track_id, row in tracks.items():
        if not isinstance(row, dict):
            continue
        counts = _as_dict(row.get("winning_cadence_counts"))
        if not counts:
            out[str(track_id)] = None
            continue
        out[str(track_id)] = max(counts.items(), key=lambda item: int(item[1] or 0))[0]
    return out


def _track_metrics(review: dict[str, Any] | None, track_id: str) -> dict[str, Any]:
    reviews = _as_dict(_as_dict(review).get("reviews"))
    return _as_dict(_as_dict(reviews.get(track_id)).get("metrics"))


def _stage(
    *,
    stage_id: str,
    title: str,
    status: str,
    ready: bool,
    revisit_when: str,
    do_not: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": stage_id,
        "title": title,
        "status": status,
        "ready": ready,
        "revisit_when": revisit_when,
        "do_not": do_not,
        "evidence": evidence,
    }


def evaluate_entry_dca_adoption_plan(
    *,
    data_dir: Path,
    paper_root: Path | None = None,
) -> dict[str, Any]:
    """Return the current DCA review/implementation plan (observe-only)."""
    data_dir = Path(data_dir)
    paper_root = Path(paper_root or data_dir / "paper_automation")
    rollup = _safe_read(paper_root / "learning_tracks_entry_dca.json")
    review = _safe_read(paper_root / "learning_tracks_review.json")
    acks = load_acks(data_dir)
    first_entry = first_entry_by_track(rollup)
    winners = winning_cadence_by_track(rollup)
    leading = str(rollup.get("leading_cadence") or "") or None
    ready_cadence = bool(_as_dict(rollup.get("readiness")).get("ready_for_cadence_analysis"))
    finding = {
        "leading_cadence": leading,
        "ready_for_cadence_analysis": ready_cadence,
        "scored_count": rollup.get("scored_count"),
        "tracks_with_closed": rollup.get("tracks_with_closed"),
        "model_independent_hint": rollup.get("model_independent_hint"),
        "first_entry_by_track": first_entry,
    }
    ack = matching_ack(acks, experiment_id="entry_dca_overlay", finding=finding)
    ack_finding = _as_dict((ack or {}).get("finding"))
    snapshot = _as_dict(ack_finding.get("first_entry_by_track"))

    acked = ack is not None and ready_cadence
    cadence_stable = leading == TARGET_CADENCE and bool(rollup.get("model_independent_hint"))
    ai_first = first_entry.get("ai_judgment", 0)
    rules_first = first_entry.get("rules", 0)
    ai_needed = max(AI_JUDGMENT_FIRST_ENTRY_MIN, int(snapshot.get("ai_judgment") or 0) + 1)
    rules_needed = max(RULES_FIRST_ENTRY_MIN, int(snapshot.get("rules") or 0) + 1)
    live_first_entry_ok = ai_first >= ai_needed and rules_first >= rules_needed
    fair_ok = True
    fair_winners: dict[str, str | None] = {}
    for track_id in FAIR_TRACKS:
        count = first_entry.get(track_id, 0)
        winner = winners.get(track_id)
        fair_winners[track_id] = winner
        if count > 0 and winner not in {None, TARGET_CADENCE}:
            fair_ok = False
    out_of_sample_ready = bool(acked and cadence_stable and live_first_entry_ok and fair_ok)

    graduated = _track_metrics(review, "graduated_allocation")
    graduated_marks = int(graduated.get("equity_marks") or 0)
    execute_ready = out_of_sample_ready and graduated_marks >= GRADUATED_MARKS_MIN

    fair_primary = _track_metrics(review, "ai_judgment_fair") or _track_metrics(
        review, "ai_judgment"
    )
    beat_market = fair_primary.get("beat_market")
    if beat_market is None:
        beat_market = _as_dict(review).get("beat_market")
    live_ready = bool(execute_ready and beat_market is True)

    stages = [
        _stage(
            stage_id="acked",
            title="Human ack of overlay finding (observe only)",
            status="done" if acked else "open",
            ready=acked,
            revisit_when="Human records ftse-experiment-assess ack for entry_dca_overlay",
            do_not="Ack is not adopt — do not execute DCA or change starter fraction",
            evidence={
                "acked": acked,
                "acked_at": None if ack is None else ack.get("acked_at"),
                "leading_cadence": leading,
                "ready_for_cadence_analysis": ready_cadence,
            },
        ),
        _stage(
            stage_id="out_of_sample_first_entry",
            title="Confirm 4× weekly on new first-entry closes (live books)",
            status="done" if out_of_sample_ready else ("open" if acked else "blocked"),
            ready=out_of_sample_ready,
            revisit_when=(
                f"ai_judgment first_entry>={ai_needed}, rules first_entry>={rules_needed}, "
                f"leading still {TARGET_CADENCE}, fair tracks still agree"
            ),
            do_not="Do not treat failing calibration shadows as live-book confirmation",
            evidence={
                "first_entry_by_track": {key: first_entry.get(key, 0) for key in LIVE_BOOKS},
                "ack_snapshot": {key: snapshot.get(key, 0) for key in LIVE_BOOKS},
                "leading_cadence": leading,
                "fair_winning_cadence": fair_winners,
                "cadence_stable": cadence_stable,
            },
        ),
        _stage(
            stage_id="paper_execute_graduated",
            title="Optional: execute 4× weekly on graduated_allocation only",
            status="open" if execute_ready else "blocked",
            ready=execute_ready,
            revisit_when=(
                "out_of_sample_first_entry ready AND graduated_allocation "
                f"equity_marks>={GRADUATED_MARKS_MIN}"
            ),
            do_not="Do not execute on primary, rules, or a new DCA paper book",
            evidence={
                "graduated_equity_marks": graduated_marks,
                "graduated_marks_min": GRADUATED_MARKS_MIN,
                "graduated_cost_drag": graduated.get("cost_drag"),
            },
        ),
        _stage(
            stage_id="primary_or_live",
            title="Primary / live size — blocked",
            status="open" if live_ready else "blocked",
            ready=live_ready,
            revisit_when="Fair-cost primary beat_market is true AND paper_execute_graduated ready",
            do_not="Overlay end-value vs lump-sum is not adoption truth vs ^FTSE",
            evidence={
                "beat_market": beat_market,
                "fair_or_primary_excess_after_costs": fair_primary.get("excess_after_costs"),
            },
        ),
    ]
    current = next((row for row in stages if row["status"] != "done"), stages[-1])
    return {
        "schema_version": 1,
        "observe_only": True,
        "experiment_id": "entry_dca_overlay",
        "target_cadence": TARGET_CADENCE,
        "updated_at": datetime.now(UTC).isoformat(),
        "acked": acked,
        "current_stage": current["id"],
        "do_not": [
            "Execute DCA on paper books until paper_execute_graduated is ready",
            "Change starter fraction from this overlay",
            "Spawn a per-model DCA paper book",
            "Apply DCA to primary AI judgment or live size while beat_market is false",
        ],
        "stages": stages,
        "finding": finding,
        "note": (
            "Human review/implementation plan for the 2026-09-13 overlay recommend. "
            "Never auto-apply. Revisit on Sunday or when first-entry windows close."
        ),
    }


def slim_entry_dca_adoption(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(plan, dict):
        return None
    stages = []
    for row in plan.get("stages") or []:
        if not isinstance(row, dict):
            continue
        stages.append(
            {
                "id": row.get("id"),
                "status": row.get("status"),
                "ready": row.get("ready"),
                "revisit_when": row.get("revisit_when"),
                "do_not": row.get("do_not"),
            }
        )
    return {
        "observe_only": True,
        "acked": bool(plan.get("acked")),
        "current_stage": plan.get("current_stage"),
        "target_cadence": plan.get("target_cadence"),
        "do_not": list(plan.get("do_not") or []),
        "stages": stages,
        "note": plan.get("note"),
    }


def write_entry_dca_adoption_plan(
    plan: dict[str, Any],
    *,
    data_dir: Path,
) -> Path:
    dest = Path(data_dir) / PLAN_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, plan, compact=False)
    return dest
