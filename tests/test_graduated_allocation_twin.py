"""Tests for the fair-cost graduated-allocation twin of the assessment-model primary."""

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from value_investor.assessment_model import apply_assessment_model, twins
from value_investor.fair_cost_lab import (
    GRADUATED_PROVENANCE_FILENAME,
    GRADUATED_TWIN_TRACK_ID,
    HOLD_BUFFER_TWIN_TRACK_ID,
    spawn_fair_cost_lab,
    spawn_graduated_allocation_twin,
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


def test_spawn_varies_only_graduated_allocation(tmp_path: Path):
    base = _model_root(tmp_path)
    parent = _config(base, "ai_judgment_fair")
    assert parent["use_graduated_allocation"] is False

    result = spawn_graduated_allocation_twin(base)

    assert result["spawned"] is True and result["created"] is True
    assert result["parent_track_id"] == "ai_judgment_fair"
    twin = _config(base, GRADUATED_TWIN_TRACK_ID)
    assert twin["use_graduated_allocation"] is True
    assert twin["is_fair_cost_lab"] is True
    assert twin["is_churn_policy_twin"] is True
    assert twin["churn_policy_parent_track"] == "ai_judgment_fair"
    for key in (
        "min_conviction",
        "max_positions",
        "exit_confirm_screens",
        "sector_cap",
        "require_research_accumulate",
        "use_adjusted_signal",
        "buy_cost_pct",
        "sell_cost_pct",
        "entry_dca_execute_cadence",
    ):
        assert twin[key] == parent[key], key

    record = twins(base)[GRADUATED_TWIN_TRACK_ID]
    assert record["varied"] == {"use_graduated_allocation": {"parent": False, "twin": True}}
    assert record["parent_knobs_at_start"]["use_graduated_allocation"] is False
    provenance = json.loads(
        (base / GRADUATED_TWIN_TRACK_ID / GRADUATED_PROVENANCE_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert provenance["varied"] == record["varied"]
    assert GRADUATED_TWIN_TRACK_ID in learning_track_dirs(base)

    again = spawn_graduated_allocation_twin(base)
    assert again["created"] is False
    assert twins(base)[GRADUATED_TWIN_TRACK_ID]["started_at"] == record["started_at"]


def test_twins_coexist_and_dry_run_writes_nothing(tmp_path: Path):
    base = _model_root(tmp_path)
    dry = spawn_graduated_allocation_twin(base, dry_run=True)
    assert dry["would_spawn"] is True
    assert not (base / GRADUATED_TWIN_TRACK_ID).exists()

    spawn_hold_buffer_twin(base)
    spawn_graduated_allocation_twin(base)
    registry = twins(base)
    assert set(registry) >= {HOLD_BUFFER_TWIN_TRACK_ID, GRADUATED_TWIN_TRACK_ID}
    assert registry[HOLD_BUFFER_TWIN_TRACK_ID]["varied"] == {
        "exit_confirm_screens": {"parent": 2, "twin": 5}
    }


def test_paper_auto_runs_twin_through_graduated_rebalance(tmp_path: Path, monkeypatch):
    from value_investor import paper_automation

    monkeypatch.setattr(
        "value_investor.paper_automation.refresh_candidate_marks",
        lambda candidates, extra_tickers=None, **_kwargs: candidates,
    )
    calls: list[int] = []
    real = paper_automation.run_graduated_rebalance

    def _spy(fund, candidates, **kwargs):
        calls.append(int(fund.config.max_positions))
        return real(fund, candidates, **kwargs)

    monkeypatch.setattr(paper_automation, "run_graduated_rebalance", _spy)
    base = _model_root(tmp_path)
    spawn_graduated_allocation_twin(base)
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

    summary = paper_automation.run_learning_tracks(
        base_dir=base,
        reports_path=reports,
        now=datetime(2026, 10, 7, 10, 0, tzinfo=LONDON),
        force=True,
        tracks=[GRADUATED_TWIN_TRACK_ID],
    )

    assert GRADUATED_TWIN_TRACK_ID in summary["tracks"]
    assert calls, "twin should rebalance through run_graduated_rebalance"
    twin = _config(base, GRADUATED_TWIN_TRACK_ID)
    assert twin["use_graduated_allocation"] is True
    assert twin["max_positions"] == _config(base, "ai_judgment_fair")["max_positions"]
