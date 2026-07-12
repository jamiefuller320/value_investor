"""Adaptive per-model weights learned from archived screening history."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.backtest import (
    HISTORY_DIR,
    RunSnapshot,
    _find_exit_snapshot,
    _parse_run_at,
    load_run_snapshots,
)

logger = logging.getLogger(__name__)

MODEL_WEIGHTS_FILE = "model_weights.json"
DEFAULT_WEIGHT = 1.0
MIN_WEIGHT = 0.25
MAX_WEIGHT = 2.5
DEFAULT_HORIZON_DAYS = 28
DEFAULT_LEARNING_RATE = 0.2
MIN_SAMPLES_PER_MODEL = 8


@dataclass
class ModelWeightState:
    weights: dict[str, float]
    sample_count: int = 0
    horizon_days: int = DEFAULT_HORIZON_DAYS
    learning_rate: float = DEFAULT_LEARNING_RATE
    updated_at: str = ""
    note: str = ""
    model_samples: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": {k: round(v, 4) for k, v in sorted(self.weights.items())},
            "sample_count": self.sample_count,
            "horizon_days": self.horizon_days,
            "learning_rate": self.learning_rate,
            "updated_at": self.updated_at,
            "note": self.note,
            "model_samples": self.model_samples,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelWeightState:
        return cls(
            weights={str(k): float(v) for k, v in dict(data.get("weights") or {}).items()},
            sample_count=int(data.get("sample_count") or 0),
            horizon_days=int(data.get("horizon_days") or DEFAULT_HORIZON_DAYS),
            learning_rate=float(data.get("learning_rate") or DEFAULT_LEARNING_RATE),
            updated_at=str(data.get("updated_at") or ""),
            note=str(data.get("note", "")),
            model_samples={str(k): int(v) for k, v in dict(data.get("model_samples") or {}).items()},
        )


def default_weights(model_ids: list[str] | None = None) -> dict[str, float]:
    if not model_ids:
        from value_investor.models import ALL_MODELS

        model_ids = [model.id for model in ALL_MODELS]
    return {model_id: DEFAULT_WEIGHT for model_id in model_ids}


def load_model_weights(output_dir: Path) -> ModelWeightState:
    path = output_dir / MODEL_WEIGHTS_FILE
    if not path.exists():
        return ModelWeightState(
            weights=default_weights(),
            note="Using equal model weights until enough archived runs accumulate.",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ModelWeightState.from_dict(data)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("Could not load model weights: %s", exc)
        return ModelWeightState(weights=default_weights(), note="Invalid weights file; using defaults.")


def save_model_weights(output_dir: Path, state: ModelWeightState) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / MODEL_WEIGHTS_FILE
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    return path


def save_model_snapshot(
    output_dir: Path,
    *,
    run_at: datetime,
    model_results: pd.DataFrame,
) -> Path:
    """Persist per-model scores alongside a screening run for weight learning."""
    history_dir = output_dir / HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)

    cols = ["ticker", "model_id", "passed", "score"]
    payload = {
        "run_at": run_at.isoformat(),
        "models": model_results[cols].to_dict(orient="records"),
    }
    stamp = run_at.strftime("%Y%m%d_%H%M%S")
    path = history_dir / f"models_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _load_model_snapshots(output_dir: Path) -> dict[str, list[dict[str, Any]]]:
    history_dir = output_dir / HISTORY_DIR
    if not history_dir.exists():
        return {}

    by_run: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(history_dir.glob("models_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            run_at = str(data["run_at"])
            by_run[run_at] = list(data.get("models") or [])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Skipping corrupt model snapshot %s: %s", path, exc)
    return by_run


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < MIN_SAMPLES_PER_MODEL or len(xs) != len(ys):
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _forward_return(
    ticker: str,
    entry: RunSnapshot,
    exit_snap: RunSnapshot,
) -> float | None:
    p0 = entry.prices.get(ticker)
    p1 = exit_snap.prices.get(ticker)
    if p0 is None or p1 is None or p0 <= 0:
        return None
    return (p1 - p0) / p0


def _target_weight_from_correlation(correlation: float | None) -> float:
    if correlation is None:
        return DEFAULT_WEIGHT
    # Map correlation (-1..1) to weight around 1.0
    return max(MIN_WEIGHT, min(MAX_WEIGHT, DEFAULT_WEIGHT + correlation * 1.25))


def update_model_weights(
    output_dir: Path,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    learning_rate: float = DEFAULT_LEARNING_RATE,
) -> ModelWeightState:
    """
    Learn model weights from historical score → forward-return pairs.

    Uses exponential smoothing against prior weights so new data refines rather
    than whipsaws the ensemble.
    """
    previous = load_model_weights(output_dir)
    snapshots = load_run_snapshots(output_dir)
    model_snapshots = _load_model_snapshots(output_dir)

    if len(snapshots) < 2:
        return ModelWeightState(
            weights=previous.weights or default_weights(),
            sample_count=0,
            horizon_days=horizon_days,
            learning_rate=learning_rate,
            updated_at=datetime.now(UTC).isoformat(),
            note="Need at least 2 archived runs before model weights can adapt.",
        )

    scores_by_model: dict[str, list[float]] = {}
    returns_by_model: dict[str, list[float]] = {}
    total_pairs = 0

    for entry in snapshots[:-1]:
        exit_snap = _find_exit_snapshot(entry, snapshots, horizon_days)
        if exit_snap is None:
            continue

        model_rows = model_snapshots.get(entry.run_at)
        if not model_rows:
            continue

        returns_cache: dict[str, float] = {}
        for row in model_rows:
            ticker = str(row["ticker"])
            if ticker not in returns_cache:
                ret = _forward_return(ticker, entry, exit_snap)
                if ret is None:
                    continue
                returns_cache[ticker] = ret

            ret = returns_cache.get(ticker)
            if ret is None:
                continue

            model_id = str(row["model_id"])
            score = float(row.get("score") or 0)
            scores_by_model.setdefault(model_id, []).append(score)
            returns_by_model.setdefault(model_id, []).append(ret)
            total_pairs += 1

    all_model_ids = sorted(set(default_weights().keys()) | set(scores_by_model.keys()))
    new_weights: dict[str, float] = {}
    model_samples: dict[str, int] = {}

    for model_id in all_model_ids:
        prior = previous.weights.get(model_id, DEFAULT_WEIGHT)
        xs = scores_by_model.get(model_id, [])
        ys = returns_by_model.get(model_id, [])
        model_samples[model_id] = len(xs)

        target = _target_weight_from_correlation(_pearson(xs, ys))
        new_weights[model_id] = (1 - learning_rate) * prior + learning_rate * target

    note = (
        f"Updated from {total_pairs} score-return pairs across {len(snapshots)} runs "
        f"({horizon_days}d horizon)."
        if total_pairs
        else "No model snapshots matched archived runs yet."
    )

    state = ModelWeightState(
        weights=new_weights,
        sample_count=total_pairs,
        horizon_days=horizon_days,
        learning_rate=learning_rate,
        updated_at=datetime.now(UTC).isoformat(),
        note=note,
        model_samples=model_samples,
    )
    save_model_weights(output_dir, state)
    return state


def apply_weights_to_results(
    model_results: pd.DataFrame,
    weights: dict[str, float],
) -> pd.DataFrame:
    out = model_results.copy()
    out["model_weight"] = out["model_id"].map(weights).fillna(DEFAULT_WEIGHT)
    return out
