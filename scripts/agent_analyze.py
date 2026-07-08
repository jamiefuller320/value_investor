"""Cursor SDK agent integration for qualitative analysis of screen results."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.pipeline import run_screen, write_outputs


def _build_analysis_prompt(signals_path: Path, top_n: int) -> str:
    return f"""You are a value investing analyst reviewing FTSE 100 screening output.

Read the signals file at: {signals_path}

Focus on the top {top_n} candidates by signal rank. For each:
1. Summarize why the quantitative models flagged it (P/E, P/B, yield, quality metrics).
2. Note sector concentration risk if several names cluster in one industry.
3. List 2–3 qualitative risks NOT captured by the screen (regulatory, cyclicality, pension deficits, etc.).
4. Give a concise verdict: accumulate / watchlist / pass — with one sentence rationale.

Do not invent financial figures; cite only what is in the CSV. End with a ranked shortlist of up to 5 names worth deeper research.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run FTSE 100 screen then ask a Cursor agent to analyze top picks"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--limit", type=int, default=None, help="Limit universe size for fetch")
    parser.add_argument("--top", type=int, default=10, help="Number of top signals for agent review")
    parser.add_argument("--model", default="composer-2.5", help="Cursor model id")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CURSOR_API_KEY"),
        help="Cursor API key (defaults to CURSOR_API_KEY env var)",
    )
    parser.add_argument(
        "--skip-screen",
        action="store_true",
        help="Reuse output/latest_signals.csv instead of re-running the screen",
    )
    args = parser.parse_args(argv)

    if not args.api_key:
        print("CURSOR_API_KEY is required", file=sys.stderr)
        return 1

    signals_path = args.output_dir / "latest_signals.csv"
    if not args.skip_screen:
        result = run_screen(limit=args.limit)
        paths = write_outputs(result, args.output_dir)
        signals_path = paths["latest"]
    elif not signals_path.exists():
        print(f"No existing signals at {signals_path}; run without --skip-screen first", file=sys.stderr)
        return 1

    prompt = _build_analysis_prompt(signals_path.resolve(), args.top)

    try:
        agent_result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=args.api_key,
                model=args.model,
                local=LocalAgentOptions(cwd=os.getcwd()),
            ),
        )
    except CursorAgentError as err:
        print(f"Agent startup failed: {err.message} (retryable={err.is_retryable})", file=sys.stderr)
        return 1

    if agent_result.status == "error":
        print(f"Agent run failed: {agent_result.id}", file=sys.stderr)
        return 2

    print(agent_result.result or "")
    report_path = args.output_dir / "agent_analysis.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(agent_result.result or "", encoding="utf-8")
    print(f"\nSaved analysis to {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
