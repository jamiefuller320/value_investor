"""CLI for independent daily paper-fund automation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.paper_automation import (
    AI_JUDGMENT_TRACK_ID,
    DEFAULT_AUTOMATION_DIR,
    RULES_TRACK_ID,
    AutomationConfig,
    format_automation_text,
    learning_track_dirs,
    run_daily_automation,
    run_learning_tracks,
    save_watchlist,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run independent automated paper-fund decisions after London open settle, "
            "with surveillance of paper + owned watchlist holdings. "
            "Default --tracks all runs the primary AI-judgment learning track plus "
            "the rules control book."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_AUTOMATION_DIR,
        help="Root directory for learning tracks (rules at root, ai_judgment/ subdir)",
    )
    parser.add_argument(
        "--reports",
        type=Path,
        default=None,
        help="Path to latest.json (or bundle) with screen reports",
    )
    parser.add_argument(
        "--settle-minutes",
        type=int,
        default=None,
        help="Minutes after 08:00 Europe/London before acting (default: 75 ≈ 09:15)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Act even before settle / on non-trading days (for testing)",
    )
    parser.add_argument(
        "--surveillance-only",
        action="store_true",
        help="Do not rebalance; only refresh marks and emit alerts",
    )
    parser.add_argument(
        "--tracks",
        default="all",
        choices=["all", "rules", "ai_judgment"],
        help="Which learning track(s) to run (default: all)",
    )
    parser.add_argument(
        "--add-watch",
        action="append",
        default=[],
        metavar="TICKER",
        help="Add a real/live owned ticker to the surveillance watchlist (repeatable)",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON result")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.add_watch:
        watch_path = output_dir / "owned_watchlist.json"
        existing = []
        if watch_path.exists():
            payload = json.loads(watch_path.read_text(encoding="utf-8"))
            existing = payload.get("holdings") or []
        have = {str(row.get("ticker") if isinstance(row, dict) else row) for row in existing}
        for ticker in args.add_watch:
            if ticker not in have:
                existing.append({"ticker": ticker, "name": ticker, "source": "live"})
                have.add(ticker)
        save_watchlist(watch_path, existing)

    if args.tracks == "all":
        from value_investor.paper_automation import ensure_learning_track_configs

        configs = ensure_learning_track_configs(output_dir)
        if args.settle_minutes is not None:
            for track_id, cfg in configs.items():
                cfg.settle_minutes_after_open = args.settle_minutes
                cfg_path = learning_track_dirs(output_dir)[track_id] / "config.json"
                cfg_path.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")
        summary = run_learning_tracks(
            base_dir=output_dir,
            reports_path=args.reports,
            force=args.force,
            surveillance_only=args.surveillance_only,
        )
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print("Learning tracks")
            print(f"  Primary: {summary.get('primary_learning_track')}")
            print(f"  Success: {summary.get('success_criterion')}")
            for track_id, row in (summary.get("tracks") or {}).items():
                print(
                    f"  [{track_id}] acted={row.get('acted')} trades={row.get('trades')} "
                    f"primary={row.get('is_primary_learning_track')} — {row.get('note')}"
                )
            print(f"\nWrote {output_dir / 'learning_tracks_summary.json'}")
        return 0

    track_id = RULES_TRACK_ID if args.tracks == "rules" else AI_JUDGMENT_TRACK_ID
    track_dir = learning_track_dirs(output_dir)[track_id]
    track_dir.mkdir(parents=True, exist_ok=True)

    config = AutomationConfig()
    config_path = track_dir / "config.json"
    if config_path.exists():
        config = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    if args.tracks == "ai_judgment":
        config.track_id = AI_JUDGMENT_TRACK_ID
        config.is_primary_learning_track = True
        config.use_adjusted_signal = True
        config.require_research_accumulate = True
        config.track_label = "AI judgment (research accumulate + adjusted_signal)"
    else:
        config.track_id = RULES_TRACK_ID
        config.is_primary_learning_track = False
        config.use_adjusted_signal = False
        config.require_research_accumulate = False
    if args.settle_minutes is not None:
        config.settle_minutes_after_open = args.settle_minutes
    if args.surveillance_only:
        config.auto_rebalance = False

    result = run_daily_automation(
        output_dir=track_dir,
        config=config,
        reports_path=args.reports,
        force=args.force,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_automation_text(result))
        print(f"\nWrote {track_dir / 'last_run.json'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
