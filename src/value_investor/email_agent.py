"""Run screener and email signal report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.emailer import EmailConfig, format_html_report, format_text_report, send_report_email
from value_investor.pipeline import run_screen, write_outputs
from value_investor.summary import build_company_reports


def _build_agent_intro_prompt(reports_json_path: Path) -> str:
    return f"""You are a value investing analyst. Read the JSON file at {reports_json_path}
containing FTSE 100 screening results (signal + summary per company).

Write a 3–5 sentence executive introduction for an email report:
- Overall market tone from signal distribution (strong buys vs avoids)
- Any sector clusters among top picks
- One caution about data limitations

Plain text only, no markdown. Do not list every company — that comes in the table below.
"""


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
        "--agent-intro",
        action="store_true",
        help="Use Cursor SDK to write an executive intro paragraph (requires CURSOR_API_KEY)",
    )
    parser.add_argument("--model", default="composer-2.5", help="Cursor model for --agent-intro")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CURSOR_API_KEY"),
        help="Cursor API key for --agent-intro",
    )
    args = parser.parse_args(argv)

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
    else:
        result = run_screen(limit=args.limit)
        write_outputs(result, args.output_dir)
        signals = result.signals
        model_results = result.model_results
        run_at = result.run_at

    reports = build_company_reports(signals, model_results)
    run_at_str = run_at.strftime("%Y-%m-%d %H:%M UTC")

    text_body = format_text_report(run_at=run_at_str, reports=reports)
    html_body = format_html_report(run_at=run_at_str, reports=reports)

    if args.agent_intro:
        if not args.api_key:
            print("CURSOR_API_KEY required for --agent-intro", file=sys.stderr)
            return 1

        reports_path = args.output_dir / "email_reports.json"
        reports_path.write_text(
            json.dumps([r.to_dict() for r in reports], indent=2),
            encoding="utf-8",
        )
        try:
            agent_result = Agent.prompt(
                _build_agent_intro_prompt(reports_path.resolve()),
                AgentOptions(
                    api_key=args.api_key,
                    model=args.model,
                    local=LocalAgentOptions(cwd=os.getcwd()),
                ),
            )
        except CursorAgentError as err:
            print(f"Agent startup failed: {err.message}", file=sys.stderr)
            return 1
        if agent_result.status == "error":
            print(f"Agent run failed: {agent_result.id}", file=sys.stderr)
            return 2
        intro = (agent_result.result or "").strip()
        if intro:
            text_body = f"{intro}\n\n{text_body}"
            html_body = html_body.replace(
                '<p style="color:#666">',
                f"<p>{intro}</p><p style=\"color:#666\">",
                1,
            )

    args.output_dir.mkdir(parents=True, exist_ok=True)
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
