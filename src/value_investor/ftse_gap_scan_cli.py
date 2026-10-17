"""CLI for the FTSE gap scan and a one-ticker annual-statement fetch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from value_investor.ftse_gap_scan import (
    CHECKS,
    HOW_TO_ADD_A_CHECK,
    load_roster,
    load_screen_rows,
    render_roster_split,
    repo_root_from_here,
    scan_ftse_gaps,
)


def _cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.root)
    hits = scan_ftse_gaps(root)
    rows = load_screen_rows(root)
    if args.json and args.roster is None:
        payload = {
            "hits": [
                {"rule_id": hit.rule_id, "ticker": hit.ticker, "detail": hit.detail} for hit in hits
            ],
            "tickers": [row.ticker for row in rows],
        }
        print(json.dumps(payload, indent=2))
        return 0

    if args.roster is None:
        text = _screen_only_report(hits, [row.ticker for row in rows])
    else:
        roster = load_roster(Path(args.roster))
        text = render_roster_split(
            hits=hits,
            roster=roster,
            from_rank=int(args.from_rank),
            screen_tickers={row.ticker for row in rows},
        )
        if args.json:
            print(text)
            return 0
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        print(f"wrote {destination}")
    else:
        print(text)
    return 0


def _screen_only_report(hits: list, tickers: list[str]) -> str:
    by_ticker: dict[str, list] = {}
    for hit in hits:
        by_ticker.setdefault(hit.ticker, []).append(hit)
    covered = [ticker for ticker in tickers if by_ticker.get(ticker)]
    needs = [ticker for ticker in tickers if ticker not in by_ticker]
    lines = [
        "# FTSE gap scan",
        "",
        "Roster file was not read. Universe is the stored FTSE screen",
        "(`reports` then `trust_reports` in `docs/data/latest.json`).",
        "",
        f"- Covered by a known rule: {len(covered)}",
        f"- Still need an agent: {len(needs)}",
        "",
    ]
    return "\n".join(lines)


def _cmd_fetch(args: argparse.Namespace) -> int:
    from value_investor.ftse_statement_fetch import (
        fetch_one_annual_statement,
        statement_key_summary,
    )

    sources = Path(args.sources_dir) if args.sources_dir else None
    result = fetch_one_annual_statement(args.ticker, sources_dir=sources)
    summary = statement_key_summary(result.payload)
    print(
        f"ticker={result.ticker} dry_run={str(result.dry_run).lower()} "
        f"income_years={summary['income_statement']} "
        f"balance_years={summary['balance_sheet']} "
        f"cashflow_years={summary['cash_flow']} "
        f"written={result.written or ''}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ftse-gap-scan",
        description=(
            "Scan stored FTSE files for handover gaps, or fetch one missing "
            "annual statement via the existing yfinance path."
        ),
        epilog=HOW_TO_ADD_A_CHECK
        + "\n\nChecks:\n"
        + "\n".join(f"  {check.rule_id}: {check.summary}" for check in CHECKS),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser(
        "scan",
        help="Read stored FTSE files and list rule hits",
        description="Read stored FTSE files and list rule hits.",
        epilog=HOW_TO_ADD_A_CHECK,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scan.add_argument("--root", type=Path, default=repo_root_from_here())
    scan.add_argument(
        "--roster",
        type=Path,
        default=None,
        help="FTSE 350 order markdown. Omit to use the repo screen list only.",
    )
    scan.add_argument(
        "--from-rank",
        type=int,
        default=131,
        help="First roster rank to split (default 131, BMY.L on the current roster)",
    )
    scan.add_argument("--output", type=Path, default=None, help="Write the markdown report here")
    scan.add_argument("--json", action="store_true", help="Print hit JSON when no roster is given")
    scan.set_defaults(func=_cmd_scan)

    fetch = sub.add_parser(
        "fetch",
        help="Fetch one missing annual statement (dry run unless --sources-dir)",
        description=(
            "Fetch one ticker through fetch_annual_financials. "
            "Does not walk the FTSE list. Omit --sources-dir for a dry run."
        ),
    )
    fetch.add_argument("--ticker", required=True, help="One ticker, for example BMY.L")
    fetch.add_argument(
        "--sources-dir",
        type=Path,
        default=None,
        help="Write financials_annual.json here. Omit to keep the dry run.",
    )
    fetch.set_defaults(func=_cmd_fetch)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
