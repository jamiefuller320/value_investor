"""Tests for the single assessment model (primary/control switch + frozen books)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from value_investor.assessment_model import (
    ASSESSMENT_MODEL_FILENAME,
    apply_assessment_model,
    control_track_id,
    frozen_tracks,
    is_track_frozen,
    primary_track_id,
)
from value_investor.paper_automation import ensure_learning_track_configs

LONDON = ZoneInfo("Europe/London")
WHEN = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _reports(tmp_path: Path) -> Path:
    reports = {
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
            },
            {
                "ticker": "SCREEN.L",
                "name": "ScreenOnly",
                "signal": "buy",
                "adjusted_signal": "buy",
                "research_verdict": None,
                "conviction_score": 0.85,
                "price": 12,
                "timing_signal": "neutral",
            },
        ]
    }
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(reports), encoding="utf-8")
    return path


def _freeze_suite_a(base: Path) -> dict:
    return apply_assessment_model(
        base,
        primary="buy_tier_level",
        control="buy_tier_level_dca",
        freeze={
            "rules": {"reason": "duplicate", "superseded_by": "buy_tier_level"},
            "ai_judgment": {"reason": "gate never binds", "superseded_by": "buy_tier_level"},
        },
        reason="test switch",
        now=WHEN,
    )


def test_legacy_roots_default_to_ai_primary_and_rules_control(tmp_path: Path):
    assert primary_track_id(tmp_path) == "ai_judgment"
    assert control_track_id(tmp_path) == "rules"
    assert frozen_tracks(tmp_path) == {}


def test_apply_records_switch_and_freeze_once(tmp_path: Path):
    base = tmp_path / "auto"
    ensure_learning_track_configs(base)
    (base / "automated_fund.json").write_text(
        json.dumps(
            {
                "holdings": {"KLR.L": {}, "PAF.L": {}},
                "trades": [{}, {}, {}],
                "equity_curve": [
                    {"at": "2026-10-05T09:30:00+01:00", "portfolio_value": 830.0},
                    {
                        "at": "2026-10-06T09:30:00+01:00",
                        "portfolio_value": 582.51,
                        "contributed_capital": 1000.0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    payload = _freeze_suite_a(base)
    assert payload["primary_track"] == "buy_tier_level"
    assert payload["control_track"] == "buy_tier_level_dca"
    assert len(payload["switches"]) == 1
    assert payload["switches"][0]["from"] == {"primary": "ai_judgment", "control": "rules"}
    rules = payload["frozen_tracks"]["rules"]
    assert rules["final_nav"] == 582.51
    assert rules["final_contributed_capital"] == 1000.0
    assert rules["final_holdings"] == ["KLR.L", "PAF.L"]
    assert rules["trade_count"] == 3
    assert rules["superseded_by"] == "buy_tier_level"

    later = datetime(2026, 10, 9, tzinfo=UTC)
    again = apply_assessment_model(
        base,
        primary="buy_tier_level",
        control="buy_tier_level_dca",
        freeze={"rules": {"reason": "changed"}, "technical": {"reason": "no trades"}},
        reason="second pass",
        now=later,
    )
    assert len(again["switches"]) == 1
    assert again["frozen_tracks"]["rules"]["reason"] == "duplicate"
    assert again["frozen_tracks"]["rules"]["frozen_at"] == WHEN.isoformat()
    assert again["frozen_tracks"]["technical"]["frozen_at"] == later.isoformat()
    assert is_track_frozen(base, "technical")


def test_apply_rejects_unknown_or_frozen_active_tracks(tmp_path: Path):
    base = tmp_path / "auto"
    ensure_learning_track_configs(base)
    with pytest.raises(ValueError, match="Unknown track"):
        apply_assessment_model(base, primary="nope", control="rules", freeze={}, reason="x")
    with pytest.raises(ValueError, match="both active and frozen"):
        apply_assessment_model(
            base,
            primary="buy_tier_level",
            control="rules",
            freeze={"rules": {}},
            reason="x",
        )
    assert not (base / ASSESSMENT_MODEL_FILENAME).exists()


def test_run_learning_tracks_skips_frozen_and_mirrors_root_last_run(tmp_path, monkeypatch):
    from value_investor.paper_automation import run_learning_tracks

    monkeypatch.setattr(
        "value_investor.paper_automation.refresh_candidate_marks",
        lambda candidates, extra_tickers=None, **_kwargs: candidates,
    )
    base = tmp_path / "auto"
    reports_path = _reports(tmp_path)
    run_learning_tracks(
        base_dir=base,
        reports_path=reports_path,
        now=datetime(2026, 7, 15, 10, 0, tzinfo=LONDON),
        force=True,
    )
    _freeze_suite_a(base)
    rules_fund = (base / "automated_fund.json").read_text(encoding="utf-8")
    ai_fund = (base / "ai_judgment" / "automated_fund.json").read_text(encoding="utf-8")

    summary = run_learning_tracks(
        base_dir=base,
        reports_path=reports_path,
        now=datetime(2026, 7, 16, 10, 0, tzinfo=LONDON),
        force=True,
    )
    assert summary["primary_learning_track"] == "buy_tier_level"
    assert summary["control_track"] == "buy_tier_level_dca"
    assert summary["frozen_tracks"] == ["ai_judgment", "rules"]
    assert "rules" not in summary["tracks"]
    assert "ai_judgment" not in summary["tracks"]
    assert summary["tracks"]["buy_tier_level"]["is_primary_learning_track"] is True
    assert (base / "automated_fund.json").read_text(encoding="utf-8") == rules_fund
    assert (base / "ai_judgment" / "automated_fund.json").read_text(encoding="utf-8") == ai_fund

    root_last_run = json.loads((base / "last_run.json").read_text(encoding="utf-8"))
    assert root_last_run["mirrored_from_track"] == "buy_tier_level"
    ai_cfg = json.loads((base / "ai_judgment" / "config.json").read_text(encoding="utf-8"))
    assert ai_cfg["is_primary_learning_track"] is False


def test_compare_learning_tracks_uses_model_primary_and_skips_frozen(tmp_path: Path):
    from value_investor.decision_review import compare_learning_tracks

    base = tmp_path / "auto"
    ensure_learning_track_configs(base)
    _freeze_suite_a(base)
    reviewed: list[str] = []

    class _Result:
        def __init__(self, name: str) -> None:
            self.name = name

        def to_dict(self) -> dict:
            excess = {"buy_tier_level": 0.02, "buy_tier_level_dca": 0.01}.get(self.name)
            return {"metrics": {"excess_after_costs": excess}}

    def fake_review(*, output_dir: Path, **_kwargs):
        name = output_dir.name if output_dir != base else "rules"
        reviewed.append(name)
        return _Result(name)

    with (
        patch("value_investor.decision_review.run_decision_review", side_effect=fake_review),
        patch("value_investor.churn_health.write_churn_health", return_value={}),
        patch("value_investor.rebalance_log.write_buffered_hold_counterfactual", return_value=None),
    ):
        summary = compare_learning_tracks(base_dir=base, apply=True, fetch_benchmark=False)
    assert "rules" not in reviewed
    assert "ai_judgment" not in reviewed
    assert summary["primary_learning_track"] == "buy_tier_level"
    assert summary["control_track"] == "buy_tier_level_dca"
    assert summary["primary_excess_after_costs"] == 0.02
    assert summary["beat_control"] is True
    assert set(summary["frozen_tracks"]) == {"rules", "ai_judgment"}


def test_scheduler_ignores_frozen_track_last_run(tmp_path: Path):
    from value_investor.paper_auto_scheduling import paper_auto_artifacts_satisfied

    base = tmp_path / "auto"
    ensure_learning_track_configs(base)
    (base / "ai_judgment" / "last_run.json").write_text(
        '{"gate": {"after_settle": true}}', encoding="utf-8"
    )
    assert paper_auto_artifacts_satisfied(base) is True
    _freeze_suite_a(base)
    assert paper_auto_artifacts_satisfied(base) is False
    (base / "buy_tier_level" / "last_run.json").write_text(
        '{"gate": {"after_settle": true}}', encoding="utf-8"
    )
    assert paper_auto_artifacts_satisfied(base) is True


def test_shadow_spawns_refuse_frozen_parent(tmp_path: Path):
    from value_investor.exclusion_ladder_replay import spawn_exclusion_shadow
    from value_investor.knob_calibration import spawn_calibration_shadow_tracks

    base = tmp_path / "auto"
    ensure_learning_track_configs(base)
    _freeze_suite_a(base)
    calibrated = spawn_calibration_shadow_tracks(base)
    assert calibrated["spawned"] is False
    assert "frozen" in calibrated["reason"]
    exclusion = spawn_exclusion_shadow(base, parent_track_id="ai_judgment")
    assert exclusion["spawned"] is False
    assert "frozen" in exclusion["reason"]


def test_ops_monitor_core_tracks_follow_model(tmp_path: Path):
    from value_investor.ops_monitor import check_paper_learning_tracks

    base = tmp_path / "paper_automation"
    ensure_learning_track_configs(base)
    _freeze_suite_a(base)
    (base / "last_run.json").write_text('{"gate": {"after_settle": true}}', encoding="utf-8")
    row = {"acted": True}
    (base / "learning_tracks_summary.json").write_text(
        json.dumps({"tracks": {"buy_tier_level": row, "buy_tier_level_dca": row}}),
        encoding="utf-8",
    )
    (base / "learning_tracks_review.json").write_text(
        json.dumps({"reviews": {"buy_tier_level": {}}}), encoding="utf-8"
    )
    (base / "buy_tier_level" / "automated_fund.json").write_text(
        json.dumps({"holdings": {"FOO.L": {}}}), encoding="utf-8"
    )
    (base / "learning_tracks_llm_agree_veto.json").write_text("{}", encoding="utf-8")
    findings = {row.title: row for row in check_paper_learning_tracks(base)}
    assert "Learning-tracks summary missing core tracks" not in findings
    missing = findings["Learning-tracks review missing core tracks"]
    assert "buy_tier_level_dca" in missing.summary
    assert "ai_judgment" not in missing.summary
