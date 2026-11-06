"""CLI for the archive replay. Refuses to score real data without a signature."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any

from value_investor.strategy_book_replay import run_replay
from value_investor.strategy_book_rules import (
    INFLUENCES_LIVE,
    REGISTRATION_ID,
    REPLAY_DETAIL_STORE_NAME,
    REPLAY_STORE_NAME,
    RegistrationUnsigned,
    require_signature_for_score,
    scores_committed_tree,
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
        if scores_committed_tree(args.fixture_dir, args.repo_root):
            dest = Path(args.repo_root) / "docs" / "data" / REPLAY_STORE_NAME
        else:
            dest = Path(root) / REPLAY_STORE_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        detail = dest.with_name(REPLAY_DETAIL_STORE_NAME)
        detail.write_bytes(
            gzip.compress(
                json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"),
                mtime=0,
            )
        )
        summary = {**summarize_replay(payload), "detail_store": detail.name}
        dest.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({**summary, "wrote": [str(dest), str(detail)]}, indent=2, default=str))
        return 0
    print(json.dumps(payload, indent=2, default=str))
    return 0


def summarize_replay(payload: dict[str, Any]) -> dict[str, Any]:
    """Boards and counts only; per-episode rows live in the gzipped detail store."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict) and ("episodes" in value or "events" in value):
            out[key] = {
                **{k: v for k, v in value.items() if k not in _DETAIL_KEYS},
                "episode_count": len(value.get("episodes") or []),
            }
        else:
            out[key] = value
    return out


_DETAIL_KEYS = frozenset({"episodes", "events"})


if __name__ == "__main__":
    raise SystemExit(main())
