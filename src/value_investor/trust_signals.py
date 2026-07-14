"""Signal generation for the investment-trust screening track."""

from __future__ import annotations

from typing import Any

import pandas as pd

from value_investor.models.trusts import TRUST_MODEL_FAMILIES, TRUST_MODEL_TO_FAMILY
from value_investor.signals import SIGNAL_ORDER, Signal
from value_investor.trust_metrics import (
    MIN_TRUST_QUALITY_FOR_ANALYSIS,
    MIN_TRUST_QUALITY_FOR_BUY,
    MIN_TRUST_QUALITY_FOR_STRONG_BUY,
)


def summarize_trust_families(model_results: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker trust family pass counts (discount / income / risk)."""
    if model_results.empty:
        return pd.DataFrame()

    tagged = model_results.copy()
    tagged["family"] = tagged["model_id"].map(TRUST_MODEL_TO_FAMILY)
    tagged = tagged.dropna(subset=["family"])

    rows: list[dict[str, Any]] = []
    for ticker, group in tagged.groupby("ticker"):
        passed_families = sorted(
            family
            for family in TRUST_MODEL_FAMILIES
            if bool(group.loc[group["family"] == family, "passed"].any())
        )
        risk_rows = group[group["family"] == "risk"]
        risk_passed = bool(risk_rows["passed"].any()) if not risk_rows.empty else True
        risk_mean = float(risk_rows["score"].mean()) if not risk_rows.empty else 0.5
        rows.append(
            {
                "ticker": ticker,
                "families_passed": len(passed_families),
                "family_count": len(TRUST_MODEL_FAMILIES),
                "passed_families": ",".join(passed_families),
                "risk_family_passed": risk_passed,
                "risk_mean_score": risk_mean,
            }
        )
    return pd.DataFrame(rows)


def assign_trust_signal(
    *,
    models_passed: int,
    model_count: int,
    mean_model_score: float,
    composite_score: float | None,
    families_passed: int,
    data_quality_score: float,
    risk_family_passed: bool,
    risk_mean_score: float,
    has_errors: bool,
    discount_to_nav: float | None,
) -> Signal:
    """Map trust model output to a signal (thresholds sized for ~5 models)."""
    if has_errors or model_count == 0:
        return Signal.INSUFFICIENT_DATA
    if data_quality_score < MIN_TRUST_QUALITY_FOR_ANALYSIS:
        return Signal.INSUFFICIENT_DATA

    pass_rate = models_passed / model_count
    composite = composite_score if composite_score is not None else mean_model_score

    signal = Signal.AVOID
    if models_passed >= 3 and composite >= 0.65 and families_passed >= 2:
        signal = Signal.STRONG_BUY
    elif models_passed >= 2 and composite >= 0.50 and families_passed >= 1:
        signal = Signal.BUY
    elif pass_rate >= 0.2 or composite >= 0.40:
        signal = Signal.HOLD

    if signal == Signal.STRONG_BUY and data_quality_score < MIN_TRUST_QUALITY_FOR_STRONG_BUY:
        signal = Signal.BUY
    if signal == Signal.BUY and data_quality_score < MIN_TRUST_QUALITY_FOR_BUY:
        signal = Signal.HOLD

    # Rich premium veto
    if not risk_family_passed or risk_mean_score < 0.35:
        if signal == Signal.STRONG_BUY:
            signal = Signal.BUY
        elif signal == Signal.BUY:
            signal = Signal.HOLD

    # Prefer not strong-buying names at a premium even if other models fire.
    if (
        signal == Signal.STRONG_BUY
        and discount_to_nav is not None
        and not pd.isna(discount_to_nav)
        and float(discount_to_nav) < 0
    ):
        signal = Signal.BUY

    return signal


def build_trust_signals(
    universe: pd.DataFrame,
    model_results: pd.DataFrame,
    summary: pd.DataFrame,
) -> pd.DataFrame:
    """Assemble per-trust signal rows for reporting."""
    if universe.empty or summary.empty:
        return pd.DataFrame()

    family = summarize_trust_families(model_results)
    merged = universe.merge(summary, on="ticker", how="left")
    if not family.empty:
        merged = merged.merge(family, on="ticker", how="left")
    else:
        merged["families_passed"] = 0
        merged["family_count"] = len(TRUST_MODEL_FAMILIES)
        merged["passed_families"] = ""
        merged["risk_family_passed"] = True
        merged["risk_mean_score"] = 0.5

    # Composite for trusts: mean model score (no ops composite_value model).
    if "mean_model_score" in merged.columns:
        merged["composite_score"] = merged["mean_model_score"]
    else:
        merged["composite_score"] = None
    merged["sector_composite_score"] = None

    signals: list[str] = []
    for _, row in merged.iterrows():
        errors = row.get("errors")
        has_errors = bool(errors) and errors not in ("[]", "", None)
        if isinstance(errors, float) and pd.isna(errors):
            has_errors = False
        discount = row.get("discount_to_nav")
        discount_f = float(discount) if discount is not None and not pd.isna(discount) else None
        signal = assign_trust_signal(
            models_passed=int(row.get("models_passed") or 0),
            model_count=int(row.get("model_count") or 0),
            mean_model_score=float(row.get("mean_model_score") or 0),
            composite_score=(
                float(row["composite_score"])
                if row.get("composite_score") is not None and not pd.isna(row.get("composite_score"))
                else None
            ),
            families_passed=int(row.get("families_passed") or 0),
            data_quality_score=float(row.get("data_quality_score") or 0),
            risk_family_passed=bool(row.get("risk_family_passed", True)),
            risk_mean_score=float(row.get("risk_mean_score") or 0.5),
            has_errors=has_errors,
            discount_to_nav=discount_f,
        )
        signals.append(signal.value)

    merged["signal"] = signals
    merged["signal_rank"] = merged["signal"].map(
        lambda s: SIGNAL_ORDER.get(Signal(s), 0)
    )
    # Defaults expected by report/email enrichers
    for col, default in (
        ("weeks_at_signal", 1),
        ("signal_trend", "new"),
        ("conviction_score", 0.0),
        ("stability_label", "new"),
        ("timing_signal", "insufficient_data"),
        ("timing_score", 0.0),
        ("rsi_14", None),
        ("price_vs_sma200_pct", None),
        ("action_note", ""),
        ("weighted_model_score", None),
    ):
        if col not in merged.columns:
            merged[col] = default

    if "conviction_score" in merged.columns:
        # Simple conviction from composite × quality for trusts (no history yet).
        merged["conviction_score"] = (
            merged["composite_score"].fillna(0).clip(0, 1)
            * merged["data_quality_score"].fillna(0).clip(0, 1)
        )

    sort_cols = ["signal_rank", "conviction_score", "composite_score", "models_passed"]
    present = [c for c in sort_cols if c in merged.columns]
    return merged.sort_values(present, ascending=[False] * len(present)).reset_index(drop=True)
