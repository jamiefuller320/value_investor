"""Which scored names are funds or investment trusts rather than operating companies.

The operating-decline gate applies company rules (revenue, operating margin, EPS,
free cash flow). A fund's "revenue" line is investment income or portfolio return
and it has no operating margin, so those rules cannot say whether its business is
getting worse. The gate returns ``insufficient_data`` for these names (owner,
Phase 1 gate review 2026-11-10). Runbook:
docs/ops/operating-decline-gate.md#funds-and-investment-trusts.

Deliberately narrower than ``universe_filters.is_investment_vehicle``: that screen
filter drops any name containing "trust", "ventures" or an "Ord" suffix, which
would catch banks (Northern Trust, Secure Trust Bank), REITs and operating
companies in library markets. REITs are operating property companies here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REASON_CODE = "fund_or_trust"
OVERRIDES_FILENAME = "fund_or_trust_overrides.json"

BASIS_OVERRIDE = "override"
BASIS_SECTOR = "sector_label"
BASIS_INDUSTRY = "industry"
BASIS_QUOTE_TYPE = "quote_type"
BASIS_NAME = "name"

_FUND_SECTOR_FRAGMENTS = (
    "investment trust",
    "closed-end fund",
    "closed end fund",
    "collective investment",
    "equity investment instrument",
    "nonequity investment instrument",
)
_FUND_INDUSTRY_FRAGMENTS = ("closed-end fund", "closed end fund", "exchange traded fund")
_FUND_QUOTE_TYPES = frozenset({"ETF", "MUTUALFUND"})
_REIT = re.compile(r"\breit\b|real estate investment trust", re.IGNORECASE)
_INVESTMENT_TRUST = re.compile(r"\binvestment trust\b", re.IGNORECASE)
_FUND_WORD = re.compile(r"\bfund\b(?!\s+manage)", re.IGNORECASE)


def load_overrides(path: Path | None) -> dict[str, dict[str, dict[str, Any]]]:
    """Reviewed per-ticker decisions: ``fund_or_trust`` and ``operating`` maps.

    A missing or unreadable file means no overrides; the automatic rules still apply.
    """
    empty: dict[str, dict[str, dict[str, Any]]] = {"fund_or_trust": {}, "operating": {}}
    if path is None:
        return empty
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return empty
    if not isinstance(raw, dict):
        return empty
    out = dict(empty)
    for key in ("fund_or_trust", "operating"):
        block = raw.get(key)
        if isinstance(block, dict):
            out[key] = {
                str(ticker).strip().upper(): (entry if isinstance(entry, dict) else {})
                for ticker, entry in block.items()
            }
    return out


def _text(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def classify_fund_or_trust(
    ticker: str,
    row: dict | None,
    overrides: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, str] | None:
    """Return ``{basis, detail}`` when the name is a fund or investment trust, else None.

    Order: reviewed override (either way), REIT carve-out, then sector label,
    Yahoo industry, Yahoo quote type and name. The name rules are only
    "investment trust" and "fund" (not "fund management"); anything subtler
    (GCP Infrastructure Investments, 3i Group, Australian listed investment
    companies) is in the override list, not a looser pattern.
    """
    row = row if isinstance(row, dict) else {}
    key = str(ticker or "").strip().upper()
    overrides = overrides or {}
    if key in (overrides.get("operating") or {}):
        return None
    listed = (overrides.get("fund_or_trust") or {}).get(key)
    if listed is not None:
        why = str(listed.get("why") or "reviewed override")
        return {"basis": BASIS_OVERRIDE, "detail": why}

    name = _text(row, "name", "long_name", "longName", "short_name", "shortName")
    sector = _text(row, "sector")
    industry = _text(row, "industry")
    quote_type = _text(row, "quote_type", "quoteType").upper()
    if _REIT.search(name) or sector.lower() in {"real estate", "reit"}:
        return None
    sector_l = sector.lower()
    for fragment in _FUND_SECTOR_FRAGMENTS:
        if fragment in sector_l:
            return {"basis": BASIS_SECTOR, "detail": f"sector label {sector!r}"}
    industry_l = industry.lower()
    for fragment in _FUND_INDUSTRY_FRAGMENTS:
        if fragment in industry_l:
            return {"basis": BASIS_INDUSTRY, "detail": f"industry {industry!r}"}
    if quote_type in _FUND_QUOTE_TYPES:
        return {"basis": BASIS_QUOTE_TYPE, "detail": f"quote type {quote_type}"}
    if _INVESTMENT_TRUST.search(name) or _FUND_WORD.search(name):
        return {"basis": BASIS_NAME, "detail": f"name {name!r}"}
    return None


def is_fund_or_trust_entry(entry: Any) -> bool:
    """True for a decline-store name entry the gate classified as a fund or trust."""
    return isinstance(entry, dict) and isinstance(entry.get(REASON_CODE), dict)
