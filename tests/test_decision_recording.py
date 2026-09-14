"""Tests for decision-time recording checklist (L386)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from value_investor.decision_recording import (
    PRIMARY_FREEZE_AT_T,
    PRIMARY_JOIN_LATER,
    PRIMARY_NEVER_BACKFILL,
    preview_freeze_for_entry,
    preview_freeze_from_rebalance_log,
    primary_recording_answers,
    validate_recording_plan,
)
from value_investor.decision_recording_cli import main as cli_main


def test_primary_answers_cover_four_questions():
    answers = primary_recording_answers().to_dict()
    assert "ticker" in answers["unit_of_analysis"].lower()
    assert answers["freeze_at_t"]
    assert "autopsy_freeze.research_revision_id" in answers["freeze_at_t"]
    assert answers["join_later"]
    assert answers["never_backfill"]
    assert answers["writer_gate"].startswith("ftse-phase-c-readiness")


def test_validate_recording_plan_accepts_complete_plan():
    plan = {
        "strand_id": "exit_shadow_lab",
        "unit_of_analysis": "closed full-position exit episode per track",
        "freeze_at_t": [
            {"field": "exit_logged_at", "source": "paper_auto"},
            "exit_kind",
            "holdings_snapshot",
        ],
        "join_later": ["forward_prices_1w_4w_8w_12w"],
        "never_backfill": ["post_exit_memo_rewrites"],
        "consumer": "counterfactual",
    }
    assert validate_recording_plan(plan) == []


def test_validate_recording_plan_rejects_gaps_and_overlap():
    errors = validate_recording_plan(
        {
            "strand_id": "",
            "unit_of_analysis": "short",
            "freeze_at_t": [],
            "join_later": [],
            "never_backfill": ["taken_action"],
        }
    )
    assert any("strand_id" in err for err in errors)
    assert any("unit_of_analysis" in err for err in errors)
    assert any("freeze_at_t" in err for err in errors)
    assert any("join_later" in err for err in errors)

    overlap_errors = validate_recording_plan(
        {
            "strand_id": "x",
            "unit_of_analysis": "ticker-day decision row",
            "freeze_at_t": ["taken_action"],
            "join_later": ["memo_prose"],
            "never_backfill": ["taken_action"],
        }
    )
    assert any("both freeze_at_t and never_backfill" in err for err in overlap_errors)


def test_preview_freeze_for_entry_marks_missing_autopsy_fields():
    entry = {
        "logged_at": "2026-09-14T08:00:00+00:00",
        "track_id": "ai_judgment",
        "schema_version": 2,
        "screen_source": {"path": "docs/data/latest.json"},
        "knob_epoch_started_at": "2026-08-26T08:00:00+00:00",
        "gate": {"can_act": True},
        "selection": {"min_conviction": 0.6},
        "acted": True,
        "plan": {},
        "trades": [],
        "screen_buy_tier": [{"ticker": "AAA.L"}],
        "candidates": [
            {
                "ticker": "AAA.L",
                "name": "Aaa",
                "signal": "buy",
                "adjusted_signal": "buy",
                "conviction_score": 0.7,
                "data_quality_score": 1.0,
                "timing_signal": "ok",
                "sector": "Industrials",
                "price": 1.0,
                "research_verdict": "accumulate",
            }
        ],
        "holdings_before": [],
        "gate_excluded": ["BBB.L"],
    }
    preview = preview_freeze_for_entry(entry)
    assert preview["coverage"]["log_top"]["ratio"] == 1.0
    assert preview["coverage"]["autopsy_freeze"]["present"] == 0
    assert preview["tickers"][0]["ticker"] == "AAA.L"
    assert preview["tickers"][0]["membership"]["in_screen_buy_tier"] is True
    assert "autopsy_freeze.research_revision_id" in preview["missing_for_phase_c"]
    assert preview["observe_only"] is True


def test_preview_freeze_from_rebalance_log_file(tmp_path: Path):
    path = tmp_path / "rebalance_log.json"
    path.write_text(
        json.dumps(
            [
                {
                    "logged_at": "2026-09-01T08:00:00+00:00",
                    "track_id": "ai_judgment",
                    "schema_version": 2,
                    "screen_source": {},
                    "knob_epoch_started_at": "2026-08-01T00:00:00+00:00",
                    "gate": {},
                    "selection": {},
                    "acted": False,
                    "plan": {},
                    "trades": [],
                    "candidates": [{"ticker": "CCC.L", "name": "C", "signal": "hold"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    report = preview_freeze_from_rebalance_log(path)
    assert report.entry_count == 1
    assert report.aggregate_missing
    assert "autopsy_freeze.research_revision_id" in report.aggregate_missing


def test_catalog_constants_are_disjoint_for_primary():
    freeze = set(PRIMARY_FREEZE_AT_T)
    never = set(PRIMARY_NEVER_BACKFILL)
    join = set(PRIMARY_JOIN_LATER)
    assert not (freeze & never)
    assert not (freeze & join)


def test_cli_show_primary_and_validate(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert cli_main(["show-primary"]) == 0
    out = capsys.readouterr().out
    assert "primary_ai_judgment" in out
    assert "autopsy_freeze.research_revision_id" in out

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "strand_id": "demo",
                "unit_of_analysis": "ticker-day decision",
                "freeze_at_t": ["logged_at", "taken_action"],
                "join_later": ["forward_marks"],
                "never_backfill": ["later_filings"],
            }
        ),
        encoding="utf-8",
    )
    assert cli_main(["validate", "--plan", str(plan_path)]) == 0
