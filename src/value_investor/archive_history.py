"""Backfill weekly run snapshots from published dashboard archives."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.backtest import HISTORY_DIR, RunSnapshot, load_run_snapshots, snapshot_prices

logger = logging.getLogger(__name__)

ARCHIVE_SIGNAL_FIELDS = (
    "ticker",
    "signal",
    "conviction_score",
    "data_quality_score",
    "timing_signal",
    "timing_score",
    "action_note",
    "models_passed",
    "weighted_model_score",
    "research_verdict",
    "adjusted_signal",
    "research_as_of",
    "core_order",
    "core_limit",
    "core_allocation_pct",
    "tactical_limit",
    "tactical_allocation_pct",
    "tactical_stop_loss",
    "tactical_take_profit",
    "trade_plan_summary",
    "atr_14",
    "volume_ratio_20",
    "price_vs_sma200_pct",
    "sector",
    "name",
)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def list_dashboard_archives(archive_dir: Path) -> list[tuple[datetime, Path]]:
    archive_dir = Path(archive_dir)
    if not archive_dir.exists():
        return []
    found: list[tuple[datetime, Path]] = []
    for path in sorted(archive_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        run_at = _parse_iso(str(payload.get("run_at") or ""))
        if run_at is None:
            # Fall back to filename date stamp.
            try:
                run_at = datetime.fromisoformat(f"{path.stem}T12:00:00+00:00")
            except ValueError:
                continue
        found.append((run_at, path))
    found.sort(key=lambda item: item[0])
    return found


def _snapshot_dates(snapshots: list[RunSnapshot]) -> set[str]:
    dates: set[str] = set()
    for snap in snapshots:
        dt = _parse_iso(snap.run_at)
        if dt is not None:
            dates.add(dt.date().isoformat())
    return dates


def archive_reports_to_signals(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for row in reports:
        if not isinstance(row, dict) or not row.get("ticker"):
            continue
        slim = {key: row[key] for key in ARCHIVE_SIGNAL_FIELDS if key in row}
        slim["ticker"] = str(row["ticker"])
        signals.append(slim)
    return signals


def archive_to_run_snapshot(
    archive_path: Path,
    *,
    fetch_prices: bool = True,
    price_overrides: dict[str, float] | None = None,
) -> RunSnapshot | None:
    try:
        payload = json.loads(Path(archive_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    reports = payload.get("reports")
    if not isinstance(reports, list) or not reports:
        return None
    run_at = str(payload.get("run_at") or "")
    if not run_at:
        run_at = f"{archive_path.stem}T12:00:00+00:00"

    signals = archive_reports_to_signals(reports)
    tickers = [str(row["ticker"]) for row in signals if row.get("ticker")]
    prices: dict[str, float] = dict(price_overrides or {})
    if fetch_prices:
        fetched = snapshot_prices([t for t in tickers if t not in prices])
        prices.update(fetched)
    else:
        prices.setdefault("^FTSE", 0.0)

    return RunSnapshot(
        run_at=run_at,
        prices=prices,
        signals=signals,
    )


def backfill_run_history_from_archives(
    data_dir: Path,
    *,
    archive_dir: Path | None = None,
    fetch_prices: bool = True,
    dry_run: bool = False,
) -> list[Path]:
    """
    Write missing ``history/run_*.json.gz`` snapshots from ``docs/data/archive/*.json``.

    Skips archive dates that already have a run snapshot (matched by calendar day).
    """
    from value_investor.storage import write_json

    data_dir = Path(data_dir)
    archive_dir = Path(archive_dir or data_dir / "archive")
    history_dir = data_dir / HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)

    existing_dates = _snapshot_dates(load_run_snapshots(data_dir))
    written: list[Path] = []

    for run_at, archive_path in list_dashboard_archives(archive_dir):
        day = run_at.date().isoformat()
        if day in existing_dates:
            logger.info("Skip archive %s — history already has %s", archive_path.name, day)
            continue
        snapshot = archive_to_run_snapshot(archive_path, fetch_prices=fetch_prices)
        if snapshot is None:
            logger.warning("Skip archive %s — could not build snapshot", archive_path.name)
            continue
        stamp = run_at.strftime("%Y%m%d_%H%M%S")
        path = history_dir / f"run_{stamp}.json.gz"
        if dry_run:
            logger.info("Would write %s from %s", path.name, archive_path.name)
            written.append(path)
            continue
        write_json(path, snapshot.to_dict(), compact=True, compress=True)
        existing_dates.add(day)
        written.append(path)
        logger.info("Wrote %s from %s", path.name, archive_path.name)
    return written
