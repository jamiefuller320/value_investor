"""Tests for dashboard overlay refresh before paper automation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from value_investor.research.document import ResearchDocument
from value_investor.research.overlay_refresh import refresh_dashboard_bundle
from value_investor.research.store import ResearchStore
from value_investor.storage import write_json


def test_refresh_dashboard_bundle_from_research_index(tmp_path: Path):
    bundle_path = tmp_path / "latest.json"
    write_json(
        bundle_path,
        {
            "run_at": "2026-07-20T00:00:00+00:00",
            "reports": [
                {
                    "ticker": "AAA.L",
                    "name": "Alpha",
                    "signal": "strong_buy",
                    "models_passed": 10,
                    "model_count": 20,
                    "composite_score": 0.8,
                    "sector_composite_score": 0.7,
                    "families_passed": 4,
                    "data_quality_score": 0.9,
                    "metrics_present": 18,
                    "metrics_total": 20,
                    "weeks_at_signal": 1,
                    "signal_trend": "new",
                    "conviction_score": 0.5,
                    "stability_label": "new",
                    "timing_signal": "neutral",
                    "timing_score": 0.0,
                    "action_note": "",
                    "summary": "Screen only",
                    "passed_models": [],
                    "key_metrics": {},
                    "research_verdict": "Verdict: pass\nRisk: high",
                    "adjusted_signal": "hold",
                }
            ],
            "research": [
                {
                    "ticker": "AAA.L",
                    "name": "Alpha",
                    "version": 2,
                    "updated_at": "2026-07-20T00:00:00+00:00",
                    "research_verdict": "accumulate",
                    "research_risk_level": "medium",
                    "research_confidence": 0.72,
                }
            ],
        },
        compact=True,
    )

    count = refresh_dashboard_bundle(bundle_path, output_dir=tmp_path / "output")
    assert count == 1

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    report = bundle["reports"][0]
    assert report["research_verdict"] == "accumulate"
    assert report["adjusted_signal"] == "strong_buy"
    assert report["research_confidence"] == 0.72


def test_refresh_dashboard_bundle_prefers_output_research_store(tmp_path: Path):
    output_dir = tmp_path / "output"
    ticker_dir = output_dir / "research" / "BBB.L"
    ticker_dir.mkdir(parents=True)
    write_json(
        ticker_dir / "research.json",
        ResearchDocument(
            ticker="BBB.L",
            name="Beta",
            signal="buy",
            version=1,
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T00:00:00+00:00",
            mode="initial",
            research_verdict="caution",
            research_risk_level="high",
            research_confidence=0.4,
        ).to_dict(),
        compact=True,
    )

    bundle_path = tmp_path / "latest.json"
    write_json(
        bundle_path,
        {
            "reports": [
                {
                    "ticker": "BBB.L",
                    "name": "Beta",
                    "signal": "strong_buy",
                    "models_passed": 8,
                    "model_count": 20,
                    "composite_score": 0.7,
                    "sector_composite_score": 0.6,
                    "families_passed": 3,
                    "data_quality_score": 0.8,
                    "metrics_present": 16,
                    "metrics_total": 20,
                    "weeks_at_signal": 1,
                    "signal_trend": "new",
                    "conviction_score": 0.6,
                    "stability_label": "new",
                    "timing_signal": "neutral",
                    "timing_score": 0.0,
                    "action_note": "",
                    "summary": "",
                    "passed_models": [],
                    "key_metrics": {},
                }
            ],
            "research": [
                {
                    "ticker": "BBB.L",
                    "name": "Beta",
                    "research_verdict": "accumulate",
                }
            ],
        },
        compact=True,
    )

    count = refresh_dashboard_bundle(bundle_path, output_dir=output_dir)
    assert count == 1
    assert ResearchStore(output_dir).list_documents()[0].research_verdict == "caution"

    report = json.loads(bundle_path.read_text(encoding="utf-8"))["reports"][0]
    assert report["research_verdict"] == "caution"
    assert report["adjusted_signal"] == "buy"


def _minimal_report(**overrides: object) -> dict:
    row = {
        "ticker": "AAA.L",
        "name": "Alpha",
        "signal": "strong_buy",
        "models_passed": 10,
        "model_count": 20,
        "composite_score": 0.8,
        "sector_composite_score": 0.7,
        "families_passed": 4,
        "data_quality_score": 0.9,
        "metrics_present": 18,
        "metrics_total": 20,
        "weeks_at_signal": 1,
        "signal_trend": "new",
        "conviction_score": 0.5,
        "stability_label": "new",
        "timing_signal": "neutral",
        "timing_score": 0.0,
        "action_note": "",
        "summary": "Screen only",
        "passed_models": [],
        "key_metrics": {},
        "price": 12.5,
    }
    row.update(overrides)
    return row


def test_refresh_preserves_sunday_eps_fcf_and_overlay_flags(tmp_path: Path):
    """Weekday overlay rebuild must not zero filing-derived EPS / overlay flags."""
    bundle_path = tmp_path / "latest.json"
    write_json(
        bundle_path,
        {
            "reports": [
                _minimal_report(
                    ticker="MEGP.L",
                    name="ME Group",
                    fcf_basis_overlay=True,
                    healthcare_overlay=True,
                    interim_quality_overlay=True,
                    interim_eps_decline_pct=0.039,
                    adjusted_eps_growth_pct=0.12,
                    research_verdict="accumulate",
                    adjusted_signal="buy",
                )
            ],
            "research": [
                {
                    "ticker": "MEGP.L",
                    "name": "ME Group",
                    "research_verdict": "accumulate",
                    "research_confidence": 0.8,
                }
            ],
        },
        compact=True,
    )

    assert refresh_dashboard_bundle(bundle_path, output_dir=tmp_path / "output") == 1
    report = json.loads(bundle_path.read_text(encoding="utf-8"))["reports"][0]
    assert report["interim_eps_decline_pct"] == pytest.approx(0.039)
    assert report["adjusted_eps_growth_pct"] == pytest.approx(0.12)
    assert report["fcf_basis_overlay"] is True
    assert report["healthcare_overlay"] is True
    assert report["interim_quality_overlay"] is True
    assert report["overlay_bound"] is True
    assert report["price"] == 12.5
    assert report["research_verdict"] == "accumulate"


def test_p1_roundtrip_producer_overlay_slim_and_agree_veto(tmp_path: Path):
    """Filing-body EPS lands on the screen frame, survives overlay, and freezes on slim."""
    import pandas as pd

    from value_investor.llm_agree_veto_shadow import judge_proposal
    from value_investor.rebalance_log import slim_candidate
    from value_investor.scoring.fcf import enrich_universe_with_filing_metrics

    ticker = "MEGP.L"
    research_root = tmp_path / "research"
    sources = research_root / ticker / "sources"
    filings_dir = sources / "filings" / "bodies"
    filings_dir.mkdir(parents=True)
    interim_body = filings_dir / "interim.txt"
    annual_body = filings_dir / "annual.txt"
    interim_body.write_text(
        "Diluted earnings per share of 6.48 pence, a decline of 3.9% "
        "(H1 2025: 6.74 pence per share).",
        encoding="utf-8",
    )
    annual_body.write_text("Adjusted EPS +12.0% versus prior year.\n", encoding="utf-8")
    write_json(
        sources / "filings" / "filings_index.json",
        {
            "fetched_at": "2026-07-13T00:00:00+00:00",
            "summary": {
                "total": 2,
                "with_body": 2,
                "period_coverage": {
                    "annual": {"total": 1, "with_body": 1},
                    "interim": {"total": 1, "with_body": 1},
                },
            },
            "filings": [
                {
                    "id": "interim",
                    "period": "interim",
                    "has_body": True,
                    "body_path": str(interim_body),
                    "published_at": "2026-07-13",
                },
                {
                    "id": "annual",
                    "period": "annual",
                    "has_body": True,
                    "body_path": str(annual_body),
                    "published_at": "2026-03-01",
                },
            ],
        },
        compact=True,
    )
    write_json(
        sources / "financials_annual.json",
        {
            "cash_flow": {
                "2025": {
                    "Operating Cash Flow": 90_762_000.0,
                    "Free Cash Flow": 25_153_000.0,
                    "Cash Dividends Paid": -29_769_000.0,
                }
            },
            "income_statement": {"2025": {"Normalized Income": 55_047_230.0}},
        },
        compact=True,
    )

    universe = pd.DataFrame([{"ticker": ticker, "name": "ME Group International plc"}])
    enriched = enrich_universe_with_filing_metrics(universe, tmp_path)
    row = enriched.iloc[0]
    assert row["interim_eps_decline_pct"] == pytest.approx(0.039)

    bundle_path = tmp_path / "latest.json"
    write_json(
        bundle_path,
        {
            "reports": [
                _minimal_report(
                    ticker=ticker,
                    name="ME Group International plc",
                    fcf_basis_overlay=False,
                    interim_eps_decline_pct=float(row["interim_eps_decline_pct"]),
                    research_verdict="accumulate",
                    adjusted_signal="strong_buy",
                )
            ],
            "research": [
                {
                    "ticker": ticker,
                    "name": "ME Group International plc",
                    "research_verdict": "accumulate",
                    "research_confidence": 0.81,
                }
            ],
        },
        compact=True,
    )

    assert (
        refresh_dashboard_bundle(
            bundle_path,
            output_dir=tmp_path / "output",
            committed_dir=research_root,
        )
        == 1
    )
    report = json.loads(bundle_path.read_text(encoding="utf-8"))["reports"][0]
    assert report["interim_eps_decline_pct"] == pytest.approx(0.039)
    assert report["filings_with_body"] == 2
    assert report["key_filing_bodies"] is True
    assert report["has_index"] is True
    assert report["overlay_bound"] is True
    assert report["fcf_basis_overlay"] is False

    slim = slim_candidate(report)
    assert slim["fcf_basis_overlay"] is False
    assert slim["key_filing_bodies"] is True
    assert slim["filings_with_body"] == 2
    assert slim["overlay_bound"] is True
    assert slim["interim_eps_decline_pct"] == pytest.approx(0.039)

    card = judge_proposal(
        {
            "ticker": ticker,
            "name": "ME Group International plc",
            "algo_action": "hold",
            "algo_reason": "Near target",
        },
        candidate=slim,
        buy_ranks={ticker: 1},
        entry_ranks={ticker: 1},
        holdings_before={ticker},
        track_id="ai_judgment",
    )
    kinds = {item["kind"] for item in card.evidence}
    assert "filing_presence" in kinds
    assert "fcf_basis_overlay" in kinds
    assert "overlay_bound" in kinds
    assert "interim_eps_decline_pct" in kinds
    assert card.influences_live is False
    assert card.observe_only is True
    assert card.shadow_verdict == "agree"
