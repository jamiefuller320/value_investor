"""Park leftover thin / unfetchable-IWB names after ingest avenues are exhausted.

Sprint loops must not keep re-running once unmeasured and zero-body names are
gone and remaining thin / indexed-without-body rows have failed every complete
deepen. Those leftovers are parked (accepted as thin for now), excluded from
the learning pool, and treated as sprint-complete so the effort cascade can
move on. True FTSE filing parity (all four counts zero) is unchanged and still
gates maintenance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.storage import read_json, write_json

INGEST_EXHAUSTION_FILENAME = "ingest_exhaustion.json"
DEFAULT_EXHAUSTION_ZERO_RUNS = 3

REASON_UNFETCHABLE_IWB = "unfetchable_iwb"
REASON_AWAITING_PERIODIC = "awaiting_periodic_report"

REVISIT_UNFETCHABLE_IWB = (
    "New 10-K/10-Q (or equivalent statutory report) is indexed, or an IR "
    "allowlist body lands for the leftover rows"
)
REVISIT_AWAITING_PERIODIC = "Next statutory annual or interim report is issued and indexed"


def ingest_exhaustion_path(library_root: Path, market_id: str) -> Path:
    return Path(library_root) / "markets" / market_id / INGEST_EXHAUSTION_FILENAME


def empty_exhaustion(market_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    stamp = (now or datetime.now(UTC)).isoformat()
    return {
        "schema_version": 1,
        "market_id": market_id,
        "updated_at": stamp,
        "exhausted": False,
        "complete_zero_improve_runs": 0,
        "min_zero_runs": DEFAULT_EXHAUSTION_ZERO_RUNS,
        "parked": [],
        "note": (
            "Leftover thin / indexed-without-body names parked after complete "
            "0-improve sprints. Unmeasured and zero-body names are never parked."
        ),
    }


def load_ingest_exhaustion(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    path = ingest_exhaustion_path(library_root, market_id)
    if not path.exists():
        return empty_exhaustion(market_id)
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return empty_exhaustion(market_id)
    if not isinstance(payload, dict):
        return empty_exhaustion(market_id)
    parked = [row for row in (payload.get("parked") or []) if isinstance(row, dict)]
    return {
        **empty_exhaustion(market_id),
        **payload,
        "market_id": str(payload.get("market_id") or market_id),
        "parked": parked,
        "exhausted": bool(payload.get("exhausted")),
    }


def parked_tickers_from_exhaustion(exhaustion: dict[str, Any] | None) -> list[str]:
    rows = (exhaustion or {}).get("parked") or []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def learning_pool_excluded_tickers(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
) -> set[str]:
    """Tickers parked from observe-sim / paper learning until coverage improves."""
    return set(
        parked_tickers_from_exhaustion(load_ingest_exhaustion(market_id, library_root=library_root))
    )


def overlay_exhaustion_on_health(
    health: dict[str, Any],
    exhaustion: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach effective thin/IWB counts; raw snapshot fields stay honest."""
    overlaid = dict(health)
    exhaustion = exhaustion or {}
    parked = set(parked_tickers_from_exhaustion(exhaustion))
    thin = [str(t).strip() for t in (overlaid.get("thin_body_tickers") or []) if str(t).strip()]
    iwb_tickers = [
        str(t).strip()
        for t in (overlaid.get("indexed_without_body_tickers") or [])
        if str(t).strip()
    ]
    by_ticker = overlaid.get("indexed_without_body_by_ticker") or {}
    effective_thin = [t for t in thin if t not in parked]
    effective_iwb_tickers = [t for t in iwb_tickers if t not in parked]
    if isinstance(by_ticker, dict) and by_ticker:
        effective_iwb = sum(int(by_ticker.get(t) or 0) for t in effective_iwb_tickers)
    elif iwb_tickers:
        raw_iwb = int(overlaid.get("indexed_without_body") or 0)
        effective_iwb = 0 if not effective_iwb_tickers else raw_iwb
    else:
        effective_iwb = int(overlaid.get("indexed_without_body") or 0)
        if parked and bool(exhaustion.get("exhausted")):
            effective_iwb = 0

    unmeasured = int(overlaid.get("unmeasured_buy_tier") or 0)
    zero = int(overlaid.get("zero_body_buy_tier") or 0)
    raw_thin = int(overlaid.get("thin_body_buy_tier") or 0)
    raw_iwb = int(overlaid.get("indexed_without_body") or 0)
    leftover = raw_thin > 0 or raw_iwb > 0
    computed_exhausted = (
        bool(parked)
        and unmeasured == 0
        and zero == 0
        and leftover
        and not effective_thin
        and int(effective_iwb) == 0
    )
    if (
        not iwb_tickers
        and not thin
        and bool(exhaustion.get("exhausted"))
        and unmeasured == 0
        and zero == 0
        and leftover
        and parked
    ):
        computed_exhausted = True
        effective_thin = []
        effective_iwb = 0

    overlaid["parked_tickers"] = sorted(parked)
    overlaid["parked_count"] = len(parked)
    overlaid["effective_thin_body_buy_tier"] = len(effective_thin)
    overlaid["effective_thin_body_tickers"] = effective_thin
    overlaid["effective_indexed_without_body"] = int(effective_iwb)
    overlaid["effective_indexed_without_body_tickers"] = effective_iwb_tickers
    overlaid["ingest_exhausted"] = bool(computed_exhausted)
    return overlaid


def apply_stored_exhaustion_overlay(
    health: dict[str, Any],
    *,
    market_id: str,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    return overlay_exhaustion_on_health(
        health,
        load_ingest_exhaustion(market_id, library_root=library_root),
    )


def count_trailing_complete_zero_improve_runs(
    log_path: Path,
    *,
    market_id: str,
) -> tuple[int, bool]:
    """Return (trailing complete 0-improve count, any of those runs had targets)."""
    if not log_path.exists():
        return 0, False
    try:
        payload = read_json(log_path)
    except (OSError, ValueError, TypeError):
        return 0, False
    entries = list(payload.get("entries") or [])
    scoped = [row for row in entries if str(row.get("market_id") or "") == market_id]
    if not scoped and market_id == "euro_depth":
        scoped = [row for row in entries if not row.get("market_id")]
    trailing = 0
    had_targets = False
    for row in reversed(scoped):
        if not isinstance(row, dict):
            break
        if row.get("runtime_cutoff") or row.get("partial"):
            break
        if int(row.get("improved") or 0) > 0:
            break
        trailing += 1
        if int(row.get("targets") or 0) > 0:
            had_targets = True
    return trailing, had_targets


def _coverage_for_ticker(
    ticker: str,
    *,
    market_id: str,
    library_root: Path,
) -> dict[str, int]:
    from value_investor.library_ingest_escalation import is_ftse_equivalent_market
    from value_investor.library_ingest_loop import _filing_coverage_for_ticker

    coverage = _filing_coverage_for_ticker(
        ticker,
        library_root=library_root,
        market_id=market_id,
        canonical_only=is_ftse_equivalent_market(market_id),
    )
    return {
        "filings_total": int(coverage.get("filings_total") or 0),
        "filings_with_body": int(coverage.get("filings_with_body") or 0),
        "indexed_without_body": int(coverage.get("indexed_without_body") or 0),
    }


def _park_reason(ticker: str, *, iwb_tickers: set[str]) -> tuple[str, str]:
    if ticker in iwb_tickers:
        return REASON_UNFETCHABLE_IWB, REVISIT_UNFETCHABLE_IWB
    return REASON_AWAITING_PERIODIC, REVISIT_AWAITING_PERIODIC


def _coverage_improved(previous: dict[str, Any], current: dict[str, int]) -> bool:
    prev_body = int(previous.get("filings_with_body") or 0)
    prev_iwb = int(previous.get("indexed_without_body") or 0)
    prev_total = int(previous.get("filings_total") or 0)
    return (
        int(current.get("filings_with_body") or 0) > prev_body
        or int(current.get("indexed_without_body") or 0) < prev_iwb
        or int(current.get("filings_total") or 0) > prev_total
    )


def refresh_library_ingest_exhaustion(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    health: dict[str, Any] | None = None,
    health_log_path: Path | None = None,
    min_zero_runs: int = DEFAULT_EXHAUSTION_ZERO_RUNS,
    now: datetime | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Park leftover thin/IWB names after N complete 0-improve runs.

    Never parks unmeasured or zero-body names. Unparks when coverage improves
    or the ticker leaves the leftover-gap sets.
    """
    from value_investor.library_ingest_escalation import resolve_library_ingest_health_log_path

    library_root = Path(library_root)
    stamp = now or datetime.now(UTC)
    existing = load_ingest_exhaustion(market_id, library_root=library_root)
    health = dict(health or {})
    log_path = Path(
        health_log_path or resolve_library_ingest_health_log_path(library_root, market_id)
    )
    zero_runs, had_targets = count_trailing_complete_zero_improve_runs(
        log_path,
        market_id=market_id,
    )

    unmeasured = {
        str(t).strip() for t in (health.get("unmeasured_tickers") or []) if str(t).strip()
    }
    zero_body = {str(t).strip() for t in (health.get("zero_body_tickers") or []) if str(t).strip()}
    thin = {str(t).strip() for t in (health.get("thin_body_tickers") or []) if str(t).strip()}
    iwb = {
        str(t).strip() for t in (health.get("indexed_without_body_tickers") or []) if str(t).strip()
    }
    bootstrap = unmeasured | zero_body
    leftover = (thin | iwb) - bootstrap

    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in existing.get("parked") or []:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker or ticker in seen or ticker in bootstrap:
            continue
        if ticker not in leftover:
            continue
        coverage = _coverage_for_ticker(ticker, market_id=market_id, library_root=library_root)
        if _coverage_improved(row, coverage):
            continue
        reason, revisit = _park_reason(ticker, iwb_tickers=iwb)
        kept.append(
            {
                **row,
                "ticker": ticker,
                "reason": reason,
                "revisit_when": revisit,
                **coverage,
                "thin": ticker in thin,
            }
        )
        seen.add(ticker)

    can_park_new = (
        int(health.get("unmeasured_buy_tier") or 0) == 0
        and int(health.get("zero_body_buy_tier") or 0) == 0
        and not unmeasured
        and not zero_body
        and leftover
        and zero_runs >= max(1, int(min_zero_runs))
        and had_targets
    )
    if can_park_new:
        for ticker in sorted(leftover):
            if ticker in seen:
                continue
            coverage = _coverage_for_ticker(ticker, market_id=market_id, library_root=library_root)
            reason, revisit = _park_reason(ticker, iwb_tickers=iwb)
            kept.append(
                {
                    "ticker": ticker,
                    "reason": reason,
                    "revisit_when": revisit,
                    "parked_at": stamp.isoformat(),
                    **coverage,
                    "thin": ticker in thin,
                }
            )
            seen.add(ticker)

    parked_set = {str(row.get("ticker") or "").strip() for row in kept}
    exhausted = (
        bool(kept)
        and not unmeasured
        and not zero_body
        and bool(leftover)
        and leftover <= parked_set
    )
    payload = {
        **empty_exhaustion(market_id, now=stamp),
        "exhausted": exhausted,
        "complete_zero_improve_runs": int(zero_runs),
        "min_zero_runs": int(min_zero_runs),
        "had_complete_targets": had_targets,
        "leftover_tickers": sorted(leftover),
        "parked": kept,
        "unparked_leftover": sorted(leftover - parked_set),
    }
    if write:
        path = ingest_exhaustion_path(library_root, market_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, compact=False)
        payload["path"] = str(path)
    return payload


__all__ = [
    "DEFAULT_EXHAUSTION_ZERO_RUNS",
    "INGEST_EXHAUSTION_FILENAME",
    "REASON_AWAITING_PERIODIC",
    "REASON_UNFETCHABLE_IWB",
    "apply_stored_exhaustion_overlay",
    "count_trailing_complete_zero_improve_runs",
    "empty_exhaustion",
    "ingest_exhaustion_path",
    "learning_pool_excluded_tickers",
    "load_ingest_exhaustion",
    "overlay_exhaustion_on_health",
    "parked_tickers_from_exhaustion",
    "refresh_library_ingest_exhaustion",
]
