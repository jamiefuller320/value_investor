"""Run screener and email signal report."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from value_investor.backtest import BacktestSummary
from value_investor.historical_analysis import HistoricalAnalysisSummary, load_historical_analysis_summary
from value_investor.simulator import SimulationComparison, simulation_comparison_from_dict
from value_investor.deep_analysis import DeepAnalysis, run_deep_analysis
from value_investor.emailer import EmailConfig, format_html_report, format_text_report, send_report_email
from value_investor.constituents import DEFAULT_UNIVERSE, VALID_UNIVERSES, universe_label
from value_investor.pipeline import run_screen, write_outputs
from value_investor.publish import publish_dashboard
from value_investor.run_diff import RunDiff
from value_investor.research.format import research_documents_for_reports
from value_investor.research.overlay import apply_research_overlay, enrich_signals_with_research
from value_investor.research.runner import (
    DEFAULT_RESEARCH_WEEKLY_CAP,
    load_existing_research,
    run_research_for_strong_buys,
)
from value_investor.storage import write_json
from value_investor.summary import build_company_reports


def _load_run_diff(output_dir: Path) -> RunDiff | None:
    diff_path = output_dir / "run_diff.json"
    if not diff_path.exists():
        return None
    data = json.loads(diff_path.read_text(encoding="utf-8"))
    return RunDiff(**data)


def _load_simulation(output_dir: Path) -> SimulationComparison | None:
    path = output_dir / "simulation_summary.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if "research_overlay" in data:
        return simulation_comparison_from_dict(data)
    from value_investor.simulator import SimulationComparison, simulation_summary_from_dict

    screen = simulation_summary_from_dict(data)
    return SimulationComparison(screen=screen, overlay=screen)


def _load_backtest(output_dir: Path) -> BacktestSummary | None:
    path = output_dir / "backtest_summary.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    from value_investor.backtest import HorizonResult

    horizons = [HorizonResult(**h) for h in data.get("horizons", [])]
    return BacktestSummary(
        run_count=int(data.get("run_count", 0)),
        horizons=horizons,
        note=str(data.get("note", "")),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run FTSE screener and email signals with reason summaries"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--limit", type=int, default=None, help="Limit universe size")
    parser.add_argument(
        "--universe",
        choices=VALID_UNIVERSES,
        default=DEFAULT_UNIVERSE,
        help=f"Screening universe (default: {DEFAULT_UNIVERSE})",
    )
    parser.add_argument(
        "--include-investment-trusts",
        action="store_true",
        help=(
            "Keep investment trusts/closed-end funds in the screen "
            "(excluded by default)"
        ),
    )
    parser.add_argument(
        "--skip-screen",
        action="store_true",
        help="Reuse latest CSV outputs instead of re-running the screen",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build report files but do not send email",
    )
    parser.add_argument(
        "--deep-analysis",
        action="store_true",
        help="Run Cursor deep analysis on top 5 picks with red-flag pass (requires CURSOR_API_KEY)",
    )
    parser.add_argument(
        "--agent-intro",
        action="store_true",
        help="Alias for --deep-analysis (kept for backward compatibility)",
    )
    parser.add_argument("--model", default="composer-2.5", help="Cursor model for deep analysis")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CURSOR_API_KEY"),
        help="Cursor API key for deep analysis",
    )
    parser.add_argument("--top", type=int, default=5, help="Number of top picks for deep analysis")
    parser.add_argument(
        "--research-docs",
        action="store_true",
        help=(
            "Generate or update per-ticker research memos for strong buys and top buys "
            f"(weekly cap default {DEFAULT_RESEARCH_WEEKLY_CAP}; "
            "5-year financials + 1-year news; weekly updates on reruns)"
        ),
    )
    parser.add_argument(
        "--research-cap",
        type=int,
        default=DEFAULT_RESEARCH_WEEKLY_CAP,
        help=(
            f"Max research memos per run when --research-docs is set "
            f"(strong buys first, then top buys; default {DEFAULT_RESEARCH_WEEKLY_CAP})"
        ),
    )
    parser.add_argument(
        "--send-only",
        action="store_true",
        help="Send email from existing output/email_report.* files (skip screening)",
    )
    parser.add_argument(
        "--publish-dashboard",
        action="store_true",
        help="Publish screening output to docs/ for GitHub Pages",
    )
    parser.add_argument(
        "--dashboard-dir",
        type=Path,
        default=Path("docs"),
        help="GitHub Pages root for --publish-dashboard",
    )
    args = parser.parse_args(argv)

    if args.send_only:
        text_path = args.output_dir / "email_report.txt"
        html_path = args.output_dir / "email_report.html"
        reports_path = args.output_dir / "email_reports.json"
        if not text_path.exists() or not html_path.exists() or not reports_path.exists():
            print("Missing email report files; run ftse-email --dry-run first", file=sys.stderr)
            return 1
        reports_data = json.loads(reports_path.read_text(encoding="utf-8"))
        strong_buys = sum(1 for r in reports_data if r.get("signal") == "strong_buy")
        run_line = text_path.read_text(encoding="utf-8").splitlines()[0]
        date_match = None
        if (match := re.search(r"(\d{4}-\d{2}-\d{2})", run_line)):
            date_match = match.group(1)
        subject = f"FTSE Value Screen — {strong_buys} strong buys — {date_match or 'report'}"
        try:
            config = EmailConfig.from_env()
        except ValueError as err:
            print(str(err), file=sys.stderr)
            return 1
        send_report_email(
            subject=subject,
            text_body=text_path.read_text(encoding="utf-8"),
            html_body=html_path.read_text(encoding="utf-8"),
            config=config,
        )
        print(f"Email sent to {config.email_to}")
        return 0

    run_diff: RunDiff | None = None
    backtest: BacktestSummary | None = None
    simulation: SimulationComparison | None = None
    historical_analysis: HistoricalAnalysisSummary | None = None
    screen_universe = args.universe
    excluded_investment_vehicles = 0

    if args.skip_screen:
        signals_path = args.output_dir / "latest_signals.csv"
        model_results_path = args.output_dir / "latest_model_results.csv"
        if not signals_path.exists() or not model_results_path.exists():
            print("Missing output files; run without --skip-screen first", file=sys.stderr)
            return 1
        import pandas as pd

        signals = pd.read_csv(signals_path)
        model_results = pd.read_csv(model_results_path)
        run_at = datetime.now(UTC)
        run_diff = _load_run_diff(args.output_dir)
        backtest = _load_backtest(args.output_dir)
        simulation = _load_simulation(args.output_dir)
        historical_analysis = load_historical_analysis_summary(args.output_dir)
        summary_files = sorted(args.output_dir.glob("summary_*.json")) + sorted(
            args.output_dir.glob("summary_*.json.gz")
        )
        if summary_files:
            from value_investor.storage import read_json

            summary = read_json(summary_files[-1])
            if isinstance(summary, dict):
                excluded_investment_vehicles = int(summary.get("excluded_investment_vehicles") or 0)
                if summary.get("universe"):
                    screen_universe = str(summary["universe"])
    else:
        result = run_screen(
            limit=args.limit,
            output_dir=args.output_dir,
            universe=args.universe,
            include_investment_trusts=args.include_investment_trusts,
        )
        write_outputs(result, args.output_dir)
        signals = result.signals
        model_results = result.model_results
        run_at = result.run_at
        screen_universe = result.universe_name
        excluded_investment_vehicles = result.excluded_investment_vehicles
        run_diff = result.run_diff or _load_run_diff(args.output_dir)
        backtest = result.backtest or _load_backtest(args.output_dir)
        simulation = result.simulation or _load_simulation(args.output_dir)
        historical_analysis = load_historical_analysis_summary(args.output_dir)

    reports = build_company_reports(signals, model_results)
    run_at_str = run_at.strftime("%Y-%m-%d %H:%M UTC")

    deep_analysis: DeepAnalysis | None = None
    research_summary = None
    research_documents = research_documents_for_reports(
        reports,
        load_existing_research(
            args.output_dir,
            tickers=[r.ticker for r in reports if r.signal in ("strong_buy", "buy")],
        ),
    )

    if args.deep_analysis or args.agent_intro:
        if not args.api_key:
            print("CURSOR_API_KEY required for --deep-analysis", file=sys.stderr)
            return 1
        try:
            deep_analysis = run_deep_analysis(
                reports=reports,
                model_results_df=model_results,
                output_dir=args.output_dir,
                api_key=args.api_key,
                model=args.model,
                top_n=args.top,
            )
        except RuntimeError as err:
            print(str(err), file=sys.stderr)
            return 2
        analysis_path = args.output_dir / "deep_analysis.txt"
        analysis_path.write_text(deep_analysis.full_text, encoding="utf-8")

    if args.research_docs:
        if not args.api_key:
            print("CURSOR_API_KEY required for --research-docs", file=sys.stderr)
            return 1
        try:
            research_summary = run_research_for_strong_buys(
                reports=reports,
                output_dir=args.output_dir,
                api_key=args.api_key,
                model=args.model,
                run_at=run_at,
                weekly_cap=args.research_cap,
            )
        except RuntimeError as err:
            print(str(err), file=sys.stderr)
            return 2
        research_documents = research_documents_for_reports(reports, research_summary.documents)

    if research_documents:
        reports = apply_research_overlay(reports, research_documents)

    signals = enrich_signals_with_research(signals, args.output_dir, run_at=run_at)
    signals_path = args.output_dir / "latest_signals.csv"
    signals.to_csv(signals_path, index=False)

    text_body = format_text_report(
        run_at=run_at_str,
        reports=reports,
        run_diff=run_diff,
        deep_analysis=deep_analysis,
        backtest=backtest,
        simulation=simulation,
        historical_analysis=historical_analysis,
        research_summary=research_summary,
        research_documents=research_documents,
        screen_label=universe_label(screen_universe),
        excluded_investment_vehicles=excluded_investment_vehicles,
    )
    html_body = format_html_report(
        run_at=run_at_str,
        reports=reports,
        run_diff=run_diff,
        deep_analysis=deep_analysis,
        backtest=backtest,
        simulation=simulation,
        historical_analysis=historical_analysis,
        research_summary=research_summary,
        research_documents=research_documents,
        screen_label=universe_label(screen_universe),
        excluded_investment_vehicles=excluded_investment_vehicles,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    reports_path = args.output_dir / "email_reports.json"
    write_json(reports_path, [r.to_dict() for r in reports], compact=True)
    text_path = args.output_dir / "email_report.txt"
    html_path = args.output_dir / "email_report.html"
    text_path.write_text(text_body, encoding="utf-8")
    html_path.write_text(html_body, encoding="utf-8")

    if args.publish_dashboard:
        dashboard_path = publish_dashboard(
            output_dir=args.output_dir,
            dest_dir=args.dashboard_dir,
        )
        print(f"Published dashboard data to {dashboard_path}")

    strong_buys = sum(1 for r in reports if r.signal == "strong_buy")
    subject = (
        f"{universe_label(screen_universe)} Value Screen — "
        f"{strong_buys} strong buys — {run_at.strftime('%Y-%m-%d')}"
    )

    if args.dry_run:
        print(f"Dry run: wrote {text_path} and {html_path}")
        print(f"Subject: {subject}")
        return 0

    try:
        config = EmailConfig.from_env()
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1

    send_report_email(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        config=config,
    )
    print(f"Email sent to {config.email_to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
