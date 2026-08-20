"""Walk-forward knob calibration on rebalance logs and archives (observe-only)."""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.cohort_selection_fitness import (
    DEFAULT_COHORT_FITNESS_WEIGHT,
    MIN_SCORE_GAP_FOR_PRIOR,
    blend_calibration_score,
    cohort_walk_forward_score,
    discover_knob_axis_discriminability,
    score_cohort_selection,
    score_gap_vs_runner_up,
)
from value_investor.decision_review import LearningKnobs
from value_investor.paper_automation import (
    AI_JUDGMENT_CALIBRATED_TRACK_ID,
    AI_JUDGMENT_TRACK_ID,
    CONFIG_FILENAME,
    FUND_FILENAME,
    AutomationConfig,
    default_ai_judgment_config,
    ensure_automated_fund,
    ensure_learning_track_configs,
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
CALIBRATION_PROVENANCE_FILENAME = "calibration_provenance.json"
DEFAULT_COST_DRAG_LAMBDA = 0.5
DEFAULT_STABILITY_PENALTY = 0.25
MIN_ACTED_FOR_CALIBRATION = 2
MIN_FOLDS_FOR_WALK_FORWARD = 2
MIN_ACTED_FOR_CONFIDENT_PRIORS = 4
MIN_ACTED_FOR_SHADOW_BOOTSTRAP = 8
MIN_ACTED_FOR_SHADOW_BOOTSTRAP_IDEAL = 12
TOP_CANDIDATES_KEPT = 20
DEFAULT_BOOTSTRAP_TOP_N = 3
RANKING_WALK_FORWARD = "walk_forward"
RANKING_FULL_PERIOD = "full_period_retrospective"
RANKING_BLENDED = "blended"
VALID_RANKING_MODES = frozenset(
    {RANKING_WALK_FORWARD, RANKING_FULL_PERIOD, RANKING_BLENDED}
)
BLENDED_FULL_PERIOD_WEIGHT = 0.5


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
    score_gap: float | None = None,
    cohort_selection: dict[str, Any] | None = None,
    use_blended_score: bool = False,
) -> dict[str, Any] | None:
    if recommended is None:
        return None
    recommended_knobs = dict(recommended.get("knobs") or {})
    changed = {
        key: value
        for key, value in recommended_knobs.items()
        if current.to_dict().get(key) != value
    }
    score_key = "blended_score" if use_blended_score else "composite_score"
    recommended_score = recommended.get(score_key) or recommended.get("composite_score")
    rationale = (
        "Top walk-forward blended score (portfolio replay + cohort-selection fitness). "
        "Seed config.json / shadow track manually; do not auto-apply."
        if use_blended_score
        else (
            "Top walk-forward composite score on rebalance-log replay. "
            "Seed config.json / decision-review probes manually; do not auto-apply."
        )
    )
    if score_gap is not None and score_gap < MIN_SCORE_GAP_FOR_PRIOR:
        rationale += (
            f" Warning: score gap vs runner-up ({score_gap}) is below "
            f"{MIN_SCORE_GAP_FOR_PRIOR} — weak discrimination."
        )
    return {
        "knobs": recommended_knobs,
        "composite_score": recommended.get("composite_score"),
        "blended_score": recommended.get("blended_score"),
        "portfolio_score": recommended.get("portfolio_score"),
        "confidence": confidence,
        "changed_vs_current": changed,
        "score_gap_vs_runner_up": score_gap,
        "cohort_selection": cohort_selection,
        "fitness_delta_vs_current": (
            None
            if current_score is None or recommended_score is None
            else round(float(recommended_score) - current_score, 4)
        ),
        "rationale": rationale,
    }


def _cohort_kwargs(
    candidate: KnobCandidate,
    *,
    use_adjusted_signal: bool | None,
    require_research_accumulate: bool | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "max_positions": candidate.max_positions,
        "skip_timing_wait": candidate.skip_timing_wait,
        "min_conviction": candidate.min_conviction,
        "sector_cap": candidate.sector_cap,
        "use_adjusted_signal": use_adjusted_signal,
        "require_research_accumulate": require_research_accumulate,
    }
    if candidate.exit_confirm_screens is not None:
        kwargs["exit_confirm_screens"] = candidate.exit_confirm_screens
    return kwargs


def _slim_cohort(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary:
        return None
    keys = (
        "cohort_hit_rate",
        "cohort_mean_forward_return",
        "selection_spread",
        "new_buy_hit_rate",
        "cohort_fitness",
        "selected_slots",
        "rejected_slots",
    )
    return {key: summary[key] for key in keys if key in summary}


def calibrated_shadow_track_id(rank: int) -> str:
    """Stable track id for competing calibrated shadows (rank 1 keeps legacy id)."""
    if int(rank) <= 1:
        return AI_JUDGMENT_CALIBRATED_TRACK_ID
    return f"{AI_JUDGMENT_CALIBRATED_TRACK_ID}_r{int(rank)}"


def calibrated_shadow_subdir(rank: int) -> str:
    if int(rank) <= 1:
        return "ai_judgment_calibrated"
    return f"ai_judgment_calibrated_r{int(rank)}"


def discover_calibration_shadow_ranks(paper_root: Path) -> list[int]:
    """Return ranks of existing calibrated shadow dirs under paper_root."""
    root = Path(paper_root)
    ranks: list[int] = []
    primary = root / calibrated_shadow_subdir(1)
    if (primary / CONFIG_FILENAME).exists():
        ranks.append(1)
    for path in sorted(root.glob("ai_judgment_calibrated_r*")):
        if not path.is_dir() or not (path / CONFIG_FILENAME).exists():
            continue
        suffix = path.name.removeprefix("ai_judgment_calibrated_r")
        if suffix.isdigit():
            ranks.append(int(suffix))
    return sorted(set(ranks))


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
    use_cohort_fitness: bool | None = None,
    cohort_weight: float = DEFAULT_COHORT_FITNESS_WEIGHT,
    ranking_mode: str = RANKING_WALK_FORWARD,
    bootstrap_top_n: int = DEFAULT_BOOTSTRAP_TOP_N,
    winner_loser_top_k: int = 5,
    winner_loser_bottom_k: int = 5,
) -> dict[str, Any]:
    """Grid-search knob combinations with walk-forward / full-period scoring."""
    from value_investor.knob_retrospective import score_full_period_retrospective

    mode = str(ranking_mode or RANKING_WALK_FORWARD).strip().lower()
    if mode not in VALID_RANKING_MODES:
        raise ValueError(
            f"ranking_mode must be one of {sorted(VALID_RANKING_MODES)}; got {ranking_mode!r}"
        )

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
    if use_cohort_fitness is None:
        use_cohort_fitness = (
            str(config.track_id or "") in {AI_JUDGMENT_TRACK_ID, AI_JUDGMENT_CALIBRATED_TRACK_ID}
            or use_adjusted_signal
        )

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
    if len(acted) < MIN_ACTED_FOR_SHADOW_BOOTSTRAP:
        warnings.append(
            f"only {len(acted)} acted log entries — shadow bootstrap prefers ≥"
            f"{MIN_ACTED_FOR_SHADOW_BOOTSTRAP} (ideal ≥{MIN_ACTED_FOR_SHADOW_BOOTSTRAP_IDEAL})"
        )
    if mode != RANKING_WALK_FORWARD:
        warnings.append(
            f"ranking_mode={mode} — bootstrap priors ranked on full-period retrospective "
            "(observe-only; does not auto-apply live knobs)"
        )
    if use_cohort_fitness:
        warnings.append(
            "cohort-selection fitness enabled — ranking blends portfolio replay with "
            f"name-level forward outcomes (weight={cohort_weight:.2f})"
        )

    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        cohort_kwargs = _cohort_kwargs(
            candidate,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
        )
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
        full_period = score_full_period_retrospective(
            acted,
            candidate,
            actual_fund=fund,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
            cost_drag_lambda=cost_drag_lambda,
            use_cohort_fitness=use_cohort_fitness,
            top_k=winner_loser_top_k,
            bottom_k=winner_loser_bottom_k,
        )
        if (
            walk_forward is None
            and full_window is None
            and archive is None
            and full_period is None
        ):
            continue
        if walk_forward is not None:
            portfolio_score = float(walk_forward["composite_score"])
        elif full_window is not None:
            portfolio_score = fold_fitness(full_window, cost_drag_lambda=cost_drag_lambda)
        elif archive is not None:
            portfolio_score = fold_fitness(archive, cost_drag_lambda=cost_drag_lambda)
        else:
            portfolio_score = -999.0

        cohort_summary = None
        cohort_wf = None
        if use_cohort_fitness:
            cohort_wf = cohort_walk_forward_score(
                acted,
                n_folds=n_folds,
                stability_penalty=stability_penalty,
                **cohort_kwargs,
            )
            cohort_summary = score_cohort_selection(acted, **cohort_kwargs)
            cohort_score = (
                float(cohort_wf["composite_score"])
                if cohort_wf is not None
                else float(cohort_summary.get("cohort_fitness") or -999.0)
            )
            blended_score = blend_calibration_score(
                portfolio_score,
                cohort_score,
                cohort_weight=cohort_weight,
            )
        else:
            cohort_score = None
            blended_score = portfolio_score

        wf_rank_score = blended_score if use_cohort_fitness else portfolio_score
        full_period_score = (
            float(full_period["full_period_score"]) if full_period is not None else wf_rank_score
        )
        if mode == RANKING_FULL_PERIOD:
            rank_score = full_period_score
        elif mode == RANKING_BLENDED:
            rank_score = (
                (1.0 - BLENDED_FULL_PERIOD_WEIGHT) * float(wf_rank_score)
                + BLENDED_FULL_PERIOD_WEIGHT * float(full_period_score)
            )
        else:
            rank_score = wf_rank_score

        scored.append(
            {
                "knobs": candidate.to_dict(),
                "composite_score": round(portfolio_score, 4),
                "portfolio_score": round(portfolio_score, 4),
                "cohort_score": round(cohort_score, 4) if cohort_score is not None else None,
                "blended_score": round(blended_score, 4),
                "full_period_score": round(full_period_score, 4),
                "walk_forward": walk_forward,
                "cohort_walk_forward": cohort_wf,
                "cohort_selection": _slim_cohort(cohort_summary),
                "full_window_log_replay": _slim_replay(full_window),
                "archive_replay": _slim_replay(archive),
                "full_period_retrospective": full_period,
                "winner_loser": (full_period or {}).get("winner_loser"),
                "_rank_score": rank_score,
            }
        )

    scored.sort(key=lambda row: float(row["_rank_score"]), reverse=True)
    for row in scored:
        row.pop("_rank_score", None)
    for rank, row in enumerate(scored[:TOP_CANDIDATES_KEPT], start=1):
        row["rank"] = rank
    scored = scored[:TOP_CANDIDATES_KEPT]

    if mode == RANKING_FULL_PERIOD:
        score_key = "full_period_score"
    elif mode == RANKING_BLENDED:
        score_key = "full_period_score" if use_cohort_fitness else "full_period_score"
    else:
        score_key = "blended_score" if use_cohort_fitness else "composite_score"
    if mode == RANKING_BLENDED:
        # Prefer explicit blended key when present on rows.
        for row in scored:
            row["blended_full_period_score"] = round(
                (1.0 - BLENDED_FULL_PERIOD_WEIGHT)
                * float(row.get("blended_score") if use_cohort_fitness else row.get("composite_score") or 0.0)
                + BLENDED_FULL_PERIOD_WEIGHT * float(row.get("full_period_score") or 0.0),
                4,
            )
        score_key = "blended_full_period_score"
    knob_axis_discriminability = (
        discover_knob_axis_discriminability(
            scored,
            tuple(axis.name for axis in grid_axes),
            score_key=score_key,
        )
        if use_cohort_fitness and scored
        else {}
    )
    for axis_name, axis_info in knob_axis_discriminability.items():
        if not axis_info.get("discriminatory"):
            warnings.append(
                f"knob axis '{axis_name}' shows negligible cohort discrimination "
                f"(range={axis_info.get('range')})"
            )

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
    current_blended = current_score
    if use_cohort_fitness:
        current_cohort_wf = cohort_walk_forward_score(
            acted,
            n_folds=n_folds,
            stability_penalty=stability_penalty,
            **_cohort_kwargs(
                current_candidate,
                use_adjusted_signal=use_adjusted_signal,
                require_research_accumulate=require_research_accumulate,
            ),
        )
        current_cohort = score_cohort_selection(
            acted,
            **_cohort_kwargs(
                current_candidate,
                use_adjusted_signal=use_adjusted_signal,
                require_research_accumulate=require_research_accumulate,
            ),
        )
        current_cohort_score = (
            float(current_cohort_wf["composite_score"])
            if current_cohort_wf is not None
            else float(current_cohort.get("cohort_fitness") or -999.0)
        )
        if current_score is not None:
            current_blended = blend_calibration_score(
                current_score,
                current_cohort_score,
                cohort_weight=cohort_weight,
            )

    top = scored[0] if scored else None
    score_gap = score_gap_vs_runner_up(scored, score_key=score_key) if scored else None
    recommended_score = float(top[score_key]) if top and top.get(score_key) is not None else None
    confidence = _prior_confidence(
        acted_count=len(acted),
        recommended_score=recommended_score,
        current_score=current_blended if use_cohort_fitness else current_score,
        fold_stability=(
            float((top.get("walk_forward") or {}).get("fold_stability") or 0.0) if top else None
        ),
    )
    if (
        score_gap is not None
        and score_gap < MIN_SCORE_GAP_FOR_PRIOR
        and confidence != "insufficient"
    ):
        confidence = "low"

    top_n = max(1, int(bootstrap_top_n))
    bootstrap_priors: list[dict[str, Any]] = []
    for row in scored[:top_n]:
        prior = _build_recommended_prior(
            row,
            current_candidate,
            confidence=confidence,
            current_score=current_blended if use_cohort_fitness else current_score,
            score_gap=score_gap,
            cohort_selection=row.get("cohort_selection"),
            use_blended_score=use_cohort_fitness,
        )
        if prior is None:
            continue
        prior["rank"] = row.get("rank")
        prior["full_period_score"] = row.get("full_period_score")
        prior["winner_loser"] = row.get("winner_loser")
        prior["shadow_track_id"] = calibrated_shadow_track_id(int(row.get("rank") or 1))
        if mode != RANKING_WALK_FORWARD:
            prior["rationale"] = (
                "Top full-period retrospective score (portfolio replay + cohort + "
                "winner/loser catch/exclude). Seed competing shadow sims for forward "
                "endurance; do not auto-apply to the live learning loop."
            )
        bootstrap_priors.append(prior)

    ready_for_shadow_bootstrap = bool(
        scored
        and len(acted) >= MIN_ACTED_FOR_SHADOW_BOOTSTRAP
        and (score_gap is None or score_gap >= MIN_SCORE_GAP_FOR_PRIOR)
        and confidence != "insufficient"
    )

    return {
        "scope": "knob_calibration",
        "observe_only": True,
        "calibrated_at": datetime.now(UTC).isoformat(),
        "track_id": str(config.track_id or track_dir.name or "rules"),
        "track_label": str(config.track_label or ""),
        "ranking_mode": mode,
        "readiness": {
            "acted_entries": len(acted),
            "walk_forward_folds": len(walk_forward_fold_ranges(len(acted), n_folds)),
            "grid_size": len(candidates),
            "ready_for_priors": bool(
                scored
                and len(acted) >= MIN_ACTED_FOR_CALIBRATION
                and (score_gap is None or score_gap >= MIN_SCORE_GAP_FOR_PRIOR)
            ),
            "ready_for_shadow_bootstrap": ready_for_shadow_bootstrap,
            "shadow_bootstrap_acted_floor": MIN_ACTED_FOR_SHADOW_BOOTSTRAP,
            "shadow_bootstrap_acted_ideal": MIN_ACTED_FOR_SHADOW_BOOTSTRAP_IDEAL,
            "warnings": warnings,
            "use_cohort_fitness": use_cohort_fitness,
            "cohort_weight": cohort_weight if use_cohort_fitness else None,
            "score_gap_vs_runner_up": score_gap,
            "ranking_score_key": score_key,
        },
        "current_knobs": current_candidate.to_dict(),
        "current_score": current_score,
        "current_blended_score": current_blended if use_cohort_fitness else None,
        "search_space": {axis.name: list(axis.values) for axis in grid_axes},
        "cost_drag_lambda": cost_drag_lambda,
        "stability_penalty": stability_penalty,
        "knob_axis_discriminability": knob_axis_discriminability,
        "candidates_ranked": scored,
        "bootstrap_priors": bootstrap_priors,
        "recommended_prior": bootstrap_priors[0] if bootstrap_priors else None,
        "limitations": (
            "Observe-only calibration on rebalance_log replay"
            + (
                " with cohort-selection fitness for AI-judgment tracks."
                if use_cohort_fitness
                else "."
            )
            + (
                " Ranking uses full-period retrospective for shadow bootstrap."
                if mode != RANKING_WALK_FORWARD
                else " Ranking uses walk-forward composite."
            )
            + " Does not auto-apply knobs. Full archive P&L needs thicker weekly screens (L111). "
            "Bootstrap shadows for forward endurance; promote survivors manually into "
            "learning-loop priors."
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


def _track_calibration_row(
    priors_payload: dict[str, Any],
    track_id: str,
) -> dict[str, Any] | None:
    if priors_payload.get("scope") == "knob_calibration_multi":
        row = (priors_payload.get("tracks") or {}).get(track_id)
        return row if isinstance(row, dict) else None
    if priors_payload.get("track_id") == track_id:
        return priors_payload
    return None


def _apply_prior_knobs_to_config(config: AutomationConfig, knobs: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    if "max_positions" in knobs and int(knobs["max_positions"]) != int(config.max_positions):
        config.max_positions = int(knobs["max_positions"])
        changed["max_positions"] = config.max_positions
    if "skip_timing_wait" in knobs and bool(knobs["skip_timing_wait"]) != bool(
        config.skip_timing_wait
    ):
        config.skip_timing_wait = bool(knobs["skip_timing_wait"])
        changed["skip_timing_wait"] = config.skip_timing_wait
    if "min_conviction" in knobs and float(knobs["min_conviction"]) != float(config.min_conviction):
        config.min_conviction = float(knobs["min_conviction"])
        changed["min_conviction"] = round(config.min_conviction, 4)
    if "sector_cap" in knobs and float(knobs["sector_cap"]) != float(config.sector_cap):
        config.sector_cap = float(knobs["sector_cap"])
        changed["sector_cap"] = round(config.sector_cap, 4)
    if "exit_confirm_screens" in knobs and int(knobs["exit_confirm_screens"]) != int(
        config.exit_confirm_screens
    ):
        config.exit_confirm_screens = int(knobs["exit_confirm_screens"])
        changed["exit_confirm_screens"] = config.exit_confirm_screens
    return changed


def _spawn_one_calibrated_shadow(
    paper_root: Path,
    *,
    parent: AutomationConfig,
    parent_track_id: str,
    prior: dict[str, Any],
    rank: int,
    priors_file: Path,
    priors_payload: dict[str, Any],
    track_row: dict[str, Any],
    force_respawn: bool,
) -> dict[str, Any]:
    prior_knobs = prior.get("knobs")
    if not isinstance(prior_knobs, dict) or not prior_knobs:
        return {"spawned": False, "rank": rank, "reason": "prior knobs missing"}

    track_id = calibrated_shadow_track_id(rank)
    shadow_dir = paper_root / calibrated_shadow_subdir(rank)
    shadow_dir.mkdir(parents=True, exist_ok=True)
    config_path = shadow_dir / CONFIG_FILENAME
    fund_path = shadow_dir / FUND_FILENAME
    provenance_path = shadow_dir / CALIBRATION_PROVENANCE_FILENAME

    existed = config_path.exists()
    if existed and not force_respawn:
        shadow = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
        respawned_fund = False
    else:
        shadow = default_ai_judgment_config(parent)
        shadow.track_id = track_id
        shadow.track_label = (
            "AI judgment calibrated shadow (frozen priors)"
            if rank <= 1
            else f"AI judgment calibrated shadow rank {rank} (frozen priors)"
        )
        shadow.is_primary_learning_track = False
        shadow.is_calibration_shadow = True
        shadow.calibration_parent_track = parent_track_id
        if fund_path.exists():
            fund_path.unlink()
        ensure_automated_fund(fund_path, shadow)
        respawned_fund = True

    parent_knobs = KnobCandidate.from_learning_knobs(
        LearningKnobs.from_config(parent),
        exit_confirm_screens=parent.exit_confirm_screens,
    ).to_dict()
    changed_vs_parent = _apply_prior_knobs_to_config(shadow, prior_knobs)
    shadow.is_calibration_shadow = True
    shadow.calibration_parent_track = parent_track_id
    shadow.is_primary_learning_track = False
    shadow.track_id = track_id
    shadow.track_label = shadow.track_label or (
        "AI judgment calibrated shadow (frozen priors)"
        if rank <= 1
        else f"AI judgment calibrated shadow rank {rank} (frozen priors)"
    )
    config_path.write_text(json.dumps(shadow.to_dict(), indent=2) + "\n", encoding="utf-8")
    ensure_automated_fund(fund_path, shadow)

    provenance = {
        "schema_version": 2,
        "spawned_at": datetime.now(UTC).isoformat(),
        "parent_track_id": parent_track_id,
        "shadow_track_id": track_id,
        "bootstrap_rank": int(rank),
        "priors_source": str(priors_file),
        "priors_calibrated_at": priors_payload.get("calibrated_at")
        or track_row.get("calibrated_at"),
        "ranking_mode": track_row.get("ranking_mode"),
        "recommended_prior": prior,
        "parent_knobs_at_spawn": parent_knobs,
        "shadow_knobs": shadow.selection_kwargs(),
        "changed_vs_parent": changed_vs_parent,
        "confidence": prior.get("confidence"),
        "full_period_score": prior.get("full_period_score"),
        "winner_loser": prior.get("winner_loser"),
        "force_respawn": bool(force_respawn),
        "respawned_fund": respawned_fund,
        "note": (
            "Frozen calibration shadow — decision-review --apply is disabled. "
            "Compare forward endurance vs primary ai_judgment and ^FTSE before promotion."
        ),
    }
    write_json(provenance_path, provenance, compact=False)

    return {
        "spawned": True,
        "created": not existed or force_respawn,
        "rank": int(rank),
        "shadow_track_id": track_id,
        "shadow_dir": str(shadow_dir),
        "confidence": prior.get("confidence"),
        "changed_vs_parent": changed_vs_parent,
        "respawned_fund": respawned_fund,
        "provenance_path": str(provenance_path),
        "knobs": prior_knobs,
    }


def spawn_calibration_shadow_tracks(
    paper_root: Path,
    *,
    parent_track_id: str = AI_JUDGMENT_TRACK_ID,
    priors_path: Path | None = None,
    top_n: int = DEFAULT_BOOTSTRAP_TOP_N,
    force_respawn: bool = False,
    require_ready: bool = False,
) -> dict[str, Any]:
    """
    Spawn up to top_n competing calibrated shadow books from bootstrap_priors.

    Rank 1 keeps the legacy `ai_judgment_calibrated` directory; ranks 2+ use
    `ai_judgment_calibrated_rN`. Observe-only — never auto-applies live knobs.
    """
    paper_root = Path(paper_root)
    if parent_track_id != AI_JUDGMENT_TRACK_ID:
        return {
            "spawned": False,
            "reason": f"Only {AI_JUDGMENT_TRACK_ID} shadow tracks are supported in phase 1",
            "shadows": [],
        }

    priors_file = priors_path or (paper_root / KNOB_CALIBRATION_PRIORS_FILENAME)
    if not priors_file.exists():
        return {
            "spawned": False,
            "reason": f"No calibration priors at {priors_file}",
            "shadows": [],
        }

    priors_payload = read_json(priors_file)
    track_row = _track_calibration_row(priors_payload, parent_track_id)
    if not track_row:
        return {
            "spawned": False,
            "reason": f"No calibration row for {parent_track_id} in {priors_file}",
            "shadows": [],
        }

    if require_ready and not (track_row.get("readiness") or {}).get("ready_for_shadow_bootstrap"):
        return {
            "spawned": False,
            "reason": "ready_for_shadow_bootstrap is false — thicken acted logs or re-run retrospective",
            "shadows": [],
            "readiness": track_row.get("readiness"),
        }

    priors = list(track_row.get("bootstrap_priors") or [])
    if not priors:
        recommended = track_row.get("recommended_prior") or {}
        if isinstance(recommended, dict) and recommended.get("knobs"):
            priors = [recommended]
    if not priors:
        return {
            "spawned": False,
            "reason": "bootstrap_priors/recommended_prior.knobs missing — run ftse-knob-calibrate first",
            "shadows": [],
        }

    configs = ensure_learning_track_configs(paper_root)
    parent = configs.get(parent_track_id)
    if parent is None:
        return {
            "spawned": False,
            "reason": f"Parent track {parent_track_id} config missing",
            "shadows": [],
        }

    n = max(1, min(int(top_n), len(priors)))
    shadows: list[dict[str, Any]] = []
    for index, prior in enumerate(priors[:n], start=1):
        rank = int(prior.get("rank") or index)
        result = _spawn_one_calibrated_shadow(
            paper_root,
            parent=parent,
            parent_track_id=parent_track_id,
            prior=prior,
            rank=rank,
            priors_file=priors_file,
            priors_payload=priors_payload,
            track_row=track_row,
            force_respawn=force_respawn,
        )
        shadows.append(result)

    spawned_any = any(row.get("spawned") for row in shadows)
    return {
        "spawned": spawned_any,
        "top_n": n,
        "ranking_mode": track_row.get("ranking_mode"),
        "shadows": shadows,
        # Back-compat fields for phase-1 callers / CLI.
        "shadow_track_id": (shadows[0].get("shadow_track_id") if shadows else None),
        "shadow_dir": (shadows[0].get("shadow_dir") if shadows else None),
        "confidence": (shadows[0].get("confidence") if shadows else None),
        "changed_vs_parent": (shadows[0].get("changed_vs_parent") if shadows else None),
        "provenance_path": (shadows[0].get("provenance_path") if shadows else None),
        "respawned_fund": (shadows[0].get("respawned_fund") if shadows else None),
        "created": (shadows[0].get("created") if shadows else None),
        "reason": None if spawned_any else "no shadows spawned",
    }


def spawn_calibrated_shadow_track(
    paper_root: Path,
    *,
    parent_track_id: str = AI_JUDGMENT_TRACK_ID,
    priors_path: Path | None = None,
    force_respawn: bool = False,
) -> dict[str, Any]:
    """
    Spawn a forward-validation shadow book with frozen calibration priors.

    Copies parent AI gates, applies recommended_prior knobs, and starts a fresh
    automated_fund at the parent's initial_cash. Idempotent unless force_respawn.
    """
    return spawn_calibration_shadow_tracks(
        paper_root,
        parent_track_id=parent_track_id,
        priors_path=priors_path,
        top_n=1,
        force_respawn=force_respawn,
        require_ready=False,
    )


def load_calibration_provenance(track_dir: Path) -> dict[str, Any] | None:
    path = Path(track_dir) / CALIBRATION_PROVENANCE_FILENAME
    if not path.exists():
        return None
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None
