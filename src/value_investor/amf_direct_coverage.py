"""AMF open-data feed coverage on French euro memos (L545).

Learning question: does the AMF regulated-information feed (France OAM,
``info-financiere.gouv.fr``) give French buy-tier memos a body-bearing latest
annual and interim, where ESEF + Google News discovery left them thin or parked?

Observe-only. Daily ops-monitor reads committed ``filings_index.json`` for each
``.PA`` / French-LEI memo across the ``euro_filings`` markets, counts
``amf_direct`` rows / bodies by period, and writes
``docs/data/amf_direct_coverage.json``. Never fetches, edits indexes, scoring or
books; hydration happens in ``ingest_filings`` and the library discovery scan.
A freshly re-ingested index with zero ``amf_direct`` rows is the breakage
signal (Opendatasoft dataset renamed / schema changed).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.research.amf_direct import SOURCE, amf_eligible
from value_investor.research.market_store import committed_research_dir
from value_investor.storage import read_json, resolve_json_path

DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_STORE_PATH = Path("docs/data/amf_direct_coverage.json")
SCHEMA_VERSION = 1
AMF_MARKETS: tuple[str, ...] = ("cac40", "euro_stoxx50", "euro_depth", "aex", "bel20")
BUY_TIER_SIGNALS = frozenset({"strong_buy", "buy"})
COVERAGE_TARGET = 0.8
# Re-ingested within this window yet no amf_direct rows → feed suspected broken.
FRESH_INDEX_DAYS = 7
SILENT_WARN_MIN = 2
MAX_LISTED_ROWS = 25
# Present in the euro_filings ingest note only once the AMF branch shipped.
INGEST_NOTE_MARKER = "AMF open data"

LEARNING_QUESTION = (
    "Does the AMF open-data feed (France OAM) give French buy-tier memos a "
    "body-bearing latest annual and interim where ESEF + Google News left them thin?"
)
COVERAGE_FINDING_TITLE = "AMF direct filings not yet on French buy-tier memos"
SILENT_FINDING_TITLE = "AMF direct feed silent on freshly ingested French memos"
STORE_FAILED_TITLE = "AMF direct coverage observe failed"


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
    amf = [f for f in filings if f.get("source") == SOURCE]
    with_body = [f for f in amf if f.get("has_body")]
    fetched = _parse_ts(index.get("fetched_at"))
    latest_results = max(
        (str(f.get("published_at") or "") for f in amf if f.get("period") in {"annual", "interim"}),
        default="",
    )
    row.update(
        {
            "filings_total": len(filings),
            "filings_with_body": sum(1 for f in filings if f.get("has_body")),
            "amf_rows": len(amf),
            "amf_with_body": len(with_body),
            "amf_annual_body": any(f.get("period") == "annual" for f in with_body),
            "amf_interim_body": any(f.get("period") == "interim" for f in with_body),
            "latest_amf_results_at": latest_results[:10] or None,
            "index_fetched_at": fetched.isoformat() if fetched else None,
        }
    )
    if not amf:
        fresh = fetched is not None and now - fetched <= timedelta(days=FRESH_INDEX_DAYS)
        # Discovery-scan merges also bump fetched_at; only a full ingest note proves
        # the AMF branch ran.
        ingested = INGEST_NOTE_MARKER in str(index.get("note") or "")
        row["status"] = "silent" if fresh and ingested else "not_reingested"
    elif row["amf_annual_body"] and row["amf_interim_body"]:
        row["status"] = "covered"
    else:
        row["status"] = "partial"
    return row


def build_amf_direct_coverage(
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    *,
    markets: tuple[str, ...] = AMF_MARKETS,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    by_market: dict[str, Any] = {}
    listed: list[dict[str, Any]] = []
    # A name can sit in several euro markets; the summary counts it once.
    buy_status: dict[str, str] = {}
    buy_with_amf: set[str] = set()
    silent_tickers: set[str] = set()
    for market_id in markets:
        research_dir = committed_research_dir(market_id, library_root=Path(library_root))
        if not research_dir.is_dir():
            continue
        rows = [
            ticker_row(ticker_dir, now=now)
            for ticker_dir in sorted(p for p in research_dir.iterdir() if p.is_dir())
            if amf_eligible(ticker_dir.name)
        ]
        if not rows:
            continue
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
            "buy_tier_with_amf": sum(1 for r in buy if int(r.get("amf_rows") or 0) > 0),
            "buy_tier_covered": counts["covered"],
            "buy_tier_status": counts,
            "silent_all_signals": sum(1 for r in rows if r.get("status") == "silent"),
        }
        for r in buy:
            buy_status.setdefault(r["ticker"], str(r.get("status") or ""))
            if int(r.get("amf_rows") or 0) > 0:
                buy_with_amf.add(r["ticker"])
        silent_tickers.update(r["ticker"] for r in rows if r.get("status") == "silent")
        listed.extend({**r, "market_id": market_id} for r in rows if r.get("status") != "covered")

    buy_tier = len(buy_status)
    covered = sum(1 for status in buy_status.values() if status == "covered")
    listed.sort(
        key=lambda r: (
            0 if r.get("status") == "silent" else 1,
            0 if r.get("buy_tier") else 1,
            r["ticker"],
            r["market_id"],
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "learning_question": LEARNING_QUESTION,
        "observe_only": True,
        "method": {
            "covered": "amf_direct rows with bodies for both an annual and an interim period",
            "silent": (
                f"index fully re-ingested within {FRESH_INDEX_DAYS}d after the AMF branch "
                "shipped, yet zero amf_direct rows"
            ),
            "eligible": ".PA tickers (AMF ticker) and cached French LEIs",
            "coverage_target": COVERAGE_TARGET,
        },
        "summary": {
            "buy_tier": buy_tier,
            "buy_tier_covered": covered,
            "buy_tier_coverage": round(covered / buy_tier, 4) if buy_tier else None,
            "buy_tier_with_amf": len(buy_with_amf),
            "silent": len(silent_tickers),
        },
        "markets": by_market,
        "not_covered": listed[:MAX_LISTED_ROWS],
        "limitations": (
            "Reads committed indexes only; names re-enter coverage as the ingest loop or "
            "discovery scan revisits them. Parked leftovers are released once when their "
            "fetch surface changes (source_surface on ingest_exhaustion.json). Full annual "
            "reports (URD) are ESEF packages and land via esef_direct, so the AMF annual "
            "body is usually the full-year results release."
        ),
    }


def refresh_amf_direct_coverage(
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = build_amf_direct_coverage(library_root, now=now)
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_findings_from_amf_direct_coverage(payload: dict[str, Any]) -> list[dict[str, Any]]:
    summary = payload.get("summary") or {}
    rows = payload.get("not_covered") or []
    findings: list[dict[str, Any]] = []
    silent = sorted({r["ticker"] for r in rows if r.get("status") == "silent"})
    if silent:
        names = ", ".join(silent[:8])
        findings.append(
            {
                "severity": "warn" if len(silent) >= SILENT_WARN_MIN else "info",
                "category": "research",
                "title": SILENT_FINDING_TITLE,
                "summary": (
                    f"{len(silent)} French memo index(es) re-ingested in the last "
                    f"{FRESH_INDEX_DAYS}d carry no amf_direct rows ({names}). The "
                    "info-financiere.gouv.fr flux-amf-new-prod dataset may have been "
                    "renamed or changed schema; French names fall back to ESEF + Google "
                    "News. See docs/ops/amf-direct-filings.md."
                ),
                "auto_fixable": False,
            }
        )
    coverage = summary.get("buy_tier_coverage")
    if coverage is not None and coverage < COVERAGE_TARGET:
        pending = sorted(
            {r["ticker"] for r in rows if r.get("buy_tier") and r.get("status") != "silent"}
        )
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": COVERAGE_FINDING_TITLE,
                "summary": (
                    f"{summary.get('buy_tier_covered')} of {summary.get('buy_tier')} French "
                    f"buy-tier memos have AMF annual + interim bodies ({coverage:.0%}, target "
                    f"{COVERAGE_TARGET:.0%}). Pending: {', '.join(pending[:10])}. Names fill as "
                    "the ingest loop re-ingests them; persisting past two weeks means targets "
                    "are not reaching these names. See docs/ops/amf-direct-filings.md."
                ),
                "auto_fixable": False,
            }
        )
    return findings
