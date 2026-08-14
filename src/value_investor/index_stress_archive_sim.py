"""Observe-only archive sim for index stress and stop-out counterfactuals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.backtest import BENCHMARK_TICKER, RunSnapshot, _parse_run_at, load_run_snapshots
from value_investor.index_stress import (
    FetchDailyBars,
    IndexStressThresholds,
    any_stress_between,
    default_fetch_daily_bars,
    label_daily_stress,
    stress_by_date,
    weekly_proxy_stress,
)
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.storage import write_json

COHORTS_FILENAME = "index_stress_archive.json"
REVIEW_FILENAME = "index_stress_archive_review.json"


@dataclass
class IndexStressArchiveConfig:
    symbol: str = BENCHMARK_TICKER
    thresholds: IndexStressThresholds = field(default_factory=IndexStressThresholds)
    sweep_thresholds: tuple[IndexStressThresholds, ...] = (
        IndexStressThresholds(abs_1d=-0.02, abs_5d=-0.04, drawdown_from_peak=-0.05),
        IndexStressThresholds(),
        IndexStressThresholds(abs_1d=-0.04, abs_5d=-0.07, drawdown_from_peak=-0.08),
    )
    min_data_quality: float = 0.0


def _effective_signal(row: dict[str, Any]) -> str:
    adjusted = str(row.get("adjusted_signal") or "").strip()
    if adjusted:
        return adjusted
    return str(row.get("signal") or "").strip()


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _snapshot_date(snapshot: RunSnapshot) -> date:
    return _parse_run_at(snapshot.run_at).date()


def _buy_tier_rows(snapshot: RunSnapshot, *, min_data_quality: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in snapshot.signals:
        if _effective_signal(row) not in BUY_SIGNALS:
            continue
        dq = _optional_float(row.get("data_quality_score"))
        if min_data_quality > 0 and (dq is None or dq < min_data_quality):
            continue
        if not str(row.get("ticker") or "").strip():
            continue
        rows.append(row)
    return rows


def _stop_hit(
    *,
    ticker: str,
    start_snapshot: RunSnapshot,
    end_snapshot: RunSnapshot,
) -> dict[str, Any] | None:
    row = next((r for r in start_snapshot.signals if str(r.get("ticker")) == ticker), None)
    if row is None:
        return None
    stop = _optional_float(row.get("tactical_stop_loss"))
    if stop is None:
        stop = _optional_float((row.get("trade_plan") or {}).get("tactical_stop_loss"))
    if stop is None:
        return None
    start_price = start_snapshot.prices.get(ticker)
    end_price = end_snapshot.prices.get(ticker)
    if start_price is None or end_price is None:
        return None
    if end_price > stop:
        return None
    return {
        "ticker": ticker,
        "stop_loss": stop,
        "price_before": round(float(start_price), 4),
        "price_after": round(float(end_price), 4),
        "drawdown_pct": round((float(end_price) - float(start_price)) / float(start_price), 4),
    }


def _index_return_between(start: RunSnapshot, end: RunSnapshot, symbol: str) -> float | None:
    start_px = start.prices.get(symbol)
    end_px = end.prices.get(symbol)
    if start_px is None or end_px is None or start_px <= 0:
        return None
    return (float(end_px) - float(start_px)) / float(start_px)


def framework_metadata() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scope": "index_stress_archive",
        "observe_only": True,
        "note": (
            "Offline lab for rule-based index stress triggers and stop-out counterfactuals. "
            "Daily bars are required for intraweek gap sensitivity; weekly snapshot index "
            "returns are a coarse fallback only."
        ),
        "recommended_trigger_stack": [
            "daily abs_1d (gap capture)",
            "daily abs_5d (panic week)",
            "vol_z_1d (unusual vs recent vol)",
            "drawdown_from_peak (sustained stress)",
        ],
    }


def replay_stop_counterfactual(
    snapshots: list[RunSnapshot],
    *,
    stress_decisions_by_date: dict[str, Any],
    thresholds: IndexStressThresholds,
    min_data_quality: float = 0.0,
    use_daily_stress: bool = True,
) -> dict[str, Any]:
    """Score hypothetical tactical stop hits with vs without stress-week suspension."""
    if len(snapshots) < 2:
        return {
            "windows": 0,
            "stress_windows": 0,
            "stop_hits_total": 0,
            "stop_hits_stress_windows": 0,
            "stop_hits_normal_windows": 0,
            "counterfactual_sells_avoided": 0,
            "episodes": [],
        }

    episodes: list[dict[str, Any]] = []
    stop_hits_total = 0
    stop_hits_stress = 0
    stop_hits_normal = 0
    stress_windows = 0

    for start, end in zip(snapshots, snapshots[1:], strict=False):
        start_day = _snapshot_date(start)
        end_day = _snapshot_date(end)
        if use_daily_stress and stress_decisions_by_date:
            stressed, triggers = any_stress_between(
                stress_decisions_by_date,
                start=start_day,
                end=end_day,
            )
        else:
            idx_ret = _index_return_between(start, end, BENCHMARK_TICKER)
            if idx_ret is None:
                stressed, triggers = False, []
            else:
                proxy = weekly_proxy_stress(index_return=idx_ret, thresholds=thresholds)
                stressed, triggers = proxy.stressed, list(proxy.triggers)

        if stressed:
            stress_windows += 1

        hits: list[dict[str, Any]] = []
        for row in _buy_tier_rows(start, min_data_quality=min_data_quality):
            ticker = str(row.get("ticker"))
            hit = _stop_hit(ticker=ticker, start_snapshot=start, end_snapshot=end)
            if hit is not None:
                hits.append(hit)

        stop_hits_total += len(hits)
        if stressed:
            stop_hits_stress += len(hits)
        else:
            stop_hits_normal += len(hits)

        episodes.append(
            {
                "window_start": start.run_at,
                "window_end": end.run_at,
                "stressed": stressed,
                "stress_triggers": triggers,
                "index_return": _index_return_between(start, end, BENCHMARK_TICKER),
                "stop_hits": hits,
                "stop_hit_count": len(hits),
            }
        )

    windows = len(episodes)
    return {
        "windows": windows,
        "stress_windows": stress_windows,
        "stress_window_rate": round(stress_windows / windows, 4) if windows else 0.0,
        "stop_hits_total": stop_hits_total,
        "stop_hits_stress_windows": stop_hits_stress,
        "stop_hits_normal_windows": stop_hits_normal,
        "counterfactual_sells_avoided": stop_hits_stress,
        "episodes": episodes,
    }


def _threshold_label(thresholds: IndexStressThresholds) -> str:
    return (
        f"1d{thresholds.abs_1d:.0%}_5d{thresholds.abs_5d:.0%}_"
        f"dd{thresholds.drawdown_from_peak:.0%}_z{thresholds.vol_z}"
    )


def run_threshold_sweep(
    snapshots: list[RunSnapshot],
    *,
    daily_bars: list[dict[str, Any]],
    sweep: tuple[IndexStressThresholds, ...],
    min_data_quality: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for thresholds in sweep:
        decisions = label_daily_stress(daily_bars, thresholds=thresholds)
        by_date = stress_by_date(decisions)
        stressed_days = sum(1 for row in decisions if row.stressed)
        replay = replay_stop_counterfactual(
            snapshots,
            stress_decisions_by_date=by_date,
            thresholds=thresholds,
            min_data_quality=min_data_quality,
            use_daily_stress=bool(daily_bars),
        )
        results.append(
            {
                "label": _threshold_label(thresholds),
                "thresholds": thresholds.to_dict(),
                "stressed_days": stressed_days,
                "daily_bar_count": len(daily_bars),
                **{k: v for k, v in replay.items() if k != "episodes"},
            }
        )
    return results


def _write_artifacts(output_dir: Path, cohorts: dict[str, Any], review: dict[str, Any]) -> None:
    write_json(output_dir / COHORTS_FILENAME, cohorts, compact=False)
    write_json(output_dir / REVIEW_FILENAME, review, compact=False)


def run_index_stress_archive_sim(
    output_dir: Path,
    *,
    config: IndexStressArchiveConfig | None = None,
    fetch_daily_bars: FetchDailyBars | None = None,
) -> dict[str, Any]:
    """Label index stress episodes and replay stop-out counterfactuals on archives."""
    cfg = config or IndexStressArchiveConfig()
    output_dir = Path(output_dir)
    snapshots = load_run_snapshots(output_dir)
    generated_at = datetime.now(UTC).isoformat()

    if len(snapshots) < 2:
        review = {
            "schema_version": 1,
            "generated_at": generated_at,
            "framework": framework_metadata(),
            "snapshot_count": len(snapshots),
            "note": "Need at least 2 archived run snapshots (ftse-archive-history).",
            "readiness": {"ready": False, "reason": "thin_snapshot_chain"},
        }
        _write_artifacts(output_dir, {"episodes": [], "daily_bars": []}, review)
        return review

    start_day = _snapshot_date(snapshots[0]) - timedelta(days=cfg.thresholds.vol_window + 5)
    end_day = _snapshot_date(snapshots[-1]) + timedelta(days=1)
    fetch = fetch_daily_bars or default_fetch_daily_bars
    daily_bars = fetch(cfg.symbol, start_day, end_day)

    decisions = label_daily_stress(daily_bars, thresholds=cfg.thresholds)
    by_date = stress_by_date(decisions)
    replay = replay_stop_counterfactual(
        snapshots,
        stress_decisions_by_date=by_date,
        thresholds=cfg.thresholds,
        min_data_quality=cfg.min_data_quality,
        use_daily_stress=bool(daily_bars),
    )
    sweep = run_threshold_sweep(
        snapshots,
        daily_bars=daily_bars,
        sweep=cfg.sweep_thresholds,
        min_data_quality=cfg.min_data_quality,
    )

    stressed_episodes = [row for row in replay["episodes"] if row.get("stressed")]
    daily_sensitivity = {
        "daily_bars_available": bool(daily_bars),
        "daily_bar_count": len(daily_bars),
        "stressed_days_primary": sum(1 for row in decisions if row.stressed),
        "note": (
            "Daily ROC is necessary for intraweek gap sensitivity. "
            "Use abs_1d + abs_5d + vol_z + drawdown together — daily alone "
            "over-fires in volatile but non-panic regimes."
        ),
    }

    review = {
        "schema_version": 1,
        "generated_at": generated_at,
        "framework": framework_metadata(),
        "snapshot_count": len(snapshots),
        "symbol": cfg.symbol,
        "primary_thresholds": cfg.thresholds.to_dict(),
        "daily_sensitivity": daily_sensitivity,
        "primary_replay": {k: v for k, v in replay.items() if k != "episodes"},
        "threshold_sweep": sweep,
        "stress_episodes": stressed_episodes,
        "readiness": {
            "ready": len(daily_bars) >= 30 and len(snapshots) >= 4,
            "snapshot_count": len(snapshots),
            "daily_bar_count": len(daily_bars),
            "reason": (
                "Sufficient for framework validation; extend archive history for calibration."
                if len(daily_bars) >= 30
                else "Fetch daily index bars or widen date range for calibration."
            ),
        },
    }

    cohorts = {
        "schema_version": 1,
        "generated_at": generated_at,
        "symbol": cfg.symbol,
        "daily_bars": daily_bars[-120:],
        "daily_stress": [row.to_dict() for row in decisions if row.stressed][-60:],
        "episodes": replay["episodes"],
    }
    _write_artifacts(output_dir, cohorts, review)
    return review


def format_index_stress_archive_text(review: dict[str, Any]) -> str:
    lines = ["Index stress archive sim (observe-only):"]
    framework = review.get("framework") or {}
    lines.append(f"  {framework.get('note', '')}".strip())

    readiness = review.get("readiness") or {}
    lines.append(
        f"  Snapshots: {review.get('snapshot_count', 0)} | "
        f"daily bars: {(review.get('daily_sensitivity') or {}).get('daily_bar_count', 0)} | "
        f"ready: {readiness.get('ready', False)}"
    )

    primary = review.get("primary_replay") or {}
    if primary:
        lines.append(
            f"  Primary replay: {primary.get('stress_windows', 0)}/{primary.get('windows', 0)} "
            f"stress windows; stop hits {primary.get('stop_hits_total', 0)} "
            f"({primary.get('stop_hits_stress_windows', 0)} on stress weeks — "
            f"counterfactual sells avoided if suspended: "
            f"{primary.get('counterfactual_sells_avoided', 0)})"
        )

    sweep = review.get("threshold_sweep") or []
    if sweep:
        lines.append("  Threshold sweep:")
        for row in sweep:
            lines.append(
                f"    • {row.get('label')}: stress_days={row.get('stressed_days')} "
                f"stress_windows={row.get('stress_windows')} "
                f"stop_hits_stress={row.get('stop_hits_stress_windows')}"
            )

    sens = review.get("daily_sensitivity") or {}
    if sens.get("note"):
        lines.append(f"  Sensitivity: {sens['note']}")

    note = review.get("note")
    if note:
        lines.append(f"  Note: {note}")
    return "\n".join(lines)


__all__ = [
    "COHORTS_FILENAME",
    "REVIEW_FILENAME",
    "IndexStressArchiveConfig",
    "format_index_stress_archive_text",
    "framework_metadata",
    "replay_stop_counterfactual",
    "run_index_stress_archive_sim",
    "run_threshold_sweep",
]
