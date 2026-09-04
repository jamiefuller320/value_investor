"""Run the offline library richness ladder for the focus market."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    DEFAULT_POLICY_PATH,
    DEFAULT_SPEND_CHECKPOINT_USD,
    SPEND_POOL_AD_HOC,
    SPEND_POOL_WEEKLY_OPS,
    approve_spend_checkpoint,
    enforce_weekly_ops_cap,
    grow_ticker_budget,
    load_policy,
    record_estimated_spend,
    record_spend_with_checkpoint,
    remaining_weekly_ops_usd,
    research_model_id,
    save_policy,
    spend_checkpoint_usd,
    spend_since_checkpoint_usd,
    weekly_ops_budget_status,
)
from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.data_library import DEFAULT_LIBRARY_ROOT, grow_library, library_status
from value_investor.library_dedupe import (
    canonical_library_ticker,
    existing_library_research_tickers,
    select_deduped_research_targets,
)
from value_investor.library_graduation import (
    graduated_market_ids,
    maybe_graduate_focus,
    run_maintenance_grow,
)
from value_investor.library_screen import (
    assess_library_metrics_health,
    effective_min_metrics_for_screen,
    library_research_reports,
    research_cap_from_budget,
    run_library_screen,
)
from value_investor.library_sim import (
    DEFAULT_OBSERVE_SIM_MARKETS,
    OBSERVE_SIM_MARKETS_MODE_GRADUATED_BENCHMARK,
    observe_sim_markets_for_policy,
    run_observe_sims_for_screened_markets,
)
from value_investor.market_paper_shard import (
    run_weekday_paper_shards_for_markets,
    run_weekly_paper_shards_for_screened_markets,
)
from value_investor.market_shard_phases import (
    refresh_committed_phase_rollup,
    weekly_paper_shard_markets_for_policy,
)
from value_investor.research.market_store import (
    DEFAULT_REMEMO_BODY_LAG_THRESHOLD,
    library_rememo_eligible_tickers,
)
from value_investor.research.runner import eligible_research_targets, run_research_for_strong_buys
from value_investor.storage import write_json

logger = logging.getLogger(__name__)

ESTIMATED_MEMO_USD = 0.40
DEFAULT_MIN_METRICS_FOR_SCREEN = 25
DEFAULT_WEEKLY_PAPER_SHARD_MARKETS: tuple[str, ...] = ("sp500", "euro_stoxx50")
DEFAULT_WEEKLY_PAPER_SHARD_CAPACITY = 2
DEFAULT_STRONG_BUY_PROBE_MAX_TICKERS = 25
DEFAULT_STRONG_BUY_PROBE_MAX_MARKETS = 4
DEFAULT_PHASE1_REQUIRE_AI_BEAT_RULES = True


def _ensure_ladder_policy(policy: dict[str, Any]) -> dict[str, Any]:
    ladder = dict(policy.get("ladder") or {})
    ladder.setdefault("enabled", True)
    ladder.setdefault("layers", ["fundamentals", "screen_lite", "selective_research"])
    ladder.setdefault("min_metrics_for_screen", DEFAULT_MIN_METRICS_FOR_SCREEN)
    ladder.setdefault("estimated_memo_usd", ESTIMATED_MEMO_USD)
    ladder.setdefault("research_hard_cap", 50)
    ladder.setdefault("research_all_graduated", True)
    ladder.setdefault("rememo_existing", True)
    ladder.setdefault("rememo_body_lag_threshold", DEFAULT_REMEMO_BODY_LAG_THRESHOLD)
    ladder.setdefault("observe_sim_after_screen", True)
    ladder.setdefault("observe_sim_markets_mode", OBSERVE_SIM_MARKETS_MODE_GRADUATED_BENCHMARK)
    ladder.setdefault("observe_sim_markets", list(DEFAULT_OBSERVE_SIM_MARKETS))
    ladder.setdefault("observe_sim_include_ingest_profile", True)
    ladder.setdefault("observe_sim_screen_missing_markets", True)
    ladder.setdefault("observe_sim_screen_when_research_skipped", True)
    ladder.setdefault("weekly_paper_shard_after_screen", True)
    ladder.setdefault("weekly_paper_shard_markets", list(DEFAULT_WEEKLY_PAPER_SHARD_MARKETS))
    ladder.setdefault("weekly_paper_shard_capacity", DEFAULT_WEEKLY_PAPER_SHARD_CAPACITY)
    ladder.setdefault("phase1_require_ai_beat_rules", DEFAULT_PHASE1_REQUIRE_AI_BEAT_RULES)
    ladder.setdefault("phase1_min_screen_archives", 12)
    ladder.setdefault("phase2_min_weekly_batches", 8)
    ladder.setdefault("phase3_min_weekday_batches", 8)
    ladder.setdefault("phase3_min_exit_shadow_closed", 15)
    ladder.setdefault("weekday_paper_shard_after_weekly", False)
    ladder.setdefault("focus_grow_cap", 25)
    ladder.setdefault("strong_buy_metrics_probe_after_maintenance", True)
    ladder.setdefault("strong_buy_metrics_probe_when_eng_idle", True)
    ladder.setdefault("strong_buy_metrics_probe_max_tickers", DEFAULT_STRONG_BUY_PROBE_MAX_TICKERS)
    ladder.setdefault("strong_buy_metrics_probe_max_markets", DEFAULT_STRONG_BUY_PROBE_MAX_MARKETS)
    ladder.setdefault("spend_checkpoint_usd", DEFAULT_SPEND_CHECKPOINT_USD)
    ladder.setdefault("spend_since_checkpoint_usd", 0.0)
    ladder.setdefault("last_run", None)
    policy["ladder"] = ladder
    return policy


def _research_markets(policy: dict[str, Any], focus: str) -> list[str]:
    """
    Markets whose buy-tier shortlists get selective research this run.

    When ``research_all_graduated`` is true (default), include the full market
    queue plus focus/graduated — so newly grown index slices get memos before
    they formally graduate. Prefer queue order for stable round-robin.
    """
    ladder = policy.get("ladder") or {}
    if not ladder.get("research_all_graduated", True):
        return [focus]
    queue = list(policy.get("market_queue") or [])
    graduated = graduated_market_ids(policy)
    ordered: list[str] = []
    for mid in [*queue, focus, *graduated]:
        if mid and mid not in ordered:
            ordered.append(mid)
    return ordered or ([focus] if focus else [])


def _screen_observe_sim_markets(
    root: Path,
    policy: dict[str, Any],
    *,
    screened_markets: set[str],
    run_at: datetime,
) -> dict[str, Any]:
    """Screen-lite for observe-sim markets the research / focus pass did not screen."""
    targets = [mid for mid in observe_sim_markets_for_policy(policy) if mid not in screened_markets]
    if not targets:
        return {"skipped": True, "reason": "all observe-sim markets already screened"}
    screened: list[str] = []
    errors: dict[str, str] = {}
    for mid in targets:
        try:
            run_library_screen(root, mid, run_at=run_at)
            screened_markets.add(mid)
            screened.append(mid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Observe-sim screen-lite for %s failed: %s", mid, exc)
            errors[mid] = str(exc)
    if not screened:
        return {
            "skipped": True,
            "reason": "observe-sim screen-lite failed for all targets",
            "targets": targets,
            "errors": errors,
        }
    return {"skipped": False, "markets": screened, "errors": errors}


def observe_sim_screen_should_run(
    *, skip_screen: bool, ladder_cfg: dict[str, Any]
) -> tuple[bool, str]:
    """Whether ladder should backfill screen-lite for observe-sim markets not yet screened.

    Runs on a normal Sunday (research ran) as well as when research is skipped, so
    ingest-profile markets keep a dated archive clock. ``skip_screen`` and the
    missing-markets kill switch still disable the pass.
    """
    if skip_screen:
        return False, "screen-lite disabled"
    if ladder_cfg.get("observe_sim_screen_missing_markets") is False:
        return False, "observe_sim_screen_missing_markets is off"
    if not ladder_cfg.get("observe_sim_screen_when_research_skipped", True):
        return False, "observe_sim_screen_when_research_skipped is off"
    return True, ""


def run_library_ladder(
    *,
    root: Path | None = None,
    policy_path: Path | None = None,
    skip_grow: bool = False,
    skip_screen: bool = False,
    skip_research: bool = False,
    skip_maintenance: bool = False,
    skip_graduation: bool = False,
    dry_run_research: bool = False,
    api_key: str | None = None,
    max_tickers: int | None = None,
    unrestricted_budget: bool = False,
    checkpoint_usd: float | None = None,
    approve_checkpoint: bool = False,
    spend_pool: str | None = None,
) -> dict[str, Any]:
    """
    Focus-market ladder: A fundamentals grow → maintenance → B screen-lite →
    C selective research → graduation check.

    Research is budget-gated. Orchestrator runs use the weekly_ops pool ($50 default);
    ad-hoc runs pass --unrestricted-budget to use the checkpoint-gated ad_hoc pool.
    """
    root = root or DEFAULT_LIBRARY_ROOT
    policy_path = policy_path or DEFAULT_POLICY_PATH
    if spend_pool is None:
        spend_pool = SPEND_POOL_AD_HOC if unrestricted_budget else SPEND_POOL_WEEKLY_OPS
    if spend_pool not in {SPEND_POOL_WEEKLY_OPS, SPEND_POOL_AD_HOC}:
        raise ValueError(f"Unknown spend_pool {spend_pool!r}")
    policy = _ensure_ladder_policy(load_policy(policy_path))
    if approve_checkpoint:
        approval = approve_spend_checkpoint(policy_path)
        result_approval = {"checkpoint_approval": approval}
    else:
        result_approval = {}
    save_policy(policy, policy_path)
    plan = grow_ticker_budget(policy)
    markets = plan["focus_markets"]
    market = markets[0]
    run_at = datetime.now(UTC)
    result: dict[str, Any] = {
        "run_at": run_at.isoformat(),
        "focus_market": market,
        "graduated_markets": graduated_market_ids(policy),
        "plan": plan,
        "layers": {},
        **result_approval,
    }

    # A — fundamentals (focus market)
    if not skip_grow:
        plan_tickers = int(max_tickers if max_tickers is not None else plan["max_tickers"])
        from value_investor.library_progression import effective_focus_grow_tickers

        tickers = effective_focus_grow_tickers(
            root=root,
            policy_path=policy_path,
            market_id=market,
            plan_max_tickers=plan_tickers,
        )
        grow_results = grow_library(
            root,
            markets=markets,
            max_tickers_per_run=tickers,
            refresh_constituents_first=True,
        )
        status = library_status(root, markets=markets)
        result["layers"]["fundamentals"] = {
            "grew": grow_results,
            "status": status,
            "max_tickers": tickers,
            "plan_max_tickers": plan_tickers,
        }
    else:
        status = library_status(root, markets=markets)
        result["layers"]["fundamentals"] = {"skipped": True, "status": status}

    # A2 — maintenance grow on already-graduated markets
    if skip_maintenance:
        result["layers"]["maintenance"] = {"skipped": True}
    else:
        policy = load_policy(policy_path)
        result["layers"]["maintenance"] = run_maintenance_grow(root, policy)

    # A2b — strong-buy-first metrics probe (eng-idle; feeds coverage engineering)
    policy = load_policy(policy_path)
    try:
        from value_investor.library_strong_buy_probe import run_strong_buy_metrics_probe

        result["layers"]["strong_buy_metrics_probe"] = run_strong_buy_metrics_probe(
            root,
            policy,
            policy_path=policy_path,
        )
    except Exception as exc:  # noqa: BLE001 — probe must not fail the ladder
        logger.warning("Strong-buy metrics probe failed: %s", exc)
        result["layers"]["strong_buy_metrics_probe"] = {
            "skipped": True,
            "reason": str(exc),
            "error": str(exc),
        }

    # A3 — offline macro / regime context (research & paper notes only — never scoring)
    macro_cfg = dict(policy.get("macro_context") or {})
    if macro_cfg.get("enabled", True) and macro_cfg.get("refresh_on_ladder", True):
        try:
            from value_investor.macro_context import refresh_macro_library

            macro_snap = refresh_macro_library(root / "macro")
            result["layers"]["macro_context"] = {
                "refreshed": True,
                "fetched_at": macro_snap.get("fetched_at"),
                "path": macro_snap.get("path"),
                "use_in_scoring": False,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Macro refresh failed: %s", exc)
            result["layers"]["macro_context"] = {
                "refreshed": False,
                "error": str(exc),
                "use_in_scoring": False,
            }
    else:
        result["layers"]["macro_context"] = {"skipped": True, "use_in_scoring": False}

    coverage = (status[0] if status else {}) or {}
    manifest_coverage = int(coverage.get("coverage_count") or 0)
    metrics_health = assess_library_metrics_health(root, market)
    # Prefer honest usable count; small indices use effective_min (≤ ticker_count).
    usable_metrics = int(
        metrics_health.get("honest_usable_rows")
        if metrics_health.get("honest_usable_rows") is not None
        else metrics_health.get("usable_rows") or 0
    )
    policy_min = int(
        policy["ladder"].get("min_metrics_for_screen") or DEFAULT_MIN_METRICS_FOR_SCREEN
    )
    ticker_count = int(coverage.get("ticker_count") or 0)
    if ticker_count <= 0:
        ticker_count = int(metrics_health.get("total_rows") or usable_metrics or 0)
    min_metrics = effective_min_metrics_for_screen(ticker_count, policy_min=policy_min)
    screened_markets: set[str] = set()

    # B — screen-lite (focus)
    if skip_screen:
        result["layers"]["screen_lite"] = {"skipped": True}
        screen_result = None
    elif usable_metrics < min_metrics:
        result["layers"]["screen_lite"] = {
            "skipped": True,
            "reason": f"need>={min_metrics} usable metrics rows, have {usable_metrics}",
            "manifest_coverage_count": manifest_coverage,
            "usable_metrics_rows": usable_metrics,
            "total_metrics_rows": int(metrics_health.get("total_rows") or 0),
            "policy_min_metrics_for_screen": policy_min,
            "effective_min_metrics_for_screen": min_metrics,
            "ticker_count": ticker_count,
        }
        screen_result = None
    else:
        try:
            screen_result = run_library_screen(root, market, run_at=run_at)
            screened_markets.add(market)
            result["layers"]["screen_lite"] = {
                **screen_result.summary,
                "manifest_coverage_count": manifest_coverage,
                "usable_metrics_rows": usable_metrics,
            }
        except (FileNotFoundError, ValueError) as exc:
            logger.warning("Screen-lite for focus %s failed: %s", market, exc)
            result["layers"]["screen_lite"] = {
                "failed": True,
                "error": str(exc),
                "manifest_coverage_count": manifest_coverage,
                "usable_metrics_rows": usable_metrics,
                "total_metrics_rows": int(metrics_health.get("total_rows") or 0),
            }
            screen_result = None

    # C — selective research across focus + graduated markets (optional USD strand)
    policy = load_policy(policy_path)
    memo_cost = float(policy["ladder"].get("estimated_memo_usd") or ESTIMATED_MEMO_USD)
    hard_cap = int(policy["ladder"].get("research_hard_cap") or 50)
    checkpoint_limit = float(
        checkpoint_usd if checkpoint_usd is not None else spend_checkpoint_usd(policy)
    )
    use_weekly_ops = spend_pool == SPEND_POOL_WEEKLY_OPS
    if use_weekly_ops:
        remaining = remaining_weekly_ops_usd(policy)
        weekly_cap_on = enforce_weekly_ops_cap(policy)
        budget_status = weekly_ops_budget_status(policy, estimated_memo_usd=memo_cost)
        if weekly_cap_on:
            research_cap = research_cap_from_budget(
                remaining_usd=remaining,
                estimated_memo_usd=memo_cost,
                hard_cap=hard_cap,
                surplus=bool(plan.get("surplus_day")),
            )
        else:
            research_cap = hard_cap
    else:
        remaining = 0.0
        weekly_cap_on = False
        budget_status = weekly_ops_budget_status(policy, estimated_memo_usd=memo_cost)
        research_cap = hard_cap
    model = research_model_id(policy)
    research_markets = _research_markets(policy, market)
    checkpoint_blocked = (
        spend_pool == SPEND_POOL_AD_HOC and spend_since_checkpoint_usd(policy) >= checkpoint_limit
    )

    if skip_research:
        result["layers"]["selective_research"] = {"skipped": True}
    elif checkpoint_blocked and not approve_checkpoint:
        result["layers"]["selective_research"] = {
            "skipped": True,
            "reason": "spend checkpoint reached — approval required to continue",
            "spend_since_checkpoint_usd": spend_since_checkpoint_usd(policy),
            "spend_checkpoint_usd": checkpoint_limit,
            "unrestricted_budget": unrestricted_budget,
            "note": (
                "Re-run with --approve-checkpoint after human approval, "
                "or reset spend_since_checkpoint_usd in policy."
            ),
        }
    elif research_cap <= 0 and weekly_cap_on:
        result["layers"]["selective_research"] = {
            "skipped": True,
            "reason": (
                "weekly orchestrator research budget exhausted"
                if use_weekly_ops
                else "research cap unavailable"
            ),
            "spend_pool": spend_pool,
            "remaining_usd": remaining,
            "enforce_weekly_ops_cap": weekly_cap_on,
            "constraining": True,
            "budget_flag": budget_status["flag"],
            "weekly_ops_cap_usd": budget_status.get("weekly_ops_cap_usd"),
            "note": budget_status.get("note"),
        }
    else:
        # Screen each research market (reuse focus screen_result when present).
        market_screens: dict[str, Any] = {}
        if screen_result is not None:
            market_screens[market] = screen_result
        for mid in research_markets:
            if mid in market_screens:
                continue
            try:
                market_screens[mid] = run_library_screen(root, mid, run_at=run_at)
                screened_markets.add(mid)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Screen-lite for research market %s failed: %s", mid, exc)

        # Round-robin buy-tier targets across markets until research_cap is filled.
        # Skip exact Yahoo-ticker duplicates and *fresh* existing memos. Thin /
        # body-lag memos stay eligible so a new focus market rememos after ingest
        # deepens filings — not only first-time names.
        per_market_reports: dict[str, list[Any]] = {}
        per_market_queues: dict[str, list[Any]] = {}
        for mid, scr in market_screens.items():
            reports = library_research_reports(scr)
            per_market_reports[mid] = reports
            # Oversample per market so dedupe can refill the global cap.
            per_market_queues[mid] = eligible_research_targets(
                reports, weekly_cap=max(research_cap * 3, research_cap)
            )

        already = existing_library_research_tickers(root)
        rememo_reasons: dict[str, str] = {}
        if bool((policy.get("ladder") or {}).get("rememo_existing", True)):
            queue_tickers = {
                canonical_library_ticker(str(getattr(report, "ticker", "") or ""))
                for queue in per_market_queues.values()
                for report in queue
            }
            rememo_reasons = library_rememo_eligible_tickers(
                root,
                tickers=queue_tickers,
                market_id=market,
                body_lag_threshold=int(
                    (policy.get("ladder") or {}).get(
                        "rememo_body_lag_threshold", DEFAULT_REMEMO_BODY_LAG_THRESHOLD
                    )
                ),
            )
        skip_fresh = already - set(rememo_reasons)
        selected, dedupe_skipped = select_deduped_research_targets(
            research_markets=research_markets,
            per_market_queues=per_market_queues,
            research_cap=research_cap,
            already_researched=skip_fresh,
        )

        status = budget_status
        layer: dict[str, Any] = {
            "model": model,
            "research_cap": research_cap,
            "research_markets": research_markets,
            "research_all_graduated": bool(
                (policy.get("ladder") or {}).get("research_all_graduated", True)
            ),
            "spend_pool": spend_pool,
            "enforce_weekly_ops_cap": weekly_cap_on,
            "unrestricted_budget": unrestricted_budget,
            "spend_checkpoint_usd": checkpoint_limit,
            "spend_since_checkpoint_usd": spend_since_checkpoint_usd(policy),
            "weekly_ops_cap_usd": status.get("weekly_ops_cap_usd"),
            "estimated_spend_weekly_ops_usd_this_week": status.get(
                "estimated_spend_weekly_ops_usd_this_week"
            ),
            "constraining": status["constraining"],
            "near_limit": status["near_limit"],
            "budget_flag": status["flag"],
            "remaining_usd_before": remaining,
            "dedupe": {
                "already_researched_count": len(already),
                "fresh_skipped_count": len(skip_fresh),
                "rememo_eligible_count": len(rememo_reasons),
                "rememo_eligible_sample": [
                    {"ticker": ticker, "reason": rememo_reasons[ticker]}
                    for ticker in sorted(rememo_reasons)[:20]
                ],
                "skipped_count": len(dedupe_skipped),
                "skipped_sample": dedupe_skipped[:20],
                "note": (
                    "Exact Yahoo ticker match; earlier queue market wins. "
                    "Fresh memos are skipped; thin / body-lag memos rememo after ingest."
                ),
            },
            "targets": [
                {
                    "market": mid,
                    "ticker": t.ticker,
                    "name": t.name,
                    "signal": t.signal,
                    "conviction_score": t.conviction_score,
                }
                for mid, t in selected
            ],
        }
        if dry_run_research or not selected:
            layer["dry_run"] = True
            layer["executed"] = 0
        else:
            key = resolve_cursor_api_key()[0] if not (api_key or "").strip() else api_key.strip()
            if not key:
                layer["skipped"] = True
                layer["reason"] = "CURSOR_API_KEY missing"
            else:
                executed = created = updated = 0
                errors: list[str] = []
                checkpoint_reached = False
                for mid, report in selected:
                    scr = market_screens[mid]
                    summary = run_research_for_strong_buys(
                        reports=[report],
                        output_dir=scr.screen_dir,
                        api_key=key,
                        model=model,
                        weekly_cap=1,
                        continue_alumni=False,
                        market=mid,
                    )
                    memo_executed = int(summary.created) + int(summary.updated)
                    executed += memo_executed
                    created += int(summary.created)
                    updated += int(summary.updated)
                    errors.extend(list(summary.errors or []))
                    if memo_executed > 0:
                        if use_weekly_ops:
                            record_estimated_spend(
                                memo_cost,
                                policy_path,
                                pool=SPEND_POOL_WEEKLY_OPS,
                            )
                            layer["estimated_spend_weekly_ops_usd_this_week"] = (
                                weekly_ops_budget_status(load_policy(policy_path))[
                                    "estimated_spend_weekly_ops_usd_this_week"
                                ]
                            )
                            ops_remaining = remaining_weekly_ops_usd(load_policy(policy_path))
                            if ops_remaining < memo_cost:
                                layer["weekly_ops_exhausted"] = True
                                layer["weekly_ops_note"] = (
                                    f"Paused — weekly orchestrator envelope spent "
                                    f"(remaining ${ops_remaining:.2f})."
                                )
                                break
                        else:
                            checkpoint_status = record_spend_with_checkpoint(
                                memo_cost,
                                policy_path,
                                checkpoint_usd=checkpoint_limit,
                            )
                            layer["spend_since_checkpoint_usd"] = checkpoint_status[
                                "spend_since_checkpoint_usd"
                            ]
                            if checkpoint_status["checkpoint_reached"]:
                                checkpoint_reached = True
                                layer["checkpoint_reached"] = True
                                layer["checkpoint_note"] = (
                                    f"Paused after ${checkpoint_status['spend_since_checkpoint_usd']:.2f} "
                                    f"since last approval (limit ${checkpoint_limit:.2f}). "
                                    "Re-run with --approve-checkpoint to continue."
                                )
                                break
                layer["executed"] = executed
                layer["created"] = created
                layer["updated"] = updated
                layer["errors"] = errors
                if executed > 0:
                    layer["estimated_spend_usd"] = round(executed * memo_cost, 4)
                    if use_weekly_ops:
                        layer["remaining_usd_after"] = remaining_weekly_ops_usd(
                            load_policy(policy_path)
                        )
                if checkpoint_reached:
                    layer["paused_for_approval"] = True
        result["layers"]["selective_research"] = layer

    # B1b — screen-lite for observe-sim markets not already screened this pass
    policy = load_policy(policy_path)
    ladder_cfg = policy.get("ladder") or {}
    should_screen, skip_reason = observe_sim_screen_should_run(
        skip_screen=skip_screen,
        ladder_cfg=ladder_cfg,
    )
    if not should_screen:
        result["layers"]["observe_sim_screen"] = {
            "skipped": True,
            "reason": skip_reason,
        }
    else:
        result["layers"]["observe_sim_screen"] = _screen_observe_sim_markets(
            root,
            policy,
            screened_markets=screened_markets,
            run_at=run_at,
        )

    # B2 — observe-only paper sim for pilot library markets (after screen + research)
    policy = load_policy(policy_path)
    if skip_screen or not screened_markets:
        result["layers"]["observe_sim"] = {
            "skipped": True,
            "reason": "screen-lite did not run this pass",
        }
    else:
        result["layers"]["observe_sim"] = run_observe_sims_for_screened_markets(
            root,
            policy,
            screened_markets,
        )

    # B3 — weekly paper shard for Phase-2 markets (after observe sim + screen)
    policy = load_policy(policy_path)
    if skip_screen or not screened_markets:
        result["layers"]["weekly_paper_shard"] = {
            "skipped": True,
            "reason": "screen-lite did not run this pass",
        }
    else:
        result["layers"]["weekly_paper_shard"] = run_weekly_paper_shards_for_screened_markets(
            root,
            policy,
            screened_markets,
        )

    # B4 — weekday paper shard for Phase-3 markets (after weekly when enabled)
    policy = load_policy(policy_path)
    if not ladder_cfg.get("weekday_paper_shard_after_weekly", False):
        result["layers"]["weekday_paper_shard"] = {
            "skipped": True,
            "reason": "weekday_paper_shard_after_weekly is off",
        }
    else:
        result["layers"]["weekday_paper_shard"] = run_weekday_paper_shards_for_markets(
            root,
            policy,
        )

    # Phase advancement rollup (observe + weekly-paper policy markets)
    policy = load_policy(policy_path)
    phase_markets = sorted(
        set(observe_sim_markets_for_policy(policy))
        | set(weekly_paper_shard_markets_for_policy(policy))
    )
    if phase_markets:
        result["shard_phases"] = refresh_committed_phase_rollup(
            phase_markets,
            library_root=root,
            policy=policy,
        )
        if "euro_depth" in phase_markets:
            try:
                from value_investor.euro_depth_ingest_dispatch import refresh_euro_ingest_dispatch

                result["euro_ingest_dispatch"] = refresh_euro_ingest_dispatch(
                    library_root=root,
                    policy_path=policy_path,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Euro ingest dispatch refresh failed: %s", exc)

    # D — graduation (after grow + screen so floors reflect this run)
    if skip_graduation:
        result["layers"]["graduation"] = {"skipped": True}
    else:
        graduation = maybe_graduate_focus(root, policy_path)
        result["layers"]["graduation"] = graduation
        result["focus_market_after"] = graduation.get("policy_focus")
        result["graduated_markets"] = graduated_market_ids(load_policy(policy_path))

    policy = load_policy(policy_path)
    policy = _ensure_ladder_policy(policy)
    policy["ladder"]["last_run"] = {
        "run_at": run_at.isoformat(),
        "focus_market": market,
        "focus_market_after": result.get("focus_market_after", market),
        "screen_shortlist": (screen_result.summary.get("shortlist_count") if screen_result else 0),
        "research": result["layers"].get("selective_research"),
        "graduation": (result["layers"].get("graduation") or {}).get("event"),
        "maintenance": {
            "skipped": bool((result["layers"].get("maintenance") or {}).get("skipped")),
            "markets": (result["layers"].get("maintenance") or {}).get("markets") or [],
        },
    }
    save_policy(policy, policy_path)

    try:
        from value_investor.engineering_tasks import draft_library_ladder_engineering_tasks
        from value_investor.library_grow_health import (
            compile_library_stall_engineering_task,
            record_library_grow_health,
        )

        grow_health = record_library_grow_health(
            root=root, policy_path=policy_path, market_id=market
        )
        result["library_grow_health"] = grow_health
        stall_compile = compile_library_stall_engineering_task(
            root=root,
            policy_path=policy_path,
        )
        result["library_grow_stall_compile"] = stall_compile

        result["engineering_tasks"] = draft_library_ladder_engineering_tasks(
            result,
            root=root,
            policy_path=policy_path,
        )
        if (
            int(result["engineering_tasks"].get("drafted_count") or 0) == 0
            and int(stall_compile.get("compiled_count") or 0) > 0
        ):
            result["engineering_tasks"] = {
                **result["engineering_tasks"],
                "drafted_count": stall_compile.get("compiled_count"),
                "task_ids": stall_compile.get("task_ids"),
                "source": "library_grow_stall",
            }
    except Exception as exc:  # noqa: BLE001 — drafting must not fail the ladder
        logger.warning("Library ladder engineering draft failed: %s", exc)
        result["engineering_tasks"] = {"drafted_count": 0, "error": str(exc)}

    try:
        from value_investor.library_progression import assess_offline_universe_progression

        drafted_count = int((result.get("engineering_tasks") or {}).get("drafted_count") or 0)
        progression = assess_offline_universe_progression(
            root=root,
            policy_path=policy_path,
        )
        progression["engineering_drafted"] = drafted_count > 0
        result["offline_universe_progression"] = progression
    except Exception as exc:  # noqa: BLE001
        logger.warning("Offline progression assessment failed: %s", exc)

    write_json(Path(root) / "last_ladder.json", result, compact=False)
    return result
