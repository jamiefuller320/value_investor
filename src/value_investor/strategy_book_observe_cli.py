"""CLI for the forward episode walker. Refuses to score real data without a signature."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from value_investor.strategy_book_observe import walk_book
from value_investor.strategy_book_replay import load_archive
from value_investor.strategy_book_rules import (
    INFLUENCES_LIVE,
    OBSERVE_STORE_NAME,
    REGISTRATION_ID,
    RegistrationUnsigned,
    require_signature_for_score,
    scores_committed_tree,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy book forward walker (observe-only)")
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="Synthetic data root shaped like docs/data. Required to run unsigned.",
    )
    parser.add_argument(
        "--persist", action="store_true", help="Write the observe JSON under the fixture dir"
    )
    args = parser.parse_args(argv)
    try:
        require_signature_for_score(args.repo_root, args.fixture_dir)
    except RegistrationUnsigned:
        print(
            json.dumps(
                {
                    "error": "registration_unsigned",
                    "registration_id": REGISTRATION_ID,
                    "influences_live": INFLUENCES_LIVE,
                }
            )
        )
        return 2
    root = (
        args.fixture_dir if args.fixture_dir is not None else Path(args.repo_root) / "docs" / "data"
    )
    if scores_committed_tree(args.fixture_dir, args.repo_root):
        from value_investor.strategy_book_forward import counts_view, run_forward_job

        summary = run_forward_job(repo_root=args.repo_root, apply=bool(args.persist))
        print(json.dumps(counts_view(summary), indent=2))
        return 0
    loaded = load_archive(root)
    payload = walk_book(loaded["specs"], mode="forward")
    payload["no_chart"] = loaded["no_chart"]
    payload["skipped_ungraduated"] = loaded["skipped_ungraduated"]
    if args.persist:
        dest = Path(root) / OBSERVE_STORE_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        payload = {**payload, "wrote": str(dest)}
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
