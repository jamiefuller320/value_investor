"""FTSE 100 constituent list."""

from __future__ import annotations

import logging
from functools import lru_cache
from io import StringIO
from urllib.request import Request, urlopen

import pandas as pd

logger = logging.getLogger(__name__)

WIKIPEDIA_FTSE_URL = "https://en.wikipedia.org/wiki/FTSE_100_Index"
WIKIPEDIA_USER_AGENT = "value-investor/0.1 (research screener; contact: local)"

# Fallback when Wikipedia is unreachable — update periodically or override via CSV.
FALLBACK_FTSE100_EPICS = [
    "III", "ADM", "AAL", "ANTO", "AHT", "ABF", "AZN", "AUTO", "AV", "BA", "BARC", "BATS",
    "BEZ", "BKG", "BP", "BATS", "BT-A", "BNZL", "CNA", "CCH", "CPG", "CRDA", "CRH", "DCC",
    "DGE", "ENT", "EXPN", "FCIT", "FRES", "GLEN", "GSK", "HLMA", "HLN", "HSBA", "HSX",
    "IMB", "INF", "IHG", "ITRK", "JD", "KGF", "LAND", "LGEN", "LLOY", "LSEG", "MKS", "MRO",
    "MNDI", "NG", "NXT", "OCDO", "PSON", "PSN", "PHNX", "PRU", "RKT", "REL", "RIO", "RR",
    "RTO", "SBRY", "SDR", "SGE", "SHEL", "SMIN", "SMT", "SN", "SPX", "SSE", "STAN", "STJ",
    "SVT", "TSCO", "ULVR", "UU", "UTG", "VOD", "WEIR", "WTB", "WPP",
]


def _to_lse_ticker(epic: str) -> str:
    """Convert LSE EPIC / ticker to yfinance symbol (e.g. BARC -> BARC.L)."""
    epic = epic.strip().upper()
    if epic.endswith(".L"):
        return epic
    return f"{epic}.L"


def _fetch_wikipedia_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": WIKIPEDIA_USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_constituents_table(html: str) -> pd.DataFrame:
    tables = pd.read_html(StringIO(html))
    constituents = None
    for table in tables:
        cols = {str(c).lower() for c in table.columns}
        if "epic" in cols or "ticker" in cols:
            constituents = table.copy()
            break

    if constituents is None:
        raise RuntimeError("Could not locate FTSE 100 constituents table on Wikipedia")

    rename_map: dict[str, str] = {}
    for col in constituents.columns:
        lower = str(col).lower()
        if lower in ("epic", "ticker"):
            rename_map[col] = "epic"
        elif lower in ("company", "name"):
            rename_map[col] = "name"
        elif "sector" in lower or "industry" in lower:
            rename_map[col] = "sector"

    constituents = constituents.rename(columns=rename_map)
    if "epic" not in constituents.columns:
        raise RuntimeError("FTSE 100 table missing EPIC/ticker column")

    constituents["epic"] = constituents["epic"].astype(str).str.strip()
    constituents = constituents[constituents["epic"].str.match(r"^[A-Za-z0-9.-]+$")]
    constituents["ticker"] = constituents["epic"].map(_to_lse_ticker)

    if "name" not in constituents.columns:
        constituents["name"] = constituents["ticker"]
    if "sector" not in constituents.columns:
        constituents["sector"] = None

    return constituents[["ticker", "name", "sector", "epic"]].drop_duplicates("ticker").reset_index(drop=True)


def _fallback_constituents() -> pd.DataFrame:
    logger.warning("Using built-in FTSE 100 fallback list — Wikipedia fetch failed")
    epics = sorted(set(FALLBACK_FTSE100_EPICS))
    return pd.DataFrame(
        {
            "epic": epics,
            "ticker": [_to_lse_ticker(e) for e in epics],
            "name": epics,
            "sector": None,
        }
    )


@lru_cache(maxsize=1)
def fetch_ftse100_constituents() -> pd.DataFrame:
    """
    Fetch current FTSE 100 constituents from Wikipedia.

    Falls back to a built-in EPIC list if the fetch fails.
    Returns a DataFrame with columns: ticker, name, sector (when available).
    """
    try:
        html = _fetch_wikipedia_html(WIKIPEDIA_FTSE_URL)
        return _parse_constituents_table(html)
    except Exception as exc:
        logger.warning("Wikipedia FTSE 100 fetch failed: %s", exc)
        return _fallback_constituents()


def normalize_tickers(tickers: list[str]) -> list[str]:
    """Normalize user-supplied tickers to LSE yfinance symbols."""
    return [_to_lse_ticker(t) for t in tickers if t.strip()]
