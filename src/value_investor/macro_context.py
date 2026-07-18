"""Offline macro / market-regime context for research and paper notes.

Intentionally **not** wired into quantitative stock scoring. Indicators are
collected per political/currency domain (US, UK, Euro, AU) and attached as
secondary context for memos and paper-fund regime notes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MACRO_ROOT = Path("docs/data/library/macro")

# Yahoo Finance symbols — best-effort free feed for offline context.
DOMAIN_SERIES: dict[str, dict[str, str]] = {
    "us": {
        "policy_proxy_13w_yield": "^IRX",
        "gov_10y_yield": "^TNX",
        "usd_index": "DX-Y.NYB",
    },
    "uk": {
        "gbp_usd": "GBPUSD=X",
        "ftse_100": "^FTSE",
    },
    "euro": {
        "eur_usd": "EURUSD=X",
        "euro_stoxx_50": "^STOXX50E",
    },
    "au": {
        "aud_usd": "AUDUSD=X",
        "asx_200": "^AXJO",
    },
    "ca": {
        "cad_usd": "CADUSD=X",
        "tsx_composite": "^GSPTSE",
    },
    "asia": {
        "usd_index": "DX-Y.NYB",
        "hang_seng": "^HSI",
    },
}

MARKET_TO_DOMAIN: dict[str, str] = {
    "sp500": "us",
    "nasdaq100": "us",
    "us_adr_asia": "us",
    "ftse350": "uk",
    "ftse_smallcap": "uk",
    "aim": "uk",
    "euro_stoxx50": "euro",
    "dax": "euro",
    "cac40": "euro",
    "ibex35": "euro",
    "ftse_mib": "euro",
    "aex": "euro",
    "bel20": "euro",
    "asx200": "au",
    "tsx60": "ca",
    "hang_seng": "asia",
    "sti": "asia",
}


def domain_for_market(market: str | None) -> str:
    m = (market or "").strip().lower()
    return MARKET_TO_DOMAIN.get(m, "us")


def _latest_close(symbol: str) -> dict[str, Any] | None:
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance unavailable for macro fetch")
        return None
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        if hist is None or hist.empty:
            return {"symbol": symbol, "value": None, "error": "no history"}
        close = float(hist["Close"].dropna().iloc[-1])
        as_of = hist.index[-1]
        as_of_s = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
        return {"symbol": symbol, "value": round(close, 4), "as_of": as_of_s}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Macro fetch failed for %s: %s", symbol, exc)
        return {"symbol": symbol, "value": None, "error": str(exc)}


def fetch_macro_snapshot(*, domains: list[str] | None = None) -> dict[str, Any]:
    """Fetch latest Yahoo markers for each domain (context only — not for scoring)."""
    wanted = domains or list(DOMAIN_SERIES)
    snapshot: dict[str, Any] = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "note": (
            "Offline macro / regime context only. Do not use these series to "
            "auto-veto or reweight quantitative screen signals."
        ),
        "domains": {},
    }
    for domain in wanted:
        series = DOMAIN_SERIES.get(domain) or {}
        markers: dict[str, Any] = {}
        for key, symbol in series.items():
            markers[key] = _latest_close(symbol)
        snapshot["domains"][domain] = {
            "domain": domain,
            "markers": markers,
        }
    return snapshot


def save_macro_snapshot(
    snapshot: dict[str, Any],
    root: Path | None = None,
) -> Path:
    from value_investor.storage import write_json

    root = Path(root or DEFAULT_MACRO_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    latest = root / "latest.json"
    dated = root / f"{datetime.now(UTC).date().isoformat()}.json"
    write_json(latest, snapshot, compact=False, compress=False)
    write_json(dated, snapshot, compact=False, compress=False)
    return latest


def load_macro_snapshot(root: Path | None = None) -> dict[str, Any] | None:
    from value_investor.storage import read_json, resolve_json_path

    path = Path(root or DEFAULT_MACRO_ROOT) / "latest.json"
    resolved = resolve_json_path(path)
    if resolved is None:
        return None
    return read_json(resolved)


def refresh_macro_library(root: Path | None = None) -> dict[str, Any]:
    snapshot = fetch_macro_snapshot()
    path = save_macro_snapshot(snapshot, root=root)
    snapshot["path"] = str(path)
    return snapshot


def macro_context_for_market(
    market: str | None,
    *,
    root: Path | None = None,
    refresh_if_missing: bool = True,
) -> dict[str, Any]:
    """
    Slice of the macro library for one market domain.

    Always includes FX vs USD where available plus a short regime note.
    """
    snapshot = load_macro_snapshot(root)
    if snapshot is None and refresh_if_missing:
        snapshot = refresh_macro_library(root)
    elif snapshot is None:
        snapshot = {"fetched_at": None, "domains": {}, "note": "macro snapshot missing"}

    domain = domain_for_market(market)
    block = (snapshot.get("domains") or {}).get(domain) or {
        "domain": domain,
        "markers": {},
    }
    return {
        "market": market,
        "domain": domain,
        "fetched_at": snapshot.get("fetched_at"),
        "note": (
            "Secondary regime context only — do not treat as a scoring input or "
            "automatic veto of the quantitative screen signal."
        ),
        "library_note": snapshot.get("note"),
        "markers": block.get("markers") or {},
        "related_domains": {
            key: (snapshot.get("domains") or {}).get(key)
            for key in ("us", "uk", "euro", "au", "ca")
            if key != domain and (snapshot.get("domains") or {}).get(key)
        },
    }


def macro_regime_note(market: str | None, *, root: Path | None = None) -> str:
    """One-line note suitable for paper-fund equity-curve marks."""
    ctx = macro_context_for_market(market, root=root, refresh_if_missing=False)
    domain = ctx.get("domain")
    markers = ctx.get("markers") or {}
    bits: list[str] = [f"macro[{domain}]"]
    for key, row in markers.items():
        if not isinstance(row, dict) or row.get("value") is None:
            continue
        bits.append(f"{key}={row['value']}")
        if len(bits) >= 4:
            break
    if len(bits) == 1:
        return f"macro[{domain}]: unavailable"
    return "; ".join(bits)
