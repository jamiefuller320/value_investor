"""Observe-only: shard day-0 NAV FX unit mismatch (N153).

Detects GBP-reporting market-shard books that debit cash at local prices then
convert equity marks to GBP (spurious day-0 NAV drag). Does **not** rewrite
funds — surfaces a warn until the native-currency twin has marks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.fx import currency_for_market
from value_investor.market_shard_admission import admitted_learning_markets_for_policy
from value_investor.market_shard_phases import shard_root_for_market
from value_investor.paper_automation import (
    BUY_TIER_LEVEL_NATIVE_SUBDIR,
    BUY_TIER_LEVEL_NATIVE_TRACK_ID,
    BUY_TIER_LEVEL_SUBDIR,
    FUND_FILENAME,
)
from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 1
DEFAULT_STORE_PATH = Path("docs/data/shard_nav_fx_warp.json")
DEFAULT_POLICY_PATH = Path("docs/data/library/policy.json")
DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
FINDING_TITLE = "Shard NAV FX unit mismatch"
# Day-0 warp: first filled mark / open NAV within this band of a typical FX rate
# (USDGBP ~0.74; EURGBP ~0.85; AUD/CAD GBP often ~0.50–0.55).
WARP_RATIO_LO = 0.45
WARP_RATIO_HI = 0.92


def _safe_read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _load_policy(policy_path: Path) -> dict[str, Any]:
    raw = _safe_read(Path(policy_path))
    return raw or {}


def _fund_open_and_first_fill(fund: dict[str, Any]) -> tuple[float | None, float | None, int]:
    curve = _as_list(fund.get("equity_curve"))
    if not curve:
        return None, None, 0
    open_nav = _float(_as_dict(curve[0]).get("portfolio_value"))
    first_fill_nav = None
    for row in curve[1:]:
        point = _as_dict(row)
        positions = int(point.get("positions") or 0)
        if positions > 0:
            first_fill_nav = _float(point.get("portfolio_value"))
            break
    return open_nav, first_fill_nav, len(curve)


def _native_twin_status(shard_root: Path) -> dict[str, Any]:
    native_dir = Path(shard_root) / BUY_TIER_LEVEL_NATIVE_SUBDIR
    config_present = (native_dir / "config.json").exists()
    fund = _safe_read(native_dir / FUND_FILENAME) or {}
    curve = _as_list(fund.get("equity_curve"))
    filled = any(int(_as_dict(row).get("positions") or 0) > 0 for row in curve)
    reporting = None
    if fund:
        reporting = _as_dict(fund.get("config")).get("reporting_currency")
    elif config_present:
        cfg = _safe_read(native_dir / "config.json") or {}
        reporting = cfg.get("reporting_currency")
    return {
        "track_id": BUY_TIER_LEVEL_NATIVE_TRACK_ID,
        "config_present": config_present,
        "fund_present": bool(fund),
        "has_fills": filled,
        "mark_count": len(curve),
        "reporting_currency": reporting,
        "status": (
            "active"
            if filled
            else ("pending" if config_present else "missing")
        ),
    }


def inspect_market_nav_fx(
    market_id: str,
    *,
    paper_root: Path = DEFAULT_PAPER_ROOT,
    shard_root: Path | None = None,
) -> dict[str, Any]:
    """Inspect one market's GBP level book vs native twin."""
    mid = str(market_id or "").strip()
    native_ccy = currency_for_market(mid)
    if shard_root is not None:
        root = Path(shard_root)
    else:
        markets_base = Path(paper_root) / "markets"
        root = shard_root_for_market(mid, base=markets_base)

    gbp_fund = _safe_read(root / BUY_TIER_LEVEL_SUBDIR / FUND_FILENAME) or {}
    fund_cfg = _as_dict(gbp_fund.get("config"))
    reporting = str(fund_cfg.get("reporting_currency") or "GBP").upper()
    open_nav, first_fill_nav, mark_count = _fund_open_and_first_fill(gbp_fund)
    ratio = None
    if open_nav and open_nav > 0 and first_fill_nav is not None:
        ratio = round(first_fill_nav / open_nav, 4)
    warp = bool(
        gbp_fund
        and reporting == "GBP"
        and str(native_ccy).upper() != "GBP"
        and ratio is not None
        and WARP_RATIO_LO <= ratio <= WARP_RATIO_HI
    )
    native = _native_twin_status(root)
    return {
        "market_id": mid,
        "native_currency": native_ccy,
        "gbp_book": {
            "track_id": "buy_tier_level",
            "reporting_currency": reporting if gbp_fund else None,
            "fund_present": bool(gbp_fund),
            "mark_count": mark_count,
            "open_nav": open_nav,
            "first_fill_nav": first_fill_nav,
            "nav_ratio": ratio,
            "fx_warp_detected": warp,
        },
        "native_twin": native,
        "needs_native_twin": str(native_ccy).upper() != "GBP",
        # Warn only while GBP warp is visible and the native twin is not yet marking.
        "warn": bool(warp and native.get("status") != "active"),
    }


def update_shard_nav_fx_warp(
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    policy_path: Path = DEFAULT_POLICY_PATH,
    paper_root: Path = DEFAULT_PAPER_ROOT,
    markets: list[str] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Refresh the observe store for admitted non-GBP shards."""
    policy = _load_policy(Path(policy_path))
    admitted = admitted_learning_markets_for_policy(policy)
    wanted = list(markets) if markets is not None else [
        mid for mid in admitted if str(currency_for_market(mid) or "GBP").upper() != "GBP"
    ]
    rows: list[dict[str, Any]] = []
    warped = 0
    twin_active = 0
    twin_pending = 0
    for mid in wanted:
        row = inspect_market_nav_fx(mid, paper_root=Path(paper_root))
        rows.append(row)
        if (row.get("gbp_book") or {}).get("fx_warp_detected"):
            warped += 1
        status = (row.get("native_twin") or {}).get("status")
        if status == "active":
            twin_active += 1
        elif status == "pending":
            twin_pending += 1
    warn_markets = [r["market_id"] for r in rows if r.get("warn")]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now(UTC).isoformat(),
        "capital_epoch": "n153_native_currency",
        "admitted": admitted,
        "markets": rows,
        "summary": {
            "market_count": len(rows),
            "gbp_warp_count": warped,
            "native_twin_active": twin_active,
            "native_twin_pending": twin_pending,
            "warn_count": len(warn_markets),
            "warn_markets": warn_markets,
        },
        "note": (
            "Observe-only. GBP buy_tier_level books with day-0 NAV≈FX are contaminated; "
            "use buy_tier_level_native (cold-start) for adoption-truth NAV. "
            "Do not rewrite mid-flight funds."
        ),
    }
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, compact=False)
    return payload


def ops_finding_from_shard_nav_fx_warp(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a warn-only finding when warped GBP books lack an active native twin."""
    if not payload:
        return None
    summary = _as_dict(payload.get("summary"))
    warn_count = int(summary.get("warn_count") or 0)
    if warn_count <= 0:
        return None
    warped = int(summary.get("gbp_warp_count") or 0)
    pending = int(summary.get("native_twin_pending") or 0)
    active = int(summary.get("native_twin_active") or 0)
    markets = ", ".join(summary.get("warn_markets") or []) or "—"
    return {
        "severity": "warn",
        "category": "paper",
        "title": FINDING_TITLE,
        "summary": (
            f"{warn_count} non-GBP shard book(s) need native-currency NAV attention "
            f"(GBP warp detected={warped}, native twin active={active}, pending={pending}): "
            f"{markets}. Prefer buy_tier_level_native; do not rewrite mid-flight GBP funds."
        ),
        "auto_fixable": False,
    }


__all__ = [
    "DEFAULT_STORE_PATH",
    "FINDING_TITLE",
    "inspect_market_nav_fx",
    "ops_finding_from_shard_nav_fx_warp",
    "update_shard_nav_fx_warp",
]
