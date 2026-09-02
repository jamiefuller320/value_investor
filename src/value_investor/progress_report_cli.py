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
from value_investor.so_what_closure import (
    apply_so_what_auto_queue,
    build_so_what_section,
    render_so_what_markdown,
    scan_so_what_issues,
    so_what_summary_for_progress,
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

    so_p = sub.add_parser(
        "so-what",
        help="Scan honest findings, ask so-what, and optionally queue auto gap-closures",
    )
    so_p.add_argument(
        "--apply",
        action="store_true",
        help="Queue auto_queue findings into engineering_tasks.json",
    )
    so_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and show would-be tasks without writing the queue",
    )
    so_p.add_argument("--json", action="store_true", help="Print JSON snapshot to stdout")
    so_p.set_defaults(func=_cmd_so_what)

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
            so_counts = (payload.get("so_what") or {}).get("counts") or {}
            print(
                "  so_what: "
                f"findings={so_counts.get('findings', 0)}, "
                f"auto_queue={so_counts.get('auto_queue', 0)}, "
                f"human_gate={so_counts.get('human_gate', 0)}"
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


def _cmd_so_what(args: argparse.Namespace) -> int:
    if args.apply or args.dry_run:
        snapshot = apply_so_what_auto_queue(dry_run=bool(args.dry_run) and not bool(args.apply))
        section = so_what_summary_for_progress(snapshot)
    else:
        section = build_so_what_section(apply=False)
        snapshot = {
            "counts": section.get("counts") or {},
            "findings": [],
            "created_tasks": [],
        }
    if args.json:
        print(json.dumps(snapshot if (args.apply or args.dry_run) else section, indent=2))
    else:
        print(render_so_what_markdown(section))
        created = snapshot.get("created_tasks") or []
        if created and args.apply:
            print(f"Queued {len(created)} engineering task(s).")
        elif created and args.dry_run:
            print(f"Dry-run: would queue {len(created)} engineering task(s) (not written).")
        elif args.apply:
            print("No new auto_queue tasks (already open or none found).")
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
