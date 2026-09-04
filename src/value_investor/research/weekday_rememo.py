"""Bounded weekday rememo when ingest lifts filing-body coverage on memo tickers."""

from __future__ import annotations

import logging
import math
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    SPEND_POOL_WEEKLY_OPS,
    estimate_agent_spend_usd,
    record_estimated_spend,
    weekly_ops_budget_status,
)
from value_investor.research.market_store import rememo_reason
from value_investor.research.memo_backfill import publish_memo_backfill_batch
from value_investor.research.runner import _process_ticker
from value_investor.research.source_quality import score_research_sources
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_WEEKDAY_REMEMO_CAP = 3
DEFAULT_CATCHUP_REMEMO_CAP = 5
DEFAULT_MEMO_USD = 0.4
DEFAULT_MIN_HEADROOM_USD = 8.0
DEFAULT_BODY_LAG_THRESHOLD = 10
DEFAULT_WEEKDAY_MAINTENANCE_DAYS = 5
DEFAULT_SUMMARY_PATH = Path("docs/data/weekday_memo_rememo_summary.json")
DEFAULT_BACKLOG_PATH = Path("docs/data/memo_rememo_backlog.json")
DEFAULT_CATCHUP_REQUEST_PATH = Path("docs/data/memo_rememo_catchup_request.json")
DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_COMMITTED_RESEARCH = Path("docs/data/research")


@dataclass
class WeekdayRememoTarget:
    ticker: str
    name: str
    reason: str
    disk_bodies: int
    published_bodies: int
    published_grade: str | None
    ingest_improved: bool = False


@dataclass
class WeekdayRememoSummary:
    run_at: str = ""
    selected: list[str] = field(default_factory=list)
    rememoed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    grades_before: dict[str, Any] = field(default_factory=dict)
    grades_after: dict[str, Any] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    mode: str = "weekday"
    backlog_before: int = 0
    backlog_after: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_at": self.run_at,
            "selected": self.selected,
            "rememoed": self.rememoed,
            "skipped": self.skipped,
            "errors": self.errors,
            "grades_before": self.grades_before,
            "grades_after": self.grades_after,
            "reasons": self.reasons,
            "budget": self.budget,
            "dry_run": self.dry_run,
            "mode": self.mode,
            "backlog_before": self.backlog_before,
            "backlog_after": self.backlog_after,
        }


def _disk_body_count(committed_dir: Path, ticker: str) -> int:
    idx = committed_dir / ticker / "sources" / "filings" / "filings_index.json"
    if not idx.exists():
        return 0
    try:
        payload = read_json(idx)
    except (OSError, ValueError, TypeError):
        return 0
    summary = payload.get("summary") or {}
    return int(summary.get("with_body") or 0)


def _published_research_by_ticker(latest_path: Path) -> dict[str, dict[str, Any]]:
    if not latest_path.exists():
        return {}
    try:
        payload = read_json(latest_path)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("research") or []:
        if isinstance(row, dict) and row.get("ticker"):
            out[str(row["ticker"]).strip().upper()] = row
    return out


def _committed_memo_meta(committed_dir: Path, ticker: str) -> dict[str, Any]:
    meta_path = committed_dir / ticker / "research.json"
    if not meta_path.exists():
        return {}
    try:
        payload = read_json(meta_path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _report_for_ticker(ticker: str, latest_path: Path, sources_dir: Path) -> CompanyReport | None:
    if latest_path.exists():
        try:
            payload = read_json(latest_path)
        except (OSError, ValueError, TypeError):
            payload = {}
        for row in (payload.get("reports") or []) if isinstance(payload, dict) else []:
            if isinstance(row, dict) and str(row.get("ticker") or "").upper() == ticker.upper():
                return CompanyReport.from_dict(row)
    snap = sources_dir / "screening_snapshot.json"
    if snap.exists():
        try:
            data = read_json(snap)
        except (OSError, ValueError, TypeError):
            data = None
        if isinstance(data, dict) and data.get("ticker"):
            return CompanyReport.from_dict(data)
    return None


def _quality_snapshot(
    ticker: str,
    *,
    committed_dir: Path,
    published: dict[str, dict[str, Any]],
    prefer_committed: bool,
) -> tuple[str | None, int, str]:
    """Return ``(grade, memo_bodies, name)`` used for body-lag comparison."""
    pub = published.get(ticker) or {}
    committed = _committed_memo_meta(committed_dir, ticker)
    committed_mq = committed.get("memo_quality") or {}
    pub_mq = pub.get("memo_quality") or {}
    if prefer_committed and committed_mq:
        grade_src = committed_mq
    else:
        grade_src = pub_mq or committed_mq
    grade = str(grade_src.get("grade") or "").strip().lower() or None
    # Prefer committed body counts only when the field is present; otherwise keep
    # latest.research counts so in-sync published rows are not false-positives.
    if prefer_committed and "filings_with_body" in committed_mq:
        bodies = int(committed_mq.get("filings_with_body") or 0)
    else:
        bodies = int(
            pub_mq.get("filings_with_body")
            or committed_mq.get("filings_with_body")
            or (pub.get("source_counts") or {}).get("filings_with_body")
            or 0
        )
    name = str(pub.get("name") or committed.get("name") or ticker)
    return grade, bodies, name


def list_rememo_backlog(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    ingest_results: list[dict[str, Any]] | None = None,
    body_lag_threshold: int = DEFAULT_BODY_LAG_THRESHOLD,
    scan_committed: bool = True,
) -> list[WeekdayRememoTarget]:
    """
    Uncapped rememo backlog.

    When ``scan_committed`` is true (default), committed ``research.json``
    memo_quality is the source of truth so catch-up includes memos absent from
    the ``latest.json`` research index.
    """
    published = _published_research_by_ticker(latest_path)
    improved = {
        str(row.get("ticker") or "").strip().upper()
        for row in (ingest_results or [])
        if isinstance(row, dict) and row.get("improved") and row.get("ticker")
    }

    candidates: list[WeekdayRememoTarget] = []
    seen: set[str] = set()

    def _consider(
        ticker: str,
        *,
        ingest_improved: bool,
        reason: str,
        grade: str | None,
        memo_bodies: int,
        disk_bodies: int,
        name: str,
    ) -> None:
        ticker = ticker.strip().upper()
        if not ticker or ticker in seen:
            return
        if not (committed_dir / ticker / "research.json").exists():
            return
        seen.add(ticker)
        candidates.append(
            WeekdayRememoTarget(
                ticker=ticker,
                name=name,
                reason=reason,
                disk_bodies=disk_bodies,
                published_bodies=memo_bodies,
                published_grade=grade,
                ingest_improved=ingest_improved,
            )
        )

    for ticker in sorted(improved):
        grade, memo_bodies, name = _quality_snapshot(
            ticker,
            committed_dir=committed_dir,
            published=published,
            prefer_committed=scan_committed,
        )
        _consider(
            ticker,
            ingest_improved=True,
            reason="ingest_improved_bodies",
            grade=grade,
            memo_bodies=memo_bodies,
            disk_bodies=_disk_body_count(committed_dir, ticker),
            name=name,
        )

    tickers: set[str] = set(published)
    if scan_committed and committed_dir.exists():
        for path in committed_dir.iterdir():
            if path.is_dir() and (path / "research.json").exists():
                tickers.add(path.name.strip().upper())

    for ticker in sorted(tickers):
        grade, memo_bodies, name = _quality_snapshot(
            ticker,
            committed_dir=committed_dir,
            published=published,
            prefer_committed=scan_committed,
        )
        disk_bodies = _disk_body_count(committed_dir, ticker)
        reason = rememo_reason(
            grade=grade,
            memo_bodies=memo_bodies,
            disk_bodies=disk_bodies,
            body_lag_threshold=body_lag_threshold,
            ingest_improved=ticker in improved,
        )
        if reason:
            _consider(
                ticker,
                ingest_improved=ticker in improved,
                reason=reason,
                grade=grade,
                memo_bodies=memo_bodies,
                disk_bodies=disk_bodies,
                name=name,
            )

    candidates.sort(
        key=lambda row: (
            0 if row.ingest_improved else 1,
            -(row.disk_bodies - row.published_bodies),
            row.ticker,
        )
    )
    return candidates


def resolve_explicit_rememo_targets(
    tickers: list[str],
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    reason: str = "stale_by_age",
    scan_committed: bool = True,
) -> tuple[list[WeekdayRememoTarget], list[str]]:
    """Build rememo targets for an operator-supplied ticker list (no body-lag filter)."""
    published = _published_research_by_ticker(latest_path)
    targets: list[WeekdayRememoTarget] = []
    missing: list[str] = []
    seen: set[str] = set()
    for raw in tickers:
        ticker = str(raw or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        if not (committed_dir / ticker / "research.json").exists():
            missing.append(ticker)
            continue
        grade, memo_bodies, name = _quality_snapshot(
            ticker,
            committed_dir=committed_dir,
            published=published,
            prefer_committed=scan_committed,
        )
        targets.append(
            WeekdayRememoTarget(
                ticker=ticker,
                name=name,
                reason=reason,
                disk_bodies=_disk_body_count(committed_dir, ticker),
                published_bodies=memo_bodies,
                published_grade=grade,
                ingest_improved=False,
            )
        )
    return targets, missing


def select_weekday_rememo_targets(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    ingest_results: list[dict[str, Any]] | None = None,
    max_targets: int = DEFAULT_WEEKDAY_REMEMO_CAP,
    body_lag_threshold: int = DEFAULT_BODY_LAG_THRESHOLD,
    scan_committed: bool = True,
) -> list[WeekdayRememoTarget]:
    """Pick a bounded set of memo tickers that need force-initial rememo."""
    return list_rememo_backlog(
        latest_path=latest_path,
        committed_dir=committed_dir,
        ingest_results=ingest_results,
        body_lag_threshold=body_lag_threshold,
        scan_committed=scan_committed,
    )[: max(0, int(max_targets))]


def weekly_rememo_maintenance_capacity(
    *,
    per_day_cap: int = DEFAULT_WEEKDAY_REMEMO_CAP,
    weekdays: int = DEFAULT_WEEKDAY_MAINTENANCE_DAYS,
) -> int:
    return max(0, int(per_day_cap) * max(0, int(weekdays)))


def assess_rememo_backlog(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    ingest_results: list[dict[str, Any]] | None = None,
    body_lag_threshold: int = DEFAULT_BODY_LAG_THRESHOLD,
    per_day_cap: int = DEFAULT_WEEKDAY_REMEMO_CAP,
    memo_usd: float = DEFAULT_MEMO_USD,
    min_headroom_usd: float = DEFAULT_MIN_HEADROOM_USD,
    scan_committed: bool = True,
) -> dict[str, Any]:
    """Compare rememo backlog to in-week maintenance capacity and budget headroom."""
    backlog = list_rememo_backlog(
        latest_path=latest_path,
        committed_dir=committed_dir,
        ingest_results=ingest_results,
        body_lag_threshold=body_lag_threshold,
        scan_committed=scan_committed,
    )
    capacity = weekly_rememo_maintenance_capacity(per_day_cap=per_day_cap)
    budget = weekly_ops_budget_status(estimated_memo_usd=memo_usd)
    remaining = float(budget.get("remaining_weekly_ops_usd") or 0.0)
    affordable = 0
    if memo_usd > 0 and remaining > float(min_headroom_usd):
        affordable = max(
            0,
            int(math.floor((remaining - float(min_headroom_usd)) / float(memo_usd))),
        )

    count = len(backlog)
    over_capacity = count > capacity
    weeks_to_clear = (
        int(math.ceil(count / capacity)) if capacity > 0 and count else (0 if count == 0 else None)
    )

    if count == 0:
        action = "none"
    elif over_capacity and affordable > 0:
        action = "catch_up"
    elif over_capacity:
        action = "escalate"
    else:
        action = "maintain"

    recommended_batch = 0
    if action == "catch_up":
        recommended_batch = max(
            int(per_day_cap),
            min(
                count,
                affordable,
                max(int(per_day_cap) * 2, DEFAULT_CATCHUP_REMEMO_CAP),
            ),
        )

    return {
        "assessed_at": datetime.now(UTC).isoformat(),
        "backlog_count": count,
        "weekly_maintenance_capacity": capacity,
        "per_day_cap": int(per_day_cap),
        "weeks_to_clear_at_maintenance": weeks_to_clear,
        "over_weekly_capacity": over_capacity,
        "affordable_now": affordable,
        "recommended_catchup_batch": recommended_batch,
        "estimated_catchup_usd": round(
            estimate_agent_spend_usd(count, memo_usd=memo_usd),
            2,
        ),
        "remaining_weekly_ops_usd": remaining,
        "min_headroom_usd": float(min_headroom_usd),
        "action": action,
        "tickers": [
            {
                "ticker": row.ticker,
                "name": row.name,
                "reason": row.reason,
                "grade": row.published_grade,
                "disk_bodies": row.disk_bodies,
                "memo_bodies": row.published_bodies,
                "lag": row.disk_bodies - row.published_bodies,
            }
            for row in backlog
        ],
        "budget": budget,
    }


def write_rememo_backlog_status(
    *,
    path: Path = DEFAULT_BACKLOG_PATH,
    catchup_request_path: Path = DEFAULT_CATCHUP_REQUEST_PATH,
    **kwargs: Any,
) -> dict[str, Any]:
    """Persist backlog assessment and activate/clear catch-up requests."""
    assessment = assess_rememo_backlog(**kwargs)
    write_json(path, assessment)

    if (
        assessment.get("action") == "catch_up"
        and int(assessment.get("recommended_catchup_batch") or 0) > 0
    ):
        request = {
            "requested_at": assessment["assessed_at"],
            "active": True,
            "reason": "backlog_exceeds_weekly_maintenance_capacity",
            "backlog_count": assessment["backlog_count"],
            "weekly_maintenance_capacity": assessment["weekly_maintenance_capacity"],
            "elevated_cap": assessment["recommended_catchup_batch"],
            "tickers": [row["ticker"] for row in assessment.get("tickers") or []],
        }
        write_json(catchup_request_path, request)
        assessment["catchup_request"] = request
    elif catchup_request_path.exists():
        try:
            existing = read_json(catchup_request_path)
        except (OSError, ValueError, TypeError):
            existing = {}
        if isinstance(existing, dict) and existing.get("active"):
            cleared = {
                **existing,
                "active": False,
                "cleared_at": assessment["assessed_at"],
                "clear_reason": assessment.get("action") or "backlog_within_capacity",
                "backlog_count": assessment["backlog_count"],
            }
            write_json(catchup_request_path, cleared)
            assessment["catchup_request"] = cleared

    return assessment


def read_active_catchup_cap(
    path: Path = DEFAULT_CATCHUP_REQUEST_PATH,
    *,
    default_cap: int = DEFAULT_WEEKDAY_REMEMO_CAP,
) -> int:
    """Return elevated rememo cap when an active catch-up request exists."""
    if not path.exists():
        return int(default_cap)
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return int(default_cap)
    if not isinstance(payload, dict) or not payload.get("active"):
        return int(default_cap)
    try:
        elevated = int(payload.get("elevated_cap") or default_cap)
    except (TypeError, ValueError):
        elevated = int(default_cap)
    return max(int(default_cap), elevated)


def run_weekday_memo_rememo_pass(
    *,
    api_key: str | None,
    latest_path: Path = DEFAULT_LATEST_PATH,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    output_dir: Path = Path("output"),
    dest_dir: Path = Path("docs"),
    ingest_results: list[dict[str, Any]] | None = None,
    ingest_loop_json: Path | None = None,
    max_targets: int = DEFAULT_WEEKDAY_REMEMO_CAP,
    body_lag_threshold: int = DEFAULT_BODY_LAG_THRESHOLD,
    memo_usd: float = DEFAULT_MEMO_USD,
    min_headroom_usd: float = DEFAULT_MIN_HEADROOM_USD,
    market: str = "ftse350",
    model: str = "composer-2.5",
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    dry_run: bool = False,
    publish: bool = True,
    record_spend: bool = True,
    scan_committed: bool = True,
    mode: str = "weekday",
    update_backlog_status: bool = True,
    honor_catchup_request: bool = True,
    catchup_request_path: Path = DEFAULT_CATCHUP_REQUEST_PATH,
    explicit_tickers: list[str] | None = None,
    explicit_reason: str = "stale_by_age",
) -> WeekdayRememoSummary:
    """Force-initial rememo for a bounded set of lagging memo tickers."""
    summary = WeekdayRememoSummary(
        run_at=datetime.now(UTC).isoformat(),
        dry_run=bool(dry_run),
        mode=str(mode or "weekday"),
    )

    if ingest_results is None and ingest_loop_json and ingest_loop_json.exists():
        try:
            loop = read_json(ingest_loop_json)
            ingest_summary = (loop.get("ingest_summary") or {}) if isinstance(loop, dict) else {}
            ingest_results = list(ingest_summary.get("results") or [])
        except (OSError, ValueError, TypeError):
            ingest_results = []

    effective_cap = int(max_targets)
    if honor_catchup_request and summary.mode == "weekday" and not explicit_tickers:
        effective_cap = read_active_catchup_cap(
            catchup_request_path,
            default_cap=effective_cap,
        )

    missing_explicit: list[str] = []
    if explicit_tickers:
        targets, missing_explicit = resolve_explicit_rememo_targets(
            explicit_tickers,
            latest_path=latest_path,
            committed_dir=committed_dir,
            reason=explicit_reason,
            scan_committed=scan_committed,
        )
        summary.backlog_before = len(targets)
        if missing_explicit:
            summary.skipped.extend(f"missing_committed:{ticker}" for ticker in missing_explicit)
        targets = targets[: max(0, effective_cap)]
    else:
        backlog = list_rememo_backlog(
            latest_path=latest_path,
            committed_dir=committed_dir,
            ingest_results=ingest_results,
            body_lag_threshold=body_lag_threshold,
            scan_committed=scan_committed,
        )
        summary.backlog_before = len(backlog)
        targets = backlog[: max(0, effective_cap)]
    summary.selected = [t.ticker for t in targets]
    summary.reasons = {t.ticker: t.reason for t in targets}
    for t in targets:
        summary.grades_before[t.ticker] = {
            "grade": t.published_grade,
            "published_bodies": t.published_bodies,
            "disk_bodies": t.disk_bodies,
            "reason": t.reason,
        }

    budget = weekly_ops_budget_status(estimated_memo_usd=memo_usd)
    estimated = estimate_agent_spend_usd(len(targets), memo_usd=memo_usd)
    remaining = float(budget.get("remaining_weekly_ops_usd") or 0.0)
    summary.budget = {
        "estimated_usd": estimated,
        "remaining_weekly_ops_usd": remaining,
        "min_headroom_usd": min_headroom_usd,
        "constraining": bool(budget.get("constraining")),
        "effective_cap": effective_cap,
    }

    def _persist_status() -> None:
        if not update_backlog_status:
            return
        status = write_rememo_backlog_status(
            latest_path=latest_path,
            committed_dir=committed_dir,
            body_lag_threshold=body_lag_threshold,
            memo_usd=memo_usd,
            min_headroom_usd=min_headroom_usd,
            scan_committed=scan_committed,
        )
        summary.backlog_after = int(status.get("backlog_count") or 0)

    if not targets:
        summary.skipped.append("no_targets")
        write_json(summary_path, summary.to_dict())
        _persist_status()
        write_json(summary_path, summary.to_dict())
        return summary

    if bool(budget.get("constraining")) or remaining < (estimated + float(min_headroom_usd)):
        affordable = 0
        if memo_usd > 0 and remaining > float(min_headroom_usd):
            affordable = int(math.floor((remaining - float(min_headroom_usd)) / float(memo_usd)))
        if affordable <= 0:
            summary.skipped.append("weekly_ops_headroom")
            write_json(summary_path, summary.to_dict())
            _persist_status()
            write_json(summary_path, summary.to_dict())
            return summary
        targets = targets[:affordable]
        summary.selected = [t.ticker for t in targets]
        summary.reasons = {t.ticker: t.reason for t in targets}
        summary.grades_before = {t.ticker: summary.grades_before[t.ticker] for t in targets}
        estimated = estimate_agent_spend_usd(len(targets), memo_usd=memo_usd)
        summary.budget["estimated_usd"] = estimated
        summary.budget["shrunk_to_affordable"] = affordable
        summary.skipped.append("weekly_ops_headroom_shrunk")

    if dry_run:
        write_json(summary_path, summary.to_dict())
        _persist_status()
        write_json(summary_path, summary.to_dict())
        return summary

    if not api_key:
        summary.errors.append("CURSOR_API_KEY required for weekday rememo")
        write_json(summary_path, summary.to_dict())
        return summary

    model = (model or "composer-2.5").strip() or "composer-2.5"
    store = ResearchStore(output_dir)
    run_at = datetime.now(UTC)

    for target in targets:
        committed = committed_dir / target.ticker
        out_ticker = output_dir / "research" / target.ticker
        try:
            if out_ticker.exists():
                shutil.rmtree(out_ticker)
            shutil.copytree(committed, out_ticker)
            for name in ("research.json", "research.md", "agent_id.txt"):
                path = out_ticker / name
                if path.exists():
                    path.unlink()

            report = _report_for_ticker(target.ticker, latest_path, out_ticker / "sources")
            if report is None:
                summary.errors.append(f"{target.ticker}: missing CompanyReport")
                continue

            doc, action = _process_ticker(
                report=report,
                store=store,
                api_key=api_key,
                model=model,
                cwd=str(Path.cwd()),
                force_initial=True,
                run_at=run_at,
                market=market,
            )
            mq = doc.memo_quality or score_research_sources(source_counts=doc.source_counts)
            summary.rememoed.append(target.ticker)
            summary.grades_after[target.ticker] = {
                "grade": mq.get("grade"),
                "score": mq.get("source_quality_score"),
                "bodies": f"{mq.get('filings_with_body')}/{mq.get('filings_total')}",
                "action": action,
            }
            logger.info(
                "Weekday rememo %s → %s (%s)",
                target.ticker,
                mq.get("grade"),
                summary.grades_after[target.ticker]["bodies"],
            )
            write_json(summary_path, summary.to_dict())
            if publish:
                publish_memo_backfill_batch(
                    output_dir,
                    dest_dir=dest_dir,
                    latest_path=dest_dir / "data" / "latest.json",
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Weekday rememo failed for %s", target.ticker)
            summary.errors.append(f"{target.ticker}: {exc}")
            write_json(summary_path, summary.to_dict())

    if record_spend and summary.rememoed:
        record_estimated_spend(
            estimate_agent_spend_usd(len(summary.rememoed), memo_usd=memo_usd),
            pool=SPEND_POOL_WEEKLY_OPS,
        )
        summary.budget = {
            **summary.budget,
            **weekly_ops_budget_status(estimated_memo_usd=memo_usd),
            "recorded_usd": estimate_agent_spend_usd(
                len(summary.rememoed),
                memo_usd=memo_usd,
            ),
        }

    _persist_status()
    write_json(summary_path, summary.to_dict())
    return summary
