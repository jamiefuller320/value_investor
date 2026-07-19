"""Progressive multi-market data library (offline from the live FTSE 350 screen)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Literal
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

DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_MAX_TICKERS_PER_RUN = 25
DEFAULT_STALE_DAYS = 14
# Dense PIT window: keep every dated metrics/constituents snapshot.
DEFAULT_RETENTION_DAYS = 400  # ~13 months of daily-ish snapshots per market
# After the dense window, keep one snapshot per calendar month until this age.
DEFAULT_MONTHLY_UNTIL_DAYS = DEFAULT_RETENTION_DAYS + 3 * 365  # ~4 years total
# Older than monthly_until: keep one per calendar quarter indefinitely (cheap coarse history).

_DATED_SNAPSHOT_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\.json(?:\.gz)?)$")
RetentionResolution = Literal["all", "month", "quarter"]


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
    # StringIO required — passing a raw HTML string can be mis-handled as a path/URL.
    try:
        return pd.read_html(StringIO(html), flavor="lxml")
    except ValueError:
        return pd.read_html(StringIO(html), flavor="html5lib")


# Wikipedia already lists Yahoo-qualified symbols for these markets
# (e.g. ADS.DE, AIR.PA). Do not append exchange suffixes or rewrite dots.
PREQUALIFIED_YAHOO_MARKETS = frozenset(
    {
        "euro_stoxx50",
        "dax",
        "cac40",
        "ibex35",
        "ftse_mib",
        "aex",
        "bel20",
    }
)


def _strip_exchange_prefix(raw: str) -> str:
    """Strip Wikipedia prefixes like ``SEHK:``, ``SGX:``, ``Euronext Brussels:``."""
    text = str(raw or "").replace("\xa0", " ").strip()
    if ":" in text:
        text = text.split(":", 1)[1].strip()
    return text


def _to_hk_yahoo(raw: str) -> str:
    """Map Wikipedia Hang Seng codes (``SEHK: 5``) to Yahoo (``0005.HK``)."""
    code = _strip_exchange_prefix(raw).upper().replace(" ", "")
    if code.endswith(".HK"):
        return code
    if code.isdigit():
        return f"{int(code):04d}.HK"
    return f"{code}.HK"


def _to_sg_yahoo(raw: str) -> str:
    code = _strip_exchange_prefix(raw).upper().replace(" ", "")
    if code.endswith(".SI"):
        return code
    return f"{code}.SI"


def _to_bel_yahoo(raw: str) -> str:
    code = _strip_exchange_prefix(raw).upper().replace(" ", "")
    if code.endswith(".BR"):
        return code
    if code.endswith("-BR"):
        return code[:-3] + ".BR"
    return f"{code}.BR"


def _pick_constituent_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """Prefer the largest listing-like table (ticker/symbol/code + company)."""
    candidates: list[pd.DataFrame] = []
    for table in tables:
        # Skip MultiIndex change-log tables (e.g. Nasdaq-100 additions/removals).
        if isinstance(table.columns, pd.MultiIndex):
            continue
        cols = {str(c).strip().lower() for c in table.columns}
        has_ticker = bool(
            {"ticker", "symbol", "code", "epic"} & cols
            or any(
                any(token in str(c).lower() for token in ("ticker", "symbol", "code", "epic"))
                for c in table.columns
            )
        )
        has_name = bool({"company", "name", "security"} & cols) or any(
            "company" in str(c).lower() or "security" in str(c).lower() for c in table.columns
        )
        if has_ticker and (has_name or len(table) >= 30):
            candidates.append(table)
        elif has_ticker:
            candidates.append(table)
    if candidates:
        return max(candidates, key=len)
    if not tables:
        raise ValueError("No HTML tables found")
    return max(tables, key=len)


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
        if "raw_ticker" not in rename.values() and (
            key in {"ticker", "symbol", "epic", "code"} or "ticker" in key or "symbol" in key
        ):
            rename[col] = "raw_ticker"
        elif "name" not in rename.values() and (
            key in {"company", "name", "security", "stock"} or "company" in key
        ):
            rename[col] = "name"
        elif "sector" not in rename.values() and ("sector" in key or key == "industry"):
            # Prefer the first sector-like column (e.g. GICS Sector over Sub-Industry).
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
        elif market_id in PREQUALIFIED_YAHOO_MARKETS:
            # Wikipedia already lists Yahoo-qualified symbols (e.g. ADS.DE, AIR.PA).
            # Do not convert '.' → '-' (that yields ADS-DE, which Yahoo rejects).
            ticker = raw
        elif yahoo_suffix:
            base = raw.replace(".", "-")
            ticker = base if base.endswith(yahoo_suffix) else f"{base}{yahoo_suffix}"
        else:
            # US class shares: BRK.B → BRK-B
            ticker = raw.replace(".", "-")
        sector_val = row["sector"] if "sector" in frame.columns else None
        if sector_val is not None and not isinstance(sector_val, str):
            try:
                if pd.isna(sector_val):
                    sector_val = None
                else:
                    sector_val = str(sector_val)
            except (ValueError, TypeError):
                sector_val = str(sector_val)
        rows.append(
            {
                "ticker": ticker,
                "name": str(row["name"] if "name" in frame.columns else ticker),
                "sector": sector_val,
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


def fetch_ftse_smallcap_constituents() -> pd.DataFrame:
    """FTSE SmallCap — with FTSE 350 this approximates the FTSE All-Share (excl. Fledgling/AIM)."""
    tables = _wiki_tables("https://en.wikipedia.org/wiki/FTSE_SmallCap_Index")
    table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="ftse_smallcap", yahoo_suffix=".L", index_label="FTSE SmallCap"
    )


def fetch_nasdaq100_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies")
    table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="nasdaq100", yahoo_suffix="", index_label="Nasdaq-100"
    )


def fetch_dax_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/DAX")
    table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="dax", yahoo_suffix="", index_label="DAX"
    )


def fetch_cac40_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/CAC_40")
    table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="cac40", yahoo_suffix="", index_label="CAC 40"
    )


def fetch_tsx60_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/S%26P/TSX_60")
    table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="tsx60", yahoo_suffix=".TO", index_label="S&P/TSX 60"
    )


def fetch_aim_constituents() -> pd.DataFrame:
    """
    Liquid AIM names from the Wikipedia AIM page company/ticker table.

    Full FTSE AIM All-Share is much larger; this ~100-name slice is the
    progressive L34 AIM step (II UK includes AIM).
    """
    tables = _wiki_tables("https://en.wikipedia.org/wiki/Alternative_Investment_Market")
    table = None
    for candidate in tables:
        cols = {str(c).strip().lower() for c in candidate.columns}
        if "company" in cols and "ticker" in cols and len(candidate) >= 20:
            table = candidate
            break
    if table is None:
        table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="aim", yahoo_suffix=".L", index_label="AIM (Wikipedia liquid)"
    )


def fetch_ibex35_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/IBEX_35")
    table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="ibex35", yahoo_suffix="", index_label="IBEX 35"
    )


def fetch_ftse_mib_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/FTSE_MIB")
    table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="ftse_mib", yahoo_suffix="", index_label="FTSE MIB"
    )


def fetch_aex_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/AEX_index")
    table = _pick_constituent_table(tables)
    return _normalize_wiki_constituents(
        table, market_id="aex", yahoo_suffix="", index_label="AEX"
    )


def fetch_bel20_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/BEL_20")
    # Prefer the current-weightings table over the historical membership log.
    table = None
    for candidate in tables:
        cols = [str(c).strip().lower() for c in candidate.columns]
        if any("ticker" in c for c in cols) and any("weight" in c for c in cols):
            table = candidate
            break
    if table is None:
        table = _pick_constituent_table(tables)

    # Columns: Company / ICB Sector / Ticker symbol (``Euronext Brussels: ABI``).
    # Do not use _normalize_wiki_constituents — it splits on spaces and keeps "Euronext".
    ticker_col = next(c for c in table.columns if "ticker" in str(c).lower())
    name_col = next(c for c in table.columns if "company" in str(c).lower() or "name" in str(c).lower())
    sector_col = next((c for c in table.columns if "sector" in str(c).lower()), None)
    rows: list[dict[str, Any]] = []
    for _, row in table.iterrows():
        raw = str(row.get(ticker_col) or "").replace("\xa0", " ").strip()
        if not raw or raw.lower() == "nan":
            continue
        # Dual-listed BEL names may show Amsterdam — keep Yahoo home suffix when present.
        lower = raw.lower()
        if "amsterdam" in lower:
            code = _strip_exchange_prefix(raw).upper().replace(" ", "")
            ticker = code if code.endswith(".AS") else f"{code}.AS"
        else:
            ticker = _to_bel_yahoo(raw)
        if ticker in {".BR", ".AS", "NO.BR"}:
            continue
        sector_val = row.get(sector_col) if sector_col is not None else None
        rows.append(
            {
                "ticker": ticker,
                "name": str(row.get(name_col) or ticker),
                "sector": None if sector_val is None or (isinstance(sector_val, float) and pd.isna(sector_val)) else str(sector_val),
                "epic": _strip_exchange_prefix(raw),
                "index": "BEL 20",
                "market": "bel20",
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.drop_duplicates("ticker", keep="first").reset_index(drop=True)


def fetch_hang_seng_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/Hang_Seng_Index")
    table = _pick_constituent_table(tables)
    # Custom normalize: SEHK codes → zero-padded Yahoo .HK symbols.
    rename: dict[str, str] = {}
    for col in table.columns:
        key = str(col).strip().lower()
        if "raw_ticker" not in rename.values() and (
            key in {"ticker", "symbol", "code"} or "ticker" in key
        ):
            rename[col] = "raw_ticker"
        elif "name" not in rename.values() and (
            key in {"name", "company", "security"} or "name" in key or "company" in key
        ):
            rename[col] = "name"
        elif "sector" not in rename.values() and ("sector" in key or "sub-index" in key):
            rename[col] = "sector"
    frame = table.rename(columns=rename).copy()
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        raw = str(row.get("raw_ticker") or "").strip()
        if not raw or raw.lower() == "nan":
            continue
        ticker = _to_hk_yahoo(raw)
        rows.append(
            {
                "ticker": ticker,
                "name": str(row.get("name") or ticker),
                "sector": row.get("sector"),
                "epic": _strip_exchange_prefix(raw),
                "index": "Hang Seng",
                "market": "hang_seng",
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.drop_duplicates("ticker", keep="first").reset_index(drop=True)


def fetch_sti_constituents() -> pd.DataFrame:
    tables = _wiki_tables("https://en.wikipedia.org/wiki/Straits_Times_Index")
    table = _pick_constituent_table(tables)
    rename: dict[str, str] = {}
    for col in table.columns:
        key = str(col).strip().lower()
        if "raw_ticker" not in rename.values() and (
            "symbol" in key or key in {"ticker", "code"}
        ):
            rename[col] = "raw_ticker"
        elif "name" not in rename.values() and (
            key in {"company", "name", "security"} or "company" in key
        ):
            rename[col] = "name"
    frame = table.rename(columns=rename).copy()
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        raw = str(row.get("raw_ticker") or "").strip()
        if not raw or raw.lower() == "nan":
            continue
        ticker = _to_sg_yahoo(raw)
        if ticker in {".SI", "SGX.SI"}:
            continue
        rows.append(
            {
                "ticker": ticker,
                "name": str(row.get("name") or ticker),
                "sector": None,
                "epic": _strip_exchange_prefix(raw),
                "index": "STI",
                "market": "sti",
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.drop_duplicates("ticker", keep="first").reset_index(drop=True)


# Major Asia home-market names commonly held via US-listed ADRs (II path for
# Japan / India / China). Curated seed — not a full ADR catalog.
US_ADR_ASIA_SEED: list[dict[str, str | None]] = [
    {"ticker": "BABA", "name": "Alibaba Group", "sector": "Consumer Cyclical", "home": "China"},
    {"ticker": "PDD", "name": "PDD Holdings", "sector": "Consumer Cyclical", "home": "China"},
    {"ticker": "JD", "name": "JD.com", "sector": "Consumer Cyclical", "home": "China"},
    {"ticker": "BIDU", "name": "Baidu", "sector": "Communication Services", "home": "China"},
    {"ticker": "NIO", "name": "NIO", "sector": "Consumer Cyclical", "home": "China"},
    {"ticker": "LI", "name": "Li Auto", "sector": "Consumer Cyclical", "home": "China"},
    {"ticker": "XPEV", "name": "XPeng", "sector": "Consumer Cyclical", "home": "China"},
    {"ticker": "TME", "name": "Tencent Music", "sector": "Communication Services", "home": "China"},
    {"ticker": "TM", "name": "Toyota Motor", "sector": "Consumer Cyclical", "home": "Japan"},
    {"ticker": "SONY", "name": "Sony Group", "sector": "Technology", "home": "Japan"},
    {"ticker": "HMC", "name": "Honda Motor", "sector": "Consumer Cyclical", "home": "Japan"},
    {"ticker": "MUFG", "name": "Mitsubishi UFJ Financial", "sector": "Financial Services", "home": "Japan"},
    {"ticker": "SMFG", "name": "Sumitomo Mitsui Financial", "sector": "Financial Services", "home": "Japan"},
    {"ticker": "MFG", "name": "Mizuho Financial", "sector": "Financial Services", "home": "Japan"},
    {"ticker": "NMR", "name": "Nomura Holdings", "sector": "Financial Services", "home": "Japan"},
    {"ticker": "TAK", "name": "Takeda Pharmaceutical", "sector": "Healthcare", "home": "Japan"},
    {"ticker": "INFY", "name": "Infosys", "sector": "Technology", "home": "India"},
    {"ticker": "WIT", "name": "Wipro", "sector": "Technology", "home": "India"},
    {"ticker": "IBN", "name": "ICICI Bank", "sector": "Financial Services", "home": "India"},
    {"ticker": "HDB", "name": "HDFC Bank", "sector": "Financial Services", "home": "India"},
    {"ticker": "RDY", "name": "Dr. Reddy's Laboratories", "sector": "Healthcare", "home": "India"},
    {"ticker": "TSM", "name": "Taiwan Semiconductor", "sector": "Technology", "home": "Taiwan"},
    {"ticker": "UMC", "name": "United Microelectronics", "sector": "Technology", "home": "Taiwan"},
    {"ticker": "ASX", "name": "ASE Technology", "sector": "Technology", "home": "Taiwan"},
]


def fetch_us_adr_asia_constituents() -> pd.DataFrame:
    """Curated US-listed ADRs for Asia home markets (II ADR path)."""
    rows = [
        {
            "ticker": str(item["ticker"]),
            "name": item.get("name"),
            "sector": item.get("sector"),
            "epic": str(item["ticker"]),
            "index": "US ADR Asia (curated)",
            "market": "us_adr_asia",
            "home_market": item.get("home"),
        }
        for item in US_ADR_ASIA_SEED
    ]
    return pd.DataFrame(rows)


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
    # Interactive Investor–aligned expansion slices (offline ladder; not live screen).
    "ftse_smallcap": MarketSpec(
        market_id="ftse_smallcap",
        label="FTSE SmallCap",
        exchange="LSE",
        currency="GBP",
        yahoo_suffix=".L",
        constituent_source="wikipedia",
    ),
    "nasdaq100": MarketSpec(
        market_id="nasdaq100",
        label="Nasdaq-100",
        exchange="US",
        currency="USD",
        yahoo_suffix="",
        constituent_source="wikipedia",
    ),
    "dax": MarketSpec(
        market_id="dax",
        label="DAX",
        exchange="XETRA",
        currency="EUR",
        yahoo_suffix="",
        constituent_source="wikipedia",
    ),
    "cac40": MarketSpec(
        market_id="cac40",
        label="CAC 40",
        exchange="Euronext Paris",
        currency="EUR",
        yahoo_suffix="",
        constituent_source="wikipedia",
    ),
    "tsx60": MarketSpec(
        market_id="tsx60",
        label="S&P/TSX 60",
        exchange="TSX",
        currency="CAD",
        yahoo_suffix=".TO",
        constituent_source="wikipedia",
    ),
    # L34 next slices — II-aligned expansion beyond the initial index queue.
    "aim": MarketSpec(
        market_id="aim",
        label="AIM (liquid Wikipedia slice)",
        exchange="LSE AIM",
        currency="GBP",
        yahoo_suffix=".L",
        constituent_source="wikipedia",
    ),
    "ibex35": MarketSpec(
        market_id="ibex35",
        label="IBEX 35",
        exchange="Bolsa de Madrid",
        currency="EUR",
        yahoo_suffix="",
        constituent_source="wikipedia",
    ),
    "ftse_mib": MarketSpec(
        market_id="ftse_mib",
        label="FTSE MIB",
        exchange="Borsa Italiana",
        currency="EUR",
        yahoo_suffix="",
        constituent_source="wikipedia",
    ),
    "aex": MarketSpec(
        market_id="aex",
        label="AEX",
        exchange="Euronext Amsterdam",
        currency="EUR",
        yahoo_suffix="",
        constituent_source="wikipedia",
    ),
    "bel20": MarketSpec(
        market_id="bel20",
        label="BEL 20",
        exchange="Euronext Brussels",
        currency="EUR",
        yahoo_suffix="",
        constituent_source="wikipedia",
    ),
    "hang_seng": MarketSpec(
        market_id="hang_seng",
        label="Hang Seng",
        exchange="HKEX",
        currency="HKD",
        yahoo_suffix=".HK",
        constituent_source="wikipedia",
    ),
    "sti": MarketSpec(
        market_id="sti",
        label="Straits Times Index",
        exchange="SGX",
        currency="SGD",
        yahoo_suffix=".SI",
        constituent_source="wikipedia",
    ),
    "us_adr_asia": MarketSpec(
        market_id="us_adr_asia",
        label="US ADR Asia (curated)",
        exchange="US ADR",
        currency="USD",
        yahoo_suffix="",
        constituent_source="curated",
    ),
}

CONSTITUENT_FETCHERS: dict[str, Callable[[], pd.DataFrame]] = {
    "ftse350": fetch_ftse350_library_constituents,
    "sp500": fetch_sp500_constituents,
    "euro_stoxx50": fetch_euro_stoxx50_constituents,
    "asx200": fetch_asx200_constituents,
    "ftse_smallcap": fetch_ftse_smallcap_constituents,
    "nasdaq100": fetch_nasdaq100_constituents,
    "dax": fetch_dax_constituents,
    "cac40": fetch_cac40_constituents,
    "tsx60": fetch_tsx60_constituents,
    "aim": fetch_aim_constituents,
    "ibex35": fetch_ibex35_constituents,
    "ftse_mib": fetch_ftse_mib_constituents,
    "aex": fetch_aex_constituents,
    "bel20": fetch_bel20_constituents,
    "hang_seng": fetch_hang_seng_constituents,
    "sti": fetch_sti_constituents,
    "us_adr_asia": fetch_us_adr_asia_constituents,
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
    exclude_tickers: set[str] | None = None,
) -> list[str]:
    from value_investor.library_dedupe import canonical_library_ticker

    now = now or datetime.now(UTC)
    stale_before = now - timedelta(days=stale_days)
    excluded = {canonical_library_ticker(t) for t in (exclude_tickers or set())}
    state = manifest.get("ticker_state") or {}
    never: list[str] = []
    stale: list[str] = []
    fresh: list[str] = []
    for ticker in manifest.get("tickers") or []:
        if canonical_library_ticker(ticker) in excluded:
            continue
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
    exclude_tickers: set[str] | None = None,
    only_tickers: list[str] | None = None,
) -> dict[str, Any]:
    """
    Progressively refresh fundamentals for a market.

    Prefers never-fetched tickers, then stale ones, capped by ``max_tickers``
    so libraries can grow across many scheduled runs without hammering APIs.
    ``exclude_tickers`` skips names already fetched earlier in the same multi-market
    grow (exact Yahoo ticker match — avoids S&P/Nasdaq double-fetch).
    ``only_tickers`` forces a specific retry set (still capped by ``max_tickers``).
    """
    if market_id not in MARKET_REGISTRY:
        raise ValueError(f"Unknown market {market_id!r}")
    manifest = load_manifest(root, market_id)
    if not manifest.get("tickers") and only_tickers is None:
        manifest = refresh_constituents(root, market_id)

    constituents_path = market_dir(root, market_id) / "constituents" / "latest.json"
    by_ticker: dict[str, dict[str, Any]] = {}
    if constituents_path.exists():
        for row in read_json(constituents_path):
            by_ticker[str(row["ticker"])] = row

    if only_tickers is not None:
        selected = list(dict.fromkeys(str(t) for t in only_tickers if t))
        selected = selected[: max(0, max_tickers)]
    else:
        selected = _select_refresh_tickers(
            manifest,
            max_tickers=max_tickers,
            stale_days=stale_days,
            exclude_tickers=exclude_tickers,
        )
    fetch = fetch_fn or (
        lambda ticker, name, sector: fetch_company_metrics(
            ticker, name=name, sector=sector, market=market_id
        )
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
    checkpoint_every = 25
    as_of = datetime.now(UTC).date().isoformat()
    total = len(selected)

    def _checkpoint(*, final: bool = False) -> None:
        rows = list(by_metrics.values())
        for row in rows:
            field_union.update(_metric_field_names(row))
        write_json(metrics_path, rows, compact=True, compress=True)
        write_json(
            market_dir(root, market_id) / "metrics" / f"{as_of}.json.gz",
            rows,
            compact=True,
            compress=True,
        )
        manifest["fields_present"] = sorted(field_union)
        manifest["last_metrics_refresh"] = datetime.now(UTC).isoformat()
        _recompute_coverage(manifest)
        save_manifest(root, market_id, manifest)
        if not final:
            logger.info(
                "Library grow checkpoint %s: %d/%d updated (coverage %s/%s)",
                market_id,
                updated,
                total,
                manifest.get("coverage_count"),
                manifest.get("ticker_count"),
            )

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
        errors_list = list(row.get("errors") or [])
        state[ticker] = {
            "last_refresh": datetime.now(UTC).isoformat(),
            "fields_present": fields,
            "errors": errors_list,
            "fetch_status": "failed" if errors_list else "ok",
        }
        manifest["ticker_state"] = state
        updated += 1
        if updated % checkpoint_every == 0:
            _checkpoint(final=False)

    _checkpoint(final=True)
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


def _parse_dated_snapshot_name(name: str) -> date | None:
    match = _DATED_SNAPSHOT_NAME.match(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _retention_period_key(file_date: date, resolution: RetentionResolution) -> str:
    if resolution == "month":
        return f"{file_date.year}-{file_date.month:02d}"
    if resolution == "quarter":
        return f"{file_date.year}-Q{(file_date.month - 1) // 3 + 1}"
    raise ValueError(f"Unsupported retention resolution {resolution!r}")


def _iter_dated_pit_snapshots(root: Path) -> list[tuple[Path, date]]:
    """Dated metrics/constituents snapshots under markets/*/… (not screen/research)."""
    root = Path(root)
    found: list[tuple[Path, date]] = []
    markets_root = root / "markets"
    if not markets_root.is_dir():
        return found
    for market_dir_path in markets_root.iterdir():
        if not market_dir_path.is_dir():
            continue
        for bucket in ("metrics", "constituents"):
            bucket_dir = market_dir_path / bucket
            if not bucket_dir.is_dir():
                continue
            for path in bucket_dir.iterdir():
                if not path.is_file() or path.name.startswith("latest"):
                    continue
                file_date = _parse_dated_snapshot_name(path.name)
                if file_date is not None:
                    found.append((path, file_date))
    return found


def apply_library_retention(
    root: Path,
    *,
    keep_days: int = DEFAULT_RETENTION_DAYS,
    monthly_until_days: int = DEFAULT_MONTHLY_UNTIL_DAYS,
    now: datetime | date | None = None,
) -> int:
    """
    Prune dated constituent/metrics PIT snapshots with decreasing resolution.

    Generous defaults (storage is cheap; prune harder later if unused):

    - age < ``keep_days``: keep every dated snapshot
    - ``keep_days`` ≤ age < ``monthly_until_days``: keep one per calendar month
    - age ≥ ``monthly_until_days``: keep one per calendar quarter indefinitely

    ``keep_days=0`` disables pruning. ``latest.*`` and non-PIT paths are untouched.
    Within a thinned period, the newest snapshot date is kept.
    """
    if keep_days <= 0:
        return 0
    root = Path(root)
    if not root.exists():
        return 0

    if isinstance(now, datetime):
        today = now.astimezone(UTC).date() if now.tzinfo else now.date()
    elif isinstance(now, date):
        today = now
    else:
        today = datetime.now(UTC).date()

    dense_cutoff = today - timedelta(days=keep_days)
    monthly_until = max(int(monthly_until_days), int(keep_days))
    monthly_cutoff = today - timedelta(days=monthly_until)

    # Group thinned snapshots by (directory, resolution, period); dense stays.
    groups: dict[tuple[Path, RetentionResolution, str], list[tuple[Path, date]]] = {}
    for path, file_date in _iter_dated_pit_snapshots(root):
        if file_date >= dense_cutoff:
            continue
        resolution: RetentionResolution = "month" if file_date >= monthly_cutoff else "quarter"
        key = (path.parent, resolution, _retention_period_key(file_date, resolution))
        groups.setdefault(key, []).append((path, file_date))

    removed = 0
    for entries in groups.values():
        if len(entries) <= 1:
            continue
        entries.sort(key=lambda item: item[1], reverse=True)
        for path, _file_date in entries[1:]:
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
    monthly_until_days: int = DEFAULT_MONTHLY_UNTIL_DAYS,
    fetch_fn: Callable[[str, str | None, str | None], Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Refresh constituents (optional) and progressively fill metrics for each market.

    Within a single grow run, identical Yahoo tickers shared across markets (e.g.
    AAPL in S&P 500 and Nasdaq-100) reuse one fetch via an in-memory cache so
    each market manifest still updates without duplicate network calls.
    """
    from value_investor.library_dedupe import canonical_library_ticker

    selected_markets = markets or list(MARKET_REGISTRY)
    results: list[dict[str, Any]] = []
    fetch_cache: dict[str, Any] = {}
    cache_hits = 0

    def _base_fetch(ticker: str, name: str | None, sector: str | None, *, market_id: str):
        if fetch_fn is not None:
            return fetch_fn(ticker, name, sector)
        return fetch_company_metrics(ticker, name=name, sector=sector, market=market_id)

    for market_id in selected_markets:
        if market_id not in MARKET_REGISTRY:
            raise ValueError(f"Unknown market {market_id!r}")
        if refresh_constituents_first:
            refresh_constituents(root, market_id)

        def cached_fetch(
            ticker: str,
            name: str | None,
            sector: str | None,
            *,
            _market_id: str = market_id,
        ):
            nonlocal cache_hits
            key = canonical_library_ticker(ticker)
            if key in fetch_cache:
                cache_hits += 1
                return dict(fetch_cache[key])
            row = _base_fetch(ticker, name, sector, market_id=_market_id)
            as_dict = row.to_dict() if hasattr(row, "to_dict") else dict(row)
            fetch_cache[key] = as_dict
            return dict(as_dict)

        result = refresh_metrics(
            root,
            market_id,
            max_tickers=max_tickers_per_run,
            stale_days=stale_days,
            fetch_fn=cached_fetch,
        )
        result["fetch_cache_size"] = len(fetch_cache)
        results.append(result)
    if retention_days > 0:
        apply_library_retention(
            root,
            keep_days=retention_days,
            monthly_until_days=monthly_until_days,
        )
    write_json(
        Path(root) / "library_status.json",
        {
            "updated_at": datetime.now(UTC).isoformat(),
            "markets": library_status(root, markets=selected_markets, stale_days=stale_days),
            "last_grow": results,
            "cross_market_fetch_cache_hits": cache_hits,
            "cross_market_fetch_cache_size": len(fetch_cache),
        },
        compact=False,
    )
    return results
