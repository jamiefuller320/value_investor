"""CLI for hypothesis-integrity / in-portfolio loser-feedback reviews."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from value_investor.hypothesis_integrity import (
    ROLLUP_FILENAME,
    run_hypothesis_integrity_pass,
    summarize_learning_tracks_hypothesis_integrity,
)
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
            "Hypothesis-first underwater review: check whether facts still support "
            "the investment thesis, and aggregate in-portfolio losers as selection "
            "feedback (observe-only)."
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
        help="Screen reports path",
    )
    parser.add_argument(
        "--tracks",
        default="all",
        help="Comma-separated track ids, or 'all'",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    args = parser.parse_args(argv)

    base_dir = Path(args.output_dir)
    dirs = learning_track_dirs(base_dir)
    selected = (
        list(dirs.keys())
        if str(args.tracks).strip().lower() == "all"
        else [t.strip() for t in str(args.tracks).split(",") if t.strip()]
    )
    candidates = load_screen_candidates(Path(args.reports))
    price_map: dict[str, float] = {
        str(row.get("ticker")): float(row.get("price") or row.get("last") or 0)
        for row in candidates
        if row.get("ticker") and (row.get("price") or row.get("last"))
    }

    reviews: dict[str, Any] = {}
    for track_id in selected:
        track_dir = dirs.get(track_id) or (base_dir / track_id)
        if not track_dir.exists():
            continue
        fund, config = _fund_and_config(track_dir)
        for ticker, position in fund.holdings.items():
            if ticker not in price_map and position.avg_cost > 0:
                price_map[ticker] = float(position.avg_cost)
        reviews[track_id] = run_hypothesis_integrity_pass(
            output_dir=track_dir,
            fund=fund,
            track_id=track_id,
            candidates=candidates,
            prices_by_ticker=price_map,
            use_adjusted_signal=bool(config.use_adjusted_signal),
        )

    rollup = summarize_learning_tracks_hypothesis_integrity(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / ROLLUP_FILENAME).write_text(json.dumps(rollup, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps({"tracks": reviews, "rollup": rollup}, indent=2))
    else:
        print(f"Wrote hypothesis integrity for {len(reviews)} track(s)")
        print(f"Rollup: {base_dir / ROLLUP_FILENAME}")
        for track_id, payload in reviews.items():
            fb = payload.get("portfolio_feedback") or {}
            print(
                f"  {track_id}: losers={fb.get('loser_count')}/"
                f"{fb.get('holding_count')} "
                f"hint={fb.get('balancing_hint')} "
                f"within_tol={fb.get('within_tolerance')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
