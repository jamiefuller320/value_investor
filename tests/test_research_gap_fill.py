"""Tests for deep-analysis red-flag extraction and gap-fill parsing."""

from __future__ import annotations

from value_investor.deep_analysis import DeepAnalysis, _parse_deep_analysis
from value_investor.research.document import parse_research_sections
from value_investor.research.format import format_gap_fill_text
from value_investor.research.gap_fill import GapFillSummary, GapFillTarget, extract_gap_fill_targets
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


def test_parse_deep_analysis_accepts_markdown_and_names_section():
    text = """## EXECUTIVE INTRO
Selective tape.

**TOP PICKS ANALYSIS**
AEP.L looks clean on balance sheet.

## NAMES WORTH DEEPER RESEARCH
- **AEP.L** — pending OCF / qualitative business review
- **ITV.L** — high yield vs cyclical ad market
"""
    parsed = _parse_deep_analysis(text)
    assert "Selective" in parsed.executive_intro
    assert "AEP.L looks clean" in parsed.top_picks_analysis
    assert "AEP.L" in parsed.red_flags
    assert "ITV.L" in parsed.red_flags


def test_parse_deep_analysis_fallback_splits_dumped_intro():
    text = """EXECUTIVE INTRO
Broad caution across the tape.

**Names worth deeper research (up to 3):** **AEP.L** (pristine metrics), **ITV.L** (timing + yield).
"""
    parsed = _parse_deep_analysis(text)
    assert "Broad caution" in parsed.executive_intro
    assert "AEP.L" in parsed.red_flags
    assert "Names worth deeper research" not in parsed.executive_intro


def test_extract_gap_fill_targets_from_red_flags():
    analysis = DeepAnalysis(
        executive_intro="Tone is cautious.",
        top_picks_analysis="",
        red_flags=(
            "NAMES WORTH DEEPER RESEARCH\n"
            "- **AEP.L** — pending OCF/qualitative business review\n"
            "- **ITV.L** — favourable accumulate timing plus high yield\n"
            "- **HIK.L** — negative FCF vs dividend puzzle\n"
        ),
    )
    reports = [
        _report("AEP.L", "Anglo-Eastern"),
        _report("ITV.L", "ITV", signal="buy"),
        _report("HIK.L", "Hikma", signal="buy"),
        _report("MEGP.L", "Morgan Sindall", signal="hold"),
    ]
    targets = extract_gap_fill_targets(analysis, reports, max_targets=3)
    assert [t.ticker for t in targets] == ["AEP.L", "ITV.L", "HIK.L"]
    assert any("OCF" in q for q in targets[0].questions)
    assert any("FCF" in q or "dividend" in q for q in targets[2].questions)


def test_parse_gap_fill_update_section():
    text = """GAP FILL UPDATE
Q: Is FCF negative structural?
Status: partially_resolved
Evidence: FY2025 cash flow still working-capital heavy.

FINANCIAL REVIEW
Filing bodies show operating cash positive.

RISKS AND RED FLAGS
Dividend cover remains the open debate.

RESEARCH VERDICT
Verdict: neutral
Risk: medium
Confidence: 0.55
Rationale: Gap-fill clarifies cash generation but not dividend sustainability.
"""
    sections = parse_research_sections(text)
    assert "partially_resolved" in sections["gap_fill_update"]
    assert "operating cash" in sections["financial_review"]
    assert "Dividend cover" in sections["risks_and_flags"]
    assert "Verdict: neutral" in sections["research_verdict"]


def test_format_gap_fill_text_lists_targets():
    report = _report("AEP.L", "Anglo-Eastern")
    summary = GapFillSummary(
        targets=[
            GapFillTarget(
                ticker="AEP.L",
                name="Anglo-Eastern",
                report=report,
                questions=["pending OCF review"],
            )
        ],
        updated=1,
    )
    text = format_gap_fill_text(summary)
    assert text is not None
    assert "AEP.L" in text
    assert "pending OCF" in text
