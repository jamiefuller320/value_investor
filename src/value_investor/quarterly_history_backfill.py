"""Keep a short Yahoo quarterly history across financials rewrites.

Yahoo's quarterly frames hold about four periods, and ``ingest_research_sources``
used to overwrite ``financials_annual.json`` on every fetch. The operating-decline
gate compares the latest interim period with the same period a year earlier, so
the quarter that just rolled off the frame is the one it needs.

``merge_quarterly_history`` unions ``quarterly_income`` and ``quarterly_cashflow``
by period-end date. Newly fetched rows replace the same period. At most
``QUARTERLY_HISTORY_KEEP`` periods are stored, newest first. Annual statements,
``cashflow_metrics`` and every other key stay on the incoming payload.

The CLI walks ``git log`` for the same file and merges older blobs the same way.
Current period values win. Only periods older than the newest dated period
already on that series are added. A trailing cash-flow source is not extended.
A shallow clone has no older blobs to read; the report says ``history unavailable``
and writes nothing.

Point-in-time: this does not rebuild a statement as of a past date. ``fetched_at``
on the current file is left as it is, and values already stored for a period are
not replaced from an older commit.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from value_investor.operating_decline_gate import (
    _latest_interim_period,
    _prior_period,
    _rows_by_period,
)

QUARTERLY_HISTORY_KEEP = 12
MAX_GIT_VERSIONS = 60
QUARTERLY_SERIES_KEYS = ("quarterly_income", "quarterly_cashflow")
HISTORY_UNAVAILABLE = "history unavailable"
STATEMENT_NAME = "financials_annual.json"


def _period_end_key(key: Any) -> str | None:
    """Return ``YYYY-MM-DD`` when ``key`` starts with a real calendar date."""

    text = str(key).strip()
    if len(text) < 10:
        return None
    day = text[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return None
    return day


def _period_sort_key(period: str) -> tuple[int, str]:
    day = _period_end_key(period)
    if day is None:
        return (0, period)
    return (1, day)


def _copy_period_row(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return dict(value)


def merge_quarterly_series(
    existing: Any,
    incoming: Any,
    *,
    max_periods: int = QUARTERLY_HISTORY_KEEP,
) -> dict[str, dict[str, Any]]:
    """Union period-end keys. Incoming rows replace existing rows on overlap.

    Malformed sections (not a dict) contribute no periods. A period whose row is
    not a dict is skipped. A key that is a calendar date (``YYYY-MM-DD``, or a
    longer timestamp beginning with one) is a period end; timestamps collapse to
    that date. Incoming rows replace existing rows on the same date. Dated
    periods are newest first and capped at ``max_periods``. Other keys already
    stored (a bare fiscal year, for example) are kept and are not part of the
    cap, so a rewrite does not drop them. ``max_periods`` below 1 yields ``{}``.
    A non-integer cap falls back to ``QUARTERLY_HISTORY_KEEP``.
    """

    try:
        limit = int(max_periods)
    except (TypeError, ValueError):
        limit = QUARTERLY_HISTORY_KEEP
    if limit < 1:
        return {}

    dated: dict[str, dict[str, Any]] = {}
    undated: dict[str, dict[str, Any]] = {}
    undated_order: list[str] = []
    for source in (existing, incoming):
        if not isinstance(source, dict):
            continue
        for key, row in source.items():
            copied = _copy_period_row(row)
            if copied is None:
                continue
            period = _period_end_key(key)
            if period is None:
                text = str(key).strip()
                if not text:
                    continue
                if text not in undated:
                    undated_order.append(text)
                undated[text] = copied
                continue
            dated[period] = copied
    ordered = sorted(dated, key=_period_sort_key, reverse=True)
    merged = {period: dated[period] for period in ordered[:limit]}
    for text in undated_order:
        merged[text] = undated[text]
    return merged


def merge_quarterly_history(
    existing: Any,
    incoming: Any,
    *,
    max_periods: int = QUARTERLY_HISTORY_KEEP,
) -> dict[str, Any]:
    """Return ``incoming`` with quarterly series merged from ``existing``.

    Incoming supplies every non-quarterly key, including annual statements and
    ``cashflow_metrics``. When either side has a quarterly series, the merged
    payload sets ``quarterly_history_kept`` to the longer of the stored income
    and cash-flow series. Inputs are not mutated.
    """

    base = dict(incoming) if isinstance(incoming, dict) else {}
    existing_dict = existing if isinstance(existing, dict) else {}
    touched = False
    for key in QUARTERLY_SERIES_KEYS:
        has_existing = isinstance(existing_dict.get(key), dict)
        has_incoming = isinstance(base.get(key), dict)
        if not has_existing and not has_incoming:
            continue
        base[key] = merge_quarterly_series(
            existing_dict.get(key),
            base.get(key),
            max_periods=max_periods,
        )
        touched = True
    if touched:
        lengths = [
            len(base[key]) for key in QUARTERLY_SERIES_KEYS if isinstance(base.get(key), dict)
        ]
        base["quarterly_history_kept"] = max(lengths) if lengths else 0
    return base


def _not_newer_than_current(
    current: Any,
    merged: Any,
    *,
    max_periods: int,
) -> dict[str, dict[str, Any]]:
    """Add older dated periods without changing rows already on ``current``.

    Every current key and row is kept, including keys that are not dates. Dated
    history is added only when it is strictly older than the newest dated period
    already stored. A current series with no dated period is not filled from
    history. The cap drops oldest added dates first and never drops a current key.
    """

    if not isinstance(current, dict):
        return {}
    kept: dict[str, dict[str, Any]] = {}
    for key, row in current.items():
        copied = _copy_period_row(row)
        if copied is None:
            continue
        kept[str(key)] = copied
    present = {day for key in kept if (day := _period_end_key(key))}
    if not present:
        return kept
    newest = max(present)
    dated = merge_quarterly_series(None, merged, max_periods=max(max_periods, 10_000))
    older = [
        period
        for period in dated
        if _period_end_key(period) == period and period < newest and period not in present
    ]
    room = max(int(max_periods) - len(kept), 0)
    for period in older[:room]:
        kept[period] = dated[period]
    ordered = sorted(
        (key for key in kept if _period_end_key(key)), key=_period_sort_key, reverse=True
    )
    undated = [key for key in kept if _period_end_key(key) is None]
    return {key: kept[key] for key in ordered + undated}


def _restrict_backfill_series(
    accumulated: dict[str, Any],
    current: dict[str, Any],
    *,
    max_periods: int,
) -> None:
    """Drop periods newer than the current series, and leave trailing cash flow alone."""

    for key in QUARTERLY_SERIES_KEYS:
        current_series = current.get(key)
        if key == "quarterly_cashflow" and "(trailing)" in str(
            current.get("quarterly_cashflow_source") or ""
        ):
            if isinstance(current_series, dict):
                accumulated[key] = current_series
            else:
                accumulated.pop(key, None)
            continue
        if not isinstance(current_series, dict):
            accumulated.pop(key, None)
            continue
        accumulated[key] = _not_newer_than_current(
            current_series,
            accumulated.get(key),
            max_periods=max_periods,
        )
    if any(isinstance(accumulated.get(key), dict) for key in QUARTERLY_SERIES_KEYS):
        accumulated["quarterly_history_kept"] = _history_kept(accumulated)


def _history_kept(payload: dict[str, Any]) -> int:
    lengths = [
        len(payload[key]) for key in QUARTERLY_SERIES_KEYS if isinstance(payload.get(key), dict)
    ]
    return max(lengths) if lengths else 0


def prior_year_period_end(quarterly: Any, *, as_of: date) -> str | None:
    """Period end within the gate's year-on-year window, if the series has one.

    Uses the same latest-period and 45-day rule as the operating-decline gate.
    The latest period is the newest row on or before ``as_of`` that carries
    revenue or EPS.
    """

    rows = _rows_by_period(quarterly, as_of)
    latest = _latest_interim_period(rows)
    if latest is None:
        return None
    prior = _prior_period(rows, latest)
    if prior is None:
        return None
    return prior.isoformat()


def load_financials_dict(path: Path) -> dict[str, Any] | None:
    """Read a financials payload. Missing or unreadable files return None."""

    from value_investor.storage import read_json, resolve_json_path

    resolved = resolve_json_path(Path(path))
    if resolved is None:
        return None
    try:
        payload = read_json(resolved)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def history_status(repo: Path) -> str:
    """``available`` or ``history unavailable`` when git cannot show older blobs."""

    probe = _git(repo, "rev-parse", "--is-shallow-repository")
    if probe.returncode != 0:
        return HISTORY_UNAVAILABLE
    if probe.stdout.strip() == "true":
        return HISTORY_UNAVAILABLE
    return "available"


def _git_versions(repo: Path, relpath: str, *, limit: int) -> list[str] | None:
    log = _git(repo, "log", "--format=%H", "-n", str(limit), "--", relpath)
    if log.returncode != 0:
        return None
    return [line.strip() for line in log.stdout.splitlines() if line.strip()]


def _git_blob(repo: Path, rev: str, relpath: str) -> dict[str, Any] | None:
    shown = subprocess.run(
        ["git", "-C", str(repo), "show", f"{rev}:{relpath}"],
        check=False,
        capture_output=True,
    )
    if shown.returncode != 0 or not shown.stdout:
        return None
    try:
        payload = json.loads(shown.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _repo_relpath(repo: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None


def _dumps_like(payload: dict[str, Any], *, trailing_newline: bool) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if trailing_newline:
        text += "\n"
    return text


def _series_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return any(before.get(key) != after.get(key) for key in QUARTERLY_SERIES_KEYS)


def backfill_file(
    path: Path,
    *,
    repo: Path,
    apply: bool,
    as_of: date,
    max_versions: int = MAX_GIT_VERSIONS,
    max_periods: int = QUARTERLY_HISTORY_KEEP,
    history: str | None = None,
) -> dict[str, Any]:
    """Merge older git versions of one financials file into the working copy.

    Current period values win. Only periods older than the newest period already
    on that series are added. A ``(trailing)`` cash-flow source is left as stored:
    it is one trailing-twelve-month figure, and an extra period would make the
    TTM reader sum it. Dry-run (``apply`` false) reports the merge and does not
    write. Returns a JSON-ready row.
    """

    resolved = Path(path)
    ticker = _ticker_from_path(resolved)
    row: dict[str, Any] = {
        "ticker": ticker,
        "path": str(resolved),
        "status": "unchanged",
        "income_before": 0,
        "income_after": 0,
        "cashflow_before": 0,
        "cashflow_after": 0,
        "prior_year_before": None,
        "prior_year_after": None,
        "gained_prior_year": False,
        "versions": 0,
        "skipped_blobs": 0,
        "note": "",
    }
    if history is None:
        history = history_status(repo)
    if history != "available":
        row["status"] = "history_unavailable"
        row["note"] = HISTORY_UNAVAILABLE
        return row
    if not resolved.is_file():
        row["status"] = "missing"
        return row
    try:
        original = resolved.read_text(encoding="utf-8")
        current = json.loads(original)
    except (OSError, UnicodeDecodeError, ValueError):
        row["status"] = "unreadable"
        return row
    if not isinstance(current, dict):
        row["status"] = "unreadable"
        return row

    income = current.get("quarterly_income")
    cashflow = current.get("quarterly_cashflow")
    row["income_before"] = len(income) if isinstance(income, dict) else 0
    row["cashflow_before"] = len(cashflow) if isinstance(cashflow, dict) else 0
    row["prior_year_before"] = prior_year_period_end(income, as_of=as_of)

    relpath = _repo_relpath(repo, resolved)
    if relpath is None:
        row["status"] = "history_unavailable"
        row["note"] = HISTORY_UNAVAILABLE
        return row
    versions = _git_versions(repo, relpath, limit=max_versions)
    if versions is None:
        row["status"] = "history_unavailable"
        row["note"] = HISTORY_UNAVAILABLE
        return row
    row["versions"] = len(versions)

    accumulated = current
    for rev in versions:
        blob = _git_blob(repo, rev, relpath)
        if blob is None:
            row["skipped_blobs"] += 1
            continue
        accumulated = merge_quarterly_history(blob, accumulated, max_periods=max_periods)

    _restrict_backfill_series(accumulated, current, max_periods=max_periods)

    merged_income = accumulated.get("quarterly_income")
    merged_cashflow = accumulated.get("quarterly_cashflow")
    row["income_after"] = len(merged_income) if isinstance(merged_income, dict) else 0
    row["cashflow_after"] = len(merged_cashflow) if isinstance(merged_cashflow, dict) else 0
    row["prior_year_after"] = prior_year_period_end(merged_income, as_of=as_of)
    row["gained_prior_year"] = bool(row["prior_year_after"]) and not row["prior_year_before"]

    if not _series_changed(current, accumulated):
        row["status"] = "unchanged"
        return row
    row["status"] = "would_write"
    if apply:
        text = _dumps_like(accumulated, trailing_newline=original.endswith("\n"))
        resolved.write_text(text, encoding="utf-8")
        row["status"] = "wrote"
    return row


def _ticker_from_path(path: Path) -> str:
    parts = path.parts
    if "sources" in parts:
        index = parts.index("sources")
        if index > 0:
            return parts[index - 1]
    return path.parent.name


def _clean_ticker(ticker: str) -> str | None:
    text = ticker.strip().upper()
    if not text or any(token in text for token in ("/", "\\", "..")):
        return None
    return text


def _ftse_screen_paths(data_dir: Path) -> list[Path]:
    latest_path = data_dir / "latest.json"
    if not latest_path.is_file():
        return []
    try:
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    paths: list[Path] = []
    seen: set[str] = set()
    for row in payload.get("reports") or []:
        if not isinstance(row, dict):
            continue
        ticker = _clean_ticker(str(row.get("ticker") or ""))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        path = data_dir / "research" / ticker / "sources" / STATEMENT_NAME
        if path.is_file():
            paths.append(path)
    return paths


def _library_paths(data_dir: Path) -> list[Path]:
    markets = data_dir / "library" / "markets"
    if not markets.is_dir():
        return []
    paths: list[Path] = []
    for market in sorted(path for path in markets.iterdir() if path.is_dir()):
        research = market / "screen" / "research"
        if not research.is_dir():
            continue
        for ticker_dir in sorted(path for path in research.iterdir() if path.is_dir()):
            path = ticker_dir / "sources" / STATEMENT_NAME
            if path.is_file():
                paths.append(path)
    return paths


def _paths_for_ticker(data_dir: Path, ticker: str, *, include_library: bool) -> list[Path]:
    paths: list[Path] = []
    ftse = data_dir / "research" / ticker / "sources" / STATEMENT_NAME
    if ftse.is_file():
        paths.append(ftse)
    if include_library:
        markets = data_dir / "library" / "markets"
        if markets.is_dir():
            for market in sorted(path for path in markets.iterdir() if path.is_dir()):
                candidate = market / "screen" / "research" / ticker / "sources" / STATEMENT_NAME
                if candidate.is_file():
                    paths.append(candidate)
    if not paths:
        paths.append(ftse)
    return paths


def collect_financials_paths(
    data_dir: Path,
    *,
    tickers: list[str] | None = None,
    limit: int | None = None,
    include_library: bool = True,
) -> list[Path]:
    """FTSE screen files first, then library research files, unless tickers are named."""

    data_dir = Path(data_dir)
    if tickers:
        paths: list[Path] = []
        for raw in tickers:
            ticker = _clean_ticker(raw)
            if ticker is None:
                continue
            paths.extend(_paths_for_ticker(data_dir, ticker, include_library=include_library))
    else:
        paths = _ftse_screen_paths(data_dir)
        if include_library:
            seen = {path.resolve() for path in paths}
            for path in _library_paths(data_dir):
                if path.resolve() not in seen:
                    paths.append(path)
                    seen.add(path.resolve())
    if limit is not None and limit >= 0:
        return paths[:limit]
    return paths


def run_quarterly_backfill(
    *,
    data_dir: Path,
    repo: Path,
    tickers: list[str] | None = None,
    limit: int | None = None,
    include_library: bool = True,
    apply: bool = False,
    as_of: date | None = None,
    max_versions: int = MAX_GIT_VERSIONS,
    max_periods: int = QUARTERLY_HISTORY_KEEP,
) -> dict[str, Any]:
    """Backfill each selected financials file. Dry-run unless ``apply`` is set."""

    as_of_date = as_of or datetime.now(UTC).date()
    history = history_status(repo)
    paths = collect_financials_paths(
        data_dir,
        tickers=tickers,
        limit=limit,
        include_library=include_library,
    )
    results = [
        backfill_file(
            path,
            repo=repo,
            apply=apply and history == "available",
            as_of=as_of_date,
            max_versions=max_versions,
            max_periods=max_periods,
            history=history,
        )
        for path in paths
    ]
    summary = {
        "files": len(results),
        "wrote": sum(1 for row in results if row["status"] == "wrote"),
        "would_write": sum(1 for row in results if row["status"] == "would_write"),
        "unchanged": sum(1 for row in results if row["status"] == "unchanged"),
        "missing": sum(1 for row in results if row["status"] == "missing"),
        "unreadable": sum(1 for row in results if row["status"] == "unreadable"),
        "history_unavailable": sum(1 for row in results if row["status"] == "history_unavailable"),
        "prior_year_before": sum(1 for row in results if row["prior_year_before"]),
        "prior_year_after": sum(1 for row in results if row["prior_year_after"]),
        "gained_prior_year": sum(1 for row in results if row["gained_prior_year"]),
    }
    return {
        "history": history,
        "apply": bool(apply),
        "as_of": as_of_date.isoformat(),
        "max_versions": max_versions,
        "max_periods": max_periods,
        "summary": summary,
        "results": results,
    }


def format_backfill_text(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        f"history: {report.get('history')}",
        (
            f"files {summary.get('files', 0)}: "
            f"wrote {summary.get('wrote', 0)}, "
            f"would_write {summary.get('would_write', 0)}, "
            f"unchanged {summary.get('unchanged', 0)}, "
            f"missing {summary.get('missing', 0)}, "
            f"unreadable {summary.get('unreadable', 0)}"
        ),
        (
            f"same-quarter prior year: "
            f"{summary.get('prior_year_before', 0)} → {summary.get('prior_year_after', 0)} "
            f"(gained {summary.get('gained_prior_year', 0)})"
        ),
    ]
    if report.get("history") != "available":
        lines.append(HISTORY_UNAVAILABLE)
    for row in report.get("results") or []:
        if row.get("status") in {"unchanged", "missing"} and not row.get("gained_prior_year"):
            continue
        lines.append(
            f"  {row.get('ticker')} [{row.get('status')}] "
            f"income {row.get('income_before')}→{row.get('income_after')} "
            f"cashflow {row.get('cashflow_before')}→{row.get('cashflow_after')} "
            f"prior {row.get('prior_year_before') or '—'}→{row.get('prior_year_after') or '—'}"
        )
    return "\n".join(lines) + "\n"


def _parse_tickers(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    tickers: list[str] = []
    for value in values:
        for part in value.split(","):
            text = part.strip()
            if text:
                tickers.append(text)
    return tickers or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Merge older Yahoo quarterly periods from git history into "
            "financials_annual.json. Current period values win. Dry-run unless "
            "--apply. A shallow clone reports history unavailable and writes nothing."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("docs/data"),
        help="Root holding latest.json, research/ and library/ (default: docs/data)",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Git working tree (default: current directory)",
    )
    parser.add_argument(
        "--tickers",
        action="append",
        default=None,
        help="Comma-separated tickers. Repeatable. Default: FTSE screen rows, then library.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Process at most this many files")
    parser.add_argument(
        "--no-library",
        action="store_true",
        help="Skip library market research directories",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write merged files. Default is a dry run.",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Date YYYY-MM-DD for the prior-year report (default: today UTC). Does not drop periods.",
    )
    parser.add_argument(
        "--max-versions",
        type=int,
        default=MAX_GIT_VERSIONS,
        help=f"Git commits to read per file (default: {MAX_GIT_VERSIONS})",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=QUARTERLY_HISTORY_KEEP,
        help=f"Newest periods to retain (default: {QUARTERLY_HISTORY_KEEP})",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    args = parser.parse_args(argv)

    as_of: date | None = None
    if args.as_of:
        try:
            as_of = date.fromisoformat(args.as_of)
        except ValueError:
            sys.stderr.write(f"unparseable --as-of: {args.as_of}\n")
            return 2
    if args.limit is not None and args.limit < 0:
        sys.stderr.write("--limit must be >= 0\n")
        return 2
    repo = args.repo or Path.cwd()
    report = run_quarterly_backfill(
        data_dir=args.data_dir,
        repo=repo,
        tickers=_parse_tickers(args.tickers),
        limit=args.limit,
        include_library=not args.no_library,
        apply=args.apply,
        as_of=as_of,
        max_versions=args.max_versions,
        max_periods=args.keep,
    )
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(format_backfill_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
