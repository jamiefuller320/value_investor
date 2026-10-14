"""Daily hub attention: status report, Push ranker, Explore lane."""

from __future__ import annotations

from pathlib import Path

from value_investor.daily_hub_attention import (
    POST_SELL_CUE_DIGEST_FILENAME,
    build_daily_explore_suggestions,
    build_daily_push_suggestions,
    build_daily_status_report,
    check_daily_push_empty_while_mapped_warns,
    filter_actionable_market_warn_tasks,
)
from value_investor.storage import write_json


def test_filter_ritual_health_warn() -> None:
    tasks = [
        {
            "task_ref": "mwarn:x:health_warn",
            "triage_action": "park",
            "market_warning": {"flag_id": "health_warn"},
        },
        {
            "task_ref": "mwarn:y:zero_body_stuck",
            "triage_action": "deepen",
            "market_warning": {"flag_id": "zero_body_stuck"},
        },
        {
            "task_ref": "mwarn:dev:1",
            "triage_action": "dismiss",
            "market_warning": {"flag_id": "ingest_deviation"},
        },
    ]
    kept = filter_actionable_market_warn_tasks(tasks)
    assert [t["task_ref"] for t in kept] == [
        "mwarn:y:zero_body_stuck",
        "mwarn:dev:1",
    ]


def test_push_ranker_maps_findings_and_digest(tmp_path: Path) -> None:
    write_json(
        tmp_path / "ops_status.json",
        {
            "overall": "warn",
            "findings": [
                {
                    "severity": "warn",
                    "title": "Decision-review knobs saturated at bounds",
                    "auto_fixable": False,
                    "category": "paper",
                },
                {
                    "severity": "info",
                    "title": "N200 volume gate ready for review",
                    "auto_fixable": False,
                    "category": "research",
                },
            ],
        },
        compact=False,
    )
    write_json(tmp_path / "engineering_tasks.json", {"tasks": []}, compact=False)
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    write_json(
        tmp_path / POST_SELL_CUE_DIGEST_FILENAME,
        {
            "generated_at": "2026-10-14T12:00:00Z",
            "headline": "3 post-sell cues ripe for review",
            "items": [{"ticker": "AAA.L"}],
        },
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path, cap=3)
    ids = [s["id"] for s in push["suggestions"]]
    assert any("post_sell_cue_digest" in i for i in ids)
    assert len(push["suggestions"]) <= 3
    assert push["fail_closed"] is True


def test_push_fail_closed_empty(tmp_path: Path) -> None:
    write_json(tmp_path / "ops_status.json", {"overall": "ok", "findings": []}, compact=False)
    write_json(tmp_path / "engineering_tasks.json", {"tasks": []}, compact=False)
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    assert push["suggestions"] == []
    assert push["empty_ok"] is True
    assert "factory green" in push["empty_message"]


def test_push_empty_finding_when_mapped_warns(tmp_path: Path) -> None:
    write_json(
        tmp_path / "ops_status.json",
        {
            "overall": "warn",
            "findings": [
                {
                    "severity": "warn",
                    "title": "Decision-review knobs saturated at bounds",
                    "auto_fixable": False,
                }
            ],
        },
        compact=False,
    )
    write_json(tmp_path / "engineering_tasks.json", {"tasks": []}, compact=False)
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    assert push["suggestions"]
    all_ids = {s["id"] for s in push["suggestions"]}
    push2 = build_daily_push_suggestions(data_dir=tmp_path, closed_ids=all_ids)
    assert push2["suggestions"] == []
    assert push2["push_empty_while_mapped_warns"] is True
    # Live check rebuilds without closed_ids so cards reappear — finding stays quiet.
    assert check_daily_push_empty_while_mapped_warns(data_dir=tmp_path) == []


def test_explore_quality_bar(tmp_path: Path) -> None:
    write_json(
        tmp_path / "project_daily_seed.json",
        {
            "explore_lines": [
                {"claim": "only claim"},  # incomplete — drop
                {
                    "id": "custom",
                    "claim": "Try X lever as observe twin",
                    "why_matters": "Might separate timing from identity",
                    "falsify_or_promote": "Need ≥N closed episodes; alone scoreboard",
                },
            ]
        },
        compact=False,
    )
    explore = build_daily_explore_suggestions(data_dir=tmp_path, cap=2)
    assert len(explore["suggestions"]) == 1
    s = explore["suggestions"][0]
    assert s["label"] == "not-today"
    assert s["claim"] and s["why_matters"] and s["falsify_or_promote"]


def test_status_report_includes_digest_row(tmp_path: Path) -> None:
    write_json(tmp_path / "ops_status.json", {"overall": "ok", "findings": []}, compact=False)
    write_json(
        tmp_path / "assessment_scoreboard.json",
        {"headline": "primary behind", "primary_track": "ai_judgment_fair"},
        compact=False,
    )
    write_json(tmp_path / "engineering_tasks.json", {"tasks": []}, compact=False)
    write_json(tmp_path / "automation.json", {}, compact=False)
    write_json(tmp_path / "post_run_clearance.json", {}, compact=False)
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    write_json(
        tmp_path / POST_SELL_CUE_DIGEST_FILENAME,
        {"headline": "digest ready", "items": [1, 2]},
        compact=False,
    )
    report = build_daily_status_report(data_dir=tmp_path, local_date="2026-10-14")
    assert report["scoreboard_headline"] == "primary behind"
    assert report["post_sell_cue_digest"]["present"] is True
    assert any(r["id"] == "post_sell_cue_digest" for r in report["rows"])
