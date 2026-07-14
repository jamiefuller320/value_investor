"""FTSE index constituent lists (100, 250, and combined 350)."""

from __future__ import annotations

import logging
from functools import lru_cache
from io import StringIO
from urllib.request import Request, urlopen

import pandas as pd

logger = logging.getLogger(__name__)

WIKIPEDIA_FTSE100_URL = "https://en.wikipedia.org/wiki/FTSE_100_Index"
WIKIPEDIA_FTSE250_URL = "https://en.wikipedia.org/wiki/FTSE_250_Index"
# Backwards-compatible alias.
WIKIPEDIA_FTSE_URL = WIKIPEDIA_FTSE100_URL
WIKIPEDIA_USER_AGENT = "value-investor/0.1 (research screener; contact: local)"

UNIVERSE_FTSE100 = "ftse100"
UNIVERSE_FTSE250 = "ftse250"
UNIVERSE_FTSE350 = "ftse350"
DEFAULT_UNIVERSE = UNIVERSE_FTSE350
VALID_UNIVERSES = (UNIVERSE_FTSE100, UNIVERSE_FTSE250, UNIVERSE_FTSE350)

UNIVERSE_LABELS = {
    UNIVERSE_FTSE100: "FTSE 100",
    UNIVERSE_FTSE250: "FTSE 250",
    UNIVERSE_FTSE350: "FTSE 350",
}

# Explicit Wikipedia/LSE EPIC → Yahoo Finance symbol overrides (without .L).
# Prefer general rules in to_lse_ticker(); keep this for odd cases only.
YFINANCE_EPIC_ALIASES: dict[str, str] = {
    "BT.A": "BT-A",
    "BTA": "BT-A",
}

# Fallback when Wikipedia is unreachable — update periodically or override via CSV.
FALLBACK_FTSE100_EPICS = [
    "III", "ADM", "AAL", "ANTO", "AHT", "ABF", "AZN", "AUTO", "AV", "BA", "BARC", "BATS",
    "BEZ", "BKG", "BP", "BT-A", "BNZL", "CNA", "CCH", "CPG", "CRDA", "CRH", "DCC",
    "DGE", "ENT", "EXPN", "FCIT", "FRES", "GLEN", "GSK", "HLMA", "HLN", "HSBA", "HSX",
    "IMB", "INF", "IHG", "ITRK", "JD", "KGF", "LAND", "LGEN", "LLOY", "LSEG", "MKS", "MRO",
    "MNDI", "NG", "NXT", "OCDO", "PSON", "PSN", "PHNX", "PRU", "RKT", "REL", "RIO", "RR",
    "RTO", "SBRY", "SDR", "SGE", "SHEL", "SMIN", "SMT", "SN", "SPX", "SSE", "STAN", "STJ",
    "SVT", "TSCO", "ULVR", "UU", "UTG", "VOD", "WEIR", "WTB", "WPP",
]

# Small mid-cap seed list only — used if Wikipedia FTSE 250 is unreachable.
FALLBACK_FTSE250_EPICS = [
    "ABDN", "BBY", "BWY", "CWK", "DRX", "EZJ", "FRAS", "HBR", "HIK", "ITV",
    "JMAT", "OSB", "PETS", "RMV", "RSW", "SCT", "TATE", "TW", "VTY", "WIZZ",
]


def to_lse_ticker(epic: str) -> str:
    """
    Convert LSE EPIC / ticker to a yfinance symbol.

    Wikipedia often lists share classes with a dot (``BT.A``); Yahoo Finance
    expects a hyphen (``BT-A.L``).
    """
    epic = epic.strip().upper()
    if epic.endswith(".L"):
        epic = epic[:-2]

    alias = YFINANCE_EPIC_ALIASES.get(epic)
    if alias:
        epic = alias
    else:
        # Class shares: BT.A → BT-A (Yahoo convention)
        epic = epic.replace(".", "-")

    return f"{epic}.L"


# Backwards-compatible private alias used by older call sites / tests.
_to_lse_ticker = to_lse_ticker


def _fetch_wikipedia_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": WIKIPEDIA_USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_constituents_table(html: str, *, index_label: str) -> pd.DataFrame:
    tables = pd.read_html(StringIO(html))
    constituents = None
    for table in tables:
        cols = {str(c).lower() for c in table.columns}
        if "epic" in cols or "ticker" in cols:
            constituents = table.copy()
            break

    if constituents is None:
        raise RuntimeError(f"Could not locate {index_label} constituents table on Wikipedia")

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
        raise RuntimeError(f"{index_label} table missing EPIC/ticker column")

    constituents["epic"] = constituents["epic"].astype(str).str.strip()
    constituents = constituents[constituents["epic"].str.match(r"^[A-Za-z0-9.-]+$")]
    constituents["ticker"] = constituents["epic"].map(to_lse_ticker)

    if "name" not in constituents.columns:
        constituents["name"] = constituents["ticker"]
    if "sector" not in constituents.columns:
        constituents["sector"] = None

    out = constituents[["ticker", "name", "sector", "epic"]].drop_duplicates("ticker").reset_index(drop=True)
    out["index"] = index_label
    return out


def _fallback_frame(epics: list[str], *, index_label: str) -> pd.DataFrame:
    unique = sorted(set(epics))
    return pd.DataFrame(
        {
            "epic": unique,
            "ticker": [to_lse_ticker(e) for e in unique],
            "name": unique,
            "sector": None,
            "index": index_label,
        }
    )


def _fallback_ftse100() -> pd.DataFrame:
    logger.warning("Using built-in FTSE 100 fallback list — Wikipedia fetch failed")
    return _fallback_frame(FALLBACK_FTSE100_EPICS, index_label="FTSE 100")


def _fallback_ftse250() -> pd.DataFrame:
    logger.warning("Using built-in FTSE 250 fallback list — Wikipedia fetch failed")
    return _fallback_frame(FALLBACK_FTSE250_EPICS, index_label="FTSE 250")


@lru_cache(maxsize=1)
def fetch_ftse100_constituents() -> pd.DataFrame:
    """
    Fetch current FTSE 100 constituents from Wikipedia.

    Falls back to a built-in EPIC list if the fetch fails.
    Returns a DataFrame with columns: ticker, name, sector, epic, index.
    """
    try:
        html = _fetch_wikipedia_html(WIKIPEDIA_FTSE100_URL)
        return _parse_constituents_table(html, index_label="FTSE 100")
    except Exception as exc:
        logger.warning("Wikipedia FTSE 100 fetch failed: %s", exc)
        return _fallback_ftse100()


@lru_cache(maxsize=1)
def fetch_ftse250_constituents() -> pd.DataFrame:
    """
    Fetch current FTSE 250 constituents from Wikipedia.

    Falls back to a short built-in EPIC list if the fetch fails.
    Returns a DataFrame with columns: ticker, name, sector, epic, index.
    """
    try:
        html = _fetch_wikipedia_html(WIKIPEDIA_FTSE250_URL)
        return _parse_constituents_table(html, index_label="FTSE 250")
    except Exception as exc:
        logger.warning("Wikipedia FTSE 250 fetch failed: %s", exc)
        return _fallback_ftse250()


def _combine_constituents(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Prefer earlier frames when tickers overlap (FTSE 100 before FTSE 250)."""
    if not frames:
        return pd.DataFrame(columns=["ticker", "name", "sector", "epic", "index"])
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates("ticker", keep="first").reset_index(drop=True)
    return combined


@lru_cache(maxsize=1)
def fetch_ftse350_constituents() -> pd.DataFrame:
    """
    Combined FTSE 100 + FTSE 250 universe (≈350 names after dedupe).

    Names that appear in both lists keep the FTSE 100 row.
    """
    return _combine_constituents(
        [fetch_ftse100_constituents(), fetch_ftse250_constituents()]
    )


def fetch_universe_constituents(universe: str = DEFAULT_UNIVERSE) -> pd.DataFrame:
    """Fetch constituents for ``ftse100``, ``ftse250``, or ``ftse350`` (default)."""
    key = (universe or DEFAULT_UNIVERSE).strip().lower()
    if key not in VALID_UNIVERSES:
        raise ValueError(
            f"Unknown universe {universe!r}; expected one of {', '.join(VALID_UNIVERSES)}"
        )
    if key == UNIVERSE_FTSE100:
        return fetch_ftse100_constituents().copy()
    if key == UNIVERSE_FTSE250:
        return fetch_ftse250_constituents().copy()
    return fetch_ftse350_constituents().copy()


def universe_label(universe: str = DEFAULT_UNIVERSE) -> str:
    key = (universe or DEFAULT_UNIVERSE).strip().lower()
    return UNIVERSE_LABELS.get(key, UNIVERSE_LABELS[DEFAULT_UNIVERSE])


def normalize_tickers(tickers: list[str]) -> list[str]:
    """Normalize user-supplied tickers to LSE yfinance symbols."""
    return [to_lse_ticker(t) for t in tickers if t.strip()]
