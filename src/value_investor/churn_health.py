"""Deterministic churn / cost health rollup for paper learning tracks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.paper_automation import (
    AI_JUDGMENT_TRACK_ID,
    MOMENTUM_GRACE_TRACK_ID,
    RULES_TRACK_ID,
    learning_track_dirs,
)
from value_investor.storage import read_json, write_json

CHURN_HEALTH_FILENAME = "learning_tracks_churn_health.json"
DEFAULT_LOOKBACK_DAYS = 7


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _local_trading_day(value: str | None) -> str | None:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return None
    return parsed.date().isoformat()


def _trades_in_window(
    trades: list[dict[str, Any]],
    *,
    since: datetime,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    end = until or datetime.now(UTC)
    kept: list[dict[str, Any]] = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        acted = _parse_iso_datetime(str(trade.get("acted_at") or ""))
        if acted is None:
            continue
        acted_utc = acted.astimezone(UTC)
        if since <= acted_utc <= end:
            kept.append(trade)
    return kept


def _adjacent_side_flips(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sell immediately followed by buy on the same ticker (or vice versa)."""
    flips: list[dict[str, Any]] = []
    prev: tuple[str, str] | None = None
    for trade in trades:
        ticker = str(trade.get("ticker") or "")
        side = str(trade.get("side") or "")
        if not ticker or side not in {"buy", "sell"}:
            continue
        if prev and prev[0] == ticker and prev[1] != side:
            flips.append(
                {
                    "ticker": ticker,
                    "from_side": prev[1],
                    "to_side": side,
                    "acted_at": trade.get("acted_at"),
                }
            )
        prev = (ticker, side)
    return flips


def _count_plan_buffer_holds(plan: dict[str, Any]) -> int:
    holds = plan.get("anticipated_holds") or plan.get("holds") or []
    return sum(
        1
        for row in holds
        if isinstance(row, dict) and "hold buffer" in str(row.get("reason") or "").lower()
    )


def _count_plan_reentry_skips(plan: dict[str, Any]) -> int:
    skipped = plan.get("skipped") or []
    return sum(
        1
        for row in skipped
        if isinstance(row, dict) and "re-entry cooldown" in str(row.get("reason") or "").lower()
    )


def summarize_track_churn_health(
    track_dir: Path,
    *,
    track_id: str,
    as_of: datetime | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Build per-track churn metrics from committed paper-auto artifacts."""
    when = as_of or datetime.now(UTC)
    since = when - timedelta(days=int(lookback_days))
    track_dir = Path(track_dir)

    review = read_json(track_dir / "decision_review.json") or {}
    review_metrics = review.get("metrics") or {}
    config = read_json(track_dir / "config.json") or {}
    fund = read_json(track_dir / "automated_fund.json") or {}
    last_run = read_json(track_dir / "last_run.json") or {}
    plan = last_run.get("plan") or {}
    rebalance_state = fund.get("rebalance_state") or {}

    trades = [row for row in (fund.get("trades") or []) if isinstance(row, dict)]
    window_trades = _trades_in_window(trades, since=since, until=when)
    full_exits = [
        trade
        for trade in window_trades
        if trade.get("side") == "sell"
        and "trim" not in str(trade.get("note") or "").lower()
    ]
    trims = [
        trade
        for trade in window_trades
        if trade.get("side") == "sell" and "trim" in str(trade.get("note") or "").lower()
    ]
    buys = [trade for trade in window_trades if trade.get("side") == "buy"]

    last_run_trades = [row for row in (last_run.get("trades") or []) if isinstance(row, dict)]
    last_run_day = _local_trading_day((last_run.get("gate") or {}).get("local_time"))
    as_of_day = when.astimezone().date().isoformat()
    trade_window_key = f"trades_last_{lookback_days}d"
    window_summary = {
        "total": len(window_trades),
        "buys": len(buys),
        "sells": len(full_exits),
        "trims": len(trims),
        "full_exits": len(full_exits),
        "adjacent_side_flips": _adjacent_side_flips(window_trades),
        "adjacent_flip_count": len(_adjacent_side_flips(window_trades)),
    }

    return {
        "track_id": track_id,
        "output_dir": str(track_dir),
        "is_primary_learning_track": bool(config.get("is_primary_learning_track", False)),
        "guards": {
            "exit_confirm_screens": int(config.get("exit_confirm_screens", 2)),
            "reentry_cooldown_screens": int(config.get("reentry_cooldown_screens", 1)),
            "min_rebalance_notional_gbp": float(config.get("min_rebalance_notional_gbp", 10.0)),
        },
        "decision_review": {
            "reviewed_at": review.get("reviewed_at"),
            "applied": bool(review.get("applied")),
            "enough_history": bool(review.get("enough_history")),
            "cost_drag": review_metrics.get("cost_drag"),
            "total_costs": review_metrics.get("total_costs"),
            "trade_count": review_metrics.get("trade_count"),
            "excess_after_costs": review_metrics.get("excess_after_costs"),
            "knobs_after": review.get("knobs_after"),
            "proposed_changes": review.get("proposed_changes"),
            "reasons": review.get("reasons") or [],
        },
        "rebalance_state": {
            "exit_streak": dict(rebalance_state.get("exit_streak") or {}),
            "reentry_cooldown": dict(rebalance_state.get("reentry_cooldown") or {}),
            "buffered_holdings": len(rebalance_state.get("exit_streak") or {}),
        },
        "last_run": {
            "acted": bool(last_run.get("acted")),
            "note": last_run.get("note"),
            "trade_count": len(last_run_trades),
            "duplicate_day_skip": "Already rebalanced today" in str(last_run.get("note") or ""),
            "buffer_holds_planned": _count_plan_buffer_holds(plan),
            "reentry_skips_planned": _count_plan_reentry_skips(plan),
            "same_trading_day_as_as_of": last_run_day == as_of_day if last_run_day else False,
        },
        trade_window_key: window_summary,
    }


def build_churn_health(
    paper_root: Path,
    *,
    as_of: datetime | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Aggregate churn health across all paper learning tracks."""
    paper_root = Path(paper_root)
    when = as_of or datetime.now(UTC)
    dirs = learning_track_dirs(paper_root)
    tracks: dict[str, Any] = {}
    for track_id, track_dir in dirs.items():
        if track_dir.exists():
            tracks[track_id] = summarize_track_churn_health(
                track_dir,
                track_id=track_id,
                as_of=when,
                lookback_days=lookback_days,
            )

    primary = tracks.get(AI_JUDGMENT_TRACK_ID) or {}
    control = tracks.get(RULES_TRACK_ID) or {}
    primary_drag = (primary.get("decision_review") or {}).get("cost_drag")
    control_drag = (control.get("decision_review") or {}).get("cost_drag")

    alerts: list[dict[str, str]] = []
    if isinstance(control_drag, (int, float)) and control_drag >= 0.06:
        alerts.append(
            {
                "severity": "watch",
                "track": RULES_TRACK_ID,
                "title": "Elevated rules-track cost drag",
                "summary": f"cost_drag={control_drag:.1%} — review churn guards and conviction floor.",
            }
        )
    if isinstance(primary_drag, (int, float)) and primary_drag >= 0.06:
        alerts.append(
            {
                "severity": "watch",
                "track": AI_JUDGMENT_TRACK_ID,
                "title": "Elevated AI-judgment cost drag",
                "summary": f"cost_drag={primary_drag:.1%} — review churn guards and selectivity.",
            }
        )
    for track_id, row in tracks.items():
        window = next(
            (value for key, value in row.items() if str(key).startswith("trades_last_")),
            {},
        )
        flip_count = int(window.get("adjacent_flip_count") or 0)
        if flip_count > 0:
            alerts.append(
                {
                    "severity": "info",
                    "track": track_id,
                    "title": "Adjacent buy/sell flips in lookback window",
                    "summary": f"{flip_count} adjacent side flip(s) in last {lookback_days}d.",
                }
            )
        if (row.get("last_run") or {}).get("duplicate_day_skip"):
            alerts.append(
                {
                    "severity": "info",
                    "track": track_id,
                    "title": "Same-day duplicate rebalance skipped",
                    "summary": "Last run hit same-day idempotency guard.",
                }
            )

    return {
        "schema_version": 1,
        "generated_at": when.isoformat(),
        "lookback_days": int(lookback_days),
        "primary_learning_track": AI_JUDGMENT_TRACK_ID,
        "control_track": RULES_TRACK_ID,
        "experimental_track": MOMENTUM_GRACE_TRACK_ID,
        "tracks": tracks,
        "alerts": alerts,
    }


def write_churn_health(
    paper_root: Path,
    *,
    as_of: datetime | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Write learning_tracks_churn_health.json under the paper automation root."""
    paper_root = Path(paper_root)
    payload = build_churn_health(
        paper_root,
        as_of=as_of,
        lookback_days=lookback_days,
    )
    path = paper_root / CHURN_HEALTH_FILENAME
    write_json(path, payload, compact=False)
    return payload
