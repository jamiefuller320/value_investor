"""Alternate-source inventory and seeking helpers for gap-fill research."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.research.filings import (
    extract_ir_presentation_metrics,
    fetch_filings_ir_allowlist,
    merge_ir_allowlist_filings,
    period_body_coverage,
    refetch_ir_allowlist_filing_bodies,
    refetch_missing_filing_bodies,
    refetch_uk_primary_filing_bodies,
)
from value_investor.research.ingest import (
    fetch_google_news_rss,
    fetch_google_news_rss_query,
    merge_news_articles,
)
from value_investor.storage import (
    COMMITTED_HISTORY_DIR,
    read_json,
    resolve_json_path,
    write_json,
)

logger = logging.getLogger(__name__)

# Evidence ladder the agent should walk before declaring unresolved.
EVIDENCE_LADDER = (
    "filings_bodies",
    "filings_index",
    "yahoo_financials",
    "yahoo_quarterly_cashflow",
    "news_manifest",
    "alternate_news",
    "screening_snapshot",
    "screen_run_manifest",
    "ir_presentation_metrics",
    "macro_context",
)

# Suggested next sources when local evidence is exhausted (by market flavour).
ALTERNATE_SOURCE_CATALOG: dict[str, list[dict[str, str]]] = {
    "uk": [
        {
            "id": "companies_house_accounts",
            "label": "Companies House filed accounts / annual report PDF",
            "why": (
                "RNS body extracts are often thin; filed PDF/iXBRL accounts hold consolidated "
                "statements plus pension, borrowings/covenant, cash-flow, and segment notes"
            ),
        },
        {
            "id": "company_ir_presentation",
            "label": "Company IR / results presentation PDF",
            "why": "Bridge tables for FCF, working capital, and segment margin often sit outside Yahoo",
        },
        {
            "id": "investegate_rns_full",
            "label": "Full Investegate / RNS HTML body re-pull",
            "why": "Index may list filings without downloadable bodies",
        },
    ],
    "us": [
        {
            "id": "sec_exhibits",
            "label": "SEC EDGAR 10-K/10-Q exhibits and MD&A deeper extract",
            "why": "Risk factors and liquidity notes may be truncated in short bodies",
        },
        {
            "id": "company_ir_presentation",
            "label": "Company IR earnings presentation",
            "why": "Non-GAAP reconciliations and FCF bridges",
        },
    ],
    "euro": [
        {
            "id": "investegate_rns_full",
            "label": "Full Investegate / RNS HTML body re-pull",
            "why": "Many Euro large-caps publish on Investegate; index may list filings without bodies",
        },
        {
            "id": "exchange_filings_full",
            "label": "Euronext / national register filing full-text re-pull",
            "why": "Euro memos often index headlines without bodies",
        },
        {
            "id": "company_ir_presentation",
            "label": "Company IR annual report / results deck PDF",
            "why": "ESEF/iXBRL and segment tables often missing from Yahoo",
        },
    ],
    "asia": [
        {
            "id": "exchange_filings_full",
            "label": "HKEX / SGX announcement full-text re-pull",
            "why": "Asia filing discovery is headline-only today",
        },
        {
            "id": "sec_exhibits",
            "label": "SEC 20-F / 6-K for dual-listed ADRs",
            "why": "US filings may hold richer English disclosures",
        },
    ],
    "tsx": [
        {
            "id": "exchange_filings_full",
            "label": "SEDAR+ / exchange filing full-text re-pull",
            "why": "Canadian announcements often lack downloaded bodies",
        },
        {
            "id": "company_ir_presentation",
            "label": "Company IR MD&A / results presentation",
            "why": "Cash-flow bridges and pension notes",
        },
    ],
    "asx": [
        {
            "id": "exchange_filings_full",
            "label": "ASX announcement full-text re-pull",
            "why": "ASX memos rely on Yahoo without announcement bodies",
        },
        {
            "id": "company_ir_presentation",
            "label": "Company IR results presentation",
            "why": "Segment and FCF detail beyond Yahoo",
        },
    ],
    "default": [
        {
            "id": "company_ir_presentation",
            "label": "Company IR / annual report PDF",
            "why": "Primary statements beyond Yahoo summaries",
        },
        {
            "id": "exchange_filings_full",
            "label": "Exchange filing full-text re-pull",
            "why": "Announcement index without body text",
        },
    ],
}


def _market_bucket(market: str | None, ticker: str) -> str:
    mid = (market or "").lower()
    if mid.startswith("ftse") or mid in {"aim"} or ticker.upper().endswith(".L"):
        return "uk"
    if mid in {"sp500", "nasdaq100", "us_adr_asia"} or "." not in ticker:
        return "us"
    if mid in {
        "euro_stoxx50",
        "dax",
        "cac40",
        "ibex35",
        "ftse_mib",
        "aex",
        "bel20",
        "atx",
        "psi20",
        "smi",
        "omxs30",
    }:
        return "euro"
    if mid in {"asx200", "asx"} or ticker.upper().endswith(".AX"):
        return "asx"
    if mid in {"tsx60", "tsx", "canada"} or ticker.upper().endswith(".TO"):
        return "tsx"
    if mid in {"hang_seng", "sti", "hk", "sgx", "asia"} or ticker.upper().endswith((".HK", ".SI")):
        return "asia"
    return "default"


def _yahoo_quarterly_cashflow_usable(sources_dir: Path) -> bool:
    """True when cached Yahoo financials include a usable quarterly cash-flow series."""
    from value_investor.research.ingest import quarterly_cashflow_has_usable_series

    financials_path = resolve_json_path(sources_dir / "financials_annual.json")
    if financials_path is None:
        return False
    try:
        payload = read_json(financials_path)
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    return quarterly_cashflow_has_usable_series(payload.get("quarterly_cashflow") or {})


def inspect_local_sources(sources_dir: Path) -> dict[str, Any]:
    """Summarise which local research sources are present and usable."""
    sources_dir = Path(sources_dir)
    filings_index = sources_dir / "filings" / "filings_index.json"
    bodies_dir = sources_dir / "filings" / "bodies"
    body_count = 0
    if bodies_dir.is_dir():
        body_count = sum(1 for path in bodies_dir.iterdir() if path.is_file())

    filings_summary: dict[str, Any] = {}
    period_coverage: dict[str, dict[str, int]] = {}
    resolved_index = resolve_json_path(filings_index)
    if resolved_index is not None:
        try:
            payload = read_json(resolved_index)
            filings_summary = dict(payload.get("summary") or {})
            period_coverage = period_body_coverage(list(payload.get("filings") or []))
            if period_coverage:
                filings_summary["period_coverage"] = period_coverage
        except (OSError, ValueError, TypeError):
            filings_summary = {}
            period_coverage = {}

    indexed_bodies = int(filings_summary.get("with_body") or 0)
    has_filing_bodies = indexed_bodies > 0 or body_count > 0

    news_count = 0
    news_path = resolve_json_path(sources_dir / "news_manifest.json")
    if news_path is not None:
        try:
            news_count = len(read_json(news_path).get("articles") or [])
        except (OSError, ValueError, TypeError):
            news_count = 0

    available = {
        "filings_index": resolved_index is not None,
        "filings_bodies": has_filing_bodies,
        "yahoo_financials": resolve_json_path(sources_dir / "financials_annual.json") is not None,
        "yahoo_quarterly_cashflow": _yahoo_quarterly_cashflow_usable(sources_dir),
        "news_manifest": news_count > 0,
        "screening_snapshot": resolve_json_path(sources_dir / "screening_snapshot.json")
        is not None,
        "screen_run_manifest": resolve_json_path(sources_dir / "screen_run_manifest.json")
        is not None,
        "ir_presentation_metrics": resolve_json_path(sources_dir / "ir_presentation_metrics.json")
        is not None,
        "macro_context": resolve_json_path(sources_dir / "macro_context.json") is not None,
        "alternate_news": resolve_json_path(sources_dir / "alternate_news.json") is not None,
    }
    thin = [key for key, ok in available.items() if not ok]
    return {
        "available": available,
        "thin": thin,
        "filings_body_files": body_count,
        "filings_indexed_bodies": indexed_bodies,
        "filings_summary": filings_summary,
        "period_coverage": period_coverage,
        "news_article_count": news_count,
        "evidence_ladder": list(EVIDENCE_LADDER),
    }


def suggest_alternate_sources(
    *,
    ticker: str,
    market: str | None,
    inventory: dict[str, Any],
    open_questions: list[str],
) -> list[dict[str, str]]:
    """Rank catalog alternatives based on what is locally thin and the questions asked."""
    bucket = _market_bucket(market, ticker)
    catalog = list(ALTERNATE_SOURCE_CATALOG.get(bucket) or [])
    catalog.extend(
        item
        for item in ALTERNATE_SOURCE_CATALOG["default"]
        if item["id"] not in {c["id"] for c in catalog}
    )

    question_blob = " ".join(open_questions).lower()
    thin = set(inventory.get("thin") or [])
    ranked: list[dict[str, str]] = []
    for item in catalog:
        score = 0
        if "filings_bodies" in thin and item["id"] in {
            "companies_house_accounts",
            "investegate_rns_full",
            "sec_exhibits",
            "exchange_filings_full",
            "company_ir_presentation",
        }:
            score += 3
        if any(token in question_blob for token in ("pension", "covenant", "going concern")):
            if item["id"] in {"companies_house_accounts", "sec_exhibits"}:
                score += 2
        if any(token in question_blob for token in ("fcf", "cash", "dividend", "working capital")):
            if item["id"] == "company_ir_presentation":
                score += 2
        if score == 0 and "filings_bodies" in thin:
            score = 1
        if score > 0:
            ranked.append({**item, "score": str(score)})
    ranked.sort(key=lambda row: int(row.get("score") or 0), reverse=True)
    return ranked[:5]


def fetch_alternate_gap_fill_news(
    company_name: str,
    ticker: str,
    *,
    max_items_per_query: int = 8,
    market: str | None = None,
) -> list[dict[str, Any]]:
    """Extra Google News RSS queries aimed at qualitative gap themes."""
    from value_investor.research.news_locale import resolve_news_locale

    locale = resolve_news_locale(market, ticker)
    symbol = ticker.replace(".L", "")
    base = fetch_google_news_rss(company_name, ticker, max_items=max_items_per_query, market=market)
    themed_queries = [
        f'"{company_name}" ("annual report" OR "full year" OR "interim results")',
        f'"{company_name}" (pension OR covenant OR "going concern" OR "working capital")',
        f'"{company_name}" OR {symbol} ("investor presentation" OR "capital markets day")',
    ]
    themed: list[dict[str, Any]] = []
    for query in themed_queries:
        themed.extend(
            fetch_google_news_rss_query(
                query,
                source_label="google_news_alternate",
                max_items=max_items_per_query,
                hl=locale["hl"],
                gl=locale["gl"],
                ceid=locale["ceid"],
            )
        )
    return merge_news_articles(base, themed)


DEFAULT_LATEST_SCREEN_PATH = Path("docs/data/latest.json")


def _latest_history_run_paths(history_dir: Path) -> tuple[Path, Path] | None:
    """Return paired (run_path, models_path) for the newest committed snapshot."""
    history_dir = Path(history_dir)
    if not history_dir.is_dir():
        return None
    run_paths = sorted(
        {
            *history_dir.glob("run_*.json.gz"),
            *history_dir.glob("run_*.json"),
        }
    )
    if not run_paths:
        return None
    run_path = run_paths[-1]
    if run_path.suffix == ".json" and run_path.with_suffix(".json.gz").exists():
        run_path = run_path.with_suffix(".json.gz")
    stamp = run_path.name.removeprefix("run_")
    models_gz = history_dir / f"models_{stamp}"
    models_plain = history_dir / f"models_{stamp.removesuffix('.gz')}"
    if models_gz.is_file():
        return run_path, models_gz
    if models_plain.is_file():
        return run_path, models_plain
    return None


def attach_screen_run_manifest(
    sources_dir: Path,
    ticker: str,
    *,
    market: str | None = None,
    history_dir: Path | None = None,
    latest_path: Path | None = None,
) -> dict[str, Any]:
    """
    Attach the latest FTSE350 screen run manifest slice for ``ticker``.

    Writes ``screen_run_manifest.json`` with universe-level signal counts and
    per-ticker signal/model rows from ``docs/data/history/run_*.json.gz`` and
    paired ``models_*.json.gz`` snapshots.
    """
    sources_dir = Path(sources_dir)
    bucket = _market_bucket(market, ticker)
    mid = (market or "").lower()
    if bucket != "uk" and not mid.startswith("ftse"):
        return {"attached": False, "reason": "not_ftse350"}

    paired = _latest_history_run_paths(history_dir or COMMITTED_HISTORY_DIR)
    if paired is None:
        return {"attached": False, "reason": "no_history_snapshots"}
    run_path, models_path = paired

    try:
        run_payload = read_json(run_path)
        models_payload = read_json(models_path)
    except (OSError, ValueError, TypeError) as exc:
        return {"attached": False, "reason": f"unreadable_snapshot: {exc}"}

    run_at = str(run_payload.get("run_at") or "")
    signals = list(run_payload.get("signals") or [])
    ticker_signal = next((row for row in signals if row.get("ticker") == ticker), None)
    ticker_models = [
        row for row in (models_payload.get("models") or []) if row.get("ticker") == ticker
    ]

    universe_meta: dict[str, Any] = {}
    latest_file = latest_path or DEFAULT_LATEST_SCREEN_PATH
    resolved_latest = resolve_json_path(latest_file)
    if resolved_latest is not None:
        try:
            latest_payload = read_json(resolved_latest)
            if str(latest_payload.get("run_at") or "") == run_at:
                universe_meta = dict(latest_payload.get("meta") or {})
        except (OSError, ValueError, TypeError):
            universe_meta = {}

    if not universe_meta and signals:
        counts: dict[str, int] = {}
        for row in signals:
            label = str(row.get("adjusted_signal") or row.get("signal") or "unknown")
            counts[label] = counts.get(label, 0) + 1
        universe_meta = {
            "company_count": len(signals),
            "signal_counts": counts,
            "universe": "ftse350",
        }

    manifest = {
        "ticker": ticker,
        "run_at": run_at,
        "attached_at": datetime.now(UTC).isoformat(),
        "history_run_path": str(run_path),
        "history_models_path": str(models_path),
        "universe_meta": universe_meta,
        "ticker_signal": ticker_signal,
        "ticker_models": ticker_models,
        "models_passed": sum(1 for row in ticker_models if row.get("passed")),
        "models_total": len(ticker_models),
    }
    manifest_path = sources_dir / "screen_run_manifest.json"
    write_json(manifest_path, manifest, compact=False, compress=False)
    manifest["attached"] = True
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def prepare_gap_fill_source_pack(
    *,
    ticker: str,
    company_name: str,
    sources_dir: Path,
    open_questions: list[str],
    market: str | None = None,
) -> dict[str, Any]:
    """
    Build a source map for the agent: inventory, alternate news pull, next-source plan.
    """
    sources_dir = Path(sources_dir)
    sources_dir.mkdir(parents=True, exist_ok=True)

    # Re-attempt PDF / direct RNS bodies before the agent answers.
    filings_dir = sources_dir / "filings"
    body_refetch = refetch_missing_filing_bodies(filings_dir)
    ch_refetch: dict[str, Any] = {}
    investegate_refetch: dict[str, Any] = {}
    ticker_rns_refetch: dict[str, Any] = {}
    if _market_bucket(market, ticker) == "uk":
        primary_refetch = refetch_uk_primary_filing_bodies(
            filings_dir,
            ticker=ticker,
            company_name=company_name,
            max_bodies=20,
        )
        ch_refetch = dict(primary_refetch.get("companies_house") or {})
        rns_refetch = dict(primary_refetch.get("rns") or {})
        investegate_refetch = dict(rns_refetch.get("investegate") or {})
        ticker_rns_refetch = dict(rns_refetch.get("ticker_rns") or {})
        if int(primary_refetch.get("fetched") or 0) > 0:
            body_refetch = primary_refetch
    ir_refetch: dict[str, Any] = {}
    ir_allowlist_rows = fetch_filings_ir_allowlist(ticker)
    if ir_allowlist_rows:
        ir_refetch = refetch_ir_allowlist_filing_bodies(
            filings_dir,
            ticker,
            company_name=company_name,
            max_bodies=20,
        )
        ir_refetch["mandatory"] = True
        ir_refetch["allowlist_count"] = len(ir_allowlist_rows)
        if int(ir_refetch.get("fetched") or 0) > 0:
            body_refetch = ir_refetch

    screen_run_manifest = attach_screen_run_manifest(
        sources_dir,
        ticker,
        market=market,
    )
    ir_presentation_metrics = extract_ir_presentation_metrics(
        filings_dir,
        ticker,
        sources_dir=sources_dir,
    )

    alternate_articles = fetch_alternate_gap_fill_news(company_name, ticker, market=market)
    alternate_path = sources_dir / "alternate_news.json"
    write_json(
        alternate_path,
        {
            "ticker": ticker,
            "fetched_at": datetime.now(UTC).isoformat(),
            "article_count": len(alternate_articles),
            "articles": alternate_articles,
        },
        compact=True,
        compress=False,
    )

    # Merge alternate headlines into the main news manifest when new.
    manifest_path = sources_dir / "news_manifest.json"
    resolved = resolve_json_path(manifest_path)
    if resolved is not None:
        try:
            manifest = read_json(resolved)
        except (OSError, ValueError, TypeError):
            manifest = {"articles": []}
    else:
        manifest = {"articles": []}
    known = {item.get("id") for item in manifest.get("articles") or []}
    merged = list(manifest.get("articles") or [])
    added = 0
    for article in alternate_articles:
        if article.get("id") in known:
            continue
        merged.append(article)
        known.add(article.get("id"))
        added += 1
    write_json(
        manifest_path,
        {
            "ticker": ticker,
            "updated_at": datetime.now(UTC).isoformat(),
            "articles": sorted(
                merged, key=lambda item: item.get("published_at") or "", reverse=True
            ),
        },
        compact=True,
        compress=False,
    )

    inventory = inspect_local_sources(sources_dir)
    planned = suggest_alternate_sources(
        ticker=ticker,
        market=market,
        inventory=inventory,
        open_questions=open_questions,
    )
    payload = {
        "ticker": ticker,
        "company_name": company_name,
        "market": market,
        "built_at": datetime.now(UTC).isoformat(),
        "inventory": inventory,
        "body_refetch": body_refetch,
        "ch_refetch": ch_refetch,
        "investegate_refetch": investegate_refetch,
        "ticker_rns_refetch": ticker_rns_refetch,
        "ir_refetch": ir_refetch,
        "screen_run_manifest": screen_run_manifest,
        "ir_presentation_metrics": {
            "bridge_count": ir_presentation_metrics.get("bridge_count", 0),
            "path": str(sources_dir / "ir_presentation_metrics.json"),
        },
        "alternate_news_added": added,
        "alternate_news_path": str(alternate_path),
        "planned_alternate_sources": planned,
        "evidence_ladder": list(EVIDENCE_LADDER),
        "instructions": (
            "Walk evidence_ladder in order. Cite what was tried. "
            "Prefer filings/bodies/*.txt when present. "
            "Use screen_run_manifest.json for universe-level signal counts and "
            "ir_presentation_metrics.json for presentation-grade FCF/dividend bridge lines. "
            "If still unresolved, pick from planned_alternate_sources and emit "
            "RESEARCH MODEL SUGGESTIONS for ingest/prompt/scoring improvements."
        ),
    }
    map_path = sources_dir / "gap_fill_source_map.json"
    write_json(map_path, payload, compact=False, compress=False)
    payload["source_map_path"] = str(map_path)
    return payload


def execute_planned_alternate_sources(
    *,
    ticker: str,
    company_name: str,
    sources_dir: Path,
    planned: list[dict[str, Any]],
    market: str | None = None,
    max_sources: int = 3,
) -> dict[str, Any]:
    """
      Execute top-ranked alternate source fetchers before a gap-fill retry.

      Re-ingests filings (Investegate/CH/SEC/IR) then refetches bodies. Stops
    when new bodies are downloaded or the planned list is exhausted.
    """
    from value_investor.research.filings import (
        ingest_filings,
        prune_orphaned_filing_bodies,
        refetch_missing_filing_bodies,
    )

    sources_dir = Path(sources_dir)
    filings_dir = sources_dir / "filings"
    sources_tried: list[str] = []
    last_refetch: dict[str, Any] = {}
    fetched_total = 0

    filing_fetcher_ids = {
        "companies_house_accounts",
        "investegate_rns_full",
        "exchange_filings_full",
        "sec_exhibits",
    }

    for item in planned[:max_sources]:
        source_id = str(item.get("id") or "").strip()
        if not source_id:
            continue
        sources_tried.append(source_id)
        if source_id == "company_ir_presentation":
            merge_ir_allowlist_filings(ticker, filings_dir)
            last_refetch = refetch_ir_allowlist_filing_bodies(
                filings_dir,
                ticker,
                company_name=company_name,
                max_bodies=20,
            )
            prune_orphaned_filing_bodies(filings_dir)
            fetched = int(last_refetch.get("fetched") or 0)
            fetched_total += fetched
            if fetched > 0:
                break
        elif source_id in filing_fetcher_ids:
            ingest_filings(
                ticker=ticker,
                company_name=company_name,
                sources_dir=sources_dir,
                market=market,
                deepen_history=True,
            )
            if _market_bucket(market, ticker) == "uk" and source_id == "companies_house_accounts":
                from value_investor.research.filings import refetch_companies_house_filing_bodies

                last_refetch = refetch_companies_house_filing_bodies(filings_dir, max_bodies=20)
            elif _market_bucket(market, ticker) == "uk" and source_id == "investegate_rns_full":
                from value_investor.research.filings import refetch_uk_primary_filing_bodies

                last_refetch = refetch_uk_primary_filing_bodies(
                    filings_dir,
                    ticker=ticker,
                    company_name=company_name,
                    max_bodies=20,
                )
            elif source_id == "investegate_rns_full":
                from value_investor.research.filings import refetch_investegate_filing_bodies

                last_refetch = refetch_investegate_filing_bodies(
                    filings_dir,
                    ticker=ticker,
                    company_name=company_name,
                    max_bodies=20,
                )
            else:
                last_refetch = refetch_missing_filing_bodies(filings_dir, max_bodies=20)
            prune_orphaned_filing_bodies(filings_dir)
            fetched = int(last_refetch.get("fetched") or 0)
            fetched_total += fetched
            if fetched > 0:
                break

    return {
        "sources_tried": sources_tried,
        "body_refetch": last_refetch,
        "fetched": fetched_total,
    }


# Minimum indexed filing bodies before the gap-fill deepen loop runs on memo paths.
THIN_FILINGS_BODY_THRESHOLD = 2


def deepen_thin_filings_if_needed(
    *,
    ticker: str,
    company_name: str,
    sources_dir: Path,
    market: str | None = None,
    filings_summary: dict[str, Any] | None = None,
    min_bodies: int = THIN_FILINGS_BODY_THRESHOLD,
    open_questions: list[str] | None = None,
) -> dict[str, Any]:
    """
    When filing bodies are thin, run the gap-fill alternate-source deepen loop.

    Used by memo create/update paths so ladder, repair, and weekly research share
    the same filing hardening as ``deepen-thin`` / gap-fill CLI.
    """
    sources_dir = Path(sources_dir)
    summary = dict(filings_summary or {})
    with_body = int(summary.get("with_body") or 0)
    if with_body >= min_bodies:
        return {
            "skipped": True,
            "reason": "sufficient_bodies",
            "with_body_before": with_body,
            "with_body_after": with_body,
        }

    questions = open_questions or [
        "Obtain annual and interim regulatory filing bodies for FINANCIAL REVIEW."
    ]
    source_pack = prepare_gap_fill_source_pack(
        ticker=ticker,
        company_name=company_name,
        sources_dir=sources_dir,
        open_questions=questions,
        market=market,
    )
    alternate = execute_planned_alternate_sources(
        ticker=ticker,
        company_name=company_name,
        sources_dir=sources_dir,
        planned=list(source_pack.get("planned_alternate_sources") or []),
        market=market,
    )

    filings_index = sources_dir / "filings" / "filings_index.json"
    after = with_body
    resolved = resolve_json_path(filings_index)
    if resolved is not None:
        try:
            after = int((read_json(resolved).get("summary") or {}).get("with_body") or 0)
        except (OSError, ValueError, TypeError):
            after = with_body

    return {
        "skipped": False,
        "with_body_before": with_body,
        "with_body_after": after,
        "improved": after > with_body,
        "alternate_sources": alternate,
        "source_pack": {
            "alternate_news_added": source_pack.get("alternate_news_added"),
            "planned_count": len(source_pack.get("planned_alternate_sources") or []),
        },
    }


_SUGGESTION_LINE = re.compile(
    r"^\s*[-*•]?\s*(?:area\s*[:=]\s*)?(?P<area>[a-z_]+)\s*[|;,]\s*"
    r"(?:priority\s*[:=]\s*)?(?P<priority>high|medium|low)\s*[|;,]\s*"
    r"(?:suggestion\s*[:=]\s*)?(?P<suggestion>.+?)\s*$",
    re.IGNORECASE,
)


def parse_model_suggestions(section_text: str) -> list[dict[str, str]]:
    """Parse RESEARCH MODEL SUGGESTIONS bullets into structured rows."""
    suggestions: list[dict[str, str]] = []
    for raw in (section_text or "").splitlines():
        line = raw.strip()
        if not line or line.upper().startswith("RESEARCH MODEL"):
            continue
        match = _SUGGESTION_LINE.match(line)
        if match:
            suggestions.append(
                {
                    "area": match.group("area").strip().lower(),
                    "priority": match.group("priority").strip().lower(),
                    "suggestion": match.group("suggestion").strip().rstrip(";"),
                }
            )
            continue
        # Fallback free-text bullet
        cleaned = re.sub(r"^[-*•]\s*", "", line).strip()
        if cleaned:
            suggestions.append(
                {
                    "area": "research",
                    "priority": "medium",
                    "suggestion": cleaned,
                }
            )
    return suggestions


def parse_question_outcomes(gap_fill_update: str) -> list[dict[str, str]]:
    """Extract Q/Status/Evidence/SourcesTried/NextSources blocks."""
    outcomes: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in (gap_fill_update or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("Q:"):
            if current.get("question"):
                outcomes.append(current)
            current = {"question": line[2:].strip()}
            continue
        if upper.startswith("STATUS:"):
            current["status"] = line.split(":", 1)[1].strip().lower()
            continue
        if upper.startswith("EVIDENCE:"):
            current["evidence"] = line.split(":", 1)[1].strip()
            continue
        if upper.startswith("SOURCESTRIED:") or upper.startswith("SOURCES TRIED:"):
            current["sources_tried"] = line.split(":", 1)[1].strip()
            continue
        if upper.startswith("NEXTSOURCES:") or upper.startswith("NEXT SOURCES:"):
            current["next_sources"] = line.split(":", 1)[1].strip()
            continue
    if current.get("question"):
        outcomes.append(current)
    return outcomes
