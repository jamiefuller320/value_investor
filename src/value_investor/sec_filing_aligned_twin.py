"""L546 observe twin: feed SEC companyfacts into US ``filing_aligned`` via reconcile_fcf.

Learning question: if SEC-filed OCF − PP&E capex replaced Yahoo annual cash-flow as
the US ``filing_aligned`` input to ``reconcile_fcf``, how often would policy FCF /
basis / mismatch flags change on buy-tier memos?

Observe-only (``influences_live=false``). Never edits live scoring, overlays,
paper books, or memos. Daily ops-monitor refreshes
``docs/data/sec_filing_aligned_twin.json``. Live Yahoo path stays the default
until a separate cold-start / epoch promotion.

Docs: ``docs/ops/sec-companyfacts.md``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.research.market_store import committed_research_dir
from value_investor.research.sec_companyfacts import (
    US_SEC_MARKETS,
    load_companyfacts_source,
)
from value_investor.scoring.fcf import (
    _filing_aligned_fcf_from_year_rows,
    compute_filing_aligned_fcf,
    reconcile_fcf,
)
from value_investor.sec_companyfacts_coverage import (
    BUY_TIER_SIGNALS,
    DIVERGENCE_THRESHOLD,
    divergence_ratio,
)
from value_investor.storage import read_json, resolve_json_path

DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_STORE_PATH = Path("docs/data/sec_filing_aligned_twin.json")
SCHEMA_VERSION = 1
MAX_LISTED_ROWS = 25
# Surface buy-tier policy flips; 1–2 stay info, ≥3 warn (same cadence as L544).
POLICY_DELTA_WARN_MIN_BUY_TIER = 3

LEARNING_QUESTION = (
    "If SEC companyfacts OCF − PP&E replaced Yahoo annual cash-flow as US "
    "filing_aligned in reconcile_fcf, how often would policy FCF / basis / "
    "mismatch flags change on buy-tier memos?"
)
EPOCH_ID = "sec-filing-aligned-twin-v0"
TWIN_FINDING_TITLE = "SEC filing_aligned twin would change reconcile_fcf policy on US buy-tier"
STORE_FAILED_TITLE = "SEC filing_aligned twin observe failed"


def _memo_signal(ticker_dir: Path) -> str:
    try:
        payload = json.loads((ticker_dir / "research.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(payload.get("signal") or "") if isinstance(payload, dict) else ""


def _load_financials(sources_dir: Path) -> dict[str, Any] | None:
    resolved = resolve_json_path(sources_dir / "financials_annual.json")
    if resolved is None:
        return None
    try:
        payload = read_json(resolved)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _yahoo_screen_ttm_stand_in(financials: dict[str, Any], year_label: str | None) -> float | None:
    """Library memos rarely keep live TTM; use Yahoo annual Free Cash Flow when present."""
    cash_flow = financials.get("cash_flow") or {}
    if not isinstance(cash_flow, dict) or not cash_flow:
        return None
    label = str(year_label) if year_label else None
    if not label:
        years = sorted((str(y) for y in cash_flow.keys()), reverse=True)
        label = years[0] if years else None
    if not label:
        return None
    rows = cash_flow.get(label)
    if not isinstance(rows, dict):
        return None
    for key in ("Free Cash Flow", "free_cashflow", "FCF"):
        value = rows.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        return number
    return None


def _bundle_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "filing_aligned": bundle.get("filing_aligned"),
        "filing_aligned_source": bundle.get("filing_aligned_source"),
        "canonical": bundle.get("canonical"),
        "policy_fcf": bundle.get("policy_fcf"),
        "policy_basis": bundle.get("policy_basis"),
        "source": bundle.get("source"),
        "fiscal_year": bundle.get("fiscal_year"),
        "currency": bundle.get("currency"),
        "filing_screen_mismatch": bool(bundle.get("filing_screen_mismatch")),
        "fcf_divergence_flagged": bool(bundle.get("fcf_divergence_flagged")),
        "divergence_flagged": bool(bundle.get("divergence_flagged")),
        "auto_policy_resolved": bool(bundle.get("auto_policy_resolved")),
    }


def _policy_changed(yahoo: dict[str, Any], sec: dict[str, Any]) -> bool:
    for key in ("policy_basis", "source"):
        if yahoo.get(key) != sec.get(key):
            return True
    for key in ("canonical", "policy_fcf", "filing_aligned"):
        left = yahoo.get(key)
        right = sec.get(key)
        if left is None and right is None:
            continue
        if left is None or right is None:
            return True
        if abs(float(left) - float(right)) > 1.0:  # ignore sub-dollar noise
            return True
    for key in ("filing_screen_mismatch", "fcf_divergence_flagged", "divergence_flagged"):
        if bool(yahoo.get(key)) != bool(sec.get(key)):
            return True
    return False


def sec_filing_aligned_from_source(source: dict[str, Any]) -> tuple[float | None, str | None, str]:
    """Return (sec_fcf, fiscal_year_label, currency) from companyfacts payload."""
    latest = source.get("latest") or {}
    if not isinstance(latest, dict):
        return None, None, "USD"
    sec_fcf = latest.get("free_cashflow")
    year_label = str(latest.get("fiscal_year_label") or "") or None
    currency = str(latest.get("currency") or "USD")
    if sec_fcf is None:
        return None, year_label, currency
    return float(sec_fcf), year_label, currency


def twin_row(ticker_dir: Path) -> dict[str, Any] | None:
    """Compare Yahoo vs SEC filing_aligned inside reconcile_fcf for one memo."""
    sources_dir = ticker_dir / "sources"
    if not sources_dir.is_dir():
        return None
    signal = _memo_signal(ticker_dir)
    companyfacts = load_companyfacts_source(sources_dir)
    if not companyfacts:
        return None
    sec_fcf, year_label, currency = sec_filing_aligned_from_source(companyfacts)
    if sec_fcf is None:
        return None
    financials = _load_financials(sources_dir)
    if not financials:
        return None
    yahoo_aligned = None
    if year_label:
        rows = (financials.get("cash_flow") or {}).get(year_label)
        if isinstance(rows, dict):
            yahoo_aligned = _filing_aligned_fcf_from_year_rows(rows)
    if yahoo_aligned is None:
        yahoo_aligned, yahoo_year = compute_filing_aligned_fcf(financials)
        year_label = year_label or yahoo_year
    if yahoo_aligned is None:
        return None

    screen_ttm = _yahoo_screen_ttm_stand_in(financials, year_label)
    yahoo_bundle = reconcile_fcf(
        screen_ttm=screen_ttm,
        financials=financials,
        filing_currency=currency,
    )
    sec_bundle = reconcile_fcf(
        screen_ttm=screen_ttm,
        financials=financials,
        filing_currency=currency,
        filing_aligned_override=sec_fcf,
        filing_aligned_source="sec_companyfacts",
        fiscal_year_override=year_label,
    )
    ratio = divergence_ratio(float(sec_fcf), float(yahoo_aligned))
    yahoo_summary = _bundle_summary(yahoo_bundle)
    sec_summary = _bundle_summary(sec_bundle)
    changed = _policy_changed(yahoo_summary, sec_summary)
    return {
        "ticker": ticker_dir.name,
        "signal": signal,
        "buy_tier": signal in BUY_TIER_SIGNALS,
        "fiscal_year_label": year_label,
        "currency": currency,
        "sec_fcf": sec_fcf,
        "yahoo_filing_aligned": yahoo_aligned,
        "divergence": round(ratio, 4) if ratio is not None else None,
        "raw_diverged": bool(ratio is not None and ratio > DIVERGENCE_THRESHOLD),
        "policy_changed": changed,
        "yahoo": yahoo_summary,
        "sec_twin": sec_summary,
        "influences_live": False,
    }


def build_sec_filing_aligned_twin(
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    *,
    markets: tuple[str, ...] = US_SEC_MARKETS,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    by_market: dict[str, Any] = {}
    for market_id in markets:
        research_dir = committed_research_dir(market_id, library_root=Path(library_root))
        if not research_dir.is_dir():
            continue
        market_rows: list[dict[str, Any]] = []
        for ticker_dir in sorted(p for p in research_dir.iterdir() if p.is_dir()):
            row = twin_row(ticker_dir)
            if row is None:
                continue
            row = {**row, "market_id": market_id}
            market_rows.append(row)
            rows.append(row)
        by_market[market_id] = {
            "compared": len(market_rows),
            "policy_changed": sum(1 for r in market_rows if r["policy_changed"]),
            "policy_changed_buy_tier": sum(
                1 for r in market_rows if r["policy_changed"] and r["buy_tier"]
            ),
            "raw_diverged_buy_tier": sum(
                1 for r in market_rows if r["raw_diverged"] and r["buy_tier"]
            ),
        }

    changed = [r for r in rows if r["policy_changed"]]
    changed_buy = [r for r in changed if r["buy_tier"]]
    changed.sort(
        key=lambda r: (
            0 if r["buy_tier"] else 1,
            -(r.get("divergence") or 0.0),
            r["ticker"],
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "epoch_id": EPOCH_ID,
        "learning_question": LEARNING_QUESTION,
        "observe_only": True,
        "influences_live": False,
        "method": {
            "yahoo_path": "reconcile_fcf with Yahoo annual cash-flow filing_aligned",
            "sec_twin_path": (
                "reconcile_fcf with filing_aligned_override=SEC companyfacts "
                "free_cashflow (OCF − PP&E)"
            ),
            "screen_ttm": "Yahoo annual Free Cash Flow stand-in when live TTM absent",
            "divergence_threshold": DIVERGENCE_THRESHOLD,
            "policy_delta_warn_min_buy_tier": POLICY_DELTA_WARN_MIN_BUY_TIER,
        },
        "summary": {
            "compared": len(rows),
            "policy_changed": len(changed),
            "policy_changed_buy_tier": len(changed_buy),
            "raw_diverged_buy_tier": sum(1 for r in rows if r["raw_diverged"] and r["buy_tier"]),
        },
        "markets": by_market,
        "policy_changed": changed[:MAX_LISTED_ROWS],
        "limitations": (
            "SEC capex is PP&E-tagged only; Yahoo CapEx can include software/intangibles. "
            "ADR unit/currency joins can inflate raw divergence. Twin does not rewrite live "
            "scoring, overlays, paper books, or memos (influences_live=false)."
        ),
    }


def refresh_sec_filing_aligned_twin(
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = build_sec_filing_aligned_twin(library_root, now=now)
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_findings_from_sec_filing_aligned_twin(payload: dict[str, Any]) -> list[dict[str, Any]]:
    summary = payload.get("summary") or {}
    buy_tier = [r for r in payload.get("policy_changed") or [] if r.get("buy_tier")]
    if not buy_tier:
        return []
    listed = "; ".join(
        f"{r['ticker']} ({r.get('market_id')}) "
        f"Yahoo {r.get('yahoo', {}).get('policy_basis')}/"
        f"{_short_fcf(r.get('yahoo', {}).get('policy_fcf'))} → "
        f"SEC {r.get('sec_twin', {}).get('policy_basis')}/"
        f"{_short_fcf(r.get('sec_twin', {}).get('policy_fcf'))}"
        for r in buy_tier[:5]
    )
    count = int(summary.get("policy_changed_buy_tier") or len(buy_tier))
    return [
        {
            "severity": "warn" if count >= POLICY_DELTA_WARN_MIN_BUY_TIER else "info",
            "category": "research",
            "title": TWIN_FINDING_TITLE,
            "summary": (
                f"{count} US buy-tier memo name(s) where feeding SEC companyfacts into "
                f"reconcile_fcf filing_aligned would change policy FCF/basis or mismatch "
                f"flags vs the live Yahoo path ({summary.get('policy_changed')} of "
                f"{summary.get('compared')} compared overall): {listed}. "
                f"Observe twin {payload.get('epoch_id')} "
                f"(influences_live=false); live scoring still reads Yahoo. See "
                "docs/ops/sec-companyfacts.md."
            ),
            "auto_fixable": False,
        }
    ]


def _short_fcf(value: Any) -> str:
    try:
        return f"{float(value) / 1e6:,.0f}M"
    except (TypeError, ValueError):
        return "?"
