"""Tests for backtest history health monitoring and safe repair."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from value_investor.backtest import BENCHMARK_TICKER
from value_investor.backtest_health import (
    audit_history_dir,
    repair_history_dir,
    run_backtest_health,
    validate_history_before_publish,
    validate_snapshot_payload,
)
from value_investor.storage import publish_committed_run_history, write_json


def _good_snapshot(run_at: str = "2026-08-02T12:34:17+00:00") -> dict:
    signals = [
        {
            "ticker": f"AAA{i}.L",
            "signal": "buy",
            "conviction_score": 0.5,
            "data_quality_score": 0.9,
        }
        for i in range(60)
    ]
    prices = {row["ticker"]: 100.0 + i for i, row in enumerate(signals)}
    prices[BENCHMARK_TICKER] = 8000.0
    return {"run_at": run_at, "prices": prices, "signals": signals}


def test_validate_snapshot_payload_flags_missing_benchmark():
    payload = _good_snapshot()
    del payload["prices"][BENCHMARK_TICKER]
    issues = validate_snapshot_payload(payload)
    assert any(row.code == "missing_benchmark" for row in issues)


def test_audit_history_dir_detects_corrupt_json(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    (history / "run_20260802_123417.json.gz").write_bytes(b"not-json")
    issues, stats = audit_history_dir(history)
    assert stats["valid_runs"] == 0
    assert any(row.code == "corrupt_json" for row in issues)


def test_repair_quarantines_corrupt_snapshot(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    bad = history / "run_20260802_123417.json.gz"
    bad.write_bytes(b"{broken")
    issues, _ = audit_history_dir(history)
    repairs = repair_history_dir(history, issues, apply=True)
    assert repairs
    assert not bad.exists()
    assert list((history / "quarantine").glob("*run_20260802_123417.json.gz"))


def test_repair_removes_duplicate_plain_when_gzip_exists(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    payload = _good_snapshot()
    plain = history / "run_20260802_123417.json"
    gz = history / "run_20260802_123417.json.gz"
    write_json(plain, payload, compact=True)
    write_json(gz, payload, compact=True, compress=True)
    issues, _ = audit_history_dir(history)
    repairs = repair_history_dir(history, issues, apply=True)
    assert repairs
    assert gz.exists()
    assert not plain.exists()


def test_validate_history_before_publish_blocks_invalid_new_snapshot(tmp_path: Path):
    output = tmp_path / "output"
    committed = tmp_path / "committed"
    history = output / "history"
    history.mkdir(parents=True)
    committed.mkdir()
    write_json(history / "run_20260802_123417.json.gz", {"broken": True}, compress=True)
    blocked = validate_history_before_publish(output, committed_dir=committed)
    assert blocked


def test_publish_skips_invalid_new_snapshot(tmp_path: Path):
    output = tmp_path / "output"
    committed = tmp_path / "committed"
    history = output / "history"
    history.mkdir(parents=True)
    committed.mkdir()
    write_json(history / "run_20260802_123417.json.gz", _good_snapshot(), compress=True)
    write_json(history / "run_20260803_123417.json.gz", {"broken": True}, compress=True)
    result = publish_committed_run_history(output, committed_dir=committed)
    assert result["copied"] >= 1
    assert result["skipped_invalid"] == 1
    assert (committed / "run_20260802_123417.json.gz").exists()
    assert not (committed / "run_20260803_123417.json.gz").exists()


def test_run_backtest_health_writes_status(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    write_json(history / "run_20260802_123417.json.gz", _good_snapshot(), compress=True)
    status = tmp_path / "backtest_health.json"
    report = run_backtest_health(history_dir=history, status_path=status, apply_repairs=False)
    assert status.exists()
    assert report.valid_runs == 1
    assert report.readiness["backtest_ready"] is False
