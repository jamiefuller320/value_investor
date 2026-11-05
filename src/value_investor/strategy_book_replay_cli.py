"""CLI for the archive replay. Refuses to score real data without a signature."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from value_investor.strategy_book_replay import run_replay
from value_investor.strategy_book_rules import (
    INFLUENCES_LIVE,
    REGISTRATION_ID,
    REPLAY_STORE_NAME,
    RegistrationUnsigned,
    require_signature_for_score,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy book archive replay (observe-only)")
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="Synthetic data root shaped like docs/data. Required to run unsigned.",
    )
    parser.add_argument(
        "--persist", action="store_true", help="Write the replay JSON under the fixture dir"
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
    payload = run_replay(root)
    if args.persist:
        dest = Path(root) / REPLAY_STORE_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        payload = {**payload, "wrote": str(dest)}
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
