"""Cohort-selection fitness for knob calibration (name-level forward outcomes)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from value_investor.paper_fund import (
    BUY_SIGNALS,
    run_automated_rebalance,
    run_technical_pass,
)
from value_investor.rebalance_log import (
    _candidate_by_ticker,
    _effective_signal_from_row,
    _selection_kwargs_for_replay,
    fund_from_pre_state,
    resolve_replay_candidates,
)

DEFAULT_COHORT_FITNESS_WEIGHT = 0.6
DEFAULT_PORTFOLIO_FITNESS_WEIGHT = 0.4
MIN_COHORT_OBSERVATIONS = 2
MIN_SCORE_GAP_FOR_PRIOR = 0.005
MIN_AXIS_DISCRIMINABILITY = 0.002


@dataclass(frozen=True)
class CohortObservation:
    ticker: str
    pass_index: int
    role: str  # selected | new_buy | rejected
    forward_return: float
    conviction_score: float | None = None


def _ticker_price(
    entry: dict[str, Any], ticker: str, *, fallback: float | None = None
) -> float | None:
    row = _candidate_by_ticker(entry).get(ticker) or {}
    raw = row.get("price")
    if raw is not None and float(raw) > 0:
        return float(raw)
    return fallback


def _eligible_rejected_tickers(
    entry: dict[str, Any],
    *,
    held: set[str],
    min_conviction: float,
    use_adjusted_signal: bool | None,
    require_research_accumulate: bool | None,
) -> set[str]:
    rejected: set[str] = set()
    for row in resolve_replay_candidates(
        entry,
        use_adjusted_signal=use_adjusted_signal,
        require_research_accumulate=require_research_accumulate,
    ):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker or ticker in held:
            continue
        if _effective_signal_from_row(row) not in BUY_SIGNALS:
            continue
        conviction = row.get("conviction_score")
        if conviction is not None and float(conviction) < float(min_conviction):
            continue
        rejected.add(ticker)
    return rejected


def collect_cohort_observations(
    acted: list[dict[str, Any]],
    *,
    max_positions: int,
    skip_timing_wait: bool,
    min_conviction: float,
    sector_cap: float,
    use_adjusted_signal: bool | None = None,
    require_research_accumulate: bool | None = None,
    exit_confirm_screens: int | None = None,
) -> list[CohortObservation]:
    """
    Replay knob settings and score forward returns for selected vs rejected names.

    Uses mark prices from the next acted pass's candidate pool (observe-only).
    """
    if len(acted) < 2:
        return []

    fund = fund_from_pre_state(acted[0])
    pass_holdings: list[set[str]] = []
    pass_new_buys: list[set[str]] = []
    pass_avg_cost: list[dict[str, float]] = []

    for entry in acted:
        mode = str(entry.get("strategy_mode") or fund.config.mode)
        candidates = resolve_replay_candidates(
            entry,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
        )
        when = str((entry.get("gate") or {}).get("local_time") or entry.get("logged_at") or "")
        kwargs = _selection_kwargs_for_replay(
            entry,
            max_positions=max_positions,
            skip_timing_wait=skip_timing_wait,
            min_conviction=min_conviction,
            sector_cap=sector_cap,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
            exit_confirm_screens=exit_confirm_screens,
        )
        fund.config.max_positions = int(kwargs.pop("max_positions"))
        holdings_before = set(fund.holdings.keys())
        if mode == "technical":
            executed = run_technical_pass(fund, candidates, acted_at=when or None)
        else:
            executed = run_automated_rebalance(fund, candidates, acted_at=when or None, **kwargs)
        new_buys = {
            str(trade.ticker)
            for trade in executed
            if str(getattr(trade, "side", "") or "") == "buy"
        }
        if not new_buys:
            new_buys = set(fund.holdings.keys()) - holdings_before
        pass_holdings.append(set(fund.holdings.keys()))
        pass_new_buys.append(new_buys)
        pass_avg_cost.append(
            {ticker: float(position.avg_cost) for ticker, position in fund.holdings.items()}
        )

    observations: list[CohortObservation] = []
    for index in range(len(acted) - 1):
        entry = acted[index]
        next_entry = acted[index + 1]
        held = pass_holdings[index]
        new_buys = pass_new_buys[index]
        avg_costs = pass_avg_cost[index]
        rejected = _eligible_rejected_tickers(
            entry,
            held=held,
            min_conviction=min_conviction,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
        )

        for ticker in held:
            start = _ticker_price(entry, ticker, fallback=avg_costs.get(ticker))
            end = _ticker_price(next_entry, ticker, fallback=start)
            if start is None or end is None or start <= 0:
                continue
            row = _candidate_by_ticker(entry).get(ticker) or {}
            role = "new_buy" if ticker in new_buys else "selected"
            observations.append(
                CohortObservation(
                    ticker=ticker,
                    pass_index=index,
                    role=role,
                    forward_return=(end - start) / start,
                    conviction_score=(
                        float(row["conviction_score"])
                        if row.get("conviction_score") is not None
                        else None
                    ),
                )
            )

        for ticker in rejected:
            start = _ticker_price(entry, ticker)
            end = _ticker_price(next_entry, ticker, fallback=start)
            if start is None or end is None or start <= 0:
                continue
            row = _candidate_by_ticker(entry).get(ticker) or {}
            observations.append(
                CohortObservation(
                    ticker=ticker,
                    pass_index=index,
                    role="rejected",
                    forward_return=(end - start) / start,
                    conviction_score=(
                        float(row["conviction_score"])
                        if row.get("conviction_score") is not None
                        else None
                    ),
                )
            )

    return observations


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def summarize_cohort_observations(observations: list[CohortObservation]) -> dict[str, Any]:
    selected = [obs.forward_return for obs in observations if obs.role in {"selected", "new_buy"}]
    rejected = [obs.forward_return for obs in observations if obs.role == "rejected"]
    new_buys = [obs.forward_return for obs in observations if obs.role == "new_buy"]

    selected_mean = _mean(selected)
    rejected_mean = _mean(rejected)
    selection_spread = (
        float(selected_mean - rejected_mean)
        if selected_mean is not None and rejected_mean is not None
        else None
    )
    hit_rate = (sum(1 for value in selected if value > 0) / len(selected)) if selected else None
    new_buy_hit_rate = (
        (sum(1 for value in new_buys if value > 0) / len(new_buys)) if new_buys else None
    )

    cohort_fitness = _cohort_fitness_scalar(
        hit_rate=hit_rate,
        mean_forward_return=selected_mean,
        selection_spread=selection_spread,
        new_buy_hit_rate=new_buy_hit_rate,
        observation_count=len(selected),
    )

    return {
        "observation_count": len(observations),
        "selected_slots": len(selected),
        "rejected_slots": len(rejected),
        "new_buy_slots": len(new_buys),
        "cohort_hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
        "cohort_mean_forward_return": (
            round(selected_mean, 4) if selected_mean is not None else None
        ),
        "rejected_mean_forward_return": (
            round(rejected_mean, 4) if rejected_mean is not None else None
        ),
        "selection_spread": round(selection_spread, 4) if selection_spread is not None else None,
        "new_buy_hit_rate": round(new_buy_hit_rate, 4) if new_buy_hit_rate is not None else None,
        "cohort_fitness": round(cohort_fitness, 4),
    }


def _cohort_fitness_scalar(
    *,
    hit_rate: float | None,
    mean_forward_return: float | None,
    selection_spread: float | None,
    new_buy_hit_rate: float | None,
    observation_count: int,
) -> float:
    if observation_count < MIN_COHORT_OBSERVATIONS:
        return -999.0
    score = 0.0
    if hit_rate is not None:
        score += 0.35 * (hit_rate - 0.5)
    if mean_forward_return is not None:
        score += 0.35 * mean_forward_return
    if selection_spread is not None:
        score += 0.2 * selection_spread
    if new_buy_hit_rate is not None:
        score += 0.1 * (new_buy_hit_rate - 0.5)
    return score


def score_cohort_selection(
    acted: list[dict[str, Any]],
    *,
    max_positions: int,
    skip_timing_wait: bool,
    min_conviction: float,
    sector_cap: float,
    use_adjusted_signal: bool | None = None,
    require_research_accumulate: bool | None = None,
    exit_confirm_screens: int | None = None,
) -> dict[str, Any]:
    observations = collect_cohort_observations(
        acted,
        max_positions=max_positions,
        skip_timing_wait=skip_timing_wait,
        min_conviction=min_conviction,
        sector_cap=sector_cap,
        use_adjusted_signal=use_adjusted_signal,
        require_research_accumulate=require_research_accumulate,
        exit_confirm_screens=exit_confirm_screens,
    )
    summary = summarize_cohort_observations(observations)
    summary["scope"] = "cohort_selection"
    return summary


def blend_calibration_score(
    portfolio_score: float,
    cohort_score: float | None,
    *,
    cohort_weight: float = DEFAULT_COHORT_FITNESS_WEIGHT,
) -> float:
    if cohort_score is None or cohort_score <= -900:
        return portfolio_score
    portfolio_weight = 1.0 - cohort_weight
    return portfolio_weight * portfolio_score + cohort_weight * cohort_score


def discover_knob_axis_discriminability(
    scored_rows: list[dict[str, Any]],
    axis_names: tuple[str, ...],
    *,
    score_key: str = "blended_score",
) -> dict[str, Any]:
    """How much each knob axis separates cohort/blended fitness across candidates."""
    axes: dict[str, dict[str, list[float]]] = {name: {} for name in axis_names}
    for row in scored_rows:
        knobs = row.get("knobs") or {}
        score = row.get(score_key)
        if score is None:
            continue
        for name in axis_names:
            raw_value = knobs.get(name)
            if raw_value is None:
                continue
            key = str(raw_value)
            axes[name].setdefault(key, []).append(float(score))

    discriminability: dict[str, Any] = {}
    for name, by_value in axes.items():
        means = {value: sum(scores) / len(scores) for value, scores in by_value.items() if scores}
        if len(means) < 2:
            discriminability[name] = {
                "range": 0.0,
                "mean_by_value": {key: round(val, 4) for key, val in means.items()},
                "discriminatory": False,
            }
            continue
        values = list(means.values())
        axis_range = max(values) - min(values)
        discriminability[name] = {
            "range": round(axis_range, 4),
            "mean_by_value": {key: round(val, 4) for key, val in means.items()},
            "discriminatory": axis_range >= MIN_AXIS_DISCRIMINABILITY,
        }
    return discriminability


def score_gap_vs_runner_up(
    scored_rows: list[dict[str, Any]], *, score_key: str = "blended_score"
) -> float | None:
    if len(scored_rows) < 2:
        return None
    top = float(scored_rows[0].get(score_key) or 0.0)
    runner = float(scored_rows[1].get(score_key) or 0.0)
    return round(top - runner, 4)


def cohort_walk_forward_score(
    acted: list[dict[str, Any]],
    *,
    n_folds: int,
    stability_penalty: float,
    max_positions: int,
    skip_timing_wait: bool,
    min_conviction: float,
    sector_cap: float,
    use_adjusted_signal: bool | None = None,
    require_research_accumulate: bool | None = None,
    exit_confirm_screens: int | None = None,
) -> dict[str, Any] | None:
    from value_investor.knob_calibration import walk_forward_fold_ranges

    if len(acted) < MIN_COHORT_OBSERVATIONS + 1:
        return None

    fold_scores: list[dict[str, Any]] = []
    for start, end in walk_forward_fold_ranges(len(acted), n_folds):
        if end - start < 2:
            continue
        slice_entries = acted[start:end]
        summary = score_cohort_selection(
            slice_entries,
            max_positions=max_positions,
            skip_timing_wait=skip_timing_wait,
            min_conviction=min_conviction,
            sector_cap=sector_cap,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
            exit_confirm_screens=exit_confirm_screens,
        )
        fitness = float(summary.get("cohort_fitness") or -999.0)
        fold_scores.append(
            {
                "fold_start": start,
                "fold_end": end,
                "cohort_fitness": round(fitness, 4),
                "cohort_hit_rate": summary.get("cohort_hit_rate"),
                "selection_spread": summary.get("selection_spread"),
                "selected_slots": summary.get("selected_slots"),
            }
        )
    if not fold_scores:
        return None

    fitnesses = [float(row["cohort_fitness"]) for row in fold_scores]
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
