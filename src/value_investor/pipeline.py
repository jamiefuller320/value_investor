"""End-to-end screening pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.backtest import (
    BacktestSummary,
    compute_backtest,
    load_run_snapshots,
    save_run_snapshot,
)
from value_investor.constituents import fetch_ftse100_constituents
from value_investor.data_quality import add_data_quality_scores
from value_investor.fetch import fetch_universe
from value_investor.run_diff import RunDiff, compute_run_diff
from value_investor.scoring import evaluate_universe, summarize_by_ticker
from value_investor.sector_scoring import add_sector_scores
from value_investor.signal_stability import (
    append_signal_history,
    enrich_signals_with_stability,
    load_signal_history,
)
from value_investor.signals import build_signals
from value_investor.simulator import SimulationSummary, run_simulation
from value_investor.technical_analysis import enrich_signals_with_technicals


@dataclass
class ScreenResult:
    run_at: datetime
    universe: pd.DataFrame
    model_results: pd.DataFrame
    signals: pd.DataFrame
    run_diff: RunDiff | None = None
    backtest: BacktestSummary | None = None
    simulation: SimulationSummary | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_at": self.run_at.isoformat(),
            "company_count": len(self.universe),
            "signals": self.signals[
                [
                    "ticker",
                    "name",
                    "sector",
                    "signal",
                    "models_passed",
                    "families_passed",
                    "composite_score",
                    "sector_composite_score",
                    "data_quality_score",
                    "conviction_score",
                    "weeks_at_signal",
                    "signal_trend",
                    "stability_label",
                    "timing_signal",
                    "timing_score",
                    "rsi_14",
                    "action_note",
                    "core_order",
                    "core_limit",
                    "tactical_limit",
                    "stop_loss",
                    "take_profit",
                    "trade_plan_summary",
                    "mean_model_score",
                ]
            ].to_dict(orient="records"),
        }
        if self.run_diff is not None:
            payload["run_diff"] = self.run_diff.to_dict()
        if self.backtest is not None:
            payload["backtest"] = self.backtest.to_dict()
        if self.simulation is not None:
            payload["simulation"] = self.simulation.to_dict()
        return payload


def run_screen(*, limit: int | None = None, output_dir: Path | None = None) -> ScreenResult:
    """Fetch FTSE 100 data, run value models, return ranked signals."""
    run_at = datetime.now(UTC)
    out_dir = output_dir or Path("output")
    constituents = fetch_ftse100_constituents()
    universe = fetch_universe(constituents, limit=limit)
    universe = add_data_quality_scores(universe)
    universe = add_sector_scores(universe)
    model_results = evaluate_universe(universe)
    summary = summarize_by_ticker(model_results)
    signals = build_signals(universe, model_results, summary)
    signals = enrich_signals_with_technicals(signals)

    history = load_signal_history(out_dir)
    signals = enrich_signals_with_stability(signals, history, run_at=run_at)

    sort_cols = [
        "signal_rank",
        "conviction_score",
        "composite_score",
        "sector_composite_score",
        "mean_model_score",
        "models_passed",
    ]
    present_cols = [c for c in sort_cols if c in signals.columns]
    signals = signals.sort_values(present_cols, ascending=[False] * len(present_cols))
    signals = signals.reset_index(drop=True)

    return ScreenResult(
        run_at=run_at,
        universe=universe,
        model_results=model_results,
        signals=signals,
    )


def write_outputs(result: ScreenResult, output_dir: Path) -> dict[str, Path]:
    """Write CSV and JSON artifacts for a screening run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.run_at.strftime("%Y%m%d_%H%M%S")

    latest = output_dir / "latest_signals.csv"
    previous_signals = pd.read_csv(latest) if latest.exists() else None

    paths: dict[str, Path] = {
        "signals": output_dir / f"signals_{stamp}.csv",
        "model_results": output_dir / f"model_results_{stamp}.csv",
        "universe": output_dir / f"universe_{stamp}.csv",
        "summary": output_dir / f"summary_{stamp}.json",
    }

    signals_out = result.signals.copy()
    signals_out["run_at"] = result.run_at.isoformat()
    signals_out.to_csv(paths["signals"], index=False)
    result.model_results.to_csv(paths["model_results"], index=False)
    result.universe.to_csv(paths["universe"], index=False)

    if previous_signals is not None:
        run_diff = compute_run_diff(previous_signals, signals_out)
        result.run_diff = run_diff
        diff_path = output_dir / "run_diff.json"
        diff_path.write_text(json.dumps(run_diff.to_dict(), indent=2), encoding="utf-8")
        paths["run_diff"] = diff_path

    snapshot_path = save_run_snapshot(output_dir, run_at=result.run_at, signals=signals_out)
    paths["snapshot"] = snapshot_path

    snapshots = load_run_snapshots(output_dir)
    result.backtest = compute_backtest(snapshots)
    backtest_path = output_dir / "backtest_summary.json"
    backtest_path.write_text(json.dumps(result.backtest.to_dict(), indent=2), encoding="utf-8")
    paths["backtest"] = backtest_path

    result.simulation = run_simulation(snapshots)
    simulation_path = output_dir / "simulation_summary.json"
    simulation_path.write_text(json.dumps(result.simulation.to_dict(), indent=2), encoding="utf-8")
    paths["simulation"] = simulation_path

    paths["summary"].write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    signals_out.to_csv(latest, index=False)
    paths["latest"] = latest

    latest_models = output_dir / "latest_model_results.csv"
    result.model_results.to_csv(latest_models, index=False)
    paths["latest_model_results"] = latest_models

    append_signal_history(output_dir, signals_out, run_at=result.run_at)
    paths["signal_history"] = output_dir / "signal_history.csv"

    return paths
