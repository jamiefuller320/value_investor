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


def record_ingest_trial(
    *,
    title: str,
    summary: str,
    ticker: str,
    params: dict[str, Any],
    review_trigger: ReviewTrigger = "horizon_scan",
    path: Path = DEFAULT_TRIALS_PATH,
) -> dict[str, Any]:
    """Append a trial record before dispatch; finalized after the ingest loop completes."""
    path = Path(path)
    store = load_ingest_trials(path)
    trial = {
        "id": _next_trial_id(store),
        "status": _STATUS_PENDING,
        "title": title.strip(),
        "summary": summary.strip(),
        "ticker": str(ticker or "").strip().upper(),
        "params": dict(params),
        "review_trigger": review_trigger,
        "recorded_at": datetime.now(UTC).isoformat(),
        "completed_at": None,
        "outcome": None,
    }
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
