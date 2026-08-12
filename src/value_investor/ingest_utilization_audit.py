"""Buy-tier ingest fragment utilization vs screen, overlay, and paper gates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from value_investor.paper_fund import BUY_SIGNALS
from value_investor.research.gap_fill_sources import inspect_local_sources
from value_investor.scoring.fcf import (
    compute_yoy_growth_rate,
    extract_income_metrics_from_annual_financials,
    parse_adjusted_eps_growth_pct,
    parse_interim_eps_decline_pct,
)
from value_investor.storage import read_json, resolve_json_path

logger = logging.getLogger(__name__)

DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_RESEARCH_ROOT = Path("docs/data/research")
DEFAULT_MEMO_DIR = Path("docs/research")
DEFAULT_OUTPUT_PATH = Path("output/ingest_utilization_audit.json")

MetricSource = Literal["body", "yahoo", "none"]


@dataclass
class UtilizationRow:
    ticker: str
    name: str
    signal: str
    adjusted_signal: str | None
    filings_total: int
    filings_with_body: int
    indexed_without_body: int
    has_sources: bool
    has_memo: bool
    research_verdict: str | None
    research_confidence: float | None
    memo_quality_grade: str | None
    interim_eps_decline_pct: float | None
    interim_eps_source: MetricSource
    adjusted_eps_growth_pct: float | None
    adjusted_eps_source: MetricSource
    screen_uses_body_parser: bool
    ai_track_buy_eligible: bool
    thin_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "signal": self.signal,
            "adjusted_signal": self.adjusted_signal,
            "filings_total": self.filings_total,
            "filings_with_body": self.filings_with_body,
            "indexed_without_body": self.indexed_without_body,
            "has_sources": self.has_sources,
            "has_memo": self.has_memo,
            "research_verdict": self.research_verdict,
            "research_confidence": self.research_confidence,
            "memo_quality_grade": self.memo_quality_grade,
            "interim_eps_decline_pct": self.interim_eps_decline_pct,
            "interim_eps_source": self.interim_eps_source,
            "adjusted_eps_growth_pct": self.adjusted_eps_growth_pct,
            "adjusted_eps_source": self.adjusted_eps_source,
            "screen_uses_body_parser": self.screen_uses_body_parser,
            "ai_track_buy_eligible": self.ai_track_buy_eligible,
            "thin_sources": list(self.thin_sources),
        }


def _effective_buy_signal(signal: str, adjusted: str | None) -> str:
    if adjusted is not None and str(adjusted).strip():
        return str(adjusted)
    return signal


def _resolve_body_path(sources_dir: Path, body_path: str | None) -> Path | None:
    if not body_path:
        return None
    path = Path(body_path)
    if not path.is_absolute():
        path = sources_dir / "filings" / path
    if path.is_file():
        return path
    resolved = resolve_json_path(path)
    if resolved is not None and resolved.is_file():
        return resolved
    return None


def _read_filing_bodies(
    sources_dir: Path,
    *,
    periods: tuple[str, ...] = ("annual", "interim"),
) -> list[str]:
    index_path = resolve_json_path(sources_dir / "filings" / "filings_index.json")
    if index_path is None:
        return []
    try:
        payload = read_json(index_path)
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = [
        row
        for row in payload.get("filings") or []
        if isinstance(row, dict) and row.get("period") in periods and row.get("has_body")
    ]
    rows.sort(key=lambda row: str(row.get("published_at") or ""), reverse=True)
    bodies: list[str] = []
    for row in rows:
        body_path = _resolve_body_path(sources_dir, str(row.get("body_path") or ""))
        if body_path is None:
            continue
        try:
            bodies.append(body_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return bodies


def _read_latest_interim_body(sources_dir: Path) -> str | None:
    index_path = resolve_json_path(sources_dir / "filings" / "filings_index.json")
    if index_path is None:
        return None
    try:
        payload = read_json(index_path)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    interim_rows = [
        row
        for row in payload.get("filings") or []
        if isinstance(row, dict) and row.get("period") == "interim" and row.get("has_body")
    ]
    interim_rows.sort(key=lambda row: str(row.get("published_at") or ""), reverse=True)
    for row in interim_rows:
        body_path = _resolve_body_path(sources_dir, str(row.get("body_path") or ""))
        if body_path is None:
            continue
        try:
            return body_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None


def _load_financials_from_sources(sources_dir: Path) -> dict[str, Any] | None:
    path = resolve_json_path(sources_dir / "financials_annual.json")
    if path is None:
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def classify_interim_eps_source_for_dir(sources_dir: Path) -> MetricSource:
    body = _read_latest_interim_body(sources_dir)
    if body and parse_interim_eps_decline_pct(body) is not None:
        return "body"
    return "none"


def classify_adjusted_eps_growth_for_dir(
    sources_dir: Path,
) -> tuple[float | None, MetricSource]:
    for body in _read_filing_bodies(sources_dir):
        parsed = parse_adjusted_eps_growth_pct(body)
        if parsed is not None:
            return parsed, "body"
    financials = _load_financials_from_sources(sources_dir)
    if financials:
        income = extract_income_metrics_from_annual_financials(financials)
        yahoo_growth = compute_yoy_growth_rate(
            income.get("net_income_adjusted"),
            income.get("net_income_adjusted_prev"),
        )
        if yahoo_growth is not None:
            return yahoo_growth, "yahoo"
    return None, "none"


def classify_interim_eps_source(ticker: str) -> MetricSource:
    for root in (DEFAULT_RESEARCH_ROOT, Path("output/research")):
        sources_dir = root / ticker / "sources"
        if sources_dir.is_dir():
            return classify_interim_eps_source_for_dir(sources_dir)
    return "none"


def classify_adjusted_eps_growth(
    ticker: str,
) -> tuple[float | None, MetricSource]:
    for root in (DEFAULT_RESEARCH_ROOT, Path("output/research")):
        sources_dir = root / ticker / "sources"
        if sources_dir.is_dir():
            return classify_adjusted_eps_growth_for_dir(sources_dir)
    return None, "none"


def _load_latest_reports(latest_path: Path) -> list[dict[str, Any]]:
    if not latest_path.exists():
        return []
    try:
        payload = read_json(latest_path)
    except (OSError, ValueError, TypeError):
        return []
    return [row for row in payload.get("reports") or [] if isinstance(row, dict)]


def _load_research_index(latest_path: Path) -> dict[str, dict[str, Any]]:
    if not latest_path.exists():
        return {}
    try:
        payload = read_json(latest_path)
    except (OSError, ValueError, TypeError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("research") or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker:
            out[ticker] = row
    return out


def run_ingest_utilization_audit(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    memo_dir: Path = DEFAULT_MEMO_DIR,
) -> dict[str, Any]:
    """Build per-buy-tier utilization matrix from published screen + committed research stores."""
    reports = _load_latest_reports(latest_path)
    research_index = _load_research_index(latest_path)
    buy_tier = [
        row
        for row in reports
        if str(row.get("signal") or "") in BUY_SIGNALS
    ]

    rows: list[UtilizationRow] = []
    for row in buy_tier:
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        name = str(row.get("name") or "")
        signal = str(row.get("signal") or "")
        adjusted = row.get("adjusted_signal")
        adjusted_str = str(adjusted) if adjusted is not None else None

        sources_dir = research_root / ticker / "sources"
        has_sources = sources_dir.is_dir()
        inventory: dict[str, Any] = {}
        if has_sources:
            inventory = inspect_local_sources(sources_dir)
        filings_summary = dict(inventory.get("filings_summary") or {})
        filings_total = int(filings_summary.get("total") or 0)
        filings_with_body = int(
            filings_summary.get("with_body") or inventory.get("filings_indexed_bodies") or 0
        )
        indexed_without_body = max(0, filings_total - filings_with_body)

        memo_path = memo_dir / f"{ticker}.md"
        has_memo = memo_path.is_file() or ticker in research_index

        indexed = research_index.get(ticker) or {}
        memo_quality = indexed.get("memo_quality")
        grade: str | None = None
        if isinstance(memo_quality, dict) and memo_quality.get("grade"):
            grade = str(memo_quality.get("grade"))

        interim_src = (
            classify_interim_eps_source_for_dir(sources_dir)
            if has_sources
            else classify_interim_eps_source(ticker)
        )
        if has_sources:
            _, adjusted_src = classify_adjusted_eps_growth_for_dir(sources_dir)
        else:
            _, adjusted_src = classify_adjusted_eps_growth(ticker)

        report_interim = row.get("interim_eps_decline_pct")
        report_adjusted = row.get("adjusted_eps_growth_pct")

        effective = _effective_buy_signal(signal, adjusted_str)
        verdict = row.get("research_verdict")
        verdict_str = str(verdict) if verdict is not None else None
        ai_eligible = (
            effective in BUY_SIGNALS
            and verdict_str == "accumulate"
        )

        rows.append(
            UtilizationRow(
                ticker=ticker,
                name=name,
                signal=signal,
                adjusted_signal=adjusted_str,
                filings_total=filings_total,
                filings_with_body=filings_with_body,
                indexed_without_body=indexed_without_body,
                has_sources=has_sources,
                has_memo=has_memo,
                research_verdict=verdict_str,
                research_confidence=(
                    float(row.get("research_confidence"))
                    if row.get("research_confidence") is not None
                    else None
                ),
                memo_quality_grade=grade,
                interim_eps_decline_pct=(
                    float(report_interim) if report_interim is not None else None
                ),
                interim_eps_source=interim_src,
                adjusted_eps_growth_pct=(
                    float(report_adjusted) if report_adjusted is not None else None
                ),
                adjusted_eps_source=adjusted_src,
                screen_uses_body_parser=interim_src == "body" or adjusted_src == "body",
                ai_track_buy_eligible=ai_eligible,
                thin_sources=list(inventory.get("thin") or []),
            )
        )

    rows.sort(key=lambda item: (-item.indexed_without_body, item.ticker))

    with_memo = sum(1 for r in rows if r.has_memo)
    with_sources = sum(1 for r in rows if r.has_sources)
    with_body_gap = sum(1 for r in rows if r.indexed_without_body > 0)
    zero_body = sum(1 for r in rows if r.filings_with_body == 0)
    body_parser = sum(1 for r in rows if r.screen_uses_body_parser)
    ai_eligible = sum(1 for r in rows if r.ai_track_buy_eligible)
    interim_on_screen = sum(1 for r in rows if r.interim_eps_decline_pct is not None)
    interim_from_body = sum(1 for r in rows if r.interim_eps_source == "body")
    adjusted_on_screen = sum(1 for r in rows if r.adjusted_eps_growth_pct is not None)
    adjusted_from_body = sum(1 for r in rows if r.adjusted_eps_source == "body")
    adjusted_from_yahoo = sum(1 for r in rows if r.adjusted_eps_source == "yahoo")

    gap_tickers = [r.ticker for r in rows if r.indexed_without_body > 0]
    no_memo = [r.ticker for r in rows if not r.has_memo]
    ingest_only = [
        r.ticker
        for r in rows
        if r.has_sources and not r.has_memo
    ]

    generated_at = datetime.now(UTC).isoformat()
    try:
        latest_payload = read_json(latest_path)
        screen_run_at = latest_payload.get("run_at")
        screen_generated_at = latest_payload.get("generated_at")
    except (OSError, ValueError, TypeError):
        screen_run_at = None
        screen_generated_at = None

    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "screen_run_at": screen_run_at,
        "screen_generated_at": screen_generated_at,
        "latest_path": str(latest_path),
        "research_root": str(research_root),
        "summary": {
            "buy_tier_count": len(rows),
            "with_committed_sources": with_sources,
            "with_memo": with_memo,
            "without_memo": len(rows) - with_memo,
            "indexed_without_body_tickers": with_body_gap,
            "zero_body_tickers": zero_body,
            "screen_body_parser_users": body_parser,
            "ai_track_buy_eligible": ai_eligible,
            "interim_eps_on_screen": interim_on_screen,
            "interim_eps_from_body": interim_from_body,
            "adjusted_eps_on_screen": adjusted_on_screen,
            "adjusted_eps_from_body": adjusted_from_body,
            "adjusted_eps_from_yahoo": adjusted_from_yahoo,
        },
        "gap_tickers": gap_tickers,
        "no_memo_tickers": no_memo,
        "sources_without_memo_tickers": ingest_only,
        "rows": [row.to_dict() for row in rows],
    }


def write_ingest_utilization_audit(
    payload: dict[str, Any],
    path: Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def format_audit_summary(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "Buy-tier ingest utilization audit",
        f"  Screen bundle: {payload.get('screen_run_at')} (published {payload.get('screen_generated_at')})",
        f"  Buy-tier names: {summary.get('buy_tier_count')}",
        f"  Committed sources dir: {summary.get('with_committed_sources')}",
        f"  Published memos: {summary.get('with_memo')} (no memo: {summary.get('without_memo')})",
        f"  Indexed-without-body tickers: {summary.get('indexed_without_body_tickers')}",
        f"  Zero filing bodies: {summary.get('zero_body_tickers')}",
        f"  Screen filing-body parsers active: {summary.get('screen_body_parser_users')}",
        f"  AI-track accumulate eligible: {summary.get('ai_track_buy_eligible')}",
        (
            "  Interim EPS on screen: "
            f"{summary.get('interim_eps_on_screen')} "
            f"(body-sourced parsers: {summary.get('interim_eps_from_body')})"
        ),
        (
            "  Adjusted EPS on screen: "
            f"{summary.get('adjusted_eps_on_screen')} "
            f"(body: {summary.get('adjusted_eps_from_body')}, "
            f"yahoo: {summary.get('adjusted_eps_from_yahoo')})"
        ),
    ]
    gaps = payload.get("gap_tickers") or []
    if gaps:
        lines.append(f"  Body gaps: {', '.join(gaps)}")
    ingest_only = payload.get("sources_without_memo_tickers") or []
    if ingest_only:
        lines.append(
            f"  Ingested but no memo ({len(ingest_only)}): "
            + ", ".join(ingest_only[:12])
            + (" …" if len(ingest_only) > 12 else "")
        )
    return "\n".join(lines)
