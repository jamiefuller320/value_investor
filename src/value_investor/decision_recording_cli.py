"""CLI for decision-time recording checklist (L386)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.decision_recording import (
    load_recording_plan,
    preview_freeze_from_rebalance_log,
    primary_recording_answers,
    validate_recording_plan,
)

DEFAULT_REBALANCE_LOG = Path("docs/data/paper_automation/ai_judgment/rebalance_log.json")


def _cmd_show_primary(_: argparse.Namespace) -> int:
    print(json.dumps(primary_recording_answers().to_dict(), indent=2))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    plan = load_recording_plan(Path(args.plan))
    errors = validate_recording_plan(plan)
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors, "plan": plan}, indent=2))
    elif errors:
        print("Recording plan incomplete:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
    else:
        print(f"Recording plan OK for strand {plan.get('strand_id')!r}")
    return 0 if not errors else 1


def _cmd_preview_freeze(args: argparse.Namespace) -> int:
    path = Path(args.rebalance_log)
    if not path.is_file():
        print(f"rebalance log not found: {path}", file=sys.stderr)
        return 2
    report = preview_freeze_from_rebalance_log(path, limit=args.limit)
    payload = report.to_dict()
    if not args.full:
        payload = {
            "rebalance_log": report.rebalance_log,
            "entry_count": report.entry_count,
            "assessed_at": report.assessed_at,
            "aggregate_missing": report.aggregate_missing,
            "latest_coverage": (report.entries[-1].get("coverage") if report.entries else None),
            "note": report.note,
        }
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out}")
    print(json.dumps(payload, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ftse-decision-recording",
        description=(
            "Decision-time recording checklist (L386): lock freeze/join/no-backfill "
            "answers before new learning strands. Observe-only freeze preview — "
            "does not enable Phase C writer."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser(
        "show-primary",
        help="Print locked primary AI-judgment recording answers",
    )
    show.set_defaults(func=_cmd_show_primary)

    validate = sub.add_parser(
        "validate",
        help="Validate a recording_plan JSON for a new strand",
    )
    validate.add_argument("--plan", required=True, help="Path to recording plan JSON")
    validate.add_argument("--json", action="store_true", help="Machine-readable result")
    validate.set_defaults(func=_cmd_validate)

    preview = sub.add_parser(
        "preview-freeze",
        help="Observe-only: coverage of Phase C freeze fields on rebalance_log",
    )
    preview.add_argument(
        "--rebalance-log",
        default=str(DEFAULT_REBALANCE_LOG),
        help=f"Path to rebalance_log.json (default: {DEFAULT_REBALANCE_LOG})",
    )
    preview.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only preview the last N entries",
    )
    preview.add_argument(
        "--full",
        action="store_true",
        help="Include per-entry ticker detail",
    )
    preview.add_argument("--json-out", default=None, help="Optional path to write JSON")
    preview.set_defaults(func=_cmd_preview_freeze)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
