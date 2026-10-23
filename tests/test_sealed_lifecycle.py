"""Phase clocks and chip returns for sealed observe lifecycle pages."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.lifecycle_board import JUST_BOUGHT_DAYS, JUST_SOLD_DAYS
from value_investor.sealed_lifecycle import (
    OPEN_MARK_BASIS,
    assign_sealed_phase,
    build_model_lifecycle,
    build_sealed_lifecycle_projection,
    chip_return,
    fair_cost_open_mark_return,
    slim_lifecycle_episode,
    with_fair_cost_open_mark,
)

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def _iso(day: str) -> str:
    return f"{day}T00:00:00+00:00"


def test_phase_and_days_use_existing_column_clocks() -> None:
    assert JUST_BOUGHT_DAYS == 14
    assert JUST_SOLD_DAYS == 14
    just = assign_sealed_phase(
        {"ticker": "NEW.L", "status": "open", "entry_run_at": _iso("2026-10-05")},
        now=NOW,
    )
    assert just is not None
    assert just["phase"] == "just_bought"
    assert just["days_in_phase"] == 14
    assert just["phase_clock"] == "entry_run_at"

    held = assign_sealed_phase(
        {"ticker": "HOLD.L", "status": "open", "entry_run_at": _iso("2026-09-01")},
        now=NOW,
    )
    assert held is not None
    assert held["phase"] == "holding"
    assert held["days_in_phase"] == 48
    assert held["phase_clock"] == "entry_run_at"

    sold = assign_sealed_phase(
        {
            "ticker": "SOLD.L",
            "status": "closed",
            "entry_run_at": _iso("2026-08-01"),
            "exit_run_at": _iso("2026-10-05"),
            "fair_cost_return": 0.01,
        },
        now=NOW,
    )
    assert sold is not None
    assert sold["phase"] == "just_sold"
    assert sold["days_in_phase"] == 14
    assert sold["phase_clock"] == "exit_run_at"

    post = assign_sealed_phase(
        {
            "ticker": "POST.L",
            "status": "closed",
            "entry_run_at": _iso("2026-08-01"),
            "exit_run_at": _iso("2026-10-04"),
            "return_pct": -0.02,
        },
        now=NOW,
    )
    assert post is not None
    assert post["phase"] == "post_sale"
    assert post["days_in_phase"] == 15


def test_missing_clock_date_skips_chip() -> None:
    assert (
        assign_sealed_phase(
            {"ticker": "NODATE.L", "status": "open"},
            now=NOW,
        )
        is None
    )
    assert (
        assign_sealed_phase(
            {"ticker": "NOEXIT.L", "status": "closed", "entry_run_at": _iso("2026-10-01")},
            now=NOW,
        )
        is None
    )
    assert (
        assign_sealed_phase(
            {"ticker": "", "status": "closed", "exit_run_at": _iso("2026-10-01")},
            now=NOW,
        )
        is None
    )


def test_closed_chip_uses_fair_cost_episode_not_median_or_stress() -> None:
    row = slim_lifecycle_episode(
        {
            "ticker": "ABDN.L",
            "entry_run_at": _iso("2026-08-02"),
            "exit_run_at": _iso("2026-08-10"),
            "control_return": 0.0344,
            "control_return_stress_report_only": -0.06,
            "return_pct_stress_report_only": -0.09,
            "patient_hold_return_pct_report_only": 0.5,
            "smooth_ret_cohort_median": -0.0055,
        }
    )
    assert row is not None
    assert row["fair_cost_return"] == 0.0344
    assert "control_return_stress_report_only" not in row
    pct, basis = chip_return(row)
    assert pct == 0.0344
    assert basis == "fair_cost_episode"

    page = build_model_lifecycle(
        {
            "generated_at": NOW.isoformat(),
            "registration_id": "strand-b-plain-value-tech-timing-v0",
            "path_scoreboard": {
                "control_smooth_ret_cohort_median": -0.0055,
                "sample_mean_close_delta": 0.0229,
            },
            "lifecycle_episodes": [row],
        },
        model_id="n200",
        label="N200",
        title="Plain value tech timing",
        registration_id="strand-b-plain-value-tech-timing-v0",
        now=NOW,
    )
    chips = page["columns"]["post_sale"]["chips"]
    assert len(chips) == 1
    assert chips[0]["return_pct"] == 0.0344
    assert chips[0]["return_basis"] == "fair_cost_episode"
    assert chips[0]["return_pct"] != page["cohort_median"]
    assert page["influences_live"] is False
    assert page["cohort_median"] == -0.0055


def test_fair_cost_open_mark_return_matches_closed_drag() -> None:
    # +10% gross, 0.5% buy + 0.1% sell → 0.094 (same as closed fair-cost).
    got = fair_cost_open_mark_return(100.0, 110.0, buy_cost_pct=0.005, sell_cost_pct=0.001)
    assert got == 0.094
    assert fair_cost_open_mark_return(0.0, 110.0, buy_cost_pct=0.0, sell_cost_pct=0.0) is None
    assert fair_cost_open_mark_return(100.0, -1.0, buy_cost_pct=0.0, sell_cost_pct=0.0) is None


def test_with_fair_cost_open_mark_fails_closed_without_quotes() -> None:
    base = {"ticker": "AAA.L", "status": "open", "entry_run_at": _iso("2026-10-18")}
    missing = with_fair_cost_open_mark(
        base,
        entry_price=None,
        mark_price=110.0,
        buy_cost_pct=0.005,
        sell_cost_pct=0.001,
    )
    assert "open_mark_return" not in missing
    marked = with_fair_cost_open_mark(
        base,
        entry_price=100.0,
        mark_price=110.0,
        buy_cost_pct=0.005,
        sell_cost_pct=0.001,
        mark_run_at=_iso("2026-10-19"),
    )
    assert marked["open_mark_return"] == 0.094
    assert marked["open_mark_basis"] == OPEN_MARK_BASIS
    assert marked["open_mark_at"] == _iso("2026-10-19")
    assert "influences_live" not in marked


def test_open_chip_uses_stored_mark_and_labels_it() -> None:
    marked = slim_lifecycle_episode(
        {
            "ticker": "OPEN.L",
            "status": "open",
            "entry_run_at": _iso("2026-10-18"),
            "open_mark_return": 0.012,
            "return_pct": 0.99,
            "smooth_ret_cohort_median": 0.007,
        }
    )
    assert marked is not None
    assert "fair_cost_return" not in marked
    pct, basis = chip_return(marked)
    assert pct == 0.012
    assert basis == "open_mark"
    chip = assign_sealed_phase(marked, now=NOW)
    assert chip is not None
    assert chip["phase"] == "just_bought"
    assert chip["days_in_phase"] == 1
    assert chip["return_basis"] == "open_mark"
    assert chip["exit_run_at"] is None

    unmarked = slim_lifecycle_episode(
        {
            "ticker": "GFRD.L",
            "status": "open",
            "entry_run_at": _iso("2026-10-18"),
        }
    )
    assert unmarked is not None
    pct_u, basis_u = chip_return(unmarked)
    assert pct_u is None
    assert basis_u == "open_unmarked"


def test_projection_keeps_only_sealed_observe_registrations(tmp_path: Path) -> None:
    def _write(name: str, payload: dict) -> None:
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")

    _write(
        "n200_tech_timing_registration.json",
        {
            "status": "sealed_observe_only",
            "registration_id": "strand-b-plain-value-tech-timing-v0",
            "influences_live": False,
        },
    )
    _write(
        "n200_tech_timing_observe.json",
        {
            "registration_id": "strand-b-plain-value-tech-timing-v0",
            "generated_at": NOW.isoformat(),
            "influences_live": False,
            "path_scoreboard": {"control_smooth_ret_cohort_median": -0.0055},
            "lifecycle_episodes": [
                {
                    "ticker": "ABDN.L",
                    "status": "closed",
                    "entry_run_at": _iso("2026-08-02"),
                    "exit_run_at": _iso("2026-08-10"),
                    "fair_cost_return": 0.0344,
                }
            ],
        },
    )
    _write(
        "n210_ai_judgment_registration.json",
        {
            "status": "active",
            "registration_id": "strand-e-ai-judgment-fixed-stake-v0",
        },
    )
    _write(
        "n210_ai_judgment_observe.json",
        {
            "registration_id": "strand-e-ai-judgment-fixed-stake-v0",
            "lifecycle_episodes": [
                {
                    "ticker": "LIVE.L",
                    "status": "closed",
                    "exit_run_at": _iso("2026-10-01"),
                    "fair_cost_return": 0.2,
                }
            ],
        },
    )
    projection = build_sealed_lifecycle_projection(tmp_path, now=NOW)
    assert projection["influences_live"] is False
    ids = [row["model_id"] for row in projection["models"]]
    assert ids == ["n200"]
    chip = projection["models"][0]["columns"]["post_sale"]["chips"][0]
    assert chip["ticker"] == "ABDN.L"
    assert chip["return_pct"] == 0.0344
    assert chip["return_basis"] == "fair_cost_episode"
