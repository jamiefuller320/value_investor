"""Tests for library ingest completion-gate dispatch (euro_depth wrapper)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.euro_depth_ingest_dispatch import (
    MODE_IDLE,
    MODE_MAINTENANCE,
    MODE_SPRINT,
    apply_library_maintenance_schedule,
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
    phase = {
        "phase3_ready": False,
        "current_phase": 2,
        "next_phase": 2,
        "blockers": ["need 8 weekday batch marks"],
    }
    health = {
        "unmeasured_buy_tier": 2,
        "zero_body_buy_tier": 1,
    }
    policy = {
        "focus_market": "euro_depth",
        "ladder": {"admitted_learning_markets": ["asx200", "sp500"]},
        "ingest_exhausted_markets": ["sp500"],
        "ingest_parity_markets": ["asx200"],
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
        patch(
            "value_investor.library_ingest_dispatch.load_policy",
            return_value=policy,
        ),
    ):
        result = evaluate_euro_ingest_dispatch()
    assert result["mode"] == MODE_SPRINT
    assert result["should_run_sprint_ingest"] is True
    assert result["should_run_maintenance_ingest"] is False
    assert result["should_run_ingest"] is True
    assert result["ingest_parity_met"] is False
    assert result["current_phase"] == 2
    assert result["next_phase"] == 2
    assert result["max_daily_successes"] == 4
    assert result["max_targets"] == 24
    # Admitted ASX/S&P stay on the shared maintenance loop even while euro sprints
    # and even if a later screen reopens buy-tier filing gaps.
    assert "asx200" in result["maintenance_markets"]
    assert "sp500" in result["maintenance_markets"]
    assert result["should_run_library_maintenance"] is True
    assert cron_enabled_for_dispatch(result) == {
        "morning": True,
        "afternoon": True,
        "midafternoon": True,
        "evening": True,
        "ladder_weekday": True,
        "maintenance": True,
        "maintenance_afternoon": True,
        "maintenance_midafternoon": True,
        "maintenance_evening": True,
    }


def test_focus_sprint_keeps_shared_maintenance_crons_when_admitted_markets_need_them():
    """Euro sprint slots stay on; library maintenance crons follow maintenance_markets."""
    sprint_row = {
        "mode": MODE_SPRINT,
        "cron_morning": True,
        "cron_afternoon": True,
        "cron_midafternoon": True,
        "cron_evening": True,
        "cron_ladder_weekday": True,
        "cron_maintenance": False,
        "should_run_sprint_ingest": True,
        "should_run_maintenance_ingest": False,
        "maintenance_markets": ["asx200", "sp500"],
    }
    apply_library_maintenance_schedule(sprint_row)
    assert sprint_row["should_run_library_maintenance"] is True
    assert sprint_row["cron_maintenance"] is True
    assert sprint_row["should_run_maintenance_ingest"] is False
    enabled = cron_enabled_for_dispatch(sprint_row)
    assert enabled["morning"] is True
    assert enabled["maintenance"] is True
    assert enabled["maintenance_evening"] is True

    empty = {
        "mode": MODE_SPRINT,
        "cron_morning": True,
        "cron_maintenance": False,
        "should_run_maintenance_ingest": False,
        "maintenance_markets": [],
    }
    apply_library_maintenance_schedule(empty)
    assert empty["should_run_library_maintenance"] is False
    assert empty["cron_maintenance"] is False
    assert cron_enabled_for_dispatch(empty)["maintenance"] is False


def test_library_grow_commits_shard_paper_books():
    text = Path(".github/workflows/library-grow.yml").read_text(encoding="utf-8")
    # L348: library-grow commits via gha_commit_artifacts.sh with a markets/
    # directory owned pathspec (covers automated_fund + weekday_batch_log).
    assert "scripts/gha_commit_artifacts.sh" in text
    assert "docs/data/paper_automation/markets" in text
    assert "stefanzweifel/git-auto-commit-action@v6" not in text


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
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
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
    assert result["mode"] == MODE_MAINTENANCE
    assert result["ingest_parity_met"] is True
    assert result["should_run_sprint_ingest"] is False
    assert result["should_run_maintenance_ingest"] is True
    assert result["should_run_ingest"] is False
    assert result["max_daily_successes"] == 8
    assert result["max_targets"] == 62
    assert MODE_IDLE == MODE_MAINTENANCE
    assert cron_enabled_for_dispatch(result) == {
        "morning": False,
        "afternoon": False,
        "midafternoon": False,
        "evening": False,
        "ladder_weekday": True,
        "maintenance": True,
        "maintenance_afternoon": True,
        "maintenance_midafternoon": True,
        "maintenance_evening": True,
    }


def test_ingest_parity_met_requires_thin_and_indexed_for_all_markets():
    base = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
        "ftse_equivalent": False,
    }
    assert ingest_parity_met(base)
    assert not ingest_parity_met({**base, "thin_body_buy_tier": 5})
    assert not ingest_parity_met({**base, "indexed_without_body": 20})
    assert not ingest_parity_met({"unmeasured_buy_tier": 1, "zero_body_buy_tier": 0})
    assert ingest_parity_met({**base, "ftse_equivalent": True})
    assert not ingest_parity_met({**base, "ftse_equivalent": True, "thin_body_buy_tier": 1})
    assert not ingest_parity_met({**base, "ftse_equivalent": True, "indexed_without_body": 12})


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


def test_evaluate_dispatch_sprint_when_euro_thin_only():
    phase = {"phase3_ready": True, "blockers": []}
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 29,
        "indexed_without_body": 94,
        "ftse_equivalent": False,
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
    assert result["ingest_parity_met"] is False
    assert result["should_run_sprint_ingest"] is True
    assert result["max_targets"] == 24
    assert "thin=29" in result["reason"]


def test_write_euro_ingest_dispatch_persists(tmp_path: Path):
    path = tmp_path / "euro_ingest_dispatch.json"
    payload = {"mode": MODE_SPRINT, "reason": "test"}
    write_euro_ingest_dispatch(payload, path=path)
    assert path.exists()
    assert '"mode": "sprint"' in path.read_text(encoding="utf-8")
