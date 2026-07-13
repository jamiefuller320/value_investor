"""CLI to publish screening output to the GitHub Pages dashboard."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from value_investor.publish import empty_dashboard_bundle, publish_dashboard
from value_investor.storage import write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish screening artifacts to the docs/ GitHub Pages dashboard"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory containing latest_signals.csv, email_reports.json, etc.",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("docs"),
        help="GitHub Pages root (default: docs/)",
    )
    parser.add_argument(
        "--init-empty",
        action="store_true",
        help="Write an empty data/latest.json placeholder (no screening run required)",
    )
    parser.add_argument(
        "--skip-research",
        action="store_true",
        help="Do not copy research memos into docs/research/",
    )
    args = parser.parse_args(argv)

    args.dest.mkdir(parents=True, exist_ok=True)

    if args.init_empty:
        data_dir = args.dest / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / "latest.json"
        write_json(path, empty_dashboard_bundle(), compact=True)
        print(f"Wrote placeholder {path}")
        return 0

    signals = args.output_dir / "latest_signals.csv"
    if not signals.exists():
        print(f"No screening output found at {signals}; run ftse-screen first", file=sys.stderr)
        return 1

    path = publish_dashboard(
        output_dir=args.output_dir,
        dest_dir=args.dest,
        include_research=not args.skip_research,
    )
    print(f"Published dashboard data to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
