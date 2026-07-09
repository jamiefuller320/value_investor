"""Run screener and email signal report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from value_investor.backtest import BacktestSummary
from value_investor.simulator import SimulationSummary
from value_investor.deep_analysis import DeepAnalysis, run_deep_analysis
from value_investor.emailer import EmailConfig, format_html_report, format_text_report, send_report_email
from value_investor.pipeline import run_screen, write_outputs
from value_investor.run_diff import RunDiff
from value_investor.summary import build_company_reports


def _load_run_diff(output_dir: Path) -> RunDiff | None:
    diff_path = output_dir / "run_diff.json"
    if not diff_path.exists():
        return None
    data = json.loads(diff_path.read_text(encoding="utf-8"))
    return RunDiff(**data)


def _load_simulation(output_dir: Path) -> SimulationSummary | None:
    path = output_dir / "simulation_summary.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    from value_investor.simulator import Trade

    trades = [Trade(**t) for t in data.get("trades", [])]
    return SimulationSummary(
        initial_capital=float(data["initial_capital"]),
        final_value=float(data["final_value"]),
        total_return=float(data["total_return"]),
        benchmark_return=float(data["benchmark_return"]),
        excess_return=float(data["excess_return"]),
        trade_count=int(data["trade_count"]),
        total_costs=float(data["total_costs"]),
        periods=int(data["periods"]),
        holdings=data.get("holdings", {}),
        trade_cost_pct=float(data.get("trade_cost_pct", 0.03)),
        trades=trades,
        equity_curve=data.get("equity_curve", []),
        note=str(data.get("note", "")),
    )


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
        description="Run FTSE 100 screener and email signals with reason summaries"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--limit", type=int, default=None, help="Limit universe size")
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
    args = parser.parse_args(argv)

    run_diff: RunDiff | None = None
    backtest: BacktestSummary | None = None
    simulation: SimulationSummary | None = None

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
    else:
        result = run_screen(limit=args.limit, output_dir=args.output_dir)
        write_outputs(result, args.output_dir)
        signals = result.signals
        model_results = result.model_results
        run_at = result.run_at
        run_diff = result.run_diff or _load_run_diff(args.output_dir)
        backtest = result.backtest or _load_backtest(args.output_dir)
        simulation = result.simulation or _load_simulation(args.output_dir)

    reports = build_company_reports(signals, model_results)
    run_at_str = run_at.strftime("%Y-%m-%d %H:%M UTC")

    deep_analysis: DeepAnalysis | None = None
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

    text_body = format_text_report(
        run_at=run_at_str,
        reports=reports,
        run_diff=run_diff,
        deep_analysis=deep_analysis,
        backtest=backtest,
        simulation=simulation,
    )
    html_body = format_html_report(
        run_at=run_at_str,
        reports=reports,
        run_diff=run_diff,
        deep_analysis=deep_analysis,
        backtest=backtest,
        simulation=simulation,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    reports_path = args.output_dir / "email_reports.json"
    reports_path.write_text(
        json.dumps([r.to_dict() for r in reports], indent=2),
        encoding="utf-8",
    )
    text_path = args.output_dir / "email_report.txt"
    html_path = args.output_dir / "email_report.html"
    text_path.write_text(text_body, encoding="utf-8")
    html_path.write_text(html_body, encoding="utf-8")

    strong_buys = sum(1 for r in reports if r.signal == "strong_buy")
    subject = f"FTSE 100 Value Screen — {strong_buys} strong buys — {run_at.strftime('%Y-%m-%d')}"

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
