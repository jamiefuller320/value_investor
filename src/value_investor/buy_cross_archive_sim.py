"""Observe-only archive lab: buy only on screen buy-tier *crosses*.

Walks weekly ``RunSnapshot``s. Week 0 records cash only (no prior → no crosses).
Names that stay buy-tier for the whole span never enter. Held names follow the
same two-screen exit buffer and one-screen re-entry cooldown as the live
``buy_tier_level`` book. T212-shaped costs are applied on every trade.

A parallel **level** replay (buy every current buy-tier name, including week 0)
is scored in the same artifact so the two entry policies can be compared on
identical history. Neither result is a promotion gate.

This lab cannot invent signals, FCF figures, or memo bodies that were not
stored on that week's snapshot — see ``archive_replay_limits``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from value_investor.archive_history import ARCHIVE_SIGNAL_FIELDS
from value_investor.backtest import BENCHMARK_TICKER, RunSnapshot, load_run_snapshots
from value_investor.market_trading_costs import LIVE_PAPER_MARKET_ID, cost_fields_for_config
from value_investor.paper_automation import BUY_TIER_LEVEL_MAX_POSITIONS
from value_investor.paper_fund import (
    BUY_SIGNALS,
    DEFAULT_EXIT_CONFIRM_SCREENS,
    DEFAULT_INITIAL_CASH,
    DEFAULT_REENTRY_COOLDOWN_SCREENS,
    PaperFund,
    PaperFundConfig,
    run_automated_rebalance,
)

COHORTS_FILENAME = "buy_cross_archive.json"
REVIEW_FILENAME = "buy_cross_archive_review.json"
ARCHIVE_TRACK_ID = "buy_cross_archive"
LEVEL_COMPARISON_TRACK_ID = "buy_tier_level_archive"

EntryMode = Literal["cross", "level"]
ENTRY_MODE_CROSS: EntryMode = "cross"
ENTRY_MODE_LEVEL: EntryMode = "level"

DEFAULT_MIN_WEEK_PAIRS = 4


@dataclass
class BuyCrossArchiveConfig:
    initial_cash: float = DEFAULT_INITIAL_CASH
    max_positions: int = BUY_TIER_LEVEL_MAX_POSITIONS
    skip_timing_wait: bool = True
    min_conviction: float = 0.0
    sector_cap: float = 1.0
    exit_confirm_screens: int = DEFAULT_EXIT_CONFIRM_SCREENS
    reentry_cooldown_screens: int = DEFAULT_REENTRY_COOLDOWN_SCREENS
    min_week_pairs: int = DEFAULT_MIN_WEEK_PAIRS
    market_id: str = LIVE_PAPER_MARKET_ID


def archive_replay_limits() -> dict[str, Any]:
    """What the weekly archive can and cannot support for counterfactual sims."""
    return {
        "cadence": "weekly_snapshots_not_daily",
        "prices": "snapshot_marks_not_fills",
        "archived_signal_fields": list(ARCHIVE_SIGNAL_FIELDS),
        "not_in_archive": [
            "fcf_basis_point_in_time",
            "filing_body_text",
            "memo_body_text",
            "intraday_or_daily_fills",
            "signals_not_computed_that_week",
            "live_overlay_closed_cohorts",
        ],
        "policy_constraint": "cannot_mutate_assign_signal",
        "costs_in_this_lab": "t212_fair_applied",
        "exclusion_universe_lab_costs": "gross_of_costs",
        "note": (
            "Counterfactuals are limited to stored weekly fields plus an explicit "
            "cost/lifecycle model. Calendar span is one constraint; missing FCF/"
            "filing PIT, fill prices, and uncomputed signals are the others."
        ),
    }


def archive_sim_metadata() -> dict[str, Any]:
    return {
        "scope": ARCHIVE_TRACK_ID,
        "observe_only": True,
        "entry_policy": "screen_buy_tier_cross_vs_prior_weekly_snapshot",
        "level_comparison": True,
        "costs_included": True,
        "exit_confirm_screens": DEFAULT_EXIT_CONFIRM_SCREENS,
        "reentry_cooldown_screens": DEFAULT_REENTRY_COOLDOWN_SCREENS,
        "limits": archive_replay_limits(),
        "note": (
            "Buy-cross archive lab — new names enter only when they newly appear "
            "in raw screen buy/strong_buy. Persistent buy-tier names never enter. "
            "Not a promotion truth; historic hold→buy crossings are sparse."
        ),
    }


def _snapshot_candidates(entry: RunSnapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in entry.signals:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        price = entry.prices.get(ticker)
        if price is None or float(price) <= 0:
            continue
        merged = dict(row)
        merged["price"] = float(price)
        rows.append(merged)
    return rows


def _buy_tier_tickers(candidates: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for row in candidates:
        signal = str(row.get("signal") or "").strip().lower()
        if signal in BUY_SIGNALS:
            out.add(str(row["ticker"]))
    return out


def _eligible_tickers(
    *,
    mode: EntryMode,
    buy_tier: set[str],
    previous_buy_tier: set[str],
    held: set[str],
    week_index: int,
) -> tuple[set[str], set[str]]:
    """Return (target tickers, newly crossed tickers)."""
    if mode == ENTRY_MODE_LEVEL:
        return set(buy_tier), set(buy_tier - previous_buy_tier) if week_index else set(buy_tier)
    if week_index == 0:
        return set(), set()
    crosses = buy_tier - previous_buy_tier
    return (held & buy_tier) | crosses, crosses


def _make_fund(cfg: BuyCrossArchiveConfig, *, name: str, created_at: str) -> PaperFund:
    costs = cost_fields_for_config(cfg.market_id)
    fund = PaperFund.create(
        PaperFundConfig(
            name=name,
            mode="automated",
            initial_cash=float(cfg.initial_cash),
            trade_cost_pct=float(costs["trade_cost_pct"]),
            buy_cost_pct=float(costs["buy_cost_pct"]),
            sell_cost_pct=float(costs["sell_cost_pct"]),
            max_positions=int(cfg.max_positions),
            created_at=created_at,
        )
    )
    return fund


def _price_map(candidates: list[dict[str, Any]], extra: dict[str, float] | None = None) -> dict[str, float]:
    prices = {str(row["ticker"]): float(row["price"]) for row in candidates}
    if extra:
        for ticker, price in extra.items():
            if ticker not in prices and float(price) > 0:
                prices[ticker] = float(price)
    return prices


def _replay_book(
    snapshots: list[RunSnapshot],
    *,
    mode: EntryMode,
    cfg: BuyCrossArchiveConfig,
) -> dict[str, Any]:
    if not snapshots:
        return {
            "entry_mode": mode,
            "week_count": 0,
            "weekly": [],
            "summary": {"week_pairs": 0, "note": "No snapshots"},
        }

    created_at = snapshots[0].run_at
    label = "Buy-cross archive" if mode == ENTRY_MODE_CROSS else "Buy-tier level archive"
    fund = _make_fund(cfg, name=label, created_at=created_at)
    previous: set[str] = set()
    weekly: list[dict[str, Any]] = []
    first_nav: float | None = None
    first_bench: float | None = None

    for index, snap in enumerate(snapshots):
        candidates = _snapshot_candidates(snap)
        buy_tier = _buy_tier_tickers(candidates)
        held = set(fund.holdings)
        targets, crosses = _eligible_tickers(
            mode=mode,
            buy_tier=buy_tier,
            previous_buy_tier=previous,
            held=held,
            week_index=index,
        )
        prices = _price_map(candidates, extra=dict(snap.prices))
        bench = snap.prices.get(BENCHMARK_TICKER)
        bench_px = float(bench) if bench is not None and float(bench) > 0 else None

        rebalance_rows = [
            row
            for row in candidates
            if str(row["ticker"]) in targets or str(row["ticker"]) in held
        ]
        # Include held names that dropped out of the screen so exits can mark.
        held_missing = held - {str(row["ticker"]) for row in rebalance_rows}
        for ticker in held_missing:
            px = prices.get(ticker)
            if px is None:
                continue
            rebalance_rows.append({"ticker": ticker, "signal": "hold", "price": px})

        trades: list[Any] = []
        if index == 0 and mode == ENTRY_MODE_CROSS:
            fund.record_mark(prices, acted_at=snap.run_at, note="Week 0 — no prior, no crosses")
        elif targets or held:
            target_rows = [row for row in rebalance_rows if str(row["ticker"]) in targets]
            # Non-targets stay in the candidate list so price_map + exit buffer work,
            # but select_automated_targets must not see leftover buy-tier persistents.
            filtered = list(target_rows)
            for row in rebalance_rows:
                ticker = str(row["ticker"])
                if ticker in targets:
                    continue
                filtered.append(row)
            trades = run_automated_rebalance(
                fund,
                filtered,
                acted_at=snap.run_at,
                skip_timing_wait=cfg.skip_timing_wait,
                min_conviction=cfg.min_conviction,
                sector_cap=cfg.sector_cap,
                use_adjusted_signal=False,
                require_research_accumulate=False,
                use_momentum_grace=False,
                exit_confirm_screens=cfg.exit_confirm_screens,
                reentry_cooldown_screens=cfg.reentry_cooldown_screens,
            )
        else:
            fund.record_mark(prices, acted_at=snap.run_at, note="No targets")

        nav = fund.nav(prices)
        if first_nav is None:
            first_nav = nav
        if first_bench is None and bench_px is not None:
            first_bench = bench_px

        prev_nav = weekly[-1]["nav"] if weekly else nav
        weekly_ret = None if prev_nav in (None, 0) else (nav / float(prev_nav)) - 1.0
        prev_bench = weekly[-1].get("benchmark_price") if weekly else bench_px
        bench_ret = None
        if bench_px is not None and prev_bench:
            bench_ret = (bench_px / float(prev_bench)) - 1.0

        weekly.append(
            {
                "run_at": snap.run_at,
                "week_index": index,
                "nav": round(nav, 4),
                "cash": round(float(fund.cash), 4),
                "holdings_count": len(fund.holdings),
                "holdings": sorted(fund.holdings),
                "buy_tier_count": len(buy_tier),
                "cross_count": len(crosses),
                "crosses": sorted(crosses),
                "target_count": len(targets),
                "trade_count": len(trades),
                "weekly_return": None if weekly_ret is None else round(weekly_ret, 6),
                "benchmark_price": bench_px,
                "benchmark_return": None if bench_ret is None else round(bench_ret, 6),
                "weekly_excess": (
                    None
                    if weekly_ret is None or bench_ret is None
                    else round(weekly_ret - bench_ret, 6)
                ),
            }
        )
        previous = buy_tier

    last_nav = weekly[-1]["nav"] if weekly else None
    last_bench = weekly[-1].get("benchmark_price") if weekly else None
    total_ret = None
    if first_nav and last_nav is not None:
        total_ret = (float(last_nav) / float(first_nav)) - 1.0
    bench_total = None
    if first_bench and last_bench:
        bench_total = (float(last_bench) / float(first_bench)) - 1.0
    week_pairs = max(0, len(weekly) - 1)
    excesses = [
        float(row["weekly_excess"])
        for row in weekly
        if row.get("weekly_excess") is not None
    ]
    summary = {
        "week_pairs": week_pairs,
        "final_nav": last_nav,
        "initial_nav": first_nav,
        "total_return": None if total_ret is None else round(total_ret, 6),
        "benchmark_total_return": None if bench_total is None else round(bench_total, 6),
        "excess_vs_benchmark": (
            None
            if total_ret is None or bench_total is None
            else round(total_ret - bench_total, 6)
        ),
        "mean_weekly_excess": (
            None if not excesses else round(sum(excesses) / len(excesses), 6)
        ),
        "final_holdings_count": weekly[-1]["holdings_count"] if weekly else 0,
        "total_crosses": sum(int(row["cross_count"]) for row in weekly),
        "total_trades": sum(int(row["trade_count"]) for row in weekly),
        "names_never_entered_if_always_buy_tier": mode == ENTRY_MODE_CROSS,
    }
    return {
        "entry_mode": mode,
        "week_count": len(weekly),
        "weekly": weekly,
        "summary": summary,
        "final_holdings": weekly[-1]["holdings"] if weekly else [],
    }


def run_buy_cross_archive_sim(
    output_dir: Path,
    *,
    config: BuyCrossArchiveConfig | None = None,
) -> dict[str, Any]:
    """Replay buy-cross (and level comparison) on archived weekly snapshots."""
    cfg = config or BuyCrossArchiveConfig()
    output_dir = Path(output_dir)
    snapshots = load_run_snapshots(output_dir)
    costs = cost_fields_for_config(cfg.market_id)
    generated_at = datetime.now(UTC).isoformat()

    if len(snapshots) < 2:
        review = {
            "schema_version": 1,
            "scope": ARCHIVE_TRACK_ID,
            "track_id": ARCHIVE_TRACK_ID,
            "generated_at": generated_at,
            "framework": archive_sim_metadata(),
            "snapshot_count": len(snapshots),
            "readiness": {
                "ready_for_priors": False,
                "reason": "Need at least 2 archived run snapshots (ftse-archive-history).",
            },
            "note": "Insufficient archive history.",
        }
        _write_artifacts(output_dir, {"cross": {}, "level": {}}, review)
        return review

    cross = _replay_book(snapshots, mode=ENTRY_MODE_CROSS, cfg=cfg)
    level = _replay_book(snapshots, mode=ENTRY_MODE_LEVEL, cfg=cfg)
    week_pairs = int((cross.get("summary") or {}).get("week_pairs") or 0)
    readiness = {
        "ready_for_priors": False,
        "week_pairs": week_pairs,
        "min_week_pairs": cfg.min_week_pairs,
        "reason": (
            "Observe-only lifecycle comparison — do not promote a live buy-cross "
            "book from this archive (sparse historic crossings; week-0 never-enter)."
        ),
    }

    store = {
        "schema_version": 1,
        "scope": ARCHIVE_TRACK_ID,
        "track_id": ARCHIVE_TRACK_ID,
        "level_comparison_track_id": LEVEL_COMPARISON_TRACK_ID,
        "framework": archive_sim_metadata(),
        "generated_at": generated_at,
        "snapshot_count": len(snapshots),
        "first_run_at": snapshots[0].run_at,
        "last_run_at": snapshots[-1].run_at,
        "config": {
            "initial_cash": cfg.initial_cash,
            "max_positions": cfg.max_positions,
            "skip_timing_wait": cfg.skip_timing_wait,
            "min_conviction": cfg.min_conviction,
            "sector_cap": cfg.sector_cap,
            "exit_confirm_screens": cfg.exit_confirm_screens,
            "reentry_cooldown_screens": cfg.reentry_cooldown_screens,
            "market_id": cfg.market_id,
            "costs": costs,
        },
        "cross": {
            "entry_mode": cross["entry_mode"],
            "summary": cross["summary"],
            "final_holdings": cross["final_holdings"],
            "weekly": cross["weekly"],
        },
        "level": {
            "entry_mode": level["entry_mode"],
            "summary": level["summary"],
            "final_holdings": level["final_holdings"],
            "weekly": level["weekly"],
        },
        "updated_at": generated_at,
    }

    review = {
        **store,
        "readiness": readiness,
        "note": (
            "Buy-cross archive sim (observe-only). Cross book buys only names that "
            "newly enter raw screen buy-tier vs the prior weekly snapshot; week 0 "
            "is cash. Level comparison buys the full buy-tier each week (the live "
            "Monday cold-start policy, replayed on history). T212 costs + two-screen "
            "exit buffer applied. Not a promotion gate."
        ),
    }
    _write_artifacts(output_dir, store, review)
    return review


def _write_artifacts(output_dir: Path, store: dict[str, Any], review: dict[str, Any]) -> None:
    (output_dir / COHORTS_FILENAME).write_text(
        json.dumps(store, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / REVIEW_FILENAME).write_text(
        json.dumps(review, indent=2) + "\n", encoding="utf-8"
    )


def format_buy_cross_archive_text(review: dict[str, Any]) -> str:
    cross = (review.get("cross") or {}).get("summary") or {}
    level = (review.get("level") or {}).get("summary") or {}
    lines = [
        "Buy-cross archive sim (observe-only)",
        f"  Snapshots: {review.get('snapshot_count', 0)}",
        f"  Week pairs: {(review.get('readiness') or {}).get('week_pairs', 0)}",
        (
            f"  Cross: return {cross.get('total_return')} | "
            f"excess {cross.get('excess_vs_benchmark')} | "
            f"trades {cross.get('total_trades')} | "
            f"crosses {cross.get('total_crosses')} | "
            f"final holdings {cross.get('final_holdings_count')}"
        ),
        (
            f"  Level: return {level.get('total_return')} | "
            f"excess {level.get('excess_vs_benchmark')} | "
            f"trades {level.get('total_trades')} | "
            f"final holdings {level.get('final_holdings_count')}"
        ),
    ]
    note = review.get("note")
    if note:
        lines.append(f"  Note: {note}")
    return "\n".join(lines)


__all__ = [
    "ARCHIVE_TRACK_ID",
    "COHORTS_FILENAME",
    "LEVEL_COMPARISON_TRACK_ID",
    "REVIEW_FILENAME",
    "BuyCrossArchiveConfig",
    "archive_replay_limits",
    "archive_sim_metadata",
    "format_buy_cross_archive_text",
    "run_buy_cross_archive_sim",
]
