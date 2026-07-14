"""Build per-trust report summaries for the closed-end / investment-trust track."""

from __future__ import annotations

import ast
from typing import Any

import pandas as pd

from value_investor.data_quality import quality_label
from value_investor.summary import SIGNAL_LABELS, CompanyReport
from value_investor.technical_analysis import TradePlan, trade_plan_from_row


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


def _format_pct(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return f"{float(value) * 100:.1f}%"


def _format_num(value: Any, *, decimals: int = 2) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return f"{float(value):.{decimals}f}"


def trust_key_metrics(row: pd.Series) -> dict[str, str]:
    metrics: dict[str, str] = {}
    discount = _format_pct(row.get("discount_to_nav"))
    if discount is not None:
        # Positive discount_to_nav means trading below book/NAV proxy.
        label = "Discount" if float(row.get("discount_to_nav") or 0) >= 0 else "Premium"
        abs_pct = _format_pct(abs(float(row["discount_to_nav"])))
        if abs_pct:
            metrics[label] = abs_pct
    pb = _format_num(row.get("price_to_book"))
    if pb is not None:
        metrics["P/B"] = pb
    yld = _format_pct(row.get("dividend_yield"))
    if yld is not None:
        metrics["Yield"] = yld
    pe = _format_num(row.get("trailing_pe"), decimals=1)
    if pe is not None:
        metrics["P/E"] = pe
    return metrics


def _trust_brief_summary(
    *,
    signal: str,
    models_passed: int,
    model_count: int,
    composite_score: float | None,
    families_passed: int,
    family_count: int,
    passed_families: str | None,
    data_quality_score: float,
    metrics_present: int,
    metrics_total: int,
    conviction_score: float,
    passed_model_names: list[str],
    passed_reasons: list[str],
    near_miss_failures: list[str],
    key_metrics: dict[str, str],
) -> str:
    label = SIGNAL_LABELS.get(signal, signal)
    parts: list[str] = []

    score_text = f"{models_passed}/{model_count} trust models"
    if composite_score is not None and not pd.isna(composite_score):
        score_text += f", composite {composite_score:.0%}"
    parts.append(f"{label} ({score_text}).")

    if families_passed:
        family_text = (passed_families or "").replace(",", ", ")
        parts.append(f"Families: {families_passed}/{family_count} ({family_text}).")

    parts.append(
        f"Data quality: {metrics_present}/{metrics_total} ({quality_label(data_quality_score)}). "
        f"Conviction {conviction_score:.0%}."
    )
    parts.append("NAV proxy: book value (Yahoo does not publish LSE trust NAVs).")

    if key_metrics:
        metric_bits = ", ".join(f"{k} {v}" for k, v in list(key_metrics.items())[:4])
        parts.append(f"Key metrics: {metric_bits}.")

    if passed_model_names:
        models_text = ", ".join(passed_model_names[:5])
        parts.append(f"Passes: {models_text}.")

    if passed_reasons:
        parts.append(f"Highlights: {'; '.join(passed_reasons[:3])}.")

    if near_miss_failures and signal in ("hold", "avoid"):
        parts.append(f"Gaps: {'; '.join(near_miss_failures[:2])}.")

    return " ".join(parts)


def build_trust_reports(signals: pd.DataFrame, model_results: pd.DataFrame) -> list[CompanyReport]:
    """Create report objects for the trust track (same shape as operating-company reports)."""
    reports: list[CompanyReport] = []
    if signals.empty:
        return reports

    for _, row in signals.iterrows():
        ticker = row["ticker"]
        ticker_models = model_results[model_results["ticker"] == ticker].copy()
        passed = ticker_models[ticker_models["passed"] == True]  # noqa: E712
        failed = ticker_models[ticker_models["passed"] == False]  # noqa: E712

        passed_model_names = passed["model_name"].tolist()
        passed_reasons: list[str] = []
        for _, model_row in passed.iterrows():
            passed_reasons.extend(_parse_list_field(model_row.get("reasons")))

        near_miss = failed.sort_values("score", ascending=False).head(3)
        near_miss_failures: list[str] = []
        for _, model_row in near_miss.iterrows():
            failures = _parse_list_field(model_row.get("failed_criteria"))
            if failures:
                near_miss_failures.append(f"{model_row['model_name']}: {failures[0]}")

        key_metrics = trust_key_metrics(row)
        composite = row.get("composite_score")
        composite_score = float(composite) if composite is not None and not pd.isna(composite) else None
        trade_plan: TradePlan | None = trade_plan_from_row(row)
        signal = str(row.get("signal", "hold"))
        family_count = int(row.get("family_count") or 3)

        summary = _trust_brief_summary(
            signal=signal,
            models_passed=int(row.get("models_passed") or 0),
            model_count=int(row.get("model_count") or 0),
            composite_score=composite_score,
            families_passed=int(row.get("families_passed") or 0),
            family_count=family_count,
            passed_families=row.get("passed_families"),
            data_quality_score=float(row.get("data_quality_score") or 0),
            metrics_present=int(row.get("metrics_present") or 0),
            metrics_total=int(row.get("metrics_total") or 0),
            conviction_score=float(row.get("conviction_score") or 0),
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
                signal=signal,
                models_passed=int(row.get("models_passed") or 0),
                model_count=int(row.get("model_count") or 0),
                composite_score=composite_score,
                sector_composite_score=None,
                families_passed=int(row.get("families_passed") or 0),
                passed_families=row.get("passed_families"),
                data_quality_score=float(row.get("data_quality_score") or 0),
                metrics_present=int(row.get("metrics_present") or 0),
                metrics_total=int(row.get("metrics_total") or 0),
                weeks_at_signal=int(row.get("weeks_at_signal") or 1),
                signal_trend=str(row.get("signal_trend") or "new"),
                conviction_score=float(row.get("conviction_score") or 0),
                stability_label=str(row.get("stability_label") or "new"),
                timing_signal=str(row.get("timing_signal") or "insufficient_data"),
                timing_score=float(row.get("timing_score") or 0),
                rsi_14=None,
                price_vs_sma200_pct=None,
                action_note=str(row.get("action_note") or ""),
                trade_plan=trade_plan,
                summary=summary,
                passed_models=passed_model_names,
                key_metrics=key_metrics,
                adjusted_signal=signal,
            )
        )

    return reports
