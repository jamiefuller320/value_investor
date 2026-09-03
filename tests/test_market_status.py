"""Tests for the dashboard market-status grid payload."""

from __future__ import annotations

import json
from pathlib import Path

from tests.test_publish import _write_sample_output
from value_investor.market_status import (
    INGEST_LIVE,
    INGEST_MAINTENANCE,
    INGEST_QUEUED,
    INGEST_SPRINT,
    LIVE_MARKET_ID,
    ROLE_FOCUS,
    ROLE_LIVE,
    build_market_status,
)
from value_investor.publish import build_dashboard_bundle, publish_dashboard
from value_investor.storage import write_json


def _seed_library(root: Path) -> Path:
    root.mkdir(parents=True)
    write_json(
        root / "policy.json",
        {
            "schema_version": 1,
            "focus_market": "euro_depth",
            "market_queue": ["sp500", "asx200", "ftse_smallcap"],
            "graduated_markets": [
                {"market": "sp500", "graduated_at": "2026-07-17T00:00:00+00:00"},
                {"market": "asx200", "graduated_at": "2026-07-17T00:00:00+00:00"},
                {"market": "nasdaq100", "graduated_at": "2026-07-18T00:00:00+00:00"},
            ],
            "ingest_parallel_sprint": ["sp500"],
            "ingest_parallel_sprint_2": ["asx200"],
        },
        compact=False,
    )
    write_json(
        root / "library_status.json",
        {
            "updated_at": "2026-09-02T00:00:00+00:00",
            "markets": [
                {
                    "market": "euro_depth",
                    "label": "EU depth",
                    "ticker_count": 194,
                    "coverage_pct": 0.98,
                    "honest_coverage_pct": 0.98,
                    "stale": 0,
                    "fresh": 194,
                    "failed_fetch_count": 0,
                    "last_metrics_refresh": "2026-09-02T07:00:00+00:00",
                },
                {
                    "market": "sp500",
                    "ticker_count": 503,
                    "coverage_pct": 1.0,
                    "honest_coverage_pct": 1.0,
                    "stale": 0,
                    "fresh": 503,
                    "last_metrics_refresh": "2026-09-02T06:00:00+00:00",
                },
                {
                    "market": "ftse_smallcap",
                    "ticker_count": 86,
                    "coverage_pct": 0.7,
                    "stale": 4,
                    "fresh": 82,
                },
            ],
        },
        compact=False,
    )
    write_json(
        root / "shard_phases.json",
        {
            "updated_at": "2026-09-02T00:00:00+00:00",
            "markets": {
                "euro_depth": {
                    "current_phase": 2,
                    "next_phase": 2,
                    "phase1_ready": True,
                    "phase2_ready": False,
                    "phase3_ready": False,
                    "blockers": ["need 4 weekly batch marks (have 1)"],
                    "phase1": {"screen_archives": 13, "observe_snapshot_count": 13},
                    "phase2": {"weekly_batch_count": 1, "min_weekly_batches": 4},
                }
            },
        },
        compact=False,
    )
    write_json(
        root / "euro_ingest_dispatch.json",
        {
            "market_id": "euro_depth",
            "focus_market": "euro_depth",
            "mode": "sprint",
            "reason": "Ingest sprint: FTSE-standard depth gaps (zero_body=1)",
            "ingest_parity_met": False,
            "filing_gaps": 1,
            "phase_blockers": ["need 4 weekly batch marks (have 1)"],
            "filing_health": {
                "buy_tier_count": 44,
                "unmeasured_buy_tier": 0,
                "zero_body_buy_tier": 1,
                "thin_body_buy_tier": 24,
                "indexed_without_body": 40,
                "bodies_median": 2,
                "zero_body_tickers": ["RAND.AS"],
                "thin_body_tickers": ["DG.PA"],
            },
            "sprint_markets": ["euro_depth", "sp500", "asx200"],
            "maintenance_markets": [],
            "parallel_sprint_markets": ["sp500"],
            "parallel_sprint_2_markets": ["asx200"],
            "parallel_sprint_status": [
                {
                    "market_id": "sp500",
                    "mode": "sprint",
                    "reason": "Ingest sprint: indexed_without_body=16",
                    "ingest_parity_met": False,
                    "filing_gaps": 0,
                    "filing_health": {
                        "buy_tier_count": 140,
                        "unmeasured_buy_tier": 0,
                        "zero_body_buy_tier": 0,
                        "thin_body_buy_tier": 0,
                        "indexed_without_body": 16,
                    },
                }
            ],
        },
        compact=False,
    )
    write_json(
        root / "markets" / "euro_depth" / "screen" / "latest_summary.json",
        {
            "market": "euro_depth",
            "run_at": "2026-09-01T12:00:00+00:00",
            "ticker_count": 194,
            "signal_counts": {"strong_buy": 8, "buy": 20, "hold": 140, "avoid": 26},
            "shortlist_count": 28,
            "strong_buy": 8,
            "buy": 20,
        },
        compact=False,
    )
    write_json(
        root / "markets" / "sp500" / "screen" / "latest_summary.json",
        {
            "market": "sp500",
            "run_at": "2026-09-01T11:00:00+00:00",
            "ticker_count": 503,
            "signal_counts": {"strong_buy": 12, "buy": 40, "hold": 380, "avoid": 71},
            "shortlist_count": 52,
            "strong_buy": 12,
            "buy": 40,
        },
        compact=False,
    )
    return root


def _by_id(payload: dict, market_id: str) -> dict:
    return next(row for row in payload["markets"] if row["market_id"] == market_id)


def test_build_market_status_classifies_ingest_and_signals(tmp_path: Path):
    library = _seed_library(tmp_path / "library")
    payload = build_market_status(
        library_root=library,
        policy_path=library / "policy.json",
        dispatch_path=library / "euro_ingest_dispatch.json",
        live_meta={"company_count": 249, "signal_counts": {"strong_buy": 16, "buy": 47, "hold": 142}},
        live_signal_counts={"strong_buy": 16, "buy": 47, "hold": 142, "avoid": 43},
        live_run_at="2026-09-03T09:00:00+00:00",
    )

    assert payload["schema_version"] == 1
    assert payload["focus_market"] == "euro_depth"
    assert payload["summary"]["sprint_count"] >= 3
    assert payload["summary"]["live_count"] == 1

    live = _by_id(payload, LIVE_MARKET_ID)
    assert live["role"] == ROLE_LIVE
    assert live["ingest"] == INGEST_LIVE
    assert live["signal_counts"]["strong_buy"] == 16
    assert live["learning_phase_label"] == "Live screen"
    assert live["ticker_count"] == 249

    focus = _by_id(payload, "euro_depth")
    assert focus["role"] == ROLE_FOCUS
    assert focus["ingest"] == INGEST_SPRINT
    assert focus["is_focus"] is True
    assert focus["signal_counts"]["buy"] == 20
    assert focus["shortlist_count"] == 28
    assert focus["filing_health"]["zero_body_buy_tier"] == 1
    assert focus["health"] == "warn"
    assert focus["learning_phase"] == 2

    sprint = _by_id(payload, "sp500")
    assert sprint["ingest"] == INGEST_SPRINT
    assert sprint["ingest_stream"] == 1
    assert sprint["is_graduated"] is True
    assert sprint["signal_counts"]["hold"] == 380

    queued = _by_id(payload, "ftse_smallcap")
    assert queued["ingest"] == INGEST_QUEUED
    assert queued["health"] == "warn"
    assert queued["coverage_pct"] == 0.7

    graduated = _by_id(payload, "nasdaq100")
    assert graduated["ingest"] == INGEST_MAINTENANCE
    assert graduated["is_graduated"] is True

    assert payload["markets"][0]["market_id"] == LIVE_MARKET_ID
    assert payload["markets"][1]["market_id"] == "euro_depth"


def test_build_market_status_survives_empty_library(tmp_path: Path):
    library = tmp_path / "empty"
    library.mkdir()
    payload = build_market_status(
        library_root=library,
        policy_path=library / "missing-policy.json",
        dispatch_path=library / "missing-dispatch.json",
        live_signal_counts={"hold": 10},
    )
    live = _by_id(payload, LIVE_MARKET_ID)
    assert live["ingest"] == INGEST_LIVE
    assert live["signal_counts"]["hold"] == 10
    assert payload["summary"]["market_count"] >= 1


def test_publish_includes_market_status(tmp_path: Path):
    _write_sample_output(tmp_path)
    bundle = build_dashboard_bundle(tmp_path)
    assert bundle["market_status"]
    assert bundle["market_status"]["schema_version"] == 1
    live = _by_id(bundle["market_status"], LIVE_MARKET_ID)
    assert live["signal_counts"]["strong_buy"] == 1
    assert live["ticker_count"] == 2


def test_publish_writes_market_status_sidecar(tmp_path: Path):
    output_dir = tmp_path / "output"
    dest_dir = tmp_path / "docs"
    _write_sample_output(output_dir)
    publish_dashboard(output_dir=output_dir, dest_dir=dest_dir, include_research=False)
    sidecar = dest_dir / "data" / "market_status.json"
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert any(row["market_id"] == LIVE_MARKET_ID for row in payload["markets"])


def test_dashboard_assets_include_market_status_grid():
    app = Path("docs/app.js").read_text(encoding="utf-8")
    html = Path("docs/index.html").read_text(encoding="utf-8")
    css = Path("docs/styles.css").read_text(encoding="utf-8")
    assert "function renderMarketStatusGrid(data)" in app
    assert "function openMarketStatusCard(marketId)" in app
    assert "function renderMarketStatusCard(row)" in app
    assert 'id="market-status-dialog"' in html
    assert 'id="market-status-body"' in html
    assert ".market-status-grid" in css
    assert ".market-tile" in css
