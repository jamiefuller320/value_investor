"""Link hypothesis thesis-at-start to exit-timing cohort outcomes (observe-only).

Scores whether intact / weakening / broken thesis calls predict hold-recovery and
swap-rotation results — the learning loop for hypothesis-first exits.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.exit_timing_cohorts import (
    COHORTS_FILENAME,
    load_exit_timing_cohorts,
    save_exit_timing_cohorts,
)
from value_investor.hypothesis_integrity import (
    THESIS_BROKEN,
    THESIS_INSUFFICIENT,
    THESIS_INTACT,
    THESIS_WEAKENING,
    assess_holding_hypothesis,
)

OUTCOMES_FILENAME = "hypothesis_outcome_link.json"
REVIEW_FILENAME = "hypothesis_outcome_link_review.json"
ROLLUP_FILENAME = "learning_tracks_hypothesis_outcomes.json"

THESIS_STATUSES = (THESIS_INTACT, THESIS_WEAKENING, THESIS_BROKEN, THESIS_INSUFFICIENT)

MIN_CLOSED_PER_BUCKET = 3
MIN_CLOSED_HOLD_TOTAL = 8
MIN_CLOSED_SWAP_TOTAL = 5


def thesis_snapshot_from_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    """Compact fields persisted on cohort episodes / swap legs."""
    return {
        "thesis_status_at_start": assessment.get("thesis_status"),
        "recommended_action_at_start": assessment.get("recommended_action"),
        "thesis_reasons_at_start": (assessment.get("reasons") or [])[:4],
        "failed_families_at_start": assessment.get("failed_families") or [],
        "research_verdict_at_start": assessment.get("research_verdict"),
        "unrealized_pct_at_thesis": assessment.get("unrealized_pct"),
    }


def assess_thesis_at_mark(
    *,
    ticker: str,
    mark: float,
    avg_cost: float,
    candidate: dict[str, Any] | None,
    use_adjusted_signal: bool = False,
) -> dict[str, Any]:
    """Run hypothesis assessment and return cohort-stamp fields."""
    assessment = assess_holding_hypothesis(
        ticker=ticker,
        mark=mark,
        avg_cost=avg_cost,
        row=candidate,
        use_adjusted_signal=use_adjusted_signal,
    )
    return thesis_snapshot_from_assessment(assessment)


def stamp_hold_episode_thesis(
    episode: dict[str, Any],
    *,
    candidate: dict[str, Any] | None,
    use_adjusted_signal: bool = False,
) -> dict[str, Any]:
    """Attach thesis-at-start fields to a hold-recovery episode if missing."""
    if episode.get("thesis_status_at_start"):
        return episode
    ticker = str(episode.get("ticker") or "")
    mark = float(episode.get("entry_mark") or 0)
    avg_cost = float(episode.get("avg_cost") or 0)
    if not ticker or mark <= 0 or avg_cost <= 0:
        return episode
    episode.update(
        assess_thesis_at_mark(
            ticker=ticker,
            mark=mark,
            avg_cost=avg_cost,
            candidate=candidate,
            use_adjusted_signal=use_adjusted_signal,
        )
    )
    return episode


def stamp_swap_rotation_thesis(
    rotation: dict[str, Any],
    *,
    candidates_by_ticker: dict[str, dict[str, Any]],
    use_adjusted_signal: bool = False,
) -> dict[str, Any]:
    """Attach thesis-at-rotation for each sell leg."""
    sells = list(rotation.get("sells") or [])
    if not sells:
        return rotation
    enriched: list[dict[str, Any]] = []
    for leg in sells:
        row = dict(leg)
        if row.get("thesis_status_at_start"):
            enriched.append(row)
            continue
        ticker = str(row.get("ticker") or "").upper()
        price = float(row.get("price") or 0)
        avg_cost = float(row.get("avg_cost_at_exit") or row.get("avg_cost") or 0)
        if not ticker or price <= 0 or avg_cost <= 0:
            enriched.append(row)
            continue
        candidate = candidates_by_ticker.get(ticker) or candidates_by_ticker.get(
            str(row.get("ticker") or "")
        )
        row.update(
            assess_thesis_at_mark(
                ticker=ticker,
                mark=price,
                avg_cost=avg_cost,
                candidate=candidate,
                use_adjusted_signal=use_adjusted_signal,
            )
        )
        enriched.append(row)
    rotation["sells"] = enriched
    return rotation


def _candidate_map(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for row in candidates:
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            mapped[ticker.upper()] = row
            mapped[ticker] = row
    return mapped


def enrich_cohorts_with_thesis(
    store: dict[str, Any],
    *,
    candidates: list[dict[str, Any]] | None = None,
    use_adjusted_signal: bool = False,
) -> dict[str, int]:
    """Backfill thesis stamps on hold episodes and swap rotations."""
    cmap = _candidate_map(candidates or [])
    hold_stamped = 0
    swap_stamped = 0

    episodes: list[dict[str, Any]] = []
    for episode in store.get("hold_episodes") or []:
        before = episode.get("thesis_status_at_start")
        episodes.append(
            stamp_hold_episode_thesis(
                dict(episode),
                candidate=cmap.get(str(episode.get("ticker") or "").upper())
                or cmap.get(str(episode.get("ticker") or "")),
                use_adjusted_signal=use_adjusted_signal,
            )
        )
        if not before and episodes[-1].get("thesis_status_at_start"):
            hold_stamped += 1
    store["hold_episodes"] = episodes

    rotations: list[dict[str, Any]] = []
    for rotation in store.get("swap_rotations") or []:
        before = any(leg.get("thesis_status_at_start") for leg in (rotation.get("sells") or []))
        stamped = stamp_swap_rotation_thesis(
            dict(rotation),
            candidates_by_ticker=cmap,
            use_adjusted_signal=use_adjusted_signal,
        )
        rotations.append(stamped)
        if not before and any(
            leg.get("thesis_status_at_start") for leg in (stamped.get("sells") or [])
        ):
            swap_stamped += 1
    store["swap_rotations"] = rotations

    return {"hold_episodes": hold_stamped, "swap_rotations": swap_stamped}


def _is_sold_underwater(episode: dict[str, Any]) -> bool:
    reason = str(episode.get("close_reason") or "")
    return reason == "sold_while_underwater"


def _hold_outcome_label(episode: dict[str, Any]) -> str:
    if episode.get("recovered_to_breakeven"):
        return "recovered"
    if _is_sold_underwater(episode):
        return "sold_underwater"
    reason = str(episode.get("close_reason") or "")
    if reason in {"underwater_max_window", "sold_while_underwater"}:
        return "stayed_underwater"
    if reason in {"recovered_max_window", "sold_while_recovered"}:
        return "recovered_or_exited_green"
    return "other"


def aggregate_hold_outcomes_by_thesis(
    episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarise closed hold-recovery episodes grouped by thesis_status_at_start."""
    closed = [
        row
        for row in episodes
        if str(row.get("status") or "open") != "open" and row.get("thesis_status_at_start")
    ]
    buckets: dict[str, list[dict[str, Any]]] = {status: [] for status in THESIS_STATUSES}
    unknown = 0
    for row in episodes:
        if str(row.get("status") or "open") == "open":
            continue
        status = str(row.get("thesis_status_at_start") or "")
        if status in buckets:
            buckets[status].append(row)
        else:
            unknown += 1

    by_status: dict[str, Any] = {}
    for status, rows in buckets.items():
        if not rows:
            by_status[status] = {"closed_count": 0}
            continue
        recovered = sum(1 for row in rows if row.get("recovered_to_breakeven"))
        sold_uw = sum(1 for row in rows if _is_sold_underwater(row))
        peaks = [float(row.get("peak_unrealized_pct") or 0) for row in rows]
        troughs = [float(row.get("trough_unrealized_pct") or 0) for row in rows]
        outcomes: dict[str, int] = {}
        for row in rows:
            label = _hold_outcome_label(row)
            outcomes[label] = outcomes.get(label, 0) + 1
        by_status[status] = {
            "closed_count": len(rows),
            "recovery_rate": round(recovered / len(rows), 4),
            "sold_underwater_rate": round(sold_uw / len(rows), 4),
            "mean_peak_unrealized_pct": round(sum(peaks) / len(rows), 4),
            "mean_trough_unrealized_pct": round(sum(troughs) / len(rows), 4),
            "outcome_labels": outcomes,
        }

    open_with_thesis = sum(
        1
        for row in episodes
        if str(row.get("status") or "open") == "open" and row.get("thesis_status_at_start")
    )
    return {
        "closed_total": len(closed),
        "closed_unknown_thesis": unknown,
        "open_with_thesis": open_with_thesis,
        "by_thesis_status": by_status,
    }


def aggregate_swap_outcomes_by_thesis(
    rotations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarise closed swap rotations grouped by sell-leg thesis at rotation."""
    closed = [row for row in rotations if str(row.get("status") or "open") != "open"]
    buckets: dict[str, dict[str, int]] = {status: {} for status in THESIS_STATUSES}
    legs_total = 0
    legs_unknown = 0

    for rotation in closed:
        verdict = str(rotation.get("verdict") or "inconclusive")
        for leg in rotation.get("sells") or []:
            legs_total += 1
            status = str(leg.get("thesis_status_at_start") or "")
            if status not in buckets:
                legs_unknown += 1
                continue
            bucket = buckets[status]
            bucket["leg_count"] = bucket.get("leg_count", 0) + 1
            bucket[verdict] = bucket.get(verdict, 0) + 1

    by_status: dict[str, Any] = {}
    for status, counts in buckets.items():
        leg_count = int(counts.get("leg_count") or 0)
        if leg_count <= 0:
            by_status[status] = {"leg_count": 0}
            continue
        replacement_wins = int(counts.get("replacement_outperformed") or 0)
        by_status[status] = {
            "leg_count": leg_count,
            "replacement_outperformed_rate": round(replacement_wins / leg_count, 4),
            "verdicts": {key: value for key, value in counts.items() if key not in {"leg_count"}},
        }

    return {
        "closed_rotation_count": len(closed),
        "sell_legs_total": legs_total,
        "sell_legs_unknown_thesis": legs_unknown,
        "by_thesis_status": by_status,
    }


def assess_outcome_linker_readiness(
    hold_summary: dict[str, Any],
    swap_summary: dict[str, Any],
) -> dict[str, Any]:
    gaps: list[str] = []
    hold_closed = int(hold_summary.get("closed_total") or 0)
    if hold_closed < MIN_CLOSED_HOLD_TOTAL:
        gaps.append(f"hold closed with thesis={hold_closed} (target >={MIN_CLOSED_HOLD_TOTAL})")

    thin_buckets = []
    for status, row in (hold_summary.get("by_thesis_status") or {}).items():
        count = int((row or {}).get("closed_count") or 0)
        if 0 < count < MIN_CLOSED_PER_BUCKET:
            thin_buckets.append(f"{status}={count}")
    if thin_buckets:
        gaps.append(
            f"hold thesis buckets thin ({', '.join(thin_buckets)}; target >={MIN_CLOSED_PER_BUCKET} each)"
        )

    swap_legs = int(swap_summary.get("sell_legs_total") or 0)
    if swap_legs < MIN_CLOSED_SWAP_TOTAL:
        gaps.append(f"swap sell legs with thesis={swap_legs} (target >={MIN_CLOSED_SWAP_TOTAL})")

    ready = not gaps and hold_closed >= MIN_CLOSED_HOLD_TOTAL
    note = (
        "Hypothesis outcome linker collecting — defer thesis-based exit policy until "
        "closed cohorts mature."
        if gaps
        else "Enough closed thesis-labelled episodes for observe-only rate comparison."
    )
    return {
        "ready_for_thesis_outcome_analysis": ready,
        "hold_closed_with_thesis": hold_closed,
        "swap_sell_legs_with_thesis": swap_legs,
        "gaps": gaps,
        "note": note,
    }


def build_hypothesis_outcome_review(
    store: dict[str, Any],
    *,
    track_id: str,
    stamped_this_pass: dict[str, int] | None = None,
) -> dict[str, Any]:
    hold_summary = aggregate_hold_outcomes_by_thesis(list(store.get("hold_episodes") or []))
    swap_summary = aggregate_swap_outcomes_by_thesis(list(store.get("swap_rotations") or []))
    readiness = assess_outcome_linker_readiness(hold_summary, swap_summary)

    intact = (hold_summary.get("by_thesis_status") or {}).get(THESIS_INTACT) or {}
    broken = (hold_summary.get("by_thesis_status") or {}).get(THESIS_BROKEN) or {}
    learning_hints: list[str] = []
    if (
        int(intact.get("closed_count") or 0) >= MIN_CLOSED_PER_BUCKET
        and int(broken.get("closed_count") or 0) >= MIN_CLOSED_PER_BUCKET
    ):
        intact_recovery = float(intact.get("recovery_rate") or 0)
        broken_recovery = float(broken.get("recovery_rate") or 0)
        if intact_recovery > broken_recovery + 0.15:
            learning_hints.append(
                "intact thesis predicts higher hold-recovery — supports tolerating intact losers"
            )
        if broken_recovery + 0.1 < intact_recovery:
            learning_hints.append(
                "broken thesis does not show worse recovery yet — need more closed episodes"
            )
        intact_sold = float(intact.get("sold_underwater_rate") or 0)
        broken_sold = float(broken.get("sold_underwater_rate") or 0)
        if broken_sold > intact_sold + 0.15:
            learning_hints.append(
                "broken thesis sells more often underwater — supports thesis-first rotation"
            )

    return {
        "schema_version": 1,
        "scope": "hypothesis_outcome_link",
        "observe_only": True,
        "track_id": track_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "stamped_this_pass": stamped_this_pass or {},
        "hold_recovery_by_thesis": hold_summary,
        "swap_rotation_by_thesis": swap_summary,
        "readiness": readiness,
        "learning_hints": learning_hints,
        "note": (
            "Links thesis_status_at_start on exit_timing cohorts to hold-recovery and "
            "swap-rotation outcomes. Does not auto-apply exit policy."
        ),
    }


def format_hypothesis_outcome_markdown(review: dict[str, Any]) -> str:
    hold = review.get("hold_recovery_by_thesis") or {}
    swap = review.get("swap_rotation_by_thesis") or {}
    readiness = review.get("readiness") or {}
    lines = [
        "# Hypothesis outcome link",
        "",
        f"Track: `{review.get('track_id')}` · {review.get('generated_at')}",
        "",
        "## Readiness",
        "",
        f"- Ready for thesis outcome analysis: **{readiness.get('ready_for_thesis_outcome_analysis')}**",
        f"- Closed hold episodes with thesis: {readiness.get('hold_closed_with_thesis')}",
        f"- Swap sell legs with thesis: {readiness.get('swap_sell_legs_with_thesis')}",
    ]
    for gap in readiness.get("gaps") or []:
        lines.append(f"- Gap: {gap}")
    lines.extend(["", "## Hold recovery by thesis", ""])
    for status, row in (hold.get("by_thesis_status") or {}).items():
        if not row or int(row.get("closed_count") or 0) == 0:
            continue
        lines.append(
            f"- **{status}** (n={row['closed_count']}): recovery "
            f"{float(row.get('recovery_rate') or 0):.0%}, sold underwater "
            f"{float(row.get('sold_underwater_rate') or 0):.0%}, mean peak "
            f"{float(row.get('mean_peak_unrealized_pct') or 0):+.1%}"
        )
    lines.extend(["", "## Swap rotation by sell thesis", ""])
    for status, row in (swap.get("by_thesis_status") or {}).items():
        if not row or int(row.get("leg_count") or 0) == 0:
            continue
        lines.append(
            f"- **{status}** (legs={row['leg_count']}): replacement won "
            f"{float(row.get('replacement_outperformed_rate') or 0):.0%}"
        )
    hints = review.get("learning_hints") or []
    if hints:
        lines.extend(["", "## Learning hints", ""])
        for hint in hints:
            lines.append(f"- {hint}")
    lines.append("")
    return "\n".join(lines)


def run_hypothesis_outcome_link_pass(
    *,
    output_dir: Path,
    track_id: str,
    candidates: list[dict[str, Any]] | None = None,
    use_adjusted_signal: bool = False,
    as_of: str | datetime | None = None,
) -> dict[str, Any]:
    """Enrich exit_timing cohorts with thesis stamps and write outcome review."""
    output_dir = Path(output_dir)
    cohorts_path = output_dir / COHORTS_FILENAME
    if not cohorts_path.exists():
        review = build_hypothesis_outcome_review(
            {"hold_episodes": [], "swap_rotations": []},
            track_id=track_id,
            stamped_this_pass={"hold_episodes": 0, "swap_rotations": 0},
        )
        review["note"] = "No exit_timing_cohorts.json yet — linker idle."
        review_path = output_dir / REVIEW_FILENAME
        review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        return review

    store = load_exit_timing_cohorts(cohorts_path)
    stamped = enrich_cohorts_with_thesis(
        store,
        candidates=candidates,
        use_adjusted_signal=use_adjusted_signal,
    )
    store["hypothesis_outcome_link_updated_at"] = (
        as_of.isoformat()
        if isinstance(as_of, datetime)
        else str(as_of or datetime.now(UTC).isoformat())
    )
    save_exit_timing_cohorts(cohorts_path, store)

    review = build_hypothesis_outcome_review(store, track_id=track_id, stamped_this_pass=stamped)
    payload = {
        **review,
        "cohorts_path": str(cohorts_path),
        "hold_episodes": store.get("hold_episodes") or [],
        "swap_rotations": store.get("swap_rotations") or [],
    }
    (output_dir / OUTCOMES_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / REVIEW_FILENAME).write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    (output_dir / "hypothesis_outcome_link.md").write_text(
        format_hypothesis_outcome_markdown(review), encoding="utf-8"
    )
    return review


def summarize_learning_tracks_hypothesis_outcomes(base_dir: Path) -> dict[str, Any]:
    from value_investor.paper_automation import learning_track_dirs

    base_dir = Path(base_dir)
    tracks: dict[str, Any] = {}
    for track_id, track_dir in learning_track_dirs(base_dir).items():
        review_path = track_dir / REVIEW_FILENAME
        if not review_path.exists():
            continue
        review = json.loads(review_path.read_text(encoding="utf-8"))
        hold = review.get("hold_recovery_by_thesis") or {}
        swap = review.get("swap_rotation_by_thesis") or {}
        tracks[track_id] = {
            "generated_at": review.get("generated_at"),
            "readiness": review.get("readiness"),
            "learning_hints": review.get("learning_hints"),
            "hold_closed_with_thesis": hold.get("closed_total"),
            "intact_recovery_rate": (
                (hold.get("by_thesis_status") or {}).get(THESIS_INTACT) or {}
            ).get("recovery_rate"),
            "broken_recovery_rate": (
                (hold.get("by_thesis_status") or {}).get(THESIS_BROKEN) or {}
            ).get("recovery_rate"),
            "swap_sell_legs_with_thesis": swap.get("sell_legs_total"),
        }

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "observe_only": True,
        "tracks": tracks,
        "note": (
            "Thesis-at-start vs hold-recovery / swap outcomes. Pair with "
            "learning_tracks_exit_timing and learning_tracks_hypothesis_integrity."
        ),
    }


__all__ = [
    "OUTCOMES_FILENAME",
    "REVIEW_FILENAME",
    "ROLLUP_FILENAME",
    "aggregate_hold_outcomes_by_thesis",
    "aggregate_swap_outcomes_by_thesis",
    "assess_outcome_linker_readiness",
    "assess_thesis_at_mark",
    "build_hypothesis_outcome_review",
    "enrich_cohorts_with_thesis",
    "format_hypothesis_outcome_markdown",
    "run_hypothesis_outcome_link_pass",
    "stamp_hold_episode_thesis",
    "stamp_swap_rotation_thesis",
    "summarize_learning_tracks_hypothesis_outcomes",
    "thesis_snapshot_from_assessment",
]
