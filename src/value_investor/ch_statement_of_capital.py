"""Companies House statement-of-capital filings (CS01 / AR01 / SH01) for share counts."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from value_investor.ch_failed_name_statements import _trim_number
from value_investor.ch_leaver_statements import _ixbrl_facts
from value_investor.research.companies_house import CH_API_BASE, RATE_LIMIT_SLEEP_S, _ch_get

logger = logging.getLogger(__name__)

_CAPITAL_TYPES = frozenset({"CS01", "AR01", "SH01", "NEWINC"})
_ORDINARY_SHARE_TOTAL_RE = re.compile(
    r"(?:total\s+number\s+of\s+)?(?:ordinary\s+shares?|equity\s+shares?)"
    r"[^0-9]{0,40}(\d[\d,\s]{4,})",
    re.I,
)
_SHARE_CLASS_ORDINARY_RE = re.compile(r"\bordinary\b", re.I)


def list_capital_filings(company_number: str, api_key: str) -> list[dict[str, Any]]:
    """Filing-history rows for capital / confirmation-statement forms."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        url = (
            f"{CH_API_BASE}/company/{urllib.parse.quote(company_number)}/filing-history?"
            + urllib.parse.urlencode({"items_per_page": 100, "start_index": start})
        )
        payload = json.loads(_ch_get(url, api_key=api_key).decode("utf-8"))
        time.sleep(RATE_LIMIT_SLEEP_S)
        items = payload.get("items") or []
        total = int(payload.get("total_count") or 0)
        for item in items:
            form = str(item.get("type") or "")
            if form not in _CAPITAL_TYPES:
                continue
            meta = (item.get("links") or {}).get("document_metadata")
            if not meta:
                continue
            rows.append(
                {
                    "transaction_id": str(item.get("transaction_id") or ""),
                    "filing_date": str(item.get("date") or ""),
                    "type": form,
                    "description": str(item.get("description") or ""),
                    "document_metadata_url": str(meta),
                }
            )
        start += len(items)
        if not items or start >= total:
            break
    rows.sort(key=lambda row: row["filing_date"])
    return rows


def _parse_plain_capital_text(text: str) -> str | None:
    best: tuple[int, str] | None = None
    for match in _ORDINARY_SHARE_TOTAL_RE.finditer(text):
        raw = re.sub(r"[\s,]", "", match.group(1))
        if not raw.isdigit():
            continue
        try:
            magnitude = int(raw)
        except ValueError:
            continue
        if magnitude < 100_000:
            continue
        if best is None or magnitude > best[0]:
            best = (magnitude, _trim_number(raw))
    return best[1] if best else None


def parse_capital_statement_html(
    html: str,
    *,
    transaction_id: str,
    filing_date: str,
) -> dict[str, Any] | None:
    """Read total ordinary shares from a CS01 / AR01 / SH01 body."""
    facts = _ixbrl_facts(html or "")
    ordinary_totals: list[tuple[int, str]] = []
    for fact in facts:
        tag = str(fact.get("tag") or "")
        if "share" not in tag or "number" not in tag:
            continue
        if not _SHARE_CLASS_ORDINARY_RE.search(tag) and "fullypaid" not in tag:
            continue
        try:
            magnitude = abs(int(Decimal(str(fact["value"]).replace(",", ""))))
        except (InvalidOperation, ValueError):
            continue
        if magnitude < 100_000:
            continue
        ordinary_totals.append((magnitude, str(fact["value"]).replace(",", "")))
    value: str | None = None
    if ordinary_totals:
        value = max(ordinary_totals, key=lambda item: item[0])[1]
    if value is None:
        value = _parse_plain_capital_text(re.sub(r"<[^>]+>", " ", html))
    if value is None:
        return None
    return {
        "value": _trim_number(value),
        "scale": "units",
        "currency": None,
        "unit": None,
        "source": "ch_statement_of_capital",
        "absent_reason": None,
        "basis": "in_issue",
        "cross_check": {"status": "unavailable"},
        "citation": {
            "transaction_id": transaction_id,
            "filing_date": filing_date,
            "page": None,
            "line": f"statement of capital ordinary shares total {value}",
            "method": "ch_capital_form",
        },
    }


def pick_capital_filing_after_period(
    filings: list[dict[str, Any]],
    period_end: str,
    *,
    within_days: int = 90,
) -> dict[str, Any] | None:
    """Nearest CS01 / AR01 after period end, else SH01, within ``within_days``."""
    try:
        period = datetime.strptime(period_end[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    in_window: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for row in filings:
        try:
            filed = datetime.strptime(str(row["filing_date"])[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except (KeyError, ValueError):
            continue
        if filed < period:
            continue
        delta = (filed - period).days
        if delta > within_days:
            continue
        form = str(row.get("type") or "")
        priority = 0 if form in {"CS01", "AR01"} else 1 if form == "SH01" else 2
        in_window.append(((priority, delta), row))
    if not in_window:
        return None
    in_window.sort(key=lambda item: item[0])
    return in_window[0][1]
