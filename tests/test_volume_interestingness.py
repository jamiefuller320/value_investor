"""Unit tests for thickness vs alone-path interestingness split."""

from __future__ import annotations

from value_investor.volume_interestingness import (
    N200_INTERESTINGNESS_TITLE,
    N201_INTERESTINGNESS_TITLE,
    evaluate_n200_interestingness,
    evaluate_n201_interestingness,
    evaluate_n206_interestingness,
    evaluate_n210_interestingness,
    interestingness_finding,
)


def test_n200_blocked_by_exit_lose_and_nonpositive_path():
    thick = {"volume_gate": {"met": True}}
    assert (
        evaluate_n200_interestingness(
            {
                **thick,
                "path_scoreboard": {"control_smooth_ret_cohort_median": 0.01},
                "per_lever_scoreboards": {"exit_verdict": "lose"},
            }
        )["met"]
        is False
    )
    assert (
        evaluate_n200_interestingness(
            {
                **thick,
                "path_scoreboard": {"control_smooth_ret_cohort_median": -0.01},
                "per_lever_scoreboards": {"exit_verdict": "win"},
            }
        )["met"]
        is False
    )
    gate = evaluate_n200_interestingness(
        {
            **thick,
            "path_scoreboard": {"control_smooth_ret_cohort_median": 0.01},
            "per_lever_scoreboards": {"exit_verdict": "win"},
        }
    )
    assert gate["met"] is True
    finding = interestingness_finding(
        title=N200_INTERESTINGNESS_TITLE, gate=gate, strand_note="N200."
    )
    assert finding is not None
    assert finding["auto_fixable"] is False


def test_n201_requires_phase_and_excess():
    base = {
        "volume_gate": {"met": True},
        "phase": {"floor_met": True},
        "path_scoreboard": {
            "smooth_ret_cohort_median": 0.03,
            "patient_hold_excess_report_only": 0.02,
        },
    }
    assert evaluate_n201_interestingness(base)["met"] is True
    no_excess = {
        **base,
        "path_scoreboard": {
            "smooth_ret_cohort_median": 0.03,
            "patient_hold_excess_report_only": 0.0,
        },
    }
    assert evaluate_n201_interestingness(no_excess)["met"] is False
    finding = interestingness_finding(
        title=N201_INTERESTINGNESS_TITLE,
        gate=evaluate_n201_interestingness(base),
        strand_note="N201.",
    )
    assert "design-open" in finding["summary"]


def test_n206_and_n210_fair_median_only_after_thickness():
    thin = {
        "volume_gate": {"met": False},
        "path_scoreboard": {"smooth_ret_cohort_median": 0.05},
    }
    assert evaluate_n206_interestingness(thin)["met"] is False
    assert evaluate_n210_interestingness(thin)["met"] is False
    thick = {
        "volume_gate": {"met": True},
        "path_scoreboard": {"smooth_ret_cohort_median": 0.05},
    }
    assert evaluate_n206_interestingness(thick)["met"] is True
    assert evaluate_n206_interestingness(thick)["not_assessment_primary"] is True
    assert evaluate_n210_interestingness(thick)["met"] is True
