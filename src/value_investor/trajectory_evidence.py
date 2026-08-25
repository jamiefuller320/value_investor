"""Trajectory evidence: transitions, boundary watch, outcome labels (+ loser cards)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from value_investor.backtest import RunSnapshot, load_run_snapshots
from value_investor.loser_snapshot_cards import run_loser_snapshot_cards
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.storage import read_json, write_json

TRANSITIONS_FILENAME = "trajectory_transitions.json"
BOUNDARY_FILENAME = "trajectory_boundary_watch.json"
REVIEW_FILENAME = "trajectory_evidence_review.json"
REVIEW_MD_FILENAME = "trajectory_evidence_review.md"

SIGNAL_RANK = {
    "avoid": 0,
    "insufficient_data": 1,
    "hold": 1,
    "buy": 2,
    "strong_buy": 3,
}

CONVICTION_MATERIAL_DELTA = 0.08
FORWARD_HORIZONS_WEEKS = (1, 4, 8, 12)
MAX_REALIZATION_WEEKS = 12
MIN_FOCUS_SAMPLE_COUNT = 8
WEAK_POSITIVE_RATE = 0.40
WEAK_HIT_RATE = 0.50
MAX_FOCUS_CANDIDATES = 6

# Tier-boundary conviction floors (also used by exit-timing near-miss gate alignment)
PRE_BUY_CONVICTION = 0.28
PRE_AVOID_CONVICTION = 0.12
STRONG_BUY_CANDIDATE_CONVICTION = 0.50
AVOID_RECOVERY_CONVICTION = 0.20

# Tags that qualify a name for the boundary panel (secondary tags alone do not).
CORE_BOUNDARY_TAGS = frozenset(
    {
        "pre_buy",
        "pre_avoid",
        "buy_weakening",
        "strong_buy_candidate",
        "timing_wait_on_buy_tier",
        "avoid_recovery_candidate",
        "hold_improving",
        "hold_deteriorating",
    }
)
SECONDARY_BOUNDARY_TAGS = frozenset({"fresh_opinion"})


def _signal_rank(signal: str | None) -> int:
    return SIGNAL_RANK.get(str(signal or "hold").strip().lower(), 1)


def _direction(from_signal: str, to_signal: str) -> str:
    delta = _signal_rank(to_signal) - _signal_rank(from_signal)
    if delta > 0:
        return "upgrade"
    if delta < 0:
        return "downgrade"
    return "lateral"


def _row_map(snapshot: RunSnapshot) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("ticker") or "").strip(): row for row in snapshot.signals if row.get("ticker")
    }


def _forward_return(
    ticker: str,
    entry: RunSnapshot,
    exit_snap: RunSnapshot | None,
) -> float | None:
    if exit_snap is None:
        return None
    p0 = entry.prices.get(ticker)
    p1 = exit_snap.prices.get(ticker)
    if p0 is None or p1 is None or float(p0) <= 0:
        return None
    return round((float(p1) / float(p0)) - 1.0, 6)


def _expected_return_sign(
    *,
    direction: str,
    conviction_delta: float,
    timing_flipped: bool,
    from_timing: str | None,
    to_timing: str | None,
) -> int | None:
    """+1 bullish, -1 bearish, None when no directional prediction is implied."""
    if direction == "upgrade":
        return 1
    if direction == "downgrade":
        return -1
    if abs(conviction_delta) >= CONVICTION_MATERIAL_DELTA:
        return 1 if conviction_delta > 0 else -1
    if timing_flipped and from_timing == "wait" and to_timing and to_timing != "wait":
        return 1
    if timing_flipped and to_timing == "wait" and from_timing and from_timing != "wait":
        return -1
    return None


def _prediction_success(expected_sign: int | None, forward_return: float | None) -> bool | None:
    if expected_sign is None or forward_return is None:
        return None
    if expected_sign > 0:
        return forward_return > 0
    return forward_return < 0


def _forward_returns_at_horizons(
    ticker: str,
    entry: RunSnapshot,
    sorted_snaps: list[RunSnapshot],
    entry_index: int,
) -> dict[str, float | None]:
    returns: dict[str, float | None] = {}
    for weeks in FORWARD_HORIZONS_WEEKS:
        forward_index = entry_index + weeks
        forward_snap = sorted_snaps[forward_index] if forward_index < len(sorted_snaps) else None
        returns[f"forward_return_{weeks}w"] = _forward_return(ticker, entry, forward_snap)
    return returns


def _weeks_to_realization(
    ticker: str,
    entry: RunSnapshot,
    sorted_snaps: list[RunSnapshot],
    entry_index: int,
    expected_sign: int | None,
) -> int | None:
    """First archive week (1..MAX_REALIZATION_WEEKS) where return aligns with prediction."""
    if expected_sign is None:
        return None
    max_weeks = min(MAX_REALIZATION_WEEKS, len(sorted_snaps) - entry_index - 1)
    for weeks in range(1, max_weeks + 1):
        forward_snap = sorted_snaps[entry_index + weeks]
        forward_return = _forward_return(ticker, entry, forward_snap)
        if _prediction_success(expected_sign, forward_return):
            return weeks
    return None


def _build_outcome_labels(
    *,
    ticker: str,
    curr: RunSnapshot,
    sorted_snaps: list[RunSnapshot],
    entry_index: int,
    direction: str,
    conviction_delta: float,
    timing_flipped: bool,
    from_timing: str | None,
    to_timing: str | None,
) -> dict[str, Any]:
    expected_sign = _expected_return_sign(
        direction=direction,
        conviction_delta=conviction_delta,
        timing_flipped=timing_flipped,
        from_timing=from_timing,
        to_timing=to_timing,
    )
    horizon_returns = _forward_returns_at_horizons(ticker, curr, sorted_snaps, entry_index)
    outcomes: dict[str, Any] = dict(horizon_returns)
    for weeks in FORWARD_HORIZONS_WEEKS:
        key = f"forward_return_{weeks}w"
        outcomes[f"prediction_success_{weeks}w"] = _prediction_success(
            expected_sign,
            horizon_returns.get(key),
        )
    weeks_to_realization = _weeks_to_realization(
        ticker,
        curr,
        sorted_snaps,
        entry_index,
        expected_sign,
    )
    outcomes["expected_return_sign"] = expected_sign
    outcomes["weeks_to_realization"] = weeks_to_realization
    outcomes["realization_within_12w"] = (
        weeks_to_realization is not None if expected_sign is not None else None
    )
    max_horizon = max(FORWARD_HORIZONS_WEEKS)
    if entry_index + 1 >= len(sorted_snaps):
        outcomes["label_note"] = "Awaiting next archive for forward labels"
    elif entry_index + max_horizon >= len(sorted_snaps):
        outcomes["label_note"] = (
            f"Partial horizons — need {entry_index + max_horizon + 1} snapshots for {max_horizon}w labels"
        )
    else:
        outcomes["label_note"] = (
            "Forward returns from transition week_to at 1/4/8/12 archive-week horizons"
        )
    return outcomes


def build_transition_events(
    snapshots: list[RunSnapshot],
    *,
    conviction_material_delta: float = CONVICTION_MATERIAL_DELTA,
) -> list[dict[str, Any]]:
    """Diff consecutive archive snapshots into sparse opinion-change events."""
    if len(snapshots) < 2:
        return []

    events: list[dict[str, Any]] = []
    sorted_snaps = sorted(snapshots, key=lambda snap: snap.run_at)
    for index in range(1, len(sorted_snaps)):
        prev = sorted_snaps[index - 1]
        curr = sorted_snaps[index]
        prev_rows = _row_map(prev)
        curr_rows = _row_map(curr)

        for ticker in sorted(set(prev_rows) & set(curr_rows)):
            before = prev_rows[ticker]
            after = curr_rows[ticker]
            from_signal = str(before.get("signal") or "hold").lower()
            to_signal = str(after.get("signal") or "hold").lower()
            from_timing = str(before.get("timing_signal") or "").lower()
            to_timing = str(after.get("timing_signal") or "").lower()
            from_conv = float(before.get("conviction_score") or 0)
            to_conv = float(after.get("conviction_score") or 0)
            conv_delta = round(to_conv - from_conv, 4)

            signal_changed = from_signal != to_signal
            timing_changed = from_timing != to_timing and (from_timing or to_timing)
            conviction_changed = abs(conv_delta) >= conviction_material_delta
            from_adj = str(before.get("adjusted_signal") or "").strip().lower()
            to_adj = str(after.get("adjusted_signal") or "").strip().lower()
            adjusted_changed = bool(from_adj or to_adj) and from_adj != to_adj

            if not (signal_changed or timing_changed or conviction_changed or adjusted_changed):
                continue

            transition_key = f"{from_signal}->{to_signal}" if signal_changed else "signal_unchanged"
            event_id = f"tr-{curr.run_at[:10].replace('-', '')}-{ticker}"
            events.append(
                {
                    "event_id": event_id,
                    "ticker": ticker,
                    "week_from": prev.run_at,
                    "week_to": curr.run_at,
                    "from_signal": from_signal,
                    "to_signal": to_signal,
                    "transition_key": transition_key,
                    "direction": _direction(from_signal, to_signal),
                    "conviction_from": from_conv,
                    "conviction_to": to_conv,
                    "conviction_delta": conv_delta,
                    "from_timing": from_timing or None,
                    "to_timing": to_timing or None,
                    "timing_flipped": timing_changed,
                    "from_adjusted_signal": from_adj or None,
                    "to_adjusted_signal": to_adj or None,
                    "adjusted_signal_changed": adjusted_changed,
                    "outcomes": _build_outcome_labels(
                        ticker=ticker,
                        curr=curr,
                        sorted_snaps=sorted_snaps,
                        entry_index=index,
                        direction=_direction(from_signal, to_signal),
                        conviction_delta=conv_delta,
                        timing_flipped=timing_changed,
                        from_timing=from_timing or None,
                        to_timing=to_timing or None,
                    ),
                }
            )
    return events


def _boundary_tags(row: dict[str, Any]) -> list[str]:
    signal = str(row.get("signal") or "hold").lower()
    conviction = float(row.get("conviction_score") or 0)
    trend = str(row.get("signal_trend") or "").lower()
    timing = str(row.get("timing_signal") or "").lower()
    tags: list[str] = []

    if signal == "hold" and conviction >= PRE_BUY_CONVICTION:
        tags.append("pre_buy")
    if signal == "hold" and conviction <= PRE_AVOID_CONVICTION:
        tags.append("pre_avoid")
    if signal == "hold" and trend == "improving":
        tags.append("hold_improving")
    if signal == "hold" and trend == "deteriorating":
        tags.append("hold_deteriorating")
    if signal in BUY_SIGNALS and trend == "deteriorating":
        tags.append("buy_weakening")
    if signal == "buy" and conviction >= STRONG_BUY_CANDIDATE_CONVICTION:
        tags.append("strong_buy_candidate")
    if signal in BUY_SIGNALS and timing == "wait":
        tags.append("timing_wait_on_buy_tier")
    if signal == "avoid" and conviction >= AVOID_RECOVERY_CONVICTION:
        tags.append("avoid_recovery_candidate")
    # Secondary only — never qualifies a name alone (keeps panel ~30–80, not whole index).
    if trend == "new" and signal in {"hold", "buy", "strong_buy"}:
        tags.append("fresh_opinion")
    return tags


def _core_boundary_tags(tags: list[str]) -> list[str]:
    return [tag for tag in tags if tag in CORE_BOUNDARY_TAGS]


def _conviction_gaps(row: dict[str, Any]) -> dict[str, float | None]:
    """Distance to nearest buy/avoid conviction floors (positive = above floor)."""
    signal = str(row.get("signal") or "hold").lower()
    conviction = float(row.get("conviction_score") or 0)
    buy_gap: float | None = None
    avoid_gap: float | None = None
    if signal == "hold":
        buy_gap = round(conviction - PRE_BUY_CONVICTION, 4)
        avoid_gap = round(conviction - PRE_AVOID_CONVICTION, 4)
    elif signal in BUY_SIGNALS:
        buy_gap = round(conviction - PRE_BUY_CONVICTION, 4)
    elif signal == "avoid":
        avoid_gap = round(conviction - PRE_AVOID_CONVICTION, 4)
    return {"conviction_gap_to_buy": buy_gap, "conviction_gap_to_avoid": avoid_gap}


def _archive_conviction_series(
    snapshots: list[RunSnapshot],
) -> dict[str, list[tuple[str, float, list[str]]]]:
    """Per ticker: chronological (run_at, conviction, core_tags) from archives."""
    series: dict[str, list[tuple[str, float, list[str]]]] = {}
    for snap in sorted(snapshots, key=lambda item: item.run_at):
        for row in snap.signals:
            ticker = str(row.get("ticker") or "").strip()
            if not ticker:
                continue
            tags = _core_boundary_tags(_boundary_tags(row))
            series.setdefault(ticker, []).append(
                (snap.run_at, float(row.get("conviction_score") or 0), tags)
            )
    return series


def _history_features(
    ticker: str,
    archive_series: dict[str, list[tuple[str, float, list[str]]]],
) -> dict[str, Any]:
    """Cheap archive-derived features for boundary panel enrichment."""
    points = archive_series.get(ticker) or []
    if not points:
        return {
            "weeks_on_boundary": 0,
            "conviction_delta_1w": None,
            "conviction_delta_4w": None,
            "archive_point_count": 0,
        }
    weeks_on_boundary = 0
    for _run_at, _conv, tags in reversed(points):
        if not tags:
            break
        weeks_on_boundary += 1
    latest_conv = points[-1][1]
    delta_1w = None
    delta_4w = None
    if len(points) >= 2:
        delta_1w = round(latest_conv - points[-2][1], 4)
    if len(points) >= 5:
        delta_4w = round(latest_conv - points[-5][1], 4)
    return {
        "weeks_on_boundary": weeks_on_boundary,
        "conviction_delta_1w": delta_1w,
        "conviction_delta_4w": delta_4w,
        "archive_point_count": len(points),
    }


def build_boundary_watch_panel(
    reports: list[dict[str, Any]],
    *,
    snapshots: list[RunSnapshot] | None = None,
) -> list[dict[str, Any]]:
    """Names near tier boundaries — full-range trajectory watch, not whole index."""
    archive_series = _archive_conviction_series(snapshots or [])
    panel: list[dict[str, Any]] = []
    for row in reports:
        tags = _boundary_tags(row)
        core_tags = _core_boundary_tags(tags)
        if not core_tags:
            continue
        ticker = str(row.get("ticker") or "").strip()
        gaps = _conviction_gaps(row)
        history = _history_features(ticker, archive_series)
        panel.append(
            {
                "ticker": row.get("ticker"),
                "name": row.get("name"),
                "signal": row.get("signal"),
                "conviction_score": row.get("conviction_score"),
                "signal_trend": row.get("signal_trend"),
                "timing_signal": row.get("timing_signal"),
                "weeks_at_signal": row.get("weeks_at_signal"),
                "passed_families": row.get("passed_families"),
                "data_quality_score": row.get("data_quality_score"),
                "sector": row.get("sector"),
                "adjusted_signal": row.get("adjusted_signal"),
                "research_verdict": row.get("research_verdict"),
                "price_vs_sma200_pct": row.get("price_vs_sma200_pct"),
                "volume_ratio_20": row.get("volume_ratio_20"),
                "conviction_gap_to_buy": gaps["conviction_gap_to_buy"],
                "conviction_gap_to_avoid": gaps["conviction_gap_to_avoid"],
                "weeks_on_boundary": history["weeks_on_boundary"],
                "conviction_delta_1w": history["conviction_delta_1w"],
                "conviction_delta_4w": history["conviction_delta_4w"],
                "archive_point_count": history["archive_point_count"],
                "boundary_tags": tags,
                "core_boundary_tags": core_tags,
            }
        )
    panel.sort(
        key=lambda item: (
            -len(item.get("core_boundary_tags") or []),
            -int(item.get("weeks_on_boundary") or 0),
            str(item.get("ticker") or ""),
        )
    )
    return panel


def summarize_boundary_panel(panel: list[dict[str, Any]]) -> dict[str, Any]:
    """Tag/count rollup for review docs and analysis-review slim payload."""
    by_tag: dict[str, int] = {}
    for row in panel:
        for tag in row.get("core_boundary_tags") or []:
            by_tag[str(tag)] = by_tag.get(str(tag), 0) + 1
    return {
        "panel_count": len(panel),
        "by_core_tag": dict(sorted(by_tag.items())),
        "mean_weeks_on_boundary": (
            round(
                mean(int(row.get("weeks_on_boundary") or 0) for row in panel),
                2,
            )
            if panel
            else None
        ),
    }


def _outcome_bucket(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    positive = sum(1 for value in values if value > 0)
    return {
        "count": len(values),
        "mean_forward_return": round(mean(values), 6),
        "positive_rate": round(positive / len(values), 4),
    }


def _direction_buckets(events: list[dict[str, Any]], horizon_weeks: int) -> dict[str, Any]:
    return_key = f"forward_return_{horizon_weeks}w"
    labeled = [
        event for event in events if (event.get("outcomes") or {}).get(return_key) is not None
    ]
    by_key: dict[str, list[float]] = {}
    upgrades: list[float] = []
    downgrades: list[float] = []
    for event in labeled:
        ret = float((event.get("outcomes") or {})[return_key])
        key = str(event.get("transition_key") or "unknown")
        by_key.setdefault(key, []).append(ret)
        direction = str(event.get("direction") or "")
        if direction == "upgrade":
            upgrades.append(ret)
        elif direction == "downgrade":
            downgrades.append(ret)
    return {
        "labeled_event_count": len(labeled),
        "by_transition_key": {key: _outcome_bucket(vals) for key, vals in sorted(by_key.items())},
        "upgrade_events": _outcome_bucket(upgrades),
        "downgrade_events": _outcome_bucket(downgrades),
    }


def summarize_transition_outcomes(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Stratified outcome labels by transition type (evaluation only)."""
    labeled_1w = [
        event
        for event in events
        if (event.get("outcomes") or {}).get("forward_return_1w") is not None
    ]
    if not labeled_1w:
        return {
            "labeled_event_count": 0,
            "note": "Need >=3 archive snapshots for 1-week forward labels on transitions",
        }

    by_horizon = {
        f"{weeks}w": _direction_buckets(events, weeks) for weeks in FORWARD_HORIZONS_WEEKS
    }
    realization_weeks = [
        int((event.get("outcomes") or {})["weeks_to_realization"])
        for event in events
        if (event.get("outcomes") or {}).get("weeks_to_realization") is not None
    ]
    scorable = [
        event
        for event in events
        if (event.get("outcomes") or {}).get("expected_return_sign") is not None
    ]
    realized_12w = [
        event
        for event in scorable
        if (event.get("outcomes") or {}).get("realization_within_12w") is True
    ]

    def _prediction_rate(horizon_weeks: int) -> dict[str, Any]:
        key = f"prediction_success_{horizon_weeks}w"
        scored = [
            bool((event.get("outcomes") or {})[key])
            for event in scorable
            if (event.get("outcomes") or {}).get(key) is not None
        ]
        if not scored:
            return {"scored_event_count": 0}
        hits = sum(1 for value in scored if value)
        return {
            "scored_event_count": len(scored),
            "prediction_hit_rate": round(hits / len(scored), 4),
        }

    horizon_1w = by_horizon["1w"]
    return {
        "labeled_event_count": horizon_1w["labeled_event_count"],
        "by_transition_key": horizon_1w["by_transition_key"],
        "upgrade_events": horizon_1w["upgrade_events"],
        "downgrade_events": horizon_1w["downgrade_events"],
        "by_horizon": by_horizon,
        "prediction_hit_rate_by_horizon": {
            f"{weeks}w": _prediction_rate(weeks) for weeks in FORWARD_HORIZONS_WEEKS
        },
        "weeks_to_realization": {
            "realized_event_count": len(realization_weeks),
            "scorable_event_count": len(scorable),
            "realized_within_12w_count": len(realized_12w),
            "realized_within_12w_rate": (
                round(len(realized_12w) / len(scorable), 4) if scorable else None
            ),
            "median_weeks": round(median(realization_weeks), 2) if realization_weeks else None,
            "within_4w_rate": (
                round(
                    sum(1 for weeks in realization_weeks if weeks <= 4) / len(realization_weeks),
                    4,
                )
                if realization_weeks
                else None
            ),
        },
        "note": "Hindsight labels for marker development — not used to define live signals",
    }


def build_model_focus_candidates(outcome_summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank assessment-model weak spots for analysis-review scoring experiments."""
    if int(outcome_summary.get("labeled_event_count") or 0) <= 0:
        return []

    candidates: list[dict[str, Any]] = []
    for key, stats in (outcome_summary.get("by_transition_key") or {}).items():
        if not isinstance(stats, dict):
            continue
        count = int(stats.get("count") or 0)
        if count < MIN_FOCUS_SAMPLE_COUNT:
            continue
        positive_rate = stats.get("positive_rate")
        mean_return = stats.get("mean_forward_return")
        if mean_return is None:
            mean_return = stats.get("mean_forward_return_1w")
        if positive_rate is None:
            continue
        weak_direction = float(positive_rate) < WEAK_POSITIVE_RATE
        weak_mean = mean_return is not None and float(mean_return) < 0
        if not (weak_direction or weak_mean):
            continue
        candidates.append(
            {
                "kind": "transition_key",
                "key": str(key),
                "horizon": "1w",
                "count": count,
                "positive_rate": positive_rate,
                "mean_forward_return": mean_return,
                "why": (
                    f"{key} 1w positive_rate={positive_rate} mean={mean_return} n={count} "
                    "— opinion flip did not match next-week price"
                ),
            }
        )
    candidates.sort(
        key=lambda row: (
            float(row.get("positive_rate") or 1.0),
            float(row.get("mean_forward_return") or 0.0),
        )
    )

    for horizon, stats in (outcome_summary.get("prediction_hit_rate_by_horizon") or {}).items():
        if not isinstance(stats, dict):
            continue
        scored = int(stats.get("scored_event_count") or 0)
        hit_rate = stats.get("prediction_hit_rate")
        if scored < MIN_FOCUS_SAMPLE_COUNT or hit_rate is None:
            continue
        if float(hit_rate) >= WEAK_HIT_RATE:
            continue
        candidates.append(
            {
                "kind": "horizon_hit_rate",
                "key": str(horizon),
                "horizon": str(horizon),
                "count": scored,
                "prediction_hit_rate": hit_rate,
                "why": (
                    f"Directional hit_rate={hit_rate} at {horizon} (n={scored}) "
                    "— implied upgrade/downgrade/conviction sign is not beating chance"
                ),
            }
        )

    realization = outcome_summary.get("weeks_to_realization") or {}
    hit_1w = (outcome_summary.get("prediction_hit_rate_by_horizon") or {}).get("1w") or {}
    hit_rate_1w = hit_1w.get("prediction_hit_rate")
    within_4w = realization.get("within_4w_rate")
    realized_n = int(realization.get("realized_event_count") or 0)
    if (
        hit_rate_1w is not None
        and within_4w is not None
        and float(hit_rate_1w) < WEAK_HIT_RATE
        and float(within_4w) >= 0.70
        and realized_n >= MIN_FOCUS_SAMPLE_COUNT
    ):
        candidates.append(
            {
                "kind": "realization_lag",
                "key": "weeks_to_realization",
                "horizon": "1w_vs_4w",
                "count": realized_n,
                "prediction_hit_rate": hit_rate_1w,
                "median_weeks": realization.get("median_weeks"),
                "within_4w_rate": within_4w,
                "why": (
                    f"1w hit_rate={hit_rate_1w} but within_4w realization={within_4w} "
                    f"(median={realization.get('median_weeks')}w, n={realized_n}) "
                    "— opinion changes may fire before price; timing/conviction delay candidate"
                ),
            }
        )

    return candidates[:MAX_FOCUS_CANDIDATES]


def slim_trajectory_evidence_for_review(review: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact payload for analysis-review / learning-director (no event dump)."""
    if not isinstance(review, dict):
        return None
    summary = review.get("outcome_summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    candidates = review.get("model_focus_candidates")
    if not isinstance(candidates, list):
        candidates = build_model_focus_candidates(summary)
    boundary_summary = review.get("boundary_summary") or {}
    return {
        "purpose": (
            "PIT prediction calibration — output is model_focus_candidates for "
            "assessment-model (scoring/timing/conviction) refinement, not a standalone dataset"
        ),
        "observe_only": True,
        "snapshot_count": review.get("snapshot_count"),
        "transition_event_count": review.get("transition_event_count"),
        "labeled_event_count": summary.get("labeled_event_count"),
        "prediction_hit_rate_by_horizon": summary.get("prediction_hit_rate_by_horizon"),
        "weeks_to_realization": summary.get("weeks_to_realization"),
        "upgrade_events": summary.get("upgrade_events"),
        "downgrade_events": summary.get("downgrade_events"),
        "boundary_watch_count": review.get("boundary_watch_count"),
        "boundary_summary": boundary_summary,
        "model_focus_candidates": candidates,
        "note": summary.get("note"),
    }


def format_trajectory_evidence_markdown(payload: dict[str, Any]) -> str:
    review = payload.get("outcome_summary") or {}
    boundary = payload.get("boundary_summary") or {}
    lines = [
        "# Trajectory evidence review",
        "",
        f"Generated: {payload.get('generated_at')}",
        f"Archive snapshots: {payload.get('snapshot_count')}",
        f"Transition events: {payload.get('transition_event_count')}",
        f"Boundary watch panel: {payload.get('boundary_watch_count')}",
        f"Loser snapshot cards: {payload.get('loser_card_count')}",
        "",
        "## Boundary watch",
        "",
    ]
    if boundary:
        lines.append(
            f"- Panel count: {boundary.get('panel_count')} "
            f"(core tags only; mean weeks on boundary="
            f"{boundary.get('mean_weeks_on_boundary')})"
        )
        for tag, count in (boundary.get("by_core_tag") or {}).items():
            lines.append(f"- {tag}: {count}")
    else:
        lines.append("No boundary summary.")
    lines.extend(
        [
            "",
            "## Outcome summary (1-week forward)",
            "",
        ]
    )
    if review.get("labeled_event_count", 0) == 0:
        lines.append(review.get("note") or "No labeled transitions yet.")
    else:
        up = review.get("upgrade_events") or {}
        down = review.get("downgrade_events") or {}
        lines.append(
            f"- Upgrades: n={up.get('count')} mean={up.get('mean_forward_return')} "
            f"positive_rate={up.get('positive_rate')}"
        )
        lines.append(
            f"- Downgrades: n={down.get('count')} mean={down.get('mean_forward_return')} "
            f"positive_rate={down.get('positive_rate')}"
        )
        lines.append("")
        lines.append("### By transition key")
        for key, row in (review.get("by_transition_key") or {}).items():
            lines.append(
                f"- {key}: n={row.get('count')} mean={row.get('mean_forward_return')} "
                f"positive_rate={row.get('positive_rate')}"
            )
        lines.extend(["", "## Multi-horizon prediction calibration", ""])
        for horizon, stats in (review.get("prediction_hit_rate_by_horizon") or {}).items():
            lines.append(
                f"- {horizon}: scored={stats.get('scored_event_count')} "
                f"hit_rate={stats.get('prediction_hit_rate')}"
            )
        real = review.get("weeks_to_realization") or {}
        lines.extend(
            [
                "",
                "## Weeks to realization",
                "",
                f"- Realized within 12w: {real.get('realized_within_12w_count')}/"
                f"{real.get('scorable_event_count')} "
                f"(rate={real.get('realized_within_12w_rate')})",
                f"- Median weeks: {real.get('median_weeks')}",
                f"- Within 4w rate: {real.get('within_4w_rate')}",
            ]
        )
    candidates = payload.get("model_focus_candidates") or []
    if candidates:
        lines.extend(["", "## Model focus candidates (for analysis-review scoring)", ""])
        for row in candidates:
            lines.append(f"- [{row.get('kind')}] {row.get('why')}")
    lines.append("")
    return "\n".join(lines)


def run_trajectory_evidence(
    *,
    data_dir: Path = Path("docs/data"),
    run_at: datetime | None = None,
    include_loser_cards: bool = True,
) -> dict[str, Any]:
    """
    Build all four trajectory evidence pieces:

    1. Transition events ledger (sparse, full signal range)
    2. Boundary watch panel (near flip, not whole index)
    3. Loser snapshot cards (avoid + failed-buy alumni)
    4. Stratified outcome labels on transitions
    """
    data_dir = Path(data_dir)
    effective_run_at = run_at or datetime.now(UTC)

    snapshots = load_run_snapshots(data_dir)
    events = build_transition_events(snapshots)

    latest = read_json(data_dir / "latest.json") or {}
    reports = list(latest.get("reports") or [])
    boundary = build_boundary_watch_panel(reports, snapshots=snapshots)
    boundary_summary = summarize_boundary_panel(boundary)
    outcome_summary = summarize_transition_outcomes(events)
    focus_candidates = build_model_focus_candidates(outcome_summary)

    loser_payload: dict[str, Any] | None = None
    if include_loser_cards:
        loser_payload = run_loser_snapshot_cards(data_dir=data_dir, run_at=effective_run_at)

    transitions_path = data_dir / TRANSITIONS_FILENAME
    boundary_path = data_dir / BOUNDARY_FILENAME
    review_path = data_dir / REVIEW_FILENAME
    review_md_path = data_dir / REVIEW_MD_FILENAME

    transitions_doc = {
        "schema_version": 1,
        "scope": "trajectory_transitions",
        "observe_only": True,
        "generated_at": effective_run_at.isoformat(),
        "snapshot_count": len(snapshots),
        "event_count": len(events),
        "events": events,
    }
    boundary_doc = {
        "schema_version": 2,
        "scope": "trajectory_boundary_watch",
        "observe_only": True,
        "generated_at": effective_run_at.isoformat(),
        "screen_run_at": latest.get("run_at"),
        "panel_count": len(boundary),
        "summary": boundary_summary,
        "note": (
            "Names near tier boundaries (core tags required) — not the full hold tier. "
            "Includes archive-derived weeks_on_boundary and conviction deltas."
        ),
        "panel": boundary,
    }
    review_doc = {
        "schema_version": 1,
        "scope": "trajectory_evidence_review",
        "observe_only": True,
        "generated_at": effective_run_at.isoformat(),
        "snapshot_count": len(snapshots),
        "transition_event_count": len(events),
        "boundary_watch_count": len(boundary),
        "boundary_summary": boundary_summary,
        "loser_card_count": (loser_payload or {}).get("card_count"),
        "outcome_summary": outcome_summary,
        "model_focus_candidates": focus_candidates,
        "loser_cohort_counts": (loser_payload or {}).get("cohort_counts"),
    }

    write_json(transitions_path, transitions_doc, compact=True)
    write_json(boundary_path, boundary_doc, compact=True)
    write_json(review_path, review_doc, compact=True)
    review_md_path.write_text(format_trajectory_evidence_markdown(review_doc), encoding="utf-8")

    return {
        **review_doc,
        "transitions_path": str(transitions_path),
        "boundary_path": str(boundary_path),
        "review_path": str(review_path),
        "loser_cards_path": str(data_dir / "loser_snapshot_cards.json") if loser_payload else None,
    }


__all__ = [
    "BOUNDARY_FILENAME",
    "CORE_BOUNDARY_TAGS",
    "FORWARD_HORIZONS_WEEKS",
    "PRE_AVOID_CONVICTION",
    "PRE_BUY_CONVICTION",
    "REVIEW_FILENAME",
    "TRANSITIONS_FILENAME",
    "build_boundary_watch_panel",
    "build_model_focus_candidates",
    "build_transition_events",
    "run_trajectory_evidence",
    "slim_trajectory_evidence_for_review",
    "summarize_boundary_panel",
    "summarize_transition_outcomes",
]
