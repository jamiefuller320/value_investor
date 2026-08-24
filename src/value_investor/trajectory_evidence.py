"""Trajectory evidence: transitions, boundary watch, outcome labels (+ loser cards)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
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
        forward_snap = sorted_snaps[index + 1] if index + 1 < len(sorted_snaps) else None

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
                    "outcomes": {
                        "forward_return_1w": _forward_return(ticker, curr, forward_snap),
                        "label_note": (
                            "1-week forward return from transition week_to to next archive"
                            if forward_snap
                            else "Awaiting next archive for forward label"
                        ),
                    },
                }
            )
    return events


def _boundary_tags(row: dict[str, Any]) -> list[str]:
    signal = str(row.get("signal") or "hold").lower()
    conviction = float(row.get("conviction_score") or 0)
    trend = str(row.get("signal_trend") or "").lower()
    timing = str(row.get("timing_signal") or "").lower()
    tags: list[str] = []

    if signal == "hold" and conviction >= 0.28:
        tags.append("pre_buy")
    if signal == "hold" and conviction <= 0.12:
        tags.append("pre_avoid")
    if signal in BUY_SIGNALS and trend == "deteriorating":
        tags.append("buy_weakening")
    if signal == "buy" and conviction >= 0.50:
        tags.append("strong_buy_candidate")
    if signal in BUY_SIGNALS and timing == "wait":
        tags.append("timing_wait_on_buy_tier")
    if signal == "avoid" and conviction >= 0.20:
        tags.append("avoid_recovery_candidate")
    if trend == "new" and signal in {"hold", "buy", "strong_buy"}:
        tags.append("fresh_opinion")
    return tags


def build_boundary_watch_panel(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Names near tier boundaries — full-range trajectory watch, not whole index."""
    panel: list[dict[str, Any]] = []
    for row in reports:
        tags = _boundary_tags(row)
        if not tags:
            continue
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
                "boundary_tags": tags,
            }
        )
    panel.sort(key=lambda item: (-len(item["boundary_tags"]), str(item.get("ticker") or "")))
    return panel


def summarize_transition_outcomes(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Stratified outcome labels by transition type (evaluation only)."""
    labeled = [
        event
        for event in events
        if (event.get("outcomes") or {}).get("forward_return_1w") is not None
    ]
    if not labeled:
        return {
            "labeled_event_count": 0,
            "note": "Need >=3 archive snapshots for 1-week forward labels on transitions",
        }

    by_key: dict[str, list[float]] = {}
    upgrades: list[float] = []
    downgrades: list[float] = []
    for event in labeled:
        ret = float((event.get("outcomes") or {})["forward_return_1w"])
        key = str(event.get("transition_key") or "unknown")
        by_key.setdefault(key, []).append(ret)
        direction = str(event.get("direction") or "")
        if direction == "upgrade":
            upgrades.append(ret)
        elif direction == "downgrade":
            downgrades.append(ret)

    def _bucket(name: str, values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0}
        positive = sum(1 for value in values if value > 0)
        return {
            "count": len(values),
            "mean_forward_return_1w": round(mean(values), 6),
            "positive_rate": round(positive / len(values), 4),
        }

    return {
        "labeled_event_count": len(labeled),
        "by_transition_key": {key: _bucket(key, vals) for key, vals in sorted(by_key.items())},
        "upgrade_events": _bucket("upgrade", upgrades),
        "downgrade_events": _bucket("downgrade", downgrades),
        "note": "Hindsight labels for marker development — not used to define live signals",
    }


def format_trajectory_evidence_markdown(payload: dict[str, Any]) -> str:
    review = payload.get("outcome_summary") or {}
    lines = [
        "# Trajectory evidence review",
        "",
        f"Generated: {payload.get('generated_at')}",
        f"Archive snapshots: {payload.get('snapshot_count')}",
        f"Transition events: {payload.get('transition_event_count')}",
        f"Boundary watch panel: {payload.get('boundary_watch_count')}",
        f"Loser snapshot cards: {payload.get('loser_card_count')}",
        "",
        "## Outcome summary (1-week forward)",
        "",
    ]
    if review.get("labeled_event_count", 0) == 0:
        lines.append(review.get("note") or "No labeled transitions yet.")
    else:
        up = review.get("upgrade_events") or {}
        down = review.get("downgrade_events") or {}
        lines.append(
            f"- Upgrades: n={up.get('count')} mean={up.get('mean_forward_return_1w')} "
            f"positive_rate={up.get('positive_rate')}"
        )
        lines.append(
            f"- Downgrades: n={down.get('count')} mean={down.get('mean_forward_return_1w')} "
            f"positive_rate={down.get('positive_rate')}"
        )
        lines.append("")
        lines.append("### By transition key")
        for key, row in (review.get("by_transition_key") or {}).items():
            lines.append(
                f"- {key}: n={row.get('count')} mean={row.get('mean_forward_return_1w')} "
                f"positive_rate={row.get('positive_rate')}"
            )
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
    boundary = build_boundary_watch_panel(reports)
    outcome_summary = summarize_transition_outcomes(events)

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
        "schema_version": 1,
        "scope": "trajectory_boundary_watch",
        "observe_only": True,
        "generated_at": effective_run_at.isoformat(),
        "screen_run_at": latest.get("run_at"),
        "panel_count": len(boundary),
        "note": "Names near tier boundaries — not the full hold tier",
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
        "loser_card_count": (loser_payload or {}).get("card_count"),
        "outcome_summary": outcome_summary,
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
    "REVIEW_FILENAME",
    "TRANSITIONS_FILENAME",
    "build_boundary_watch_panel",
    "build_transition_events",
    "run_trajectory_evidence",
    "summarize_transition_outcomes",
]
