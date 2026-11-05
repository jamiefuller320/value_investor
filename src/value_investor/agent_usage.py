"""Append-only ledger of real Cursor SDK agent token usage.

``record_agent_usage`` calls ``agent.get_usage`` after a run finishes. A
recording failure is logged and stored as ``usage_error``; it never changes
the caller's result. The helper is a no-op under pytest (unless
``FTSE_AGENT_USAGE_RECORD=1``) and when the object has no ``get_usage``.

Cost is server-derived and eventually consistent. ``cost_pending`` stays true
until ``raw_cost_cents`` / ``charged_cents`` arrive. Backfill re-reads pending
rows with ``Agent.resume`` plus ``get_usage``. Both are unary RPCs: resume
returns a handle and does not call ``send``; ``GetUsage`` is read-only
(``cursor_sdk/_agent.py`` ``Agent.get_usage``, ``cursor_sdk/_client.py``
``Client.resume_agent``).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = Path("docs/data/agent_usage_log.jsonl")
BACKFILL_MAX_AGE_DAYS = 7

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
    return log_path.with_name(log_path.name + ".lock")


@contextmanager
def _exclusive_lock(log_path: Path) -> Iterator[None]:
    """Serialize appends and rewrites so parallel jobs do not tear lines."""
    lock_path = _lock_path(log_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _write_lines_unlocked(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(line if line.endswith("\n") else f"{line}\n" for line in lines)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


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

    path = Path(log_path) if log_path is not None else DEFAULT_LOG_PATH
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


def read_usage_rows(log_path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(log_path) if log_path is not None else DEFAULT_LOG_PATH
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _read_raw_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


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


def _apply_backfill(row: dict[str, Any], agent_usage: Any, *, now: datetime) -> bool:
    cost = _cost_from_usage_payload(agent_usage, row)
    raw_cost, charged, pending = _cost_payload(cost)
    if pending:
        return False
    row["raw_cost_cents"] = raw_cost
    row["charged_cents"] = charged
    row["cost_pending"] = False
    row["cost_backfilled_at"] = now.isoformat()
    if row.get("input_tokens") is None:
        usage, _cost, usage_run_id = _select_usage(agent_usage, row.get("run_id"))
        row.update(_token_payload(usage))
        if usage_run_id and not row.get("usage_run_id"):
            row["usage_run_id"] = usage_run_id
        if row.get("usage_error") and row.get("total_tokens") is not None:
            row["usage_error"] = None
    return True


def backfill_pending_costs(
    *,
    log_path: Path | None = None,
    now: datetime | None = None,
    max_age_days: int = BACKFILL_MAX_AGE_DAYS,
    resume_agent: Any = None,
) -> dict[str, Any]:
    """Re-query cost for ``cost_pending`` rows younger than ``max_age_days``.

    Uses ``Agent.resume(agent_id)`` then ``get_usage()`` and ``close()``.
    Resume is ``ResumeAgent``, a unary that returns a handle and does not
    call ``send``. ``get_usage`` is ``GetUsage``, a read-only unary. This
    pass never sends a message. If resume fails, the row stays pending and
    the error is reported.
    """
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    path = Path(log_path) if log_path is not None else DEFAULT_LOG_PATH
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
        "method": (
            "Agent.resume (ResumeAgent unary, no send) + "
            "get_usage (GetUsage unary, read-only) + close"
        ),
        "max_age_days": max_age_days,
    }
    with _exclusive_lock(path):
        raw_lines = _read_raw_lines(path)
    pending_by_agent: dict[str, list[dict[str, Any]]] = {}
    max_age_seconds = float(max_age_days) * 86400.0
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if not item.get("cost_pending"):
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

    if resume_agent is None:
        if not _backfill_enabled():
            report["skipped"] = True
            report["reason"] = (
                "backfill disabled so tests do not resume live agents; "
                "set FTSE_AGENT_USAGE_BACKFILL=1 to query"
            )
            report["still_pending"] += sum(len(rows) for rows in pending_by_agent.values())
            return report

        def resume_agent(agent_id: str) -> Any:
            from cursor_sdk import Agent

            return Agent.resume(agent_id)

    updates: dict[str, dict[str, Any]] = {}
    for agent_id, rows in pending_by_agent.items():
        report["queried_agents"] += 1
        try:
            agent = resume_agent(agent_id)
        except Exception as exc:
            report["errors"].append({"agent_id": agent_id, "error": str(exc)[:500]})
            report["still_pending"] += len(rows)
            logger.warning("usage backfill resume failed for %s: %s", agent_id, exc)
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
            continue
        for row in rows:
            if _apply_backfill(row, payload, now=moment):
                row_id = str(row.get("row_id") or "")
                if row_id:
                    updates[row_id] = row
                report["updated_rows"] += 1
            else:
                report["still_pending"] += 1

    if not updates:
        return report

    with _exclusive_lock(path):
        current = _read_raw_lines(path)
        rewritten: list[str] = []
        for line in current:
            if not line.strip():
                rewritten.append(line)
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                rewritten.append(line)
                continue
            if not isinstance(item, dict):
                rewritten.append(line)
                continue
            row_id = str(item.get("row_id") or "")
            replacement = updates.get(row_id)
            if replacement is None or not item.get("cost_pending"):
                rewritten.append(line)
                continue
            rewritten.append(json.dumps(replacement, ensure_ascii=False, default=_json_default))
        _write_lines_unlocked(path, rewritten)
    return report


def merge_snapshot_into(dest: Path, snapshot: Path) -> int:
    """Append snapshot lines that are not already in ``dest``.

    Used when a job commits the ledger onto a newer main that another job
    already extended. Returns the number of lines appended.
    """
    snap_lines = [
        line for line in snapshot.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    with _exclusive_lock(dest):
        existing = [line for line in _read_raw_lines(dest) if line.strip()]
        have = set(existing)
        added = [line for line in snap_lines if line not in have]
        if not added:
            return 0
        _write_lines_unlocked(dest, existing + added)
        return len(added)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cursor agent token-usage ledger helpers")
    sub = parser.add_subparsers(dest="command", required=True)
    merge = sub.add_parser(
        "merge-snapshot",
        help="Append snapshot JSONL lines missing from the destination log",
    )
    merge.add_argument("--snapshot", type=Path, required=True)
    merge.add_argument("--dest", type=Path, required=True)
    fill = sub.add_parser("backfill", help="Re-query pending cost (read-only get_usage)")
    fill.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH)
    args = parser.parse_args(argv)
    if args.command == "merge-snapshot":
        added = merge_snapshot_into(args.dest, args.snapshot)
        print(json.dumps({"appended": added}))
        return 0
    report = backfill_pending_costs(log_path=args.log)
    print(json.dumps(report, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
