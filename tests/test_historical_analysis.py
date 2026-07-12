"""Tests for point-in-time historical analysis engine."""

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.historical_analysis import (
    HistoricalAnalysisConfig,
    run_historical_analysis,
)
from value_investor.model_weights import save_model_snapshot
from value_investor.research.document import ResearchDocument
from value_investor.research.store import ResearchStore
from value_investor.research.timeline import archive_revision
import pandas as pd


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

    model_results = pd.DataFrame([
        {"ticker": "AAA.L", "model_id": "good_model", "passed": True, "score": 0.9},
        {"ticker": "BBB.L", "model_id": "good_model", "passed": True, "score": 0.2},
    ])
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

    store = ResearchStore(tmp_path)
    assert store.timeline_path("AAA.L").exists()
