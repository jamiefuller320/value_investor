"""CLI for progressive multi-market data libraries."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .agent_model_policy import (
    DEFAULT_POLICY_PATH,
    focus_markets,
    grow_ticker_budget,
    load_policy,
    recommend_cheapest_model,
    research_model_id,
    review_model,
    save_policy,
)
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
from .library_retention import DEFAULT_MONTHLY_UNTIL_DAYS, DEFAULT_RETENTION_DAYS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ftse-library",
        description=(
            "Progressively grow and maintain offline multi-market data libraries "
            "without changing the live FTSE 350 screening path."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_LIBRARY_ROOT,
        help=f"Library root (default: {DEFAULT_LIBRARY_ROOT})",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY_PATH,
        help=f"Library/budget policy JSON (default: {DEFAULT_POLICY_PATH})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="List registered markets")
    list_p.set_defaults(func=cmd_list)

    status_p = sub.add_parser("status", help="Show library coverage / freshness")
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

    policy_p = sub.add_parser("policy", help="Show or update library focus / budget policy")
    policy_p.add_argument("--json", action="store_true")
    policy_p.add_argument("--focus", default="", help="Set focus market id (e.g. sp500)")
    policy_p.add_argument(
        "--plan-monthly-usd",
        type=float,
        default=None,
        help="Included plan budget in USD (e.g. 20 for Pro)",
    )
    policy_p.add_argument(
        "--weekly-fraction",
        type=float,
        default=None,
        help="Fraction of plan budget for library strand per week (default 0.10)",
    )
    policy_p.add_argument(
        "--refresh-day",
        type=int,
        default=None,
        help="Day of month when Cursor plan credits refresh (1-28)",
    )
    policy_p.set_defaults(func=cmd_policy)

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
        default=os.environ.get("CURSOR_API_KEY"),
        help="Cursor API key for selective research",
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

    ii_p = sub.add_parser(
        "ii-overlay",
        help=(
            "Build Interactive Investor coverage overlay for library markets "
            "(exchange allowlist — not a full instrument catalog)"
        ),
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
    ii_p.set_defaults(func=cmd_ii_overlay)

    firds_p = sub.add_parser(
        "firds-filter",
        help=(
            "Filter a public FCA/ESMA FIRDS XML/CSV dump to II-advertised online MICs "
            "(venue admission ≠ II order acceptance)"
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
        default="unavailable_on_ii",
        help="Reason code (default: unavailable_on_ii)",
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
    max_tickers = int(args.max_tickers) if args.max_tickers is not None else int(plan["max_tickers"])
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
            "weekly_library_usd": plan["weekly_library_usd"],
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
        f"weekly_budget=${plan['weekly_library_usd']}  "
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
    if args.weekly_fraction is not None:
        budget["weekly_library_fraction"] = float(args.weekly_fraction)
        changed = True
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
        print(json.dumps(policy, indent=2))
        return 0
    budget = policy.get("budget") or {}
    model = policy.get("research_model") or {}
    fg = policy.get("focus_graduation") or {}
    graduated = graduated_market_ids(policy)
    print(f"Policy: {args.policy}")
    print(f"Focus market: {policy.get('focus_market')}")
    print(f"Queue: {', '.join(policy.get('market_queue') or [])}")
    print(f"Graduated: {', '.join(graduated) if graduated else '—'}")
    print(
        f"Graduation floors: coverage>={fg.get('min_coverage_pct')}  "
        f"stale<={fg.get('max_stale_pct')}  "
        f"auto_advance={fg.get('auto_advance')}  "
        f"maintenance_max_tickers={fg.get('maintenance_max_tickers')}"
    )
    print(
        f"Budget: ${budget.get('weekly_library_usd')}/week "
        f"({100 * float(budget.get('weekly_library_fraction') or 0):.0f}% of "
        f"${budget.get('plan_monthly_usd')}/mo)  "
        f"refresh_day={budget.get('plan_refresh_day_of_month')}  "
        f"surplus_day_before_refresh={budget.get('surplus_day_before_refresh')}"
    )
    print(
        f"Research model: {model.get('model_id')} "
        f"({model.get('pool')}) — {model.get('reason')}"
    )
    print(f"Set refresh day to match Cursor billing: ftse-library policy --refresh-day N")
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
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"Ladder focus: {payload['focus_market']}")
    if payload.get("focus_market_after") and payload["focus_market_after"] != payload["focus_market"]:
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


def cmd_ii_overlay(args: argparse.Namespace) -> int:
    from .ii_coverage import build_ii_overlays

    markets = _parse_markets(args.markets)
    summary = build_ii_overlays(
        args.root,
        markets=markets,
        write=not bool(args.dry_run),
    )
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    totals = summary.get("totals") or {}
    print(f"Library root: {args.root}")
    print(f"II overlay as_of: {summary.get('as_of')}")
    print(summary.get("note"))
    print(
        f"Totals: markets={totals.get('markets')}  "
        f"tickers={totals.get('tickers')}  "
        f"tradable={totals.get('tradable')}  "
        f"unknown_venue={totals.get('unknown_venue')}"
    )
    for mid, row in (summary.get("markets") or {}).items():
        print(
            f"  {mid}: tradable={row.get('tradable_count')}/{row.get('ticker_count')} "
            f"({100 * float(row.get('tradable_pct') or 0):.1f}%)  "
            f"unknown={row.get('unknown_venue_count')}  "
            f"curated={row.get('curated_exception_count')}"
        )
        sample = row.get("non_tradable_sample") or []
        if sample:
            bits = ", ".join(
                f"{s['ticker']} ({s.get('basis')})" for s in sample[:5]
            )
            print(f"    non-tradable sample: {bits}")
    print("\nNext slice candidates:")
    for item in summary.get("next_slices") or []:
        print(
            f"  [{item.get('priority')}] {item.get('id')}: {item.get('label')} "
            f"({item.get('status')})"
        )
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
    print(f"II online MICs ({len(mics)}): {', '.join(sorted(mics))}")
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
            reason=str(args.reason or "unavailable_on_ii"),
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


def cmd_retry_failed(args: argparse.Namespace) -> int:
    from .library_maintenance import retry_failed_metrics

    markets = _parse_markets(args.markets) or [
        mid for mid in MARKET_REGISTRY if mid != "ftse350"
    ]
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
    timeline = ((payload.get("achievements") or {}).get("timeline") or [])
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
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
