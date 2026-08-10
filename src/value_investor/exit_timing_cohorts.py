"""Observe-only hold-recovery and swap-rotation cohorts for exit-timing research.

Collects data to answer later:
  P(hold -> breakeven) vs P(swap -> better prospect)

Does not change live paper books, knobs, or decision-review apply paths.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.paper_fund import BUY_SIGNALS, PaperFund, Position

COHORTS_FILENAME = "exit_timing_cohorts.json"
REVIEW_FILENAME = "exit_timing_cohorts_review.json"
DEFAULT_WINDOWS_DAYS = (7, 28, 56, 84)
BREAKEVEN_THRESHOLD = 0.0
UNDERWATER_THRESHOLD = -0.01


@dataclass
class ExitTimingCohortConfig:
    shadow_windows_days: tuple[int, ...] = DEFAULT_WINDOWS_DAYS
    underwater_threshold: float = UNDERWATER_THRESHOLD
    breakeven_threshold: float = BREAKEVEN_THRESHOLD


def _parse_date(value: str | datetime | None):
    from datetime import date

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def _days_between(start: str, end: str | datetime | None) -> int:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date is None or end_date is None:
        return 0
    return max(0, (end_date - start_date).days)


def framework_metadata() -> dict[str, Any]:
    """Describe the analysis strand and readiness for downstream probability work."""
    return {
        "purpose": (
            "Observe-only cohorts for hold-to-breakeven vs swap-success exit timing. "
            "Knob changes remain manual until cohorts mature (see deferred N25/L85/L117)."
        ),
        "hold_recovery": {
            "question": "When a position is stressed but still held, does it recover to breakeven?",
            "episode_triggers": [
                "unrealized below underwater_threshold",
                "exit_streak >= 1 (hold buffer active)",
                "momentum_grace on position",
                "effective signal no longer buy-tier while still held",
            ],
            "outcomes": [
                "recovered_to_breakeven (peak unrealized >= breakeven_threshold)",
                "sold_while_underwater",
                "max_window_elapsed",
            ],
            "fields_for_later_analysis": [
                "data_quality_score",
                "conviction_score",
                "screen_signal",
                "effective_signal",
                "exit_streak",
                "stress_triggers",
                "checkpoints",
            ],
        },
        "swap_rotation": {
            "question": "When we rotate (sell + buy same pass), does the replacement beat the exit?",
            "pairing": "same rebalance pass sells vs buys on one track",
            "outcomes": [
                "replacement_outperformed",
                "exit_outperformed",
                "inconclusive",
            ],
            "fields_for_later_analysis": [
                "sell_tickers",
                "buy_tickers",
                "sell_realized_pct",
                "post_rotation_returns",
                "trade_costs",
            ],
        },
        "related_artifacts": [
            "exit_shadow.json (post-exit path after sell)",
            "rebalance_log.json (counterfactual replay)",
            "learning_tracks_churn_health.json",
        ],
    }


def _candidate_map(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for row in candidates:
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker:
            mapped[ticker] = row
    return mapped


def _effective_signal(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    adjusted = str(row.get("adjusted_signal") or "").strip()
    if adjusted:
        return adjusted
    return str(row.get("signal") or "").strip()


def _hold_stress_triggers(
    *,
    position: Position,
    mark_price: float,
    candidate: dict[str, Any] | None,
    exit_streak: int,
    cfg: ExitTimingCohortConfig,
) -> list[str]:
    triggers: list[str] = []
    if mark_price > 0 and position.avg_cost > 0:
        unrealized = (mark_price - position.avg_cost) / position.avg_cost
        if unrealized <= cfg.underwater_threshold:
            triggers.append("underwater")
    if exit_streak >= 1:
        triggers.append("exit_streak")
    if position.momentum_grace:
        triggers.append("momentum_grace")
    signal = _effective_signal(candidate)
    if signal and signal not in BUY_SIGNALS:
        triggers.append("signal_downgrade")
    return triggers


def _episode_id(track_id: str, ticker: str, started_at: str) -> str:
    return f"{track_id}:{ticker}:{started_at}"


def ingest_hold_episodes(
    fund: PaperFund,
    store: dict[str, Any],
    *,
    track_id: str,
    candidates: list[dict[str, Any]],
    prices_by_ticker: dict[str, float],
    as_of: str,
    cfg: ExitTimingCohortConfig | None = None,
) -> int:
    """Open hold-recovery episodes when stress triggers fire on an open position."""
    cfg = cfg or ExitTimingCohortConfig()
    cmap = _candidate_map(candidates)
    episodes: list[dict[str, Any]] = list(store.get("hold_episodes") or [])
    open_by_ticker = {
        str(row.get("ticker")): row
        for row in episodes
        if str(row.get("status") or "open") == "open"
    }
    added = 0
    exit_streaks = dict(fund.rebalance_state.exit_streak or {})

    for ticker, position in fund.holdings.items():
        mark = prices_by_ticker.get(ticker)
        if mark is None or mark <= 0:
            continue
        candidate = cmap.get(ticker.upper()) or cmap.get(ticker)
        triggers = _hold_stress_triggers(
            position=position,
            mark_price=mark,
            candidate=candidate,
            exit_streak=int(exit_streaks.get(ticker, 0)),
            cfg=cfg,
        )
        if not triggers:
            continue
        if ticker in open_by_ticker:
            continue
        started_at = str(as_of)
        episode = {
            "episode_id": _episode_id(track_id, ticker, started_at),
            "track_id": track_id,
            "ticker": ticker,
            "name": position.name,
            "started_at": started_at,
            "status": "open",
            "stress_triggers": triggers,
            "entry_mark": round(mark, 4),
            "avg_cost": round(position.avg_cost, 4),
            "unrealized_pct_at_start": round(
                (mark - position.avg_cost) / position.avg_cost if position.avg_cost > 0 else 0.0,
                4,
            ),
            "screen_signal": str((candidate or {}).get("signal") or ""),
            "effective_signal": _effective_signal(candidate),
            "data_quality_score": (candidate or {}).get("data_quality_score"),
            "conviction_score": (candidate or {}).get("conviction_score"),
            "exit_streak_at_start": int(exit_streaks.get(ticker, 0)),
            "momentum_grace": bool(position.momentum_grace),
            "checkpoints": [],
            "peak_unrealized_pct": round(
                (mark - position.avg_cost) / position.avg_cost if position.avg_cost > 0 else 0.0,
                4,
            ),
            "trough_unrealized_pct": round(
                (mark - position.avg_cost) / position.avg_cost if position.avg_cost > 0 else 0.0,
                4,
            ),
            "recovered_to_breakeven": None,
            "close_reason": None,
            "closed_at": None,
            "linked_sell_trade_id": None,
        }
        episodes.append(episode)
        open_by_ticker[ticker] = episode
        added += 1

    store["hold_episodes"] = episodes
    return added


def update_hold_episodes(
    fund: PaperFund,
    store: dict[str, Any],
    *,
    prices_by_ticker: dict[str, float],
    as_of: str,
    cfg: ExitTimingCohortConfig | None = None,
) -> int:
    """Refresh open hold episodes with marks; close on sell, recovery window, or max horizon."""
    cfg = cfg or ExitTimingCohortConfig()
    when = str(as_of)
    max_window = max(cfg.shadow_windows_days) if cfg.shadow_windows_days else 84
    updated = 0
    episodes: list[dict[str, Any]] = list(store.get("hold_episodes") or [])
    holdings = set(fund.holdings.keys())

    for episode in episodes:
        if str(episode.get("status") or "open") != "open":
            continue
        ticker = str(episode.get("ticker") or "")
        avg_cost = float(episode.get("avg_cost") or 0)
        price = prices_by_ticker.get(ticker)
        if price is None or price <= 0 or avg_cost <= 0:
            continue

        unrealized = (price - avg_cost) / avg_cost
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

        scored_days = {int(cp.get("days_after") or 0) for cp in episode.get("checkpoints") or []}
        days_elapsed = _days_between(str(episode.get("started_at") or ""), when)
        for window in cfg.shadow_windows_days:
            if days_elapsed < window or window in scored_days:
                continue
            episode.setdefault("checkpoints", []).append(
                {
                    "scored_at": when,
                    "days_after": window,
                    "price": round(price, 4),
                    "unrealized_pct": round(unrealized, 4),
                    "peak_unrealized_pct": episode["peak_unrealized_pct"],
                    "trough_unrealized_pct": episode["trough_unrealized_pct"],
                }
            )
            updated += 1

        if ticker not in holdings:
            episode["status"] = "closed"
            episode["closed_at"] = when
            episode["close_reason"] = (
                "sold_while_recovered"
                if episode.get("recovered_to_breakeven")
                else "sold_while_underwater"
            )
            sell = next(
                (
                    t
                    for t in reversed(fund.trades)
                    if str(t.get("side") if isinstance(t, dict) else getattr(t, "side", ""))
                    == "sell"
                    and str(t.get("ticker") if isinstance(t, dict) else getattr(t, "ticker", ""))
                    == ticker
                ),
                None,
            )
            if sell is not None:
                episode["linked_sell_trade_id"] = str(
                    sell.get("id") if isinstance(sell, dict) else getattr(sell, "id", "")
                )
            continue

        if days_elapsed >= max_window:
            episode["status"] = "closed"
            episode["closed_at"] = when
            episode["close_reason"] = (
                "recovered_max_window"
                if episode.get("recovered_to_breakeven")
                else "underwater_max_window"
            )

    store["hold_episodes"] = episodes
    return updated


def ingest_swap_rotations(
    store: dict[str, Any],
    *,
    track_id: str,
    trades: list[dict[str, Any]],
    as_of: str,
    trade_cost_pct: float,
) -> int:
    """Record same-pass sell+buy rotations for swap-success analysis."""
    sells = [t for t in trades if str(t.get("side") or "") == "sell"]
    buys = [t for t in trades if str(t.get("side") or "") == "buy"]
    if not sells or not buys:
        return 0

    rotations: list[dict[str, Any]] = list(store.get("swap_rotations") or [])
    rotation_id = f"{track_id}:{as_of}"
    if any(str(row.get("rotation_id") or "") == rotation_id for row in rotations):
        return 0

    def _leg(row: dict[str, Any], side: str) -> dict[str, Any]:
        price = float(row.get("price") or 0)
        avg_cost = float(row.get("avg_cost_at_exit") or 0)
        realized = ((price - avg_cost) / avg_cost) if side == "sell" and avg_cost > 0 else None
        payload = {
            "ticker": str(row.get("ticker") or ""),
            "price": round(price, 4),
            "shares": round(float(row.get("shares") or 0), 6),
            "gross": round(float(row.get("gross") or 0), 2),
            "cost": round(float(row.get("cost") or 0), 2),
        }
        if realized is not None:
            payload["realized_pct"] = round(realized, 4)
        return payload

    rotations.append(
        {
            "rotation_id": rotation_id,
            "track_id": track_id,
            "logged_at": str(as_of),
            "status": "open",
            "trade_cost_pct": round(float(trade_cost_pct), 4),
            "sells": [_leg(row, "sell") for row in sells],
            "buys": [_leg(row, "buy") for row in buys],
            "checkpoints": [],
            "sell_returns_since_rotation": {},
            "buy_returns_since_rotation": {},
            "verdict": None,
            "closed_at": None,
        }
    )
    store["swap_rotations"] = rotations
    return 1


def update_swap_rotations(
    store: dict[str, Any],
    *,
    prices_by_ticker: dict[str, float],
    as_of: str,
    cfg: ExitTimingCohortConfig | None = None,
) -> int:
    """Mark open swap rotations and score post-rotation relative performance."""
    cfg = cfg or ExitTimingCohortConfig()
    when = str(as_of)
    max_window = max(cfg.shadow_windows_days) if cfg.shadow_windows_days else 84
    updated = 0
    rotations: list[dict[str, Any]] = list(store.get("swap_rotations") or [])

    for rotation in rotations:
        if str(rotation.get("status") or "open") != "open":
            continue
        logged_at = str(rotation.get("logged_at") or "")
        days_elapsed = _days_between(logged_at, when)
        sell_returns: dict[str, float] = dict(rotation.get("sell_returns_since_rotation") or {})
        buy_returns: dict[str, float] = dict(rotation.get("buy_returns_since_rotation") or {})

        for leg in rotation.get("sells") or []:
            ticker = str(leg.get("ticker") or "")
            entry = float(leg.get("price") or 0)
            mark = prices_by_ticker.get(ticker)
            if ticker and entry > 0 and mark is not None and mark > 0:
                sell_returns[ticker] = round((mark - entry) / entry, 4)

        for leg in rotation.get("buys") or []:
            ticker = str(leg.get("ticker") or "")
            entry = float(leg.get("price") or 0)
            mark = prices_by_ticker.get(ticker)
            if ticker and entry > 0 and mark is not None and mark > 0:
                buy_returns[ticker] = round((mark - entry) / entry, 4)

        rotation["sell_returns_since_rotation"] = sell_returns
        rotation["buy_returns_since_rotation"] = buy_returns

        scored_days = {int(cp.get("days_after") or 0) for cp in rotation.get("checkpoints") or []}
        for window in cfg.shadow_windows_days:
            if days_elapsed < window or window in scored_days:
                continue
            avg_sell = sum(sell_returns.values()) / len(sell_returns) if sell_returns else None
            avg_buy = sum(buy_returns.values()) / len(buy_returns) if buy_returns else None
            rotation.setdefault("checkpoints", []).append(
                {
                    "scored_at": when,
                    "days_after": window,
                    "avg_sell_return": round(avg_sell, 4) if avg_sell is not None else None,
                    "avg_buy_return": round(avg_buy, 4) if avg_buy is not None else None,
                    "replacement_delta": round(avg_buy - avg_sell, 4)
                    if avg_sell is not None and avg_buy is not None
                    else None,
                }
            )
            updated += 1

        if days_elapsed >= max_window:
            rotation["status"] = "closed"
            rotation["closed_at"] = when
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

    store["swap_rotations"] = rotations
    return updated


def build_exit_timing_review(store: dict[str, Any], *, track_id: str) -> dict[str, Any]:
    hold_episodes = list(store.get("hold_episodes") or [])
    swap_rotations = list(store.get("swap_rotations") or [])
    open_hold = [row for row in hold_episodes if str(row.get("status") or "open") == "open"]
    closed_hold = [row for row in hold_episodes if str(row.get("status") or "open") != "open"]
    open_swap = [row for row in swap_rotations if str(row.get("status") or "open") == "open"]
    closed_swap = [row for row in swap_rotations if str(row.get("status") or "open") != "open"]

    def _hold_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"count": 0}
        recovered = sum(1 for row in rows if row.get("recovered_to_breakeven"))
        by_reason: dict[str, int] = {}
        for row in rows:
            reason = str(row.get("close_reason") or "open")
            by_reason[reason] = by_reason.get(reason, 0) + 1
        return {
            "count": len(rows),
            "recovered_to_breakeven": recovered,
            "close_reasons": by_reason,
        }

    def _swap_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"count": 0}
        verdicts: dict[str, int] = {}
        for row in rows:
            verdict = str(row.get("verdict") or "open")
            verdicts[verdict] = verdicts.get(verdict, 0) + 1
        return {"count": len(rows), "verdicts": verdicts}

    readiness = assess_framework_readiness(store)
    return {
        "schema_version": 1,
        "track_id": track_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "framework": framework_metadata(),
        "readiness": readiness,
        "hold_recovery": {
            "open": _hold_summary(open_hold),
            "closed": _hold_summary(closed_hold),
        },
        "swap_rotation": {
            "open": _swap_summary(open_swap),
            "closed": _swap_summary(closed_swap),
        },
        "note": readiness.get("note"),
    }


def assess_framework_readiness(store: dict[str, Any]) -> dict[str, Any]:
    hold_closed = [
        row
        for row in (store.get("hold_episodes") or [])
        if str(row.get("status") or "open") != "open"
    ]
    swap_closed = [
        row
        for row in (store.get("swap_rotations") or [])
        if str(row.get("status") or "open") != "open"
    ]
    hold_with_dq = [
        row
        for row in (store.get("hold_episodes") or [])
        if row.get("data_quality_score") is not None
    ]
    gaps: list[str] = []
    if len(hold_closed) < 15:
        gaps.append(f"hold_recovery closed episodes={len(hold_closed)} (target >=15)")
    if len(swap_closed) < 10:
        gaps.append(f"swap_rotation closed rotations={len(swap_closed)} (target >=10)")
    if not hold_with_dq:
        gaps.append("no hold episodes with data_quality_score yet (needs screen marks on pass)")

    ready_for_probability = len(hold_closed) >= 15 and len(swap_closed) >= 10
    note = (
        "Framework collecting — probability estimates deferred until closed cohort targets met."
        if gaps
        else "Closed cohorts reached initial targets; probability strand analysis can begin."
    )
    return {
        "ready_for_probability_analysis": ready_for_probability,
        "hold_closed_count": len(hold_closed),
        "swap_closed_count": len(swap_closed),
        "hold_with_data_quality_count": len(hold_with_dq),
        "gaps": gaps,
        "note": note,
    }


def load_exit_timing_cohorts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_exit_timing_cohorts(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def run_exit_timing_cohort_pass(
    *,
    output_dir: Path,
    fund: PaperFund,
    track_id: str,
    candidates: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    prices_by_ticker: dict[str, float],
    trade_cost_pct: float,
    as_of: str | datetime | None = None,
    config: ExitTimingCohortConfig | None = None,
) -> dict[str, Any]:
    """Ingest/update observe-only exit-timing cohorts for one paper track."""
    cfg = config or ExitTimingCohortConfig()
    output_dir = Path(output_dir)
    cohorts_path = output_dir / COHORTS_FILENAME
    review_path = output_dir / REVIEW_FILENAME
    when = (
        as_of.isoformat()
        if isinstance(as_of, datetime)
        else str(as_of or datetime.now(UTC).isoformat())
    )

    store = load_exit_timing_cohorts(cohorts_path)
    store.setdefault("schema_version", 1)
    store["track_id"] = track_id
    store["framework"] = framework_metadata()
    store["updated_at"] = datetime.now(UTC).isoformat()

    hold_added = ingest_hold_episodes(
        fund,
        store,
        track_id=track_id,
        candidates=candidates,
        prices_by_ticker=prices_by_ticker,
        as_of=when,
        cfg=cfg,
    )
    hold_scored = update_hold_episodes(
        fund,
        store,
        prices_by_ticker=prices_by_ticker,
        as_of=when,
        cfg=cfg,
    )
    swap_added = ingest_swap_rotations(
        store,
        track_id=track_id,
        trades=trades,
        as_of=when,
        trade_cost_pct=trade_cost_pct,
    )
    swap_scored = update_swap_rotations(
        store,
        prices_by_ticker=prices_by_ticker,
        as_of=when,
        cfg=cfg,
    )

    review = build_exit_timing_review(store, track_id=track_id)
    review["ingested_this_pass"] = {
        "hold_episodes": hold_added,
        "swap_rotations": swap_added,
    }
    review["checkpoints_added_this_pass"] = {
        "hold_episodes": hold_scored,
        "swap_rotations": swap_scored,
    }

    save_exit_timing_cohorts(cohorts_path, store)
    review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    return review


def summarize_learning_tracks_exit_timing(base_dir: Path) -> dict[str, Any]:
    from value_investor.paper_automation import learning_track_dirs

    base_dir = Path(base_dir)
    tracks: dict[str, Any] = {}
    for track_id, track_dir in learning_track_dirs(base_dir).items():
        review_path = track_dir / REVIEW_FILENAME
        if review_path.exists():
            tracks[track_id] = json.loads(review_path.read_text(encoding="utf-8"))

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "framework": framework_metadata(),
        "tracks": tracks,
        "note": (
            "Observe-only hold-recovery and swap-rotation cohorts. "
            "Pair with exit_shadow and rebalance_log counterfactuals for exit-timing research."
        ),
    }
