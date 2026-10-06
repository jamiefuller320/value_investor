"""HKEX direct feed coverage on hang_seng memos (L543).

Learning question: does the HKEXnews direct feed give hang_seng buy-tier memos
a body-bearing latest annual and interim, where Google News discovery left
them thin or parked?

Observe-only. Daily ops-monitor reads committed ``filings_index.json`` for each
``.HK`` memo, counts ``hkex_direct`` rows / bodies by period, and writes
``docs/data/hkex_direct_coverage.json``. Never fetches, edits indexes, scoring
or books; hydration happens in ``ingest_filings`` and the library discovery
scan. A freshly re-ingested ``.HK`` index with zero ``hkex_direct`` rows is the
breakage signal (HKEXnews changed shape or the stock lookup failed).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.research.hkex_direct import SOURCE, is_hkex_ticker
from value_investor.research.market_store import committed_research_dir
from value_investor.storage import read_json, resolve_json_path

DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_STORE_PATH = Path("docs/data/hkex_direct_coverage.json")
SCHEMA_VERSION = 1
HKEX_MARKETS: tuple[str, ...] = ("hang_seng",)
BUY_TIER_SIGNALS = frozenset({"strong_buy", "buy"})
COVERAGE_TARGET = 0.8
# Re-ingested within this window yet no hkex_direct rows → feed suspected broken.
FRESH_INDEX_DAYS = 7
SILENT_WARN_MIN = 2
MAX_LISTED_ROWS = 25

LEARNING_QUESTION = (
    "Does the HKEXnews direct feed give hang_seng buy-tier memos a body-bearing "
    "latest annual and interim where Google News discovery left them thin?"
)
COVERAGE_FINDING_TITLE = "HKEX direct filings not yet on hang_seng buy-tier memos"
SILENT_FINDING_TITLE = "HKEX direct feed silent on freshly ingested hang_seng memos"
STORE_FAILED_TITLE = "HKEX direct coverage observe failed"


def _screen_buy_tier(library_root: Path, market_id: str) -> set[str] | None:
    from value_investor.library_ingest_loop import load_library_buy_tier_reports

    try:
        return {r.ticker for r in load_library_buy_tier_reports(library_root, market_id)}
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None


def _memo_signal(ticker_dir: Path) -> str:
    try:
        payload = json.loads((ticker_dir / "research.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(payload.get("signal") or "") if isinstance(payload, dict) else ""


def _load_index(ticker_dir: Path) -> dict[str, Any] | None:
    resolved = resolve_json_path(ticker_dir / "sources" / "filings" / "filings_index.json")
    if resolved is None:
        return None
    try:
        payload = read_json(resolved)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_ts(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def ticker_row(ticker_dir: Path, *, now: datetime) -> dict[str, Any]:
    row: dict[str, Any] = {"ticker": ticker_dir.name, "signal": _memo_signal(ticker_dir)}
    index = _load_index(ticker_dir)
    if index is None:
        row["status"] = "no_index"
        return row
    filings = [f for f in index.get("filings") or [] if isinstance(f, dict)]
    hkex = [f for f in filings if f.get("source") == SOURCE]
    with_body = [f for f in hkex if f.get("has_body")]
    fetched = _parse_ts(index.get("fetched_at"))
    latest_results = max(
        (
            str(f.get("published_at") or "")
            for f in hkex
            if f.get("period") in {"annual", "interim"}
        ),
        default="",
    )
    row.update(
        {
            "filings_total": len(filings),
            "filings_with_body": sum(1 for f in filings if f.get("has_body")),
            "hkex_rows": len(hkex),
            "hkex_with_body": len(with_body),
            "hkex_annual_body": any(f.get("period") == "annual" for f in with_body),
            "hkex_interim_body": any(f.get("period") == "interim" for f in with_body),
            "latest_hkex_results_at": latest_results[:10] or None,
            "index_fetched_at": fetched.isoformat() if fetched else None,
        }
    )
    if not hkex:
        fresh = fetched is not None and now - fetched <= timedelta(days=FRESH_INDEX_DAYS)
        # Discovery-scan merges also bump fetched_at; only a full ingest note proves
        # the HKEX branch ran.
        ingested = "HKEXnews" in str(index.get("note") or "")
        row["status"] = "silent" if fresh and ingested else "not_reingested"
    elif row["hkex_annual_body"] and row["hkex_interim_body"]:
        row["status"] = "covered"
    else:
        row["status"] = "partial"
    return row


def build_hkex_direct_coverage(
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    *,
    markets: tuple[str, ...] = HKEX_MARKETS,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    by_market: dict[str, Any] = {}
    listed: list[dict[str, Any]] = []
    for market_id in markets:
        research_dir = committed_research_dir(market_id, library_root=Path(library_root))
        if not research_dir.is_dir():
            continue
        rows = [
            ticker_row(ticker_dir, now=now)
            for ticker_dir in sorted(p for p in research_dir.iterdir() if p.is_dir())
            if is_hkex_ticker(ticker_dir.name)
        ]
        # Current screen shortlist, not the signal frozen into each memo.
        screen_buy = _screen_buy_tier(Path(library_root), market_id)
        for r in rows:
            r["buy_tier"] = (
                r["ticker"] in screen_buy
                if screen_buy is not None
                else r.get("signal") in BUY_TIER_SIGNALS
            )
        buy = [r for r in rows if r["buy_tier"]]
        counts = {
            status: sum(1 for r in buy if r.get("status") == status)
            for status in ("covered", "partial", "not_reingested", "silent", "no_index")
        }
        by_market[market_id] = {
            "memos": len(rows),
            "buy_tier": len(buy),
            "buy_tier_with_hkex": sum(1 for r in buy if int(r.get("hkex_rows") or 0) > 0),
            "buy_tier_covered": counts["covered"],
            "buy_tier_status": counts,
            "silent_all_signals": sum(1 for r in rows if r.get("status") == "silent"),
        }
        listed.extend({**r, "market_id": market_id} for r in rows if r.get("status") != "covered")

    buy_tier = sum(m["buy_tier"] for m in by_market.values())
    covered = sum(m["buy_tier_covered"] for m in by_market.values())
    listed.sort(
        key=lambda r: (
            0 if r.get("status") == "silent" else 1,
            0 if r.get("buy_tier") else 1,
            r["ticker"],
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "learning_question": LEARNING_QUESTION,
        "observe_only": True,
        "method": {
            "covered": "hkex_direct rows with bodies for both an annual and an interim period",
            "silent": (
                f"index fully re-ingested within {FRESH_INDEX_DAYS}d after the HKEX branch "
                "shipped, yet zero hkex_direct rows"
            ),
            "coverage_target": COVERAGE_TARGET,
        },
        "summary": {
            "buy_tier": buy_tier,
            "buy_tier_covered": covered,
            "buy_tier_coverage": round(covered / buy_tier, 4) if buy_tier else None,
            "buy_tier_with_hkex": sum(m["buy_tier_with_hkex"] for m in by_market.values()),
            "silent": sum(m["silent_all_signals"] for m in by_market.values()),
        },
        "markets": by_market,
        "not_covered": listed[:MAX_LISTED_ROWS],
        "limitations": (
            "Reads committed indexes only; names re-enter coverage as the ingest loop or "
            "discovery scan revisits them. Parked leftovers are released once when their "
            "fetch surface changes (source_surface on ingest_exhaustion.json)."
        ),
    }


def refresh_hkex_direct_coverage(
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = build_hkex_direct_coverage(library_root, now=now)
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_findings_from_hkex_direct_coverage(payload: dict[str, Any]) -> list[dict[str, Any]]:
    summary = payload.get("summary") or {}
    rows = payload.get("not_covered") or []
    findings: list[dict[str, Any]] = []
    silent = [r for r in rows if r.get("status") == "silent"]
    if silent:
        names = ", ".join(r["ticker"] for r in silent[:8])
        findings.append(
            {
                "severity": "warn" if len(silent) >= SILENT_WARN_MIN else "info",
                "category": "research",
                "title": SILENT_FINDING_TITLE,
                "summary": (
                    f"{len(silent)} .HK memo index(es) re-ingested in the last "
                    f"{FRESH_INDEX_DAYS}d carry no hkex_direct rows ({names}). HKEXnews "
                    "prefix.do / titleSearchServlet may have changed shape or the stock "
                    "lookup failed; hang_seng falls back to Google News headlines. See "
                    "docs/ops/hkex-direct-filings.md."
                ),
                "auto_fixable": False,
            }
        )
    coverage = summary.get("buy_tier_coverage")
    if coverage is not None and coverage < COVERAGE_TARGET:
        pending = [r["ticker"] for r in rows if r.get("buy_tier") and r.get("status") != "silent"]
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": COVERAGE_FINDING_TITLE,
                "summary": (
                    f"{summary.get('buy_tier_covered')} of {summary.get('buy_tier')} hang_seng "
                    f"buy-tier memos have HKEX annual + interim bodies ({coverage:.0%}, target "
                    f"{COVERAGE_TARGET:.0%}). Pending: {', '.join(pending[:10])}. Names fill as "
                    "the ingest loop re-ingests them; persisting past two weeks means targets "
                    "are not reaching these names. See docs/ops/hkex-direct-filings.md."
                ),
                "auto_fixable": False,
            }
        )
    return findings
