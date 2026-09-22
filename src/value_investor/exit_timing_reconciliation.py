"""Reconcile live paper vs archive exit-timing cohort denominators (L121).

Shared episode-outcome definitions and comparability gates before blending
hold→breakeven or swap-success rates across sources.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.exit_timing_cohorts import (
    BREAKEVEN_THRESHOLD,
    DEFAULT_WINDOWS_DAYS,
    REVIEW_FILENAME,
    framework_metadata,
)

RECONCILIATION_FILENAME = "exit_timing_reconciliation.json"
PRIMARY_LIVE_TRACK_ID = "rules"
ARCHIVE_REVIEW_FILENAME = "exit_timing_near_miss_review.json"

# Map source-specific close_reason labels to shared outcome + exit-mechanism buckets.
HOLD_CLOSE_REASON_CANONICAL: dict[str, tuple[str, str]] = {
    "sold_while_recovered": ("recovered_at_close", "sold_while_held"),
    "sold_while_underwater": ("not_recovered_at_close", "sold_while_held"),
    "recovered_max_window": ("recovered_at_close", "max_scoring_window"),
    "underwater_max_window": ("not_recovered_at_close", "max_scoring_window"),
    "recovered_archive_end": ("recovered_at_close", "archive_horizon"),
    "underwater_archive_end": ("not_recovered_at_close", "archive_horizon"),
}

EPISODE_SOURCE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "live_paper_book": {
        "artifact": "paper_automation/<track>/exit_timing_cohorts_review.json",
        "population": "Names on the paper book when hold-recovery stress triggers fire.",
        "hold_entry_triggers": [
            "underwater vs avg_cost",
            "exit_streak >= 1",
            "momentum_grace",
            "effective signal no longer buy-tier while held",
        ],
        "swap_pairing": "Same rebalance pass sells and buys on one track.",
        "role": "Primary evidence for knob promotion after readiness targets.",
    },
    "archive_near_miss": {
        "artifact": "docs/data/exit_timing_near_miss_review.json",
        "population": "Synthetic observe-only holds on near-miss screen rows (default signal hold).",
        "hold_entry_triggers": [
            "signal below buy tier",
            "conviction >= pre_buy floor (default 0.28)",
            "capped episodes per archive week",
        ],
        "swap_pairing": "Near-miss hold vs top buy-tier name from same weekly screen snapshot.",
        "role": "Offline priors until live paper cohorts mature; not interchangeable denominators.",
    },
}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def canonicalize_hold_close_reasons(close_reasons: dict[str, int] | None) -> dict[str, int]:
    """Roll up raw close_reason counts into shared outcome buckets."""
    buckets: dict[str, int] = {}
    for reason, count in (close_reasons or {}).items():
        canonical = HOLD_CLOSE_REASON_CANONICAL.get(str(reason))
        if canonical is None:
            key = f"other:{reason}"
        else:
            key = canonical[0]
        buckets[key] = buckets.get(key, 0) + int(count)
    return buckets


def hold_recovery_metrics(review: dict[str, Any] | None) -> dict[str, Any]:
    if not review:
        return {"present": False}
    closed = ((review.get("hold_recovery") or {}).get("closed") or {}) if review else {}
    count = int(closed.get("count") or 0)
    recovered = int(closed.get("recovered_to_breakeven") or 0)
    rate = round(recovered / count, 4) if count else None
    readiness = review.get("readiness") or {}
    return {
        "present": True,
        "track_id": review.get("track_id"),
        "scope": review.get("scope"),
        "readiness": readiness,
        "hold_closed_count": count,
        "recovered_to_breakeven_count": recovered,
        "hold_recovery_rate": rate,
        "close_reasons_raw": closed.get("close_reasons"),
        "close_reasons_canonical": canonicalize_hold_close_reasons(
            closed.get("close_reasons") if isinstance(closed.get("close_reasons"), dict) else None
        ),
    }


def swap_rotation_metrics(review: dict[str, Any] | None) -> dict[str, Any]:
    if not review:
        return {"present": False}
    closed = ((review.get("swap_rotation") or {}).get("closed") or {}) if review else {}
    count = int(closed.get("count") or 0)
    readiness = review.get("readiness") or {}
    verdicts = closed.get("verdicts") if isinstance(closed.get("verdicts"), dict) else {}
    replacement_wins = int(verdicts.get("replacement_outperformed") or 0)
    swap_success_rate = round(replacement_wins / count, 4) if count else None
    return {
        "present": True,
        "track_id": review.get("track_id"),
        "scope": review.get("scope"),
        "readiness": readiness,
        "swap_closed_count": count,
        "verdicts": verdicts,
        "swap_replacement_outperformed_rate": swap_success_rate,
    }


def resolve_live_exit_timing_review(
    paper_root: Path,
    *,
    primary_track_id: str = PRIMARY_LIVE_TRACK_ID,
) -> dict[str, Any] | None:
    """Primary live review for analysis payloads (rules track by default)."""
    paper_root = Path(paper_root)
    primary_path = paper_root / primary_track_id / REVIEW_FILENAME
    primary = _load_json(primary_path)
    if primary:
        return primary
    rollup = _load_json(paper_root / "learning_tracks_exit_timing.json")
    if not rollup:
        return None
    tracks = rollup.get("tracks") or {}
    if isinstance(tracks, dict) and primary_track_id in tracks:
        row = tracks[primary_track_id]
        return row if isinstance(row, dict) else None
    return None


def aggregate_live_tracks(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum closed counts across tracks; rates use pooled recovered counts."""
    hold_closed = 0
    hold_recovered = 0
    swap_closed = 0
    replacement_wins = 0
    canonical_reasons: dict[str, int] = {}
    track_ids: list[str] = []
    for review in reviews:
        if not review:
            continue
        track_ids.append(str(review.get("track_id") or ""))
        hold = hold_recovery_metrics(review)
        if hold.get("present"):
            hold_closed += int(hold.get("hold_closed_count") or 0)
            hold_recovered += int(hold.get("recovered_to_breakeven_count") or 0)
            for key, val in (hold.get("close_reasons_canonical") or {}).items():
                canonical_reasons[key] = canonical_reasons.get(key, 0) + int(val)
        swap = swap_rotation_metrics(review)
        if swap.get("present"):
            swap_closed += int(swap.get("swap_closed_count") or 0)
            verdicts = swap.get("verdicts") or {}
            replacement_wins += int(verdicts.get("replacement_outperformed") or 0)

    gaps: list[str] = []
    if hold_closed < 15:
        gaps.append(f"hold_recovery closed episodes={hold_closed} (target >=15)")
    if swap_closed < 10:
        gaps.append(f"swap_rotation closed rotations={swap_closed} (target >=10)")
    readiness = {
        "ready_for_probability_analysis": hold_closed >= 15 and swap_closed >= 10,
        "hold_closed_count": hold_closed,
        "swap_closed_count": swap_closed,
        "gaps": gaps,
        "note": (
            "Framework collecting — probability estimates deferred until closed cohort targets met."
            if gaps
            else "Closed cohorts reached initial targets; probability strand analysis can begin."
        ),
    }
    return {
        "track_ids": [tid for tid in track_ids if tid],
        "hold_closed_count": hold_closed,
        "recovered_to_breakeven_count": hold_recovered,
        "hold_recovery_rate": round(hold_recovered / hold_closed, 4) if hold_closed else None,
        "close_reasons_canonical": canonical_reasons,
        "swap_closed_count": swap_closed,
        "swap_replacement_outperformed_rate": round(replacement_wins / swap_closed, 4)
        if swap_closed
        else None,
        "readiness": readiness,
        "note": (
            "Pooled across FTSE paper tracks; episodes are per-track (same ticker may appear "
            "on multiple tracks)."
        ),
    }


def _comparability_gates(
    *,
    live_primary: dict[str, Any],
    live_aggregate: dict[str, Any],
    archive_hold: dict[str, Any],
    archive_swap: dict[str, Any],
) -> dict[str, Any]:
    live_primary_ready = bool(
        ((live_primary.get("readiness") or {}).get("ready_for_probability_analysis"))
    )
    archive_ready = bool(
        ((archive_hold.get("readiness") or {}).get("ready_for_probability_analysis"))
    )
    live_swap_closed = int(live_aggregate.get("swap_closed_count") or 0)
    archive_swap_closed = int(archive_swap.get("swap_closed_count") or 0)

    hold_rates_comparable = False
    hold_blockers = [
        "Hold-recovery episodes enter on different populations "
        "(live book stress vs archive near-miss observe)."
    ]
    swap_rates_comparable = live_swap_closed >= 10 and archive_swap_closed >= 10
    swap_blockers: list[str] = []
    if live_swap_closed < 10:
        swap_blockers.append(
            f"live pooled swap_closed_count={live_swap_closed} (target >=10 for probability work)"
        )
    if archive_swap_closed < 10:
        swap_blockers.append(f"archive swap_closed_count={archive_swap_closed} (unexpected)")

    blended_probability_ok = live_primary_ready or (
        archive_ready and not live_primary_ready and live_swap_closed == 0
    )

    return {
        "shared_metric_definitions": {
            "breakeven_threshold": BREAKEVEN_THRESHOLD,
            "checkpoint_windows_days": list(DEFAULT_WINDOWS_DAYS),
            "hold_recovery_rate_numerator": "closed episodes with recovered_to_breakeven=true",
            "hold_recovery_rate_denominator": "closed hold-recovery episodes (status != open)",
            "swap_success_rate_numerator": "closed rotations with verdict=replacement_outperformed",
            "swap_success_rate_denominator": "closed swap rotations (status != open)",
            "close_reason_canonical_map": {
                raw: {"outcome": pair[0], "exit_mechanism": pair[1]}
                for raw, pair in HOLD_CLOSE_REASON_CANONICAL.items()
            },
        },
        "episode_sources": EPISODE_SOURCE_DEFINITIONS,
        "hold_recovery_rates_directly_comparable": hold_rates_comparable,
        "hold_recovery_comparability_blockers": hold_blockers,
        "swap_rotation_rates_directly_comparable": swap_rates_comparable,
        "swap_rotation_comparability_blockers": swap_blockers,
        "archive_may_inform_priors_while_live_collects": archive_ready and not live_primary_ready,
        "live_primary_ready_for_probability": live_primary_ready,
        "archive_ready_for_probability": archive_ready,
        "blended_rate_narrative_allowed": blended_probability_ok,
        "analysis_contract": (
            "Cite exit_timing_reconciliation before comparing live vs archive rates. "
            "Use archive hold_recovery_rate as offline_sim prior only until live primary "
            "track hits readiness; never average rates across sources."
        ),
    }


def build_exit_timing_reconciliation(
    *,
    paper_root: Path,
    data_dir: Path,
    primary_track_id: str = PRIMARY_LIVE_TRACK_ID,
) -> dict[str, Any]:
    paper_root = Path(paper_root)
    data_dir = Path(data_dir)

    live_reviews: list[dict[str, Any]] = []
    rollup = _load_json(paper_root / "learning_tracks_exit_timing.json")
    if rollup and isinstance(rollup.get("tracks"), dict):
        for row in rollup["tracks"].values():
            if isinstance(row, dict):
                live_reviews.append(row)
    if not live_reviews:
        from value_investor.paper_automation import learning_track_dirs

        for _track_id, track_dir in learning_track_dirs(paper_root).items():
            review = _load_json(track_dir / REVIEW_FILENAME)
            if review:
                live_reviews.append(review)

    primary_review = resolve_live_exit_timing_review(
        paper_root, primary_track_id=primary_track_id
    )
    archive_review = _load_json(data_dir / ARCHIVE_REVIEW_FILENAME)

    live_primary_hold = hold_recovery_metrics(primary_review)
    live_primary_swap = swap_rotation_metrics(primary_review)
    live_aggregate = aggregate_live_tracks(live_reviews)
    archive_hold = hold_recovery_metrics(archive_review)
    archive_swap = swap_rotation_metrics(archive_review)

    comparability = _comparability_gates(
        live_primary={"readiness": live_primary_hold.get("readiness") or {}},
        live_aggregate=live_aggregate,
        archive_hold={"readiness": archive_hold.get("readiness") or {}},
        archive_swap=archive_swap,
    )

    return {
        "schema_version": 1,
        "deferred_id": "L121",
        "generated_at": datetime.now(UTC).isoformat(),
        "framework": framework_metadata(),
        "primary_live_track_id": primary_track_id,
        "sources": {
            "live_primary": {
                "hold_recovery": live_primary_hold,
                "swap_rotation": live_primary_swap,
            },
            "live_all_tracks_pooled": live_aggregate,
            "archive_near_miss": {
                "hold_recovery": archive_hold,
                "swap_rotation": archive_swap,
                "episodes_opened": (archive_review or {}).get("episodes_opened"),
                "by_conviction_band": (archive_review or {}).get("by_conviction_band"),
            },
        },
        "comparability": comparability,
        "note": (
            "Observe-only reconciliation for exit-timing learning. "
            "Regenerated on paper-auto rollup, exit-timing archive, and analysis-review payload."
        ),
    }


def write_exit_timing_reconciliation(
    *,
    paper_root: Path,
    data_dir: Path,
    primary_track_id: str = PRIMARY_LIVE_TRACK_ID,
) -> dict[str, Any]:
    reconciliation = build_exit_timing_reconciliation(
        paper_root=paper_root,
        data_dir=data_dir,
        primary_track_id=primary_track_id,
    )
    out_path = Path(data_dir) / RECONCILIATION_FILENAME
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(reconciliation, indent=2) + "\n", encoding="utf-8")
    return reconciliation


__all__ = [
    "ARCHIVE_REVIEW_FILENAME",
    "EPISODE_SOURCE_DEFINITIONS",
    "HOLD_CLOSE_REASON_CANONICAL",
    "PRIMARY_LIVE_TRACK_ID",
    "RECONCILIATION_FILENAME",
    "aggregate_live_tracks",
    "build_exit_timing_reconciliation",
    "canonicalize_hold_close_reasons",
    "hold_recovery_metrics",
    "resolve_live_exit_timing_review",
    "swap_rotation_metrics",
    "write_exit_timing_reconciliation",
]
