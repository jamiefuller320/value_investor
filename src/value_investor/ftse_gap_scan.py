"""Scan stored FTSE 350 files for handover gaps that already have a rule.

The scanner reads ``docs/data/latest.json``, the 11 Oct 2026 history run,
``docs/data/research/*/sources/financials_annual.json``, and
``docs/data/ftse350_ordinary_shares.json``. It does not fetch, and it does not
invent a figure the file does not contain.

A new handover question becomes one check. Add a function that takes a
``ScreenRow`` and returns a detail string, or None. Register it in ``CHECKS``
with a stable rule id and a one-line summary. Add a test that flags a ticker
the handover already names, when the stored files still contain that example.
Re-run ``ftse-gap-scan``. A name that matches leaves the "needs an agent" list.
"""

from __future__ import annotations

import gzip
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from value_investor.ftse_pound_cap import SCREEN_PRICE_RUN_PREFIX, SOURCED_SHARES
from value_investor.storage import resolve_json_path

# Same ordinary-share fields the pound-cap reader uses.
_SHARE_FIELDS = (
    "Ordinary Shares Number",
    "Share Issued",
    "Basic Average Shares",
)

_ROSTER_SECTION = "## FTSE 350 order"
_ROSTER_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|")

HOW_TO_ADD_A_CHECK = """
How a new handover question becomes one check
----------------------------------------------
1. Read the stored fields the question names. Do not invent a figure.
2. Add one function in value_investor.ftse_gap_scan that takes a ScreenRow
   and returns a short detail string, or None when the row does not match.
3. Register that function in CHECKS with a stable rule id and a one-line summary.
4. Add a test that flags a ticker the handover already names, when the stored
   files still contain that example.
5. Run ftse-gap-scan. A name that matches leaves the "needs an agent" list.
""".strip()


@dataclass(frozen=True)
class ScreenRow:
    """One stored FTSE screen row plus the files the checks read."""

    ticker: str
    name: str
    trust: bool
    dividend_yield_raw: float | None
    yield_display: str | None
    pe_display: str | None
    key_metric_names: frozenset[str]
    displayed_fcf: float | None
    operating_cashflow: float | None
    filing_aligned: float | None
    fcf_is_object: bool
    fcf_has_figure: bool
    has_annual_statement: bool
    history_price: float | None
    ordinary_shares: float | None


@dataclass(frozen=True)
class GapHit:
    rule_id: str
    ticker: str
    detail: str


@dataclass(frozen=True)
class Check:
    rule_id: str
    summary: str
    fn: Callable[[ScreenRow], str | None]


@dataclass(frozen=True)
class RosterName:
    rank: int
    ticker: str
    name: str


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def _optional_float(value: Any) -> float | None:
    """Parse a stored number. Booleans, blanks, and non-numeric text stay missing."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if text.endswith("%"):
            text = text[:-1].strip()
        if not text or text.lower() in {"none", "nan", "inf", "-inf", "+inf"}:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
    if number != number:  # NaN
        return None
    return number


def _num(value: float) -> str:
    if value == int(value) and abs(value) < 1e16:
        return str(int(value))
    return str(value)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _statement_path(root: Path, ticker: str) -> Path | None:
    return resolve_json_path(
        root / "docs/data/research" / ticker / "sources" / "financials_annual.json"
    )


def _statement_shares(path: Path) -> float | None:
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    balance = payload.get("balance_sheet") or {}
    if not isinstance(balance, dict):
        return None
    for year in sorted(balance, reverse=True):
        row = balance[year]
        if not isinstance(row, dict):
            continue
        for field in _SHARE_FIELDS:
            number = _optional_float(row.get(field))
            if number is not None and number > 0:
                return number
    return None


def _history_prices(root: Path) -> dict[str, float]:
    history = root / "docs/data/history"
    paths = sorted(history.glob(f"run_{SCREEN_PRICE_RUN_PREFIX}_*.json.gz"))
    if not paths:
        paths = sorted(history.glob(f"run_{SCREEN_PRICE_RUN_PREFIX}_*.json"))
    if not paths:
        return {}
    path = paths[-1]
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = _load_json(path)
    prices = payload.get("prices") or {}
    out: dict[str, float] = {}
    for ticker, raw in prices.items():
        number = _optional_float(raw)
        if number is not None:
            out[str(ticker)] = number
    return out


def _sourced_shares(root: Path) -> dict[str, float]:
    path = root / SOURCED_SHARES
    if not path.exists():
        return {}
    payload = _load_json(path)
    tickers = payload.get("tickers") or {}
    out: dict[str, float] = {}
    for ticker, row in tickers.items():
        if not isinstance(row, dict):
            continue
        number = _optional_float(row.get("ordinary_shares"))
        if number is not None and number > 0:
            out[str(ticker)] = number
    return out


def _fcf_figure(fcf: dict[str, Any], key_metrics: dict[str, Any]) -> tuple[float | None, bool]:
    """Return the displayed free-cash-flow figure and whether any figure is stored."""

    fields = (
        _optional_float(fcf.get("canonical")),
        _optional_float(fcf.get("primary_fcf")),
        _optional_float(fcf.get("policy_fcf")),
        _optional_float(fcf.get("screen_ttm")),
        _optional_float(fcf.get("filing_aligned")),
        _optional_float(key_metrics.get("FCF")),
    )
    displayed = next((number for number in fields if number is not None), None)
    return displayed, displayed is not None


def load_screen_rows(root: Path | None = None) -> list[ScreenRow]:
    """Load one row per stored FTSE 350 screen ticker."""

    root = Path(root or repo_root_from_here())
    latest = _load_json(root / "docs/data/latest.json")
    prices = _history_prices(root)
    sourced = _sourced_shares(root)
    rows: list[ScreenRow] = []
    for bucket, is_trust in (("reports", False), ("trust_reports", True)):
        for raw in latest.get(bucket) or []:
            if not isinstance(raw, dict):
                continue
            ticker = str(raw.get("ticker") or "").strip()
            if not ticker:
                continue
            key_metrics = raw.get("key_metrics") or {}
            if not isinstance(key_metrics, dict):
                key_metrics = {}
            screening = raw.get("screening_inputs") or {}
            if not isinstance(screening, dict):
                screening = {}
            fcf = raw.get("fcf")
            fcf_obj = fcf if isinstance(fcf, dict) else {}
            displayed, has_figure = _fcf_figure(fcf_obj, key_metrics)
            statement = _statement_path(root, ticker)
            own_shares = _statement_shares(statement) if statement is not None else None
            shares = own_shares if own_shares is not None else sourced.get(ticker)
            rows.append(
                ScreenRow(
                    ticker=ticker,
                    name=str(raw.get("name") or ""),
                    trust=is_trust,
                    dividend_yield_raw=_optional_float(screening.get("dividend_yield_raw")),
                    yield_display=(
                        str(key_metrics["Yield"]) if key_metrics.get("Yield") is not None else None
                    ),
                    pe_display=(
                        str(key_metrics["P/E"]) if key_metrics.get("P/E") is not None else None
                    ),
                    key_metric_names=frozenset(str(key) for key in key_metrics),
                    displayed_fcf=displayed,
                    operating_cashflow=_optional_float(raw.get("operating_cashflow")),
                    filing_aligned=_optional_float(fcf_obj.get("filing_aligned")),
                    fcf_is_object=isinstance(fcf, dict),
                    fcf_has_figure=has_figure,
                    has_annual_statement=statement is not None,
                    history_price=prices.get(ticker),
                    ordinary_shares=shares,
                )
            )
    return rows


def check_raw_yield_below_one_displayed_as_percent(row: ScreenRow) -> str | None:
    """Raw yield strictly between 0 and 1, displayed as that number times 100."""

    raw = row.dividend_yield_raw
    shown = _optional_float(row.yield_display)
    if raw is None or shown is None or not (0 < raw < 1):
        return None
    if round(shown, 1) != round(raw * 100, 1):
        return None
    return f"dividend_yield_raw {raw} displayed {row.yield_display}"


def check_filing_aligned_fcf_without_filing(row: ScreenRow) -> str | None:
    if row.filing_aligned is None or row.has_annual_statement:
        return None
    return f"filing_aligned {_num(row.filing_aligned)} and no annual statement"


def check_fcf_greater_than_operating_cashflow(row: ScreenRow) -> str | None:
    fcf = row.displayed_fcf
    ocf = row.operating_cashflow
    if fcf is None or ocf is None or not fcf > ocf:
        return None
    return f"free cash flow {_num(fcf)} greater than operating cash flow {_num(ocf)}"


def check_fcf_more_negative_than_operating_cashflow(row: ScreenRow) -> str | None:
    fcf = row.displayed_fcf
    ocf = row.operating_cashflow
    if fcf is None or ocf is None or not (fcf < 0 and fcf < ocf):
        return None
    return f"free cash flow {_num(fcf)} is more negative than operating cash flow {_num(ocf)}"


def check_empty_fcf_object_with_operating_cashflow(row: ScreenRow) -> str | None:
    if not row.fcf_is_object or row.fcf_has_figure or row.operating_cashflow is None:
        return None
    return (
        "operating cash flow "
        f"{_num(row.operating_cashflow)} stored and the free-cash-flow object has no figure"
    )


def check_fcf_stored_operating_cashflow_missing(row: ScreenRow) -> str | None:
    if row.displayed_fcf is None or row.operating_cashflow is not None:
        return None
    return f"free cash flow {_num(row.displayed_fcf)} stored and operating cash flow missing"


def check_screen_pe_equals_pence_price(row: ScreenRow) -> str | None:
    pe = _optional_float(row.pe_display)
    price = row.history_price
    if pe is None or price is None:
        return None
    if round(pe, 1) != round(price, 1):
        return None
    return (
        f"screen P/E {row.pe_display} equals the {SCREEN_PRICE_RUN_PREFIX} "
        f"history price {price} at one decimal"
    )


def check_trust_row_missing_yield_key(row: ScreenRow) -> str | None:
    if not row.trust or "Yield" in row.key_metric_names:
        return None
    return "trust key metrics omit Yield"


def check_trust_row_pe_only(row: ScreenRow) -> str | None:
    if not row.trust or row.key_metric_names != frozenset({"P/E"}):
        return None
    return "trust key metrics are a P/E only"


def check_missing_annual_statement(row: ScreenRow) -> str | None:
    if row.has_annual_statement:
        return None
    return f"no docs/data/research/{row.ticker}/sources/financials_annual.json"


def check_price_without_ordinary_share_count(row: ScreenRow) -> str | None:
    if row.history_price is None or row.ordinary_shares is not None:
        return None
    return (
        f"history price {row.history_price} on {SCREEN_PRICE_RUN_PREFIX} "
        "and no ordinary share count"
    )


CHECKS: tuple[Check, ...] = (
    Check(
        "raw_yield_below_one_displayed_as_percent",
        "raw dividend yield below 1 displayed as a percent",
        check_raw_yield_below_one_displayed_as_percent,
    ),
    Check(
        "filing_aligned_fcf_without_filing",
        "filing_aligned free cash flow with no filing",
        check_filing_aligned_fcf_without_filing,
    ),
    Check(
        "fcf_greater_than_operating_cashflow",
        "free cash flow greater than operating cash flow",
        check_fcf_greater_than_operating_cashflow,
    ),
    Check(
        "fcf_more_negative_than_operating_cashflow",
        "free cash flow more negative than operating cash flow",
        check_fcf_more_negative_than_operating_cashflow,
    ),
    Check(
        "empty_fcf_object_with_operating_cashflow",
        "an empty free-cash-flow object while operating cash flow is stored",
        check_empty_fcf_object_with_operating_cashflow,
    ),
    Check(
        "fcf_stored_operating_cashflow_missing",
        "free cash flow stored while operating cash flow is missing",
        check_fcf_stored_operating_cashflow_missing,
    ),
    Check(
        "screen_pe_equals_pence_price",
        "a screen P/E equal to the London price in pence",
        check_screen_pe_equals_pence_price,
    ),
    Check(
        "trust_row_missing_yield_key",
        "a trust row missing its yield key",
        check_trust_row_missing_yield_key,
    ),
    Check(
        "trust_row_pe_only",
        "a trust row that is only a P/E",
        check_trust_row_pe_only,
    ),
    Check(
        "missing_annual_statement",
        "a missing annual statement",
        check_missing_annual_statement,
    ),
    Check(
        "price_without_ordinary_share_count",
        "a stored price with no ordinary-share count",
        check_price_without_ordinary_share_count,
    ),
)


def hits_for(row: ScreenRow) -> list[GapHit]:
    found: list[GapHit] = []
    for check in CHECKS:
        detail = check.fn(row)
        if detail:
            found.append(GapHit(rule_id=check.rule_id, ticker=row.ticker, detail=detail))
    return found


def scan_ftse_gaps(root: Path | None = None) -> list[GapHit]:
    """Return every rule hit on the stored FTSE 350 screen."""

    hits: list[GapHit] = []
    for row in load_screen_rows(root):
        hits.extend(hits_for(row))
    return hits


def load_roster(path: Path) -> list[RosterName]:
    """Read the FTSE 350 order table. Other roster sections are ignored."""

    text = path.read_text(encoding="utf-8")
    start = text.find(_ROSTER_SECTION)
    if start < 0:
        raise ValueError(f"{path} has no {_ROSTER_SECTION!r} section")
    section = text[start:]
    nxt = section.find("\n## ", 1)
    if nxt > 0:
        section = section[:nxt]
    rows: list[RosterName] = []
    for line in section.splitlines():
        match = _ROSTER_ROW.match(line)
        if match is None:
            continue
        ticker = match.group(2).strip()
        if ticker in {"Ticker", "#"} or "." not in ticker:
            continue
        rows.append(
            RosterName(rank=int(match.group(1)), ticker=ticker, name=match.group(3).strip())
        )
    if not rows:
        raise ValueError(f"{path} FTSE 350 order table has no ticker rows")
    return rows


def render_roster_split(
    *,
    hits: list[GapHit],
    roster: list[RosterName],
    from_rank: int,
    screen_tickers: set[str],
) -> str:
    """Split roster names into those a known rule covers and those that still need an agent."""

    selected = [row for row in roster if row.rank >= from_rank]
    by_ticker: dict[str, list[GapHit]] = {}
    for hit in hits:
        by_ticker.setdefault(hit.ticker, []).append(hit)

    covered: list[tuple[RosterName, list[GapHit]]] = []
    needs_agent: list[tuple[RosterName, str]] = []
    for row in selected:
        matched = by_ticker.get(row.ticker) or []
        if row.ticker not in screen_tickers:
            needs_agent.append((row, "not on the stored FTSE screen"))
        elif matched:
            covered.append((row, matched))
        else:
            needs_agent.append((row, ""))

    rule_counts: dict[str, int] = {check.rule_id: 0 for check in CHECKS}
    for _, matched in covered:
        for hit in matched:
            rule_counts[hit.rule_id] = rule_counts.get(hit.rule_id, 0) + 1

    lines = [
        "# FTSE gap scan",
        "",
        "Stored-file scan of the live FTSE 350 screen. Each hit is a rule already",
        "named in the data-gap handover. No figure here was calculated from a",
        "filing the file does not contain.",
        "",
        f"Roster ranks {from_rank} onward"
        + (f", starting at {selected[0].ticker}." if selected else "."),
        "A name is covered when at least one check matches. A name still needs an",
        "agent when none of these checks match.",
        "",
        "## Counts",
        "",
        f"- Covered by a known rule: {len(covered)}",
        f"- Still need an agent: {len(needs_agent)}",
        f"- Roster rows in this range: {len(selected)}",
        "",
        "## Rule hits in this range",
        "",
        "| Rule | Names |",
        "|---|---:|",
    ]
    for check in CHECKS:
        lines.append(f"| `{check.rule_id}` | {rule_counts.get(check.rule_id, 0)} |")
    lines.extend(
        [
            "",
            "## Covered by a known rule",
            "",
            "| Rank | Ticker | Rules |",
            "|---:|---|---|",
        ]
    )
    for row, matched in covered:
        rule_ids = ", ".join(hit.rule_id for hit in matched)
        lines.append(f"| {row.rank} | {row.ticker} | {rule_ids} |")
    lines.extend(["", "## Still need an agent", ""])
    if not needs_agent:
        lines.append("None. Every name in this range matches at least one check.")
        lines.append("")
        return "\n".join(lines)
    lines.extend(
        [
            "| Rank | Ticker | Name | Note |",
            "|---:|---|---|---|",
        ]
    )
    for row, note in needs_agent:
        lines.append(f"| {row.rank} | {row.ticker} | {row.name} | {note} |")
    lines.append("")
    return "\n".join(lines)
