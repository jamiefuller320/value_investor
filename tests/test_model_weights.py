"""Tests for adaptive model weight learning."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.model_weights import (
    load_model_weights,
    save_model_snapshot,
    update_model_weights,
)
from value_investor.scoring import summarize_by_ticker


def test_summarize_by_ticker_applies_weights():
    model_results = pd.DataFrame([
        {"ticker": "AAA.L", "model_id": "model_a", "passed": True, "score": 1.0},
        {"ticker": "AAA.L", "model_id": "model_b", "passed": False, "score": 0.0},
    ])
    summary = summarize_by_ticker(model_results, weights={"model_a": 2.0, "model_b": 0.5})
    row = summary.iloc[0]
    assert row["mean_model_score"] == 0.5
    assert row["weighted_model_score"] > 0.5


def test_update_model_weights_from_archived_history(tmp_path: Path):
    run_at_1 = "2026-06-01T07:00:00+00:00"
    run_at_2 = "2026-06-29T07:00:00+00:00"
    tickers = [f"T{i:02d}.L" for i in range(10)]

    prices_1 = {ticker: 100.0 + i for i, ticker in enumerate(tickers)}
    prices_2 = {
        ticker: prices_1[ticker] * (1.05 + i * 0.01) for i, ticker in enumerate(tickers)
    }
    prices_1["^FTSE"] = 8000.0
    prices_2["^FTSE"] = 8040.0

    history_dir = tmp_path / "history"
    history_dir.mkdir(parents=True)

    signals = [
        {"ticker": ticker, "signal": "strong_buy", "conviction_score": 0.8, "data_quality_score": 0.8}
        for ticker in tickers
    ]
    (history_dir / "run_20260601_070000.json").write_text(
        json.dumps({"run_at": run_at_1, "prices": prices_1, "signals": signals})
    )
    (history_dir / "run_20260629_070000.json").write_text(
        json.dumps({"run_at": run_at_2, "prices": prices_2, "signals": signals})
    )

    model_rows: list[dict] = []
    for i, ticker in enumerate(tickers):
        aligned_score = i / 9
        inverse_score = 1.0 - aligned_score
        model_rows.append(
            {"ticker": ticker, "model_id": "aligned_model", "passed": aligned_score > 0.5, "score": aligned_score}
        )
        model_rows.append(
            {"ticker": ticker, "model_id": "inverse_model", "passed": inverse_score > 0.5, "score": inverse_score}
        )

    save_model_snapshot(
        tmp_path,
        run_at=datetime.fromisoformat(run_at_1),
        model_results=pd.DataFrame(model_rows),
    )

    state = update_model_weights(tmp_path, horizon_days=7, learning_rate=0.5)
    assert state.sample_count >= 16
    assert state.weights["aligned_model"] > state.weights["inverse_model"]
    reloaded = load_model_weights(tmp_path)
    assert reloaded.weights["aligned_model"] > reloaded.weights["inverse_model"]
