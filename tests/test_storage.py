"""Tests for compact JSON, gzip, and retention helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.storage import (
    apply_output_retention,
    dumps_json,
    history_cutoff,
    prune_dashboard_archives,
    read_json,
    resolve_json_path,
    summarize_text,
    write_json,
)


def test_write_read_compact_json(tmp_path: Path):
    path = tmp_path / "sample.json"
    write_json(path, {"a": 1, "b": [2, 3]}, compact=True)
    text = path.read_text(encoding="utf-8")
    assert "\n" not in text
    assert read_json(path) == {"a": 1, "b": [2, 3]}
    assert dumps_json({"x": 1}, compact=True) == '{"x":1}'


def test_write_read_gzip_json(tmp_path: Path):
    path = tmp_path / "sample.json"
    written = write_json(path, {"hello": "world"}, compact=True, compress=True)
    assert written.name.endswith(".json.gz")
    assert written.exists()
    assert not path.exists()
    assert read_json(path) == {"hello": "world"}
    assert resolve_json_path(path) == written


def test_summarize_text_truncates():
    long = "word " * 200
    snippet = summarize_text(long, max_chars=40)
    assert len(snippet) <= 40
    assert snippet.endswith("…")


def test_prune_dashboard_archives_keeps_newest(tmp_path: Path):
    archive = tmp_path / "archive"
    archive.mkdir()
    for day in ("2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"):
        (archive / f"{day}.json").write_text("{}", encoding="utf-8")

    removed = prune_dashboard_archives(archive, keep=2)
    assert len(removed) == 2
    remaining = sorted(p.name for p in archive.iterdir())
    assert remaining == ["2026-03-01.json", "2026-04-01.json"]


def test_apply_output_retention_removes_old_history(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    old_stamp = "20200101_070000"
    new_stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    (history / f"run_{old_stamp}.json").write_text("{}", encoding="utf-8")
    (history / f"run_{new_stamp}.json").write_text("{}", encoding="utf-8")
    (tmp_path / f"signals_{old_stamp}.csv").write_text("ticker\n", encoding="utf-8")
    (tmp_path / f"signals_{new_stamp}.csv").write_text("ticker\n", encoding="utf-8")

    counts = apply_output_retention(tmp_path, max_years=3, now=datetime(2026, 7, 13, tzinfo=UTC))
    assert counts["history"] == 1
    assert counts["timestamped_outputs"] == 1
    assert not (history / f"run_{old_stamp}.json").exists()
    assert (history / f"run_{new_stamp}.json").exists()
    assert history_cutoff(max_years=3, now=datetime(2026, 7, 13, tzinfo=UTC)).year == 2023
