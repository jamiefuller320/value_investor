"""Canonical free-cash-flow reconciliation for screening and snapshots."""

from __future__ import annotations

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

_FILING_METRIC_KEYS = (
    "operating_cashflow",
    "operating_cashflow_prev",
    "free_cashflow",
    "free_cashflow_prev",
    "net_income_adjusted",
    "net_income_adjusted_prev",
)

_RESEARCH_ROOTS = (
    Path("docs/data/research"),
    Path("output/research"),
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


def extract_filing_metrics_from_annual_financials(
    financials: dict[str, Any],
) -> dict[str, float | None]:
    """Combined cash-flow and adjusted-earnings metrics from cached Yahoo annuals."""
    metrics = extract_cashflow_metrics_from_annual_financials(financials)
    metrics.update(extract_income_metrics_from_annual_financials(financials))
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


def reconcile_fcf(
    *,
    screen_ttm: float | None,
    financials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Pick one canonical FCF from screen TTM, ``cashflow_metrics.free_cashflow``, and OCF−CapEx.

    Priority: filing-aligned OCF−CapEx, then annual ``Free Cash Flow`` line, then screen TTM.
    """
    cashflow_metrics = (
        extract_cashflow_metrics_from_annual_financials(financials) if financials else {}
    )
    filing_aligned, fiscal_year = (
        compute_filing_aligned_fcf(financials) if financials else (None, None)
    )
    metrics_fcf = cashflow_metrics.get("free_cashflow")
    metrics_fcf = float(metrics_fcf) if metrics_fcf is not None else None

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
        "fiscal_year": fiscal_year,
        "currency": "USD",
        "cashflow_metrics": snapshot_metrics,
    }


def reconcile_fcf_for_ticker(
    ticker: str,
    *,
    screen_ttm: float | None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    financials = load_cached_financials(ticker, output_dir=output_dir)
    return reconcile_fcf(screen_ttm=screen_ttm, financials=financials)


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


FCF_DIVERGENCE_THRESHOLD = 0.25


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
) -> bool:
    """True when sign differs or relative magnitude gap exceeds ``threshold``."""
    if canonical is None or screen_ttm is None:
        return False
    if canonical == screen_ttm:
        return False
    if _fcf_sign(canonical) != _fcf_sign(screen_ttm):
        return True
    denominator = max(abs(canonical), abs(screen_ttm))
    if denominator == 0:
        return False
    return abs(canonical - screen_ttm) / denominator > threshold


def _format_fcf_compact(value: float) -> str:
    sign = "−" if value < 0 else ""
    abs_val = abs(value)
    if abs_val >= 1_000_000:
        scaled = abs_val / 1_000_000
        if scaled == int(scaled):
            return f"{sign}${int(scaled)}M"
        return f"{sign}${scaled:.1f}M"
    if abs_val >= 1_000:
        scaled = abs_val / 1_000
        if scaled == int(scaled):
            return f"{sign}${int(scaled)}K"
        return f"{sign}${scaled:.1f}K"
    if abs_val == int(abs_val):
        return f"{sign}${int(abs_val)}"
    return f"{sign}${abs_val:.1f}"


def format_fcf_divergence_action_note(
    canonical: float,
    screen_ttm: float,
) -> str:
    """Surface both FCF figures when filing-aligned and screen TTM disagree."""
    return (
        f"FCF filing-aligned {_format_fcf_compact(canonical)} "
        f"vs screen TTM {_format_fcf_compact(screen_ttm)}"
    )


def append_fcf_divergence_to_action_note(
    action_note: str,
    *,
    canonical: float | None,
    screen_ttm: float | None,
) -> str:
    """Append a compact FCF bridge note when canonical and screen TTM diverge."""
    if not fcf_values_diverge(canonical, screen_ttm):
        return action_note
    assert canonical is not None and screen_ttm is not None
    divergence_note = format_fcf_divergence_action_note(canonical, screen_ttm)
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

    return out
