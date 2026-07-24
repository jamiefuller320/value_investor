"""CLI for buy-tier deep research documents."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.constituents import DEFAULT_UNIVERSE, VALID_UNIVERSES
from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.research.format import format_research_text
from value_investor.research.runner import (
    DEFAULT_RESEARCH_ALUMNI_CAP,
    DEFAULT_RESEARCH_WEEKLY_CAP,
    run_research_for_strong_buys,
    select_research_targets,
)
from value_investor.research.store import ResearchStore
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
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Cursor model for research agent "
            "(default: CURSOR_RESEARCH_MODEL, else library policy, else composer-2.5)"
        ),
    )
    parser.add_argument(
        "--api-key",
        default=(resolve_cursor_api_key()[0] or None),
        help="Cursor API key (default: CURSOR_API_KEY_V2 then CURSOR_API_KEY)",
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
            f"Max active buy-tier memos per run "
            f"(strong buys first, then top buys; default {DEFAULT_RESEARCH_WEEKLY_CAP})"
        ),
    )
    parser.add_argument(
        "--alumni-cap",
        type=int,
        default=DEFAULT_RESEARCH_ALUMNI_CAP,
        help=(
            f"Max weekly updates for researched names that left the buy list "
            f"(oldest memos first; default {DEFAULT_RESEARCH_ALUMNI_CAP})"
        ),
    )
    parser.add_argument(
        "--no-continue-alumni",
        action="store_true",
        help="Do not refresh research for names that dropped off the buy list",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List eligible research targets without calling the research agent",
    )
    parser.add_argument(
        "--gap-fill",
        action="store_true",
        help=(
            "Run red-flag gap-fill loop from output/deep_analysis.txt instead of "
            "the normal buy-tier research selection"
        ),
    )
    parser.add_argument(
        "--gap-fill-cap",
        type=int,
        default=3,
        help="Max tickers for --gap-fill (default: 3)",
    )
    parser.add_argument(
        "--deepen-sources",
        action="store_true",
        help=(
            "Re-ingest filings with historical deepen for existing memo tickers "
            "(Companies House accounts years + RNS/PDF bodies). Does not call Cursor "
            "and does not backdate research revisions."
        ),
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated tickers for --deepen-sources (default: all memos in output-dir)",
    )
    args = parser.parse_args(argv)

    if args.deepen_sources:
        from value_investor.research.deepen_sources import deepen_sources_for_memo_tickers

        ticker_list = [t.strip() for t in str(args.tickers).split(",") if t.strip()] or None
        result = deepen_sources_for_memo_tickers(
            output_dir=args.output_dir,
            tickers=ticker_list,
            market="ftse350" if args.universe.startswith("ftse") else args.universe,
        )
        print(
            f"Deepened sources for {len(result.deepened)} memo ticker(s); "
            f"skipped={len(result.skipped)} errors={len(result.errors)}"
        )
        for row in result.deepened:
            print(
                f"  • {row['ticker']}: filings={row.get('filings_total')} "
                f"with_body={row.get('filings_with_body')}"
            )
        for err in result.errors:
            print(f"  ! {err}", file=sys.stderr)
        print(f"Wrote {args.output_dir / 'deepen_sources_summary.json'}")
        return 1 if result.errors and not result.deepened else 0

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

    if args.gap_fill:
        from value_investor.deep_analysis import _parse_deep_analysis
        from value_investor.research.gap_fill import (
            extract_gap_fill_targets,
            run_red_flag_gap_fill,
        )
        from value_investor.storage import write_json

        analysis_path = args.output_dir / "deep_analysis.txt"
        if not analysis_path.exists():
            print("Missing deep_analysis.txt; run ftse-email --deep-analysis first", file=sys.stderr)
            return 1
        deep_analysis = _parse_deep_analysis(analysis_path.read_text(encoding="utf-8"))
        targets = extract_gap_fill_targets(
            deep_analysis,
            reports,
            max_targets=int(args.gap_fill_cap),
        )
        print(f"Selected {len(targets)} gap-fill target(s) (cap={args.gap_fill_cap})")
        for target in targets:
            q0 = target.questions[0] if target.questions else ""
            print(f"  • {target.name} ({target.ticker}) — {q0[:120]}")
        if args.dry_run:
            return 0
        if not args.api_key:
            print("CURSOR_API_KEY required for research generation", file=sys.stderr)
            return 1
        model = args.model or os.environ.get("CURSOR_RESEARCH_MODEL") or "composer-2.5"
        print(f"Research model: {model}")
        gap_summary = run_red_flag_gap_fill(
            deep_analysis=deep_analysis,
            reports=reports,
            output_dir=args.output_dir,
            api_key=args.api_key,
            model=model,
            max_targets=int(args.gap_fill_cap),
            market="ftse350",
        )
        write_json(
            args.output_dir / "gap_fill_summary.json",
            {"run_at": datetime.now(UTC).isoformat(), **gap_summary.to_dict()},
            compact=True,
        )
        print(
            f"Gap-fill complete: created={gap_summary.created} "
            f"updated={gap_summary.updated} errors={len(gap_summary.errors)}"
        )
        for error in gap_summary.errors:
            print(f"  ! {error}", file=sys.stderr)
        return 1 if gap_summary.errors and not gap_summary.documents else 0

    store = ResearchStore(args.output_dir)
    active, alumni = select_research_targets(
        reports,
        store,
        weekly_cap=args.research_cap,
        continue_alumni=not args.no_continue_alumni,
        alumni_cap=args.alumni_cap,
    )
    targets = [*active, *alumni]
    strong_count = sum(1 for r in active if r.signal == "strong_buy")
    buy_count = sum(1 for r in active if r.signal == "buy")
    print(
        f"Selected {len(targets)} research target(s) "
        f"({strong_count} strong buy, {buy_count} buy, {len(alumni)} alumni; "
        f"caps active={args.research_cap} alumni={args.alumni_cap})"
    )

    if args.dry_run:
        for report in active:
            print(f"  • {report.name} ({report.ticker}) — {report.signal}")
        for report in alumni:
            print(f"  • {report.name} ({report.ticker}) — {report.signal} [alumni]")
        return 0

    if not args.api_key:
        print("CURSOR_API_KEY required for research generation", file=sys.stderr)
        return 1

    model = args.model or os.environ.get("CURSOR_RESEARCH_MODEL")
    if not model:
        try:
            from value_investor.agent_model_policy import research_model_id

            model = research_model_id()
        except Exception:  # noqa: BLE001
            model = "composer-2.5"
    print(f"Research model: {model}")

    summary = run_research_for_strong_buys(
        reports=reports,
        output_dir=args.output_dir,
        api_key=args.api_key,
        model=model,
        force_initial=args.force_initial,
        weekly_cap=args.research_cap,
        continue_alumni=not args.no_continue_alumni,
        alumni_cap=args.alumni_cap,
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
            "alumni_cap": args.alumni_cap,
            "continue_alumni": not args.no_continue_alumni,
            "active_count": summary.active_count,
            "alumni_count": summary.alumni_count,
            "alumni_updated": summary.alumni_updated,
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
