"""Extract balance-sheet and income-statement fields from yfinance."""

from __future__ import annotations

from typing import Any

import pandas as pd

# yfinance label variants across regions / reporting standards.
_LABEL_ALIASES: dict[str, list[str]] = {
    "total_assets": ["Total Assets"],
    "total_current_assets": ["Current Assets", "Total Current Assets"],
    "total_liabilities": ["Total Liab", "Total Liabilities"],
    "total_current_liabilities": ["Current Liabilities", "Total Current Liabilities"],
    "total_debt_bs": ["Total Debt", "Long Term Debt And Capital Lease Obligation"],
    "net_income": ["Net Income", "Net Income Common Stockholders"],
    "operating_income": ["Operating Income", "EBIT", "Operating Income Or Loss"],
    "total_revenue": ["Total Revenue", "Operating Revenue"],
    "gross_profit": ["Gross Profit"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "shares_outstanding": [
        "Ordinary Shares Number",
        "Share Issued",
        "Basic Average Shares",
    ],
}


def _row_value(frame: pd.DataFrame, labels: list[str], column_index: int = 0) -> float | None:
    if frame is None or frame.empty:
        return None
    for label in labels:
        if label in frame.index:
            try:
                val = frame.loc[label].iloc[column_index]
                if pd.notna(val):
                    return float(val)
            except (IndexError, TypeError, ValueError):
                continue
    return None


def extract_statement_metrics(
    balance_sheet: pd.DataFrame | None,
    income_stmt: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
) -> dict[str, Any]:
    """Pull latest and prior-year metrics for screening models."""
    metrics: dict[str, Any] = {}

    for key, labels in _LABEL_ALIASES.items():
        source = balance_sheet
        if key in ("net_income", "operating_income", "total_revenue", "gross_profit"):
            source = income_stmt
        elif key == "operating_cashflow":
            source = cashflow
        elif key == "interest_expense":
            source = income_stmt

        metrics[key] = _row_value(source, labels, 0)
        metrics[f"{key}_prev"] = _row_value(source, labels, 1)

    if metrics.get("total_current_assets") is not None and metrics.get("total_liabilities") is not None:
        metrics["ncav"] = metrics["total_current_assets"] - metrics["total_liabilities"]

    if metrics.get("gross_profit") is not None and metrics.get("total_revenue"):
        metrics["gross_margin"] = metrics["gross_profit"] / metrics["total_revenue"]

    if metrics.get("gross_profit_prev") is not None and metrics.get("total_revenue_prev"):
        metrics["gross_margin_prev"] = metrics["gross_profit_prev"] / metrics["total_revenue_prev"]

    if metrics.get("net_income") is not None and metrics.get("total_assets"):
        metrics["return_on_assets"] = metrics["net_income"] / metrics["total_assets"]

    if metrics.get("net_income_prev") is not None and metrics.get("total_assets_prev"):
        metrics["return_on_assets_prev"] = metrics["net_income_prev"] / metrics["total_assets_prev"]

    if metrics.get("total_current_assets") and metrics.get("total_current_liabilities"):
        metrics["current_ratio_bs"] = (
            metrics["total_current_assets"] / metrics["total_current_liabilities"]
        )

    if metrics.get("total_current_assets_prev") and metrics.get("total_current_liabilities_prev"):
        metrics["current_ratio_bs_prev"] = (
            metrics["total_current_assets_prev"] / metrics["total_current_liabilities_prev"]
        )

    if metrics.get("total_debt_bs") is not None and metrics.get("total_assets"):
        metrics["leverage"] = metrics["total_debt_bs"] / metrics["total_assets"]

    if metrics.get("total_debt_bs_prev") is not None and metrics.get("total_assets_prev"):
        metrics["leverage_prev"] = metrics["total_debt_bs_prev"] / metrics["total_assets_prev"]

    if metrics.get("total_revenue") and metrics.get("total_assets"):
        metrics["asset_turnover"] = metrics["total_revenue"] / metrics["total_assets"]

    if metrics.get("total_revenue_prev") and metrics.get("total_assets_prev"):
        metrics["asset_turnover_prev"] = metrics["total_revenue_prev"] / metrics["total_assets_prev"]

    return metrics
