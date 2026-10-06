"""SEC companyfacts coverage and Yahoo FCF-basis divergence on US memos (L544).

Learning question: does SEC-filed OCF − capex agree with the Yahoo-derived
``filing_aligned`` basis that the FCF overlay reads on US names?

Observe-only. Daily ops-monitor scans US library memo trees, compares the
latest ``sources/sec_companyfacts.json`` period with the Yahoo
``financials_annual.json`` row for the same fiscal-year label, and writes
``docs/data/sec_companyfacts_coverage.json``. Never edits scoring, overlays,
books or memos. Hydration happens in library ingest maintenance and
``ingest_filings``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.research.market_store import committed_research_dir
from value_investor.research.sec_companyfacts import (
    DEFAULT_MAX_AGE_DAYS,
    US_SEC_MARKETS,
    companyfacts_source_age_days,
    load_companyfacts_source,
)
from value_investor.storage import read_json, resolve_json_path

DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_STORE_PATH = Path("docs/data/sec_companyfacts_coverage.json")
SCHEMA_VERSION = 1
# Same tolerance as the FCF basis majority policy (docs/ops/fcf-basis-bridges.md).
DIVERGENCE_THRESHOLD = 0.25
COVERAGE_TARGET = 0.8
# One or two definitional gaps (e.g. capitalised software in Yahoo capex) stay info.
DIVERGENCE_WARN_MIN_BUY_TIER = 3
BUY_TIER_SIGNALS = frozenset({"strong_buy", "buy"})
MAX_LISTED_ROWS = 25

LEARNING_QUESTION = (
    "Does SEC-filed OCF − capex agree with the Yahoo-derived filing_aligned FCF "
    "basis on US memo names?"
)
DIVERGENCE_FINDING_TITLE = "SEC filed FCF diverges from Yahoo basis on US buy-tier"
COVERAGE_FINDING_TITLE = "SEC companyfacts coverage below target on US memos"
STORE_FAILED_TITLE = "SEC companyfacts coverage observe failed"


def _memo_signal(ticker_dir: Path) -> str:
    try:
        payload = json.loads((ticker_dir / "research.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(payload.get("signal") or "") if isinstance(payload, dict) else ""


def _yahoo_filing_aligned(sources_dir: Path, year_label: str) -> float | None:
    from value_investor.scoring.fcf import _filing_aligned_fcf_from_year_rows

    resolved = resolve_json_path(sources_dir / "financials_annual.json")
    if resolved is None:
        return None
    try:
        financials = read_json(resolved)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(financials, dict):
        return None
    rows = (financials.get("cash_flow") or {}).get(year_label)
    if not isinstance(rows, dict):
        return None
    return _filing_aligned_fcf_from_year_rows(rows)


def divergence_ratio(sec_fcf: float, yahoo_fcf: float) -> float | None:
    scale = max(abs(sec_fcf), abs(yahoo_fcf))
    if scale <= 0:
        return None
    return abs(sec_fcf - yahoo_fcf) / scale


def ticker_row(ticker_dir: Path, *, now: datetime) -> dict[str, Any]:
    sources_dir = ticker_dir / "sources"
    row: dict[str, Any] = {"ticker": ticker_dir.name, "signal": _memo_signal(ticker_dir)}
    source = load_companyfacts_source(sources_dir)
    if not source:
        row["status"] = "missing"
        return row
    age = companyfacts_source_age_days(sources_dir, now=now)
    row["age_days"] = round(age, 1) if age is not None else None
    latest = source.get("latest") or {}
    sec_fcf = latest.get("free_cashflow")
    year_label = str(latest.get("fiscal_year_label") or "")
    row.update(
        {
            "status": "stale" if age is None or age >= DEFAULT_MAX_AGE_DAYS else "fresh",
            "period_end": latest.get("period_end"),
            "currency": latest.get("currency"),
            "sec_fcf": sec_fcf,
            "sec_filed": (latest.get("operating_cashflow") or {}).get("filed"),
        }
    )
    if sec_fcf is None or not year_label:
        row["comparison"] = "no_sec_fcf"
        return row
    yahoo_fcf = _yahoo_filing_aligned(sources_dir, year_label)
    row["yahoo_filing_aligned"] = yahoo_fcf
    if yahoo_fcf is None:
        row["comparison"] = "no_yahoo_year"
        return row
    ratio = divergence_ratio(float(sec_fcf), float(yahoo_fcf))
    row["divergence"] = round(ratio, 4) if ratio is not None else None
    row["comparison"] = (
        "diverged" if ratio is not None and ratio > DIVERGENCE_THRESHOLD else "agrees"
    )
    return row


def build_sec_companyfacts_coverage(
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    *,
    markets: tuple[str, ...] = US_SEC_MARKETS,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    by_market: dict[str, Any] = {}
    diverged: list[dict[str, Any]] = []
    for market_id in markets:
        research_dir = committed_research_dir(market_id, library_root=Path(library_root))
        if not research_dir.is_dir():
            continue
        rows = [
            ticker_row(ticker_dir, now=now)
            for ticker_dir in sorted(p for p in research_dir.iterdir() if p.is_dir())
            if (ticker_dir / "sources").is_dir()
        ]
        compared = [r for r in rows if r.get("comparison") in {"agrees", "diverged"}]
        market_diverged = [r for r in compared if r["comparison"] == "diverged"]
        by_market[market_id] = {
            "memos": len(rows),
            "with_companyfacts": sum(1 for r in rows if r["status"] != "missing"),
            "fresh": sum(1 for r in rows if r["status"] == "fresh"),
            "compared": len(compared),
            "diverged": len(market_diverged),
            "diverged_buy_tier": sum(
                1 for r in market_diverged if r.get("signal") in BUY_TIER_SIGNALS
            ),
        }
        diverged.extend({**r, "market_id": market_id} for r in market_diverged)

    memos = sum(m["memos"] for m in by_market.values())
    covered = sum(m["with_companyfacts"] for m in by_market.values())
    compared = sum(m["compared"] for m in by_market.values())
    diverged.sort(key=lambda r: -(r.get("divergence") or 0.0))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "learning_question": LEARNING_QUESTION,
        "observe_only": True,
        "method": {
            "divergence": "|sec − yahoo| / max(|sec|, |yahoo|) on the same fiscal-year label",
            "divergence_threshold": DIVERGENCE_THRESHOLD,
            "coverage_target": COVERAGE_TARGET,
            "fresh_within_days": DEFAULT_MAX_AGE_DAYS,
        },
        "summary": {
            "memos": memos,
            "with_companyfacts": covered,
            "coverage": round(covered / memos, 4) if memos else None,
            "compared": compared,
            "diverged": len(diverged),
            "diverged_share": round(len(diverged) / compared, 4) if compared else None,
            "diverged_buy_tier": sum(1 for r in diverged if r.get("signal") in BUY_TIER_SIGNALS),
        },
        "markets": by_market,
        "diverged": diverged[:MAX_LISTED_ROWS],
        "limitations": (
            "Yahoo capex can include capitalised software or intangibles while SEC capex "
            "here is PP&E only, so some divergence is definitional. Scoring still reads "
            "the Yahoo basis; this store is evidence for a promotion decision, not a fix."
        ),
    }


def refresh_sec_companyfacts_coverage(
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = build_sec_companyfacts_coverage(library_root, now=now)
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_findings_from_sec_companyfacts_coverage(payload: dict[str, Any]) -> list[dict[str, Any]]:
    summary = payload.get("summary") or {}
    findings: list[dict[str, Any]] = []
    buy_tier = [r for r in payload.get("diverged") or [] if r.get("signal") in BUY_TIER_SIGNALS]
    if buy_tier:
        listed = "; ".join(
            f"{r['ticker']} ({r.get('market_id')}) FY{str(r.get('period_end') or '')[:4]} "
            f"SEC {float(r['sec_fcf']) / 1e6:,.0f}M vs Yahoo "
            f"{float(r['yahoo_filing_aligned']) / 1e6:,.0f}M ({float(r['divergence']):.0%})"
            for r in buy_tier[:5]
        )
        findings.append(
            {
                "severity": (
                    "warn"
                    if int(summary.get("diverged_buy_tier") or len(buy_tier))
                    >= DIVERGENCE_WARN_MIN_BUY_TIER
                    else "info"
                ),
                "category": "research",
                "title": DIVERGENCE_FINDING_TITLE,
                "summary": (
                    f"{summary.get('diverged_buy_tier')} US buy-tier memo name(s) where SEC-filed "
                    f"OCF − capex differs from the Yahoo filing_aligned basis by "
                    f">{DIVERGENCE_THRESHOLD:.0%} ({summary.get('diverged')} of "
                    f"{summary.get('compared')} compared overall): {listed}. Observe-only: "
                    "memos cite sec_companyfacts.json; scoring still reads Yahoo. See "
                    "docs/ops/sec-companyfacts.md for the promotion gate."
                ),
                "auto_fixable": False,
            }
        )
    coverage = summary.get("coverage")
    if coverage is not None and coverage < COVERAGE_TARGET:
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": COVERAGE_FINDING_TITLE,
                "summary": (
                    f"{summary.get('with_companyfacts')} of {summary.get('memos')} US memo "
                    f"names have sec_companyfacts.json ({coverage:.0%}, target "
                    f"{COVERAGE_TARGET:.0%}). Library ingest maintenance hydrates up to 40 "
                    "names per US market per run; persisting after a week means the backfill "
                    "is not running or CIKs are unresolved. See docs/ops/sec-companyfacts.md."
                ),
                "auto_fixable": False,
            }
        )
    return findings
