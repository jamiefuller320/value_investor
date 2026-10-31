"""N206 sealed observe-only: patient plain earnings-yield identity.

registration_id: ``strand-d-plain-ey-identity-v0``

Promotes N201's report-only ``patient_plain_ey_hold_v0`` baseline to a
first-class observe strand. Walks the same FTSE history and admitted library
screen panels N201 already uses. Entry is plain EY top-30% local and
``financial_health`` pass. No momentum filter and no price-bar fetch.

Fixed 100 local-currency stake. Primary scoreboard is fair-cost episode %
cohort median. Stress 3%/side and cash excess are report-only.

Observe-only — ``influences_live`` is false. Alone-first (O3). Does not write
strand A books, knobs, ``max_positions``, ``sector_cap``, or
``decision-review --apply``. Does not promote N200, N201, or N210 and does not
crown an assessment primary.

See ``docs/ops/n206-plain-ey-observe.md``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.backtest import RunSnapshot, load_run_snapshots
from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.n201_value_mom_observe import (
    DEFAULT_LIBRARY_POLICY_PATH,
    DEFAULT_MARKET_ID,
    EY_TOP_SHARE,
    FIXED_STAKE_UNITS,
    HOLD_TRADING_DAYS,
    PHASE_ENTRIES_PER_WEEK_FLOOR,
    STRESS_TRADE_COST_PCT,
    VOLUME_MIN_EPISODES,
    VOLUME_MIN_WEEKS,
    N201Config,
    _admitted_markets,
    _earnings_yield,
    _entry_filter_state,
    _find_exit_index,
    _latest_quote,
    _median_or_none,
    _parse_dt,
    _plain_ey_top_share,
    _price_at,
    _row_market_id,
    _safe_read_json,
    _snapshot_rows,
    _utc_now,
    enrich_snapshots_from_archives,
    episode_return,
    fixed_stake_pnl,
    load_library_market_snapshots,
    row_f9_eligible,
    trading_days_between,
)
from value_investor.sealed_lifecycle import with_fair_cost_open_mark
from value_investor.volume_interestingness import (
    N206_INTERESTINGNESS_TITLE,
    VOLUME_THICKNESS_SUMMARY_SUFFIX,
    evaluate_n206_interestingness,
    interestingness_finding,
)

DEFAULT_OUTPUT_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/n206_plain_ey_observe.json")
DEFAULT_REGISTRATION_PATH = Path("docs/data/n206_plain_ey_registration.json")
DEFAULT_OPS_STATUS_PATH = Path("docs/data/ops_status.json")
DEFAULT_OPS_DOC = Path("docs/ops/n206-plain-ey-observe.md")

REGISTRATION_ID = "strand-d-plain-ey-identity-v0"
DEFERRED_ID = "N206"
IDENTITY_ID = "plain_ey_top30_financial_health"
BASELINE_ID = "patient_plain_ey_hold_v0"
SUCCESS_METRIC_ID = "smooth_ret_cohort_median"
SCHEMA_VERSION = 1
PIPELINE_HEALTH_SCHEMA_VERSION = 1
SEAL_MARKER_ID = "n206-seal-v0"
ELIGIBILITY_MODE = "entry_fields_required_f9_or_pass"
MAX_EPISODES = 500
DEFAULT_STALE_AFTER_HOURS = 30.0
DEFAULT_STORE_LAG_WARN_HOURS = 2.0

LEARNING_QUESTION = (
    "Across live and admitted markets, does a patient plain earnings-yield "
    "top-30% local book (financial_health pass, no momentum filter), sized as "
    "a fixed 100 local-currency stake, earn a positive fair-cost episode "
    "cohort median?"
)

FINDING_TITLE = "N206 plain-EY observe refreshed"
STORE_FAILED_TITLE = "N206 plain-EY observe failed"
VOLUME_GATE_TITLE = "N206 volume gate ready for review"
INTERESTINGNESS_TITLE = N206_INTERESTINGNESS_TITLE

PIPELINE_HEALTH_DISCLAIMER = (
    "Phase floor and sample-thickness volume gate measure factory mechanism "
    "throughput — not alpha or capital readiness (F8). Alone-path "
    "interestingness is separate Push/checklist heat. Fixed-stake episode % "
    "is independent of fund NAV. Alone-first (O3). Observe-only; "
    "influences_live is false. Not an assessment primary."
)


def _hours_since(then: datetime | None, *, now: datetime) -> float | None:
    if then is None:
        return None
    return round((now - then).total_seconds() / 3600.0, 2)


def _weeks_spanned(snapshots: list[RunSnapshot]) -> int:
    if len(snapshots) >= 2:
        start = snapshots[0].run_at
        end = snapshots[-1].run_at
        from value_investor.n201_value_mom_observe import _days_between

        return max(1, _days_between(start, end) // 7)
    if snapshots:
        return 1
    return 0


def build_registration_payload(*, sealed_at: str | None = None) -> dict[str, Any]:
    """Canonical seal record written to ``n206_plain_ey_registration.json``."""
    cfg = N201Config(fetch_momentum_prices=False)
    cost = cfg.primary_cost_fields()
    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "status": "sealed_observe_only",
        "sealed_at": sealed_at or "2026-10-16",
        "observe_only": True,
        "influences_live": False,
        "alone_first": True,
        "identity_id": IDENTITY_ID,
        "baseline_promoted_from": BASELINE_ID,
        "success_metric_id": SUCCESS_METRIC_ID,
        "learning_question": LEARNING_QUESTION,
        "entry_filters": {
            "plain_ey_top_share_local": EY_TOP_SHARE,
            "momentum_filter": False,
            "financial_health": "pass",
            "all_required": True,
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
            "markets": "ftse350_plus_admitted",
            "returns": "market_native",
            "fx_conversion": False,
            "panels": "existing_ftse_history_and_library_screen",
        },
        "buy_trigger": "next_eligible_weekly_refresh_after_filters_clear",
        "exit": {
            "hold_trading_days": HOLD_TRADING_DAYS,
            "or_identity_quality_break": True,
            "whichever_first": True,
            "archive_trading_day_proxy": "busday_with_market_holidays",
        },
        "o3_volume_gate": {
            "completed_entry_episodes_min": VOLUME_MIN_EPISODES,
            "calendar_weeks_spanned_min": VOLUME_MIN_WEEKS,
            "rule": "both_required",
            "alone_first": True,
            "pairwise": False,
        },
        "o4_smoother": SUCCESS_METRIC_ID,
        "o5_primacy": {
            "primary": "absolute_smoothed_return_fair_costs",
            "cash_excess": "report_only",
            "stress_cost": "report_only",
            "market_index": "omitted_no_index_series_on_panels",
        },
        "o6_phase_floor": {
            "entries_per_week_target": PHASE_ENTRIES_PER_WEEK_FLOOR,
            "note": "mechanism floor only — not alpha",
        },
        "cost_basis": cost,
        "trade_cost_pct": cost["trade_cost_pct_symmetric_proxy"],
        "buy_cost_pct": cost["buy_cost_pct"],
        "sell_cost_pct": cost["sell_cost_pct"],
        "stress_trade_cost_pct": cost["stress_trade_cost_pct"],
        "eligibility_mode": ELIGIBILITY_MODE,
        "panels_used": [
            "docs/data/history run snapshots (FTSE)",
            "library signals_*.csv earnings yield / trailing P/E",
            "library screen/history models_*.json.gz financial_health",
        ],
        "filing_ingest_sprint": False,
        "momentum_price_fetch": False,
        "launch_queue": {
            "enqueued": True,
            "data_deepen_requested": False,
            "rank_note": (
                "Scores panels the repo already has. No filing ingest sprint "
                "ahead of holdings or N200. Not a deepen-queue head."
            ),
            "doc": "docs/ops/data-pillar-priorities.md",
        },
        "does_not": [
            "widen_max_positions",
            "widen_sector_cap",
            "promote_n200",
            "promote_n201",
            "promote_n210",
            "crown_assessment_primary",
            "pairwise_compete",
            "fourth_equal_ingest_sprint",
            "live_llm_influence",
        ],
        "shrink_policy": "new_twins_failure_mode_ladder_not_mid_flight_prune",
        "constraints": [
            "observe_only",
            "influences_live_false",
            "alone_first",
            "no_live_strand_a_writes",
            "no_decision_review_apply",
            "no_new_screen_extras",
            "no_momentum_price_fetch",
            "no_filing_ingest_sprint",
            "f9_eligibility",
            "f8_fail_closed",
            "fixed_stake_not_fund_nav",
            "fair_costs_primary",
            "stress_cost_report_only",
            "cash_excess_report_only",
            "no_pairwise",
            "logged_change_markers",
            "no_fx_conversion",
        ],
        "ops_doc": str(DEFAULT_OPS_DOC),
        "observe_store": str(DEFAULT_STORE_PATH),
    }


def _sealed_lifecycle_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from value_investor.sealed_lifecycle import slim_lifecycle_episodes

    return slim_lifecycle_episodes(episodes)


def score_plain_ey_hold(
    snapshots: list[RunSnapshot],
    *,
    cfg: N201Config | None = None,
    generated_at: str | None = None,
    prior_markers: list[dict[str, Any]] | None = None,
    panel_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score patient plain-EY episodes. No momentum and no external price fetch."""
    cfg = cfg or N201Config(fetch_momentum_prices=False)
    cost_fields = cfg.primary_cost_fields()
    stress_pct = float(cfg.stress_trade_cost_pct)
    row_maps = [_snapshot_rows(s) for s in snapshots]
    ey_top_by_snap = [_plain_ey_top_share(rm, top_share=cfg.ey_top_share) for rm in row_maps]

    strategy_returns: list[float] = []
    stress_returns: list[float] = []
    episodes: list[dict[str, Any]] = []
    open_lifecycle: list[dict[str, Any]] = []
    skipped_missing_fields = 0
    skipped_ineligible = 0
    skipped_filters = 0
    prev_clear: set[str] = set()

    for i, snap in enumerate(snapshots):
        row_map = row_maps[i]
        ey_top = ey_top_by_snap[i]
        clear: set[str] = set()
        for ticker, row in row_map.items():
            ok, _note, _detail = _entry_filter_state(
                row,
                in_ey_top=ticker in ey_top,
                momentum=None,
                require_momentum=False,
            )
            if ok:
                clear.add(ticker)

        for ticker in sorted(clear - prev_clear):
            row = row_map[ticker]
            eligible, elig_note = row_f9_eligible(row)
            if not eligible:
                skipped_ineligible += 1
                continue
            ok, note, detail = _entry_filter_state(
                row,
                in_ey_top=True,
                momentum=None,
                require_momentum=False,
            )
            if not ok:
                if not note.startswith("soft_gap_missing"):
                    skipped_filters += 1
                continue

            mid = _row_market_id(row, cfg.market_id)
            exit_idx, exit_reason = _find_exit_index(
                snapshots,
                i,
                ticker,
                hold_trading_days=cfg.hold_trading_days,
                ey_top_by_snap=ey_top_by_snap,
                market_id=mid,
                sessions=None,
            )
            buy_pct, sell_pct = cfg.primary_buy_sell(mid)
            if exit_idx is None:
                # Display-only open mark from real archive quotes; not path primary.
                p_entry = _price_at(snapshots, i, ticker)
                p_mark, mark_at = _latest_quote(snapshots, ticker, from_idx=i)
                open_lifecycle.append(
                    with_fair_cost_open_mark(
                        {
                            "ticker": ticker,
                            "market_id": mid,
                            "entry_run_at": snap.run_at,
                            "status": "open",
                            "influences_live": False,
                        },
                        entry_price=p_entry,
                        mark_price=p_mark,
                        buy_cost_pct=buy_pct,
                        sell_cost_pct=sell_pct,
                        mark_run_at=mark_at,
                    )
                )
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
            strategy_returns.append(stake["return_pct"])
            stress_ret = episode_return(p_entry, p_exit, trade_cost_pct=stress_pct)
            stress_returns.append(stress_ret)
            episodes.append(
                {
                    "ticker": ticker,
                    "market_id": mid,
                    "entry_run_at": snap.run_at,
                    "exit_run_at": snapshots[exit_idx].run_at,
                    "hold_trading_days": trading_days_between(
                        snap.run_at,
                        snapshots[exit_idx].run_at,
                        market_id=mid,
                    ),
                    "exit_reason": exit_reason,
                    "eligibility": elig_note,
                    "entry_detail": detail,
                    "fixed_stake_units": cfg.fixed_stake_units,
                    "return_pct": round(stake["return_pct"], 6),
                    "pnl_local_report_only": round(stake["pnl_local"], 6),
                    "return_pct_stress_report_only": round(stress_ret, 6),
                    "scoreboard_unit": "fair_cost_episode_pct",
                    "independent_of_fund_nav": True,
                }
            )
            if len(episodes) >= cfg.max_episodes:
                break

        for ticker, row in row_map.items():
            if ticker in clear or ticker in prev_clear:
                continue
            _ok, note, _detail = _entry_filter_state(
                row,
                in_ey_top=ticker in ey_top,
                momentum=None,
                require_momentum=False,
            )
            if note.startswith("soft_gap_missing") and _earnings_yield(row) is not None:
                skipped_missing_fields += 1

        prev_clear = clear
        if len(episodes) >= cfg.max_episodes:
            break

    return _payload_from_returns(
        strategy_returns=strategy_returns,
        stress_returns=stress_returns,
        episodes=episodes,
        snapshots=snapshots,
        cfg=cfg,
        cost_fields=cost_fields,
        stress_pct=stress_pct,
        skipped_missing_fields=skipped_missing_fields,
        skipped_ineligible=skipped_ineligible,
        skipped_filters=skipped_filters,
        open_lifecycle=open_lifecycle,
        generated_at=generated_at,
        prior_markers=prior_markers,
        panel_coverage=panel_coverage,
    )


def _payload_from_returns(
    *,
    strategy_returns: list[float],
    stress_returns: list[float],
    episodes: list[dict[str, Any]],
    snapshots: list[RunSnapshot],
    cfg: N201Config,
    cost_fields: dict[str, Any],
    stress_pct: float,
    skipped_missing_fields: int,
    skipped_ineligible: int,
    skipped_filters: int,
    generated_at: str | None,
    prior_markers: list[dict[str, Any]] | None,
    panel_coverage: dict[str, Any] | None,
    snapshot_count: int | None = None,
    weeks: int | None = None,
    open_lifecycle: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    absolute_primary = _median_or_none(strategy_returns)
    stress_median = _median_or_none(stress_returns)
    cash_excess = None if absolute_primary is None else round(absolute_primary - 0.0, 6)
    if weeks is None:
        weeks = _weeks_spanned(snapshots)
    completed = len(strategy_returns)
    entries_per_week = round(completed / weeks, 3) if weeks else None
    volume_gate_met = completed >= cfg.volume_min_episodes and weeks >= cfg.volume_min_weeks
    phase_ok = entries_per_week is not None and entries_per_week >= cfg.phase_entries_per_week_floor
    seal_marker = {
        "marker_id": SEAL_MARKER_ID,
        "at": "2026-10-16T00:00:00+00:00",
        "lever": "identity",
        "before_id": BASELINE_ID,
        "after_id": REGISTRATION_ID,
        "registration_id": REGISTRATION_ID,
        "reason": (
            "Initial seal: patient plain EY top-30% local + financial_health "
            "pass; no momentum filter; fixed 100 local stake; 63d or "
            "identity/quality-break exit; fair-cost smooth_ret_cohort_median "
            "primary. Promoted from N201 patient-hold baseline. Alone-first. "
            "influences_live false."
        ),
        "eligible_set_ref": ELIGIBILITY_MODE,
        "success_metric_id": SUCCESS_METRIC_ID,
        "applies_to": "observe_only",
    }
    markers = list(prior_markers or [])
    if not any(m.get("marker_id") == seal_marker["marker_id"] for m in markers):
        markers.insert(0, seal_marker)
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "generated_at": generated_at or _utc_now(),
        "observe_only": True,
        "influences_live": False,
        "alone_first": True,
        "not_assessment_primary": True,
        "identity_id": IDENTITY_ID,
        "baseline_promoted_from": BASELINE_ID,
        "success_metric_id": SUCCESS_METRIC_ID,
        "learning_question": LEARNING_QUESTION,
        "eligibility_mode": ELIGIBILITY_MODE,
        "momentum_filter": False,
        "momentum_price_fetch": False,
        "filing_ingest_sprint": False,
        "sizing": {
            "mode": "fixed_stake",
            "stake_units": cfg.fixed_stake_units,
            "cash_fund_nav": "parked",
            "scoreboard_unit": "fair_cost_episode_pct",
            "independent_of_fund_nav": True,
        },
        "cost_basis": cost_fields,
        "snapshot_count": len(snapshots) if snapshot_count is None else snapshot_count,
        "completed_entry_episodes": completed,
        "skipped_missing_entry_fields": skipped_missing_fields,
        "skipped_ineligible": skipped_ineligible,
        "skipped_filters": skipped_filters,
        "calendar_weeks_spanned": weeks,
        "hold_trading_day_mode": "busday_with_market_holidays",
        "volume_gate": {
            "min_episodes": cfg.volume_min_episodes,
            "min_weeks": cfg.volume_min_weeks,
            "met": volume_gate_met,
            "role": "sample_thickness_pipeline_badge",
        },
        "phase": {
            "entries_per_week": entries_per_week,
            "floor": cfg.phase_entries_per_week_floor,
            "floor_met": phase_ok,
        },
        "path_scoreboard": {
            "primary": "absolute_smoothed_return_fair_costs",
            "success_metric_id": SUCCESS_METRIC_ID,
            "smooth_ret_cohort_median": absolute_primary,
            "smooth_ret_cohort_median_stress_report_only": stress_median,
            "cash_excess_report_only": cash_excess,
            "market_index_diagnostic": "omitted_no_index_series_on_panels",
            "n": completed,
            "independent_of_fund_nav": True,
            "alone_first": True,
            "note": (
                "Primary is fair-cost episode % cohort median on fixed-stake "
                "patient plain-EY entries. Fund NAV / cash drag not used. "
                "Cash excess (median minus 0) and stress 3%/side are "
                "report-only. No pairwise versus N200, N201, or N210 (O3)."
            ),
        },
        "stress_scoreboard_report_only": {
            "trade_cost_pct_per_side": stress_pct,
            "smooth_ret_cohort_median": stress_median,
            "n": len(stress_returns),
            "role": "report_only",
        },
        "launch_queue": {
            "enqueued": True,
            "data_deepen_requested": False,
            "rank_note": ("Existing panels only. No filing ingest ahead of holdings or N200."),
        },
        "change_markers": markers,
        "episodes_sample": episodes[:25],
        "lifecycle_episodes": _sealed_lifecycle_rows([*episodes, *(open_lifecycle or [])]),
        "ops_doc": str(DEFAULT_OPS_DOC),
        "_return_pcts": [round(v, 6) for v in strategy_returns],
        "_stress_return_pcts": [round(v, 6) for v in stress_returns],
    }
    if panel_coverage is not None:
        out["panel_coverage"] = panel_coverage
    out["interestingness_gate"] = evaluate_n206_interestingness(out)
    return out


def _strip_private(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.pop("_return_pcts", None)
    out.pop("_stress_return_pcts", None)
    return out


def _merge_payloads(
    payloads: list[dict[str, Any]],
    *,
    generated_at: str | None,
    prior_markers: list[dict[str, Any]],
    panel_coverage: dict[str, Any],
    cfg: N201Config,
) -> dict[str, Any]:
    if not payloads:
        return _strip_private(
            score_plain_ey_hold(
                [],
                cfg=cfg,
                generated_at=generated_at,
                prior_markers=prior_markers,
                panel_coverage=panel_coverage,
            )
        )
    if len(payloads) == 1:
        out = _strip_private(payloads[0])
        out["panel_coverage"] = panel_coverage
        return out

    strategy: list[float] = []
    stress: list[float] = []
    episodes: list[dict[str, Any]] = []
    skipped_missing = skipped_ineligible = skipped_filters = snapshot_count = 0
    markers = list(prior_markers)
    for payload in payloads:
        snapshot_count += int(payload.get("snapshot_count") or 0)
        skipped_missing += int(payload.get("skipped_missing_entry_fields") or 0)
        skipped_ineligible += int(payload.get("skipped_ineligible") or 0)
        skipped_filters += int(payload.get("skipped_filters") or 0)
        strategy.extend(float(v) for v in payload.get("_return_pcts") or [])
        stress.extend(float(v) for v in payload.get("_stress_return_pcts") or [])
        for ep in payload.get("episodes_sample") or []:
            if isinstance(ep, dict):
                episodes.append(ep)
        for marker in payload.get("change_markers") or []:
            if isinstance(marker, dict) and marker.get("marker_id") not in {
                m.get("marker_id") for m in markers
            }:
                markers.append(marker)
    weeks = max(int(p.get("calendar_weeks_spanned") or 0) for p in payloads)
    merged = _payload_from_returns(
        strategy_returns=strategy,
        stress_returns=stress,
        episodes=episodes,
        snapshots=[],
        cfg=cfg,
        cost_fields=cfg.primary_cost_fields(),
        stress_pct=float(cfg.stress_trade_cost_pct),
        skipped_missing_fields=skipped_missing,
        skipped_ineligible=skipped_ineligible,
        skipped_filters=skipped_filters,
        generated_at=generated_at,
        prior_markers=markers,
        panel_coverage=panel_coverage,
        snapshot_count=snapshot_count,
        weeks=weeks,
    )
    # episodes_sample was rebuilt from concatenated samples; cap again.
    merged["episodes_sample"] = episodes[:25]
    lifecycle_episodes: list[dict[str, Any]] = []
    for payload in payloads:
        for row in payload.get("lifecycle_episodes") or []:
            if isinstance(row, dict):
                lifecycle_episodes.append(row)
    merged["lifecycle_episodes"] = lifecycle_episodes
    merged["markets_scored"] = [
        str((p.get("cost_basis") or {}).get("market_id") or "") for p in payloads
    ]
    return _strip_private(merged)


def refresh_n206_plain_ey_observe(
    *,
    output_dir: Path | None = None,
    store_path: Path | None = None,
    registration_path: Path | None = None,
    persist: bool = True,
    cfg: N201Config | None = None,
    generated_at: str | None = None,
    library_root: Path | None = None,
    library_policy_path: Path | None = None,
    include_admitted_markets: bool = True,
) -> dict[str, Any]:
    """Load existing FTSE history and library panels; score patient plain EY."""
    data_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    reg_path = (
        Path(registration_path) if registration_path is not None else DEFAULT_REGISTRATION_PATH
    )
    lib_root = Path(library_root) if library_root is not None else DEFAULT_LIBRARY_ROOT
    cfg = cfg or N201Config(
        fetch_momentum_prices=False,
        max_episodes=MAX_EPISODES,
        ey_top_share=EY_TOP_SHARE,
        hold_trading_days=HOLD_TRADING_DAYS,
        fixed_stake_units=FIXED_STAKE_UNITS,
        stress_trade_cost_pct=STRESS_TRADE_COST_PCT,
        volume_min_episodes=VOLUME_MIN_EPISODES,
        volume_min_weeks=VOLUME_MIN_WEEKS,
        phase_entries_per_week_floor=PHASE_ENTRIES_PER_WEEK_FLOOR,
    )

    prior_markers: list[dict[str, Any]] = []
    if store.is_file():
        prior = _safe_read_json(store) or {}
        markers = prior.get("change_markers")
        if isinstance(markers, list):
            prior_markers = [m for m in markers if isinstance(m, dict)]

    ftse_snapshots = enrich_snapshots_from_archives(
        load_run_snapshots(data_dir), data_dir / "archive"
    )
    payloads: list[dict[str, Any]] = []
    ftse_cfg = N201Config(
        market_id=cfg.market_id or DEFAULT_MARKET_ID,
        buy_cost_pct=cfg.buy_cost_pct,
        sell_cost_pct=cfg.sell_cost_pct,
        stress_trade_cost_pct=cfg.stress_trade_cost_pct,
        volume_min_episodes=cfg.volume_min_episodes,
        volume_min_weeks=cfg.volume_min_weeks,
        phase_entries_per_week_floor=cfg.phase_entries_per_week_floor,
        hold_trading_days=cfg.hold_trading_days,
        fixed_stake_units=cfg.fixed_stake_units,
        ey_top_share=cfg.ey_top_share,
        max_episodes=cfg.max_episodes,
        fetch_momentum_prices=False,
    )
    payloads.append(
        score_plain_ey_hold(
            ftse_snapshots,
            cfg=ftse_cfg,
            generated_at=generated_at,
            prior_markers=prior_markers,
        )
    )
    panel_loaded: list[str] = []
    panel_missing: list[str] = []
    panel_counts: dict[str, int] = {DEFAULT_MARKET_ID: len(ftse_snapshots)}
    if include_admitted_markets:
        policy_path = (
            Path(library_policy_path)
            if library_policy_path is not None
            else DEFAULT_LIBRARY_POLICY_PATH
        )
        for mid in _admitted_markets(policy_path):
            snaps = load_library_market_snapshots(lib_root, mid)
            if not snaps:
                panel_missing.append(mid)
                continue
            panel_loaded.append(mid)
            panel_counts[mid] = len(snaps)
            remaining = max(
                0,
                cfg.max_episodes
                - sum(int(p.get("completed_entry_episodes") or 0) for p in payloads),
            )
            if remaining <= 0:
                break
            mid_cfg = N201Config(
                market_id=mid,
                buy_cost_pct=cfg.buy_cost_pct,
                sell_cost_pct=cfg.sell_cost_pct,
                stress_trade_cost_pct=cfg.stress_trade_cost_pct,
                volume_min_episodes=cfg.volume_min_episodes,
                volume_min_weeks=cfg.volume_min_weeks,
                phase_entries_per_week_floor=cfg.phase_entries_per_week_floor,
                hold_trading_days=cfg.hold_trading_days,
                fixed_stake_units=cfg.fixed_stake_units,
                ey_top_share=cfg.ey_top_share,
                max_episodes=remaining,
                fetch_momentum_prices=False,
            )
            payloads.append(
                score_plain_ey_hold(
                    snaps,
                    cfg=mid_cfg,
                    generated_at=generated_at,
                    prior_markers=[],
                )
            )
    panel_coverage = {
        "ftse_snapshots": len(ftse_snapshots),
        "admitted_loaded": panel_loaded,
        "admitted_missing_or_empty": panel_missing,
        "panel_snapshot_counts": panel_counts,
        "library_root": str(lib_root),
        "scoring_inputs": "existing_screen_panels_only",
        "filing_ingest_sprint": False,
        "momentum_price_fetch": False,
    }
    payload = _merge_payloads(
        payloads,
        generated_at=generated_at,
        prior_markers=prior_markers,
        panel_coverage=panel_coverage,
        cfg=cfg,
    )
    registration = build_registration_payload()
    if persist:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(registration, indent=2) + "\n", encoding="utf-8")
        from value_investor.sealed_lifecycle import publish_sealed_lifecycle_projection

        publish_sealed_lifecycle_projection(store.parent)
    return payload


def ops_findings_from_n206_observe(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map observe store → ops-monitor finding dicts (observe-only)."""
    n = int(payload.get("completed_entry_episodes") or 0)
    weeks = int(payload.get("calendar_weeks_spanned") or 0)
    phase = payload.get("phase") if isinstance(payload.get("phase"), dict) else {}
    path = (
        payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    )
    missing = int(payload.get("skipped_missing_entry_fields") or 0)
    findings: list[dict[str, Any]] = [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"{REGISTRATION_ID}: {n} completed episodes over {weeks} weeks; "
                f"entries/week={phase.get('entries_per_week')}; "
                f"{SUCCESS_METRIC_ID}={path.get('smooth_ret_cohort_median')} "
                f"(fair costs primary; fixed-stake %; independent of fund NAV); "
                f"cash_excess_report_only={path.get('cash_excess_report_only')}; "
                f"stress_3pct_report_only="
                f"{path.get('smooth_ret_cohort_median_stress_report_only')}; "
                f"skipped_missing_entry_fields={missing}. "
                "Observe-only — influences_live false; alone-first; "
                "no filing ingest sprint; no live writes (F8)."
            ),
            "auto_fixable": False,
        }
    ]
    volume = payload.get("volume_gate") if isinstance(payload.get("volume_gate"), dict) else {}
    if volume.get("met"):
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": VOLUME_GATE_TITLE,
                "summary": (
                    f"Sample thickness met (episodes>={VOLUME_MIN_EPISODES} and "
                    f"weeks>={VOLUME_MIN_WEEKS}). Alone-first; "
                    f"{VOLUME_THICKNESS_SUMMARY_SUFFIX}"
                ),
                "auto_fixable": False,
            }
        )
    # Always re-evaluate from current path fields (store stamp may lag).
    gate = evaluate_n206_interestingness(payload)
    interesting = interestingness_finding(
        title=INTERESTINGNESS_TITLE,
        gate=gate,
        strand_note="N206 plain-EY (alone design optional — no assessment crown).",
    )
    if interesting is not None:
        findings.append(interesting)
    return findings


def format_n206_observe_text(payload: dict[str, Any]) -> str:
    path = (
        payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    )
    phase = payload.get("phase") if isinstance(payload.get("phase"), dict) else {}
    volume = payload.get("volume_gate") if isinstance(payload.get("volume_gate"), dict) else {}
    cost = payload.get("cost_basis") if isinstance(payload.get("cost_basis"), dict) else {}
    lines = [
        f"N206 {payload.get('registration_id')} (observe-only)",
        f"  episodes={payload.get('completed_entry_episodes')} "
        f"weeks={payload.get('calendar_weeks_spanned')} "
        f"entries/week={phase.get('entries_per_week')}",
        f"  {SUCCESS_METRIC_ID}={path.get('smooth_ret_cohort_median')} "
        f"(fair {cost.get('market_id')} RT={cost.get('round_trip_pct')}; "
        f"fixed-stake %; independent of fund NAV)",
        f"  cash_excess_report_only={path.get('cash_excess_report_only')}",
        f"  stress_3pct_report_only={path.get('smooth_ret_cohort_median_stress_report_only')}",
        f"  volume_gate_met={volume.get('met')} phase_floor_met={phase.get('floor_met')}",
        f"  influences_live={payload.get('influences_live')} alone_first={payload.get('alone_first')}",
        f"  skipped_missing_entry_fields={payload.get('skipped_missing_entry_fields')}",
    ]
    return "\n".join(lines) + "\n"


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
        state, label, detail = (
            "missing",
            "Missing",
            "N206 observe store not published yet.",
        )
    elif age_h is None:
        state, label, detail = "unknown", "Unknown", "Store present but no usable timestamp."
    elif age_h >= stale_after_hours:
        state, label, detail = (
            "stale",
            "Stale",
            f"Last refresh {age_h:.1f}h ago (limit {stale_after_hours:.0f}h).",
        )
    elif store_lag_h is not None and store_lag_h >= store_lag_warn_hours:
        state, label, detail = (
            "lagging",
            "Lagging ops",
            f"Store trails ops_status by {store_lag_h:.1f}h.",
        )
    else:
        state, label, detail = "fresh", "Fresh", f"Last refresh {age_h:.1f}h ago."
    return {
        "state": state,
        "label": label,
        "detail": detail,
        "as_of": as_of.isoformat() if as_of else None,
        "age_hours": age_h,
        "store_lag_hours": store_lag_h,
        "stale_after_hours": float(stale_after_hours),
    }


def _ops_check_status(ops_status: dict[str, Any] | None) -> dict[str, Any]:
    findings = (ops_status or {}).get("findings")
    rows = findings if isinstance(findings, list) else []
    titles = {str(row.get("title") or "") for row in rows if isinstance(row, dict)}
    if STORE_FAILED_TITLE in titles:
        return {
            "ops_check_ok": False,
            "ops_finding_present": True,
            "detail": f"Ops finding: {STORE_FAILED_TITLE}",
        }
    if FINDING_TITLE in titles:
        return {
            "ops_check_ok": True,
            "ops_finding_present": True,
            "detail": f"Ops finding: {FINDING_TITLE}",
        }
    return {
        "ops_check_ok": False,
        "ops_finding_present": False,
        "detail": "No N206 ops finding in latest ops_status.",
    }


def build_n206_pipeline_health_projection(
    payload: dict[str, Any] | None = None,
    *,
    store_path: Path | None = None,
    ops_status_path: Path | None = None,
    ops_status: dict[str, Any] | None = None,
    now: datetime | None = None,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    store_lag_warn_hours: float = DEFAULT_STORE_LAG_WARN_HOURS,
) -> dict[str, Any]:
    """Slim dashboard projection: phase, volume, freshness (mechanism only)."""
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
    ops_check = _ops_check_status(ops_status)
    phase = (
        (payload or {}).get("phase")
        if present and isinstance((payload or {}).get("phase"), dict)
        else {}
    )
    volume = (
        (payload or {}).get("volume_gate")
        if present and isinstance((payload or {}).get("volume_gate"), dict)
        else {}
    )
    path = (
        (payload or {}).get("path_scoreboard")
        if present and isinstance((payload or {}).get("path_scoreboard"), dict)
        else {}
    )
    episodes = int((payload or {}).get("completed_entry_episodes") or 0) if present else 0
    weeks = int((payload or {}).get("calendar_weeks_spanned") or 0) if present else 0
    entries_pw = phase.get("entries_per_week")
    floor = phase.get("floor", PHASE_ENTRIES_PER_WEEK_FLOOR)
    floor_met = bool(phase.get("floor_met")) if present and "floor_met" in phase else False
    volume_met = bool(volume.get("met")) if present and "met" in volume else False
    freshness_ok = freshness["state"] in {"fresh", "lagging"}
    ops_ok = bool(ops_check["ops_check_ok"]) or (freshness["state"] == "fresh" and present)
    functioning = bool(present and freshness_ok and ops_ok)
    if not present:
        headline = "N206 observe store missing — pipeline not yet published."
    elif not functioning:
        headline = (
            f"N206 pipeline attention — freshness={freshness['state']}; "
            f"phase floor {'met' if floor_met else 'not met'}; "
            f"volume gate {'met' if volume_met else 'not met'}."
        )
    else:
        headline = (
            f"N206 pipeline functioning — phase {entries_pw}/{floor} "
            f"entries/week; volume {'met' if volume_met else 'not met'} "
            f"({episodes} ep / {weeks} wk); "
            f"{SUCCESS_METRIC_ID}={path.get('smooth_ret_cohort_median')}."
        )
    return {
        "schema_version": PIPELINE_HEALTH_SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "observe_only": True,
        "influences_live": False,
        "not_alpha_signal": True,
        "not_capital_ready": True,
        "not_assessment_primary": True,
        "alone_first": True,
        "independent_of_fund_nav": True,
        "launch_queue_waiter": True,
        "data_deepen_requested": False,
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
            "role": "sample_thickness_pipeline_badge",
        },
        "interestingness_gate": (
            (payload or {}).get("interestingness_gate")
            if present and isinstance((payload or {}).get("interestingness_gate"), dict)
            else evaluate_n206_interestingness(payload or {})
            if present
            else {"met": False, "thickness_met": False}
        ),
        "path_scoreboard": {
            "smooth_ret_cohort_median": path.get("smooth_ret_cohort_median"),
            "cash_excess_report_only": path.get("cash_excess_report_only"),
            "smooth_ret_cohort_median_stress_report_only": path.get(
                "smooth_ret_cohort_median_stress_report_only"
            ),
            "independent_of_fund_nav": True,
        },
        "freshness": freshness,
        "pipeline": {
            "functioning": functioning,
            "ops_check_ok": bool(ops_check["ops_check_ok"]),
            "ops_finding_present": bool(ops_check["ops_finding_present"]),
            "ops_run_at": ops_run_at.isoformat() if ops_run_at else None,
            "detail": f"{ops_check['detail']} {freshness['detail']}".strip(),
        },
        "ops_doc": str(DEFAULT_OPS_DOC),
    }
