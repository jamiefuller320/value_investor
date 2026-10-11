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
from value_investor.paper_fund import BUY_SIGNALS

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/n200_tech_timing_observe.json")
DEFAULT_REGISTRATION_PATH = Path("docs/data/n200_tech_timing_registration.json")
DEFAULT_OPS_DOC = Path("docs/ops/n200-tech-timing-observe.md")

REGISTRATION_ID = "strand-b-plain-value-tech-timing-v0"
DEFERRED_ID = "N200"
IDENTITY_ID = "raw_buy_tier"
SUCCESS_METRIC_ID = "smooth_ret_cohort_median"
SCHEMA_VERSION = 1

BRACKET_OFFSETS_DAYS = (-14, 0, 14)
TRADE_COST_PCT = 0.03
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
    trade_cost_pct: float = TRADE_COST_PCT,
) -> float:
    """Round-trip cost-aware simple return."""
    raw = exit_price / entry_price - 1.0
    return raw - 2.0 * trade_cost_pct


@dataclass(frozen=True)
class N200Config:
    bracket_offsets_days: tuple[int, ...] = BRACKET_OFFSETS_DAYS
    trade_cost_pct: float = TRADE_COST_PCT
    volume_min_episodes: int = VOLUME_MIN_EPISODES
    volume_min_weeks: int = VOLUME_MIN_WEEKS
    phase_entries_per_week_floor: float = PHASE_ENTRIES_PER_WEEK_FLOOR
    max_episodes: int = MAX_EPISODES


def build_registration_payload(*, sealed_at: str | None = None) -> dict[str, Any]:
    """Canonical seal record written to ``n200_tech_timing_registration.json``."""
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
            "primary": "absolute_smoothed_return",
            "control_excess": "report_only",
        },
        "o6_phase_floor": {
            "entries_per_week_target": PHASE_ENTRIES_PER_WEEK_FLOOR,
            "note": "illustrative sealed mechanism floor (5–10 band)",
        },
        "brackets": {
            "entry_offsets_days": list(BRACKET_OFFSETS_DAYS),
            "exit_offsets_days": list(BRACKET_OFFSETS_DAYS),
        },
        "trade_cost_pct": TRADE_COST_PCT,
        "constraints": [
            "observe_only",
            "no_live_strand_a_writes",
            "no_decision_review_apply",
            "no_new_screen_extras",
            "f9_eligibility",
            "f8_fail_closed",
            "per_lever_scoreboard_separate_from_path_pnl",
            "logged_change_markers",
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
    episodes: list[dict[str, Any]] = []
    skipped_ineligible = 0
    cell_returns: dict[str, list[float]] = {_cell_key(e, x): [] for e in offsets for x in offsets}
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
                    ret = episode_return(p_entry, p_exit, trade_cost_pct=cfg.trade_cost_pct)
                    episode_cells[_cell_key(e_off, x_off)] = round(ret, 6)
                    cell_returns[_cell_key(e_off, x_off)].append(ret)
                # Entry lever: control exit (0)
                x0 = _nearest_snapshot_index(snapshots, exit_idx, 0)
                if x0 is not None and x0 > e_i:
                    p_x = _price_at(snapshots, x0, ticker)
                    if p_x is not None:
                        entry_lever_returns[e_off].append(
                            episode_return(p_entry, p_x, trade_cost_pct=cfg.trade_cost_pct)
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
                        episode_return(p_e0, p_x, trade_cost_pct=cfg.trade_cost_pct)
                    )
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
    markers = list(prior_markers or [])
    if not any(m.get("marker_id") == seal_marker["marker_id"] for m in markers):
        markers.insert(0, seal_marker)

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
            "primary": "absolute_smoothed_return",
            "success_metric_id": SUCCESS_METRIC_ID,
            "control_cell": control_key,
            "control_smooth_ret_cohort_median": absolute_primary,
            "diagnostic_best_cell": best_cell,
            "diagnostic_best_median": best_med,
            "note": (
                "Control absolute primary is sealed path metric. "
                "Best-cell is diagnostic only — not a promote signal (F8)."
            ),
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
    entries_pw = phase.get("entries_per_week")
    findings.append(
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"{REGISTRATION_ID}: {n} completed episodes over {weeks} weeks; "
                f"entries/week={entries_pw}; control {SUCCESS_METRIC_ID}={control_med}. "
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
    lines = [
        f"N200 {payload.get('registration_id')} (observe-only)",
        f"  episodes={payload.get('completed_entry_episodes')} "
        f"weeks={payload.get('calendar_weeks_spanned')} "
        f"entries/week={phase.get('entries_per_week')}",
        f"  control {SUCCESS_METRIC_ID}={path.get('control_smooth_ret_cohort_median')}",
        f"  volume_gate_met={volume.get('met')} phase_floor_met={phase.get('floor_met')}",
        f"  diagnostic_best_cell={path.get('diagnostic_best_cell')}",
    ]
    return "\n".join(lines) + "\n"
