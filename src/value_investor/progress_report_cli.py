"""CLI for the standardised FTSE progress report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.progress_report import (
    DEFAULT_MARKDOWN_PATH,
    DEFAULT_REPORT_PATH,
    build_progress_report,
    format_progress_report_markdown,
    write_progress_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Standardised progress report: north-star appraisal, actionable deferred items, "
            "and join-up / role coherence checks"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser("build", help="Build progress report (stdout, optional write)")
    build_p.add_argument("--json", action="store_true", help="Print JSON to stdout")
    build_p.add_argument(
        "--write",
        action="store_true",
        help=f"Write {DEFAULT_REPORT_PATH} and {DEFAULT_MARKDOWN_PATH}",
    )
    build_p.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    build_p.add_argument("--markdown-path", type=Path, default=DEFAULT_MARKDOWN_PATH)
    build_p.set_defaults(func=_cmd_build)

    md_p = sub.add_parser("markdown", help="Render markdown from an existing JSON report")
    md_p.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Existing progress_report.json (default: build fresh)",
    )
    md_p.add_argument("--fresh", action="store_true", help="Ignore saved JSON; build fresh")
    md_p.set_defaults(func=_cmd_markdown)

    args = parser.parse_args(argv)
    return int(args.func(args))


def _cmd_build(args: argparse.Namespace) -> int:
    if args.write:
        payload = write_progress_report(
            json_path=args.report_path,
            markdown_path=args.markdown_path,
        )
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Progress report: {payload.get('overall')}")
            print(f"  JSON: {args.report_path}")
            print(f"  Markdown: {args.markdown_path}")
            counts = (payload.get("actionable") or {}).get("counts") or {}
            print(
                "  actionable: "
                f"defer_now={counts.get('defer_now', 0)}, "
                f"fragments={counts.get('open_fragments', 0)}, "
                f"proposed={counts.get('proposed_total', 0)}, "
                f"engineering_open={counts.get('engineering_open', 0)}"
            )
    else:
        payload = build_progress_report()
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(format_progress_report_markdown(payload))
    if payload.get("overall") == "fail":
        return 1
    return 0


def _cmd_markdown(args: argparse.Namespace) -> int:
    if args.fresh or not args.report_path.exists():
        payload = build_progress_report()
    else:
        payload = json.loads(args.report_path.read_text(encoding="utf-8"))
    print(format_progress_report_markdown(payload))
    return 0 if payload.get("overall") != "fail" else 1


if __name__ == "__main__":
    sys.exit(main())
