"""Tests for committed data JSON integrity guard."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.committed_data_json import check_path, main


def test_check_path_flags_merge_conflict_markers(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text('{"ok": true}\n<<<<<<< conflict\n', encoding="utf-8")
    errors = check_path(path)
    assert errors and "merge conflict marker" in errors[0]


def test_check_path_flags_bare_equals_conflict_separator(tmp_path: Path):
    path = tmp_path / "sep.json"
    path.write_text('{"a": 1}\n=======\n{"b": 2}\n', encoding="utf-8")
    errors = check_path(path)
    assert errors and "=======" in errors[0]


def test_check_path_ignores_pytest_failure_banner_inside_string(tmp_path: Path):
    """Engineering queue stores pytest tails; those banners are not git conflicts."""
    path = tmp_path / "queue.json"
    payload = {
        "summary": (
            "pytest rc=1: "
            "=================================== FAILURES ===================================\n"
            "E   assert False\n"
        )
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert check_path(path) == []


def test_check_path_accepts_valid_json(tmp_path: Path):
    path = tmp_path / "good.json"
    path.write_text('{"ok": true}', encoding="utf-8")
    assert not check_path(path)


def test_main_returns_zero_for_valid_policy_json():
    assert main(["docs/data/library/policy.json"]) == 0


def test_main_returns_zero_for_engineering_tasks_with_pytest_banner():
    assert main(["docs/data/engineering_tasks.json"]) == 0
