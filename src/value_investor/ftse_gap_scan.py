"""Scan stored FTSE 350 files for handover gaps that already have a rule.

The scanner reads ``docs/data/latest.json``, the 11 Oct 2026 history run, and
``docs/data/research/*/sources/financials_annual.json``. An ordinary share
count is a positive number on that statement. A blank or null share field is
not a count. It does not fetch, and it does not invent a figure.

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

from value_investor.ftse_pound_cap import SCREEN_PRICE_RUN_PREFIX
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
    company_adjusted: float | None = None
    screen_ttm: float | None = None
    cash_dividend: float | None = None
    repurchase: float | None = None
    diluted_eps: float | None = None
    net_income: float | None = None
    stockholders_equity: float | None = None
    screen_roe: float | None = None
    unusual_items: tuple[tuple[str, float], ...] = ()
    price_quote_currency: str | None = None
    statement_currency: str | None = None
    statement_fcf: float | None = None
    fcf_divergence_flagged: bool | None = None
    statement_revenue: float | None = None
    discount_display: str | None = None
    premium_display: str | None = None
    net_normalized_gaps: tuple[tuple[str, float, float], ...] = ()
    income_sign_gaps: tuple[tuple[str, float, float], ...] = ()
    chart_currency: str | None = None
    revenue_year_without_eps: tuple[str, float, float] | None = None
    eps_scale_pairs: tuple[tuple[str, float, float, str, float, float], ...] = ()
    has_price_quote_file: bool = True


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


def _positive_share(value: Any) -> float | None:
    """A stored ordinary-share count. Blank, null, and zero are not a count."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, str) and value.strip().lower() in {"null", "none", "nan"}:
        return None
    number = _optional_float(value)
    if number is None or number <= 0:
        return None
    return number


def share_count_from_balance(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Positive ordinary-share count already on a statement. Blank and null are skipped."""

    balance = payload.get("balance_sheet") or {}
    if not isinstance(balance, dict):
        return None
    for year in sorted(balance, reverse=True):
        row = balance[year]
        if not isinstance(row, dict):
            continue
        for field in _SHARE_FIELDS:
            number = _positive_share(row.get(field))
            if number is not None:
                return {"field": field, "year": str(year), "ordinary_shares": number}
    return None


def _statement_shares(path: Path) -> float | None:
    facts = _statement_facts(path)
    shares = facts.get("ordinary_shares")
    return None if shares is None else float(shares)


def _latest_statement_row(block: Any) -> dict[str, Any] | None:
    if not isinstance(block, dict) or not block:
        return None
    row = block[sorted(block, reverse=True)[0]]
    return row if isinstance(row, dict) else None


def _statement_facts(path: Path | None) -> dict[str, Any]:
    """Figures already stored on one annual statement. Missing lines stay missing."""

    facts: dict[str, Any] = {
        "ordinary_shares": None,
        "cash_dividend": None,
        "repurchase": None,
        "diluted_eps": None,
        "net_income": None,
        "stockholders_equity": None,
        "unusual_items": (),
        "statement_currency": None,
        "statement_fcf": None,
        "statement_revenue": None,
        "net_normalized_gaps": (),
        "income_sign_gaps": (),
        "revenue_year_without_eps": None,
        "eps_scale_pairs": (),
    }
    if path is None:
        return facts
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return facts
    if not isinstance(payload, dict):
        return facts
    stamp = share_count_from_balance(payload)
    if stamp is not None:
        facts["ordinary_shares"] = stamp["ordinary_shares"]
    for key in ("reporting_currency", "financialCurrency", "currency"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            facts["statement_currency"] = value.strip()
            break
    cash_flow = _latest_statement_row(payload.get("cash_flow"))
    if cash_flow is not None:
        for field in ("Common Stock Dividend Paid", "Cash Dividends Paid"):
            if field in cash_flow:
                facts["cash_dividend"] = _optional_float(cash_flow.get(field))
                break
        if "Repurchase Of Capital Stock" in cash_flow:
            facts["repurchase"] = _optional_float(cash_flow.get("Repurchase Of Capital Stock"))
        if "Free Cash Flow" in cash_flow:
            facts["statement_fcf"] = _optional_float(cash_flow.get("Free Cash Flow"))
    income = payload.get("income_statement") or {}
    balance = payload.get("balance_sheet") or {}
    latest_income = _latest_statement_row(income)
    if latest_income is not None:
        if "Diluted EPS" in latest_income:
            facts["diluted_eps"] = _optional_float(latest_income.get("Diluted EPS"))
        unusual: list[tuple[str, float]] = []
        for field in (
            "Total Unusual Items",
            "Total Unusual Items Excluding Goodwill",
            "Special Income Charges",
        ):
            if field not in latest_income:
                continue
            number = _optional_float(latest_income.get(field))
            if number is not None:
                unusual.append((field, number))
        facts["unusual_items"] = tuple(unusual)
    if isinstance(income, dict):
        for year in sorted(income, reverse=True):
            inc_row = income[year]
            if not isinstance(inc_row, dict):
                continue
            revenue = None
            for field in ("Total Revenue", "Operating Revenue"):
                if field not in inc_row:
                    continue
                revenue = _optional_float(inc_row.get(field))
                if revenue is not None:
                    break
            if revenue is not None:
                facts["statement_revenue"] = revenue
                break
    if isinstance(income, dict) and isinstance(balance, dict):
        for year in sorted(set(income) & set(balance), reverse=True):
            inc_row = income[year]
            bal_row = balance[year]
            if not isinstance(inc_row, dict) or not isinstance(bal_row, dict):
                continue
            net_income = _optional_float(inc_row.get("Net Income"))
            equity = _optional_float(bal_row.get("Stockholders Equity"))
            if equity is None:
                equity = _optional_float(bal_row.get("Common Stock Equity"))
            if net_income is None or equity is None or equity == 0:
                continue
            facts["net_income"] = net_income
            facts["stockholders_equity"] = equity
            break
    facts["net_normalized_gaps"] = _net_normalized_gaps(income)
    facts["income_sign_gaps"] = _income_sign_gaps(income)
    facts["revenue_year_without_eps"] = _revenue_year_without_eps(income)
    facts["eps_scale_pairs"] = _eps_scale_pairs(income)
    return facts


def _stored_revenue(row: dict[str, Any]) -> float | None:
    for field in ("Total Revenue", "Operating Revenue"):
        if field not in row:
            continue
        number = _optional_float(row.get(field))
        if number is not None:
            return number
    return None


def _revenue_year_without_eps(income: Any) -> tuple[str, float, float] | None:
    """Latest year with revenue and net income, when that year has no diluted-EPS line.

    An earlier diluted-EPS line is not copied forward. No earnings figure is calculated.
    """

    if not isinstance(income, dict):
        return None
    for year in sorted(income, reverse=True):
        row = income[year]
        if not isinstance(row, dict):
            continue
        revenue = _stored_revenue(row)
        if "Net Income" not in row:
            continue
        net = _optional_float(row.get("Net Income"))
        if revenue is None or net is None:
            continue
        if "Diluted EPS" in row:
            return None
        return (str(year), revenue, net)
    return None


def _eps_scale_pairs(
    income: Any,
) -> tuple[tuple[str, float, float, str, float, float], ...]:
    """Year pairs where diluted EPS differs by more than ten times and net income does not.

    Both figures are compared as stored. Neither is rescaled. A zero is not a ratio.
    """

    if not isinstance(income, dict):
        return ()
    points: list[tuple[str, float, float]] = []
    for year in sorted(income):
        row = income[year]
        if not isinstance(row, dict):
            continue
        if "Diluted EPS" not in row or "Net Income" not in row:
            continue
        eps = _optional_float(row.get("Diluted EPS"))
        net = _optional_float(row.get("Net Income"))
        if eps is None or net is None or eps == 0 or net == 0:
            continue
        points.append((str(year), eps, net))
    pairs: list[tuple[str, float, float, str, float, float]] = []
    for index, left in enumerate(points):
        year_left, eps_left, net_left = left
        for year_right, eps_right, net_right in points[index + 1 :]:
            if max(abs(eps_left), abs(eps_right)) <= 10 * min(abs(eps_left), abs(eps_right)):
                continue
            if max(abs(net_left), abs(net_right)) > 10 * min(abs(net_left), abs(net_right)):
                continue
            pairs.append((year_left, eps_left, net_left, year_right, eps_right, net_right))
    return tuple(pairs)


def _net_normalized_gaps(income: Any) -> tuple[tuple[str, float, float], ...]:
    """Years where both income figures are nonzero and one is more than ten times the other.

    The stored numbers are compared as stored. Neither figure is rescaled.
    """

    if not isinstance(income, dict):
        return ()
    gaps: list[tuple[str, float, float]] = []
    for year in sorted(income):
        row = income[year]
        if not isinstance(row, dict):
            continue
        if "Net Income" not in row or "Normalized Income" not in row:
            continue
        net = _optional_float(row.get("Net Income"))
        normalized = _optional_float(row.get("Normalized Income"))
        if net is None or normalized is None or net == 0 or normalized == 0:
            continue
        larger = max(abs(net), abs(normalized))
        smaller = min(abs(net), abs(normalized))
        if larger > 10 * smaller:
            gaps.append((str(year), net, normalized))
    return tuple(gaps)


def _income_sign_gaps(income: Any) -> tuple[tuple[str, float, float], ...]:
    """Years where net income and normalized income are both nonzero and have opposite signs.

    The stored numbers are compared as stored. Neither figure is rescaled.
    """

    if not isinstance(income, dict):
        return ()
    gaps: list[tuple[str, float, float]] = []
    for year in sorted(income):
        row = income[year]
        if not isinstance(row, dict):
            continue
        if "Net Income" not in row or "Normalized Income" not in row:
            continue
        net = _optional_float(row.get("Net Income"))
        normalized = _optional_float(row.get("Normalized Income"))
        if net is None or normalized is None or net == 0 or normalized == 0:
            continue
        if (net > 0) == (normalized > 0):
            continue
        gaps.append((str(year), net, normalized))
    return tuple(gaps)


def _price_quote_path(root: Path, ticker: str) -> Path | None:
    return resolve_json_path(root / "docs/data/research" / ticker / "sources" / "price_quote.json")


def _price_quote_currency(root: Path, ticker: str) -> str | None:
    path = _price_quote_path(root, ticker)
    if path is None:
        return None
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("quote_currency") if isinstance(payload, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _chart_currency(root: Path, ticker: str) -> str | None:
    path = resolve_json_path(root / "docs/data/charts" / f"{ticker}.json")
    if path is None:
        return None
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("currency") if isinstance(payload, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _screen_roe_fraction(display: Any) -> float | None:
    """Screen ROE stored as a percent string, such as ``33.7%``."""

    if not isinstance(display, str) or not display.strip().endswith("%"):
        return None
    number = _optional_float(display)
    if number is None:
        return None
    return number / 100.0


def _price_in_statement_currency(row: ScreenRow) -> float | None:
    """Scale a price only when both currencies are stored and the unit is pence or pounds."""

    price = row.history_price
    quote = row.price_quote_currency
    statement = row.statement_currency
    if price is None or not quote or not statement:
        return None
    if quote == statement:
        return price
    if quote == "GBp" and statement == "GBP":
        return price / 100.0
    if quote == "GBP" and statement == "GBp":
        return price * 100.0
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
            facts = _statement_facts(statement)
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
                    ordinary_shares=facts["ordinary_shares"],
                    company_adjusted=_optional_float(fcf_obj.get("company_adjusted")),
                    screen_ttm=_optional_float(fcf_obj.get("screen_ttm")),
                    cash_dividend=facts["cash_dividend"],
                    repurchase=facts["repurchase"],
                    diluted_eps=facts["diluted_eps"],
                    net_income=facts["net_income"],
                    stockholders_equity=facts["stockholders_equity"],
                    screen_roe=_screen_roe_fraction(key_metrics.get("ROE")),
                    unusual_items=facts["unusual_items"],
                    price_quote_currency=_price_quote_currency(root, ticker),
                    has_price_quote_file=_price_quote_path(root, ticker) is not None,
                    chart_currency=_chart_currency(root, ticker),
                    statement_currency=facts["statement_currency"],
                    statement_fcf=facts["statement_fcf"],
                    fcf_divergence_flagged=(
                        fcf_obj.get("fcf_divergence_flagged")
                        if isinstance(fcf_obj.get("fcf_divergence_flagged"), bool)
                        else None
                    ),
                    statement_revenue=facts["statement_revenue"],
                    discount_display=_metric_text(key_metrics, "Discount"),
                    premium_display=_metric_text(key_metrics, "Premium"),
                    net_normalized_gaps=facts["net_normalized_gaps"],
                    income_sign_gaps=facts["income_sign_gaps"],
                    revenue_year_without_eps=facts["revenue_year_without_eps"],
                    eps_scale_pairs=facts["eps_scale_pairs"],
                )
            )
    return rows


def _metric_text(key_metrics: dict[str, Any], name: str) -> str | None:
    value = key_metrics.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


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


def check_trust_pe_without_discount_or_premium(row: ScreenRow) -> str | None:
    """Trust row whose key metrics include a P/E and include neither a discount nor a premium."""

    if (
        not row.trust
        or "P/E" not in row.key_metric_names
        or "Discount" in row.key_metric_names
        or "Premium" in row.key_metric_names
    ):
        return None
    shown = row.pe_display if row.pe_display is not None else "present"
    return f"trust key metrics include P/E {shown} and include neither a discount nor a premium"


def check_trust_revenue_discount_without_fcf_or_price(row: ScreenRow) -> str | None:
    """Trust row with statement revenue, a discount or premium, no free-cash-flow figure, and no 11 Oct price."""

    if (
        not row.trust
        or row.statement_revenue is None
        or (row.discount_display is None and row.premium_display is None)
        or row.fcf_has_figure
        or row.history_price is not None
    ):
        return None
    labels: list[str] = []
    if row.discount_display is not None:
        labels.append(f"discount {row.discount_display}")
    if row.premium_display is not None:
        labels.append(f"premium {row.premium_display}")
    return (
        f"trust {'; '.join(labels)}; statement revenue {_num(row.statement_revenue)}; "
        f"no free-cash-flow figure; no {SCREEN_PRICE_RUN_PREFIX} price"
    )


def check_missing_annual_statement(row: ScreenRow) -> str | None:
    if row.has_annual_statement:
        return None
    return f"no docs/data/research/{row.ticker}/sources/financials_annual.json"


def check_filing_aligned_differs_from_statement_fcf(row: ScreenRow) -> str | None:
    """Displayed filing_aligned figure differs from the statement line, and the flag is false.

    The screen figures may still equal one another. A missing flag is not false.
    """

    if (
        row.statement_fcf is None
        or row.filing_aligned is None
        or row.displayed_fcf != row.filing_aligned
        or row.fcf_divergence_flagged is not False
        or row.filing_aligned == row.statement_fcf
    ):
        return None
    return (
        f"filing_aligned {_num(row.filing_aligned)} differs from statement free cash flow "
        f"{_num(row.statement_fcf)} and fcf_divergence_flagged is false"
    )


def check_fcf_figures_disagree(row: ScreenRow) -> str | None:
    """Keep filing, company-adjusted, and screen free cash flow as separate stored figures."""

    stored = {
        "filing_aligned": row.filing_aligned,
        "company_adjusted": row.company_adjusted,
        "screen_ttm": row.screen_ttm,
    }
    present = {name: value for name, value in stored.items() if value is not None}
    if len(present) < 2 or len(set(present.values())) < 2:
        return None
    return "; ".join(f"{name} {_num(value)}" for name, value in present.items())


def check_dividend_plus_repurchase_against_filing_fcf(row: ScreenRow) -> str | None:
    if row.cash_dividend is None or row.repurchase is None or row.filing_aligned is None:
        return None
    returned = abs(row.cash_dividend) + abs(row.repurchase)
    if not returned > row.filing_aligned:
        return None
    return (
        f"dividend {_num(row.cash_dividend)} plus repurchase {_num(row.repurchase)} "
        f"is {_num(returned)} against filing free cash flow {_num(row.filing_aligned)}"
    )


def check_cash_dividend_over_cap_against_yield(row: ScreenRow) -> str | None:
    if (
        row.cash_dividend is None
        or row.yield_display is None
        or row.history_price is None
        or row.ordinary_shares is None
    ):
        return None
    shown = _optional_float(row.yield_display)
    price = _price_in_statement_currency(row)
    if price is None or shown is None or row.ordinary_shares <= 0:
        quote = row.price_quote_currency or "unknown"
        statement = row.statement_currency or "unknown"
        return (
            f"cash dividend {_num(row.cash_dividend)}; price {row.history_price} quote {quote}; "
            f"ordinary shares {_num(row.ordinary_shares)}; statement currency {statement}; "
            f"displayed yield {row.yield_display}; readings left side by side"
        )
    cap = price * row.ordinary_shares
    if cap <= 0:
        return None
    cash_yield = abs(row.cash_dividend) / cap * 100.0
    if round(cash_yield, 1) == round(shown, 1):
        return None
    return (
        f"cash dividend {_num(row.cash_dividend)} over cap {_num(cap)} is "
        f"{cash_yield} percent; displayed yield {row.yield_display}"
    )


def check_screen_roe_against_net_income_over_equity(row: ScreenRow) -> str | None:
    if row.screen_roe is None or row.net_income is None or row.stockholders_equity is None:
        return None
    if row.stockholders_equity == 0:
        return None
    ratio = row.net_income / row.stockholders_equity
    if round(row.screen_roe * 100.0, 1) == round(ratio * 100.0, 1):
        return None
    return (
        f"screen ROE {row.screen_roe * 100.0} percent; net income {_num(row.net_income)} "
        f"over equity {_num(row.stockholders_equity)} is {ratio * 100.0} percent"
    )


def check_unusual_items_disagree(row: ScreenRow) -> str | None:
    if len(row.unusual_items) < 2:
        return None
    if len({value for _name, value in row.unusual_items}) < 2:
        return None
    return "; ".join(f"{name} {_num(value)}" for name, value in row.unusual_items)


def check_net_income_ten_times_normalized(row: ScreenRow) -> str | None:
    """A year where both income figures are nonzero and one is more than ten times the other."""

    if not row.net_normalized_gaps:
        return None
    parts = [
        f"{year} net income {_num(net)} beside normalized income {_num(normalized)}"
        for year, net, normalized in row.net_normalized_gaps
    ]
    return "; ".join(parts)


def check_chart_gbp_price_without_quote_file(row: ScreenRow) -> str | None:
    """An 11 Oct price and a chart labeled GBP, with no price_quote.json.

    Absence of the quote file is not a currency. This check does not invent one.
    """

    if row.history_price is None or row.chart_currency != "GBP" or row.has_price_quote_file:
        return None
    return (
        f"chart currency GBP; {SCREEN_PRICE_RUN_PREFIX} price {_num(row.history_price)}; "
        "no price_quote.json"
    )


def check_screen_ttm_differs_filing_aligned_matches_statement(row: ScreenRow) -> str | None:
    """screen_ttm differs from filing_aligned, the flag is false, and filing_aligned equals the statement line.

    Separate from the check where the displayed figure equals filing_aligned and
    that figure differs from the statement. A missing flag is not false.
    """

    if (
        row.screen_ttm is None
        or row.filing_aligned is None
        or row.statement_fcf is None
        or row.fcf_divergence_flagged is not False
        or row.screen_ttm == row.filing_aligned
        or row.filing_aligned != row.statement_fcf
    ):
        return None
    return (
        f"screen_ttm {_num(row.screen_ttm)} differs from filing_aligned "
        f"{_num(row.filing_aligned)}, which equals statement free cash flow "
        f"{_num(row.statement_fcf)}, and fcf_divergence_flagged is false"
    )


def check_chart_gbp_quote_not_pound(row: ScreenRow) -> str | None:
    """Chart file labels the price GBP while the quote currency is neither GBP nor GBp."""

    quote = row.price_quote_currency
    if row.chart_currency != "GBP" or not quote or quote in {"GBP", "GBp"}:
        return None
    if row.history_price is None:
        return f"chart currency GBP and quote currency {quote}"
    return (
        f"chart currency GBP and quote currency {quote}; "
        f"{SCREEN_PRICE_RUN_PREFIX} price {_num(row.history_price)}"
    )


def check_diluted_eps_ten_times_while_net_income_within_ten(row: ScreenRow) -> str | None:
    """One stored diluted EPS is more than ten times another, while net income stays within ten."""

    if not row.eps_scale_pairs:
        return None
    parts = [
        (
            f"{year_left} diluted EPS {_num(eps_left)} beside {year_right} diluted EPS "
            f"{_num(eps_right)}; net income {_num(net_left)} beside {_num(net_right)}"
        )
        for year_left, eps_left, net_left, year_right, eps_right, net_right in row.eps_scale_pairs
    ]
    return "; ".join(parts)


def check_screen_pe_without_diluted_eps_line(row: ScreenRow) -> str | None:
    """Screen P/E beside the latest revenue-and-income year that has no diluted-EPS line."""

    if "P/E" not in row.key_metric_names or not row.pe_display:
        return None
    gap = row.revenue_year_without_eps
    if gap is None:
        return None
    year, revenue, net = gap
    return (
        f"screen P/E {row.pe_display}; {year} revenue {_num(revenue)} "
        f"net income {_num(net)}; no diluted EPS line"
    )


def check_positive_diluted_eps_without_screen_pe(row: ScreenRow) -> str | None:
    """Latest diluted EPS is positive and the screen key metrics have no P/E key."""

    eps = row.diluted_eps
    if eps is None or not eps > 0 or "P/E" in row.key_metric_names:
        return None
    return f"diluted EPS {_num(eps)} and the screen key metrics have no P/E key"


def check_net_income_normalized_opposite_signs(row: ScreenRow) -> str | None:
    """A year where net income and normalized income are nonzero and have opposite signs."""

    if not row.income_sign_gaps:
        return None
    parts = [
        f"{year} net income {_num(net)} beside normalized income {_num(normalized)}"
        for year, net, normalized in row.income_sign_gaps
    ]
    return "; ".join(parts)


def check_positive_screen_pe_beside_negative_diluted_eps(row: ScreenRow) -> str | None:
    """A positive screen P/E beside a negative diluted EPS. Neither figure is rescaled."""

    pe = _optional_float(row.pe_display)
    eps = row.diluted_eps
    if pe is None or eps is None or not pe > 0 or not eps < 0:
        return None
    return f"screen P/E {row.pe_display} beside diluted EPS {_num(eps)}"


def check_screen_pe_against_price_over_diluted_eps(row: ScreenRow) -> str | None:
    pe = _optional_float(row.pe_display)
    if pe is None or row.history_price is None or row.diluted_eps is None:
        return None
    price = _price_in_statement_currency(row)
    if price is None or row.diluted_eps == 0:
        quote = row.price_quote_currency or "unknown"
        statement = row.statement_currency or "unknown"
        return (
            f"screen P/E {row.pe_display}; price {row.history_price} quote {quote}; "
            f"diluted EPS {_num(row.diluted_eps)}; statement currency {statement}; "
            "readings left side by side"
        )
    ratio = price / row.diluted_eps
    if round(ratio, 1) == round(pe, 1):
        return None
    return (
        f"screen P/E {row.pe_display}; price {price} {row.statement_currency} "
        f"over diluted EPS {_num(row.diluted_eps)} is {ratio}"
    )


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
        "trust_pe_without_discount_or_premium",
        "a trust row whose key metrics include a P/E and include neither a discount nor a premium",
        check_trust_pe_without_discount_or_premium,
    ),
    Check(
        "trust_revenue_discount_without_fcf_or_price",
        "a trust row with statement revenue, a discount or premium, no free-cash-flow figure, and no 11 Oct price",
        check_trust_revenue_discount_without_fcf_or_price,
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
    Check(
        "filing_aligned_differs_from_statement_fcf",
        "filing_aligned display differs from the statement free-cash-flow line while unflagged",
        check_filing_aligned_differs_from_statement_fcf,
    ),
    Check(
        "screen_ttm_differs_filing_aligned_matches_statement",
        "screen TTM differs from filing_aligned while that figure equals the statement line and the flag is false",
        check_screen_ttm_differs_filing_aligned_matches_statement,
    ),
    Check(
        "fcf_figures_disagree",
        "filing, company-adjusted, and screen free cash flow that differ",
        check_fcf_figures_disagree,
    ),
    Check(
        "dividend_plus_repurchase_against_filing_fcf",
        "dividend plus repurchase against filing free cash flow",
        check_dividend_plus_repurchase_against_filing_fcf,
    ),
    Check(
        "cash_dividend_over_cap_against_yield",
        "cash dividend over cap against the displayed yield",
        check_cash_dividend_over_cap_against_yield,
    ),
    Check(
        "screen_roe_against_net_income_over_equity",
        "screen return on equity against net income over equity",
        check_screen_roe_against_net_income_over_equity,
    ),
    Check(
        "unusual_items_disagree",
        "unusual-item fields that disagree",
        check_unusual_items_disagree,
    ),
    Check(
        "screen_pe_against_price_over_diluted_eps",
        "screen P/E against price over diluted earnings when the currency is known",
        check_screen_pe_against_price_over_diluted_eps,
    ),
    Check(
        "net_income_ten_times_normalized",
        "a year where net income and normalized income are both nonzero and one is more than ten times the other",
        check_net_income_ten_times_normalized,
    ),
    Check(
        "positive_screen_pe_beside_negative_diluted_eps",
        "a positive screen P/E beside a negative diluted EPS",
        check_positive_screen_pe_beside_negative_diluted_eps,
    ),
    Check(
        "chart_gbp_quote_not_pound",
        "a chart that labels the price GBP while the quote currency is neither GBP nor GBp",
        check_chart_gbp_quote_not_pound,
    ),
    Check(
        "chart_gbp_price_without_quote_file",
        "an 11 Oct price and a chart labeled GBP, with no price_quote.json",
        check_chart_gbp_price_without_quote_file,
    ),
    Check(
        "positive_diluted_eps_without_screen_pe",
        "a positive diluted EPS while the screen key metrics have no P/E key",
        check_positive_diluted_eps_without_screen_pe,
    ),
    Check(
        "screen_pe_without_diluted_eps_line",
        "a stored screen P/E whose latest revenue and net-income year has no diluted EPS line",
        check_screen_pe_without_diluted_eps_line,
    ),
    Check(
        "diluted_eps_ten_times_while_net_income_within_ten",
        "one stored diluted EPS more than ten times another while net income in those years stays within ten times",
        check_diluted_eps_ten_times_while_net_income_within_ten,
    ),
    Check(
        "net_income_normalized_opposite_signs",
        "a year where net income and normalized income have opposite signs",
        check_net_income_normalized_opposite_signs,
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
