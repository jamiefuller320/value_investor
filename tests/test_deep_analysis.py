"""Tests for deep analysis response parsing."""

from value_investor.deep_analysis import _parse_deep_analysis


def test_parse_deep_analysis_splits_sections():
    text = """EXECUTIVE INTRO
Markets look selective with few strong buys.

TOP PICKS ANALYSIS
Alpha PLC looks attractive on cheapness and quality screens.

RED FLAGS
Watch cyclical exposure in energy names.

NAMES WORTH DEEPER RESEARCH
- AAA.L — confirm pension deficit size
"""
    result = _parse_deep_analysis(text)

    assert "selective" in result.executive_intro
    assert "Alpha PLC" in result.top_picks_analysis
    assert "cyclical" in result.red_flags
    assert "AAA.L" in result.red_flags
    assert "Red flags" not in result.red_flags
