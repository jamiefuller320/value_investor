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
    DEFAULT_RETENTION_DAYS,
    DEFAULT_STALE_DAYS,
    MARKET_REGISTRY,
    grow_library,
    library_status,
    list_markets,
    refresh_constituents,
)


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
        help=f"Delete dated snapshots older than this (default: {DEFAULT_RETENTION_DAYS}; 0 = keep all)",
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
    print(f"Policy: {args.policy}")
    print(f"Focus market: {policy.get('focus_market')}")
    print(f"Queue: {', '.join(policy.get('market_queue') or [])}")
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
