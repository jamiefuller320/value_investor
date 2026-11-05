"""CLI for the observe-only sector headwind gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from value_investor.sector_headwind_gate import (
    DEFAULT_CHARTS_DIR,
    DEFAULT_DECLINE_STORE,
    DEFAULT_LABEL_HISTORY,
    DEFAULT_LATEST_PATH,
    DEFAULT_LIBRARY_ROOT,
    DEFAULT_MARKET_STATUS,
    DEFAULT_STORE_PATH,
    refresh_sector_headwind_gate,
)


def _select_sector(payload: dict[str, Any], query: str) -> tuple[str, dict[str, Any]] | None:
    sectors = payload.get("sectors")
    if not isinstance(sectors, dict):
        return None
    needle = query.casefold()
    exact: list[tuple[str, dict[str, Any]]] = []
    named: list[tuple[str, dict[str, Any]]] = []
    for key, row in sectors.items():
        if not isinstance(row, dict):
            continue
        if key.casefold() == needle:
            exact.append((key, row))
        elif str(row.get("sector") or "").casefold() == needle:
            named.append((key, row))
    if len(exact) == 1:
        return exact[0]
    if len(named) == 1:
        return named[0]
    return None


def _format_text(payload: dict[str, Any], selected: tuple[str, dict[str, Any]] | None) -> str:
    if selected is not None:
        key, row = selected
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        return (
            f"{key}: {row.get('verdict')}\n"
            f"  members={len(row.get('members') or [])} "
            f"buy_tier={len(row.get('buy_tier_members') or [])}\n"
            f"  below_200d={metrics.get('price_below_sma200_share')} "
            f"return_63d={metrics.get('sector_return_63d')} "
            f"return_126d={metrics.get('sector_return_126d')} "
            f"drawdown_1y={metrics.get('sector_drawdown_from_1y_high')}\n"
            f"  earnings_component={metrics.get('earnings_component')} "
            f"declining_share={metrics.get('earnings_declining_share')}\n"
        )
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "Sector headwind gate (observe-only)",
        (
            f"  as_of={payload.get('as_of')} markets={summary.get('markets')} "
            f"sectors={summary.get('sectors')} "
            f"sound={summary.get('sound')} headwind={summary.get('headwind')} "
            f"insufficient_data={summary.get('insufficient_data')}"
        ),
        (
            f"  chart_coverage={summary.get('chart_file_coverage_share')} "
            f"buy_tier_names={summary.get('buy_tier_names')} "
            f"buy_tier_in_headwind={summary.get('buy_tier_in_headwind_sector')} "
            f"buy_tier_insufficient_data="
            f"{summary.get('buy_tier_in_insufficient_data_sector')}"
        ),
        f"  influences_live={payload.get('influences_live')}",
    ]
    by_market = summary.get("by_market") if isinstance(summary.get("by_market"), dict) else {}
    for market in by_market:
        row = by_market[market]
        if not isinstance(row, dict):
            continue
        lines.append(
            f"  {market}: sectors={row.get('sectors')} sound={row.get('sound')} "
            f"headwind={row.get('headwind')} insufficient_data={row.get('insufficient_data')} "
            f"buy_tier={row.get('buy_tier_names')} "
            f"buy_tier_insufficient={row.get('buy_tier_in_insufficient_data_sector')}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh the point-in-time sector headwind gate. Observe-only; "
            "never changes signals, books, or knobs."
        )
    )
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST_PATH)
    parser.add_argument("--charts-dir", type=Path, default=DEFAULT_CHARTS_DIR)
    parser.add_argument("--decline-store", type=Path, default=DEFAULT_DECLINE_STORE)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--market-status", type=Path, default=DEFAULT_MARKET_STATUS)
    parser.add_argument("--library-root", type=Path, default=DEFAULT_LIBRARY_ROOT)
    parser.add_argument("--label-history", type=Path, default=DEFAULT_LABEL_HISTORY)
    parser.add_argument("--as-of", help="Decision cutoff date or ISO timestamp")
    parser.add_argument("--sector", help="Show one sector by name or market:sector key")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = refresh_sector_headwind_gate(
        latest_path=args.latest,
        charts_dir=args.charts_dir,
        decline_store=args.decline_store,
        store_path=args.store,
        market_status_path=args.market_status,
        library_root=args.library_root,
        label_history_path=args.label_history,
        persist=not args.no_persist,
        as_of=args.as_of,
    )
    selected = _select_sector(payload, args.sector) if args.sector else None
    if args.sector and selected is None:
        parser.error(f"sector not found or ambiguous: {args.sector}. Use a market:sector key.")
    if args.json:
        output: dict[str, Any] = payload
        if selected is not None:
            output = {"key": selected[0], **selected[1]}
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(_format_text(payload, selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
