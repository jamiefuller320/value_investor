"""N210 sealed observe-only stub: fixed-stake AI/filter judgment (B3).

registration_id: ``strand-e-ai-judgment-fixed-stake-v0``

B3 cold-start judgment instrument. Primary scoreboard = fair-cost episode %
(cohort median). Episode walker lands in a follow-up; this module registers the
seal, persists an automation-runnable observe store, and emits ops findings.

Observe-only — never writes strand A books, knobs, or ``decision-review --apply``.
Does not steal P1 from holdings / N200 (launch-queue waiter).

See ``docs/ops/n210-ai-judgment-observe.md``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.market_trading_costs import (
    LEGACY_STRESS_TRADE_COST_PCT,
    LIVE_PAPER_MARKET_ID,
    costs_for_market,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/n210_ai_judgment_observe.json")
DEFAULT_REGISTRATION_PATH = Path("docs/data/n210_ai_judgment_registration.json")
DEFAULT_OPS_DOC = Path("docs/ops/n210-ai-judgment-observe.md")

REGISTRATION_ID = "strand-e-ai-judgment-fixed-stake-v0"
DEFERRED_ID = "N210"
IDENTITY_ID = "ai_filter_accumulate_min_conviction_0_6"
SUCCESS_METRIC_ID = "smooth_ret_cohort_median"
SCHEMA_VERSION = 1
SEAL_MARKER_ID = "n210-seal-v0"
PIPELINE_STATUS = "stub_awaiting_episode_walker"

VOLUME_MIN_EPISODES = 48
VOLUME_MIN_WEEKS = 8
PHASE_ENTRIES_PER_WEEK_FLOOR = 8.0
FIXED_STAKE_UNITS = 100.0

FINDING_TITLE = "N210 AI-judgment observe refreshed"
STORE_FAILED_TITLE = "N210 AI-judgment observe failed"
VOLUME_GATE_TITLE = "N210 volume gate ready for review"
STUB_TITLE = "N210 AI-judgment observe registered (awaiting episode pipeline)"

LEARNING_QUESTION = (
    "On threshold-eligible FTSE names, does the AI/filter identity "
    "(adjusted_signal + research_verdict=accumulate, min_conviction=0.6) "
    "improve fair-cost episode % vs an unfiltered buy-tier draw of the same "
    "eligible set, sized as a fixed-stake mechanical test?"
)


def build_registration_payload(*, sealed_at: str | None = None) -> dict[str, Any]:
    fair = costs_for_market(LIVE_PAPER_MARKET_ID)
    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "status": "sealed_observe_only",
        "sealed_at": sealed_at or "2026-10-15",
        "observe_only": True,
        "influences_live": False,
        "b3_epoch": True,
        "pipeline_status": PIPELINE_STATUS,
        "learning_question": LEARNING_QUESTION,
        "identity_id": IDENTITY_ID,
        "success_metric_id": SUCCESS_METRIC_ID,
        "o2_identity": IDENTITY_ID,
        "entry_filters": {
            "use_adjusted_signal": True,
            "require_research_accumulate": True,
            "min_conviction": 0.6,
            "source": "ai_judgment_fair_gate_identity",
            "note": (
                "Reuse existing AI/filter gates (F4) — no new screen extras. "
                "Known limit: gate may not bind at 0.6 (same as parent; N189)."
            ),
        },
        "sizing": {
            "mode": "fixed_stake",
            "stake_units": FIXED_STAKE_UNITS,
            "stake_currency": "local_market",
            "cash_fund_nav": "parked",
            "scoreboard_unit": "fair_cost_episode_pct",
            "dca": "not_on_v0",
        },
        "universe": {
            "markets": "ftse350",
            "returns": "market_native",
            "fx_conversion": False,
        },
        "o3_volume_gate": {
            "completed_entry_episodes_min": VOLUME_MIN_EPISODES,
            "calendar_weeks_spanned_min": VOLUME_MIN_WEEKS,
            "rule": "both_required",
        },
        "o4_smoother": SUCCESS_METRIC_ID,
        "o5_primacy": {
            "primary": "absolute_smoothed_return_fair_costs",
            "unfiltered_buy_tier_excess": "report_only",
            "stress_cost": "report_only",
            "matched30_fund_nav": "separate_instrument",
        },
        "o6_phase_floor": {
            "entries_per_week_target": PHASE_ENTRIES_PER_WEEK_FLOOR,
            "note": "mechanism floor only — not alpha",
        },
        "cost_basis": {
            "primary": "fair_market_table",
            "market_id": LIVE_PAPER_MARKET_ID,
            "buy_cost_pct": fair.buy_pct,
            "sell_cost_pct": fair.sell_pct,
            "round_trip_pct": fair.buy_pct + fair.sell_pct,
            "trade_cost_pct_symmetric_proxy": (fair.buy_pct + fair.sell_pct) / 2.0,
            "source": "t212_invest_fair_v1",
            "stress_trade_cost_pct": LEGACY_STRESS_TRADE_COST_PCT,
            "stress_role": "report_only",
        },
        "trade_cost_pct": (fair.buy_pct + fair.sell_pct) / 2.0,
        "buy_cost_pct": fair.buy_pct,
        "sell_cost_pct": fair.sell_pct,
        "stress_trade_cost_pct": LEGACY_STRESS_TRADE_COST_PCT,
        "launch_queue": {
            "enqueued": True,
            "rank_note": (
                "B3 judgment observe — Data deepen / shortlist demand waits behind "
                "holdings and already-running sealed units (N200). Do not steal P1."
            ),
            "doc": "docs/ops/data-pillar-priorities.md",
        },
        "constraints": [
            "observe_only",
            "no_live_strand_a_writes",
            "no_decision_review_apply",
            "no_new_screen_extras",
            "f8_fail_closed",
            "fixed_stake_not_fund_nav",
            "fair_costs_primary",
            "stress_cost_report_only",
            "o3_alone_first",
            "b3_dual_shadow",
            "logged_change_markers",
        ],
        "ops_doc": str(DEFAULT_OPS_DOC),
        "observe_store": str(DEFAULT_STORE_PATH),
        "matched_fund_twin_track": "ai_judgment_matched30_fair",
        "matched_control_twin_track": "buy_tier_matched30_fair",
    }


def _empty_path_scoreboard() -> dict[str, Any]:
    return {
        "primary": "absolute_smoothed_return_fair_costs",
        "scoreboard_unit": "fair_cost_episode_pct",
        "smooth_ret_cohort_median": None,
        "completed_entry_episodes": 0,
        "companions": {
            "volume_toward_gate": f"0/{VOLUME_MIN_EPISODES}",
            "calendar_weeks_spanned": 0,
            "weeks_toward_gate": f"0/{VOLUME_MIN_WEEKS}",
            "years_to_detect": None,
            "ci90": None,
            "stress_cost": "report_only",
        },
        "note": (
            "Stub store — episode walker not yet wired. Do not read null median "
            "as evidence. Judgment primary remains fair-cost episode % once volume exists."
        ),
    }


def build_n210_observe(*, now: datetime | None = None) -> dict[str, Any]:
    when = now or datetime.now(UTC)
    registration = build_registration_payload()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": when.isoformat(),
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "status": "sealed_observe_only",
        "observe_only": True,
        "influences_live": False,
        "independent_of_fund_nav": True,
        "b3_epoch": True,
        "pipeline_status": PIPELINE_STATUS,
        "learning_question": LEARNING_QUESTION,
        "identity_id": IDENTITY_ID,
        "success_metric_id": SUCCESS_METRIC_ID,
        "sizing": registration["sizing"],
        "completed_entry_episodes": 0,
        "calendar_weeks_spanned": 0,
        "volume_gate": {
            "min_episodes": VOLUME_MIN_EPISODES,
            "min_weeks": VOLUME_MIN_WEEKS,
            "met": False,
            "rule": "both_required",
        },
        "phase": {
            "entries_per_week": 0.0,
            "floor": PHASE_ENTRIES_PER_WEEK_FLOOR,
            "floor_met": False,
        },
        "path_scoreboard": _empty_path_scoreboard(),
        "launch_queue": registration["launch_queue"],
        "change_markers": [
            {
                "id": SEAL_MARKER_ID,
                "at": registration["sealed_at"],
                "summary": (
                    "B3 lock: seal fixed-stake AI/filter judgment observe as "
                    "evidentiary primary for filter LQ (shadow until volume gates)."
                ),
            }
        ],
        "soft_gaps": [
            "Episode walker not yet wired — refresh persists registration + empty "
            "scoreboard so automation can run without half-wired capital.",
            "Do not crown assessment_model primary from this stub (F8).",
        ],
    }


def refresh_n210_ai_judgment_observe(
    *,
    output_dir: Path | None = None,
    store_path: Path | None = None,
    registration_path: Path | None = None,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    del output_dir  # reserved for walker; stub does not read archives yet
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    reg_path = (
        Path(registration_path) if registration_path is not None else DEFAULT_REGISTRATION_PATH
    )
    payload = build_n210_observe(now=now)
    registration = build_registration_payload()
    if persist:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(registration, indent=2) + "\n", encoding="utf-8")
        payload["store_path"] = str(store)
        payload["registration_path"] = str(reg_path)
    return payload


def ops_findings_from_n210_observe(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"N210 ({REGISTRATION_ID}) refreshed; pipeline={payload.get('pipeline_status')}; "
                f"episodes={payload.get('completed_entry_episodes', 0)}; "
                f"volume_gate_met={bool((payload.get('volume_gate') or {}).get('met'))}. "
                "Observe-only; influences_live=false."
            ),
            "auto_fixable": False,
        }
    ]
    if payload.get("pipeline_status") == PIPELINE_STATUS:
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": STUB_TITLE,
                "summary": (
                    "B3 judgment observe is sealed as a registration stub. Episode walker "
                    "not yet producing marks — do not promote or apply knobs (F8). "
                    "Fair-cost episode % is the judgment primary once volume exists."
                ),
                "auto_fixable": False,
            }
        )
    gate = payload.get("volume_gate") or {}
    if gate.get("met"):
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": VOLUME_GATE_TITLE,
                "summary": (
                    f"N210 volume gate met (≥{VOLUME_MIN_EPISODES} episodes and "
                    f"≥{VOLUME_MIN_WEEKS} weeks). Human review only — no auto-promote (F8)."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def format_n210_observe_text(payload: dict[str, Any]) -> str:
    gate = payload.get("volume_gate") or {}
    lines = [
        f"N210 AI-judgment observe ({payload.get('registration_id')})",
        f"  status: {payload.get('status')}  pipeline: {payload.get('pipeline_status')}",
        f"  influences_live: {payload.get('influences_live')}",
        f"  episodes: {payload.get('completed_entry_episodes')}  "
        f"weeks: {payload.get('calendar_weeks_spanned')}",
        f"  volume_gate: met={gate.get('met')} "
        f"(need ≥{gate.get('min_episodes')}/{gate.get('min_weeks')}w)",
        f"  LQ: {payload.get('learning_question')}",
    ]
    return "\n".join(lines) + "\n"
