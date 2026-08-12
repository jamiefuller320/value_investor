"""Record ingest experiments for horizon / analysis review (observe-only)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_TRIALS_PATH = Path("docs/data/ingest_trials.json")
ReviewTrigger = Literal["horizon_scan", "analysis_review", "both"]
MAX_TRIAL_GAP_CHAIN_ROUNDS = 3

_STATUS_PENDING = "pending_review"
_STATUS_REVIEWED = "reviewed"
_STATUS_DISMISSED = "dismissed"


def load_ingest_trials(path: Path = DEFAULT_TRIALS_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"trials": [], "updated_at": None}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        logger.warning("Could not read ingest trials at %s", path)
        return {"trials": [], "updated_at": None}
    if not isinstance(payload, dict):
        return {"trials": [], "updated_at": None}
    payload.setdefault("trials", [])
    return payload


def _next_trial_id(store: dict[str, Any]) -> str:
    prefix = datetime.now(UTC).strftime("trial-%Y%m%d-")
    existing = {
        str(row.get("id") or "")
        for row in store.get("trials") or []
        if str(row.get("id") or "").startswith(prefix)
    }
    index = 1
    while f"{prefix}{index:02d}" in existing:
        index += 1
    return f"{prefix}{index:02d}"


def _resolve_chain_root_id(parent_trial_id: str, store: dict[str, Any]) -> str:
    for row in store.get("trials") or []:
        if str(row.get("id") or "") == parent_trial_id:
            return str(row.get("chain_root_id") or parent_trial_id)
    return parent_trial_id


def _count_chain_trials(store: dict[str, Any], chain_root_id: str) -> int:
    return sum(
        1
        for row in store.get("trials") or []
        if str(row.get("chain_root_id") or row.get("id") or "") == chain_root_id
    )


def trial_chain_root_id(trial: dict[str, Any], *, path: Path = DEFAULT_TRIALS_PATH) -> str:
    explicit = str(trial.get("chain_root_id") or "").strip()
    if explicit:
        return explicit
    parent = str(trial.get("parent_trial_id") or "").strip()
    if parent:
        store = load_ingest_trials(path)
        return _resolve_chain_root_id(parent, store)
    return str(trial.get("id") or "")


def count_chain_engineering_rounds(
    chain_root_id: str,
    *,
    tasks_path: Path,
) -> int:
    from value_investor.engineering_tasks import load_engineering_tasks

    if not chain_root_id:
        return 0
    payload = load_engineering_tasks(tasks_path)
    count = 0
    for row in payload.get("tasks") or []:
        if str(row.get("source") or "") != "ingest_trial":
            continue
        status = str(row.get("status") or "open")
        if status in {"cancelled", "failed", "parked"}:
            continue
        evidence = row.get("evidence") or {}
        if str(evidence.get("chain_root_id") or "") == chain_root_id:
            count += 1
            continue
        trial_id = str(evidence.get("trial_id") or "")
        if trial_id and trial_id == chain_root_id:
            count += 1
    return count


def trial_ticker_has_gaps(
    ticker: str,
    *,
    data_dir: Path = Path("docs/data"),
) -> bool:
    from value_investor.research.ingest_improvement import (
        _filing_coverage,
        _has_outstanding_ingest_gap,
    )
    from value_investor.research.store import ResearchStore

    token = str(ticker or "").strip().upper()
    if not token:
        return False
    store = ResearchStore(data_dir)
    coverage = _filing_coverage(store, token, data_dir)
    return _has_outstanding_ingest_gap(coverage)


def mark_trial_chain_exhausted(
    chain_root_id: str,
    *,
    reason: str = "",
    path: Path = DEFAULT_TRIALS_PATH,
) -> None:
    path = Path(path)
    store = load_ingest_trials(path)
    for row in store.get("trials") or []:
        if str(row.get("id") or "") != chain_root_id:
            continue
        row["chain_status"] = "exhausted"
        row["chain_exhausted_at"] = datetime.now(UTC).isoformat()
        if reason.strip():
            row["chain_exhausted_reason"] = reason.strip()
        store["updated_at"] = datetime.now(UTC).isoformat()
        write_json(path, store, compact=False)
        return


def has_open_ingest_engineering_for_chain(
    chain_root_id: str,
    *,
    tasks_path: Path,
) -> bool:
    from value_investor.engineering_tasks import load_engineering_tasks

    payload = load_engineering_tasks(tasks_path)
    for row in payload.get("tasks") or []:
        if str(row.get("area") or "").lower() != "ingest":
            continue
        status = str(row.get("status") or "open")
        if status not in {"open", "pr_open"}:
            continue
        if row.get("merged_at"):
            continue
        evidence = row.get("evidence") or {}
        if str(evidence.get("chain_root_id") or "") == chain_root_id:
            return True
        if (
            str(row.get("source") or "") == "ingest_trial"
            and str(evidence.get("trial_id") or "") == chain_root_id
        ):
            return True
    return False


def should_auto_compile_gap_engineering(
    trial: dict[str, Any],
    *,
    data_dir: Path = Path("docs/data"),
    tasks_path: Path = Path("docs/data/engineering_tasks.json"),
    trials_path: Path = DEFAULT_TRIALS_PATH,
) -> tuple[bool, str]:
    """Whether to queue another ingest-trial engineering round for gap closure."""
    if str(trial.get("status") or "") != _STATUS_PENDING:
        return False, "trial_not_pending"
    ticker = str(trial.get("ticker") or "").strip().upper()
    if not ticker:
        return False, "no_ticker"
    params = trial.get("params") or {}
    if not params.get("require_outstanding_gaps"):
        return False, "not_gap_trial"
    if not trial_ticker_has_gaps(ticker, data_dir=data_dir):
        return False, "gaps_closed"

    chain_root = trial_chain_root_id(trial, path=trials_path)
    rounds = count_chain_engineering_rounds(chain_root, tasks_path=tasks_path)
    if rounds >= MAX_TRIAL_GAP_CHAIN_ROUNDS:
        mark_trial_chain_exhausted(
            chain_root,
            reason=f"max engineering rounds ({MAX_TRIAL_GAP_CHAIN_ROUNDS}) reached",
            path=trials_path,
        )
        return False, "chain_exhausted"

    if has_open_ingest_engineering_for_chain(chain_root, tasks_path=tasks_path):
        return False, "eng_in_flight_for_chain"

    outcome = trial.get("outcome") or {}
    if int(outcome.get("delta_filings_with_body") or 0) > 0:
        return False, "book_improved"
    per_ticker = outcome.get("per_ticker") or []
    if per_ticker and per_ticker[0].get("improved"):
        return False, "ticker_improved"

    stats = trial_refetch_stats(trial)
    if stats["attempted"] > 0 and stats["fetched"] <= 0:
        return True, "zero_yield_refetch"
    if str(trial.get("parent_trial_id") or "").strip():
        return True, "verification_gaps_remain"
    return False, "no_actionable_failure"


def record_ingest_trial(
    *,
    title: str,
    summary: str,
    ticker: str,
    params: dict[str, Any],
    review_trigger: ReviewTrigger = "horizon_scan",
    parent_trial_id: str = "",
    path: Path = DEFAULT_TRIALS_PATH,
) -> dict[str, Any]:
    """Append a trial record before dispatch; finalized after the ingest loop completes."""
    path = Path(path)
    store = load_ingest_trials(path)
    trial_id = _next_trial_id(store)
    chain_root_id = trial_id
    if parent_trial_id.strip():
        chain_root_id = _resolve_chain_root_id(parent_trial_id.strip(), store)
    trial = {
        "id": trial_id,
        "status": _STATUS_PENDING,
        "title": title.strip(),
        "summary": summary.strip(),
        "ticker": str(ticker or "").strip().upper(),
        "params": dict(params),
        "review_trigger": review_trigger,
        "chain_root_id": chain_root_id,
        "chain_attempt": _count_chain_trials(store, chain_root_id) + 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "completed_at": None,
        "outcome": None,
    }
    if parent_trial_id.strip():
        trial["parent_trial_id"] = parent_trial_id.strip()
    trials = list(store.get("trials") or [])
    trials.append(trial)
    store["trials"] = trials
    store["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, store, compact=False)
    return trial


def finalize_pending_ingest_trial(
    *,
    health_before: dict[str, Any],
    health_after: dict[str, Any],
    ingest_summary: Any | None,
    path: Path = DEFAULT_TRIALS_PATH,
) -> dict[str, Any] | None:
    """Attach health deltas and per-ticker results to the latest pending trial."""
    path = Path(path)
    store = load_ingest_trials(path)
    trials = list(store.get("trials") or [])
    pending_idx = next(
        (
            idx
            for idx in range(len(trials) - 1, -1, -1)
            if str(trials[idx].get("status") or "") == _STATUS_PENDING
        ),
        None,
    )
    if pending_idx is None:
        return None

    row = dict(trials[pending_idx])
    targets = []
    if ingest_summary is not None:
        raw_targets = getattr(ingest_summary, "targets", None) or []
        for t in raw_targets:
            if isinstance(t, dict):
                targets.append(str(t.get("ticker") or ""))
            else:
                targets.append(str(getattr(t, "ticker", "") or ""))

    outcome: dict[str, Any] = {
        "delta_filings_with_body": int(health_after.get("filings_with_body") or 0)
        - int(health_before.get("filings_with_body") or 0),
        "delta_indexed_without_body": int(health_before.get("indexed_without_body") or 0)
        - int(health_after.get("indexed_without_body") or 0),
        "delta_zero_body_buy_tier": int(health_before.get("zero_body_buy_tier") or 0)
        - int(health_after.get("zero_body_buy_tier") or 0),
        "targets_planned": getattr(ingest_summary, "targets_planned", None),
        "targets_completed": getattr(ingest_summary, "targets_completed", None),
        "runtime_cutoff": bool(getattr(ingest_summary, "runtime_cutoff", False)),
        "tickers": [t for t in targets if t],
        "results": getattr(ingest_summary, "results", None) if ingest_summary else None,
    }
    if ingest_summary is not None and hasattr(ingest_summary, "results"):
        outcome["per_ticker"] = [
            {
                "ticker": r.get("ticker"),
                "with_body_before": r.get("with_body_before"),
                "with_body_after": r.get("with_body_after"),
                "improved": r.get("improved"),
            }
            for r in (ingest_summary.results or [])
            if isinstance(r, dict)
        ]

    row["status"] = _STATUS_PENDING  # stays pending until horizon reviews
    row["completed_at"] = datetime.now(UTC).isoformat()
    row["outcome"] = outcome
    if not row.get("chain_root_id"):
        row["chain_root_id"] = trial_chain_root_id(row, path=path)
    trials[pending_idx] = row
    store["trials"] = trials
    store["updated_at"] = datetime.now(UTC).isoformat()
    write_json(path, store, compact=False)
    return row


def list_trials_pending_review(
    *,
    trigger: ReviewTrigger | None = "horizon_scan",
    path: Path = DEFAULT_TRIALS_PATH,
) -> list[dict[str, Any]]:
    """Trials awaiting strategic review (completed runs with outcomes attached)."""
    store = load_ingest_trials(path)
    rows: list[dict[str, Any]] = []
    for row in store.get("trials") or []:
        if str(row.get("status") or "") != _STATUS_PENDING:
            continue
        if row.get("completed_at") is None:
            continue
        rt = str(row.get("review_trigger") or "horizon_scan")
        if trigger is not None and trigger != "both" and rt not in {trigger, "both"}:
            continue
        rows.append(dict(row))
    return rows


def mark_trial_reviewed(
    trial_id: str,
    *,
    disposition: Literal["promote", "dismiss", "defer"] = "promote",
    note: str = "",
    path: Path = DEFAULT_TRIALS_PATH,
) -> dict[str, Any]:
    """Close a trial after horizon or analysis review."""
    path = Path(path)
    store = load_ingest_trials(path)
    for row in store.get("trials") or []:
        if str(row.get("id") or "") != trial_id:
            continue
        row["status"] = _STATUS_REVIEWED if disposition == "promote" else _STATUS_DISMISSED
        row["reviewed_at"] = datetime.now(UTC).isoformat()
        row["disposition"] = disposition
        if note.strip():
            row["review_note"] = note.strip()
        store["updated_at"] = datetime.now(UTC).isoformat()
        write_json(path, store, compact=False)
        return dict(row)
    raise KeyError(f"Unknown ingest trial id: {trial_id}")


def trial_refetch_stats(trial: dict[str, Any]) -> dict[str, int]:
    """Sum refetch attempted/fetched across primary ingest-improvement steps."""
    outcome = trial.get("outcome") or {}
    results = outcome.get("results") or []
    if not results or not isinstance(results[0], dict):
        return {"attempted": 0, "fetched": 0}
    row = results[0]
    attempted = 0
    fetched = 0
    for key in ("ch_refetch", "investegate_refetch", "ticker_rns_refetch", "indexed_refetch"):
        block = row.get(key) or {}
        if not isinstance(block, dict):
            continue
        attempted += int(block.get("attempted") or 0)
        fetched += int(block.get("fetched") or 0)
    return {"attempted": attempted, "fetched": fetched}


def trial_needs_gap_engineering(trial: dict[str, Any]) -> bool:
    """True when a gap-required trial ran refetches but did not close indexed gaps."""
    if str(trial.get("status") or "") != _STATUS_PENDING:
        return False
    if not str(trial.get("ticker") or "").strip():
        return False
    params = trial.get("params") or {}
    if not params.get("require_outstanding_gaps"):
        return False
    outcome = trial.get("outcome") or {}
    if int(outcome.get("delta_filings_with_body") or 0) > 0:
        return False
    per_ticker = outcome.get("per_ticker") or []
    if per_ticker and per_ticker[0].get("improved"):
        return False
    stats = trial_refetch_stats(trial)
    if stats["attempted"] <= 0:
        return False
    return stats["fetched"] <= 0


def attach_engineering_task_to_trial(
    trial_id: str,
    engineering_task_id: str,
    *,
    path: Path = DEFAULT_TRIALS_PATH,
) -> dict[str, Any] | None:
    path = Path(path)
    store = load_ingest_trials(path)
    for row in store.get("trials") or []:
        if str(row.get("id") or "") != trial_id:
            continue
        row["engineering_task_id"] = str(engineering_task_id)
        store["updated_at"] = datetime.now(UTC).isoformat()
        write_json(path, store, compact=False)
        return dict(row)
    return None
