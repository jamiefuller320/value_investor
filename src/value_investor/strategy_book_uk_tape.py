"""EODHD point-in-time tape for the UK/Europe strategy-book replay.

Produces the panel rows, adjusted bars and gate labels the sealed walker
(``strategy_book_observe.walk_book``) already consumes. Licensed numbers stay
in memory or in the gitignored cache. Nothing here is written to the repo.

Constants are read from ``strategy_book_uk_replay.REGISTRATION_CONSTANTS``.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

import pandas as pd

from value_investor.ch_failed_name_statements import CH_NAME_BY_KEY
from value_investor.eodhd_coverage_check import _name_matches, _parse_date, _trading_days_between
from value_investor.fund_or_trust import classify_fund_or_trust

_SCALE = {
    "millions": 1_000_000.0,
    "million": 1_000_000.0,
    "thousands": 1_000.0,
    "thousand": 1_000.0,
    "billions": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
    "units": 1.0,
    "unit": 1.0,
}


def _const(name: str) -> Any:
    from value_investor.strategy_book_uk_replay import REGISTRATION_CONSTANTS

    return REGISTRATION_CONSTANTS[name]


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text or text.lower() in {"na", "none", "null", "nm"}:
            return None
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def listing_unit(code: str | None) -> str | None:
    """``pence``, ``pounds``, ``eur`` or ``usd``. ``GBp`` is pence; ``GBP`` is pounds."""
    if not code or not str(code).strip():
        return None
    text = str(code).strip()
    upper = text.upper()
    if upper == "GBX" or (upper == "GBP" and "p" in text):
        return "pence"
    if upper == "GBP":
        return "pounds"
    if upper == "EUR":
        return "eur"
    if upper == "USD":
        return "usd"
    return None


def parse_split(value: Any) -> float | None:
    """``new/old`` as a scale factor. A single number is not a split."""
    text = str(value or "").strip()
    if text.count("/") != 1:
        return None
    left, right = text.split("/", 1)
    new = finite(left)
    old = finite(right)
    if new is None or old is None or old == 0 or new <= 0:
        return None
    return new / old


def select_shares(
    annual: Sequence[Mapping[str, Any]] | None,
    quarterly: Sequence[Mapping[str, Any]] | None,
    session: date,
) -> dict[str, Any] | None:
    """Latest positive shares row on ``dateFormatted`` only. Quarterly wins a tie."""
    field = str(_const("SHARES_DATE_FIELD"))
    best: dict[str, Any] | None = None
    best_key: tuple[int, int] | None = None
    for period, rows in (("annual", annual or ()), ("quarterly", quarterly or ())):
        # EODHD keys ``outstandingShares`` periods "0", "1", ...: the rows are the values.
        for row in rows.values() if isinstance(rows, Mapping) else rows:
            if not isinstance(row, Mapping):
                continue
            formatted = _parse_date(row.get(field))
            if formatted is None or formatted > session:
                continue
            shares = finite(row.get("shares"))
            if shares is None or shares <= 0:
                continue
            key = (formatted.toordinal(), 1 if period == "quarterly" else 0)
            if best_key is None or key > best_key:
                best_key = key
                best = {"shares": shares, "date": formatted, "period": period}
    return best


def scale_shares(
    shares: float,
    share_date: date,
    splits: Sequence[Mapping[str, Any]] | None,
    session: date,
) -> tuple[float | None, bool]:
    """Scale by splits dated after the shares date and on or before the session.

    An unparsed split in that window returns ``(None, True)``.
    """
    factor = 1.0
    for row in splits or ():
        if not isinstance(row, Mapping):
            continue
        day = _parse_date(row.get("date"))
        if day is None or not (share_date < day <= session):
            continue
        ratio = parse_split(row.get("split"))
        if ratio is None:
            return None, True
        factor *= ratio
    return shares * factor, False


class FxSeries(dict):
    """A date -> close map with its days sorted once. Do not mutate after building."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.days = sorted(self)

    def on_or_before(self, session: date) -> date | None:
        position = bisect_right(self.days, session)
        return self.days[position - 1] if position else None


def _fx_on(series: Mapping[date, float] | None, session: date) -> float | None:
    if not series:
        return None
    found = None
    if isinstance(series, FxSeries):
        found = series.on_or_before(session)
    else:
        for day, _value in series.items():
            if day <= session and (found is None or day > found):
                found = day
    if found is None:
        return None
    if (session - found).days > int(_const("FX_CARRY_DAYS")):
        return None
    value = series[found]
    return value if value and value > 0 else None


def cap_in_rank_currency(
    raw_close: float | None,
    currency: str | None,
    shares: float | None,
    *,
    rank_currency: str,
    session: date,
    eurgbp: Mapping[date, float] | None,
    usdgbp: Mapping[date, float] | None,
) -> dict[str, Any]:
    """Market cap, or a not-computable / implausible reason. No previous-month fill."""
    if raw_close is None or raw_close <= 0 or shares is None or shares <= 0:
        return {"cap": None, "reason": "cap_not_computable"}
    unit = listing_unit(currency)
    if unit is None:
        return {"cap": None, "reason": "cap_not_computable"}
    gbp_rate = _fx_on(eurgbp, session)
    usd_rate = _fx_on(usdgbp, session)
    price_gbp: float | None
    if unit == "pence":
        price_gbp = raw_close / 100.0
    elif unit == "pounds":
        price_gbp = raw_close
    elif unit == "eur":
        price_gbp = None if gbp_rate is None else raw_close * gbp_rate
    else:
        price_gbp = None if usd_rate is None else raw_close * usd_rate
    if price_gbp is None:
        return {"cap": None, "reason": "cap_not_computable"}
    cap_gbp = price_gbp * shares
    high = float(_const("CAP_IMPLAUSIBLE_HIGH_GBP"))
    low = float(_const("CAP_IMPLAUSIBLE_LOW_GBP"))
    if cap_gbp > high or cap_gbp < low:
        return {"cap": None, "reason": "cap_unit_implausible", "cap_gbp": cap_gbp}
    if rank_currency == "GBP":
        return {"cap": cap_gbp, "reason": None}
    if rank_currency != "EUR":
        return {"cap": None, "reason": "cap_not_computable"}
    if unit == "eur":
        return {"cap": raw_close * shares, "reason": None}
    if unit == "usd":
        if gbp_rate is None or usd_rate is None:
            return {"cap": None, "reason": "cap_not_computable"}
        return {"cap": raw_close * shares * usd_rate / gbp_rate, "reason": None}
    return {"cap": None, "reason": "cap_not_computable"}


def fx_band_ok(
    eurgbp: Sequence[tuple[date, float]], usdgbp: Sequence[tuple[date, float]]
) -> tuple[bool, str | None]:
    """First 2024 session of each pair must sit in the sealed band. Pairs are not inverted."""
    bands = {
        "EURGBP": (_const("EURGBP_SANITY_LOW"), _const("EURGBP_SANITY_HIGH"), eurgbp),
        "USDGBP": (_const("USDGBP_SANITY_LOW"), _const("USDGBP_SANITY_HIGH"), usdgbp),
    }
    for name, (low, high, rows) in bands.items():
        first = next((value for day, value in sorted(rows) if day.year == 2024), None)
        if first is None or not (float(low) <= float(first) <= float(high)):
            return False, f"{name} first 2024 close outside [{low}, {high}]"
    return True, None


def is_common_stock(general_type: str | None) -> bool:
    if general_type is None or not str(general_type).strip():
        return True
    return str(general_type).strip().lower() == "common stock"


def fund_or_trust(ticker: str, general: Mapping[str, Any]) -> bool:
    """Existing name/sector/industry/type rules. The live override file is not applied."""
    row = {
        "name": general.get("Name") or general.get("name"),
        "sector": general.get("Sector") or general.get("sector"),
        "industry": general.get("Industry") or general.get("industry"),
        "quote_type": general.get("Type") or general.get("type"),
    }
    return classify_fund_or_trust(ticker, row, overrides=None) is not None


def month_end_dates(sessions: Iterable[date]) -> list[date]:
    """Last session of each calendar month. A session is a date that has a close."""
    ends: dict[tuple[int, int], date] = {}
    for day in sessions:
        key = (day.year, day.month)
        if key not in ends or day > ends[key]:
            ends[key] = day
    return [ends[key] for key in sorted(ends)]


def listed_on(session: date, *, delisted: bool, last_bar: date | None) -> bool:
    """A delisted symbol ranks only on sessions on or before its last close."""
    if not delisted:
        return True
    return last_bar is not None and session <= last_bar


def rank_month(
    rows: Sequence[Mapping[str, Any]],
    *,
    rank_count: int,
) -> dict[str, Any]:
    """Largest-cap cut. Ties break by symbol ascending. Gaps are counted, not carried."""
    excluded_not_common = 0
    excluded_fund = 0
    not_computable = 0
    implausible = 0
    unparsed = 0
    eligible: list[tuple[float, str]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if not is_common_stock(row.get("general_type")):
            excluded_not_common += 1
            continue
        if row.get("fund_or_trust"):
            excluded_fund += 1
            continue
        reason = row.get("cap_reason")
        if reason == "cap_unit_implausible":
            implausible += 1
            continue
        if reason or row.get("cap") is None:
            not_computable += 1
            if row.get("split_unparsed"):
                unparsed += 1
            continue
        eligible.append((float(row["cap"]), symbol))
    eligible.sort(key=lambda item: (-item[0], item[1]))
    ties = 0
    for index in range(1, len(eligible)):
        if eligible[index][0] == eligible[index - 1][0]:
            ties += 1
    kept = [symbol for _cap, symbol in eligible[: int(rank_count)]]
    return {
        "members": kept,
        "cap_tie_broken_by_symbol": ties,
        "cap_not_computable": not_computable,
        "cap_unit_implausible": implausible,
        "excluded_not_common": excluded_not_common,
        "excluded_fund_or_trust": excluded_fund,
        "split_unparsed": unparsed,
        "considered": len(rows),
    }


def membership_spans(
    month_members: Sequence[tuple[date, set[str]]],
    last_session: date,
) -> dict[str, list[tuple[date, date]]]:
    """A month-end set dated *D* covers sessions strictly after *D*, through the next *D*."""
    if not month_members:
        return {}
    ordered = sorted(month_members, key=lambda item: item[0])
    spans: dict[str, list[tuple[date, date]]] = {}
    for index, (day, members) in enumerate(ordered):
        start = day + timedelta(days=1)
        end = ordered[index + 1][0] if index + 1 < len(ordered) else last_session
        if start > end:
            continue
        for symbol in members:
            rows = spans.setdefault(symbol, [])
            if rows and rows[-1][1] + timedelta(days=1) >= start and rows[-1][1] < start:
                rows[-1] = (rows[-1][0], end)
            elif rows and rows[-1][1] >= start:
                rows[-1] = (rows[-1][0], max(rows[-1][1], end))
            else:
                rows.append((start, end))
    return spans


def first_visible_session(
    *,
    period_end: date | None,
    filing_date: date | None,
    annual: bool,
) -> date | None:
    """Filing date, else period end plus the statement lag, then the 2-day visibility lag."""
    if filing_date is not None:
        base = filing_date
    elif period_end is not None:
        lag = int(_const("STATEMENT_LAG_DAYS") if annual else _const("INTERIM_STATEMENT_LAG_DAYS"))
        base = period_end + timedelta(days=lag)
    else:
        return None
    return base + timedelta(days=int(_const("FILING_LAG_DAYS")))


def is_stale(session: date, period_end: date | None) -> bool:
    if period_end is None:
        return True
    return (session - period_end).days > int(_const("STALE_FILING_DAYS"))


def _yearly_maps(block: Any) -> list[dict[str, Any]]:
    if isinstance(block, dict):
        rows = []
        for key, value in block.items():
            if not isinstance(value, dict):
                continue
            row = dict(value)
            row.setdefault("date", key)
            rows.append(row)
        return rows
    if isinstance(block, list):
        return [dict(row) for row in block if isinstance(row, dict)]
    return []


def _field(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in row:
            number = finite(row.get(key))
            if number is not None:
                return number
    return None


def _ch_amount(field: Mapping[str, Any] | None, *, money: bool) -> float | None:
    if not field or field.get("value") in (None, ""):
        return None
    number = finite(field.get("value"))
    if number is None:
        return None
    scale = _SCALE.get(str(field.get("scale") or "").lower(), 1.0)
    if money:
        number *= scale
    unit = str(field.get("unit") or "").lower()
    if unit == "pence":
        number /= 100.0
    return number


def _statement_from_fields(
    *,
    year: int,
    period_end: date | None,
    filing_date: date | None,
    source: str,
    fields: Mapping[str, Any],
    annual: bool,
) -> dict[str, Any]:
    revenue = _ch_amount(fields.get("revenue"), money=True)
    operating = _ch_amount(fields.get("operating_profit"), money=True)
    net_income = _ch_amount(fields.get("profit_attributable_to_owners"), money=True)
    shares = _ch_amount(fields.get("weighted_average_basic_shares"), money=False)
    if shares is not None:
        scale = _SCALE.get(
            str((fields.get("weighted_average_basic_shares") or {}).get("scale") or "").lower(),
            1.0,
        )
        shares *= scale
    eps = _ch_amount(fields.get("basic_eps"), money=False)
    ocf = _ch_amount(fields.get("net_cash_from_operating_activities"), money=True)
    capex = _ch_amount(fields.get("capital_expenditure"), money=True)
    fcf = None
    if ocf is not None and capex is not None and capex >= 0:
        fcf = ocf - capex
    visible = first_visible_session(period_end=period_end, filing_date=filing_date, annual=annual)
    return {
        "year": year,
        "period_end": period_end,
        "filing_date": filing_date,
        "visible_from": visible,
        "source": source,
        "total_revenue": revenue,
        "operating_income": operating,
        "ebit": operating,
        "net_income": net_income,
        "shares": shares,
        "eps": eps,
        "eps_basis": "companies_house_basic" if eps is not None or net_income is not None else None,
        "operating_cashflow": ocf,
        "free_cashflow": fcf,
        "balance_sheet": False,
    }


def ch_statements(filings: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Primary year, plus a comparative only for a year with no primary filing."""
    primary: dict[int, dict[str, Any]] = {}
    comparative: dict[int, dict[str, Any]] = {}
    for filing in filings or ():
        year = filing.get("fiscal_year")
        if year is None:
            continue
        year = int(year)
        primary[year] = _statement_from_fields(
            year=year,
            period_end=_parse_date(filing.get("fiscal_year_end")),
            filing_date=_parse_date(filing.get("filing_date")),
            source="primary",
            fields=filing.get("fields") or {},
            annual=True,
        )
        comp = filing.get("comparative") or {}
        comp_year = comp.get("fiscal_year")
        if comp_year is None:
            continue
        comparative[int(comp_year)] = _statement_from_fields(
            year=int(comp_year),
            period_end=_parse_date(comp.get("fiscal_year_end")),
            filing_date=_parse_date(comp.get("filing_date") or filing.get("filing_date")),
            source="comparative",
            fields=comp.get("fields") or {},
            annual=True,
        )
    years = set(primary) | set(comparative)
    out = []
    for year in sorted(years):
        out.append(primary[year] if year in primary else comparative[year])
    return out


def eodhd_annual_statements(fundamentals: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Fiscal-year income, cash flow and balance sheet. Highlights are not read."""
    if not fundamentals:
        return []
    financials = fundamentals.get("Financials") or {}
    income = _yearly_maps((financials.get("Income_Statement") or {}).get("yearly"))
    cash = {
        str(row.get("date") or "")[:10]: row
        for row in _yearly_maps((financials.get("Cash_Flow") or {}).get("yearly"))
    }
    balance = {
        str(row.get("date") or "")[:10]: row
        for row in _yearly_maps((financials.get("Balance_Sheet") or {}).get("yearly"))
    }
    earnings = {
        str(row.get("date") or "")[:10]: row
        for row in _yearly_maps((fundamentals.get("Earnings") or {}).get("Annual"))
    }
    out = []
    for row in income:
        period_end = _parse_date(row.get("date"))
        if period_end is None:
            continue
        key = period_end.isoformat()
        flow = cash.get(key, {})
        sheet = balance.get(key, {})
        earned = earnings.get(key, {})
        capex = _field(flow, "capitalExpenditures")
        ocf = _field(flow, "totalCashFromOperatingActivities")
        fcf = _field(flow, "freeCashFlow")
        if fcf is None and ocf is not None and capex is not None and capex <= 0:
            fcf = ocf + capex
        eps = _field(earned, "epsActual")
        shares = _field(sheet, "commonStockSharesOutstanding")
        net_income = _field(row, "netIncomeApplicableToCommonShares", "netIncome")
        eps_basis = None
        if eps is not None:
            eps_basis = "vendor_eps"
        elif net_income is not None and shares not in (None, 0):
            eps = net_income / shares
            eps_basis = "net_income_over_shares"
        filing = _parse_date(row.get("filing_date"))
        out.append(
            {
                "year": period_end.year,
                "period_end": period_end,
                "filing_date": filing,
                "visible_from": first_visible_session(
                    period_end=period_end, filing_date=filing, annual=True
                ),
                "source": "primary",
                "total_revenue": _field(row, "totalRevenue"),
                "operating_income": _field(row, "operatingIncome"),
                "ebit": _field(row, "ebit", "operatingIncome"),
                "ebitda": _field(row, "ebitda"),
                "net_income": net_income,
                "interest_expense": _field(row, "interestExpense"),
                "gross_profit": _field(row, "grossProfit"),
                "operating_cashflow": ocf,
                "free_cashflow": fcf,
                "total_assets": _field(sheet, "totalAssets"),
                "total_current_assets": _field(sheet, "totalCurrentAssets"),
                "total_liabilities": _field(sheet, "totalLiab"),
                "total_current_liabilities": _field(sheet, "totalCurrentLiabilities"),
                "total_debt": _debt(sheet),
                "total_cash": _field(sheet, "cashAndShortTermInvestments", "cash"),
                "book_value": _field(sheet, "totalStockholderEquity"),
                "shares": shares,
                "eps": eps,
                "eps_basis": eps_basis,
                "balance_sheet": True,
            }
        )
    return out


def _debt(sheet: Mapping[str, Any]) -> float | None:
    total = _field(sheet, "shortLongTermDebtTotal")
    if total is not None:
        return total
    short = _field(sheet, "shortTermDebt")
    long = _field(sheet, "longTermDebt")
    if short is None and long is None:
        return None
    return (short or 0.0) + (long or 0.0)


def merge_statement_years(
    eodhd_rows: Sequence[Mapping[str, Any]],
    ch_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """One source per fiscal year. Companies House fills only a year EODHD lacks.

    A missing year stays missing. Nothing is copied forward from the last year on file.
    """
    by_year: dict[int, dict[str, Any]] = {}
    for row in eodhd_rows:
        by_year[int(row["year"])] = dict(row)
    for row in ch_rows:
        year = int(row["year"])
        if year not in by_year:
            by_year[year] = dict(row)
    return [by_year[year] for year in sorted(by_year)]


def eodhd_quarterly(fundamentals: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not fundamentals:
        return []
    financials = fundamentals.get("Financials") or {}
    rows = _yearly_maps((financials.get("Income_Statement") or {}).get("quarterly"))
    out = []
    for row in rows:
        period_end = _parse_date(row.get("date"))
        if period_end is None:
            continue
        filing = _parse_date(row.get("filing_date"))
        out.append(
            {
                "period_end": period_end,
                "visible_from": first_visible_session(
                    period_end=period_end, filing_date=filing, annual=False
                ),
                "total_revenue": _field(row, "totalRevenue"),
            }
        )
    return out


def interim_eps_rows(fundamentals: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    history = ((fundamentals or {}).get("Earnings") or {}).get("History")
    out = []
    for row in _yearly_maps(history):
        day = _parse_date(row.get("reportDate")) or _parse_date(row.get("date"))
        if day is None:
            continue
        out.append(
            {
                "period_end": _parse_date(row.get("date")) or day,
                "visible_from": day + timedelta(days=int(_const("FILING_LAG_DAYS"))),
                "eps": _field(row, "epsActual"),
                "eps_basis": "vendor_eps",
            }
        )
    return out


def _visible_rows(
    rows: Sequence[Mapping[str, Any]], session: date, *, fresh: bool = True
) -> list[Mapping[str, Any]]:
    """Rows filed by ``session``. ``fresh`` also drops stale rows.

    Staleness applies to the latest statement only. A prior year is a
    comparator: it needs to be visible, not fresh (as in the US rehearsal).
    """
    kept = []
    for row in rows:
        visible = row.get("visible_from")
        if visible is None or visible > session:
            continue
        if fresh and is_stale(session, row.get("period_end")):
            continue
        kept.append(row)
    return kept


def _change(latest: float | None, prior: float | None) -> float | None:
    if latest is None or prior is None or prior <= 0:
        return None
    return latest / prior - 1.0


def _prior_year(rows: Sequence[Mapping[str, Any]], year: int) -> Mapping[str, Any] | None:
    found = [row for row in rows if int(row["year"]) == year]
    return found[-1] if found else None


def decline_verdict(
    annual: Sequence[Mapping[str, Any]],
    quarterly: Sequence[Mapping[str, Any]],
    interim_eps: Sequence[Mapping[str, Any]],
    session: date,
) -> dict[str, Any]:
    """Section 3.2. Dividend-cut and headline checks do not fire."""
    hard: list[str] = []
    soft: list[str] = []
    visible = _visible_rows(annual, session)
    compared = _visible_rows(annual, session, fresh=False)
    revenue_ok = margin_ok = eps_ok = False
    mismatch = 0
    checks: dict[str, Any] = {
        "statement_basis": "eodhd_annual",
        "dividend": "absent",
        "profit_warning": "absent",
        "impairment_or_downgrade": "absent",
    }
    if visible:
        latest = max(visible, key=lambda row: (row.get("period_end") or date.min, row["year"]))
        prior = _prior_year(compared, int(latest["year"]) - 1)
        prior2 = _prior_year(compared, int(latest["year"]) - 2)
        change = _change(
            latest.get("total_revenue"), None if prior is None else prior.get("total_revenue")
        )
        prior_change = None
        if prior is not None and prior2 is not None:
            prior_change = _change(prior.get("total_revenue"), prior2.get("total_revenue"))
        revenue_ok = change is not None
        if change is not None and change < -float(_const("REVENUE_DROP_PCT")):
            hard.append("revenue_decline")
        flat = float(_const("REVENUE_FLAT_TOLERANCE_PCT"))
        if (
            change is not None
            and prior_change is not None
            and change < -flat
            and prior_change < -flat
        ):
            hard.append("revenue_two_year_decline")
        checks["revenue"] = {
            "change_pct": change,
            "prior_change_pct": prior_change,
            "evaluable": revenue_ok,
            "source": latest.get("source"),
        }
        margin = _margin_change(latest, prior)
        margin_ok = margin is not None
        if margin is not None and -margin > float(_const("MARGIN_DROP_PP")):
            hard.append("operating_margin_drop")
        checks["operating_margin"] = {"change_pp": margin, "evaluable": margin_ok}
        eps_now, eps_prev, basis_now, basis_prev = _eps_pair(latest, prior)
        if basis_now and basis_prev and basis_now != basis_prev:
            mismatch += 1
            eps_ok = False
            eps_change = None
        else:
            eps_ok = eps_now is not None and eps_prev is not None
            eps_change = _change(eps_now, eps_prev)
            if (
                eps_prev is not None
                and eps_prev > 0
                and eps_now is not None
                and eps_now < eps_prev * (1.0 - float(_const("EPS_ANNUAL_DROP_PCT")))
            ):
                soft.append("eps_decline_annual")
        checks["eps_annual"] = {
            "change_pct": eps_change if mismatch == 0 else None,
            "evaluable": eps_ok,
            "eps_basis": basis_now if basis_now == basis_prev else None,
        }
        fcf_now = latest.get("free_cashflow")
        fcf_prev = None if prior is None else prior.get("free_cashflow")
        if fcf_now is not None and fcf_prev is not None and fcf_prev > 0:
            if fcf_now < 0:
                hard.append("fcf_turned_negative")
            elif fcf_now < fcf_prev * (1.0 - float(_const("FCF_SHARP_FALL_PCT"))):
                soft.append("fcf_sharp_fall")
        checks["fcf"] = {
            "evaluable": fcf_now is not None and fcf_prev is not None,
            "change_pct": _change(fcf_now, fcf_prev),
        }
    else:
        checks["revenue"] = {"change_pct": None, "prior_change_pct": None, "evaluable": False}
    interim = _interim_revenue(quarterly, session)
    if interim is not None and interim < -float(_const("INTERIM_REVENUE_DROP_PCT")):
        hard.append("interim_revenue_decline")
    checks["interim_revenue"] = {"change_pct": interim, "evaluable": interim is not None}
    eps_interim_ok, eps_interim_change = _interim_eps(interim_eps, session, soft)
    checks["eps_interim"] = {"change_pct": eps_interim_change, "evaluable": eps_interim_ok}
    checks["hard_reasons"] = list(hard)
    checks["eps_basis_mismatch"] = mismatch
    if hard or len(soft) >= int(_const("SOFT_SIGNALS_TO_DECLINE")):
        verdict = "declining"
    elif not revenue_ok or not (margin_ok or eps_ok or eps_interim_ok):
        verdict = "insufficient_data"
    else:
        verdict = "clear"
    return {
        "verdict": verdict,
        "checks": checks,
        "soft": soft,
        "revenue_evaluable": revenue_ok,
        "eps_basis_mismatch": mismatch,
    }


def _margin_change(latest: Mapping[str, Any], prior: Mapping[str, Any] | None) -> float | None:
    if prior is None:
        return None
    revenue_now = latest.get("total_revenue")
    revenue_prev = prior.get("total_revenue")
    if not revenue_now or not revenue_prev or revenue_now <= 0 or revenue_prev <= 0:
        return None
    for key in ("operating_income", "ebit"):
        now = latest.get(key)
        then = prior.get(key)
        if now is not None and then is not None and latest.get(key) is not None:
            if (latest.get("operating_income") is not None) != (
                prior.get("operating_income") is not None
            ):
                continue
            return now / revenue_now - then / revenue_prev
    return None


def _eps_pair(
    latest: Mapping[str, Any], prior: Mapping[str, Any] | None
) -> tuple[float | None, float | None, str | None, str | None]:
    if prior is None:
        return latest.get("eps"), None, latest.get("eps_basis"), None
    return latest.get("eps"), prior.get("eps"), latest.get("eps_basis"), prior.get("eps_basis")


def year_before(day: date) -> date:
    """Same day a year earlier. 29 February maps to 28 February."""
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def _interim_rows(
    rows: Sequence[Mapping[str, Any]], session: date
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """(filed by ``session``, of those the ones within the age limit).

    The age limit applies to the latest quarter; the year-earlier quarter is a
    comparator and needs only to be filed.
    """
    visible = [
        row
        for row in rows
        if row.get("visible_from") is not None
        and row["visible_from"] <= session
        and row.get("period_end") is not None
    ]
    limit = int(_const("INTERIM_MAX_AGE_DAYS"))
    fresh = [row for row in visible if (session - row["period_end"]).days <= limit]
    return visible, fresh


def _interim_revenue(rows: Sequence[Mapping[str, Any]], session: date) -> float | None:
    visible, fresh = _interim_rows(rows, session)
    if not fresh:
        return None
    latest = max(fresh, key=lambda row: row["period_end"])
    target = year_before(latest["period_end"])
    window = int(_const("INTERIM_YOY_WINDOW_DAYS"))
    prior = None
    best_gap = None
    for row in visible:
        if row["period_end"] == latest["period_end"]:
            continue
        gap = abs((row["period_end"] - target).days)
        if gap <= window and (best_gap is None or gap < best_gap):
            best_gap = gap
            prior = row
    if prior is None:
        return None
    return _change(latest.get("total_revenue"), prior.get("total_revenue"))


def _interim_eps(
    rows: Sequence[Mapping[str, Any]], session: date, soft: list[str]
) -> tuple[bool, float | None]:
    visible, fresh = _interim_rows(rows, session)
    if not fresh:
        return False, None
    latest = max(fresh, key=lambda row: row["period_end"])
    target = year_before(latest["period_end"])
    window = int(_const("INTERIM_YOY_WINDOW_DAYS"))
    prior = None
    best_gap = None
    for row in visible:
        if row["period_end"] == latest["period_end"]:
            continue
        gap = abs((row["period_end"] - target).days)
        if gap <= window and (best_gap is None or gap < best_gap):
            best_gap = gap
            prior = row
    if prior is None or latest.get("eps") is None or prior.get("eps") is None:
        return False, None
    if latest.get("eps_basis") != prior.get("eps_basis"):
        return False, None
    change = _change(latest.get("eps"), prior.get("eps"))
    prev = prior.get("eps")
    now = latest.get("eps")
    if prev is not None and prev > 0 and now is not None:
        if now < prev * (1.0 - float(_const("EPS_INTERIM_DROP_PCT"))):
            soft.append("eps_decline_interim")
    return True, change


def sector_decision(
    *,
    price_coverage: bool,
    price_trigger: bool,
    decline_coverage: bool,
    decline_breadth: float | None,
    sector_missing: bool,
) -> dict[str, Any]:
    """Section 3.3 table. ``price_only`` is sound only when decline coverage fails."""
    if sector_missing:
        return {"verdict": "sector_missing", "sector_basis": "sector_missing"}
    breadth_fires = (
        decline_coverage
        and decline_breadth is not None
        and decline_breadth >= float(_const("EARNINGS_BREADTH_HEADWIND"))
    )
    if price_trigger or breadth_fires:
        if price_coverage and decline_coverage:
            basis = "price_and_decline"
        elif price_trigger:
            basis = "price_only" if not decline_coverage else "price_and_decline"
        else:
            basis = "decline_only"
        return {"verdict": "headwind", "sector_basis": basis}
    if price_coverage and not price_trigger and decline_coverage and not breadth_fires:
        return {"verdict": "sound", "sector_basis": "price_and_decline"}
    if price_coverage and not price_trigger and not decline_coverage:
        return {"verdict": "sound", "sector_basis": "price_only"}
    return {"verdict": "insufficient_data", "sector_basis": None}


def price_trigger(breadth_share: float | None, trend: float | None, *, covered: bool) -> bool:
    if not covered or breadth_share is None or trend is None:
        return False
    return breadth_share >= float(_const("PRICE_BREADTH_HEADWIND")) and trend < float(
        _const("SECTOR_RETURN_126D_HEADWIND")
    )


def coverage_met(with_data: int, members: int) -> bool:
    if members <= 0:
        return False
    return (
        with_data >= int(_const("MIN_MEMBERS_WITH_DATA"))
        and with_data >= float(_const("MIN_COVERAGE_SHARE")) * members
    )


def probe_class(key: str | None) -> str:
    if not key:
        return "unclassified"
    for row in _const("PROBE_CLASSES"):
        if row["key"] == key:
            return str(row["klass"])
    return "unclassified"


def haircut_for(key: str | None, *, variant: str, delisted: bool) -> float | None:
    """Baseline 0. Sensitivity −30% on failures and unclassified. Takeovers stay at 0."""
    if not delisted:
        return None
    if variant == "baseline":
        return float(_const("DELIST_HAIRCUT_BASELINE"))
    if probe_class(key) == "known_takeover":
        return float(_const("DELIST_HAIRCUT_BASELINE"))
    return float(_const("DELIST_HAIRCUT_SENSITIVITY"))


def price_ended_before_known_event(last_bar: date | None, known_end: date | None) -> bool:
    if last_bar is None or known_end is None or last_bar >= known_end:
        return False
    return _trading_days_between(last_bar, known_end) > int(_const("TRADING_DAYS_TOLERANCE"))


def match_ch_key(name: str | None) -> str | None:
    if not name:
        return None
    for key, row in CH_NAME_BY_KEY.items():
        if _name_matches(str(row.get("name") or ""), name) or _name_matches(
            name, str(row.get("name") or "")
        ):
            return key
    return None


CH_LEAVING_DATE_TOLERANCE_DAYS = 31


def _symbol_code(symbol: str) -> str:
    return str(symbol or "").split(".", 1)[0].upper()


def _leaving_date_consistent(leaving: Any, last_bar: date | None) -> bool:
    left = _parse_date(leaving)
    if left is None or last_bar is None:
        return False
    return abs((last_bar - left).days) <= CH_LEAVING_DATE_TOLERANCE_DAYS


def match_ch_record(
    store: Mapping[str, Any],
    *,
    symbol: str,
    name: str | None,
    last_bar: date | None,
) -> str | None:
    """The store key whose record names this listed company, or None.

    Sealed rule (UK replay registration, owner sign-off): a Companies House
    record is used only when its EPIC and leaving date are consistent with the
    EODHD symbol. Rows without an EPIC need a name match plus the leaving date.
    The seven hand-verified probe names carry neither and keep the name match.
    More than one candidate is ambiguous and matches nothing.
    """
    code = _symbol_code(symbol)
    found: set[str] = set()
    for row in store.get("names") or []:
        if not isinstance(row, Mapping) or not row.get("key"):
            continue
        key = str(row["key"])
        epic = str(row.get("epic") or "").upper()
        leaving = row.get("leaving_date")
        row_name = str(row.get("name") or "")
        named = bool(name) and (_name_matches(row_name, name) or _name_matches(name, row_name))
        if epic:
            if (code == epic or code.startswith(epic + "_")) and _leaving_date_consistent(
                leaving, last_bar
            ):
                found.add(key)
        elif leaving:
            if named and _leaving_date_consistent(leaving, last_bar):
                found.add(key)
        elif key in CH_NAME_BY_KEY and named:
            found.add(key)
    return found.pop() if len(found) == 1 else None


def gross_margin(gross_profit: float | None, revenue: float | None) -> float | None:
    if gross_profit is None or revenue is None or revenue <= 0:
        return None
    return gross_profit / revenue


def dividend_yield(
    dividends: Sequence[Mapping[str, Any]] | None,
    session: date,
    raw_close: float | None,
) -> float | None:
    """Cash dividends with an ex-date in the 365 days up to the session, over the raw close.

    No dated rows leave the yield null. Absence is not a zero yield.
    """
    if raw_close is None or raw_close <= 0:
        return None
    window = int(_const("DIVIDEND_YIELD_LOOKBACK_DAYS"))
    start = session - timedelta(days=window)
    total = 0.0
    found = False
    for row in dividends or ():
        if not isinstance(row, Mapping):
            continue
        ex = _parse_date(row.get("date") or row.get("exDate"))
        amount = finite(row.get("value") if "value" in row else row.get("amount"))
        if ex is None or amount is None or not (start < ex <= session):
            continue
        total += amount
        found = True
    if not found:
        return None
    return total / raw_close


def panel_row_from_statement(
    statement: Mapping[str, Any] | None,
    prior: Mapping[str, Any] | None,
    *,
    market_cap: float | None,
    raw_close: float | None,
    dividend: float | None,
    sector: str | None,
    shares_fallback: float | None,
) -> dict[str, Any]:
    """Sharadar-shaped panel columns. A missing field stays null. Debt and cash are not zero."""
    row: dict[str, Any] = {
        key: None
        for key in (
            "market_cap",
            "total_revenue",
            "ebit",
            "ebitda",
            "net_income",
            "interest_expense",
            "gross_margin",
            "free_cashflow",
            "operating_cashflow",
            "total_assets",
            "total_current_assets",
            "total_liabilities",
            "total_current_liabilities",
            "total_debt",
            "total_cash",
            "book_value",
            "shares_outstanding",
            "trailing_pe",
            "price_to_book",
            "enterprise_value",
            "dividend_yield",
            "current_ratio",
            "debt_to_equity",
            "return_on_equity",
            "return_on_assets",
            "profit_margins",
            "revenue_growth",
            "earnings_growth",
            "ncav",
            "last_price",
            "return_on_assets_prev",
            "gross_margin_prev",
            "current_ratio_bs",
            "current_ratio_bs_prev",
            "leverage",
            "leverage_prev",
            "asset_turnover",
            "asset_turnover_prev",
            "shares_outstanding_prev",
            "total_assets_prev",
        )
    }
    row["market_cap"] = market_cap
    row["last_price"] = raw_close
    row["dividend_yield"] = dividend
    row["sector"] = sector
    if statement is None:
        row["data_quality_score"] = 0.0
        return row
    for key in (
        "total_revenue",
        "ebit",
        "ebitda",
        "net_income",
        "interest_expense",
        "free_cashflow",
        "operating_cashflow",
        "total_assets",
        "total_current_assets",
        "total_liabilities",
        "total_current_liabilities",
        "total_debt",
        "total_cash",
        "book_value",
    ):
        if key in statement:
            row[key] = statement.get(key)
    shares = (
        statement.get("shares") if statement.get("shares") not in (None, 0) else shares_fallback
    )
    row["shares_outstanding"] = shares
    row["gross_margin"] = gross_margin(
        statement.get("gross_profit"), statement.get("total_revenue")
    )
    revenue = statement.get("total_revenue")
    net_income = statement.get("net_income")
    equity = statement.get("book_value")
    assets = statement.get("total_assets")
    if market_cap is not None and net_income is not None and net_income > 0:
        row["trailing_pe"] = market_cap / net_income
    if market_cap is not None and equity is not None and equity > 0:
        row["price_to_book"] = market_cap / equity
    debt = statement.get("total_debt")
    cash = statement.get("total_cash")
    if market_cap is not None and debt is not None and cash is not None:
        row["enterprise_value"] = market_cap + debt - cash
    current_assets = statement.get("total_current_assets")
    current_liab = statement.get("total_current_liabilities")
    if current_assets is not None and current_liab is not None and current_liab > 0:
        row["current_ratio"] = current_assets / current_liab
        row["current_ratio_bs"] = row["current_ratio"]
    if debt is not None and equity is not None and equity > 0:
        row["debt_to_equity"] = debt / equity * float(_const("DEBT_TO_EQUITY_SCALE"))
    if net_income is not None and equity is not None and equity > 0:
        row["return_on_equity"] = net_income / equity
    if net_income is not None and assets is not None and assets > 0:
        row["return_on_assets"] = net_income / assets
    if net_income is not None and revenue is not None and revenue > 0:
        row["profit_margins"] = net_income / revenue
    if current_assets is not None and statement.get("total_liabilities") is not None:
        row["ncav"] = current_assets - statement["total_liabilities"]
    if revenue is not None and assets is not None and assets > 0:
        row["asset_turnover"] = revenue / assets
    if debt is not None and assets is not None and assets > 0:
        row["leverage"] = debt / assets
    if prior is not None:
        row["revenue_growth"] = _change(revenue, prior.get("total_revenue"))
        row["earnings_growth"] = _change(net_income, prior.get("net_income"))
        prev_assets = prior.get("total_assets")
        prev_income = prior.get("net_income")
        if prev_income is not None and prev_assets is not None and prev_assets > 0:
            row["return_on_assets_prev"] = prev_income / prev_assets
        row["gross_margin_prev"] = gross_margin(
            prior.get("gross_profit"), prior.get("total_revenue")
        )
        prev_ca = prior.get("total_current_assets")
        prev_cl = prior.get("total_current_liabilities")
        if prev_ca is not None and prev_cl is not None and prev_cl > 0:
            row["current_ratio_bs_prev"] = prev_ca / prev_cl
        prev_debt = prior.get("total_debt")
        if prev_debt is not None and prev_assets is not None and prev_assets > 0:
            row["leverage_prev"] = prev_debt / prev_assets
        prev_rev = prior.get("total_revenue")
        if prev_rev is not None and prev_assets is not None and prev_assets > 0:
            row["asset_turnover_prev"] = prev_rev / prev_assets
        row["shares_outstanding_prev"] = prior.get("shares")
        row["total_assets_prev"] = prev_assets
    present = all(row.get(key) is not None for key in ("market_cap", "total_revenue", "net_income"))
    row["data_quality_score"] = 1.0 if present else 0.0
    row["data_quality_basis"] = "three_fields"
    return row


def estimate_calls(
    *,
    names: int,
    list_calls: int,
    fx_calls: int = 2,
) -> dict[str, int]:
    """Weighted calls and HTTP requests. Fundamentals weigh 10; everything else weighs 1."""
    per_name = (
        int(_const("EOD_CALL_WEIGHT"))
        + int(_const("FUNDAMENTALS_CALL_WEIGHT"))
        + int(_const("DIV_CALL_WEIGHT"))
        + int(_const("SPLIT_CALL_WEIGHT"))
    )
    weighted = (
        list_calls * int(_const("LIST_CALL_WEIGHT"))
        + names * per_name
        + fx_calls * int(_const("EOD_CALL_WEIGHT"))
    )
    http = list_calls + names * 4 + fx_calls
    return {"names": names, "weighted": weighted, "http": http, "per_name": per_name}


def lse_fetch_plan() -> dict[str, Any]:
    active = int(_const("LSE_ACTIVE_MEASURED"))
    delisted = int(_const("LSE_DELISTED_MEASURED"))
    plan = estimate_calls(names=active + delisted, list_calls=2, fx_calls=2)
    cap = int(_const("DAILY_CALL_BUDGET_SOFT_CAP"))
    plan.update(
        {
            "market": "LSE",
            "active": active,
            "delisted": delisted,
            "soft_cap": cap,
            "headroom": cap - plan["weighted"],
            "sealed_total": int(_const("LSE_WEIGHTED_CALLS")),
        }
    )
    return plan


def europe_name_cap() -> int:
    """Names one UTC day can hold after four list calls and two FX calls."""
    cap = int(_const("DAILY_CALL_BUDGET_SOFT_CAP"))
    overhead = 4 * int(_const("LIST_CALL_WEIGHT")) + 2 * int(_const("EOD_CALL_WEIGHT"))
    per_name = estimate_calls(names=1, list_calls=0, fx_calls=0)["per_name"]
    return (cap - overhead) // per_name


def issuer_key(symbol: str, isin: str | None) -> str:
    if isin and str(isin).strip():
        return str(isin).strip().upper()
    return symbol.split(".", 1)[0].upper()


def drop_overlap(
    members: Mapping[str, set[str]],
    issuers: Mapping[str, str],
) -> tuple[dict[str, set[str]], int]:
    """A name in ftse350 and another market that session stays ftse350 only."""
    home = {issuers.get(symbol, symbol) for symbol in members.get("ftse350", set())}
    out = {market: set(symbols) for market, symbols in members.items()}
    dropped = 0
    for market, symbols in list(out.items()):
        if market == "ftse350":
            continue
        keep = set()
        for symbol in symbols:
            if issuers.get(symbol, symbol) in home:
                dropped += 1
            else:
                keep.add(symbol)
        out[market] = keep
    return out, dropped


def scaled_high_low(
    high: float | None, low: float | None, close: float | None, adjusted: float | None
) -> tuple[float | None, float | None]:
    if high is None or low is None or close is None or adjusted is None or close <= 0:
        return None, None
    factor = adjusted / close
    return high * factor, low * factor


def ch_filings_for_key(store: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    for row in store.get("names") or []:
        if isinstance(row, Mapping) and row.get("key") == key:
            filings = row.get("filings") or []
            return [item for item in filings if isinstance(item, dict)]
    return []


def bias_shares(
    universe_months: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Share of ranked name-months whose annual revenue check is not evaluable."""
    buckets = {"still_listed": [0, 0], "later_delisted": [0, 0], "list_unknown": [0, 0]}
    not_computable = []
    funds = []
    for month in universe_months:
        total = int(month.get("ranked") or 0)
        missing = int(month.get("revenue_not_evaluable") or 0)
        kind = str(month.get("list_status") or "list_unknown")
        if kind not in buckets:
            kind = "list_unknown"
        buckets[kind][0] += missing
        buckets[kind][1] += total
        considered = int(month.get("considered") or 0)
        if considered:
            not_computable.append(int(month.get("cap_not_computable") or 0) / considered)
        funds.append(int(month.get("excluded_fund_or_trust") or 0))

    def _share(pair: list[int]) -> float | None:
        return None if pair[1] == 0 else pair[0] / pair[1]

    return {
        "universe_months": sum(pair[1] for pair in buckets.values()),
        "revenue_not_evaluable_share": {key: _share(pair) for key, pair in buckets.items()},
        "mean_cap_not_computable_share": (
            None if not not_computable else sum(not_computable) / len(not_computable)
        ),
        "mean_excluded_fund_or_trust": None if not funds else sum(funds) / len(funds),
    }


def empty_panel_frame() -> pd.DataFrame:
    return pd.DataFrame()
