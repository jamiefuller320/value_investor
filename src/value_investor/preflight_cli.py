"""CLI for pre-flight checks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from value_investor.preflight import run_preflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check environment and artifacts before the weekly FTSE screen run"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--require-email",
        action="store_true",
        help="Fail if SMTP secrets are not configured",
    )
    parser.add_argument(
        "--require-agents",
        action="store_true",
        help="Fail if CURSOR_API_KEY is not set",
    )
    args = parser.parse_args(argv)

    report = run_preflight(
        args.output_dir,
        require_email=args.require_email,
        require_agents=args.require_agents,
    )
    print(report.to_text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
