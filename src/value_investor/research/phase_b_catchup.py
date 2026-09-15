"""Bounded Phase B catch-up: essay-mode committed memos → structured_verdict* modes.

Distinct from weekday body-lag rememo (force_initial). Uses the same weekly
structured update path as Sunday ``--research-docs`` after seeding committed
stores into ``output/research``.
"""

from __future__ import annotations

import logging
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
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.phase_c_readiness import STRUCTURED_VERDICT_MODES
from value_investor.research.memo_backfill import (
    load_buy_tier_reports,
    publish_memo_backfill_batch,
    sync_committed_memos_to_output,
    sync_committed_sources_to_output,
    sync_output_research_to_committed,
)
from value_investor.research.runner import _process_ticker
from value_investor.research.store import ResearchStore
from value_investor.research.weekday_rememo import (
    DEFAULT_COMMITTED_RESEARCH,
    DEFAULT_LATEST_PATH,
    _report_for_ticker,
)
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("docs/data/phase_b_catchup_state.json")
DEFAULT_SUMMARY_PATH = Path("docs/data/phase_b_catchup_summary.json")
DEFAULT_BATCH_SIZE = 6
DEFAULT_MEMO_USD = 0.35
DEFAULT_MIN_HEADROOM_USD = 2.0


@dataclass
class PhaseBCatchupSummary:
    run_at: str
    dry_run: bool = False
    backlog_before: int = 0
    backlog_after: int | None = None
    selected: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    persisted_trees: int = 0
    budget: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_at": self.run_at,
            "dry_run": self.dry_run,
            "backlog_before": self.backlog_before,
            "backlog_after": self.backlog_after,
            "selected": list(self.selected),
            "updated": list(self.updated),
            "skipped": list(self.skipped),
            "errors": list(self.errors),
            "persisted_trees": self.persisted_trees,
            "budget": dict(self.budget),
        }


def _needs_phase_b_catchup(meta: dict[str, Any]) -> bool:
    mode = str(meta.get("mode") or "").strip()
    return mode not in STRUCTURED_VERDICT_MODES


def list_phase_b_backlog(
    *,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    latest_path: Path = DEFAULT_LATEST_PATH,
) -> list[str]:
    """Tickers whose committed ``research.json`` is not yet a structured_verdict* mode."""
    if not committed_dir.is_dir():
        return []
    reports_by_ticker = {r.ticker.strip().upper(): r for r in load_buy_tier_reports(latest_path)}
    backlog: list[str] = []
    for ticker_dir in sorted(committed_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        meta_path = ticker_dir / "research.json"
        if not meta_path.is_file():
            continue
        try:
            meta = read_json(meta_path)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(meta, dict) or not _needs_phase_b_catchup(meta):
            continue
        backlog.append(ticker_dir.name.strip().upper())

    def sort_key(ticker: str) -> tuple[int, int, float, str]:
        report = reports_by_ticker.get(ticker)
        if report is None:
            return (1, 2, 0.0, ticker)
        signal_rank = (
            0 if report.signal == "strong_buy" else (1 if report.signal in BUY_SIGNALS else 2)
        )
        return (0, signal_rank, -(report.conviction_score or 0.0), ticker)

    backlog.sort(key=sort_key)
    return backlog


def _company_report_for_catchup(
    ticker: str,
    *,
    latest_path: Path,
    committed_dir: Path,
) -> CompanyReport | None:
    sources_dir = committed_dir / ticker / "sources"
    report = _report_for_ticker(ticker, latest_path, sources_dir)
    if report is not None:
        return report
    meta_path = committed_dir / ticker / "research.json"
    if not meta_path.exists():
        return None
    try:
        meta = read_json(meta_path)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(meta, dict):
        return None
    signal = str(meta.get("signal") or "buy")
    name = str(meta.get("name") or ticker)
    return CompanyReport.from_dict(
        {
            "ticker": ticker,
            "name": name,
            "signal": signal,
            "sector": None,
            "models_passed": 0,
            "model_count": 0,
            "composite_score": None,
            "sector_composite_score": None,
            "families_passed": 0,
            "passed_families": None,
            "data_quality_score": 0.0,
            "metrics_present": 0,
            "metrics_total": 0,
            "weeks_at_signal": 0,
            "signal_trend": "flat",
            "conviction_score": 0.0,
            "stability_label": "",
            "timing_signal": "",
            "timing_score": 0.0,
            "rsi_14": None,
            "price_vs_sma200_pct": None,
            "action_note": "",
            "trade_plan": None,
            "summary": "",
            "passed_models": [],
            "key_metrics": {},
        }
    )


def write_phase_b_backlog_status(
    *,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    latest_path: Path = DEFAULT_LATEST_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    recommended_batch: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    backlog = list_phase_b_backlog(committed_dir=committed_dir, latest_path=latest_path)
    payload = {
        "schema_version": 1,
        "updated_at": datetime.now(UTC).isoformat(),
        "backlog_count": len(backlog),
        "recommended_batch": int(recommended_batch),
        "remaining_tickers": backlog,
        "next_batch": backlog[: int(recommended_batch)],
    }
    write_json(state_path, payload, compact=False)
    return payload


def run_phase_b_catchup_pass(
    *,
    api_key: str | None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    latest_path: Path = DEFAULT_LATEST_PATH,
    output_dir: Path = Path("output"),
    dest_dir: Path = Path("docs"),
    dry_run: bool = False,
    publish: bool = True,
    record_spend: bool = True,
    memo_usd: float = DEFAULT_MEMO_USD,
    min_headroom_usd: float = DEFAULT_MIN_HEADROOM_USD,
    market: str = "ftse350",
    model: str = "composer-2.5",
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    explicit_tickers: list[str] | None = None,
) -> PhaseBCatchupSummary:
    """Run structured weekly updates for a bounded essay-mode backlog."""
    summary = PhaseBCatchupSummary(
        run_at=datetime.now(UTC).isoformat(),
        dry_run=bool(dry_run),
    )
    backlog = list_phase_b_backlog(committed_dir=committed_dir, latest_path=latest_path)
    summary.backlog_before = len(backlog)

    if explicit_tickers:
        wanted = {t.strip().upper() for t in explicit_tickers if t and t.strip()}
        selected = [t for t in backlog if t in wanted]
        missing = sorted(wanted - set(selected))
        summary.skipped.extend(f"not_in_backlog:{t}" for t in missing)
    else:
        selected = backlog[: max(0, int(batch_size))]

    budget = weekly_ops_budget_status(estimated_memo_usd=memo_usd)
    estimated = estimate_agent_spend_usd(len(selected), memo_usd=memo_usd)
    remaining = float(budget.get("remaining_weekly_ops_usd") or 0.0)
    summary.budget = {
        "estimated_usd": estimated,
        "remaining_weekly_ops_usd": remaining,
        "min_headroom_usd": min_headroom_usd,
        "constraining": bool(budget.get("constraining")),
    }

    if not selected:
        summary.skipped.append("no_targets")
        write_phase_b_backlog_status(
            committed_dir=committed_dir,
            latest_path=latest_path,
            state_path=state_path,
            recommended_batch=batch_size,
        )
        summary.backlog_after = len(
            list_phase_b_backlog(committed_dir=committed_dir, latest_path=latest_path)
        )
        write_json(summary_path, summary.to_dict(), compact=False)
        return summary

    if bool(budget.get("constraining")) or remaining < (estimated + float(min_headroom_usd)):
        affordable = 0
        if memo_usd > 0 and remaining > float(min_headroom_usd):
            affordable = int((remaining - float(min_headroom_usd)) // float(memo_usd))
        if affordable <= 0:
            summary.skipped.append("weekly_ops_headroom")
            write_json(summary_path, summary.to_dict(), compact=False)
            return summary
        selected = selected[:affordable]
        summary.budget["shrunk_to_affordable"] = affordable
        summary.skipped.append("weekly_ops_headroom_shrunk")

    summary.selected = list(selected)

    if dry_run:
        write_phase_b_backlog_status(
            committed_dir=committed_dir,
            latest_path=latest_path,
            state_path=state_path,
            recommended_batch=batch_size,
        )
        summary.backlog_after = summary.backlog_before
        write_json(summary_path, summary.to_dict(), compact=False)
        return summary

    if not api_key:
        summary.errors.append("CURSOR_API_KEY required for Phase B catch-up")
        write_json(summary_path, summary.to_dict(), compact=False)
        return summary

    synced_memos = sync_committed_memos_to_output(output_dir, tickers=selected)
    synced_sources = sync_committed_sources_to_output(output_dir, tickers=selected)
    logger.info(
        "Phase B catch-up seeded memos=%s sources=%s for %s ticker(s)",
        synced_memos,
        synced_sources,
        len(selected),
    )

    store = ResearchStore(output_dir)
    run_at = datetime.now(UTC)
    model = (model or "composer-2.5").strip() or "composer-2.5"

    for ticker in selected:
        try:
            report = _company_report_for_catchup(
                ticker,
                latest_path=latest_path,
                committed_dir=committed_dir,
            )
            if report is None:
                summary.errors.append(f"{ticker}: missing CompanyReport")
                continue
            doc, action = _process_ticker(
                report=report,
                store=store,
                api_key=api_key,
                model=model,
                cwd=str(Path.cwd()),
                force_initial=False,
                run_at=run_at,
                market=market,
            )
            if doc.mode not in STRUCTURED_VERDICT_MODES:
                summary.errors.append(
                    f"{ticker}: expected structured_verdict* mode, got {doc.mode!r} ({action})"
                )
                continue
            summary.updated.append(ticker)
            logger.info("Phase B catch-up %s → mode=%s (%s)", ticker, doc.mode, action)
            write_json(summary_path, summary.to_dict(), compact=False)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Phase B catch-up failed for %s", ticker)
            summary.errors.append(f"{ticker}: {exc}")
            write_json(summary_path, summary.to_dict(), compact=False)

    if summary.updated:
        summary.persisted_trees = sync_output_research_to_committed(
            output_dir,
            tickers=summary.updated,
        )
        if publish:
            publish_memo_backfill_batch(
                output_dir,
                dest_dir=dest_dir,
                latest_path=dest_dir / "data" / "latest.json",
                tickers=summary.updated,
            )
        if record_spend:
            record_estimated_spend(
                estimate_agent_spend_usd(len(summary.updated), memo_usd=memo_usd),
                pool=SPEND_POOL_WEEKLY_OPS,
            )

    write_phase_b_backlog_status(
        committed_dir=committed_dir,
        latest_path=latest_path,
        state_path=state_path,
        recommended_batch=batch_size,
    )
    summary.backlog_after = len(
        list_phase_b_backlog(committed_dir=committed_dir, latest_path=latest_path)
    )
    write_json(summary_path, summary.to_dict(), compact=False)
    return summary
