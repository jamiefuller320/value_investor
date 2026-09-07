"""Tests for the dashboard market-status grid payload."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.market_status import (
    INGEST_LIVE,
    INGEST_MAINTENANCE,
    INGEST_QUEUED,
    INGEST_SPRINT,
    LIVE_MARKET_ID,
    ROLE_ADMITTED,
    ROLE_FOCUS,
    ROLE_LIVE,
    build_market_status,
    write_market_status,
)
from value_investor.publish import build_dashboard_bundle, publish_dashboard
from value_investor.storage import write_json


def _write_sample_output(output_dir: Path) -> None:
    signals = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "name": "Alpha PLC",
                "sector": "Financials",
                "signal": "strong_buy",
                "models_passed": 10,
                "model_count": 18,
                "composite_score": 0.8,
                "sector_composite_score": 0.82,
                "families_passed": 3,
                "passed_families": "cheapness,quality",
                "data_quality_score": 0.85,
                "metrics_present": 18,
                "metrics_total": 20,
                "weeks_at_signal": 2,
                "signal_trend": "stable",
                "conviction_score": 0.7,
                "stability_label": "building",
                "timing_signal": "accumulate",
                "timing_score": 0.75,
                "rsi_14": 34.0,
                "price_vs_sma200_pct": -0.05,
                "timing_reasons": "['RSI below neutral (34)']",
                "action_note": "Strong Buy — favourable entry timing",
                "run_at": "2026-07-08T07:00:00+00:00",
            },
            {
                "ticker": "BBB.L",
                "name": "Beta PLC",
                "sector": "Energy",
                "signal": "hold",
                "models_passed": 5,
                "model_count": 18,
                "composite_score": 0.5,
                "sector_composite_score": 0.48,
                "families_passed": 2,
                "passed_families": "cheapness",
                "data_quality_score": 0.7,
                "metrics_present": 14,
                "metrics_total": 20,
                "weeks_at_signal": 1,
                "signal_trend": "new",
                "conviction_score": 0.4,
                "stability_label": "new",
                "timing_signal": "neutral",
                "timing_score": 0.5,
                "rsi_14": 50.0,
                "price_vs_sma200_pct": 0.02,
                "timing_reasons": "[]",
                "action_note": "Hold — neutral timing",
                "run_at": "2026-07-08T07:00:00+00:00",
            },
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "model_name": "Graham Defensive",
                "passed": True,
                "score": 1.0,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    signals.to_csv(output_dir / "latest_signals.csv", index=False)
    model_results.to_csv(output_dir / "latest_model_results.csv", index=False)
    (output_dir / "run_diff.json").write_text(
        json.dumps(
            {
                "new_strong_buys": ["Alpha (AAA.L)"],
                "persistent_strong_buys": [],
                "lost_strong_buys": [],
                "upgrades": [],
                "downgrades": [],
                "unchanged_top_signals": 1,
            }
        ),
        encoding="utf-8",
    )


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
        root / "markets" / "aim" / "manifest.json",
        {
            "ticker_count": 40,
            "coverage_count": 38,
            "coverage_pct": 0.95,
            "last_metrics_refresh": "2026-09-01T08:00:00+00:00",
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


def _status_roots(tmp_path: Path) -> dict:
    return {
        "paper_root": tmp_path / "paper_live",
        "charts_dir": tmp_path / "charts",
        "macro_root": tmp_path / "macro",
        "shard_root": tmp_path / "paper",
    }


def test_build_market_status_classifies_ingest_and_signals(tmp_path: Path):
    library = _seed_library(tmp_path / "library")
    payload = build_market_status(
        library_root=library,
        policy_path=library / "policy.json",
        dispatch_path=library / "euro_ingest_dispatch.json",
        **_status_roots(tmp_path),
        live_meta={
            "company_count": 249,
            "signal_counts": {"strong_buy": 16, "buy": 47, "hold": 142},
        },
        live_signal_counts={"strong_buy": 16, "buy": 47, "hold": 142, "avoid": 43},
        live_run_at="2026-09-03T09:00:00+00:00",
    )

    assert payload["schema_version"] == 3
    assert payload["focus_market"] == "euro_depth"
    assert payload["summary"]["sprint_count"] >= 3
    assert payload["summary"]["live_count"] == 1

    live = _by_id(payload, LIVE_MARKET_ID)
    assert live["role"] == ROLE_LIVE
    assert live["ingest"] == INGEST_LIVE
    assert live["signal_counts"]["strong_buy"] == 16
    assert live["learning_phase_label"] == "Live screen"
    assert live["ticker_count"] == 249
    assert live["held_vs_market"]["branch_ready"] is True
    assert all(
        isinstance((row.get("held_vs_market") or {}).get("points"), list)
        for row in payload["markets"]
    )

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

    from_manifest = _by_id(payload, "aim")
    assert from_manifest["coverage_pct"] == 0.95
    assert from_manifest["ticker_count"] == 40
    assert from_manifest["last_metrics_refresh"] == "2026-09-01T08:00:00+00:00"

    assert payload["markets"][0]["market_id"] == LIVE_MARKET_ID
    assert payload["markets"][1]["market_id"] == "euro_depth"


def test_build_market_status_survives_empty_library(tmp_path: Path):
    library = tmp_path / "empty"
    library.mkdir()
    payload = build_market_status(
        library_root=library,
        policy_path=library / "missing-policy.json",
        dispatch_path=library / "missing-dispatch.json",
        **_status_roots(tmp_path),
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
    assert bundle["market_status"]["schema_version"] == 3
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
    assert payload["schema_version"] == 3
    assert any(row["market_id"] == LIVE_MARKET_ID for row in payload["markets"])


def test_dashboard_assets_include_market_status_grid():
    app = Path("docs/app.js").read_text(encoding="utf-8")
    html = Path("docs/index.html").read_text(encoding="utf-8")
    css = Path("docs/styles.css").read_text(encoding="utf-8")
    assert "function renderMarketStatusGrid(data)" in app
    assert "function openMarketStatusCard(marketId)" in app
    assert "function renderMarketStatusCard(row)" in app
    assert "row.is_admitted" in app
    assert "Epoch-0 book" in app
    assert "Near-miss watch" in app
    assert "function bindDashboardAutoRefresh()" in app
    assert "async function applyDashboardSidecars(data)" in app
    assert "function spareSprintLabel(spare)" in app
    assert "function learningBookLine(row)" in app
    assert "Learning ·" in app
    assert "async function refreshLocalMarketStatus()" in app
    assert 'id="market-status-dialog"' in html
    assert 'id="market-status-body"' in html
    assert ".market-status-grid" in css
    assert ".market-tile" in css
    assert ".market-tile-chips" in css
    assert "grid-auto-rows: 1fr" in css
    assert 'class="market-tile-chips"' in app
    assert "function sprintProgressLine(progress)" in app
    assert "function renderSprintProgressCard(progress)" in app
    assert "Last ${esc(String(progress.window_days || 2))} days ingest" in app
    assert "admission-flag" in app
    assert ".admission-flag" in css
    assert ".market-tile-sprint" in css
    assert "function equalizeMarketTileHeights()" in app
    assert "equalizeMarketTileHeights()" in app
    assert "function heldVsMarketLastCaption(payload, { showExcess = true } = {})" in Path(
        "docs/charts.js"
    ).read_text(encoding="utf-8")
    assert "function renderHeldVsMarketSparkline(payload)" in Path("docs/charts.js").read_text(
        encoding="utf-8"
    )
    assert "function renderHeldVsMarketChart(payload)" in Path("docs/charts.js").read_text(
        encoding="utf-8"
    )
    assert "renderHeldVsMarketSparkline(row.held_vs_market)" in app
    assert "renderHeldVsMarketChart(row.held_vs_market)" in app
    assert ".held-vs-market-spark" in css
    assert (
        "flex-direction: column"
        in css.split(".held-vs-market-spark.empty {", 1)[1].split("}", 1)[0]
    )
    assert "branch-ready" in Path("docs/charts.js").read_text(encoding="utf-8")
    tile_css = css.split(".market-tile {", 1)[1].split("}", 1)[0]
    assert "white-space: normal" in tile_css
    assert "height: 100%" in tile_css
    header_css = css.split(".market-tile-header {", 1)[1].split("}", 1)[0]
    assert "flex-direction: column" in header_css


def test_dashboard_assets_include_system_gaps_card():
    app = Path("docs/app.js").read_text(encoding="utf-8")
    html = Path("docs/index.html").read_text(encoding="utf-8")
    css = Path("docs/styles.css").read_text(encoding="utf-8")
    assert "function renderSystemGapsCard(data)" in app
    assert "function openSystemGapCard(flagId)" in app
    assert 'id="system-gaps-card"' in app
    assert 'id="system-gaps-dialog"' in html
    assert 'id="system-gaps-body"' in html
    assert ".system-gaps-grid" in css
    assert ".system-gap-tile" in css


def test_build_market_status_admitted_epoch0_and_near_miss(tmp_path: Path):
    library = _seed_library(tmp_path / "library")
    policy = json.loads((library / "policy.json").read_text(encoding="utf-8"))
    policy["ladder"] = {
        "admitted_learning_markets": ["sp500", "asx200"],
        "weekly_paper_shard_markets": ["euro_depth"],
    }
    policy["ingest_parallel_sprint"] = ["tsx60"]
    policy["ingest_parallel_sprint_2"] = ["ftse_smallcap"]
    policy["ingest_exhausted_markets"] = ["sp500"]
    policy["ftse_equivalent_markets"] = ["sp500"]
    (library / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    write_json(
        library / "equal_support_status.json",
        {
            "generated_at": "2026-09-07T10:54:00+00:00",
            "admitted": ["sp500", "asx200"],
            "ai_judgment": False,
            "knob_apply": False,
            "markets": {
                "sp500": {
                    "buy_tier_not_now_count": 12,
                    "hold_near_buy_count": 152,
                    "not_buy_tier_count": 363,
                    "never_buy_tier_count": 336,
                    "rememo_eligible_count": 54,
                    "timing_signal_present": True,
                }
            },
        },
        compact=False,
    )
    write_json(
        library / "markets" / "sp500" / "screen" / "near_miss_watch.json",
        {
            "buy_tier_not_now_count": 12,
            "hold_near_buy_count": 152,
            "not_buy_tier_count": 363,
            "never_buy_tier_count": 336,
            "timing_signal_present": True,
            "buy_tier_not_now": [{"ticker": "XYZ"}],
            "hold_near_buy": [{"ticker": "ABC"}],
        },
        compact=False,
    )
    dispatch = json.loads((library / "euro_ingest_dispatch.json").read_text(encoding="utf-8"))
    dispatch["maintenance_markets"] = ["sp500"]
    dispatch["should_run_library_maintenance"] = True
    dispatch["sprint_markets"] = ["euro_depth"]
    dispatch["parallel_sprint_markets"] = ["tsx60"]
    dispatch["parallel_sprint_2_markets"] = ["ftse_smallcap"]
    dispatch["parallel_sprint_status"] = []
    (library / "euro_ingest_dispatch.json").write_text(json.dumps(dispatch), encoding="utf-8")

    shard = tmp_path / "paper" / "sp500"
    write_json(
        shard / "weekday_batch_log.json",
        {
            "updated_at": "2026-09-07T10:31:56+00:00",
            "entries": [
                {
                    "run_at": "2026-09-07T10:31:56+00:00",
                    "cadence": "epoch0",
                    "ai_judgment": False,
                    "knob_apply": False,
                    "tracks_acted": {"buy_tier_level": True},
                }
            ],
        },
        compact=False,
    )
    write_json(
        shard / "buy_tier_level" / "automated_fund.json",
        {
            "cash": 0.0,
            "contributed_capital": 1000.0,
            "holdings": {"AAA": {"ticker": "AAA"}, "BBB": {"ticker": "BBB"}},
            "equity_curve": [
                {
                    "at": "2026-09-01T10:31:56+00:00",
                    "portfolio_value": 1000.0,
                    "cash": 0.0,
                    "positions": 2,
                },
                {
                    "at": "2026-09-07T10:31:56+00:00",
                    "portfolio_value": 737.41,
                    "cash": 0.0,
                    "positions": 2,
                },
            ],
        },
        compact=False,
    )

    payload = build_market_status(
        library_root=library,
        policy_path=library / "policy.json",
        dispatch_path=library / "euro_ingest_dispatch.json",
        **_status_roots(tmp_path),
        live_signal_counts={"hold": 1},
    )
    sp500 = _by_id(payload, "sp500")
    assert sp500["is_admitted"] is True
    assert sp500["role"] == ROLE_ADMITTED
    assert sp500["ingest"] == INGEST_MAINTENANCE
    assert sp500["ingest_exhausted"] is True
    assert sp500["shared_maintenance"] is True
    assert sp500["is_ftse_equivalent"] is True
    assert sp500["learning_phase_label"] == "Epoch-0 level"
    assert sp500["epoch0"]["holdings"] == 2
    assert sp500["epoch0"]["nav"] == 737.41
    chart = sp500["held_vs_market"]
    assert chart["status"] == "ok"
    assert chart["branch_ready"] is True
    assert chart["source"] == "paper_fund"
    assert len(chart["points"]) == 2
    assert chart["points"][-1]["held"] == 737.41
    assert any(row["kind"] == "branch" or row["id"] == "held" for row in chart["series"])
    assert sp500["near_miss"]["buy_tier_not_now_count"] == 12
    assert sp500["near_miss"]["hold_near_buy_sample"] == ["ABC"]
    assert sp500["equal_support"]["rememo_eligible_count"] == 54
    assert payload["admitted_markets"] == ["sp500", "asx200"]
    assert payload["summary"]["should_run_library_maintenance"] is True
    assert payload["summary"]["spare_sprint"] == {"1": "tsx60", "2": "ftse_smallcap"}
    tsx60 = _by_id(payload, "tsx60")
    assert tsx60["ingest"] == INGEST_SPRINT
    assert tsx60["learning_phase"] == 1
    assert tsx60["learning_phase_label"] == "Observe"
    smallcap = _by_id(payload, "ftse_smallcap")
    assert smallcap["ingest"] == INGEST_SPRINT
    assert smallcap["learning_phase"] == 1
    assert smallcap["learning_phase_label"] == "Observe"

    dest = tmp_path / "docs" / "data" / "market_status.json"
    write_json(
        tmp_path / "docs" / "data" / "latest.json",
        {
            "run_at": "2026-09-07T00:00:00+00:00",
            "meta": {"company_count": 2, "signal_counts": {"hold": 2}},
        },
        compact=False,
    )
    path = write_market_status(
        library_root=library,
        policy_path=library / "policy.json",
        dispatch_path=library / "euro_ingest_dispatch.json",
        **_status_roots(tmp_path),
        latest_path=tmp_path / "docs" / "data" / "latest.json",
        path=dest,
    )
    assert path == dest
    written = json.loads(dest.read_text(encoding="utf-8"))
    assert written["schema_version"] == 3
    assert _by_id(written, LIVE_MARKET_ID)["ticker_count"] == 2


def test_sprint_without_benchmark_shows_ingest_only(tmp_path: Path):
    library = _seed_library(tmp_path / "library")
    policy = json.loads((library / "policy.json").read_text(encoding="utf-8"))
    policy["ingest_parallel_sprint"] = ["aim"]
    policy["ingest_parallel_sprint_2"] = []
    (library / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    dispatch = json.loads((library / "euro_ingest_dispatch.json").read_text(encoding="utf-8"))
    dispatch["sprint_markets"] = ["euro_depth", "aim"]
    dispatch["parallel_sprint_markets"] = ["aim"]
    dispatch["parallel_sprint_2_markets"] = []
    dispatch["parallel_sprint_status"] = [
        {
            "market_id": "aim",
            "mode": "sprint",
            "reason": "Ingest sprint: indexed_without_body=1",
            "phase_blockers": ["no benchmark configured for aim"],
        }
    ]
    (library / "euro_ingest_dispatch.json").write_text(json.dumps(dispatch), encoding="utf-8")

    payload = build_market_status(
        library_root=library,
        policy_path=library / "policy.json",
        dispatch_path=library / "euro_ingest_dispatch.json",
        **_status_roots(tmp_path),
        live_signal_counts={"hold": 1},
    )
    aim = _by_id(payload, "aim")
    assert aim["ingest"] == INGEST_SPRINT
    assert aim["learning_phase"] == 0
    assert aim["learning_phase_label"] == "Ingest only"
    assert "no benchmark configured for aim" in aim["phase_blockers"]


def test_dispatch_current_phase_fills_missing_shard_row(tmp_path: Path):
    library = _seed_library(tmp_path / "library")
    policy = json.loads((library / "policy.json").read_text(encoding="utf-8"))
    policy["ingest_parallel_sprint"] = ["tsx60"]
    (library / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    dispatch = json.loads((library / "euro_ingest_dispatch.json").read_text(encoding="utf-8"))
    dispatch["sprint_markets"] = ["euro_depth", "tsx60"]
    dispatch["parallel_sprint_markets"] = ["tsx60"]
    dispatch["parallel_sprint_status"] = [
        {
            "market_id": "tsx60",
            "mode": "sprint",
            "current_phase": 1,
            "next_phase": 1,
            "phase_blockers": ["need 4 observe snapshots (have 0)"],
        }
    ]
    (library / "euro_ingest_dispatch.json").write_text(json.dumps(dispatch), encoding="utf-8")

    payload = build_market_status(
        library_root=library,
        policy_path=library / "policy.json",
        dispatch_path=library / "euro_ingest_dispatch.json",
        **_status_roots(tmp_path),
        live_signal_counts={"hold": 1},
    )
    tsx60 = _by_id(payload, "tsx60")
    assert tsx60["learning_phase"] == 1
    assert tsx60["learning_phase_label"] == "Observe"
    assert tsx60["learning"]["current_phase"] == 1


def test_stale_dispatch_benchmark_blocker_yields_to_live_phase(tmp_path: Path):
    library = _seed_library(tmp_path / "library")
    policy = json.loads((library / "policy.json").read_text(encoding="utf-8"))
    policy["ingest_parallel_sprint_2"] = ["ftse_smallcap"]
    (library / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    dispatch = json.loads((library / "euro_ingest_dispatch.json").read_text(encoding="utf-8"))
    dispatch["sprint_markets"] = ["euro_depth", "ftse_smallcap"]
    dispatch["parallel_sprint_2_markets"] = ["ftse_smallcap"]
    dispatch["parallel_sprint_2_status"] = [
        {
            "market_id": "ftse_smallcap",
            "mode": "sprint",
            "phase_blockers": ["no benchmark configured for ftse_smallcap"],
        }
    ]
    (library / "euro_ingest_dispatch.json").write_text(json.dumps(dispatch), encoding="utf-8")

    payload = build_market_status(
        library_root=library,
        policy_path=library / "policy.json",
        dispatch_path=library / "euro_ingest_dispatch.json",
        **_status_roots(tmp_path),
        live_signal_counts={"hold": 1},
    )
    smallcap = _by_id(payload, "ftse_smallcap")
    assert smallcap["learning_phase"] == 1
    assert smallcap["learning_phase_label"] == "Observe"
    assert "no benchmark configured for ftse_smallcap" not in smallcap["phase_blockers"]
    assert any("observe snapshots" in item for item in smallcap["phase_blockers"])


def _health_snapshot(
    *,
    unmeasured: int,
    zero_body: int,
    thin: int,
    iwb: int,
    unmeasured_tickers: list[str] | None = None,
    zero_tickers: list[str] | None = None,
) -> dict:
    return {
        "unmeasured_buy_tier": unmeasured,
        "zero_body_buy_tier": zero_body,
        "thin_body_buy_tier": thin,
        "indexed_without_body": iwb,
        "unmeasured_tickers": unmeasured_tickers or [],
        "zero_body_tickers": zero_tickers or [],
        "ingest_exhausted": False,
    }


def test_sprint_tiles_include_two_day_ingest_and_admission_flags(tmp_path: Path):
    library = _seed_library(tmp_path / "library")
    policy = json.loads((library / "policy.json").read_text(encoding="utf-8"))
    policy["ingest_parallel_sprint"] = ["tsx60"]
    policy["ingest_parallel_sprint_2"] = ["ftse_smallcap"]
    (library / "policy.json").write_text(json.dumps(policy), encoding="utf-8")

    dispatch = json.loads((library / "euro_ingest_dispatch.json").read_text(encoding="utf-8"))
    dispatch["sprint_markets"] = ["euro_depth", "tsx60", "ftse_smallcap"]
    dispatch["parallel_sprint_markets"] = ["tsx60"]
    dispatch["parallel_sprint_2_markets"] = ["ftse_smallcap"]
    dispatch["parallel_sprint_status"] = [
        {
            "market_id": "tsx60",
            "mode": "sprint",
            "ingest_parity_met": False,
            "ingest_exhausted": False,
            "filing_gaps": 2,
            "filing_health": _health_snapshot(
                unmeasured=1,
                zero_body=1,
                thin=5,
                iwb=182,
                unmeasured_tickers=["GIB-A.TO"],
                zero_tickers=["CCL-B.TO"],
            ),
        }
    ]
    dispatch["parallel_sprint_2_status"] = [
        {
            "market_id": "ftse_smallcap",
            "mode": "sprint",
            "ingest_parity_met": False,
            "ingest_exhausted": False,
            "filing_gaps": 2,
            "phase_blockers": ["no benchmark configured for ftse_smallcap"],
            "filing_health": _health_snapshot(unmeasured=0, zero_body=2, thin=1, iwb=45),
        }
    ]
    (library / "euro_ingest_dispatch.json").write_text(json.dumps(dispatch), encoding="utf-8")

    now = datetime(2026, 9, 7, 16, 0, tzinfo=UTC)
    tsx_screen = library / "markets" / "tsx60" / "screen"
    tsx_screen.mkdir(parents=True)
    write_json(
        tsx_screen / "latest_summary.json",
        {
            "market": "tsx60",
            "run_at": "2026-08-16T11:58:34+00:00",
            "ticker_count": 59,
            "signal_counts": {"buy": 13, "strong_buy": 6, "hold": 29},
            "shortlist_count": 19,
        },
        compact=False,
    )
    write_json(
        library / "markets" / "tsx60" / "ingest_health_log.json",
        {
            "entries": [
                {
                    "run_at": "2026-09-06T13:42:00+00:00",
                    "market_id": "tsx60",
                    "health_before": _health_snapshot(unmeasured=1, zero_body=3, thin=9, iwb=235),
                    "health_after": _health_snapshot(unmeasured=1, zero_body=1, thin=8, iwb=200),
                    "targets": 18,
                    "improved": 14,
                    "improved_tickers": ["SU.TO", "NTR.TO"],
                    "runtime_cutoff": False,
                    "partial": False,
                    "errors": [],
                },
                {
                    "run_at": "2026-09-07T14:04:00+00:00",
                    "market_id": "tsx60",
                    "health_before": _health_snapshot(unmeasured=1, zero_body=1, thin=8, iwb=200),
                    "health_after": _health_snapshot(unmeasured=1, zero_body=1, thin=5, iwb=182),
                    "targets": 12,
                    "improved": 4,
                    "improved_tickers": ["CNR.TO", "WSP.TO"],
                    "runtime_cutoff": False,
                    "partial": False,
                    "errors": [],
                },
            ]
        },
        compact=False,
    )

    small_screen = library / "markets" / "ftse_smallcap" / "screen"
    small_screen.mkdir(parents=True, exist_ok=True)
    write_json(
        small_screen / "latest_summary.json",
        {
            "market": "ftse_smallcap",
            "run_at": "2026-08-16T11:58:34+00:00",
            "ticker_count": 79,
            "signal_counts": {"buy": 10, "strong_buy": 2, "hold": 47},
            "shortlist_count": 12,
        },
        compact=False,
    )
    write_json(
        library / "markets" / "ftse_smallcap" / "ingest_health_log.json",
        {
            "entries": [
                {
                    "run_at": "2026-09-06T17:07:00+00:00",
                    "market_id": "ftse_smallcap",
                    "health_before": _health_snapshot(unmeasured=0, zero_body=3, thin=6, iwb=108),
                    "health_after": _health_snapshot(unmeasured=0, zero_body=2, thin=3, iwb=70),
                    "targets": 6,
                    "improved": 3,
                    "improved_tickers": ["FOXT.L"],
                    "runtime_cutoff": False,
                    "errors": [],
                },
                {
                    "run_at": "2026-09-07T14:21:00+00:00",
                    "market_id": "ftse_smallcap",
                    "health_before": _health_snapshot(unmeasured=0, zero_body=2, thin=3, iwb=70),
                    "health_after": _health_snapshot(unmeasured=0, zero_body=2, thin=1, iwb=45),
                    "targets": 6,
                    "improved": 2,
                    "improved_tickers": ["DFS.L"],
                    "runtime_cutoff": False,
                    "errors": [],
                },
            ]
        },
        compact=False,
    )

    payload = build_market_status(
        library_root=library,
        policy_path=library / "policy.json",
        dispatch_path=library / "euro_ingest_dispatch.json",
        **_status_roots(tmp_path),
        live_signal_counts={"hold": 1},
        now=now,
    )
    tsx = _by_id(payload, "tsx60")
    progress = tsx["sprint_progress"]
    assert tsx["ingest"] == INGEST_SPRINT
    assert progress["run_count"] == 2
    assert progress["targets"] == 30
    assert progress["improved"] == 18
    assert progress["gap_delta"]["indexed_without_body"] == -53
    assert progress["remaining"]["unmeasured"] == 1
    assert progress["admission_ready"] is False
    flag_ids = {row["id"] for row in progress["admission_warnings"]}
    assert "stale_buy_tier_screen" in flag_ids
    assert "unmeasured_stuck" in flag_ids
    assert "zero_body_stuck" not in flag_ids
    assert "no_ingest_in_window" not in flag_ids
    assert "no_observe_benchmark" not in flag_ids

    small = _by_id(payload, "ftse_smallcap")
    small_progress = small["sprint_progress"]
    assert small["ingest_stream"] == 2
    assert small_progress["run_count"] == 2
    assert small_progress["improved"] == 5
    small_flags = {row["id"] for row in small_progress["admission_warnings"]}
    # L333 mapped ftse_smallcap to ^FTSC, so the observe-clock flag clears.
    assert "no_observe_benchmark" not in small_flags
    assert "stale_buy_tier_screen" in small_flags
    assert "zero_body_stuck" not in small_flags
    assert "unmeasured_stuck" not in small_flags
    assert small["learning_phase_label"] == "Observe"

    live = _by_id(payload, LIVE_MARKET_ID)
    assert live["sprint_progress"] is None

    focus = _by_id(payload, "euro_depth")
    assert focus["ingest"] == INGEST_SPRINT
    assert {
        row["id"] for row in (focus["sprint_progress"] or {}).get("admission_warnings") or []
    } >= {"no_ingest_in_window"}
