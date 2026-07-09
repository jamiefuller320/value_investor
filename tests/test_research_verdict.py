"""Tests for research verdict parsing and overlay rules."""

import pytest

from value_investor.research.verdict import (
    adjust_conviction_for_research,
    compute_adjusted_signal,
    format_research_action_note,
    parse_research_verdict,
)


def test_parse_research_verdict():
    text = """Verdict: caution
Risk: medium
Confidence: 0.72
Rationale: Pension deficit not fully reflected in screen.
"""
    parsed = parse_research_verdict(text)
    assert parsed["research_verdict"] == "caution"
    assert parsed["research_risk_level"] == "medium"
    assert parsed["research_confidence"] == 0.72
    assert "Pension" in str(parsed["research_rationale"])


def test_parse_research_verdict_percent_confidence():
    parsed = parse_research_verdict("Verdict: accumulate\nConfidence: 85")
    assert parsed["research_verdict"] == "accumulate"
    assert parsed["research_confidence"] == 0.85


def test_compute_adjusted_signal_caution_downgrades_strong_buy():
    assert compute_adjusted_signal("strong_buy", "caution") == "buy"
    assert compute_adjusted_signal("buy", "caution") == "hold"
    assert compute_adjusted_signal("hold", "caution") == "hold"


def test_compute_adjusted_signal_pass_downgrades_buys():
    assert compute_adjusted_signal("strong_buy", "pass") == "hold"
    assert compute_adjusted_signal("buy", "pass") == "hold"


def test_compute_adjusted_signal_accumulate_unchanged():
    assert compute_adjusted_signal("strong_buy", "accumulate") == "strong_buy"
    assert compute_adjusted_signal("strong_buy", None) == "strong_buy"


def test_adjust_conviction_for_research():
    assert adjust_conviction_for_research(0.8, "accumulate") == pytest.approx(0.85)
    assert adjust_conviction_for_research(0.8, "caution") == pytest.approx(0.68)
    assert adjust_conviction_for_research(0.8, "pass") == pytest.approx(0.56)


def test_format_research_action_note():
    note = format_research_action_note(
        verdict="caution",
        risk_level="high",
        rationale="Governance concerns.",
        adjusted_signal="buy",
        signal="strong_buy",
    )
    assert note is not None
    assert "Caution" in note
    assert "adjusted to buy" in note
    assert "Governance" in note
