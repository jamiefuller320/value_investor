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
DEFAULT_DATA_DIR = Path("docs/data")


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

    spawn_p = sub.add_parser(
        "spawn-fair-lab",
        help="Spawn Suite B fair-cost AI + rules tracks (does not flip Suite A off 3%)",
    )
    spawn_p.add_argument(
        "--paper-root",
        type=Path,
        default=DEFAULT_PAPER_ROOT,
        help="Paper automation root (default: docs/data/paper_automation)",
    )
    spawn_p.add_argument(
        "--market",
        default="ftse350",
        help="Market id for fair cost stamps (default: ftse350)",
    )
    spawn_p.add_argument(
        "--force",
        action="store_true",
        help="Recreate configs/funds even if Suite B tracks already exist",
    )
    spawn_p.add_argument("--json", action="store_true")
    spawn_p.set_defaults(func=_cmd_spawn_fair_lab)

    warm_p = sub.add_parser(
        "warm-start-fair-lab",
        help="PIT warm-start Suite B tracks from Suite A parent rebalance logs",
    )
    warm_p.add_argument(
        "--paper-root",
        type=Path,
        default=DEFAULT_PAPER_ROOT,
        help="Paper automation root (default: docs/data/paper_automation)",
    )
    warm_p.add_argument(
        "--force",
        action="store_true",
        help="Re-seed even when endurance_zero_datum already exists",
    )
    warm_p.add_argument("--json", action="store_true")
    warm_p.set_defaults(func=_cmd_warm_start_fair_lab)

    twins_p = sub.add_parser(
        "spawn-fair-twins",
        help=(
            "Human-only: spawn Suite B fair-cost twins for experiment_assessment "
            "recommend rows (default dry-run; never auto-fork)"
        ),
    )
    twins_p.add_argument(
        "--paper-root",
        type=Path,
        default=DEFAULT_PAPER_ROOT,
        help="Paper automation root (default: docs/data/paper_automation)",
    )
    twins_p.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Data dir with experiment_assessment.json (default: docs/data)",
    )
    twins_p.add_argument(
        "--market",
        default="ftse350",
        help="Market id for fair cost stamps (default: ftse350)",
    )
    twins_p.add_argument(
        "--max-spawns",
        type=int,
        default=2,
        help="Cap new twins this invocation (default: 2)",
    )
    twins_p.add_argument(
        "--experiment-id",
        default="",
        help="Limit to one experiment_id or track_id",
    )
    twins_mode = twins_p.add_mutually_exclusive_group()
    twins_mode.add_argument(
        "--dry-run",
        dest="apply",
        action="store_false",
        help="Preview only (default)",
    )
    twins_mode.add_argument(
        "--apply",
        dest="apply",
        action="store_true",
        help="Write fair-cost twin configs (human gate)",
    )
    twins_p.add_argument(
        "--force",
        action="store_true",
        help="Recreate an existing twin config/fund",
    )
    twins_p.add_argument("--json", action="store_true")
    twins_p.set_defaults(apply=False, func=_cmd_spawn_fair_twins)

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


def _cmd_spawn_fair_lab(args: argparse.Namespace) -> int:
    from value_investor.fair_cost_lab import spawn_fair_cost_lab

    payload = spawn_fair_cost_lab(
        args.paper_root,
        market_id=args.market,
        force=bool(args.force),
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(
        f"Suite B spawn: created={payload.get('created_count')} "
        f"spawned={payload.get('spawned_count')} market={payload.get('market_id')}"
    )
    for row in payload.get("tracks") or []:
        print(
            f"  [{row.get('track_id')}] created={row.get('created')} "
            f"parent={row.get('parent_track_id')} dir={row.get('track_dir')}"
        )
    return 0


def _cmd_warm_start_fair_lab(args: argparse.Namespace) -> int:
    from value_investor.fair_cost_lab import warm_start_fair_cost_lab

    payload = warm_start_fair_cost_lab(
        args.paper_root,
        force=bool(args.force),
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(
        f"Suite B warm-start: warm_started={payload.get('warm_started_count')} "
        f"skipped={payload.get('skipped_count')}"
    )
    for row in payload.get("tracks") or []:
        if row.get("warm_started"):
            zero = row.get("endurance_zero_datum") or {}
            print(
                f"  [{row.get('track_id')}] positions={row.get('positions')} "
                f"zero_at={zero.get('started_at')}"
            )
        else:
            print(f"  [{row.get('track_id')}] {row.get('reason') or row.get('skipped')}")
    return 0


def _cmd_spawn_fair_twins(args: argparse.Namespace) -> int:
    from value_investor.fair_cost_lab import spawn_fair_cost_twins_for_recommendations

    payload = spawn_fair_cost_twins_for_recommendations(
        args.paper_root,
        args.data_dir,
        dry_run=not bool(args.apply),
        max_spawns=int(args.max_spawns),
        experiment_id=str(args.experiment_id or "").strip() or None,
        market_id=args.market,
        force=bool(args.force),
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    mode = "dry-run" if payload.get("dry_run") else "apply"
    print(
        f"Fair twins ({mode}): recommend={payload.get('recommend_count')} "
        f"selected={payload.get('selected_count')} spawned={payload.get('spawned_count')}"
    )
    print(payload.get("note") or "")
    for row in payload.get("tracks") or []:
        print(
            f"  [{row.get('twin_track_id') or row.get('track_id')}] "
            f"parent={row.get('parent_track_id')} "
            f"spawned={row.get('spawned')} "
            f"{row.get('reason') or ''}"
        )
    for skipped in payload.get("skipped_budget") or []:
        print(f"  skipped {skipped.get('track_id')}: {skipped.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
