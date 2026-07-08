"""Build per-company reason summaries from screening output."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

import pandas as pd

SIGNAL_LABELS = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "hold": "Hold",
    "avoid": "Avoid",
    "insufficient_data": "Insufficient Data",
}


@dataclass
class CompanyReport:
    ticker: str
    name: str
    sector: str | None
    signal: str
    models_passed: int
    model_count: int
    composite_score: float | None
    summary: str
    passed_models: list[str]
    key_metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "signal": self.signal,
            "models_passed": self.models_passed,
            "model_count": self.model_count,
            "composite_score": self.composite_score,
            "summary": self.summary,
            "passed_models": self.passed_models,
            "key_metrics": self.key_metrics,
        }


def _parse_list_field(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "[]":
            return []
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (SyntaxError, ValueError):
            return [text]
    return []


def _format_metric(value: Any, *, pct: bool = False, decimals: int = 1) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if pct:
        # yfinance dividend yield is often already a percentage number for LSE
        if abs(float(value)) > 1:
            return f"{float(value):.{decimals}f}%"
        return f"{float(value) * 100:.{decimals}f}%"
    return f"{float(value):.{decimals}f}"


def _key_metrics_row(row: pd.Series) -> dict[str, str]:
    metrics: dict[str, str] = {}
    mapping = [
        ("trailing_pe", "P/E", False),
        ("price_to_book", "P/B", False),
        ("dividend_yield", "Yield", True),
        ("return_on_equity", "ROE", True),
        ("free_cashflow", "FCF", False),
    ]
    for col, label, is_pct in mapping:
        formatted = _format_metric(row.get(col), pct=is_pct)
        if formatted is not None:
            metrics[label] = formatted
    return metrics


def _brief_summary(
    *,
    signal: str,
    models_passed: int,
    model_count: int,
    composite_score: float | None,
    passed_model_names: list[str],
    passed_reasons: list[str],
    near_miss_failures: list[str],
    key_metrics: dict[str, str],
) -> str:
    label = SIGNAL_LABELS.get(signal, signal)
    parts: list[str] = []

    score_text = f"{models_passed}/{model_count} models"
    if composite_score is not None and not pd.isna(composite_score):
        score_text += f", composite {composite_score:.0%}"
    parts.append(f"{label} ({score_text}).")

    if key_metrics:
        metric_bits = ", ".join(f"{k} {v}" for k, v in list(key_metrics.items())[:4])
        parts.append(f"Key metrics: {metric_bits}.")

    if passed_model_names:
        models_text = ", ".join(passed_model_names[:5])
        if len(passed_model_names) > 5:
            models_text += f" +{len(passed_model_names) - 5} more"
        parts.append(f"Passes: {models_text}.")

    if passed_reasons:
        highlights = "; ".join(passed_reasons[:3])
        parts.append(f"Highlights: {highlights}.")

    if near_miss_failures and signal in ("hold", "avoid"):
        misses = "; ".join(near_miss_failures[:2])
        parts.append(f"Gaps: {misses}.")

    return " ".join(parts)


def build_company_reports(signals: pd.DataFrame, model_results: pd.DataFrame) -> list[CompanyReport]:
    """Create a brief reason summary for every screened company."""
    reports: list[CompanyReport] = []

    for _, row in signals.iterrows():
        ticker = row["ticker"]
        ticker_models = model_results[model_results["ticker"] == ticker].copy()

        passed = ticker_models[ticker_models["passed"] == True]  # noqa: E712
        failed = ticker_models[ticker_models["passed"] == False]  # noqa: E712

        passed_model_names = passed["model_name"].tolist()
        passed_reasons: list[str] = []
        for _, model_row in passed.iterrows():
            passed_reasons.extend(_parse_list_field(model_row.get("reasons")))

        # Near-miss: highest-scoring models that did not pass
        near_miss = failed.sort_values("score", ascending=False).head(3)
        near_miss_failures: list[str] = []
        for _, model_row in near_miss.iterrows():
            failures = _parse_list_field(model_row.get("failed_criteria"))
            if failures:
                near_miss_failures.append(f"{model_row['model_name']}: {failures[0]}")

        key_metrics = _key_metrics_row(row)
        composite = row.get("composite_score")
        composite_score = float(composite) if composite is not None and not pd.isna(composite) else None

        summary = _brief_summary(
            signal=str(row.get("signal", "hold")),
            models_passed=int(row.get("models_passed") or 0),
            model_count=int(row.get("model_count") or 0),
            composite_score=composite_score,
            passed_model_names=passed_model_names,
            passed_reasons=passed_reasons,
            near_miss_failures=near_miss_failures,
            key_metrics=key_metrics,
        )

        reports.append(
            CompanyReport(
                ticker=ticker,
                name=str(row.get("name") or ticker),
                sector=row.get("sector"),
                signal=str(row.get("signal", "hold")),
                models_passed=int(row.get("models_passed") or 0),
                model_count=int(row.get("model_count") or 0),
                composite_score=composite_score,
                summary=summary,
                passed_models=passed_model_names,
                key_metrics=key_metrics,
            )
        )

    return reports
