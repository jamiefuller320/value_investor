"""Observe-only FTSE holdings ∪ buy-tier weekday decision-input inventory.

Pinned learning question: on the next weekday paper-auto / AI-judgment pass,
which FTSE held and buy-tier names still lack bound FCF basis, overlay bind,
or a sufficiently recent memo — is P1 still the bottleneck vs judgment on
rich inputs?

Steady-state utilization (not flip→usable lag). Does not rememo, deepen
ingest, or dispatch engineering. Persists
``docs/data/decision_input_inventory.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.buy_tier_flip_lag import (
    _index_meta,
    _research_doc_times,
)
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.storage import read_json, write_json

DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_RESEARCH_ROOT = Path("docs/data/research")
DEFAULT_MEMO_DIR = Path("docs/research")
DEFAULT_PAPER_FUND_PATH = Path(
    "docs/data/paper_automation/ai_judgment/automated_fund.json"
)
DEFAULT_STORE_PATH = Path("docs/data/decision_input_inventory.json")

SCHEMA_VERSION = 1
DEFAULT_MEMO_MAX_AGE_DAYS = 21
# Green-enough: dominant gap field has at most this many gaps (absolute).
DEFAULT_GREEN_ENOUGH_MAX_GAPS = 2
# Ops warn when dominant gap exceeds this count.
DEFAULT_WARN_MIN_GAPS = 3

LEARNING_QUESTION = (
    "On the next weekday paper-auto / AI-judgment pass, which FTSE held and "
    "buy-tier names still lack bound FCF basis, overlay bind, or sufficiently "
    "recent memo — is P1 still the bottleneck vs judgment on rich inputs?"
)

# Bind fields ranked by P1 decision impact (first wins ties).
BIND_FIELDS = (
    "key_filing_bodies",
    "fcf_basis_bound",
    "overlay_bound",
    "memo_recent",
)

VERDICT_GREEN = "P1 green-enough"


def _fcf_basis_bound(report: dict[str, Any]) -> bool:
    """True when the live report carries a boolean FCF basis overlay flag."""
    return isinstance(report.get("fcf_basis_overlay"), bool)


def _overlay_bound(report: dict[str, Any], *, research_verdict: str | None) -> bool:
    """True when research overlay is bound: verdict present and adjusted_signal set."""
    verdict = research_verdict or report.get("research_verdict")
    adjusted = report.get("adjusted_signal")
    return bool(str(verdict or "").strip()) and bool(str(adjusted or "").strip())


def load_paper_holdings(path: Path = DEFAULT_PAPER_FUND_PATH) -> set[str]:
    """Tickers held in the AI-judgment (primary) paper fund."""
    path = Path(path)
    if not path.exists():
        return set()
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    out: set[str] = set()
    for ticker in (payload.get("holdings") or {}).keys():
        token = str(ticker or "").strip().upper()
        if token:
            out.add(token)
    return out


def _load_latest_reports(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return []
    rows = payload.get("reports") or []
    return [row for row in rows if isinstance(row, dict)]


def _memo_age_days(
    memo_at: datetime | None,
    *,
    now: datetime,
) -> float | None:
    if memo_at is None:
        return None
    return round((now - memo_at).total_seconds() / 86400.0, 2)


@dataclass
class DecisionInputRow:
    ticker: str
    name: str
    in_buy_tier: bool
    in_holdings: bool
    signal: str
    adjusted_signal: str | None
    key_filing_bodies: bool
    fcf_basis_bound: bool
    overlay_bound: bool
    has_memo: bool
    memo_at: str | None
    memo_age_days: float | None
    memo_recent: bool
    research_verdict: str | None
    filings_total: int = 0
    filings_with_body: int = 0
    has_index: bool = False
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "in_buy_tier": self.in_buy_tier,
            "in_holdings": self.in_holdings,
            "signal": self.signal,
            "adjusted_signal": self.adjusted_signal,
            "key_filing_bodies": self.key_filing_bodies,
            "fcf_basis_bound": self.fcf_basis_bound,
            "overlay_bound": self.overlay_bound,
            "has_memo": self.has_memo,
            "memo_at": self.memo_at,
            "memo_age_days": self.memo_age_days,
            "memo_recent": self.memo_recent,
            "research_verdict": self.research_verdict,
            "filings_total": self.filings_total,
            "filings_with_body": self.filings_with_body,
            "has_index": self.has_index,
            "gaps": list(self.gaps),
        }


def snapshot_decision_input(
    report: dict[str, Any],
    *,
    holdings: set[str],
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    memo_max_age_days: float = DEFAULT_MEMO_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> DecisionInputRow | None:
    """Build one inventory row for a report in the holdings ∪ buy-tier universe."""
    now = now or datetime.now(UTC)
    ticker = str(report.get("ticker") or "").strip().upper()
    if not ticker:
        return None
    signal = str(report.get("signal") or "")
    in_buy_tier = signal in BUY_SIGNALS
    in_holdings = ticker in holdings
    if not in_buy_tier and not in_holdings:
        return None

    adjusted = report.get("adjusted_signal")
    adjusted_str = str(adjusted).strip() if adjusted is not None and str(adjusted).strip() else None

    index_meta = _index_meta(ticker, research_root=research_root)
    key_bodies = bool(index_meta.get("key_bodies"))
    fcf_bound = _fcf_basis_bound(report)

    has_disk_memo, memo_created, disk_verdict = _research_doc_times(
        ticker, research_root=research_root
    )
    memo_md = (Path(memo_dir) / f"{ticker}.md").is_file()
    has_memo = has_disk_memo or memo_md
    memo_at = memo_created
    age = _memo_age_days(memo_at, now=now)
    memo_recent = bool(
        has_memo and age is not None and age <= float(memo_max_age_days)
    )

    screen_verdict = report.get("research_verdict")
    verdict_str = (
        str(screen_verdict).strip()
        if screen_verdict is not None and str(screen_verdict).strip()
        else (str(disk_verdict).strip() if disk_verdict else None)
    )
    if verdict_str == "":
        verdict_str = None

    overlay = _overlay_bound(report, research_verdict=verdict_str)

    gaps: list[str] = []
    if not key_bodies:
        gaps.append("key_filing_bodies")
    if not fcf_bound:
        gaps.append("fcf_basis_bound")
    if not overlay:
        gaps.append("overlay_bound")
    if not memo_recent:
        gaps.append("memo_recent")

    return DecisionInputRow(
        ticker=ticker,
        name=str(report.get("name") or ""),
        in_buy_tier=in_buy_tier,
        in_holdings=in_holdings,
        signal=signal,
        adjusted_signal=adjusted_str,
        key_filing_bodies=key_bodies,
        fcf_basis_bound=fcf_bound,
        overlay_bound=overlay,
        has_memo=has_memo,
        memo_at=memo_at.isoformat() if memo_at else None,
        memo_age_days=age,
        memo_recent=memo_recent,
        research_verdict=verdict_str,
        filings_total=int(index_meta.get("filings_total") or 0),
        filings_with_body=int(index_meta.get("filings_with_body") or 0),
        has_index=bool(index_meta.get("has_index")),
        gaps=gaps,
    )


def _rollup(
    rows: list[DecisionInputRow],
    *,
    green_enough_max_gaps: int = DEFAULT_GREEN_ENOUGH_MAX_GAPS,
) -> dict[str, Any]:
    gap_counts: dict[str, int] = {name: 0 for name in BIND_FIELDS}
    for row in rows:
        if not row.key_filing_bodies:
            gap_counts["key_filing_bodies"] += 1
        if not row.fcf_basis_bound:
            gap_counts["fcf_basis_bound"] += 1
        if not row.overlay_bound:
            gap_counts["overlay_bound"] += 1
        if not row.memo_recent:
            gap_counts["memo_recent"] += 1

    n = len(rows)
    gap_rates = {
        name: (round(count / n, 4) if n else 0.0) for name, count in gap_counts.items()
    }

    # Prefer the P1-ranked field among those tied for the maximum gap count.
    max_gaps = max(gap_counts.values()) if gap_counts else 0
    dominant: str | None = None
    if max_gaps > 0:
        for name in BIND_FIELDS:
            if gap_counts[name] == max_gaps:
                dominant = name
                break

    if dominant is None or max_gaps <= int(green_enough_max_gaps):
        verdict = VERDICT_GREEN
        sunday_bind_field = VERDICT_GREEN
        note = (
            "Holdings ∪ buy-tier decision inputs look green-enough for P1; "
            "next bottleneck is likely judgment on already-rich inputs."
        )
    else:
        verdict = dominant
        sunday_bind_field = dominant
        note = (
            f"Dominant utilization gap is `{dominant}` "
            f"({gap_counts[dominant]} of {n} names) — still the bind field "
            "most likely to change Sunday decisions."
        )

    held = sum(1 for r in rows if r.in_holdings)
    buy_tier = sum(1 for r in rows if r.in_buy_tier)
    gapped = sum(1 for r in rows if r.gaps)
    fully_ready = sum(1 for r in rows if not r.gaps)

    return {
        "verdict": verdict,
        "sunday_bind_field": sunday_bind_field,
        "dominant_gap_field": dominant,
        "gap_counts": gap_counts,
        "gap_rates": gap_rates,
        "inventory_count": n,
        "held_count": held,
        "buy_tier_count": buy_tier,
        "names_with_any_gap": gapped,
        "fully_ready_count": fully_ready,
        "green_enough_max_gaps": int(green_enough_max_gaps),
        "note": note,
        "learning_question": LEARNING_QUESTION,
    }


def run_decision_input_inventory(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    paper_fund_path: Path = DEFAULT_PAPER_FUND_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
    memo_max_age_days: float = DEFAULT_MEMO_MAX_AGE_DAYS,
    green_enough_max_gaps: int = DEFAULT_GREEN_ENOUGH_MAX_GAPS,
    now: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Build holdings ∪ buy-tier decision-input inventory; optionally persist."""
    now = now or datetime.now(UTC)
    reports = _load_latest_reports(latest_path)
    holdings = load_paper_holdings(paper_fund_path)

    by_ticker: dict[str, dict[str, Any]] = {}
    for row in reports:
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker:
            by_ticker[ticker] = row

    # Include held names missing from the screen bundle as stubs.
    for ticker in holdings:
        if ticker not in by_ticker:
            by_ticker[ticker] = {"ticker": ticker, "name": "", "signal": "hold"}

    rows: list[DecisionInputRow] = []
    for report in by_ticker.values():
        snap = snapshot_decision_input(
            report,
            holdings=holdings,
            research_root=research_root,
            memo_dir=memo_dir,
            memo_max_age_days=memo_max_age_days,
            now=now,
        )
        if snap is not None:
            rows.append(snap)

    rows.sort(
        key=lambda r: (
            0 if r.gaps else 1,
            -len(r.gaps),
            0 if r.in_holdings else 1,
            r.ticker,
        )
    )

    rollup = _rollup(rows, green_enough_max_gaps=green_enough_max_gaps)
    gapped_tickers = [r.ticker for r in rows if r.gaps]

    try:
        latest_payload = read_json(latest_path) if Path(latest_path).exists() else {}
        screen_run_at = latest_payload.get("run_at") if isinstance(latest_payload, dict) else None
        screen_generated_at = (
            latest_payload.get("generated_at") if isinstance(latest_payload, dict) else None
        )
    except (OSError, ValueError, TypeError):
        screen_run_at = None
        screen_generated_at = None

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "observe_only": True,
        "not_flip_lag": True,
        "latest_path": str(latest_path),
        "research_root": str(research_root),
        "paper_fund_path": str(paper_fund_path),
        "memo_max_age_days": float(memo_max_age_days),
        "screen_run_at": screen_run_at,
        "screen_generated_at": screen_generated_at,
        "holdings": sorted(holdings),
        "summary": {
            "inventory_count": rollup["inventory_count"],
            "held_count": rollup["held_count"],
            "buy_tier_count": rollup["buy_tier_count"],
            "fully_ready_count": rollup["fully_ready_count"],
            "names_with_any_gap": rollup["names_with_any_gap"],
            "gap_counts": rollup["gap_counts"],
            "verdict": rollup["verdict"],
            "sunday_bind_field": rollup["sunday_bind_field"],
        },
        "rollup": rollup,
        "gapped_tickers": gapped_tickers,
        "rows": [row.to_dict() for row in rows],
    }

    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, compact=False)
    return payload


def format_decision_input_summary(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    rollup = payload.get("rollup") or {}
    lines = [
        "FTSE holdings ∪ buy-tier decision-input inventory (observe-only)",
        f"  Generated: {payload.get('generated_at')}",
        f"  Inventory: {summary.get('inventory_count')} "
        f"(held={summary.get('held_count')}, buy-tier={summary.get('buy_tier_count')})",
        f"  Fully ready: {summary.get('fully_ready_count')} "
        f"(any gap: {summary.get('names_with_any_gap')})",
        f"  Verdict / Sunday bind field: {summary.get('sunday_bind_field')}",
    ]
    gaps = summary.get("gap_counts") or {}
    if gaps:
        parts = [f"{k}={v}" for k, v in gaps.items()]
        lines.append(f"  Gap counts: {', '.join(parts)}")
    note = rollup.get("note")
    if note:
        lines.append(f"  Note: {note}")
    gapped = payload.get("gapped_tickers") or []
    if gapped:
        lines.append(
            "  Gapped: "
            + ", ".join(gapped[:16])
            + (" …" if len(gapped) > 16 else "")
        )
    return "\n".join(lines)


def ops_finding_from_decision_input_inventory(
    payload: dict[str, Any],
    *,
    warn_min_gaps: int = DEFAULT_WARN_MIN_GAPS,
) -> dict[str, Any] | None:
    """Ops warn when the dominant P1 bind gap is material; else None."""
    rollup = payload.get("rollup") or {}
    verdict = str(rollup.get("verdict") or summary_verdict(payload))
    if verdict == VERDICT_GREEN:
        return None
    gap_counts = dict(rollup.get("gap_counts") or {})
    dominant = str(rollup.get("dominant_gap_field") or verdict)
    count = int(gap_counts.get(dominant) or 0)
    if count < int(warn_min_gaps):
        return None
    n = int(rollup.get("inventory_count") or 0)
    gapped = list(payload.get("gapped_tickers") or [])
    bits = ", ".join(gapped[:10])
    extra = len(gapped) - 10
    summary = (
        f"Steady-state P1 decision-input gap on holdings ∪ buy-tier: "
        f"`{dominant}` missing on {count}/{n} names"
    )
    if bits:
        summary += f" (e.g. {bits}"
        if extra > 0:
            summary += f" +{extra} more"
        summary += ")"
    summary += (
        ". Observe-only — do not rememo/ingest burst from this alert; "
        "see docs/data/decision_input_inventory.json."
    )
    return {
        "severity": "warn",
        "category": "ingest",
        "title": "FTSE decision-input utilization gap",
        "summary": summary,
        "auto_fixable": False,
    }


def summary_verdict(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    return str(summary.get("verdict") or VERDICT_GREEN)


__all__ = [
    "BIND_FIELDS",
    "DEFAULT_GREEN_ENOUGH_MAX_GAPS",
    "DEFAULT_MEMO_MAX_AGE_DAYS",
    "DEFAULT_PAPER_FUND_PATH",
    "DEFAULT_STORE_PATH",
    "DEFAULT_WARN_MIN_GAPS",
    "LEARNING_QUESTION",
    "VERDICT_GREEN",
    "format_decision_input_summary",
    "load_paper_holdings",
    "ops_finding_from_decision_input_inventory",
    "run_decision_input_inventory",
    "snapshot_decision_input",
]
