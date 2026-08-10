"""Monitor, safely repair, and report on archived backtest run history."""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.backtest import (
    BENCHMARK_TICKER,
    BacktestSummary,
    compute_backtest,
    load_run_snapshots,
)
from value_investor.storage import (
    COMMITTED_HISTORY_DIR,
    history_snapshot_paths,
    read_json,
)

logger = logging.getLogger(__name__)

DEFAULT_STATUS_PATH = Path("docs/data/backtest_health.json")
QUARANTINE_DIRNAME = "quarantine"
RUN_FILE_RE = re.compile(r"^run_(\d{8}_\d{6})\.json(?:\.gz)?$")
MODEL_FILE_RE = re.compile(r"^models_(\d{8}_\d{6})\.json(?:\.gz)?$")
REQUIRED_SIGNAL_FIELDS = ("ticker", "signal")
MIN_SIGNAL_COUNT = 50
MIN_PRICE_COVERAGE = 0.5
FUTURE_SLACK = timedelta(hours=2)


@dataclass
class SnapshotIssue:
    path: str
    severity: str  # warn | fail
    code: str
    summary: str
    auto_fixable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "severity": self.severity,
            "code": self.code,
            "summary": self.summary,
            "auto_fixable": self.auto_fixable,
        }


@dataclass
class RepairAction:
    action: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "detail": self.detail}


@dataclass
class BacktestHealthReport:
    checked_at: str
    history_dir: str
    run_files: int
    model_files: int
    valid_runs: int
    issues: list[SnapshotIssue] = field(default_factory=list)
    repairs: list[RepairAction] = field(default_factory=list)
    backtest: dict[str, Any] = field(default_factory=dict)
    readiness: dict[str, Any] = field(default_factory=dict)
    overall: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "history_dir": self.history_dir,
            "run_files": self.run_files,
            "model_files": self.model_files,
            "valid_runs": self.valid_runs,
            "issues": [row.to_dict() for row in self.issues],
            "repairs": [row.to_dict() for row in self.repairs],
            "backtest": self.backtest,
            "readiness": self.readiness,
            "overall": self.overall,
        }


def _parse_run_at(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (TypeError, ValueError):
        return None


def _snapshot_stamp(path: Path) -> str | None:
    match = RUN_FILE_RE.match(path.name)
    return match.group(1) if match else None


def validate_snapshot_payload(
    data: dict[str, Any],
    *,
    path: Path | None = None,
    now: datetime | None = None,
) -> list[SnapshotIssue]:
    """Validate a run snapshot dict without mutating it."""
    issues: list[SnapshotIssue] = []
    label = path.as_posix() if path else "snapshot"
    now = now or datetime.now(UTC)

    if not isinstance(data, dict):
        return [
            SnapshotIssue(
                path=label,
                severity="fail",
                code="invalid_root",
                summary="Snapshot root is not a JSON object",
                auto_fixable=True,
            )
        ]

    run_at_raw = data.get("run_at")
    run_at = _parse_run_at(str(run_at_raw or ""))
    if run_at is None:
        issues.append(
            SnapshotIssue(
                path=label,
                severity="fail",
                code="invalid_run_at",
                summary=f"Missing or unparseable run_at: {run_at_raw!r}",
                auto_fixable=True,
            )
        )
    elif run_at > now + FUTURE_SLACK:
        issues.append(
            SnapshotIssue(
                path=label,
                severity="fail",
                code="future_run_at",
                summary=f"run_at is in the future: {run_at.isoformat()}",
                auto_fixable=True,
            )
        )

    prices = data.get("prices")
    if not isinstance(prices, dict) or not prices:
        issues.append(
            SnapshotIssue(
                path=label,
                severity="fail",
                code="missing_prices",
                summary="prices map is missing or empty",
                auto_fixable=True,
            )
        )
        prices = {}
    else:
        if BENCHMARK_TICKER not in prices:
            issues.append(
                SnapshotIssue(
                    path=label,
                    severity="fail",
                    code="missing_benchmark",
                    summary=f"Benchmark price missing ({BENCHMARK_TICKER})",
                    auto_fixable=False,
                )
            )
        bad_prices = [
            key
            for key, value in prices.items()
            if not isinstance(value, (int, float)) or float(value) <= 0
        ]
        if bad_prices:
            issues.append(
                SnapshotIssue(
                    path=label,
                    severity="fail",
                    code="invalid_prices",
                    summary=f"Non-positive or invalid prices for {len(bad_prices)} ticker(s)",
                    auto_fixable=True,
                )
            )

    signals = data.get("signals")
    if not isinstance(signals, list) or not signals:
        issues.append(
            SnapshotIssue(
                path=label,
                severity="fail",
                code="missing_signals",
                summary="signals list is missing or empty",
                auto_fixable=True,
            )
        )
        signals = []

    if isinstance(signals, list):
        if len(signals) < MIN_SIGNAL_COUNT:
            issues.append(
                SnapshotIssue(
                    path=label,
                    severity="warn",
                    code="thin_signals",
                    summary=f"Only {len(signals)} signal rows (expected ≥{MIN_SIGNAL_COUNT} for FTSE screen)",
                    auto_fixable=False,
                )
            )
        missing_fields = 0
        for row in signals:
            if not isinstance(row, dict):
                missing_fields += 1
                continue
            if any(field not in row for field in REQUIRED_SIGNAL_FIELDS):
                missing_fields += 1
        if missing_fields:
            issues.append(
                SnapshotIssue(
                    path=label,
                    severity="fail",
                    code="invalid_signal_rows",
                    summary=f"{missing_fields} signal row(s) missing required fields",
                    auto_fixable=True,
                )
            )

        if prices and signals:
            tickers = {
                str(row.get("ticker"))
                for row in signals
                if isinstance(row, dict) and row.get("ticker")
            }
            covered = sum(1 for ticker in tickers if ticker in prices)
            ratio = covered / max(1, len(tickers))
            if ratio < MIN_PRICE_COVERAGE:
                issues.append(
                    SnapshotIssue(
                        path=label,
                        severity="warn",
                        code="low_price_coverage",
                        summary=(
                            f"Only {covered}/{len(tickers)} signal tickers have entry prices "
                            f"({ratio:.0%})"
                        ),
                        auto_fixable=False,
                    )
                )

    return issues


def _load_snapshot_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return read_json(path), None
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def audit_history_dir(
    history_dir: Path,
    *,
    now: datetime | None = None,
) -> tuple[list[SnapshotIssue], dict[str, Any]]:
    """Scan a history directory for structural issues without modifying files."""
    history_dir = Path(history_dir)
    issues: list[SnapshotIssue] = []
    if not history_dir.exists():
        return issues, {"run_files": 0, "model_files": 0, "valid_runs": 0}

    run_paths = sorted(
        path for path in history_dir.iterdir() if path.is_file() and RUN_FILE_RE.match(path.name)
    )
    model_paths = sorted(
        path for path in history_dir.iterdir() if path.is_file() and MODEL_FILE_RE.match(path.name)
    )

    stamps: dict[str, list[Path]] = {}
    for path in run_paths:
        stamp = _snapshot_stamp(path)
        if stamp:
            stamps.setdefault(stamp, []).append(path)

    for stamp, paths in stamps.items():
        if len(paths) > 1:
            joined = ", ".join(p.name for p in paths)
            issues.append(
                SnapshotIssue(
                    path=history_dir.as_posix(),
                    severity="fail",
                    code="duplicate_run_stamp",
                    summary=f"Duplicate run snapshots for stamp {stamp}: {joined}",
                    auto_fixable=True,
                )
            )
        plain = history_dir / f"run_{stamp}.json"
        gz = history_dir / f"run_{stamp}.json.gz"
        if plain.exists() and gz.exists():
            issues.append(
                SnapshotIssue(
                    path=plain.as_posix(),
                    severity="warn",
                    code="duplicate_plain_gzip",
                    summary=f"Both {plain.name} and {gz.name} exist — prefer gzip only",
                    auto_fixable=True,
                )
            )

    model_stamps = {
        match.group(1) for path in model_paths if (match := MODEL_FILE_RE.match(path.name))
    }
    run_stamps = set(stamps)
    for stamp in sorted(model_stamps - run_stamps):
        issues.append(
            SnapshotIssue(
                path=history_dir.as_posix(),
                severity="warn",
                code="orphan_model_snapshot",
                summary=f"Model snapshot without matching run for stamp {stamp}",
                auto_fixable=False,
            )
        )
    for stamp in sorted(run_stamps - model_stamps):
        plain = history_dir / f"run_{stamp}.json"
        gz = history_dir / f"run_{stamp}.json.gz"
        run_path = gz if gz.exists() else plain
        issues.append(
            SnapshotIssue(
                path=run_path.as_posix(),
                severity="warn",
                code="missing_model_snapshot",
                summary=f"Run snapshot without matching models file for stamp {stamp}",
                auto_fixable=run_path.exists(),
            )
        )

    valid_runs = 0
    for path in run_paths:
        if path.suffix == ".json" and path.with_suffix(".json.gz").exists():
            continue
        payload, error = _load_snapshot_file(path)
        if payload is None:
            issues.append(
                SnapshotIssue(
                    path=path.as_posix(),
                    severity="fail",
                    code="corrupt_json",
                    summary=f"Unreadable snapshot: {error}",
                    auto_fixable=True,
                )
            )
            continue
        file_issues = validate_snapshot_payload(payload, path=path, now=now)
        issues.extend(file_issues)
        if not any(issue.severity == "fail" for issue in file_issues):
            valid_runs += 1

    stats = {
        "run_files": len(run_paths),
        "model_files": len(model_paths),
        "valid_runs": valid_runs,
    }
    return issues, stats


def _quarantine_path(history_dir: Path, source: Path, *, now: datetime | None = None) -> Path:
    now = now or datetime.now(UTC)
    quarantine_root = history_dir / QUARANTINE_DIRNAME
    quarantine_root.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    target = quarantine_root / f"{stamp}_{source.name}"
    if target.exists():
        target = quarantine_root / f"{stamp}_{source.stat().st_size}_{source.name}"
    return target


def repair_history_dir(
    history_dir: Path,
    issues: list[SnapshotIssue],
    *,
    apply: bool = False,
    now: datetime | None = None,
) -> list[RepairAction]:
    """
    Apply safe, non-destructive repairs.

    Never rewrites snapshot payloads or backfills prices (pollution guard).
    """
    history_dir = Path(history_dir)
    repairs: list[RepairAction] = []
    if not apply or not history_dir.exists():
        return repairs

    now = now or datetime.now(UTC)
    seen_paths: set[str] = set()

    for issue in issues:
        if not issue.auto_fixable:
            continue
        path = Path(issue.path)
        if issue.code == "duplicate_plain_gzip" and path.suffix == ".json":
            gz = path.with_suffix(".json.gz")
            if path.exists() and gz.exists() and path.as_posix() not in seen_paths:
                target = _quarantine_path(history_dir, path, now=now)
                shutil.move(str(path), str(target))
                repairs.append(
                    RepairAction(
                        action="quarantine_duplicate_plain_json",
                        detail=f"moved {path.name} → {target.relative_to(history_dir).as_posix()}",
                    )
                )
                seen_paths.add(path.as_posix())
        elif issue.code in {
            "corrupt_json",
            "invalid_root",
            "invalid_run_at",
            "future_run_at",
            "missing_prices",
            "missing_signals",
            "invalid_prices",
            "invalid_signal_rows",
            "missing_model_snapshot",
        }:
            if path.exists() and path.is_file() and path.as_posix() not in seen_paths:
                target = _quarantine_path(history_dir, path, now=now)
                shutil.move(str(path), str(target))
                action = (
                    "quarantine_orphan_run"
                    if issue.code == "missing_model_snapshot"
                    else "quarantine_corrupt_snapshot"
                )
                repairs.append(
                    RepairAction(
                        action=action,
                        detail=f"moved {path.name} → {target.relative_to(history_dir).as_posix()} ({issue.code})",
                    )
                )
                seen_paths.add(path.as_posix())

    duplicate_stamps = {issue.summary for issue in issues if issue.code == "duplicate_run_stamp"}
    if duplicate_stamps:
        for _stamp, paths in _group_run_paths_by_stamp(history_dir).items():
            if len(paths) <= 1:
                continue
            keep = max(paths, key=lambda item: (item.suffix == ".gz", item.stat().st_size))
            for path in paths:
                if path == keep or path.as_posix() in seen_paths:
                    continue
                target = _quarantine_path(history_dir, path, now=now)
                shutil.move(str(path), str(target))
                repairs.append(
                    RepairAction(
                        action="quarantine_duplicate_stamp",
                        detail=f"moved {path.name} → {target.relative_to(history_dir).as_posix()} (kept {keep.name})",
                    )
                )
                seen_paths.add(path.as_posix())

    return repairs


def _group_run_paths_by_stamp(history_dir: Path) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = {}
    for path in history_dir.iterdir():
        if not path.is_file():
            continue
        stamp = _snapshot_stamp(path)
        if stamp:
            grouped.setdefault(stamp, []).append(path)
    return grouped


def assess_readiness(
    *,
    valid_runs: int,
    backtest: BacktestSummary,
) -> dict[str, Any]:
    return {
        "valid_runs": valid_runs,
        "backtest_ready": valid_runs >= 2,
        "horizons_computed": len(backtest.horizons),
        "note": backtest.note,
    }


def _overall_status(issues: list[SnapshotIssue]) -> str:
    if any(issue.severity == "fail" for issue in issues):
        return "fail"
    if issues:
        return "warn"
    return "ok"


def run_backtest_health(
    *,
    history_dir: Path = COMMITTED_HISTORY_DIR,
    output_dir: Path | None = None,
    apply_repairs: bool = False,
    status_path: Path = DEFAULT_STATUS_PATH,
    now: datetime | None = None,
) -> BacktestHealthReport:
    """Audit history, optionally quarantine corrupt files, and refresh readiness metrics."""
    now = now or datetime.now(UTC)
    history_dir = Path(history_dir)
    issues, stats = audit_history_dir(history_dir, now=now)
    repairs = repair_history_dir(history_dir, issues, apply=apply_repairs, now=now)

    if apply_repairs and repairs:
        issues, stats = audit_history_dir(history_dir, now=now)

    load_dir = output_dir or history_dir
    snapshots = load_run_snapshots(load_dir)
    backtest = compute_backtest(snapshots)
    readiness = assess_readiness(valid_runs=stats["valid_runs"], backtest=backtest)

    report = BacktestHealthReport(
        checked_at=now.isoformat(),
        history_dir=history_dir.as_posix(),
        run_files=int(stats["run_files"]),
        model_files=int(stats["model_files"]),
        valid_runs=int(stats["valid_runs"]),
        issues=issues,
        repairs=repairs,
        backtest=backtest.to_dict(),
        readiness=readiness,
        overall=_overall_status(issues),
    )

    status_path = Path(status_path)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    from value_investor.storage import write_json

    write_json(status_path, report.to_dict(), compact=False)
    return report


def validate_history_before_publish(
    output_dir: Path,
    *,
    committed_dir: Path | None = None,
) -> list[SnapshotIssue]:
    """
    Guard publish: reject invalid new run snapshots in output/history.

    Does not mutate files — caller should run repair on committed dir separately.
    """
    source = Path(output_dir) / "history"
    if not source.exists():
        return []
    committed = Path(committed_dir or COMMITTED_HISTORY_DIR)
    committed_names = (
        {path.name for path in history_snapshot_paths(committed)} if committed.exists() else set()
    )

    blocking: list[SnapshotIssue] = []
    for path in sorted(source.glob("run_*.json*")):
        if path.name in committed_names:
            continue
        payload, error = _load_snapshot_file(path)
        if payload is None:
            blocking.append(
                SnapshotIssue(
                    path=path.as_posix(),
                    severity="fail",
                    code="corrupt_json",
                    summary=f"Refusing to publish unreadable snapshot: {error}",
                    auto_fixable=False,
                )
            )
            continue
        file_issues = [
            issue
            for issue in validate_snapshot_payload(payload, path=path)
            if issue.severity == "fail"
        ]
        blocking.extend(file_issues)
    return blocking


def findings_for_ops_monitor(report: BacktestHealthReport) -> list[dict[str, Any]]:
    """Map health issues into ops-monitor-friendly dict rows."""
    rows: list[dict[str, Any]] = []
    for issue in report.issues:
        rows.append(
            {
                "severity": issue.severity,
                "category": "backtest",
                "title": f"Backtest history: {issue.code}",
                "summary": issue.summary,
                "auto_fixable": issue.auto_fixable,
            }
        )
    if report.valid_runs < 2:
        rows.append(
            {
                "severity": "warn",
                "category": "backtest",
                "title": "Backtest history still seeding",
                "summary": (
                    f"{report.valid_runs} valid run snapshot(s) — need ≥2 weekly archives "
                    "before forward-return backtest populates."
                ),
                "auto_fixable": False,
            }
        )
    return rows
