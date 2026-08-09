"""Ruff lint/format checks scoped to changed Python files (PR-friendly, no legacy debt gate)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_PREFIXES: tuple[str, ...] = ("src/", "tests/")
DEFAULT_EXCLUDES: tuple[str, ...] = ()


def git_changed_files(
    *,
    base_ref: str,
    head_ref: str = "HEAD",
    prefixes: tuple[str, ...] = DEFAULT_PREFIXES,
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
    repo_root: Path | None = None,
) -> list[Path]:
    """Return added/changed/copied/renamed Python paths under ``prefixes`` in a git range."""
    if base_ref == head_ref:
        return []
    cwd = str(repo_root) if repo_root is not None else None
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", f"{base_ref}...{head_ref}"],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git diff failed for {base_ref}...{head_ref}")
    paths: list[Path] = []
    for line in proc.stdout.splitlines():
        raw = line.strip()
        if not raw.endswith(".py"):
            continue
        if not any(raw.startswith(prefix) for prefix in prefixes):
            continue
        if any(raw.startswith(exclude) for exclude in excludes):
            continue
        paths.append(Path(raw))
    return paths


def run_ruff_on_files(files: list[Path]) -> tuple[int, list[str]]:
    """Run ruff check + format --check on ``files``. Returns (exit_code, log lines)."""
    if not files:
        return 0, ["No changed Python files under src/ or tests/ — skipping ruff."]
    existing = [path for path in files if path.exists()]
    missing = [path for path in files if not path.exists()]
    logs: list[str] = []
    if missing:
        logs.append(
            f"Deleted Python files (lint skipped): {', '.join(p.as_posix() for p in missing)}"
        )
    if not existing:
        return 0, logs + ["Only deletions in scope — skipping ruff."]
    paths = [path.as_posix() for path in existing]
    logs.append(f"Ruff scope ({len(paths)} file(s)): {', '.join(paths)}")
    for label, args in (
        ("check", ["check", *paths]),
        ("format", ["format", "--check", *paths]),
    ):
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.stdout:
            logs.append(proc.stdout.rstrip())
        if proc.stderr:
            logs.append(proc.stderr.rstrip())
        if proc.returncode != 0:
            logs.append(f"ruff {label} failed (exit {proc.returncode})")
            return proc.returncode, logs
    logs.append("ruff check + format passed")
    return 0, logs


def check_changed_python(
    *,
    base_ref: str,
    head_ref: str = "HEAD",
    prefixes: tuple[str, ...] = DEFAULT_PREFIXES,
) -> tuple[int, list[str]]:
    files = git_changed_files(base_ref=base_ref, head_ref=head_ref, prefixes=prefixes)
    code, logs = run_ruff_on_files(files)
    return code, logs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        required=True,
        help="Git base ref for diff range (e.g. origin/main)",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Git head ref for diff range (default: HEAD)",
    )
    args = parser.parse_args(argv)
    try:
        code, logs = check_changed_python(base_ref=args.base, head_ref=args.head)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    for line in logs:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
