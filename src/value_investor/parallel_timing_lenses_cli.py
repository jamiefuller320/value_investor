"""Optional CLI for L652 parallel timing lenses (observe-only).

Production path is daily ops-monitor ``check_parallel_timing_lenses``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.parallel_timing_lenses import (
    DEFAULT_DATA_DIR,
    STORE_FILENAME,
    catalog_payload,
    refresh_parallel_timing_lenses,
)
from value_investor.storage import read_json


def _print(payload: dict, *, as_json: bool) -> None:
    if as_json or not isinstance(payload, dict):
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    if payload.get("lenses") and "buy_learning" in payload:
        print(
            f"buy={payload.get('buy_learning')} sell={payload.get('sell_learning')} "
            f"baseline={payload.get('sell_baseline')} cap={payload.get('sell_learning_cap')}"
        )
        return
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    print(
        f"candidates={summary.get('candidate_count')} "
        f"buy={summary.get('buy_candidates')} sell={summary.get('sell_candidates')} "
        f"looking={summary.get('lenses_looking')} entered={summary.get('lenses_entered')} "
        f"abandoned={summary.get('lenses_abandoned')} "
        f"concurrence_mean={summary.get('concurrence_mean')} "
        f"influences_live=false path={payload.get('path') or STORE_FILENAME}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ftse-parallel-timing-lenses",
        description=(
            "L652 parallel timing lenses (observe-only). Fixed-stake v0; "
            "concurrence companion; never influences fills."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Dashboard data directory (default: docs/data)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalog", help="Show owner-locked v0 lens catalog")
    sub.add_parser("refresh", help="Rebuild store from MFT + entry_blind candidates")
    show = sub.add_parser("show", help="Show persisted store summary (or full JSON)")
    show.add_argument(
        "--candidate-id",
        default="",
        help="Optional candidate_id filter",
    )

    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)

    if args.cmd == "catalog":
        _print(catalog_payload(), as_json=args.json)
        return 0

    if args.cmd == "refresh":
        payload = refresh_parallel_timing_lenses(data_dir=data_dir, persist=True)
        _print(payload, as_json=args.json)
        return 0

    if args.cmd == "show":
        path = data_dir / STORE_FILENAME
        try:
            payload = read_json(path)
        except (OSError, FileNotFoundError, ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        cid = str(args.candidate_id or "").strip()
        if cid:
            rows = [
                row
                for row in (payload.get("candidates") or [])
                if isinstance(row, dict) and row.get("candidate_id") == cid
            ]
            _print({"candidate_id": cid, "matches": rows}, as_json=True)
            return 0
        payload["path"] = str(path)
        _print(payload, as_json=args.json)
        return 0

    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
