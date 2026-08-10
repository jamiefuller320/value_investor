"""Compact JSON, optional gzip, and retention helpers for growing artifacts."""

from __future__ import annotations

import gzip
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Align with historical analysis window.
MAX_HISTORY_YEARS = 3
# Git-tracked mirror of output/history for CI (see restore/publish helpers below).
COMMITTED_HISTORY_DIR = Path("docs/data/history")
_HISTORY_SNAPSHOT_GLOBS = (
    "run_*.json",
    "run_*.json.gz",
    "models_*.json",
    "models_*.json.gz",
)
# Keep a short rolling set of dashboard archives in git (not full history).
DASHBOARD_ARCHIVE_KEEP = 8
# Dashboard research index stores a short blurb, not the full memo.
SUMMARY_SNIPPET_CHARS = 400

COMPACT_SEPARATORS = (",", ":")

_STAMP_RE = re.compile(r"(?:^|_)(\d{8})(?:_(\d{6}))?(?:\.[^.]+)*$")
_DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json(?:\.gz)?$")


def dumps_json(data: Any, *, compact: bool = True) -> str:
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=COMPACT_SEPARATORS)
    return json.dumps(data, ensure_ascii=False, indent=2)


def write_json(
    path: Path,
    data: Any,
    *,
    compact: bool = True,
    compress: bool = False,
) -> Path:
    """
    Write JSON to ``path``.

    When ``compress`` is True, writes gzip to a ``.json.gz`` path (adds suffix if needed).
    """
    target = path
    if compress:
        if target.suffix == ".gz":
            pass
        elif target.suffix == ".json":
            target = target.with_suffix(".json.gz")
        else:
            target = Path(str(target) + ".json.gz")

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dumps_json(data, compact=compact).encode("utf-8")
    if compress or target.suffix == ".gz":
        with gzip.open(target, "wb") as handle:
            handle.write(payload)
    else:
        target.write_bytes(payload)
    return target


def read_json(path: Path) -> Any:
    """Read JSON from a plain or gzip-compressed file."""
    resolved = resolve_json_path(path)
    if resolved is None:
        raise FileNotFoundError(path)
    if resolved.suffix == ".gz" or resolved.name.endswith(".json.gz"):
        with gzip.open(resolved, "rb") as handle:
            return json.loads(handle.read().decode("utf-8"))
    return json.loads(resolved.read_text(encoding="utf-8"))


def resolve_json_path(path: Path) -> Path | None:
    """
    Prefer an existing path; if missing, try sibling ``.json`` / ``.json.gz`` variants.
    """
    candidates: list[Path] = [path]
    name = path.name
    if name.endswith(".json.gz"):
        candidates.append(path.with_name(name[: -len(".gz")]))
    elif name.endswith(".json"):
        candidates.append(path.with_name(name + ".gz"))
    else:
        candidates.append(Path(str(path) + ".json"))
        candidates.append(Path(str(path) + ".json.gz"))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def summarize_text(text: str, *, max_chars: int = SUMMARY_SNIPPET_CHARS) -> str:
    """Collapse whitespace and truncate for dashboard index payloads."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    truncated = cleaned[: max_chars - 1].rsplit(" ", 1)[0]
    return (truncated or cleaned[: max_chars - 1]).rstrip(",;:") + "…"


def history_cutoff(*, max_years: int = MAX_HISTORY_YEARS, now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current - timedelta(days=int(365.25 * max_years))


def _stamp_datetime(path: Path) -> datetime | None:
    match = _STAMP_RE.search(path.name)
    if not match:
        return None
    day = match.group(1)
    time_part = match.group(2) or "000000"
    try:
        return datetime.strptime(f"{day}{time_part}", "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _archive_date(path: Path) -> datetime | None:
    match = _DATE_FILE_RE.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def prune_paths_older_than(paths: list[Path], cutoff: datetime) -> list[Path]:
    """Delete files whose embedded stamp/date (or mtime fallback) is before cutoff."""
    removed: list[Path] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        stamped = _stamp_datetime(path) or _archive_date(path)
        if stamped is None:
            stamped = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if stamped < cutoff:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


def history_snapshot_paths(history_dir: Path) -> list[Path]:
    """List run/model snapshot files under a history directory."""
    paths: list[Path] = []
    if not history_dir.exists():
        return paths
    for pattern in _HISTORY_SNAPSHOT_GLOBS:
        paths.extend(history_dir.glob(pattern))
    return paths


def prune_history_dir(
    output_dir: Path,
    *,
    max_years: int = MAX_HISTORY_YEARS,
    now: datetime | None = None,
) -> list[Path]:
    """Remove run/model snapshots older than the retention window."""
    history_dir = output_dir / "history"
    if not history_dir.exists():
        return []
    cutoff = history_cutoff(max_years=max_years, now=now)
    return prune_paths_older_than(history_snapshot_paths(history_dir), cutoff)


def restore_committed_run_history(
    output_dir: Path,
    *,
    committed_dir: Path | None = None,
) -> int:
    """
    Copy git-tracked run/model snapshots into ``output/history`` before a screen.

    Skips files that already exist locally so dev runs are not overwritten.
    """
    source = committed_dir or COMMITTED_HISTORY_DIR
    if not source.exists():
        return 0
    dest = output_dir / "history"
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in history_snapshot_paths(source):
        target = dest / path.name
        if target.exists():
            continue
        shutil.copy2(path, target)
        copied += 1
    return copied


def publish_committed_run_history(
    output_dir: Path,
    *,
    committed_dir: Path | None = None,
    max_years: int = MAX_HISTORY_YEARS,
    now: datetime | None = None,
) -> dict[str, int]:
    """
    Mirror ``output/history`` into ``docs/data/history`` for git commit.

    Applies the same retention window as local ``output/history``.
    Skips new run snapshots that fail backtest health validation (pollution guard).
    """
    from value_investor.backtest_health import validate_history_before_publish

    source = output_dir / "history"
    dest = committed_dir or COMMITTED_HISTORY_DIR
    dest.mkdir(parents=True, exist_ok=True)
    blocked = validate_history_before_publish(output_dir, committed_dir=dest)
    blocked_names = {
        Path(row.path).name for row in blocked if Path(row.path).suffix in {".json", ".gz"}
    }
    copied = 0
    skipped = 0
    if source.exists():
        for path in history_snapshot_paths(source):
            if path.name in blocked_names and not (dest / path.name).exists():
                skipped += 1
                continue
            shutil.copy2(path, dest / path.name)
            copied += 1
    pruned = prune_paths_older_than(
        history_snapshot_paths(dest),
        history_cutoff(max_years=max_years, now=now),
    )
    return {"copied": copied, "pruned": len(pruned), "skipped_invalid": skipped}


def prune_timestamped_outputs(
    output_dir: Path,
    *,
    max_years: int = MAX_HISTORY_YEARS,
    now: datetime | None = None,
) -> list[Path]:
    """Remove aged per-run CSV/JSON copies under output/ (keeps latest_* files)."""
    if not output_dir.exists():
        return []
    cutoff = history_cutoff(max_years=max_years, now=now)
    patterns = (
        "signals_*.csv",
        "model_results_*.csv",
        "universe_*.csv",
        "summary_*.json",
        "summary_*.json.gz",
    )
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(output_dir.glob(pattern))
    return prune_paths_older_than(paths, cutoff)


def prune_research_source_batches(
    output_dir: Path,
    *,
    max_years: int = MAX_HISTORY_YEARS,
    now: datetime | None = None,
) -> list[Path]:
    """Remove aged news_batch_* files under research/*/sources/."""
    research_root = output_dir / "research"
    if not research_root.exists():
        return []
    cutoff = history_cutoff(max_years=max_years, now=now)
    paths = list(research_root.glob("*/sources/news_batch_*.json"))
    paths.extend(research_root.glob("*/sources/news_batch_*.json.gz"))
    return prune_paths_older_than(paths, cutoff)


def prune_dashboard_archives(
    archive_dir: Path,
    *,
    keep: int = DASHBOARD_ARCHIVE_KEEP,
) -> list[Path]:
    """Keep only the newest ``keep`` dated dashboard archive files."""
    if keep < 1 or not archive_dir.exists():
        return []
    archives = [
        path for path in archive_dir.iterdir() if path.is_file() and _archive_date(path) is not None
    ]
    archives.sort(
        key=lambda path: _archive_date(path) or datetime.min.replace(tzinfo=UTC), reverse=True
    )
    removed: list[Path] = []
    for path in archives[keep:]:
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed


def apply_output_retention(
    output_dir: Path,
    *,
    max_years: int = MAX_HISTORY_YEARS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Run all local output retention passes; return counts removed per bucket."""
    return {
        "history": len(prune_history_dir(output_dir, max_years=max_years, now=now)),
        "timestamped_outputs": len(
            prune_timestamped_outputs(output_dir, max_years=max_years, now=now)
        ),
        "research_batches": len(
            prune_research_source_batches(output_dir, max_years=max_years, now=now)
        ),
    }
