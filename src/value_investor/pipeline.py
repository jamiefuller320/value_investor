"""End-to-end screening pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.constituents import fetch_ftse100_constituents
from value_investor.fetch import fetch_universe
from value_investor.scoring import evaluate_universe, summarize_by_ticker
from value_investor.signals import build_signals


@dataclass
class ScreenResult:
    run_at: datetime
    universe: pd.DataFrame
    model_results: pd.DataFrame
    signals: pd.DataFrame

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_at": self.run_at.isoformat(),
            "company_count": len(self.universe),
            "signals": self.signals[
                ["ticker", "name", "sector", "signal", "models_passed", "composite_score", "mean_model_score"]
            ].to_dict(orient="records"),
        }


def run_screen(*, limit: int | None = None) -> ScreenResult:
    """Fetch FTSE 100 data, run value models, return ranked signals."""
    constituents = fetch_ftse100_constituents()
    universe = fetch_universe(constituents, limit=limit)
    model_results = evaluate_universe(universe)
    summary = summarize_by_ticker(model_results)
    signals = build_signals(universe, model_results, summary)

    return ScreenResult(
        run_at=datetime.now(UTC),
        universe=universe,
        model_results=model_results,
        signals=signals,
    )


def write_outputs(result: ScreenResult, output_dir: Path) -> dict[str, Path]:
    """Write CSV and JSON artifacts for a screening run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.run_at.strftime("%Y%m%d_%H%M%S")

    paths = {
        "signals": output_dir / f"signals_{stamp}.csv",
        "model_results": output_dir / f"model_results_{stamp}.csv",
        "universe": output_dir / f"universe_{stamp}.csv",
        "summary": output_dir / f"summary_{stamp}.json",
    }

    result.signals.to_csv(paths["signals"], index=False)
    result.model_results.to_csv(paths["model_results"], index=False)
    result.universe.to_csv(paths["universe"], index=False)
    paths["summary"].write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    latest = output_dir / "latest_signals.csv"
    result.signals.to_csv(latest, index=False)
    paths["latest"] = latest

    latest_models = output_dir / "latest_model_results.csv"
    result.model_results.to_csv(latest_models, index=False)
    paths["latest_model_results"] = latest_models

    return paths
