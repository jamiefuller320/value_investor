"""Tests for the single assessment scoreboard (observe-only)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.assessment_model import apply_assessment_model
from value_investor.assessment_scoreboard import (
    FINDING_TITLE,
    STORE_FAILED_TITLE,
    build_assessment_scoreboard,
    gate_status,
    ops_finding_from_assessment_scoreboard,
    published_value_hurdle,
    stress_cost_sensitivity,
)
from value_investor.paper_automation import ensure_learning_track_configs

WHEN = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _window(total: float, bench: float, *, start: str = "2026-09-07T08:30:00+00:00") -> dict:
    return {
        "start": start,
        "end": "2026-10-06T08:30:00+00:00",
        "marks": 21,
        "base_capital": 1000.0,
        "total_return": total,
        "benchmark_total_return": bench,
        "excess_total_return": round(total - bench, 4),
        "dividends_gbp": 4.0,
    }


def _seed(tmp_path: Path, *, primary_tr: float = 0.01, control_tr: float = 0.02) -> Path:
    data = tmp_path / "data"
    paper = data / "paper_automation"
    ensure_learning_track_configs(paper)
    apply_assessment_model(
        paper,
        primary="buy_tier_level",
        control="buy_tier_level_dca",
        freeze={"rules": {"reason": "stress book", "superseded_by": "buy_tier_level"}},
        reason="test",
        now=WHEN,
    )
    _write(
        paper / "buy_tier_level" / "automated_fund.json",
        {
            "trades": [
                {"acted_at": "2026-09-01T08:30:00+00:00", "gross": 900.0, "cost": 27.0},
                {"acted_at": "2026-09-10T08:30:00+00:00", "gross": 500.0, "cost": 2.5},
                {"acted_at": "2026-09-20T08:30:00+00:00", "gross": 500.0, "cost": 0.5},
            ]
        },
    )
    _write(
        data / "total_return_view.json",
        {
            "updated_at": WHEN.isoformat(),
            "benchmarks": {"total_return": "FTAL.L"},
            "tracks": {
                "buy_tier_level": {
                    "lifetime": _window(-0.02, -0.01, start="2026-08-25T08:30:00+00:00"),
                    "clean_epoch": _window(primary_tr, -0.01),
                },
                "buy_tier_level_dca": {"lifetime": _window(control_tr, -0.01)},
                "rules": {"lifetime": _window(-0.30, -0.01)},
            },
            "pairs": {
                "p": {
                    "left": "buy_tier_level",
                    "right": "buy_tier_level_dca",
                    "start": "2026-09-07T08:30:00+00:00",
                    "left_total_return": primary_tr,
                    "right_total_return": control_tr,
                    "difference": round(primary_tr - control_tr, 4),
                }
            },
        },
    )
    _write(
        data / "track_statistics.json",
        {
            "tracks": {
                "buy_tier_level": {
                    "status": "ok",
                    "vs": "^FTSE",
                    "annualized_active_return": 0.04,
                    "ci_annualized_active_return": [-0.3, 0.4],
                    "verdict": "indistinguishable_from_noise",
                    "years_to_detect_target_edge": 80.0,
                },
                "buy_tier_level_dca": {"status": "insufficient_data", "periods": 9},
            }
        },
    )
    return data


def test_stress_cost_sensitivity_reprices_window_trades():
    trades = [
        {"acted_at": "2026-09-01T08:30:00+00:00", "gross": 900.0, "cost": 27.0},
        {"acted_at": "2026-09-10T08:30:00+00:00", "gross": 500.0, "cost": 2.5},
        {"acted_at": "2026-09-20T08:30:00+00:00", "gross": -500.0, "cost": 0.5},
    ]
    out = stress_cost_sensitivity(
        trades,
        start=datetime(2026, 9, 7, tzinfo=UTC),
        end=datetime(2026, 10, 6, tzinfo=UTC),
        base_capital=1000.0,
    )
    assert out == {
        "trades": 2,
        "turnover": 1.0,
        "costs_paid_pct": 0.003,
        "costs_at_stress_pct": 0.03,
        "extra_drag_at_stress": 0.027,
    }
    assert stress_cost_sensitivity(trades, start=None, end=None, base_capital=1000.0) is None


def test_gate_status_flags_a_gate_that_lets_nearly_everything_through():
    premise = {"horizons": {"7": {"ai_gate_pass_share": 0.92}, "28": {"ai_gate_pass_share": 0.94}}}
    gated = gate_status({"require_research_accumulate": True, "min_conviction": 0.6}, premise)
    assert gated["buy_tier_pass_share"] == 0.92
    assert gated["binds"] is False
    assert gate_status({"require_research_accumulate": True}, {})["binds"] is None
    assert gate_status({"require_research_accumulate": False}, premise) == {
        "gate": None,
        "binds": None,
    }


def test_build_scoreboard_orders_roles_and_lists_frozen(tmp_path: Path):
    data = _seed(tmp_path)
    board = build_assessment_scoreboard(data, now=WHEN)
    assert board["primary_track"] == "buy_tier_level"
    assert board["control_track"] == "buy_tier_level_dca"
    roles = [(row["track_id"], row["role"]) for row in board["tracks"][:2]]
    assert roles == [("buy_tier_level", "primary"), ("buy_tier_level_dca", "control")]
    assert "rules" not in {row["track_id"] for row in board["tracks"]}

    primary = board["tracks"][0]
    assert primary["basis"] == "clean_epoch"
    assert primary["excess_total_return"] == 0.02
    assert primary["cost_sensitivity"]["trades"] == 2
    assert primary["excess_total_return_at_stress_cost"] == round(0.02 - 0.027, 4)
    assert primary["statistics"]["ci90"] == [-0.3, 0.4]
    assert board["tracks"][1]["statistics"]["status"] == "insufficient_data"

    assert board["primary_vs_control"]["difference"] == -0.01
    assert board["frozen_tracks"][0]["track_id"] == "rules"
    assert board["frozen_tracks"][0]["lifetime_excess_total_return"] == -0.29
    assert "not yet distinguishable from the market" in board["headline"]
    assert "buy_tier_level_dca: -1.0%" in board["headline"]
    assert board["value_hurdle"] is None


def test_value_hurdle_sits_beside_the_primary_and_does_not_warn(tmp_path: Path):
    data = _seed(tmp_path)
    _write(
        data / "value_factor_base_rate.json",
        {
            "built_at": "2026-10-07T00:00:00+00:00",
            "source": {"us_data_cut": "202608"},
            "uk_local_value_weight": {
                "earnings_price": {
                    "high_minus_market": {
                        "start": 197501,
                        "end": 202512,
                        "windows": {
                            "full": {
                                "months": 612,
                                "annualised_arithmetic_pct": 2.72,
                                "t_stat": 2.55,
                            }
                        },
                    }
                },
                "cash_earnings_price": {
                    "high_minus_market": {
                        "start": 197501,
                        "end": 202512,
                        "windows": {
                            "full": {
                                "months": 612,
                                "annualised_arithmetic_pct": 3.24,
                                "t_stat": 2.73,
                            }
                        },
                    }
                },
            },
        },
    )
    board = build_assessment_scoreboard(data, now=WHEN)
    hurdle = board["value_hurdle"]
    assert hurdle["not_a_book"] is True
    assert hurdle["earnings_price"]["annualised_arithmetic_pct"] == 2.72
    assert hurdle["cash_earnings_price"]["annualised_arithmetic_pct"] == 3.24
    assert hurdle["primary_excess_total_return"] == board["tracks"][0]["excess_total_return"]
    assert "UK high earnings/price +2.72%/yr (t=2.55)" in board["headline"]
    assert "cash earnings/price +3.24%/yr (t=2.73)" in board["headline"]
    assert ops_finding_from_assessment_scoreboard(board) is None
    assert published_value_hurdle({}) is None


def test_finding_fires_when_primary_trails_control_by_five_points(tmp_path: Path):
    quiet = build_assessment_scoreboard(_seed(tmp_path / "a"), now=WHEN)
    assert ops_finding_from_assessment_scoreboard(quiet) is None
    behind = build_assessment_scoreboard(
        _seed(tmp_path / "b", primary_tr=-0.04, control_tr=0.02), now=WHEN
    )
    finding = ops_finding_from_assessment_scoreboard(behind)
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False
    assert "-6.0%" in finding["summary"]


def test_check_assessment_scoreboard_persists_and_fails_closed(tmp_path: Path, monkeypatch):
    from value_investor import assessment_scoreboard as module
    from value_investor.ops_monitor import check_assessment_scoreboard

    data = _seed(tmp_path, primary_tr=-0.04, control_tr=0.02)
    store = tmp_path / "assessment_scoreboard.json"
    findings = check_assessment_scoreboard(data_dir=data, store_path=store)
    assert [f.title for f in findings] == [FINDING_TITLE]
    assert json.loads(store.read_text())["primary_track"] == "buy_tier_level"

    def boom(*_a, **_k):
        raise ValueError("bad store")

    monkeypatch.setattr(module, "build_assessment_scoreboard", boom)
    failed = check_assessment_scoreboard(data_dir=data, store_path=store)
    assert [f.title for f in failed] == [STORE_FAILED_TITLE]
    assert check_assessment_scoreboard(data_dir=tmp_path / "missing", store_path=store) == []
