"""Run the offline library richness ladder for the focus market."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    DEFAULT_POLICY_PATH,
    DEFAULT_SPEND_CHECKPOINT_USD,
    approve_spend_checkpoint,
    enforce_weekly_research_cap,
    grow_ticker_budget,
    load_policy,
    record_spend_with_checkpoint,
    remaining_weekly_budget_usd,
    research_model_id,
    save_policy,
    spend_checkpoint_usd,
    spend_since_checkpoint_usd,
    weekly_budget_status,
)
from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.data_library import DEFAULT_LIBRARY_ROOT, grow_library, library_status
from value_investor.library_dedupe import (
    existing_library_research_tickers,
    select_deduped_research_targets,
)
from value_investor.library_graduation import (
    graduated_market_ids,
    maybe_graduate_focus,
    run_maintenance_grow,
)
from value_investor.library_screen import (
    library_research_reports,
    research_cap_from_budget,
    run_library_screen,
)
from value_investor.research.runner import eligible_research_targets, run_research_for_strong_buys
from value_investor.storage import write_json

logger = logging.getLogger(__name__)

ESTIMATED_MEMO_USD = 0.40
DEFAULT_MIN_METRICS_FOR_SCREEN = 25


def _ensure_ladder_policy(policy: dict[str, Any]) -> dict[str, Any]:
    ladder = dict(policy.get("ladder") or {})
    ladder.setdefault("enabled", True)
    ladder.setdefault("layers", ["fundamentals", "screen_lite", "selective_research"])
    ladder.setdefault("min_metrics_for_screen", DEFAULT_MIN_METRICS_FOR_SCREEN)
    ladder.setdefault("estimated_memo_usd", ESTIMATED_MEMO_USD)
    ladder.setdefault("research_hard_cap", 50)
    ladder.setdefault("research_all_graduated", True)
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
) -> dict[str, Any]:
    """
    Focus-market ladder: A fundamentals grow → maintenance → B screen-lite →
    C selective research → graduation check.

    Research is budget-gated (10% weekly / surplus day) and uses the policy model.
    """
    root = root or DEFAULT_LIBRARY_ROOT
    policy_path = policy_path or DEFAULT_POLICY_PATH
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
        tickers = int(max_tickers if max_tickers is not None else plan["max_tickers"])
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
    metrics_count = int(coverage.get("coverage_count") or 0)
    min_metrics = int(policy["ladder"].get("min_metrics_for_screen") or DEFAULT_MIN_METRICS_FOR_SCREEN)

    # B — screen-lite (focus)
    if skip_screen:
        result["layers"]["screen_lite"] = {"skipped": True}
        screen_result = None
    elif metrics_count < min_metrics:
        result["layers"]["screen_lite"] = {
            "skipped": True,
            "reason": f"need>={min_metrics} metrics rows, have {metrics_count}",
        }
        screen_result = None
    else:
        screen_result = run_library_screen(root, market, run_at=run_at)
        result["layers"]["screen_lite"] = screen_result.summary

    # C — selective research across focus + graduated markets (optional USD strand)
    policy = load_policy(policy_path)
    remaining = remaining_weekly_budget_usd(policy)
    memo_cost = float(policy["ladder"].get("estimated_memo_usd") or ESTIMATED_MEMO_USD)
    hard_cap = int(policy["ladder"].get("research_hard_cap") or 50)
    weekly_cap_on = False if unrestricted_budget else enforce_weekly_research_cap(policy)
    checkpoint_limit = float(
        checkpoint_usd if checkpoint_usd is not None else spend_checkpoint_usd(policy)
    )
    if weekly_cap_on:
        research_cap = research_cap_from_budget(
            remaining_usd=remaining,
            estimated_memo_usd=memo_cost,
            hard_cap=hard_cap,
            surplus=bool(plan.get("surplus_day")),
        )
    else:
        research_cap = hard_cap
    model = research_model_id(policy)
    research_markets = _research_markets(policy, market)
    checkpoint_blocked = spend_since_checkpoint_usd(policy) >= checkpoint_limit

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
        status = weekly_budget_status(policy, estimated_memo_usd=memo_cost)
        result["layers"]["selective_research"] = {
            "skipped": True,
            "reason": "weekly library research budget exhausted",
            "remaining_usd": remaining,
            "enforce_weekly_research_cap": weekly_cap_on,
            "constraining": True,
            "budget_flag": status["flag"],
            "allocation_basis": status["allocation_basis"],
            "weekly_usage_gbp": status["weekly_usage_gbp"],
            "note": status.get("note"),
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
            except Exception as exc:  # noqa: BLE001
                logger.warning("Screen-lite for research market %s failed: %s", mid, exc)

        # Round-robin buy-tier targets across markets until research_cap is filled.
        # Skip exact Yahoo-ticker duplicates (e.g. AAPL in sp500 + nasdaq100) and
        # names that already have a memo under any library market.
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
        selected, dedupe_skipped = select_deduped_research_targets(
            research_markets=research_markets,
            per_market_queues=per_market_queues,
            research_cap=research_cap,
            already_researched=already,
        )

        status = weekly_budget_status(policy, estimated_memo_usd=memo_cost)
        layer: dict[str, Any] = {
            "model": model,
            "research_cap": research_cap,
            "research_markets": research_markets,
            "research_all_graduated": bool(
                (policy.get("ladder") or {}).get("research_all_graduated", True)
            ),
            "enforce_weekly_research_cap": weekly_cap_on,
            "unrestricted_budget": unrestricted_budget,
            "spend_checkpoint_usd": checkpoint_limit,
            "spend_since_checkpoint_usd": spend_since_checkpoint_usd(policy),
            "constraining": status["constraining"],
            "near_limit": status["near_limit"],
            "budget_flag": status["flag"],
            "allocation_basis": status["allocation_basis"],
            "weekly_usage_gbp": status["weekly_usage_gbp"],
            "remaining_usd_before": remaining,
            "dedupe": {
                "already_researched_count": len(already),
                "skipped_count": len(dedupe_skipped),
                "skipped_sample": dedupe_skipped[:20],
                "note": (
                    "Exact Yahoo ticker match; earlier queue market wins. "
                    "Existing memos in any library market are not re-created elsewhere."
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
            key = api_key or resolve_cursor_api_key()[0]
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
                    layer["remaining_usd_after"] = remaining_weekly_budget_usd(
                        load_policy(policy_path)
                    )
                if checkpoint_reached:
                    layer["paused_for_approval"] = True
        result["layers"]["selective_research"] = layer

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

    write_json(Path(root) / "last_ladder.json", result, compact=False)
    return result
