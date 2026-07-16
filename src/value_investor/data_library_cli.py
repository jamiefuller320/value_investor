"""CLI for progressive multi-market data libraries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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
        help="Comma-separated market ids (default: all registered)",
    )
    refresh_p.set_defaults(func=cmd_refresh)

    grow_p = sub.add_parser(
        "grow",
        help="Refresh constituents (optional) and fetch a budgeted set of ticker metrics",
    )
    grow_p.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: all registered)",
    )
    grow_p.add_argument(
        "--max-tickers",
        type=int,
        default=DEFAULT_MAX_TICKERS_PER_RUN,
        help=f"Max tickers to fetch per market this run (default: {DEFAULT_MAX_TICKERS_PER_RUN})",
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
    grow_p.add_argument("--json", action="store_true", help="Emit JSON summary")
    grow_p.set_defaults(func=cmd_grow)

    return parser


def _parse_markets(raw: str) -> list[str] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return [part.strip() for part in text.split(",") if part.strip()]


def cmd_list(args: argparse.Namespace) -> int:
    print(f"Library root: {args.root}")
    print()
    for row in list_markets():
        mid = row["market_id"]
        print(f"{mid:16}  {row['label']}")
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
    markets = _parse_markets(args.markets) or list(MARKET_REGISTRY)
    for mid in markets:
        manifest = refresh_constituents(args.root, mid)
        print(
            f"{mid}: {manifest.get('ticker_count', 0)} constituents "
            f"(asof {manifest.get('last_constituents_refresh')})"
        )
    return 0


def cmd_grow(args: argparse.Namespace) -> int:
    markets = _parse_markets(args.markets)
    results = grow_library(
        args.root,
        markets=markets,
        max_tickers_per_run=int(args.max_tickers),
        stale_days=int(args.stale_days),
        refresh_constituents_first=not bool(args.skip_constituents),
        retention_days=int(args.retention_days),
    )
    status_rows = library_status(args.root, markets=markets, stale_days=int(args.stale_days))
    by_market = {r["market"]: r for r in status_rows}
    if args.json:
        print(
            json.dumps(
                {"root": str(args.root), "last_grow": results, "markets": status_rows},
                indent=2,
            )
        )
        return 0
    print(f"Library root: {args.root}")
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
