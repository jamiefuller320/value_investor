"""Full-period knob retrospective: winner/loser catch rates over the monitoring window."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from value_investor.cohort_selection_fitness import (
    CohortObservation,
    collect_cohort_observations,
    score_cohort_selection,
)
from value_investor.paper_fund import BUY_SIGNALS, PaperFund
from value_investor.rebalance_log import _candidate_by_ticker, resolve_replay_candidates

if TYPE_CHECKING:
    from value_investor.knob_calibration import KnobCandidate

DEFAULT_TOP_BOTTOM_K = 5
WINNER_LOSER_WEIGHT = 0.25
COHORT_FULL_PERIOD_WEIGHT = 0.35
DEFAULT_COST_DRAG_LAMBDA = 0.5


def _price_map(entry: dict[str, Any]) -> dict[str, float]:
    prices: dict[str, float] = {}
    by_ticker = _candidate_by_ticker(entry)
    for ticker, row in by_ticker.items():
        raw = (row or {}).get("price")
        if raw is not None and float(raw) > 0:
            prices[str(ticker)] = float(raw)
    return prices


def _buy_tier_tickers(entry: dict[str, Any]) -> set[str]:
    tickers: set[str] = set()
    for row in entry.get("screen_buy_tier") or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            tickers.add(ticker)
    if tickers:
        return tickers
    buy_signals = {str(signal).lower() for signal in BUY_SIGNALS}
    for row in resolve_replay_candidates(entry):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        signal = str(row.get("signal") or "").strip().lower()
        if ticker and signal in buy_signals:
            tickers.add(ticker)
    return tickers


def rank_buy_tier_forward_performers(
    acted: list[dict[str, Any]],
    *,
    top_k: int = DEFAULT_TOP_BOTTOM_K,
    bottom_k: int = DEFAULT_TOP_BOTTOM_K,
) -> dict[str, Any]:
    """
    Rank buy-tier names by cumulative pass-to-pass return over the acted log.

    Uses candidate/screen prices on consecutive acted passes (observe-only).
    """
    if len(acted) < 2:
        return {
            "ranked": [],
            "top_performers": [],
            "bottom_performers": [],
            "observation_slots": 0,
        }

    cumulative: dict[str, float] = defaultdict(float)
    slots: dict[str, int] = defaultdict(int)

    for index in range(len(acted) - 1):
        entry = acted[index]
        next_entry = acted[index + 1]
        prices_now = _price_map(entry)
        prices_next = _price_map(next_entry)
        for ticker in _buy_tier_tickers(entry):
            px0 = prices_now.get(ticker)
            px1 = prices_next.get(ticker)
            if px0 is None or px1 is None or px0 <= 0:
                continue
            cumulative[ticker] += (px1 / px0) - 1.0
            slots[ticker] += 1

    ranked = sorted(
        (
            {
                "ticker": ticker,
                "cumulative_forward_return": round(cumulative[ticker], 4),
                "observation_slots": slots[ticker],
            }
            for ticker in cumulative
        ),
        key=lambda row: float(row["cumulative_forward_return"]),
        reverse=True,
    )
    n = len(ranked)
    if n == 0:
        return {
            "ranked": [],
            "top_performers": [],
            "bottom_performers": [],
            "observation_slots": 0,
        }
    # Keep top/bottom disjoint so catch/exclude rates stay meaningful.
    half = max(1, n // 2)
    k_top = min(max(0, int(top_k)), half)
    k_bottom = min(max(0, int(bottom_k)), half)
    top = [row["ticker"] for row in ranked[:k_top]]
    bottom = [row["ticker"] for row in ranked[-k_bottom:]][::-1]
    # Drop any accidental overlap on odd-sized universes.
    bottom = [ticker for ticker in bottom if ticker not in set(top)]
    return {
        "ranked": ranked,
        "top_performers": top,
        "bottom_performers": bottom,
        "observation_slots": sum(slots.values()),
    }


def _selected_tickers_from_observations(
    observations: list[CohortObservation],
) -> set[str]:
    return {obs.ticker for obs in observations if obs.role in {"selected", "new_buy"}}


def winner_loser_summary(
    acted: list[dict[str, Any]],
    candidate: KnobCandidate,
    *,
    use_adjusted_signal: bool | None,
    require_research_accumulate: bool | None,
    top_k: int = DEFAULT_TOP_BOTTOM_K,
    bottom_k: int = DEFAULT_TOP_BOTTOM_K,
) -> dict[str, Any]:
    """Measure whether a knob set held top performers and avoided bottom ones."""
    from value_investor.knob_calibration import _cohort_kwargs

    universe = rank_buy_tier_forward_performers(acted, top_k=top_k, bottom_k=bottom_k)
    top = list(universe.get("top_performers") or [])
    bottom = list(universe.get("bottom_performers") or [])
    observations = collect_cohort_observations(
        acted,
        **_cohort_kwargs(
            candidate,
            use_adjusted_signal=use_adjusted_signal,
            require_research_accumulate=require_research_accumulate,
        ),
    )
    selected = _selected_tickers_from_observations(observations)
    caught = [ticker for ticker in top if ticker in selected]
    avoided = [ticker for ticker in bottom if ticker not in selected]
    caught_poor = [ticker for ticker in bottom if ticker in selected]
    catch_rate = (len(caught) / len(top)) if top else None
    exclude_rate = (len(avoided) / len(bottom)) if bottom else None
    return {
        "top_buy_tier": top,
        "bottom_buy_tier": bottom,
        "top_buy_tier_caught": caught,
        "bottom_buy_tier_avoided": avoided,
        "bottom_buy_tier_held": caught_poor,
        "catch_rate": None if catch_rate is None else round(catch_rate, 4),
        "exclude_rate": None if exclude_rate is None else round(exclude_rate, 4),
        "selected_unique": sorted(selected),
        "observation_count": len(observations),
        "universe_observation_slots": universe.get("observation_slots"),
    }


def _winner_loser_bonus(summary: dict[str, Any] | None) -> float:
    if not summary:
        return 0.0
    catch = summary.get("catch_rate")
    exclude = summary.get("exclude_rate")
    if catch is None and exclude is None:
        return 0.0
    catch_v = float(catch) if catch is not None else 0.5
    exclude_v = float(exclude) if exclude is not None else 0.5
    return catch_v + exclude_v - 1.0


def score_full_period_retrospective(
    acted: list[dict[str, Any]],
    candidate: KnobCandidate,
    *,
    actual_fund: PaperFund | None,
    use_adjusted_signal: bool | None,
    require_research_accumulate: bool | None,
    cost_drag_lambda: float = DEFAULT_COST_DRAG_LAMBDA,
    use_cohort_fitness: bool = True,
    top_k: int = DEFAULT_TOP_BOTTOM_K,
    bottom_k: int = DEFAULT_TOP_BOTTOM_K,
) -> dict[str, Any] | None:
    """
    Full-monitoring-window score for a knob candidate.

    Combines full-log portfolio replay, cohort fitness, and winner/loser overlap.
    Does not change screen thresholds (N3).
    """
    from value_investor.knob_calibration import (
        _cohort_kwargs,
        _replay_candidate_on_entries,
        fold_fitness,
    )

    if len(acted) < 2:
        return None

    full_window = _replay_candidate_on_entries(
        acted,
        candidate,
        actual_fund=actual_fund,
        use_adjusted_signal=use_adjusted_signal,
        require_research_accumulate=require_research_accumulate,
    )
    if full_window is None:
        return None

    portfolio_score = fold_fitness(full_window, cost_drag_lambda=cost_drag_lambda)
    cohort_summary = None
    cohort_score = None
    if use_cohort_fitness:
        cohort_summary = score_cohort_selection(
            acted,
            **_cohort_kwargs(
                candidate,
                use_adjusted_signal=use_adjusted_signal,
                require_research_accumulate=require_research_accumulate,
            ),
        )
        cohort_score = float(cohort_summary.get("cohort_fitness") or 0.0)

    winner_loser = winner_loser_summary(
        acted,
        candidate,
        use_adjusted_signal=use_adjusted_signal,
        require_research_accumulate=require_research_accumulate,
        top_k=top_k,
        bottom_k=bottom_k,
    )
    wl_bonus = _winner_loser_bonus(winner_loser)

    if cohort_score is not None:
        full_period_score = (
            (1.0 - COHORT_FULL_PERIOD_WEIGHT - WINNER_LOSER_WEIGHT) * portfolio_score
            + COHORT_FULL_PERIOD_WEIGHT * cohort_score
            + WINNER_LOSER_WEIGHT * wl_bonus
        )
    else:
        full_period_score = (
            1.0 - WINNER_LOSER_WEIGHT
        ) * portfolio_score + WINNER_LOSER_WEIGHT * wl_bonus

    return {
        "full_period_score": round(full_period_score, 4),
        "portfolio_score": round(portfolio_score, 4),
        "cohort_score": None if cohort_score is None else round(cohort_score, 4),
        "winner_loser_bonus": round(wl_bonus, 4),
        "winner_loser": winner_loser,
        "full_window_log_replay": {
            key: full_window[key]
            for key in (
                "simulated_return",
                "simulated_cost_drag",
                "simulated_trade_count",
                "return_delta_vs_actual",
                "log_entries_replayed",
            )
            if key in full_window
        },
        "cohort_selection": (
            {
                key: cohort_summary[key]
                for key in (
                    "cohort_hit_rate",
                    "cohort_mean_forward_return",
                    "selection_spread",
                    "new_buy_hit_rate",
                    "cohort_fitness",
                )
                if key in cohort_summary
            }
            if cohort_summary
            else None
        ),
    }
