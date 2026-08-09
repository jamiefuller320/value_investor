"""Canonical free-cash-flow reconciliation for screening and snapshots."""

from __future__ import annotations

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

_FILING_METRIC_KEYS = (
    "operating_cashflow",
    "operating_cashflow_prev",
    "free_cashflow",
    "free_cashflow_prev",
    "net_income_adjusted",
    "net_income_adjusted_prev",
    "dividends_paid",
    "interim_eps_decline_pct",
)

_RESEARCH_ROOTS = (
    Path("docs/data/research"),
    Path("output/research"),
)

FCF_DIVERGENCE_THRESHOLD = 0.50
FCF_SIGN_DIVERGENCE_MIN_ABS = 50_000_000.0
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


def extract_cashflow_metrics_from_annual_financials(
    financials: dict[str, Any],
) -> dict[str, float | None]:
    """Extract latest (and prior-year) cash-flow metrics from ``financials_annual.json``."""
    cash_flow = financials.get("cash_flow") or {}
    if not cash_flow:
        return {}

    years = _sorted_financial_years(cash_flow)
    metrics: dict[str, float | None] = {}
    for key, labels in (
        ("operating_cashflow", _OPERATING_CASHFLOW_LABELS),
        ("free_cashflow", _FREE_CASHFLOW_LABELS),
    ):
        if years:
            metrics[key] = _annual_label_value(cash_flow.get(years[0]) or {}, labels)
        if len(years) > 1:
            metrics[f"{key}_prev"] = _annual_label_value(cash_flow.get(years[1]) or {}, labels)
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
        metrics["net_income_adjusted"] = _annual_label_value(
            income_statement.get(years[0]) or {},
            _ADJUSTED_EARNINGS_LABELS,
        )
    if len(years) > 1:
        metrics["net_income_adjusted_prev"] = _annual_label_value(
            income_statement.get(years[1]) or {},
            _ADJUSTED_EARNINGS_LABELS,
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
            if isinstance(row, dict)
            and row.get("period") == "interim"
            and row.get("has_body")
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


def extract_filing_metrics_from_annual_financials(
    financials: dict[str, Any],
) -> dict[str, float | None]:
    """Combined cash-flow and adjusted-earnings metrics from cached Yahoo annuals."""
    metrics = extract_cashflow_metrics_from_annual_financials(financials)
    metrics.update(extract_income_metrics_from_annual_financials(financials))
    metrics["dividends_paid"] = extract_dividends_paid_from_annual_financials(financials)
    return metrics


def _financials_candidates(ticker: str, output_dir: Path | None = None) -> list[Path]:
    ticker = ticker.strip().upper()
    candidates: list[Path] = []
    if output_dir is not None:
        candidates.append(Path(output_dir) / "research" / ticker / "sources" / "financials_annual.json")
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
        if isinstance(payload, dict) and (payload.get("cash_flow") or payload.get("income_statement")):
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
    ocf = _annual_label_value(year_rows, _OPERATING_CASHFLOW_LABELS)
    capex = _annual_label_value(year_rows, _CAPEX_LABELS)
    if ocf is not None and capex is not None:
        return float(ocf) + float(capex), fiscal_year

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


def parse_company_adjusted_fcf(text: str, *, default_currency: str = "GBP") -> tuple[float | None, str | None]:
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

    if not divergence_flagged and not fcf_values_diverge(canonical, screen_ttm):
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
        canonicals.append(bundle.get("canonical"))

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
        for key, value in extracted.items():
            if value is None:
                continue
            current = out.at[index, key]
            if current is None or (isinstance(current, float) and pd.isna(current)):
                out.at[index, key] = value

        interim_decline = extract_interim_eps_decline_for_ticker(ticker, output_dir=output_dir)
        if interim_decline is not None:
            current = out.at[index, "interim_eps_decline_pct"]
            if current is None or (isinstance(current, float) and pd.isna(current)):
                out.at[index, "interim_eps_decline_pct"] = interim_decline

    return out
