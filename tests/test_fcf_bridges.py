"""FCF bridge policy + fail-closed TTM + research gating."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from value_investor.research.document import ResearchDocument
from value_investor.research.overlay import apply_research_overlay
from value_investor.research.runner import eligible_research_targets, eligible_strong_buys
from value_investor.scoring.fcf import (
    enrich_universe_with_canonical_fcf,
    load_fcf_bridge,
    overlay_free_cashflow_from_bundle,
    reconcile_fcf,
    reconcile_fcf_for_ticker,
)
from value_investor.scoring.fcf_basis_overlay import enrich_signals_with_fcf_basis_overlay
from value_investor.summary import CompanyReport


def _itv_style_financials() -> dict:
    return {
        "ticker": "ITV.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 202_000_000.0,
                "Capital Expenditure": -54_000_000.0,
                "Free Cash Flow": 148_000_000.0,
            }
        },
    }


def _write_bridge(tmp_path: Path, ticker: str, payload: dict) -> None:
    sources = tmp_path / "research" / ticker / "sources"
    sources.mkdir(parents=True)
    (sources / "fcf_bridge.json").write_text(json.dumps(payload), encoding="utf-8")
    (sources / "financials_annual.json").write_text(
        json.dumps(_itv_style_financials()), encoding="utf-8"
    )


def test_load_fcf_bridge_and_policy_canonical(tmp_path: Path):
    _write_bridge(
        tmp_path,
        "ITV.L",
        {
            "ticker": "ITV.L",
            "fiscal_year": "2025",
            "period": "annual",
            "currency": "GBP",
            "resolved": True,
            "policy_basis": "company_adjusted",
            "policy_fcf": 187_000_000.0,
            "company_adjusted": 187_000_000.0,
            "screen_ttm": 211_900_000.0,
        },
    )
    bridge = load_fcf_bridge("ITV.L", output_dir=tmp_path)
    assert bridge is not None
    assert bridge["policy_fcf"] == 187_000_000.0

    bundle = reconcile_fcf_for_ticker("ITV.L", screen_ttm=211_900_000.0, output_dir=tmp_path)
    assert bundle["bridge_resolved"] is True
    assert bundle["canonical"] == 187_000_000.0
    assert bundle["source"] == "policy_company_adjusted"
    assert bundle["filing_screen_mismatch"] is True


def test_overlay_free_cashflow_fail_closed_on_mismatch_without_non_ttm_source():
    row = pd.Series({"free_cashflow": 211_900_000.0, "free_cashflow_screen_ttm": 211_900_000.0})
    bundle = reconcile_fcf(
        screen_ttm=211_900_000.0,
        financials=None,
        company_adjusted=None,
        filing_currency="GBP",
    )
    # Mismatch with no filing/company/policy figure — must not fall back to Yahoo TTM.
    bundle["filing_aligned"] = None
    bundle["filing_screen_mismatch"] = True
    bundle["divergence_flagged"] = True
    bundle["source"] = "screen_ttm"
    bundle["canonical"] = 211_900_000.0
    assert overlay_free_cashflow_from_bundle(row, bundle) is None


def test_enrich_universe_never_keeps_divergent_yahoo_ttm(tmp_path: Path):
    # Synthetic ticker avoids the committed ITV.L bridge under docs/data/research.
    financials = {
        "ticker": "ZZZZ.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 202_000_000.0,
                "Capital Expenditure": -54_000_000.0,
                "Free Cash Flow": 148_000_000.0,
            }
        },
    }
    sources = tmp_path / "research" / "ZZZZ.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")
    universe = pd.DataFrame([{"ticker": "ZZZZ.L", "free_cashflow": 211_900_000.0}])
    enriched = enrich_universe_with_canonical_fcf(universe, output_dir=tmp_path)
    assert enriched.iloc[0]["free_cashflow_screen_ttm"] == 211_900_000.0
    # Filing-aligned 148m replaces divergent Yahoo TTM as live FCF.
    assert enriched.iloc[0]["free_cashflow"] == pytest.approx(148_000_000.0)


def test_fcf_basis_overlay_caps_strong_buy_on_25pct_mismatch_without_yield_pass(
    tmp_path: Path,
):
    sources = tmp_path / "research" / "ITV.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(_itv_style_financials()), encoding="utf-8"
    )
    signals = pd.DataFrame(
        [
            {
                "ticker": "ITV.L",
                "signal": "strong_buy",
                "conviction_score": 0.6,
                "free_cashflow": 148_000_000.0,
                "free_cashflow_screen_ttm": 211_900_000.0,
            }
        ]
    )
    # No fcf_yield / composite_value / quality_value pass — 25% mismatch alone must cap.
    model_results = pd.DataFrame(
        [
            {
                "ticker": "ITV.L",
                "model_id": "graham_net_net",
                "model_name": "Graham",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )
    enriched = enrich_signals_with_fcf_basis_overlay(signals, model_results, output_dir=tmp_path)
    assert bool(enriched.iloc[0]["fcf_basis_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"
    assert enriched.iloc[0]["conviction_score"] == pytest.approx(0.51)


def test_research_overlay_preserves_fcf_basis_cap():
    report = CompanyReport(
        ticker="ITV.L",
        name="ITV",
        sector="Media",
        signal="strong_buy",
        models_passed=8,
        model_count=18,
        composite_score=0.8,
        sector_composite_score=0.7,
        families_passed=3,
        passed_families="cheapness,quality,dividend",
        data_quality_score=0.9,
        metrics_present=18,
        metrics_total=20,
        weeks_at_signal=2,
        signal_trend="stable",
        conviction_score=0.6,
        stability_label="building",
        timing_signal="accumulate",
        timing_score=0.7,
        rsi_14=40.0,
        price_vs_sma200_pct=-0.05,
        action_note="Strong Buy",
        trade_plan=None,
        summary="Screen strong buy.",
        passed_models=["graham"],
        key_metrics={},
        fcf_basis_overlay=True,
        adjusted_signal="buy",
    )
    doc = ResearchDocument(
        ticker="ITV.L",
        name="ITV",
        signal="strong_buy",
        version=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-02T00:00:00+00:00",
        mode="initial",
        research_verdict="accumulate",
        research_risk_level="low",
        research_confidence=0.8,
        research_rationale="Thesis intact.",
    )
    updated = apply_research_overlay([report], [doc])[0]
    assert updated.adjusted_signal == "buy"
    assert updated.fcf_basis_overlay is True
    assert updated.conviction_score == pytest.approx(0.51)


def test_eligible_research_targets_uses_adjusted_signal_and_blocks_unresolved_mismatch():
    capped = CompanyReport(
        ticker="ITV.L",
        name="ITV",
        sector="Media",
        signal="strong_buy",
        models_passed=8,
        model_count=18,
        composite_score=0.8,
        sector_composite_score=0.7,
        families_passed=3,
        passed_families="cheapness,quality,dividend",
        data_quality_score=0.9,
        metrics_present=18,
        metrics_total=20,
        weeks_at_signal=2,
        signal_trend="stable",
        conviction_score=0.6,
        stability_label="building",
        timing_signal="accumulate",
        timing_score=0.7,
        rsi_14=40.0,
        price_vs_sma200_pct=-0.05,
        action_note="capped",
        trade_plan=None,
        summary="capped",
        passed_models=[],
        key_metrics={},
        fcf_basis_overlay=True,
        adjusted_signal="buy",
        fcf={"filing_screen_mismatch": True, "bridge_resolved": True},
    )
    unresolved = CompanyReport(
        ticker="ZZZ.L",
        name="Zed",
        sector="Media",
        signal="buy",
        models_passed=5,
        model_count=18,
        composite_score=0.7,
        sector_composite_score=0.6,
        families_passed=2,
        passed_families="cheapness,quality",
        data_quality_score=0.9,
        metrics_present=18,
        metrics_total=20,
        weeks_at_signal=1,
        signal_trend="new",
        conviction_score=0.55,
        stability_label="new",
        timing_signal="neutral",
        timing_score=0.5,
        rsi_14=50.0,
        price_vs_sma200_pct=0.0,
        action_note="mismatch",
        trade_plan=None,
        summary="mismatch",
        passed_models=[],
        key_metrics={},
        adjusted_signal="buy",
        fcf={"filing_screen_mismatch": True, "bridge_resolved": False},
    )
    assert eligible_strong_buys([capped]) == []
    eligible = eligible_research_targets([capped, unresolved], weekly_cap=8)
    assert [r.ticker for r in eligible] == ["ITV.L"]


def test_committed_bridges_resolve_policy_for_itv_fgp_hik():
    for ticker, screen_ttm, expected in [
        ("ITV.L", 211_900_000.0, 187_000_000.0),
        ("FGP.L", 302_800_000.0, 113_500_000.0),
        ("HIK.L", 14_400_000.0, 119_000_000.0),
    ]:
        bridge = load_fcf_bridge(ticker)
        assert bridge is not None and bridge.get("resolved") is True
        bundle = reconcile_fcf_for_ticker(ticker, screen_ttm=screen_ttm)
        assert bundle["bridge_resolved"] is True
        assert bundle["canonical"] == pytest.approx(expected)
        assert bundle["source"].startswith("policy_")
