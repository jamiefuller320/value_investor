"""Companies House annual statements for UK names EODHD does not cover.

Learning question: can Companies House annual-report PDFs supply point-in-time
annual statements for failed UK names that EODHD lacks, accurately enough to
fill check A (at least 7 of 11 failed names with statements from 2013) when
combined with the EODHD coverage report?

Observe-only. ``influences_live`` is false. Nothing here is a replay and nothing
is applied to a book, signal, or knob.

Companies House data is Crown copyright, reused under the Open Government Licence.
The committed store holds extracted figures with citations. It does not hold the
PDFs.

Text layer first (pypdf, then pymupdf). Scanned pages use the same OCR stack as
``research.filings`` (pymupdf render + pytesseract), per page, because the
statement pages sit past the memo OCR page cap and the citation needs a page
number. pdfplumber is not a project dependency.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from value_investor.eodhd_coverage_check import (
    CHECK_A_MIN_WITH_FUNDAMENTALS,
    CHECK_A_TOTAL_NAMES,
    KNOWN_FAILURE_CASES,
)
from value_investor.research.companies_house import (
    CH_API_BASE,
    RATE_LIMIT_SLEEP_S,
    _ch_get,
    companies_house_api_key,
    fetch_document_bytes,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_STORE_PATH = Path("docs/data/ch_failed_name_statements.json")
DEFAULT_CACHE_DIR = Path("/tmp/ch-pdfs")
EARLIEST_MADE_UP = "2012-01-01"
CACHE_VERSION = 2
CHECK_A_BAR = CHECK_A_MIN_WITH_FUNDAMENTALS
LEARNING_QUESTION = (
    "Can Companies House annual-report PDFs supply point-in-time annual statements "
    "for failed UK names that EODHD lacks, accurately enough to fill check A "
    "(at least 7 of 11 failed names with statements from 2013) when combined with EODHD?"
)
LICENCE_NOTE = (
    "Contains Companies House information © Crown copyright. Reused under the "
    "Open Government Licence v3.0. Figures are extracted from filed annual-account "
    "PDFs with a citation to the Companies House transaction and PDF page. "
    "This is not an EODHD extract."
)
FINDING_TITLE = "Companies House statements for failed UK names"
STORE_FAILED_TITLE = "Companies House failed-name statements store unreadable"
RUNBOOK = "docs/ops/ch-failed-name-statements.md"

FIELD_NAMES = (
    "revenue",
    "operating_profit",
    "profit_attributable_to_owners",
    "basic_eps",
    "weighted_average_basic_shares",
    "net_cash_from_operating_activities",
    "capital_expenditure",
    "dividends_per_share",
    "reporting_currency",
    "fiscal_year_end",
)
MONEY_FIELDS = {
    "revenue",
    "operating_profit",
    "profit_attributable_to_owners",
    "net_cash_from_operating_activities",
    "capital_expenditure",
}

# Verified 2026-11-12 from the Companies House company profile (previous names)
# and from type-AA filing history. Hard-coded so a name search cannot swap in a
# successor title or a similarly named subsidiary.
FAILED_UK_NAMES: tuple[dict[str, str], ...] = (
    {
        "key": "carillion",
        "name": "Carillion plc",
        "company_number": "03782379",
        "verified": (
            "Profile name CARILLION PLC, incorporated 1999-05-28, status liquidation. "
            "Type AA group accounts are filed for years ended 31 December 2012-2016."
        ),
    },
    {
        "key": "thomas_cook",
        "name": "Thomas Cook Group plc",
        "company_number": "06091951",
        "verified": (
            "Profile name THOMAS COOK GROUP PLC, incorporated 2007-02-08, status liquidation. "
            "Type AA group accounts run from the year ended 30 September 2012 through 2018."
        ),
    },
    {
        "key": "debenhams",
        "name": "Debenhams plc",
        "company_number": "05448421",
        "verified": (
            "Profile name DEBENHAMS PLC, incorporated 2005-05-10, dissolved 2024-10-26. "
            "Type AA group accounts cover the retail years ended 2012-2018."
        ),
    },
    {
        "key": "patisserie_holdings",
        "name": "Patisserie Holdings plc",
        "company_number": "08963601",
        "verified": (
            "Profile name PATISSERIE HOLDINGS PLC, incorporated 2014-03-27, status liquidation. "
            "First type AA group accounts are for the year ended 30 September 2014, so there is "
            "no 2013 primary filing for this company number."
        ),
    },
    {
        "key": "sirius",
        "name": "Sirius Minerals plc",
        "company_number": "04948435",
        "verified": (
            "Previous name SIRIUS MINERALS PLC from 2010-09-28 to 2020-03-17. "
            "Now ANGLO AMERICAN CROP NUTRIENTS LIMITED (intermediate names included "
            "SIRIUS MINERALS LIMITED). Company search for 'Sirius Minerals' returns "
            "04948435 first. Type AA group accounts cover the listed years."
        ),
    },
    {
        "key": "gkn",
        "name": "GKN plc",
        "company_number": "04191106",
        "verified": (
            "Previous name GKN PLC from 2001-08-01 to 2018-08-16. Now GKN LIMITED. "
            "Same legal entity as the listed plc (renamed after the Melrose acquisition), "
            "not a similarly named subsidiary. GKN HOLDINGS LIMITED is 00066549 and is "
            "a different company. Type AA group accounts run through the year ended "
            "31 December 2017; later AA filings are accounts-type-full."
        ),
    },
    {
        "key": "sky",
        "name": "Sky plc",
        "company_number": "02247735",
        "verified": (
            "Previous name SKY PLC from 2014-11-21 to 2018-12-19, and "
            "BRITISH SKY BROADCASTING GROUP PLC from 1994-07-01 to 2014-11-21. "
            "Now SKY LIMITED. Type AA group accounts cover the June year-ends "
            "through 30 June 2018."
        ),
    },
)

CH_NAME_BY_KEY = {row["key"]: row for row in FAILED_UK_NAMES}

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_HEADER_WORDS = {
    "for",
    "the",
    "year",
    "ended",
    "ending",
    "to",
    "weeks",
    "week",
    "period",
    "months",
    "month",
    "as",
    "at",
    "and",
}
_CARRY_RE = re.compile(
    r"attributable|earnings per share|loss per share|weighted average|dividend|per share|net cash",
    re.I,
)
_REVENUE_LINE_RE = re.compile(
    r"^(?:group |total |consolidated |statutory )?(?:revenue|turnover|sales)\b",
    re.I,
)
_REVENUE_REJECT_RE = re.compile(
    r"\b(adjust\w*|tax|excise|dut(?:y|ies)|lev(?:y|ies)|vat|benefit)\b",
    re.I,
)
_INCOME_HEADING_RE = re.compile(
    r"^\s*(consolidated\s+|group\s+)?"
    r"(income statement|statement of (profit or loss|comprehensive income)|profit and loss account)\b",
    re.I,
)
_CASH_HEADING_RE = re.compile(
    r"^\s*(consolidated\s+|group\s+)?(cash flow statement|statement of cash flows)\b",
    re.I,
)
_EPS_NOTE_RE = re.compile(r"^\s*(\d{1,2}[\.\)\s]+)?earnings per share\b", re.I)
_DIV_NOTE_RE = re.compile(r"^\s*(\d{1,2}[\.\)\s]+)?dividends?\b", re.I)
_PARENT_RE = re.compile(
    r"\b(parent company|company income statement|company statement|company cash flow|"
    r"company balance sheet|notes to the company)\b",
    re.I,
)
_DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})", re.I)
_YEAR_RE = re.compile(r"\b(20[0-2]\d)\b")


def _ocr_enabled() -> bool:
    """Same switch as ``research.filings._companies_house_ocr_enabled``."""
    flag = (os.environ.get("COMPANIES_HOUSE_OCR") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def repair_spaced_decimals(text: str) -> str:
    """Join a thousands amount and a following single digit that is a lost decimal.

    Scanned £m statements often OCR ``4,080.9`` as ``4,080 9``, ``4 080 9`` or
    ``23.3p`` as ``23 3p``. A one-digit note reference (``2 3,332.6``) is left
    alone because the left side is not a comma-grouped or 3-digit amount.
    """

    def repl(match: re.Match[str]) -> str:
        return f"{match.group(1)}.{match.group(2)}"

    # A digit OCR split off inside the parentheses is part of the amount: ``(3 10.1)``.
    text = re.sub(r"\((\d)\s(\d+\.\d+)\)", r"(\1\2)", text)
    text = re.sub(r"\((\d{1,3})\s(\d{3})\s(\d)\)", r"(\1,\2.\3)", text)
    # Do not treat the fractional digit of ``100.2 148 8`` as the start of a thousands group.
    text = re.sub(r"(?<![\d.])(\d{1,3})\s(\d{3})\s(\d)(?!\d)", r"\1,\2.\3", text)
    text = re.sub(r"(\d{1,3})\s(\d)p\b", r"\1.\2p", text, flags=re.I)
    text = re.sub(r"(\(\d{1,3}(?:,\d{3})*)\s(\d)\)", r"\1.\2)", text)
    # The following character must not start another amount (``11,271 9,585``).
    text = re.sub(r"(\d{1,3}(?:,\d{3})+|\d{3,})\s(\d)(?![\d,])", repl, text)
    return text


def repair_glued_thousands(text: str) -> str:
    """Insert a decimal when a thousands group has an extra trailing digit.

    ``4,0809`` is not a valid thousands grouping; the extra digit is the pence
    of millions (``4,080.9``). ``76,641`` is already valid and is unchanged.
    A trailing zero (``20,9030``) is not turned into ``.0``: that digit may be
    a misread, and dropping it would change the digit count.
    """
    return re.sub(r"(\d{1,3}(?:,\d{3})+)([1-9])(?!\d)", r"\1.\2", text)


def _trim_number(text: str) -> str:
    dec = Decimal(text)
    if dec == dec.to_integral():
        return format(dec.to_integral(), "f")
    quantized = dec.quantize(Decimal("0.0001"))
    rendered = format(quantized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def parse_amount(token: str, *, scale: str | None) -> tuple[str, str | None, str | None]:
    """Return ``(kind, value, unit)``.

    ``kind`` is ``ok``, ``unresolved`` (decimal not recovered; do not guess),
    or ``no`` (not a number).
    """
    raw = token.strip().replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    raw = raw.replace("–", "-").replace("—", "-").replace("−", "-")
    # OCR drops one side of a parenthesis: ``37)`` or ``(21.6``.
    if raw.count("(") < raw.count(")") and raw.endswith(")"):
        raw = raw[:-1]
    elif raw.count("(") > raw.count(")") and raw.startswith("("):
        raw = raw[1:]
    unit: str | None = None
    if re.search(r"(?:\d|\))p$", raw, flags=re.I):
        unit = "pence"
        raw = raw[:-1]
    if raw in {"-", "–", "—"}:
        return "ok", "0", unit
    negative = raw.startswith("(") and raw.endswith(")")
    inner = raw[1:-1] if negative else raw
    inner = repair_glued_thousands(inner)
    if "," in inner:
        head, _, _frac = inner.partition(".")
        groups = head.split(",")
        if len(groups) < 2 or any(len(group) != 3 or not group.isdigit() for group in groups[1:]):
            # ``20,9030`` is not a thousands group. Do not drop the extra digit.
            return "unresolved", None, unit
    bare = inner.replace(",", "")
    if scale == "millions" and re.fullmatch(r"\d{1,3}\.\d{3}", bare):
        # ``7.235`` is ambiguous (a decimal, or a comma read as a dot). Do not guess.
        return "unresolved", None, unit
    if (
        scale == "millions"
        and re.fullmatch(r"\d{3,}", bare)
        and "." not in inner
        and "," not in inner
    ):
        return "unresolved", None, unit
    if unit == "pence" and re.fullmatch(r"\d{3,}", bare) and "." not in inner:
        return "unresolved", None, unit
    if not re.fullmatch(r"\d+(\.\d+)?", bare):
        return "no", None, unit
    try:
        rendered = _trim_number(("-" if negative else "") + bare)
    except InvalidOperation:
        return "no", None, unit
    # A repair must not drop or invent a digit. ``(310.1)`` stays -310.1; a
    # shorter reading such as -10.1 is rejected. Trailing zeros that the
    # display then strips are still part of the token.
    source_digits = re.sub(r"\D", "", token)
    parsed_digits = re.sub(r"\D", "", bare)
    if source_digits != parsed_digits:
        return "unresolved", None, unit
    return "ok", rendered, unit


_NUMBERISH_RE = re.compile(
    r"^(?:[\(\{\[]?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?[\)\}\]]?(?:p)?|"
    r"[\(\{\[]?-?\d+(?:\.\d+)?[\)\}\]]?(?:p)?|[-–—−])$",
    re.I,
)


def _is_numberish(token: str) -> bool:
    return bool(_NUMBERISH_RE.fullmatch(token.strip()))


def _short_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:180]


@dataclass
class AmountCell:
    kind: str
    value: str | None
    unit: str | None


@dataclass
class Candidate:
    field: str
    priority: int
    label: str
    line: str
    page: int
    current: str
    prior: str | None
    unit: str | None
    money: bool
    share_scale: str | None = None


@dataclass
class StatementPage:
    page: int
    text: str
    method: str = "fixture"
    alt_text: str = ""


@dataclass
class _PageParse:
    candidates: dict[str, list[Candidate]] = field(default_factory=dict)
    capex: list[Candidate] = field(default_factory=list)
    # A purchase line was seen but its amount does not stand on its own.
    capex_incomplete: bool = False
    rejected: dict[str, str] = field(default_factory=dict)
    currency: str | None = None
    scale: str | None = None
    currency_line: str = ""
    year_columns: list[int] | None = None
    current_idx: int | None = None
    prior_idx: int | None = None
    prior_year: int | None = None
    fiscal_year_end_read: str | None = None
    fiscal_year_end_line: str = ""
    shares_in_millions: bool = False


def _year_columns(lines: list[str]) -> list[int] | None:
    best: list[int] | None = None
    for line in lines[:40]:
        years = [int(y) for y in _YEAR_RE.findall(line)]
        if len(years) < 2:
            continue
        words = re.findall(r"[A-Za-z]+|\d+", line)
        extra = [
            word
            for word in words
            if not _YEAR_RE.fullmatch(word)
            and not re.fullmatch(r"\d{1,2}", word)
            and word.lower() not in _HEADER_WORDS
            and word.lower() not in _MONTHS
        ]
        if extra:
            continue
        if best is None or len(years) > len(best):
            best = years
    return best


def select_columns(
    years: list[int], current_year: int
) -> tuple[int | None, int | None, int | None]:
    """Pick the current-year column and, when it is a different year, the prior column.

    Several columns can share the current year (before-exceptional, exceptional,
    total). The statutory total is the rightmost of those. A header that is only
    the current year twice (a short period and its same-year comparative) uses
    the left column and does not emit a comparative.
    """
    current_idxs = [i for i, year in enumerate(years) if year == current_year]
    prior = [(i, year) for i, year in enumerate(years) if year != current_year]
    if not current_idxs:
        return None, None, None
    prior_years = {year for _, year in prior}
    if prior_years:
        current_idx = current_idxs[-1]
        if len(prior_years) == 1:
            prior_idx, prior_year = prior[-1]
            return current_idx, prior_idx, prior_year
        return current_idx, None, None
    return current_idxs[0], None, None


def _prepare_line(text: str) -> str:
    """Normalise OCR braces, then recover decimals that were spaced or glued."""
    text = text.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    # A scanned nil cell is often ``*``, ``=`` or a lone dot rather than a dash.
    text = re.sub(r"(?<=\s)[*·•=~](?=\s|$)", "-", text)
    text = re.sub(r"(?<=\s)\.(?=\s|$)", "-", text)
    return repair_glued_thousands(repair_spaced_decimals(text))


def _split_amount_row(
    text: str, n_columns: int, scale: str | None
) -> tuple[str | None, list[AmountCell], str]:
    tokens = _prepare_line(text).split()
    if not tokens:
        return None, [], "not a data line"
    values: list[str] = []
    index = len(tokens)
    while index > 0 and re.fullmatch(r"[|_.;,¦│]+", tokens[index - 1]):
        index -= 1
    while index > 0 and _is_numberish(tokens[index - 1]) and len(values) < n_columns:
        values.append(tokens[index - 1])
        index -= 1
    values.reverse()
    if not values:
        return None, [], "not a data line"
    if index > 0 and _is_numberish(tokens[index - 1]):
        if re.fullmatch(r"\d{1,2}", tokens[index - 1]) and int(tokens[index - 1]) <= 45:
            index -= 1
        else:
            return " ".join(tokens[:index]), [], "column count"
    rest = tokens[:index]
    extra_amounts = []
    note_refs = 0
    for tok in rest:
        if re.fullmatch(r"[-–—−]", tok):
            continue
        if re.fullmatch(r"\d{1,2}", tok) and int(tok) <= 45:
            note_refs += 1
            continue
        if _is_numberish(tok):
            extra_amounts.append(tok)
    if extra_amounts or note_refs > 1:
        # More amount cells sit to the left (a before/exceptional/total block
        # whose year header did not repeat the year). Do not take the rightmost pair.
        return " ".join(tokens[:index]), [], "column count"
    if len(values) != n_columns:
        return " ".join(tokens[:index]), [], "column count"
    label_tokens = tokens[:index]
    cells: list[AmountCell] = []
    unresolved = False
    for token in values:
        kind, value, unit = parse_amount(token, scale=scale)
        if kind == "unresolved":
            unresolved = True
        if kind == "no":
            return None, [], "not a data line"
        cells.append(AmountCell(kind, value, unit))
    if cells and all(cell.value and re.fullmatch(r"20\d\d", cell.value) for cell in cells):
        return None, [], "year header"
    if unresolved:
        return " ".join(label_tokens), cells, "unresolved"
    return " ".join(label_tokens), cells, "ok"


def _detect_money_unit(lines: list[str]) -> tuple[str | None, str | None, str]:
    for line in lines[:30]:
        low = line.lower().replace("’", "'").replace("‘", "'")
        if re.search(r"£\s?'?0{3}|\$\s?'?0{3}|€\s?'?0{3}", low):
            currency = "GBP"
            if "$" in line:
                currency = "USD"
            elif "€" in line:
                currency = "EUR"
            return currency, "thousands", _short_line(line)
        if re.search(r"£\s?m\b|£\s?million|sterling in millions", low):
            return "GBP", "millions", _short_line(line)
        if re.search(r"(?:us)?\$\s?m\b|\$\s?million", low):
            return "USD", "millions", _short_line(line)
        if re.search(r"€\s?m\b|€\s?million", low):
            return "EUR", "millions", _short_line(line)
    return None, None, ""


def _read_period_end(lines: list[str], year: int | None = None) -> tuple[str | None, str]:
    for line in lines[:25]:
        for match in _DATE_RE.finditer(line):
            month = _MONTHS.get(match.group(2).lower())
            found_year = int(match.group(3))
            if year is not None and found_year != year:
                continue
            if not month:
                continue
            try:
                found = date(found_year, month, int(match.group(1))).isoformat()
            except ValueError:
                continue
            return found, _short_line(line)
    return None, ""


def _share_scale(label: str) -> str | None:
    low = label.lower()
    if "million" in low:
        return "millions"
    if "thousand" in low or "'000" in low or "’000" in low or "000s" in low:
        return "thousands"
    return "units"


def _unit_from_label(label: str, token_unit: str | None) -> str | None:
    if token_unit:
        return token_unit
    low = label.lower()
    if "pence" in low:
        return "pence"
    if re.search(r"\bpounds?\b", low) or "£" in label:
        return "pounds"
    return None


def _consider(
    parsed: _PageParse,
    *,
    field_name: str,
    priority: int,
    label: str,
    line: str,
    page: int,
    cells: list[AmountCell],
    money: bool,
) -> None:
    if parsed.current_idx is None or parsed.current_idx >= len(cells):
        return
    current = cells[parsed.current_idx]
    if current.kind != "ok" or current.value is None:
        parsed.rejected.setdefault(field_name, "decimal place not recovered")
        return
    if (
        field_name == "basic_eps"
        and "." not in str(current.value)
        and abs(Decimal(current.value)) >= Decimal("10")
    ):
        # ``125`` is not a reading of ``12.5``. Leave it absent rather than guess the point.
        parsed.rejected.setdefault(field_name, "EPS decimal not recovered")
        return
    prior_value = None
    if (
        parsed.prior_idx is not None
        and parsed.prior_idx < len(cells)
        and cells[parsed.prior_idx].kind == "ok"
    ):
        prior_value = cells[parsed.prior_idx].value
    unit = _unit_from_label(label, current.unit)
    parsed.candidates.setdefault(field_name, []).append(
        Candidate(
            field=field_name,
            priority=priority,
            label=label,
            line=line,
            page=page,
            current=current.value,
            prior=prior_value,
            unit=unit,
            money=money,
            share_scale=(
                "millions"
                if field_name == "weighted_average_basic_shares"
                and _share_scale(label) == "units"
                and parsed.shares_in_millions
                else _share_scale(label)
                if field_name == "weighted_average_basic_shares"
                else None
            ),
        )
    )


def _label_fields(label: str) -> list[tuple[str, int, bool]]:
    """Return (field, priority, money) matches for a statement label."""
    low = label.lower()
    found: list[tuple[str, int, bool]] = []
    # The label has to be the revenue line. A sales-tax, excise or adjustment
    # row is not revenue even when the word sales or revenue appears on it.
    if _REVENUE_LINE_RE.match(low) and not _REVENUE_REJECT_RE.search(low):
        if re.search(r"\bgroup revenue\b", low):
            found.append(("revenue", 3, True))
        elif "total revenue" in low:
            found.append(("revenue", 1, True))
        else:
            found.append(("revenue", 2, True))
    if "operating profit" in low or "operating loss" in low or "operating (loss)" in low:
        blocked = any(
            token in low
            for token in (
                "before",
                "underlying",
                "adjusted",
                "analysed",
                "analyzed",
                "amortisation",
                "amortization",
                "jointly",
                "joint venture",
                "exceptional",
            )
        )
        if not blocked:
            priority = 2 if "group operating profit" in low else 1
            found.append(("operating_profit", priority, True))
    owners = any(
        token in low
        for token in (
            "equity holder",
            "owners of the parent",
            "owners of the company",
            "equity shareholders",
            "shareholders of the parent",
            "attributable to equity",
            "attributable to the owners",
            "attributable to owners",
        )
    )
    if (
        "attributable" in low
        and owners
        and "non-controlling" not in low
        and "non controlling" not in low
    ):
        comprehensive_only = "comprehensive" in low and not any(
            token in low
            for token in ("profit for the year", "profit after tax", "profit for the period")
        )
        if not comprehensive_only:
            found.append(("profit_attributable_to_owners", 2, True))
    basic_and_diluted = "basic and diluted" in low or "basic & diluted" in low
    per_share = (
        "earnings per share" in low
        or "loss per share" in low
        or bool(re.search(r"\beps\b", low))
        or bool(re.search(r"\blps\b", low))
    )
    if (
        re.search(r"\bbasic\b", low)
        and ("diluted" not in low or basic_and_diluted)
        and "weighted average" not in low
        and "number of shares" not in low
        and not any(token in low for token in ("underlying", "adjusted", "headline"))
        and (per_share or low.strip() == "basic")
    ):
        # "basic" alone is only EPS when the carried heading said earnings or loss per share.
        if per_share:
            if "continuing" in low or "discontinued" in low:
                found.append(("basic_eps", 1, False))
            else:
                found.append(("basic_eps", 3, False))
    if (
        "weighted average" in low
        and "share" in low
        and not ("diluted" in low and "basic" not in low)
    ):
        found.append(("weighted_average_basic_shares", 2 if "basic" in low else 1, False))
    if (
        re.search(
            r"net cash (flows? )?(generated from|from|inflow from|outflow from|used in)",
            low,
        )
        and "operating activities" in low
        and "before" not in low
    ):
        found.append(("net_cash_from_operating_activities", 2, True))
    if "per share" in low and "dividend" in low and "diluted" not in low:
        priority = 3 if re.search(r"total|full[- ]year", low) else 1
        found.append(("dividends_per_share", priority, False))
    return found


def _is_capex_ppe(label: str) -> bool:
    low = label.lower()
    if any(token in low for token in ("subsidiary", "subsidiaries", "joint", "equity", "business")):
        return False
    return bool(
        re.search(
            r"(purchase|acquisition|additions?) of (property, plant and equipment|tangible)",
            low,
        )
    )


def _is_capex_intangible(label: str) -> bool:
    low = label.lower()
    if any(token in low for token in ("subsidiary", "subsidiaries", "joint", "equity", "business")):
        return False
    return bool(re.search(r"(purchase|acquisition) of intangible", low))


def _parse_page_body(
    text: str,
    *,
    page: int,
    current_year: int,
    kinds: set[str],
    comprehensive_only: bool = False,
) -> _PageParse:
    raw_lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in raw_lines if line]
    parsed = _PageParse()
    years = _year_columns(lines)
    parsed.year_columns = years
    if not years:
        return parsed
    current_idx, prior_idx, prior_year = select_columns(years, current_year)
    parsed.current_idx = current_idx
    parsed.prior_idx = prior_idx
    parsed.prior_year = prior_year
    currency, scale, currency_line = _detect_money_unit(lines)
    parsed.currency = currency
    parsed.scale = scale
    parsed.currency_line = currency_line
    read_end, end_line = _read_period_end(lines, current_year)
    parsed.fiscal_year_end_read = read_end
    parsed.fiscal_year_end_line = end_line
    parsed.shares_in_millions = bool(
        re.search(r"millions of shares|ordinary shares\b.{0,40}\bmillion", "\n".join(lines), re.I)
    )
    if current_idx is None:
        return parsed

    pending = ""
    started = False
    saw_revenue_bridge = False
    # Profit for the year is read from the income statement. A statement of
    # comprehensive income repeats "attributable to equity holders" for total
    # comprehensive income, which is a different number.
    in_oci = comprehensive_only
    income_fields = {
        "revenue",
        "operating_profit",
        "profit_attributable_to_owners",
        "basic_eps",
        "dividends_per_share",
    }
    for line in lines:
        if re.search(r"\bstatement of comprehensive\b", line, re.I):
            in_oci = True
            pending = ""
            continue
        if re.search(r"\b(less|share of)\b.*\brevenue\b", line, re.I):
            saw_revenue_bridge = True
        if re.match(
            r"^\s*(consolidated\s+)?(balance sheet|statement of (changes|financial position))\b",
            line,
            re.I,
        ):
            if started:
                break
        label, cells, status = _split_amount_row(line, len(years), scale)
        if (
            scale == "millions"
            and parsed.current_idx is not None
            and parsed.current_idx < len(cells)
            and cells[parsed.current_idx].kind == "ok"
            and cells[parsed.current_idx].value is not None
            and row_decimal_conflict(Decimal(cells[parsed.current_idx].value), _prepare_line(line))
        ):
            # ``64.7`` beside ``785`` and ``1,005``, or ``(41)`` beside ``(1.2)``.
            cells[parsed.current_idx] = AmountCell(
                "unresolved", None, cells[parsed.current_idx].unit
            )
            status = "unresolved"
        if status == "column count" and label:
            for field_name, _priority, _money in _label_fields(label):
                parsed.rejected.setdefault(
                    field_name, "column count does not match the year header"
                )
            pending = _short_line(label) if _CARRY_RE.search(label) else ""
            continue
        if label is None:
            if _CARRY_RE.search(line):
                pending = _short_line(line)
            elif line.strip():
                pending = ""
            continue
        if (
            pending
            and len(label.split()) <= 5
            and not re.search(r"attributable|earnings per share|weighted average", label, re.I)
        ):
            label = f"{pending} {label}".strip()
        pending = ""
        if len(label.split()) > 14:
            continue
        current_ok = status == "ok" or (
            status == "unresolved"
            and parsed.current_idx is not None
            and parsed.current_idx < len(cells)
            and cells[parsed.current_idx].kind == "ok"
        )
        if not current_ok:
            if label and "cash" in kinds and (_is_capex_ppe(label) or _is_capex_intangible(label)):
                # Do not publish property, plant and equipment alone when the
                # intangibles line was on the page and could not be read.
                parsed.capex_incomplete = True
            if status == "unresolved":
                for field_name, _priority, _money in _label_fields(label):
                    parsed.rejected.setdefault(field_name, "decimal place not recovered")
            continue
        matched = False
        for field_name, priority, money in _label_fields(label):
            if in_oci and field_name in income_fields:
                continue
            if field_name in {
                "revenue",
                "operating_profit",
                "profit_attributable_to_owners",
                "basic_eps",
            }:
                if (
                    "income" not in kinds
                    and "income_maybe" not in kinds
                    and "eps_note" not in kinds
                ):
                    continue
            if (
                field_name == "weighted_average_basic_shares"
                and "eps_note" not in kinds
                and "income" not in kinds
            ):
                continue
            if field_name == "net_cash_from_operating_activities" and "cash" not in kinds:
                continue
            if (
                field_name == "dividends_per_share"
                and "dividend_note" not in kinds
                and "income" not in kinds
            ):
                continue
            _consider(
                parsed,
                field_name=field_name,
                priority=priority,
                label=label,
                line=line,
                page=page,
                cells=cells,
                money=money,
            )
            matched = True
        if "cash" in kinds and (_is_capex_ppe(label) or _is_capex_intangible(label)):
            _consider(
                parsed,
                field_name="capital_expenditure",
                priority=2 if _is_capex_ppe(label) else 1,
                label=label,
                line=line,
                page=page,
                cells=cells,
                money=True,
            )
            if parsed.candidates.get("capital_expenditure"):
                parsed.capex.append(parsed.candidates["capital_expenditure"][-1])
            matched = True
        if matched:
            started = True
    if saw_revenue_bridge:
        kept = [
            cand
            for cand in parsed.candidates.get("revenue") or []
            if "total revenue" not in cand.label.lower()
        ]
        if kept:
            parsed.candidates["revenue"] = kept
        else:
            parsed.candidates.pop("revenue", None)
            parsed.rejected["revenue"] = (
                "group revenue line was not read; total revenue includes joint-venture "
                "share and was not used"
            )
    if "eps_note" in kinds and "weighted_average_basic_shares" not in parsed.candidates:
        prose = _prepare_line("\n".join(lines))
        match = re.search(
            r"weighted average number of ordinary shares\b.{0,180}?(\d{2,4}\.\d)\s*million",
            prose,
            re.I | re.S,
        )
        if match:
            sentence = _short_line(match.group(0))
            parsed.candidates["weighted_average_basic_shares"] = [
                Candidate(
                    field="weighted_average_basic_shares",
                    priority=1,
                    label=sentence,
                    line=sentence,
                    page=page,
                    current=match.group(1),
                    prior=None,
                    unit=None,
                    money=False,
                    share_scale="millions",
                )
            ]
    return parsed


def _heading_line(line: str, pattern: re.Pattern[str], *, max_len: int) -> bool:
    """True when the line is the statement heading, not a sentence that mentions it."""
    stripped = line.strip(" .|")
    if not stripped or len(stripped) > max_len:
        return False
    match = pattern.match(stripped)
    if not match:
        return False
    rest = stripped[match.end() :].strip(" .|")
    return len(rest) <= 8


def _heading_kinds(text: str) -> set[str]:
    head = "\n".join(text.splitlines()[:18])
    if _PARENT_RE.search(head):
        return set()
    kinds: set[str] = set()
    income_line = False
    maybe_line = False
    for line in text.splitlines()[:24]:
        stripped = line.strip(" .|")
        if (
            len(stripped) <= 48
            and re.search(r"income statement\b", stripped, re.I)
            and not re.search(r"recognis|impact|items|five.year|summary", stripped, re.I)
        ):
            income_line = True
        elif _heading_line(line, _INCOME_HEADING_RE, max_len=70):
            if re.search(r"comprehensive income", line, re.I) and not re.search(
                r"income statement|profit or loss|profit and loss", line, re.I
            ):
                maybe_line = True
            else:
                income_line = True
        if _heading_line(line, _CASH_HEADING_RE, max_len=70):
            kinds.add("cash")
        if _heading_line(line, _EPS_NOTE_RE, max_len=40):
            kinds.add("eps_note")
        if _heading_line(line, _DIV_NOTE_RE, max_len=40):
            kinds.add("dividend_note")
    if income_line:
        kinds.add("income")
    elif maybe_line:
        kinds.add("income_maybe")
    return kinds


def _best_candidate(cands: list[Candidate]) -> Candidate | None:
    if not cands:
        return None
    top = max(cand.priority for cand in cands)
    return next(cand for cand in cands if cand.priority == top)


def _citation(transaction_id: str, cand: Candidate) -> dict[str, Any]:
    return {
        "transaction_id": transaction_id,
        "page": cand.page,
        "line": _short_line(cand.line),
    }


def _empty_field(reason: str, *, source: str = "primary") -> dict[str, Any]:
    return {
        "value": None,
        "scale": None,
        "currency": None,
        "unit": None,
        "source": source,
        "absent_reason": reason,
        "citation": None,
    }


def _filled_field(
    cand: Candidate,
    *,
    transaction_id: str,
    source: str,
    scale: str | None,
    currency: str | None,
    value: str | None = None,
    extra_line: str | None = None,
) -> dict[str, Any]:
    use_scale = scale if cand.money else cand.share_scale
    use_currency = currency if cand.money else None
    citation = _citation(transaction_id, cand)
    if extra_line:
        citation["line"] = _short_line(f"{cand.line} | {extra_line}")
    return {
        "value": cand.current if value is None else value,
        "scale": use_scale,
        "currency": use_currency,
        "unit": cand.unit,
        "source": source,
        "absent_reason": None,
        "citation": citation,
    }


def _capex_field(
    components: list[Candidate],
    *,
    transaction_id: str,
    scale: str | None,
    currency: str | None,
) -> dict[str, Any]:
    ppe = [cand for cand in components if _is_capex_ppe(cand.label)]
    intang = [cand for cand in components if _is_capex_intangible(cand.label)]
    chosen = []
    if ppe:
        chosen.append(ppe[0])
    if intang:
        chosen.append(intang[0])
    if not chosen:
        return _empty_field("purchase of property, plant and equipment not found on the cash flow")
    total = sum(Decimal(cand.current) for cand in chosen)
    note = None
    if ppe and not intang:
        note = "intangible purchases not shown on the cash flow; value is property, plant and equipment only"
    elif intang and not ppe:
        note = (
            "property, plant and equipment purchases not shown; value is intangible purchases only"
        )
    primary = chosen[0]
    extra = " | ".join(_short_line(cand.line) for cand in chosen[1:])
    field_row = _filled_field(
        primary,
        transaction_id=transaction_id,
        source="primary",
        scale=scale,
        currency=currency,
        value=_trim_number(str(total)),
        extra_line=extra or None,
    )
    field_row["components"] = [
        {"label": _short_line(cand.label), "value": cand.current, "page": cand.page}
        for cand in chosen
    ]
    if note:
        field_row["note"] = note
    return field_row


def _dividend_field(
    cands: list[Candidate], rejected: dict[str, str], transaction_id: str
) -> dict[str, Any]:
    if not cands:
        return _empty_field(rejected.get("dividends_per_share", "dividend per share not found"))
    totals = [cand for cand in cands if cand.priority >= 3]
    if totals:
        return _filled_field(
            totals[0], transaction_id=transaction_id, source="primary", scale=None, currency=None
        )
    if len(cands) == 1:
        return _filled_field(
            cands[0], transaction_id=transaction_id, source="primary", scale=None, currency=None
        )
    return _empty_field(
        "interim and final dividends per share are shown separately; no total line was read"
    )


def parse_statement_pages(
    pages: list[StatementPage],
    *,
    fiscal_year_end: str,
    filing_date: str,
    transaction_id: str,
) -> dict[str, Any]:
    """Parse already-extracted page text. No network and no OCR."""
    current_year = int(fiscal_year_end[:4])
    classified: list[tuple[StatementPage, set[str]]] = []
    for page in pages:
        kinds = _heading_kinds(page.text)
        if kinds:
            classified.append((page, kinds))

    income_pages = [row for row in classified if "income" in row[1] or "income_maybe" in row[1]]
    definite = [row for row in income_pages if "income" in row[1]]
    if definite:
        income_pages = definite
    consolidated = [
        row
        for row in income_pages
        if re.search(r"consolidat|\bgroup\b", "\n".join(row[0].text.splitlines()[:8]), re.I)
    ]
    if consolidated:
        income_pages = consolidated

    cash_pages = [row for row in classified if "cash" in row[1]]
    cash_consolidated = [
        row
        for row in cash_pages
        if re.search(r"consolidat|\bgroup\b", "\n".join(row[0].text.splitlines()[:8]), re.I)
    ]
    if cash_consolidated:
        cash_pages = cash_consolidated

    note_pages = [row for row in classified if "eps_note" in row[1] or "dividend_note" in row[1]]

    def score(parsed: _PageParse, names: tuple[str, ...]) -> int:
        return sum(1 for name in names if parsed.candidates.get(name))

    income_parsed: _PageParse | None = None
    best_income = -1
    for page, kinds in income_pages:
        body_kinds = set(kinds)
        comprehensive_only = "income" not in kinds and "income_maybe" in kinds
        if "income_maybe" in body_kinds and not comprehensive_only:
            body_kinds.add("income")
        parsed = _parse_page_body(
            page.text,
            page=page.page,
            current_year=current_year,
            kinds=body_kinds,
            comprehensive_only=comprehensive_only,
        )
        ranked = score(
            parsed, ("revenue", "operating_profit", "profit_attributable_to_owners", "basic_eps")
        )
        if ranked > best_income:
            best_income = ranked
            income_parsed = parsed

    cash_parsed: _PageParse | None = None
    best_cash = -1
    for page, kinds in cash_pages:
        parsed = _parse_page_body(page.text, page=page.page, current_year=current_year, kinds=kinds)
        ranked = score(parsed, ("net_cash_from_operating_activities",)) + (1 if parsed.capex else 0)
        if ranked > best_cash:
            best_cash = ranked
            cash_parsed = parsed

    note_parsed: list[_PageParse] = []
    for page, kinds in note_pages:
        note_parsed.append(
            _parse_page_body(page.text, page=page.page, current_year=current_year, kinds=kinds)
        )

    scale = None
    currency = None
    currency_line = ""
    currency_page = None
    for source in (income_parsed, cash_parsed):
        if source and source.currency and source.scale:
            scale = source.scale
            currency = source.currency
            currency_line = source.currency_line
            break
    if income_parsed and income_parsed.currency_line:
        currency_page = next((page.page for page, _ in income_pages), None)

    rejected: dict[str, str] = {}
    for source in (income_parsed, cash_parsed, *note_parsed):
        if source:
            rejected.update(source.rejected)

    def pool(*sources: _PageParse | None, name: str) -> list[Candidate]:
        rows: list[Candidate] = []
        for source in sources:
            if source:
                rows.extend(source.candidates.get(name) or [])
        return rows

    fields: dict[str, Any] = {}
    income_pool_args = (income_parsed,)
    for name in ("revenue", "operating_profit", "profit_attributable_to_owners"):
        chosen = _best_candidate(pool(*income_pool_args, name=name))
        if chosen is None and name == "basic_eps":
            chosen = _best_candidate(pool(*note_parsed, name=name))
        if chosen is None:
            fields[name] = _empty_field(
                rejected.get(name, f"{name.replace('_', ' ')} not found on the statement")
            )
        else:
            fields[name] = _filled_field(
                chosen,
                transaction_id=transaction_id,
                source="primary",
                scale=scale,
                currency=currency,
            )

    eps_from_income = _best_candidate(pool(income_parsed, name="basic_eps"))
    eps_from_note = _best_candidate(pool(*note_parsed, name="basic_eps"))
    eps_choice = eps_from_income or eps_from_note
    if eps_choice is None:
        fields["basic_eps"] = _empty_field(
            rejected.get("basic_eps", "basic earnings per share not found on the statement")
        )
    else:
        fields["basic_eps"] = _filled_field(
            eps_choice, transaction_id=transaction_id, source="primary", scale=None, currency=None
        )

    shares = _best_candidate(
        pool(income_parsed, *note_parsed, name="weighted_average_basic_shares")
    )
    if shares is None:
        fields["weighted_average_basic_shares"] = _empty_field(
            rejected.get(
                "weighted_average_basic_shares",
                "weighted average number of shares not found in the earnings-per-share note",
            )
        )
    else:
        fields["weighted_average_basic_shares"] = _filled_field(
            shares, transaction_id=transaction_id, source="primary", scale=None, currency=None
        )
    _reject_eps_if_earnings_disagree(fields)

    cash_choice = _best_candidate(pool(cash_parsed, name="net_cash_from_operating_activities"))
    if cash_choice is None:
        fields["net_cash_from_operating_activities"] = _empty_field(
            rejected.get(
                "net_cash_from_operating_activities",
                "net cash from operating activities not found on the cash flow statement",
            )
        )
    else:
        fields["net_cash_from_operating_activities"] = _filled_field(
            cash_choice,
            transaction_id=transaction_id,
            source="primary",
            scale=scale,
            currency=currency,
        )

    if cash_parsed and cash_parsed.capex_incomplete:
        fields["capital_expenditure"] = _empty_field(
            "a purchase line was read but its amount did not agree with the row"
        )
    else:
        fields["capital_expenditure"] = _capex_field(
            (cash_parsed.capex if cash_parsed else []),
            transaction_id=transaction_id,
            scale=scale,
            currency=currency,
        )
    div_cands = pool(income_parsed, *note_parsed, name="dividends_per_share")
    fields["dividends_per_share"] = _dividend_field(div_cands, rejected, transaction_id)

    if currency and scale:
        fields["reporting_currency"] = {
            "value": currency,
            "scale": scale,
            "currency": currency,
            "unit": None,
            "source": "primary",
            "absent_reason": None,
            "citation": {
                "transaction_id": transaction_id,
                "page": currency_page,
                "line": currency_line or f"{currency} {scale}",
            },
        }
    else:
        fields["reporting_currency"] = _empty_field(
            "currency unit (£m, £'000, $m, €m) not found on the statement header"
        )

    read_end = income_parsed.fiscal_year_end_read if income_parsed else None
    end_line = income_parsed.fiscal_year_end_line if income_parsed else ""
    if read_end is None and cash_parsed:
        read_end = cash_parsed.fiscal_year_end_read
        end_line = cash_parsed.fiscal_year_end_line
    if read_end:
        fields["fiscal_year_end"] = {
            "value": read_end,
            "scale": None,
            "currency": None,
            "unit": None,
            "source": "primary",
            "absent_reason": None,
            "citation": {
                "transaction_id": transaction_id,
                "page": next((page.page for page, _ in income_pages), None),
                "line": end_line,
            },
        }
    else:
        fields["fiscal_year_end"] = {
            "value": fiscal_year_end,
            "scale": None,
            "currency": None,
            "unit": None,
            "source": "primary",
            "absent_reason": None,
            "citation": {
                "transaction_id": transaction_id,
                "page": None,
                "line": "Companies House filing-history made_up_date",
            },
            "note": "not printed as a parsed date on the statement page; Companies House made_up_date used",
        }

    comparative = _comparative_record(
        income_parsed,
        cash_parsed,
        note_parsed,
        transaction_id=transaction_id,
        filing_date=filing_date,
        scale=scale,
        currency=currency,
        page_text="\n".join(page.text for page, _ in income_pages),
    )
    methods = sorted({page.method for page in pages})
    warnings: list[str] = []
    if read_end and read_end != fiscal_year_end:
        warnings.append(
            f"statement date {read_end} differs from Companies House made_up_date {fiscal_year_end}"
        )
    if not income_pages:
        warnings.append("no income-statement heading found")
    if not cash_pages:
        warnings.append("no cash-flow heading found")
    return {
        "fiscal_year_end": fiscal_year_end,
        "fiscal_year": current_year,
        "filing_date": filing_date,
        "transaction_id": transaction_id,
        "source": "primary",
        "fields": fields,
        "comparative": comparative,
        "methods": methods,
        "warnings": warnings,
        "pages": [
            {"page": page.page, "method": page.method, "kinds": sorted(_heading_kinds(page.text))}
            for page in pages
        ],
    }


def _comparative_record(
    income_parsed: _PageParse | None,
    cash_parsed: _PageParse | None,
    note_parsed: list[_PageParse],
    *,
    transaction_id: str,
    filing_date: str,
    scale: str | None,
    currency: str | None,
    page_text: str,
) -> dict[str, Any] | None:
    prior_year = None
    if income_parsed and income_parsed.prior_year:
        prior_year = income_parsed.prior_year
    elif cash_parsed and cash_parsed.prior_year:
        prior_year = cash_parsed.prior_year
    if prior_year is None:
        return None
    # Same-year comparatives (short periods) are not used to fill a missing year.
    current_year = None
    if income_parsed and income_parsed.year_columns and income_parsed.current_idx is not None:
        current_year = income_parsed.year_columns[income_parsed.current_idx]
    if current_year is not None and prior_year == current_year:
        return None

    fields: dict[str, Any] = {}

    def take(name: str, sources: list[_PageParse | None], money: bool) -> None:
        chosen = None
        for source in sources:
            if not source:
                continue
            cand = _best_candidate(source.candidates.get(name) or [])
            if cand and cand.prior is not None:
                chosen = cand
                break
        if chosen is None:
            return
        row = _filled_field(
            chosen,
            transaction_id=transaction_id,
            source="comparative",
            scale=scale,
            currency=currency if money else None,
            value=chosen.prior,
        )
        row["source"] = "comparative"
        fields[name] = row

    take("revenue", [income_parsed], True)
    take("operating_profit", [income_parsed], True)
    take("profit_attributable_to_owners", [income_parsed], True)
    take("basic_eps", [income_parsed, *note_parsed], False)
    take("weighted_average_basic_shares", [income_parsed, *note_parsed], False)
    take("net_cash_from_operating_activities", [cash_parsed], True)
    take("dividends_per_share", [income_parsed, *note_parsed], False)
    if not fields:
        return None
    end, _line = _read_period_end(page_text.splitlines(), prior_year)
    return {
        "source": "comparative",
        "fiscal_year": prior_year,
        "fiscal_year_end": end,
        "filing_date": filing_date,
        "transaction_id": transaction_id,
        "fields": fields,
    }


def _eps_value(fields: dict[str, Any] | None) -> str | None:
    if not fields:
        return None
    row = fields.get("basic_eps") or {}
    value = row.get("value")
    return str(value) if value not in (None, "") else None


def years_with_eps(filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Years with basic EPS. A comparative fills a year only when no primary EPS exists."""
    primary: dict[int, dict[str, Any]] = {}
    comparative: dict[int, dict[str, Any]] = {}
    for filing in filings:
        year = int(filing["fiscal_year"])
        if _eps_value(filing.get("fields")):
            primary[year] = {
                "year": year,
                "source": "primary",
                "fiscal_year_end": filing.get("fiscal_year_end"),
                "filing_date": filing.get("filing_date"),
                "transaction_id": filing.get("transaction_id"),
                "value": _eps_value(filing.get("fields")),
            }
        comp = filing.get("comparative") or {}
        comp_year = comp.get("fiscal_year")
        if comp_year is None:
            continue
        comp_year = int(comp_year)
        if _eps_value(comp.get("fields")):
            comparative[comp_year] = {
                "year": comp_year,
                "source": "comparative",
                "fiscal_year_end": comp.get("fiscal_year_end"),
                "filing_date": comp.get("filing_date"),
                "transaction_id": comp.get("transaction_id"),
                "value": _eps_value(comp.get("fields")),
            }
    rows = []
    for year in sorted(set(primary) | set(comparative)):
        if year in primary:
            rows.append(primary[year])
        else:
            rows.append(comparative[year])
    return rows


def statements_from_2013(eps_years: list[dict[str, Any]]) -> bool:
    years = [int(row["year"]) for row in eps_years if int(row["year"]) >= 2013]
    return bool(years) and min(years) <= 2013


def field_coverage(filings: list[dict[str, Any]]) -> dict[str, Any]:
    found = {name: 0 for name in FIELD_NAMES}
    absent = {name: 0 for name in FIELD_NAMES}
    for filing in filings:
        fields = filing.get("fields") or {}
        for name in FIELD_NAMES:
            row = fields.get(name) or {}
            if row.get("value") not in (None, ""):
                found[name] += 1
            else:
                absent[name] += 1
    return {"found": found, "absent": absent}


def combined_check_a(
    name_rows: list[dict[str, Any]], eodhd_payload: dict[str, Any] | None
) -> dict[str, Any]:
    """Count the 11 check-A names that have statements from 2013 via EODHD or Companies House."""
    eodhd_flags: dict[str, bool] = {}
    checks = (eodhd_payload or {}).get("checks") or {}
    survivorship = checks.get("a_survivorship") or {}
    for row in survivorship.get("rows") or []:
        if isinstance(row, dict) and row.get("key"):
            eodhd_flags[str(row["key"])] = row.get("fundamentals_depth_from_2013") is True
    ch_flags = {
        str(row["key"]): bool(row.get("statements_from_2013"))
        for row in name_rows
        if row.get("key")
    }
    rows = []
    for case in KNOWN_FAILURE_CASES:
        key = str(case["key"])
        eodhd_ok = eodhd_flags.get(key, False)
        ch_ok = ch_flags.get(key, False)
        rows.append(
            {
                "key": key,
                "name": case["name"],
                "eodhd_statements_from_2013": eodhd_ok,
                "ch_statements_from_2013": ch_ok,
                "ch_applicable": key in CH_NAME_BY_KEY,
                "combined_statements_from_2013": eodhd_ok or ch_ok,
            }
        )
    count = sum(1 for row in rows if row["combined_statements_from_2013"])
    return {
        "bar": CHECK_A_BAR,
        "total_names": CHECK_A_TOTAL_NAMES,
        "combined_check_a_with_statements": count,
        "pass": count >= CHECK_A_BAR,
        "rows": rows,
        "eodhd_report_present": eodhd_payload is not None,
    }


QC_EPS_JUMP = "eps_jump"
QC_EPS_EARNINGS = "eps_inconsistent_with_earnings"
QC_REVENUE_PROFIT = "revenue_below_operating_profit"
QC_UNIT_SLIP = "pence_pound_unit_slip"


def _decimal_field(
    fields: dict[str, Any] | None, name: str
) -> tuple[Decimal, dict[str, Any]] | None:
    row = (fields or {}).get(name) or {}
    raw = row.get("value")
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw)), row
    except InvalidOperation:
        return None


def years_with_field(filings: list[dict[str, Any]], field_name: str) -> list[dict[str, Any]]:
    """One row per fiscal year. A primary value wins over a comparative."""
    primary: dict[int, dict[str, Any]] = {}
    comparative: dict[int, dict[str, Any]] = {}
    for filing in filings:
        year = filing.get("fiscal_year")
        if year is None:
            continue
        parsed = _decimal_field(filing.get("fields"), field_name)
        if parsed is not None:
            _value, row = parsed
            primary[int(year)] = {
                "year": int(year),
                "source": "primary",
                "value": row.get("value"),
                "unit": row.get("unit"),
                "scale": row.get("scale"),
                "currency": row.get("currency"),
            }
        comp = filing.get("comparative") or {}
        comp_year = comp.get("fiscal_year")
        if comp_year is None:
            continue
        comp_parsed = _decimal_field(comp.get("fields"), field_name)
        if comp_parsed is not None:
            _value, row = comp_parsed
            comparative[int(comp_year)] = {
                "year": int(comp_year),
                "source": "comparative",
                "value": row.get("value"),
                "unit": row.get("unit"),
                "scale": row.get("scale"),
                "currency": row.get("currency"),
            }
    rows = []
    for year in sorted(set(primary) | set(comparative)):
        rows.append(primary[year] if year in primary else comparative[year])
    return rows


def _to_absolute(value: Decimal, scale: str | None) -> Decimal:
    if scale == "millions":
        return value * Decimal("1000000")
    if scale == "thousands":
        return value * Decimal("1000")
    return value


def _share_count(value: Decimal, scale: str | None) -> Decimal:
    if scale == "millions":
        return value * Decimal("1000000")
    if scale in (None, "") and abs(value) < Decimal("100000"):
        return value * Decimal("1000000")
    return value


def _expected_eps(
    profit: Decimal,
    profit_scale: str | None,
    shares: Decimal,
    share_scale: str | None,
    unit: str | None,
) -> Decimal | None:
    count = _share_count(shares, share_scale)
    if count == 0:
        return None
    pounds = _to_absolute(profit, profit_scale) / count
    if unit == "pence":
        return pounds * Decimal("100")
    return pounds


def _eps_gaps(
    eps: Decimal,
    profit: Decimal,
    profit_scale: str | None,
    shares: Decimal,
    share_scale: str | None,
    unit: str | None,
) -> list[Decimal]:
    """Gaps against profit/shares. An unset unit is tried as pence and as pounds."""
    units = [unit] if unit else ["pence", "pounds"]
    gaps: list[Decimal] = []
    for candidate in units:
        expected = _expected_eps(profit, profit_scale, shares, share_scale, candidate)
        if expected is None:
            continue
        gaps.append(abs(eps - expected) / max(abs(expected), Decimal("0.01")))
    return gaps


def _reject_eps_if_earnings_disagree(fields: dict[str, Any]) -> None:
    """Drop basic EPS when it is not profit attributable divided by the share count.

    No replacement is written. A missing share count leaves the EPS alone; the
    cross-year magnitude check is the value gate's job.
    """
    eps = _decimal_field(fields, "basic_eps")
    profit = _decimal_field(fields, "profit_attributable_to_owners")
    shares = _decimal_field(fields, "weighted_average_basic_shares")
    if not (eps and profit and shares):
        return
    gaps = _eps_gaps(
        eps[0],
        profit[0],
        profit[1].get("scale"),
        shares[0],
        shares[1].get("scale"),
        eps[1].get("unit"),
    )
    if gaps and min(gaps) > Decimal("0.15"):
        fields["basic_eps"] = _empty_field(
            "basic EPS does not match profit attributable divided by weighted shares"
        )


def plausibility_flags(filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag suspicious figures. Values are kept; nothing is dropped.

    Checks: EPS magnitude jumps above 10x between adjacent years; EPS more than
    20% away from profit attributable divided by weighted shares when all three
    exist; revenue below operating profit; pence/pound unit slips.
    """
    flags: list[dict[str, Any]] = []
    eps_rows = [
        row for row in years_with_field(filings, "basic_eps") if row.get("value") not in (None, "")
    ]
    for prev, curr in zip(eps_rows, eps_rows[1:], strict=False):
        if int(curr["year"]) - int(prev["year"]) != 1:
            continue
        try:
            left = abs(Decimal(str(prev["value"])))
            right = abs(Decimal(str(curr["value"])))
        except InvalidOperation:
            continue
        small = min(left, right)
        large = max(left, right)
        if large > Decimal("10") * max(small, Decimal("0.005")) and large >= Decimal("0.05"):
            flags.append(
                {
                    "code": QC_EPS_JUMP,
                    "years": [prev["year"], curr["year"]],
                    "detail": f"basic EPS {prev['value']} then {curr['value']}",
                }
            )
        if prev.get("unit") != curr.get("unit") and small > 0:
            ratio = large / small
            if Decimal("50") <= ratio <= Decimal("200"):
                flags.append(
                    {
                        "code": QC_UNIT_SLIP,
                        "years": [prev["year"], curr["year"]],
                        "detail": (
                            f"unit changed {prev.get('unit')} to {curr.get('unit')} "
                            f"with a {ratio:.0f}x raw jump"
                        ),
                    }
                )
    by_year_filings: dict[int, dict[str, Any]] = {}
    for filing in filings:
        year = filing.get("fiscal_year")
        if year is not None:
            by_year_filings[int(year)] = filing
    for row in eps_rows:
        filing = by_year_filings.get(int(row["year"]))
        fields = (filing or {}).get("fields") if row["source"] == "primary" else None
        if row["source"] != "primary":
            comp = (filing or {}).get("comparative") or {}
            if comp.get("fiscal_year") == row["year"]:
                fields = comp.get("fields")
            else:
                fields = None
                for other in filings:
                    comp = other.get("comparative") or {}
                    if comp.get("fiscal_year") == row["year"]:
                        fields = comp.get("fields")
                        break
        if not fields:
            continue
        profit = _decimal_field(fields, "profit_attributable_to_owners")
        shares = _decimal_field(fields, "weighted_average_basic_shares")
        eps = _decimal_field(fields, "basic_eps")
        if not (profit and shares and eps):
            continue
        unit = eps[1].get("unit") or row.get("unit") or "pounds"
        expected = _expected_eps(
            profit[0], profit[1].get("scale"), shares[0], shares[1].get("scale"), unit
        )
        if expected is None:
            continue
        gap = abs(eps[0] - expected) / max(abs(expected), Decimal("0.01"))
        if gap > Decimal("0.2"):
            flags.append(
                {
                    "code": QC_EPS_EARNINGS,
                    "years": [row["year"]],
                    "detail": (
                        f"basic EPS {eps[0]} vs profit/shares {expected.quantize(Decimal('0.01'))} "
                        f"({unit})"
                    ),
                }
            )
            other_unit = "pounds" if unit == "pence" else "pence"
            other = _expected_eps(
                profit[0],
                profit[1].get("scale"),
                shares[0],
                shares[1].get("scale"),
                other_unit,
            )
            if other is not None:
                other_gap = abs(eps[0] - other) / max(abs(other), Decimal("0.01"))
                if other_gap <= Decimal("0.2"):
                    flags.append(
                        {
                            "code": QC_UNIT_SLIP,
                            "years": [row["year"]],
                            "detail": f"EPS matches {other_unit}, stored unit is {unit}",
                        }
                    )
        if unit == "pounds" and abs(eps[0]) >= Decimal("20"):
            flags.append(
                {
                    "code": QC_UNIT_SLIP,
                    "years": [row["year"]],
                    "detail": f"EPS {eps[0]} stored as pounds",
                }
            )
        if unit == "pence" and abs(eps[0]) >= Decimal("5000"):
            flags.append(
                {
                    "code": QC_UNIT_SLIP,
                    "years": [row["year"]],
                    "detail": f"EPS {eps[0]} stored as pence",
                }
            )
    for filing in filings:
        year = filing.get("fiscal_year")
        fields = filing.get("fields") or {}
        revenue = _decimal_field(fields, "revenue")
        operating = _decimal_field(fields, "operating_profit")
        if not (revenue and operating and year is not None):
            continue
        revenue_abs = _to_absolute(revenue[0], revenue[1].get("scale"))
        operating_abs = _to_absolute(operating[0], operating[1].get("scale"))
        if revenue_abs < operating_abs:
            flags.append(
                {
                    "code": QC_REVENUE_PROFIT,
                    "years": [int(year)],
                    "detail": f"revenue {revenue[0]} below operating profit {operating[0]}",
                }
            )
    return flags


_FINANCIAL_NAME_RE = re.compile(
    r"bank|insurance|assurance|asset management|investment trust|\breit\b|"
    r"\blife\b|annuity|building society",
    re.I,
)
_JUMP_EXPLAINED_RE = re.compile(
    r"exceptional|discontinued|disposal|impairment|restat|demerger",
    re.I,
)
_GATED_FIELDS = {
    "revenue",
    "operating_profit",
    "profit_attributable_to_owners",
    "basic_eps",
    "weighted_average_basic_shares",
    "net_cash_from_operating_activities",
    "capital_expenditure",
    "dividends_per_share",
}
GATE_DIGIT_COUNT = "digit_count"
GATE_SIGN = "sign"
GATE_EPS_DECIMAL = "eps_decimal"
GATE_EPS_EARNINGS = "eps_versus_earnings"
GATE_OPERATING_PROFIT = "operating_profit_above_revenue"
GATE_SCALE_JUMP = "scale_jump"
GATE_ROW_DECIMAL = "row_decimal"
_ROW_AMOUNT_RE = re.compile(r"[(\[{]?-?\d[\d,]*(?:\.\d+)?[)\]}]?")


def _valid_thousands(head: str) -> bool:
    groups = head.split(",")
    return (
        len(groups) >= 2
        and groups[0].isdigit()
        and 1 <= len(groups[0]) <= 3
        and all(len(group) == 3 and group.isdigit() for group in groups[1:])
    )


def _classify_row_amounts(line: str) -> list[tuple[Decimal, str]]:
    """Amounts on a citation line as (absolute value, decimal|integer|invalid)."""
    text = line.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    found: list[tuple[Decimal, str]] = []
    for match in _ROW_AMOUNT_RE.finditer(text):
        token = match.group().strip("()[]{}")
        if token.startswith("-"):
            token = token[1:]
        if not token or not token[0].isdigit():
            continue
        if "." in token:
            head, _, frac = token.partition(".")
            if not frac.isdigit() or ("," in head and not _valid_thousands(head)):
                kind = "invalid"
            else:
                kind = "decimal"
        elif "," in token:
            kind = "integer" if _valid_thousands(token) else "invalid"
        else:
            kind = "integer"
        bare = token.replace(",", "")
        try:
            found.append((abs(Decimal(bare)), kind))
        except InvalidOperation:
            continue
    return found


def row_decimal_conflict(value: Decimal, line: str) -> bool:
    """True when the decimal on this value disagrees with the other amounts on its line.

    ``64.7`` beside ``785 1,005 1,093 1,058`` is the digits of 647 with a point
    inserted. ``(41)`` beside ``(1.2)`` is ``(4.1)`` with the point dropped.
    Neither is rewritten; the caller leaves the value absent.
    """
    amounts = _classify_row_amounts(line)
    magnitude = abs(value)
    integral = value == value.to_integral_value()
    if integral and Decimal("10") <= magnitude <= Decimal("99"):
        for sibling, kind in amounts:
            if kind != "decimal" or not (Decimal("0") < sibling < Decimal("100")):
                continue
            repaired = magnitude / Decimal("10")
            if magnitude / sibling > Decimal("5") and max(repaired, sibling) / min(
                repaired, sibling
            ) <= Decimal("5"):
                return True
        return False
    if integral:
        return False
    integers = [item for item, kind in amounts if kind == "integer" and item >= Decimal("100")]
    if len(integers) < 2 or max(integers) / min(integers) > Decimal("5"):
        return False
    median = sorted(integers)[len(integers) // 2]
    if median <= 0 or magnitude <= 0:
        return False
    if max(median, magnitude) / min(median, magnitude) <= Decimal("5"):
        return False
    stripped = Decimal(re.sub(r"\D", "", format(magnitude, "f")))
    if stripped <= 0:
        return False
    return max(median, stripped) / min(median, stripped) <= Decimal("5")


def is_financial_name(name: str) -> bool:
    return bool(_FINANCIAL_NAME_RE.search(name or ""))


def _citation_line(row: dict[str, Any]) -> str:
    citation = row.get("citation") or {}
    return str(citation.get("line") or "")


def _citation_tokens(line: str) -> list[tuple[str, str]]:
    """Number tokens as (digits, raw) after thousands commas are removed."""
    text = line.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    found: list[tuple[str, str]] = []
    for match in re.finditer(r"\(?-?\d+(?:\.\d+)?\)?", text):
        token = match.group()
        found.append((re.sub(r"\D", "", token), token))
    for match in re.finditer(r"\(?-?\d+\s\d(?!\d)\)?", text):
        token = match.group()
        found.append((re.sub(r"\D", "", token), token))
    return found


def _token_is_negative(token: str) -> bool:
    return token.startswith("(") or token.startswith("-") or token.endswith(")")


def citation_supports(value: Decimal, line: str) -> tuple[bool, bool, bool]:
    """Return (digits match a token, sign matches, a matching token has a decimal)."""
    want = re.sub(r"\D", "", format(abs(value), "f"))
    matches = [token for digits, token in _citation_tokens(line) if digits == want]
    if not matches:
        return False, False, False
    if value < 0:
        sign_ok = any(_token_is_negative(token) for token in matches)
    elif value > 0:
        sign_ok = any(not _token_is_negative(token) for token in matches)
    else:
        sign_ok = True
    has_decimal = any("." in token for token in matches)
    return True, sign_ok, has_decimal


def _null_value(row: dict[str, Any], reason: str, counts: dict[str, int]) -> None:
    if row.get("value") in (None, ""):
        return
    row["nulled_from"] = row.get("value")
    row["value"] = None
    row["absent_reason"] = reason
    counts[reason] = counts.get(reason, 0) + 1


def _field_rows(filings: list[dict[str, Any]], name: str) -> list[tuple[int, dict[str, Any]]]:
    """Primary wins over a comparative for the same year."""
    found: dict[int, dict[str, Any]] = {}
    for filing in filings:
        year = filing.get("fiscal_year")
        row = (filing.get("fields") or {}).get(name)
        if year is not None and isinstance(row, dict) and row.get("value") not in (None, ""):
            found[int(year)] = row
        comp = filing.get("comparative") or {}
        comp_year = comp.get("fiscal_year")
        comp_row = (comp.get("fields") or {}).get(name)
        if (
            comp_year is not None
            and int(comp_year) not in found
            and isinstance(comp_row, dict)
            and comp_row.get("value") not in (None, "")
        ):
            found[int(comp_year)] = comp_row
    return [(year, found[year]) for year in sorted(found)]


def apply_value_gate(filings: list[dict[str, Any]], *, financial: bool = False) -> dict[str, Any]:
    """Null stored values that fail a check. Nothing is replaced with a guess.

    The seven hand-verified filings are not passed through here. Counts are the
    values nulled by this call.
    """
    counts: dict[str, int] = {}
    live: list[tuple[str, int, dict[str, Any]]] = []
    for filing in filings:
        blocks = [("primary", filing.get("fiscal_year"), filing.get("fields") or {})]
        comp = filing.get("comparative") or {}
        if comp:
            blocks.append(("comparative", comp.get("fiscal_year"), comp.get("fields") or {}))
        for _source, year, fields in blocks:
            if not isinstance(fields, dict):
                continue
            for name, row in fields.items():
                if name not in _GATED_FIELDS:
                    continue
                if isinstance(row, dict) and row.get("value") not in (None, ""):
                    live.append((str(name), int(year) if year is not None else -1, row))

    for name, _year, row in live:
        if name == "capital_expenditure" and row.get("components"):
            line = _citation_line(row)
            components_ok = True
            for component in row.get("components") or []:
                try:
                    component_value = Decimal(str(component.get("value")))
                except InvalidOperation:
                    components_ok = False
                    break
                if not citation_supports(component_value, line)[0]:
                    components_ok = False
                    break
            if not components_ok:
                _null_value(row, GATE_DIGIT_COUNT, counts)
                continue
            if row.get("scale") == "millions" and any(
                row_decimal_conflict(Decimal(str(component.get("value"))), line)
                for component in row.get("components") or []
                if component.get("value") not in (None, "")
            ):
                _null_value(row, GATE_ROW_DECIMAL, counts)
            continue
        try:
            value = Decimal(str(row.get("value")))
        except InvalidOperation:
            _null_value(row, GATE_DIGIT_COUNT, counts)
            continue
        digits_ok, sign_ok, has_decimal = citation_supports(value, _citation_line(row))
        if not digits_ok:
            _null_value(row, GATE_DIGIT_COUNT, counts)
            continue
        if not sign_ok:
            _null_value(row, GATE_SIGN, counts)
            continue
        if (
            row.get("scale") == "millions"
            and name not in {"basic_eps", "weighted_average_basic_shares", "dividends_per_share"}
            and row_decimal_conflict(value, _citation_line(row))
        ):
            _null_value(row, GATE_ROW_DECIMAL, counts)
            continue
        if (
            name == "basic_eps"
            and "." not in str(row.get("value"))
            and abs(value) >= Decimal("10")
            and not has_decimal
        ):
            _null_value(row, GATE_EPS_DECIMAL, counts)

    if not financial:
        for filing in filings:
            fields = filing.get("fields") or {}
            revenue = _decimal_field(fields, "revenue")
            operating = _decimal_field(fields, "operating_profit")
            if not (revenue and operating):
                continue
            if revenue[0] <= 0:
                continue
            revenue_abs = _to_absolute(revenue[0], revenue[1].get("scale"))
            operating_abs = abs(_to_absolute(operating[0], operating[1].get("scale")))
            if operating_abs > revenue_abs:
                _null_value(operating[1], GATE_OPERATING_PROFIT, counts)

    for filing in filings:
        blocks = [filing.get("fields") or {}]
        comp = filing.get("comparative") or {}
        if comp.get("fields"):
            blocks.append(comp["fields"])
        for fields in blocks:
            eps = _decimal_field(fields, "basic_eps")
            profit = _decimal_field(fields, "profit_attributable_to_owners")
            shares = _decimal_field(fields, "weighted_average_basic_shares")
            if not (eps and profit and shares):
                continue
            gaps = _eps_gaps(
                eps[0],
                profit[0],
                profit[1].get("scale"),
                shares[0],
                shares[1].get("scale"),
                eps[1].get("unit"),
            )
            if gaps and min(gaps) > Decimal("0.15"):
                _null_value(eps[1], GATE_EPS_EARNINGS, counts)

    for name in (
        "revenue",
        "operating_profit",
        "profit_attributable_to_owners",
        "basic_eps",
        "net_cash_from_operating_activities",
        "capital_expenditure",
    ):
        rows = _field_rows(filings, name)
        snapshot = []
        for year, row in rows:
            try:
                snapshot.append(
                    (
                        year,
                        row,
                        Decimal(str(row["value"])),
                        row.get("scale"),
                        row.get("unit"),
                    )
                )
            except InvalidOperation:
                continue
        for prev, curr in zip(snapshot, snapshot[1:], strict=False):
            prev_year, prev, left_raw, left_scale, left_unit = prev
            year, row, right_raw, right_scale, right_unit = curr
            if year - prev_year != 1:
                continue
            try:
                left = abs(_comparable(left_raw, left_scale, left_unit))
                right = abs(_comparable(right_raw, right_scale, right_unit))
            except InvalidOperation:
                continue
            if left <= Decimal("0.01") or right <= Decimal("0.01"):
                continue
            raw_left = abs(left_raw)
            raw_right = abs(right_raw)
            if raw_left <= Decimal("0.01") or raw_right <= Decimal("0.01"):
                continue
            raw_ratio = max(raw_left, raw_right) / min(raw_left, raw_right)
            scaled_ratio = max(left, right) / min(left, right)
            later_line = _citation_line(row)
            # The two columns of one printed line are not an unexplained jump.
            same_line = bool(later_line) and later_line == _citation_line(prev)
            if (
                raw_ratio <= Decimal("5")
                and scaled_ratio > Decimal("5")
                and left_scale != right_scale
            ):
                # The figures agree and the scale label does not. Drop the blank label.
                if not right_scale and left_scale:
                    _null_value(row, GATE_SCALE_JUMP, counts)
                elif not left_scale and right_scale:
                    _null_value(prev, GATE_SCALE_JUMP, counts)
                elif not same_line:
                    _null_value(row, GATE_SCALE_JUMP, counts)
                continue
            if same_line or scaled_ratio <= Decimal("5"):
                continue
            if _JUMP_EXPLAINED_RE.search(later_line):
                continue
            _null_value(row, GATE_SCALE_JUMP, counts)

    return {"total": sum(counts.values()), "by_check": counts}


def merge_ocr_readings(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    """Fill gaps from a second reading. Keep the longer digit string when one truncates the other.

    Readings that disagree and neither is a truncated form of the other are
    dropped. Nothing is invented.
    """

    def digits(value: object) -> str:
        return re.sub(r"\D", "", str(value or ""))

    def take(block_a: dict[str, Any] | None, block_b: dict[str, Any] | None) -> None:
        if not isinstance(block_a, dict) or not isinstance(block_b, dict):
            return
        for name in _GATED_FIELDS:
            left = block_a.get(name)
            right = block_b.get(name)
            if not isinstance(left, dict) or not isinstance(right, dict):
                continue
            av, bv = left.get("value"), right.get("value")
            if av in (None, "") and bv not in (None, ""):
                block_a[name] = right
            elif av not in (None, "") and bv not in (None, "") and str(av) != str(bv):
                da, db = digits(av), digits(bv)
                if da and db and da != db and (da.endswith(db) or db.endswith(da)):
                    block_a[name] = left if len(da) >= len(db) else right
                else:
                    block_a[name] = _empty_field(
                        "rendered page and fax image disagree; value left absent"
                    )

    take(primary.get("fields"), secondary.get("fields"))
    comp_a = primary.get("comparative") or {}
    comp_b = secondary.get("comparative") or {}
    if comp_a and comp_b and comp_a.get("fiscal_year") == comp_b.get("fiscal_year"):
        take(comp_a.get("fields"), comp_b.get("fields"))
    elif not comp_a and comp_b:
        primary["comparative"] = comp_b
    return primary


def _comparable(value: Decimal, scale: str | None, unit: str | None) -> Decimal:
    number = _to_absolute(value, scale)
    if unit == "pence":
        return number / Decimal("100")
    return number


def leaver_year_coverage(
    filings: list[dict[str, Any]],
    *,
    first_year: int,
    leaving_year: int,
) -> dict[str, Any]:
    """Years present, and whether every expected year has an EPS.

    Expected years run from max(2012, first year in the FTSE 350 window) through
    the leaving year. A missing year stays missing: nothing is carried forward.
    """
    start = max(2012, int(first_year))
    expected = list(range(start, int(leaving_year) + 1))

    def present(field_name: str) -> list[int]:
        return [int(row["year"]) for row in years_with_field(filings, field_name)]

    eps_years = present("basic_eps")
    revenue_years = present("revenue")
    cash_years = present("net_cash_from_operating_activities")
    capex_years = present("capital_expenditure")
    cash_and_capex = sorted(set(cash_years) & set(capex_years))
    return {
        "expected_years": expected,
        "years_with_eps": eps_years,
        "years_with_revenue": revenue_years,
        "years_with_operating_cash_flow": cash_years,
        "years_with_capex": capex_years,
        "years_with_operating_cash_flow_and_capex": cash_and_capex,
        "statements_every_year": bool(expected) and all(year in eps_years for year in expected),
    }


def summarise_leaver_coverage(name_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Stable summary the replay bias counter can read."""
    leavers = [row for row in name_rows if row.get("reason_class")]
    summary: dict[str, Any] = {
        "names": len(leavers),
        "ch_applicable": 0,
        "ch_not_applicable": 0,
        "unresolved": 0,
        "with_any_statement": 0,
        "every_year": 0,
        "by_reason_class": {},
    }
    for reason in ("takeover", "failure", "other"):
        summary["by_reason_class"][reason] = {
            "names": 0,
            "ch_applicable": 0,
            "with_any_statement": 0,
            "every_year": 0,
        }
    for row in leavers:
        reason = str(row.get("reason_class") or "other")
        bucket = summary["by_reason_class"].setdefault(
            reason,
            {"names": 0, "ch_applicable": 0, "with_any_statement": 0, "every_year": 0},
        )
        bucket["names"] += 1
        if row.get("ch_applicable") is False:
            summary["ch_not_applicable"] += 1
            continue
        if row.get("company_number_status") == "unresolved" or row.get("ch_applicable") is not True:
            summary["unresolved"] += 1
            continue
        summary["ch_applicable"] += 1
        bucket["ch_applicable"] += 1
        coverage = row.get("leaver_coverage") or {}
        any_statement = bool(coverage.get("years_with_eps") or coverage.get("years_with_revenue"))
        if any_statement:
            summary["with_any_statement"] += 1
            bucket["with_any_statement"] += 1
        if coverage.get("statements_every_year") is True:
            summary["every_year"] += 1
            bucket["every_year"] += 1
    return summary


def ops_findings_from_ch_failed_name_statements(
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not payload:
        return []
    combined = payload.get("combined") or {}
    count = combined.get(
        "combined_check_a_with_statements", payload.get("combined_check_a_with_statements")
    )
    bar = combined.get("bar", CHECK_A_BAR)
    total = combined.get("total_names", CHECK_A_TOTAL_NAMES)
    generated = str(payload.get("generated_at") or "")[:10]
    summary = (
        f"Combined check A names with statements from 2013: {count} of {total} "
        f"(bar {bar}). Generated {generated or 'unknown'}."
    )
    leaver = payload.get("leaver_coverage") or {}
    if leaver:
        summary += (
            f" Leaver statements every expected year: {leaver.get('every_year')} of "
            f"{leaver.get('ch_applicable')} Companies House-applicable leavers "
            f"({leaver.get('with_any_statement')} with any statement year)."
        )
    summary += f" Observe-only. See {RUNBOOK}."
    return [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": summary,
            "auto_fixable": False,
        }
    ]


def load_store(path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def list_aa_filings(company_number: str, api_key: str) -> list[dict[str, Any]]:
    """All type-AA filings with a period end on or after 2012-01-01."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        url = (
            f"{CH_API_BASE}/company/{urllib.parse.quote(company_number)}/filing-history?"
            + urllib.parse.urlencode(
                {"category": "accounts", "items_per_page": 100, "start_index": start}
            )
        )
        payload = json.loads(_ch_get(url, api_key=api_key).decode("utf-8"))
        time.sleep(RATE_LIMIT_SLEEP_S)
        items = payload.get("items") or []
        total = int(payload.get("total_count") or 0)
        for item in items:
            if str(item.get("type") or "") != "AA":
                continue
            made = str((item.get("description_values") or {}).get("made_up_date") or "")
            if not made or made < EARLIEST_MADE_UP:
                continue
            meta = (item.get("links") or {}).get("document_metadata")
            if not meta:
                continue
            rows.append(
                {
                    "transaction_id": str(item.get("transaction_id") or ""),
                    "filing_date": str(item.get("date") or ""),
                    "made_up_date": made,
                    "description": str(item.get("description") or ""),
                    "pdf_pages": item.get("pages"),
                    "document_metadata_url": str(meta),
                }
            )
        start += len(items)
        if not items or start >= total:
            break
    rows.sort(key=lambda row: row["made_up_date"])
    return rows


@dataclass
class _Char:
    ch: str
    x0: int
    x1: int
    top: int


def _chars_to_lines(chars: list[_Char]) -> list[str]:
    if not chars:
        return []
    heights = [max(8, 12) for _ in chars]
    median_height = sorted(heights)[len(heights) // 2]
    # y clustering uses the top coordinate. Height is estimated from gaps later;
    # tesseract boxes carry height, stored as a minimum via the caller.
    chars = sorted(chars, key=lambda item: (item.top, item.x0))
    tops = [item.top for item in chars]
    # Estimate line height from the most common gap between successive tops.
    gaps = [b - a for a, b in zip(tops, tops[1:], strict=False) if 8 <= (b - a) <= 80]
    if gaps:
        median_height = sorted(gaps)[len(gaps) // 2]
    line_gap = max(8, int(median_height * 0.55))
    word_gap = max(6, int(median_height * 0.32))
    lines: list[list[_Char]] = []
    current: list[_Char] = [chars[0]]
    for item in chars[1:]:
        if item.top - current[0].top > line_gap:
            lines.append(current)
            current = [item]
        else:
            current.append(item)
    lines.append(current)
    rendered: list[str] = []
    for line in lines:
        ordered = sorted(line, key=lambda item: item.x0)
        tokens: list[list[_Char]] = [[ordered[0]]]
        for prev, nxt in zip(ordered, ordered[1:], strict=False):
            if nxt.x0 - prev.x1 >= word_gap:
                tokens.append([nxt])
            else:
                tokens[-1].append(nxt)
        parts = [_token_text(token) for token in tokens]
        text = " ".join(part for part in parts if part)
        if text.strip():
            rendered.append(text)
    return rendered


def _token_text(chars: list[_Char]) -> str:
    if not chars:
        return ""
    gaps = [b.x0 - a.x1 for a, b in zip(chars, chars[1:], strict=False)]
    digit_gaps = [
        (index, gap)
        for index, gap in enumerate(gaps)
        if chars[index].ch.isdigit() and chars[index + 1].ch.isdigit()
    ]
    insert_at: int | None = None
    if len(digit_gaps) >= 2 and not any(item.ch == "." for item in chars):
        last_index, last_gap = digit_gaps[-1]
        others = [gap for _, gap in digit_gaps[:-1]]
        med = sorted(others)[len(others) // 2]
        if last_index == len(chars) - 2 and last_gap >= max(med * 1.6, med + 3):
            insert_at = len(chars) - 1
    out: list[str] = []
    for index, item in enumerate(chars):
        if insert_at is not None and index == insert_at:
            out.append(".")
        out.append(item.ch)
    return "".join(out)


def _page_image(doc: Any, index: int, *, zoom: float = 2.2, prefer_embedded: bool = True) -> Any:
    from PIL import Image

    page = doc[index]
    images = page.get_images()
    text = (page.get_text("text") or "").strip()
    # The raw fax is higher resolution but Tesseract drops digits inside
    # parentheses on it. Statement pages are rendered instead.
    if prefer_embedded and len(images) == 1 and len(text) < 40:
        xref = images[0][0]
        info = doc.extract_image(xref)
        image = Image.open(__import__("io").BytesIO(info["image"]))
        return image.convert("L")
    matrix = __import__("pymupdf").Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    if pix.n == 1:
        return Image.frombytes("L", (pix.width, pix.height), pix.samples)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")


def _insert_decimal_from_boxes(token: str, boxes: list[_Char]) -> str:
    """Put a decimal before the last digit when the glyph gap shows one was printed.

    Tesseract's line text often reads ``124.4`` as ``1244`` and ``7.6`` as ``76``.
    The character boxes still have a wide gap before that last digit. The original
    digits are kept; only the gap is used. A uniform gap (a real integer) is left
    unchanged.
    """
    match = re.fullmatch(r"([\{\(\[]?)(\d{2,5})([\)\}\]]?)(p?)", token, flags=re.I)
    if not match or "," in token or "." in token:
        return token
    digits = match.group(2)
    digit_boxes = [item for item in boxes if item.ch.isdigit()]
    if len(digit_boxes) != len(digits):
        return token
    gaps = [b.x0 - a.x1 for a, b in zip(digit_boxes, digit_boxes[1:], strict=False)]
    if not gaps:
        return token
    last = gaps[-1]
    if len(gaps) == 1:
        width = max(digit_boxes[0].x1 - digit_boxes[0].x0, digit_boxes[1].x1 - digit_boxes[1].x0, 1)
        # A two-digit pence amount. Compare the only gap with the glyph width.
        if last < max(6, int(width * 0.45)):
            return token
    else:
        others = sorted(gaps[:-1])
        median = others[len(others) // 2]
        if last < max(median * 1.6, median + 3):
            return token
    repaired = digits[:-1] + "." + digits[-1]
    return f"{match.group(1)}{repaired}{match.group(3)}{match.group(4)}"


def _ocr_statement_lines(image: Any) -> list[str]:
    """Line text from Tesseract, with a decimal restored on £m amounts.

    Gap repair runs only when the page is denominated in millions. £'000
    statements are integers, and a one-decimal insert would change them.
    """
    import pytesseract

    data = pytesseract.image_to_data(image, config="--psm 6", output_type=pytesseract.Output.DICT)
    grouped: dict[tuple[int, int, int], list[int]] = {}
    for index, word in enumerate(data["text"]):
        if not str(word).strip():
            continue
        key = (
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        grouped.setdefault(key, []).append(index)
    ordered_keys = sorted(
        grouped,
        key=lambda key: (data["top"][grouped[key][0]], data["left"][grouped[key][0]]),
    )
    lines: list[str] = []
    words_by_line: list[list[int]] = []
    for key in ordered_keys:
        indexes = grouped[key]
        line = " ".join(str(data["text"][index]).strip() for index in indexes)
        if line.strip():
            lines.append(line.strip())
            words_by_line.append(indexes)
    blob = "\n".join(lines).lower().replace("’", "'").replace("‘", "'")
    # ``4,0809`` is a one-decimal millions amount whose point was glued on.
    # ``76,641`` is already a valid thousands group and does not match.
    glued_millions = bool(re.search(r"\d,\d{3}\d", blob))
    millions = glued_millions or bool(
        re.search(r"£\s?m\b|£\s?million|(?:us)?\$\s?m\b|€\s?m\b|\bmillion\b", blob)
    )
    thousands = bool(re.search(r"£\s?'?0{3}|\$\s?'?0{3}|€\s?'?0{3}", blob))
    if not millions or thousands:
        return lines
    repaired_lines: list[str] = []
    for _line, indexes in zip(lines, words_by_line, strict=True):
        line_text = " ".join(str(data["text"][index]).strip() for index in indexes)
        pence_line = bool(re.search(r"per share|pence", line_text, re.I))
        parts: list[str] = []
        for index in indexes:
            word = str(data["text"][index]).strip()
            two_digit_pence = pence_line and bool(
                re.fullmatch(r"[\{\(\[]?\d{2}[\)\}\]]?p?", word, flags=re.I)
            )
            if two_digit_pence or re.fullmatch(r"[\{\(\[]?\d{3,5}[\)\}\]]?p?", word, flags=re.I):
                pad = 3
                left = max(0, int(data["left"][index]) - pad)
                top = max(0, int(data["top"][index]) - pad)
                right = int(data["left"][index]) + int(data["width"][index]) + pad
                bottom = int(data["top"][index]) + int(data["height"][index]) + pad
                crop = image.crop((left, top, min(image.width, right), min(image.height, bottom)))
                raw = pytesseract.image_to_boxes(crop, config="--psm 7")
                boxes: list[_Char] = []
                for raw_line in raw.splitlines():
                    piece = raw_line.split()
                    if len(piece) < 5:
                        continue
                    boxes.append(_Char(piece[0], int(piece[1]), int(piece[3]), 0))
                boxes.sort(key=lambda item: item.x0)
                word = _insert_decimal_from_boxes(word, boxes)
            parts.append(word)
        repaired_lines.append(" ".join(parts))
    return repaired_lines


def _ocr_image_lines(image: Any, *, header_only: bool = False) -> list[str]:
    """Tesseract's own line grouping. Full-page character boxes split these fax scans."""
    import pytesseract

    if header_only:
        work = image.crop((0, 0, image.width, max(40, int(image.height * 0.22))))
        text = pytesseract.image_to_string(work, config="--psm 6")
        return [line.strip() for line in text.splitlines() if line.strip()]
    return _ocr_statement_lines(image)


def _cache_dir(cache: Path, transaction_id: str) -> Path:
    path = cache / f"ocr-v{CACHE_VERSION}" / transaction_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _fast_statement_pages(headers: list[str]) -> list[int]:
    """Income, cash flow, and one EPS note. Not every page that mentions them."""
    chosen: list[int] = []
    seen_income = seen_cash = seen_eps = False
    income_at = None
    for index, header in enumerate(headers):
        kinds = _heading_kinds(str(header))
        if "income" in kinds and not seen_income:
            chosen.extend([index, index + 1])
            seen_income = True
            income_at = index
        elif "cash" in kinds and not seen_cash:
            chosen.extend([index, index + 1])
            seen_cash = True
        elif "eps_note" in kinds and seen_income and not seen_eps:
            chosen.append(index)
            seen_eps = True
        if seen_income and seen_cash and seen_eps:
            break
        if seen_income and seen_cash and income_at is not None and index > income_at + 25:
            break
    return chosen


def extract_statement_pages(
    pdf_path: Path,
    *,
    transaction_id: str,
    cache_dir: Path,
    zoom: float = 2.2,
    page_zoom: float | None = None,
) -> list[StatementPage]:
    """Text layer when present, otherwise OCR the statement and note pages."""
    import pymupdf

    doc = pymupdf.open(pdf_path)
    try:
        sample_indexes = [
            i for i in (0, doc.page_count // 2, max(0, doc.page_count - 1)) if i < doc.page_count
        ]
        has_text = any(len((doc[i].get_text("text") or "").strip()) > 80 for i in sample_indexes)
        if has_text:
            pages = []
            for index in range(doc.page_count):
                text = doc[index].get_text("text") or ""
                method = "pymupdf"
                if len(text.strip()) < 40:
                    text, method = _pypdf_page(pdf_path, index)
                pages.append(StatementPage(page=index + 1, text=text or "", method=method))
            interesting = [page for page in pages if _heading_kinds(page.text)]
            return interesting or pages[:1]

        if not _ocr_enabled():
            return [
                StatementPage(
                    page=1,
                    text="",
                    method="ocr_disabled",
                )
            ]
        cache = _cache_dir(cache_dir, transaction_id)
        statement_zoom = zoom if page_zoom is None else page_zoom
        # Leaver statement pages are rendered at their own zoom. The 1.6 cache
        # dropped digits inside parentheses, so it is not reused.
        if statement_zoom == zoom:
            page_cache = cache
        else:
            page_cache = cache_dir / f"ocr-v{CACHE_VERSION}-z{statement_zoom:.1f}" / transaction_id
            page_cache.mkdir(parents=True, exist_ok=True)
        header_label = "ocr-headers" if zoom == 2.2 else f"ocr-headers-z{zoom:.1f}"
        header_path = cache_dir / header_label / transaction_id / "headers.json"
        header_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_headers = cache_dir / "ocr-v1" / transaction_id / "headers.json"
        if not header_path.exists() and legacy_headers.exists():
            header_path.write_text(legacy_headers.read_text(encoding="utf-8"), encoding="utf-8")
        headers = _load_json(header_path)
        if not (isinstance(headers, list) and len(headers) == doc.page_count):
            alt_headers = _load_json(cache_dir / "ocr-headers" / transaction_id / "headers.json")
            if isinstance(alt_headers, list) and len(alt_headers) == doc.page_count:
                headers = alt_headers
        fast = zoom != 2.2
        if fast and isinstance(headers, list) and len(headers) == doc.page_count:
            chosen = _fast_statement_pages(headers)
        elif fast:
            chosen = []
            seen_income = seen_cash = seen_eps = False
            income_at = None
            scanned: list[str] = []
            limit = min(doc.page_count, 100)
            for index in range(limit):
                image = _page_image(doc, index, zoom=zoom)
                header = "\n".join(_ocr_image_lines(image, header_only=True))
                scanned.append(header)
                kinds = _heading_kinds(header)
                if "income" in kinds and not seen_income:
                    chosen.extend([index, index + 1])
                    seen_income = True
                    income_at = index
                elif "cash" in kinds and not seen_cash:
                    chosen.extend([index, index + 1])
                    seen_cash = True
                elif "eps_note" in kinds and seen_income and not seen_eps:
                    chosen.append(index)
                    seen_eps = True
                if seen_income and seen_cash and seen_eps:
                    break
                if seen_income and seen_cash and income_at is not None and index > income_at + 25:
                    break
            if not seen_income and doc.page_count > limit:
                for index in range(max(limit, doc.page_count - 40), doc.page_count):
                    image = _page_image(doc, index, zoom=zoom)
                    header = "\n".join(_ocr_image_lines(image, header_only=True))
                    kinds = _heading_kinds(header)
                    if "income" in kinds and not seen_income:
                        chosen.extend([index, index + 1])
                        seen_income = True
                    elif "cash" in kinds and not seen_cash:
                        chosen.extend([index, index + 1])
                        seen_cash = True
                    elif "eps_note" in kinds and seen_income and not seen_eps:
                        chosen.append(index)
                        seen_eps = True
                    if seen_income and seen_cash and seen_eps:
                        break
            logger.info(
                "headers %s fast %s/%s",
                transaction_id,
                len(scanned),
                doc.page_count,
            )
        else:
            if not isinstance(headers, list) or len(headers) != doc.page_count:
                headers = []
                for index in range(doc.page_count):
                    image = _page_image(doc, index, zoom=zoom)
                    lines = _ocr_image_lines(image, header_only=True)
                    headers.append("\n".join(lines))
                    if (index + 1) % 25 == 0:
                        logger.info("headers %s %s/%s", transaction_id, index + 1, doc.page_count)
                header_path.write_text(json.dumps(headers), encoding="utf-8")
            chosen = []
            for index, header in enumerate(headers):
                if _heading_kinds(str(header)):
                    chosen.append(index)
                    if index + 1 < doc.page_count:
                        chosen.append(index + 1)
        # Keep order, drop duplicates.
        seen: set[int] = set()
        ordered = []
        for index in chosen:
            if index not in seen and index < doc.page_count:
                seen.add(index)
                ordered.append(index)
        pages: list[StatementPage] = []
        for index in ordered:
            page_path = page_cache / f"p{index + 1}.json"
            cached = _load_json(page_path)
            alt_lines: list[str] = []
            if isinstance(cached, dict) and isinstance(cached.get("lines"), list):
                text = "\n".join(str(line) for line in cached["lines"])
                method = str(cached.get("method") or "ocr")
                if isinstance(cached.get("alt_lines"), list):
                    alt_lines = [str(line) for line in cached["alt_lines"]]
            else:
                image = _page_image(doc, index, zoom=statement_zoom, prefer_embedded=False)
                lines = _ocr_image_lines(image, header_only=False)
                text = "\n".join(lines)
                method = "ocr"
                cached = {"method": method, "lines": lines}
                page_path.write_text(json.dumps(cached), encoding="utf-8")
                logger.info("ocr %s page %s (%s lines)", transaction_id, index + 1, len(lines))
            if statement_zoom != zoom and not alt_lines and isinstance(cached, dict):
                rendered = _page_image(doc, index, zoom=statement_zoom, prefer_embedded=False)
                fax = _page_image(doc, index, zoom=statement_zoom, prefer_embedded=True)
                if fax.size != rendered.size:
                    alt_lines = _ocr_image_lines(fax, header_only=False)
                    cached["alt_lines"] = alt_lines
                    page_path.write_text(json.dumps(cached), encoding="utf-8")
                    logger.info(
                        "ocr fax %s page %s (%s lines)", transaction_id, index + 1, len(alt_lines)
                    )
            pages.append(
                StatementPage(
                    page=index + 1,
                    text=text,
                    method=method,
                    alt_text="\n".join(alt_lines),
                )
            )
        return pages
    finally:
        doc.close()


def _pypdf_page(pdf_path: Path, index: int) -> tuple[str, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "pymupdf"
    try:
        reader = PdfReader(str(pdf_path))
        if index >= len(reader.pages):
            return "", "pypdf"
        return reader.pages[index].extract_text() or "", "pypdf"
    except Exception as exc:  # noqa: BLE001
        logger.info("pypdf page extract failed: %s", exc)
        return "", "pymupdf"


def _pdf_path(cache_dir: Path, key: str, made_up: str) -> Path:
    return cache_dir / f"{key}_{made_up}.pdf"


def ensure_pdf(
    cache_dir: Path,
    *,
    key: str,
    made_up: str,
    document_metadata_url: str,
    api_key: str,
) -> Path | None:
    path = _pdf_path(cache_dir, key, made_up)
    if path.exists() and path.stat().st_size > 1000:
        return path
    fetched = fetch_document_bytes(document_metadata_url, api_key=api_key, prefer="application/pdf")
    if not fetched:
        return None
    raw, content_type = fetched
    if "pdf" not in content_type and not raw.startswith(b"%PDF"):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _method_mix(filings: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for filing in filings:
        for page in filing.get("pages") or []:
            counts[str(page.get("method") or "unknown")] += 1
    return dict(counts)


def _summarise_name(spec: dict[str, str], filings: list[dict[str, Any]]) -> dict[str, Any]:
    eps_years = [row for row in years_with_eps(filings) if int(row["year"]) >= 2013]
    coverage = field_coverage(filings)
    return {
        "key": spec["key"],
        "name": spec["name"],
        "company_number": spec["company_number"],
        "company_number_verified": spec["verified"],
        "filing_count": len(filings),
        "years_with_eps_from_2013": [row["year"] for row in eps_years],
        "eps_years": eps_years,
        "statements_from_2013": statements_from_2013(eps_years),
        "fields_found": coverage["found"],
        "fields_absent": coverage["absent"],
        "extraction_methods": _method_mix(filings),
        "filings": filings,
    }


def load_eodhd_report(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_store(
    name_rows: list[dict[str, Any]],
    *,
    eodhd_payload: dict[str, Any] | None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    combined = combined_check_a(name_rows, eodhd_payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(UTC).replace(microsecond=0).isoformat(),
        "learning_question": LEARNING_QUESTION,
        "observe_only": True,
        "influences_live": False,
        "licence": LICENCE_NOTE,
        "point_in_time": (
            "Companies House accounts filing date. That is later than the results "
            "announcement, so it is a conservative point-in-time date."
        ),
        "check_a_bar": CHECK_A_BAR,
        "combined_check_a_with_statements": combined["combined_check_a_with_statements"],
        "combined_check_a_pass": combined["pass"],
        "combined": combined,
        "names": name_rows,
    }


def write_store(payload: dict[str, Any], path: Path = DEFAULT_STORE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_extraction(
    *,
    api_key: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    only: set[str] | None = None,
    made_up: set[str] | None = None,
    eodhd_path: Path | None = None,
) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    name_rows: list[dict[str, Any]] = []
    for spec in FAILED_UK_NAMES:
        if only and spec["key"] not in only:
            continue
        logger.info("listing %s %s", spec["key"], spec["company_number"])
        metas = list_aa_filings(spec["company_number"], api_key)
        filings: list[dict[str, Any]] = []
        for meta in metas:
            if made_up and meta["made_up_date"] not in made_up:
                continue
            logger.info(
                "filing %s %s filed %s", spec["key"], meta["made_up_date"], meta["filing_date"]
            )
            try:
                pdf = ensure_pdf(
                    cache_dir,
                    key=spec["key"],
                    made_up=meta["made_up_date"],
                    document_metadata_url=meta["document_metadata_url"],
                    api_key=api_key,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("download failed %s %s: %s", spec["key"], meta["made_up_date"], exc)
                pdf = None
            if pdf is None:
                filings.append(
                    {
                        **{
                            k: meta[k]
                            for k in (
                                "transaction_id",
                                "filing_date",
                                "made_up_date",
                                "description",
                            )
                        },
                        "fiscal_year": int(meta["made_up_date"][:4]),
                        "fiscal_year_end": meta["made_up_date"],
                        "source": "primary",
                        "error": "PDF download failed or the filing has no PDF",
                        "fields": {
                            name: _empty_field("PDF download failed or the filing has no PDF")
                            for name in FIELD_NAMES
                        },
                        "comparative": None,
                        "pages": [],
                        "methods": [],
                        "warnings": ["pdf unavailable"],
                    }
                )
                continue
            pages = extract_statement_pages(
                pdf, transaction_id=meta["transaction_id"], cache_dir=cache_dir
            )
            parsed = parse_statement_pages(
                pages,
                fiscal_year_end=meta["made_up_date"],
                filing_date=meta["filing_date"],
                transaction_id=meta["transaction_id"],
            )
            parsed["description"] = meta["description"]
            parsed["pdf_pages"] = meta.get("pdf_pages")
            filings.append(parsed)
        name_rows.append(_summarise_name(spec, filings))
    eodhd_payload = load_eodhd_report(eodhd_path or Path("docs/data/eodhd_coverage_check.json"))
    return build_store(name_rows, eodhd_payload=eodhd_payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract Companies House annual statements for failed UK names (observe-only)."
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument(
        "--only", action="append", default=None, help="Name key to extract (repeatable)."
    )
    parser.add_argument(
        "--made-up",
        action="append",
        default=None,
        help="Limit to these period-end dates (YYYY-MM-DD, repeatable).",
    )
    parser.add_argument(
        "--eodhd",
        type=Path,
        default=Path("docs/data/eodhd_coverage_check.json"),
        help="EODHD coverage report used only for its booleans and years.",
    )
    parser.add_argument(
        "--leavers",
        action="store_true",
        help="Extract FTSE 350 delisting leavers as well as the seven verified names.",
    )
    parser.add_argument(
        "--leaver-list",
        type=Path,
        default=Path("docs/data/ftse350_leavers_2013_2025.json"),
    )
    parser.add_argument(
        "--allow-ocr",
        action="store_true",
        help="OCR image-only leaver filings. One Tesseract process. Headers at zoom 1.6, statement pages at 2.2.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Stop after this many pending leavers."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-extract --only keys even when they are already complete.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    api_key = companies_house_api_key()
    if not api_key:
        print("COMPANIES_HOUSE_API_KEY is not set", file=sys.stderr)
        return 2
    if args.leavers:
        from value_investor.ch_leaver_statements import run_leaver_extraction

        payload = run_leaver_extraction(
            leaver_path=args.leaver_list,
            out_path=args.out,
            api_key=api_key,
            cache_dir=args.cache_dir,
            allow_ocr=args.allow_ocr,
            only=set(args.only) if args.only else None,
            limit=args.limit,
            eodhd_path=args.eodhd,
            refresh=set(args.only) if args.refresh and args.only else None,
        )
        coverage = payload.get("leaver_coverage") or {}
        logger.info(
            "wrote %s leavers every_year=%s applicable=%s pending=%s",
            args.out,
            coverage.get("every_year"),
            coverage.get("ch_applicable"),
            (payload.get("leaver_cursor") or {}).get("pending_count"),
        )
        return 0
    payload = run_extraction(
        api_key=api_key,
        cache_dir=args.cache_dir,
        only=set(args.only) if args.only else None,
        made_up=set(args.made_up) if args.made_up else None,
        eodhd_path=args.eodhd,
    )
    write_store(payload, args.out)
    combined = payload["combined_check_a_with_statements"]
    logger.info(
        "wrote %s combined_check_a_with_statements=%s bar=%s",
        args.out,
        combined,
        CHECK_A_BAR,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
