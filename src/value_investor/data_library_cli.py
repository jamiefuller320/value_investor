"""CLI for progressive multi-market data libraries."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .agent_model_policy import (
    DEFAULT_POLICY_PATH,
    DEFAULT_WEEKLY_OPS_PLAN_CREDIT_SHARE_CAP,
    focus_markets,
    grow_ticker_budget,
    load_policy,
    recommend_cheapest_model,
    review_model,
    save_policy,
)
from .cli_args import apply_parsed_globals
from .data_library import (
    DEFAULT_LIBRARY_ROOT,
    DEFAULT_MAX_TICKERS_PER_RUN,
    DEFAULT_STALE_DAYS,
    MARKET_REGISTRY,
    grow_library,
    library_status,
    list_markets,
    refresh_constituents,
)
from .library_ingest_dispatch import (
    FTSE_MAINTENANCE_MAX_BODIES,
    FTSE_MAINTENANCE_MAX_RUNTIME_SECONDS,
    FTSE_MAINTENANCE_MAX_TARGETS,
)
from .library_retention import DEFAULT_MONTHLY_UNTIL_DAYS, DEFAULT_RETENTION_DAYS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ftse-library",
        description=(
            "Progressively grow and maintain offline multi-market data libraries "
            "without changing the live FTSE 350 screening path."
        ),
    )
    common = argparse.ArgumentParser(add_help=False)

    def _add_shared_flags(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--root",
            type=Path,
            default=DEFAULT_LIBRARY_ROOT,
            help=f"Library root (default: {DEFAULT_LIBRARY_ROOT})",
        )
        target.add_argument(
            "--policy",
            type=Path,
            default=DEFAULT_POLICY_PATH,
            help=f"Library/budget policy JSON (default: {DEFAULT_POLICY_PATH})",
        )

    _add_shared_flags(common)
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", parents=[common], help="List registered markets")
    list_p.set_defaults(func=cmd_list)

    status_p = sub.add_parser("status", parents=[common], help="Show library coverage / freshness")
    status_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: all registered)",
    )
    status_p.add_argument("--json", action="store_true", help="Emit JSON")
    status_p.set_defaults(func=cmd_status)

    refresh_p = sub.add_parser(
        "refresh-constituents",
        help="Refresh constituent lists only (no Yahoo metrics)",
    )
    refresh_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: focus market from policy)",
    )
    refresh_p.set_defaults(func=cmd_refresh)

    grow_p = sub.add_parser(
        "grow",
        parents=[common],
        help="Refresh constituents (optional) and fetch a budgeted set of ticker metrics",
    )
    grow_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: single focus market from policy)",
    )
    grow_p.add_argument(
        "--max-tickers",
        type=int,
        default=None,
        help="Max tickers to fetch per market (default: from budget policy)",
    )
    grow_p.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"Prefer re-fetch when metrics older than this many days (default: {DEFAULT_STALE_DAYS})",
    )
    grow_p.add_argument(
        "--skip-constituents",
        action="store_true",
        help="Do not refresh constituent lists this run",
    )
    grow_p.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=(
            "Dense PIT window in days: keep every dated metrics/constituents snapshot "
            f"(default: {DEFAULT_RETENTION_DAYS}). Older ages thin to monthly then quarterly; "
            "0 disables pruning."
        ),
    )
    grow_p.add_argument(
        "--retention-monthly-until-days",
        type=int,
        default=DEFAULT_MONTHLY_UNTIL_DAYS,
        help=(
            "After the dense window, keep one snapshot per month until this age in days "
            f"(default: {DEFAULT_MONTHLY_UNTIL_DAYS}); older ages keep one per quarter forever."
        ),
    )
    grow_p.add_argument(
        "--all-markets",
        action="store_true",
        help="Override focus policy and grow every registered market (not recommended)",
    )
    grow_p.add_argument("--json", action="store_true", help="Emit JSON summary")
    grow_p.set_defaults(func=cmd_grow)

    policy_p = sub.add_parser(
        "policy", parents=[common], help="Show or update library focus / budget policy"
    )
    policy_p.add_argument("--json", action="store_true")
    policy_p.add_argument("--focus", default="", help="Set focus market id (e.g. sp500)")
    policy_p.add_argument(
        "--plan-monthly-usd",
        type=float,
        default=None,
        help="Cursor subscription included pool USD (metadata; e.g. 20 for Pro)",
    )
    policy_p.add_argument(
        "--weekly-ops-cap-usd",
        type=float,
        default=None,
        help="Ring-fenced USD envelope for orchestrator weekly runs (email + ladder)",
    )
    policy_p.add_argument(
        "--refresh-day",
        type=int,
        default=None,
        help="Day of month when Cursor plan credits refresh (1-28)",
    )
    policy_p.set_defaults(func=cmd_policy)

    surplus_p = sub.add_parser(
        "cycle-surplus",
        parents=[common],
        help="Assess / apply / review a cycle-end weekly_ops bump from leftover plan credit",
    )
    surplus_p.add_argument(
        "surplus_action",
        choices=["assess", "apply", "review"],
        help="assess leftover, apply a provisional weekly_ops bump, or review keep/revert",
    )
    surplus_p.add_argument(
        "--unused-fraction",
        type=float,
        default=None,
        help="Declared unused Cursor plan fraction from the usage page (e.g. 0.40)",
    )
    surplus_p.add_argument(
        "--unused-usd",
        type=float,
        default=None,
        help=(
            "Declared leftover USD from the usage page. Prefer this when leftover "
            "exceeds listed plan_monthly_usd (do not invent a new Ultra price)."
        ),
    )
    surplus_p.add_argument(
        "--replace-provisional",
        action="store_true",
        help=(
            "Rebase a new bump on the original weekly_ops cap instead of stacking "
            "on an already-applied provisional raise"
        ),
    )
    surplus_p.add_argument(
        "--plan-monthly-usd",
        type=float,
        default=None,
        help="Plan included pool USD for surplus math (default: 200 Ultra, else policy)",
    )
    surplus_p.add_argument(
        "--transfer-fraction",
        type=float,
        default=None,
        help="Share of unused monthly credit to move into weekly_ops (default: 0.25)",
    )
    surplus_p.add_argument(
        "--max-weekly-bump-usd",
        type=float,
        default=None,
        help="Hard cap on the weekly_ops raise (default: 20)",
    )
    surplus_p.add_argument(
        "--plan-credit-share-cap",
        type=float,
        default=None,
        help=(
            "Max weekly_ops as a fraction of plan_monthly_usd (default: 0.15). "
            "Leaves included credit for development and other projects."
        ),
    )
    surplus_p.add_argument(
        "--update-plan-metadata",
        action="store_true",
        help="On apply, write plan_name / plan_monthly_usd into policy (metadata only)",
    )
    surplus_p.add_argument(
        "--plan-name",
        default=None,
        help="plan_name to store when --update-plan-metadata is set (e.g. 'Cursor Ultra')",
    )
    surplus_p.add_argument(
        "--keep",
        action="store_true",
        help="On review: keep the provisional weekly_ops bump",
    )
    surplus_p.add_argument(
        "--revert",
        action="store_true",
        help="On review: revert weekly_ops_cap to the pre-bump value",
    )
    surplus_p.add_argument("--json", action="store_true")
    surplus_p.set_defaults(func=cmd_cycle_surplus)

    review_p = sub.add_parser(
        "review-model",
        help="Re-select the cheapest Cursor agent model available to this key",
    )
    review_p.add_argument(
        "--api-key",
        default=os.environ.get("CURSOR_API_KEY"),
        help="Cursor API key (default: CURSOR_API_KEY)",
    )
    review_p.add_argument("--json", action="store_true")
    review_p.set_defaults(func=cmd_review_model)

    screen_p = sub.add_parser(
        "screen",
        help="Run offline screen-lite on library metrics for the focus market",
    )
    screen_p.add_argument(
        "--markets",
        default="",
        help="Market id (default: focus market from policy)",
    )
    screen_p.add_argument("--json", action="store_true")
    screen_p.set_defaults(func=cmd_screen)

    sim_p = sub.add_parser(
        "sim",
        parents=[common],
        help="Observe-only offline paper sim from screen-lite archives (library markets)",
    )
    sim_p.add_argument(
        "--markets",
        default="sp500",
        help="Market id (default: sp500)",
    )
    sim_p.add_argument(
        "--benchmark",
        default="",
        help="Benchmark ticker override (default: per-market, e.g. ^GSPC for sp500)",
    )
    sim_p.add_argument("--capital", type=float, default=1000.0)
    sim_p.add_argument(
        "--trade-cost",
        type=float,
        default=None,
        help=(
            "Per-side trade cost override (decimal). Default: fair market assumption "
            "from ftse-trading-costs (not the live FTSE 3%% stress case)."
        ),
    )
    sim_p.add_argument("--max-positions", type=int, default=5)
    sim_p.add_argument(
        "--no-rebuild-snapshots",
        action="store_true",
        help="Reuse existing screen/history snapshots",
    )
    sim_p.add_argument("--json", action="store_true")
    sim_p.set_defaults(func=cmd_sim)

    shard_status_p = sub.add_parser(
        "shard-status",
        parents=[common],
        help="Show market-shard phase gates, blockers, and advancement triggers",
    )
    shard_status_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: observe + weekly-paper policy markets)",
    )
    shard_status_p.add_argument("--json", action="store_true")
    shard_status_p.set_defaults(func=cmd_shard_status)

    shard_paper_p = sub.add_parser(
        "shard-paper",
        parents=[common],
        help="Run Phase 2 weekly paper shard batch for eligible markets",
    )
    shard_paper_p.add_argument(
        "--markets",
        default="sp500,euro_stoxx50",
        help="Comma-separated market ids",
    )
    shard_paper_p.add_argument(
        "--force",
        action="store_true",
        help="Force paper-auto pass even outside settle window",
    )
    shard_paper_p.add_argument("--json", action="store_true")
    shard_paper_p.set_defaults(func=cmd_shard_paper)

    ingest_loop_p = sub.add_parser(
        "ingest-loop",
        parents=[common],
        help="Weekday buy-tier filing deepen for a library market (euro_depth pilot)",
    )
    ingest_loop_p.add_argument(
        "--market",
        default="euro_depth",
        help="Library market id (default: euro_depth)",
    )
    ingest_loop_p.add_argument("--max-targets", type=int, default=12)
    ingest_loop_p.add_argument("--max-runtime-seconds", type=float, default=2100.0)
    ingest_loop_p.add_argument(
        "--per-ticker-max-seconds",
        type=float,
        default=320.0,
        help=(
            "Weekday mid-ticker wall-clock cap (all library markets). "
            "Disabled automatically for --pin-ticker / --record-gap-closure. "
            "Set 0 to disable."
        ),
    )
    ingest_loop_p.add_argument("--max-bodies", type=int, default=20)
    ingest_loop_p.add_argument("--stall-runs", type=int, default=2)
    ingest_loop_p.add_argument("--micro-compile-max-tasks", type=int, default=1)
    ingest_loop_p.add_argument(
        "--record-gap-closure",
        action="store_true",
        help="Record run in ingest_gap_closure_runs.json for horizon/analysis review",
    )
    ingest_loop_p.add_argument(
        "--record-trial",
        action="store_true",
        help="Deprecated alias for --record-gap-closure",
    )
    ingest_loop_p.add_argument("--gap-closure-title", default="")
    ingest_loop_p.add_argument("--gap-closure-summary", default="")
    ingest_loop_p.add_argument(
        "--gap-closure-review-trigger",
        default="horizon_scan",
        choices=["horizon_scan", "analysis_review", "both"],
    )
    ingest_loop_p.add_argument("--gap-closure-parent-id", default="")
    ingest_loop_p.add_argument("--gap-closure-trigger", default="")
    ingest_loop_p.add_argument("--pin-ticker", default="")
    ingest_loop_p.add_argument(
        "--discovery-scan",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run listing-only discovery before deepen (default: on in maintenance mode)",
    )
    ingest_loop_p.add_argument(
        "--maintenance-mode",
        action="store_true",
        help="Maintenance pass: 4 targets, discovery scan on by default",
    )
    ingest_loop_p.add_argument("--json", action="store_true")
    ingest_loop_p.add_argument(
        "--json-path",
        type=Path,
        default=None,
        help="Write result JSON to this path (avoids stdout log pollution in CI)",
    )
    ingest_loop_p.set_defaults(func=cmd_library_ingest_loop)

    ingest_dev_p = sub.add_parser(
        "ingest-deviations",
        help=(
            "List / approve / dismiss post-ingest deviations "
            "(dashboard Automation tab; approve writes an intensive pin)"
        ),
    )
    ingest_dev_p.add_argument(
        "action",
        choices=["list", "approve", "dismiss"],
        help="list open rows, or approve/dismiss <id>",
    )
    ingest_dev_p.add_argument("deviation_id", nargs="?", default="", help="Deviation id")
    ingest_dev_p.add_argument(
        "--store",
        type=Path,
        default=None,
        help="ingest_deviations.json path (default: docs/data/ingest_deviations.json)",
    )
    ingest_dev_p.add_argument(
        "--pins-path",
        type=Path,
        default=None,
        help="library_ingest_pins.json path when approving",
    )
    ingest_dev_p.add_argument("--note", default="", help="Optional review note")
    ingest_dev_p.add_argument("--json", action="store_true")
    ingest_dev_p.set_defaults(func=cmd_library_ingest_deviations)

    ingest_followup_p = sub.add_parser(
        "ingest-gap-closure-followup",
        parents=[common],
        help=(
            "Evaluate automatic intensive gap-closure after a library ingest "
            "stall or zero-improve complete run"
        ),
    )
    ingest_followup_p.add_argument(
        "--market",
        default="",
        help="Library market id (default: market_id from --loop-json, else euro_depth)",
    )
    ingest_followup_p.add_argument(
        "--loop-json",
        type=Path,
        default=None,
        help=(
            "Path to ingest-loop JSON, or sprint/maintenance JSON with a "
            "results[] of per-market loop payloads"
        ),
    )
    ingest_followup_p.add_argument(
        "--pin-ticker",
        default="",
        help="Prefer this sticky ticker when it still has filing gaps",
    )
    ingest_followup_p.add_argument(
        "--tasks-path",
        type=Path,
        default=Path("docs/data/engineering_tasks.json"),
        help="Engineering tasks JSON used to skip when a library ingest task is open",
    )
    ingest_followup_p.add_argument(
        "--runs-path",
        type=Path,
        default=None,
        help="ingest_gap_closure_runs.json (default: committed path)",
    )
    ingest_followup_p.add_argument("--json", action="store_true")
    ingest_followup_p.add_argument(
        "--json-path",
        type=Path,
        default=None,
        help="Write result JSON to this path (avoids stdout log pollution in CI)",
    )
    ingest_followup_p.set_defaults(func=cmd_library_ingest_gap_closure_followup)

    euro_dispatch_p = sub.add_parser(
        "euro-ingest-dispatch",
        parents=[common],
        help="Evaluate euro_depth ingest completion gate and cron throttle state",
    )
    euro_dispatch_p.add_argument(
        "--market",
        default="euro_depth",
        help="Library market id (default: euro_depth)",
    )
    euro_dispatch_p.add_argument(
        "--refresh",
        action="store_true",
        help="Persist dispatch JSON to docs/data/library/euro_ingest_dispatch.json",
    )
    euro_dispatch_p.add_argument(
        "--sync-cron",
        action="store_true",
        help="Enable/disable cron-job.org euro ingest + ladder jobs (needs CRONJOB_API_KEY)",
    )
    euro_dispatch_p.add_argument("--json", action="store_true")
    euro_dispatch_p.add_argument(
        "--json-path",
        type=Path,
        default=None,
        help="Write dispatch JSON to this path (avoids stdout log pollution in CI)",
    )
    euro_dispatch_p.set_defaults(func=cmd_euro_ingest_dispatch)

    ingest_maint_p = sub.add_parser(
        "ingest-maintenance",
        parents=[common],
        help="FTSE-standard scan-then-target maintenance for library markets at filing parity",
    )
    ingest_maint_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: parity markets from policy + focus)",
    )
    ingest_maint_p.add_argument("--max-targets", type=int, default=FTSE_MAINTENANCE_MAX_TARGETS)
    ingest_maint_p.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=FTSE_MAINTENANCE_MAX_RUNTIME_SECONDS,
    )
    ingest_maint_p.add_argument("--max-bodies", type=int, default=FTSE_MAINTENANCE_MAX_BODIES)
    ingest_maint_p.add_argument(
        "--no-discovery-scan",
        action="store_true",
        help="Skip listing-only discovery pass",
    )
    ingest_maint_p.add_argument("--json", action="store_true")
    ingest_maint_p.add_argument(
        "--json-path",
        type=Path,
        default=None,
        help="Write result JSON to this path (avoids stdout log pollution in CI)",
    )
    ingest_maint_p.set_defaults(func=cmd_library_ingest_maintenance)

    ingest_sprint_p = sub.add_parser(
        "ingest-sprint",
        parents=[common],
        help="Parallel sprint ingest for ingest_parallel_sprint markets (non-focus)",
    )
    ingest_sprint_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: ingest_parallel_sprint with gaps)",
    )
    ingest_sprint_p.add_argument(
        "--parallel-stream",
        type=int,
        default=1,
        choices=[1, 2],
        help="Parallel sprint stream (1=ingest_parallel_sprint, 2=ingest_parallel_sprint_2)",
    )
    ingest_sprint_p.add_argument("--max-targets", type=int, default=24)
    ingest_sprint_p.add_argument("--max-runtime-seconds", type=float, default=2100.0)
    ingest_sprint_p.add_argument("--max-bodies", type=int, default=20)
    ingest_sprint_p.add_argument(
        "--head-idle",
        action="store_true",
        help="Head workflow is not running (GHA already waited). Disables peak-hour fallback skip.",
    )
    ingest_sprint_p.add_argument(
        "--higher-spare-in-progress",
        action="store_true",
        help="A higher-priority spare stream is still running",
    )
    ingest_sprint_p.add_argument("--json", action="store_true")
    ingest_sprint_p.add_argument(
        "--json-path",
        type=Path,
        default=None,
        help="Write result JSON to this path (avoids stdout log pollution in CI)",
    )
    ingest_sprint_p.set_defaults(func=cmd_library_ingest_sprint)

    ingest_sched_p = sub.add_parser(
        "ingest-schedule",
        parents=[common],
        help="Evaluate P2 ingest scheduler (wait / skip / run + leftover budget)",
    )
    ingest_sched_p.add_argument(
        "--stream",
        type=int,
        default=1,
        choices=[1, 2],
        dest="parallel_stream",
    )
    ingest_sched_p.add_argument("--max-targets", type=int, default=24)
    ingest_sched_p.add_argument("--max-runtime-seconds", type=float, default=2100.0)
    ingest_sched_p.add_argument(
        "--head-in-progress",
        action="store_true",
        help="Focus ingest workflow is queued or in progress",
    )
    ingest_sched_p.add_argument(
        "--head-idle",
        action="store_true",
        help="Focus ingest workflow is not running",
    )
    ingest_sched_p.add_argument(
        "--higher-spare-in-progress",
        action="store_true",
    )
    ingest_sched_p.add_argument(
        "--waited-seconds",
        type=float,
        default=0.0,
        help="Seconds already spent waiting on a predecessor",
    )
    ingest_sched_p.add_argument("--json", action="store_true")
    ingest_sched_p.add_argument("--json-path", type=Path, default=None)
    ingest_sched_p.set_defaults(func=cmd_library_ingest_schedule)

    learning_depth_p = sub.add_parser(
        "learning-depth",
        parents=[common],
        help=("Assess FTSE-equivalent filing + trajectory depth (canonical screen research only)"),
    )
    learning_depth_p.add_argument(
        "--market",
        default="sp500",
        help="Library market id (default: sp500)",
    )
    learning_depth_p.add_argument(
        "--write",
        action="store_true",
        help="Persist markets/{id}/learning_depth.json",
    )
    learning_depth_p.add_argument(
        "--write-trajectory",
        action="store_true",
        help="Refresh markets/{id}/screen/trajectory_*.json from existing snapshots",
    )
    learning_depth_p.add_argument("--json", action="store_true")
    learning_depth_p.add_argument(
        "--json-path",
        type=Path,
        default=None,
        help="Write result JSON to this path",
    )
    learning_depth_p.set_defaults(func=cmd_library_learning_depth)

    shard_weekday_p = sub.add_parser(
        "shard-weekday",
        parents=[common],
        help="Run Phase 3 weekday paper shard batch for Phase-2-ready markets",
    )
    shard_weekday_p.add_argument(
        "--markets",
        default="euro_depth",
        help="Comma-separated market ids",
    )
    shard_weekday_p.add_argument("--json", action="store_true")
    shard_weekday_p.set_defaults(func=cmd_shard_weekday)

    ladder_p = sub.add_parser(
        "ladder",
        help="Run offline ladder: fundamentals → maintenance → screen-lite → research → graduate",
    )
    ladder_p.add_argument("--skip-grow", action="store_true")
    ladder_p.add_argument("--skip-screen", action="store_true")
    ladder_p.add_argument("--skip-research", action="store_true")
    ladder_p.add_argument("--skip-maintenance", action="store_true")
    ladder_p.add_argument("--skip-graduation", action="store_true")
    ladder_p.add_argument(
        "--dry-run-research",
        action="store_true",
        help="List research targets without calling the Cursor agent",
    )
    ladder_p.add_argument(
        "--max-tickers",
        type=int,
        default=None,
        help="Override fundamentals grow budget for this run",
    )
    ladder_p.add_argument(
        "--api-key",
        default=None,
        help="Cursor API key for selective research (default: CURSOR_API_KEY_V2 then CURSOR_API_KEY)",
    )
    ladder_p.add_argument(
        "--unrestricted-budget",
        action="store_true",
        help="Disable weekly research cap for this run (uses ad_hoc checkpoint pool only)",
    )
    ladder_p.add_argument(
        "--checkpoint-usd",
        type=float,
        default=None,
        help="Pause research after this much estimated spend since last approval (default: 60)",
    )
    ladder_p.add_argument(
        "--approve-checkpoint",
        action="store_true",
        help="Reset spend-since-checkpoint after human approval to continue research",
    )
    ladder_p.add_argument(
        "--spend-pool",
        choices=("weekly_ops", "ad_hoc"),
        default=None,
        help=(
            "Spend ledger pool: weekly_ops (orchestrator Sunday bundle, default) or "
            "ad_hoc (checkpoint-gated manual depth passes; implied by --unrestricted-budget)"
        ),
    )
    ladder_p.add_argument("--json", action="store_true")
    ladder_p.set_defaults(func=cmd_ladder)

    grad_p = sub.add_parser(
        "graduate",
        help="Evaluate focus graduation floors and advance queue if met",
    )
    grad_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show evaluation without changing focus_market",
    )
    grad_p.add_argument("--json", action="store_true")
    grad_p.set_defaults(func=cmd_graduate)

    macro_p = sub.add_parser(
        "macro",
        help=(
            "Refresh or show offline macro / regime context "
            "(research & paper notes only — not scoring)"
        ),
    )
    macro_p.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch latest Yahoo markers and write docs/data/library/macro/",
    )
    macro_p.add_argument(
        "--market",
        default="",
        help="Show sliced context for one market id (e.g. asx200)",
    )
    macro_p.add_argument("--json", action="store_true")
    macro_p.set_defaults(func=cmd_macro)

    overlaps_p = sub.add_parser(
        "overlaps",
        help="Show exact Yahoo-ticker overlaps across library markets (dedupe identity)",
    )
    overlaps_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: all registered except unused)",
    )
    overlaps_p.add_argument(
        "--live",
        action="store_true",
        help="Fetch constituents from Wikipedia now (else use library manifests)",
    )
    overlaps_p.add_argument("--json", action="store_true")
    overlaps_p.set_defaults(func=cmd_overlaps)

    t212_cat = sub.add_parser(
        "t212-catalogue",
        help=(
            "Fetch Trading 212 instrument catalogue via API "
            "(requires TRADING212_API_KEY / TRADING212_API_SECRET; metadata scope)"
        ),
    )
    t212_cat.add_argument(
        "--env",
        default="",
        help="demo|live (default: TRADING212_ENV or demo)",
    )
    t212_cat.add_argument(
        "--skip-exchanges",
        action="store_true",
        help="Do not also fetch /equity/metadata/exchanges",
    )
    t212_cat.add_argument("--json", action="store_true")
    t212_cat.set_defaults(func=cmd_t212_catalogue)

    t212_p = sub.add_parser(
        "t212-overlay",
        help=(
            "Build Trading 212 coverage overlay for library markets "
            "(catalogue hits + venue allowlist fallback)"
        ),
    )
    t212_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: all offline library markets)",
    )
    t212_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute summary without writing by_market artifacts",
    )
    t212_p.add_argument("--json", action="store_true")
    t212_p.set_defaults(func=cmd_t212_overlay)

    t212_align = sub.add_parser(
        "t212-align",
        help=(
            "Assess offline library vs Trading 212 catalogue "
            "(writes t212_coverage/alignment_report.json)"
        ),
    )
    t212_align.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: all offline library markets)",
    )
    t212_align.add_argument(
        "--allowlist-only",
        action="store_true",
        help="Ignore any local catalogue and report allowlist-assumed coverage only",
    )
    t212_align.add_argument(
        "--dry-run",
        action="store_true",
        help="Print report without writing alignment_report.json",
    )
    t212_align.add_argument("--json", action="store_true")
    t212_align.set_defaults(func=cmd_t212_align)

    ii_p = sub.add_parser(
        "ii-overlay",
        help="Alias for t212-overlay (Trading 212 is the tradable north star)",
    )
    ii_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: all offline library markets)",
    )
    ii_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute summary without writing by_market artifacts",
    )
    ii_p.add_argument("--json", action="store_true")
    ii_p.set_defaults(func=cmd_t212_overlay)

    firds_p = sub.add_parser(
        "firds-filter",
        help=(
            "Filter a public FCA/ESMA FIRDS XML/CSV dump to coverage-policy online MICs "
            "(venue admission ≠ Trading 212 order acceptance — prefer t212-catalogue)"
        ),
    )
    firds_p.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to FIRDS .xml or .csv file",
    )
    firds_p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max rows to keep (for smoke tests)",
    )
    firds_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts without writing firds_ii_mics.json/csv",
    )
    firds_p.add_argument("--json", action="store_true")
    firds_p.set_defaults(func=cmd_firds_filter)

    unavail_p = sub.add_parser(
        "unavailable-watch",
        help=(
            "List / mark / restore tickers unavailable to trade on II "
            "(kept watching; excluded from suggested trades)"
        ),
    )
    unavail_p.add_argument(
        "action",
        choices=["list", "mark", "restore"],
        help="list | mark <ticker> | restore <ticker>",
    )
    unavail_p.add_argument("ticker", nargs="?", default="", help="Ticker for mark/restore")
    unavail_p.add_argument("--name", default="", help="Optional company name when marking")
    unavail_p.add_argument(
        "--reason",
        default="unavailable_on_t212",
        help="Reason code (default: unavailable_on_t212)",
    )
    unavail_p.add_argument("--json", action="store_true")
    unavail_p.set_defaults(func=cmd_unavailable_watch)

    reingest_p = sub.add_parser(
        "reingest-filings",
        help="Re-ingest primary filings for existing research memos (backfill regimes)",
    )
    reingest_p.add_argument(
        "--markets",
        default="asx200,euro_stoxx50",
        help="Comma-separated market ids (default: asx200,euro_stoxx50)",
    )
    reingest_p.add_argument(
        "--all",
        action="store_true",
        help="Re-ingest every memo, not only unsupported/missing indexes",
    )
    reingest_p.add_argument(
        "--api-key",
        default=os.environ.get("TICKER_API_KEY") or os.environ.get("CURSOR_API_KEY"),
        help="Optional Ticker API key for UK RNS (default: TICKER_API_KEY)",
    )
    reingest_p.add_argument("--json", action="store_true")
    reingest_p.set_defaults(func=cmd_reingest_filings)

    repair_p = sub.add_parser(
        "repair-research",
        help="Re-ingest filings and re-memo library research tickers (e.g. batch 1 repair)",
    )
    repair_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: all library markets)",
    )
    repair_p.add_argument(
        "--batch-date",
        default="2026-07-25",
        help="Only repair memos updated on this date (YYYY-MM-DD)",
    )
    repair_p.add_argument(
        "--rememo-all",
        action="store_true",
        help="Re-memo every target after re-ingest (default: only when sources improved or flagged)",
    )
    repair_p.add_argument(
        "--api-key",
        default=None,
        help="Cursor API key (default: CURSOR_API_KEY_V2 then CURSOR_API_KEY)",
    )
    repair_p.add_argument("--json", action="store_true")
    repair_p.set_defaults(func=cmd_repair_research)

    deepen_p = sub.add_parser(
        "deepen-thin",
        help="Re-ingest filings and gap-fill source deepen for thin library memos (0 bodies)",
    )
    deepen_p.add_argument(
        "--markets",
        default="asx200,euro_stoxx50",
        help="Comma-separated market ids (default: asx200,euro_stoxx50)",
    )
    deepen_p.add_argument(
        "--max-with-body",
        type=int,
        default=0,
        help="Include memos with at most this many indexed filing bodies (default: 0)",
    )
    deepen_p.add_argument(
        "--rememo",
        action="store_true",
        help="Re-memo tickers when filing bodies improve (requires Cursor API key)",
    )
    deepen_p.add_argument(
        "--rememo-all",
        action="store_true",
        help="Re-memo every target after deepen (not only when bodies improved)",
    )
    deepen_p.add_argument(
        "--api-key",
        default=None,
        help="Cursor API key for optional re-memo (default: CURSOR_API_KEY_V2 then CURSOR_API_KEY)",
    )
    deepen_p.add_argument("--json", action="store_true")
    deepen_p.set_defaults(func=cmd_deepen_thin)

    retry_p = sub.add_parser(
        "retry-failed",
        help="Re-fetch library metrics rows that currently have errors",
    )
    retry_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: all registered offline markets)",
    )
    retry_p.add_argument("--json", action="store_true")
    retry_p.set_defaults(func=cmd_retry_failed)

    prune_p = sub.add_parser(
        "prune-screen",
        help=(
            "Prune dated screen-lite history with decreasing resolution "
            "(dense → monthly → quarterly; also thins signal_history.csv)"
        ),
    )
    prune_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: all offline markets with screens)",
    )
    prune_p.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=(
            "Dense window in days: keep every dated screen run "
            f"(default: {DEFAULT_RETENTION_DAYS}; 0 disables pruning)"
        ),
    )
    prune_p.add_argument(
        "--retention-monthly-until-days",
        type=int,
        default=DEFAULT_MONTHLY_UNTIL_DAYS,
        help=(
            "After the dense window, keep one run per month until this age "
            f"(default: {DEFAULT_MONTHLY_UNTIL_DAYS}); older ages keep one per quarter"
        ),
    )
    prune_p.add_argument("--json", action="store_true")
    prune_p.set_defaults(func=cmd_prune_screen)

    auto_p = sub.add_parser(
        "automation-status",
        help="Assemble dashboard automation settings + dated achievement log",
    )
    auto_p.add_argument(
        "--output",
        type=Path,
        default=Path("docs/data/automation.json"),
        help="Write path (default: docs/data/automation.json)",
    )
    auto_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary without writing",
    )
    auto_p.add_argument("--json", action="store_true")
    auto_p.set_defaults(func=cmd_automation_status)

    return parser


def _parse_markets(raw: str) -> list[str] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return [part.strip() for part in text.split(",") if part.strip()]


def cmd_list(args: argparse.Namespace) -> int:
    policy = load_policy(args.policy)
    print(f"Library root: {args.root}")
    print(f"Focus market: {policy.get('focus_market')}")
    print()
    for row in list_markets():
        mid = row["market_id"]
        marker = " ← focus" if mid == policy.get("focus_market") else ""
        print(f"{mid:16}  {row['label']}{marker}")
        print(
            f"{'':16}  exchange={row['exchange']}  currency={row['currency']}  "
            f"source={row['constituent_source']}"
        )
        print()
    print("Offline only — not used by the live FTSE 350 screen until stage 4.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    markets = _parse_markets(args.markets)
    rows = library_status(args.root, markets=markets, stale_days=DEFAULT_STALE_DAYS)
    if args.json:
        print(json.dumps({"root": str(args.root), "markets": rows}, indent=2))
        return 0
    print(f"Library root: {args.root}")
    print()
    for row in rows:
        mid = row["market"]
        print(
            f"{mid}: constituents={row.get('ticker_count', 0)}  "
            f"metrics={row.get('coverage_count', 0)}/{row.get('ticker_count', 0)}  "
            f"coverage={round(100 * float(row.get('coverage_pct') or 0), 1)}%  "
            f"never_fetched={row.get('never_fetched', 0)}  "
            f"stale={row.get('stale', 0)}  "
            f"fresh={row.get('fresh', 0)}"
        )
        print(
            f"  constituents_asof={row.get('last_constituents_refresh') or '—'}  "
            f"metrics_asof={row.get('last_metrics_refresh') or '—'}"
        )
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    markets = _parse_markets(args.markets) or focus_markets(load_policy(args.policy))
    for mid in markets:
        manifest = refresh_constituents(args.root, mid)
        print(
            f"{mid}: {manifest.get('ticker_count', 0)} constituents "
            f"(asof {manifest.get('last_constituents_refresh')})"
        )
    return 0


def cmd_grow(args: argparse.Namespace) -> int:
    policy = load_policy(args.policy)
    plan = grow_ticker_budget(policy, base_max_tickers=DEFAULT_MAX_TICKERS_PER_RUN)
    if args.all_markets:
        markets = list(MARKET_REGISTRY)
    else:
        markets = _parse_markets(args.markets) or plan["focus_markets"]
    max_tickers = (
        int(args.max_tickers) if args.max_tickers is not None else int(plan["max_tickers"])
    )
    results = grow_library(
        args.root,
        markets=markets,
        max_tickers_per_run=max_tickers,
        stale_days=int(args.stale_days),
        refresh_constituents_first=not bool(args.skip_constituents),
        retention_days=int(args.retention_days),
        monthly_until_days=int(args.retention_monthly_until_days),
    )
    status_rows = library_status(args.root, markets=markets, stale_days=int(args.stale_days))
    by_market = {r["market"]: r for r in status_rows}
    payload = {
        "root": str(args.root),
        "policy": {
            "focus_markets": markets,
            "max_tickers": max_tickers,
            "surplus_day": plan["surplus_day"],
            "weekly_ops_cap_usd": plan["weekly_ops_cap_usd"],
            "research_model": plan["research_model"],
        },
        "last_grow": results,
        "markets": status_rows,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"Library root: {args.root}")
    print(
        f"Focus: {', '.join(markets)}  max_tickers={max_tickers}  "
        f"surplus_day={plan['surplus_day']}  "
        f"weekly_ops_cap=${plan['weekly_ops_cap_usd']}  "
        f"budget_flag={plan.get('budget_flag')}  "
        f"model={plan['research_model']}"
    )
    print()
    for row in results:
        mid = row["market"]
        st = by_market.get(mid) or {}
        print(
            f"{mid}: selected={len(row.get('selected') or [])}  "
            f"updated={row.get('updated', 0)}  errors={row.get('errors', 0)}  "
            f"coverage={row.get('coverage_count', 0)}/{row.get('ticker_count', 0)} "
            f"({round(100 * float(row.get('coverage_pct') or 0), 1)}%)"
        )
        print(
            f"  never_fetched={st.get('never_fetched', 0)}  "
            f"stale={st.get('stale', 0)}  fresh={st.get('fresh', 0)}"
        )
    return 0


def cmd_policy(args: argparse.Namespace) -> int:
    from .agent_model_policy import weekly_ops_budget_status
    from .library_graduation import graduated_market_ids

    policy = load_policy(args.policy)
    changed = False
    if args.focus:
        if args.focus not in MARKET_REGISTRY:
            print(f"Unknown market {args.focus!r}; known: {', '.join(MARKET_REGISTRY)}")
            return 1
        policy["focus_market"] = args.focus
        changed = True
    budget = dict(policy.get("budget") or {})
    if args.plan_monthly_usd is not None:
        budget["plan_monthly_usd"] = float(args.plan_monthly_usd)
        changed = True
    if args.weekly_ops_cap_usd is not None:
        requested = float(args.weekly_ops_cap_usd)
        budget["weekly_ops_cap_usd"] = requested
        changed = True
        monthly = float(budget.get("plan_monthly_usd") or policy.get("budget", {}).get("plan_monthly_usd") or 0.0)
        share = float(
            budget.get("weekly_ops_plan_credit_share_cap")
            or DEFAULT_WEEKLY_OPS_PLAN_CREDIT_SHARE_CAP
        )
        ceiling = round(max(0.0, monthly * share), 2)
        if monthly > 0 and requested > ceiling and not args.json:
            print(
                f"Warning: weekly_ops_cap ${requested:.2f} exceeds "
                f"{share:.0%} of plan ${monthly:.0f} (${ceiling:.2f}). "
                "Surplus apply will clamp to that ceiling.",
                file=sys.stderr,
            )
    if args.refresh_day is not None:
        budget["plan_refresh_day_of_month"] = max(1, min(28, int(args.refresh_day)))
        changed = True
    policy["budget"] = budget
    if not (policy.get("research_model") or {}).get("model_id"):
        policy["research_model"] = recommend_cheapest_model().to_dict()
        changed = True
    if changed or not args.policy.exists():
        save_policy(policy, args.policy)
        policy = load_policy(args.policy)
    if args.json:
        payload = dict(policy)
        payload["weekly_ops_status"] = weekly_ops_budget_status(policy)
        print(json.dumps(payload, indent=2))
        return 0
    budget = policy.get("budget") or {}
    model = policy.get("research_model") or {}
    fg = policy.get("focus_graduation") or {}
    graduated = graduated_market_ids(policy)
    ops_status = weekly_ops_budget_status(policy)
    ladder = policy.get("ladder") or {}
    print(f"Policy: {args.policy}")
    print(f"Focus market: {policy.get('focus_market')}")
    print(f"Queue: {', '.join(policy.get('market_queue') or [])}")
    print(
        "FTSE-equivalent markets: "
        + (", ".join(policy.get("ftse_equivalent_markets") or []) or "—")
    )
    print(f"Graduated: {', '.join(graduated) if graduated else '—'}")
    print(
        f"Graduation floors: coverage>={fg.get('min_coverage_pct')}  "
        f"stale<={fg.get('max_stale_pct')}  "
        f"auto_advance={fg.get('auto_advance')}  "
        f"maintenance_max_tickers={fg.get('maintenance_max_tickers')}"
    )
    print(
        f"Subscription: ${budget.get('plan_monthly_usd')}/mo ({budget.get('plan_name') or 'Cursor'})  "
        f"refresh_day={budget.get('plan_refresh_day_of_month')}  "
        f"surplus_day_before_refresh={budget.get('surplus_day_before_refresh')}"
    )
    print(
        f"Spend this week (all pools): ${ops_status.get('estimated_spend_usd_this_week')}  "
        f"cycle=${budget.get('estimated_spend_usd_this_cycle')}"
    )
    print(
        f"Weekly ops (orchestrator): ${ops_status.get('estimated_spend_weekly_ops_usd_this_week')} / "
        f"${ops_status.get('weekly_ops_cap_usd')}  "
        f"remaining=${ops_status.get('remaining_weekly_ops_usd')}  "
        f"flag={ops_status.get('flag')}"
        + (f"  — {ops_status['note']}" if ops_status.get("note") else "")
    )
    print(
        f"Weekly ops plan-credit ceiling: "
        f"{float(ops_status.get('weekly_ops_plan_credit_share_cap') or 0):.0%} of "
        f"${ops_status.get('plan_monthly_usd')} = "
        f"${ops_status.get('weekly_ops_plan_credit_ceiling_usd')}"
        + (
            "  (cap exceeds ceiling)"
            if ops_status.get("weekly_ops_cap_exceeds_plan_share")
            else ""
        )
    )
    print(
        f"Ad hoc checkpoint: ${ladder.get('spend_since_checkpoint_usd', 0)} / "
        f"${ladder.get('spend_checkpoint_usd', 60)}"
    )
    print(f"Research model: {model.get('model_id')} ({model.get('pool')}) — {model.get('reason')}")
    print("Set weekly ops envelope: ftse-library policy --weekly-ops-cap-usd 50")
    return 0


def cmd_cycle_surplus(args: argparse.Namespace) -> int:
    from .cycle_budget_surplus import (
        DEFAULT_ARTIFACT_PATH,
        DEFAULT_MAX_WEEKLY_BUMP_USD,
        DEFAULT_TRANSFER_FRACTION,
        DEFAULT_ULTRA_MONTHLY_USD,
        apply_cycle_surplus,
        assess_cycle_surplus,
        review_cycle_surplus,
        write_cycle_surplus,
    )

    policy = load_policy(args.policy)
    budget = policy.get("budget") or {}
    if args.surplus_action == "assess":
        unused = args.unused_fraction
        unused_usd = args.unused_usd
        if unused is None and unused_usd is None:
            print(
                "--unused-usd or --unused-fraction is required for assess",
                file=sys.stderr,
            )
            return 1
        plan_monthly = args.plan_monthly_usd
        if plan_monthly is None:
            existing = float(budget.get("plan_monthly_usd") or 0.0)
            plan_monthly = existing if existing and existing >= 100 else DEFAULT_ULTRA_MONTHLY_USD
        assessment = assess_cycle_surplus(
            unused_fraction=None if unused is None else float(unused),
            unused_usd=None if unused_usd is None else float(unused_usd),
            plan_monthly_usd=float(plan_monthly),
            transfer_fraction=(
                float(args.transfer_fraction)
                if args.transfer_fraction is not None
                else DEFAULT_TRANSFER_FRACTION
            ),
            max_weekly_bump_usd=(
                float(args.max_weekly_bump_usd)
                if args.max_weekly_bump_usd is not None
                else DEFAULT_MAX_WEEKLY_BUMP_USD
            ),
            plan_credit_share_cap=(
                float(args.plan_credit_share_cap)
                if args.plan_credit_share_cap is not None
                else None
            ),
            replace_provisional=bool(args.replace_provisional),
            policy=policy,
            path=args.policy,
        )
        write_cycle_surplus(assessment)
        if args.json:
            print(json.dumps(assessment, indent=2))
        else:
            unused_frac = assessment.get("unused_fraction")
            frac_txt = (
                f"{float(unused_frac):.0%} of ${assessment['plan_monthly_usd']:.0f}"
                if unused_frac is not None
                else "declared leftover"
            )
            print(
                f"Cycle {assessment['cycle_id']}: unused {frac_txt} → "
                f"${assessment['unused_monthly_usd']:.2f}"
            )
            print(
                f"Transfer {assessment['transfer_fraction']:.0%} = ${assessment['transfer_usd']:.2f} "
                f"(weekly bump ${assessment['weekly_bump_usd']:.2f})"
            )
            print(
                f"Plan-credit weekly-ops ceiling "
                f"{float(assessment.get('plan_credit_share_cap') or 0):.0%} of "
                f"${assessment['plan_monthly_usd']:.0f} = "
                f"${float(assessment.get('plan_credit_ceiling_usd') or 0):.2f}"
                + ("  (ceiling binds)" if assessment.get("ceiling_bound") else "")
            )
            print(
                f"weekly_ops ${assessment['current_weekly_ops_cap_usd']:.2f} → "
                f"${assessment['proposed_weekly_ops_cap_usd']:.2f}  "
                f"action={assessment['action']}  review={assessment['review_cycle_id']}"
            )
            print("Rememo daily cap unchanged. Apply with: ftse-library cycle-surplus apply")
            print(f"Wrote {DEFAULT_ARTIFACT_PATH}")
        return 0

    if args.surplus_action == "apply":
        try:
            applied = apply_cycle_surplus(
                policy_path=args.policy,
                update_plan_metadata=bool(args.update_plan_metadata),
                plan_name=args.plan_name,
                replace_provisional=bool(args.replace_provisional),
            )
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(applied, indent=2))
        else:
            prov = applied.get("provisional") or {}
            print(
                f"Applied provisional weekly_ops "
                f"${prov.get('previous_weekly_ops_cap_usd')} → "
                f"${prov.get('applied_weekly_ops_cap_usd')}  "
                f"review={prov.get('review_cycle_id')}"
            )
            print(f"Wrote {DEFAULT_ARTIFACT_PATH}")
        return 0

    if args.keep and args.revert:
        print("Use only one of --keep or --revert", file=sys.stderr)
        return 1
    keep: bool | None
    if args.keep:
        keep = True
    elif args.revert:
        keep = False
    else:
        keep = None
    reviewed = review_cycle_surplus(keep=keep, policy_path=args.policy)
    if args.json:
        print(json.dumps(reviewed, indent=2))
    else:
        print(
            f"Review action={reviewed.get('action')} recommend={reviewed.get('recommend')} "
            f"due={reviewed.get('review_due')} cycle={reviewed.get('cycle_id')}"
        )
        if reviewed.get("action") == "too_early":
            print(f"Wait until {reviewed.get('review_cycle_id')} before --keep / --revert")
    return 0


def cmd_review_model(args: argparse.Namespace) -> int:
    if not args.api_key:
        # Offline rank from catalog only
        pick = recommend_cheapest_model()
        policy = load_policy(args.policy)
        policy["research_model"] = pick.to_dict()
        save_policy(policy, args.policy)
        result = {"pick": pick.to_dict(), "changed": True, "previous": None, "mode": "catalog"}
    else:
        result = review_model(args.policy, api_key=args.api_key)
        result["mode"] = "live"
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    pick = result["pick"]
    print(
        f"Selected {pick['model_id']} ({pick['pool']}) — {pick['reason']}"
        + (f"  [was {result['previous']}]" if result.get("previous") else "")
    )
    print(f"Saved to {args.policy}")
    print(f"Use with: ftse-research --model {pick['model_id']}")
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    from .library_screen import run_library_screen

    markets = _parse_markets(args.markets) or focus_markets(load_policy(args.policy))
    summaries = []
    for mid in markets:
        result = run_library_screen(args.root, mid)
        summaries.append(result.summary)
        if not args.json:
            print(
                f"{mid}: screened {result.summary['ticker_count']}  "
                f"strong_buy={result.summary.get('strong_buy', 0)}  "
                f"buy={result.summary.get('buy', 0)}  "
                f"shortlist={result.summary.get('shortlist_count', 0)}"
            )
            print(f"  wrote {result.screen_dir}")
    if args.json:
        print(json.dumps({"markets": summaries}, indent=2))
    return 0


def cmd_sim(args: argparse.Namespace) -> int:
    from .library_sim import run_library_observe_sim

    markets = _parse_markets(args.markets) or ["sp500"]
    payloads = []
    for mid in markets:
        result = run_library_observe_sim(
            args.root,
            mid,
            benchmark=args.benchmark or None,
            initial_capital=float(args.capital),
            trade_cost_pct=None if args.trade_cost is None else float(args.trade_cost),
            max_positions=int(args.max_positions),
            rebuild_snapshots=not args.no_rebuild_snapshots,
        )
        payloads.append(result.to_dict())
        if not args.json:
            screen = result.tracks.get("screen_rules") or {}
            cost_pct = screen.get("trade_cost_pct") if isinstance(screen, dict) else None
            print(f"{mid}: benchmark={result.benchmark}  snapshots={result.snapshot_count}")
            if cost_pct is not None:
                print(
                    f"  trade_cost_pct={float(cost_pct):.4%} (fair market default unless overridden)"
                )
            print(
                f"  screen_rules return={screen.get('total_return', 0):+.1%}  "
                f"excess={screen.get('excess_return', 0):+.1%}  "
                f"trades={screen.get('trade_count', 0)}"
            )
            print(f"  {result.comparison_note}")
            print(f"  wrote {args.root}/markets/{mid}/screen/sim/observe_summary.json")
    if args.json:
        print(json.dumps({"markets": payloads}, indent=2))
    return 0


def cmd_shard_status(args: argparse.Namespace) -> int:
    from value_investor.agent_model_policy import load_policy
    from value_investor.library_sim import observe_sim_markets_for_policy
    from value_investor.market_shard_phases import (
        COMMITTED_PHASES_PATH,
        evaluate_market_phase,
        refresh_committed_phase_rollup,
        weekly_paper_shard_capacity_for_policy,
        weekly_paper_shard_markets_for_policy,
    )

    policy = load_policy(args.policy)
    markets = _parse_markets(args.markets)
    if not markets:
        markets = sorted(
            set(observe_sim_markets_for_policy(policy))
            | set(weekly_paper_shard_markets_for_policy(policy))
        )
    rollup = refresh_committed_phase_rollup(
        markets,
        library_root=args.root,
        policy=policy,
        path=COMMITTED_PHASES_PATH,
    )
    if args.json:
        print(json.dumps(rollup, indent=2))
        return 0
    print(f"Phase rollup: {COMMITTED_PHASES_PATH}")
    capacity = weekly_paper_shard_capacity_for_policy(policy)
    slots = weekly_paper_shard_markets_for_policy(policy)
    print(f"Weekly paper capacity: {len(slots)}/{capacity} slots ({', '.join(slots) or '—'})")
    observe = observe_sim_markets_for_policy(policy)
    print(f"Observe sim markets ({len(observe)}): {', '.join(observe) or '—'}")
    for market_id in markets:
        evaluation = (rollup.get("markets") or {}).get(market_id) or evaluate_market_phase(
            market_id,
            library_root=args.root,
            policy=policy,
        )
        blockers = evaluation.get("blockers") or []
        print(
            f"\n{market_id}: phase={evaluation.get('current_phase')}  "
            f"next={evaluation.get('next_phase')}  "
            f"benchmark={evaluation.get('benchmark_ticker')}"
        )
        p1 = evaluation.get("phase1") or {}
        p2 = evaluation.get("phase2") or {}
        print(
            f"  Phase 1: archives={p1.get('screen_archives')}/"
            f"{p1.get('min_archives')}  "
            f"snapshots={p1.get('observe_snapshot_count')}  "
            f"ready={evaluation.get('phase1_ready')}"
        )
        print(
            f"  Phase 2: batches={p2.get('weekly_batch_count')}/"
            f"{p2.get('min_weekly_batches')}  "
            f"beat_control={p2.get('beat_control_latest')}  "
            f"ready={evaluation.get('phase2_ready')}"
        )
        if blockers:
            for blocker in blockers:
                print(f"  blocker: {blocker}")
    return 0


def cmd_shard_paper(args: argparse.Namespace) -> int:
    from value_investor.agent_model_policy import load_policy
    from value_investor.market_paper_shard import run_weekly_market_paper_shard

    policy = load_policy(args.policy)
    markets = _parse_markets(args.markets) or ["sp500", "euro_stoxx50"]
    payloads: dict[str, Any] = {}
    for market_id in markets:
        try:
            result = run_weekly_market_paper_shard(
                market_id,
                library_root=args.root,
                force=True,
                policy=policy,
            )
            payloads[market_id] = result
            if not args.json:
                review = result.get("review") or {}
                phase = result.get("phase") or {}
                print(
                    f"{market_id}: verdict={review.get('verdict')}  "
                    f"phase={phase.get('current_phase')}"
                )
                print(
                    f"  beat_control={review.get('beat_control')}  "
                    f"excess={review.get('primary_excess_after_costs')}"
                )
                for blocker in phase.get("blockers") or []:
                    print(f"  blocker: {blocker}")
        except Exception as exc:  # noqa: BLE001
            payloads[market_id] = {"error": str(exc)}
            if not args.json:
                print(f"{market_id}: ERROR — {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps({"markets": payloads}, indent=2))
    return 0 if all("error" not in row for row in payloads.values()) else 1


def _library_gap_closure_spec(args: argparse.Namespace) -> dict[str, Any] | None:
    if not (args.record_gap_closure or args.record_trial):
        return None
    spec: dict[str, Any] = {
        "title": args.gap_closure_title or "Library ingest gap-closure run",
        "summary": args.gap_closure_summary or "",
        "review_trigger": args.gap_closure_review_trigger,
        "parent_run_id": args.gap_closure_parent_id or "",
    }
    if args.gap_closure_trigger:
        spec["trigger"] = args.gap_closure_trigger
    return spec


def _emit_cli_json(payload: dict[str, Any], args: argparse.Namespace) -> None:
    """Write optional --json-path and/or print --json (FTSE ingest-loop parity)."""
    text = json.dumps(payload, indent=2)
    json_path = getattr(args, "json_path", None)
    if json_path is not None:
        path = Path(json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    if getattr(args, "json", False):
        print(text)
        sys.stdout.flush()


def cmd_library_ingest_loop(args: argparse.Namespace) -> int:
    from value_investor.library_ingest_loop import run_library_ingest_loop

    pin_tickers = [args.pin_ticker.strip().upper()] if str(args.pin_ticker or "").strip() else None
    result = run_library_ingest_loop(
        args.market,
        library_root=args.root,
        max_targets=args.max_targets,
        max_runtime_seconds=args.max_runtime_seconds,
        per_ticker_max_seconds=args.per_ticker_max_seconds,
        max_bodies=args.max_bodies,
        stall_runs=args.stall_runs,
        micro_compile_max_tasks=args.micro_compile_max_tasks,
        pin_tickers=pin_tickers,
        record_gap_closure=_library_gap_closure_spec(args),
        discovery_scan=args.discovery_scan,
        maintenance_mode=args.maintenance_mode,
    )
    payload = result.to_dict()
    if args.json or args.json_path is not None:
        _emit_cli_json(payload, args)
    else:
        gaps_before = int(result.health_before.get("unmeasured_buy_tier") or 0) + int(
            result.health_before.get("zero_body_buy_tier") or 0
        )
        gaps_after = int(result.health_after.get("unmeasured_buy_tier") or 0) + int(
            result.health_after.get("zero_body_buy_tier") or 0
        )
        print(
            f"{args.market}: targets={len(result.targets)} improved={len(result.improved)} "
            f"filing_gaps {gaps_before} → {gaps_after}; stalled={result.stalled}; "
            f"micro_compiled={result.micro_compiled}; "
            f"gap_closure_compiled={result.gap_closure_compiled}; partial={result.partial}"
        )
        for ticker in result.improved:
            print(f"  improved {ticker}")
        if result.micro_compiled:
            print(f"  added tasks: {', '.join(result.micro_compile.get('task_ids') or [])}")
        if result.gap_closure_compiled:
            print(
                f"  gap-closure tasks: "
                f"{', '.join(result.gap_closure_compile.get('task_ids') or [])}"
            )
        for err in result.errors:
            print(f"  error: {err}", file=sys.stderr)
    return 0 if not result.errors or result.improved else 1


def cmd_library_ingest_deviations(args: argparse.Namespace) -> int:
    from value_investor.ingest_deviations import (
        DEFAULT_INGEST_DEVIATIONS_PATH,
        load_ingest_deviations,
        open_ingest_deviations,
        review_ingest_deviation,
        slim_ingest_deviations_for_dashboard,
    )

    store_path = Path(args.store or DEFAULT_INGEST_DEVIATIONS_PATH)
    action = str(args.action or "").strip()
    if action == "list":
        payload = slim_ingest_deviations_for_dashboard(load_ingest_deviations(store_path))
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            open_rows = open_ingest_deviations(store_path)
            print(f"open_count={len(open_rows)} store={store_path}")
            for row in open_rows:
                print(
                    f"  {row.get('id')}: {row.get('ticker')} {row.get('kind')} "
                    f"— {row.get('summary')}"
                )
                reprocess = row.get("reprocess") or {}
                if reprocess.get("approve"):
                    print(f"    approve: {reprocess['approve']}")
        return 0
    deviation_id = str(args.deviation_id or "").strip()
    if not deviation_id:
        print("deviation_id required for approve/dismiss", file=sys.stderr)
        return 2
    try:
        result = review_ingest_deviation(
            deviation_id,
            action=action,
            path=store_path,
            pins_path=args.pins_path,
            note=str(args.note or ""),
        )
    except (KeyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{action} {deviation_id} open_count={result.get('open_count')}")
        pin = result.get("pin") or {}
        if pin.get("pin"):
            print(f"  pin until {pin['pin'].get('until')}")
    return 0


def cmd_library_ingest_gap_closure_followup(args: argparse.Namespace) -> int:
    from value_investor.ingest_gap_closure import (
        evaluate_library_ingest_gap_closure_followups,
    )

    loop_payload: dict[str, Any] = {}
    if args.loop_json is not None:
        loop_path = Path(args.loop_json)
        try:
            loaded = json.loads(loop_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            print(f"Could not read ingest-loop JSON at {loop_path}: {exc}", file=sys.stderr)
            return 1
        if isinstance(loaded, dict):
            loop_payload = loaded
    result = evaluate_library_ingest_gap_closure_followups(
        loop_payload,
        market_id=str(args.market or "").strip() or None,
        prefer_ticker=str(args.pin_ticker or "").strip() or None,
        library_root=args.root,
        tasks_path=args.tasks_path,
        runs_path=args.runs_path,
    )
    if args.json or args.json_path is not None:
        _emit_cli_json(result, args)
    else:
        dispatches = result.get("dispatches")
        if isinstance(dispatches, list):
            print(f"should_dispatch={result.get('should_dispatch')} dispatches={len(dispatches)}")
            for row in dispatches:
                print(
                    f"  {row.get('market_id')}: pin_ticker={row.get('pin_ticker') or ''} "
                    f"trigger={row.get('trigger') or ''}"
                )
        else:
            print(
                f"{result.get('market_id') or args.market or 'euro_depth'}: "
                f"should_dispatch={result.get('should_dispatch')} "
                f"pin_ticker={result.get('pin_ticker') or ''} "
                f"trigger={result.get('trigger') or ''} "
                f"reason={result.get('reason') or ''}"
            )
    return 0


def cmd_library_ingest_maintenance(args: argparse.Namespace) -> int:
    from value_investor.library_ingest_maintenance import run_library_ingest_maintenance

    markets = [m.strip() for m in str(args.markets or "").split(",") if m.strip()] or None
    outcome = run_library_ingest_maintenance(
        library_root=args.root,
        policy_path=args.policy,
        markets=markets,
        max_targets=args.max_targets,
        max_runtime_seconds=args.max_runtime_seconds,
        max_bodies=args.max_bodies,
        discovery_scan=not args.no_discovery_scan,
    )
    payload = outcome.to_dict()
    if args.json or args.json_path is not None:
        _emit_cli_json(payload, args)
    else:
        print(
            f"maintenance: markets={len(outcome.markets)} "
            f"results={len(outcome.results)} errors={len(outcome.errors)}"
        )
        for err in outcome.errors:
            print(f"  error: {err}", file=sys.stderr)
    return 0 if not outcome.errors else 1


def cmd_library_learning_depth(args: argparse.Namespace) -> int:
    from value_investor.agent_model_policy import load_policy
    from value_investor.library_learning_depth import assess_library_learning_depth

    policy = load_policy(args.policy)
    payload = assess_library_learning_depth(
        str(args.market),
        library_root=args.root,
        policy=policy,
        write=bool(args.write),
        write_trajectory=bool(args.write_trajectory),
    )
    _emit_cli_json(payload, args)
    if args.json:
        return 0
    filing = payload.get("filing") or {}
    screen = payload.get("screen") or {}
    traj = payload.get("trajectory") or {}
    print(f"{payload.get('market_id')}: learning_ready={payload.get('learning_ready')}")
    print(
        f"  filing_ready={payload.get('filing_ready')}  "
        f"unmeasured={payload.get('unmeasured_buy_tier')}  "
        f"zero_body={filing.get('zero_body_buy_tier')}  "
        f"thin={filing.get('thin_body_buy_tier')}  "
        f"indexed_without_body={filing.get('indexed_without_body')}"
    )
    print(
        f"  coverage_scope={payload.get('coverage_scope')}  "
        f"ftse_equivalent={payload.get('ftse_equivalent')}"
    )
    print(
        f"  screen files={screen.get('archive_files')}  "
        f"unique_days={screen.get('unique_days')}  "
        f"span_weeks={screen.get('span_weeks')}  "
        f"last={screen.get('last_screen')}  stale={screen.get('stale')}"
    )
    print(
        f"  trajectory_ready={payload.get('trajectory_ready')}  "
        f"events={traj.get('event_count')}  "
        f"boundary={traj.get('boundary_count')}  "
        f"{traj.get('ready_reason')}"
    )
    if payload.get("path"):
        print(f"  wrote {payload['path']}")
    return 0


def cmd_library_ingest_schedule(args: argparse.Namespace) -> int:
    from value_investor.library_ingest_cascade import head_market_id
    from value_investor.library_ingest_dispatch import ingest_parity_met
    from value_investor.library_ingest_escalation import snapshot_library_buy_tier_filing_health
    from value_investor.library_ingest_scheduler import evaluate_scheduler, load_runtime_state
    from value_investor.library_ingest_sprint import parallel_sprint_markets_needing_ingest

    policy = load_policy(args.policy)
    head = head_market_id(policy)
    head_health = snapshot_library_buy_tier_filing_health(
        head, library_root=args.root, policy=policy
    )
    needing = parallel_sprint_markets_needing_ingest(
        library_root=args.root,
        policy=policy,
        parallel_stream=int(args.parallel_stream),
    )
    for mid in list(policy.get("market_queue") or []):
        name = str(mid or "").strip()
        if not name or name == head or name in needing:
            continue
        health = snapshot_library_buy_tier_filing_health(
            name, library_root=args.root, policy=policy
        )
        if not ingest_parity_met(health):
            needing.append(name)
    phase2_ready = False
    try:
        from value_investor.market_shard_phases import evaluate_market_phase

        phase2_ready = bool(
            evaluate_market_phase(head, library_root=args.root, policy=policy).get("phase2_ready")
        )
    except Exception:  # noqa: BLE001
        phase2_ready = False
    if args.head_idle:
        head_in_progress: bool | None = False
    elif args.head_in_progress:
        head_in_progress = True
    else:
        head_in_progress = None
    decision = evaluate_scheduler(
        int(args.parallel_stream),
        policy=policy,
        head_at_parity=ingest_parity_met(head_health),
        needing_markets=needing,
        requested_targets=int(args.max_targets),
        requested_runtime=float(args.max_runtime_seconds),
        head_in_progress=head_in_progress,
        higher_spare_in_progress=bool(args.higher_spare_in_progress),
        phase2_ready=phase2_ready,
        leftover_state=load_runtime_state(Path(args.root) / "ingest_cascade_runtime.json"),
        waited_seconds=float(args.waited_seconds or 0.0),
    )
    payload = decision.to_dict()
    if args.json or args.json_path is not None:
        _emit_cli_json(payload, args)
    else:
        print(
            f"schedule stream={decision.stream} action={decision.action} "
            f"markets={','.join(decision.markets) or '-'} "
            f"runtime={decision.max_runtime_seconds:.0f}s "
            f"targets={decision.max_targets}"
        )
        print(f"  {decision.reason}")
    return 0


def cmd_library_ingest_sprint(args: argparse.Namespace) -> int:
    from value_investor.library_ingest_sprint import run_library_ingest_sprint

    markets = [m.strip() for m in str(args.markets or "").split(",") if m.strip()] or None
    outcome = run_library_ingest_sprint(
        library_root=args.root,
        policy_path=args.policy,
        markets=markets,
        max_targets=args.max_targets,
        max_runtime_seconds=args.max_runtime_seconds,
        max_bodies=args.max_bodies,
        parallel_stream=int(args.parallel_stream),
        head_in_progress=False if args.head_idle else None,
        higher_spare_in_progress=bool(args.higher_spare_in_progress),
    )
    payload = outcome.to_dict()
    if args.json or args.json_path is not None:
        _emit_cli_json(payload, args)
    else:
        print(
            f"sprint: markets={len(outcome.markets)} "
            f"results={len(outcome.results)} skipped={len(outcome.skipped)} "
            f"errors={len(outcome.errors)}"
        )
        for row in outcome.skipped:
            print(f"  skipped {row.get('market_id') or ''}: {row.get('reason')}")
        for err in outcome.errors:
            print(f"  error: {err}", file=sys.stderr)
    return 0 if not outcome.errors else 1


def cmd_euro_ingest_dispatch(args: argparse.Namespace) -> int:
    from value_investor.euro_depth_ingest_dispatch import (
        evaluate_euro_ingest_dispatch,
        refresh_euro_ingest_dispatch,
    )

    if args.refresh or args.sync_cron:
        payload = refresh_euro_ingest_dispatch(
            market_id=args.market,
            library_root=args.root,
            policy_path=args.policy,
            sync_cron=bool(args.sync_cron),
        )
    else:
        payload = evaluate_euro_ingest_dispatch(
            market_id=args.market,
            library_root=args.root,
            policy_path=args.policy,
        )
    if args.json or args.json_path is not None:
        _emit_cli_json(payload, args)
    else:
        print(
            f"{args.market}: mode={payload.get('mode')} "
            f"should_run_ingest={payload.get('should_run_ingest')} "
            f"max_daily={payload.get('max_daily_successes')} "
            f"max_targets={payload.get('max_targets')}"
        )
        print(f"  reason: {payload.get('reason')}")
        for blocker in payload.get("phase_blockers") or []:
            print(f"  blocker: {blocker}")
    return 0


def cmd_shard_weekday(args: argparse.Namespace) -> int:
    from value_investor.agent_model_policy import load_policy
    from value_investor.market_paper_shard import run_weekday_market_paper_shard

    policy = load_policy(args.policy)
    markets = _parse_markets(args.markets) or ["euro_depth"]
    payloads: dict[str, Any] = {}
    for market_id in markets:
        try:
            result = run_weekday_market_paper_shard(
                market_id,
                library_root=args.root,
                force=True,
                policy=policy,
            )
            payloads[market_id] = result
            if not args.json:
                review = result.get("review") or {}
                phase = result.get("phase") or {}
                print(
                    f"{market_id}: verdict={review.get('verdict')}  "
                    f"phase={phase.get('current_phase')}  "
                    f"phase3_ready={phase.get('phase3_ready')}"
                )
                for blocker in phase.get("blockers") or []:
                    print(f"  blocker: {blocker}")
        except Exception as exc:  # noqa: BLE001
            payloads[market_id] = {"error": str(exc)}
            if not args.json:
                print(f"{market_id}: ERROR — {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps({"markets": payloads}, indent=2))
    return 0 if all("error" not in row for row in payloads.values()) else 1


def cmd_ladder(args: argparse.Namespace) -> int:
    from .library_ladder import run_library_ladder

    payload = run_library_ladder(
        root=args.root,
        policy_path=args.policy,
        skip_grow=bool(args.skip_grow),
        skip_screen=bool(args.skip_screen),
        skip_research=bool(args.skip_research),
        skip_maintenance=bool(args.skip_maintenance),
        skip_graduation=bool(args.skip_graduation),
        dry_run_research=bool(args.dry_run_research),
        api_key=args.api_key,
        max_tickers=args.max_tickers,
        unrestricted_budget=bool(args.unrestricted_budget),
        checkpoint_usd=args.checkpoint_usd,
        approve_checkpoint=bool(args.approve_checkpoint),
        spend_pool=args.spend_pool,
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"Ladder focus: {payload['focus_market']}")
    if (
        payload.get("focus_market_after")
        and payload["focus_market_after"] != payload["focus_market"]
    ):
        print(f"Focus after graduation: {payload['focus_market_after']}")
    for name, layer in (payload.get("layers") or {}).items():
        if layer.get("skipped"):
            print(f"  {name}: skipped — {layer.get('reason') or 'flagged'}")
        elif name == "fundamentals":
            st = (layer.get("status") or [{}])[0]
            print(
                f"  fundamentals: coverage={st.get('coverage_count', 0)}/"
                f"{st.get('ticker_count', 0)}  max_tickers={layer.get('max_tickers')}"
            )
        elif name == "maintenance":
            print(
                f"  maintenance: markets={', '.join(layer.get('markets') or []) or '—'}  "
                f"max_tickers={layer.get('max_tickers')}"
            )
        elif name == "strong_buy_metrics_probe":
            if layer.get("skipped"):
                print(f"  strong_buy_metrics_probe: skipped — {layer.get('reason') or 'flagged'}")
            else:
                drafted = layer.get("drafted_task_ids") or []
                print(
                    f"  strong_buy_metrics_probe: markets="
                    f"{', '.join(layer.get('market_ids') or []) or '—'}  "
                    f"selected={layer.get('total_selected')}  "
                    f"errors={layer.get('total_errors')}  "
                    f"drafted={', '.join(drafted) if drafted else '—'}"
                )
        elif name == "screen_lite":
            print(
                f"  screen_lite: tickers={layer.get('ticker_count')}  "
                f"strong_buy={layer.get('strong_buy')}  buy={layer.get('buy')}  "
                f"shortlist={layer.get('shortlist_count')}"
            )
        elif name == "selective_research":
            print(
                f"  selective_research: model={layer.get('model')}  "
                f"cap={layer.get('research_cap')}  "
                f"targets={len(layer.get('targets') or [])}  "
                f"executed={layer.get('executed', 0)}"
            )
            for t in layer.get("targets") or []:
                print(f"    • {t['ticker']} {t['signal']} ({t.get('name')})")
        elif name == "graduation":
            ev = layer.get("event") or {}
            evaluation = layer.get("evaluation") or {}
            print(
                f"  graduation: meets={evaluation.get('meets_floors')}  "
                f"coverage={evaluation.get('coverage_pct')}  "
                f"stale_pct={evaluation.get('stale_pct')}  "
                f"event={ev.get('reason')}  "
                f"{ev.get('from_market')}→{ev.get('to_market')}"
            )
        elif name == "observe_sim":
            if layer.get("skipped"):
                print(f"  observe_sim: skipped — {layer.get('reason')}")
            else:
                for mid, row in (layer.get("markets") or {}).items():
                    if row.get("error"):
                        print(f"  observe_sim [{mid}]: error — {row['error']}")
                    else:
                        print(
                            f"  observe_sim [{mid}]: snapshots={row.get('snapshot_count')}  "
                            f"excess={row.get('screen_rules_excess')}"
                        )
        elif name == "weekly_paper_shard":
            if layer.get("skipped"):
                print(f"  weekly_paper_shard: skipped — {layer.get('reason')}")
            else:
                for mid, row in (layer.get("markets") or {}).items():
                    if row.get("error"):
                        print(f"  weekly_paper_shard [{mid}]: error — {row['error']}")
                    else:
                        print(
                            f"  weekly_paper_shard [{mid}]: verdict={row.get('verdict')}  "
                            f"phase={row.get('current_phase')}  "
                            f"batches_ready={row.get('phase2_ready')}"
                        )
        elif name == "observe_sim_screen":
            if layer.get("skipped"):
                print(f"  observe_sim_screen: skipped — {layer.get('reason')}")
            else:
                print(f"  observe_sim_screen: markets={', '.join(layer.get('markets') or [])}")
    if payload.get("shard_phases"):
        markets = payload["shard_phases"].get("markets") or {}
        ready = [mid for mid, ev in markets.items() if ev.get("phase2_ready")]
        if ready:
            print(f"  shard_phases: Phase 2 exit met for {', '.join(ready)}")
    return 0


def cmd_graduate(args: argparse.Namespace) -> int:
    from .library_graduation import evaluate_graduation, maybe_graduate_focus

    if args.dry_run:
        policy = load_policy(args.policy)
        evaluation = evaluate_graduation(args.root, policy)
        payload = {
            "evaluation": evaluation,
            "event": {
                "graduated": False,
                "dry_run": True,
                "would_advance": evaluation.get("can_advance"),
                "from_market": evaluation.get("focus_market"),
                "to_market": evaluation.get("next_focus"),
            },
            "policy_focus": policy.get("focus_market"),
        }
    else:
        payload = maybe_graduate_focus(args.root, args.policy)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    evaluation = payload.get("evaluation") or {}
    event = payload.get("event") or {}
    print(f"Focus: {evaluation.get('focus_market')}")
    print(
        f"Floors: coverage={evaluation.get('coverage_pct')} "
        f"(need>={evaluation.get('min_coverage_pct')})  "
        f"stale_pct={evaluation.get('stale_pct')} "
        f"(need<={evaluation.get('max_stale_pct')})  "
        f"meets={evaluation.get('meets_floors')}"
    )
    if event.get("dry_run"):
        print(
            f"Dry run: would_advance={event.get('would_advance')}  "
            f"{event.get('from_market')}→{event.get('to_market')}"
        )
    else:
        print(
            f"Event: {event.get('reason')}  "
            f"{event.get('from_market')}→{event.get('to_market')}  "
            f"policy_focus={payload.get('policy_focus')}"
        )
    return 0


def cmd_t212_catalogue(args: argparse.Namespace) -> int:
    from .t212_client import Trading212APIError, Trading212AuthError
    from .t212_coverage import catalogue_dir, fetch_and_save_catalogue

    env = (args.env or "").strip() or None
    try:
        meta = fetch_and_save_catalogue(
            library_root=args.root,
            env=env,
            include_exchanges=not bool(args.skip_exchanges),
        )
    except Trading212AuthError as exc:
        print(f"Trading 212 auth error: {exc}", file=sys.stderr)
        return 2
    except Trading212APIError as exc:
        print(f"Trading 212 API error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(meta, indent=2))
        return 0
    print(f"Library root: {args.root}")
    print(f"Catalogue dir: {catalogue_dir(args.root)}")
    print(f"Fetched at: {meta.get('fetched_at')}")
    print(f"Env/source: {meta.get('env')} / {meta.get('source')}")
    print(
        f"Instruments: {meta.get('instrument_count')}  "
        f"ISINs: {meta.get('isin_count')}  "
        f"Exchanges: {meta.get('exchanges_count')}"
    )
    types = meta.get("type_counts") or {}
    if types:
        bits = ", ".join(f"{k}={v}" for k, v in sorted(types.items()))
        print(f"Types: {bits}")
    print("Next: ftse-library t212-overlay")
    return 0


def cmd_t212_overlay(args: argparse.Namespace) -> int:
    from .t212_coverage import build_t212_overlays

    markets = _parse_markets(args.markets)
    summary = build_t212_overlays(
        args.root,
        markets=markets,
        write=not bool(args.dry_run),
    )
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    totals = summary.get("totals") or {}
    print(f"Library root: {args.root}")
    print(f"T212 overlay as_of: {summary.get('as_of')}")
    print(f"Catalogue loaded: {summary.get('catalogue_loaded')}")
    cat = summary.get("catalogue") or {}
    if cat:
        print(
            f"Catalogue fetched_at: {cat.get('fetched_at')}  "
            f"instruments={cat.get('instrument_count')}"
        )
    print(summary.get("note"))
    print(
        f"Totals: markets={totals.get('markets')}  "
        f"tickers={totals.get('tickers')}  "
        f"tradable={totals.get('tradable')}  "
        f"catalogue_hits={totals.get('catalogue_hits')}  "
        f"unknown_venue={totals.get('unknown_venue')}"
    )
    for mid, row in (summary.get("markets") or {}).items():
        print(
            f"  {mid}: tradable={row.get('tradable_count')}/{row.get('ticker_count')} "
            f"({100 * float(row.get('tradable_pct') or 0):.1f}%)  "
            f"catalogue={row.get('catalogue_hit_count')}  "
            f"unknown={row.get('unknown_venue_count')}  "
            f"curated={row.get('curated_exception_count')}"
        )
        sample = row.get("non_tradable_sample") or []
        if sample:
            bits = ", ".join(f"{s['ticker']} ({s.get('basis')})" for s in sample[:5])
            print(f"    non-tradable sample: {bits}")
    print("\nNext slice candidates:")
    for item in summary.get("next_slices") or []:
        print(
            f"  [{item.get('priority')}] {item.get('id')}: {item.get('label')} "
            f"({item.get('status')})"
        )
    return 0


# Backward-compatible name used by older docs/scripts.
cmd_ii_overlay = cmd_t212_overlay


def cmd_t212_align(args: argparse.Namespace) -> int:
    from .t212_coverage import assess_t212_alignment, t212_coverage_root

    markets = _parse_markets(args.markets)
    report = assess_t212_alignment(
        args.root,
        markets=markets,
        write=not bool(args.dry_run),
        allowlist_only=bool(args.allowlist_only),
    )
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    totals = report.get("library_totals") or {}
    print(f"Library root: {args.root}")
    print(f"Coverage root: {t212_coverage_root(args.root)}")
    print(f"Mode: {report.get('mode')}")
    print(report.get("note"))
    if report.get("catalogue"):
        cat = report["catalogue"]
        print(
            f"Catalogue: instruments={cat.get('instrument_count')}  "
            f"fetched_at={cat.get('fetched_at')}"
        )
    print(
        f"Library totals: markets={totals.get('markets')}  "
        f"tickers={totals.get('tickers')}  "
        f"tradable={totals.get('tradable')}  "
        f"catalogue_hits={totals.get('catalogue_hits')}"
    )
    print("\nPer-market alignment:")
    for row in report.get("markets") or []:
        print(
            f"  {row['market']:16} tradable={row['tradable_count']}/{row['ticker_count']} "
            f"({100 * float(row['tradable_pct']):5.1f}%)  "
            f"catalogue={row['catalogue_hit_count']} "
            f"({100 * float(row['catalogue_hit_pct']):5.1f}%)  "
            f"unk={row['unknown_venue_count']} cur={row['curated_exception_count']}"
        )
    weak = report.get("weak_existing_markets") or []
    if weak:
        print("\nWeak catalogue matches (existing markets):")
        for row in weak:
            print(
                f"  {row['market']}: {100 * float(row['catalogue_hit_pct']):.1f}% "
                f"({row['catalogue_hit_count']}/{row['ticker_count']}) — {row['note']}"
            )
    print("\nSuggested ladder markets:")
    suggestions = report.get("suggested_ladder_markets") or []
    if not suggestions:
        print("  (none — catalogue absent filters none, or all gaps already covered)")
    for item in suggestions:
        support = item.get("catalogue_support")
        extra = ""
        if support:
            extra = f"  catalogue_stocks={support.get('stock_count_on_hints')}"
        print(f"  [{item.get('priority')}] {item.get('id')}: {item.get('label')}{extra}")
        print(f"      {item.get('rationale')}")
    if not args.dry_run:
        print(f"\nWrote: {t212_coverage_root(args.root) / 'alignment_report.json'}")
    return 0


def cmd_firds_filter(args: argparse.Namespace) -> int:
    from .firds_mics import filter_firds_file, ii_allowed_mics, write_firds_filter_result

    mics = ii_allowed_mics()
    rows = filter_firds_file(args.input, mics=mics, limit=args.limit)
    payload = {
        "input": str(args.input),
        "mic_count": len(mics),
        "mics": sorted(mics),
        "row_count": len(rows),
        "sample": rows[:5],
    }
    if not args.dry_run:
        path = write_firds_filter_result(rows, library_root=args.root, source_path=args.input)
        payload["wrote"] = str(path)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"FIRDS filter: {args.input}")
    print(f"Coverage online MICs ({len(mics)}): {', '.join(sorted(mics))}")
    print(f"Matched rows: {len(rows)}")
    if args.dry_run:
        print("(dry-run — not written)")
    else:
        print(f"Wrote: {payload.get('wrote')}")
    for row in rows[:5]:
        print(f"  {row.get('isin')}  {row.get('mic')}  {row.get('name')}")
    return 0


def cmd_unavailable_watch(args: argparse.Namespace) -> int:
    import sys

    from .unavailable_watch import (
        default_unavailable_path,
        load_unavailable_watch,
        mark_unavailable,
        restore_unavailable,
    )

    path = default_unavailable_path(args.root)
    action = str(args.action)
    ticker = str(args.ticker or "").strip()

    if action == "list":
        payload = load_unavailable_watch(path)
    elif action == "mark":
        if not ticker:
            print("ticker required for mark", file=sys.stderr)
            return 2
        payload = mark_unavailable(
            ticker,
            name=str(args.name or "").strip() or None,
            reason=str(args.reason or "unavailable_on_t212"),
            path=path,
        )
    else:  # restore
        if not ticker:
            print("ticker required for restore", file=sys.stderr)
            return 2
        payload = restore_unavailable(ticker, path=path)

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    items = payload.get("items") or []
    print(f"Unavailable watch: {path}")
    print(f"Items: {len(items)}")
    for row in items:
        print(
            f"  {row.get('ticker')}: {row.get('name') or '—'}  "
            f"reason={row.get('reason')}  status={row.get('status')}"
        )
    return 0


def cmd_overlaps(args: argparse.Namespace) -> int:
    from .data_library import CONSTITUENT_FETCHERS, load_manifest
    from .library_dedupe import summarize_ticker_overlaps

    markets = _parse_markets(args.markets)
    if markets is None:
        # Default: registered offline slices (live FTSE 350 screen list optional via --markets).
        markets = [mid for mid in MARKET_REGISTRY if mid != "ftse350"]

    market_tickers: dict[str, list[str]] = {}
    for mid in markets:
        if mid not in MARKET_REGISTRY:
            print(f"Unknown market: {mid}")
            return 2
        if args.live:
            frame = CONSTITUENT_FETCHERS[mid]()
            market_tickers[mid] = [str(t) for t in frame["ticker"].tolist()]
            continue
        manifest = load_manifest(args.root, mid)
        tickers = list(manifest.get("tickers") or [])
        if not tickers:
            # Fall back to live fetch when library not grown yet.
            try:
                frame = CONSTITUENT_FETCHERS[mid]()
                tickers = [str(t) for t in frame["ticker"].tolist()]
            except Exception as exc:  # noqa: BLE001
                print(f"{mid}: unavailable ({exc})")
                continue
        market_tickers[mid] = tickers

    payload = summarize_ticker_overlaps(market_tickers)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"Markets: {', '.join(payload['markets'])}")
    print(f"Tickers in ≥2 markets: {payload['tickers_in_multiple_markets']}")
    print(payload["note"])
    for row in payload["pairs"]:
        a, b = row["markets"]
        print(f"  {a} ∩ {b}: {row['overlap_count']}  e.g. {row['sample']}")
    return 0


def cmd_reingest_filings(args: argparse.Namespace) -> int:
    from .library_maintenance import reingest_research_filings

    markets = _parse_markets(args.markets) or ["asx200", "euro_stoxx50"]
    payload = reingest_research_filings(
        args.root,
        markets,
        only_unsupported=not bool(args.all),
        api_key=args.api_key,
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"Library root: {args.root}")
    print(
        f"Re-ingested filings for {payload['target_count']} memo(s) "
        f"across {', '.join(payload['markets'])}"
    )
    for row in payload.get("results") or []:
        print(
            f"  {row['market']}/{row['ticker']}: "
            f"{row.get('prior_regime')}→{row.get('regime')}  "
            f"filings={row.get('filings_total')}  bodies={row.get('with_body')}"
        )
    return 0


def cmd_repair_research(args: argparse.Namespace) -> int:
    from value_investor.cursor_api_key import resolve_cursor_api_key

    from .library_maintenance import list_batch1_repair_targets, repair_library_research_memos

    markets = _parse_markets(args.markets) or None
    targets = list_batch1_repair_targets(
        args.root,
        batch_date=str(args.batch_date),
        markets=markets,
    )
    key = (args.api_key or "").strip() or resolve_cursor_api_key()[0]
    if not key:
        print("CURSOR_API_KEY_V2 / CURSOR_API_KEY required for re-memo", file=sys.stderr)
        return 1
    payload = repair_library_research_memos(
        args.root,
        targets,
        api_key=key,
        rememo_all=bool(args.rememo_all),
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if not payload.get("errors") else 1
    print(
        f"Repair targets: {payload['target_count']}  "
        f"re-memoed: {payload['rememoed']}  "
        f"skipped: {payload['skipped_rememo']}  "
        f"errors: {len(payload.get('errors') or [])}"
    )
    for row in payload.get("results") or []:
        if row.get("error"):
            print(f"  ERROR {row['market']}/{row['ticker']}: {row['error']}")
        else:
            print(
                f"  {row['market']}/{row['ticker']}: "
                f"bodies {row.get('bodies_before')}→{row.get('bodies_after')}  "
                f"rememo={row.get('rememo')}  reasons={','.join(row.get('reasons') or [])}"
            )
    return 0 if not payload.get("errors") else 1


def cmd_deepen_thin(args: argparse.Namespace) -> int:
    from value_investor.cursor_api_key import resolve_cursor_api_key

    from .library_maintenance import deepen_library_research_memos, list_thin_library_memos

    markets = _parse_markets(args.markets) or ["asx200", "euro_stoxx50"]
    targets = list_thin_library_memos(
        args.root,
        markets=markets,
        max_with_body=int(args.max_with_body),
    )
    key = None
    if args.rememo or args.rememo_all:
        key = (args.api_key or "").strip() or resolve_cursor_api_key()[0]
        if not key:
            print(
                "CURSOR_API_KEY_V2 / CURSOR_API_KEY required for --rememo / --rememo-all",
                file=sys.stderr,
            )
            return 1
    payload = deepen_library_research_memos(
        args.root,
        targets,
        api_key=key,
        rememo_when_improved=bool(args.rememo),
        rememo_all=bool(args.rememo_all),
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if not payload.get("errors") else 1
    print(
        f"Thin targets: {payload['target_count']}  "
        f"deepened: {payload['deepened']}  "
        f"re-memoed: {payload['rememoed']}  "
        f"errors: {len(payload.get('errors') or [])}"
    )
    for row in payload.get("results") or []:
        if row.get("error"):
            print(f"  ERROR {row['market']}/{row['ticker']}: {row['error']}")
        else:
            print(
                f"  {row['market']}/{row['ticker']}: "
                f"bodies {row.get('bodies_before')}→{row.get('bodies_after')}  "
                f"improved={row.get('improved')}  rememo={row.get('rememo')}"
            )
    return 0 if not payload.get("errors") else 1


def cmd_retry_failed(args: argparse.Namespace) -> int:
    from .library_maintenance import retry_failed_metrics

    markets = _parse_markets(args.markets) or [mid for mid in MARKET_REGISTRY if mid != "ftse350"]
    results = retry_failed_metrics(args.root, markets)
    payload = {"root": str(args.root), "markets": results}
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"Library root: {args.root}")
    for row in results:
        still = row.get("still_failed") or []
        print(
            f"{row['market']}: retried={len(row.get('selected') or [])}  "
            f"errors={row.get('errors', 0)}  still_failed={len(still)}"
        )
        if still:
            print(f"  still: {', '.join(still)}")
    return 0


def cmd_prune_screen(args: argparse.Namespace) -> int:
    from .library_maintenance import prune_library_screen_history

    markets = _parse_markets(args.markets)
    payload = prune_library_screen_history(
        args.root,
        markets=markets,
        keep_days=int(args.retention_days),
        monthly_until_days=int(args.retention_monthly_until_days),
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"Library root: {args.root}")
    print(
        f"Pruned screen-lite history "
        f"(dense={payload['keep_days']}d, monthly_until={payload['monthly_until_days']}d): "
        f"removed {payload['total_removed']} file(s), "
        f"{payload.get('total_signal_history_rows_removed', 0)} signal_history row(s)"
    )
    for mid, counts in (payload.get("per_market") or {}).items():
        if counts.get("removed") or counts.get("signal_history_rows_removed"):
            print(
                f"  {mid}: screen={counts.get('screen_removed', 0)}  "
                f"history={counts.get('history_removed', 0)}  "
                f"signal_rows={counts.get('signal_history_rows_removed', 0)}"
            )
    return 0


def cmd_automation_status(args: argparse.Namespace) -> int:
    from .automation_status import build_automation_status, write_automation_status

    if args.dry_run:
        payload = build_automation_status(library_root=args.root)
    else:
        path = write_automation_status(library_root=args.root, path=args.output)
        payload = build_automation_status(library_root=args.root)
        payload = {**payload, "wrote": str(path)}

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    settings = payload.get("settings") or {}
    library = settings.get("library") or {}
    paper = settings.get("paper") or {}
    timeline = (payload.get("achievements") or {}).get("timeline") or []
    print(f"Focus market: {library.get('focus_market')}")
    print(
        f"Graduated: {library.get('graduated_count')}  "
        f"queue_complete={library.get('queue_complete')}"
    )
    print(
        f"Paper auto: enabled={paper.get('enabled')}  "
        f"rebalance={paper.get('auto_rebalance')}  "
        f"max_positions={paper.get('max_positions')}"
    )
    print(f"Timeline events: {len(timeline)}")
    for event in timeline[:8]:
        print(f"  {event.get('at')}: {event.get('title')}")
    if not args.dry_run:
        print(f"Wrote: {payload.get('wrote')}")
    return 0


def cmd_macro(args: argparse.Namespace) -> int:
    from .macro_context import (
        load_macro_snapshot,
        macro_context_for_market,
        refresh_macro_library,
    )

    # Keep macro under the library root (default or overridden --root).
    macro_root = Path(args.root) / "macro"

    if args.refresh:
        snapshot = refresh_macro_library(macro_root)
        payload: dict = {"refreshed": True, "snapshot": snapshot}
    else:
        snapshot = load_macro_snapshot(macro_root)
        payload = {"refreshed": False, "snapshot": snapshot}

    market = str(args.market or "").strip()
    if market:
        payload["market_context"] = macro_context_for_market(
            market,
            root=macro_root,
            refresh_if_missing=False,
        )

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    snap = payload.get("snapshot") or {}
    print(f"Macro root: {macro_root}")
    print(f"Fetched at: {snap.get('fetched_at')}")
    print(f"Note: {snap.get('note')}")
    domains = snap.get("domains") or {}
    for domain, block in domains.items():
        markers = (block or {}).get("markers") or {}
        bits = []
        for key, row in markers.items():
            if isinstance(row, dict) and row.get("value") is not None:
                bits.append(f"{key}={row['value']}")
        print(f"  {domain}: {', '.join(bits) if bits else '(empty)'}")
    if market:
        ctx = payload.get("market_context") or {}
        print(f"\nMarket {market} → domain {ctx.get('domain')}")
        print(f"  {ctx.get('note')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv_list = list(argv or sys.argv[1:])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_LIBRARY_ROOT,
        help=f"Library root (default: {DEFAULT_LIBRARY_ROOT})",
    )
    common.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY_PATH,
        help=f"Library/budget policy JSON (default: {DEFAULT_POLICY_PATH})",
    )
    pre, remaining = common.parse_known_args(argv_list)
    parser = build_parser()
    args = parser.parse_args(remaining)
    apply_parsed_globals(args, pre, argv_list, ["root", "policy"])
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
