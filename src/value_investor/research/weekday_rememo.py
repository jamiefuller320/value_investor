"""Bounded weekday rememo when ingest lifts filing-body coverage on memo tickers."""

from __future__ import annotations

import logging
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
from value_investor.research.memo_backfill import publish_memo_backfill_batch
from value_investor.research.runner import _process_ticker
from value_investor.research.source_quality import score_research_sources
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_WEEKDAY_REMEMO_CAP = 3
DEFAULT_MEMO_USD = 0.4
DEFAULT_MIN_HEADROOM_USD = 8.0
DEFAULT_BODY_LAG_THRESHOLD = 10
DEFAULT_SUMMARY_PATH = Path("docs/data/weekday_memo_rememo_summary.json")
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


def select_weekday_rememo_targets(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    ingest_results: list[dict[str, Any]] | None = None,
    max_targets: int = DEFAULT_WEEKDAY_REMEMO_CAP,
    body_lag_threshold: int = DEFAULT_BODY_LAG_THRESHOLD,
) -> list[WeekdayRememoTarget]:
    """
    Pick memo tickers that need a force-initial rememo after weekday ingest.

    Priority:
    1. Ingest ``improved`` rows that already have a research memo
    2. Published ``adequate`` (or missing) grades whose disk bodies lag the
       published ``filings_with_body`` by ``body_lag_threshold``+
    """
    published = _published_research_by_ticker(latest_path)
    improved = {
        str(row.get("ticker") or "").strip().upper()
        for row in (ingest_results or [])
        if isinstance(row, dict) and row.get("improved") and row.get("ticker")
    }

    candidates: list[WeekdayRememoTarget] = []
    seen: set[str] = set()

    def _consider(ticker: str, *, ingest_improved: bool, reason: str) -> None:
        ticker = ticker.strip().upper()
        if not ticker or ticker in seen:
            return
        meta_path = committed_dir / ticker / "research.json"
        if not meta_path.exists():
            return
        disk_bodies = _disk_body_count(committed_dir, ticker)
        pub = published.get(ticker) or {}
        mq = pub.get("memo_quality") or {}
        pub_bodies = int(mq.get("filings_with_body") or (pub.get("source_counts") or {}).get("filings_with_body") or 0)
        grade = str(mq.get("grade") or "").strip().lower() or None
        seen.add(ticker)
        candidates.append(
            WeekdayRememoTarget(
                ticker=ticker,
                name=str(pub.get("name") or ticker),
                reason=reason,
                disk_bodies=disk_bodies,
                published_bodies=pub_bodies,
                published_grade=grade,
                ingest_improved=ingest_improved,
            )
        )

    for ticker in sorted(improved):
        _consider(
            ticker,
            ingest_improved=True,
            reason="ingest_improved_bodies",
        )

    for ticker, pub in sorted(published.items()):
        mq = pub.get("memo_quality") or {}
        grade = str(mq.get("grade") or "").strip().lower()
        pub_bodies = int(mq.get("filings_with_body") or 0)
        disk_bodies = _disk_body_count(committed_dir, ticker)
        lag = disk_bodies - pub_bodies
        if grade in {"adequate", "thin", "poor", ""} and lag >= body_lag_threshold:
            _consider(
                ticker,
                ingest_improved=ticker in improved,
                reason=f"stale_{grade or 'missing'}_grade_body_lag_{lag}",
            )
        elif lag >= max(body_lag_threshold * 2, 25):
            # Strong badge but large body lag — text still written on thin corpus.
            _consider(
                ticker,
                ingest_improved=ticker in improved,
                reason=f"strong_grade_large_body_lag_{lag}",
            )

    # Prefer ingest-improved, then largest body lag.
    candidates.sort(
        key=lambda row: (
            0 if row.ingest_improved else 1,
            -(row.disk_bodies - row.published_bodies),
            row.ticker,
        )
    )
    return candidates[: max(0, int(max_targets))]


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
) -> WeekdayRememoSummary:
    """Force-initial rememo for a bounded set of lagging memo tickers."""
    summary = WeekdayRememoSummary(
        run_at=datetime.now(UTC).isoformat(),
        dry_run=bool(dry_run),
    )

    if ingest_results is None and ingest_loop_json and ingest_loop_json.exists():
        try:
            loop = read_json(ingest_loop_json)
            ingest_summary = (loop.get("ingest_summary") or {}) if isinstance(loop, dict) else {}
            ingest_results = list(ingest_summary.get("results") or [])
        except (OSError, ValueError, TypeError):
            ingest_results = []

    targets = select_weekday_rememo_targets(
        latest_path=latest_path,
        committed_dir=committed_dir,
        ingest_results=ingest_results,
        max_targets=max_targets,
        body_lag_threshold=body_lag_threshold,
    )
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
    }

    if not targets:
        summary.skipped.append("no_targets")
        write_json(summary_path, summary.to_dict())
        return summary

    if bool(budget.get("constraining")) or remaining < (estimated + float(min_headroom_usd)):
        summary.skipped.append("weekly_ops_headroom")
        write_json(summary_path, summary.to_dict())
        return summary

    if dry_run:
        write_json(summary_path, summary.to_dict())
        return summary

    if not api_key:
        summary.errors.append("CURSOR_API_KEY required for weekday rememo")
        write_json(summary_path, summary.to_dict())
        return summary

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
            "recorded_usd": estimate_agent_spend_usd(len(summary.rememoed), memo_usd=memo_usd),
        }

    write_json(summary_path, summary.to_dict())
    return summary
