"""Validate committed data JSON for conflict markers and parse errors."""

from __future__ import annotations

import argparse
import json
import subprocess
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


def changed_data_paths(root: str = "docs/data") -> tuple[list[str], list[str]]:
    """Working-tree JSON files under ``root`` that differ from HEAD, and unmerged paths.

    ``git pull --rebase --autostash`` exits 0 when popping the stash conflicts and
    leaves markers in the tree; a broad ``docs/data/**`` commit would then publish them.
    """
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", root],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    changed: list[str] = []
    unmerged: list[str] = []
    for line in status.splitlines():
        code, path = line[:2], line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if "U" in code or code in {"AA", "DD"}:
            unmerged.append(path)
        if path.endswith((".json", ".jsonl")) and code.strip() != "D":
            changed.append(path)
    return changed, unmerged


def check_jsonl_path(path: Path) -> list[str]:
    if not path.exists():
        return []
    marker = _conflict_marker_in_text(path.read_text(encoding="utf-8"))
    return [f"{path}: contains merge conflict marker {marker!r}"] if marker else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        default=list(DEFAULT_PATHS),
        help="JSON files to validate (default: core committed data paths)",
    )
    parser.add_argument(
        "--changed",
        action="store_true",
        help="Check every changed JSON/JSONL file under docs/data and fail on unmerged paths",
    )
    args = parser.parse_args(argv)
    if args.changed:
        changed, unmerged = changed_data_paths()
        errors = [f"{path}: unmerged after autostash" for path in unmerged]
        for raw in changed:
            path = Path(raw)
            errors.extend(check_jsonl_path(path) if raw.endswith(".jsonl") else check_path(path))
        args.paths = changed
    else:
        errors = check_paths(args.paths)
    if errors:
        for row in errors:
            print(row, file=sys.stderr)
        return 1
    print(f"OK — {len(args.paths)} JSON file(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
