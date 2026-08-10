"""Observe-only archive sim for near-miss exit-timing priors (below buy tier).

Walks archived weekly screen snapshots and scores hypothetical hold-recovery
and swap-rotation paths using forward prices in the snapshot chain. Does not
replace live paper cohorts — priors for hold buffer / grace knobs until paper N
matures (deferred L118).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.backtest import RunSnapshot, load_run_snapshots
from value_investor.exit_timing_cohorts import (
    BREAKEVEN_THRESHOLD,
    DEFAULT_WINDOWS_DAYS,
    assess_framework_readiness,
    build_exit_timing_review,
    framework_metadata,
)
from value_investor.paper_fund import BUY_SIGNALS

COHORTS_FILENAME = "exit_timing_near_miss.json"
REVIEW_FILENAME = "exit_timing_near_miss_review.json"
ARCHIVE_TRACK_ID = "archive_near_miss"


@dataclass
class ExitTimingArchiveSimConfig:
    shadow_windows_days: tuple[int, ...] = DEFAULT_WINDOWS_DAYS
    min_conviction: float = 0.35
    min_data_quality: float = 0.0
    near_miss_signals: frozenset[str] = frozenset({"hold"})
    max_episodes_per_week: int = 10
    breakeven_threshold: float = BREAKEVEN_THRESHOLD


def _effective_signal(row: dict[str, Any]) -> str:
    adjusted = str(row.get("adjusted_signal") or "").strip()
    if adjusted:
        return adjusted
    return str(row.get("signal") or "").strip()


def _days_between_run_at(start: str, end: str) -> int:
    from value_investor.backtest import _parse_run_at

    start_dt = _parse_run_at(start)
    end_dt = _parse_run_at(end)
    return max(0, int((end_dt - start_dt).total_seconds() // 86400))


def _is_near_miss(row: dict[str, Any], cfg: ExitTimingArchiveSimConfig) -> bool:
    signal = _effective_signal(row)
    if signal in BUY_SIGNALS:
        return False
    if signal not in cfg.near_miss_signals:
        return False
    if float(row.get("conviction_score") or 0) < cfg.min_conviction:
        return False
    dq = row.get("data_quality_score")
    if cfg.min_data_quality > 0:
        if dq is None or float(dq) < cfg.min_data_quality:
            return False
    ticker = str(row.get("ticker") or "").strip()
    return bool(ticker)


def _best_buy_tier_row(snapshot: RunSnapshot) -> dict[str, Any] | None:
    best: tuple[float, dict[str, Any]] | None = None
    for row in snapshot.signals:
        if _effective_signal(row) not in BUY_SIGNALS:
            continue
        ticker = str(row.get("ticker") or "").strip()
        price = snapshot.prices.get(ticker)
        if not ticker or price is None or float(price) <= 0:
            continue
        conviction = float(row.get("conviction_score") or 0)
        if best is None or conviction > best[0]:
            best = (conviction, row)
    return best[1] if best else None


def _open_hold_episode(
    snapshot: RunSnapshot,
    row: dict[str, Any],
    cfg: ExitTimingArchiveSimConfig,
) -> dict[str, Any] | None:
    ticker = str(row.get("ticker") or "").strip()
    price = snapshot.prices.get(ticker)
    if not ticker or price is None or float(price) <= 0:
        return None
    entry = float(price)
    return {
        "episode_id": f"{ARCHIVE_TRACK_ID}:{snapshot.run_at}:{ticker}",
        "episode_kind": "near_miss_observe",
        "track_id": ARCHIVE_TRACK_ID,
        "ticker": ticker,
        "name": str(row.get("name") or ""),
        "started_at": snapshot.run_at,
        "status": "open",
        "stress_triggers": ["near_miss_below_buy_tier"],
        "entry_mark": round(entry, 4),
        "avg_cost": round(entry, 4),
        "unrealized_pct_at_start": 0.0,
        "screen_signal": str(row.get("signal") or ""),
        "effective_signal": _effective_signal(row),
        "data_quality_score": row.get("data_quality_score"),
        "conviction_score": row.get("conviction_score"),
        "exit_streak_at_start": 0,
        "momentum_grace": False,
        "checkpoints": [],
        "peak_unrealized_pct": 0.0,
        "trough_unrealized_pct": 0.0,
        "recovered_to_breakeven": None,
        "close_reason": None,
        "closed_at": None,
        "linked_sell_trade_id": None,
    }


def _open_swap_rotation(
    snapshot: RunSnapshot,
    near_miss: dict[str, Any],
    buy_row: dict[str, Any],
) -> dict[str, Any] | None:
    nm_ticker = str(near_miss.get("ticker") or "").strip()
    buy_ticker = str(buy_row.get("ticker") or "").strip()
    if not nm_ticker or not buy_ticker or nm_ticker == buy_ticker:
        return None
    nm_price = snapshot.prices.get(nm_ticker)
    buy_price = snapshot.prices.get(buy_ticker)
    if nm_price is None or buy_price is None or float(nm_price) <= 0 or float(buy_price) <= 0:
        return None

    def _leg(ticker: str, price: float) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "price": round(float(price), 4),
            "shares": 1.0,
            "gross": round(float(price), 2),
            "cost": 0.0,
        }

    return {
        "rotation_id": f"{ARCHIVE_TRACK_ID}:{snapshot.run_at}:{nm_ticker}:{buy_ticker}",
        "rotation_kind": "near_miss_swap_observe",
        "track_id": ARCHIVE_TRACK_ID,
        "logged_at": snapshot.run_at,
        "status": "open",
        "trade_cost_pct": 0.0,
        "near_miss_ticker": nm_ticker,
        "swap_ticker": buy_ticker,
        "sells": [_leg(nm_ticker, nm_price)],
        "buys": [_leg(buy_ticker, buy_price)],
        "checkpoints": [],
        "sell_returns_since_rotation": {},
        "buy_returns_since_rotation": {},
        "verdict": None,
        "closed_at": None,
    }


def _score_hold_episode(
    episode: dict[str, Any],
    snapshots: list[RunSnapshot],
    cfg: ExitTimingArchiveSimConfig,
) -> None:
    started_at = str(episode.get("started_at") or "")
    ticker = str(episode.get("ticker") or "")
    entry_price = float(episode.get("avg_cost") or 0)
    if not started_at or not ticker or entry_price <= 0:
        return

    max_window = max(cfg.shadow_windows_days) if cfg.shadow_windows_days else 84
    scored_days = {int(cp.get("days_after") or 0) for cp in episode.get("checkpoints") or []}

    for snap in snapshots:
        if _days_between_run_at(started_at, snap.run_at) == 0:
            continue
        days_elapsed = _days_between_run_at(started_at, snap.run_at)
        price = snap.prices.get(ticker)
        if price is None or float(price) <= 0:
            continue

        unrealized = (float(price) - entry_price) / entry_price
        episode["peak_unrealized_pct"] = round(
            max(float(episode.get("peak_unrealized_pct") or unrealized), unrealized),
            4,
        )
        episode["trough_unrealized_pct"] = round(
            min(float(episode.get("trough_unrealized_pct") or unrealized), unrealized),
            4,
        )
        if unrealized >= cfg.breakeven_threshold:
            episode["recovered_to_breakeven"] = True

        for window in cfg.shadow_windows_days:
            if days_elapsed < window or window in scored_days:
                continue
            episode.setdefault("checkpoints", []).append(
                {
                    "scored_at": snap.run_at,
                    "days_after": window,
                    "price": round(float(price), 4),
                    "unrealized_pct": round(unrealized, 4),
                    "peak_unrealized_pct": episode["peak_unrealized_pct"],
                    "trough_unrealized_pct": episode["trough_unrealized_pct"],
                }
            )
            scored_days.add(window)

        if days_elapsed >= max_window:
            episode["status"] = "closed"
            episode["closed_at"] = snap.run_at
            episode["close_reason"] = (
                "recovered_max_window"
                if episode.get("recovered_to_breakeven")
                else "underwater_max_window"
            )
            return

    if str(episode.get("status") or "open") == "open" and snapshots:
        last = snapshots[-1]
        days_elapsed = _days_between_run_at(started_at, last.run_at)
        if days_elapsed > 0:
            episode["status"] = "closed"
            episode["closed_at"] = last.run_at
            episode["close_reason"] = (
                "recovered_archive_end"
                if episode.get("recovered_to_breakeven")
                else "underwater_archive_end"
            )


def _score_swap_rotation(
    rotation: dict[str, Any],
    snapshots: list[RunSnapshot],
    cfg: ExitTimingArchiveSimConfig,
) -> None:
    logged_at = str(rotation.get("logged_at") or "")
    if not logged_at:
        return

    sell_leg = (rotation.get("sells") or [{}])[0]
    buy_leg = (rotation.get("buys") or [{}])[0]
    sell_ticker = str(sell_leg.get("ticker") or "")
    buy_ticker = str(buy_leg.get("ticker") or "")
    sell_entry = float(sell_leg.get("price") or 0)
    buy_entry = float(buy_leg.get("price") or 0)
    if not sell_ticker or not buy_ticker or sell_entry <= 0 or buy_entry <= 0:
        return

    max_window = max(cfg.shadow_windows_days) if cfg.shadow_windows_days else 84
    scored_days = {int(cp.get("days_after") or 0) for cp in rotation.get("checkpoints") or []}

    for snap in snapshots:
        if _days_between_run_at(logged_at, snap.run_at) == 0:
            continue
        days_elapsed = _days_between_run_at(logged_at, snap.run_at)
        sell_mark = snap.prices.get(sell_ticker)
        buy_mark = snap.prices.get(buy_ticker)
        if sell_mark is None or buy_mark is None:
            continue
        sell_ret = (float(sell_mark) - sell_entry) / sell_entry
        buy_ret = (float(buy_mark) - buy_entry) / buy_entry
        rotation["sell_returns_since_rotation"] = {sell_ticker: round(sell_ret, 4)}
        rotation["buy_returns_since_rotation"] = {buy_ticker: round(buy_ret, 4)}

        for window in cfg.shadow_windows_days:
            if days_elapsed < window or window in scored_days:
                continue
            rotation.setdefault("checkpoints", []).append(
                {
                    "scored_at": snap.run_at,
                    "days_after": window,
                    "avg_sell_return": round(sell_ret, 4),
                    "avg_buy_return": round(buy_ret, 4),
                    "replacement_delta": round(buy_ret - sell_ret, 4),
                }
            )
            scored_days.add(window)

        if days_elapsed >= max_window:
            rotation["status"] = "closed"
            rotation["closed_at"] = snap.run_at
            checkpoints = rotation.get("checkpoints") or []
            last = checkpoints[-1] if checkpoints else {}
            delta = last.get("replacement_delta")
            if delta is None:
                rotation["verdict"] = "inconclusive"
            elif float(delta) > 0:
                rotation["verdict"] = "replacement_outperformed"
            elif float(delta) < 0:
                rotation["verdict"] = "exit_outperformed"
            else:
                rotation["verdict"] = "inconclusive"
            return

    if str(rotation.get("status") or "open") == "open" and snapshots:
        last = snapshots[-1]
        days_elapsed = _days_between_run_at(logged_at, last.run_at)
        if days_elapsed > 0:
            rotation["status"] = "closed"
            rotation["closed_at"] = last.run_at
            checkpoints = rotation.get("checkpoints") or []
            last_cp = checkpoints[-1] if checkpoints else {}
            delta = last_cp.get("replacement_delta")
            if delta is None:
                rotation["verdict"] = "inconclusive"
            elif float(delta) > 0:
                rotation["verdict"] = "replacement_outperformed"
            elif float(delta) < 0:
                rotation["verdict"] = "exit_outperformed"
            else:
                rotation["verdict"] = "inconclusive"


def archive_sim_metadata() -> dict[str, Any]:
    base = framework_metadata()
    base["scope"] = "archive_near_miss"
    base["near_miss_gate"] = {
        "below_buy_tier": True,
        "default_signals": sorted({"hold"}),
        "default_min_conviction": 0.35,
    }
    base["note"] = (
        "Observe-only priors from archived weekly screens. "
        "Does not replace live paper exit_timing cohorts."
    )
    return base


def run_exit_timing_archive_sim(
    output_dir: Path,
    *,
    config: ExitTimingArchiveSimConfig | None = None,
) -> dict[str, Any]:
    """Score near-miss hold/swap paths from archived run snapshots."""
    cfg = config or ExitTimingArchiveSimConfig()
    output_dir = Path(output_dir)
    snapshots = load_run_snapshots(output_dir)

    if len(snapshots) < 2:
        review = {
            "schema_version": 1,
            "scope": "archive_near_miss",
            "track_id": ARCHIVE_TRACK_ID,
            "generated_at": datetime.now(UTC).isoformat(),
            "framework": archive_sim_metadata(),
            "snapshot_count": len(snapshots),
            "readiness": assess_framework_readiness({"hold_episodes": [], "swap_rotations": []}),
            "note": "Need at least 2 archived run snapshots (ftse-archive-history).",
        }
        _write_artifacts(output_dir, {"hold_episodes": [], "swap_rotations": []}, review)
        return review

    hold_episodes: list[dict[str, Any]] = []
    swap_rotations: list[dict[str, Any]] = []

    for entry in snapshots[:-1]:
        near_miss_rows = [
            row for row in entry.signals if _is_near_miss(row, cfg)
        ]
        near_miss_rows.sort(
            key=lambda row: float(row.get("conviction_score") or 0),
            reverse=True,
        )
        if cfg.max_episodes_per_week > 0:
            near_miss_rows = near_miss_rows[: cfg.max_episodes_per_week]

        buy_row = _best_buy_tier_row(entry)

        for row in near_miss_rows:
            episode = _open_hold_episode(entry, row, cfg)
            if episode is not None:
                hold_episodes.append(episode)
            if buy_row is not None:
                rotation = _open_swap_rotation(entry, row, buy_row)
                if rotation is not None:
                    swap_rotations.append(rotation)

    for episode in hold_episodes:
        _score_hold_episode(episode, snapshots, cfg)
    for rotation in swap_rotations:
        _score_swap_rotation(rotation, snapshots, cfg)

    store = {
        "schema_version": 1,
        "scope": "archive_near_miss",
        "track_id": ARCHIVE_TRACK_ID,
        "framework": archive_sim_metadata(),
        "config": {
            "min_conviction": cfg.min_conviction,
            "min_data_quality": cfg.min_data_quality,
            "near_miss_signals": sorted(cfg.near_miss_signals),
            "max_episodes_per_week": cfg.max_episodes_per_week,
            "shadow_windows_days": list(cfg.shadow_windows_days),
        },
        "snapshot_count": len(snapshots),
        "hold_episodes": hold_episodes,
        "swap_rotations": swap_rotations,
        "updated_at": datetime.now(UTC).isoformat(),
    }

    review = build_exit_timing_review(store, track_id=ARCHIVE_TRACK_ID)
    review["scope"] = "archive_near_miss"
    review["framework"] = archive_sim_metadata()
    review["snapshot_count"] = len(snapshots)
    review["episodes_opened"] = {
        "hold_recovery": len(hold_episodes),
        "swap_rotation": len(swap_rotations),
    }
    review["note"] = (
        "Archive near-miss observe sim — priors only; pair with live "
        "learning_tracks_exit_timing.json for paper-track evidence."
    )
    _write_artifacts(output_dir, store, review)
    return review


def _write_artifacts(output_dir: Path, store: dict[str, Any], review: dict[str, Any]) -> None:
    cohorts_path = output_dir / COHORTS_FILENAME
    review_path = output_dir / REVIEW_FILENAME
    cohorts_path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")


def format_exit_timing_archive_text(review: dict[str, Any]) -> str:
    readiness = review.get("readiness") or {}
    hold = (review.get("hold_recovery") or {}).get("closed") or {}
    swap = (review.get("swap_rotation") or {}).get("closed") or {}
    lines = [
        "Exit-timing archive near-miss sim (observe-only priors)",
        f"  Snapshots: {review.get('snapshot_count', 0)}",
        f"  Closed hold episodes: {hold.get('count', 0)}",
        f"  Closed swap rotations: {swap.get('count', 0)}",
        f"  Ready for probability work: {readiness.get('ready_for_probability_analysis')}",
    ]
    note = review.get("note")
    if note:
        lines.append(f"  Note: {note}")
    return "\n".join(lines)
