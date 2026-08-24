"""Record ingest gap-closure runs for horizon / analysis review (observe-only)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from value_investor.research.gap_fill import DEFAULT_SUGGESTIONS_PATH
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_RUNS_PATH = Path("docs/data/ingest_gap_closure_runs.json")
LEGACY_RUNS_PATH = Path("docs/data/ingest_trials.json")
ReviewTrigger = Literal["horizon_scan", "analysis_review", "both"]
MAX_GAP_CLOSURE_CHAIN_ROUNDS = 3
MAX_TRIAL_GAP_CHAIN_ROUNDS = MAX_GAP_CLOSURE_CHAIN_ROUNDS

_STATUS_PENDING = "pending_review"
_STATUS_REVIEWED = "reviewed"
_STATUS_DISMISSED = "dismissed"


def resolve_runs_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    if DEFAULT_RUNS_PATH.exists():
        return DEFAULT_RUNS_PATH
    if LEGACY_RUNS_PATH.exists():
        return LEGACY_RUNS_PATH
    return DEFAULT_RUNS_PATH


def _runs_key(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("runs"), list):
        return "runs"
    return "trials"


def load_ingest_gap_closure_runs(path: Path | None = None) -> dict[str, Any]:
    path = resolve_runs_path(path)
    if not path.exists():
        return {"runs": [], "updated_at": None}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        logger.warning("Could not read ingest gap closure runs at %s", path)
        return {"runs": [], "updated_at": None}
    if not isinstance(payload, dict):
        return {"runs": [], "updated_at": None}
    key = _runs_key(payload)
    runs = list(payload.get(key) or [])
    if key == "trials" and "runs" not in payload:
        payload = {"runs": runs, "updated_at": payload.get("updated_at")}
    else:
        payload.setdefault("runs", runs)
    return payload


def load_ingest_trials(path: Path | None = None) -> dict[str, Any]:
    """Backward-compatible alias for load_ingest_gap_closure_runs."""
    return load_ingest_gap_closure_runs(path)


def _next_run_id(store: dict[str, Any]) -> str:
    prefix = datetime.now(UTC).strftime("igc-%Y%m%d-")
    legacy_prefix = datetime.now(UTC).strftime("trial-%Y%m%d-")
    existing = {
        str(row.get("id") or "")
        for row in store.get("runs") or []
        if str(row.get("id") or "").startswith(prefix)
        or str(row.get("id") or "").startswith(legacy_prefix)
    }
    index = 1
    while f"{prefix}{index:02d}" in existing:
        index += 1
    return f"{prefix}{index:02d}"


def _resolve_chain_root_id(parent_run_id: str, store: dict[str, Any]) -> str:
    for row in store.get("runs") or []:
        if str(row.get("id") or "") == parent_run_id:
            return str(row.get("chain_root_id") or parent_run_id)
    return parent_run_id


def _count_chain_runs(store: dict[str, Any], chain_root_id: str) -> int:
    return sum(
        1
        for row in store.get("runs") or []
        if str(row.get("chain_root_id") or row.get("id") or "") == chain_root_id
    )


def gap_closure_chain_root_id(
    run: dict[str, Any],
    *,
    path: Path | None = None,
) -> str:
    explicit = str(run.get("chain_root_id") or "").strip()
    if explicit:
        return explicit
    parent = str(run.get("parent_run_id") or run.get("parent_trial_id") or "").strip()
    if parent:
        store = load_ingest_gap_closure_runs(path)
        return _resolve_chain_root_id(parent, store)
    return str(run.get("id") or "")


def trial_chain_root_id(
    trial: dict[str, Any],
    *,
    path: Path | None = None,
) -> str:
    return gap_closure_chain_root_id(trial, path=path)


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
        source = str(row.get("source") or "")
        if source not in {"ingest_gap_closure", "ingest_trial"}:
            continue
        status = str(row.get("status") or "open")
        if status in {"cancelled", "failed", "parked"}:
            continue
        evidence = row.get("evidence") or {}
        if str(evidence.get("chain_root_id") or "") == chain_root_id:
            count += 1
            continue
        run_id = str(evidence.get("gap_closure_run_id") or evidence.get("trial_id") or "")
        if run_id and run_id == chain_root_id:
            count += 1
    return count


def gap_closure_ticker_has_gaps(
    ticker: str,
    *,
    data_dir: Path = Path("docs/data"),
    market_id: str | None = None,
) -> bool:
    token = str(ticker or "").strip().upper()
    if not token:
        return False
    market = str(market_id or "").strip() or None
    if market:
        from value_investor.library_ingest_escalation import library_ingest_ticker_has_gaps

        return library_ingest_ticker_has_gaps(token, market_id=market)
    from value_investor.research.ingest_improvement import (
        _filing_coverage,
        _has_outstanding_ingest_gap,
    )
    from value_investor.research.store import ResearchStore

    store = ResearchStore(data_dir)
    coverage = _filing_coverage(store, token, data_dir)
    return _has_outstanding_ingest_gap(coverage)


def trial_ticker_has_gaps(
    ticker: str,
    *,
    data_dir: Path = Path("docs/data"),
) -> bool:
    return gap_closure_ticker_has_gaps(ticker, data_dir=data_dir)


def mark_gap_closure_chain_exhausted(
    chain_root_id: str,
    *,
    reason: str = "",
    path: Path | None = None,
    data_dir: Path | None = None,
    prune_failed_residual_fetches: bool = True,
) -> None:
    path = resolve_runs_path(path)
    store = load_ingest_gap_closure_runs(path)
    for row in store.get("runs") or []:
        if str(row.get("id") or "") != chain_root_id:
            continue
        row["chain_status"] = "exhausted"
        row["chain_exhausted_at"] = datetime.now(UTC).isoformat()
        if reason.strip():
            row["chain_exhausted_reason"] = reason.strip()
        store["updated_at"] = datetime.now(UTC).isoformat()
        write_json(path, store, compact=False)
        if prune_failed_residual_fetches and data_dir is not None:
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker:
                from value_investor.research.filings import refetch_residual_filing_bodies

                filings_dir = Path(data_dir) / "research" / ticker / "sources" / "filings"
                if filings_dir.is_dir():
                    company_name = ticker
                    index_path = filings_dir / "filings_index.json"
                    if index_path.is_file():
                        try:
                            index_payload = json.loads(index_path.read_text(encoding="utf-8"))
                            company_name = str(index_payload.get("company_name") or company_name)
                        except (OSError, ValueError, TypeError):
                            pass
                    refetch_residual_filing_bodies(
                        filings_dir,
                        ticker=ticker,
                        company_name=company_name,
                        max_bodies=40,
                        prune_unfetchable_after_attempt=True,
                    )
        return


def mark_trial_chain_exhausted(
    chain_root_id: str,
    *,
    reason: str = "",
    path: Path | None = None,
    data_dir: Path | None = None,
    prune_failed_residual_fetches: bool = True,
) -> None:
    mark_gap_closure_chain_exhausted(
        chain_root_id,
        reason=reason,
        path=path,
        data_dir=data_dir,
        prune_failed_residual_fetches=prune_failed_residual_fetches,
    )


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
        source = str(row.get("source") or "")
        run_id = str(evidence.get("gap_closure_run_id") or evidence.get("trial_id") or "")
        if source in {"ingest_gap_closure", "ingest_trial"} and run_id == chain_root_id:
            return True
    return False


def should_auto_compile_gap_engineering(
    run: dict[str, Any],
    *,
    data_dir: Path = Path("docs/data"),
    tasks_path: Path = Path("docs/data/engineering_tasks.json"),
    runs_path: Path | None = None,
    trials_path: Path | None = None,
) -> tuple[bool, str]:
    """Whether to queue another ingest gap-closure engineering round."""
    effective_runs_path = trials_path or runs_path
    if str(run.get("status") or "") != _STATUS_PENDING:
        return False, "run_not_pending"
    ticker = str(run.get("ticker") or "").strip().upper()
    if not ticker:
        return False, "no_ticker"
    params = run.get("params") or {}
    if not params.get("require_outstanding_gaps"):
        return False, "not_gap_run"
    market_id = str(params.get("market_id") or "").strip() or None
    if not gap_closure_ticker_has_gaps(ticker, data_dir=data_dir, market_id=market_id):
        return False, "gaps_closed"

    chain_root = gap_closure_chain_root_id(run, path=effective_runs_path)
    rounds = count_chain_engineering_rounds(chain_root, tasks_path=tasks_path)
    if rounds >= MAX_GAP_CLOSURE_CHAIN_ROUNDS:
        mark_gap_closure_chain_exhausted(
            chain_root,
            reason=f"max engineering rounds ({MAX_GAP_CLOSURE_CHAIN_ROUNDS}) reached",
            path=effective_runs_path,
            data_dir=data_dir,
        )
        return False, "chain_exhausted"

    if has_open_ingest_engineering_for_chain(chain_root, tasks_path=tasks_path):
        return False, "eng_in_flight_for_chain"

    outcome = run.get("outcome") or {}
    if int(outcome.get("delta_filings_with_body") or 0) > 0:
        if not gap_closure_ticker_has_gaps(ticker, data_dir=data_dir, market_id=market_id):
            return False, "gaps_closed_after_improvement"
    per_ticker = outcome.get("per_ticker") or []
    if per_ticker and per_ticker[0].get("improved"):
        return False, "ticker_improved"

    stats = gap_closure_refetch_stats(run)
    if stats["attempted"] > 0 and stats["fetched"] <= 0:
        return True, "zero_yield_refetch"
    parent = str(run.get("parent_run_id") or run.get("parent_trial_id") or "").strip()
    if parent:
        return True, "verification_gaps_remain"
    return False, "no_actionable_failure"


def record_ingest_gap_closure_run(
    *,
    title: str,
    summary: str,
    ticker: str,
    params: dict[str, Any],
    review_trigger: ReviewTrigger = "horizon_scan",
    parent_run_id: str = "",
    trigger: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Append a gap-closure run before dispatch; finalized after ingest loop completes."""
    path = resolve_runs_path(path)
    store = load_ingest_gap_closure_runs(path)
    run_id = _next_run_id(store)
    chain_root_id = run_id
    if parent_run_id.strip():
        chain_root_id = _resolve_chain_root_id(parent_run_id.strip(), store)
    run = {
        "id": run_id,
        "status": _STATUS_PENDING,
        "title": title.strip(),
        "summary": summary.strip(),
        "ticker": str(ticker or "").strip().upper(),
        "params": dict(params),
        "review_trigger": review_trigger,
        "chain_root_id": chain_root_id,
        "chain_attempt": _count_chain_runs(store, chain_root_id) + 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "completed_at": None,
        "outcome": None,
    }
    if trigger.strip():
        run["trigger"] = trigger.strip()
    if parent_run_id.strip():
        run["parent_run_id"] = parent_run_id.strip()
    runs = list(store.get("runs") or [])
    runs.append(run)
    store["runs"] = runs
    store["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, store, compact=False)
    return run


def record_ingest_trial(
    *,
    title: str,
    summary: str,
    ticker: str,
    params: dict[str, Any],
    review_trigger: ReviewTrigger = "horizon_scan",
    parent_trial_id: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    return record_ingest_gap_closure_run(
        title=title,
        summary=summary,
        ticker=ticker,
        params=params,
        review_trigger=review_trigger,
        parent_run_id=parent_trial_id,
        path=path,
    )


def finalize_pending_gap_closure_run(
    *,
    health_before: dict[str, Any],
    health_after: dict[str, Any],
    ingest_summary: Any | None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Attach health deltas and per-ticker results to the latest pending run."""
    path = resolve_runs_path(path)
    store = load_ingest_gap_closure_runs(path)
    runs = list(store.get("runs") or [])
    pending_idx = next(
        (
            idx
            for idx in range(len(runs) - 1, -1, -1)
            if str(runs[idx].get("status") or "") == _STATUS_PENDING
        ),
        None,
    )
    if pending_idx is None:
        return None

    row = dict(runs[pending_idx])
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
        per_ticker: list[dict[str, Any]] = []
        for r in ingest_summary.results or []:
            if not isinstance(r, dict):
                continue
            before = r.get("before") if isinstance(r.get("before"), dict) else {}
            after = r.get("after") if isinstance(r.get("after"), dict) else {}
            per_ticker.append(
                {
                    "ticker": r.get("ticker"),
                    "with_body_before": r.get("with_body_before", before.get("filings_with_body")),
                    "with_body_after": r.get("with_body_after", after.get("filings_with_body")),
                    "improved": r.get("improved"),
                }
            )
        outcome["per_ticker"] = per_ticker

    row["status"] = _STATUS_PENDING
    row["completed_at"] = datetime.now(UTC).isoformat()
    row["outcome"] = outcome
    if not row.get("chain_root_id"):
        row["chain_root_id"] = gap_closure_chain_root_id(row, path=path)
    runs[pending_idx] = row
    store["runs"] = runs
    store["updated_at"] = datetime.now(UTC).isoformat()
    write_json(path, store, compact=False)
    return row


def finalize_pending_ingest_trial(
    *,
    health_before: dict[str, Any],
    health_after: dict[str, Any],
    ingest_summary: Any | None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    return finalize_pending_gap_closure_run(
        health_before=health_before,
        health_after=health_after,
        ingest_summary=ingest_summary,
        path=path,
    )


def list_gap_closure_runs_pending_review(
    *,
    trigger: ReviewTrigger | None = "horizon_scan",
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Gap-closure runs awaiting strategic review (completed runs with outcomes attached)."""
    store = load_ingest_gap_closure_runs(path)
    rows: list[dict[str, Any]] = []
    for row in store.get("runs") or []:
        if str(row.get("status") or "") != _STATUS_PENDING:
            continue
        if row.get("completed_at") is None:
            continue
        rt = str(row.get("review_trigger") or "horizon_scan")
        if trigger is not None and trigger != "both" and rt not in {trigger, "both"}:
            continue
        rows.append(dict(row))
    return rows


def list_trials_pending_review(
    *,
    trigger: ReviewTrigger | None = "horizon_scan",
    path: Path | None = None,
) -> list[dict[str, Any]]:
    return list_gap_closure_runs_pending_review(trigger=trigger, path=path)


def mark_gap_closure_run_reviewed(
    run_id: str,
    *,
    disposition: Literal["promote", "dismiss", "defer"] = "promote",
    note: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Close a gap-closure run after horizon or analysis review."""
    path = resolve_runs_path(path)
    store = load_ingest_gap_closure_runs(path)
    for row in store.get("runs") or []:
        if str(row.get("id") or "") != run_id:
            continue
        row["status"] = _STATUS_REVIEWED if disposition == "promote" else _STATUS_DISMISSED
        row["reviewed_at"] = datetime.now(UTC).isoformat()
        row["disposition"] = disposition
        if note.strip():
            row["review_note"] = note.strip()
        store["updated_at"] = datetime.now(UTC).isoformat()
        write_json(path, store, compact=False)
        return dict(row)
    raise KeyError(f"Unknown ingest gap closure run id: {run_id}")


def mark_trial_reviewed(
    trial_id: str,
    *,
    disposition: Literal["promote", "dismiss", "defer"] = "promote",
    note: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    return mark_gap_closure_run_reviewed(
        run_id=trial_id,
        disposition=disposition,
        note=note,
        path=path,
    )


def gap_closure_refetch_stats(run: dict[str, Any]) -> dict[str, int]:
    """Sum refetch attempted/fetched across primary ingest-improvement steps."""
    params = run.get("params") or {}
    if str(params.get("market_id") or "").strip():
        outcome = run.get("outcome") or {}
        per_ticker = list(outcome.get("per_ticker") or [])
        if per_ticker:
            attempted = len(per_ticker)
            fetched = sum(1 for row in per_ticker if row.get("improved"))
            return {"attempted": attempted, "fetched": fetched}
        results = list(outcome.get("results") or [])
        attempted = len(results)
        fetched = sum(1 for row in results if isinstance(row, dict) and row.get("improved"))
        return {"attempted": attempted, "fetched": fetched}
    outcome = run.get("outcome") or {}
    results = outcome.get("results") or []
    if not results or not isinstance(results[0], dict):
        return {"attempted": 0, "fetched": 0}
    row = results[0]
    attempted = 0
    fetched = 0
    for key in (
        "ch_refetch",
        "investegate_refetch",
        "ticker_rns_refetch",
        "indexed_refetch",
        "residual_refetch",
    ):
        block = row.get(key) or {}
        if not isinstance(block, dict):
            continue
        attempted += int(block.get("attempted") or 0)
        fetched += int(block.get("fetched") or 0)
    return {"attempted": attempted, "fetched": fetched}


def trial_refetch_stats(trial: dict[str, Any]) -> dict[str, int]:
    return gap_closure_refetch_stats(trial)


def gap_closure_needs_engineering(run: dict[str, Any]) -> bool:
    """True when a gap-required run did refetches but did not close indexed gaps."""
    if str(run.get("status") or "") != _STATUS_PENDING:
        return False
    if not str(run.get("ticker") or "").strip():
        return False
    params = run.get("params") or {}
    if not params.get("require_outstanding_gaps"):
        return False
    outcome = run.get("outcome") or {}
    if int(outcome.get("delta_filings_with_body") or 0) > 0:
        return False
    per_ticker = outcome.get("per_ticker") or []
    if per_ticker and per_ticker[0].get("improved"):
        return False
    stats = gap_closure_refetch_stats(run)
    if stats["attempted"] <= 0:
        return False
    return stats["fetched"] <= 0


def trial_needs_gap_engineering(trial: dict[str, Any]) -> bool:
    return gap_closure_needs_engineering(trial)


def attach_engineering_task_to_run(
    run_id: str,
    engineering_task_id: str,
    *,
    path: Path | None = None,
) -> dict[str, Any] | None:
    path = resolve_runs_path(path)
    store = load_ingest_gap_closure_runs(path)
    for row in store.get("runs") or []:
        if str(row.get("id") or "") != run_id:
            continue
        row["engineering_task_id"] = str(engineering_task_id)
        store["updated_at"] = datetime.now(UTC).isoformat()
        write_json(path, store, compact=False)
        return dict(row)
    return None


def attach_engineering_task_to_trial(
    trial_id: str,
    engineering_task_id: str,
    *,
    path: Path | None = None,
) -> dict[str, Any] | None:
    return attach_engineering_task_to_run(trial_id, engineering_task_id, path=path)


def paper_holding_tickers(data_dir: Path = Path("docs/data")) -> set[str]:
    """Tickers held in paper automation funds (any strategy subdirectory)."""
    tickers: set[str] = set()
    base = Path(data_dir) / "paper_automation"
    if not base.is_dir():
        return tickers
    for path in base.rglob("automated_fund.json"):
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        for ticker in (payload.get("holdings") or {}).keys():
            token = str(ticker or "").strip().upper()
            if token:
                tickers.add(token)
    return tickers


def select_gap_closure_candidate(
    *,
    latest_path: Path = Path("docs/data/latest.json"),
    data_dir: Path = Path("docs/data"),
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    prefer_paper_holdings: bool = False,
) -> dict[str, Any]:
    """Pick the top buy-tier ticker with outstanding ingest gaps."""
    from value_investor.ingest_loop import reports_from_latest
    from value_investor.research.ingest_improvement import select_ingest_improvement_targets

    reports = reports_from_latest(latest_path)
    if not reports:
        return {"should_dispatch": False, "reason": "no reports in latest.json"}
    candidates = select_ingest_improvement_targets(
        reports,
        output_dir=data_dir,
        suggestions_path=suggestions_path,
        max_targets=20,
        require_outstanding_gaps=True,
    )
    if prefer_paper_holdings:
        paper = paper_holding_tickers(data_dir)
        paper_candidates = [row for row in candidates if row.ticker.upper() in paper]
        if paper_candidates:
            candidates = paper_candidates
    if not candidates:
        return {"should_dispatch": False, "reason": "no buy-tier tickers with outstanding gaps"}
    top = candidates[0]
    return {
        "should_dispatch": True,
        "pin_ticker": top.ticker,
        "reason": (
            f"top gap candidate {top.ticker} "
            f"(priority_score={top.priority_score}, indexed_without_body={top.indexed_without_body})"
        ),
    }


def has_recent_intensive_gap_closure_run(
    *,
    within_hours: float = 12.0,
    runs_path: Path | None = None,
) -> bool:
    store = load_ingest_gap_closure_runs(runs_path)
    now = datetime.now(UTC)
    for row in reversed(store.get("runs") or []):
        params = row.get("params") or {}
        if not params.get("intensive_gap_closure"):
            continue
        stamp = str(row.get("recorded_at") or "")
        if not stamp:
            continue
        try:
            recorded = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        age_hours = (now - recorded).total_seconds() / 3600.0
        if age_hours <= within_hours:
            return True
    return False


def evaluate_weekly_gap_closure_followup(
    *,
    health_after: dict[str, Any],
    was_gap_closure_run: bool,
    latest_path: Path = Path("docs/data/latest.json"),
    data_dir: Path = Path("docs/data"),
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    tasks_path: Path = Path("docs/data/engineering_tasks.json"),
    runs_path: Path | None = None,
) -> dict[str, Any]:
    """After weekday batch ingest, dispatch intensive single-ticker gap closure when gaps persist."""
    if was_gap_closure_run:
        return {"should_dispatch": False, "reason": "current run was already gap closure"}
    indexed_without_body = int(health_after.get("indexed_without_body") or 0)
    zero_body_buy_tier = int(health_after.get("zero_body_buy_tier") or 0)
    if indexed_without_body <= 0 and zero_body_buy_tier <= 0:
        return {"should_dispatch": False, "reason": "no outstanding ingest gaps after batch"}
    if has_recent_intensive_gap_closure_run(runs_path=runs_path, within_hours=6.0):
        return {"should_dispatch": False, "reason": "intensive gap closure run within 6h"}
    from value_investor.ingest_loop import has_open_ingest_engineering_tasks

    if has_open_ingest_engineering_tasks(tasks_path):
        return {"should_dispatch": False, "reason": "open ingest engineering task in flight"}
    candidate = select_gap_closure_candidate(
        latest_path=latest_path,
        data_dir=data_dir,
        suggestions_path=suggestions_path,
        prefer_paper_holdings=False,
    )
    if not candidate.get("should_dispatch"):
        return candidate
    return {
        **candidate,
        "trigger": "weekly_followup",
        "title": "Weekday ingest gap-closure follow-up",
        "summary": (
            "Automated intensive single-ticker pass after weekday batch left outstanding "
            "indexed_without_body on buy-tier names; review outcome for ingest-loop policy."
        ),
    }


def evaluate_eng_idle_gap_closure_dispatch(
    *,
    open_count: int,
    pr_open_count: int,
    agent_running_count: int = 0,
    latest_path: Path = Path("docs/data/latest.json"),
    data_dir: Path = Path("docs/data"),
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    tasks_path: Path = Path("docs/data/engineering_tasks.json"),
    runs_path: Path | None = None,
) -> dict[str, Any]:
    """When engineering queue is idle, dispatch intensive gap closure for paper holdings / buy-tier."""
    if int(open_count) > 0 or int(pr_open_count) > 0:
        return {"should_dispatch": False, "reason": "engineering queue not idle"}
    if int(agent_running_count) > 0:
        return {"should_dispatch": False, "reason": "engineering agent still running"}
    if has_recent_intensive_gap_closure_run(runs_path=runs_path, within_hours=6.0):
        return {"should_dispatch": False, "reason": "intensive gap closure run within 6h"}
    from value_investor.ingest_loop import has_open_ingest_engineering_tasks

    if has_open_ingest_engineering_tasks(tasks_path):
        return {"should_dispatch": False, "reason": "open ingest engineering task in flight"}
    candidate = select_gap_closure_candidate(
        latest_path=latest_path,
        data_dir=data_dir,
        suggestions_path=suggestions_path,
        prefer_paper_holdings=True,
    )
    if not candidate.get("should_dispatch"):
        return candidate
    return {
        **candidate,
        "trigger": "eng_idle",
        "title": "Eng-idle ingest gap-closure pass",
        "summary": (
            "Engineering queue idle with outstanding ingest gaps on paper holdings or top "
            "buy-tier candidate; intensive single-ticker closure for horizon assessment."
        ),
    }
