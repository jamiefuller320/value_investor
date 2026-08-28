"""CLI for per-market fair trading-cost assumptions and paper-book assessments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.market_trading_costs import (
    LEGACY_STRESS_TRADE_COST_PCT,
    assess_paper_tracks_under_fair_costs,
    costs_for_market,
    list_market_costs,
)

DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fair T212-shaped trading costs by market, and assess paper funds "
            "without rewriting the live FTSE 3% stress configs"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="List fair cost assumptions by market")
    list_p.add_argument("--json", action="store_true")
    list_p.add_argument(
        "--market",
        default="",
        help="Optional market_id to show one row (default: all registered)",
    )
    list_p.set_defaults(func=_cmd_list)

    assess_p = sub.add_parser(
        "assess",
        help="Recompute recorded trade friction under fair costs (read-only)",
    )
    assess_p.add_argument(
        "--paper-root",
        type=Path,
        default=DEFAULT_PAPER_ROOT,
        help="Paper automation root (default: docs/data/paper_automation)",
    )
    assess_p.add_argument(
        "--market",
        default="ftse350",
        help="Market id for fair assumptions (default: ftse350 for live books)",
    )
    assess_p.add_argument(
        "--tracks",
        default="",
        help="Comma-separated track ids (default: all learning tracks present)",
    )
    assess_p.add_argument("--json", action="store_true")
    assess_p.set_defaults(func=_cmd_assess)

    args = parser.parse_args(argv)
    return int(args.func(args))


def _cmd_list(args: argparse.Namespace) -> int:
    if args.market:
        rows = [costs_for_market(args.market).to_dict()]
    else:
        rows = list_market_costs()
    if args.json:
        print(
            json.dumps(
                {
                    "legacy_stress_trade_cost_pct": LEGACY_STRESS_TRADE_COST_PCT,
                    "markets": rows,
                },
                indent=2,
            )
        )
        return 0
    print(f"{'market':<16} {'buy%':>8} {'sell%':>8} {'RT%':>8} {'sym%':>8}  notes")
    print("-" * 88)
    for row in rows:
        print(
            f"{row['market_id']:<16} "
            f"{row['buy_pct'] * 100:7.3f}% "
            f"{row['sell_pct'] * 100:7.3f}% "
            f"{row['round_trip_pct'] * 100:7.3f}% "
            f"{row['symmetric_proxy_pct'] * 100:7.3f}%  "
            f"{row.get('notes', '')[:48]}"
        )
    print()
    print(
        f"Live FTSE paper default remains stress trade_cost_pct="
        f"{LEGACY_STRESS_TRADE_COST_PCT:.0%} per side unless configs are changed."
    )
    return 0


def _cmd_assess(args: argparse.Namespace) -> int:
    tracks = [t.strip() for t in str(args.tracks or "").split(",") if t.strip()] or None
    payload = assess_paper_tracks_under_fair_costs(
        args.paper_root,
        market_id=args.market,
        track_ids=tracks,
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    model = payload.get("assumptions") or {}
    print(f"paper_root={payload.get('paper_root')}")
    print(
        f"fair market={payload.get('market_id')}  "
        f"buy={float(model.get('buy_pct') or 0) * 100:.3f}%  "
        f"sell={float(model.get('sell_pct') or 0) * 100:.3f}%  "
        f"RT={float(model.get('round_trip_pct') or 0) * 100:.3f}%"
    )
    print(payload.get("note") or "")
    print()
    for track_id, row in (payload.get("tracks") or {}).items():
        if not row.get("ok"):
            print(f"  {track_id}: {row.get('reason')}")
            continue
        recorded = float(row.get("recorded_costs") or 0)
        fair = float(row.get("fair_costs") or 0)
        relief = row.get("cost_drag_relief")
        relief_s = f"{float(relief) * 100:+.2f}pp of capital" if relief is not None else "n/a"
        print(
            f"  {track_id}: trades={row.get('trade_count')}  "
            f"recorded_costs={recorded:.2f}  fair_costs={fair:.4f}  "
            f"drag_relief={relief_s}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
