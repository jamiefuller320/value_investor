"""CLI for the model-independent entry DCA / graduated-entry overlay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from value_investor.entry_dca_overlay import (
    ROLLUP_FILENAME,
    run_entry_dca_overlay_pass,
    summarize_learning_tracks_entry_dca,
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
from value_investor.rebalance_log import snapshot_holdings

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
            "Observe-only dollar-cost-averaging overlay: score counterfactual "
            "entry cadences on every paper track's new buys (does not trade)."
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
        else [item.strip() for item in str(args.tracks).split(",") if item.strip()]
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
        buy_cost = float(getattr(config, "buy_cost_pct", None) or config.trade_cost_pct or 0.0)
        as_of = str(fund.last_mark_at or "")
        reviews[track_id] = run_entry_dca_overlay_pass(
            output_dir=track_dir,
            track_id=track_id,
            trades=[],
            holdings_before=snapshot_holdings(fund),
            holdings_after_tickers=set(fund.holdings),
            candidates=candidates,
            prices_by_ticker=price_map,
            buy_cost_pct=buy_cost,
            as_of=as_of or "1970-01-01T00:00:00+00:00",
        )

    rollup = summarize_learning_tracks_entry_dca(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / ROLLUP_FILENAME).write_text(json.dumps(rollup, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps({"tracks": reviews, "rollup": rollup}, indent=2))
    else:
        print(f"Wrote entry DCA overlay for {len(reviews)} track(s)")
        print(f"Rollup: {base_dir / ROLLUP_FILENAME}")
        readiness = rollup.get("readiness") or {}
        print(
            f"  scored={rollup.get('scored_count')} "
            f"tracks={rollup.get('tracks_with_closed')} "
            f"ready={readiness.get('ready_for_cadence_analysis')} "
            f"leading={rollup.get('leading_cadence')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
