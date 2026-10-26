"""CLI for cue-consumer MFT observe lab (super book) — ad-hoc drill-down."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.cue_consumer_mft import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_QUEUE_PATH,
    DEFAULT_START_GATE_PATH,
    DEFAULT_STORE_PATH,
    format_cue_consumer_mft_text,
    freeze_start_cohort,
    propose_start_cohort,
    refresh_cue_consumer_mft,
)
from value_investor.storage import write_json


def _safe_read(path: Path) -> dict | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Cue-consumer MFT observe lab (super book): declared-incomparable "
            "fixed-stake mid-flight-tune sleeve. Never writes live books "
            "(influences_live=false)."
        )
    )
    sub = parser.add_subparsers(dest="command")

    refresh_p = sub.add_parser("refresh", help="Arm/refresh observe stores (default)")
    propose_p = sub.add_parser(
        "propose-cohort",
        help="Rebuild Q8B proposed non-mechanical autopsy cohort (does not freeze)",
    )
    freeze_p = sub.add_parser(
        "freeze-cohort",
        help="Freeze proposed cohort_review_ids (dry-run unless --apply)",
    )

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--output-dir",
            type=Path,
            default=DEFAULT_OUTPUT_DIR,
            help="Data root (default: docs/data)",
        )
        p.add_argument(
            "--store",
            type=Path,
            default=DEFAULT_STORE_PATH,
            help="Observe store path (default: docs/data/cue_consumer_mft_observe.json)",
        )
        p.add_argument(
            "--start-gate",
            type=Path,
            default=DEFAULT_START_GATE_PATH,
            help="Start-gate store (default: docs/data/cue_consumer_mft_start_gate.json)",
        )
        p.add_argument(
            "--queue",
            type=Path,
            default=DEFAULT_QUEUE_PATH,
            help="Post-sale review queue (default: docs/data/post_sale_review_queue.json)",
        )
        p.add_argument(
            "--json",
            action="store_true",
            help="Print full payload JSON",
        )
        p.add_argument(
            "--no-persist",
            action="store_true",
            help="Compute without writing store files (refresh)",
        )
        p.add_argument(
            "--refresh-proposal",
            action="store_true",
            help="Rebuild sticky proposed cohort even if one already exists",
        )

    _add_common(parser)
    _add_common(refresh_p)
    _add_common(propose_p)
    _add_common(freeze_p)
    propose_p.add_argument(
        "--persist",
        action="store_true",
        help="Write proposed ids into start-gate store (still does not freeze)",
    )
    freeze_p.add_argument(
        "--apply",
        action="store_true",
        help="Actually write cohort_review_ids (required to freeze)",
    )

    args = parser.parse_args(argv)
    command = args.command or "refresh"

    if command == "propose-cohort":
        queue = _safe_read(args.queue)
        proposal = propose_start_cohort(queue)
        if args.persist:
            gate = _safe_read(args.start_gate) or {}
            gate = dict(gate)
            gate["proposed_cohort_review_ids"] = list(
                proposal.get("proposed_cohort_review_ids") or []
            )
            gate["proposed_at"] = gate.get("proposed_at")  # refreshed below via refresh
            gate["cohort_selection_id"] = proposal.get("selection_id")
            gate["proposal_summary"] = {
                "proposed_cohort_size": proposal.get("proposed_cohort_size"),
                "by_exit_reason": proposal.get("by_exit_reason"),
                "by_book_id": proposal.get("by_book_id"),
                "owner_decision": proposal.get("owner_decision"),
                "excludes": proposal.get("excludes"),
            }
            write_json(args.start_gate, gate, compact=False)
            # Keep observe store in sync without wiping freeze state.
            refresh_cue_consumer_mft(
                output_dir=args.output_dir,
                store_path=args.store,
                start_gate_path=args.start_gate,
                queue_path=args.queue,
                persist=True,
                refresh_proposal=False,
            )
        if args.json:
            json.dump(proposal, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(
                f"Proposed Q8B cohort ({proposal.get('selection_id')}): "
                f"{proposal.get('proposed_cohort_size')} review_ids\n"
                f"  by_exit_reason: {proposal.get('by_exit_reason')}\n"
                f"  by_book_id: {proposal.get('by_book_id')}\n"
                f"  owner_decision: {proposal.get('owner_decision')}\n"
                "  (does not freeze — run freeze-cohort --apply after confirm)\n"
            )
        return 0

    if command == "freeze-cohort":
        gate = _safe_read(args.start_gate) or {}
        result = freeze_start_cohort(start_gate=gate, apply=bool(args.apply))
        if args.apply and result.get("status") == "frozen":
            write_json(args.start_gate, result["gate"], compact=False)
            payload = refresh_cue_consumer_mft(
                output_dir=args.output_dir,
                store_path=args.store,
                start_gate_path=args.start_gate,
                queue_path=args.queue,
                persist=True,
            )
            if args.json:
                json.dump({"freeze": result, "lab": payload}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                sys.stdout.write(
                    f"Frozen {result.get('would_freeze_n')} review_ids into {args.start_gate}\n"
                )
                sys.stdout.write(format_cue_consumer_mft_text(payload))
            return 0
        if args.json:
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(
                f"freeze-cohort status={result.get('status')} "
                f"would_freeze_n={result.get('would_freeze_n')} "
                f"already_frozen_n={result.get('already_frozen_n')}\n"
                "  (pass --apply to write cohort_review_ids)\n"
            )
        return 0

    # refresh (default)
    no_persist = bool(getattr(args, "no_persist", False))
    refresh_proposal = bool(getattr(args, "refresh_proposal", False))
    payload = refresh_cue_consumer_mft(
        output_dir=args.output_dir,
        store_path=args.store,
        start_gate_path=args.start_gate,
        queue_path=args.queue,
        persist=not no_persist,
        refresh_proposal=refresh_proposal,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_cue_consumer_mft_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
