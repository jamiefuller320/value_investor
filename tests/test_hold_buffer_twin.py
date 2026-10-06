"""Tests for the L541 hold-buffer twin of the assessment-model primary."""

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from value_investor.assessment_model import apply_assessment_model, register_twin, twins
from value_investor.assessment_scoreboard import twin_comparison
from value_investor.fair_cost_lab import (
    HOLD_BUFFER_TWIN_TRACK_ID,
    spawn_fair_cost_lab,
    spawn_hold_buffer_twin,
)
from value_investor.paper_automation import ensure_learning_track_configs, learning_track_dirs

LONDON = ZoneInfo("Europe/London")
WHEN = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _model_root(tmp_path: Path) -> Path:
    base = tmp_path / "auto"
    ensure_learning_track_configs(base)
    spawn_fair_cost_lab(base, track_ids=["ai_judgment_fair"])
    apply_assessment_model(
        base,
        primary="ai_judgment_fair",
        control="buy_tier_level",
        freeze={"rules": {"reason": "stress"}, "ai_judgment": {"reason": "stress"}},
        reason="test switch",
        now=WHEN,
    )
    return base


def _config(base: Path, track_id: str) -> dict:
    return json.loads((base / track_id / "config.json").read_text(encoding="utf-8"))


def test_spawn_copies_primary_and_varies_only_exit_buffer(tmp_path: Path):
    base = _model_root(tmp_path)
    parent = _config(base, "ai_judgment_fair")

    result = spawn_hold_buffer_twin(base)

    assert result["spawned"] is True and result["created"] is True
    assert result["parent_track_id"] == "ai_judgment_fair"
    twin = _config(base, HOLD_BUFFER_TWIN_TRACK_ID)
    assert twin["exit_confirm_screens"] == 5
    assert parent["exit_confirm_screens"] != 5
    assert twin["is_fair_cost_lab"] is True
    assert twin["is_churn_policy_twin"] is True
    assert twin["churn_policy_parent_track"] == "ai_judgment_fair"
    for key in ("min_conviction", "max_positions", "sector_cap", "buy_cost_pct", "sell_cost_pct"):
        assert twin[key] == parent[key]
    fund = json.loads(
        (base / HOLD_BUFFER_TWIN_TRACK_ID / "automated_fund.json").read_text(encoding="utf-8")
    )
    assert fund.get("trades") in (None, [])

    record = twins(base)[HOLD_BUFFER_TWIN_TRACK_ID]
    assert record["parent_track"] == "ai_judgment_fair"
    assert record["varied"]["exit_confirm_screens"] == {
        "parent": parent["exit_confirm_screens"],
        "twin": 5,
    }
    assert record["parent_knobs_at_start"]["min_conviction"] == parent["min_conviction"]
    assert HOLD_BUFFER_TWIN_TRACK_ID in learning_track_dirs(base)

    again = spawn_hold_buffer_twin(base)
    assert again["created"] is False
    assert twins(base)[HOLD_BUFFER_TWIN_TRACK_ID]["started_at"] == record["started_at"]


def test_register_twin_refuses_frozen_parent(tmp_path: Path):
    base = _model_root(tmp_path)
    with pytest.raises(ValueError, match="frozen"):
        register_twin(
            base,
            track_id="x_twin",
            parent_track_id="rules",
            varied={},
            parent_knobs_at_start={},
            learning_question="q",
            readiness_gate="g",
        )


def test_model_switch_keeps_twin_registry(tmp_path: Path):
    base = _model_root(tmp_path)
    spawn_hold_buffer_twin(base)
    apply_assessment_model(
        base,
        primary="ai_judgment_fair",
        control="buy_tier_level",
        freeze={"momentum_grace": {"reason": "stress"}},
        reason="another freeze",
    )
    assert HOLD_BUFFER_TWIN_TRACK_ID in twins(base)


def test_paper_auto_runs_twin_with_fixed_knobs(tmp_path: Path, monkeypatch):
    from value_investor.paper_automation import run_learning_tracks

    monkeypatch.setattr(
        "value_investor.paper_automation.refresh_candidate_marks",
        lambda candidates, extra_tickers=None, **_kwargs: candidates,
    )
    base = _model_root(tmp_path)
    spawn_hold_buffer_twin(base)
    reports = tmp_path / "latest.json"
    reports.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "ticker": "GOOD.L",
                        "name": "Good",
                        "signal": "strong_buy",
                        "adjusted_signal": "strong_buy",
                        "research_verdict": "accumulate",
                        "conviction_score": 0.9,
                        "price": 10,
                        "timing_signal": "accumulate",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = run_learning_tracks(
        base_dir=base,
        reports_path=reports,
        now=datetime(2026, 10, 7, 10, 0, tzinfo=LONDON),
        force=True,
    )

    assert HOLD_BUFFER_TWIN_TRACK_ID in summary["tracks"]
    twin = _config(base, HOLD_BUFFER_TWIN_TRACK_ID)
    assert twin["exit_confirm_screens"] == 5
    assert twin["is_churn_policy_twin"] is True
    assert twin["buy_cost_pct"] == _config(base, "ai_judgment_fair")["buy_cost_pct"]


def _fund(path: Path, navs: list[float]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    curve = [
        {
            "at": f"2026-10-{6 + i:02d}T09:30:00+00:00",
            "portfolio_value": nav,
            "contributed_capital": 1000.0,
        }
        for i, nav in enumerate(navs)
    ]
    (path / "automated_fund.json").write_text(json.dumps({"equity_curve": curve}), encoding="utf-8")


def test_twin_comparison_uses_common_days_and_flags_parent_drift(tmp_path: Path):
    _fund(tmp_path / "parent", [1000.0, 1100.0, 1100.0, 1210.0])
    _fund(tmp_path / "twin", [1000.0, 1000.0, 1050.0])
    (tmp_path / "parent" / "config.json").write_text(
        json.dumps({"min_conviction": 0.7, "exit_confirm_screens": 2}), encoding="utf-8"
    )
    dirs = {"parent": tmp_path / "parent", "twin": tmp_path / "twin"}
    record = {
        "parent_track": "parent",
        "started_at": "2026-10-06T09:00:00+00:00",
        "parent_knobs_at_start": {"min_conviction": 0.6, "exit_confirm_screens": 2},
    }

    row = twin_comparison("twin", record, dirs)

    assert row["status"] == "ok"
    assert row["common_days"] == 2
    assert row["parent_return"] == pytest.approx(0.1)
    assert row["twin_return"] == pytest.approx(0.05)
    assert row["difference"] == pytest.approx(-0.05)
    assert row["parent_knobs_changed"] == ["min_conviction"]
