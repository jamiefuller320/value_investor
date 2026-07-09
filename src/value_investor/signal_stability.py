"""Track signal persistence and conviction across screening runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.signals import SIGNAL_ORDER, Signal


@dataclass
class StabilityInfo:
    weeks_at_signal: int
    signal_trend: str  # improving | stable | deteriorating | new
    conviction_score: float
    stability_label: str  # new | building | persistent

    def to_dict(self) -> dict[str, Any]:
        return {
            "weeks_at_signal": self.weeks_at_signal,
            "signal_trend": self.signal_trend,
            "conviction_score": round(self.conviction_score, 4),
            "stability_label": self.stability_label,
        }


HISTORY_FILE = "signal_history.csv"


def _signal_rank_value(signal: str) -> int:
    try:
        return SIGNAL_ORDER[Signal(signal)]
    except ValueError:
        return 0


def conviction_score(
    *,
    blended_composite: float,
    families_passed: int,
    family_count: int,
    data_quality_score: float,
    weeks_at_signal: int,
) -> float:
    """Higher when quality data, multi-family support, and signal persistence align."""
    family_factor = families_passed / family_count if family_count else 0.0
    stability_factor = min(1.0, 0.5 + weeks_at_signal * 0.125)
    raw = blended_composite * family_factor * data_quality_score * stability_factor
    return round(max(0.0, min(1.0, raw)), 4)


def _stability_label(weeks_at_signal: int) -> str:
    if weeks_at_signal <= 1:
        return "new"
    if weeks_at_signal < 4:
        return "building"
    return "persistent"


def load_signal_history(output_dir: Path) -> pd.DataFrame:
    path = output_dir / HISTORY_FILE
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "run_at",
                "ticker",
                "signal",
                "signal_rank",
                "conviction_score",
                "data_quality_score",
            ]
        )
    return pd.read_csv(path)


def append_signal_history(
    output_dir: Path,
    signals: pd.DataFrame,
    *,
    run_at: datetime,
) -> Path:
    """Append current run to rolling signal history."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / HISTORY_FILE

    rows = []
    run_at_str = run_at.isoformat()
    for _, row in signals.iterrows():
        rows.append(
            {
                "run_at": run_at_str,
                "ticker": row["ticker"],
                "signal": row["signal"],
                "signal_rank": int(row.get("signal_rank") or _signal_rank_value(str(row["signal"]))),
                "conviction_score": float(row.get("conviction_score") or 0),
                "data_quality_score": float(row.get("data_quality_score") or 0),
            }
        )

    frame = pd.DataFrame(rows)
    if path.exists():
        frame.to_csv(path, mode="a", header=False, index=False)
    else:
        frame.to_csv(path, index=False)
    return path


def compute_stability(
    history: pd.DataFrame,
    *,
    ticker: str,
    current_signal: str,
    current_rank: int,
    blended_composite: float,
    families_passed: int,
    family_count: int,
    data_quality_score: float,
    current_run_at: datetime,
) -> StabilityInfo:
    """Derive weeks at signal, trend, and conviction for one ticker."""
    weeks_at_signal = 1
    signal_trend = "new"
    prior_rank: int | None = None

    if not history.empty and ticker in history["ticker"].values:
        ticker_history = history[history["ticker"] == ticker].copy()
        ticker_history["run_at_dt"] = pd.to_datetime(ticker_history["run_at"], utc=True)
        ticker_history = ticker_history.sort_values("run_at_dt")

        # Exclude current run if already appended
        current_ts = pd.Timestamp(current_run_at)
        if current_ts.tzinfo is None:
            current_ts = current_ts.tz_localize("UTC")
        prior = ticker_history[ticker_history["run_at_dt"] < current_ts]

        if not prior.empty:
            last = prior.iloc[-1]
            prior_rank = int(last["signal_rank"])
            prior_signal = str(last["signal"])

            if prior_signal == current_signal:
                consecutive = 1
                for signal in reversed(prior["signal"].tolist()):
                    if str(signal) == current_signal:
                        consecutive += 1
                    else:
                        break
                weeks_at_signal = consecutive
                signal_trend = "stable"
            elif current_rank > prior_rank:
                signal_trend = "improving"
            else:
                signal_trend = "deteriorating"

    conv = conviction_score(
        blended_composite=blended_composite,
        families_passed=families_passed,
        family_count=family_count,
        data_quality_score=data_quality_score,
        weeks_at_signal=weeks_at_signal,
    )

    return StabilityInfo(
        weeks_at_signal=weeks_at_signal,
        signal_trend=signal_trend,
        conviction_score=conv,
        stability_label=_stability_label(weeks_at_signal),
    )


def enrich_signals_with_stability(
    signals: pd.DataFrame,
    history: pd.DataFrame,
    *,
    run_at: datetime,
) -> pd.DataFrame:
    """Add stability and conviction columns to signals DataFrame."""
    out = signals.copy()
    weeks_list: list[int] = []
    trend_list: list[str] = []
    conviction_list: list[float] = []
    label_list: list[str] = []

    for _, row in out.iterrows():
        composite = row.get("composite_score")
        sector = row.get("sector_composite_score")
        comp = float(composite) if composite is not None and not pd.isna(composite) else 0.0
        sec = float(sector) if sector is not None and not pd.isna(sector) else comp
        blended = (comp + sec) / 2

        info = compute_stability(
            history,
            ticker=str(row["ticker"]),
            current_signal=str(row["signal"]),
            current_rank=int(row.get("signal_rank") or 0),
            blended_composite=blended,
            families_passed=int(row.get("families_passed") or 0),
            family_count=int(row.get("family_count") or 4),
            data_quality_score=float(row.get("data_quality_score") or 0),
            current_run_at=run_at,
        )
        weeks_list.append(info.weeks_at_signal)
        trend_list.append(info.signal_trend)
        conviction_list.append(info.conviction_score)
        label_list.append(info.stability_label)

    out["weeks_at_signal"] = weeks_list
    out["signal_trend"] = trend_list
    out["conviction_score"] = conviction_list
    out["stability_label"] = label_list
    return out


def load_stability_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
