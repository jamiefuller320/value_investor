"""Validate committed data JSON for conflict markers and parse errors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Git conflict markers only — not long pytest banners like "==== FAILURES ====".
CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")

DEFAULT_PATHS: tuple[str, ...] = (
    "docs/data/library/policy.json",
    "docs/data/ops_status.json",
    "docs/data/engineering_tasks.json",
    "docs/data/ingest_health_log.json",
    "docs/data/latest.json",
)


def _conflict_marker_in_text(text: str) -> str | None:
    """Return a conflict marker if a git-style conflict line is present.

    Matches only whole-line markers (optional surrounding whitespace). A bare
    ``=======`` line is a conflict separator; longer ``====...====`` runs inside
    stored pytest logs are not.
    """
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("<<<<<<<") or stripped.startswith(">>>>>>>"):
            return stripped[:7]
        if stripped == "=======":
            return "======="
    return None


def check_path(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return errors
    text = path.read_text(encoding="utf-8")
    marker = _conflict_marker_in_text(text)
    if marker is not None:
        errors.append(f"{path}: contains merge conflict marker {marker!r}")
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: invalid JSON ({exc})")
    return errors


def check_paths(paths: list[str | Path]) -> list[str]:
    errors: list[str] = []
    for raw in paths:
        errors.extend(check_path(Path(raw)))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        default=list(DEFAULT_PATHS),
        help="JSON files to validate (default: core committed data paths)",
    )
    args = parser.parse_args(argv)
    errors = check_paths(args.paths)
    if errors:
        for row in errors:
            print(row, file=sys.stderr)
        return 1
    print(f"OK — {len(args.paths)} JSON file(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
