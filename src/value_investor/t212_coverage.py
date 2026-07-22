"""Trading 212 coverage overlay — tradable north star (catalogue + allowlist fallback).

Primary source: authenticated T212 instrument catalogue
(``GET /api/v0/equity/metadata/instruments``), joined by ISIN then shortName/epic.

Fallback: venue allowlist in ``policy.json`` (legacy exchange heuristics) when the
catalogue is missing or a ticker cannot be matched. Advisory only — does not
filter live FTSE 350 screening.
"""

from __future__ import annotations

import csv
import logging
import re
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

DEFAULT_T212_ROOT = DEFAULT_LIBRARY_ROOT / "t212_coverage"
# Legacy path kept for one-release reads / migration.
LEGACY_II_ROOT = DEFAULT_LIBRARY_ROOT / "ii_coverage"

POLICY_NAME = "policy.json"
EXCEPTIONS_NAME = "exceptions.json"
SUMMARY_NAME = "summary.json"
CATALOGUE_DIR = "catalogue"
INSTRUMENTS_NAME = "instruments.json"
EXCHANGES_NAME = "exchanges.json"
INDEX_NAME = "index.json"
META_NAME = "fetched_at.json"

# Yahoo suffix → candidate T212 ticker exchange codes (middle segment of AAPL_US_EQ).
DEFAULT_SUFFIX_EXCHANGES: dict[str, list[str]] = {
    "": ["US"],
    ".L": ["LN", "UK", "LSE"],
    ".DE": ["DE", "GY", "XE", "EU"],
    ".PA": ["FP", "PA", "FR"],
    ".AS": ["AS", "NA", "NL"],
    ".BR": ["BB", "BR", "BE"],
    ".MI": ["IM", "MI", "IT"],
    ".MC": ["MC", "SM", "ES"],
    ".IR": ["IR", "ID", "IE"],
    ".TO": ["TO", "TSE", "CA"],
    ".AX": ["AU", "AX", "ASX"],
    ".HK": ["HK"],
    ".SI": ["SI", "SG"],
    ".ST": ["ST", "SS", "SE"],
    ".SW": ["SW", "VX", "CH"],
    ".HE": ["HE", "FH", "FI"],
}


def t212_coverage_root(library_root: Path | None = None) -> Path:
    root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    preferred = root / "t212_coverage"
    if preferred.exists():
        return preferred
    legacy = root / "ii_coverage"
    if legacy.exists():
        return legacy
    return preferred


def ii_coverage_root(library_root: Path | None = None) -> Path:
    """Backward-compatible alias → Trading 212 coverage root."""
    return t212_coverage_root(library_root)


def catalogue_dir(library_root: Path | None = None) -> Path:
    return t212_coverage_root(library_root) / CATALOGUE_DIR


def load_t212_policy(t212_root: Path | None = None) -> dict[str, Any]:
    path = (t212_root or DEFAULT_T212_ROOT) / POLICY_NAME
    if not path.exists():
        # Fall back to legacy II policy during migration.
        legacy = LEGACY_II_ROOT / POLICY_NAME
        if legacy.exists() and t212_root is None:
            return read_json(legacy)
        raise FileNotFoundError(f"T212 coverage policy missing: {path}")
    return read_json(path)


def load_ii_policy(ii_root: Path | None = None) -> dict[str, Any]:
    return load_t212_policy(ii_root)


def load_t212_exceptions(t212_root: Path | None = None) -> dict[str, dict[str, Any]]:
    path = (t212_root or DEFAULT_T212_ROOT) / EXCEPTIONS_NAME
    if not path.exists():
        legacy = LEGACY_II_ROOT / EXCEPTIONS_NAME
        if legacy.exists() and t212_root is None:
            path = legacy
        else:
            return {}
    payload = read_json(path)
    raw = payload.get("exceptions") or {}
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def load_ii_exceptions(ii_root: Path | None = None) -> dict[str, dict[str, Any]]:
    return load_t212_exceptions(ii_root)


def yahoo_suffix(ticker: str) -> str:
    """Return Yahoo exchange suffix including leading dot, or '' for bare US symbols."""
    text = (ticker or "").strip().upper()
    if "." not in text:
        return ""
    return "." + text.rsplit(".", 1)[-1]


def yahoo_epic(ticker: str) -> str:
    """Yahoo symbol without exchange suffix (SHEL.L → SHEL, BRK-B → BRK-B)."""
    text = (ticker or "").strip().upper()
    if "." not in text:
        return text
    return text.rsplit(".", 1)[0]


def parse_t212_ticker(t212_ticker: str) -> tuple[str, str | None, str | None]:
    """
    Split ``AAPL_US_EQ`` → (``AAPL``, ``US``, ``EQ``).

    Returns (symbol, exchange_code, instrument_kind). Exchange/kind may be None
    when the ticker does not follow the usual pattern.
    """
    text = (t212_ticker or "").strip().upper()
    if not text:
        return "", None, None
    parts = text.split("_")
    if len(parts) >= 3 and parts[-1] in {"EQ", "ETF", "CFD", "WAR"}:
        return "_".join(parts[:-2]), parts[-2], parts[-1]
    if len(parts) == 2:
        return parts[0], parts[1], None
    return text, None, None


def _suffix_index(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in policy.get("exchanges") or []:
        for suf in row.get("yahoo_suffixes") or []:
            key = str(suf)
            if key not in index:
                index[key] = row
    return index


def _suffix_exchange_map(policy: dict[str, Any] | None) -> dict[str, list[str]]:
    merged = {k: list(v) for k, v in DEFAULT_SUFFIX_EXCHANGES.items()}
    custom = (policy or {}).get("yahoo_suffix_to_t212_exchanges") or {}
    for suf, codes in custom.items():
        merged[str(suf)] = [str(c).upper() for c in codes]
    return merged


def normalize_instrument(row: dict[str, Any]) -> dict[str, Any]:
    ticker = str(row.get("ticker") or "").strip()
    symbol, exchange, kind = parse_t212_ticker(ticker)
    short = str(row.get("shortName") or symbol or "").strip().upper()
    isin = str(row.get("isin") or "").strip().upper() or None
    return {
        "ticker": ticker,
        "shortName": short or None,
        "name": row.get("name"),
        "isin": isin,
        "type": row.get("type"),
        "currencyCode": row.get("currencyCode"),
        "exchangeCode": exchange,
        "instrumentKind": kind,
        "symbol": symbol or None,
        "extendedHours": row.get("extendedHours"),
        "maxOpenQuantity": row.get("maxOpenQuantity"),
        "addedOn": row.get("addedOn"),
        "workingScheduleId": row.get("workingScheduleId"),
    }


def build_catalogue_index(instruments: list[dict[str, Any]]) -> dict[str, Any]:
    by_isin: dict[str, list[str]] = {}
    by_short: dict[str, list[str]] = {}
    by_ticker: dict[str, dict[str, Any]] = {}
    type_counts: dict[str, int] = {}

    for raw in instruments:
        if not isinstance(raw, dict):
            continue
        norm = normalize_instrument(raw)
        t212 = norm["ticker"]
        if not t212:
            continue
        by_ticker[t212] = norm
        itype = str(norm.get("type") or "UNKNOWN")
        type_counts[itype] = type_counts.get(itype, 0) + 1
        if norm.get("isin"):
            by_isin.setdefault(str(norm["isin"]), []).append(t212)
        if norm.get("shortName"):
            by_short.setdefault(str(norm["shortName"]), []).append(t212)
        if norm.get("symbol") and norm["symbol"] != norm.get("shortName"):
            by_short.setdefault(str(norm["symbol"]), []).append(t212)

    return {
        "schema_version": 1,
        "instrument_count": len(by_ticker),
        "isin_count": len(by_isin),
        "short_name_count": len(by_short),
        "type_counts": type_counts,
        "by_isin": by_isin,
        "by_short_name": by_short,
        "by_ticker": by_ticker,
    }


def save_catalogue(
    instruments: list[dict[str, Any]],
    *,
    library_root: Path | None = None,
    exchanges: list[dict[str, Any]] | None = None,
    env: str | None = None,
    source: str = "api",
) -> dict[str, Any]:
    """Persist raw instruments + compact index under ``t212_coverage/catalogue/``."""
    cat = catalogue_dir(library_root)
    cat.mkdir(parents=True, exist_ok=True)
    index = build_catalogue_index(instruments)
    fetched_at = datetime.now(UTC).isoformat()
    meta = {
        "schema_version": 1,
        "fetched_at": fetched_at,
        "env": (env or "demo"),
        "source": source,
        "instrument_count": index["instrument_count"],
        "isin_count": index["isin_count"],
        "type_counts": index["type_counts"],
        "exchanges_count": len(exchanges or []),
    }
    write_json(cat / INSTRUMENTS_NAME, instruments, compact=True)
    write_json(cat / INDEX_NAME, index, compact=True)
    write_json(cat / META_NAME, meta, compact=False)
    if exchanges is not None:
        write_json(cat / EXCHANGES_NAME, exchanges, compact=True)
    logger.info(
        "Saved T212 catalogue: %d instruments (%d ISINs) → %s",
        index["instrument_count"],
        index["isin_count"],
        cat,
    )
    return meta


def fetch_and_save_catalogue(
    *,
    library_root: Path | None = None,
    env: str | None = None,
    include_exchanges: bool = True,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> dict[str, Any]:
    from value_investor.t212_client import fetch_exchanges, fetch_instruments, t212_base_url

    instruments = fetch_instruments(env=env, api_key=api_key, api_secret=api_secret)
    exchanges: list[dict[str, Any]] | None = None
    if include_exchanges:
        try:
            exchanges = fetch_exchanges(env=env, api_key=api_key, api_secret=api_secret)
        except Exception as exc:  # noqa: BLE001 — catalogue is primary
            logger.warning("T212 exchanges fetch failed (continuing): %s", exc)
            exchanges = None
    meta = save_catalogue(
        instruments,
        library_root=library_root,
        exchanges=exchanges,
        env=env,
        source=t212_base_url(env),
    )
    return meta


def load_catalogue_index(library_root: Path | None = None) -> dict[str, Any] | None:
    path = catalogue_dir(library_root) / INDEX_NAME
    if not path.exists():
        instruments_path = catalogue_dir(library_root) / INSTRUMENTS_NAME
        if instruments_path.exists():
            instruments = read_json(instruments_path)
            if isinstance(instruments, list):
                return build_catalogue_index(instruments)
        return None
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def load_catalogue_meta(library_root: Path | None = None) -> dict[str, Any] | None:
    path = catalogue_dir(library_root) / META_NAME
    if not path.exists():
        return None
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def _pick_instrument(
    candidates: list[str],
    by_ticker: dict[str, dict[str, Any]],
    *,
    yahoo_suf: str,
    policy: dict[str, Any],
    prefer_types: set[str] | None = None,
) -> dict[str, Any] | None:
    prefer_types = prefer_types or {"STOCK", "ETF"}
    rows = [by_ticker[t] for t in candidates if t in by_ticker]
    if not rows:
        return None
    typed = [r for r in rows if str(r.get("type") or "").upper() in prefer_types]
    if typed:
        rows = typed

    exch_map = _suffix_exchange_map(policy)
    wanted = {c.upper() for c in exch_map.get(yahoo_suf, [])}
    if wanted:
        matched = [
            r
            for r in rows
            if (r.get("exchangeCode") or "").upper() in wanted
        ]
        if len(matched) == 1:
            return matched[0]
        if len(matched) > 1:
            # Prefer STOCK over ETF when still ambiguous.
            stocks = [r for r in matched if str(r.get("type") or "").upper() == "STOCK"]
            return stocks[0] if stocks else matched[0]

    if len(rows) == 1:
        return rows[0]
    # Ambiguous across venues — refuse catalogue hit (fall through to allowlist).
    return None


def match_catalogue(
    ticker: str,
    *,
    isin: str | None = None,
    index: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a normalised T212 instrument for a Yahoo ticker, or None."""
    if index is None:
        return None
    by_ticker = index.get("by_ticker") or {}
    by_isin = index.get("by_isin") or {}
    by_short = index.get("by_short_name") or {}
    policy = policy or {}

    isin_key = (isin or "").strip().upper()
    if isin_key and isin_key in by_isin:
        picked = _pick_instrument(
            list(by_isin[isin_key]),
            by_ticker,
            yahoo_suf=yahoo_suffix(ticker),
            policy=policy,
        )
        if picked:
            return picked

    epic = yahoo_epic(ticker)
    if epic and epic in by_short:
        picked = _pick_instrument(
            list(by_short[epic]),
            by_ticker,
            yahoo_suf=yahoo_suffix(ticker),
            policy=policy,
        )
        if picked:
            return picked

    # Soft match: strip punctuation from epic (BRK.B / BRK-B variants).
    soft = re.sub(r"[^A-Z0-9]", "", epic)
    if soft and soft != epic:
        for key, tickers in by_short.items():
            if re.sub(r"[^A-Z0-9]", "", key) == soft:
                picked = _pick_instrument(
                    list(tickers),
                    by_ticker,
                    yahoo_suf=yahoo_suffix(ticker),
                    policy=policy,
                )
                if picked:
                    return picked
    return None


def _exception_tradable_flag(exc: dict[str, Any]) -> bool:
    if "tradable_on_t212" in exc:
        return bool(exc.get("tradable_on_t212"))
    return bool(exc.get("tradable_on_ii"))


def _overlay_row(
    *,
    ticker: str,
    market_id: str | None,
    isin: str | None,
    tradable: bool,
    deal_channel: str,
    confidence: str,
    basis: str,
    exchange_label: str | None,
    exception_reason: str | None,
    t212_hit: dict[str, Any] | None = None,
    updated_at: str,
) -> dict[str, Any]:
    t212_ticker = (t212_hit or {}).get("ticker")
    t212_isin = (t212_hit or {}).get("isin") or isin
    return {
        "ticker": ticker,
        "market": market_id,
        "isin": t212_isin or isin,
        # Canonical Trading 212 fields
        "tradable_on_t212": tradable,
        "t212_ticker": t212_ticker,
        "t212_isin": t212_isin,
        "t212_type": (t212_hit or {}).get("type"),
        "t212_currency": (t212_hit or {}).get("currencyCode"),
        "t212_exchange": (t212_hit or {}).get("exchangeCode") or exchange_label,
        "broker": "trading212",
        "broker_basis": basis,
        "broker_confidence": confidence,
        # Legacy aliases (dashboard / older packs)
        "ii_exchange": exchange_label or (t212_hit or {}).get("exchangeCode"),
        "tradable_on_ii": tradable,
        "deal_channel": deal_channel,
        "confidence": confidence,
        "basis": basis,
        "exception_reason": exception_reason,
        "updated_at": updated_at,
    }


def classify_ticker(
    ticker: str,
    *,
    market_id: str | None = None,
    isin: str | None = None,
    policy: dict[str, Any] | None = None,
    exceptions: dict[str, dict[str, Any]] | None = None,
    catalogue_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Classify one Yahoo ticker for Trading 212 tradability.

    Preference: curated exception → catalogue hit → venue allowlist → unknown.
    """
    policy = policy or load_t212_policy()
    exceptions = exceptions if exceptions is not None else load_t212_exceptions()
    key = (ticker or "").strip()
    now = datetime.now(UTC).date().isoformat()

    if key in exceptions:
        exc = exceptions[key]
        tradable = _exception_tradable_flag(exc)
        return _overlay_row(
            ticker=key,
            market_id=market_id,
            isin=exc.get("isin") or isin,
            tradable=tradable,
            deal_channel=exc.get("deal_channel") or ("online" if tradable else "n/a"),
            confidence=exc.get("confidence") or "curated",
            basis=exc.get("basis") or "exception",
            exchange_label=exc.get("t212_exchange") or exc.get("ii_exchange"),
            exception_reason=exc.get("exception_reason"),
            t212_hit={
                "ticker": exc.get("t212_ticker"),
                "isin": exc.get("isin"),
                "type": exc.get("t212_type"),
                "currencyCode": exc.get("t212_currency"),
                "exchangeCode": exc.get("t212_exchange") or exc.get("ii_exchange"),
            }
            if exc.get("t212_ticker") or exc.get("isin")
            else None,
            updated_at=now,
        )

    hit = match_catalogue(
        key,
        isin=isin,
        index=catalogue_index,
        policy=policy,
    )
    if hit is not None:
        return _overlay_row(
            ticker=key,
            market_id=market_id,
            isin=hit.get("isin") or isin,
            tradable=True,
            deal_channel="online",
            confidence="verified",
            basis="catalogue_hit",
            exchange_label=hit.get("exchangeCode"),
            exception_reason=None,
            t212_hit=hit,
            updated_at=now,
        )

    # --- Venue allowlist fallback (assumed) ---
    suf = yahoo_suffix(key)
    by_suffix = _suffix_index(policy)
    exchange_row = by_suffix.get(suf)

    if exchange_row is not None:
        phone_only = bool(exchange_row.get("phone_only"))
        online = bool(exchange_row.get("online_dealable")) and not phone_only
        venues = exchange_row.get("venues") or [
            exchange_row.get("t212_label") or exchange_row.get("ii_label")
        ]
        label = "/".join(str(v) for v in venues if v)
        return _overlay_row(
            ticker=key,
            market_id=market_id,
            isin=isin,
            tradable=online,
            deal_channel="phone" if phone_only else ("online" if online else "n/a"),
            confidence="assumed",
            basis="exchange_allowlist",
            exchange_label=label,
            exception_reason=(
                "Venue listed as phone orders only on legacy allowlist"
                if phone_only
                else (
                    None
                    if online
                    else "Not matched in T212 catalogue; allowlist marks non-online"
                )
            ),
            updated_at=now,
        )

    defaults = (policy.get("market_defaults") or {}).get(market_id or "", {})
    default_tradable = defaults.get("tradable_on_t212")
    if default_tradable is None:
        default_tradable = defaults.get("tradable_on_ii")
    if defaults and default_tradable is not None:
        tradable = bool(default_tradable)
        return _overlay_row(
            ticker=key,
            market_id=market_id,
            isin=isin,
            tradable=tradable,
            deal_channel=defaults.get("deal_channel") or ("online" if tradable else "n/a"),
            confidence=defaults.get("confidence") or "assumed",
            basis=defaults.get("basis") or "market_default",
            exchange_label=defaults.get("t212_exchange") or defaults.get("ii_exchange"),
            exception_reason=None,
            updated_at=now,
        )

    return _overlay_row(
        ticker=key,
        market_id=market_id,
        isin=isin,
        tradable=False,
        deal_channel="n/a",
        confidence="assumed",
        basis="unknown_venue",
        exchange_label=None,
        exception_reason=(
            f"No T212 catalogue match and Yahoo suffix {suf!r} is not on the "
            "fallback venue allowlist"
        ),
        updated_at=now,
    )


def _isin_lookup_for_market(library_root: Path, market_id: str) -> dict[str, str]:
    """Best-effort Yahoo ticker → ISIN from constituents or overlay artifacts."""
    out: dict[str, str] = {}
    path = market_dir(library_root, market_id) / "constituents" / "latest.json"
    if path.exists():
        rows = read_json(path)
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                t = str(row.get("ticker") or "").strip()
                i = str(row.get("isin") or "").strip().upper()
                if t and i:
                    out[t] = i
    return out


def _tickers_for_market(library_root: Path, market_id: str) -> list[str]:
    if market_id not in MARKET_REGISTRY:
        raise ValueError(f"Unknown market {market_id!r}")
    manifest = load_manifest(library_root, market_id)
    tickers = [str(t) for t in (manifest.get("tickers") or []) if t]
    if tickers:
        return tickers
    path = market_dir(library_root, market_id) / "constituents" / "latest.json"
    if path.exists():
        rows = read_json(path)
        return [str(r["ticker"]) for r in rows if isinstance(r, dict) and r.get("ticker")]
    return []


def build_market_overlay(
    library_root: Path,
    market_id: str,
    *,
    policy: dict[str, Any] | None = None,
    exceptions: dict[str, dict[str, Any]] | None = None,
    catalogue_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    root = t212_coverage_root(library_root)
    policy = policy or load_t212_policy(root)
    exceptions = (
        exceptions if exceptions is not None else load_t212_exceptions(root)
    )
    if catalogue_index is None:
        catalogue_index = load_catalogue_index(library_root)
    isins = _isin_lookup_for_market(library_root, market_id)
    return [
        classify_ticker(
            ticker,
            market_id=market_id,
            isin=isins.get(ticker),
            policy=policy,
            exceptions=exceptions,
            catalogue_index=catalogue_index,
        )
        for ticker in _tickers_for_market(library_root, market_id)
    ]


def _write_overlay_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "ticker",
        "market",
        "isin",
        "tradable_on_t212",
        "t212_ticker",
        "t212_isin",
        "t212_type",
        "t212_currency",
        "t212_exchange",
        "broker_basis",
        "broker_confidence",
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
            for bool_key in ("tradable_on_t212", "tradable_on_ii"):
                if isinstance(out.get(bool_key), bool):
                    out[bool_key] = "true" if out[bool_key] else "false"
            writer.writerow(out)


def _market_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    tradable = sum(1 for r in rows if r.get("tradable_on_t212") is True)
    catalogue = sum(1 for r in rows if r.get("broker_basis") == "catalogue_hit")
    phone = sum(1 for r in rows if r.get("deal_channel") == "phone")
    unknown = sum(1 for r in rows if r.get("basis") == "unknown_venue")
    curated = sum(1 for r in rows if r.get("confidence") == "curated")
    return {
        "ticker_count": total,
        "tradable_count": tradable,
        "tradable_pct": round(tradable / total, 4) if total else 0.0,
        "catalogue_hit_count": catalogue,
        "phone_only_count": phone,
        "unknown_venue_count": unknown,
        "curated_exception_count": curated,
    }


def build_t212_overlays(
    library_root: Path | None = None,
    markets: list[str] | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """
    Build per-market Trading 212 overlays for offline library slices.

    Skips ``ftse350`` by default (live screen path); include explicitly if needed.
    """
    library_root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    t212_root = t212_coverage_root(library_root)
    t212_root.mkdir(parents=True, exist_ok=True)
    policy = load_t212_policy(t212_root)
    exceptions = load_t212_exceptions(t212_root)
    catalogue_index = load_catalogue_index(library_root)
    catalogue_meta = load_catalogue_meta(library_root)

    if markets is None:
        markets = [mid for mid in MARKET_REGISTRY if mid != "ftse350"]

    per_market: dict[str, Any] = {}
    for market_id in markets:
        rows = build_market_overlay(
            library_root,
            market_id,
            policy=policy,
            exceptions=exceptions,
            catalogue_index=catalogue_index,
        )
        stats = _market_stats(rows)
        non_tradable = [
            {
                "ticker": r["ticker"],
                "t212_exchange": r.get("t212_exchange"),
                "ii_exchange": r.get("ii_exchange"),
                "deal_channel": r.get("deal_channel"),
                "basis": r.get("basis"),
                "exception_reason": r.get("exception_reason"),
            }
            for r in rows
            if r.get("tradable_on_t212") is not True
        ]
        per_market[market_id] = {
            **stats,
            "non_tradable_sample": non_tradable[:20],
            "path": f"by_market/{market_id}.csv",
        }
        if write:
            _write_overlay_csv(t212_root / "by_market" / f"{market_id}.csv", rows)
            write_json(
                t212_root / "by_market" / f"{market_id}.json",
                {
                    "market": market_id,
                    "broker": "trading212",
                    "as_of": datetime.now(UTC).isoformat(),
                    "stats": stats,
                    "rows": rows,
                },
                compact=True,
            )
            logger.info(
                "T212 overlay %s: %d/%d tradable (%d catalogue hits)",
                market_id,
                stats["tradable_count"],
                stats["ticker_count"],
                stats["catalogue_hit_count"],
            )

    summary = {
        "schema_version": 2,
        "broker": "trading212",
        "as_of": datetime.now(UTC).isoformat(),
        "policy_as_of": policy.get("as_of"),
        "catalogue": catalogue_meta,
        "catalogue_loaded": catalogue_index is not None,
        "source_urls": policy.get("source_urls"),
        "note": (
            "Advisory Trading 212 overlay — catalogue hits are verified presence; "
            "allowlist rows are assumed. Does not filter library screens or the live "
            "FTSE 350 path. Fetch catalogue: ftse-library t212-catalogue."
        ),
        "markets": per_market,
        "next_slices": policy.get("next_slices") or [],
        "totals": {
            "markets": len(per_market),
            "tickers": sum(m["ticker_count"] for m in per_market.values()),
            "tradable": sum(m["tradable_count"] for m in per_market.values()),
            "catalogue_hits": sum(
                m.get("catalogue_hit_count", 0) for m in per_market.values()
            ),
            "unknown_venue": sum(m["unknown_venue_count"] for m in per_market.values()),
        },
    }
    if write:
        write_json(t212_root / SUMMARY_NAME, summary, compact=False)
        (t212_root / "README.md").write_text(
            "\n".join(
                [
                    "# Trading 212 coverage overlay",
                    "",
                    "Tradable north star for offline library markets.",
                    "",
                    "- `catalogue/` — instruments dump + compact ISIN/shortName index "
                    "(`ftse-library t212-catalogue`)",
                    "- `policy.json` — suffix↔exchange hints + venue allowlist fallback",
                    "- `exceptions.json` — curated ticker overrides",
                    "- `by_market/*` — per-ticker overlay (`ftse-library t212-overlay`)",
                    "- `summary.json` — rollup stats",
                    "- `unavailable_watch.json` — dashboard bypass seed",
                    "",
                    "Does not change live FTSE 350 screening. No live order placement.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return summary


def build_ii_overlays(
    library_root: Path | None = None,
    markets: list[str] | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Backward-compatible alias for :func:`build_t212_overlays`."""
    return build_t212_overlays(library_root, markets, write=write)


def annotate_shortlist_rows(
    rows: list[dict[str, Any]],
    *,
    market_id: str | None = None,
    library_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Attach Trading 212 overlay fields to shortlist/signal dict rows (advisory)."""
    library_root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    root = t212_coverage_root(library_root)
    policy = load_t212_policy(root)
    exceptions = load_t212_exceptions(root)
    catalogue_index = load_catalogue_index(library_root)
    annotated: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "")
        mid = market_id or row.get("market")
        overlay = classify_ticker(
            ticker,
            market_id=str(mid) if mid else None,
            isin=str(row["isin"]).strip().upper() if row.get("isin") else None,
            policy=policy,
            exceptions=exceptions,
            catalogue_index=catalogue_index,
        )
        merged = dict(row)
        merged["tradable_on_t212"] = overlay["tradable_on_t212"]
        merged["t212_ticker"] = overlay.get("t212_ticker")
        merged["t212_isin"] = overlay.get("t212_isin")
        merged["t212_type"] = overlay.get("t212_type")
        merged["t212_currency"] = overlay.get("t212_currency")
        merged["broker_basis"] = overlay.get("broker_basis")
        merged["broker_confidence"] = overlay.get("broker_confidence")
        # Legacy aliases
        merged["tradable_on_ii"] = overlay["tradable_on_t212"]
        merged["ii_tradable"] = overlay["tradable_on_t212"]
        merged["ii_deal_channel"] = overlay["deal_channel"]
        merged["ii_confidence"] = overlay["confidence"]
        merged["ii_exchange"] = overlay.get("ii_exchange")
        merged["ii_basis"] = overlay.get("basis")
        annotated.append(merged)
    return annotated


def annotate_dashboard_reports(
    reports: list[dict[str, Any]],
    *,
    library_root: Path | None = None,
    market_id: str | None = None,
) -> list[dict[str, Any]]:
    """Annotate live dashboard reports with T212 overlay fields (advisory)."""
    try:
        return annotate_shortlist_rows(
            reports, market_id=market_id, library_root=library_root
        )
    except FileNotFoundError:
        logger.warning("T212 coverage policy missing — skipping dashboard annotation")
        return reports
