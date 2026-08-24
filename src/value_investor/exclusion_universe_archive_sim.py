"""Observe-only archive lab: equal-weight universe vs universe-minus-exclusions.

Compares forward returns of the full screened (or buy-tier) universe against
progressively tighter exclusion ladders using point-in-time screen fields only.
Hindsight quartile metrics are evaluation-only — never used to define exclusions.

Complements knob calibration (portfolio replay) and exit-timing archive sims.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from value_investor.backtest import BENCHMARK_TICKER, RunSnapshot, load_run_snapshots
from value_investor.paper_fund import BUY_SIGNALS

COHORTS_FILENAME = "exclusion_universe_archive.json"
REVIEW_FILENAME = "exclusion_universe_review.json"
ARCHIVE_TRACK_ID = "exclusion_universe_archive"

UNIVERSE_FULL_SCREENED = "full_screened"
UNIVERSE_BUY_TIER_ONLY = "buy_tier_only"
VALID_UNIVERSE_MODES = frozenset({UNIVERSE_FULL_SCREENED, UNIVERSE_BUY_TIER_ONLY})

DEFAULT_MIN_FILTERED_POOL = 15
DEFAULT_MAX_POSITIONS = 5
DEFAULT_MIN_WEEK_PAIRS = 4


@dataclass(frozen=True)
class ExclusionStep:
    """Cumulative exclusion state at one ladder rung (monotonic tightening)."""

    step_id: str
    label: str
    exclude_signals: frozenset[str] = frozenset()
    exclude_timing_wait: bool = False
    min_conviction: float = 0.0
    require_effective_buy_tier: bool = False
    require_research_accumulate: bool = False
    min_data_quality: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "label": self.label,
            "exclude_signals": sorted(self.exclude_signals),
            "exclude_timing_wait": self.exclude_timing_wait,
            "min_conviction": self.min_conviction,
            "require_effective_buy_tier": self.require_effective_buy_tier,
            "require_research_accumulate": self.require_research_accumulate,
            "min_data_quality": self.min_data_quality,
        }


def exclusion_step_from_dict(data: dict[str, Any]) -> ExclusionStep:
    """Parse ladder step from archive review JSON."""
    return ExclusionStep(
        step_id=str(data.get("step_id") or ""),
        label=str(data.get("label") or data.get("step_id") or ""),
        exclude_signals=frozenset(str(s) for s in (data.get("exclude_signals") or [])),
        exclude_timing_wait=bool(data.get("exclude_timing_wait")),
        min_conviction=float(data.get("min_conviction") or 0),
        require_effective_buy_tier=bool(data.get("require_effective_buy_tier")),
        require_research_accumulate=bool(data.get("require_research_accumulate")),
        min_data_quality=float(data.get("min_data_quality") or 0),
    )


@dataclass
class ExclusionUniverseArchiveConfig:
    universe_mode: str = UNIVERSE_BUY_TIER_ONLY
    ladder: tuple[ExclusionStep, ...] = ()
    use_adjusted_signal: bool = False
    resolve_research_pit: bool = True
    skip_timing_wait_default: bool = True
    max_positions: int = DEFAULT_MAX_POSITIONS
    min_filtered_pool: int = DEFAULT_MIN_FILTERED_POOL
    min_week_pairs: int = DEFAULT_MIN_WEEK_PAIRS
    bottom_quartile_fraction: float = 0.25
    top_quartile_fraction: float = 0.25


def default_exclusion_ladder(*, include_ai_overlay_steps: bool = True) -> tuple[ExclusionStep, ...]:
    """Graduated tightening ladder — each step is cumulative (full state at rung)."""
    steps: list[ExclusionStep] = [
        ExclusionStep("u0", "Baseline universe"),
        ExclusionStep("u1", "Exclude avoid", exclude_signals=frozenset({"avoid"})),
        ExclusionStep(
            "u2",
            "Exclude avoid + timing wait",
            exclude_signals=frozenset({"avoid"}),
            exclude_timing_wait=True,
        ),
        ExclusionStep(
            "u3",
            "… + conviction >= 0.25",
            exclude_signals=frozenset({"avoid"}),
            exclude_timing_wait=True,
            min_conviction=0.25,
        ),
        ExclusionStep(
            "u4",
            "… + conviction >= 0.35",
            exclude_signals=frozenset({"avoid"}),
            exclude_timing_wait=True,
            min_conviction=0.35,
        ),
        ExclusionStep(
            "u5",
            "… + conviction >= 0.45",
            exclude_signals=frozenset({"avoid"}),
            exclude_timing_wait=True,
            min_conviction=0.45,
        ),
    ]
    if include_ai_overlay_steps:
        steps.extend(
            [
                ExclusionStep(
                    "u6",
                    "… + effective buy-tier (overlay)",
                    exclude_signals=frozenset({"avoid"}),
                    exclude_timing_wait=True,
                    min_conviction=0.35,
                    require_effective_buy_tier=True,
                ),
                ExclusionStep(
                    "u7",
                    "… + research accumulate",
                    exclude_signals=frozenset({"avoid"}),
                    exclude_timing_wait=True,
                    min_conviction=0.35,
                    require_effective_buy_tier=True,
                    require_research_accumulate=True,
                ),
            ]
        )
    return tuple(steps)


def _effective_signal(row: dict[str, Any]) -> str:
    adjusted = str(row.get("adjusted_signal") or "").strip()
    if adjusted:
        return adjusted
    return str(row.get("signal") or "hold").strip()


def _resolve_row_fields(
    output_dir: Path,
    entry: RunSnapshot,
    row: dict[str, Any],
    *,
    use_adjusted_signal: bool,
    resolve_research_pit: bool,
) -> dict[str, Any]:
    """Return row enriched with PIT effective signal and research verdict when needed."""
    ticker = str(row.get("ticker") or "").strip()
    screen_signal = str(row.get("signal") or "hold").strip()
    effective = _effective_signal(row) if use_adjusted_signal else screen_signal
    verdict = row.get("research_verdict")
    verdict_str = str(verdict).strip() if verdict is not None and str(verdict).strip() else None

    if (
        use_adjusted_signal
        and resolve_research_pit
        and not str(row.get("adjusted_signal") or "").strip()
    ):
        from value_investor.backtest import _parse_run_at
        from value_investor.historical_analysis import _resolve_overlay_fields

        run_at = _parse_run_at(entry.run_at)
        effective, verdict_str = _resolve_overlay_fields(
            output_dir=output_dir,
            ticker=ticker,
            run_at=run_at,
            row=row,
        )

    return {
        **row,
        "screen_signal": screen_signal,
        "effective_signal": effective,
        "research_verdict": verdict_str,
    }


def _in_baseline_universe(
    enriched: dict[str, Any],
    *,
    universe_mode: str,
    entry: RunSnapshot,
) -> bool:
    ticker = str(enriched.get("ticker") or "").strip()
    if not ticker:
        return False
    price = entry.prices.get(ticker)
    if price is None or float(price) <= 0:
        return False
    if universe_mode == UNIVERSE_BUY_TIER_ONLY:
        screen = str(enriched.get("screen_signal") or "").strip().lower()
        return screen in BUY_SIGNALS
    return True


def _passes_exclusion_step(enriched: dict[str, Any], step: ExclusionStep) -> bool:
    effective = str(enriched.get("effective_signal") or "hold").strip().lower()
    screen = str(enriched.get("screen_signal") or "hold").strip().lower()

    if effective in step.exclude_signals or screen in step.exclude_signals:
        return False

    if step.exclude_timing_wait:
        timing = str(enriched.get("timing_signal") or "").strip().lower()
        if timing == "wait":
            return False

    conviction = float(enriched.get("conviction_score") or 0)
    if conviction < float(step.min_conviction):
        return False

    dq = enriched.get("data_quality_score")
    if step.min_data_quality > 0:
        if dq is None or float(dq) < float(step.min_data_quality):
            return False

    if step.require_effective_buy_tier and effective not in BUY_SIGNALS:
        return False

    if step.require_research_accumulate:
        verdict = str(enriched.get("research_verdict") or "").strip().lower()
        if verdict != "accumulate":
            return False

    return True


def _equal_weight_forward_return(
    tickers: list[str],
    entry: RunSnapshot,
    exit_snap: RunSnapshot,
) -> tuple[float | None, int]:
    returns: list[float] = []
    for ticker in tickers:
        p0 = entry.prices.get(ticker)
        p1 = exit_snap.prices.get(ticker)
        if p0 is None or p1 is None or float(p0) <= 0:
            continue
        returns.append((float(p1) / float(p0)) - 1.0)
    if not returns:
        return None, 0
    return sum(returns) / len(returns), len(returns)


def _top_conviction_tickers(rows: list[dict[str, Any]], max_positions: int) -> list[str]:
    ranked = sorted(
        rows,
        key=lambda row: float(row.get("conviction_score") or 0),
        reverse=True,
    )
    tickers: list[str] = []
    for row in ranked[: max(0, int(max_positions))]:
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            tickers.append(ticker)
    return tickers


def _quartile_tickers(
    ticker_returns: dict[str, float],
    *,
    fraction: float,
    bottom: bool,
) -> list[str]:
    if not ticker_returns:
        return []
    ranked = sorted(ticker_returns.items(), key=lambda item: item[1], reverse=not bottom)
    count = max(1, int(len(ranked) * fraction))
    return [ticker for ticker, _ in ranked[:count]]


def _hindsight_eval(
    baseline_tickers: list[str],
    filtered_tickers: list[str],
    ticker_returns: dict[str, float],
    *,
    bottom_fraction: float,
    top_fraction: float,
) -> dict[str, Any]:
    filtered_set = set(filtered_tickers)
    baseline_set = set(baseline_tickers)
    universe_returns = {t: ticker_returns[t] for t in baseline_set if t in ticker_returns}
    if not universe_returns:
        return {
            "observation_count": 0,
            "bottom_quartile_exclude_rate": None,
            "bottom_quartile_retained_rate": None,
            "top_quartile_retain_rate": None,
            "note": "No forward returns for hindsight eval",
        }

    bottom = _quartile_tickers(universe_returns, fraction=bottom_fraction, bottom=True)
    top = _quartile_tickers(universe_returns, fraction=top_fraction, bottom=False)
    bottom_excluded = [t for t in bottom if t not in filtered_set]
    bottom_retained = [t for t in bottom if t in filtered_set]
    top_retained = [t for t in top if t in filtered_set]

    return {
        "observation_count": len(universe_returns),
        "bottom_quartile": bottom,
        "top_quartile": top,
        "bottom_quartile_excluded": bottom_excluded,
        "bottom_quartile_retained": bottom_retained,
        "bottom_quartile_exclude_rate": (
            round(len(bottom_excluded) / len(bottom), 4) if bottom else None
        ),
        "bottom_quartile_retained_rate": (
            round(len(bottom_retained) / len(bottom), 4) if bottom else None
        ),
        "top_quartile_retain_rate": round(len(top_retained) / len(top), 4) if top else None,
        "note": "Hindsight only — quartiles from forward returns, not used to define exclusions",
    }


def _summarize_weekly_deltas(weekly: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in weekly if row.get("exclusion_alpha") is not None]
    if not valid:
        return {
            "week_pairs": 0,
            "mean_weekly_exclusion_alpha": None,
            "cumulative_exclusion_alpha": None,
            "positive_alpha_weeks": 0,
            "positive_alpha_rate": None,
            "median_weekly_alpha": None,
            "avg_baseline_pool_size": None,
            "avg_filtered_pool_size": None,
            "min_filtered_pool_size": None,
            "pool_reduction_pct": None,
        }

    alphas = [float(row["exclusion_alpha"]) for row in valid]
    baseline_sizes = [int(row.get("baseline_pool_size") or 0) for row in valid]
    filtered_sizes = [int(row.get("filtered_pool_size") or 0) for row in valid]
    positive = sum(1 for alpha in alphas if alpha > 0)
    avg_baseline = sum(baseline_sizes) / len(baseline_sizes) if baseline_sizes else 0.0
    avg_filtered = sum(filtered_sizes) / len(filtered_sizes) if filtered_sizes else 0.0
    pool_reduction = (avg_baseline - avg_filtered) / avg_baseline if avg_baseline > 0 else None

    return {
        "week_pairs": len(valid),
        "mean_weekly_exclusion_alpha": round(sum(alphas) / len(alphas), 6),
        "cumulative_exclusion_alpha": round(sum(alphas), 6),
        "positive_alpha_weeks": positive,
        "positive_alpha_rate": round(positive / len(valid), 4),
        "median_weekly_alpha": round(median(alphas), 6),
        "avg_baseline_pool_size": round(avg_baseline, 2),
        "avg_filtered_pool_size": round(avg_filtered, 2),
        "min_filtered_pool_size": min(filtered_sizes) if filtered_sizes else None,
        "pool_reduction_pct": None if pool_reduction is None else round(pool_reduction, 4),
    }


def _summarize_book_deltas(weekly: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [
        row
        for row in weekly
        if row.get("book_alpha_vs_baseline") is not None
        and row.get("filtered_book_return") is not None
    ]
    if not valid:
        return {
            "week_pairs": 0,
            "mean_book_alpha_vs_baseline": None,
            "cumulative_book_alpha_vs_baseline": None,
            "mean_book_alpha_vs_filtered_ew": None,
        }
    vs_baseline = [float(row["book_alpha_vs_baseline"]) for row in valid]
    vs_filtered = [
        float(row["book_alpha_vs_filtered_ew"])
        for row in valid
        if row.get("book_alpha_vs_filtered_ew") is not None
    ]
    return {
        "week_pairs": len(valid),
        "mean_book_alpha_vs_baseline": round(sum(vs_baseline) / len(vs_baseline), 6),
        "cumulative_book_alpha_vs_baseline": round(sum(vs_baseline), 6),
        "mean_book_alpha_vs_filtered_ew": (
            round(sum(vs_filtered) / len(vs_filtered), 6) if vs_filtered else None
        ),
    }


def _pick_recommended_step(
    ladder_results: list[dict[str, Any]],
    *,
    min_filtered_pool: int,
    min_week_pairs: int,
) -> dict[str, Any] | None:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in ladder_results:
        summary = row.get("summary") or {}
        week_pairs = int(summary.get("week_pairs") or 0)
        if week_pairs < min_week_pairs:
            continue
        avg_pool = summary.get("avg_filtered_pool_size")
        if avg_pool is None or float(avg_pool) < float(min_filtered_pool):
            continue
        cumulative = summary.get("cumulative_exclusion_alpha")
        if cumulative is None:
            continue
        positive_rate = float(summary.get("positive_alpha_rate") or 0)
        score = float(cumulative) + 0.01 * positive_rate
        candidates.append((score, row))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best = candidates[0][1]
    return {
        "step_id": best.get("step_id"),
        "label": best.get("label"),
        "cumulative_exclusion_alpha": (best.get("summary") or {}).get("cumulative_exclusion_alpha"),
        "positive_alpha_rate": (best.get("summary") or {}).get("positive_alpha_rate"),
        "avg_filtered_pool_size": (best.get("summary") or {}).get("avg_filtered_pool_size"),
        "selection_note": (
            f"Highest cumulative exclusion alpha among steps with "
            f">={min_week_pairs} week pairs and avg pool >={min_filtered_pool}"
        ),
    }


def archive_sim_metadata() -> dict[str, Any]:
    return {
        "scope": ARCHIVE_TRACK_ID,
        "observe_only": True,
        "comparison": "equal_weight_universe vs equal_weight_universe_minus_exclusions",
        "pit_exclusions": True,
        "hindsight_quartiles": "evaluation_only",
        "costs_included": False,
        "note": (
            "Archive exclusion-universe lab — graduated tightening ladders on weekly "
            "screen snapshots. Pair with rebalance_log replay before live knob promotion."
        ),
    }


def run_exclusion_universe_archive_sim(
    output_dir: Path,
    *,
    config: ExclusionUniverseArchiveConfig | None = None,
) -> dict[str, Any]:
    """Score exclusion ladders via consecutive weekly snapshot pairs."""
    cfg = config or ExclusionUniverseArchiveConfig()
    output_dir = Path(output_dir)
    universe_mode = str(cfg.universe_mode or UNIVERSE_BUY_TIER_ONLY)
    if universe_mode not in VALID_UNIVERSE_MODES:
        universe_mode = UNIVERSE_BUY_TIER_ONLY

    ladder = cfg.ladder
    if not ladder:
        ladder = default_exclusion_ladder(include_ai_overlay_steps=cfg.use_adjusted_signal)
    snapshots = load_run_snapshots(output_dir)

    if len(snapshots) < 2:
        review = {
            "schema_version": 1,
            "scope": ARCHIVE_TRACK_ID,
            "track_id": ARCHIVE_TRACK_ID,
            "generated_at": datetime.now(UTC).isoformat(),
            "framework": archive_sim_metadata(),
            "snapshot_count": len(snapshots),
            "universe_mode": universe_mode,
            "ladder": [step.to_dict() for step in ladder],
            "ladder_results": [],
            "readiness": {
                "ready_for_priors": False,
                "reason": "Need at least 2 archived run snapshots (ftse-archive-history).",
            },
            "note": "Insufficient archive history.",
        }
        _write_artifacts(output_dir, {"ladder_results": []}, review)
        return review

    ladder_results: list[dict[str, Any]] = []
    for step in ladder:
        weekly_rows: list[dict[str, Any]] = []
        hindsight_rows: list[dict[str, Any]] = []

        for entry, exit_snap in zip(snapshots, snapshots[1:], strict=False):
            enriched_rows = [
                _resolve_row_fields(
                    output_dir,
                    entry,
                    row,
                    use_adjusted_signal=cfg.use_adjusted_signal,
                    resolve_research_pit=cfg.resolve_research_pit,
                )
                for row in entry.signals
                if isinstance(row, dict)
            ]

            baseline_rows = [
                row
                for row in enriched_rows
                if _in_baseline_universe(row, universe_mode=universe_mode, entry=entry)
            ]
            filtered_rows = [row for row in baseline_rows if _passes_exclusion_step(row, step)]

            baseline_tickers = [str(row["ticker"]) for row in baseline_rows]
            filtered_tickers = [str(row["ticker"]) for row in filtered_rows]

            baseline_ret, baseline_n = _equal_weight_forward_return(
                baseline_tickers, entry, exit_snap
            )
            filtered_ret, filtered_n = _equal_weight_forward_return(
                filtered_tickers, entry, exit_snap
            )

            book_tickers = _top_conviction_tickers(filtered_rows, cfg.max_positions)
            book_ret, book_n = _equal_weight_forward_return(book_tickers, entry, exit_snap)

            exclusion_alpha = None
            if baseline_ret is not None and filtered_ret is not None:
                exclusion_alpha = filtered_ret - baseline_ret

            book_alpha_vs_baseline = None
            book_alpha_vs_filtered_ew = None
            if book_ret is not None and baseline_ret is not None:
                book_alpha_vs_baseline = book_ret - baseline_ret
            if book_ret is not None and filtered_ret is not None:
                book_alpha_vs_filtered_ew = book_ret - filtered_ret

            ticker_returns: dict[str, float] = {}
            for ticker in baseline_tickers:
                p0 = entry.prices.get(ticker)
                p1 = exit_snap.prices.get(ticker)
                if p0 is None or p1 is None or float(p0) <= 0:
                    continue
                ticker_returns[ticker] = (float(p1) / float(p0)) - 1.0

            hindsight = _hindsight_eval(
                baseline_tickers,
                filtered_tickers,
                ticker_returns,
                bottom_fraction=cfg.bottom_quartile_fraction,
                top_fraction=cfg.top_quartile_fraction,
            )
            hindsight_rows.append(hindsight)

            bench_entry = entry.prices.get(BENCHMARK_TICKER)
            bench_exit = exit_snap.prices.get(BENCHMARK_TICKER)
            benchmark_return = None
            if bench_entry and bench_exit and float(bench_entry) > 0:
                benchmark_return = (float(bench_exit) / float(bench_entry)) - 1.0

            weekly_rows.append(
                {
                    "run_at": entry.run_at,
                    "exit_run_at": exit_snap.run_at,
                    "baseline_pool_size": baseline_n,
                    "filtered_pool_size": filtered_n,
                    "book_pool_size": book_n,
                    "excluded_count": max(0, baseline_n - filtered_n),
                    "baseline_ew_return": None if baseline_ret is None else round(baseline_ret, 6),
                    "filtered_ew_return": None if filtered_ret is None else round(filtered_ret, 6),
                    "book_top_n_return": None if book_ret is None else round(book_ret, 6),
                    "exclusion_alpha": (
                        None if exclusion_alpha is None else round(exclusion_alpha, 6)
                    ),
                    "book_alpha_vs_baseline": (
                        None if book_alpha_vs_baseline is None else round(book_alpha_vs_baseline, 6)
                    ),
                    "book_alpha_vs_filtered_ew": (
                        None
                        if book_alpha_vs_filtered_ew is None
                        else round(book_alpha_vs_filtered_ew, 6)
                    ),
                    "benchmark_return": (
                        None if benchmark_return is None else round(benchmark_return, 6)
                    ),
                    "hindsight": hindsight,
                }
            )

        summary = _summarize_weekly_deltas(weekly_rows)
        book_summary = _summarize_book_deltas(weekly_rows)

        bottom_exclude_rates = [
            float(row["bottom_quartile_exclude_rate"])
            for row in hindsight_rows
            if row.get("bottom_quartile_exclude_rate") is not None
        ]
        top_retain_rates = [
            float(row["top_quartile_retain_rate"])
            for row in hindsight_rows
            if row.get("top_quartile_retain_rate") is not None
        ]
        hindsight_summary = {
            "week_pairs": len(hindsight_rows),
            "mean_bottom_quartile_exclude_rate": (
                round(sum(bottom_exclude_rates) / len(bottom_exclude_rates), 4)
                if bottom_exclude_rates
                else None
            ),
            "mean_top_quartile_retain_rate": (
                round(sum(top_retain_rates) / len(top_retain_rates), 4)
                if top_retain_rates
                else None
            ),
            "note": "Evaluation only — quartiles from realized forward returns",
        }

        ladder_results.append(
            {
                "step_id": step.step_id,
                "label": step.label,
                "step": step.to_dict(),
                "summary": summary,
                "book_summary": book_summary,
                "hindsight_summary": hindsight_summary,
                "weekly": weekly_rows,
            }
        )

    recommended = _pick_recommended_step(
        ladder_results,
        min_filtered_pool=cfg.min_filtered_pool,
        min_week_pairs=cfg.min_week_pairs,
    )
    max_week_pairs = max(
        (int((row.get("summary") or {}).get("week_pairs") or 0) for row in ladder_results),
        default=0,
    )
    readiness = {
        "ready_for_priors": bool(recommended and max_week_pairs >= cfg.min_week_pairs),
        "week_pairs": max_week_pairs,
        "min_week_pairs": cfg.min_week_pairs,
        "min_filtered_pool": cfg.min_filtered_pool,
        "recommended_step": recommended,
    }

    store = {
        "schema_version": 1,
        "scope": ARCHIVE_TRACK_ID,
        "track_id": ARCHIVE_TRACK_ID,
        "framework": archive_sim_metadata(),
        "generated_at": datetime.now(UTC).isoformat(),
        "snapshot_count": len(snapshots),
        "universe_mode": universe_mode,
        "config": {
            "use_adjusted_signal": cfg.use_adjusted_signal,
            "resolve_research_pit": cfg.resolve_research_pit,
            "max_positions": cfg.max_positions,
            "min_filtered_pool": cfg.min_filtered_pool,
            "min_week_pairs": cfg.min_week_pairs,
        },
        "ladder": [step.to_dict() for step in ladder],
        "ladder_results": [
            {
                "step_id": row["step_id"],
                "label": row["label"],
                "step": row["step"],
                "summary": row["summary"],
                "book_summary": row["book_summary"],
                "hindsight_summary": row["hindsight_summary"],
                "weekly": row.get("weekly") or [],
            }
            for row in ladder_results
        ],
        "recommended_step": recommended,
        "updated_at": datetime.now(UTC).isoformat(),
    }

    review = {
        **store,
        "readiness": readiness,
        "note": (
            "Exclusion-universe archive sim (observe-only). Positive exclusion_alpha means "
            "the filtered equal-weight universe beat the baseline universe gross of costs. "
            "Use recommended_step as a prior for offline_sim / paper_knobs — not auto-apply."
        ),
    }
    _write_artifacts(output_dir, store, review)
    return review


def _write_artifacts(output_dir: Path, store: dict[str, Any], review: dict[str, Any]) -> None:
    cohorts_path = output_dir / COHORTS_FILENAME
    review_path = output_dir / REVIEW_FILENAME
    cohorts_path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")


def format_exclusion_universe_text(review: dict[str, Any]) -> str:
    lines = [
        "Exclusion-universe archive sim (observe-only)",
        f"  Snapshots: {review.get('snapshot_count', 0)}",
        f"  Universe: {review.get('universe_mode', '—')}",
        f"  Week pairs: {(review.get('readiness') or {}).get('week_pairs', 0)}",
    ]
    recommended = review.get("recommended_step")
    if recommended:
        lines.append(
            f"  Recommended step: {recommended.get('step_id')} — {recommended.get('label')} "
            f"(cum alpha {recommended.get('cumulative_exclusion_alpha'):+.4f})"
        )
    else:
        lines.append("  Recommended step: — (insufficient history or no qualifying rung)")

    lines.append("  Ladder summary:")
    for row in review.get("ladder_results") or []:
        summary = row.get("summary") or {}
        hindsight = row.get("hindsight_summary") or {}
        cum = summary.get("cumulative_exclusion_alpha")
        cum_s = f"{cum:+.4f}" if cum is not None else "n/a"
        excl = hindsight.get("mean_bottom_quartile_exclude_rate")
        excl_s = f"{excl:.1%}" if excl is not None else "n/a"
        lines.append(
            f"    {row.get('step_id')}: {row.get('label')} | "
            f"cum α {cum_s} | pool {summary.get('avg_filtered_pool_size', '—')} | "
            f"bottom-q exclude {excl_s}"
        )

    note = review.get("note")
    if note:
        lines.append(f"  Note: {note}")
    return "\n".join(lines)


__all__ = [
    "ARCHIVE_TRACK_ID",
    "COHORTS_FILENAME",
    "REVIEW_FILENAME",
    "ExclusionStep",
    "ExclusionUniverseArchiveConfig",
    "archive_sim_metadata",
    "default_exclusion_ladder",
    "exclusion_step_from_dict",
    "format_exclusion_universe_text",
    "run_exclusion_universe_archive_sim",
]
