"""Stable pytest file sharding for parallel CI jobs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_TEST_ROOT = Path("tests")
DEFAULT_NUM_SHARDS = 4


def _stable_bucket(index: int, num_shards: int) -> int:
    """Round-robin by sorted file order — even split, no empty shard when len >= num_shards."""
    return index % num_shards


def discover_test_files(*, test_root: Path = DEFAULT_TEST_ROOT) -> list[str]:
    """Repo-relative paths of test modules under ``tests/``."""
    repo = Path.cwd().resolve()
    root = test_root.resolve()
    if not root.is_dir():
        return []
    files: list[str] = []
    for path in sorted(root.rglob("*.py")):
        name = path.name
        if not (name.startswith("test_") or name.endswith("_test.py")):
            continue
        rel = path.relative_to(repo).as_posix()
        files.append(rel)
    return sorted(files)


def shard_test_files(
    files: list[str],
    *,
    shard: int,
    num_shards: int,
) -> list[str]:
    if num_shards < 1:
        raise ValueError("num_shards must be >= 1")
    if shard < 0 or shard >= num_shards:
        raise ValueError(f"shard must be in [0, {num_shards})")
    ordered = sorted(files)
    return [path for i, path in enumerate(ordered) if _stable_bucket(i, num_shards) == shard]


def partition_coverage(files: list[str], *, num_shards: int) -> dict[int, list[str]]:
    buckets: dict[int, list[str]] = {i: [] for i in range(num_shards)}
    for i, path in enumerate(sorted(files)):
        buckets[_stable_bucket(i, num_shards)].append(path)
    return buckets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print pytest file paths for one CI shard")
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, default=DEFAULT_NUM_SHARDS)
    parser.add_argument("--test-root", type=Path, default=DEFAULT_TEST_ROOT)
    parser.add_argument(
        "--check-coverage",
        action="store_true",
        help="Verify all discovered files are assigned exactly once (exit 1 on gap/overlap)",
    )
    args = parser.parse_args(argv)

    files = discover_test_files(test_root=args.test_root)
    if args.check_coverage:
        buckets = partition_coverage(files, num_shards=args.shards)
        seen = [p for bucket in buckets.values() for p in bucket]
        if len(seen) != len(files) or len(set(seen)) != len(files):
            print("shard coverage check failed", file=sys.stderr)
            return 1
        return 0

    selected = shard_test_files(files, shard=args.shard, num_shards=args.shards)
    if not selected:
        print("no test files in shard", file=sys.stderr)
        return 1
    print(" ".join(selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
