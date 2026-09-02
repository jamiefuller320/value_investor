"""Track signal persistence and conviction across screening runs."""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.library_retention import (
    DEFAULT_MONTHLY_UNTIL_DAYS,
    DEFAULT_RETENTION_DAYS,
    dates_to_remove,
)
from value_investor.model_families import FAMILY_COUNT
from value_investor.signals import SIGNAL_ORDER, Signal
from value_investor.storage import COMMITTED_HISTORY_DIR, history_snapshot_paths, read_json

logger = logging.getLogger(__name__)


@dataclass
class StabilityInfo:
    weeks_at_signal: int
    signal_trend: str  # improving | stable | deteriorating | new
    conviction_score: float
    stability_label: str  # new | building | persistent
    signal_since: str | None = None  # ISO date when the current signal streak began

    def to_dict(self) -> dict[str, Any]:
        return {
            "weeks_at_signal": self.weeks_at_signal,
            "signal_trend": self.signal_trend,
            "conviction_score": round(self.conviction_score, 4),
            "stability_label": self.stability_label,
            "signal_since": self.signal_since,
        }


HISTORY_FILE = "signal_history.csv"
COMMITTED_SIGNAL_HISTORY = Path("docs/data/signal_history.csv")
HISTORY_COLUMNS = [
    "run_at",
    "ticker",
    "signal",
    "signal_rank",
    "conviction_score",
    "data_quality_score",
]


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
        return pd.DataFrame(columns=HISTORY_COLUMNS)
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
                "signal_rank": int(
                    row.get("signal_rank") or _signal_rank_value(str(row["signal"]))
                ),
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


def prune_signal_history_rows(
    output_dir: Path,
    *,
    keep_days: int = DEFAULT_RETENTION_DAYS,
    monthly_until_days: int = DEFAULT_MONTHLY_UNTIL_DAYS,
    now: datetime | date | None = None,
) -> dict[str, int]:
    """
    Thin ``signal_history.csv`` runs with the shared dense → monthly → quarterly policy.

    Keeps every run inside the dense window; older runs keep the newest ``run_at``
    per calendar month, then per quarter indefinitely.
    """
    path = Path(output_dir) / HISTORY_FILE
    if not path.exists() or keep_days <= 0:
        return {"removed_rows": 0, "removed_runs": 0}

    frame = pd.read_csv(path)
    if frame.empty or "run_at" not in frame.columns:
        return {"removed_rows": 0, "removed_runs": 0}

    dated_runs: list[tuple[str, date]] = []
    seen: set[str] = set()
    for raw in frame["run_at"].tolist():
        run_key = str(raw)
        if run_key in seen:
            continue
        seen.add(run_key)
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        dated_runs.append((run_key, ts.date()))

    drop_runs = dates_to_remove(
        dated_runs,
        keep_days=keep_days,
        monthly_until_days=monthly_until_days,
        now=now,
    )
    if not drop_runs:
        return {"removed_rows": 0, "removed_runs": 0}

    before = len(frame)
    kept = frame[~frame["run_at"].astype(str).isin(drop_runs)]
    kept.to_csv(path, index=False)
    return {
        "removed_rows": int(before - len(kept)),
        "removed_runs": int(len(drop_runs)),
    }


def signal_history_from_run_snapshots(history_dir: Path) -> pd.DataFrame:
    """Rebuild ``signal_history.csv`` rows from archived ``run_*.json(.gz)`` snapshots."""
    rows: list[dict[str, Any]] = []
    for path in sorted(history_snapshot_paths(history_dir)):
        try:
            payload = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable run snapshot %s: %s", path.name, exc)
            continue
        if not isinstance(payload, dict):
            continue
        run_at = payload.get("run_at")
        signals = payload.get("signals") or []
        if not run_at or not isinstance(signals, list):
            continue
        for row in signals:
            if not isinstance(row, dict) or not row.get("ticker"):
                continue
            signal = str(row.get("signal") or "hold")
            rank_raw = row.get("signal_rank")
            rows.append(
                {
                    "run_at": str(run_at),
                    "ticker": str(row["ticker"]),
                    "signal": signal,
                    "signal_rank": int(rank_raw)
                    if rank_raw is not None and not pd.isna(rank_raw)
                    else _signal_rank_value(signal),
                    "conviction_score": float(row.get("conviction_score") or 0),
                    "data_quality_score": float(row.get("data_quality_score") or 0),
                }
            )
    if not rows:
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    frame = pd.DataFrame(rows)
    frame = frame.drop_duplicates(subset=["run_at", "ticker"], keep="last")
    return frame.sort_values(["run_at", "ticker"]).reset_index(drop=True)


def restore_committed_signal_history(
    output_dir: Path,
    *,
    committed_path: Path | None = None,
) -> bool:
    """
    Copy git-tracked live ``signal_history.csv`` into ``output_dir`` before a screen.

    Skips when a local history already exists so dev reruns are not overwritten.
    """
    source = committed_path or COMMITTED_SIGNAL_HISTORY
    dest = Path(output_dir) / HISTORY_FILE
    if dest.exists() or not source.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return True


def publish_committed_signal_history(
    output_dir: Path,
    *,
    committed_path: Path | None = None,
) -> bool:
    """Mirror ``output/signal_history.csv`` into ``docs/data`` for the next CI screen."""
    source = Path(output_dir) / HISTORY_FILE
    dest = committed_path or COMMITTED_SIGNAL_HISTORY
    if not source.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return True


def ensure_signal_history(
    output_dir: Path,
    *,
    committed_path: Path | None = None,
    history_dir: Path | None = None,
    committed_history_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Make sure ``output_dir/signal_history.csv`` exists before stability enrichment.

    Order: keep local file → restore committed CSV → backfill from run snapshots.
    """
    output_dir = Path(output_dir)
    dest = output_dir / HISTORY_FILE
    if dest.exists():
        return {"source": "local", "rows": int(len(pd.read_csv(dest)))}

    if restore_committed_signal_history(output_dir, committed_path=committed_path):
        return {"source": "committed", "rows": int(len(pd.read_csv(dest)))}

    snapshot_dirs = [
        history_dir or (output_dir / "history"),
        committed_history_dir or COMMITTED_HISTORY_DIR,
    ]
    frames: list[pd.DataFrame] = []
    for snap_dir in snapshot_dirs:
        if snap_dir is None or not Path(snap_dir).exists():
            continue
        frame = signal_history_from_run_snapshots(Path(snap_dir))
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return {"source": "empty", "rows": 0}

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["run_at", "ticker"], keep="last")
    merged = merged.sort_values(["run_at", "ticker"]).reset_index(drop=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    merged.to_csv(dest, index=False)
    return {"source": "snapshots", "rows": int(len(merged))}


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

    current_ts = pd.Timestamp(current_run_at)
    if current_ts.tzinfo is None:
        current_ts = current_ts.tz_localize("UTC")
    signal_since = current_ts.date().isoformat()

    if not history.empty and ticker in history["ticker"].values:
        ticker_history = history[history["ticker"] == ticker].copy()
        ticker_history["run_at_dt"] = pd.to_datetime(ticker_history["run_at"], utc=True)
        ticker_history = ticker_history.sort_values("run_at_dt")

        # Exclude current run if already appended
        prior = ticker_history[ticker_history["run_at_dt"] < current_ts]

        if not prior.empty:
            last = prior.iloc[-1]
            prior_rank = int(last["signal_rank"])
            prior_signal = str(last["signal"])

            if prior_signal == current_signal:
                consecutive = 1
                since_ts = current_ts
                for _, hist_row in prior.iloc[::-1].iterrows():
                    if str(hist_row["signal"]) == current_signal:
                        consecutive += 1
                        since_ts = hist_row["run_at_dt"]
                    else:
                        break
                weeks_at_signal = consecutive
                signal_trend = "stable"
                signal_since = pd.Timestamp(since_ts).date().isoformat()
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
        signal_since=signal_since,
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
    since_list: list[str | None] = []

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
            family_count=int(row.get("family_count") or FAMILY_COUNT),
            data_quality_score=float(row.get("data_quality_score") or 0),
            current_run_at=run_at,
        )
        weeks_list.append(info.weeks_at_signal)
        trend_list.append(info.signal_trend)
        conviction_list.append(info.conviction_score)
        label_list.append(info.stability_label)
        since_list.append(info.signal_since)

    out["weeks_at_signal"] = weeks_list
    out["signal_trend"] = trend_list
    out["conviction_score"] = conviction_list
    out["stability_label"] = label_list
    out["signal_since"] = since_list
    return out


def patch_report_stability_fields(
    report: dict[str, Any],
    info: StabilityInfo,
    *,
    family_count: int = FAMILY_COUNT,
) -> dict[str, Any]:
    """Update a dashboard report dict with recomputed stability / family denominator."""
    out = dict(report)
    out["weeks_at_signal"] = info.weeks_at_signal
    out["signal_trend"] = info.signal_trend
    out["conviction_score"] = info.conviction_score
    out["stability_label"] = info.stability_label
    out["signal_since"] = info.signal_since
    out["family_count"] = int(out.get("family_count") or family_count)

    summary = str(out.get("summary") or "")
    families_passed = int(out.get("families_passed") or 0)
    if families_passed and "/4 (" in summary:
        summary = summary.replace(
            f"Families: {families_passed}/4 (",
            f"Families: {families_passed}/{out['family_count']} (",
        )
    # Refresh the conviction clause when present.
    summary = re.sub(
        r"Conviction [0-9]+% \([^)]*\)",
        (
            f"Conviction {info.conviction_score:.0%} "
            f"({info.stability_label}, {info.weeks_at_signal}w at signal, {info.signal_trend})"
        ),
        summary,
        count=1,
    )
    out["summary"] = summary
    return out


def refresh_dashboard_report_stability(
    reports: list[dict[str, Any]],
    history: pd.DataFrame,
    *,
    run_at: datetime,
    family_count: int = FAMILY_COUNT,
) -> list[dict[str, Any]]:
    """Recompute stability fields on published dashboard reports using signal history."""
    refreshed: list[dict[str, Any]] = []
    for report in reports:
        if not isinstance(report, dict) or not report.get("ticker"):
            refreshed.append(report)
            continue
        composite = report.get("composite_score")
        sector = report.get("sector_composite_score")
        comp = float(composite) if composite is not None else 0.0
        sec = float(sector) if sector is not None else comp
        blended = (comp + sec) / 2
        signal = str(report.get("signal") or "hold")
        info = compute_stability(
            history,
            ticker=str(report["ticker"]),
            current_signal=signal,
            current_rank=int(report.get("signal_rank") or _signal_rank_value(signal)),
            blended_composite=blended,
            families_passed=int(report.get("families_passed") or 0),
            family_count=int(report.get("family_count") or family_count),
            data_quality_score=float(report.get("data_quality_score") or 0),
            current_run_at=run_at,
        )
        refreshed.append(
            patch_report_stability_fields(report, info, family_count=family_count)
        )
    return refreshed


def load_stability_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
