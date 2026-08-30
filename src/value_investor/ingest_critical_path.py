"""Critical-path monitoring and automated actions for filing ingest.

Classifies buy-tier filing gaps into actionable buckets and recommends
automated next steps for library (and FTSE-shaped) ingest loops:

- ``unmeasured`` / ``zero_body`` — bootstrap / body fetch
- ``indexed_without_body`` — residual body download (highest sprint ROI)
- ``thin_need_discovery`` — need more filings found (IR/ESEF/news), not re-download
- ``thin_need_bodies`` — thin with residual indexed rows still missing bodies

Used by ``library_ingest_loop`` to force discovery scans, prefer iwb/unmeasured
targets, and persist a rollup for ops dashboards.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.storage import write_json

DEFAULT_CRITICAL_PATH_PATH = Path("docs/data/library/ingest_critical_path.json")
AUTO_PIN_LIMIT = 8


@dataclass
class IngestCriticalPath:
    market_id: str
    assessed_at: str
    unmeasured: list[str] = field(default_factory=list)
    zero_body: list[str] = field(default_factory=list)
    indexed_without_body: list[dict[str, Any]] = field(default_factory=list)
    thin_need_discovery: list[str] = field(default_factory=list)
    thin_need_bodies: list[str] = field(default_factory=list)
    primary_blocker: str = "none"
    force_discovery_scan: bool = False
    auto_pin_tickers: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    gap_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _thin_buckets(
    *,
    total: int,
    with_body: int,
    indexed_without_body: int,
) -> tuple[bool, bool]:
    """Return (need_discovery, need_bodies) for a thin ticker."""
    if total <= 0 or with_body <= 0:
        return False, False
    if with_body >= max(3, total // 2):
        return False, False
    # Already have bodies for everything indexed → only discovery helps.
    if indexed_without_body <= 0 and with_body >= total:
        return True, False
    if total < 3:
        return True, indexed_without_body > 0
    return False, indexed_without_body > 0


def assess_library_ingest_critical_path(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    reports: list[Any] | None = None,
    health: dict[str, Any] | None = None,
    auto_pin_limit: int = AUTO_PIN_LIMIT,
) -> IngestCriticalPath:
    """Classify buy-tier gaps and choose automated ingest actions."""
    from value_investor.library_ingest_escalation import is_ftse_equivalent_market
    from value_investor.library_ingest_loop import (
        _filing_coverage_for_ticker,
        load_library_buy_tier_reports,
    )

    library_root = Path(library_root)
    if reports is None:
        try:
            reports = load_library_buy_tier_reports(library_root, market_id)
        except FileNotFoundError:
            reports = []
    canonical_only = is_ftse_equivalent_market(market_id)

    unmeasured: list[str] = []
    zero_body: list[str] = []
    iwb_rows: list[dict[str, Any]] = []
    thin_discovery: list[str] = []
    thin_bodies: list[str] = []

    for report in reports:
        ticker = str(getattr(report, "ticker", "") or "").strip()
        if not ticker:
            continue
        coverage = _filing_coverage_for_ticker(
            ticker,
            library_root=library_root,
            market_id=market_id,
            canonical_only=canonical_only,
        )
        total = int(coverage.get("filings_total") or 0)
        with_body = int(coverage.get("filings_with_body") or 0)
        iwb = int(coverage.get("indexed_without_body") or 0)
        if total == 0:
            unmeasured.append(ticker)
        elif with_body == 0:
            zero_body.append(ticker)
        else:
            need_disc, need_bod = _thin_buckets(
                total=total, with_body=with_body, indexed_without_body=iwb
            )
            if need_disc:
                thin_discovery.append(ticker)
            if need_bod:
                thin_bodies.append(ticker)
        if iwb > 0:
            iwb_rows.append(
                {
                    "ticker": ticker,
                    "indexed_without_body": iwb,
                    "filings_total": total,
                    "filings_with_body": with_body,
                }
            )

    iwb_rows.sort(key=lambda row: (-int(row["indexed_without_body"]), str(row["ticker"])))

    # Prefer actionable body-fill and bootstrap over discovery-only thin churn.
    if unmeasured:
        primary = "unmeasured"
    elif zero_body:
        primary = "zero_body"
    elif iwb_rows:
        primary = "indexed_without_body"
    elif thin_discovery:
        primary = "thin_need_discovery"
    elif thin_bodies:
        primary = "thin_need_bodies"
    else:
        primary = "none"

    force_discovery = bool(
        unmeasured
        or thin_discovery
        or (
            health
            and (
                int((health or {}).get("unmeasured_buy_tier") or 0) > 0
                or int((health or {}).get("thin_body_buy_tier") or 0) > 0
            )
        )
    )

    auto_pin: list[str] = []
    for row in iwb_rows:
        if len(auto_pin) >= auto_pin_limit:
            break
        auto_pin.append(str(row["ticker"]))
    for ticker in unmeasured + zero_body:
        if len(auto_pin) >= auto_pin_limit:
            break
        if ticker not in auto_pin:
            auto_pin.append(ticker)

    actions: list[str] = []
    if unmeasured:
        actions.append(
            f"Bootstrap {len(unmeasured)} unmeasured buy-tier ticker(s) "
            "(IR allowlist + ESEF/news discovery)"
        )
    if iwb_rows:
        top = ", ".join(f"{r['ticker']}({r['indexed_without_body']})" for r in iwb_rows[:5])
        actions.append(
            f"Prefer indexed-without-body body refetch ({len(iwb_rows)} tickers, top: {top})"
        )
    if thin_discovery:
        actions.append(
            f"Discovery/IR seed for {len(thin_discovery)} thin ticker(s) "
            "that already have bodies for every indexed filing"
        )
    if force_discovery:
        actions.append("Run listing-only discovery_scan before deepen")
    if primary == "none":
        actions.append("Filing critical path clear — maintenance deepen only")

    return IngestCriticalPath(
        market_id=market_id,
        assessed_at=datetime.now(UTC).isoformat(),
        unmeasured=unmeasured,
        zero_body=zero_body,
        indexed_without_body=iwb_rows,
        thin_need_discovery=thin_discovery,
        thin_need_bodies=thin_bodies,
        primary_blocker=primary,
        force_discovery_scan=force_discovery,
        auto_pin_tickers=auto_pin,
        recommended_actions=actions,
        gap_counts={
            "unmeasured": len(unmeasured),
            "zero_body": len(zero_body),
            "indexed_without_body_tickers": len(iwb_rows),
            "indexed_without_body_rows": sum(int(r["indexed_without_body"]) for r in iwb_rows),
            "thin_need_discovery": len(thin_discovery),
            "thin_need_bodies": len(thin_bodies),
        },
    )


def persist_ingest_critical_path(
    assessment: IngestCriticalPath,
    *,
    path: Path = DEFAULT_CRITICAL_PATH_PATH,
    library_root: Path | None = None,
) -> Path:
    """Write rollup JSON (global + optional per-market copy)."""
    path = Path(path)
    write_json(path, assessment.to_dict(), compact=False)
    if library_root is not None:
        per_market = (
            Path(library_root) / "markets" / assessment.market_id / "ingest_critical_path.json"
        )
        write_json(per_market, assessment.to_dict(), compact=False)
    return path


def apply_critical_path_to_target_order(
    targets: list[Any],
    assessment: IngestCriticalPath,
) -> list[Any]:
    """Stable-prefer auto-pin / critical tickers at the front of an already-scored list."""
    if not targets:
        return targets
    pin = {str(t).strip().upper() for t in assessment.auto_pin_tickers if str(t).strip()}
    if not pin:
        return targets
    head = [row for row in targets if str(getattr(row, "ticker", "")).upper() in pin]
    tail = [row for row in targets if str(getattr(row, "ticker", "")).upper() not in pin]
    return head + tail


__all__ = [
    "AUTO_PIN_LIMIT",
    "DEFAULT_CRITICAL_PATH_PATH",
    "IngestCriticalPath",
    "apply_critical_path_to_target_order",
    "assess_library_ingest_critical_path",
    "persist_ingest_critical_path",
]
