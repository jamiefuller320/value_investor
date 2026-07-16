"""Progressive multi-market data library (offline from the live FTSE 350 screen)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

import pandas as pd

from value_investor.constituents import (
    WIKIPEDIA_USER_AGENT,
    fetch_universe_constituents,
    to_lse_ticker,
)
from value_investor.fetch import fetch_company_metrics
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_LIBRARY_ROOT = Path("output/library")
DEFAULT_MAX_TICKERS_PER_RUN = 25
DEFAULT_STALE_DAYS = 14
DEFAULT_RETENTION_DAYS = 400  # ~13 months of daily-ish snapshots per market


@dataclass(frozen=True)
class MarketSpec:
    market_id: str
    label: str
    exchange: str
    currency: str
    yahoo_suffix: str  # "" for US, ".L" handled via to_lse_ticker, ".AX" for ASX
    constituent_source: str


def _wiki_tables(url: str) -> list[pd.DataFrame]:
    request = Request(url, headers={"User-Agent": WIKIPEDIA_USER_AGENT})
    with urlopen(request, timeout=60) as response:  # noqa: S310 — curated Wikipedia URLs
        html = response.read().decode("utf-8", errors="replace")
    return pd.read_html(html)


def _pick_constituent_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    for table in tables:
        cols = {str(c).strip().lower() for c in table.columns}
        if {"ticker", "symbol"} & cols or any("ticker" in c or "symbol" in c for c in cols):
            return table
        if "company" in cols or "name" in cols:
            # Prefer tables that also look like listings
            if any("ticker" in str(c).lower() or "symbol" in str(c).lower() for c in table.columns):
                return table
    if not tables:
        raise ValueError("No HTML tables found")
    return tables[0]


def _normalize_wiki_constituents(
    table: pd.DataFrame,
    *,
    market_id: str,
    yahoo_suffix: str,
    index_label: str,
) -> pd.DataFrame:
    rename: dict[str, str] = {}
    for col in table.columns:
        key = str(col).strip().lower()
        if key in {"ticker", "symbol", "epic", "code"} or "ticker" in key or "symbol" in key:
            rename[col] = "raw_ticker"
        elif key in {"company", "name", "security", "stock"} or "company" in key:
            rename[col] = "name"
        elif "sector" in key or "industry" in key:
            rename[col] = "sector"
    frame = table.rename(columns=rename).copy()
    if "raw_ticker" not in frame.columns:
        raise ValueError(f"Could not find ticker column for {market_id}")
    if "name" not in frame.columns:
        frame["name"] = frame["raw_ticker"]
    if "sector" not in frame.columns:
        frame["sector"] = None

    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        raw = str(row["raw_ticker"]).strip()
        if not raw or raw.lower() == "nan":
            continue
        raw = raw.split(" ")[0].replace("\xa0", "")
        if yahoo_suffix == ".L":
            ticker = to_lse_ticker(raw)
        elif yahoo_suffix:
            base = raw.replace(".", "-")
            ticker = base if base.endswith(yahoo_suffix) else f"{base}{yahoo_suffix}"
        else:
            ticker = raw.replace(".", "-")
        rows.append(
            {
                "ticker": ticker,
                "name": str(row.get("name") or ticker),
                "sector": None if pd.isna(row.get("sector")) else str(row.get("sector")),
                "epic": raw,
                "index": index_label,
                "market": market_id,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.drop_duplicates("ticker", keep="first").reset_index(drop=True)


def fetch_sp500_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="sp500", yahoo_suffix="", index_label="S&P 500"
    )


def fetch_euro_stoxx50_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/EURO_STOXX_50")
    table = _pick_constituent_table(tables)
    # EURO STOXX 50 tickers on Wikipedia are often exchange-local; keep as-is for Yahoo best-effort.
    return _normalize_wiki_constituents(
        table, market_id="euro_stoxx50", yahoo_suffix="", index_label="EURO STOXX 50"
    )


def fetch_asx200_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/S%26P/ASX_200")
    table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="asx200", yahoo_suffix=".AX", index_label="S&P/ASX 200"
    )


def fetch_ftse350_library_constituents() -> pd.DataFrame:
    frame = fetch_universe_constituents("ftse350").copy()
    frame["market"] = "ftse350"
    return frame


MARKET_REGISTRY: dict[str, MarketSpec] = {
    "ftse350": MarketSpec(
        market_id="ftse350",
        label="FTSE 350",
        exchange="LSE",
        currency="GBP",
        yahoo_suffix=".L",
        constituent_source="wikipedia+local",
    ),
    "sp500": MarketSpec(
        market_id="sp500",
        label="S&P 500",
        exchange="US",
        currency="USD",
        yahoo_suffix="",
        constituent_source="wikipedia",
    ),
    "euro_stoxx50": MarketSpec(
        market_id="euro_stoxx50",
        label="EURO STOXX 50",
        exchange="EU",
        currency="EUR",
        yahoo_suffix="",
        constituent_source="wikipedia",
    ),
    "asx200": MarketSpec(
        market_id="asx200",
        label="S&P/ASX 200",
        exchange="ASX",
        currency="AUD",
        yahoo_suffix=".AX",
        constituent_source="wikipedia",
    ),
}

CONSTITUENT_FETCHERS: dict[str, Callable[[], pd.DataFrame]] = {
    "ftse350": fetch_ftse350_library_constituents,
    "sp500": fetch_sp500_constituents,
    "euro_stoxx50": fetch_euro_stoxx50_constituents,
    "asx200": fetch_asx200_constituents,
}


def list_markets() -> list[dict[str, Any]]:
    return [
        {
            "market_id": spec.market_id,
            "label": spec.label,
            "exchange": spec.exchange,
            "currency": spec.currency,
            "constituent_source": spec.constituent_source,
        }
        for spec in MARKET_REGISTRY.values()
    ]


def market_dir(root: Path, market_id: str) -> Path:
    return Path(root) / "markets" / market_id


def manifest_path(root: Path, market_id: str) -> Path:
    return market_dir(root, market_id) / "manifest.json"


def empty_manifest(spec: MarketSpec) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "market": spec.market_id,
        "label": spec.label,
        "exchange": spec.exchange,
        "currency": spec.currency,
        "constituent_source": spec.constituent_source,
        "tickers": [],
        "ticker_count": 0,
        "covered_tickers": [],
        "coverage_count": 0,
        "coverage_pct": 0.0,
        "last_constituents_refresh": None,
        "last_metrics_refresh": None,
        "fields_present": [],
        "ticker_state": {},  # ticker -> {last_refresh, fields_present, errors}
        "paths": {
            "constituents_latest": "constituents/latest.json",
            "metrics_latest": "metrics/latest.json.gz",
        },
        "note": "Offline library — not used by the live FTSE 350 screen until explicitly incorporated.",
    }


def load_manifest(root: Path, market_id: str) -> dict[str, Any]:
    path = manifest_path(root, market_id)
    if not path.exists():
        return empty_manifest(MARKET_REGISTRY[market_id])
    return read_json(path)


def save_manifest(root: Path, market_id: str, manifest: dict[str, Any]) -> Path:
    return write_json(manifest_path(root, market_id), manifest, compact=False)


def refresh_constituents(root: Path, market_id: str) -> dict[str, Any]:
    if market_id not in MARKET_REGISTRY:
        raise ValueError(f"Unknown market {market_id!r}; known: {', '.join(MARKET_REGISTRY)}")
    spec = MARKET_REGISTRY[market_id]
    fetcher = CONSTITUENT_FETCHERS[market_id]
    frame = fetcher()
    as_of = datetime.now(UTC).date().isoformat()
    base = market_dir(root, market_id)
    records = frame.to_dict(orient="records")
    write_json(base / "constituents" / "latest.json", records, compact=False)
    write_json(base / "constituents" / f"{as_of}.json", records, compact=False)

    manifest = load_manifest(root, market_id)
    tickers = [str(r["ticker"]) for r in records]
    manifest.update(
        {
            "tickers": tickers,
            "ticker_count": len(tickers),
            "last_constituents_refresh": datetime.now(UTC).isoformat(),
            "label": spec.label,
            "exchange": spec.exchange,
            "currency": spec.currency,
        }
    )
    # Drop state for names that left the index (survivorship: keep dated constituent files).
    state = dict(manifest.get("ticker_state") or {})
    manifest["ticker_state"] = {t: state[t] for t in tickers if t in state}
    _recompute_coverage(manifest)
    save_manifest(root, market_id, manifest)
    return manifest


def _metric_field_names(row: dict[str, Any]) -> list[str]:
    skip = {"ticker", "name", "sector", "errors", "data_sources"}
    return sorted(
        key
        for key, value in row.items()
        if key not in skip and value is not None and value != ""
    )


def _select_refresh_tickers(
    manifest: dict[str, Any],
    *,
    max_tickers: int,
    stale_days: int,
    now: datetime | None = None,
) -> list[str]:
    now = now or datetime.now(UTC)
    stale_before = now - timedelta(days=stale_days)
    state = manifest.get("ticker_state") or {}
    never: list[str] = []
    stale: list[str] = []
    fresh: list[str] = []
    for ticker in manifest.get("tickers") or []:
        entry = state.get(ticker) or {}
        last = entry.get("last_refresh")
        if not last:
            never.append(ticker)
            continue
        try:
            stamp = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        except ValueError:
            never.append(ticker)
            continue
        if stamp < stale_before:
            stale.append(ticker)
        else:
            fresh.append(ticker)
    ordered = never + stale + fresh
    return ordered[: max(0, max_tickers)]


def refresh_metrics(
    root: Path,
    market_id: str,
    *,
    max_tickers: int = DEFAULT_MAX_TICKERS_PER_RUN,
    stale_days: int = DEFAULT_STALE_DAYS,
    fetch_fn: Callable[[str, str | None, str | None], Any] | None = None,
) -> dict[str, Any]:
    """
    Progressively refresh fundamentals for a market.

    Prefers never-fetched tickers, then stale ones, capped by ``max_tickers``
    so libraries can grow across many scheduled runs without hammering APIs.
    """
    if market_id not in MARKET_REGISTRY:
        raise ValueError(f"Unknown market {market_id!r}")
    manifest = load_manifest(root, market_id)
    if not manifest.get("tickers"):
        manifest = refresh_constituents(root, market_id)

    constituents_path = market_dir(root, market_id) / "constituents" / "latest.json"
    by_ticker: dict[str, dict[str, Any]] = {}
    if constituents_path.exists():
        for row in read_json(constituents_path):
            by_ticker[str(row["ticker"])] = row

    selected = _select_refresh_tickers(
        manifest, max_tickers=max_tickers, stale_days=stale_days
    )
    fetch = fetch_fn or (
        lambda ticker, name, sector: fetch_company_metrics(ticker, name=name, sector=sector)
    )

    metrics_path = market_dir(root, market_id) / "metrics" / "latest.json.gz"
    existing_rows: list[dict[str, Any]] = []
    if metrics_path.exists() or metrics_path.with_suffix("").exists():
        try:
            existing_rows = list(read_json(metrics_path))
        except FileNotFoundError:
            existing_rows = []
    by_metrics = {str(r.get("ticker")): r for r in existing_rows if r.get("ticker")}

    updated = 0
    errors = 0
    field_union: set[str] = set()
    for ticker in selected:
        meta = by_ticker.get(ticker) or {"ticker": ticker}
        try:
            metrics = fetch(ticker, meta.get("name"), meta.get("sector"))
            row = metrics.to_dict() if hasattr(metrics, "to_dict") else dict(metrics)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Library fetch failed for %s: %s", ticker, exc)
            row = {
                "ticker": ticker,
                "name": meta.get("name"),
                "sector": meta.get("sector"),
                "errors": [str(exc)],
            }
            errors += 1
        fields = _metric_field_names(row)
        field_union.update(fields)
        by_metrics[ticker] = row
        state = dict(manifest.get("ticker_state") or {})
        state[ticker] = {
            "last_refresh": datetime.now(UTC).isoformat(),
            "fields_present": fields,
            "errors": list(row.get("errors") or []),
        }
        manifest["ticker_state"] = state
        updated += 1

    rows = list(by_metrics.values())
    as_of = datetime.now(UTC).date().isoformat()
    write_json(metrics_path, rows, compact=True, compress=True)
    write_json(
        market_dir(root, market_id) / "metrics" / f"{as_of}.json.gz",
        rows,
        compact=True,
        compress=True,
    )

    # Union fields across all covered tickers for manifest summary
    for row in rows:
        field_union.update(_metric_field_names(row))
    manifest["fields_present"] = sorted(field_union)
    manifest["last_metrics_refresh"] = datetime.now(UTC).isoformat()
    _recompute_coverage(manifest)
    save_manifest(root, market_id, manifest)
    return {
        "market": market_id,
        "selected": selected,
        "updated": updated,
        "errors": errors,
        "coverage_count": manifest.get("coverage_count"),
        "coverage_pct": manifest.get("coverage_pct"),
        "ticker_count": manifest.get("ticker_count"),
    }


def _recompute_coverage(manifest: dict[str, Any]) -> None:
    tickers = list(manifest.get("tickers") or [])
    state = manifest.get("ticker_state") or {}
    covered = [t for t in tickers if (state.get(t) or {}).get("last_refresh")]
    manifest["covered_tickers"] = covered
    manifest["coverage_count"] = len(covered)
    manifest["coverage_pct"] = round((len(covered) / len(tickers)), 4) if tickers else 0.0


def _freshness_buckets(
    manifest: dict[str, Any],
    *,
    stale_days: int = DEFAULT_STALE_DAYS,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    stale_before = now - timedelta(days=stale_days)
    state = manifest.get("ticker_state") or {}
    never = stale = fresh = 0
    for ticker in manifest.get("tickers") or []:
        entry = state.get(ticker) or {}
        last = entry.get("last_refresh")
        if not last:
            never += 1
            continue
        try:
            stamp = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        except ValueError:
            never += 1
            continue
        if stamp < stale_before:
            stale += 1
        else:
            fresh += 1
    return {"never_fetched": never, "stale": stale, "fresh": fresh}


def library_status(
    root: Path,
    markets: list[str] | None = None,
    *,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    selected = markets or list(MARKET_REGISTRY)
    for market_id in selected:
        if market_id not in MARKET_REGISTRY:
            raise ValueError(f"Unknown market {market_id!r}")
        spec = MARKET_REGISTRY[market_id]
        manifest = load_manifest(root, market_id)
        buckets = _freshness_buckets(manifest, stale_days=stale_days)
        rows.append(
            {
                "market": market_id,
                "label": spec.label,
                "ticker_count": manifest.get("ticker_count") or 0,
                "coverage_count": manifest.get("coverage_count") or 0,
                "coverage_pct": manifest.get("coverage_pct") or 0.0,
                "last_constituents_refresh": manifest.get("last_constituents_refresh"),
                "last_metrics_refresh": manifest.get("last_metrics_refresh"),
                "fields_present": len(manifest.get("fields_present") or []),
                **buckets,
            }
        )
    return rows


def apply_library_retention(root: Path, *, keep_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Prune dated constituent/metrics snapshots older than keep_days; keep latest.*."""
    cutoff = datetime.now(UTC).date() - timedelta(days=keep_days)
    removed = 0
    root = Path(root)
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if name.startswith("latest"):
            continue
        if name == "manifest.json":
            continue
        stem = name.split(".")[0]
        try:
            file_date = datetime.strptime(stem[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def grow_library(
    root: Path,
    markets: list[str] | None = None,
    *,
    max_tickers_per_run: int = DEFAULT_MAX_TICKERS_PER_RUN,
    stale_days: int = DEFAULT_STALE_DAYS,
    refresh_constituents_first: bool = True,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    fetch_fn: Callable[[str, str | None, str | None], Any] | None = None,
) -> list[dict[str, Any]]:
    """Refresh constituents (optional) and progressively fill metrics for each market."""
    selected_markets = markets or list(MARKET_REGISTRY)
    results: list[dict[str, Any]] = []
    for market_id in selected_markets:
        if market_id not in MARKET_REGISTRY:
            raise ValueError(f"Unknown market {market_id!r}")
        if refresh_constituents_first:
            refresh_constituents(root, market_id)
        result = refresh_metrics(
            root,
            market_id,
            max_tickers=max_tickers_per_run,
            stale_days=stale_days,
            fetch_fn=fetch_fn,
        )
        results.append(result)
    if retention_days > 0:
        apply_library_retention(root, keep_days=retention_days)
    write_json(
        Path(root) / "library_status.json",
        {
            "updated_at": datetime.now(UTC).isoformat(),
            "markets": library_status(root, markets=selected_markets, stale_days=stale_days),
            "last_grow": results,
        },
        compact=False,
    )
    return results
