"""CLI for Supabase dashboard command bridge."""

from __future__ import annotations

import argparse
import json
import sys

from value_investor.dashboard_bridge import process_pending_dashboard_commands
from value_investor.queue_health import refresh_queue_health_ui


def _print_json(payload: object) -> None:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _cmd_process_pending(args: argparse.Namespace) -> int:
    result = process_pending_dashboard_commands(limit=args.limit, dry_run=args.dry_run)
    if args.json:
        _print_json(result)
    else:
        processed = result.get("processed") or []
        print(f"processed={len(processed)} ok={result.get('ok')} reason={result.get('reason', '')}")
        for row in processed:
            print(f"  {row}")
    if not result.get("ok") and result.get("reason") == "supabase_not_configured":
        return 0
    return 0 if result.get("ok") else 1


def _cmd_refresh_queue_health(args: argparse.Namespace) -> int:
    open_prs = None
    if args.open_prs_json:
        payload = json.loads(open(args.open_prs_json, encoding="utf-8").read())
        open_prs = list(payload) if isinstance(payload, list) else None
    result = refresh_queue_health_ui(open_prs=open_prs)
    if args.json:
        _print_json(result)
    else:
        print(
            f"queue_health overall={result.get('overall')} "
            f"merge={result.get('merge_lane')} agent={result.get('agent_lane')}"
        )
    return 0


def _cmd_refresh_lifecycle_maturity(args: argparse.Namespace) -> int:
    """Ad-hoc drill-down for L463 — production path is ops-monitor / queue-health."""
    from value_investor.lifecycle_maturity_trajectory import (
        refresh_lifecycle_maturity_trajectory,
    )

    snap = refresh_lifecycle_maturity_trajectory()
    if args.json:
        _print_json(snap)
    else:
        traj = snap.get("trajectory_summary") or {}
        print(
            f"lifecycle_maturity markets={snap.get('market_count')} "
            f"freshness={snap.get('surface_freshness')} "
            f"history={traj.get('history_points')} "
            f"traj↑{traj.get('improving')}/↓{traj.get('worsening')}"
        )
        print(snap.get("headline") or "")
    return 0


def _cmd_refresh_lifecycle_board(args: argparse.Namespace) -> int:
    """Ad-hoc L468 light board refresh — production path is ops-monitor collect."""
    from value_investor.lifecycle_board import maybe_refresh_lifecycle_board

    result = maybe_refresh_lifecycle_board(force=bool(args.force))
    if args.json:
        # Avoid dumping the full board payload on CLI stdout.
        slim = {k: v for k, v in result.items() if k != "payload"}
        market_count = 0
        payload = result.get("payload")
        if isinstance(payload, dict):
            markets = payload.get("markets")
            if isinstance(markets, list):
                market_count = len(markets)
        slim["market_count"] = market_count
        _print_json(slim)
    else:
        print(
            f"lifecycle_board refreshed={result.get('refreshed')} "
            f"age_h={result.get('age_hours')} "
            f"generated_at={result.get('generated_at')}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FTSE dashboard Supabase bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    pending_p = sub.add_parser("process-pending", help="Poll Supabase and dispatch GitHub events")
    pending_p.add_argument("--limit", type=int, default=10)
    pending_p.add_argument("--dry-run", action="store_true")
    pending_p.add_argument("--json", action="store_true")
    pending_p.set_defaults(func=_cmd_process_pending)

    health_p = sub.add_parser("refresh-queue-health", help="Write docs/data/queue_health.json")
    health_p.add_argument("--open-prs-json")
    health_p.add_argument("--json", action="store_true")
    health_p.set_defaults(func=_cmd_refresh_queue_health)

    maturity_p = sub.add_parser(
        "refresh-lifecycle-maturity",
        help="Write docs/data/lifecycle_maturity_trajectory.json (L463 observe twin)",
    )
    maturity_p.add_argument("--json", action="store_true")
    maturity_p.set_defaults(func=_cmd_refresh_lifecycle_maturity)

    board_p = sub.add_parser(
        "refresh-lifecycle-board",
        help="Light-rebuild docs/data/lifecycle_board.json when stale (L468)",
    )
    board_p.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when board age is under the light-refresh window",
    )
    board_p.add_argument("--json", action="store_true")
    board_p.set_defaults(func=_cmd_refresh_lifecycle_board)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
