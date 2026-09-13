"""CLI: deliberate automated Phase C readiness assessment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.phase_c_readiness import (
    DEFAULT_AI_JUDGMENT_DIR,
    DEFAULT_LATEST_PATH,
    DEFAULT_RESEARCH_ROOT,
    assess_phase_c_readiness,
    format_phase_c_readiness_text,
    write_phase_c_readiness_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Assess whether Phase C PIT decision autopsy prerequisites are met "
            "(Phase B slim, rebalance_log span, feature-flag coverage)."
        )
    )
    parser.add_argument(
        "--ai-judgment-dir",
        type=Path,
        default=DEFAULT_AI_JUDGMENT_DIR,
        help="Paper-auto AI-judgment directory containing rebalance_log.json",
    )
    parser.add_argument(
        "--research-root",
        type=Path,
        default=DEFAULT_RESEARCH_ROOT,
        help="Research store root (ticker/research.json)",
    )
    parser.add_argument(
        "--latest",
        type=Path,
        default=DEFAULT_LATEST_PATH,
        help="latest.json with report rows for feature-flag sampling",
    )
    parser.add_argument(
        "--force-phase-b-done",
        action="store_true",
        help="Operator override: treat Phase B slim prerequisite as satisfied",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write the readiness JSON report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print JSON report to stdout instead of text",
    )
    args = parser.parse_args(argv)

    report = assess_phase_c_readiness(
        ai_judgment_dir=args.ai_judgment_dir,
        research_root=args.research_root,
        latest_path=args.latest,
        force_phase_b_done=args.force_phase_b_done,
    )
    if args.json_out is not None:
        write_phase_c_readiness_report(report, args.json_out)
    if args.print_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_phase_c_readiness_text(report), end="")
        if args.json_out is not None:
            print(f"Wrote {args.json_out}", file=sys.stderr)
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
