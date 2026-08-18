"""Canonical free-cash-flow reconciliation for screening and snapshots."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.storage import read_json, resolve_json_path

_CAPEX_LABELS = [
    "Capital Expenditure",
    "Capital Expenditures",
    "Purchase Of PPE",
    "Purchase Of Property Plant And Equipment",
]

_OPERATING_CASHFLOW_LABELS = [
    "Operating Cash Flow",
    "Cash Flow From Continuing Operating Activities",
    "Total Cash From Operating Activities",
    "Cash from Operating Activities",
]

_FREE_CASHFLOW_LABELS = [
    "Free Cash Flow",
]

_ADJUSTED_EARNINGS_LABELS = [
    "Normalized Income",
    "Normalized Net Income",
]

_BASIC_EPS_LABELS = [
    "Basic EPS",
]

_DIVIDENDS_PAID_LABELS = [
    "Cash Dividends Paid",
    "Common Stock Dividend Paid",
]

_INTERIM_EPS_DECLINE_RES = (
    re.compile(
        r"(?:diluted|basic|adjusted)?\s*earnings per share\b.{0,200}?"
        r"(?:decline|decrease|down)\s+of\s+([\d.]+)\s*%",
        re.IGNORECASE,
    ),
    re.compile(
        r"\beps\b.{0,120}?(?:decline|decrease|down)\s+of\s+([\d.]+)\s*%",
        re.IGNORECASE,
    ),
)

_ADJUSTED_EPS_GROWTH_RES = (
    re.compile(
        r"adjusted\s+eps\s+\+?\s*([\d.]+)\s*%",
        re.IGNORECASE,
    ),
    re.compile(
        r"adjusted\s+eps\s+increased\s+by\s+([\d.]+)\s*%",
        re.IGNORECASE,
    ),
    re.compile(
        r"([\d.]+)\s*%\s+growth\s+in\s+adjusted\s+eps",
        re.IGNORECASE,
    ),
    re.compile(
        r"growth\s+in\s+adjusted\s+eps[^.\n]{0,80}?([\d.]+)\s*%",
        re.IGNORECASE,
    ),
    re.compile(
        r"adjusted\s+earnings\s+per\s+share\s+[\d.]+\s*p?\s+[\d.]+\s+p?\s+([\d.]+)\s*%",
        re.IGNORECASE,
    ),
)

_GROSS_OPERATING_CASHFLOW_RES = (
    re.compile(
        r"Cash generated\s+from operations\s+[£$€]?\s*([\d,.]+)\s*m\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"Cash generated from operations\s+[£$€]?\s*([\d,.]+)\s*m\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"Cash generated from operations\s+([\d,]+)\s+[\d,]",
        re.IGNORECASE,
    ),
)

_FILING_METRIC_KEYS = (
    "operating_cashflow",
    "operating_cashflow_gross",
    "operating_cashflow_prev",
    "free_cashflow",
    "free_cashflow_prev",
    "capital_expenditure",
    "net_income_adjusted",
    "net_income_adjusted_prev",
    "basic_eps",
    "basic_eps_prev",
    "basic_eps_growth_pct",
    "dividends_paid",
    "fcf_dividend_coverage_gross",
    "fcf_dividend_coverage_net",
    "interim_eps_decline_pct",
    "adjusted_eps_growth_pct",
)

_RESEARCH_ROOTS = (
    Path("docs/data/research"),
    Path("output/research"),
)

FCF_DIVERGENCE_THRESHOLD = 0.50
FCF_FILING_SCREEN_DIVERGENCE_THRESHOLD = 0.25
FCF_YIELD_COMPANY_TOLERANCE = 0.25
FCF_SIGN_DIVERGENCE_MIN_ABS = 50_000_000.0
FCF_YIELD_MODEL_ID = "fcf_yield"
_FX_TO_USD = {"USD": 1.0, "GBP": 1.35, "EUR": 1.10}

_COMPANY_ADJUSTED_FCF_RES = (
    re.compile(
        r"(?:group\s+)?(?:adjusted\s+)?free\s+cash\s+flow\s+of\s+([£$€]?)\s*([\d,.]+)\s*m",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Free cash flow\s+([\d,.]+)\s+[\d,.]+",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"Free Cash Flow\s+[\d.()]+\s+[\d.()]+\s+[\d.()]+\s+[\d.]+\s+([\d,.]+)\b",
        re.IGNORECASE,
    ),
)


def _sorted_financial_years(section: dict[str, Any]) -> list[str]:
    return sorted((str(year) for year in section.keys()), reverse=True)


def _annual_label_value(year_rows: dict[str, Any], labels: list[str]) -> float | None:
    for label in labels:
        value = year_rows.get(label)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if pd.notna(number):
            return number
    return None


def _filing_aligned_fcf_from_year_rows(year_rows: dict[str, Any]) -> float | None:
    """Reported-year FCF as OCF plus capital expenditure (CapEx is negative in Yahoo)."""
    ocf = _annual_label_value(year_rows, _OPERATING_CASHFLOW_LABELS)
    capex = _annual_label_value(year_rows, _CAPEX_LABELS)
    if ocf is not None and capex is not None:
        return float(ocf) + float(capex)
    return _annual_label_value(year_rows, _FREE_CASHFLOW_LABELS)


def _parse_gross_operating_amount(raw: str) -> float | None:
    try:
        amount = float(raw.replace(",", ""))
    except (TypeError, ValueError):
        return None
    if amount == 0:
        return 0.0
    # Table rows in filing bodies are often in thousands; prose uses millions.
    if amount >= 1_000_000:
        return amount
    if amount >= 1_000:
        return amount * 1_000.0
    return amount * 1_000_000.0


def parse_gross_cash_from_operations(text: str) -> float | None:
    """Parse gross cash generated from operations from filing prose or tables."""
    if not text:
        return None
    for pattern in _GROSS_OPERATING_CASHFLOW_RES:
        match = pattern.search(text)
        if not match:
            continue
        amount = _parse_gross_operating_amount(str(match.group(1)))
        if amount is not None and amount > 0:
            return amount
    return None


def extract_gross_cash_from_operations_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> float | None:
    """Return annual gross cash-from-operations when annual filing bodies expose it."""
    for body in _iter_filing_bodies(ticker, output_dir=output_dir, periods=("annual",)):
        parsed = parse_gross_cash_from_operations(body)
        if parsed is not None:
            return parsed
    return None


def fcf_dividend_coverage(
    free_cashflow: float | None,
    dividends_paid: float | None,
) -> float | None:
    """Return FCF divided by annual cash dividends when both are available."""
    if free_cashflow is None or (isinstance(free_cashflow, float) and pd.isna(free_cashflow)):
        return None
    if dividends_paid is None or (isinstance(dividends_paid, float) and pd.isna(dividends_paid)):
        return None
    dividends = abs(float(dividends_paid))
    if dividends <= 0:
        return None
    return float(free_cashflow) / dividends


def filing_aligned_fcf(
    operating_cashflow: float | None,
    capital_expenditure: float | None,
    *,
    free_cashflow: float | None = None,
) -> float | None:
    """FCF as net operating cash plus capital expenditure (CapEx is negative in Yahoo)."""
    if operating_cashflow is not None and capital_expenditure is not None:
        return float(operating_cashflow) + float(capital_expenditure)
    return free_cashflow


def compute_dual_fcf_dividend_coverage(
    *,
    operating_cashflow: float | None,
    operating_cashflow_gross: float | None,
    capital_expenditure: float | None,
    dividends_paid: float | None,
    free_cashflow: float | None = None,
) -> dict[str, float | None]:
    """Return gross- and net-OCF FCF/dividend coverage ratios from one fiscal period.

    All inputs must refer to the same annual period (annual OCF, annual capex, annual
    dividends). Never pair interim/H1 operating cash with full-year capex or dividends.
    """
    net_fcf = filing_aligned_fcf(
        operating_cashflow,
        capital_expenditure,
        free_cashflow=free_cashflow,
    )
    gross_fcf = (
        filing_aligned_fcf(operating_cashflow_gross, capital_expenditure)
        if operating_cashflow_gross is not None
        else None
    )
    return {
        "fcf_dividend_coverage_net": fcf_dividend_coverage(net_fcf, dividends_paid),
        "fcf_dividend_coverage_gross": fcf_dividend_coverage(gross_fcf, dividends_paid),
    }


def extract_cashflow_metrics_from_annual_financials(
    financials: dict[str, Any],
) -> dict[str, float | None]:
    """Extract latest (and prior-year) filing-aligned cash-flow metrics."""
    cash_flow = financials.get("cash_flow") or {}
    if not cash_flow:
        return {}

    years = _sorted_financial_years(cash_flow)
    metrics: dict[str, float | None] = {}
    if years:
        latest_rows = cash_flow.get(years[0]) or {}
        metrics["operating_cashflow"] = _annual_label_value(latest_rows, _OPERATING_CASHFLOW_LABELS)
        metrics["capital_expenditure"] = _annual_label_value(latest_rows, _CAPEX_LABELS)
        metrics["free_cashflow"] = _filing_aligned_fcf_from_year_rows(latest_rows)
    if len(years) > 1:
        prior_rows = cash_flow.get(years[1]) or {}
        metrics["operating_cashflow_prev"] = _annual_label_value(
            prior_rows, _OPERATING_CASHFLOW_LABELS
        )
        metrics["free_cashflow_prev"] = _filing_aligned_fcf_from_year_rows(prior_rows)
    return metrics


def extract_income_metrics_from_annual_financials(
    financials: dict[str, Any],
) -> dict[str, float | None]:
    """Extract latest (and prior-year) adjusted earnings from ``financials_annual.json``."""
    income_statement = financials.get("income_statement") or {}
    if not income_statement:
        return {}

    years = _sorted_financial_years(income_statement)
    metrics: dict[str, float | None] = {}
    if years:
        latest_rows = income_statement.get(years[0]) or {}
        metrics["net_income_adjusted"] = _annual_label_value(latest_rows, _ADJUSTED_EARNINGS_LABELS)
        metrics["basic_eps"] = _annual_label_value(latest_rows, _BASIC_EPS_LABELS)
    if len(years) > 1:
        prior_rows = income_statement.get(years[1]) or {}
        metrics["net_income_adjusted_prev"] = _annual_label_value(
            prior_rows, _ADJUSTED_EARNINGS_LABELS
        )
        metrics["basic_eps_prev"] = _annual_label_value(prior_rows, _BASIC_EPS_LABELS)
    metrics["basic_eps_growth_pct"] = compute_yoy_growth_rate(
        metrics.get("basic_eps"),
        metrics.get("basic_eps_prev"),
    )
    return metrics


def extract_dividends_paid_from_annual_financials(
    financials: dict[str, Any],
) -> float | None:
    """Latest annual cash dividends paid (absolute value) from ``financials_annual.json``."""
    cash_flow = financials.get("cash_flow") or {}
    if not cash_flow:
        return None
    years = _sorted_financial_years(cash_flow)
    if not years:
        return None
    paid = _annual_label_value(cash_flow.get(years[0]) or {}, _DIVIDENDS_PAID_LABELS)
    if paid is None:
        return None
    return abs(float(paid))


def parse_interim_eps_decline_pct(text: str) -> float | None:
    """Return positive decline fraction (e.g. 0.039 for 3.9%) from interim filing prose."""
    if not text:
        return None
    for pattern in _INTERIM_EPS_DECLINE_RES:
        match = pattern.search(text)
        if not match:
            continue
        try:
            pct = float(match.group(1)) / 100.0
        except (TypeError, ValueError):
            continue
        if pct > 0:
            return pct
    return None


def parse_adjusted_eps_growth_pct(text: str) -> float | None:
    """Return signed growth fraction (e.g. 0.16 for +16%) from filing adjusted-EPS prose."""
    if not text:
        return None
    for pattern in _ADJUSTED_EPS_GROWTH_RES:
        match = pattern.search(text)
        if not match:
            continue
        try:
            pct = float(match.group(1)) / 100.0
        except (TypeError, ValueError):
            continue
        if pct != 0:
            return pct
    return None


def compute_yoy_growth_rate(current: float | None, previous: float | None) -> float | None:
    """Year-on-year growth rate when both values are available and prior is non-zero."""
    if current is None or previous is None:
        return None
    if isinstance(current, float) and pd.isna(current):
        return None
    if isinstance(previous, float) and pd.isna(previous):
        return None
    prev = float(previous)
    if prev == 0:
        return None
    return (float(current) - prev) / abs(prev)


def earnings_growth_signs_diverge(
    statutory_growth: float | None,
    adjusted_growth: float | None,
) -> bool:
    """True when Yahoo statutory and filing-adjusted growth rates differ in sign."""
    if statutory_growth is None or adjusted_growth is None:
        return False
    if isinstance(statutory_growth, float) and pd.isna(statutory_growth):
        return False
    if isinstance(adjusted_growth, float) and pd.isna(adjusted_growth):
        return False
    statutory = float(statutory_growth)
    adjusted = float(adjusted_growth)
    if statutory == 0 or adjusted == 0:
        return False
    return (statutory > 0) != (adjusted > 0)


def _filings_index_candidates(ticker: str, output_dir: Path | None = None) -> list[Path]:
    ticker = ticker.strip().upper()
    candidates: list[Path] = []
    if output_dir is not None:
        candidates.append(
            Path(output_dir) / "research" / ticker / "sources" / "filings" / "filings_index.json"
        )
    for root in _RESEARCH_ROOTS:
        candidates.append(root / ticker / "sources" / "filings" / "filings_index.json")
    return candidates


def _resolve_filing_body_path(body_path: str | None) -> Path | None:
    if not body_path:
        return None
    path = Path(body_path)
    if path.is_file():
        return path
    resolved = resolve_json_path(path)
    if resolved is not None and resolved.is_file():
        return resolved
    return None


def load_latest_interim_filing_body(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> str | None:
    """Load text from the newest indexed interim filing body when available."""
    for index_path in _filings_index_candidates(ticker, output_dir):
        resolved = resolve_json_path(index_path)
        if resolved is None:
            continue
        try:
            payload = read_json(resolved)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue

        interim_rows = [
            row
            for row in payload.get("filings") or []
            if isinstance(row, dict) and row.get("period") == "interim" and row.get("has_body")
        ]
        if not interim_rows:
            continue

        interim_rows.sort(
            key=lambda row: str(row.get("published_at") or ""),
            reverse=True,
        )
        for row in interim_rows:
            body_path = _resolve_filing_body_path(row.get("body_path"))
            if body_path is None:
                continue
            try:
                return body_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return None


def extract_interim_eps_decline_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> float | None:
    """Parse interim diluted-EPS decline from cached filing bodies."""
    body = load_latest_interim_filing_body(ticker, output_dir=output_dir)
    if not body:
        return None
    return parse_interim_eps_decline_pct(body)


def _iter_filing_bodies(
    ticker: str,
    *,
    output_dir: Path | None = None,
    periods: tuple[str, ...] = ("annual", "interim"),
) -> list[str]:
    """Load filing body text for ``periods`` in reverse published_at order."""
    bodies: list[str] = []
    for index_path in _filings_index_candidates(ticker, output_dir):
        resolved = resolve_json_path(index_path)
        if resolved is None:
            continue
        try:
            payload = read_json(resolved)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue

        rows = [
            row
            for row in payload.get("filings") or []
            if isinstance(row, dict) and row.get("period") in periods and row.get("has_body")
        ]
        if not rows:
            continue

        rows.sort(
            key=lambda row: str(row.get("published_at") or ""),
            reverse=True,
        )
        for row in rows:
            body_path = _resolve_filing_body_path(row.get("body_path"))
            if body_path is None:
                continue
            try:
                bodies.append(body_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        if bodies:
            break
    return bodies


def extract_adjusted_eps_growth_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
    financials: dict[str, Any] | None = None,
) -> float | None:
    """Parse adjusted-EPS growth from filing bodies, falling back to normalized income YoY."""
    for body in _iter_filing_bodies(ticker, output_dir=output_dir):
        parsed = parse_adjusted_eps_growth_pct(body)
        if parsed is not None:
            return parsed

    payload = (
        financials
        if financials is not None
        else load_cached_financials(ticker, output_dir=output_dir)
    )
    if not payload:
        return None
    income_metrics = extract_income_metrics_from_annual_financials(payload)
    return compute_yoy_growth_rate(
        income_metrics.get("net_income_adjusted"),
        income_metrics.get("net_income_adjusted_prev"),
    )


def extract_filing_metrics_from_annual_financials(
    financials: dict[str, Any],
) -> dict[str, float | None]:
    """Combined cash-flow and adjusted-earnings metrics from cached Yahoo annuals."""
    metrics = extract_cashflow_metrics_from_annual_financials(financials)
    metrics.update(extract_income_metrics_from_annual_financials(financials))
    metrics["dividends_paid"] = extract_dividends_paid_from_annual_financials(financials)
    metrics.update(
        compute_dual_fcf_dividend_coverage(
            operating_cashflow=metrics.get("operating_cashflow"),
            operating_cashflow_gross=metrics.get("operating_cashflow_gross"),
            capital_expenditure=metrics.get("capital_expenditure"),
            dividends_paid=metrics.get("dividends_paid"),
            free_cashflow=metrics.get("free_cashflow"),
        )
    )
    return metrics


def _financials_candidates(ticker: str, output_dir: Path | None = None) -> list[Path]:
    ticker = ticker.strip().upper()
    candidates: list[Path] = []
    if output_dir is not None:
        candidates.append(
            Path(output_dir) / "research" / ticker / "sources" / "financials_annual.json"
        )
    for root in _RESEARCH_ROOTS:
        candidates.append(root / ticker / "sources" / "financials_annual.json")
    return candidates


def load_cached_financials(ticker: str, *, output_dir: Path | None = None) -> dict[str, Any] | None:
    """Load ``financials_annual.json`` from committed research stores when present."""
    for path in _financials_candidates(ticker, output_dir):
        resolved = resolve_json_path(path)
        if resolved is None:
            continue
        try:
            payload = read_json(resolved)
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(payload, dict) and (
            payload.get("cash_flow") or payload.get("income_statement")
        ):
            return payload
    return None


def compute_filing_aligned_fcf(financials: dict[str, Any]) -> tuple[float | None, str | None]:
    """Latest reported-year FCF as OCF plus capital expenditure (CapEx is negative in Yahoo)."""
    cash_flow = financials.get("cash_flow") or {}
    if not cash_flow:
        return None, None

    years = _sorted_financial_years(cash_flow)
    if not years:
        return None, None

    fiscal_year = years[0]
    year_rows = cash_flow.get(fiscal_year) or {}
    aligned = _filing_aligned_fcf_from_year_rows(year_rows)
    if aligned is not None:
        return aligned, fiscal_year

    metrics = extract_cashflow_metrics_from_annual_financials(financials)
    fallback = metrics.get("free_cashflow")
    if fallback is not None:
        return float(fallback), fiscal_year
    return None, None


def _currency_symbol_to_code(symbol: str) -> str:
    if symbol == "£":
        return "GBP"
    if symbol in ("$", ""):
        return "USD"
    if symbol == "€":
        return "EUR"
    return "USD"


def _ticker_reporting_currency(ticker: str) -> str:
    return "GBP" if ticker.strip().upper().endswith(".L") else "USD"


def _normalize_fcf_to_usd(value: float, currency: str | None) -> float:
    code = (currency or "USD").upper()
    rate = _FX_TO_USD.get(code, 1.0)
    return float(value) * rate


def _parse_company_adjusted_amount(raw: str) -> float | None:
    try:
        amount = float(raw.replace(",", ""))
    except (TypeError, ValueError):
        return None
    if amount == 0:
        return 0.0
    return amount * 1_000_000.0


def parse_company_adjusted_fcf(
    text: str, *, default_currency: str = "GBP"
) -> tuple[float | None, str | None]:
    """Parse management adjusted FCF (absolute value) and currency from filing prose."""
    if not text:
        return None, None

    for pattern in _COMPANY_ADJUSTED_FCF_RES:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groups()
        if len(groups) == 2:
            currency = _currency_symbol_to_code(str(groups[0] or "")) or default_currency
            amount = _parse_company_adjusted_amount(str(groups[1]))
        else:
            currency = default_currency
            amount = _parse_company_adjusted_amount(str(groups[0]))
        if amount is not None:
            return amount, currency
    return None, None


def load_filing_bodies_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> list[str]:
    """Load all cached filing body texts for ``ticker`` when indexed."""
    bodies: list[str] = []
    for index_path in _filings_index_candidates(ticker, output_dir):
        resolved = resolve_json_path(index_path)
        if resolved is None:
            continue
        try:
            payload = read_json(resolved)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue

        for row in payload.get("filings") or []:
            if not isinstance(row, dict) or not row.get("has_body"):
                continue
            body_path = _resolve_filing_body_path(row.get("body_path"))
            if body_path is None:
                continue
            try:
                body = body_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if body.strip():
                bodies.append(body)
    return bodies


def extract_company_adjusted_fcf_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> tuple[float | None, str | None]:
    """Return company-adjusted FCF from IR/filing bodies when prose exposes it."""
    default_currency = _ticker_reporting_currency(ticker)
    for body in load_filing_bodies_for_ticker(ticker, output_dir=output_dir):
        amount, currency = parse_company_adjusted_fcf(body, default_currency=default_currency)
        if amount is not None:
            return amount, currency or default_currency
    return None, None


def fcf_basis_values_diverge(
    left: float | None,
    right: float | None,
    *,
    left_currency: str | None = None,
    right_currency: str | None = None,
    threshold: float = FCF_DIVERGENCE_THRESHOLD,
    sign_min_abs: float = FCF_SIGN_DIVERGENCE_MIN_ABS,
) -> bool:
    """True when two FCF bases differ by >50% or >$50m/£50m after USD normalisation."""
    if left is None or right is None:
        return False
    left_usd = _normalize_fcf_to_usd(float(left), left_currency)
    right_usd = _normalize_fcf_to_usd(float(right), right_currency)
    return fcf_values_diverge(
        left_usd,
        right_usd,
        threshold=threshold,
        sign_min_abs=sign_min_abs,
    )


def fcf_basis_divergence_flagged(
    *,
    filing_aligned: float | None,
    screen_ttm: float | None,
    company_adjusted: float | None,
    filing_currency: str = "USD",
    company_adjusted_currency: str | None = None,
) -> bool:
    """Auto-flag when any available FCF basis pair exceeds divergence thresholds."""
    pairs: list[tuple[float | None, str | None, float | None, str | None]] = [
        (filing_aligned, filing_currency, screen_ttm, filing_currency),
        (filing_aligned, filing_currency, company_adjusted, company_adjusted_currency),
        (screen_ttm, filing_currency, company_adjusted, company_adjusted_currency),
    ]
    return any(
        fcf_basis_values_diverge(a, b, left_currency=curr_a, right_currency=curr_b)
        for a, curr_a, b, curr_b in pairs
    )


def fcf_within_company_tolerance(
    canonical: float | None,
    company_adjusted: float | None,
    *,
    filing_currency: str = "USD",
    company_adjusted_currency: str | None = None,
    threshold: float = FCF_YIELD_COMPANY_TOLERANCE,
) -> bool:
    """True when canonical FCF is within ``threshold`` of the company filing definition."""
    if canonical is None or company_adjusted is None:
        return False
    left_usd = _normalize_fcf_to_usd(float(canonical), filing_currency)
    right_usd = _normalize_fcf_to_usd(float(company_adjusted), company_adjusted_currency)
    if left_usd == right_usd:
        return True
    abs_gap = abs(left_usd - right_usd)
    denominator = max(abs(left_usd), abs(right_usd))
    if denominator == 0:
        return False
    return abs_gap / denominator <= threshold


def fcf_yield_pass_suppressed(
    *,
    divergence_flagged: bool,
    canonical: float | None,
    company_adjusted: float | None,
    company_adjusted_currency: str | None = None,
    filing_currency: str = "USD",
) -> bool:
    """True when FCF Yield pass should be suppressed due to basis divergence."""
    if not divergence_flagged or company_adjusted is None:
        return False
    return not fcf_within_company_tolerance(
        canonical,
        company_adjusted,
        filing_currency=filing_currency,
        company_adjusted_currency=company_adjusted_currency,
    )


def _append_failed_criterion(existing: Any, message: str) -> list[str]:
    if isinstance(existing, list):
        failed = [str(item) for item in existing]
    elif isinstance(existing, str) and existing.strip():
        try:
            parsed = ast.literal_eval(existing)
            failed = [str(item) for item in parsed] if isinstance(parsed, list) else []
        except (SyntaxError, ValueError):
            failed = [existing]
    else:
        failed = []
    if message not in failed:
        failed.append(message)
    return failed


def suppress_fcf_yield_passes(
    model_results: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Flip FCF Yield passes to fail when divergence exceeds company filing tolerance."""
    if model_results.empty or universe.empty:
        return model_results

    out = model_results.copy()
    for _, urow in universe.iterrows():
        ticker = str(urow["ticker"])
        screen_ttm = screen_ttm_from_row(urow)
        bundle = reconcile_fcf_for_ticker(
            ticker,
            screen_ttm=screen_ttm,
            output_dir=output_dir,
        )
        if not fcf_yield_pass_suppressed(
            divergence_flagged=bool(bundle.get("divergence_flagged")),
            canonical=bundle.get("canonical"),
            company_adjusted=bundle.get("company_adjusted"),
            company_adjusted_currency=bundle.get("company_adjusted_currency"),
            filing_currency=str(bundle.get("currency") or "USD"),
        ):
            continue

        mask = (
            (out["ticker"] == ticker)
            & (out["model_id"] == FCF_YIELD_MODEL_ID)
            & (out["passed"] == True)  # noqa: E712
        )
        if not mask.any():
            continue
        out.loc[mask, "passed"] = False
        for index in out.index[mask]:
            out.at[index, "failed_criteria"] = _append_failed_criterion(
                out.at[index, "failed_criteria"],
                "FCF yield suppressed: canonical basis diverges from company filing definition",
            )
    return out


def resolve_statutory_earnings_growth(row: pd.Series) -> float | None:
    """Prefer filing basic-EPS YoY growth over Yahoo statutory earnings growth."""
    basic = row.get("basic_eps_growth_pct")
    if basic is not None and not (isinstance(basic, float) and pd.isna(basic)):
        return float(basic)
    statutory = row.get("earnings_growth")
    if statutory is None or (isinstance(statutory, float) and pd.isna(statutory)):
        return None
    return float(statutory)


def reconcile_fcf(
    *,
    screen_ttm: float | None,
    financials: dict[str, Any] | None = None,
    company_adjusted: float | None = None,
    company_adjusted_currency: str | None = None,
) -> dict[str, Any]:
    """
    Pick one canonical FCF from screen TTM, ``cashflow_metrics.free_cashflow``, and OCF−CapEx.

    Priority: filing-aligned OCF−CapEx, then annual ``Free Cash Flow`` line, then screen TTM.
    Also surfaces screen TTM and company-adjusted FCF side-by-side with a divergence flag.
    """
    cashflow_metrics = (
        extract_cashflow_metrics_from_annual_financials(financials) if financials else {}
    )
    filing_aligned, fiscal_year = (
        compute_filing_aligned_fcf(financials) if financials else (None, None)
    )
    metrics_fcf = cashflow_metrics.get("free_cashflow")
    metrics_fcf = float(metrics_fcf) if metrics_fcf is not None else None
    filing_currency = "USD"

    if filing_aligned is not None:
        canonical = filing_aligned
        source = "filing_aligned_ocf_capex"
    elif metrics_fcf is not None:
        canonical = metrics_fcf
        source = "cashflow_metrics"
    elif screen_ttm is not None:
        canonical = float(screen_ttm)
        source = "screen_ttm"
    else:
        canonical = None
        source = "none"

    divergence_flagged = fcf_basis_divergence_flagged(
        filing_aligned=filing_aligned,
        screen_ttm=screen_ttm,
        company_adjusted=company_adjusted,
        filing_currency=filing_currency,
        company_adjusted_currency=company_adjusted_currency,
    )

    snapshot_metrics = (
        {key: value for key, value in cashflow_metrics.items() if value is not None}
        if cashflow_metrics
        else None
    )

    return {
        "canonical": canonical,
        "source": source,
        "screen_ttm": screen_ttm,
        "cashflow_metrics_free_cashflow": metrics_fcf,
        "filing_aligned": filing_aligned,
        "company_adjusted": company_adjusted,
        "company_adjusted_currency": company_adjusted_currency,
        "divergence_flagged": divergence_flagged,
        "fiscal_year": fiscal_year,
        "currency": filing_currency,
        "cashflow_metrics": snapshot_metrics,
    }


def reconcile_fcf_for_ticker(
    ticker: str,
    *,
    screen_ttm: float | None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    financials = load_cached_financials(ticker, output_dir=output_dir)
    company_adjusted, company_adjusted_currency = extract_company_adjusted_fcf_for_ticker(
        ticker,
        output_dir=output_dir,
    )
    return reconcile_fcf(
        screen_ttm=screen_ttm,
        financials=financials,
        company_adjusted=company_adjusted,
        company_adjusted_currency=company_adjusted_currency,
    )


def _float_or_none(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def screen_ttm_from_row(row: pd.Series) -> float | None:
    """Yahoo trailing FCF preserved before canonical enrichment."""
    preserved = _float_or_none(row.get("free_cashflow_screen_ttm"))
    if preserved is not None:
        return preserved
    return _float_or_none(row.get("free_cashflow"))


def resolve_free_cashflow(row: pd.Series) -> float | None:
    """Canonical FCF for overlays and key metrics."""
    return _float_or_none(row.get("free_cashflow"))


def _fcf_sign(value: float) -> int:
    if value < 0:
        return -1
    if value > 0:
        return 1
    return 0


def fcf_values_diverge(
    canonical: float | None,
    screen_ttm: float | None,
    *,
    threshold: float = FCF_DIVERGENCE_THRESHOLD,
    sign_min_abs: float = FCF_SIGN_DIVERGENCE_MIN_ABS,
) -> bool:
    """True when signs differ by more than ``sign_min_abs``, or same-sign gap exceeds ``threshold``."""
    if canonical is None or screen_ttm is None:
        return False
    if canonical == screen_ttm:
        return False
    abs_gap = abs(canonical - screen_ttm)
    if _fcf_sign(canonical) != _fcf_sign(screen_ttm):
        return abs_gap > sign_min_abs
    denominator = max(abs(canonical), abs(screen_ttm))
    if denominator == 0:
        return False
    return abs_gap / denominator > threshold


def fcf_filing_screen_mismatch(
    *,
    filing_aligned: float | None,
    screen_ttm: float | None,
    divergence_flagged: bool = False,
    threshold: float = FCF_FILING_SCREEN_DIVERGENCE_THRESHOLD,
) -> bool:
    """True when FCF Yield, Earnings Quality, and overlays should ignore Yahoo screen TTM."""
    if divergence_flagged:
        return True
    if filing_aligned is None or screen_ttm is None:
        return False
    return fcf_values_diverge(filing_aligned, screen_ttm, threshold=threshold)


def overlay_free_cashflow_from_bundle(
    row: pd.Series,
    fcf_bundle: dict[str, Any],
) -> float | None:
    """Pick filing-aligned or screen TTM FCF for yield, quality, and overlay inputs."""
    screen_ttm = screen_ttm_from_row(row)
    filing_aligned = fcf_bundle.get("filing_aligned")
    if isinstance(filing_aligned, (int, float)):
        filing_aligned = float(filing_aligned)
    else:
        filing_aligned = None

    if fcf_filing_screen_mismatch(
        filing_aligned=filing_aligned,
        screen_ttm=screen_ttm,
        divergence_flagged=bool(fcf_bundle.get("divergence_flagged")),
    ):
        canonical = fcf_bundle.get("canonical")
        if canonical is not None:
            return float(canonical)
        if filing_aligned is not None:
            return filing_aligned

    if screen_ttm is not None:
        return screen_ttm
    return resolve_free_cashflow(row)


def _format_fcf_compact(value: float, *, currency: str = "USD") -> str:
    sign = "−" if value < 0 else ""
    abs_val = abs(value)
    symbol = {"GBP": "£", "EUR": "€"}.get(currency.upper(), "$")
    if abs_val >= 1_000_000:
        scaled = abs_val / 1_000_000
        if scaled == int(scaled):
            return f"{sign}{symbol}{int(scaled)}M"
        return f"{sign}{symbol}{scaled:.1f}M"
    if abs_val >= 1_000:
        scaled = abs_val / 1_000
        if scaled == int(scaled):
            return f"{sign}{symbol}{int(scaled)}K"
        return f"{sign}{symbol}{scaled:.1f}K"
    if abs_val == int(abs_val):
        return f"{sign}{symbol}{int(abs_val)}"
    return f"{sign}{symbol}{abs_val:.1f}"


def format_fcf_basis_action_note(
    *,
    filing_aligned: float | None,
    screen_ttm: float | None,
    company_adjusted: float | None = None,
    filing_currency: str = "USD",
    company_adjusted_currency: str | None = None,
) -> str:
    """Surface filing-aligned, screen TTM, and company-adjusted FCF side-by-side."""
    parts: list[str] = []
    if filing_aligned is not None:
        parts.append(f"filing {_format_fcf_compact(filing_aligned, currency=filing_currency)}")
    if screen_ttm is not None:
        parts.append(f"screen TTM {_format_fcf_compact(screen_ttm, currency=filing_currency)}")
    if company_adjusted is not None:
        parts.append(
            "company-adj "
            f"{_format_fcf_compact(company_adjusted, currency=company_adjusted_currency or 'GBP')}"
        )
    return "FCF basis mismatch: " + " | ".join(parts)


def format_fcf_divergence_action_note(
    canonical: float,
    screen_ttm: float,
    *,
    filing_currency: str = "USD",
) -> str:
    """Surface both FCF figures when filing-aligned and screen TTM disagree."""
    return (
        f"FCF filing-aligned {_format_fcf_compact(canonical, currency=filing_currency)} "
        f"vs screen TTM {_format_fcf_compact(screen_ttm, currency=filing_currency)}"
    )


def append_fcf_divergence_to_action_note(
    action_note: str,
    *,
    canonical: float | None,
    screen_ttm: float | None,
    fcf_bundle: dict[str, Any] | None = None,
) -> str:
    """Append a compact FCF bridge note when FCF bases diverge beyond thresholds."""
    bundle = fcf_bundle or {}
    filing_aligned = bundle.get("filing_aligned", canonical)
    company_adjusted = bundle.get("company_adjusted")
    company_adjusted_currency = bundle.get("company_adjusted_currency")
    filing_currency = str(bundle.get("currency") or "USD")
    divergence_flagged = bool(bundle.get("divergence_flagged"))
    filing_for_mismatch = filing_aligned if filing_aligned is not None else canonical

    if not fcf_filing_screen_mismatch(
        filing_aligned=filing_for_mismatch,
        screen_ttm=screen_ttm,
        divergence_flagged=divergence_flagged,
    ):
        return action_note

    if company_adjusted is not None or divergence_flagged:
        divergence_note = format_fcf_basis_action_note(
            filing_aligned=filing_aligned if filing_aligned is not None else canonical,
            screen_ttm=screen_ttm,
            company_adjusted=company_adjusted,
            filing_currency=filing_currency,
            company_adjusted_currency=company_adjusted_currency,
        )
    else:
        assert canonical is not None and screen_ttm is not None
        divergence_note = format_fcf_divergence_action_note(
            canonical,
            screen_ttm,
            filing_currency=filing_currency,
        )

    if action_note and divergence_note in action_note:
        return action_note
    if action_note:
        return f"{action_note} | {divergence_note}"
    return divergence_note


def enrich_universe_with_canonical_fcf(
    universe: pd.DataFrame,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Replace ``free_cashflow`` with filing-aligned canonical values when research caches exist."""
    if universe.empty or "free_cashflow" not in universe.columns:
        return universe

    out = universe.copy()
    screen_ttms: list[float | None] = []
    canonicals: list[float | None] = []

    for _, row in out.iterrows():
        screen_ttm = _float_or_none(row.get("free_cashflow"))
        bundle = reconcile_fcf_for_ticker(
            str(row["ticker"]),
            screen_ttm=screen_ttm,
            output_dir=output_dir,
        )
        screen_ttms.append(screen_ttm)
        if fcf_filing_screen_mismatch(
            filing_aligned=bundle.get("filing_aligned"),
            screen_ttm=screen_ttm,
            divergence_flagged=bool(bundle.get("divergence_flagged")),
        ):
            canonicals.append(bundle.get("canonical"))
        else:
            canonicals.append(screen_ttm)

    out["free_cashflow_screen_ttm"] = screen_ttms
    out["free_cashflow"] = [
        canonical if canonical is not None else screen
        for canonical, screen in zip(canonicals, screen_ttms, strict=True)
    ]
    return out


def enrich_universe_with_filing_metrics(
    universe: pd.DataFrame,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Fill missing cash-flow and adjusted-earnings fields from cached ``financials_annual.json``."""
    if universe.empty:
        return universe

    out = universe.copy()
    for key in _FILING_METRIC_KEYS:
        if key not in out.columns:
            out[key] = None

    for index, row in out.iterrows():
        ticker = str(row["ticker"])
        financials = load_cached_financials(ticker, output_dir=output_dir)
        if not financials:
            continue

        extracted = extract_filing_metrics_from_annual_financials(financials)
        gross_ocf = extract_gross_cash_from_operations_for_ticker(ticker, output_dir=output_dir)
        if gross_ocf is not None:
            extracted["operating_cashflow_gross"] = gross_ocf
            out.at[index, "operating_cashflow_gross"] = gross_ocf

        for key, value in extracted.items():
            if value is None:
                continue
            current = out.at[index, key]
            if current is None or (isinstance(current, float) and pd.isna(current)):
                out.at[index, key] = value

        coverage = compute_dual_fcf_dividend_coverage(
            operating_cashflow=_float_or_none(out.at[index, "operating_cashflow"]),
            operating_cashflow_gross=_float_or_none(out.at[index, "operating_cashflow_gross"]),
            capital_expenditure=_float_or_none(out.at[index, "capital_expenditure"]),
            dividends_paid=_float_or_none(out.at[index, "dividends_paid"]),
            free_cashflow=_float_or_none(out.at[index, "free_cashflow"]),
        )
        for key, value in coverage.items():
            if value is not None:
                out.at[index, key] = value

        interim_decline = extract_interim_eps_decline_for_ticker(ticker, output_dir=output_dir)
        if interim_decline is not None:
            current = out.at[index, "interim_eps_decline_pct"]
            if current is None or (isinstance(current, float) and pd.isna(current)):
                out.at[index, "interim_eps_decline_pct"] = interim_decline

        adjusted_growth = extract_adjusted_eps_growth_for_ticker(
            ticker,
            output_dir=output_dir,
            financials=financials,
        )
        if adjusted_growth is not None:
            current = out.at[index, "adjusted_eps_growth_pct"]
            if current is None or (isinstance(current, float) and pd.isna(current)):
                out.at[index, "adjusted_eps_growth_pct"] = adjusted_growth

    return out
