"""CLI for dual-path sleeve episodes (observe-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.paper_automation import (
    CONFIG_FILENAME as AUTOMATION_CONFIG_FILENAME,
)
from value_investor.paper_automation import (
    DEFAULT_AUTOMATION_DIR,
    FUND_FILENAME,
    AutomationConfig,
    ensure_automated_fund,
    learning_track_dirs,
    load_screen_candidates,
)
from value_investor.paper_fund import PaperFund
from value_investor.sleeve_episodes import (
    ROLLUP_FILENAME,
    SleeveEpisodeConfig,
    run_sleeve_episodes_pass,
    summarize_learning_tracks_sleeve_episodes,
)

DEFAULT_REPORTS = Path("docs/data/latest.json")


def _fund_and_config(track_dir: Path) -> tuple[PaperFund, AutomationConfig]:
    config_path = track_dir / AUTOMATION_CONFIG_FILENAME
    if config_path.exists():
        config = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    else:
        config = AutomationConfig()
    fund = ensure_automated_fund(track_dir / FUND_FILENAME, config)
    return fund, config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe-only dual-path sleeve episodes: widest buy-tier lifecycle "
            "with on_book / off_book / never_funded capital tags."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_AUTOMATION_DIR,
        help="Paper automation root (default: docs/data/paper_automation)",
    )
    parser.add_argument(
        "--reports",
        type=Path,
        default=DEFAULT_REPORTS,
        help="Screen reports JSON (default: docs/data/latest.json)",
    )
    parser.add_argument(
        "--tracks",
        default="all",
        help="Comma-separated track ids or 'all'",
    )
    parser.add_argument("--json", action="store_true", help="Print rollup JSON")
    args = parser.parse_args(argv)

    base = args.output_dir
    dirs = learning_track_dirs(base)
    selected = (
        list(dirs.keys())
        if str(args.tracks).strip().lower() == "all"
        else [t.strip() for t in str(args.tracks).split(",") if t.strip()]
    )
    candidates = load_screen_candidates(args.reports)
    reviews: dict[str, object] = {}
    for track_id in selected:
        track_dir = dirs.get(track_id) or (base / track_id)
        if not track_dir.exists() and track_id not in dirs:
            print(f"skip missing track dir: {track_id}", file=sys.stderr)
            continue
        fund, config = _fund_and_config(track_dir)
        prices = {
            str(row.get("ticker")): float(row["price"])
            for row in candidates
            if row.get("ticker") and row.get("price") not in (None, "")
        }
        for ticker, pos in fund.holdings.items():
            if ticker not in prices and pos.avg_cost > 0:
                prices[ticker] = float(pos.avg_cost)
        review = run_sleeve_episodes_pass(
            output_dir=track_dir,
            fund=fund,
            track_id=str(config.track_id or track_id),
            candidates=candidates,
            trades=[],
            prices_by_ticker=prices,
            config=SleeveEpisodeConfig(
                exit_confirm_screens=int(getattr(config, "exit_confirm_screens", 2) or 2),
                use_adjusted_signal=bool(config.use_adjusted_signal),
            ),
        )
        reviews[track_id] = review
        print(
            f"{track_id}: open={review.get('open_count')} "
            f"closed={review.get('closed_count')} "
            f"ready={review.get('readiness', {}).get('ready_for_sleeve_timing_analysis')}"
        )

    rollup = summarize_learning_tracks_sleeve_episodes(base)
    (base / ROLLUP_FILENAME).write_text(json.dumps(rollup, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(rollup, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
