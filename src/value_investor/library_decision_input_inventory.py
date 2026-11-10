"""Observe-only F9-B input-quality binds for graduated library buy-tier names.

Learning question: for every buy-tier name in every graduated library market,
are the four binds true (filing bodies, FCF basis, overlay, memo recency),
computed from that name's research folder and library screen with the same
meanings as the FTSE inventory, and which binds are the gaps?

Report-only. Does not rememo, ingest, or change the FTSE inventory.
Persists ``docs/data/library_decision_input_inventory.json``.
"""

from __future__ import annotations

import csv
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.buy_tier_flip_lag import _index_meta, _parse_dt, _research_doc_times
from value_investor.decision_input_inventory import (
    BIND_FIELDS,
    DEFAULT_MEMO_MAX_AGE_DAYS,
    _memo_age_days,
    _overlay_bound,
)
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.scoring.fcf import (
    compute_filing_aligned_fcf,
    fcf_basis_divergence_flagged,
    fcf_filing_screen_mismatch,
)
from value_investor.storage import read_json, write_json

DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_MARKET_STATUS_PATH = Path("docs/data/market_status.json")
DEFAULT_STORE_PATH = Path("docs/data/library_decision_input_inventory.json")

SCHEMA_VERSION = 1
FINDING_TITLE = "Library decision-input binds (observe)"
STORE_FAILED_TITLE = "Library decision-input binds observe failed"

LEARNING_QUESTION = (
    "For every buy-tier name in every graduated library market, are the four "
    "F9-B binds true, computed from that name's research folder and library "
    "screen with the same meanings as the FTSE inventory, and which binds are the gaps?"
)

# Stated library meaning of fcf_basis_bound. The FTSE inventory treats a boolean
# fcf_basis_overlay as "the divergence check was evaluated". Library screens do
# not store that flag, so this module evaluates the same check from the folder.
LIBRARY_FCF_DEFINITION = (
    "Library screens do not store fcf_basis_overlay. The free-cash-flow bind is "
    "true only when the same divergence check the live screen records as that "
    "boolean can be evaluated. Evaluation needs a numeric screen free_cashflow "
    "from the point-in-time screen, and a filing-side free cash flow from "
    "sources/financials_annual.json (operating cash flow plus capital expenditure, "
    "otherwise the reported Free Cash Flow line), otherwise "
    "sources/sec_companyfacts.json latest.free_cashflow, otherwise a resolved "
    "sources/fcf_bridge.json with a numeric company-adjusted or policy figure. "
    "Each file counts only when it carries a timestamp on or before the as-of "
    "date. The evaluated yes/no is stored as fcf_basis_overlay. A missing side "
    "leaves the bind false and fcf_basis_overlay null. A true or false overlay "
    "is bound either way, matching the FTSE inventory."
)

_RUN_STAMP = re.compile(r"run_(\d{8})_(\d{6})")
_FILE_DATE_KEYS = ("fetched_at", "updated_at", "created_at", "reviewed_at", "ch_refetched_at")
_MISSING_TEXT = frozenset({"", "none", "nan", "null"})


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _MISSING_TEXT:
        return None
    return text


def _number(value: Any) -> float | None:
    text = _clean_text(value)
    if text is None:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number:  # NaN
        return None
    return number


def _file_payload_as_of(path: Path, as_of: datetime) -> dict[str, Any] | None:
    """Load a JSON object only when it carries a timestamp on or before ``as_of``."""
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    stamped: datetime | None = None
    for key in _FILE_DATE_KEYS:
        stamped = _parse_dt(payload.get(key))
        if stamped is not None:
            break
    if stamped is None or stamped > as_of:
        return None
    return payload


def graduated_market_ids(market_status_path: Path = DEFAULT_MARKET_STATUS_PATH) -> list[str]:
    """Market ids whose ``is_graduated`` flag is true. Missing file → none."""
    path = Path(market_status_path)
    if not path.is_file():
        return []
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []
    out: list[str] = []
    for row in payload.get("markets") or []:
        if not isinstance(row, dict) or not row.get("is_graduated"):
            continue
        market_id = str(row.get("market_id") or "").strip()
        if market_id:
            out.append(market_id)
    return out


def _stamp_from_name(path: Path) -> datetime | None:
    match = _RUN_STAMP.search(path.name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S").replace(
            tzinfo=UTC
        )
    except ValueError:
        return None


def _newest_screen_run(
    history_dir: Path,
    as_of: datetime,
) -> tuple[datetime | None, str | None, dict[str, dict[str, Any]]]:
    """Newest ``run_*.json.gz`` whose ``run_at`` is on or before ``as_of``."""
    if not history_dir.is_dir():
        return None, None, {}
    candidates: list[tuple[datetime, Path]] = []
    for path in history_dir.iterdir():
        name = path.name
        if not path.is_file() or not name.startswith("run_"):
            continue
        if not (name.endswith(".json.gz") or name.endswith(".json")):
            continue
        stamp = _stamp_from_name(path)
        if stamp is None or stamp > as_of:
            continue
        candidates.append((stamp, path))
    candidates.sort(key=lambda item: item[0], reverse=True)
    for _stamp, path in candidates:
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        run_at = _parse_dt(payload.get("run_at")) or _stamp
        if run_at > as_of:
            continue
        by_ticker: dict[str, dict[str, Any]] = {}
        for row in payload.get("signals") or []:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker and ticker not in by_ticker:
                by_ticker[ticker] = row
        return run_at, path.name, by_ticker
    return None, None, {}


def _summary_run_at(screen_dir: Path) -> datetime | None:
    path = screen_dir / "latest_summary.json"
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_dt(payload.get("run_at"))


def _csv_rows(path: Path, *, buy_only: bool = False) -> dict[str, dict[str, str]]:
    """First row per ticker. ``buy_only`` keeps the inventory's buy-tier filter."""
    if not path.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ticker = str(row.get("ticker") or "").strip().upper()
            signal = str(row.get("signal") or "").strip()
            if not ticker or ticker in out:
                continue
            if buy_only and signal not in BUY_SIGNALS:
                continue
            out[ticker] = {
                str(key): "" if value is None else str(value) for key, value in row.items()
            }
    return out


def _csv_buy_rows(path: Path) -> dict[str, dict[str, str]]:
    return _csv_rows(path, buy_only=True)


def library_screen_free_cashflow(
    screen_dir: Path,
    ticker: str,
    *,
    as_of: datetime,
) -> dict[str, Any]:
    """``free_cashflow`` from ``latest_signals.csv``, dated like the inventory.

    ``_buy_tier_members`` reads that CSV only when ``latest_summary.json``
    ``run_at`` is on or before ``as_of``. A later snapshot is
    ``screen_fcf_after_session``. A missing date, row, or figure is
    ``screen_fcf_missing``. ``paths`` lists the files actually read.
    """
    summary_path = screen_dir / "latest_summary.json"
    csv_path = screen_dir / "latest_signals.csv"
    read: list[str] = []
    if summary_path.is_file():
        read.append(str(summary_path))
    summary_at = _summary_run_at(screen_dir)
    if summary_at is None:
        return {"free_cashflow": None, "reason": "screen_fcf_missing", "paths": read}
    if _as_utc(summary_at) > _as_utc(as_of):
        return {"free_cashflow": None, "reason": "screen_fcf_after_session", "paths": read}
    if csv_path.is_file():
        read.append(str(csv_path))
    row = _csv_rows(csv_path).get(str(ticker or "").strip().upper())
    value = _number(row.get("free_cashflow")) if row else None
    if value is None:
        return {"free_cashflow": None, "reason": "screen_fcf_missing", "paths": read}
    return {"free_cashflow": value, "reason": "", "paths": read}


def _sec_free_cashflow(payload: dict[str, Any]) -> tuple[float | None, str]:
    latest = payload.get("latest")
    if not isinstance(latest, dict):
        return None, "USD"
    currency = str(latest.get("currency") or "USD")
    return _number(latest.get("free_cashflow")), currency


def _bridge_figures(payload: dict[str, Any]) -> tuple[float | None, float | None, str | None]:
    """Return (filing-side figure, company-adjusted, currency) from a resolved bridge."""
    if payload.get("resolved") is not True:
        return None, None, None
    currency = _clean_text(payload.get("currency"))
    company = _number(payload.get("company_adjusted"))
    if company is None and payload.get("policy_basis") == "company_adjusted":
        company = _number(payload.get("policy_fcf"))
    policy = _number(payload.get("policy_fcf"))
    filing_side = company if company is not None else policy
    return filing_side, company, currency


def evaluate_library_fcf_basis(
    research_dir: Path,
    *,
    screen_fcf: float | None,
    as_of: datetime,
) -> dict[str, Any]:
    """Evaluate the library free-cash-flow bind for one research folder.

    ``fcf_basis_bound`` is true when the check produced a boolean.
    ``fcf_basis_overlay`` is that boolean, or null when an input is missing.
    """
    sources = Path(research_dir) / "sources"
    filing: float | None = None
    source: str | None = None
    company: float | None = None
    currency = "USD"

    financials = _file_payload_as_of(sources / "financials_annual.json", as_of)
    if financials and (financials.get("cash_flow") or financials.get("income_statement")):
        aligned, _year = compute_filing_aligned_fcf(financials)
        if aligned is not None:
            filing = float(aligned)
            source = "financials_annual"

    sec = _file_payload_as_of(sources / "sec_companyfacts.json", as_of)
    if sec is not None:
        sec_fcf, sec_currency = _sec_free_cashflow(sec)
        if filing is None and sec_fcf is not None:
            filing = sec_fcf
            source = "sec_companyfacts"
            currency = sec_currency

    bridge = _file_payload_as_of(sources / "fcf_bridge.json", as_of)
    if bridge is not None:
        side, bridge_company, bridge_currency = _bridge_figures(bridge)
        if bridge_currency:
            currency = bridge_currency
        company = bridge_company
        if filing is None and side is not None:
            filing = side
            source = "fcf_bridge"

    detail = {
        "fcf_basis_source": source,
        "fcf_screen_ttm": screen_fcf,
        "fcf_filing_aligned": filing,
        "fcf_company_adjusted": company,
    }
    if filing is None or screen_fcf is None:
        detail["fcf_basis_bound"] = False
        detail["fcf_basis_overlay"] = None
        return detail

    mismatch = fcf_filing_screen_mismatch(filing_aligned=filing, screen_ttm=screen_fcf)
    divergence = fcf_basis_divergence_flagged(
        filing_aligned=filing,
        screen_ttm=screen_fcf,
        company_adjusted=company,
        filing_currency=currency,
        company_adjusted_currency=currency if company is not None else None,
    )
    detail["fcf_basis_bound"] = True
    detail["fcf_basis_overlay"] = bool(mismatch or divergence)
    return detail


def _memo_as_of(
    ticker: str,
    *,
    research_root: Path,
    as_of: datetime,
) -> tuple[bool, datetime | None, str | None]:
    """Memo activity and disk verdict using only timestamps on or before ``as_of``."""
    has_disk, created, updated, disk_verdict = _research_doc_times(
        ticker, research_root=research_root
    )
    if not has_disk:
        return False, None, None
    if created is not None and created > as_of:
        created = None
    verdict = _clean_text(disk_verdict)
    if updated is not None and updated > as_of:
        updated = None
        # The file on disk may be a later rewrite. Do not use its verdict.
        verdict = None
    memo_at = updated or created
    if memo_at is None:
        return False, None, None
    return True, memo_at, verdict


def _index_as_of(
    ticker: str,
    *,
    research_root: Path,
    as_of: datetime,
) -> dict[str, Any]:
    """Filings-index meta, ignored when its body stamp is missing or after ``as_of``.

    The body stamp is the latest pass that could add bodies
    (``filings_index_dating.bodies_at``); listing-only scans do not move it.
    """
    meta = _index_meta(ticker, research_root=research_root)
    index_at = _parse_dt(meta.get("bodies_at"))
    if index_at is None or index_at > as_of:
        return {
            "has_index": False,
            "filings_total": 0,
            "filings_with_body": 0,
            "key_bodies": False,
        }
    return {
        "has_index": bool(meta.get("has_index")),
        "filings_total": int(meta.get("filings_total") or 0),
        "filings_with_body": int(meta.get("filings_with_body") or 0),
        "key_bodies": bool(meta.get("key_bodies")),
    }


def _buy_tier_members(
    screen_dir: Path,
    *,
    as_of: datetime,
    run_rows: dict[str, dict[str, Any]],
    run_at: datetime | None,
) -> tuple[dict[str, dict[str, Any]], datetime | None, str]:
    """Point-in-time buy-tier rows and where the raw signal came from."""
    summary_at = _summary_run_at(screen_dir)
    if summary_at is not None and summary_at <= as_of:
        members: dict[str, dict[str, Any]] = {}
        for ticker, row in _csv_buy_rows(screen_dir / "latest_signals.csv").items():
            members[ticker] = {
                "name": str(row.get("name") or ""),
                "signal": str(row.get("signal") or ""),
                "free_cashflow": _number(row.get("free_cashflow")),
            }
        return members, summary_at, "latest_signals"

    members = {}
    for ticker, row in run_rows.items():
        signal = str(row.get("signal") or "").strip()
        if signal not in BUY_SIGNALS:
            continue
        members[ticker] = {
            "name": str(row.get("name") or ""),
            "signal": signal,
            "free_cashflow": _number(row.get("free_cashflow")),
        }
    return members, run_at, "screen_run"


def _row_for_name(
    *,
    market_id: str,
    ticker: str,
    member: dict[str, Any],
    run_row: dict[str, Any] | None,
    run_at: datetime | None,
    run_name: str | None,
    signal_as_of: datetime | None,
    signal_source: str,
    research_root: Path,
    as_of: datetime,
    memo_max_age_days: float,
) -> dict[str, Any]:
    research_dir = research_root / ticker
    index = _index_as_of(ticker, research_root=research_root, as_of=as_of)
    has_memo, memo_at, disk_verdict = _memo_as_of(ticker, research_root=research_root, as_of=as_of)
    age = _memo_age_days(memo_at, now=as_of)
    memo_recent = bool(has_memo and age is not None and age <= float(memo_max_age_days))

    run_row = run_row or {}
    adjusted = _clean_text(run_row.get("adjusted_signal"))
    run_verdict = _clean_text(run_row.get("research_verdict"))
    if run_verdict:
        verdict = run_verdict
        verdict_source = "screen_run"
    elif disk_verdict:
        verdict = disk_verdict
        verdict_source = "research_json"
    else:
        verdict = None
        verdict_source = None

    overlay = _overlay_bound({"adjusted_signal": adjusted}, research_verdict=verdict)
    fcf = evaluate_library_fcf_basis(
        research_dir,
        screen_fcf=member.get("free_cashflow"),
        as_of=as_of,
    )

    gaps: list[str] = []
    if not index["key_bodies"]:
        gaps.append("key_filing_bodies")
    if not fcf["fcf_basis_bound"]:
        gaps.append("fcf_basis_bound")
    if not overlay:
        gaps.append("overlay_bound")
    if not memo_recent:
        gaps.append("memo_recent")

    return {
        "market_id": market_id,
        "ticker": ticker,
        "name": str(member.get("name") or ""),
        "signal": str(member.get("signal") or ""),
        "signal_source": signal_source,
        "signal_as_of": signal_as_of.isoformat() if signal_as_of else None,
        "adjusted_signal": adjusted,
        "research_verdict": verdict,
        "research_verdict_source": verdict_source,
        "screen_run_at": run_at.isoformat() if run_at and run_row else None,
        "screen_run_file": run_name if run_row else None,
        "key_filing_bodies": bool(index["key_bodies"]),
        "fcf_basis_bound": bool(fcf["fcf_basis_bound"]),
        "fcf_basis_overlay": fcf["fcf_basis_overlay"],
        "fcf_basis_source": fcf["fcf_basis_source"],
        "fcf_screen_ttm": fcf["fcf_screen_ttm"],
        "fcf_filing_aligned": fcf["fcf_filing_aligned"],
        "fcf_company_adjusted": fcf["fcf_company_adjusted"],
        "overlay_bound": bool(overlay),
        "has_memo": has_memo,
        "memo_at": memo_at.isoformat() if memo_at else None,
        "memo_age_days": age,
        "memo_recent": memo_recent,
        "filings_total": index["filings_total"],
        "filings_with_body": index["filings_with_body"],
        "has_index": index["has_index"],
        "has_research_folder": research_dir.is_dir(),
        "gaps": gaps,
        "all_four_green": not gaps,
    }


def _market_rows(
    market_id: str,
    *,
    library_root: Path,
    as_of: datetime,
    memo_max_age_days: float,
) -> list[dict[str, Any]]:
    screen_dir = Path(library_root) / "markets" / market_id / "screen"
    research_root = screen_dir / "research"
    run_at, run_name, run_rows = _newest_screen_run(screen_dir / "history", as_of)
    members, signal_as_of, signal_source = _buy_tier_members(
        screen_dir,
        as_of=as_of,
        run_rows=run_rows,
        run_at=run_at,
    )
    rows: list[dict[str, Any]] = []
    for ticker in sorted(members):
        run_row = run_rows.get(ticker)
        rows.append(
            _row_for_name(
                market_id=market_id,
                ticker=ticker,
                member=members[ticker],
                run_row=run_row,
                run_at=run_at if run_row else None,
                run_name=run_name if run_row else None,
                signal_as_of=signal_as_of,
                signal_source=signal_source,
                research_root=research_root,
                as_of=as_of,
                memo_max_age_days=memo_max_age_days,
            )
        )
    return rows


def _gap_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in BIND_FIELDS}
    for row in rows:
        for name in BIND_FIELDS:
            if not row.get(name):
                counts[name] += 1
    return counts


def _market_summary(market_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    gap_counts = _gap_counts(rows)
    return {
        "market_id": market_id,
        "buy_tier_names": len(rows),
        "all_four_green": sum(1 for row in rows if row.get("all_four_green")),
        "gap_counts": gap_counts,
    }


def run_library_decision_input_inventory(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    market_status_path: Path = DEFAULT_MARKET_STATUS_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
    memo_max_age_days: float = DEFAULT_MEMO_MAX_AGE_DAYS,
    as_of: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Build the library buy-tier bind inventory and optionally persist it."""
    moment = _as_utc(as_of or datetime.now(UTC))
    markets = graduated_market_ids(market_status_path)
    rows: list[dict[str, Any]] = []
    by_market: list[dict[str, Any]] = []
    for market_id in markets:
        market_rows = _market_rows(
            market_id,
            library_root=library_root,
            as_of=moment,
            memo_max_age_days=memo_max_age_days,
        )
        rows.extend(market_rows)
        by_market.append(_market_summary(market_id, market_rows))

    gap_counts = _gap_counts(rows)
    # P1 field order wins a tie, so the first maximum in BIND_FIELDS is the largest gap.
    dominant: str | None = None
    best = 0
    for name in BIND_FIELDS:
        if gap_counts[name] > best:
            best = gap_counts[name]
            dominant = name

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": moment.isoformat(),
        "as_of": moment.isoformat(),
        "observe_only": True,
        "influences_live": False,
        "learning_question": LEARNING_QUESTION,
        "memo_max_age_days": float(memo_max_age_days),
        "fcf_basis_definition": LIBRARY_FCF_DEFINITION,
        "library_root": str(library_root),
        "market_status_path": str(market_status_path),
        "graduated_markets": list(markets),
        "summary": {
            "buy_tier_names": len(rows),
            "all_four_green": sum(1 for row in rows if row.get("all_four_green")),
            "gap_counts": gap_counts,
            "dominant_gap_field": dominant,
            "by_market": by_market,
        },
        "rows": rows,
    }
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, compact=False)
    return payload


def format_library_decision_input_summary(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "Library buy-tier decision-input binds (observe-only)",
        f"  As of: {payload.get('as_of')}",
        f"  Buy-tier names: {summary.get('buy_tier_names')}",
        f"  All four green: {summary.get('all_four_green')}",
    ]
    gaps = summary.get("gap_counts") or {}
    if gaps:
        parts = [f"{name}={gaps.get(name)}" for name in BIND_FIELDS]
        lines.append("  Gap counts: " + ", ".join(parts))
    dominant = summary.get("dominant_gap_field")
    if dominant:
        lines.append(f"  Largest gap: {dominant}")
    for market in summary.get("by_market") or []:
        market_gaps = market.get("gap_counts") or {}
        gap_text = ", ".join(f"{name}={market_gaps.get(name)}" for name in BIND_FIELDS)
        lines.append(
            f"  {market.get('market_id')}: names={market.get('buy_tier_names')} "
            f"all_four={market.get('all_four_green')} {gap_text}"
        )
    return "\n".join(lines)


def ops_finding_from_library_decision_input_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    """Summary finding. Observe-only: no rememo, ingest, or engineering task."""
    summary = payload.get("summary") or {}
    gap_counts = summary.get("gap_counts") or {}
    parts = [f"{name}={int(gap_counts.get(name) or 0)}" for name in BIND_FIELDS]
    dominant = summary.get("dominant_gap_field")
    dominant_text = f" Largest gap: {dominant}." if dominant else ""
    text = (
        f"Graduated library buy-tier names: {int(summary.get('buy_tier_names') or 0)}; "
        f"all four binds true: {int(summary.get('all_four_green') or 0)}. "
        f"Gaps: {', '.join(parts)}.{dominant_text} "
        "Observe-only — do not rememo, ingest, or open an engineering task from "
        "this finding. See docs/data/library_decision_input_inventory.json."
    )
    return {
        "severity": "info",
        "category": "research",
        "title": FINDING_TITLE,
        "summary": text,
        "auto_fixable": False,
    }


__all__ = [
    "DEFAULT_LIBRARY_ROOT",
    "DEFAULT_MARKET_STATUS_PATH",
    "DEFAULT_MEMO_MAX_AGE_DAYS",
    "DEFAULT_STORE_PATH",
    "FINDING_TITLE",
    "LEARNING_QUESTION",
    "LIBRARY_FCF_DEFINITION",
    "STORE_FAILED_TITLE",
    "evaluate_library_fcf_basis",
    "format_library_decision_input_summary",
    "graduated_market_ids",
    "ops_finding_from_library_decision_input_inventory",
    "run_library_decision_input_inventory",
]
