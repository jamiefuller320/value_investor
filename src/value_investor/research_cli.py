"""CLI for buy-tier deep research documents."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.constituents import DEFAULT_UNIVERSE, VALID_UNIVERSES
from value_investor.research.format import format_research_text
from value_investor.research.runner import (
    DEFAULT_RESEARCH_WEEKLY_CAP,
    eligible_research_targets,
    run_research_for_strong_buys,
)
from value_investor.summary import build_company_reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate or update deep research memos for strong buys and top buy-rated names "
            f"(weekly cap default {DEFAULT_RESEARCH_WEEKLY_CAP})"
        )
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--skip-screen",
        action="store_true",
        help="Reuse latest_signals.csv instead of re-running the screener",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit universe when screening")
    parser.add_argument(
        "--universe",
        choices=VALID_UNIVERSES,
        default=DEFAULT_UNIVERSE,
        help=f"Screening universe when not using --skip-screen (default: {DEFAULT_UNIVERSE})",
    )
    parser.add_argument(
        "--include-investment-trusts",
        action="store_true",
        help="Merge trusts into the operating-company screen (disables separate trust track)",
    )
    parser.add_argument(
        "--skip-trust-screen",
        action="store_true",
        help="Skip the separate investment-trust track when screening",
    )
    parser.add_argument("--model", default="composer-2.5", help="Cursor model for research agent")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CURSOR_API_KEY"),
        help="Cursor API key (required)",
    )
    parser.add_argument(
        "--force-initial",
        action="store_true",
        help="Regenerate initial deep pass even if a memo already exists",
    )
    parser.add_argument(
        "--research-cap",
        type=int,
        default=DEFAULT_RESEARCH_WEEKLY_CAP,
        help=(
            f"Max memos per run (strong buys first, then top buys; default {DEFAULT_RESEARCH_WEEKLY_CAP})"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List eligible research targets without calling the research agent",
    )
    args = parser.parse_args(argv)

    if args.skip_screen:
        signals_path = args.output_dir / "latest_signals.csv"
        model_results_path = args.output_dir / "latest_model_results.csv"
        if not signals_path.exists() or not model_results_path.exists():
            print("Missing output files; run ftse-screen first", file=sys.stderr)
            return 1
        signals = pd.read_csv(signals_path)
        model_results = pd.read_csv(model_results_path)
    else:
        from value_investor.pipeline import run_screen, write_outputs

        result = run_screen(
            limit=args.limit,
            output_dir=args.output_dir,
            universe=args.universe,
            include_investment_trusts=args.include_investment_trusts,
            screen_trusts=not args.skip_trust_screen,
        )
        write_outputs(result, args.output_dir)
        signals = result.signals
        model_results = result.model_results

    reports = build_company_reports(signals, model_results)
    targets = eligible_research_targets(reports, weekly_cap=args.research_cap)
    strong_count = sum(1 for r in targets if r.signal == "strong_buy")
    buy_count = sum(1 for r in targets if r.signal == "buy")
    print(
        f"Selected {len(targets)} research target(s) "
        f"({strong_count} strong buy, {buy_count} buy; cap {args.research_cap})"
    )

    if args.dry_run:
        for report in targets:
            print(f"  • {report.name} ({report.ticker}) — {report.signal}")
        return 0

    if not args.api_key:
        print("CURSOR_API_KEY required for research generation", file=sys.stderr)
        return 1

    summary = run_research_for_strong_buys(
        reports=reports,
        output_dir=args.output_dir,
        api_key=args.api_key,
        model=args.model,
        force_initial=args.force_initial,
        weekly_cap=args.research_cap,
    )

    summary_path = args.output_dir / "research_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    from value_investor.storage import write_json

    write_json(
        summary_path,
        {
            "run_at": datetime.now(UTC).isoformat(),
            "created": summary.created,
            "updated": summary.updated,
            "skipped": summary.skipped,
            "errors": summary.errors,
            "weekly_cap": args.research_cap,
            "documents": [doc.to_dict() for doc in summary.documents],
        },
        compact=True,
    )

    preview = format_research_text(summary, summary.documents)
    if preview:
        print(preview)

    if summary.errors:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
