"""Per-process shards of real Cursor SDK agent token usage.

``record_agent_usage`` calls ``agent.get_usage`` after a run finishes. A
recording failure is logged and stored as ``usage_error``; it never changes
the caller's result. The helper is a no-op under pytest (unless
``FTSE_AGENT_USAGE_RECORD=1``) and when the object has no ``get_usage``.

Each process appends to its own new file
``docs/data/agent_usage/<YYYY-MM-DD>/<job>-<id>.jsonl``. Shards are never
rewritten, so reset-and-overlay, rebase, and merge cannot drop another job's
rows. Cost lag is filled into ``docs/data/agent_usage_cost_backfill.json``
(ops-monitor only), not into the shards.

``Agent.resume`` plus ``get_usage`` are unary RPCs: resume returns a handle
and does not call ``send``; ``GetUsage`` is read-only
(``cursor_sdk/_agent.py`` ``Agent.get_usage``, ``cursor_sdk/_client.py``
``Client.resume_agent``).
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import tempfile
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SHARD_DIR = Path("docs/data/agent_usage")
DEFAULT_LEGACY_LOG_PATH = Path("docs/data/agent_usage_log.jsonl")
DEFAULT_BACKFILL_PATH = Path("docs/data/agent_usage_cost_backfill.json")
# Kept so older callers that passed the single log still compile. New writes
# go to a shard; the report still reads this file when it exists.
DEFAULT_LOG_PATH = DEFAULT_LEGACY_LOG_PATH
BACKFILL_MAX_AGE_DAYS = 7

_PROCESS_SHARD_ID: str | None = None
_shard_paths: dict[str, Path] = {}

_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
    "reasoning_tokens",
)


def _recording_enabled() -> bool:
    flag = os.environ.get("FTSE_AGENT_USAGE_RECORD", "").strip()
    if flag == "1":
        return True
    if flag == "0":
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _backfill_enabled() -> bool:
    flag = os.environ.get("FTSE_AGENT_USAGE_BACKFILL", "").strip()
    if flag == "1":
        return True
    if flag == "0":
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _lock_path(log_path: Path) -> Path:
    """Lock beside the file in the system temp dir so git never commits it."""
    digest = hashlib.sha256(str(log_path.resolve()).encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"ftse-agent-usage-{digest}.lock"


def reset_process_shard_state() -> None:
    """Forget the process shard id. Tests use this; production calls it never."""
    global _PROCESS_SHARD_ID
    _PROCESS_SHARD_ID = None
    _shard_paths.clear()


def process_shard_id() -> str:
    """Id unique to this process.

    GitHub Actions: ``GITHUB_RUN_ID-GITHUB_RUN_ATTEMPT-<pid>-<suffix>``.
    Anywhere else: a uuid. The suffix keeps two processes in one job apart.
    """
    global _PROCESS_SHARD_ID
    if _PROCESS_SHARD_ID is not None:
        return _PROCESS_SHARD_ID
    suffix = uuid.uuid4().hex[:8]
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    if run_id:
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "").strip() or "1"
        _PROCESS_SHARD_ID = f"{run_id}-{attempt}-{os.getpid()}-{suffix}"
    else:
        _PROCESS_SHARD_ID = uuid.uuid4().hex
    return _PROCESS_SHARD_ID


def _safe_job_name(job: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (job or "").strip())
    return cleaned or "job"


def shard_path_for_job(
    job: str,
    *,
    now: datetime | None = None,
    shard_dir: Path | None = None,
) -> Path:
    """One new file per process per job. Threads in the process share it."""
    root = Path(shard_dir) if shard_dir is not None else DEFAULT_SHARD_DIR
    cache_key = f"{root}|{_safe_job_name(job)}"
    cached = _shard_paths.get(cache_key)
    if cached is not None:
        return cached
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    day = moment.astimezone(UTC).strftime("%Y-%m-%d")
    path = root / day / f"{_safe_job_name(job)}-{process_shard_id()}.jsonl"
    _shard_paths[cache_key] = path
    return path


@contextmanager
def _exclusive_lock(log_path: Path) -> Iterator[None]:
    """Serialize appends from threads in this process. Shards are not shared."""
    lock_path = _lock_path(log_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _append_line_unlocked(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line if line.endswith("\n") else f"{line}\n")
        handle.flush()
        os.fsync(handle.fileno())


def _json_default(value: Any) -> str:
    return str(value)


def _result_run_id(result: Any) -> str | None:
    if result is None:
        return None
    value = getattr(result, "id", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _is_bad_run_id(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return "badrequest" in name or "run-" in text or "usage uuid" in text


def _call_get_usage(agent: Any, run_id: str | None) -> tuple[str, Any]:
    get_usage = getattr(agent, "get_usage", None)
    if not callable(get_usage):
        return "missing", None
    client_minted = bool(run_id) and str(run_id).startswith("run-")
    try:
        if run_id and not client_minted:
            try:
                return "ok", get_usage(run_id=run_id)
            except Exception as exc:
                if not _is_bad_run_id(exc):
                    raise
                logger.info(
                    "get_usage rejected run_id %s (%s); retrying unfiltered",
                    run_id,
                    exc,
                )
        return "ok", get_usage()
    except Exception as exc:
        return "error", exc


def _select_usage(agent_usage: Any, run_id: str | None) -> tuple[Any, Any, str | None]:
    """Pick the turn this row should attribute.

    Local agents key ``runs[].run_id`` by a usage UUID, not the client
    ``run-<uuid>`` on ``RunResult.id``. Passing that client id to
    ``get_usage(run_id=...)`` raises ``BadRequestError``. When several turns
    are returned, the last one is the send that just finished; agent totals
    would double-count a resumed agent.
    """
    runs = list(getattr(agent_usage, "runs", ()) or ())
    chosen = None
    if run_id:
        for run in runs:
            if str(getattr(run, "run_id", "") or "") == run_id:
                chosen = run
                break
    if chosen is None and len(runs) == 1:
        chosen = runs[0]
    elif chosen is None and len(runs) > 1:
        chosen = runs[-1]
    if chosen is not None:
        usage_run_id = str(getattr(chosen, "run_id", "") or "") or None
        return getattr(chosen, "usage", None), getattr(chosen, "cost", None), usage_run_id
    return (
        getattr(agent_usage, "usage", None),
        getattr(agent_usage, "cost", None),
        None,
    )


def _token_payload(usage: Any) -> dict[str, int | None]:
    payload: dict[str, int | None] = {}
    for name in _TOKEN_FIELDS:
        raw = getattr(usage, name, None) if usage is not None else None
        if raw is None:
            payload[name] = None
            continue
        try:
            payload[name] = int(raw)
        except (TypeError, ValueError):
            payload[name] = None
    return payload


def _cost_payload(cost: Any) -> tuple[float | None, float | None, bool]:
    if cost is None:
        return None, None, True
    try:
        raw_cost = float(cost.raw_cost_cents)
        charged = float(cost.charged_cents)
    except (TypeError, ValueError, AttributeError):
        return None, None, True
    return raw_cost, charged, False


def _blank_row(
    *,
    job: str,
    model: str | None,
    agent_id: str | None,
    run_id: str | None,
    ticker: str | None,
    pool: str | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema_version": 1,
        "row_id": uuid.uuid4().hex,
        "timestamp": datetime.now(UTC).isoformat(),
        "job": job,
        "model": model,
        "agent_id": agent_id,
        "run_id": run_id,
        "usage_run_id": None,
        "ticker": ticker,
        "pool": pool,
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "total_tokens": None,
        "reasoning_tokens": None,
        "raw_cost_cents": None,
        "charged_cents": None,
        "cost_pending": True,
        "usage_error": None,
    }
    return row


def record_agent_usage(
    agent: Any,
    *,
    job: str,
    model: str | None,
    run_id: str | None = None,
    ticker: str | None = None,
    pool: str | None = None,
    extra: Mapping[str, Any] | None = None,
    log_path: Path | None = None,
) -> dict[str, Any] | None:
    """Record one agent run. Never raises into the caller.

    Returns the stored row, or ``None`` when recording is disabled or the
    object has no ``get_usage`` (test doubles and pytest).
    """
    try:
        return _record_agent_usage(
            agent,
            job=job,
            model=model,
            run_id=run_id,
            ticker=ticker,
            pool=pool,
            extra=extra,
            log_path=log_path,
        )
    except Exception:
        logger.exception("agent usage record failed for job %s", job)
        return None


def _record_agent_usage(
    agent: Any,
    *,
    job: str,
    model: str | None,
    run_id: str | None,
    ticker: str | None,
    pool: str | None,
    extra: Mapping[str, Any] | None,
    log_path: Path | None,
) -> dict[str, Any] | None:
    if not _recording_enabled():
        return None
    if not callable(getattr(agent, "get_usage", None)):
        return None

    agent_id = getattr(agent, "agent_id", None)
    if agent_id is not None:
        agent_id = str(agent_id) or None
    row = _blank_row(
        job=job,
        model=model,
        agent_id=agent_id,
        run_id=run_id,
        ticker=ticker,
        pool=pool,
    )
    status, payload = _call_get_usage(agent, run_id)
    if status == "missing":
        return None
    if status == "error":
        message = str(payload)[:500]
        row["usage_error"] = message
        logger.warning("agent get_usage failed for %s: %s", job, message)
    else:
        usage, cost, usage_run_id = _select_usage(payload, run_id)
        row.update(_token_payload(usage))
        raw_cost, charged, pending = _cost_payload(cost)
        row["raw_cost_cents"] = raw_cost
        row["charged_cents"] = charged
        row["cost_pending"] = pending
        row["usage_run_id"] = usage_run_id
    if extra:
        for key, value in extra.items():
            if key not in row:
                row[key] = value

    if log_path is not None:
        path = Path(log_path)
    else:
        path = shard_path_for_job(job)
    line = json.dumps(row, ensure_ascii=False, default=_json_default)
    with _exclusive_lock(path):
        _append_line_unlocked(path, line)
    return row


def prompt_and_record(
    message: Any,
    options: Any,
    *,
    job: str,
    model: str | None = None,
    ticker: str | None = None,
    pool: str | None = None,
    extra: Mapping[str, Any] | None = None,
    agent_cls: Any = None,
) -> Any:
    """Mirror ``Agent.prompt`` and record usage before ``close``.

    ``Agent.prompt`` closes the agent before the caller sees the result, so
    call sites that used it record here instead. Control flow matches the SDK:
    create, send, wait, close. ``close`` errors still propagate. Recording
    does not.
    """
    agent_type = agent_cls
    if agent_type is None:
        from cursor_sdk import Agent as agent_type

    agent = agent_type.create(options)
    result = None
    try:
        result = agent.send(message).wait()
        return result
    finally:
        record_agent_usage(
            agent,
            job=job,
            model=model,
            run_id=_result_run_id(result),
            ticker=ticker,
            pool=pool,
            extra=extra,
        )
        agent.close()


def parse_usage_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _read_raw_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _parse_jsonl_lines(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def read_usage_rows(log_path: Path | None = None) -> list[dict[str, Any]]:
    """Read one JSONL file. Does not apply the backfill map.

    ``log_path`` defaults to the legacy single log. Shard directories are
    read by ``load_ledger_rows``.
    """
    path = Path(log_path) if log_path is not None else DEFAULT_LEGACY_LOG_PATH
    return _parse_jsonl_lines(_read_raw_lines(path))


def usage_source_files(
    log_path: Path | None = None,
    *,
    shard_dir: Path | None = None,
) -> list[Path]:
    """JSONL inputs for the report and backfill.

    An explicit file is that file only (tests). An explicit directory is every
    ``*.jsonl`` under it. The default is every shard plus the legacy log when
    that file still exists.
    """
    if log_path is not None and Path(log_path).is_file():
        return [Path(log_path)]
    if log_path is not None and Path(log_path).is_dir():
        root = Path(log_path)
    else:
        root = Path(shard_dir) if shard_dir is not None else DEFAULT_SHARD_DIR
    files = (
        sorted(item for item in root.rglob("*.jsonl") if item.is_file()) if root.is_dir() else []
    )
    legacy = DEFAULT_LEGACY_LOG_PATH
    if legacy.is_file() and legacy.resolve() not in {item.resolve() for item in files}:
        files.append(legacy)
    return files


def resolve_backfill_path(
    backfill_path: Path | None = None,
    log_path: Path | None = None,
) -> Path:
    if backfill_path is not None:
        return Path(backfill_path)
    if log_path is not None and Path(log_path).is_file():
        return Path(log_path).parent / DEFAULT_BACKFILL_PATH.name
    return DEFAULT_BACKFILL_PATH


def load_backfill_map(path: Path | None = None) -> dict[str, dict[str, Any]]:
    target = Path(path) if path is not None else DEFAULT_BACKFILL_PATH
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("by_row_id")
    if not isinstance(rows, dict):
        rows = {
            key: value
            for key, value in payload.items()
            if key not in {"schema_version", "generated_at"} and isinstance(value, dict)
        }
    out: dict[str, dict[str, Any]] = {}
    for key, value in rows.items():
        if isinstance(value, dict):
            out[str(key)] = value
    return out


def _backfill_entry_filled(entry: Mapping[str, Any] | None) -> bool:
    if not entry or entry.get("error"):
        return False
    return entry.get("raw_cost_cents") is not None


def apply_backfill_entry(row: Mapping[str, Any], entry: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy cost from the backfill map. The shard row is not modified on disk."""
    copied = dict(row)
    if not _backfill_entry_filled(entry):
        return copied
    assert entry is not None
    copied["raw_cost_cents"] = entry.get("raw_cost_cents")
    copied["charged_cents"] = entry.get("charged_cents")
    copied["cost_pending"] = False
    filled_at = entry.get("filled_at")
    if filled_at:
        copied["cost_backfilled_at"] = filled_at
    return copied


def dedupe_usage_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per ``row_id``. A filled copy wins over a still-pending copy."""
    order: list[str] = []
    chosen: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for row in rows:
        row_id = str(row.get("row_id") or "").strip()
        if not row_id:
            anonymous.append(row)
            continue
        previous = chosen.get(row_id)
        if previous is None:
            chosen[row_id] = row
            order.append(row_id)
            continue
        if previous.get("cost_pending") and not row.get("cost_pending"):
            chosen[row_id] = row
    return [chosen[row_id] for row_id in order] + anonymous


def load_ledger_rows(
    log_path: Path | None = None,
    *,
    shard_dir: Path | None = None,
    backfill_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Read every shard (and the legacy log), apply the backfill map, dedupe."""
    mapping = load_backfill_map(resolve_backfill_path(backfill_path, log_path))
    rows: list[dict[str, Any]] = []
    for path in usage_source_files(log_path, shard_dir=shard_dir):
        for row in _parse_jsonl_lines(_read_raw_lines(path)):
            row_id = str(row.get("row_id") or "")
            rows.append(apply_backfill_entry(row, mapping.get(row_id)))
    return dedupe_usage_rows(rows)


def _write_backfill_map(path: Path, rows: dict[str, dict[str, Any]], *, now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "by_row_id": rows,
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _cost_from_usage_payload(agent_usage: Any, row: Mapping[str, Any]) -> Any:
    runs = list(getattr(agent_usage, "runs", ()) or ())
    keys = [str(row.get("usage_run_id") or ""), str(row.get("run_id") or "")]
    keys = [key for key in keys if key]
    for key in keys:
        for run in runs:
            if str(getattr(run, "run_id", "") or "") == key:
                return getattr(run, "cost", None)
    if len(runs) == 1:
        cost = getattr(runs[0], "cost", None)
        if cost is not None:
            return cost
        return getattr(agent_usage, "cost", None)
    return None


def _filled_entry(cost: Any, *, now: datetime) -> dict[str, Any] | None:
    raw_cost, charged, pending = _cost_payload(cost)
    if pending:
        return None
    return {
        "raw_cost_cents": raw_cost,
        "charged_cents": charged,
        "filled_at": now.isoformat(),
    }


def backfill_pending_costs(
    *,
    log_path: Path | None = None,
    shard_dir: Path | None = None,
    backfill_path: Path | None = None,
    now: datetime | None = None,
    max_age_days: int = BACKFILL_MAX_AGE_DAYS,
    resume_agent: Any = None,
) -> dict[str, Any]:
    """Re-query cost for ``cost_pending`` rows younger than ``max_age_days``.

    Writes ``docs/data/agent_usage_cost_backfill.json`` only. Shard files are
    not opened for write. Resume is ``ResumeAgent``, a unary that returns a
    handle and does not call ``send``. ``get_usage`` is ``GetUsage``, a
    read-only unary. This pass never sends a message. If resume fails, the
    map stores an error and the shard row stays pending.
    """
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    dest = resolve_backfill_path(backfill_path, log_path)
    report: dict[str, Any] = {
        "queried_agents": 0,
        "updated_rows": 0,
        "still_pending": 0,
        "skipped_older_than_days": 0,
        "skipped_no_agent_id": 0,
        "errors": [],
        "skipped": False,
        "reason": None,
        "read_only": True,
        "shards_unchanged": True,
        "backfill_path": str(dest),
        "method": (
            "Agent.resume (ResumeAgent unary, no send) + "
            "get_usage (GetUsage unary, read-only) + close; "
            "cost is written to the backfill map, not the shards"
        ),
        "max_age_days": max_age_days,
    }
    sources = usage_source_files(log_path, shard_dir=shard_dir)
    pending_by_agent: dict[str, list[dict[str, Any]]] = {}
    max_age_seconds = float(max_age_days) * 86400.0
    existing = load_backfill_map(dest)
    for path in sources:
        for item in _parse_jsonl_lines(_read_raw_lines(path)):
            if not item.get("cost_pending"):
                continue
            row_id = str(item.get("row_id") or "")
            if row_id and _backfill_entry_filled(existing.get(row_id)):
                continue
            stamp = parse_usage_timestamp(item.get("timestamp"))
            if stamp is None:
                report["still_pending"] += 1
                continue
            age = (moment - stamp).total_seconds()
            if age >= max_age_seconds:
                report["skipped_older_than_days"] += 1
                continue
            agent_id = str(item.get("agent_id") or "").strip()
            if not agent_id:
                report["skipped_no_agent_id"] += 1
                report["still_pending"] += 1
                continue
            pending_by_agent.setdefault(agent_id, []).append(item)

    if not pending_by_agent:
        report["reason"] = "no pending rows under the age bound"
        return report

    resume = resume_agent
    if resume is None:
        if not _backfill_enabled():
            report["skipped"] = True
            report["reason"] = (
                "backfill disabled so tests do not resume live agents; "
                "set FTSE_AGENT_USAGE_BACKFILL=1 to query"
            )
            report["still_pending"] += sum(len(rows) for rows in pending_by_agent.values())
            return report

        def _default_resume(agent_id: str) -> Any:
            from cursor_sdk import Agent

            return Agent.resume(agent_id)

        resume = _default_resume

    updates: dict[str, dict[str, Any]] = {}
    for agent_id, rows in pending_by_agent.items():
        report["queried_agents"] += 1
        try:
            agent = resume(agent_id)
        except Exception as exc:
            message = str(exc)[:500]
            report["errors"].append({"agent_id": agent_id, "error": message})
            report["still_pending"] += len(rows)
            logger.warning("usage backfill resume failed for %s: %s", agent_id, exc)
            for row in rows:
                row_id = str(row.get("row_id") or "")
                if row_id:
                    updates[row_id] = {"error": message}
            continue
        try:
            status, payload = _call_get_usage(agent, None)
        finally:
            close = getattr(agent, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.warning("usage backfill close failed for %s", agent_id, exc_info=True)
        if status != "ok":
            message = str(payload)[:500]
            report["errors"].append({"agent_id": agent_id, "error": message})
            report["still_pending"] += len(rows)
            for row in rows:
                row_id = str(row.get("row_id") or "")
                if row_id:
                    updates[row_id] = {"error": message}
            continue
        for row in rows:
            entry = _filled_entry(_cost_from_usage_payload(payload, row), now=moment)
            row_id = str(row.get("row_id") or "")
            if entry is None or not row_id:
                report["still_pending"] += 1
                continue
            updates[row_id] = entry
            report["updated_rows"] += 1

    if not updates:
        return report

    with _exclusive_lock(dest):
        # Re-read so a concurrent ops-monitor writer is not dropped. Shards
        # are not locked and are not written.
        current = load_backfill_map(dest)
        current.update(updates)
        _write_backfill_map(dest, current, now=moment)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cursor agent token-usage ledger helpers")
    sub = parser.add_subparsers(dest="command", required=True)
    fill = sub.add_parser(
        "backfill",
        help="Re-query pending cost into the backfill map (does not edit shards)",
    )
    fill.add_argument("--shard-dir", type=Path, default=DEFAULT_SHARD_DIR)
    fill.add_argument("--backfill", type=Path, default=DEFAULT_BACKFILL_PATH)
    args = parser.parse_args(argv)
    report = backfill_pending_costs(shard_dir=args.shard_dir, backfill_path=args.backfill)
    print(json.dumps(report, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
