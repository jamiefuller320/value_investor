"""CLI for unified experiment assessment ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.entry_dca_adoption import (
    evaluate_entry_dca_adoption_plan,
    first_entry_by_track,
)
from value_investor.experiment_acks import record_ack
from value_investor.experiment_assessment import (
    ASSESSMENT_FILENAME,
    refresh_experiment_assessment,
    slim_experiment_assessment_for_review,
)
from value_investor.storage import read_json

DEFAULT_DATA_DIR = Path("docs/data")


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _cmd_refresh(args: argparse.Namespace) -> int:
    payload = refresh_experiment_assessment(
        Path(args.data_dir),
        paper_root=Path(args.paper_root) if args.paper_root else None,
        min_marks=int(args.min_marks),
        min_excess_vs_market=float(args.min_excess),
        min_excess_vs_parent=float(args.min_excess_vs_parent),
        fetch_benchmark=bool(args.fetch_benchmark),
        sync_task_status=bool(args.sync_task_status),
        output_path=Path(args.output) if args.output else None,
    )
    if args.json:
        _print_json(payload)
        return 0
    print(f"Experiment assessment: {payload.get('path') or ASSESSMENT_FILENAME}")
    summary = payload.get("summary") or {}
    print(f"  Total: {summary.get('total', 0)}")
    for status in ("proposed", "observing", "continue", "fail", "recommend"):
        count = summary.get(status, 0)
        if count:
            print(f"  {status}: {count}")
    if summary.get("human_ack_pending"):
        print(f"  human_ack_pending: {summary['human_ack_pending']}")
    for row in payload.get("recommendations") or []:
        print(
            f"  RECOMMEND [{row.get('kind')}] {row.get('experiment_id')} "
            f"marks={row.get('gate_marks')}"
        )
    plan = payload.get("entry_dca_adoption") or {}
    if plan:
        print(f"  DCA plan stage: {plan.get('current_stage')} acked={plan.get('acked')}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.data_dir) / ASSESSMENT_FILENAME
    if not path.exists():
        print(f"Missing {path}", file=sys.stderr)
        return 1
    payload = read_json(path)
    if args.json:
        _print_json(slim_experiment_assessment_for_review(payload))
        return 0
    slim = slim_experiment_assessment_for_review(payload)
    print(f"Experiment assessment: {path}")
    print(f"  Updated: {slim.get('updated_at')}")
    summary = slim.get("summary") or {}
    print(f"  Total: {summary.get('total', 0)}")
    print(f"  human_ack_pending: {summary.get('human_ack_pending', 0)}")
    for row in slim.get("recommendations") or []:
        print(f"  RECOMMEND {row.get('experiment_id')} ({row.get('pipeline')})")
    plan = slim.get("entry_dca_adoption") or {}
    if plan:
        print(f"  DCA plan: {plan.get('current_stage')} acked={plan.get('acked')}")
    return 0


def _finding_for_ack(data_dir: Path, paper_root: Path, experiment_id: str) -> dict:
    assessment_path = data_dir / ASSESSMENT_FILENAME
    try:
        assessment = read_json(assessment_path)
    except FileNotFoundError:
        assessment = {}
    if not isinstance(assessment, dict):
        assessment = {}
    row = next(
        (
            item
            for item in (assessment.get("experiments") or [])
            if isinstance(item, dict) and str(item.get("experiment_id") or "") == experiment_id
        ),
        {},
    )
    evidence = dict(row.get("forward_evidence") or {}) if isinstance(row, dict) else {}
    try:
        rollup = read_json(paper_root / "learning_tracks_entry_dca.json")
    except FileNotFoundError:
        rollup = {}
    if not isinstance(rollup, dict):
        rollup = {}
    finding = {
        "leading_cadence": evidence.get("leading_cadence") or rollup.get("leading_cadence"),
        "ready_for_cadence_analysis": bool(
            evidence.get("ready_for_cadence_analysis")
            or (rollup.get("readiness") or {}).get("ready_for_cadence_analysis")
        ),
        "scored_count": evidence.get("scored_count") or rollup.get("scored_count"),
        "tracks_with_closed": evidence.get("tracks_with_closed")
        or rollup.get("tracks_with_closed"),
        "model_independent_hint": evidence.get("model_independent_hint")
        if "model_independent_hint" in evidence
        else rollup.get("model_independent_hint"),
        "first_entry_by_track": first_entry_by_track(rollup),
    }
    return finding


def _cmd_ack(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    paper_root = Path(args.paper_root) if args.paper_root else data_dir / "paper_automation"
    experiment_id = str(args.experiment_id).strip()
    finding = _finding_for_ack(data_dir, paper_root, experiment_id)
    ack = record_ack(
        data_dir,
        experiment_id=experiment_id,
        decision=str(args.decision),
        note=str(args.note or ""),
        finding=finding,
        source=str(args.source or ""),
        acked_by=str(args.acked_by or "human"),
    )
    payload = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    if args.json:
        _print_json({"ack": ack, "summary": payload.get("summary"), "path": ack.get("path")})
        return 0
    print(f"Acked {experiment_id} ({ack.get('decision')}) → {ack.get('path')}")
    print(f"  finding.leading_cadence={finding.get('leading_cadence')}")
    summary = payload.get("summary") or {}
    print(f"  human_ack_pending: {summary.get('human_ack_pending', 0)}")
    plan = payload.get("entry_dca_adoption") or {}
    if plan:
        print(f"  DCA plan stage: {plan.get('current_stage')}")
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    paper_root = Path(args.paper_root) if args.paper_root else data_dir / "paper_automation"
    plan = evaluate_entry_dca_adoption_plan(data_dir=data_dir, paper_root=paper_root)
    if args.json:
        _print_json(plan)
        return 0
    print(f"DCA adoption plan: current_stage={plan.get('current_stage')} acked={plan.get('acked')}")
    for row in plan.get("stages") or []:
        print(
            f"  [{row.get('status')}] {row.get('id')} ready={row.get('ready')} "
            f"— {row.get('revisit_when')}"
        )
    for item in plan.get("do_not") or []:
        print(f"  do_not: {item}")
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    common.add_argument("--paper-root", default=None)
    common.add_argument("--json", action="store_true")

    parser = argparse.ArgumentParser(description="Unified experiment assessment ledger")
    sub = parser.add_subparsers(dest="command", required=True)

    refresh_p = sub.add_parser(
        "refresh", parents=[common], help="Rebuild experiment assessment ledger"
    )
    refresh_p.add_argument("--min-marks", default="4")
    refresh_p.add_argument("--min-excess", default="0.0")
    refresh_p.add_argument("--min-excess-vs-parent", default="0.0")
    refresh_p.add_argument("--fetch-benchmark", action="store_true")
    refresh_p.add_argument("--sync-task-status", action="store_true")
    refresh_p.add_argument("--output", default=None)
    refresh_p.set_defaults(func=_cmd_refresh)

    status_p = sub.add_parser("status", parents=[common], help="Show committed assessment ledger")
    status_p.set_defaults(func=_cmd_status)

    ack_p = sub.add_parser(
        "ack",
        parents=[common],
        help="Record a human ack for a recommend row (observe-only; never auto-apply)",
    )
    ack_p.add_argument("--experiment-id", required=True)
    ack_p.add_argument("--decision", default="ack_observe")
    ack_p.add_argument("--note", default="")
    ack_p.add_argument("--source", default="")
    ack_p.add_argument("--acked-by", default="human")
    ack_p.set_defaults(func=_cmd_ack)

    plan_p = sub.add_parser(
        "plan",
        parents=[common],
        help="Show the entry-DCA review/implementation plan",
    )
    plan_p.set_defaults(func=_cmd_plan)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
