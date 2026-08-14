"""Tests for library grow health logging and stall detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.data_library import _recompute_coverage, summarize_manifest_fetch_health
from value_investor.library_grow_health import (
    library_grow_stalled,
    record_library_grow_health,
    snapshot_focus_market_health,
)


def test_summarize_manifest_fetch_health_excludes_failed_refresh():
    manifest = {
        "tickers": ["AAA.ST", "BBB.ST"],
        "ticker_state": {
            "AAA.ST": {"fetch_status": "ok", "fields_present": ["market_cap"], "last_refresh": "x"},
            "BBB.ST": {"fetch_status": "failed", "errors": ["401"], "last_refresh": "x"},
        },
    }
    health = summarize_manifest_fetch_health(manifest)
    assert health["ok_fetch_count"] == 1
    assert health["failed_fetch_count"] == 1
    _recompute_coverage(manifest)
    assert manifest["coverage_count"] == 1
    assert manifest["honest_coverage_count"] == 1


def test_library_grow_stalled_detects_no_progress(tmp_path: Path):
    log = tmp_path / "grow_health_log.json"
    market = "omxs30"
    base = {
        "market": market,
        "health_after": {
            "market": market,
            "ok_fetch_count": 0,
            "failed_fetch_count": 30,
            "usable_metrics_rows": 0,
            "latent_failure": True,
        },
        "delta_ok_fetch": 0,
        "delta_usable_metrics": 0,
    }
    from value_investor.library_grow_health import append_grow_health_log

    append_grow_health_log({**base, "run_at": "2026-08-01"}, path=log)
    append_grow_health_log({**base, "run_at": "2026-08-08"}, path=log)
    assert library_grow_stalled(log_path=log, min_runs=2, market_id=market)


def test_record_library_grow_health_writes_delta(tmp_path: Path):
    root = tmp_path / "library"
    policy = root / "policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        '{"focus_market":"omxs30","market_queue":[],"graduated_markets":[]}',
        encoding="utf-8",
    )
    market_dir = root / "markets" / "omxs30"
    market_dir.mkdir(parents=True)
    (market_dir / "manifest.json").write_text(
        '{"market":"omxs30","tickers":["AAA.ST"],"ticker_state":{"AAA.ST":{"fetch_status":"failed","errors":["x"],"last_refresh":"t"}},"coverage_count":1}',
        encoding="utf-8",
    )
    (market_dir / "metrics").mkdir()
    (market_dir / "metrics" / "latest.json").write_text("[]", encoding="utf-8")

    log = tmp_path / "grow_health_log.json"
    with patch(
        "value_investor.library_grow_health.assess_library_metrics_health",
        return_value={"usable_rows": 0, "total_rows": 0, "sample_errors": [], "sample_tickers": []},
    ):
        entry = record_library_grow_health(
            root=root,
            policy_path=policy,
            log_path=log,
        )
    assert entry["delta_usable_metrics"] == 0
    snap = snapshot_focus_market_health(root=root, policy_path=policy)
    assert snap["failed_fetch_count"] == 1
