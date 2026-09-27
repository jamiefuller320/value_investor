"""Tests for point-in-time historical analysis engine."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.backtest import load_run_snapshots
from value_investor.historical_analysis import (
    COHORT_FULL_UNIVERSE,
    COHORT_OVERLAY_BUY_TIER,
    PRIMARY_ATTRIBUTION_HORIZON_DAYS,
    RETURN_BASIS_EXCESS_VS_FTSE,
    RETURN_BASIS_RAW,
    SUCCESS_DEFINITION_BUY_TIER_EXCESS,
    HistoricalAnalysisConfig,
    ModelAttributionMeta,
    _build_observations,
    _filter_observations_for_cohort,
    _model_attribution,
    historical_analysis_summary_from_dict,
    run_historical_analysis,
)
from value_investor.model_weights import DEFAULT_HORIZON_DAYS, save_model_snapshot
from value_investor.research.document import ResearchDocument
from value_investor.research.store import ResearchStore
from value_investor.research.timeline import archive_revision


def _write_run_snapshot(
    history_dir: Path,
    *,
    stamp: str,
    run_at: str,
    prices: dict[str, float],
    signals: list[dict],
) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    payload = {"run_at": run_at, "prices": prices, "signals": signals}
    (history_dir / f"run_{stamp}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_historical_analysis_point_in_time_research_and_smoothing(tmp_path: Path):
    history = tmp_path / "history"
    _write_run_snapshot(
        history,
        stamp="20260601_070000",
        run_at="2026-06-01T07:00:00+00:00",
        prices={"AAA.L": 100.0, "BBB.L": 50.0, "^FTSE": 8000.0},
        signals=[
            {
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "conviction_score": 0.8,
                "data_quality_score": 0.8,
            },
            {
                "ticker": "BBB.L",
                "signal": "buy",
                "conviction_score": 0.7,
                "data_quality_score": 0.8,
            },
        ],
    )
    _write_run_snapshot(
        history,
        stamp="20260608_070000",
        run_at="2026-06-08T07:00:00+00:00",
        prices={"AAA.L": 110.0, "BBB.L": 45.0, "^FTSE": 8040.0},
        signals=[
            {
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "conviction_score": 0.8,
                "data_quality_score": 0.8,
            },
            {
                "ticker": "BBB.L",
                "signal": "buy",
                "conviction_score": 0.7,
                "data_quality_score": 0.8,
            },
        ],
    )
    _write_run_snapshot(
        history,
        stamp="20260615_070000",
        run_at="2026-06-15T07:00:00+00:00",
        prices={"AAA.L": 115.0, "BBB.L": 40.0, "^FTSE": 8080.0},
        signals=[
            {
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "conviction_score": 0.8,
                "data_quality_score": 0.8,
            },
            {
                "ticker": "BBB.L",
                "signal": "buy",
                "conviction_score": 0.7,
                "data_quality_score": 0.8,
            },
        ],
    )

    ticker_dir = tmp_path / "research" / "AAA.L"
    ticker_dir.mkdir(parents=True)
    archive_revision(
        ticker_dir,
        doc=ResearchDocument(
            ticker="AAA.L",
            name="Alpha",
            signal="strong_buy",
            version=1,
            created_at="2026-06-01T07:00:00+00:00",
            updated_at="2026-06-01T07:00:00+00:00",
            mode="initial",
            research_verdict="accumulate",
            research_confidence=0.72,
            memo_quality={"source_quality_score": 0.81, "grade": "strong"},
        ),
        run_at=datetime(2026, 6, 1, 7, 0, tzinfo=UTC),
        sources_as_of={},
    )
    archive_revision(
        ticker_dir,
        doc=ResearchDocument(
            ticker="AAA.L",
            name="Alpha",
            signal="strong_buy",
            version=2,
            created_at="2026-06-01T07:00:00+00:00",
            updated_at="2026-06-08T07:00:00+00:00",
            mode="weekly_update",
            research_verdict="pass",
        ),
        run_at=datetime(2026, 6, 8, 7, 0, tzinfo=UTC),
        sources_as_of={},
        delta={"verdict_changed": True},
    )

    model_results = pd.DataFrame(
        [
            {"ticker": "AAA.L", "model_id": "good_model", "passed": True, "score": 0.9},
            {"ticker": "BBB.L", "model_id": "good_model", "passed": True, "score": 0.2},
        ]
    )
    save_model_snapshot(
        tmp_path,
        run_at=datetime(2026, 6, 1, 7, 0, tzinfo=UTC),
        model_results=model_results,
    )

    summary = run_historical_analysis(
        tmp_path,
        config=HistoricalAnalysisConfig(
            max_years=3,
            horizon_days=(7,),
            smoothing_weeks=2,
            min_observations=1,
        ),
    )

    assert summary.has_results()
    strategies = {item.strategy: item for item in summary.strategy_horizons}
    assert "screen:strong_buy" in strategies
    assert "overlay:strong_buy" in strategies or "overlay:hold" in strategies
    assert summary.overlay_comparison
    assert summary.model_attribution
    assert summary.weekly_series

    snapshots = load_run_snapshots(tmp_path)
    observations = _build_observations(
        output_dir=tmp_path,
        snapshots=snapshots,
        horizon_days=7,
    )
    aaa_obs = [obs for obs in observations if obs.ticker == "AAA.L"]
    assert aaa_obs
    assert aaa_obs[0].source_quality_score == 0.81
    assert aaa_obs[0].research_confidence == 0.72

    store = ResearchStore(tmp_path)
    assert store.timeline_path("AAA.L").exists()

    assert summary.model_attribution_meta.primary_horizon_days == PRIMARY_ATTRIBUTION_HORIZON_DAYS
    assert summary.model_attribution_meta.primary_horizon_days == DEFAULT_HORIZON_DAYS
    assert summary.model_attribution_meta.success_definition == SUCCESS_DEFINITION_BUY_TIER_EXCESS
    assert summary.model_attribution_meta.cohort == COHORT_OVERLAY_BUY_TIER
    assert summary.model_attribution_meta.return_basis == RETURN_BASIS_EXCESS_VS_FTSE
    assert summary.model_attribution_meta.exit_join.get("status") == "not_computed"
    for row in summary.model_attribution:
        assert row.cohort == COHORT_OVERLAY_BUY_TIER
        assert row.return_basis == RETURN_BASIS_EXCESS_VS_FTSE
    assert summary.model_attribution_comparison
    for row in summary.model_attribution_comparison:
        assert row.cohort == COHORT_FULL_UNIVERSE
        assert row.return_basis == RETURN_BASIS_RAW


def _write_buy_tier_attribution_fixture(tmp_path: Path) -> None:
    """Four weekly runs so 28d exits exist; mix buy-tier and hold names."""
    history = tmp_path / "history"
    runs = [
        (
            "20260601_070000",
            "2026-06-01T07:00:00+00:00",
            {
                "AAA.L": 100.0,
                "BBB.L": 50.0,
                "HOLD.L": 80.0,
                "^FTSE": 8000.0,
            },
        ),
        (
            "20260608_070000",
            "2026-06-08T07:00:00+00:00",
            {
                "AAA.L": 105.0,
                "BBB.L": 48.0,
                "HOLD.L": 90.0,
                "^FTSE": 8200.0,
            },
        ),
        (
            "20260615_070000",
            "2026-06-15T07:00:00+00:00",
            {
                "AAA.L": 110.0,
                "BBB.L": 46.0,
                "HOLD.L": 95.0,
                "^FTSE": 8400.0,
            },
        ),
        (
            "20260629_070000",
            "2026-06-29T07:00:00+00:00",
            {
                "AAA.L": 120.0,
                "BBB.L": 40.0,
                "HOLD.L": 110.0,
                "^FTSE": 8600.0,
            },
        ),
    ]
    signals = [
        {
            "ticker": "AAA.L",
            "signal": "strong_buy",
            "adjusted_signal": "strong_buy",
            "conviction_score": 0.9,
            "data_quality_score": 0.8,
        },
        {
            "ticker": "BBB.L",
            "signal": "buy",
            "adjusted_signal": "buy",
            "conviction_score": 0.7,
            "data_quality_score": 0.8,
        },
        {
            "ticker": "HOLD.L",
            "signal": "hold",
            "adjusted_signal": "hold",
            "conviction_score": 0.2,
            "data_quality_score": 0.8,
        },
    ]
    for stamp, run_at, prices in runs:
        _write_run_snapshot(
            history,
            stamp=stamp,
            run_at=run_at,
            prices=prices,
            signals=signals,
        )

    # High score on AAA (beats market on excess), low on BBB (lags), mid on HOLD
    # (raw winner but hold — must be excluded from primary cohort).
    model_results = pd.DataFrame(
        [
            {"ticker": "AAA.L", "model_id": "alpha_model", "passed": True, "score": 0.95},
            {"ticker": "BBB.L", "model_id": "alpha_model", "passed": True, "score": 0.15},
            {"ticker": "HOLD.L", "model_id": "alpha_model", "passed": True, "score": 0.55},
        ]
    )
    for run_at in (
        datetime(2026, 6, 1, 7, 0, tzinfo=UTC),
        datetime(2026, 6, 8, 7, 0, tzinfo=UTC),
        datetime(2026, 6, 15, 7, 0, tzinfo=UTC),
    ):
        save_model_snapshot(tmp_path, run_at=run_at, model_results=model_results)


def test_model_attribution_buy_tier_excess_primary_path(tmp_path: Path):
    _write_buy_tier_attribution_fixture(tmp_path)

    summary = run_historical_analysis(
        tmp_path,
        config=HistoricalAnalysisConfig(
            max_years=3,
            horizon_days=(7, 28),
            smoothing_weeks=2,
            min_observations=1,
        ),
    )

    assert summary.model_attribution_meta.primary_horizon_days == 28
    assert summary.model_attribution_meta.aligned_with_weight_learning_horizon is True

    primary_28 = [
        row for row in summary.model_attribution if row.horizon_days == 28
    ]
    assert primary_28, "28d buy-tier excess attribution should populate"
    assert all(row.cohort == COHORT_OVERLAY_BUY_TIER for row in primary_28)
    assert all(row.return_basis == RETURN_BASIS_EXCESS_VS_FTSE for row in primary_28)
    assert all(row.observation_weeks >= 1 for row in primary_28)

    # HOLD.L is only in full-universe comparison samples (higher n).
    primary_n = primary_28[0].sample_count
    comparison_28 = [
        row
        for row in summary.model_attribution_comparison
        if row.horizon_days == 28 and row.model_id == "alpha_model"
    ]
    assert comparison_28
    assert comparison_28[0].cohort == COHORT_FULL_UNIVERSE
    assert comparison_28[0].return_basis == RETURN_BASIS_RAW
    assert comparison_28[0].sample_count > primary_n

    payload = summary.to_dict()
    assert payload["model_attribution_meta"]["success_definition"] == (
        SUCCESS_DEFINITION_BUY_TIER_EXCESS
    )
    assert payload["model_attribution_meta"]["exit_join"]["status"] == "not_computed"
    assert "join_keys" in payload["model_attribution_meta"]["exit_join"]

    restored = historical_analysis_summary_from_dict(payload)
    assert restored.model_attribution_meta.primary_horizon_days == 28
    assert restored.model_attribution[0].cohort == COHORT_OVERLAY_BUY_TIER


def test_model_attribution_excludes_non_buy_tier_from_primary(tmp_path: Path):
    _write_buy_tier_attribution_fixture(tmp_path)
    snapshots = load_run_snapshots(tmp_path)
    observations = _build_observations(
        output_dir=tmp_path,
        snapshots=snapshots,
        horizon_days=28,
    )
    buy_tier = _filter_observations_for_cohort(observations, COHORT_OVERLAY_BUY_TIER)
    full = _filter_observations_for_cohort(observations, COHORT_FULL_UNIVERSE)
    assert {obs.ticker for obs in buy_tier} <= {"AAA.L", "BBB.L"}
    assert "HOLD.L" in {obs.ticker for obs in full}
    assert "HOLD.L" not in {obs.ticker for obs in buy_tier}

    primary = _model_attribution(
        output_dir=tmp_path,
        observations=observations,
        horizon_days=28,
        smoothing_weeks=2,
        cohort=COHORT_OVERLAY_BUY_TIER,
        return_basis=RETURN_BASIS_EXCESS_VS_FTSE,
    )
    comparison = _model_attribution(
        output_dir=tmp_path,
        observations=observations,
        horizon_days=28,
        smoothing_weeks=2,
        cohort=COHORT_FULL_UNIVERSE,
        return_basis=RETURN_BASIS_RAW,
    )
    assert primary and comparison
    assert primary[0].sample_count < comparison[0].sample_count


def test_model_attribution_meta_from_legacy_payload():
    """Old summaries without meta/comparison still load with safe defaults."""
    legacy = {
        "run_count": 2,
        "window_start": "2026-06-01T07:00:00+00:00",
        "window_end": "2026-06-08T07:00:00+00:00",
        "max_years": 3,
        "smoothing_weeks": 4,
        "strategy_horizons": [],
        "model_attribution": [
            {
                "model_id": "legacy_model",
                "horizon_days": 7,
                "raw_correlation": 0.1,
                "smoothed_correlation": 0.1,
                "sample_count": 10,
            }
        ],
        "overlay_comparison": [],
        "weekly_series": [],
        "note": "",
    }
    summary = historical_analysis_summary_from_dict(legacy)
    assert summary.model_attribution[0].model_id == "legacy_model"
    assert summary.model_attribution[0].cohort == COHORT_OVERLAY_BUY_TIER
    assert summary.model_attribution_meta.primary_horizon_days == 28
    assert summary.model_attribution_comparison == []
    meta = ModelAttributionMeta.from_dict(None)
    assert meta.exit_join["planned_metric"] == "entry_score_quintile_vs_realized_return"
