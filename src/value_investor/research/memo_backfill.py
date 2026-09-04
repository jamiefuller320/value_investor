"""Batch initial research memos for buy-tier names with ingest but no published memo."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.paper_fund import BUY_SIGNALS
from value_investor.research.ingest_bootstrap import ensure_canonical_research_store
from value_investor.research.market_store import (
    documents_from_research_index,
    list_documents_from_research_root,
    merge_documents_by_ticker,
    resolve_research_documents,
)
from value_investor.research.overlay import apply_research_overlay
from value_investor.research.runner import _process_ticker
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_MEMO_DIR = Path("docs/research")
DEFAULT_COMMITTED_RESEARCH = Path("docs/data/research")
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_STATE_PATH = Path("docs/data/memo_backfill_state.json")
DEFAULT_LEGACY_REMEMO_STATE_PATH = Path("docs/data/legacy_rememo_state.json")
DEFAULT_BATCH_SIZE = 6


@dataclass
class MemoBackfillSummary:
    batch_size: int
    selected: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)
    published: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "selected": list(self.selected),
            "created": list(self.created),
            "skipped": list(self.skipped),
            "errors": list(self.errors),
            "remaining": list(self.remaining),
            "published": dict(self.published),
        }


def has_published_memo(
    ticker: str,
    *,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> bool:
    ticker = ticker.strip().upper()
    if (memo_dir / f"{ticker}.md").exists():
        return True
    if (committed_dir / ticker / "research.json").exists():
        return True
    if (output_dir / "research" / ticker / "research.json").exists():
        return True
    return False


def filings_with_body_count(
    ticker: str, *, committed_dir: Path = DEFAULT_COMMITTED_RESEARCH
) -> int:
    index_path = (
        committed_dir / ticker.strip().upper() / "sources" / "filings" / "filings_index.json"
    )
    if not index_path.exists():
        return 0
    try:
        payload = read_json(index_path)
    except (OSError, ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    summary = payload.get("summary") or {}
    return int(summary.get("with_body") or 0)


def load_buy_tier_reports(latest_path: Path = DEFAULT_LATEST_PATH) -> list[CompanyReport]:
    if not latest_path.exists():
        return []
    try:
        payload = read_json(latest_path)
    except (OSError, ValueError, TypeError):
        return []
    reports: list[CompanyReport] = []
    for row in payload.get("reports") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("signal") or "") not in BUY_SIGNALS:
            continue
        reports.append(CompanyReport.from_dict(row))
    return reports


def has_canonical_research_json(
    ticker: str,
    *,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> bool:
    ticker = ticker.strip().upper()
    if (committed_dir / ticker / "research.json").exists():
        return True
    if (output_dir / "research" / ticker / "research.json").exists():
        return True
    return False


def list_legacy_rememo_reports(
    reports: list[CompanyReport],
    *,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[CompanyReport]:
    """Buy-tier names with published markdown but no canonical ``research.json`` store."""
    legacy = [
        report
        for report in reports
        if (memo_dir / f"{report.ticker.strip().upper()}.md").exists()
        and not has_canonical_research_json(
            report.ticker,
            committed_dir=committed_dir,
            output_dir=output_dir,
        )
    ]
    legacy.sort(
        key=lambda report: (
            0 if report.signal == "strong_buy" else 1,
            -filings_with_body_count(report.ticker, committed_dir=committed_dir),
            -(report.conviction_score or 0.0),
            report.ticker,
        )
    )
    return legacy


def list_missing_memo_reports(
    reports: list[CompanyReport],
    *,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[CompanyReport]:
    missing = [
        report
        for report in reports
        if not has_published_memo(
            report.ticker,
            memo_dir=memo_dir,
            committed_dir=committed_dir,
            output_dir=output_dir,
        )
    ]
    missing.sort(
        key=lambda report: (
            0 if report.signal == "strong_buy" else 1,
            -filings_with_body_count(report.ticker, committed_dir=committed_dir),
            -(report.conviction_score or 0.0),
            report.ticker,
        )
    )
    return missing


def load_backfill_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_backfill_state(payload: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)


def sync_output_research_to_committed(
    output_dir: Path,
    data_dir: Path = Path("docs/data"),
    *,
    tickers: list[str] | None = None,
) -> int:
    """Copy memo artifacts from output/research into docs/data/research/{TICKER}/."""
    src_root = output_dir / "research"
    if not src_root.is_dir():
        return 0
    wanted = {str(t).strip().upper() for t in (tickers or []) if str(t).strip()} or None
    synced = 0
    dest_root = data_dir / "research"
    for ticker_dir in sorted(src_root.iterdir()):
        if not ticker_dir.is_dir():
            continue
        if wanted is not None and ticker_dir.name.strip().upper() not in wanted:
            continue
        if not (ticker_dir / "research.json").exists():
            continue
        dest = dest_root / ticker_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("research.json", "research.md", "agent_id.txt", "timeline.json"):
            src = ticker_dir / name
            if src.is_file():
                shutil.copy2(src, dest / name)
        revisions_src = ticker_dir / "revisions"
        if revisions_src.is_dir():
            shutil.copytree(revisions_src, dest / "revisions", dirs_exist_ok=True)
        sources_src = ticker_dir / "sources"
        if sources_src.is_dir():
            shutil.copytree(sources_src, dest / "sources", dirs_exist_ok=True)
        synced += 1
    return synced


def sync_committed_sources_to_output(
    output_dir: Path,
    *,
    data_dir: Path = Path("docs/data"),
    tickers: list[str] | None = None,
) -> int:
    """
    Copy thickened filing/news sources from docs/data/research into output/research.

    Sunday email historically wrote memos under ``output/`` *before* weekday-style
    ingest improvement thickened ``docs/data/``. Seeding output from committed
    sources first lets research-docs / gap-fill score and cite full bodies.
    """
    committed_root = data_dir / "research"
    if not committed_root.is_dir():
        return 0
    wanted = {t.strip().upper() for t in (tickers or []) if t and t.strip()} or None
    synced = 0
    dest_root = output_dir / "research"
    dest_root.mkdir(parents=True, exist_ok=True)
    for ticker_dir in sorted(committed_root.iterdir()):
        if not ticker_dir.is_dir():
            continue
        ticker = ticker_dir.name.strip().upper()
        if wanted is not None and ticker not in wanted:
            continue
        sources_src = ticker_dir / "sources"
        if not sources_src.is_dir():
            continue
        dest = dest_root / ticker
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(sources_src, dest / "sources", dirs_exist_ok=True)
        synced += 1
    return synced


def publish_memo_backfill_batch(
    output_dir: Path,
    *,
    dest_dir: Path = Path("docs"),
    latest_path: Path | None = None,
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Copy new memos to docs/research and merge research overlay into latest.json.

    When ``tickers`` is set, only those trees are copied from ``output/research``
    into markdown + committed stores. A prior full-index rebuild that restaged
    older trees into ``output/`` must not overwrite newer weekday copies.
    Omit ``tickers`` for ``rebuild_full_research_index``.
    """
    from value_investor.publish import _copy_research_memos

    latest_path = latest_path or (dest_dir / "data" / "latest.json")
    if not latest_path.exists():
        return {"error": f"missing {latest_path}"}

    payload = read_json(latest_path)
    if not isinstance(payload, dict):
        return {"error": "latest.json is not an object"}

    wanted = [str(t).strip().upper() for t in (tickers or []) if str(t).strip()]
    new_entries = _copy_research_memos(
        output_dir,
        dest_dir,
        tickers=wanted or None,
    )
    by_ticker = {
        str(row.get("ticker") or "").strip().upper(): row
        for row in payload.get("research") or []
        if isinstance(row, dict) and row.get("ticker")
    }
    for entry in new_entries:
        ticker = str(entry.get("ticker") or "").strip().upper()
        if ticker:
            by_ticker[ticker] = entry
    payload["research"] = sorted(by_ticker.values(), key=lambda item: str(item.get("name") or ""))

    reports = [
        CompanyReport.from_dict(row)
        for row in payload.get("reports") or []
        if isinstance(row, dict)
    ]
    if wanted:
        batch_docs = [
            doc
            for doc in ResearchStore(output_dir).list_documents()
            if str(doc.ticker or "").strip().upper() in set(wanted)
        ]
        documents = merge_documents_by_ticker(
            batch_docs,
            list_documents_from_research_root(dest_dir / "data" / "research"),
            documents_from_research_index(list(payload.get("research") or [])),
        )
    else:
        documents = resolve_research_documents(
            output_dir=output_dir,
            bundle=payload,
            committed_dir=dest_dir / "data" / "research",
        )
    overlay_reports = apply_research_overlay(reports, documents)
    overlay_by_ticker = {
        str(report.ticker or "").strip().upper(): report for report in overlay_reports
    }
    updated_reports: list[dict[str, Any]] = []
    for raw in payload.get("reports") or []:
        if not isinstance(raw, dict):
            continue
        ticker = str(raw.get("ticker") or "").strip().upper()
        if ticker in overlay_by_ticker:
            updated_reports.append(overlay_by_ticker[ticker].to_dict())
        else:
            updated_reports.append(raw)
    payload["reports"] = updated_reports
    payload["generated_at"] = datetime.now(UTC).isoformat()
    write_json(latest_path, payload, compact=True, compress=False)

    synced = sync_output_research_to_committed(
        output_dir,
        data_dir=dest_dir / "data",
        tickers=wanted or None,
    )
    return {
        "new_memo_entries": len(new_entries),
        "research_index_count": len(payload["research"]),
        "synced_committed_trees": synced,
        "tickers": wanted,
    }


def run_missing_memo_backfill(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    state_path: Path = DEFAULT_STATE_PATH,
    batch_size: int = DEFAULT_BATCH_SIZE,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    market: str = "ftse350",
    publish: bool = True,
    dest_dir: Path = Path("docs"),
    dry_run: bool = False,
) -> MemoBackfillSummary:
    """Create initial memos for buy-tier names that lack a published memo."""
    reports = load_buy_tier_reports(latest_path)
    missing = list_missing_memo_reports(
        reports,
        memo_dir=memo_dir,
        committed_dir=committed_dir,
        output_dir=output_dir,
    )
    batch_size = max(1, int(batch_size))
    selected_reports = missing[:batch_size]
    summary = MemoBackfillSummary(
        batch_size=batch_size,
        selected=[report.ticker for report in selected_reports],
        remaining=[report.ticker for report in missing[batch_size:]],
    )

    if dry_run:
        write_backfill_state(
            {
                "schema_version": 1,
                "updated_at": datetime.now(UTC).isoformat(),
                "dry_run": True,
                "missing_count": len(missing),
                "remaining": summary.remaining,
                "next_batch": summary.selected,
            },
            path=state_path,
        )
        return summary

    store = ResearchStore(output_dir)
    run_at = datetime.now(UTC)

    for report in selected_reports:
        try:
            ensure_canonical_research_store(
                report.ticker,
                report.name,
                output_dir=output_dir,
                screening_snapshot=report.to_dict(),
                market=market,
                seed_if_missing=False,
            )
            if store.exists(report.ticker):
                summary.skipped.append(report.ticker)
                continue
            doc, action = _process_ticker(
                report=report,
                store=store,
                api_key=api_key,
                model=model,
                cwd=cwd,
                force_initial=False,
                run_at=run_at,
                market=market,
            )
            if action == "created":
                summary.created.append(report.ticker)
                logger.info("Created memo for %s (bodies=%s)", report.ticker, doc.source_counts)
            else:
                summary.skipped.append(report.ticker)
        except Exception as exc:  # noqa: BLE001
            message = f"{report.ticker}: {exc}"
            logger.exception("Memo backfill failed for %s", report.ticker)
            summary.errors.append(message)

    if publish and summary.created:
        summary.published = publish_memo_backfill_batch(
            output_dir,
            dest_dir=dest_dir,
            latest_path=dest_dir / "data" / "latest.json",
            tickers=summary.created,
        )

    write_backfill_state(
        {
            "schema_version": 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "batch_size": batch_size,
            "missing_before": len(missing),
            "created": summary.created,
            "skipped": summary.skipped,
            "errors": summary.errors,
            "remaining": summary.remaining,
            "published": summary.published,
        },
        path=state_path,
    )
    return summary


def rebuild_full_research_index(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    dest_dir: Path = Path("docs"),
) -> dict[str, Any]:
    """Copy all committed research trees to output and refresh dashboard index + overlay."""
    output_root = output_dir / "research"
    output_root.mkdir(parents=True, exist_ok=True)
    for ticker_dir in sorted(committed_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        if not (ticker_dir / "research.json").exists():
            continue
        dest = output_root / ticker_dir.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(ticker_dir, dest)
    return publish_memo_backfill_batch(
        output_dir,
        dest_dir=dest_dir,
        latest_path=dest_dir / "data" / "latest.json",
    )


def run_legacy_rememo_pass(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    committed_dir: Path = DEFAULT_COMMITTED_RESEARCH,
    state_path: Path = DEFAULT_LEGACY_REMEMO_STATE_PATH,
    batch_size: int = DEFAULT_BATCH_SIZE,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    market: str = "ftse350",
    publish: bool = True,
    dest_dir: Path = Path("docs"),
    dry_run: bool = False,
    rebuild_index: bool = False,
) -> MemoBackfillSummary:
    """Force-initial research pass for legacy markdown memos missing canonical JSON."""
    reports = load_buy_tier_reports(latest_path)
    legacy = list_legacy_rememo_reports(
        reports,
        memo_dir=memo_dir,
        committed_dir=committed_dir,
        output_dir=output_dir,
    )
    batch_size = max(1, int(batch_size))
    selected_reports = legacy[:batch_size]
    summary = MemoBackfillSummary(
        batch_size=batch_size,
        selected=[report.ticker for report in selected_reports],
        remaining=[report.ticker for report in legacy[batch_size:]],
    )

    if dry_run:
        write_backfill_state(
            {
                "schema_version": 1,
                "updated_at": datetime.now(UTC).isoformat(),
                "dry_run": True,
                "legacy_count": len(legacy),
                "remaining": summary.remaining,
                "next_batch": summary.selected,
            },
            path=state_path,
        )
        return summary

    store = ResearchStore(output_dir)
    run_at = datetime.now(UTC)
    data_dir = committed_dir.parent if committed_dir.name == "research" else committed_dir

    for report in selected_reports:
        try:
            ensure_canonical_research_store(
                report.ticker,
                report.name,
                output_dir=data_dir,
                screening_snapshot=report.to_dict(),
                market=market,
                seed_if_missing=False,
            )
            ensure_canonical_research_store(
                report.ticker,
                report.name,
                output_dir=output_dir,
                screening_snapshot=report.to_dict(),
                market=market,
                seed_if_missing=False,
            )
            doc, action = _process_ticker(
                report=report,
                store=store,
                api_key=api_key,
                model=model,
                cwd=cwd,
                force_initial=True,
                run_at=run_at,
                market=market,
            )
            if action == "created":
                summary.created.append(report.ticker)
                logger.info("Re-memoed %s (bodies=%s)", report.ticker, doc.source_counts)
            else:
                summary.skipped.append(report.ticker)
        except Exception as exc:  # noqa: BLE001
            message = f"{report.ticker}: {exc}"
            logger.exception("Legacy re-memo failed for %s", report.ticker)
            summary.errors.append(message)

    if publish and summary.created:
        summary.published = publish_memo_backfill_batch(
            output_dir,
            dest_dir=dest_dir,
            latest_path=dest_dir / "data" / "latest.json",
            tickers=summary.created,
        )
    if rebuild_index and not summary.remaining:
        summary.published = rebuild_full_research_index(
            output_dir,
            committed_dir=committed_dir,
            dest_dir=dest_dir,
        )

    write_backfill_state(
        {
            "schema_version": 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "batch_size": batch_size,
            "legacy_before": len(legacy),
            "rememoed": summary.created,
            "skipped": summary.skipped,
            "errors": summary.errors,
            "remaining": summary.remaining,
            "published": summary.published,
            "complete": not summary.remaining and not summary.errors,
        },
        path=state_path,
    )
    return summary
