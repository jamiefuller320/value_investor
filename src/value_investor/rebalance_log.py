"""Append-only per-rebalance decision log for paper automation tracks."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.paper_fund import (
    BUY_SIGNALS,
    PaperFund,
    PaperFundConfig,
    Position,
    RebalanceState,
    run_automated_rebalance,
    run_technical_pass,
)
from value_investor.portfolio_diversity import DEFAULT_TARGET_SECTOR_CAP

REBALANCE_LOG_FILENAME = "rebalance_log.json"
BUFFERED_HOLD_COUNTERFACTUAL_FILENAME = "buffered_hold_counterfactual.json"
LOG_SCHEMA_VERSION = 2
LOG_KEEP = 104  # ~2 years of weekday passes
MIN_LOG_ACTED_ENTRIES = 2

_VERDICT_PREVIEW_CHARS = 120


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _truncate_verdict(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= _VERDICT_PREVIEW_CHARS:
        return text
    return text[: _VERDICT_PREVIEW_CHARS - 3] + "..."


def slim_candidate(row: dict[str, Any]) -> dict[str, Any]:
    """Decision-time candidate fields needed for faithful selection replay."""
    trade_plan = row.get("trade_plan") or {}
    slim: dict[str, Any] = {
        "ticker": row.get("ticker"),
        "name": row.get("name"),
        "signal": row.get("signal"),
        "adjusted_signal": row.get("adjusted_signal"),
        "conviction_score": row.get("conviction_score"),
        "data_quality_score": row.get("data_quality_score"),
        "timing_signal": row.get("timing_signal"),
        "sector": row.get("sector"),
        "price": row.get("price") if row.get("price") is not None else row.get("last"),
        "research_verdict": _truncate_verdict(row.get("research_verdict")),
    }
    if trade_plan:
        plan_subset = {
            key: trade_plan.get(key)
            for key in (
                "tactical_stop_loss",
                "tactical_take_profit",
                "core_stop_loss",
                "core_take_profit",
            )
            if trade_plan.get(key) is not None
        }
        if plan_subset:
            slim["trade_plan"] = plan_subset
    return {key: value for key, value in slim.items() if value is not None}


def collect_screen_buy_tier(
    marked_rows: list[dict[str, Any]],
    fund: PaperFund,
) -> list[dict[str, Any]]:
    """Raw screen buy-tier plus held names (before AI overlay gates)."""
    included: dict[str, dict[str, Any]] = {}
    for row in marked_rows:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        signal = str(row.get("signal") or "")
        if signal in BUY_SIGNALS or ticker in fund.holdings:
            included[ticker] = slim_candidate(row)
    return list(included.values())


def collect_decision_candidates(
    marked_rows: list[dict[str, Any]],
    fund: PaperFund,
    *,
    use_adjusted_signal: bool,
) -> list[dict[str, Any]]:
    """Effective buy-tier universe plus held names (after AI overlay gates)."""
    included: dict[str, dict[str, Any]] = {}
    for row in marked_rows:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        signal = str(row.get("signal") or "")
        effective = signal
        if use_adjusted_signal:
            adjusted = row.get("adjusted_signal")
            if adjusted is not None and str(adjusted).strip():
                effective = str(adjusted)
        if effective in BUY_SIGNALS or ticker in fund.holdings:
            included[ticker] = slim_candidate(row)
    return list(included.values())


def gate_excluded_tickers(
    screen_buy_tier: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[str]:
    """Tickers in raw screen buy-tier but excluded by effective decision gates."""
    candidate_tickers = {
        str(row.get("ticker") or "").strip()
        for row in candidates
        if str(row.get("ticker") or "").strip()
    }
    excluded: list[str] = []
    for row in screen_buy_tier:
        ticker = str(row.get("ticker") or "").strip()
        if ticker and ticker not in candidate_tickers:
            excluded.append(ticker)
    return sorted(excluded)


def snapshot_holdings(fund: PaperFund) -> list[dict[str, Any]]:
    return [
        {
            "ticker": ticker,
            "shares": round(float(pos.shares), 6),
            "avg_cost": round(float(pos.avg_cost), 4),
            "sector": pos.sector,
            "name": pos.name,
            "momentum_grace": bool(pos.momentum_grace),
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
        }
        for ticker, pos in fund.holdings.items()
    ]


def resolve_screen_source(reports_path: Path | None) -> dict[str, Any]:
    path = Path(reports_path) if reports_path is not None else Path("docs/data/latest.json")
    if not path.exists():
        return {"path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"path": str(path)}
    if isinstance(payload, dict):
        return {
            "path": str(path),
            "run_at": payload.get("run_at"),
            "generated_at": payload.get("generated_at"),
        }
    return {"path": str(path)}


def load_knob_epoch_started_at(output_dir: Path) -> str | None:
    epoch_path = Path(output_dir) / "knob_epoch.json"
    if not epoch_path.exists():
        return None
    try:
        payload = json.loads(epoch_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(payload, dict):
        started = str(payload.get("started_at") or "").strip()
        return started or None
    return None


def build_rebalance_log_entry(
    *,
    track_id: str,
    track_label: str,
    strategy_mode: str,
    gate: dict[str, Any],
    acted: bool,
    note: str,
    selection: dict[str, Any],
    max_positions: int,
    trade_cost_pct: float,
    screen_source: dict[str, Any],
    knob_epoch_started_at: str | None,
    candidates: list[dict[str, Any]],
    screen_buy_tier: list[dict[str, Any]] | None = None,
    gate_excluded: list[str] | None = None,
    plan: dict[str, Any],
    trades: list[dict[str, Any]],
    nav_before: float,
    cash_before: float,
    contributed_capital_before: float,
    holdings_before: list[dict[str, Any]],
    rebalance_state_before: dict[str, Any],
    nav_after: float,
    cash_after: float,
    holdings_after: list[dict[str, Any]],
    rebalance_state_after: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": LOG_SCHEMA_VERSION,
        "logged_at": _utcnow_iso(),
        "track_id": track_id,
        "track_label": track_label,
        "strategy_mode": strategy_mode,
        "screen_source": screen_source,
        "knob_epoch_started_at": knob_epoch_started_at,
        "gate": gate,
        "acted": bool(acted),
        "note": note,
        "selection": dict(selection),
        "max_positions": int(max_positions),
        "trade_cost_pct": round(float(trade_cost_pct), 4),
        "candidates": candidates,
        "screen_buy_tier": screen_buy_tier if screen_buy_tier is not None else [],
        "gate_excluded": gate_excluded if gate_excluded is not None else [],
        "plan": plan,
        "trades": trades,
        "nav_before": round(float(nav_before), 2),
        "cash_before": round(float(cash_before), 2),
        "contributed_capital_before": round(float(contributed_capital_before), 2),
        "holdings_before": holdings_before,
        "rebalance_state_before": rebalance_state_before,
        "nav_after": round(float(nav_after), 2),
        "cash_after": round(float(cash_after), 2),
        "holdings_after": holdings_after,
        "rebalance_state_after": rebalance_state_after,
    }


def load_rebalance_log(output_dir: Path) -> list[dict[str, Any]]:
    path = Path(output_dir) / REBALANCE_LOG_FILENAME
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def append_rebalance_log(output_dir: Path, entry: dict[str, Any]) -> None:
    path = Path(output_dir) / REBALANCE_LOG_FILENAME
    history = load_rebalance_log(output_dir)
    history.append(entry)
    history = history[-LOG_KEEP:]
    path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")


def _entry_sort_key(entry: dict[str, Any]) -> str:
    gate = entry.get("gate") or {}
    return str(gate.get("local_time") or entry.get("logged_at") or "")


def acted_log_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [entry for entry in entries if entry.get("acted")],
        key=_entry_sort_key,
    )


_TRACK_SUBDIRS: dict[str, str] = {
    "rules": "",
    "ai_judgment": "ai_judgment",
    "momentum_grace": "momentum_grace",
    "technical": "technical",
}


def resolve_track_dir(paper_root: Path, track_id: str) -> Path:
    """Map learning track id to its rebalance_log directory under paper_root."""
    sub = _TRACK_SUBDIRS.get(str(track_id or "").strip(), str(track_id or "").strip())
    root = Path(paper_root)
    return root if not sub else root / sub


def load_learning_track_logs(
    paper_root: Path,
    track_ids: tuple[str, ...] = ("rules", "ai_judgment"),
) -> list[dict[str, Any]]:
    """Load rebalance_log entries from one or more paper automation tracks."""
    combined: list[dict[str, Any]] = []
    for track_id in track_ids:
        track_dir = resolve_track_dir(paper_root, track_id)
        for entry in load_rebalance_log(track_dir):
            if not str(entry.get("track_id") or "").strip():
                entry = {**entry, "track_id": track_id}
            combined.append(entry)
    return combined


def _effective_signal_from_row(row: dict[str, Any]) -> str:
    adjusted = str(row.get("adjusted_signal") or "").strip()
    if adjusted:
        return adjusted
    return str(row.get("signal") or "").strip()


def _candidate_by_ticker(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    # Decision-time candidates override raw screen rows (adjusted_signal / AI gates).
    for pool in (entry.get("screen_buy_tier") or [], entry.get("candidates") or []):
        for row in pool:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").strip()
            if ticker:
                mapped[ticker] = row
    return mapped


def collect_buy_tier_history_tickers(entries: list[dict[str, Any]]) -> frozenset[str]:
    """Tickers that ever appeared in buy-tier screen rows or were bought on an acted pass."""
    history: set[str] = set()
    for entry in acted_log_entries(entries):
        for row in entry.get("screen_buy_tier") or []:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").strip()
            signal = str(row.get("signal") or "")
            if ticker and signal in BUY_SIGNALS:
                history.add(ticker)
        for row in entry.get("candidates") or []:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").strip()
            if ticker and _effective_signal_from_row(row) in BUY_SIGNALS:
                history.add(ticker)
        for trade in entry.get("trades") or []:
            if not isinstance(trade, dict):
                continue
            if str(trade.get("side") or "") == "buy":
                ticker = str(trade.get("ticker") or "").strip()
                if ticker:
                    history.add(ticker)
    return frozenset(history)


def extract_held_stress_episode_seeds(
    entries: list[dict[str, Any]],
    *,
    buy_tier_history: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Held positions with effective signal below buy-tier on an acted pass.

    Requires buy-tier history (prior buy screen or buy trade) so archive replay
    covers names that entered the book, not only below-buy-tier near-miss gates.
    """
    history = (
        buy_tier_history
        if buy_tier_history is not None
        else collect_buy_tier_history_tickers(entries)
    )
    seeds: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for entry in acted_log_entries(entries):
        track_id = str(entry.get("track_id") or "rules")
        when = _entry_sort_key(entry)
        cmap = _candidate_by_ticker(entry)
        exit_streak = dict((entry.get("rebalance_state_before") or {}).get("exit_streak") or {})

        for holding in entry.get("holdings_before") or []:
            if not isinstance(holding, dict):
                continue
            ticker = str(holding.get("ticker") or "").strip()
            if not ticker or ticker not in history:
                continue
            candidate = cmap.get(ticker) or {}
            signal = _effective_signal_from_row(candidate)
            if signal in BUY_SIGNALS:
                continue

            key = (track_id, ticker, when)
            if key in seen:
                continue
            seen.add(key)

            avg_cost = float(holding.get("avg_cost") or 0)
            mark = float(candidate.get("price") or avg_cost or 0)
            unrealized = (mark - avg_cost) / avg_cost if avg_cost > 0 and mark > 0 else 0.0
            triggers: list[str] = ["signal_downgrade"]
            if int(exit_streak.get(ticker, 0)) >= 1:
                triggers.append("exit_streak")
            if bool(holding.get("momentum_grace", False)):
                triggers.append("momentum_grace")

            seeds.append(
                {
                    "track_id": track_id,
                    "ticker": ticker,
                    "name": str(holding.get("name") or candidate.get("name") or ""),
                    "started_at": when,
                    "avg_cost": avg_cost,
                    "mark_price": mark,
                    "unrealized_pct_at_start": round(unrealized, 4),
                    "screen_signal": str(candidate.get("signal") or ""),
                    "effective_signal": signal,
                    "data_quality_score": candidate.get("data_quality_score"),
                    "conviction_score": candidate.get("conviction_score"),
                    "exit_streak_at_start": int(exit_streak.get(ticker, 0)),
                    "momentum_grace": bool(holding.get("momentum_grace", False)),
                    "stress_triggers": triggers,
                }
            )
    return seeds


def extract_log_swap_rotation_seeds(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same-pass sell+buy rotations from acted log entries (trim sells excluded)."""
    seeds: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in acted_log_entries(entries):
        when = _entry_sort_key(entry)
        track_id = str(entry.get("track_id") or "rules")
        trades = [t for t in (entry.get("trades") or []) if isinstance(t, dict)]
        sells = [
            t
            for t in trades
            if str(t.get("side") or "") == "sell" and "trim" not in str(t.get("note") or "").lower()
        ]
        buys = [t for t in trades if str(t.get("side") or "") == "buy"]
        if not sells or not buys:
            continue

        rotation_id = f"{track_id}:{when}"
        if rotation_id in seen:
            continue
        seen.add(rotation_id)
        seeds.append(
            {
                "rotation_id": rotation_id,
                "track_id": track_id,
                "logged_at": when,
                "trade_cost_pct": float(entry.get("trade_cost_pct") or 0),
                "sells": sells,
                "buys": buys,
            }
        )
    return seeds


def filter_acted_log_entries_since(
    entries: list[dict[str, Any]],
    *,
    lookback_days: int,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return acted log entries whose pass timestamp falls within the lookback window."""
    when = as_of or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    since = when - timedelta(days=int(lookback_days))
    filtered: list[dict[str, Any]] = []
    for entry in acted_log_entries(entries):
        when_text = _entry_sort_key(entry)
        entry_dt = _parse_iso_datetime(when_text)
        if entry_dt is None:
            continue
        entry_utc = entry_dt.astimezone(UTC) if entry_dt.tzinfo else entry_dt.replace(tzinfo=UTC)
        if since <= entry_utc <= when:
            filtered.append(entry)
    return filtered


def filter_acted_log_entries_from_sim_start(
    entries: list[dict[str, Any]],
    *,
    sim_start: str | datetime | None = None,
) -> list[dict[str, Any]]:
    """Return acted log entries on/after ``sim_start`` (inclusive)."""
    acted = acted_log_entries(entries)
    if sim_start is None:
        return acted
    if isinstance(sim_start, datetime):
        start_dt = sim_start
    else:
        start_dt = _parse_iso_datetime(str(sim_start))
    if start_dt is None:
        return acted
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=UTC)
    start_utc = start_dt.astimezone(UTC)
    filtered: list[dict[str, Any]] = []
    for entry in acted:
        when_text = _entry_sort_key(entry)
        entry_dt = _parse_iso_datetime(when_text)
        if entry_dt is None:
            continue
        entry_utc = entry_dt.astimezone(UTC) if entry_dt.tzinfo else entry_dt.replace(tzinfo=UTC)
        if entry_utc >= start_utc:
            filtered.append(entry)
    return filtered


def build_replay_fund_from_log(
    entries: list[dict[str, Any]],
    *,
    max_positions: int,
    skip_timing_wait: bool = True,
    min_conviction: float = 0.0,
    sector_cap: float = DEFAULT_TARGET_SECTOR_CAP,
    use_adjusted_signal: bool | None = None,
    require_research_accumulate: bool | None = None,
    exit_confirm_screens: int | None = None,
    candidate_source: str = "auto",
    sim_start: str | datetime | None = None,
    lookback_days: int | None = None,
    as_of: datetime | None = None,
    fund_name: str | None = None,
) -> tuple[PaperFund, dict[str, Any]] | None:
    """
    Materialize a PaperFund by replaying logged rebalance passes with alternate knobs.

    Uses only each pass's logged candidates / screen_buy_tier (PIT at entry).
    Does not fetch live prices. Returns None when no acted entries remain after filters.
    """
    if lookback_days is not None:
        acted = filter_acted_log_entries_since(
            entries,
            lookback_days=int(lookback_days),
            as_of=as_of,
        )
    else:
        acted = filter_acted_log_entries_from_sim_start(entries, sim_start=sim_start)
    if not acted:
        return None

    first = acted[0]
    last = acted[-1]
    fund = fund_from_pre_state(first)
    if fund_name:
        fund.config.name = str(fund_name)
    fund.config.max_positions = int(max_positions)
    fund.config.trade_cost_pct = float(first.get("trade_cost_pct") or fund.config.trade_cost_pct)

    replay_trades = 0
    used_screen_pool = False
    for entry in acted:
        mode = str(entry.get("strategy_mode") or fund.config.mode)
        screen_pool = list(entry.get("screen_buy_tier") or [])
        candidates = resolve_replay_candidates(
            entry,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
            candidate_source=candidate_source,
        )
        if screen_pool:
            screen_tickers = {
                str(row.get("ticker") or "").strip()
                for row in screen_pool
                if str(row.get("ticker") or "").strip()
            }
            replay_tickers = {
                str(row.get("ticker") or "").strip()
                for row in candidates
                if str(row.get("ticker") or "").strip()
            }
            if screen_tickers and replay_tickers == screen_tickers:
                used_screen_pool = True
        when = str((entry.get("gate") or {}).get("local_time") or entry.get("logged_at") or "")
        kwargs = _selection_kwargs_for_replay(
            entry,
            max_positions=max_positions,
            skip_timing_wait=skip_timing_wait,
            min_conviction=min_conviction,
            sector_cap=sector_cap,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
            exit_confirm_screens=exit_confirm_screens,
        )
        fund.config.max_positions = int(kwargs.pop("max_positions"))
        if mode == "technical":
            executed = run_technical_pass(fund, candidates, acted_at=when or None)
        else:
            executed = run_automated_rebalance(fund, candidates, acted_at=when or None, **kwargs)
        replay_trades += len(executed)

    prices = _merge_candidate_price_maps(
        list(last.get("candidates") or []),
        list(last.get("screen_buy_tier") or []),
    )
    for row in last.get("holdings_after") or []:
        if isinstance(row, dict):
            ticker = str(row.get("ticker") or "")
            avg = row.get("avg_cost")
            if ticker and ticker not in prices and avg is not None and float(avg) > 0:
                prices[ticker] = float(avg)
    # Ensure a terminal equity mark at seed end for zero-datum baseline.
    seed_end = _entry_sort_key(last)
    last_mark_at = str((fund.equity_curve[-1] or {}).get("at") or "") if fund.equity_curve else ""
    if not fund.equity_curve or seed_end > last_mark_at:
        fund.record_mark(prices, acted_at=seed_end or None, note="Warm-start seed end")

    sim_perf = fund.performance(prices)
    stats = {
        "scope": "rebalance_log_materialize",
        "log_entries_replayed": len(acted),
        "replay_from": _entry_sort_key(first),
        "replay_to": _entry_sort_key(last),
        "simulated_nav": round(float(sim_perf["portfolio_value"] or 0.0), 2),
        "simulated_trade_count": replay_trades,
        "positions": int(sim_perf.get("positions") or 0),
        "used_screen_buy_tier_pool": used_screen_pool,
        "equity_marks": len(fund.equity_curve or []),
        "trade_count": len(fund.trades or []),
        "sim_start_applied": (
            None
            if sim_start is None
            else (sim_start.isoformat() if isinstance(sim_start, datetime) else str(sim_start))
        ),
    }
    return fund, stats


def _count_full_exits_in_entries(entries: list[dict[str, Any]]) -> int:
    count = 0
    for entry in entries:
        for trade in entry.get("trades") or []:
            if not isinstance(trade, dict):
                continue
            if trade.get("side") != "sell":
                continue
            if "trim" in str(trade.get("note") or "").lower():
                continue
            count += 1
    return count


def _buffered_hold_context(entries: list[dict[str, Any]]) -> dict[str, Any]:
    last = entries[-1] if entries else {}
    state = (last.get("rebalance_state_after") or {}) if isinstance(last, dict) else {}
    exit_streak = dict(state.get("exit_streak") or {})
    return {
        "exit_streak": exit_streak,
        "buffered_holdings": len(exit_streak),
        "full_exits_in_window": _count_full_exits_in_entries(entries),
        "log_entries_in_window": len(entries),
    }


def _price_map_from_candidates(candidates: list[dict[str, Any]]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for row in candidates:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        price = row.get("price")
        if price is not None and float(price) > 0:
            prices[ticker] = float(price)
    return prices


def fund_from_pre_state(entry: dict[str, Any]) -> PaperFund:
    mode = str(entry.get("strategy_mode") or "automated")
    if mode not in {"automated", "technical"}:
        mode = "automated"
    config = PaperFundConfig(
        name=str(entry.get("track_label") or "Replay"),
        mode=mode,  # type: ignore[arg-type]
        initial_cash=float(entry.get("contributed_capital_before") or 1000.0),
        trade_cost_pct=float(entry.get("trade_cost_pct") or 0.03),
        max_positions=int(entry.get("max_positions") or 5),
    )
    fund = PaperFund(
        config=config,
        cash=float(entry.get("cash_before") or config.initial_cash),
        contributed_capital=float(entry.get("contributed_capital_before") or config.initial_cash),
    )
    for row in entry.get("holdings_before") or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        fund.holdings[ticker] = Position(
            ticker=ticker,
            shares=float(row.get("shares") or 0),
            avg_cost=float(row.get("avg_cost") or 0),
            name=str(row.get("name") or ticker),
            sector=str(row.get("sector") or ""),
            stop_loss=row.get("stop_loss"),
            take_profit=row.get("take_profit"),
            momentum_grace=bool(row.get("momentum_grace", False)),
        )
    fund.rebalance_state = RebalanceState.from_dict(entry.get("rebalance_state_before"))
    return fund


def _selection_kwargs_for_replay(
    entry: dict[str, Any],
    *,
    max_positions: int,
    skip_timing_wait: bool,
    min_conviction: float,
    sector_cap: float,
    use_adjusted_signal: bool | None = None,
    require_research_accumulate: bool | None = None,
    exit_confirm_screens: int | None = None,
) -> dict[str, Any]:
    selection = dict(entry.get("selection") or {})
    logged_use_adj = bool(selection.get("use_adjusted_signal", False))
    logged_req_acc = bool(selection.get("require_research_accumulate", False))
    logged_exit_confirm = int(selection.get("exit_confirm_screens") or 2)
    return {
        "skip_timing_wait": bool(skip_timing_wait),
        "min_conviction": float(min_conviction),
        "sector_cap": float(sector_cap),
        "use_adjusted_signal": (
            logged_use_adj if use_adjusted_signal is None else bool(use_adjusted_signal)
        ),
        "require_research_accumulate": (
            logged_req_acc
            if require_research_accumulate is None
            else bool(require_research_accumulate)
        ),
        "use_momentum_grace": bool(selection.get("use_momentum_grace", False)),
        "exit_confirm_screens": (
            logged_exit_confirm if exit_confirm_screens is None else int(exit_confirm_screens)
        ),
        "reentry_cooldown_screens": int(selection.get("reentry_cooldown_screens") or 1),
        "min_rebalance_notional_gbp": float(selection.get("min_rebalance_notional_gbp") or 10.0),
        "max_positions": int(max_positions),
    }


def resolve_replay_candidates(
    entry: dict[str, Any],
    *,
    use_adjusted_signal: bool | None = None,
    require_research_accumulate: bool | None = None,
    candidate_source: str = "auto",
) -> list[dict[str, Any]]:
    """
    Choose candidate pool for log replay.

    ``auto`` uses ``screen_buy_tier`` when AI overlay gates differ from the
    logged pass and raw screen snapshots exist; otherwise ``candidates``.
    """
    selection = dict(entry.get("selection") or {})
    logged_use_adj = bool(selection.get("use_adjusted_signal", False))
    logged_req_acc = bool(selection.get("require_research_accumulate", False))
    screen = list(entry.get("screen_buy_tier") or [])
    candidates = list(entry.get("candidates") or [])

    source = str(candidate_source or "auto").strip().lower()
    if source == "screen_buy_tier":
        return screen or candidates
    if source == "candidates":
        return candidates

    ai_gate_changed = (
        use_adjusted_signal is not None and bool(use_adjusted_signal) != logged_use_adj
    ) or (
        require_research_accumulate is not None
        and bool(require_research_accumulate) != logged_req_acc
    )
    if ai_gate_changed and screen:
        return screen
    return candidates


def _merge_candidate_price_maps(*pools: list[dict[str, Any]]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for pool in pools:
        prices.update(_price_map_from_candidates(pool))
    return prices


def replay_counterfactual_from_log(
    entries: list[dict[str, Any]],
    *,
    max_positions: int,
    skip_timing_wait: bool = True,
    min_conviction: float = 0.0,
    sector_cap: float = DEFAULT_TARGET_SECTOR_CAP,
    use_adjusted_signal: bool | None = None,
    require_research_accumulate: bool | None = None,
    exit_confirm_screens: int | None = None,
    candidate_source: str = "auto",
    lookback_days: int | None = None,
    as_of: datetime | None = None,
    actual_fund: PaperFund | None = None,
) -> dict[str, Any] | None:
    """
    Replay logged rebalance passes with alternate knobs on a shadow fund.

    When ``screen_buy_tier`` is present, AI-gate counterfactuals can widen the
    replay pool to raw screen buy-tier names (or force via ``candidate_source``).

    Pass ``lookback_days`` to replay only passes within that window (observe-only
    churn probe). ``exit_confirm_screens`` overrides the logged hold-buffer knob.

    Returns None when there are no acted log entries to replay.
    """
    acted = acted_log_entries(entries)
    if lookback_days is not None:
        acted = filter_acted_log_entries_since(
            entries,
            lookback_days=int(lookback_days),
            as_of=as_of,
        )
    if not acted:
        return None

    first = acted[0]
    last = acted[-1]
    fund = fund_from_pre_state(first)
    fund.config.max_positions = int(max_positions)
    fund.config.trade_cost_pct = float(first.get("trade_cost_pct") or fund.config.trade_cost_pct)

    replay_trades = 0
    used_screen_pool = False
    for entry in acted:
        mode = str(entry.get("strategy_mode") or fund.config.mode)
        screen_pool = list(entry.get("screen_buy_tier") or [])
        candidates = resolve_replay_candidates(
            entry,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
            candidate_source=candidate_source,
        )
        if screen_pool:
            screen_tickers = {
                str(row.get("ticker") or "").strip()
                for row in screen_pool
                if str(row.get("ticker") or "").strip()
            }
            replay_tickers = {
                str(row.get("ticker") or "").strip()
                for row in candidates
                if str(row.get("ticker") or "").strip()
            }
            if screen_tickers and replay_tickers == screen_tickers:
                used_screen_pool = True
        when = str((entry.get("gate") or {}).get("local_time") or entry.get("logged_at") or "")
        kwargs = _selection_kwargs_for_replay(
            entry,
            max_positions=max_positions,
            skip_timing_wait=skip_timing_wait,
            min_conviction=min_conviction,
            sector_cap=sector_cap,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
            exit_confirm_screens=exit_confirm_screens,
        )
        fund.config.max_positions = int(kwargs.pop("max_positions"))
        if mode == "technical":
            executed = run_technical_pass(fund, candidates, acted_at=when or None)
        else:
            executed = run_automated_rebalance(fund, candidates, acted_at=when or None, **kwargs)
        replay_trades += len(executed)

    prices = _merge_candidate_price_maps(
        list(last.get("candidates") or []),
        list(last.get("screen_buy_tier") or []),
    )
    for row in last.get("holdings_after") or []:
        if isinstance(row, dict):
            ticker = str(row.get("ticker") or "")
            avg = row.get("avg_cost")
            if ticker and ticker not in prices and avg is not None and float(avg) > 0:
                prices[ticker] = float(avg)
    sim_perf = fund.performance(prices)
    sim_costs = sum(float(t.cost or 0.0) for t in fund.trades)
    baseline_nav = float(first.get("nav_before") or 0.0)
    sim_nav = float(sim_perf["portfolio_value"] or 0.0)
    sim_return = ((sim_nav - baseline_nav) / baseline_nav) if baseline_nav > 0 else 0.0
    contributed = float(first.get("contributed_capital_before") or baseline_nav or 1.0)
    sim_drag = (sim_costs / contributed) if contributed > 0 else 0.0

    selection = dict(first.get("selection") or {})
    effective_use_adj = (
        bool(selection.get("use_adjusted_signal", False))
        if use_adjusted_signal is None
        else bool(use_adjusted_signal)
    )
    effective_req_acc = (
        bool(selection.get("require_research_accumulate", False))
        if require_research_accumulate is None
        else bool(require_research_accumulate)
    )
    effective_exit_confirm = (
        int(selection.get("exit_confirm_screens") or 2)
        if exit_confirm_screens is None
        else int(exit_confirm_screens)
    )
    payload: dict[str, Any] = {
        "scope": "rebalance_log_replay",
        "knobs": {
            "max_positions": int(max_positions),
            "skip_timing_wait": bool(skip_timing_wait),
            "min_conviction": round(float(min_conviction), 4),
            "sector_cap": round(float(sector_cap), 4),
            "use_adjusted_signal": effective_use_adj,
            "require_research_accumulate": effective_req_acc,
            "exit_confirm_screens": effective_exit_confirm,
            "candidate_source": str(candidate_source or "auto"),
        },
        "used_screen_buy_tier_pool": used_screen_pool,
        "log_entries_total": len(entries),
        "log_entries_replayed": len(acted),
        "lookback_days": int(lookback_days) if lookback_days is not None else None,
        "replay_from": _entry_sort_key(first),
        "replay_to": _entry_sort_key(last),
        "simulated_nav": round(sim_nav, 2),
        "baseline_nav": round(baseline_nav, 2),
        "simulated_return": round(sim_return, 4),
        "simulated_total_costs": round(sim_costs, 2),
        "simulated_cost_drag": round(sim_drag, 4),
        "simulated_trade_count": replay_trades,
        "limitations": (
            "Replay covers logged rebalance passes only; pre-logging history "
            "needs archive lab (L111). Names never in screen_buy_tier (hold/avoid "
            "on raw screen) still need full archive replay. Technical track replays "
            "stops/targets from logged trade_plan snapshots."
        ),
    }

    if actual_fund is not None:
        actual_costs_window = 0.0
        start_dt = _entry_sort_key(first)
        end_dt = _entry_sort_key(last)
        for trade in actual_fund.trades:
            acted_at = str(trade.acted_at or "")
            if start_dt <= acted_at <= end_dt:
                actual_costs_window += float(trade.cost or 0.0)
        actual_perf = actual_fund.performance(prices)
        actual_nav = float(actual_perf["portfolio_value"] or 0.0)
        actual_return = ((actual_nav - baseline_nav) / baseline_nav) if baseline_nav > 0 else 0.0
        actual_drag = (actual_costs_window / contributed) if contributed > 0 else 0.0
        payload.update(
            {
                "actual_nav": round(actual_nav, 2),
                "actual_return_over_window": round(actual_return, 4),
                "actual_total_costs_over_window": round(actual_costs_window, 2),
                "actual_cost_drag_over_window": round(actual_drag, 4),
                "return_delta_vs_actual": round(sim_return - actual_return, 4),
                "cost_drag_delta_vs_actual": round(actual_drag - sim_drag, 4),
            }
        )

    return payload


def _filter_snapshots_from(
    snapshots: list[Any],
    start_when: str,
) -> list[Any]:
    start_dt = _parse_iso_datetime(start_when)
    if start_dt is None:
        return list(snapshots)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=UTC)
    start_day = start_dt.date()
    from value_investor.backtest import _parse_run_at

    filtered: list[Any] = []
    for snapshot in snapshots:
        snap_dt = _parse_run_at(str(getattr(snapshot, "run_at", "") or ""))
        if snap_dt.date() >= start_day:
            filtered.append(snapshot)
    return filtered


def _snapshot_to_marked_rows(snapshot: Any) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for row in snapshot.signals:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        item = dict(row)
        price = snapshot.prices.get(ticker)
        if price is not None and float(price) > 0:
            item["price"] = float(price)
            item["last"] = float(price)
        marked.append(item)
    return marked


def _resolve_archive_replay_passes(
    data_dir: Path,
    *,
    start_when: str,
    archive_dir: Path | None,
    fetch_prices: bool,
) -> list[tuple[str, list[dict[str, Any]]]]:
    """
    Prefer backfilled history/run_* snapshots (priced) and fall back to dashboard
    archives for weeks missing from history.
    """
    from value_investor.archive_history import list_dashboard_archives
    from value_investor.backtest import load_run_snapshots

    data_dir = Path(data_dir)
    history = _filter_snapshots_from(load_run_snapshots(data_dir), start_when)
    history_by_day: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    for snapshot in history:
        from value_investor.backtest import _parse_run_at

        day = _parse_run_at(snapshot.run_at).date().isoformat()
        history_by_day[day] = (snapshot.run_at, _snapshot_to_marked_rows(snapshot))

    archives = _filter_archives_from(
        list_dashboard_archives(Path(archive_dir or data_dir / "archive")),
        start_when,
    )
    passes: list[tuple[str, list[dict[str, Any]]]] = []
    seen_days: set[str] = set()
    for run_at, archive_path in archives:
        from value_investor.backtest import _parse_run_at

        day = _parse_run_at(run_at.isoformat()).date().isoformat()
        if day in seen_days:
            continue
        seen_days.add(day)
        if day in history_by_day:
            passes.append(history_by_day[day])
            continue
        marked = archive_to_marked_rows(
            archive_path,
            price_hints={},
            fetch_prices=fetch_prices,
        )
        if marked:
            passes.append((run_at.isoformat(), marked))
    return passes


def _filter_archives_from(
    archives: list[tuple[datetime, Path]],
    start_when: str,
) -> list[tuple[datetime, Path]]:
    start_dt = _parse_iso_datetime(start_when)
    if start_dt is None:
        return list(archives)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=UTC)
    start_day = start_dt.date()
    filtered: list[tuple[datetime, Path]] = []
    for run_at, path in archives:
        archive_dt = run_at if run_at.tzinfo is not None else run_at.replace(tzinfo=UTC)
        if archive_dt.date() >= start_day:
            filtered.append((run_at, path))
    return filtered


def _counterfactual_actual_window(
    actual_fund: PaperFund | None,
    *,
    start_when: str,
    end_when: str,
    baseline_nav: float,
    contributed: float,
    mark_prices: dict[str, float],
) -> dict[str, Any]:
    if actual_fund is None:
        return {}
    actual_costs_window = 0.0
    for trade in actual_fund.trades:
        acted_at = str(trade.acted_at or "")
        if start_when <= acted_at <= end_when:
            actual_costs_window += float(trade.cost or 0.0)
    actual_perf = actual_fund.performance(mark_prices)
    actual_nav = float(actual_perf["portfolio_value"] or 0.0)
    actual_return = ((actual_nav - baseline_nav) / baseline_nav) if baseline_nav > 0 else 0.0
    actual_drag = (actual_costs_window / contributed) if contributed > 0 else 0.0
    return {
        "actual_nav": round(actual_nav, 2),
        "actual_return_over_window": round(actual_return, 4),
        "actual_total_costs_over_window": round(actual_costs_window, 2),
        "actual_cost_drag_over_window": round(actual_drag, 4),
    }


def replay_counterfactual_from_archive(
    track_dir: Path,
    *,
    max_positions: int,
    skip_timing_wait: bool = True,
    min_conviction: float = 0.0,
    sector_cap: float = DEFAULT_TARGET_SECTOR_CAP,
    use_adjusted_signal: bool | None = None,
    require_research_accumulate: bool | None = None,
    archive_dir: Path | None = None,
    fetch_prices: bool = True,
    actual_fund: PaperFund | None = None,
) -> dict[str, Any] | None:
    """
    Walk archived weekly screens from the first acted rebalance log pass and
    re-run automated rebalance with alternate knobs on a shadow fund.

    Observe-only counterfactual — complements the shorter log-entry replay when
    pre-logging history or sparse weekday passes leave gaps in ``rebalance_log``.
    """
    from value_investor.paper_automation import CONFIG_FILENAME, AutomationConfig

    track_dir = Path(track_dir)
    entries = load_rebalance_log(track_dir)
    acted = acted_log_entries(entries)
    if not acted:
        return None

    first = acted[0]
    last = acted[-1]
    replay_from = _entry_sort_key(first)
    replay_to = _entry_sort_key(last)

    if (track_dir / CONFIG_FILENAME).exists():
        config = AutomationConfig.from_dict(
            json.loads((track_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
        )
    else:
        config = AutomationConfig()

    data_dir = Path(archive_dir).parent if archive_dir else Path("docs/data")
    replay_passes = _resolve_archive_replay_passes(
        data_dir,
        start_when=replay_from,
        archive_dir=archive_dir,
        fetch_prices=fetch_prices,
    )
    if not replay_passes:
        return None

    fund = fund_from_pre_state(first)
    fund.config.max_positions = int(max_positions)
    fund.config.trade_cost_pct = float(first.get("trade_cost_pct") or fund.config.trade_cost_pct)

    selection = dict(first.get("selection") or {})
    effective_use_adj = (
        bool(config.use_adjusted_signal)
        if use_adjusted_signal is None
        else bool(use_adjusted_signal)
    )
    effective_req_acc = (
        bool(config.require_research_accumulate)
        if require_research_accumulate is None
        else bool(require_research_accumulate)
    )

    price_hints: dict[str, float] = {}
    for row in first.get("holdings_before") or []:
        if isinstance(row, dict):
            ticker = str(row.get("ticker") or "")
            avg = row.get("avg_cost")
            if ticker and avg is not None and float(avg) > 0:
                price_hints[ticker] = float(avg)

    replay_trades = 0
    archive_passes: list[str] = []
    for when, marked in replay_passes:
        if not marked:
            continue
        for row in marked:
            ticker = str(row.get("ticker") or "")
            price = row.get("price")
            if ticker and price is not None and float(price) > 0:
                price_hints[ticker] = float(price)

        if effective_use_adj or effective_req_acc:
            from value_investor.research.overlay import enrich_marked_rows_with_research

            marked = enrich_marked_rows_with_research(marked, data_dir, as_of=when)

        candidates = collect_decision_candidates(
            marked,
            fund,
            use_adjusted_signal=effective_use_adj,
        )
        kwargs = {
            "skip_timing_wait": bool(skip_timing_wait),
            "min_conviction": float(min_conviction),
            "sector_cap": float(sector_cap),
            "use_adjusted_signal": effective_use_adj,
            "require_research_accumulate": effective_req_acc,
            "use_momentum_grace": bool(selection.get("use_momentum_grace", False)),
            "exit_confirm_screens": int(selection.get("exit_confirm_screens") or 2),
            "reentry_cooldown_screens": int(selection.get("reentry_cooldown_screens") or 1),
            "min_rebalance_notional_gbp": float(
                selection.get("min_rebalance_notional_gbp") or 10.0
            ),
        }
        mode = str(first.get("strategy_mode") or fund.config.mode)
        if mode == "technical":
            executed = run_technical_pass(fund, marked, acted_at=when)
        else:
            executed = run_automated_rebalance(fund, candidates, acted_at=when, **kwargs)
        replay_trades += len(executed)
        archive_passes.append(when)

    if not archive_passes:
        return None

    last_marked = replay_passes[-1][1]
    prices = _merge_candidate_price_maps(last_marked)
    for row in last.get("holdings_after") or []:
        if isinstance(row, dict):
            ticker = str(row.get("ticker") or "")
            avg = row.get("avg_cost")
            if ticker and ticker not in prices and avg is not None and float(avg) > 0:
                prices[ticker] = float(avg)
    for ticker, pos in fund.holdings.items():
        if ticker not in prices and pos.avg_cost > 0:
            prices[ticker] = float(pos.avg_cost)

    sim_perf = fund.performance(prices)
    sim_costs = sum(float(t.cost or 0.0) for t in fund.trades)
    baseline_nav = float(first.get("nav_before") or 0.0)
    sim_nav = float(sim_perf["portfolio_value"] or 0.0)
    sim_return = ((sim_nav - baseline_nav) / baseline_nav) if baseline_nav > 0 else 0.0
    contributed = float(first.get("contributed_capital_before") or baseline_nav or 1.0)
    sim_drag = (sim_costs / contributed) if contributed > 0 else 0.0

    payload: dict[str, Any] = {
        "scope": "archive_rebalance_replay",
        "knobs": {
            "max_positions": int(max_positions),
            "skip_timing_wait": bool(skip_timing_wait),
            "min_conviction": round(float(min_conviction), 4),
            "sector_cap": round(float(sector_cap), 4),
            "use_adjusted_signal": effective_use_adj,
            "require_research_accumulate": effective_req_acc,
        },
        "archive_passes_replayed": len(archive_passes),
        "archive_replay_from": archive_passes[0],
        "archive_replay_to": archive_passes[-1],
        "log_replay_from": replay_from,
        "log_replay_to": replay_to,
        "log_entries_replayed": len(acted),
        "simulated_nav": round(sim_nav, 2),
        "baseline_nav": round(baseline_nav, 2),
        "simulated_return": round(sim_return, 4),
        "simulated_total_costs": round(sim_costs, 2),
        "simulated_cost_drag": round(sim_drag, 4),
        "simulated_trade_count": replay_trades,
        "limitations": (
            "Observe-only archive walk — one rebalance per archived weekly screen "
            "from first logged pass. Does not mutate live knobs. AI overlay gates "
            "use PIT research joins (L113) when a research timeline exists under "
            "the archive parent data_dir."
        ),
    }

    actual_window = _counterfactual_actual_window(
        actual_fund,
        start_when=replay_from,
        end_when=replay_to,
        baseline_nav=baseline_nav,
        contributed=contributed,
        mark_prices=prices,
    )
    if actual_window:
        actual_return = float(actual_window["actual_return_over_window"])
        payload.update(actual_window)
        payload["return_delta_vs_actual"] = round(sim_return - actual_return, 4)
        payload["cost_drag_delta_vs_actual"] = round(
            float(actual_window["actual_cost_drag_over_window"]) - sim_drag,
            4,
        )

    return payload


def compare_buffered_hold_counterfactual(
    track_dir: Path,
    *,
    lookback_days: int = 7,
    exit_confirm_variants: tuple[int, ...] = (1, 2),
    as_of: datetime | None = None,
    max_positions: int | None = None,
    skip_timing_wait: bool | None = None,
    min_conviction: float | None = None,
    sector_cap: float | None = None,
    use_adjusted_signal: bool | None = None,
    require_research_accumulate: bool | None = None,
    actual_fund: PaperFund | None = None,
) -> dict[str, Any] | None:
    """
    Compare hold-buffer sensitivity by replaying recent log passes at alternate
    ``exit_confirm_screens`` values (observe-only — no live knob apply).
    """
    track_dir = Path(track_dir)
    entries = load_rebalance_log(track_dir)
    window_entries = filter_acted_log_entries_since(
        entries,
        lookback_days=int(lookback_days),
        as_of=as_of,
    )
    if not window_entries:
        return None

    first = window_entries[0]
    selection = dict(first.get("selection") or {})
    replay_max_positions = int(
        max_positions if max_positions is not None else first.get("max_positions") or 5
    )
    replay_skip_timing = (
        bool(selection.get("skip_timing_wait", True))
        if skip_timing_wait is None
        else bool(skip_timing_wait)
    )
    replay_min_conviction = (
        float(selection.get("min_conviction") or 0.0)
        if min_conviction is None
        else float(min_conviction)
    )
    replay_sector_cap = (
        float(selection.get("sector_cap") or DEFAULT_TARGET_SECTOR_CAP)
        if sector_cap is None
        else float(sector_cap)
    )

    variants: dict[str, dict[str, Any]] = {}
    for screens in exit_confirm_variants:
        preview = replay_counterfactual_from_log(
            entries,
            max_positions=replay_max_positions,
            skip_timing_wait=replay_skip_timing,
            min_conviction=replay_min_conviction,
            sector_cap=replay_sector_cap,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
            exit_confirm_screens=int(screens),
            lookback_days=int(lookback_days),
            as_of=as_of,
            actual_fund=actual_fund,
        )
        if preview is not None:
            variants[str(int(screens))] = preview

    if not variants:
        return None

    ordered = sorted(int(key) for key in variants)
    comparison: dict[str, Any] = {
        "exit_confirm_variants": ordered,
    }
    if len(ordered) >= 2:
        low, high = ordered[0], ordered[-1]
        low_preview = variants[str(low)]
        high_preview = variants[str(high)]
        comparison.update(
            {
                "trade_count_delta_lower_minus_higher": int(
                    low_preview.get("simulated_trade_count") or 0
                )
                - int(high_preview.get("simulated_trade_count") or 0),
                "cost_drag_delta_lower_minus_higher": round(
                    float(low_preview.get("simulated_cost_drag") or 0.0)
                    - float(high_preview.get("simulated_cost_drag") or 0.0),
                    4,
                ),
                "return_delta_lower_minus_higher": round(
                    float(low_preview.get("simulated_return") or 0.0)
                    - float(high_preview.get("simulated_return") or 0.0),
                    4,
                ),
            }
        )
        if low_preview.get("return_delta_vs_actual") is not None:
            comparison["return_delta_vs_actual_lower_minus_higher"] = round(
                float(low_preview.get("return_delta_vs_actual") or 0.0)
                - float(high_preview.get("return_delta_vs_actual") or 0.0),
                4,
            )

    when = as_of or datetime.now(UTC)
    return {
        "scope": "buffered_hold_counterfactual",
        "observe_only": True,
        "track_id": str(first.get("track_id") or track_dir.name or "rules"),
        "lookback_days": int(lookback_days),
        "as_of": when.isoformat(),
        "churn_context": _buffered_hold_context(window_entries),
        "variants": variants,
        "comparison": comparison,
        "limitations": (
            "Observe-only replay of logged passes in the lookback window; "
            "does not mutate live exit_confirm_screens. Lower screen count "
            "exits sooner (more churn); higher count buffers longer."
        ),
    }


def compare_buffered_hold_across_tracks(
    paper_root: Path,
    *,
    track_ids: tuple[str, ...] = ("rules", "ai_judgment"),
    lookback_days: int = 7,
    exit_confirm_variants: tuple[int, ...] = (1, 2),
    as_of: datetime | None = None,
) -> dict[str, Any] | None:
    """Run buffered-hold counterfactual on rules and ai_judgment learning tracks."""
    from value_investor.paper_automation import (
        CONFIG_FILENAME,
        FUND_FILENAME,
        AutomationConfig,
        ensure_automated_fund,
        learning_track_dirs,
    )

    paper_root = Path(paper_root)
    dirs = learning_track_dirs(paper_root)
    tracks: dict[str, Any] = {}
    for track_id in track_ids:
        track_dir = dirs.get(track_id)
        if track_dir is None or not track_dir.exists():
            continue
        fund_path = track_dir / FUND_FILENAME
        config_path = track_dir / CONFIG_FILENAME
        fund = None
        if fund_path.exists() and config_path.exists():
            config = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
            fund = ensure_automated_fund(fund_path, config)
        preview = compare_buffered_hold_counterfactual(
            track_dir,
            lookback_days=lookback_days,
            exit_confirm_variants=exit_confirm_variants,
            as_of=as_of,
            actual_fund=fund,
        )
        if preview is not None:
            tracks[track_id] = preview

    if not tracks:
        return None

    when = as_of or datetime.now(UTC)
    return {
        "scope": "buffered_hold_counterfactual_multi",
        "observe_only": True,
        "lookback_days": int(lookback_days),
        "as_of": when.isoformat(),
        "tracks": tracks,
        "summary": {
            track_id: {
                "churn_context": (row.get("churn_context") or {}),
                "comparison": (row.get("comparison") or {}),
                "logged_exit_confirm_screens": (
                    ((row.get("variants") or {}).get("2") or {}).get("knobs") or {}
                ).get("exit_confirm_screens"),
            }
            for track_id, row in tracks.items()
        },
    }


def write_buffered_hold_counterfactual(
    paper_root: Path,
    *,
    lookback_days: int = 7,
    exit_confirm_variants: tuple[int, ...] = (1, 2),
    as_of: datetime | None = None,
) -> dict[str, Any] | None:
    """Write observe-only buffered-hold counterfactual rollup for learning tracks."""
    from value_investor.storage import write_json

    paper_root = Path(paper_root)
    payload = compare_buffered_hold_across_tracks(
        paper_root,
        lookback_days=lookback_days,
        exit_confirm_variants=exit_confirm_variants,
        as_of=as_of,
    )
    if payload is None:
        return None
    write_json(paper_root / BUFFERED_HOLD_COUNTERFACTUAL_FILENAME, payload, compact=False)
    return payload


def compare_rebalance_counterfactual_previews(
    track_dir: Path,
    *,
    max_positions: int,
    skip_timing_wait: bool = True,
    min_conviction: float = 0.0,
    sector_cap: float = DEFAULT_TARGET_SECTOR_CAP,
    use_adjusted_signal: bool | None = None,
    require_research_accumulate: bool | None = None,
    candidate_source: str = "auto",
    archive_dir: Path | None = None,
    fetch_prices: bool = True,
    actual_fund: PaperFund | None = None,
) -> dict[str, Any] | None:
    """Run log replay and archive replay side-by-side for the same knob set."""
    track_dir = Path(track_dir)
    entries = load_rebalance_log(track_dir)
    log_preview = replay_counterfactual_from_log(
        entries,
        max_positions=max_positions,
        skip_timing_wait=skip_timing_wait,
        min_conviction=min_conviction,
        sector_cap=sector_cap,
        use_adjusted_signal=use_adjusted_signal,
        require_research_accumulate=require_research_accumulate,
        candidate_source=candidate_source,
        actual_fund=actual_fund,
    )
    archive_preview = replay_counterfactual_from_archive(
        track_dir,
        max_positions=max_positions,
        skip_timing_wait=skip_timing_wait,
        min_conviction=min_conviction,
        sector_cap=sector_cap,
        use_adjusted_signal=use_adjusted_signal,
        require_research_accumulate=require_research_accumulate,
        archive_dir=archive_dir,
        fetch_prices=fetch_prices,
        actual_fund=actual_fund,
    )
    if log_preview is None and archive_preview is None:
        return None

    log_delta = (log_preview or {}).get("return_delta_vs_actual")
    archive_delta = (archive_preview or {}).get("return_delta_vs_actual")
    gap: float | None = None
    if log_delta is not None and archive_delta is not None:
        gap = round(float(archive_delta) - float(log_delta), 4)

    return {
        "scope": "rebalance_counterfactual_comparison",
        "observe_only": True,
        "knobs": (log_preview or archive_preview or {}).get("knobs"),
        "log_preview": log_preview,
        "archive_preview": archive_preview,
        "comparison": {
            "log_entries_replayed": (log_preview or {}).get("log_entries_replayed"),
            "archive_passes_replayed": (archive_preview or {}).get("archive_passes_replayed"),
            "log_return_delta_vs_actual": log_delta,
            "archive_return_delta_vs_actual": archive_delta,
            "return_delta_gap_archive_minus_log": gap,
            "log_simulated_return": (log_preview or {}).get("simulated_return"),
            "archive_simulated_return": (archive_preview or {}).get("simulated_return"),
        },
    }


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


def load_initial_knobs(output_dir: Path) -> dict[str, Any]:
    path = Path(output_dir) / "decision_review_history.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, list) or not raw:
        return {}
    first = raw[0]
    if isinstance(first, dict):
        knobs = first.get("knobs_before")
        if isinstance(knobs, dict):
            return dict(knobs)
    return {}


def load_decision_knob_timeline(output_dir: Path) -> list[tuple[datetime, dict[str, Any]]]:
    path = Path(output_dir) / "decision_review_history.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    timeline: list[tuple[datetime, dict[str, Any]]] = []
    for row in raw:
        if not isinstance(row, dict) or not row.get("applied"):
            continue
        if not row.get("proposed_changes"):
            continue
        when = _parse_iso_datetime(str(row.get("reviewed_at") or ""))
        knobs = row.get("knobs_after")
        if when is None or not isinstance(knobs, dict):
            continue
        timeline.append((when, dict(knobs)))
    timeline.sort(key=lambda item: item[0])
    return timeline


def selection_at_time(
    config: Any,
    timeline: list[tuple[datetime, dict[str, Any]]],
    when: str,
    *,
    initial_knobs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge track config selection with applied knob changes as-of a pass timestamp."""
    when_dt = _parse_iso_datetime(when)
    base = config.selection_kwargs() if hasattr(config, "selection_kwargs") else {}
    merged = dict(base)
    seed = dict(initial_knobs or {})
    for key in ("max_positions", "skip_timing_wait", "min_conviction", "sector_cap"):
        if key in seed:
            merged[key] = seed[key]
    if when_dt is None:
        return merged
    for reviewed_at, knobs in timeline:
        if reviewed_at <= when_dt:
            for key in ("max_positions", "skip_timing_wait", "min_conviction", "sector_cap"):
                if key in knobs:
                    merged[key] = knobs[key]
    return merged


def nearest_archive_for(
    archives: list[tuple[datetime, Path]],
    when: str,
) -> Path | None:
    when_dt = _parse_iso_datetime(when)
    if when_dt is None or not archives:
        return None
    best: tuple[datetime, Path] | None = None
    for run_at, path in archives:
        if run_at <= when_dt and (best is None or run_at > best[0]):
            best = (run_at, path)
    if best is not None:
        return best[1]
    return archives[0][1]


def archive_to_marked_rows(
    archive_path: Path,
    *,
    price_hints: dict[str, float],
    fetch_prices: bool = False,
) -> list[dict[str, Any]]:
    from value_investor.archive_history import archive_to_run_snapshot

    snapshot = archive_to_run_snapshot(
        archive_path,
        fetch_prices=fetch_prices,
        price_overrides=price_hints,
    )
    if snapshot is None:
        return []
    marked: list[dict[str, Any]] = []
    for row in snapshot.signals:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        item = dict(row)
        price = snapshot.prices.get(ticker) or price_hints.get(ticker)
        if price is not None and float(price) > 0:
            item["price"] = float(price)
            item["last"] = float(price)
        marked.append(item)
    return marked


def _group_trades_by_pass(trades: list[Any]) -> list[tuple[str, list[Any]]]:
    buckets: dict[str, list[Any]] = {}
    order: list[str] = []
    for trade in trades:
        key = str(getattr(trade, "acted_at", "") or "")
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(trade)
    return [(key, buckets[key]) for key in order]


def bootstrap_rebalance_log(
    track_dir: Path,
    *,
    archive_dir: Path | None = None,
    fetch_prices: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Reconstruct rebalance_log.json from trade history + nearest dashboard archives.

    Rules tracks join archives only. Tracks with AI overlay gates
    (``use_adjusted_signal`` / ``require_research_accumulate``) also apply
    point-in-time research via ``get_research_as_of`` (L113). Entries are
    marked ``bootstrapped: true``.
    """
    from value_investor.archive_history import list_dashboard_archives
    from value_investor.paper_automation import (
        CONFIG_FILENAME,
        FUND_FILENAME,
        AutomationConfig,
    )
    from value_investor.paper_fund import PaperFund, PaperFundConfig, preview_automated_plan

    track_dir = Path(track_dir)
    config_path = track_dir / CONFIG_FILENAME
    fund_path = track_dir / FUND_FILENAME
    if not fund_path.exists():
        return {"ok": False, "reason": "missing automated_fund.json", "entries": 0}

    if config_path.exists():
        config = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    else:
        config = AutomationConfig()

    source_fund = PaperFund.from_dict(json.loads(fund_path.read_text(encoding="utf-8")))
    if not source_fund.trades:
        return {"ok": False, "reason": "no trades to bootstrap", "entries": 0}

    log_path = track_dir / REBALANCE_LOG_FILENAME
    if log_path.exists() and not overwrite:
        existing = load_rebalance_log(track_dir)
        if existing:
            return {
                "ok": True,
                "skipped": True,
                "reason": "rebalance_log.json already exists (use overwrite=True)",
                "entries": len(existing),
            }

    data_dir = Path(archive_dir).parent if archive_dir else Path("docs/data")
    archives = list_dashboard_archives(Path(archive_dir or data_dir / "archive"))
    if not archives:
        return {"ok": False, "reason": "no dashboard archives found", "entries": 0}

    knob_timeline = load_decision_knob_timeline(track_dir)
    initial_knobs = load_initial_knobs(track_dir)
    replay_fund = PaperFund.create(
        PaperFundConfig(
            name=source_fund.config.name,
            mode=source_fund.config.mode,
            initial_cash=float(source_fund.config.initial_cash),
            trade_cost_pct=float(source_fund.config.trade_cost_pct),
            max_positions=int(source_fund.config.max_positions),
        )
    )

    price_hints: dict[str, float] = {}
    for trade in source_fund.trades:
        if float(trade.price) > 0:
            price_hints[str(trade.ticker)] = float(trade.price)
    for ticker, pos in source_fund.holdings.items():
        if pos.avg_cost > 0:
            price_hints.setdefault(ticker, float(pos.avg_cost))

    entries: list[dict[str, Any]] = []
    for acted_at, pass_trades in _group_trades_by_pass(source_fund.trades):
        archive_path = nearest_archive_for(archives, acted_at)
        if archive_path is None:
            continue

        archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
        marked = archive_to_marked_rows(
            archive_path,
            price_hints=price_hints,
            fetch_prices=fetch_prices,
        )
        selection = selection_at_time(config, knob_timeline, acted_at, initial_knobs=initial_knobs)
        pit_research = bool(
            selection.get("use_adjusted_signal") or selection.get("require_research_accumulate")
        )
        if pit_research:
            from value_investor.research.overlay import enrich_marked_rows_with_research

            marked = enrich_marked_rows_with_research(
                marked,
                data_dir,
                as_of=archive_payload.get("run_at") or acted_at,
            )
        max_pos = int(selection.get("max_positions") or config.max_positions)
        replay_fund.config.max_positions = max_pos

        prices_pre = {
            t: float(p.avg_cost) for t, p in replay_fund.holdings.items() if p.avg_cost > 0
        }
        for row in marked:
            ticker = str(row.get("ticker") or "")
            price = row.get("price")
            if ticker and price is not None and float(price) > 0:
                prices_pre[ticker] = float(price)

        nav_before = replay_fund.nav(prices_pre)
        cash_before = float(replay_fund.cash)
        holdings_before = snapshot_holdings(replay_fund)
        rebalance_state_before = replay_fund.rebalance_state.to_dict()

        plan: dict[str, Any] = {}
        if replay_fund.config.mode == "automated":
            plan = preview_automated_plan(
                replay_fund,
                marked,
                skip_timing_wait=bool(selection.get("skip_timing_wait", True)),
                min_conviction=float(selection.get("min_conviction") or 0.0),
                sector_cap=float(selection.get("sector_cap") or 1.0),
                use_adjusted_signal=bool(selection.get("use_adjusted_signal", False)),
                require_research_accumulate=bool(
                    selection.get("require_research_accumulate", False)
                ),
                use_momentum_grace=bool(selection.get("use_momentum_grace", False)),
                exit_confirm_screens=int(selection.get("exit_confirm_screens") or 2),
                reentry_cooldown_screens=int(selection.get("reentry_cooldown_screens") or 1),
                min_rebalance_notional_gbp=float(
                    selection.get("min_rebalance_notional_gbp") or 10.0
                ),
            )

        candidates = collect_decision_candidates(
            marked,
            replay_fund,
            use_adjusted_signal=bool(selection.get("use_adjusted_signal", False)),
        )
        screen_buy_tier = collect_screen_buy_tier(marked, replay_fund)
        gate_excluded = gate_excluded_tickers(screen_buy_tier, candidates)
        trade_payloads = [t.to_dict() for t in pass_trades]
        sector_by_ticker = {
            str(row.get("ticker")): str(row.get("sector") or "")
            for row in marked
            if row.get("ticker")
        }
        for trade in pass_trades:
            if trade.side == "buy":
                ticker = str(trade.ticker)
                replay_fund.buy(
                    ticker=ticker,
                    price=float(trade.price),
                    sizing_mode="shares",
                    amount=float(trade.shares),
                    name=str(trade.name or ticker),
                    sector=sector_by_ticker.get(ticker, ""),
                    note=str(trade.note or "Bootstrapped buy"),
                    acted_at=str(trade.acted_at),
                )
            else:
                replay_fund.sell(
                    ticker=str(trade.ticker),
                    price=float(trade.price),
                    sizing_mode="shares",
                    amount=float(trade.shares),
                    note=str(trade.note or "Bootstrapped sell"),
                    acted_at=str(trade.acted_at),
                )

        prices_post = dict(prices_pre)
        for trade in pass_trades:
            if float(trade.price) > 0:
                prices_post[str(trade.ticker)] = float(trade.price)

        entry = build_rebalance_log_entry(
            track_id=str(config.track_id or "rules"),
            track_label=str(config.track_label or ""),
            strategy_mode=str(config.strategy_mode or replay_fund.config.mode),
            gate={
                "local_time": acted_at,
                "trading_day": True,
                "after_settle": True,
                "can_act": True,
                "reason": "bootstrapped from trade history",
            },
            acted=True,
            note="Bootstrapped rebalance pass from trades + archive",
            selection=selection,
            max_positions=max_pos,
            trade_cost_pct=float(replay_fund.config.trade_cost_pct),
            screen_source={
                "path": str(archive_path),
                "run_at": archive_payload.get("run_at"),
                "generated_at": archive_payload.get("generated_at"),
            },
            knob_epoch_started_at=load_knob_epoch_started_at(track_dir),
            candidates=candidates,
            screen_buy_tier=screen_buy_tier,
            gate_excluded=gate_excluded,
            plan=plan,
            trades=trade_payloads,
            nav_before=nav_before,
            cash_before=cash_before,
            contributed_capital_before=float(replay_fund.contributed_capital),
            holdings_before=holdings_before,
            rebalance_state_before=rebalance_state_before,
            nav_after=replay_fund.nav(prices_post),
            cash_after=float(replay_fund.cash),
            holdings_after=snapshot_holdings(replay_fund),
            rebalance_state_after=replay_fund.rebalance_state.to_dict(),
        )
        entry["bootstrapped"] = True
        entry["bootstrap_source"] = (
            "trades+archives+pit_research" if pit_research else "trades+archives"
        )
        entry["bootstrap_pit_research"] = pit_research
        entries.append(entry)

    log_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "entries": len(entries),
        "path": str(log_path),
        "passes": [e["gate"]["local_time"] for e in entries],
    }
