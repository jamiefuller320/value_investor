"""CLI for buy-tier ingest fragment utilization audit."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from value_investor.ingest_utilization_audit import (
    DEFAULT_LATEST_PATH,
    DEFAULT_MEMO_DIR,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_RESEARCH_ROOT,
    format_audit_summary,
    run_ingest_utilization_audit,
    write_ingest_utilization_audit,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit buy-tier ingest fragment utilization vs screen overlay and paper gates"
        ),
    )
    parser.add_argument("--latest-path", type=Path, default=DEFAULT_LATEST_PATH)
    parser.add_argument("--research-root", type=Path, default=DEFAULT_RESEARCH_ROOT)
    parser.add_argument("--memo-dir", type=Path, default=DEFAULT_MEMO_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Write full JSON audit (default: output/ingest_utilization_audit.json)",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON to stdout")
    parser.add_argument("--no-write", action="store_true", help="Skip writing output file")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    payload = run_ingest_utilization_audit(
        latest_path=args.latest_path,
        research_root=args.research_root,
        memo_dir=args.memo_dir,
    )

    if not args.no_write:
        written = write_ingest_utilization_audit(payload, args.output)
        logger.info("Wrote %s", written)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_audit_summary(payload))

    return 0


if __name__ == "__main__":
    sys.exit(main())
