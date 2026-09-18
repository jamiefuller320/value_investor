"""Tests for pytest CI sharding."""

from __future__ import annotations

from pathlib import Path

from value_investor.pytest_shard import (
    discover_test_files,
    partition_coverage,
    shard_test_files,
)


def test_partition_covers_every_file_once(tmp_path: Path, monkeypatch):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_a.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (tests / "test_b.py").write_text("def test_y(): pass\n", encoding="utf-8")
    sub = tests / "sub"
    sub.mkdir()
    (sub / "test_c.py").write_text("def test_z(): pass\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    files = discover_test_files(test_root=Path("tests"))
    assert len(files) == 3
    buckets = partition_coverage(files, num_shards=4)
    merged = [p for bucket in buckets.values() for p in bucket]
    assert sorted(merged) == sorted(files)


def test_shard_is_subset_of_discovery(tmp_path: Path, monkeypatch):
    tests = tmp_path / "tests"
    tests.mkdir()
    for i in range(8):
        (tests / f"test_{i}.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    files = discover_test_files(test_root=Path("tests"))
    for shard in range(4):
        part = shard_test_files(files, shard=shard, num_shards=4)
        assert part
        assert set(part) <= set(files)
