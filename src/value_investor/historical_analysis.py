"""Point-in-time historical analysis of screen + research recommendations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.backtest import (
    BENCHMARK_TICKER,
    HORIZON_DAYS,
    RunSnapshot,
    _find_exit_snapshot,
    _parse_run_at,
    load_run_snapshots,
)
from value_investor.model_weights import load_model_snapshot_for_run
from value_investor.research.timeline import get_research_as_of
from value_investor.research.verdict import compute_adjusted_signal

logger = logging.getLogger(__name__)

MAX_HISTORY_YEARS = 3
DEFAULT_SMOOTHING_WEEKS = 4
BUY_SIGNALS = frozenset({"strong_buy", "buy"})


@dataclass
class HistoricalAnalysisConfig:
    max_years: int = MAX_HISTORY_YEARS
    horizon_days: tuple[int, ...] = HORIZON_DAYS
    smoothing_weeks: int = DEFAULT_SMOOTHING_WEEKS
    min_observations: int = 3


@dataclass
class HistoricalObservation:
    run_at: str
    week_key: str
    ticker: str
    horizon_days: int
    forward_return: float
    benchmark_return: float
    excess_return: float
    screen_signal: str
    adjusted_signal: str
    research_verdict: str | None
    weighted_model_score: float | None
    models_passed: int | None

    def strategy_tags(self) -> list[str]:
        tags = [f"screen:{self.screen_signal}"]
        tags.append(f"overlay:{self.adjusted_signal}")
        if self.research_verdict:
            tags.append(f"research:{self.research_verdict}")
        if (
            self.screen_signal in BUY_SIGNALS
            and self.adjusted_signal not in BUY_SIGNALS
            and self.research_verdict
        ):
            tags.append("research:downgraded")
        return tags


@dataclass
class StrategyHorizonResult:
    strategy: str
    horizon_days: int
    raw_avg_return: float
    raw_excess_return: float
    smoothed_avg_return: float
    smoothed_excess_return: float
    count: int
    observation_weeks: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "horizon_days": self.horizon_days,
            "raw_avg_return": round(self.raw_avg_return, 4),
            "raw_excess_return": round(self.raw_excess_return, 4),
            "smoothed_avg_return": round(self.smoothed_avg_return, 4),
            "smoothed_excess_return": round(self.smoothed_excess_return, 4),
            "count": self.count,
            "observation_weeks": self.observation_weeks,
        }


@dataclass
class ModelAttributionResult:
    model_id: str
    horizon_days: int
    raw_correlation: float | None
    smoothed_correlation: float | None
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "horizon_days": self.horizon_days,
            "raw_correlation": (
                round(self.raw_correlation, 4) if self.raw_correlation is not None else None
            ),
            "smoothed_correlation": (
                round(self.smoothed_correlation, 4)
                if self.smoothed_correlation is not None
                else None
            ),
            "sample_count": self.sample_count,
        }


@dataclass
class OverlayComparison:
    horizon_days: int
    screen_excess_return: float
    overlay_excess_return: float
    smoothed_screen_excess: float
    smoothed_overlay_excess: float
    downgrade_count: int
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon_days": self.horizon_days,
            "screen_excess_return": round(self.screen_excess_return, 4),
            "overlay_excess_return": round(self.overlay_excess_return, 4),
            "smoothed_screen_excess": round(self.smoothed_screen_excess, 4),
            "smoothed_overlay_excess": round(self.smoothed_overlay_excess, 4),
            "downgrade_count": self.downgrade_count,
            "sample_count": self.sample_count,
        }


@dataclass
class HistoricalAnalysisSummary:
    run_count: int
    window_start: str | None
    window_end: str | None
    max_years: int
    smoothing_weeks: int
    strategy_horizons: list[StrategyHorizonResult] = field(default_factory=list)
    model_attribution: list[ModelAttributionResult] = field(default_factory=list)
    overlay_comparison: list[OverlayComparison] = field(default_factory=list)
    weekly_series: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_count": self.run_count,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "max_years": self.max_years,
            "smoothing_weeks": self.smoothing_weeks,
            "strategy_horizons": [item.to_dict() for item in self.strategy_horizons],
            "model_attribution": [item.to_dict() for item in self.model_attribution],
            "overlay_comparison": [item.to_dict() for item in self.overlay_comparison],
            "weekly_series": self.weekly_series,
            "note": self.note,
        }

    def has_results(self) -> bool:
        return bool(self.strategy_horizons)


def historical_analysis_summary_from_dict(data: dict[str, Any]) -> HistoricalAnalysisSummary:
    return HistoricalAnalysisSummary(
        run_count=int(data.get("run_count", 0)),
        window_start=data.get("window_start"),
        window_end=data.get("window_end"),
        max_years=int(data.get("max_years", MAX_HISTORY_YEARS)),
        smoothing_weeks=int(data.get("smoothing_weeks", DEFAULT_SMOOTHING_WEEKS)),
        strategy_horizons=[StrategyHorizonResult(**item) for item in data.get("strategy_horizons", [])],
        model_attribution=[ModelAttributionResult(**item) for item in data.get("model_attribution", [])],
        overlay_comparison=[OverlayComparison(**item) for item in data.get("overlay_comparison", [])],
        weekly_series=list(data.get("weekly_series", [])),
        note=str(data.get("note", "")),
    )


def load_historical_analysis_summary(output_dir: Path) -> HistoricalAnalysisSummary | None:
    path = output_dir / "historical_analysis_summary.json"
    if not path.exists():
        return None
    return historical_analysis_summary_from_dict(json.loads(path.read_text(encoding="utf-8")))


def _week_key(run_at: datetime) -> str:
    year, week, _ = run_at.isocalendar()
    return f"{year}-W{week:02d}"


def _rolling_mean(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    smoothed: list[float] = []
    for index in range(len(values)):
        start = max(0, index - window + 1)
        chunk = values[start : index + 1]
        smoothed.append(sum(chunk) / len(chunk))
    return smoothed


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _filter_snapshots(
    snapshots: list[RunSnapshot],
    *,
    max_years: int,
    reference: datetime | None = None,
) -> list[RunSnapshot]:
    if not snapshots:
        return []
    ref = reference or datetime.now(UTC)
    cutoff = ref - timedelta(days=max_years * 365)
    return [snap for snap in snapshots if _parse_run_at(snap.run_at) >= cutoff]


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_overlay_fields(
    *,
    output_dir: Path,
    ticker: str,
    run_at: datetime,
    row: dict[str, Any],
) -> tuple[str, str | None]:
    screen_signal = str(row.get("signal") or "hold")
    stored_adjusted = row.get("adjusted_signal")
    stored_verdict = row.get("research_verdict")

    if stored_adjusted is not None and str(stored_adjusted).strip():
        adjusted = str(stored_adjusted)
        verdict = str(stored_verdict) if stored_verdict is not None else None
        return adjusted, verdict

    doc = get_research_as_of(output_dir, ticker, run_at)
    if doc is None or not doc.research_verdict:
        return screen_signal, None
    return compute_adjusted_signal(screen_signal, doc.research_verdict), doc.research_verdict


def _build_observations(
    *,
    output_dir: Path,
    snapshots: list[RunSnapshot],
    horizon_days: int,
) -> list[HistoricalObservation]:
    observations: list[HistoricalObservation] = []
    for entry in snapshots[:-1]:
        exit_snap = _find_exit_snapshot(entry, snapshots, horizon_days)
        if exit_snap is None:
            continue

        entry_at = _parse_run_at(entry.run_at)
        week = _week_key(entry_at)
        bench_entry = entry.prices.get(BENCHMARK_TICKER)
        bench_exit = exit_snap.prices.get(BENCHMARK_TICKER)
        benchmark_return = 0.0
        if bench_entry and bench_exit and bench_entry > 0:
            benchmark_return = (bench_exit - bench_entry) / bench_entry

        for row in entry.signals:
            ticker = str(row["ticker"])
            p0 = entry.prices.get(ticker)
            p1 = exit_snap.prices.get(ticker)
            if p0 is None or p1 is None or p0 <= 0:
                continue

            screen_signal = str(row.get("signal") or "hold")
            adjusted_signal, research_verdict = _resolve_overlay_fields(
                output_dir=output_dir,
                ticker=ticker,
                run_at=entry_at,
                row=row,
            )

            forward_return = (p1 - p0) / p0
            observations.append(
                HistoricalObservation(
                    run_at=entry.run_at,
                    week_key=week,
                    ticker=ticker,
                    horizon_days=horizon_days,
                    forward_return=forward_return,
                    benchmark_return=benchmark_return,
                    excess_return=forward_return - benchmark_return,
                    screen_signal=screen_signal,
                    adjusted_signal=adjusted_signal,
                    research_verdict=research_verdict,
                    weighted_model_score=_float_or_none(row.get("weighted_model_score")),
                    models_passed=_int_or_none(row.get("models_passed")),
                )
            )
    return observations


def _weekly_excess_by_strategy(
    observations: list[HistoricalObservation],
) -> dict[str, dict[str, float]]:
    buckets: dict[str, dict[str, list[float]]] = {}
    for obs in observations:
        for tag in obs.strategy_tags():
            buckets.setdefault(tag, {}).setdefault(obs.week_key, []).append(obs.excess_return)

    return {
        strategy: {
            week: sum(values) / len(values)
            for week, values in sorted(week_map.items())
        }
        for strategy, week_map in buckets.items()
    }


def _strategy_results(
    observations: list[HistoricalObservation],
    *,
    horizon_days: int,
    smoothing_weeks: int,
    min_observations: int,
) -> list[StrategyHorizonResult]:
    by_strategy: dict[str, list[HistoricalObservation]] = {}
    for obs in observations:
        for tag in obs.strategy_tags():
            by_strategy.setdefault(tag, []).append(obs)

    weekly_excess = _weekly_excess_by_strategy(observations)
    results: list[StrategyHorizonResult] = []

    for strategy, items in sorted(by_strategy.items()):
        if len(items) < min_observations:
            continue
        raw_avg = sum(item.forward_return for item in items) / len(items)
        raw_excess = sum(item.excess_return for item in items) / len(items)
        week_map = weekly_excess.get(strategy, {})
        ordered = [week_map[week] for week in sorted(week_map.keys())]
        smoothed_weeks = _rolling_mean(ordered, smoothing_weeks)
        smoothed_excess = smoothed_weeks[-1] if smoothed_weeks else raw_excess
        smoothed_avg = raw_avg - raw_excess + smoothed_excess
        results.append(
            StrategyHorizonResult(
                strategy=strategy,
                horizon_days=horizon_days,
                raw_avg_return=raw_avg,
                raw_excess_return=raw_excess,
                smoothed_avg_return=smoothed_avg,
                smoothed_excess_return=smoothed_excess,
                count=len(items),
                observation_weeks=len(week_map),
            )
        )
    return results


def _overlay_comparisons(
    observations: list[HistoricalObservation],
    *,
    horizon_days: int,
    smoothing_weeks: int,
) -> list[OverlayComparison]:
    if not observations:
        return []

    screen_items = [obs for obs in observations if obs.screen_signal in BUY_SIGNALS]
    overlay_items = [
        obs for obs in screen_items if obs.adjusted_signal in BUY_SIGNALS
    ]
    downgrade_count = sum(
        1 for obs in screen_items if obs.adjusted_signal not in BUY_SIGNALS and obs.research_verdict
    )

    screen_weekly: dict[str, list[float]] = {}
    overlay_weekly: dict[str, list[float]] = {}
    for obs in screen_items:
        screen_weekly.setdefault(obs.week_key, []).append(obs.excess_return)
    for obs in overlay_items:
        overlay_weekly.setdefault(obs.week_key, []).append(obs.excess_return)

    weeks = sorted(screen_weekly.keys())
    if not weeks:
        return []

    screen_series = [sum(screen_weekly[w]) / len(screen_weekly[w]) for w in weeks]
    overlay_series = [
        sum(overlay_weekly[w]) / len(overlay_weekly[w]) if overlay_weekly.get(w) else screen_series[i]
        for i, w in enumerate(weeks)
    ]
    screen_smoothed = _rolling_mean(screen_series, smoothing_weeks)
    overlay_smoothed = _rolling_mean(overlay_series, smoothing_weeks)

    screen_excess = sum(obs.excess_return for obs in screen_items) / len(screen_items)
    overlay_excess = (
        sum(obs.excess_return for obs in overlay_items) / len(overlay_items) if overlay_items else 0.0
    )

    return [
        OverlayComparison(
            horizon_days=horizon_days,
            screen_excess_return=screen_excess,
            overlay_excess_return=overlay_excess,
            smoothed_screen_excess=screen_smoothed[-1] if screen_smoothed else 0.0,
            smoothed_overlay_excess=overlay_smoothed[-1] if overlay_smoothed else 0.0,
            downgrade_count=downgrade_count,
            sample_count=len(screen_items),
        )
    ]


def _model_attribution(
    *,
    output_dir: Path,
    snapshots: list[RunSnapshot],
    horizon_days: int,
    smoothing_weeks: int,
) -> list[ModelAttributionResult]:
    scores_by_model_week: dict[str, dict[str, list[tuple[float, float]]]] = {}

    for entry in snapshots[:-1]:
        exit_snap = _find_exit_snapshot(entry, snapshots, horizon_days)
        if exit_snap is None:
            continue

        entry_at = _parse_run_at(entry.run_at)
        week = _week_key(entry_at)
        model_rows = load_model_snapshot_for_run(output_dir, entry.run_at)
        if not model_rows:
            continue

        returns_by_ticker: dict[str, float] = {}
        for row in entry.signals:
            ticker = str(row["ticker"])
            p0 = entry.prices.get(ticker)
            p1 = exit_snap.prices.get(ticker)
            if p0 is None or p1 is None or p0 <= 0:
                continue
            returns_by_ticker[ticker] = (p1 - p0) / p0

        for model_row in model_rows:
            ticker = str(model_row["ticker"])
            if ticker not in returns_by_ticker:
                continue
            model_id = str(model_row["model_id"])
            score = float(model_row.get("score") or 0)
            scores_by_model_week.setdefault(model_id, {}).setdefault(week, []).append(
                (score, returns_by_ticker[ticker])
            )

    results: list[ModelAttributionResult] = []
    for model_id, weeks in sorted(scores_by_model_week.items()):
        ordered_weeks = sorted(weeks.keys())
        weekly_correlations: list[float] = []
        all_scores: list[float] = []
        all_returns: list[float] = []

        for week in ordered_weeks:
            pairs = weeks[week]
            xs = [pair[0] for pair in pairs]
            ys = [pair[1] for pair in pairs]
            all_scores.extend(xs)
            all_returns.extend(ys)
            corr = _pearson(xs, ys)
            if corr is not None:
                weekly_correlations.append(corr)

        raw_corr = _pearson(all_scores, all_returns)
        smoothed = _rolling_mean(weekly_correlations, smoothing_weeks)
        results.append(
            ModelAttributionResult(
                model_id=model_id,
                horizon_days=horizon_days,
                raw_correlation=raw_corr,
                smoothed_correlation=smoothed[-1] if smoothed else raw_corr,
                sample_count=len(all_scores),
            )
        )

    results.sort(
        key=lambda item: item.smoothed_correlation or item.raw_correlation or -999,
        reverse=True,
    )
    return results[:15]


def run_historical_analysis(
    output_dir: Path,
    *,
    snapshots: list[RunSnapshot] | None = None,
    config: HistoricalAnalysisConfig | None = None,
) -> HistoricalAnalysisSummary:
    """
    Replay archived weekly runs with point-in-time research and model scores.

    Applies rolling-week smoothing to dampen short-term noise in weekly cohorts.
    """
    config = config or HistoricalAnalysisConfig()
    all_snapshots = snapshots or load_run_snapshots(output_dir)
    filtered = _filter_snapshots(all_snapshots, max_years=config.max_years)

    if len(filtered) < 2:
        return HistoricalAnalysisSummary(
            run_count=len(filtered),
            window_start=None,
            window_end=None,
            max_years=config.max_years,
            smoothing_weeks=config.smoothing_weeks,
            note="Need at least 2 archived weekly runs within the analysis window.",
        )

    window_start = filtered[0].run_at
    window_end = filtered[-1].run_at

    strategy_horizons: list[StrategyHorizonResult] = []
    model_attribution: list[ModelAttributionResult] = []
    overlay_comparison: list[OverlayComparison] = []
    weekly_rows: list[dict[str, Any]] = []

    for horizon in config.horizon_days:
        observations = _build_observations(
            output_dir=output_dir,
            snapshots=filtered,
            horizon_days=horizon,
        )
        if not observations:
            continue

        strategy_horizons.extend(
            _strategy_results(
                observations,
                horizon_days=horizon,
                smoothing_weeks=config.smoothing_weeks,
                min_observations=config.min_observations,
            )
        )
        model_attribution.extend(
            _model_attribution(
                output_dir=output_dir,
                snapshots=filtered,
                horizon_days=horizon,
                smoothing_weeks=config.smoothing_weeks,
            )
        )
        overlay_comparison.extend(
            _overlay_comparisons(
                observations,
                horizon_days=horizon,
                smoothing_weeks=config.smoothing_weeks,
            )
        )

        weekly = _weekly_excess_by_strategy(observations)
        for strategy, week_map in weekly.items():
            smoothed = _rolling_mean([week_map[w] for w in sorted(week_map.keys())], config.smoothing_weeks)
            for index, week in enumerate(sorted(week_map.keys())):
                weekly_rows.append(
                    {
                        "horizon_days": horizon,
                        "strategy": strategy,
                        "week": week,
                        "raw_excess_return": round(week_map[week], 4),
                        "smoothed_excess_return": round(smoothed[index], 4),
                    }
                )

    note = ""
    if not strategy_horizons:
        note = "No strategy results yet — archive more weekly runs with prices and model snapshots."

    return HistoricalAnalysisSummary(
        run_count=len(filtered),
        window_start=window_start,
        window_end=window_end,
        max_years=config.max_years,
        smoothing_weeks=config.smoothing_weeks,
        strategy_horizons=strategy_horizons,
        model_attribution=model_attribution,
        overlay_comparison=overlay_comparison,
        weekly_series=weekly_rows,
        note=note,
    )


def save_historical_analysis(output_dir: Path, summary: HistoricalAnalysisSummary) -> Path:
    from value_investor.storage import write_json

    path = output_dir / "historical_analysis_summary.json"
    return write_json(path, summary.to_dict(), compact=True)


def format_historical_analysis_html(summary: HistoricalAnalysisSummary) -> str:
    if not summary.has_results():
        return ""

    text = format_historical_analysis_text(summary).replace("\n", "<br>")
    return f"""
  <div style="background:#eef8f4;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #1b7f3a">
    <h3 style="margin-top:0">Historical analysis</h3>
    <p style="color:#666;font-size:13px;margin-top:0">
      Point-in-time replay of screen + research recommendations ({summary.max_years}y window,
      {summary.smoothing_weeks}w smoothing, {summary.run_count} runs).
    </p>
    <p style="margin-bottom:0">{text}</p>
  </div>
"""


def format_historical_analysis_text(summary: HistoricalAnalysisSummary) -> str:
    if not summary.has_results():
        return summary.note or "Historical analysis not yet available."

    lines = [
        (
            f"Historical analysis ({summary.max_years}y window, "
            f"{summary.smoothing_weeks}w smoothing, {summary.run_count} runs):"
        ),
        f"  Window: {summary.window_start[:10]} → {summary.window_end[:10]}",
        "",
        "Strategy performance (smoothed excess vs FTSE):",
    ]

    current_horizon: int | None = None
    for item in sorted(summary.strategy_horizons, key=lambda row: (row.horizon_days, row.strategy)):
        if item.horizon_days != current_horizon:
            current_horizon = item.horizon_days
            lines.append(f"  ~{current_horizon // 7}w horizon:")
        if item.strategy.startswith(("screen:strong_buy", "screen:buy", "overlay:", "research:")):
            lines.append(
                f"    {item.strategy}: {item.smoothed_excess_return:+.1%} smoothed "
                f"({item.raw_excess_return:+.1%} raw, n={item.count}, weeks={item.observation_weeks})"
            )

    if summary.overlay_comparison:
        lines.extend(["", "Screen vs research overlay (buy cohort):"])
        for row in summary.overlay_comparison:
            lines.append(
                f"  ~{row.horizon_days // 7}w: screen {row.smoothed_screen_excess:+.1%}, "
                f"overlay {row.smoothed_overlay_excess:+.1%} "
                f"({row.downgrade_count} research downgrades)"
            )

    if summary.model_attribution:
        lines.extend(["", "Top model attribution (smoothed score→return correlation):"])
        for row in summary.model_attribution[:5]:
            corr = row.smoothed_correlation if row.smoothed_correlation is not None else row.raw_correlation
            if corr is None:
                continue
            lines.append(f"  {row.model_id} (~{row.horizon_days // 7}w): {corr:+.2f} (n={row.sample_count})")

    return "\n".join(lines)
