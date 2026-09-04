"""Tests for library screen-lite → paper shard reports adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.market_paper_adapter import (
    build_market_reports_bundle,
    load_library_screen_result,
    write_market_screen_bundle,
)


def _write_latest_artifacts(screen_dir: Path) -> None:
    screen_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "signal": "strong_buy",
                "composite_score": 0.91,
                "last_price": 180.0,
                "name": "Apple",
            }
        ]
    ).to_csv(screen_dir / "latest_signals.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "model_score": 0.9,
                "score": 0.9,
                "passed": True,
                "model_name": "value",
            }
        ]
    ).to_csv(
        screen_dir / "latest_model_results.csv",
        index=False,
    )
    write_json = __import__("value_investor.storage", fromlist=["write_json"]).write_json
    write_json(
        screen_dir / "latest_summary.json",
        {"market": "sp500", "run_at": datetime(2026, 8, 16, 12, 0, tzinfo=UTC).isoformat()},
        compact=False,
    )


def test_load_library_screen_result_defaults_conviction(tmp_path: Path):
    root = tmp_path / "library"
    screen_dir = root / "markets" / "sp500" / "screen"
    _write_latest_artifacts(screen_dir)
    result = load_library_screen_result(root, "sp500")
    assert result.market == "sp500"
    assert "conviction_score" in result.signals.columns
    assert float(result.signals.loc[0, "conviction_score"]) == 0.91


def test_build_market_reports_bundle_shape(tmp_path: Path):
    root = tmp_path / "library"
    screen_dir = root / "markets" / "sp500" / "screen"
    _write_latest_artifacts(screen_dir)
    bundle = build_market_reports_bundle(root, "sp500")
    assert bundle["meta"]["universe"] == "sp500"
    assert bundle["meta"]["shard"] is True
    assert bundle["meta"]["benchmark_ticker"] == "^GSPC"
    assert len(bundle["reports"]) >= 1


def test_build_market_reports_bundle_uses_sibling_home_memo(tmp_path: Path):
    root = tmp_path / "library"
    screen_dir = root / "markets" / "euro_depth" / "screen"
    _write_latest_artifacts(screen_dir)
    # Rename AAPL row is already there; write sibling memo for AAPL under nasdaq100.
    home = root / "markets" / "nasdaq100" / "screen" / "research" / "AAPL"
    home.mkdir(parents=True)
    write_json = __import__("value_investor.storage", fromlist=["write_json"]).write_json
    write_json(
        home / "research.json",
        {
            "ticker": "AAPL",
            "name": "Apple",
            "signal": "strong_buy",
            "version": 1,
            "created_at": "2026-07-01T00:00:00+00:00",
            "updated_at": "2026-07-01T00:00:00+00:00",
            "mode": "initial",
            "research_verdict": "accumulate",
            "research_confidence": 0.8,
        },
        compact=True,
    )
    (home / "research.md").write_text("# Apple\n", encoding="utf-8")
    bundle = build_market_reports_bundle(root, "euro_depth")
    report = bundle["reports"][0]
    assert report["ticker"] == "AAPL"
    assert report["research_verdict"] == "accumulate"


def test_write_market_screen_bundle(tmp_path: Path):
    root = tmp_path / "library"
    screen_dir = root / "markets" / "sp500" / "screen"
    _write_latest_artifacts(screen_dir)
    shard_root = tmp_path / "paper" / "markets" / "sp500"
    path = write_market_screen_bundle(root, "sp500", shard_root)
    assert path.exists()
    assert path.name == "screen_latest.json"
