"""Core-lot sell trigger: failed reason, not a lost rank."""

from value_investor.core_sell_trigger import (
    RESEARCH_FAILED,
    SCREEN_AVOID,
    core_sell_reason,
    note_thesis_streak,
    thesis_break_confirmed,
)


def test_hard_avoid_is_a_core_sell_even_when_research_still_says_accumulate():
    assert core_sell_reason({"signal": "avoid", "research_verdict": "accumulate"}) == SCREEN_AVOID


def test_research_pass_is_a_core_sell_while_the_name_is_still_a_buy():
    assert core_sell_reason({"signal": "buy", "research_verdict": "pass"}) == RESEARCH_FAILED
    assert (
        core_sell_reason({"signal": "buy", "research_verdict": "Verdict: pass\nRisk: high"})
        == RESEARCH_FAILED
    )


def test_rank_caution_and_cheapness_do_not_sell_the_core():
    assert core_sell_reason({"signal": "hold", "research_verdict": "accumulate"}) is None
    assert core_sell_reason({"signal": "buy", "research_verdict": "caution"}) is None
    assert core_sell_reason({"signal": "buy", "research_verdict": "neutral"}) is None
    assert core_sell_reason({"signal": "", "passed_families": "quality"}) is None
    assert core_sell_reason(None) is None


def test_a_missing_row_does_not_advance_or_clear_the_streak():
    streaks: dict[str, int] = {}
    assert note_thesis_streak(streaks, "AAA.L", {"signal": "avoid"}) == 1
    assert note_thesis_streak(streaks, "AAA.L", None) == 1
    assert (
        note_thesis_streak(streaks, "AAA.L", {"signal": "buy", "research_verdict": "accumulate"})
        == 0
    )
    assert thesis_break_confirmed(1, 2) is False
    assert thesis_break_confirmed(2, 2) is True
