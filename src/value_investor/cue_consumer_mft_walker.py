"""Lab paper episode walker for ``cue_consumer_mft`` (super book).

Thin v0: when Q8B / calendar makes ``evolutionary_shadows_eligible``, walk
archived weekly screen snapshots, consume PIT whitelist cues, and open/close
**lab** fixed-stake paper episodes with durable evidence.

Observe-only (``influences_live=false``). No sealed spawn, no Package L, no
strand-A promote, no Data P1 fat-slot claim. Sealed-child anti-noise remains
on the spawn path (N223/N226/N227) — this module only fills the lab book.

See ``docs/ops/cue-consumer-mft.md``.
"""

from __future__ import annotations

import hashlib
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from value_investor.backtest import RunSnapshot
from value_investor.cue_consumer_mft import (
    CUE_WHITELIST,
    CUE_WHITELIST_ID,
    FIXED_STAKE_UNITS,
    JUDGMENT_RUBRIC_ID,
    LAB_ARM_MARKER_ID,
    LAB_ID,
    REGISTRATION_ID,
    TUNE_SPEC_ID,
    assess_same_day_round_trip,
    judgment_in_the_round_stub,
    select_pit_cues,
)
from value_investor.market_trading_costs import (
    LEGACY_STRESS_TRADE_COST_PCT,
    LIVE_PAPER_MARKET_ID,
    costs_for_market,
)
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.research.verdict import coerce_research_verdict
from value_investor.sealed_lifecycle import with_fair_cost_open_mark

WALKER_MARKER_ID = "mft-episode-walker-v0"
PIPELINE_STATUS_WALKER = "episode_walker_active"
HOLD_TRADING_DAYS = 63
MAX_OPEN_POSITIONS = 30
MAX_CLOSED_EPISODES = 500
MIN_CONVICTION_N210 = 0.6
DEFAULT_MARKET_ID = LIVE_PAPER_MARKET_ID
STRESS_TRADE_COST_PCT = LEGACY_STRESS_TRADE_COST_PCT

# Prefer stronger / richer cues when multiple whitelist sources clear the same name.
CUE_SOURCE_PRIORITY: tuple[str, ...] = (
    "n210_ai_filter",
    "n200_raw_buy_tier",
    "ftse_control_buy_tier",
)

_FTSE_HOLIDAYS = frozenset(
    {
        "2025-01-01",
        "2025-04-18",
        "2025-04-21",
        "2025-05-05",
        "2025-05-26",
        "2025-08-25",
        "2025-12-25",
        "2025-12-26",
        "2026-01-01",
        "2026-04-03",
        "2026-04-06",
        "2026-05-04",
        "2026-05-25",
        "2026-08-31",
        "2026-12-25",
        "2026-12-28",
    }
)

WALKER_FINDING_TITLE = "Cue-consumer MFT episode walker (lab paper fills)"


def _parse_run_at(value: str) -> datetime:
    from value_investor.backtest import _parse_run_at as _br

    return _br(value)


def trading_days_between(start: str, end: str) -> int:
    """Count trading days in ``(start, end]`` with a small UK holiday table."""
    a = _parse_run_at(start).date()
    b = _parse_run_at(end).date()
    if b <= a:
        return 0
    holidays = sorted(_FTSE_HOLIDAYS)
    try:
        return int(np.busday_count(a, b, holidays=holidays))
    except Exception:  # noqa: BLE001 — never break observe on calendar quirks
        days = 0
        cur = a + timedelta(days=1)
        while cur <= b:
            if cur.weekday() < 5 and cur.isoformat() not in _FTSE_HOLIDAYS:
                days += 1
            cur += timedelta(days=1)
        return days


def episode_return(
    entry_price: float,
    exit_price: float,
    *,
    buy_cost_pct: float,
    sell_cost_pct: float,
) -> float:
    raw = exit_price / entry_price - 1.0
    return raw - float(buy_cost_pct) - float(sell_cost_pct)


def fixed_stake_pnl(
    entry_price: float,
    exit_price: float,
    *,
    stake_units: float = FIXED_STAKE_UNITS,
    buy_cost_pct: float,
    sell_cost_pct: float,
) -> dict[str, float]:
    ret = episode_return(
        entry_price, exit_price, buy_cost_pct=buy_cost_pct, sell_cost_pct=sell_cost_pct
    )
    return {
        "stake_units": float(stake_units),
        "return_pct": ret,
        "pnl_local": float(stake_units) * ret,
    }


def _snapshot_rows(snapshot: RunSnapshot) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in snapshot.signals:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        price = snapshot.prices.get(ticker)
        if price is None or float(price) <= 0:
            continue
        out[ticker] = row
    return out


def _price_at(snapshots: list[RunSnapshot], idx: int, ticker: str) -> float | None:
    price = snapshots[idx].prices.get(ticker)
    if price is None or float(price) <= 0:
        return None
    return float(price)


def _latest_quote(
    snapshots: list[RunSnapshot],
    ticker: str,
    *,
    from_idx: int = 0,
) -> tuple[float | None, str | None]:
    start = max(0, int(from_idx))
    for idx in range(len(snapshots) - 1, start - 1, -1):
        price = _price_at(snapshots, idx, ticker)
        if price is not None:
            return price, snapshots[idx].run_at
    return None, None


def _row_market_id(row: dict[str, Any], default: str = DEFAULT_MARKET_ID) -> str:
    mid = str(row.get("market_id") or row.get("market") or "").strip()
    return mid or default


def _buy_sell_costs(market_id: str) -> tuple[float, float]:
    model = costs_for_market(market_id)
    return float(model.buy_pct), float(model.sell_pct)


def _cue_clear(
    row: dict[str, Any],
    *,
    cue_source_id: str,
) -> tuple[bool, str, dict[str, Any]]:
    """Whether the row presents a fireable PIT cue for ``cue_source_id``."""
    signal_raw = str(row.get("signal") or "").strip()
    adjusted = str(row.get("adjusted_signal") or "").strip()
    conviction_raw = row.get("conviction_score")
    try:
        conviction = float(conviction_raw) if conviction_raw is not None else None
        if conviction is not None and conviction != conviction:
            conviction = None
    except (TypeError, ValueError):
        conviction = None
    verdict_raw = row.get("research_verdict")
    verdict = coerce_research_verdict(str(verdict_raw) if verdict_raw is not None else None)
    detail = {
        "cue_source_id": cue_source_id,
        "signal": signal_raw,
        "adjusted_signal": adjusted or None,
        "research_verdict": verdict,
        "conviction_score": conviction,
        "timing_signal": row.get("timing_signal"),
    }

    if cue_source_id in {"n200_raw_buy_tier", "ftse_control_buy_tier"}:
        if signal_raw not in BUY_SIGNALS:
            return False, "not_buy_tier", detail
        if row.get("timing_signal") == "wait":
            return False, "timing_wait", detail
        return True, "raw_buy_tier_clear", detail

    if cue_source_id == "n210_ai_filter":
        signal = adjusted or signal_raw
        detail["signal"] = signal
        if not adjusted and not signal_raw:
            return False, "soft_gap_missing_signal", detail
        if signal not in BUY_SIGNALS:
            return False, "not_buy_tier", detail
        if row.get("timing_signal") == "wait":
            return False, "timing_wait", detail
        if verdict_raw is None or str(verdict_raw).strip() == "":
            return False, "soft_gap_missing_research_verdict", detail
        if verdict != "accumulate":
            return False, "research_not_accumulate", detail
        if conviction is None:
            return False, "soft_gap_missing_conviction", detail
        if conviction < MIN_CONVICTION_N210:
            return False, "conviction_below_floor", detail
        return True, "ai_filter_clear", detail

    return False, "unknown_cue_source", detail


def _episode_id(*, ticker: str, cue_source_id: str, entry_run_at: str) -> str:
    raw = f"{LAB_ID}|{ticker}|{cue_source_id}|{entry_run_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _entry_evidence(
    *,
    ticker: str,
    cue_source_id: str,
    cue_ts: str,
    decision_ts: str,
    clear_note: str,
    detail: dict[str, Any],
) -> dict[str, Any]:
    """Durable open evidence — judgment schema present; N228 fill still deferred."""
    pit = select_pit_cues(
        [
            {
                "cue_source_id": cue_source_id,
                "cue_ts": cue_ts,
                "ticker": ticker,
                "clear_note": clear_note,
            }
        ],
        decision_ts=decision_ts,
    )
    judgment = judgment_in_the_round_stub()
    # B4: registered rule/cue proposes — cite the whitelist cue (scaffold only).
    judgment["buy"]["B4"] = {
        "answer": "cue_whitelist_proposes",
        "confidence": "low",
        "cites": [
            f"cue_source_id={cue_source_id}",
            f"cue_whitelist_id={CUE_WHITELIST_ID}",
            f"clear_note={clear_note}",
        ],
        "unknown": False,
    }
    judgment["rule_candidates"] = [
        {
            "rule_id": cue_source_id,
            "role": "scaffold_propose",
            "cue_whitelist_id": CUE_WHITELIST_ID,
        }
    ]
    judgment["note"] = (
        "v0 walker stamps B4 from PIT cue scaffold; remaining B/S cells stay "
        "unknown until N228 rule-aware LLM decide fill. influences_live=false."
    )
    return {
        "pit_selected": pit,
        "pit_ok": bool(pit),
        "clear_note": clear_note,
        "entry_detail": detail,
        "judgment_in_the_round": judgment,
        "influences_live": False,
        "observe_only": True,
    }


@dataclass(frozen=True)
class WalkerConfig:
    hold_trading_days: int = HOLD_TRADING_DAYS
    fixed_stake_units: float = FIXED_STAKE_UNITS
    max_open_positions: int = MAX_OPEN_POSITIONS
    max_closed_episodes: int = MAX_CLOSED_EPISODES
    market_id: str = DEFAULT_MARKET_ID
    stress_trade_cost_pct: float = STRESS_TRADE_COST_PCT
    cue_sources: tuple[str, ...] = CUE_SOURCE_PRIORITY


def _find_exit_index(
    snapshots: list[RunSnapshot],
    entry_idx: int,
    ticker: str,
    *,
    cue_source_id: str,
    hold_trading_days: int,
) -> tuple[int | None, str | None]:
    entry_at = snapshots[entry_idx].run_at
    for j in range(entry_idx + 1, len(snapshots)):
        row_map = _snapshot_rows(snapshots[j])
        row = row_map.get(ticker)
        reason: str | None = None
        if row is None:
            reason = "identity_break_missing_row"
        else:
            ok, note, _ = _cue_clear(row, cue_source_id=cue_source_id)
            if not ok and not note.startswith("soft_gap_missing"):
                reason = f"identity_break_{note}"
        if reason is not None:
            return j, reason
        held = trading_days_between(entry_at, snapshots[j].run_at)
        if held >= hold_trading_days:
            return j, "hold_trading_days"
    return None, None


def walk_lab_paper_episodes(
    snapshots: list[RunSnapshot],
    *,
    cfg: WalkerConfig | None = None,
    knob_epoch_started_at: str | None = None,
    lab_arm_marker_id: str = LAB_ARM_MARKER_ID,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Walk archive snapshots → lab open/closed fixed-stake paper episodes."""
    cfg = cfg or WalkerConfig()
    when = generated_at or datetime.now(UTC).isoformat()
    epoch_at = knob_epoch_started_at or when

    closed: list[dict[str, Any]] = []
    open_eps: list[dict[str, Any]] = []
    skipped_soft_gap = 0
    skipped_at_open_cap = 0
    cues_considered = 0
    cues_accepted = 0

    # ticker → currently open (prevent double-stake on lab book)
    open_tickers: set[str] = set()
    # per cue-source progressive clear sets
    prev_clear: dict[str, set[str]] = {src: set() for src in cfg.cue_sources}

    for i, snap in enumerate(snapshots):
        if len(closed) >= cfg.max_closed_episodes:
            break
        row_map = _snapshot_rows(snap)
        decision_ts = snap.run_at

        # Progressive clears this snapshot, keyed by cue source.
        clears_now: dict[str, set[str]] = {}
        clear_meta: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        for src in cfg.cue_sources:
            clears_now[src] = set()
            for ticker, row in row_map.items():
                ok, note, detail = _cue_clear(row, cue_source_id=src)
                if ok:
                    clears_now[src].add(ticker)
                    clear_meta[(src, ticker)] = (note, detail)

        # Progressive entries — prefer higher-priority cue when several fire.
        candidates: list[tuple[str, str]] = []  # (ticker, cue_source_id)
        seen_ticker: set[str] = set()
        for src in cfg.cue_sources:
            newly = clears_now[src] - prev_clear[src]
            for ticker in sorted(newly):
                if ticker in seen_ticker or ticker in open_tickers:
                    continue
                seen_ticker.add(ticker)
                candidates.append((ticker, src))

        for ticker, src in candidates:
            cues_considered += 1
            if len(open_tickers) >= cfg.max_open_positions:
                skipped_at_open_cap += 1
                continue

            row = row_map[ticker]
            note, detail = clear_meta[(src, ticker)]
            mid = _row_market_id(row, cfg.market_id)
            buy_pct, sell_pct = _buy_sell_costs(mid)
            evidence = _entry_evidence(
                ticker=ticker,
                cue_source_id=src,
                cue_ts=decision_ts,
                decision_ts=decision_ts,
                clear_note=note,
                detail=detail,
            )
            if not evidence.get("pit_ok"):
                skipped_soft_gap += 1
                continue

            exit_idx, exit_reason = _find_exit_index(
                snapshots,
                i,
                ticker,
                cue_source_id=src,
                hold_trading_days=cfg.hold_trading_days,
            )
            ep_id = _episode_id(ticker=ticker, cue_source_id=src, entry_run_at=decision_ts)
            base = {
                "episode_id": ep_id,
                "lab_id": LAB_ID,
                "registration_id": REGISTRATION_ID,
                "book_kind": "lab_paper",
                "ticker": ticker,
                "market_id": mid,
                "cue_source_id": src,
                "cue_whitelist_id": CUE_WHITELIST_ID,
                "cue_ts": decision_ts,
                "decision_ts": decision_ts,
                "entry_run_at": decision_ts,
                "fixed_stake_units": cfg.fixed_stake_units,
                "sizing_mode": "fixed_stake",
                "scoreboard_unit": "fair_cost_episode_pct",
                "independent_of_fund_nav": True,
                "influences_live": False,
                "observe_only": True,
                "declared_incomparable": True,
                "lab_arm_marker_id": lab_arm_marker_id,
                "walker_marker_id": WALKER_MARKER_ID,
                "tune_spec_id": TUNE_SPEC_ID,
                "knob_epoch_started_at": epoch_at,
                "judgment_rubric_id": JUDGMENT_RUBRIC_ID,
                "evidence": evidence,
                "evolutionary_spawn": False,
                "package_l": False,
            }

            if exit_idx is None:
                p_entry = _price_at(snapshots, i, ticker)
                p_mark, mark_at = _latest_quote(snapshots, ticker, from_idx=i)
                open_eps.append(
                    with_fair_cost_open_mark(
                        {**base, "status": "open"},
                        entry_price=p_entry,
                        mark_price=p_mark,
                        buy_cost_pct=buy_pct,
                        sell_cost_pct=sell_pct,
                        mark_run_at=mark_at,
                    )
                )
                open_tickers.add(ticker)
                cues_accepted += 1
                continue

            p_entry = _price_at(snapshots, i, ticker)
            p_exit = _price_at(snapshots, exit_idx, ticker)
            if p_entry is None or p_exit is None:
                continue
            stake = fixed_stake_pnl(
                p_entry,
                p_exit,
                stake_units=cfg.fixed_stake_units,
                buy_cost_pct=buy_pct,
                sell_cost_pct=sell_pct,
            )
            exit_at = snapshots[exit_idx].run_at
            hold_days = trading_days_between(decision_ts, exit_at)
            same_day = assess_same_day_round_trip(
                entry_at=decision_ts,
                exit_at=exit_at,
                hold_days=hold_days,
            )
            closed.append(
                {
                    **base,
                    "status": "closed",
                    "exit_run_at": exit_at,
                    "hold_trading_days": hold_days,
                    "exit_reason": exit_reason,
                    "return_pct": round(stake["return_pct"], 6),
                    "pnl_local_report_only": round(stake["pnl_local"], 6),
                    "return_pct_stress_report_only": round(
                        episode_return(
                            p_entry,
                            p_exit,
                            buy_cost_pct=cfg.stress_trade_cost_pct,
                            sell_cost_pct=cfg.stress_trade_cost_pct,
                        ),
                        6,
                    ),
                    "same_day_assessment": same_day,
                    "levers_cited": ["stock_choice", "buy_timing", "sell_timing"],
                }
            )
            cues_accepted += 1
            if len(closed) >= cfg.max_closed_episodes:
                break

        for src in cfg.cue_sources:
            prev_clear[src] = clears_now[src]

    returns = [float(e["return_pct"]) for e in closed if e.get("return_pct") is not None]
    median_ret = round(float(statistics.median(returns)), 6) if returns else None

    return {
        "walker_marker_id": WALKER_MARKER_ID,
        "status": "active",
        "pipeline_status": PIPELINE_STATUS_WALKER,
        "influences_live": False,
        "observe_only": True,
        "book_kind": "lab_paper",
        "evolutionary_spawn": False,
        "package_l": False,
        "steals_data_p1_fat_slot": False,
        "cue_whitelist_id": CUE_WHITELIST_ID,
        "cue_sources": list(cfg.cue_sources),
        "whitelist": list(CUE_WHITELIST),
        "hold_trading_days": cfg.hold_trading_days,
        "fixed_stake_units": cfg.fixed_stake_units,
        "max_open_positions": cfg.max_open_positions,
        "cues_considered": cues_considered,
        "cues_accepted": cues_accepted,
        "skipped_soft_gap": skipped_soft_gap,
        "skipped_at_open_cap": skipped_at_open_cap,
        "open_lab_episodes": len(open_eps),
        "closed_lab_episodes": len(closed),
        "open_episodes_sample": open_eps[:25],
        "closed_episodes_sample": closed[:25],
        "closed_episodes": closed,
        "open_episodes": open_eps,
        "path_scoreboard": {
            "unit": "fair_cost_episode_pct",
            "smooth_ret_cohort_median": median_ret,
            "completed_n": len(closed),
            "open_n": len(open_eps),
            "declared_incomparable": True,
            "note": (
                "Lab fair-cost episode % only — never credit cue-book historical NAV as lab wins."
            ),
        },
        "generated_at": when,
    }


def gated_walker_payload(*, reason: str, generated_at: str | None = None) -> dict[str, Any]:
    """Payload when Q8B/calendar has not cleared — no lab fills."""
    return {
        "walker_marker_id": WALKER_MARKER_ID,
        "status": "gated",
        "pipeline_status": None,
        "reason": reason,
        "influences_live": False,
        "observe_only": True,
        "book_kind": "lab_paper",
        "evolutionary_spawn": False,
        "open_lab_episodes": 0,
        "closed_lab_episodes": 0,
        "open_episodes_sample": [],
        "closed_episodes_sample": [],
        "closed_episodes": [],
        "open_episodes": [],
        "path_scoreboard": {
            "unit": "fair_cost_episode_pct",
            "smooth_ret_cohort_median": None,
            "completed_n": 0,
            "open_n": 0,
            "declared_incomparable": True,
        },
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "note": (
            "Episode walker waits on evolutionary_shadows_eligible "
            "(Q8B cohort complete or calendar fallback)."
        ),
    }


__all__ = [
    "HOLD_TRADING_DAYS",
    "MAX_OPEN_POSITIONS",
    "PIPELINE_STATUS_WALKER",
    "WALKER_FINDING_TITLE",
    "WALKER_MARKER_ID",
    "WalkerConfig",
    "fixed_stake_pnl",
    "gated_walker_payload",
    "trading_days_between",
    "walk_lab_paper_episodes",
]
