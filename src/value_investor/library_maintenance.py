"""One-shot / CLI maintenance for offline multi-market libraries."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import (
    MARKET_REGISTRY,
    market_dir,
    refresh_metrics,
)
from value_investor.library_retention import (
    DEFAULT_MONTHLY_UNTIL_DAYS,
    DEFAULT_RETENTION_DAYS,
    dates_to_remove,
)
from value_investor.research.filings import ingest_filings
from value_investor.signal_stability import prune_signal_history_rows
from value_investor.storage import read_json

logger = logging.getLogger(__name__)

_SCREEN_DATED_GLOBS = (
    "signals_*.csv",
    "model_results_*.csv",
    "universe_*.csv",
    "summary_*.json",
    "summary_*.json.gz",
)
_HISTORY_DATED_GLOBS = (
    "run_*.json",
    "run_*.json.gz",
    "models_*.json",
    "models_*.json.gz",
)
_RUN_STAMP_RE = re.compile(r"_(\d{8}_\d{6})(?:\.[^.]+)*$")


def _run_stamp(path: Path) -> str | None:
    match = _RUN_STAMP_RE.search(path.name)
    return match.group(1) if match else None


def _stamp_date(stamp: str) -> date | None:
    try:
        return datetime.strptime(stamp[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _collect_screen_run_files(screen_dir: Path) -> dict[str, list[Path]]:
    stamped: dict[str, list[Path]] = {}
    if not screen_dir.exists():
        return stamped
    for pattern in _SCREEN_DATED_GLOBS:
        for path in screen_dir.glob(pattern):
            if not path.is_file() or path.name.startswith("latest"):
                continue
            stamp = _run_stamp(path)
            if stamp is None:
                continue
            stamped.setdefault(stamp, []).append(path)
    history_dir = screen_dir / "history"
    if history_dir.is_dir():
        for pattern in _HISTORY_DATED_GLOBS:
            for path in history_dir.glob(pattern):
                if not path.is_file():
                    continue
                stamp = _run_stamp(path)
                if stamp is None:
                    continue
                stamped.setdefault(stamp, []).append(path)
    return stamped


def _company_name_for_memo(ticker_dir: Path, ticker: str) -> str:
    research_path = ticker_dir / "research.json"
    if research_path.exists():
        try:
            payload = read_json(research_path)
        except (OSError, ValueError):
            payload = {}
        name = payload.get("name") or payload.get("company_name")
        if name:
            return str(name)

    index_path = ticker_dir / "sources" / "filings" / "filings_index.json"
    if index_path.exists():
        try:
            index = read_json(index_path)
        except (OSError, ValueError):
            index = {}
        name = index.get("company_name")
        if name:
            return str(name)

    snapshots = ticker_dir / "sources" / "snapshots"
    if snapshots.exists():
        latest = sorted(snapshots.glob("*.json"), reverse=True)
        if latest:
            try:
                snap = read_json(latest[0])
            except (OSError, ValueError):
                snap = {}
            name = snap.get("name") or snap.get("company_name")
            if name:
                return str(name)

    return ticker


def list_research_filings_targets(
    root: Path,
    markets: list[str],
    *,
    only_unsupported: bool = True,
) -> list[dict[str, Any]]:
    """Enumerate research memos whose filings index should be re-ingested."""
    targets: list[dict[str, Any]] = []
    for market_id in markets:
        research_root = market_dir(root, market_id) / "screen" / "research"
        if not research_root.exists():
            continue
        for ticker_dir in sorted(p for p in research_root.iterdir() if p.is_dir()):
            index_path = ticker_dir / "sources" / "filings" / "filings_index.json"
            regime = None
            if index_path.exists():
                try:
                    index = read_json(index_path)
                except (OSError, ValueError):
                    index = {}
                regime = index.get("regime") or index.get("status")
            if only_unsupported and regime not in {None, "unsupported"}:
                continue
            ticker = ticker_dir.name
            targets.append(
                {
                    "market": market_id,
                    "ticker": ticker,
                    "company_name": _company_name_for_memo(ticker_dir, ticker),
                    "sources_dir": ticker_dir / "sources",
                    "prior_regime": regime,
                }
            )
    return targets


def _simplified_company_name(name: str, ticker: str) -> str | None:
    """Shorter search label when a legal full name returns zero news hits."""
    text = (name or "").strip()
    if not text:
        return None
    simplified = text
    # Leading corporate prefixes (Euro/French listings often need the core brand).
    for prefix in ("Compagnie de ", "Compagnie ", "The "):
        if simplified.startswith(prefix):
            simplified = simplified[len(prefix) :]
            break
    # Drop common legal suffixes / punctuation noise.
    for token in (
        " S.A.",
        " SA",
        " SE",
        " NV",
        " N.V.",
        " plc",
        " PLC",
        " Limited",
        " Ltd.",
        " Ltd",
        " Corporation",
        " Corp.",
        " Inc.",
        " Inc",
        " Group",
    ):
        simplified = simplified.replace(token, " ")
    simplified = " ".join(simplified.split()).strip(" ,.-")
    if not simplified or simplified.lower() == text.lower():
        # Fall back to first two words of the original.
        parts = text.replace(",", " ").split()
        simplified = " ".join(parts[:2]).strip() if parts else ""
    if not simplified or simplified.lower() == text.lower():
        return None
    if simplified.upper() == ticker.upper():
        return None
    return simplified


def reingest_research_filings(
    root: Path,
    markets: list[str],
    *,
    only_unsupported: bool = True,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Re-run ``ingest_filings`` for existing research memos.

    Used to backfill ASX / Euro regimes written before those sources existed.
    """
    targets = list_research_filings_targets(
        root, markets, only_unsupported=only_unsupported
    )
    results: list[dict[str, Any]] = []
    for target in targets:
        company_name = target["company_name"]
        meta = ingest_filings(
            ticker=target["ticker"],
            company_name=company_name,
            sources_dir=target["sources_dir"],
            api_key=api_key,
            market=target["market"],
        )
        summary = meta.get("filings_summary") or {}
        used_name = company_name
        if int(summary.get("total") or 0) == 0:
            alt = _simplified_company_name(company_name, target["ticker"])
            if alt:
                meta = ingest_filings(
                    ticker=target["ticker"],
                    company_name=alt,
                    sources_dir=target["sources_dir"],
                    api_key=api_key,
                    market=target["market"],
                )
                summary = meta.get("filings_summary") or {}
                used_name = alt
        results.append(
            {
                "market": target["market"],
                "ticker": target["ticker"],
                "prior_regime": target["prior_regime"],
                "regime": meta.get("filings_regime"),
                "company_name_used": used_name,
                "filings_total": summary.get("total", 0),
                "with_body": summary.get("with_body", 0),
            }
        )
        logger.info(
            "Re-ingested filings %s/%s → regime=%s total=%s",
            target["market"],
            target["ticker"],
            meta.get("filings_regime"),
            summary.get("total", 0),
        )
    return {
        "markets": list(markets),
        "only_unsupported": only_unsupported,
        "target_count": len(targets),
        "results": results,
    }


def list_failed_metric_tickers(root: Path, market_id: str) -> list[str]:
    """Tickers in latest metrics that still carry fetch errors."""
    path = market_dir(root, market_id) / "metrics" / "latest.json.gz"
    alt = market_dir(root, market_id) / "metrics" / "latest.json"
    metrics_path = path if path.exists() else alt
    if not metrics_path.exists():
        return []
    rows = read_json(metrics_path)
    return [
        str(row["ticker"])
        for row in rows
        if row.get("ticker") and row.get("errors")
    ]


def retry_failed_metrics(
    root: Path,
    markets: list[str],
    *,
    fetch_fn=None,
) -> list[dict[str, Any]]:
    """Re-fetch every metrics row that currently has errors."""
    summaries: list[dict[str, Any]] = []
    for market_id in markets:
        if market_id not in MARKET_REGISTRY:
            raise ValueError(f"Unknown market {market_id!r}")
        failed = list_failed_metric_tickers(root, market_id)
        if not failed:
            summaries.append(
                {
                    "market": market_id,
                    "selected": [],
                    "updated": 0,
                    "errors": 0,
                    "still_failed": [],
                }
            )
            continue
        result = refresh_metrics(
            root,
            market_id,
            max_tickers=len(failed),
            only_tickers=failed,
            fetch_fn=fetch_fn,
        )
        still = list_failed_metric_tickers(root, market_id)
        result["still_failed"] = still
        summaries.append(result)
        logger.info(
            "Retried failed metrics %s: %d selected, %d still failed",
            market_id,
            len(failed),
            len(still),
        )
    return summaries


def prune_screen_dir(
    screen_dir: Path,
    *,
    keep_days: int = DEFAULT_RETENTION_DAYS,
    monthly_until_days: int = DEFAULT_MONTHLY_UNTIL_DAYS,
    now: datetime | date | None = None,
    prune_signal_history: bool = True,
) -> dict[str, Any]:
    """
    Apply decreasing-resolution retention to one market's screen-lite artifacts.

    Dated run groups (``signals_*``, ``universe_*``, ``summary_*``, ``history/*``)
    use the same dense → monthly → quarterly policy as fundamentals PIT snapshots.
    ``latest_*`` is never removed. ``signal_history.csv`` rows are thinned on the
    same cadence when ``prune_signal_history`` is true.
    """
    screen_dir = Path(screen_dir)
    stamped = _collect_screen_run_files(screen_dir)
    dated_stamps: list[tuple[str, date]] = []
    for stamp in stamped:
        stamp_day = _stamp_date(stamp)
        if stamp_day is not None:
            dated_stamps.append((stamp, stamp_day))

    drop_stamps = dates_to_remove(
        dated_stamps,
        keep_days=keep_days,
        monthly_until_days=monthly_until_days,
        now=now,
    )
    removed_screen = 0
    removed_history = 0
    for stamp in drop_stamps:
        for path in stamped.get(stamp, []):
            path.unlink(missing_ok=True)
            if path.parent.name == "history":
                removed_history += 1
            else:
                removed_screen += 1

    history_stats = {"removed_rows": 0, "removed_runs": 0}
    if prune_signal_history:
        history_stats = prune_signal_history_rows(
            screen_dir,
            keep_days=keep_days,
            monthly_until_days=monthly_until_days,
            now=now,
        )

    return {
        "screen_removed": removed_screen,
        "history_removed": removed_history,
        "runs_removed": len(drop_stamps),
        "signal_history_rows_removed": int(history_stats.get("removed_rows") or 0),
        "signal_history_runs_removed": int(history_stats.get("removed_runs") or 0),
        "removed": removed_screen + removed_history,
    }


def prune_library_screen_history(
    root: Path,
    markets: list[str] | None = None,
    *,
    keep_days: int = DEFAULT_RETENTION_DAYS,
    monthly_until_days: int = DEFAULT_MONTHLY_UNTIL_DAYS,
    now: datetime | date | None = None,
    prune_signal_history: bool = True,
) -> dict[str, Any]:
    """
    Prune dated screen-lite history under each market's ``screen/``.

    Same decreasing-resolution policy as fundamentals PIT retention. Always keeps
    ``latest_*``; thins ``signal_history.csv`` rows on the same schedule.
    """
    selected = markets or [mid for mid in MARKET_REGISTRY if mid != "ftse350"]
    per_market: dict[str, dict[str, int]] = {}
    total_removed = 0
    total_history_rows = 0
    for market_id in selected:
        screen_dir = market_dir(root, market_id) / "screen"
        if not screen_dir.exists():
            continue
        counts = prune_screen_dir(
            screen_dir,
            keep_days=keep_days,
            monthly_until_days=monthly_until_days,
            now=now,
            prune_signal_history=prune_signal_history,
        )
        per_market[market_id] = counts
        total_removed += int(counts.get("removed") or 0)
        total_history_rows += int(counts.get("signal_history_rows_removed") or 0)
    return {
        "keep_days": keep_days,
        "monthly_until_days": monthly_until_days,
        "markets": selected,
        "total_removed": total_removed,
        "total_signal_history_rows_removed": total_history_rows,
        "per_market": per_market,
    }


def _filings_body_count(sources_dir: Path) -> int:
    index_path = sources_dir / "filings" / "filings_index.json"
    if not index_path.exists():
        return 0
    try:
        index = read_json(index_path)
    except (OSError, ValueError, TypeError):
        return 0
    return int((index.get("summary") or {}).get("with_body") or 0)


def _memo_updated_date(ticker_dir: Path) -> str | None:
    memo = ticker_dir / "research.md"
    if not memo.exists():
        return None
    match = re.search(r"Updated (\d{4}-\d{2}-\d{2})", memo.read_text(encoding="utf-8", errors="ignore"))
    return match.group(1) if match else None


def _memo_quality_flags(ticker_dir: Path) -> dict[str, bool]:
    memo = ticker_dir / "research.md"
    if not memo.exists():
        return {"yahoo_only": False, "sec_collision": False}
    text = memo.read_text(encoding="utf-8", errors="ignore")
    yahoo_only = bool(
        re.search(
            r"no primary regulatory filings|all financial figures below from Yahoo|"
            r"Yahoo.*only|not available in the research library|not usable for Vinci",
            text,
            flags=re.I,
        )
    )
    sec_collision = bool(
        re.search(r"ticker collision|Dollar General Corporation \(NYSE: DG\)", text, flags=re.I)
        or ("Dollar General" in text and "Vinci" in text)
    )
    return {"yahoo_only": yahoo_only, "sec_collision": sec_collision}


def list_batch1_repair_targets(
    root: Path,
    *,
    batch_date: str = "2026-07-25",
    markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Memos from a given batch date that need source repair or re-memo."""
    selected = markets or [mid for mid in MARKET_REGISTRY if mid != "ftse350"]
    targets: list[dict[str, Any]] = []
    for market_id in selected:
        research_root = market_dir(root, market_id) / "screen" / "research"
        if not research_root.exists():
            continue
        for ticker_dir in sorted(p for p in research_root.iterdir() if p.is_dir()):
            updated = _memo_updated_date(ticker_dir)
            if updated != batch_date:
                continue
            flags = _memo_quality_flags(ticker_dir)
            reasons: list[str] = []
            if flags["sec_collision"]:
                reasons.append("sec_collision")
            if flags["yahoo_only"]:
                reasons.append("yahoo_only")
            if ticker_dir.name.upper().endswith(".L"):
                reasons.append("uk_library")
            if market_id in {"asx200", "hang_seng", "sti"}:
                reasons.append("asia_pacific_gap")
            if not reasons:
                reasons.append("batch_refresh")
            targets.append(
                {
                    "market": market_id,
                    "ticker": ticker_dir.name,
                    "company_name": _company_name_for_memo(ticker_dir, ticker_dir.name),
                    "sources_dir": ticker_dir / "sources",
                    "screen_dir": market_dir(root, market_id) / "screen",
                    "reasons": reasons,
                    "updated": updated,
                }
            )
    return targets


def list_thin_library_memos(
    root: Path,
    *,
    markets: list[str] | None = None,
    max_with_body: int = 0,
) -> list[dict[str, Any]]:
    """
    Library memos with thin filing coverage (no indexed bodies by default).

    Used by ``deepen-thin`` maintenance to re-ingest and optionally gap-fill.
    """
    selected = markets or [mid for mid in MARKET_REGISTRY if mid != "ftse350"]
    targets: list[dict[str, Any]] = []
    for market_id in selected:
        research_root = market_dir(root, market_id) / "screen" / "research"
        if not research_root.exists():
            continue
        for ticker_dir in sorted(p for p in research_root.iterdir() if p.is_dir()):
            sources_dir = ticker_dir / "sources"
            bodies = _filings_body_count(sources_dir)
            if bodies > max_with_body:
                continue
            ticker = ticker_dir.name
            targets.append(
                {
                    "market": market_id,
                    "ticker": ticker,
                    "company_name": _company_name_for_memo(ticker_dir, ticker),
                    "sources_dir": sources_dir,
                    "screen_dir": market_dir(root, market_id) / "screen",
                    "bodies_before": bodies,
                    "reasons": ["thin_filings"],
                }
            )
    return targets


def deepen_library_research_memos(
    root: Path,
    targets: list[dict[str, Any]],
    *,
    api_key: str | None = None,
    model: str = "composer-2.5",
    rememo_when_improved: bool = True,
) -> dict[str, Any]:
    """
    Re-ingest filings and run the gap-fill source deepen loop for thin library memos.

    Re-memos when filing bodies increase after ingest + alternate-source retry.
    """
    from datetime import UTC, datetime

    from value_investor.research.gap_fill_sources import (
        execute_planned_alternate_sources,
        prepare_gap_fill_source_pack,
    )
    from value_investor.research.runner import _process_ticker
    from value_investor.research.store import ResearchStore

    results: list[dict[str, Any]] = []
    rememoed = 0
    deepened = 0
    errors: list[str] = []

    for target in targets:
        market = str(target["market"])
        ticker = str(target["ticker"])
        company_name = str(target.get("company_name") or ticker)
        sources_dir = Path(target["sources_dir"])
        screen_dir = Path(target["screen_dir"])
        before_bodies = int(target.get("bodies_before") or _filings_body_count(sources_dir))
        row: dict[str, Any] = {
            "market": market,
            "ticker": ticker,
            "reasons": list(target.get("reasons") or ["thin_filings"]),
            "bodies_before": before_bodies,
        }
        try:
            meta = ingest_filings(
                ticker=ticker,
                company_name=company_name,
                sources_dir=sources_dir,
                api_key=api_key,
                market=market,
                deepen_history=True,
            )
            row["bodies_after_ingest"] = int((meta.get("filings_summary") or {}).get("with_body") or 0)

            source_pack = prepare_gap_fill_source_pack(
                ticker=ticker,
                company_name=company_name,
                sources_dir=sources_dir,
                open_questions=[
                    "Obtain annual and interim regulatory filing bodies for FINANCIAL REVIEW."
                ],
                market=market,
            )
            planned = list(source_pack.get("planned_alternate_sources") or [])
            row["alternate_sources"] = execute_planned_alternate_sources(
                ticker=ticker,
                company_name=company_name,
                sources_dir=sources_dir,
                planned=planned,
                market=market,
            )
            after_bodies = _filings_body_count(sources_dir)
            row["bodies_after"] = after_bodies
            improved = after_bodies > before_bodies
            row["improved"] = improved
            if improved:
                deepened += 1

            should_rememo = rememo_when_improved and improved
            row["rememo"] = should_rememo
            if should_rememo:
                if not api_key:
                    raise RuntimeError("CURSOR API key required for re-memo after deepen")
                snapshot_path = sources_dir / "screening_snapshot.json"
                if not snapshot_path.exists():
                    raise FileNotFoundError(f"missing screening_snapshot for {market}/{ticker}")
                snapshot = read_json(snapshot_path)
                report = _company_report_from_snapshot(snapshot)
                store = ResearchStore(screen_dir)
                doc, action = _process_ticker(
                    report=report,
                    store=store,
                    api_key=api_key,
                    model=model,
                    cwd=None,
                    force_initial=True,
                    run_at=datetime.now(UTC),
                    market=market,
                )
                row["rememo_action"] = action
                row["rememo_version"] = doc.version
                rememoed += 1
        except Exception as exc:  # noqa: BLE001
            message = f"{market}/{ticker}: {exc}"
            logger.exception("Deepen failed for %s", message)
            errors.append(message)
            row["error"] = str(exc)
        results.append(row)

    return {
        "target_count": len(targets),
        "deepened": deepened,
        "rememoed": rememoed,
        "errors": errors,
        "results": results,
    }


def _company_report_from_snapshot(snapshot: dict[str, Any]) -> Any:
    from value_investor.summary import CompanyReport

    return CompanyReport(
        ticker=str(snapshot["ticker"]),
        name=str(snapshot.get("name") or snapshot["ticker"]),
        sector=snapshot.get("sector"),
        signal=str(snapshot.get("signal") or "buy"),
        models_passed=int(snapshot.get("models_passed") or 0),
        model_count=int(snapshot.get("model_count") or 0),
        composite_score=snapshot.get("composite_score"),
        sector_composite_score=snapshot.get("sector_composite_score"),
        families_passed=int(snapshot.get("families_passed") or 0),
        passed_families=snapshot.get("passed_families"),
        data_quality_score=float(snapshot.get("data_quality_score") or 0),
        metrics_present=int(snapshot.get("metrics_present") or 0),
        metrics_total=int(snapshot.get("metrics_total") or 0),
        weeks_at_signal=int(snapshot.get("weeks_at_signal") or 0),
        signal_trend=str(snapshot.get("signal_trend") or "stable"),
        conviction_score=float(snapshot.get("conviction_score") or 0),
        stability_label=str(snapshot.get("stability_label") or "building"),
        timing_signal=str(snapshot.get("timing_signal") or "insufficient_data"),
        timing_score=float(snapshot.get("timing_score") or 0),
        rsi_14=snapshot.get("rsi_14"),
        price_vs_sma200_pct=snapshot.get("price_vs_sma200_pct"),
        action_note=str(snapshot.get("action_note") or ""),
        trade_plan=None,
        summary=str(snapshot.get("summary") or ""),
        passed_models=list(snapshot.get("passed_models") or []),
        key_metrics=dict(snapshot.get("key_metrics") or {}),
        adjusted_signal=snapshot.get("adjusted_signal"),
        research_verdict=snapshot.get("research_verdict"),
        research_risk_level=snapshot.get("research_risk_level"),
        research_confidence=snapshot.get("research_confidence"),
        research_rationale=snapshot.get("research_rationale"),
    )


def repair_library_research_memos(
    root: Path,
    targets: list[dict[str, Any]],
    *,
    api_key: str,
    model: str = "composer-2.5",
    deepen_history: bool = True,
    rememo_all: bool = False,
) -> dict[str, Any]:
    """
    Re-ingest filings (and optionally re-memo) for library research tickers.

    Re-memos when ``rememo_all`` is true, sources improved (more bodies), or the
    target was flagged (SEC collision, yahoo-only, UK library gap).
    """
    from datetime import UTC, datetime

    from value_investor.research.runner import _process_ticker
    from value_investor.research.store import ResearchStore

    results: list[dict[str, Any]] = []
    rememoed = 0
    skipped_rememo = 0
    errors: list[str] = []

    for target in targets:
        market = str(target["market"])
        ticker = str(target["ticker"])
        company_name = str(target.get("company_name") or ticker)
        sources_dir = Path(target["sources_dir"])
        screen_dir = Path(target["screen_dir"])
        reasons = list(target.get("reasons") or [])
        before_bodies = _filings_body_count(sources_dir)
        row: dict[str, Any] = {
            "market": market,
            "ticker": ticker,
            "reasons": reasons,
            "bodies_before": before_bodies,
        }
        try:
            meta = ingest_filings(
                ticker=ticker,
                company_name=company_name,
                sources_dir=sources_dir,
                api_key=api_key,
                market=market,
                deepen_history=deepen_history,
            )
            after_bodies = int((meta.get("filings_summary") or {}).get("with_body") or 0)
            row["bodies_after"] = after_bodies
            row["filings_total"] = int((meta.get("filings_summary") or {}).get("total") or 0)
            row["regime"] = meta.get("filings_regime")
            should_rememo = rememo_all or bool(
                {"sec_collision", "yahoo_only", "uk_library", "asia_pacific_gap"} & set(reasons)
            ) or (after_bodies > before_bodies)
            row["rememo"] = should_rememo
            if should_rememo:
                snapshot_path = sources_dir / "screening_snapshot.json"
                if not snapshot_path.exists():
                    raise FileNotFoundError(f"missing screening_snapshot for {market}/{ticker}")
                snapshot = read_json(snapshot_path)
                report = _company_report_from_snapshot(snapshot)
                store = ResearchStore(screen_dir)
                doc, action = _process_ticker(
                    report=report,
                    store=store,
                    api_key=api_key,
                    model=model,
                    cwd=None,
                    force_initial=True,
                    run_at=datetime.now(UTC),
                    market=market,
                )
                row["rememo_action"] = action
                row["rememo_version"] = doc.version
                rememoed += 1
            else:
                skipped_rememo += 1
        except Exception as exc:  # noqa: BLE001
            message = f"{market}/{ticker}: {exc}"
            logger.exception("Repair failed for %s", message)
            errors.append(message)
            row["error"] = str(exc)
        results.append(row)

    return {
        "target_count": len(targets),
        "rememoed": rememoed,
        "skipped_rememo": skipped_rememo,
        "errors": errors,
        "results": results,
    }
