"""Offline macro / market-regime context for research and paper notes.

Intentionally **not** wired into quantitative stock scoring. Indicators are
collected per political/currency domain (US, UK, Euro, AU) and attached as
secondary context for memos and paper-fund regime notes.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
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
        "sp500": "^GSPC",
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
    "euro_depth": "euro",
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
    "atx": "euro",
    "psi20": "euro",
    "smi": "euro",
    "omxs30": "euro",
    "iseq20": "euro",
}


# Equity indexes used by dashboard held-vs-market (dated snapshots, no live fetch).
EQUITY_INDEX_MARKERS: dict[str, tuple[str, str]] = {
    "uk": ("ftse_100", "^FTSE"),
    "euro": ("euro_stoxx_50", "^STOXX50E"),
    "au": ("asx_200", "^AXJO"),
    "ca": ("tsx_composite", "^GSPTSE"),
    "asia": ("hang_seng", "^HSI"),
    "us": ("sp500", "^GSPC"),
}

_DATED_MACRO = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


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


def _macro_date_key(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.date().isoformat()
    except ValueError:
        return None


def fetch_symbol_closes(
    symbol: str,
    *,
    start: str,
    end: str | None = None,
) -> dict[str, float]:
    """Yahoo daily closes for one symbol. Not used on dashboard refresh."""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance unavailable for %s history", symbol)
        return {}
    kwargs: dict[str, Any] = {"start": start}
    if end:
        kwargs["end"] = end
    try:
        hist = yf.Ticker(symbol).history(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.info("Index history failed for %s: %s", symbol, exc)
        return {}
    if hist is None or hist.empty or "Close" not in hist.columns:
        return {}
    out: dict[str, float] = {}
    for stamp, row in hist.iterrows():
        day = _macro_date_key(stamp.isoformat() if hasattr(stamp, "isoformat") else str(stamp))
        try:
            close = float(row["Close"])
        except (TypeError, ValueError):
            continue
        if day and close == close and close > 0:
            out[day] = round(close, 4)
    return out


def _close_on_or_before(closes: dict[str, float], day: str) -> tuple[str, float] | None:
    if day in closes:
        return day, closes[day]
    prior = [key for key in closes if key <= day]
    if not prior:
        return None
    key = max(prior)
    return key, closes[key]


def backfill_equity_index_snapshots(
    root: Path | None = None,
    *,
    closes_by_symbol: dict[str, dict[str, float]] | None = None,
    fetch_missing: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write equity-index markers into dated macro files (and ``latest.json``).

    Dashboard ``held_vs_market`` only *reads* these files — it does not fetch.
    """
    from value_investor.storage import read_json, write_json

    macro_root = Path(root or DEFAULT_MACRO_ROOT)
    dated = sorted(path for path in macro_root.glob("*.json") if _DATED_MACRO.match(path.name))
    targets = list(dated)
    latest = macro_root / "latest.json"
    if latest.exists():
        targets.append(latest)
    if not targets:
        return {"patched": 0, "skipped": 0, "fetched": [], "files": 0}

    start = dated[0].stem if dated else datetime.now(UTC).date().isoformat()
    # Pad start so weekend/holiday files can forward-fill from the prior session.
    try:
        start = (datetime.fromisoformat(start).date() - timedelta(days=7)).isoformat()
    except ValueError:
        pass
    provided = {str(sym): dict(series) for sym, series in (closes_by_symbol or {}).items()}
    fetched: list[str] = []
    if fetch_missing:
        needed: set[str] = set()
        for path in targets:
            snapshot = read_json(path)
            if not isinstance(snapshot, dict):
                needed.update(symbol for _key, symbol in EQUITY_INDEX_MARKERS.values())
                continue
            domains = snapshot.get("domains") or {}
            for domain, (marker_key, symbol) in EQUITY_INDEX_MARKERS.items():
                if symbol in provided:
                    continue
                marker = ((domains.get(domain) or {}).get("markers") or {}).get(marker_key)
                if not isinstance(marker, dict) or marker.get("value") is None:
                    needed.add(symbol)
        for symbol in sorted(needed):
            series = fetch_symbol_closes(symbol, start=start)
            if series:
                provided[symbol] = series
                fetched.append(symbol)

    patched = 0
    skipped = 0
    for path in targets:
        match = _DATED_MACRO.match(path.name)
        file_day = (
            match.group(1)
            if match
            else _macro_date_key(str((read_json(path) or {}).get("fetched_at") or ""))
        )
        if not file_day and path.name == "latest.json" and dated:
            file_day = dated[-1].stem
        if not file_day:
            skipped += 1
            continue
        snapshot = read_json(path)
        if not isinstance(snapshot, dict):
            skipped += 1
            continue
        domains = snapshot.setdefault("domains", {})
        changed = False
        for domain, (marker_key, symbol) in EQUITY_INDEX_MARKERS.items():
            series = provided.get(symbol) or {}
            picked = _close_on_or_before(series, file_day)
            if picked is None:
                continue
            as_of, value = picked
            block = domains.setdefault(domain, {"domain": domain, "markers": {}})
            markers = block.setdefault("markers", {})
            existing = markers.get(marker_key)
            if not overwrite and isinstance(existing, dict) and existing.get("value") is not None:
                continue
            markers[marker_key] = {
                "symbol": symbol,
                "value": value,
                "as_of": as_of,
            }
            changed = True
        if changed:
            write_json(path, snapshot, compact=False, compress=False)
            patched += 1
        else:
            skipped += 1
    return {
        "patched": patched,
        "skipped": skipped,
        "fetched": fetched,
        "files": len(targets),
        "start": start,
    }
