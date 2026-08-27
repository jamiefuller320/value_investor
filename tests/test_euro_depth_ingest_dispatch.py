"""Tests for library ingest completion-gate dispatch (euro_depth wrapper)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.euro_depth_ingest_dispatch import (
    MODE_IDLE,
    MODE_MAINTENANCE,
    MODE_SPRINT,
    cron_enabled_for_dispatch,
    evaluate_euro_ingest_dispatch,
    ingest_parity_met,
    snapshot_library_buy_tier_filing_health,
    write_euro_ingest_dispatch,
)
from value_investor.storage import write_json
from value_investor.summary import CompanyReport


def _report(ticker: str, signal: str = "buy", conviction: float = 0.5) -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=f"{ticker} Co",
        sector="X",
        signal=signal,
        models_passed=5,
        model_count=10,
        composite_score=0.6,
        sector_composite_score=0.55,
        families_passed=3,
        passed_families="cheapness",
        data_quality_score=0.8,
        metrics_present=10,
        metrics_total=12,
        weeks_at_signal=1,
        signal_trend="stable",
        conviction_score=conviction,
        stability_label="stable",
        timing_signal="hold",
        timing_score=0.0,
        rsi_14=None,
        price_vs_sma200_pct=None,
        action_note="",
        trade_plan=None,
        summary="",
        passed_models=[],
        key_metrics={},
    )


def test_snapshot_library_buy_tier_filing_health_counts_gaps(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    screen_dir = root / "markets" / market / "screen"
    research_dir = screen_dir / "research"
    for ticker, total, with_body in (("AAA.DE", 0, 0), ("BBB.DE", 4, 0), ("CCC.DE", 6, 2)):
        filings_dir = research_dir / ticker / "sources" / "filings"
        filings_dir.mkdir(parents=True)
        write_json(
            filings_dir / "filings_index.json",
            {"summary": {"total": total, "with_body": with_body}, "filings": []},
            compact=False,
        )
    with patch(
        "value_investor.library_ingest_loop.load_library_buy_tier_reports",
        return_value=[_report("AAA.DE"), _report("BBB.DE"), _report("CCC.DE")],
    ):
        health = snapshot_library_buy_tier_filing_health(market, library_root=root)
    assert health["buy_tier_count"] == 3
    assert health["unmeasured_buy_tier"] == 1
    assert health["zero_body_buy_tier"] == 1
    assert health["thin_body_buy_tier"] == 1
    assert health["indexed_without_body"] == 8
    assert health["bodies_min"] == 2
    assert health["bodies_median"] == 2
    assert health["bodies_max"] == 2
    assert health["coverage_scope"] == "canonical_plus_shards"
    assert health["ftse_equivalent"] is False


def test_evaluate_dispatch_sprint_when_filing_gaps_remain():
    phase = {"phase3_ready": False, "blockers": ["need 8 weekday batch marks"]}
    health = {
        "unmeasured_buy_tier": 2,
        "zero_body_buy_tier": 1,
    }
    with (
        patch(
            "value_investor.library_ingest_dispatch.evaluate_market_phase",
            return_value=phase,
        ),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
    ):
        result = evaluate_euro_ingest_dispatch()
    assert result["mode"] == MODE_SPRINT
    assert result["should_run_sprint_ingest"] is True
    assert result["should_run_maintenance_ingest"] is False
    assert result["should_run_ingest"] is True
    assert result["ingest_parity_met"] is False
    assert result["max_daily_successes"] == 4
    assert result["max_targets"] == 24
    assert cron_enabled_for_dispatch(result) == {
        "morning": True,
        "afternoon": True,
        "midafternoon": True,
        "evening": True,
        "ladder_weekday": True,
        "maintenance": False,
    }


def test_evaluate_dispatch_sprint_when_phase3_ready_but_gaps_remain():
    phase = {"phase3_ready": True, "blockers": []}
    health = {"unmeasured_buy_tier": 1, "zero_body_buy_tier": 0}
    with (
        patch(
            "value_investor.library_ingest_dispatch.evaluate_market_phase",
            return_value=phase,
        ),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
    ):
        result = evaluate_euro_ingest_dispatch()
    assert result["mode"] == MODE_SPRINT
    assert result["should_run_sprint_ingest"] is True
    assert result["should_run_ingest"] is True


def test_evaluate_dispatch_maintenance_when_parity_met():
    phase = {"phase3_ready": True, "blockers": []}
    health = {"unmeasured_buy_tier": 0, "zero_body_buy_tier": 0}
    with (
        patch(
            "value_investor.library_ingest_dispatch.evaluate_market_phase",
            return_value=phase,
        ),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
    ):
        result = evaluate_euro_ingest_dispatch()
    assert result["mode"] == MODE_MAINTENANCE
    assert result["ingest_parity_met"] is True
    assert result["should_run_sprint_ingest"] is False
    assert result["should_run_maintenance_ingest"] is True
    assert result["should_run_ingest"] is False
    assert result["max_daily_successes"] == 1
    assert result["max_targets"] == 4
    assert MODE_IDLE == MODE_MAINTENANCE
    assert cron_enabled_for_dispatch(result) == {
        "morning": False,
        "afternoon": False,
        "midafternoon": False,
        "evening": False,
        "ladder_weekday": True,
        "maintenance": True,
    }


def test_ingest_parity_met_euro_depth_ignores_thin_and_indexed():
    assert ingest_parity_met(
        {
            "unmeasured_buy_tier": 0,
            "zero_body_buy_tier": 0,
            "thin_body_buy_tier": 5,
            "indexed_without_body": 20,
            "ftse_equivalent": False,
        }
    )
    assert not ingest_parity_met({"unmeasured_buy_tier": 1, "zero_body_buy_tier": 0})


def test_ingest_parity_met_ftse_equivalent_requires_thin_and_indexed():
    base = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
        "ftse_equivalent": True,
    }
    assert ingest_parity_met(base)
    assert not ingest_parity_met({**base, "thin_body_buy_tier": 1})
    assert not ingest_parity_met({**base, "indexed_without_body": 12})


def test_evaluate_dispatch_sprint_when_ftse_equivalent_thin_only():
    phase = {"phase3_ready": False, "blockers": []}
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 21,
        "indexed_without_body": 1154,
        "ftse_equivalent": True,
    }
    with (
        patch(
            "value_investor.library_ingest_dispatch.evaluate_market_phase",
            return_value=phase,
        ),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
    ):
        result = evaluate_euro_ingest_dispatch(market_id="sp500")
    assert result["mode"] == MODE_SPRINT
    assert result["ingest_parity_met"] is False
    assert result["max_targets"] == 24
    assert "indexed_without_body" in result["reason"]


def test_write_euro_ingest_dispatch_persists(tmp_path: Path):
    path = tmp_path / "euro_ingest_dispatch.json"
    payload = {"mode": MODE_SPRINT, "reason": "test"}
    write_euro_ingest_dispatch(payload, path=path)
    assert path.exists()
    assert '"mode": "sprint"' in path.read_text(encoding="utf-8")
