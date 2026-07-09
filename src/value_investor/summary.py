"""Build per-company reason summaries from screening output."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

import pandas as pd

from value_investor.data_quality import quality_label
from value_investor.model_families import format_family_summary
from value_investor.technical_analysis import TradePlan, format_timing_summary, format_trade_plan_text, trade_plan_from_row

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
    sector_composite_score: float | None
    families_passed: int
    passed_families: str | None
    data_quality_score: float
    metrics_present: int
    metrics_total: int
    weeks_at_signal: int
    signal_trend: str
    conviction_score: float
    stability_label: str
    timing_signal: str
    timing_score: float
    rsi_14: float | None
    price_vs_sma200_pct: float | None
    action_note: str
    trade_plan: TradePlan | None
    summary: str
    passed_models: list[str]
    key_metrics: dict[str, Any]
    adjusted_signal: str | None = None
    research_verdict: str | None = None
    research_risk_level: str | None = None
    research_confidence: float | None = None
    research_rationale: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "signal": self.signal,
            "models_passed": self.models_passed,
            "model_count": self.model_count,
            "composite_score": self.composite_score,
            "sector_composite_score": self.sector_composite_score,
            "families_passed": self.families_passed,
            "passed_families": self.passed_families,
            "data_quality_score": self.data_quality_score,
            "metrics_present": self.metrics_present,
            "metrics_total": self.metrics_total,
            "weeks_at_signal": self.weeks_at_signal,
            "signal_trend": self.signal_trend,
            "conviction_score": self.conviction_score,
            "stability_label": self.stability_label,
            "timing_signal": self.timing_signal,
            "timing_score": self.timing_score,
            "rsi_14": self.rsi_14,
            "price_vs_sma200_pct": self.price_vs_sma200_pct,
            "action_note": self.action_note,
            "trade_plan": self.trade_plan.to_dict() if self.trade_plan else None,
            "summary": self.summary,
            "passed_models": self.passed_models,
            "key_metrics": self.key_metrics,
            "adjusted_signal": self.adjusted_signal,
            "research_verdict": self.research_verdict,
            "research_risk_level": self.research_risk_level,
            "research_confidence": self.research_confidence,
            "research_rationale": self.research_rationale,
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
    sector_composite_score: float | None,
    families_passed: int,
    passed_families: str | None,
    data_quality_score: float,
    metrics_present: int,
    metrics_total: int,
    weeks_at_signal: int,
    signal_trend: str,
    conviction_score: float,
    stability_label: str,
    timing_signal: str,
    timing_score: float,
    rsi_14: float | None,
    timing_reasons: list[str] | str,
    action_note: str,
    trade_plan: TradePlan | None,
    passed_model_names: list[str],
    passed_reasons: list[str],
    near_miss_failures: list[str],
    key_metrics: dict[str, str],
    research_verdict: str | None = None,
    adjusted_signal: str | None = None,
) -> str:
    label = SIGNAL_LABELS.get(signal, signal)
    parts: list[str] = []

    score_text = f"{models_passed}/{model_count} models"
    if composite_score is not None and not pd.isna(composite_score):
        score_text += f", composite {composite_score:.0%}"
    if sector_composite_score is not None and not pd.isna(sector_composite_score):
        score_text += f", sector-relative {sector_composite_score:.0%}"
    parts.append(f"{label} ({score_text}).")

    if families_passed:
        family_text = format_family_summary(passed_families)
        parts.append(f"Families: {families_passed}/4 ({family_text}).")

    parts.append(
        f"Data quality: {metrics_present}/{metrics_total} ({quality_label(data_quality_score)}). "
        f"Conviction {conviction_score:.0%} ({stability_label}, {weeks_at_signal}w at signal, {signal_trend})."
    )

    if timing_signal and timing_signal != "insufficient_data":
        parts.append(format_timing_summary(timing_signal, rsi_14, timing_reasons))
        if action_note:
            parts.append(f"Action: {action_note}.")

    if signal == "strong_buy" and trade_plan is not None:
        plan_text = format_trade_plan_text(trade_plan)
        if plan_text:
            parts.append(plan_text)

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

    if research_verdict:
        verdict_label = research_verdict.replace("_", " ").title()
        overlay = f"Research verdict: {verdict_label}"
        if adjusted_signal and adjusted_signal != signal:
            overlay += f" (adjusted to {SIGNAL_LABELS.get(adjusted_signal, adjusted_signal)})"
        parts.append(f"{overlay}.")

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
        sector_score = row.get("sector_composite_score")
        sector_composite_score = (
            float(sector_score) if sector_score is not None and not pd.isna(sector_score) else None
        )

        timing_reasons_raw = row.get("timing_reasons")
        if isinstance(timing_reasons_raw, str) and timing_reasons_raw.startswith("["):
            timing_reasons = _parse_list_field(timing_reasons_raw)
        elif isinstance(timing_reasons_raw, list):
            timing_reasons = timing_reasons_raw
        else:
            timing_reasons = []

        trade_plan = trade_plan_from_row(row)

        signal = str(row.get("signal", "hold"))
        adjusted_signal = row.get("adjusted_signal")
        adjusted_signal_str = (
            str(adjusted_signal)
            if adjusted_signal is not None and not (isinstance(adjusted_signal, float) and pd.isna(adjusted_signal))
            else None
        )
        research_verdict = row.get("research_verdict")
        research_verdict_str = (
            str(research_verdict)
            if research_verdict is not None and not (isinstance(research_verdict, float) and pd.isna(research_verdict))
            else None
        )
        research_risk = row.get("research_risk_level")
        research_risk_str = (
            str(research_risk)
            if research_risk is not None and not (isinstance(research_risk, float) and pd.isna(research_risk))
            else None
        )
        research_conf = row.get("research_confidence")
        research_confidence = (
            float(research_conf)
            if research_conf is not None and not (isinstance(research_conf, float) and pd.isna(research_conf))
            else None
        )
        research_rat = row.get("research_rationale")
        research_rationale_str = (
            str(research_rat)
            if research_rat is not None and not (isinstance(research_rat, float) and pd.isna(research_rat))
            else None
        )

        summary = _brief_summary(
            signal=signal,
            models_passed=int(row.get("models_passed") or 0),
            model_count=int(row.get("model_count") or 0),
            composite_score=composite_score,
            sector_composite_score=sector_composite_score,
            families_passed=int(row.get("families_passed") or 0),
            passed_families=row.get("passed_families"),
            data_quality_score=float(row.get("data_quality_score") or 0),
            metrics_present=int(row.get("metrics_present") or 0),
            metrics_total=int(row.get("metrics_total") or 20),
            weeks_at_signal=int(row.get("weeks_at_signal") or 1),
            signal_trend=str(row.get("signal_trend") or "new"),
            conviction_score=float(row.get("conviction_score") or 0),
            stability_label=str(row.get("stability_label") or "new"),
            timing_signal=str(row.get("timing_signal") or "insufficient_data"),
            timing_score=float(row.get("timing_score") or 0),
            rsi_14=float(row["rsi_14"]) if row.get("rsi_14") is not None and not pd.isna(row.get("rsi_14")) else None,
            timing_reasons=timing_reasons,
            action_note=str(row.get("action_note") or ""),
            trade_plan=trade_plan,
            passed_model_names=passed_model_names,
            passed_reasons=passed_reasons,
            near_miss_failures=near_miss_failures,
            key_metrics=key_metrics,
            research_verdict=research_verdict_str,
            adjusted_signal=adjusted_signal_str,
        )

        vs_sma = row.get("price_vs_sma200_pct")
        price_vs_sma200_pct = float(vs_sma) if vs_sma is not None and not pd.isna(vs_sma) else None

        reports.append(
            CompanyReport(
                ticker=ticker,
                name=str(row.get("name") or ticker),
                sector=row.get("sector"),
                signal=signal,
                models_passed=int(row.get("models_passed") or 0),
                model_count=int(row.get("model_count") or 0),
                composite_score=composite_score,
                sector_composite_score=sector_composite_score,
                families_passed=int(row.get("families_passed") or 0),
                passed_families=row.get("passed_families"),
                data_quality_score=float(row.get("data_quality_score") or 0),
                metrics_present=int(row.get("metrics_present") or 0),
                metrics_total=int(row.get("metrics_total") or 20),
                weeks_at_signal=int(row.get("weeks_at_signal") or 1),
                signal_trend=str(row.get("signal_trend") or "new"),
                conviction_score=float(row.get("conviction_score") or 0),
                stability_label=str(row.get("stability_label") or "new"),
                timing_signal=str(row.get("timing_signal") or "insufficient_data"),
                timing_score=float(row.get("timing_score") or 0),
                rsi_14=float(row["rsi_14"]) if row.get("rsi_14") is not None and not pd.isna(row.get("rsi_14")) else None,
                price_vs_sma200_pct=price_vs_sma200_pct,
                action_note=str(row.get("action_note") or ""),
                trade_plan=trade_plan,
                summary=summary,
                passed_models=passed_model_names,
                key_metrics=key_metrics,
                adjusted_signal=adjusted_signal_str or signal,
                research_verdict=research_verdict_str,
                research_risk_level=research_risk_str,
                research_confidence=research_confidence,
                research_rationale=research_rationale_str,
            )
        )

    return reports
