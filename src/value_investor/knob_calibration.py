"""Walk-forward knob calibration on rebalance logs and archives (observe-only)."""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.decision_review import LearningKnobs
from value_investor.paper_automation import (
    CONFIG_FILENAME,
    FUND_FILENAME,
    AutomationConfig,
    ensure_automated_fund,
    learning_track_dirs,
)
from value_investor.paper_fund import PaperFund
from value_investor.rebalance_log import (
    acted_log_entries,
    load_rebalance_log,
    replay_counterfactual_from_archive,
    replay_counterfactual_from_log,
)
from value_investor.storage import read_json, write_json

KNOB_CALIBRATION_PRIORS_FILENAME = "knob_calibration_priors.json"
DEFAULT_COST_DRAG_LAMBDA = 0.5
DEFAULT_STABILITY_PENALTY = 0.25
MIN_ACTED_FOR_CALIBRATION = 2
MIN_FOLDS_FOR_WALK_FORWARD = 2
MIN_ACTED_FOR_CONFIDENT_PRIORS = 4
TOP_CANDIDATES_KEPT = 20


@dataclass(frozen=True)
class KnobGridAxis:
    name: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class KnobCandidate:
    max_positions: int
    skip_timing_wait: bool
    min_conviction: float
    sector_cap: float
    exit_confirm_screens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "max_positions": int(self.max_positions),
            "skip_timing_wait": bool(self.skip_timing_wait),
            "min_conviction": round(float(self.min_conviction), 4),
            "sector_cap": round(float(self.sector_cap), 4),
        }
        if self.exit_confirm_screens is not None:
            payload["exit_confirm_screens"] = int(self.exit_confirm_screens)
        return payload

    @classmethod
    def from_learning_knobs(
        cls,
        knobs: LearningKnobs,
        *,
        exit_confirm_screens: int | None = None,
    ) -> KnobCandidate:
        return cls(
            max_positions=int(knobs.max_positions),
            skip_timing_wait=bool(knobs.skip_timing_wait),
            min_conviction=float(knobs.min_conviction),
            sector_cap=float(knobs.sector_cap),
            exit_confirm_screens=exit_confirm_screens,
        )


def default_grid_axes(*, include_churn_knobs: bool = False) -> tuple[KnobGridAxis, ...]:
    axes: tuple[KnobGridAxis, ...] = (
        KnobGridAxis("max_positions", (3, 4, 5)),
        KnobGridAxis("min_conviction", (0.0, 0.15, 0.25, 0.35)),
        KnobGridAxis("sector_cap", (0.2, 0.25, 0.3)),
        KnobGridAxis("skip_timing_wait", (True,)),
    )
    if include_churn_knobs:
        axes = axes + (KnobGridAxis("exit_confirm_screens", (1, 2)),)
    return axes


def parse_grid_values(raw: str, *, kind: str = "float") -> tuple[Any, ...]:
    parts = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not parts:
        return ()
    if kind == "int":
        return tuple(int(part) for part in parts)
    if kind == "bool":
        return tuple(part.lower() in {"1", "true", "yes"} for part in parts)
    return tuple(float(part) for part in parts)


def grid_axes_from_cli(
    *,
    max_positions: str | None = None,
    min_conviction: str | None = None,
    sector_cap: str | None = None,
    skip_timing_wait: str | None = None,
    exit_confirm_screens: str | None = None,
    include_churn_knobs: bool = False,
) -> tuple[KnobGridAxis, ...]:
    if not any(
        value is not None
        for value in (
            max_positions,
            min_conviction,
            sector_cap,
            skip_timing_wait,
            exit_confirm_screens,
        )
    ):
        return default_grid_axes(include_churn_knobs=include_churn_knobs)

    axes: list[KnobGridAxis] = []
    defaults = default_grid_axes(include_churn_knobs=include_churn_knobs)
    if max_positions:
        axes.append(KnobGridAxis("max_positions", parse_grid_values(max_positions, kind="int")))
    else:
        axes.append(KnobGridAxis("max_positions", defaults[0].values))
    if min_conviction:
        axes.append(KnobGridAxis("min_conviction", parse_grid_values(min_conviction, kind="float")))
    else:
        axes.append(KnobGridAxis("min_conviction", defaults[1].values))
    if sector_cap:
        axes.append(KnobGridAxis("sector_cap", parse_grid_values(sector_cap, kind="float")))
    else:
        axes.append(KnobGridAxis("sector_cap", defaults[2].values))
    if skip_timing_wait:
        axes.append(
            KnobGridAxis(
                "skip_timing_wait",
                parse_grid_values(skip_timing_wait, kind="bool"),
            )
        )
    else:
        axes.append(KnobGridAxis("skip_timing_wait", (True,)))
    if include_churn_knobs or exit_confirm_screens:
        values = (
            parse_grid_values(exit_confirm_screens, kind="int") if exit_confirm_screens else (1, 2)
        )
        axes.append(KnobGridAxis("exit_confirm_screens", values))
    return tuple(axes)


def iter_grid_candidates(axes: Iterable[KnobGridAxis]) -> list[KnobCandidate]:
    axis_list = list(axes)
    names = [axis.name for axis in axis_list]
    value_lists = [axis.values for axis in axis_list]
    candidates: list[KnobCandidate] = []
    for combo in itertools.product(*value_lists):
        kwargs = dict(zip(names, combo, strict=True))
        candidates.append(KnobCandidate(**kwargs))
    return candidates


def walk_forward_fold_ranges(n_entries: int, n_folds: int) -> list[tuple[int, int]]:
    """Chronological [start, end) index ranges for walk-forward test folds."""
    if n_entries < MIN_ACTED_FOR_CALIBRATION:
        return []
    fold_count = max(MIN_FOLDS_FOR_WALK_FORWARD, min(int(n_folds), n_entries))
    chunk = n_entries / fold_count
    boundaries = [0]
    for index in range(1, fold_count):
        boundaries.append(int(round(index * chunk)))
    boundaries.append(n_entries)
    for index in range(1, len(boundaries)):
        if boundaries[index] <= boundaries[index - 1]:
            boundaries[index] = min(boundaries[index - 1] + 1, n_entries)
    boundaries[-1] = n_entries
    return [
        (boundaries[index], boundaries[index + 1])
        for index in range(len(boundaries) - 1)
        if boundaries[index + 1] > boundaries[index]
    ]


def fold_fitness(
    replay: dict[str, Any],
    *,
    cost_drag_lambda: float = DEFAULT_COST_DRAG_LAMBDA,
) -> float:
    cost_drag = float(replay.get("simulated_cost_drag") or 0.0)
    if replay.get("return_delta_vs_actual") is not None:
        base = float(replay["return_delta_vs_actual"])
    else:
        base = float(replay.get("simulated_return") or 0.0)
    return base - cost_drag_lambda * cost_drag


def _slim_replay(replay: dict[str, Any] | None) -> dict[str, Any] | None:
    if not replay:
        return None
    keys = (
        "scope",
        "simulated_return",
        "simulated_cost_drag",
        "simulated_trade_count",
        "return_delta_vs_actual",
        "cost_drag_delta_vs_actual",
        "log_entries_replayed",
        "archive_passes_replayed",
    )
    return {key: replay[key] for key in keys if key in replay}


def _replay_candidate_on_entries(
    entries: list[dict[str, Any]],
    candidate: KnobCandidate,
    *,
    actual_fund: PaperFund | None,
    use_adjusted_signal: bool | None,
    require_research_accumulate: bool | None,
) -> dict[str, Any] | None:
    kwargs: dict[str, Any] = {
        "max_positions": candidate.max_positions,
        "skip_timing_wait": candidate.skip_timing_wait,
        "min_conviction": candidate.min_conviction,
        "sector_cap": candidate.sector_cap,
        "use_adjusted_signal": use_adjusted_signal,
        "require_research_accumulate": require_research_accumulate,
        "actual_fund": actual_fund,
    }
    if candidate.exit_confirm_screens is not None:
        kwargs["exit_confirm_screens"] = candidate.exit_confirm_screens
    return replay_counterfactual_from_log(entries, **kwargs)


def score_candidate_walk_forward(
    acted: list[dict[str, Any]],
    candidate: KnobCandidate,
    *,
    n_folds: int,
    cost_drag_lambda: float,
    stability_penalty: float,
    actual_fund: PaperFund | None,
    use_adjusted_signal: bool | None,
    require_research_accumulate: bool | None,
) -> dict[str, Any] | None:
    if len(acted) < MIN_ACTED_FOR_CALIBRATION:
        return None

    fold_scores: list[dict[str, Any]] = []
    for start, end in walk_forward_fold_ranges(len(acted), n_folds):
        slice_entries = acted[start:end]
        replay = _replay_candidate_on_entries(
            slice_entries,
            candidate,
            actual_fund=actual_fund,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
        )
        if replay is None:
            continue
        fitness = fold_fitness(replay, cost_drag_lambda=cost_drag_lambda)
        fold_scores.append(
            {
                "fold_start": start,
                "fold_end": end,
                "fitness": round(fitness, 4),
                "simulated_return": replay.get("simulated_return"),
                "simulated_cost_drag": replay.get("simulated_cost_drag"),
                "log_entries_replayed": replay.get("log_entries_replayed"),
            }
        )
    if not fold_scores:
        return None

    fitnesses = [float(row["fitness"]) for row in fold_scores]
    mean_fitness = sum(fitnesses) / len(fitnesses)
    if len(fitnesses) > 1:
        variance = sum((value - mean_fitness) ** 2 for value in fitnesses) / len(fitnesses)
        stability = math.sqrt(variance)
    else:
        stability = 0.0
    composite = mean_fitness - stability_penalty * stability
    return {
        "fold_scores": fold_scores,
        "mean_fitness": round(mean_fitness, 4),
        "fold_stability": round(stability, 4),
        "composite_score": round(composite, 4),
    }


def _prior_confidence(
    *,
    acted_count: int,
    recommended_score: float | None,
    current_score: float | None,
    fold_stability: float | None,
) -> str:
    if acted_count < MIN_ACTED_FOR_CALIBRATION or recommended_score is None:
        return "insufficient"
    if acted_count < MIN_ACTED_FOR_CONFIDENT_PRIORS:
        return "low"
    uplift = 0.0 if current_score is None else recommended_score - current_score
    stability = float(fold_stability or 0.0)
    if acted_count >= 8 and uplift >= 0.03 and stability <= 0.05:
        return "high"
    if uplift >= 0.01:
        return "medium"
    return "low"


def _build_recommended_prior(
    recommended: dict[str, Any] | None,
    current: KnobCandidate,
    *,
    confidence: str,
    current_score: float | None,
) -> dict[str, Any] | None:
    if recommended is None:
        return None
    recommended_knobs = dict(recommended.get("knobs") or {})
    changed = {
        key: value
        for key, value in recommended_knobs.items()
        if current.to_dict().get(key) != value
    }
    return {
        "knobs": recommended_knobs,
        "composite_score": recommended.get("composite_score"),
        "confidence": confidence,
        "changed_vs_current": changed,
        "fitness_delta_vs_current": (
            None
            if current_score is None
            else round(float(recommended["composite_score"]) - current_score, 4)
        ),
        "rationale": (
            "Top walk-forward composite score on rebalance-log replay. "
            "Seed config.json / decision-review probes manually; do not auto-apply."
        ),
    }


def calibrate_track(
    track_dir: Path,
    *,
    axes: tuple[KnobGridAxis, ...] | None = None,
    include_churn_knobs: bool = False,
    n_folds: int = 3,
    cost_drag_lambda: float = DEFAULT_COST_DRAG_LAMBDA,
    stability_penalty: float = DEFAULT_STABILITY_PENALTY,
    archive_dir: Path | None = None,
    fetch_prices: bool = False,
) -> dict[str, Any]:
    """Grid-search knob combinations with walk-forward scoring on rebalance logs."""
    track_dir = Path(track_dir)
    entries = load_rebalance_log(track_dir)
    acted = acted_log_entries(entries)

    config_path = track_dir / CONFIG_FILENAME
    fund_path = track_dir / FUND_FILENAME
    if config_path.exists():
        config = AutomationConfig.from_dict(read_json(config_path))
    else:
        config = AutomationConfig()
    fund = ensure_automated_fund(fund_path, config) if fund_path.exists() else None

    current_knobs = LearningKnobs.from_config(config)
    selection = config.selection_kwargs()
    current_candidate = KnobCandidate.from_learning_knobs(
        current_knobs,
        exit_confirm_screens=int(selection.get("exit_confirm_screens") or 2)
        if include_churn_knobs
        else None,
    )

    grid_axes = axes or default_grid_axes(include_churn_knobs=include_churn_knobs)
    candidates = iter_grid_candidates(grid_axes)
    use_adjusted_signal = bool(config.use_adjusted_signal)
    require_research_accumulate = bool(config.require_research_accumulate)

    warnings: list[str] = []
    if any(entry.get("bootstrapped") for entry in acted):
        warnings.append(
            "rebalance_log contains bootstrapped entries (L113 PIT caveat for AI gates)"
        )
    if use_adjusted_signal or require_research_accumulate:
        warnings.append(
            "AI overlay gates fixed to track config — not swept until L113 PIT bootstrap"
        )
    if len(acted) < MIN_ACTED_FOR_CONFIDENT_PRIORS:
        warnings.append(f"only {len(acted)} acted log entries — priors are low confidence")

    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        walk_forward = score_candidate_walk_forward(
            acted,
            candidate,
            n_folds=n_folds,
            cost_drag_lambda=cost_drag_lambda,
            stability_penalty=stability_penalty,
            actual_fund=fund,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
        )
        full_window = _replay_candidate_on_entries(
            acted,
            candidate,
            actual_fund=fund,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
        )
        archive = replay_counterfactual_from_archive(
            track_dir,
            max_positions=candidate.max_positions,
            skip_timing_wait=candidate.skip_timing_wait,
            min_conviction=candidate.min_conviction,
            sector_cap=candidate.sector_cap,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
            archive_dir=archive_dir,
            fetch_prices=fetch_prices,
            actual_fund=fund,
        )
        if walk_forward is None and full_window is None and archive is None:
            continue
        if walk_forward is not None:
            composite_score = float(walk_forward["composite_score"])
        elif full_window is not None:
            composite_score = fold_fitness(full_window, cost_drag_lambda=cost_drag_lambda)
        elif archive is not None:
            composite_score = fold_fitness(archive, cost_drag_lambda=cost_drag_lambda)
        else:
            composite_score = -999.0
        scored.append(
            {
                "knobs": candidate.to_dict(),
                "composite_score": round(composite_score, 4),
                "walk_forward": walk_forward,
                "full_window_log_replay": _slim_replay(full_window),
                "archive_replay": _slim_replay(archive),
            }
        )

    scored.sort(key=lambda row: float(row["composite_score"]), reverse=True)
    for rank, row in enumerate(scored[:TOP_CANDIDATES_KEPT], start=1):
        row["rank"] = rank
    scored = scored[:TOP_CANDIDATES_KEPT]

    current_walk_forward = score_candidate_walk_forward(
        acted,
        current_candidate,
        n_folds=n_folds,
        cost_drag_lambda=cost_drag_lambda,
        stability_penalty=stability_penalty,
        actual_fund=fund,
        use_adjusted_signal=use_adjusted_signal,
        require_research_accumulate=require_research_accumulate,
    )
    current_score = float(current_walk_forward["composite_score"]) if current_walk_forward else None

    top = scored[0] if scored else None
    confidence = _prior_confidence(
        acted_count=len(acted),
        recommended_score=float(top["composite_score"]) if top else None,
        current_score=current_score,
        fold_stability=(
            float((top.get("walk_forward") or {}).get("fold_stability") or 0.0) if top else None
        ),
    )

    return {
        "scope": "knob_calibration",
        "observe_only": True,
        "calibrated_at": datetime.now(UTC).isoformat(),
        "track_id": str(config.track_id or track_dir.name or "rules"),
        "track_label": str(config.track_label or ""),
        "readiness": {
            "acted_entries": len(acted),
            "walk_forward_folds": len(walk_forward_fold_ranges(len(acted), n_folds)),
            "grid_size": len(candidates),
            "ready_for_priors": bool(scored and len(acted) >= MIN_ACTED_FOR_CALIBRATION),
            "warnings": warnings,
        },
        "current_knobs": current_candidate.to_dict(),
        "current_score": current_score,
        "search_space": {axis.name: list(axis.values) for axis in grid_axes},
        "cost_drag_lambda": cost_drag_lambda,
        "stability_penalty": stability_penalty,
        "candidates_ranked": scored,
        "recommended_prior": _build_recommended_prior(
            top,
            current_candidate,
            confidence=confidence,
            current_score=current_score,
        ),
        "limitations": (
            "Observe-only walk-forward calibration on rebalance_log replay. "
            "Does not auto-apply knobs. Full archive P&L needs thicker weekly screens (L111). "
            "Promote priors via manual config.json edit or paper_knobs experiment."
        ),
    }


def calibrate_learning_tracks(
    paper_root: Path,
    *,
    track_ids: tuple[str, ...] = ("rules", "ai_judgment"),
    **kwargs: Any,
) -> dict[str, Any]:
    paper_root = Path(paper_root)
    dirs = learning_track_dirs(paper_root)
    tracks: dict[str, Any] = {}
    for track_id in track_ids:
        track_dir = dirs.get(track_id)
        if track_dir is None or not track_dir.exists():
            continue
        result = calibrate_track(track_dir, **kwargs)
        if result.get("readiness", {}).get("acted_entries", 0) > 0 or result.get(
            "candidates_ranked"
        ):
            tracks[track_id] = result
    return {
        "scope": "knob_calibration_multi",
        "observe_only": True,
        "calibrated_at": datetime.now(UTC).isoformat(),
        "tracks": tracks,
        "limitations": (
            "Observe-only multi-track knob calibration. Human gate required before "
            "seeding live config.json or decision-review starting points."
        ),
    }


def write_knob_calibration_priors(
    paper_root: Path,
    payload: dict[str, Any],
) -> Path:
    paper_root = Path(paper_root)
    path = paper_root / KNOB_CALIBRATION_PRIORS_FILENAME
    write_json(path, payload, compact=False)
    return path
