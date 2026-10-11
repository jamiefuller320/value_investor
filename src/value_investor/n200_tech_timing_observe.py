"""N200 sealed observe-only: raw buy-tier identity + technical entry/exit brackets.

registration_id: ``strand-b-plain-value-tech-timing-v0``

Walks archived weekly screen snapshots, opens episodes when a name newly enters
the buy tier, and scores calendar ±14d entry/exit brackets against default
timing (offset 0). Observe-only — never writes strand A books, knobs, or
``decision-review --apply``.

See ``docs/ops/n200-tech-timing-observe.md`` and Project store
``alternate-strand-learning-questions.md``.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.backtest import RunSnapshot, load_run_snapshots
from value_investor.market_trading_costs import (
    LEGACY_STRESS_TRADE_COST_PCT,
    LIVE_PAPER_MARKET_ID,
    costs_for_market,
)
from value_investor.paper_fund import BUY_SIGNALS

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/n200_tech_timing_observe.json")
DEFAULT_REGISTRATION_PATH = Path("docs/data/n200_tech_timing_registration.json")
DEFAULT_OPS_STATUS_PATH = Path("docs/data/ops_status.json")
DEFAULT_OPS_DOC = Path("docs/ops/n200-tech-timing-observe.md")

REGISTRATION_ID = "strand-b-plain-value-tech-timing-v0"
DEFERRED_ID = "N200"
IDENTITY_ID = "raw_buy_tier"
SUCCESS_METRIC_ID = "smooth_ret_cohort_median"
SCHEMA_VERSION = 2
PIPELINE_HEALTH_SCHEMA_VERSION = 1
# Ops-monitor runs ~2×/day; past this the observe store is obviously stale.
DEFAULT_STALE_AFTER_HOURS = 30.0
DEFAULT_STORE_LAG_WARN_HOURS = 2.0
PIPELINE_HEALTH_DISCLAIMER = (
    "Phase floor and volume gate measure mechanism throughput health — "
    "not alpha, path P&L, or capital readiness (F8). Observe-only."
)

BRACKET_OFFSETS_DAYS = (-14, 0, 14)
# Primary = fair market-table (FTSE/LSE archive → ftse350). Stress 3%/side = report-only.
DEFAULT_MARKET_ID = LIVE_PAPER_MARKET_ID
STRESS_TRADE_COST_PCT = LEGACY_STRESS_TRADE_COST_PCT
FAIR_COST_MARKER_ID = "n200-fair-cost-primary-v1"
VOLUME_MIN_EPISODES = 24
VOLUME_MIN_WEEKS = 8
PHASE_ENTRIES_PER_WEEK_FLOOR = 5.0
MAX_EPISODES = 500

F9_BIND_FIELDS = (
    "key_filing_bodies",
    "fcf_basis_bound",
    "overlay_bound",
    "memo_recent",
)

LEARNING_QUESTION = (
    "On threshold-eligible names, does raw_buy_tier identity with calendar "
    "±14d entry/exit timing brackets beat default timing (offset 0) on "
    "cost-aware smooth_ret_cohort_median?"
)

FINDING_TITLE = "N200 tech-timing observe refreshed"
STORE_FAILED_TITLE = "N200 tech-timing observe failed"
VOLUME_GATE_TITLE = "N200 volume gate ready for review"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_run_at(value: str) -> datetime:
    from value_investor.backtest import _parse_run_at

    return _parse_run_at(value)


def _days_between(start: str, end: str) -> int:
    return max(0, int((_parse_run_at(end) - _parse_run_at(start)).total_seconds() // 86400))


def _effective_signal(row: dict[str, Any]) -> str:
    adjusted = str(row.get("adjusted_signal") or "").strip()
    if adjusted:
        return adjusted
    return str(row.get("signal") or "").strip()


def _is_buy_tier(row: dict[str, Any]) -> bool:
    return _effective_signal(row) in BUY_SIGNALS


def _truthy_bind(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"", "none", "null"}:
        return None
    if text in {"0", "false", "no", "missing", "stale"}:
        return False
    return True


def row_f9_eligible(row: dict[str, Any]) -> tuple[bool, str]:
    """F9 per-name binds when present; else pass with note (archive MVP).

    Capital influence remains fail-closed elsewhere (F8) — this observe lane
    never promotes.
    """
    present = 0
    for field in F9_BIND_FIELDS:
        flag = _truthy_bind(row.get(field))
        if flag is None:
            continue
        present += 1
        if not flag:
            return False, f"f9_fail:{field}"
    if present == 0:
        return True, "eligibility_mode=row_fields_or_pass"
    return True, "f9_binds_ok"


def _buy_tier_rows(snapshot: RunSnapshot) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in snapshot.signals:
        if not _is_buy_tier(row):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        price = snapshot.prices.get(ticker)
        if price is None or float(price) <= 0:
            continue
        out[ticker] = row
    return out


def _nearest_snapshot_index(
    snapshots: list[RunSnapshot],
    origin_idx: int,
    offset_days: int,
) -> int | None:
    if not snapshots:
        return None
    if offset_days == 0:
        return origin_idx
    origin = _parse_run_at(snapshots[origin_idx].run_at)
    target = origin.timestamp() + offset_days * 86400
    best_i: int | None = None
    best_delta: float | None = None
    for i, snap in enumerate(snapshots):
        ts = _parse_run_at(snap.run_at).timestamp()
        delta = abs(ts - target)
        # Prefer snapshots on the correct side of origin when close.
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_i = i
    if best_i is None:
        return None
    # Reject if more than ~10 days off the requested offset (sparse history).
    if best_delta is not None and best_delta > 10 * 86400:
        return None
    return best_i


def _price_at(snapshots: list[RunSnapshot], idx: int, ticker: str) -> float | None:
    price = snapshots[idx].prices.get(ticker)
    if price is None or float(price) <= 0:
        return None
    return float(price)


def episode_return(
    entry_price: float,
    exit_price: float,
    *,
    trade_cost_pct: float | None = None,
    buy_cost_pct: float | None = None,
    sell_cost_pct: float | None = None,
) -> float:
    """Round-trip cost-aware simple return.

    Prefer asymmetric ``buy_cost_pct`` / ``sell_cost_pct`` (fair market table).
    ``trade_cost_pct`` is a symmetric per-side proxy (``raw - 2 * pct``), used
    for stress diagnostics and explicit overrides.
    """
    raw = exit_price / entry_price - 1.0
    if buy_cost_pct is not None and sell_cost_pct is not None:
        return raw - float(buy_cost_pct) - float(sell_cost_pct)
    if trade_cost_pct is None:
        raise ValueError("Provide buy_cost_pct+sell_cost_pct or trade_cost_pct")
    return raw - 2.0 * float(trade_cost_pct)


@dataclass(frozen=True)
class N200Config:
    bracket_offsets_days: tuple[int, ...] = BRACKET_OFFSETS_DAYS
    market_id: str = DEFAULT_MARKET_ID
    buy_cost_pct: float | None = None
    sell_cost_pct: float | None = None
    stress_trade_cost_pct: float = STRESS_TRADE_COST_PCT
    volume_min_episodes: int = VOLUME_MIN_EPISODES
    volume_min_weeks: int = VOLUME_MIN_WEEKS
    phase_entries_per_week_floor: float = PHASE_ENTRIES_PER_WEEK_FLOOR
    max_episodes: int = MAX_EPISODES

    def primary_buy_sell(self) -> tuple[float, float]:
        if self.buy_cost_pct is not None and self.sell_cost_pct is not None:
            return float(self.buy_cost_pct), float(self.sell_cost_pct)
        model = costs_for_market(self.market_id)
        return float(model.buy_pct), float(model.sell_pct)

    def primary_cost_fields(self) -> dict[str, Any]:
        model = costs_for_market(self.market_id)
        buy, sell = self.primary_buy_sell()
        return {
            "primary": "fair_market_table",
            "market_id": model.market_id,
            "buy_cost_pct": round(buy, 6),
            "sell_cost_pct": round(sell, 6),
            "round_trip_pct": round(buy + sell, 6),
            "trade_cost_pct_symmetric_proxy": round((buy + sell) / 2.0, 6),
            "source": model.source,
            "stress_trade_cost_pct": float(self.stress_trade_cost_pct),
            "stress_role": "report_only",
        }


def build_registration_payload(*, sealed_at: str | None = None) -> dict[str, Any]:
    """Canonical seal record written to ``n200_tech_timing_registration.json``."""
    cfg = N200Config()
    cost = cfg.primary_cost_fields()
    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "status": "sealed_observe_only",
        "sealed_at": sealed_at or "2026-10-11",
        "observe_only": True,
        "influences_live": False,
        "learning_question": LEARNING_QUESTION,
        "identity_id": IDENTITY_ID,
        "success_metric_id": SUCCESS_METRIC_ID,
        "o2_identity": IDENTITY_ID,
        "o3_volume_gate": {
            "completed_entry_episodes_min": VOLUME_MIN_EPISODES,
            "calendar_weeks_spanned_min": VOLUME_MIN_WEEKS,
            "rule": "both_required",
        },
        "o4_smoother": SUCCESS_METRIC_ID,
        "o5_primacy": {
            "primary": "absolute_smoothed_return_fair_costs",
            "control_excess": "report_only",
            "stress_cost": "report_only",
        },
        "o6_phase_floor": {
            "entries_per_week_target": PHASE_ENTRIES_PER_WEEK_FLOOR,
            "note": "illustrative sealed mechanism floor (5–10 band)",
        },
        "brackets": {
            "entry_offsets_days": list(BRACKET_OFFSETS_DAYS),
            "exit_offsets_days": list(BRACKET_OFFSETS_DAYS),
        },
        "cost_basis": cost,
        # Symmetric proxy for legacy single-rate readers (fair table, not stress).
        "trade_cost_pct": cost["trade_cost_pct_symmetric_proxy"],
        "buy_cost_pct": cost["buy_cost_pct"],
        "sell_cost_pct": cost["sell_cost_pct"],
        "stress_trade_cost_pct": cost["stress_trade_cost_pct"],
        "cost_amendment": {
            "kept_registration_id": True,
            "marker_id": FAIR_COST_MARKER_ID,
            "reason": (
                "Amend-in-place: fair market-table costs become primary; "
                "legacy 3% per side kept as stress/report-only. Same "
                "registration_id — exploratory stamp fix via change marker, "
                "not a new learning question."
            ),
        },
        "constraints": [
            "observe_only",
            "no_live_strand_a_writes",
            "no_decision_review_apply",
            "no_new_screen_extras",
            "f9_eligibility",
            "f8_fail_closed",
            "per_lever_scoreboard_separate_from_path_pnl",
            "logged_change_markers",
            "fair_costs_primary",
            "stress_cost_report_only",
        ],
        "n201_sealed": False,
        "ops_doc": str(DEFAULT_OPS_DOC),
        "observe_store": str(DEFAULT_STORE_PATH),
    }


def _cell_key(entry_offset: int, exit_offset: int) -> str:
    return f"entry_{entry_offset:+d}__exit_{exit_offset:+d}"


def _median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(statistics.median(values)), 6)


def build_n200_observe(
    snapshots: list[RunSnapshot],
    *,
    cfg: N200Config | None = None,
    generated_at: str | None = None,
    prior_markers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score N200 brackets from archive snapshots (pure; no I/O)."""
    cfg = cfg or N200Config()
    offsets = tuple(cfg.bracket_offsets_days)
    buy_pct, sell_pct = cfg.primary_buy_sell()
    stress_pct = float(cfg.stress_trade_cost_pct)
    cost_fields = cfg.primary_cost_fields()
    episodes: list[dict[str, Any]] = []
    skipped_ineligible = 0
    cell_returns: dict[str, list[float]] = {_cell_key(e, x): [] for e in offsets for x in offsets}
    stress_control_returns: list[float] = []
    entry_lever_returns: dict[int, list[float]] = {o: [] for o in offsets}
    exit_lever_returns: dict[int, list[float]] = {o: [] for o in offsets}

    prev_buy: set[str] = set()
    for i, snap in enumerate(snapshots):
        buy_map = _buy_tier_rows(snap)
        buy_set = set(buy_map)
        for ticker in sorted(buy_set - prev_buy):
            row = buy_map[ticker]
            eligible, elig_note = row_f9_eligible(row)
            if not eligible:
                skipped_ineligible += 1
                continue
            # Find first leave of buy-tier.
            exit_idx: int | None = None
            for j in range(i + 1, len(snapshots)):
                if ticker not in _buy_tier_rows(snapshots[j]):
                    exit_idx = j
                    break
            if exit_idx is None:
                continue  # still open — not scored for primary
            episode_cells: dict[str, float | None] = {}
            for e_off in offsets:
                e_i = _nearest_snapshot_index(snapshots, i, e_off)
                if e_i is None:
                    continue
                p_entry = _price_at(snapshots, e_i, ticker)
                if p_entry is None:
                    continue
                for x_off in offsets:
                    x_i = _nearest_snapshot_index(snapshots, exit_idx, x_off)
                    if x_i is None or x_i <= e_i:
                        episode_cells[_cell_key(e_off, x_off)] = None
                        continue
                    p_exit = _price_at(snapshots, x_i, ticker)
                    if p_exit is None:
                        episode_cells[_cell_key(e_off, x_off)] = None
                        continue
                    ret = episode_return(
                        p_entry, p_exit, buy_cost_pct=buy_pct, sell_cost_pct=sell_pct
                    )
                    episode_cells[_cell_key(e_off, x_off)] = round(ret, 6)
                    cell_returns[_cell_key(e_off, x_off)].append(ret)
                # Entry lever: control exit (0)
                x0 = _nearest_snapshot_index(snapshots, exit_idx, 0)
                if x0 is not None and x0 > e_i:
                    p_x = _price_at(snapshots, x0, ticker)
                    if p_x is not None:
                        entry_lever_returns[e_off].append(
                            episode_return(
                                p_entry, p_x, buy_cost_pct=buy_pct, sell_cost_pct=sell_pct
                            )
                        )
            # Exit lever: control entry (0)
            e0 = _nearest_snapshot_index(snapshots, i, 0)
            p_e0 = _price_at(snapshots, e0, ticker) if e0 is not None else None
            if p_e0 is not None:
                for x_off in offsets:
                    x_i = _nearest_snapshot_index(snapshots, exit_idx, x_off)
                    if x_i is None or e0 is None or x_i <= e0:
                        continue
                    p_x = _price_at(snapshots, x_i, ticker)
                    if p_x is None:
                        continue
                    exit_lever_returns[x_off].append(
                        episode_return(p_e0, p_x, buy_cost_pct=buy_pct, sell_cost_pct=sell_pct)
                    )
            # Stress diagnostic on control cell only (report-only).
            control_ret_stress: float | None = None
            e0_ctrl = _nearest_snapshot_index(snapshots, i, 0)
            x0_ctrl = _nearest_snapshot_index(snapshots, exit_idx, 0)
            if e0_ctrl is not None and x0_ctrl is not None and x0_ctrl > e0_ctrl:
                p_in = _price_at(snapshots, e0_ctrl, ticker)
                p_out = _price_at(snapshots, x0_ctrl, ticker)
                if p_in is not None and p_out is not None:
                    control_ret_stress = episode_return(p_in, p_out, trade_cost_pct=stress_pct)
                    stress_control_returns.append(control_ret_stress)
            hold_days = _days_between(snap.run_at, snapshots[exit_idx].run_at)
            episodes.append(
                {
                    "ticker": ticker,
                    "entry_run_at": snap.run_at,
                    "exit_run_at": snapshots[exit_idx].run_at,
                    "hold_days": hold_days,
                    "eligibility": elig_note,
                    "cells": episode_cells,
                    "control_return": episode_cells.get(_cell_key(0, 0)),
                    "control_return_stress_report_only": (
                        None if control_ret_stress is None else round(control_ret_stress, 6)
                    ),
                }
            )
            if len(episodes) >= cfg.max_episodes:
                break
        prev_buy = buy_set
        if len(episodes) >= cfg.max_episodes:
            break

    control_key = _cell_key(0, 0)
    control_returns = cell_returns.get(control_key) or []
    absolute_primary = _median_or_none(control_returns)
    stress_control_median = _median_or_none(stress_control_returns)

    cell_summary: dict[str, Any] = {}
    best_cell = control_key
    best_med = absolute_primary
    for key, vals in cell_returns.items():
        med = _median_or_none(vals)
        excess = None
        if med is not None and absolute_primary is not None:
            excess = round(med - absolute_primary, 6)
        cell_summary[key] = {
            "n": len(vals),
            "smooth_ret_cohort_median": med,
            "control_excess_report_only": excess,
        }
        if med is not None and (best_med is None or med > best_med):
            best_med = med
            best_cell = key

    entry_lever = {
        str(o): {
            "n": len(entry_lever_returns[o]),
            "smooth_ret_cohort_median": _median_or_none(entry_lever_returns[o]),
        }
        for o in offsets
    }
    exit_lever = {
        str(o): {
            "n": len(exit_lever_returns[o]),
            "smooth_ret_cohort_median": _median_or_none(exit_lever_returns[o]),
        }
        for o in offsets
    }

    weeks = 0
    if len(snapshots) >= 2:
        weeks = max(1, _days_between(snapshots[0].run_at, snapshots[-1].run_at) // 7)
    elif snapshots:
        weeks = 1
    entries_per_week = round(len(episodes) / weeks, 3) if weeks else None
    volume_gate_met = len(episodes) >= cfg.volume_min_episodes and weeks >= cfg.volume_min_weeks
    phase_ok = entries_per_week is not None and entries_per_week >= cfg.phase_entries_per_week_floor

    seal_marker = {
        "marker_id": "n200-seal-v0",
        "at": "2026-10-11T00:00:00+00:00",
        "lever": "params",
        "before_id": None,
        "after_id": REGISTRATION_ID,
        "registration_id": REGISTRATION_ID,
        "reason": "Initial seal: raw_buy_tier + ±14d brackets, absolute primary",
        "eligible_set_ref": "archive_history_buy_tier_f9_or_pass",
        "success_metric_id": SUCCESS_METRIC_ID,
        "applies_to": "observe_only",
    }
    fair_cost_marker = {
        "marker_id": FAIR_COST_MARKER_ID,
        "at": "2026-10-11T12:00:00+00:00",
        "lever": "params",
        "before_id": "cost_stamp_stress_0.03_per_side",
        "after_id": "cost_stamp_fair_market_table_ftse350",
        "registration_id": REGISTRATION_ID,
        "reason": (
            "Amend sealed cost stamp in place: primary episode returns use "
            "fair market-table costs (T212-shaped / market_trading_costs for "
            f"{cost_fields['market_id']}); legacy 3% per side kept as "
            "stress/report-only. Same registration_id — exploratory stamp "
            "fix via logged marker, not a new learning question."
        ),
        "eligible_set_ref": "archive_history_buy_tier_f9_or_pass",
        "success_metric_id": SUCCESS_METRIC_ID,
        "applies_to": "observe_only",
    }
    markers = list(prior_markers or [])
    if not any(m.get("marker_id") == seal_marker["marker_id"] for m in markers):
        markers.insert(0, seal_marker)
    if not any(m.get("marker_id") == fair_cost_marker["marker_id"] for m in markers):
        markers.append(fair_cost_marker)

    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "generated_at": generated_at or _utc_now(),
        "observe_only": True,
        "influences_live": False,
        "identity_id": IDENTITY_ID,
        "success_metric_id": SUCCESS_METRIC_ID,
        "learning_question": LEARNING_QUESTION,
        "cost_basis": cost_fields,
        "snapshot_count": len(snapshots),
        "completed_entry_episodes": len(episodes),
        "skipped_ineligible": skipped_ineligible,
        "calendar_weeks_spanned": weeks,
        "volume_gate": {
            "min_episodes": cfg.volume_min_episodes,
            "min_weeks": cfg.volume_min_weeks,
            "met": volume_gate_met,
        },
        "phase": {
            "entries_per_week": entries_per_week,
            "floor": cfg.phase_entries_per_week_floor,
            "floor_met": phase_ok,
        },
        "path_scoreboard": {
            "primary": "absolute_smoothed_return_fair_costs",
            "success_metric_id": SUCCESS_METRIC_ID,
            "control_cell": control_key,
            "control_smooth_ret_cohort_median": absolute_primary,
            "control_smooth_ret_cohort_median_stress_report_only": stress_control_median,
            "diagnostic_best_cell": best_cell,
            "diagnostic_best_median": best_med,
            "note": (
                "Control absolute primary uses fair market-table costs. "
                "Stress 3%/side control median is report-only. "
                "Best-cell is diagnostic only — not a promote signal (F8)."
            ),
        },
        "stress_scoreboard_report_only": {
            "trade_cost_pct_per_side": stress_pct,
            "control_cell": control_key,
            "control_smooth_ret_cohort_median": stress_control_median,
            "n": len(stress_control_returns),
            "role": "report_only",
        },
        "cells": cell_summary,
        "entry_lever_scoreboard": entry_lever,
        "exit_lever_scoreboard": exit_lever,
        "change_markers": markers,
        "episodes_sample": episodes[:25],
        "ops_doc": str(DEFAULT_OPS_DOC),
    }


def refresh_n200_tech_timing_observe(
    *,
    output_dir: Path | None = None,
    store_path: Path | None = None,
    registration_path: Path | None = None,
    persist: bool = True,
    cfg: N200Config | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Load archive history, score brackets, optionally persist stores."""
    data_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    reg_path = (
        Path(registration_path) if registration_path is not None else DEFAULT_REGISTRATION_PATH
    )

    prior_markers: list[dict[str, Any]] = []
    if store.is_file():
        try:
            prior = json.loads(store.read_text(encoding="utf-8"))
            markers = prior.get("change_markers")
            if isinstance(markers, list):
                prior_markers = [m for m in markers if isinstance(m, dict)]
        except (OSError, json.JSONDecodeError):
            prior_markers = []

    snapshots = load_run_snapshots(data_dir)
    payload = build_n200_observe(
        snapshots,
        cfg=cfg,
        generated_at=generated_at,
        prior_markers=prior_markers,
    )
    registration = build_registration_payload()

    if persist:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(registration, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_findings_from_n200_observe(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map observe store → ops-monitor finding dicts (observe-only)."""
    findings: list[dict[str, Any]] = []
    n = int(payload.get("completed_entry_episodes") or 0)
    weeks = int(payload.get("calendar_weeks_spanned") or 0)
    phase = payload.get("phase") if isinstance(payload.get("phase"), dict) else {}
    path = (
        payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    )
    control_med = path.get("control_smooth_ret_cohort_median")
    stress_med = path.get("control_smooth_ret_cohort_median_stress_report_only")
    entries_pw = phase.get("entries_per_week")
    findings.append(
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"{REGISTRATION_ID}: {n} completed episodes over {weeks} weeks; "
                f"entries/week={entries_pw}; control {SUCCESS_METRIC_ID}="
                f"{control_med} (fair costs primary); "
                f"stress_3pct_report_only={stress_med}. "
                "Observe-only — no live writes (F8)."
            ),
            "auto_fixable": False,
        }
    )
    volume = payload.get("volume_gate") if isinstance(payload.get("volume_gate"), dict) else {}
    if volume.get("met"):
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": VOLUME_GATE_TITLE,
                "summary": (
                    f"Volume gate met (episodes>={VOLUME_MIN_EPISODES} and "
                    f"weeks>={VOLUME_MIN_WEEKS}). Human may review brackets; "
                    "no auto-promote."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def format_n200_observe_text(payload: dict[str, Any]) -> str:
    path = (
        payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    )
    phase = payload.get("phase") if isinstance(payload.get("phase"), dict) else {}
    volume = payload.get("volume_gate") if isinstance(payload.get("volume_gate"), dict) else {}
    cost = payload.get("cost_basis") if isinstance(payload.get("cost_basis"), dict) else {}
    lines = [
        f"N200 {payload.get('registration_id')} (observe-only)",
        f"  episodes={payload.get('completed_entry_episodes')} "
        f"weeks={payload.get('calendar_weeks_spanned')} "
        f"entries/week={phase.get('entries_per_week')}",
        f"  control {SUCCESS_METRIC_ID}={path.get('control_smooth_ret_cohort_median')} "
        f"(fair {cost.get('market_id')} RT={cost.get('round_trip_pct')})",
        f"  stress_3pct_report_only="
        f"{path.get('control_smooth_ret_cohort_median_stress_report_only')}",
        f"  volume_gate_met={volume.get('met')} phase_floor_met={phase.get('floor_met')}",
        f"  diagnostic_best_cell={path.get('diagnostic_best_cell')}",
    ]
    return "\n".join(lines) + "\n"


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _hours_since(then: datetime | None, *, now: datetime) -> float | None:
    if then is None:
        return None
    return round((now - then).total_seconds() / 3600.0, 2)


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _freshness_block(
    *,
    as_of: datetime | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
    present: bool,
) -> dict[str, Any]:
    age_h = _hours_since(as_of, now=now)
    store_lag_h = None
    if as_of is not None and ops_run_at is not None and ops_run_at > as_of:
        store_lag_h = round((ops_run_at - as_of).total_seconds() / 3600.0, 2)

    if not present:
        state = "missing"
        label = "Missing"
        detail = "N200 observe store not published yet."
    elif age_h is None:
        state = "unknown"
        label = "Unknown"
        detail = "Store present but no usable timestamp."
    elif age_h >= stale_after_hours:
        state = "stale"
        label = "Stale"
        detail = f"Last refresh {age_h:.1f}h ago (limit {stale_after_hours:.0f}h)."
    elif store_lag_h is not None and store_lag_h >= store_lag_warn_hours:
        state = "lagging"
        label = "Lagging ops"
        detail = f"Store trails ops_status by {store_lag_h:.1f}h (check ops-monitor commit path)."
    else:
        state = "fresh"
        label = "Fresh"
        detail = f"Last refresh {age_h:.1f}h ago."

    return {
        "state": state,
        "label": label,
        "detail": detail,
        "as_of": as_of.isoformat() if as_of else None,
        "age_hours": age_h,
        "store_lag_hours": store_lag_h,
        "stale_after_hours": float(stale_after_hours),
    }


def _ops_n200_check_status(ops_status: dict[str, Any] | None) -> dict[str, Any]:
    """Whether daily ops-monitor N200 check looks healthy in findings."""
    findings = (ops_status or {}).get("findings")
    rows = findings if isinstance(findings, list) else []
    titles = {str(row.get("title") or "") for row in rows if isinstance(row, dict)}
    failed = STORE_FAILED_TITLE in titles
    refreshed = FINDING_TITLE in titles
    if failed:
        return {
            "ops_check_ok": False,
            "ops_finding_present": True,
            "detail": f"Ops finding: {STORE_FAILED_TITLE}",
        }
    if refreshed:
        return {
            "ops_check_ok": True,
            "ops_finding_present": True,
            "detail": f"Ops finding: {FINDING_TITLE}",
        }
    return {
        "ops_check_ok": False,
        "ops_finding_present": False,
        "detail": "No N200 ops finding in latest ops_status (store may lag until ops commits).",
    }


def build_n200_pipeline_health_projection(
    payload: dict[str, Any] | None = None,
    *,
    store_path: Path | None = None,
    ops_status_path: Path | None = None,
    ops_status: dict[str, Any] | None = None,
    now: datetime | None = None,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    store_lag_warn_hours: float = DEFAULT_STORE_LAG_WARN_HOURS,
) -> dict[str, Any]:
    """Slim dashboard projection: phase floor, volume gate, pipeline freshness.

    Reads the committed observe store (does **not** re-score archive history).
    Phase green = throughput health only — never alpha or capital-ready (F8).
    """
    clock = now or datetime.now(UTC)
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    if payload is None:
        payload = _safe_read_json(store)
    present = isinstance(payload, dict) and bool(payload)

    if ops_status is None:
        ops_path = Path(ops_status_path) if ops_status_path is not None else DEFAULT_OPS_STATUS_PATH
        ops_status = _safe_read_json(ops_path)

    ops_run_at = _parse_dt((ops_status or {}).get("run_at"))
    store_as_of = _parse_dt((payload or {}).get("generated_at")) if present else None
    freshness = _freshness_block(
        as_of=store_as_of,
        now=clock,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=present,
    )
    ops_check = _ops_n200_check_status(ops_status)

    phase_raw = (payload or {}).get("phase") if present else None
    phase = phase_raw if isinstance(phase_raw, dict) else {}
    volume_raw = (payload or {}).get("volume_gate") if present else None
    volume = volume_raw if isinstance(volume_raw, dict) else {}
    episodes = int((payload or {}).get("completed_entry_episodes") or 0) if present else 0
    weeks = int((payload or {}).get("calendar_weeks_spanned") or 0) if present else 0

    entries_pw = phase.get("entries_per_week")
    floor = phase.get("floor", PHASE_ENTRIES_PER_WEEK_FLOOR)
    floor_met = bool(phase.get("floor_met")) if present and "floor_met" in phase else False
    volume_met = bool(volume.get("met")) if present and "met" in volume else False

    # Functioning = store usable + not stale/missing + (ops check ok OR store fresh).
    freshness_ok = freshness["state"] in {"fresh", "lagging"}
    ops_ok = bool(ops_check["ops_check_ok"]) or (freshness["state"] == "fresh" and present)
    functioning = bool(present and freshness_ok and ops_ok)

    if not present:
        headline = "N200 observe store missing — pipeline not yet published."
    elif not functioning:
        headline = (
            f"N200 pipeline attention — freshness={freshness['state']}; "
            f"phase floor {'met' if floor_met else 'not met'}; "
            f"volume gate {'met' if volume_met else 'not met'}."
        )
    elif floor_met and volume_met:
        headline = (
            f"N200 pipeline functioning — phase {entries_pw}/{floor} entries/week "
            f"(floor met); volume gate met ({episodes} ep / {weeks} wk)."
        )
    elif floor_met:
        headline = (
            f"N200 pipeline functioning — phase floor met ({entries_pw}/{floor} "
            f"entries/week); volume gate not yet met ({episodes} ep / {weeks} wk)."
        )
    else:
        headline = (
            f"N200 pipeline functioning — phase below floor "
            f"({entries_pw}/{floor} entries/week); volume "
            f"{'met' if volume_met else 'not met'}."
        )

    pipeline_detail_parts = [
        ops_check["detail"],
        freshness["detail"],
    ]
    if functioning:
        pipeline_detail_parts.insert(0, "Observe refresh path looks alive.")
    else:
        pipeline_detail_parts.insert(0, "Pipeline not fully healthy.")

    return {
        "schema_version": PIPELINE_HEALTH_SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "observe_only": True,
        "influences_live": False,
        "not_alpha_signal": True,
        "not_capital_ready": True,
        "registration_id": (payload or {}).get("registration_id") or REGISTRATION_ID,
        "deferred_id": (payload or {}).get("deferred_id") or DEFERRED_ID,
        "headline": headline,
        "disclaimer": PIPELINE_HEALTH_DISCLAIMER,
        "store_present": present,
        "store_generated_at": store_as_of.isoformat() if store_as_of else None,
        "phase": {
            "entries_per_week": entries_pw,
            "floor": floor,
            "floor_met": floor_met,
        },
        "volume_gate": {
            "met": volume_met,
            "episodes": episodes,
            "weeks": weeks,
            "min_episodes": volume.get("min_episodes", VOLUME_MIN_EPISODES),
            "min_weeks": volume.get("min_weeks", VOLUME_MIN_WEEKS),
        },
        "freshness": freshness,
        "pipeline": {
            "functioning": functioning,
            "ops_check_ok": bool(ops_check["ops_check_ok"]),
            "ops_finding_present": bool(ops_check["ops_finding_present"]),
            "ops_run_at": ops_run_at.isoformat() if ops_run_at else None,
            "detail": " ".join(pipeline_detail_parts),
        },
        "ops_doc": str(DEFAULT_OPS_DOC),
    }
