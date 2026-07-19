"""Alternate-source inventory and seeking helpers for gap-fill research."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.research.ingest import (
    fetch_google_news_rss,
    fetch_google_news_rss_query,
    merge_news_articles,
)
from value_investor.storage import read_json, resolve_json_path, write_json

logger = logging.getLogger(__name__)

# Evidence ladder the agent should walk before declaring unresolved.
EVIDENCE_LADDER = (
    "filings_bodies",
    "filings_index",
    "yahoo_financials",
    "news_manifest",
    "alternate_news",
    "screening_snapshot",
    "macro_context",
)

# Suggested next sources when local evidence is exhausted (by market flavour).
ALTERNATE_SOURCE_CATALOG: dict[str, list[dict[str, str]]] = {
    "uk": [
        {
            "id": "companies_house_accounts",
            "label": "Companies House filed accounts / annual report PDF",
            "why": "RNS body extracts are often thin; statutory accounts hold pensions, covenants, going-concern language",
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
    return "default"


def inspect_local_sources(sources_dir: Path) -> dict[str, Any]:
    """Summarise which local research sources are present and usable."""
    sources_dir = Path(sources_dir)
    filings_index = sources_dir / "filings" / "filings_index.json"
    bodies_dir = sources_dir / "filings" / "bodies"
    body_count = 0
    if bodies_dir.is_dir():
        body_count = sum(1 for path in bodies_dir.iterdir() if path.is_file())

    filings_summary: dict[str, Any] = {}
    resolved_index = resolve_json_path(filings_index)
    if resolved_index is not None:
        try:
            payload = read_json(resolved_index)
            filings_summary = dict(payload.get("summary") or {})
        except (OSError, ValueError, TypeError):
            filings_summary = {}

    news_count = 0
    news_path = resolve_json_path(sources_dir / "news_manifest.json")
    if news_path is not None:
        try:
            news_count = len((read_json(news_path).get("articles") or []))
        except (OSError, ValueError, TypeError):
            news_count = 0

    available = {
        "filings_index": resolved_index is not None,
        "filings_bodies": body_count > 0,
        "yahoo_financials": resolve_json_path(sources_dir / "financials_annual.json") is not None,
        "news_manifest": news_count > 0,
        "screening_snapshot": resolve_json_path(sources_dir / "screening_snapshot.json") is not None,
        "macro_context": resolve_json_path(sources_dir / "macro_context.json") is not None,
        "alternate_news": resolve_json_path(sources_dir / "alternate_news.json") is not None,
    }
    thin = [key for key, ok in available.items() if not ok]
    return {
        "available": available,
        "thin": thin,
        "filings_body_files": body_count,
        "filings_summary": filings_summary,
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
) -> list[dict[str, Any]]:
    """Extra Google News RSS queries aimed at qualitative gap themes."""
    symbol = ticker.replace(".L", "")
    base = fetch_google_news_rss(company_name, ticker, max_items=max_items_per_query)
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
            )
        )
    return merge_news_articles(base, themed)


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

    alternate_articles = fetch_alternate_gap_fill_news(company_name, ticker)
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
            "articles": sorted(merged, key=lambda item: item.get("published_at") or "", reverse=True),
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
        "alternate_news_added": added,
        "alternate_news_path": str(alternate_path),
        "planned_alternate_sources": planned,
        "evidence_ladder": list(EVIDENCE_LADDER),
        "instructions": (
            "Walk evidence_ladder in order. Cite what was tried. "
            "If still unresolved, pick from planned_alternate_sources and emit "
            "RESEARCH MODEL SUGGESTIONS for ingest/prompt/scoring improvements."
        ),
    }
    map_path = sources_dir / "gap_fill_source_map.json"
    write_json(map_path, payload, compact=False, compress=False)
    payload["source_map_path"] = str(map_path)
    return payload


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
