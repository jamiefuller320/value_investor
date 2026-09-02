"""Build per-company reason summaries from screening output."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.data_quality import quality_label
from value_investor.model_families import format_family_summary
from value_investor.models.piotroski import piotroski_snapshot_from_result
from value_investor.scoring.cash_conversion_overlay import apply_cash_conversion_overlay_to_signal
from value_investor.scoring.cyclical_exposure_overlay import (
    apply_cyclical_exposure_overlay_to_signal,
)
from value_investor.scoring.dividend_yield_overlay import apply_dividend_yield_overlay_to_signal
from value_investor.scoring.earnings_basis_overlay import apply_earnings_basis_overlay_to_signal
from value_investor.scoring.earnings_growth_overlay import (
    build_earnings_growth_overlay,
    format_earnings_growth_bps_warning,
)
from value_investor.scoring.fcf import (
    append_fcf_divergence_to_action_note,
    build_labelled_fcf_dividend_coverage,
    fcf_dividend_coverage,
    fcf_filing_screen_mismatch,
    ocf_definition_diverges,
    overlay_free_cashflow_from_bundle,
    reconcile_fcf_for_ticker,
    resolve_free_cashflow,
    resolve_statutory_earnings_growth,
    screen_ttm_from_row,
)
from value_investor.scoring.fcf_basis_overlay import apply_fcf_basis_overlay_to_signal
from value_investor.scoring.healthcare_overlay import (
    apply_healthcare_overlay_to_signal,
    piotroski_score_for_ticker,
)
from value_investor.scoring.healthcare_price_erosion_overlay import (
    apply_healthcare_price_erosion_overlay_to_signal,
)
from value_investor.scoring.interim_quality_overlay import apply_interim_quality_overlay_to_signal
from value_investor.scoring.leverage_overlay import format_adjusted_net_debt_gbp
from value_investor.scoring.peer_model_pass_table import (
    attach_peer_model_pass_table,
    build_peer_model_pass_table,
)
from value_investor.technical_analysis import (
    TradePlan,
    format_timing_summary,
    format_trade_plan_text,
    trade_plan_from_row,
)

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
    failed_models: list[str] = field(default_factory=list)
    model_failures: dict[str, list[str]] = field(default_factory=dict)
    screening_inputs: dict[str, Any] = field(default_factory=dict)
    cashflow_metrics: dict[str, Any] | None = None
    fcf: dict[str, Any] | None = None
    piotroski_f_score: dict[str, Any] | None = None
    healthcare_overlay: bool = False
    healthcare_price_erosion_overlay: bool = False
    cash_conversion_overlay: bool = False
    dividend_yield_overlay: bool = False
    interim_quality_overlay: bool = False
    cyclical_exposure_overlay: bool = False
    cyclical_exposure_detected: bool = False
    earnings_basis_overlay: bool = False
    earnings_growth_overlay: dict[str, Any] = field(default_factory=dict)
    earnings_growth_bps_divergence_warning: bool = False
    peer_model_pass_table: dict[str, Any] = field(default_factory=dict)
    fcf_basis_overlay: bool = False
    leverage_override: bool = False
    dual_leverage_display: bool = False
    operating_cashflow: float | None = None
    fcf_dividend_coverage_gross: float | None = None
    fcf_dividend_coverage_net: float | None = None
    fcf_dividend_coverage: dict[str, Any] | None = None
    fcf_definition_divergence: bool = False
    fcf_divergence_flagged: bool = False
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
            "failed_models": self.failed_models,
            "model_failures": self.model_failures,
            "screening_inputs": self.screening_inputs,
            "key_metrics": self.key_metrics,
            "cashflow_metrics": self.cashflow_metrics,
            "fcf": self.fcf,
            "piotroski_f_score": self.piotroski_f_score,
            "healthcare_overlay": self.healthcare_overlay,
            "healthcare_price_erosion_overlay": self.healthcare_price_erosion_overlay,
            "cash_conversion_overlay": self.cash_conversion_overlay,
            "dividend_yield_overlay": self.dividend_yield_overlay,
            "interim_quality_overlay": self.interim_quality_overlay,
            "cyclical_exposure_overlay": self.cyclical_exposure_overlay,
            "cyclical_exposure_detected": self.cyclical_exposure_detected,
            "earnings_basis_overlay": self.earnings_basis_overlay,
            "earnings_growth_overlay": self.earnings_growth_overlay,
            "earnings_growth_bps_divergence_warning": self.earnings_growth_bps_divergence_warning,
            "peer_model_pass_table": self.peer_model_pass_table,
            "fcf_basis_overlay": self.fcf_basis_overlay,
            "leverage_override": self.leverage_override,
            "dual_leverage_display": self.dual_leverage_display,
            "operating_cashflow": self.operating_cashflow,
            "fcf_dividend_coverage_gross": self.fcf_dividend_coverage_gross,
            "fcf_dividend_coverage_net": self.fcf_dividend_coverage_net,
            "fcf_dividend_coverage": self.fcf_dividend_coverage,
            "fcf_definition_divergence": self.fcf_definition_divergence,
            "fcf_divergence_flagged": self.fcf_divergence_flagged,
            "adjusted_signal": self.adjusted_signal,
            "research_verdict": self.research_verdict,
            "research_risk_level": self.research_risk_level,
            "research_confidence": self.research_confidence,
            "research_rationale": self.research_rationale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompanyReport:
        from value_investor.technical_analysis import trade_plan_from_row

        trade_plan_raw = data.get("trade_plan")
        trade_plan = trade_plan_from_row(trade_plan_raw) if trade_plan_raw else None
        return cls(
            ticker=str(data["ticker"]),
            name=str(data.get("name") or data["ticker"]),
            sector=data.get("sector"),
            signal=str(data.get("signal") or "hold"),
            models_passed=int(data.get("models_passed") or 0),
            model_count=int(data.get("model_count") or 0),
            composite_score=data.get("composite_score"),
            sector_composite_score=data.get("sector_composite_score"),
            families_passed=int(data.get("families_passed") or 0),
            passed_families=data.get("passed_families"),
            data_quality_score=float(data.get("data_quality_score") or 0.0),
            metrics_present=int(data.get("metrics_present") or 0),
            metrics_total=int(data.get("metrics_total") or 0),
            weeks_at_signal=int(data.get("weeks_at_signal") or 0),
            signal_trend=str(data.get("signal_trend") or "new"),
            conviction_score=float(data.get("conviction_score") or 0.0),
            stability_label=str(data.get("stability_label") or "new"),
            timing_signal=str(data.get("timing_signal") or "neutral"),
            timing_score=float(data.get("timing_score") or 0.0),
            rsi_14=data.get("rsi_14"),
            price_vs_sma200_pct=data.get("price_vs_sma200_pct"),
            action_note=str(data.get("action_note") or ""),
            trade_plan=trade_plan,
            summary=str(data.get("summary") or ""),
            passed_models=list(data.get("passed_models") or []),
            key_metrics=dict(data.get("key_metrics") or {}),
            failed_models=list(data.get("failed_models") or []),
            model_failures=dict(data.get("model_failures") or {}),
            screening_inputs=dict(data.get("screening_inputs") or {}),
            cashflow_metrics=data.get("cashflow_metrics"),
            fcf=data.get("fcf"),
            piotroski_f_score=data.get("piotroski_f_score"),
            healthcare_overlay=bool(data.get("healthcare_overlay")),
            healthcare_price_erosion_overlay=bool(data.get("healthcare_price_erosion_overlay")),
            cash_conversion_overlay=bool(data.get("cash_conversion_overlay")),
            dividend_yield_overlay=bool(data.get("dividend_yield_overlay")),
            interim_quality_overlay=bool(data.get("interim_quality_overlay")),
            cyclical_exposure_overlay=bool(data.get("cyclical_exposure_overlay")),
            cyclical_exposure_detected=bool(data.get("cyclical_exposure_detected")),
            earnings_basis_overlay=bool(data.get("earnings_basis_overlay")),
            earnings_growth_overlay=dict(data.get("earnings_growth_overlay") or {}),
            earnings_growth_bps_divergence_warning=bool(
                data.get("earnings_growth_bps_divergence_warning")
            ),
            peer_model_pass_table=dict(data.get("peer_model_pass_table") or {}),
            fcf_basis_overlay=bool(data.get("fcf_basis_overlay")),
            leverage_override=bool(data.get("leverage_override")),
            dual_leverage_display=bool(data.get("dual_leverage_display")),
            operating_cashflow=data.get("operating_cashflow"),
            fcf_dividend_coverage_gross=data.get("fcf_dividend_coverage_gross"),
            fcf_dividend_coverage_net=data.get("fcf_dividend_coverage_net"),
            fcf_dividend_coverage=data.get("fcf_dividend_coverage"),
            fcf_definition_divergence=bool(data.get("fcf_definition_divergence")),
            fcf_divergence_flagged=bool(data.get("fcf_divergence_flagged")),
            adjusted_signal=data.get("adjusted_signal"),
            research_verdict=data.get("research_verdict"),
            research_risk_level=data.get("research_risk_level"),
            research_confidence=data.get("research_confidence"),
            research_rationale=data.get("research_rationale"),
        )


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


def _key_metrics_row(row: pd.Series, *, canonical_fcf: float | None = None) -> dict[str, str]:
    metrics: dict[str, str] = {}
    mapping = [
        ("trailing_pe", "P/E", False),
        ("price_to_book", "P/B", False),
        ("dividend_yield", "Yield", True),
        ("return_on_equity", "ROE", True),
    ]
    for col, label, is_pct in mapping:
        formatted = _format_metric(row.get(col), pct=is_pct)
        if formatted is not None:
            metrics[label] = formatted

    dual_display = row.get("dual_leverage_display")
    if (
        dual_display is not None
        and not (isinstance(dual_display, float) and pd.isna(dual_display))
        and bool(dual_display)
    ):
        yahoo_de = row.get("debt_to_equity_yahoo")
        if yahoo_de is not None and not (isinstance(yahoo_de, float) and pd.isna(yahoo_de)):
            metrics["D/E (Yahoo)"] = f"{float(yahoo_de):.0f}%"
        filing_label = format_adjusted_net_debt_gbp(row.get("filing_adjusted_net_debt_gbp"))
        if filing_label is not None:
            metrics["Leverage (filing)"] = filing_label
        effective_de = row.get("debt_to_equity")
        if (
            row.get("leverage_override") is not None
            and not (
                isinstance(row.get("leverage_override"), float)
                and pd.isna(row.get("leverage_override"))
            )
            and bool(row.get("leverage_override"))
            and effective_de is not None
            and not (isinstance(effective_de, float) and pd.isna(effective_de))
        ):
            metrics["D/E (screen)"] = f"{float(effective_de):.0f}%"

    fcf_value = canonical_fcf if canonical_fcf is not None else row.get("free_cashflow")
    formatted_fcf = _format_metric(fcf_value, pct=False)
    if formatted_fcf is not None:
        metrics["FCF"] = formatted_fcf
    return metrics


def _build_screening_inputs(row: pd.Series) -> dict[str, Any]:
    """Raw metric inputs cited by D/E, liquidity, growth, NCAV, and yield models."""
    inputs: dict[str, Any] = {}

    yahoo_de = row.get("debt_to_equity_yahoo")
    effective_de = row.get("debt_to_equity")
    filing_net_debt = row.get("filing_adjusted_net_debt_gbp")
    dual_display = row.get("dual_leverage_display")
    leverage_override = row.get("leverage_override")

    if (
        dual_display is not None
        and not (isinstance(dual_display, float) and pd.isna(dual_display))
        and bool(dual_display)
    ):
        if yahoo_de is not None and not (isinstance(yahoo_de, float) and pd.isna(yahoo_de)):
            inputs["debt_to_equity_yahoo"] = float(yahoo_de)
        if effective_de is not None and not (
            isinstance(effective_de, float) and pd.isna(effective_de)
        ):
            inputs["debt_to_equity"] = float(effective_de)
        if filing_net_debt is not None and not (
            isinstance(filing_net_debt, float) and pd.isna(filing_net_debt)
        ):
            inputs["filing_adjusted_net_debt_gbp"] = float(filing_net_debt)
        if leverage_override is not None and not (
            isinstance(leverage_override, float) and pd.isna(leverage_override)
        ):
            inputs["leverage_override"] = bool(leverage_override)
    elif effective_de is not None and not (
        isinstance(effective_de, float) and pd.isna(effective_de)
    ):
        inputs["debt_to_equity"] = float(effective_de)

    cr = row.get("current_ratio_bs")
    if cr is None or (isinstance(cr, float) and pd.isna(cr)):
        cr = row.get("current_ratio")
    if cr is not None and not (isinstance(cr, float) and pd.isna(cr)):
        inputs["current_ratio"] = float(cr)

    growth = row.get("earnings_growth")
    basic_growth = row.get("basic_eps_growth_pct")
    if basic_growth is not None and not (isinstance(basic_growth, float) and pd.isna(basic_growth)):
        inputs["basic_eps_growth_pct"] = float(basic_growth)
    if growth is not None and not (isinstance(growth, float) and pd.isna(growth)):
        inputs["earnings_growth_pct"] = float(growth)

    statutory_growth = resolve_statutory_earnings_growth(row)
    if statutory_growth is not None:
        inputs["statutory_earnings_growth_pct"] = statutory_growth

    adjusted_growth = row.get("adjusted_eps_growth_pct")
    if adjusted_growth is not None and not (
        isinstance(adjusted_growth, float) and pd.isna(adjusted_growth)
    ):
        inputs["adjusted_eps_growth_pct"] = float(adjusted_growth)

    ncav = row.get("ncav")
    inputs["ncav_available"] = ncav is not None and not (isinstance(ncav, float) and pd.isna(ncav))
    if inputs["ncav_available"]:
        inputs["ncav"] = float(ncav)

    yld = row.get("dividend_yield")
    if yld is not None and not (isinstance(yld, float) and pd.isna(yld)):
        inputs["dividend_yield_raw"] = float(yld)

    return inputs


def _build_model_failures(ticker_models: pd.DataFrame) -> dict[str, list[str]]:
    """Map failed model names to their ``failed_criteria`` reasons."""
    failures: dict[str, list[str]] = {}
    if ticker_models.empty:
        return failures

    failed = ticker_models[ticker_models["passed"] == False]  # noqa: E712
    for _, model_row in failed.iterrows():
        reasons = _parse_list_field(model_row.get("failed_criteria"))
        if reasons:
            failures[str(model_row["model_name"])] = reasons
    return failures


def _piotroski_f_score_from_models(ticker_models: pd.DataFrame) -> dict[str, Any] | None:
    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return None
    piotroski = ticker_models[ticker_models["model_id"] == "piotroski_f"]
    if piotroski.empty:
        return None

    model_row = piotroski.iloc[0]
    details = model_row.get("details")
    if isinstance(details, str) and details.strip():
        try:
            parsed = ast.literal_eval(details)
            details = parsed if isinstance(parsed, dict) else None
        except (SyntaxError, ValueError):
            details = None
    elif not isinstance(details, dict):
        details = None

    return piotroski_snapshot_from_result(
        passed=bool(model_row.get("passed")),
        score=float(model_row.get("score") or 0),
        reasons=_parse_list_field(model_row.get("reasons")),
        failed_criteria=_parse_list_field(model_row.get("failed_criteria")),
        details=details,
    )


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
    healthcare_overlay: bool = False,
    healthcare_price_erosion_overlay: bool = False,
    cash_conversion_overlay: bool = False,
    dividend_yield_overlay: bool = False,
    interim_quality_overlay: bool = False,
    cyclical_exposure_overlay: bool = False,
    earnings_basis_overlay: bool = False,
    earnings_growth_bps_divergence_warning: bool = False,
    fcf_basis_overlay: bool = False,
    leverage_override: bool = False,
    dual_leverage_display: bool = False,
    debt_to_equity_yahoo: float | None = None,
    filing_adjusted_net_debt_gbp: float | None = None,
    fcf_dividend_coverage_gross: float | None = None,
    fcf_dividend_coverage_net: float | None = None,
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
    elif action_note and (
        "FCF basis mismatch" in action_note or "FCF filing-aligned" in action_note
    ):
        parts.append(f"Action: {action_note}.")

    if signal in ("strong_buy", "buy") and trade_plan is not None:
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

    if healthcare_overlay and adjusted_signal and adjusted_signal != signal:
        parts.append(
            f"Healthcare overlay: negative FCF with weak Piotroski "
            f"(adjusted to {SIGNAL_LABELS.get(adjusted_signal, adjusted_signal)})."
        )

    if cash_conversion_overlay and adjusted_signal and adjusted_signal != signal:
        parts.append(
            f"Cash-conversion overlay: negative FCF with dividend screens and buyback "
            f"(adjusted to {SIGNAL_LABELS.get(adjusted_signal, adjusted_signal)})."
        )

    if dividend_yield_overlay and adjusted_signal and adjusted_signal != signal:
        parts.append(
            f"Dividend-yield overlay: high yield passes but FCF yield and earnings quality fail "
            f"(adjusted to {SIGNAL_LABELS.get(adjusted_signal, adjusted_signal)})."
        )

    if interim_quality_overlay and adjusted_signal and adjusted_signal != signal:
        coverage_note = ""
        if fcf_dividend_coverage_gross is not None and fcf_dividend_coverage_net is not None:
            coverage_note = (
                f" (gross {fcf_dividend_coverage_gross:.2f}×, net {fcf_dividend_coverage_net:.2f}×)"
            )
        parts.append(
            f"Interim-quality overlay: quality passes but interim EPS declined and net FCF/dividend "
            f"coverage is below 1.0×{coverage_note} "
            f"(adjusted to {SIGNAL_LABELS.get(adjusted_signal, adjusted_signal)})."
        )

    if cyclical_exposure_overlay and adjusted_signal and adjusted_signal != signal:
        parts.append(
            f"Cyclical-exposure overlay: discretionary demand risk with interim EPS decline and thin "
            f"dividend cover "
            f"(adjusted to {SIGNAL_LABELS.get(adjusted_signal, adjusted_signal)})."
        )

    if healthcare_price_erosion_overlay and adjusted_signal and adjusted_signal != signal:
        parts.append(
            f"Healthcare price-erosion overlay: quality/income pass but yield screens fail with "
            f"filing pricing pressure "
            f"(adjusted to {SIGNAL_LABELS.get(adjusted_signal, adjusted_signal)})."
        )

    if earnings_basis_overlay and adjusted_signal and adjusted_signal != signal:
        parts.append(
            f"Earnings-basis overlay: statutory and filing-adjusted EPS growth diverge in sign "
            f"while growth-dependent screens pass "
            f"(adjusted to {SIGNAL_LABELS.get(adjusted_signal, adjusted_signal)})."
        )

    if earnings_growth_bps_divergence_warning:
        parts.append(
            "Earnings growth warning: statutory and filing core EPS growth diverge by >300 bps."
        )

    if fcf_basis_overlay and adjusted_signal and adjusted_signal != signal:
        parts.append(
            f"FCF basis overlay: filing, screen TTM, and company-adjusted FCF diverge while "
            f"yield-dependent screens pass "
            f"(adjusted to {SIGNAL_LABELS.get(adjusted_signal, adjusted_signal)})."
        )

    if dual_leverage_display:
        yahoo_text = (
            f"Yahoo D/E {debt_to_equity_yahoo:.0f}%"
            if debt_to_equity_yahoo is not None
            else "Yahoo D/E elevated"
        )
        filing_text = (
            format_adjusted_net_debt_gbp(filing_adjusted_net_debt_gbp) or "filing net debt"
        )
        if leverage_override:
            parts.append(
                f"Leverage override: {yahoo_text} vs {filing_text} "
                f"(IFRS lease gross-up; screening uses filing-adjusted net debt)."
            )
        else:
            parts.append(
                f"Dual leverage: {yahoo_text} vs {filing_text} "
                f"(review filing-adjusted net debt before verdict)."
            )

    return " ".join(parts)


def build_company_reports(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> list[CompanyReport]:
    """Create a brief reason summary for every screened company."""
    reports: list[CompanyReport] = []

    for _, row in signals.iterrows():
        ticker = row["ticker"]
        ticker_models = model_results[model_results["ticker"] == ticker].copy()

        passed = ticker_models[ticker_models["passed"] == True]  # noqa: E712
        failed = ticker_models[ticker_models["passed"] == False]  # noqa: E712

        passed_model_names = passed["model_name"].tolist()
        failed_model_names = failed["model_name"].tolist()
        model_failures = _build_model_failures(ticker_models)
        screening_inputs = _build_screening_inputs(row)
        earnings_growth_overlay = build_earnings_growth_overlay(row)
        earnings_growth_bps_divergence_warning = bool(
            earnings_growth_overlay.get("bps_divergence_warning")
        )
        screening_inputs.update(
            {key: value for key, value in earnings_growth_overlay.items() if value is not None}
        )
        piotroski_f_score = _piotroski_f_score_from_models(ticker_models)
        screen_ttm = screen_ttm_from_row(row)
        fcf_bundle = reconcile_fcf_for_ticker(ticker, screen_ttm=screen_ttm, output_dir=output_dir)
        free_cashflow = overlay_free_cashflow_from_bundle(row, fcf_bundle)
        if free_cashflow is None:
            free_cashflow = resolve_free_cashflow(row)

        operating_cashflow_raw = row.get("operating_cashflow")
        operating_cashflow = (
            float(operating_cashflow_raw)
            if operating_cashflow_raw is not None
            and not (isinstance(operating_cashflow_raw, float) and pd.isna(operating_cashflow_raw))
            else None
        )
        if operating_cashflow is None:
            cashflow_metrics = fcf_bundle.get("cashflow_metrics") or {}
            ocf_from_metrics = cashflow_metrics.get("operating_cashflow")
            if ocf_from_metrics is not None:
                operating_cashflow = float(ocf_from_metrics)

        coverage_gross_raw = row.get("fcf_dividend_coverage_gross")
        fcf_dividend_coverage_gross = (
            float(coverage_gross_raw)
            if coverage_gross_raw is not None
            and not (isinstance(coverage_gross_raw, float) and pd.isna(coverage_gross_raw))
            else None
        )
        coverage_net_raw = row.get("fcf_dividend_coverage_net")
        fcf_dividend_coverage_net = (
            float(coverage_net_raw)
            if coverage_net_raw is not None
            and not (isinstance(coverage_net_raw, float) and pd.isna(coverage_net_raw))
            else None
        )
        definition_div_raw = row.get("fcf_definition_divergence")
        gross_ocf_raw = row.get("operating_cashflow_gross")
        operating_cashflow_gross = (
            float(gross_ocf_raw)
            if gross_ocf_raw is not None
            and not (isinstance(gross_ocf_raw, float) and pd.isna(gross_ocf_raw))
            else None
        )
        fcf_definition_divergence = (
            bool(definition_div_raw)
            if definition_div_raw is not None
            and not (isinstance(definition_div_raw, float) and pd.isna(definition_div_raw))
            else ocf_definition_diverges(operating_cashflow, operating_cashflow_gross)
        )
        divergence_flag_raw = row.get("fcf_divergence_flagged")
        fcf_divergence_flagged = (
            bool(divergence_flag_raw)
            if divergence_flag_raw is not None
            and not (isinstance(divergence_flag_raw, float) and pd.isna(divergence_flag_raw))
            else bool(fcf_bundle.get("fcf_divergence_flagged"))
        )
        labelled_fcf_dividend_coverage = build_labelled_fcf_dividend_coverage(
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
            fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
        )
        if (
            labelled_fcf_dividend_coverage["statutory_ocf_minus_capex"]["ratio"] is None
            and labelled_fcf_dividend_coverage["management_cash_generated_minus_capex"]["ratio"]
            is None
        ):
            labelled_fcf_dividend_coverage = None
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

        key_metrics = _key_metrics_row(row, canonical_fcf=free_cashflow)
        composite = row.get("composite_score")
        composite_score = (
            float(composite) if composite is not None and not pd.isna(composite) else None
        )
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
            if adjusted_signal is not None
            and not (isinstance(adjusted_signal, float) and pd.isna(adjusted_signal))
            else None
        )
        healthcare_overlay_flag = row.get("healthcare_overlay")
        if healthcare_overlay_flag is not None and not (
            isinstance(healthcare_overlay_flag, float) and pd.isna(healthcare_overlay_flag)
        ):
            healthcare_overlay = bool(healthcare_overlay_flag)
        else:
            piotroski_score = piotroski_score_for_ticker(ticker_models)
            healthcare_overlay, adjusted_signal_str = apply_healthcare_overlay_to_signal(
                signal,
                sector=row.get("sector"),
                free_cashflow=free_cashflow,
                piotroski_f_score=piotroski_score,
                adjusted_signal=adjusted_signal_str,
            )

        shares = row.get("shares_outstanding")
        shares_outstanding = (
            float(shares)
            if shares is not None and not (isinstance(shares, float) and pd.isna(shares))
            else None
        )
        shares_prev = row.get("shares_outstanding_prev")
        shares_outstanding_prev = (
            float(shares_prev)
            if shares_prev is not None
            and not (isinstance(shares_prev, float) and pd.isna(shares_prev))
            else None
        )

        cash_conversion_overlay_flag = row.get("cash_conversion_overlay")
        if cash_conversion_overlay_flag is not None and not (
            isinstance(cash_conversion_overlay_flag, float)
            and pd.isna(cash_conversion_overlay_flag)
        ):
            cash_conversion_overlay = bool(cash_conversion_overlay_flag)
        else:
            cash_conversion_overlay, adjusted_signal_str = apply_cash_conversion_overlay_to_signal(
                signal,
                free_cashflow=free_cashflow,
                shares_outstanding=shares_outstanding,
                shares_outstanding_prev=shares_outstanding_prev,
                ticker_models=ticker_models,
                adjusted_signal=adjusted_signal_str,
            )

        action_note = append_fcf_divergence_to_action_note(
            str(row.get("action_note") or ""),
            canonical=free_cashflow,
            screen_ttm=screen_ttm,
            fcf_bundle=fcf_bundle,
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
            fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
            fcf_definition_divergence=fcf_definition_divergence,
        )
        bps_warning = format_earnings_growth_bps_warning(earnings_growth_overlay)
        if bps_warning and bps_warning not in action_note:
            action_note = f"{action_note} | {bps_warning}" if action_note else bps_warning

        dividend_yield_overlay_flag = row.get("dividend_yield_overlay")
        if dividend_yield_overlay_flag is not None and not (
            isinstance(dividend_yield_overlay_flag, float) and pd.isna(dividend_yield_overlay_flag)
        ):
            dividend_yield_overlay = bool(dividend_yield_overlay_flag)
        else:
            dividend_yield_overlay, adjusted_signal_str = apply_dividend_yield_overlay_to_signal(
                signal,
                ticker_models=ticker_models,
                adjusted_signal=adjusted_signal_str,
            )

        interim_decline = row.get("interim_eps_decline_pct")
        interim_eps_decline_pct = (
            float(interim_decline)
            if interim_decline is not None
            and not (isinstance(interim_decline, float) and pd.isna(interim_decline))
            else None
        )
        dividends = row.get("dividends_paid")
        dividends_paid = (
            float(dividends)
            if dividends is not None and not (isinstance(dividends, float) and pd.isna(dividends))
            else None
        )

        interim_quality_overlay_flag = row.get("interim_quality_overlay")
        if interim_quality_overlay_flag is not None and not (
            isinstance(interim_quality_overlay_flag, float)
            and pd.isna(interim_quality_overlay_flag)
        ):
            interim_quality_overlay = bool(interim_quality_overlay_flag)
        else:
            interim_quality_overlay, adjusted_signal_str = apply_interim_quality_overlay_to_signal(
                signal,
                passed_families=row.get("passed_families"),
                interim_eps_decline_pct=interim_eps_decline_pct,
                free_cashflow=free_cashflow,
                dividends_paid=dividends_paid,
                fcf_dividend_coverage_net=fcf_dividend_coverage_net,
                fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
                adjusted_signal=adjusted_signal_str,
            )

        cyclical_overlay_flag = row.get("cyclical_exposure_overlay")
        cyclical_detected_flag = row.get("cyclical_exposure_detected")
        if cyclical_detected_flag is not None and not (
            isinstance(cyclical_detected_flag, float) and pd.isna(cyclical_detected_flag)
        ):
            cyclical_exposure_detected = bool(cyclical_detected_flag)
        else:
            cyclical_exposure_detected = False

        if cyclical_overlay_flag is not None and not (
            isinstance(cyclical_overlay_flag, float) and pd.isna(cyclical_overlay_flag)
        ):
            cyclical_exposure_overlay = bool(cyclical_overlay_flag)
        else:
            cyclical_exposure_overlay, adjusted_signal_str = (
                apply_cyclical_exposure_overlay_to_signal(
                    signal,
                    cyclical_exposure_detected_flag=cyclical_exposure_detected,
                    passed_families=row.get("passed_families"),
                    interim_eps_decline_pct=interim_eps_decline_pct,
                    fcf_dividend_coverage_net=fcf_dividend_coverage_net,
                    free_cashflow=free_cashflow,
                    dividends_paid=dividends_paid,
                    adjusted_signal=adjusted_signal_str,
                )
            )

        healthcare_price_erosion_overlay_flag = row.get("healthcare_price_erosion_overlay")
        if healthcare_price_erosion_overlay_flag is not None and not (
            isinstance(healthcare_price_erosion_overlay_flag, float)
            and pd.isna(healthcare_price_erosion_overlay_flag)
        ):
            healthcare_price_erosion_overlay = bool(healthcare_price_erosion_overlay_flag)
        else:
            from value_investor.scoring.healthcare_price_erosion_overlay import (
                price_erosion_for_ticker,
            )

            healthcare_price_erosion_overlay, adjusted_signal_str = (
                apply_healthcare_price_erosion_overlay_to_signal(
                    signal,
                    sector=row.get("sector"),
                    passed_families=row.get("passed_families"),
                    ticker_models=ticker_models,
                    price_erosion_detected=price_erosion_for_ticker(
                        ticker,
                        output_dir=output_dir,
                    ),
                    adjusted_signal=adjusted_signal_str,
                )
            )

        conviction_score = float(row.get("conviction_score") or 0)
        earnings_basis_overlay_flag = row.get("earnings_basis_overlay")
        if earnings_basis_overlay_flag is not None and not (
            isinstance(earnings_basis_overlay_flag, float) and pd.isna(earnings_basis_overlay_flag)
        ):
            earnings_basis_overlay = bool(earnings_basis_overlay_flag)
        else:
            statutory_growth = resolve_statutory_earnings_growth(row)
            adjusted_metric = row.get("adjusted_eps_growth_pct")
            adjusted_growth = (
                float(adjusted_metric)
                if adjusted_metric is not None
                and not (isinstance(adjusted_metric, float) and pd.isna(adjusted_metric))
                else None
            )
            earnings_basis_overlay, adjusted_signal_str, conviction_score = (
                apply_earnings_basis_overlay_to_signal(
                    signal,
                    statutory_growth=statutory_growth,
                    adjusted_growth=adjusted_growth,
                    ticker_models=ticker_models,
                    conviction_score=conviction_score,
                    adjusted_signal=adjusted_signal_str,
                )
            )

        fcf_basis_overlay_flag = row.get("fcf_basis_overlay")
        if fcf_basis_overlay_flag is not None and not (
            isinstance(fcf_basis_overlay_flag, float) and pd.isna(fcf_basis_overlay_flag)
        ):
            fcf_basis_overlay = bool(fcf_basis_overlay_flag)
        else:
            fcf_basis_overlay, adjusted_signal_str, conviction_score = (
                apply_fcf_basis_overlay_to_signal(
                    signal,
                    divergence_flagged=bool(fcf_bundle.get("divergence_flagged")),
                    filing_screen_mismatch=bool(fcf_bundle.get("filing_screen_mismatch"))
                    or fcf_filing_screen_mismatch(
                        filing_aligned=fcf_bundle.get("filing_aligned"),
                        screen_ttm=screen_ttm,
                        divergence_flagged=bool(fcf_bundle.get("divergence_flagged")),
                    ),
                    ticker_models=ticker_models,
                    conviction_score=conviction_score,
                    adjusted_signal=adjusted_signal_str,
                )
            )

        leverage_override_flag = row.get("leverage_override")
        leverage_override = (
            bool(leverage_override_flag)
            if leverage_override_flag is not None
            and not (isinstance(leverage_override_flag, float) and pd.isna(leverage_override_flag))
            else False
        )
        dual_display_flag = row.get("dual_leverage_display")
        dual_leverage_display = (
            bool(dual_display_flag)
            if dual_display_flag is not None
            and not (isinstance(dual_display_flag, float) and pd.isna(dual_display_flag))
            else False
        )
        yahoo_de_raw = row.get("debt_to_equity_yahoo")
        debt_to_equity_yahoo = (
            float(yahoo_de_raw)
            if yahoo_de_raw is not None
            and not (isinstance(yahoo_de_raw, float) and pd.isna(yahoo_de_raw))
            else None
        )
        filing_net_debt_raw = row.get("filing_adjusted_net_debt_gbp")
        filing_adjusted_net_debt_gbp = (
            float(filing_net_debt_raw)
            if filing_net_debt_raw is not None
            and not (isinstance(filing_net_debt_raw, float) and pd.isna(filing_net_debt_raw))
            else None
        )

        research_verdict = row.get("research_verdict")
        research_verdict_str = (
            str(research_verdict)
            if research_verdict is not None
            and not (isinstance(research_verdict, float) and pd.isna(research_verdict))
            else None
        )
        research_risk = row.get("research_risk_level")
        research_risk_str = (
            str(research_risk)
            if research_risk is not None
            and not (isinstance(research_risk, float) and pd.isna(research_risk))
            else None
        )
        research_conf = row.get("research_confidence")
        research_confidence = (
            float(research_conf)
            if research_conf is not None
            and not (isinstance(research_conf, float) and pd.isna(research_conf))
            else None
        )
        research_rat = row.get("research_rationale")
        research_rationale_str = (
            str(research_rat)
            if research_rat is not None
            and not (isinstance(research_rat, float) and pd.isna(research_rat))
            else None
        )

        cashflow_metrics = dict(fcf_bundle.get("cashflow_metrics") or {})
        if operating_cashflow is not None:
            cashflow_metrics["operating_cashflow"] = operating_cashflow
        if free_cashflow is not None:
            cashflow_metrics["free_cashflow"] = free_cashflow
        filing_aligned = fcf_bundle.get("filing_aligned")
        if fcf_filing_screen_mismatch(
            filing_aligned=filing_aligned if filing_aligned is not None else free_cashflow,
            screen_ttm=screen_ttm,
            divergence_flagged=bool(fcf_bundle.get("divergence_flagged")),
        ):
            overlay_coverage = fcf_dividend_coverage(free_cashflow, dividends_paid)
            if overlay_coverage is not None:
                fcf_dividend_coverage_net = overlay_coverage
        if fcf_dividend_coverage_gross is not None:
            cashflow_metrics["fcf_dividend_coverage_gross"] = fcf_dividend_coverage_gross
        if fcf_dividend_coverage_net is not None:
            cashflow_metrics["fcf_dividend_coverage_net"] = fcf_dividend_coverage_net

        peer_model_pass_table: dict[str, Any] = {}
        if signal in ("strong_buy", "buy"):
            if output_dir is not None:
                peer_model_pass_table = attach_peer_model_pass_table(
                    Path(output_dir) / "research" / ticker / "sources",
                    ticker,
                    sector=row.get("sector"),
                    output_dir=output_dir,
                )
            else:
                peer_model_pass_table = build_peer_model_pass_table(
                    ticker,
                    sector=row.get("sector"),
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
            conviction_score=conviction_score,
            stability_label=str(row.get("stability_label") or "new"),
            timing_signal=str(row.get("timing_signal") or "insufficient_data"),
            timing_score=float(row.get("timing_score") or 0),
            rsi_14=float(row["rsi_14"])
            if row.get("rsi_14") is not None and not pd.isna(row.get("rsi_14"))
            else None,
            timing_reasons=timing_reasons,
            action_note=action_note,
            trade_plan=trade_plan,
            passed_model_names=passed_model_names,
            passed_reasons=passed_reasons,
            near_miss_failures=near_miss_failures,
            key_metrics=key_metrics,
            research_verdict=research_verdict_str,
            adjusted_signal=adjusted_signal_str,
            healthcare_overlay=healthcare_overlay,
            healthcare_price_erosion_overlay=healthcare_price_erosion_overlay,
            cash_conversion_overlay=cash_conversion_overlay,
            dividend_yield_overlay=dividend_yield_overlay,
            interim_quality_overlay=interim_quality_overlay,
            cyclical_exposure_overlay=cyclical_exposure_overlay,
            earnings_basis_overlay=earnings_basis_overlay,
            earnings_growth_bps_divergence_warning=earnings_growth_bps_divergence_warning,
            fcf_basis_overlay=fcf_basis_overlay,
            leverage_override=leverage_override,
            dual_leverage_display=dual_leverage_display,
            debt_to_equity_yahoo=debt_to_equity_yahoo,
            filing_adjusted_net_debt_gbp=filing_adjusted_net_debt_gbp,
            fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
        )

        vs_sma = row.get("price_vs_sma200_pct")
        price_vs_sma200_pct = float(vs_sma) if vs_sma is not None and not pd.isna(vs_sma) else None

        fcf_snapshot = {
            key: value
            for key, value in fcf_bundle.items()
            if key != "cashflow_metrics" and value is not None
        }
        if fcf_definition_divergence:
            fcf_snapshot["fcf_definition_divergence"] = True
        if fcf_divergence_flagged:
            fcf_snapshot["fcf_divergence_flagged"] = True

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
                conviction_score=conviction_score,
                stability_label=str(row.get("stability_label") or "new"),
                timing_signal=str(row.get("timing_signal") or "insufficient_data"),
                timing_score=float(row.get("timing_score") or 0),
                rsi_14=float(row["rsi_14"])
                if row.get("rsi_14") is not None and not pd.isna(row.get("rsi_14"))
                else None,
                price_vs_sma200_pct=price_vs_sma200_pct,
                action_note=action_note,
                trade_plan=trade_plan,
                summary=summary,
                passed_models=passed_model_names,
                key_metrics=key_metrics,
                failed_models=failed_model_names,
                model_failures=model_failures,
                screening_inputs=screening_inputs,
                cashflow_metrics=cashflow_metrics or None,
                fcf=fcf_snapshot or None,
                piotroski_f_score=piotroski_f_score,
                healthcare_overlay=healthcare_overlay,
                healthcare_price_erosion_overlay=healthcare_price_erosion_overlay,
                cash_conversion_overlay=cash_conversion_overlay,
                dividend_yield_overlay=dividend_yield_overlay,
                interim_quality_overlay=interim_quality_overlay,
                cyclical_exposure_overlay=cyclical_exposure_overlay,
                cyclical_exposure_detected=cyclical_exposure_detected,
                earnings_basis_overlay=earnings_basis_overlay,
                earnings_growth_overlay=earnings_growth_overlay,
                earnings_growth_bps_divergence_warning=earnings_growth_bps_divergence_warning,
                peer_model_pass_table=peer_model_pass_table,
                fcf_basis_overlay=fcf_basis_overlay,
                leverage_override=leverage_override,
                dual_leverage_display=dual_leverage_display,
                operating_cashflow=operating_cashflow,
                fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
                fcf_dividend_coverage_net=fcf_dividend_coverage_net,
                fcf_dividend_coverage=labelled_fcf_dividend_coverage,
                fcf_definition_divergence=fcf_definition_divergence,
                fcf_divergence_flagged=fcf_divergence_flagged,
                adjusted_signal=adjusted_signal_str or signal,
                research_verdict=research_verdict_str,
                research_risk_level=research_risk_str,
                research_confidence=research_confidence,
                research_rationale=research_rationale_str,
            )
        )

    return reports
