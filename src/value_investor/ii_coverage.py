"""Interactive Investor coverage overlay for offline library markets (L34 v1).

Uses II's *public* exchange list as an allowlist. This is not a full broker
instrument catalog — individual names are assumed tradable when their Yahoo
venue maps to an online-dealable II exchange, unless a curated exception says
otherwise. Do not scrape logged-in ii.co.uk pages.
"""

from __future__ import annotations

import csv
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import (
    DEFAULT_LIBRARY_ROOT,
    MARKET_REGISTRY,
    load_manifest,
    market_dir,
)
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_II_ROOT = DEFAULT_LIBRARY_ROOT / "ii_coverage"
POLICY_NAME = "policy.json"
EXCEPTIONS_NAME = "exceptions.json"
SUMMARY_NAME = "summary.json"


def ii_coverage_root(library_root: Path | None = None) -> Path:
    root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    return root / "ii_coverage"


def load_ii_policy(ii_root: Path | None = None) -> dict[str, Any]:
    path = (ii_root or DEFAULT_II_ROOT) / POLICY_NAME
    if not path.exists():
        raise FileNotFoundError(f"II coverage policy missing: {path}")
    return read_json(path)


def load_ii_exceptions(ii_root: Path | None = None) -> dict[str, dict[str, Any]]:
    path = (ii_root or DEFAULT_II_ROOT) / EXCEPTIONS_NAME
    if not path.exists():
        return {}
    payload = read_json(path)
    raw = payload.get("exceptions") or {}
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def yahoo_suffix(ticker: str) -> str:
    """Return Yahoo exchange suffix including leading dot, or '' for bare US symbols."""
    text = (ticker or "").strip().upper()
    if "." not in text:
        return ""
    return "." + text.rsplit(".", 1)[-1]


def _suffix_index(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map Yahoo suffix → first matching exchange row from policy."""
    index: dict[str, dict[str, Any]] = {}
    for row in policy.get("exchanges") or []:
        for suf in row.get("yahoo_suffixes") or []:
            key = str(suf)
            # First declaration wins; US bare suffix "" is intentional.
            if key not in index:
                index[key] = row
    return index


def classify_ticker(
    ticker: str,
    *,
    market_id: str | None = None,
    policy: dict[str, Any] | None = None,
    exceptions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Classify one Yahoo ticker for II tradability.

    Returns overlay fields suitable for CSV/JSON rows.
    """
    policy = policy or load_ii_policy()
    exceptions = exceptions if exceptions is not None else load_ii_exceptions()
    key = (ticker or "").strip()
    now = datetime.now(UTC).date().isoformat()

    if key in exceptions:
        exc = exceptions[key]
        return {
            "ticker": key,
            "market": market_id,
            "isin": exc.get("isin"),
            "ii_exchange": exc.get("ii_exchange"),
            "tradable_on_ii": bool(exc.get("tradable_on_ii")),
            "deal_channel": exc.get("deal_channel") or "n/a",
            "confidence": exc.get("confidence") or "curated",
            "basis": exc.get("basis") or "exception",
            "exception_reason": exc.get("exception_reason"),
            "updated_at": now,
        }

    suf = yahoo_suffix(key)
    by_suffix = _suffix_index(policy)
    exchange_row = by_suffix.get(suf)

    # Bare US tickers: only treat as US when market is a US slice (or unknown + bare).
    if suf == "" and exchange_row is not None:
        us_markets = {"sp500", "nasdaq100", "us", "nyse", "nasdaq"}
        if market_id and market_id not in us_markets and market_id != "ftse350":
            # Unlikely bare non-US in our registry; leave unknown rather than force US.
            pass

    if exchange_row is not None:
        phone_only = bool(exchange_row.get("phone_only"))
        online = bool(exchange_row.get("online_dealable")) and not phone_only
        venues = exchange_row.get("venues") or [exchange_row.get("ii_label")]
        return {
            "ticker": key,
            "market": market_id,
            "isin": None,
            "ii_exchange": "/".join(str(v) for v in venues if v),
            "tradable_on_ii": online,
            "deal_channel": "phone" if phone_only else ("online" if online else "n/a"),
            "confidence": "assumed",
            "basis": "exchange_allowlist",
            "exception_reason": (
                "II lists this venue as phone orders only"
                if phone_only
                else None
            ),
            "updated_at": now,
        }

    # Market-level default for known homogeneous slices when suffix is unexpected.
    defaults = (policy.get("market_defaults") or {}).get(market_id or "", {})
    if defaults and defaults.get("tradable_on_ii") is not None:
        return {
            "ticker": key,
            "market": market_id,
            "isin": None,
            "ii_exchange": defaults.get("ii_exchange"),
            "tradable_on_ii": bool(defaults.get("tradable_on_ii")),
            "deal_channel": defaults.get("deal_channel") or "online",
            "confidence": defaults.get("confidence") or "assumed",
            "basis": defaults.get("basis") or "market_default",
            "exception_reason": None,
            "updated_at": now,
        }

    return {
        "ticker": key,
        "market": market_id,
        "isin": None,
        "ii_exchange": None,
        "tradable_on_ii": False,
        "deal_channel": "n/a",
        "confidence": "assumed",
        "basis": "unknown_venue",
        "exception_reason": (
            f"Yahoo suffix {suf!r} is not on II's published online/phone exchange list"
        ),
        "updated_at": now,
    }


def _tickers_for_market(library_root: Path, market_id: str) -> list[str]:
    if market_id not in MARKET_REGISTRY:
        raise ValueError(f"Unknown market {market_id!r}")
    manifest = load_manifest(library_root, market_id)
    tickers = [str(t) for t in (manifest.get("tickers") or []) if t]
    if tickers:
        return tickers
    # Fall back to constituents file if manifest empty.
    path = market_dir(library_root, market_id) / "constituents" / "latest.json"
    if path.exists():
        rows = read_json(path)
        return [str(r["ticker"]) for r in rows if r.get("ticker")]
    return []


def build_market_overlay(
    library_root: Path,
    market_id: str,
    *,
    policy: dict[str, Any] | None = None,
    exceptions: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    policy = policy or load_ii_policy(ii_coverage_root(library_root))
    exceptions = (
        exceptions
        if exceptions is not None
        else load_ii_exceptions(ii_coverage_root(library_root))
    )
    rows = [
        classify_ticker(
            ticker,
            market_id=market_id,
            policy=policy,
            exceptions=exceptions,
        )
        for ticker in _tickers_for_market(library_root, market_id)
    ]
    return rows


def _write_overlay_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "ticker",
        "market",
        "isin",
        "ii_exchange",
        "tradable_on_ii",
        "deal_channel",
        "confidence",
        "basis",
        "exception_reason",
        "updated_at",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            # CSV-friendly booleans
            if isinstance(out.get("tradable_on_ii"), bool):
                out["tradable_on_ii"] = "true" if out["tradable_on_ii"] else "false"
            writer.writerow(out)


def _market_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    tradable = sum(1 for r in rows if r.get("tradable_on_ii") is True)
    phone = sum(1 for r in rows if r.get("deal_channel") == "phone")
    unknown = sum(1 for r in rows if r.get("basis") == "unknown_venue")
    curated = sum(1 for r in rows if r.get("confidence") == "curated")
    return {
        "ticker_count": total,
        "tradable_count": tradable,
        "tradable_pct": round(tradable / total, 4) if total else 0.0,
        "phone_only_count": phone,
        "unknown_venue_count": unknown,
        "curated_exception_count": curated,
    }


def build_ii_overlays(
    library_root: Path | None = None,
    markets: list[str] | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """
    Build per-market II overlays for offline library slices.

    Skips ``ftse350`` by default (live screen path); include explicitly if needed.
    """
    library_root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    ii_root = ii_coverage_root(library_root)
    policy = load_ii_policy(ii_root)
    exceptions = load_ii_exceptions(ii_root)

    if markets is None:
        markets = [mid for mid in MARKET_REGISTRY if mid != "ftse350"]

    per_market: dict[str, Any] = {}
    for market_id in markets:
        rows = build_market_overlay(
            library_root,
            market_id,
            policy=policy,
            exceptions=exceptions,
        )
        stats = _market_stats(rows)
        non_tradable = [
            {
                "ticker": r["ticker"],
                "ii_exchange": r.get("ii_exchange"),
                "deal_channel": r.get("deal_channel"),
                "basis": r.get("basis"),
                "exception_reason": r.get("exception_reason"),
            }
            for r in rows
            if r.get("tradable_on_ii") is not True
        ]
        per_market[market_id] = {
            **stats,
            "non_tradable_sample": non_tradable[:20],
            "path": f"by_market/{market_id}.csv",
        }
        if write:
            _write_overlay_csv(ii_root / "by_market" / f"{market_id}.csv", rows)
            write_json(
                ii_root / "by_market" / f"{market_id}.json",
                {
                    "market": market_id,
                    "as_of": datetime.now(UTC).isoformat(),
                    "stats": stats,
                    "rows": rows,
                },
                compact=True,
            )
            logger.info(
                "II overlay %s: %d/%d tradable (assumed/curated)",
                market_id,
                stats["tradable_count"],
                stats["ticker_count"],
            )

    summary = {
        "schema_version": 1,
        "as_of": datetime.now(UTC).isoformat(),
        "policy_as_of": policy.get("as_of"),
        "source_urls": policy.get("source_urls"),
        "note": (
            "Advisory overlay only — does not filter library screens or the live "
            "FTSE 350 path. Full verified instrument catalog remains L34."
        ),
        "markets": per_market,
        "next_slices": policy.get("next_slices") or [],
        "totals": {
            "markets": len(per_market),
            "tickers": sum(m["ticker_count"] for m in per_market.values()),
            "tradable": sum(m["tradable_count"] for m in per_market.values()),
            "unknown_venue": sum(m["unknown_venue_count"] for m in per_market.values()),
        },
    }
    if write:
        write_json(ii_root / SUMMARY_NAME, summary, compact=False)
        # Lightweight README for humans browsing the tree.
        readme = ii_root / "README.md"
        readme.write_text(
            "\n".join(
                [
                    "# Interactive Investor coverage overlay (L34 v1)",
                    "",
                    "Exchange-allowlist mapping from II public pages onto offline library tickers.",
                    "",
                    "- `policy.json` — published venues (Yahoo suffixes + MICs) + next slices",
                    "- `exceptions.json` — curated ticker overrides",
                    "- `by_market/*.csv` — per-ticker overlay joined by Yahoo ticker",
                    "- `summary.json` — rollup stats",
                    "- `unavailable_watch.json` — optional bypass seed for unactionable II names",
                    "- `firds_ii_mics.*` — optional FIRDS MIC filter output",
                    "",
                    "**Not** a full broker instrument book. Do not scrape logged-in ii.co.uk.",
                    "Does not change live FTSE 350 screening.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return summary


def annotate_shortlist_rows(
    rows: list[dict[str, Any]],
    *,
    market_id: str | None = None,
    library_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Attach II overlay fields to shortlist/signal dict rows (advisory)."""
    library_root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    policy = load_ii_policy(ii_coverage_root(library_root))
    exceptions = load_ii_exceptions(ii_coverage_root(library_root))
    annotated: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "")
        mid = market_id or row.get("market")
        overlay = classify_ticker(
            ticker,
            market_id=str(mid) if mid else None,
            policy=policy,
            exceptions=exceptions,
        )
        merged = dict(row)
        merged["tradable_on_ii"] = overlay["tradable_on_ii"]
        merged["ii_deal_channel"] = overlay["deal_channel"]
        merged["ii_confidence"] = overlay["confidence"]
        merged["ii_exchange"] = overlay["ii_exchange"]
        merged["ii_basis"] = overlay.get("basis")
        annotated.append(merged)
    return annotated


def annotate_dashboard_reports(
    reports: list[dict[str, Any]],
    *,
    library_root: Path | None = None,
    market_id: str | None = None,
) -> list[dict[str, Any]]:
    """Annotate live dashboard reports with II overlay fields (advisory)."""
    try:
        return annotate_shortlist_rows(
            reports, market_id=market_id, library_root=library_root
        )
    except FileNotFoundError:
        logger.warning("II coverage policy missing — skipping dashboard annotation")
        return reports
