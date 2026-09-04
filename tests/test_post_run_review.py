"""Tests for post-run synthesis payload and parsing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.deep_analysis import DeepAnalysis
from value_investor.post_run_review import (
    PostRunReview,
    _parse_post_run_review,
    build_post_run_payload,
)
from value_investor.research.format import format_post_run_review_text
from value_investor.summary import CompanyReport


def _report(ticker: str, name: str, signal: str = "strong_buy") -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=name,
        sector="Industrials",
        signal=signal,
        models_passed=5,
        model_count=10,
        composite_score=0.7,
        sector_composite_score=0.8,
        families_passed=4,
        passed_families="cheapness,quality",
        data_quality_score=0.9,
        metrics_present=18,
        metrics_total=20,
        weeks_at_signal=1,
        signal_trend="new",
        conviction_score=0.5,
        stability_label="new",
        timing_signal="neutral",
        timing_score=0.0,
        rsi_14=50.0,
        price_vs_sma200_pct=0.0,
        action_note="",
        trade_plan=None,
        summary="test",
        passed_models=[],
        key_metrics={},
    )


def test_parse_post_run_review_splits_sections():
    text = """EXECUTIVE SUMMARY
Filing ingest is the main blocker.

PERSISTENT WEAKNESSES
- Missing RNS bodies across buy tier

THIS WEEK'S FINDINGS
HIK.L partially resolved cash bridge.

PRIORITISED IMPROVEMENT PLAN
1. [ingest] Fix Investegate fetch — unlocks 3+ tickers

DEFER
- LSE liquidity overlay until ingest stabilises
"""
    review = _parse_post_run_review(text)
    assert "Filing ingest" in review.executive_summary
    assert "Missing RNS" in review.persistent_weaknesses
    assert "HIK.L" in review.this_week_findings
    assert "[ingest]" in review.improvement_plan
    assert "liquidity" in review.defer
    assert "PRIORITISED IMPROVEMENT PLAN" in review.full_text


def test_build_post_run_payload_aggregates_suggestions(tmp_path: Path):
    output_dir = tmp_path / "output"
    suggestions_path = tmp_path / "suggestions.json"
    suggestions_path.write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "ticker": "HIK.L",
                        "area": "ingest",
                        "priority": "high",
                        "suggestion": "Fetch IR PDF bodies",
                        "recorded_at": "2026-07-24T21:00:00+00:00",
                    },
                    {
                        "ticker": "MEGP.L",
                        "area": "scoring",
                        "priority": "medium",
                        "suggestion": "Export failed_models",
                        "recorded_at": "2026-07-20T12:00:00+00:00",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = build_post_run_payload(
        reports=[_report("HIK.L", "Hikma"), _report("MEGP.L", "ME Group")],
        output_dir=output_dir,
        run_at=datetime(2026, 7, 24, 21, 0, tzinfo=UTC),
        deep_analysis=DeepAnalysis(
            executive_intro="Cautious tape.",
            top_picks_analysis="HIK looks cheap.",
            red_flags="HIK.L: negative TTM FCF",
        ),
        suggestions_path=suggestions_path,
    )

    assert payload["buy_tier_count"] == 2
    assert payload["deep_analysis"]["executive_intro"] == "Cautious tape."
    assert payload["suggestions_backlog"]["total"] == 2
    assert payload["suggestions_backlog"]["by_area"]["ingest"] == 1
    assert len(payload["filing_coverage"]) == 2
    assert payload["system_gaps"] is not None
    assert payload["system_gaps"]["healthy_counter_distrust"]


def test_format_post_run_review_text():
    review = PostRunReview(
        executive_summary="Ingest gaps dominate.",
        persistent_weaknesses="",
        this_week_findings="",
        improvement_plan="1. [ingest] Fix RNS bodies",
        defer="",
    )
    text = format_post_run_review_text(review)
    assert text is not None
    assert "Ingest gaps dominate" in text
    assert "1. [ingest]" in text
