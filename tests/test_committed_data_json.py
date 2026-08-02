"""Tests for committed data JSON integrity guard."""

from __future__ import annotations

from pathlib import Path

from value_investor.committed_data_json import check_path, main


def test_check_path_flags_merge_conflict_markers(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text('{"ok": true}\n<<<<<<< conflict\n', encoding="utf-8")
    errors = check_path(path)
    assert errors and "merge conflict marker" in errors[0]


def test_check_path_accepts_valid_json(tmp_path: Path):
    path = tmp_path / "good.json"
    path.write_text('{"ok": true}', encoding="utf-8")
    assert not check_path(path)


def test_main_returns_zero_for_valid_policy_json():
    assert main(["docs/data/library/policy.json"]) == 0
