"""Daily hub attention: status report, Push ranker, Explore lane."""

from __future__ import annotations

from pathlib import Path

from value_investor.daily_hub_attention import (
    LATER_CROWN_ID,
    POST_SELL_CUE_DIGEST_FILENAME,
    apply_hub_task_relevance,
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
            "timing_cues": [{"cue_id": "t1"}],
            "selection_cues": [],
            "hub_feed": {
                "schema_version": 1,
                "explore_candidates": [
                    {
                        "id": "post_sell:t1",
                        "claim": "Timing cue A",
                        "why_matters": "Why A",
                        "falsify_or_promote": "Falsify A",
                        "not_today": True,
                    }
                ],
                "push_candidates": [
                    {
                        "id": "post_sell:human-gate",
                        "claim": "Judge post-sell human gate",
                        "why_matters": "Maps to a live checklist gate",
                        "falsify_or_promote": "Gate closed or parked",
                    }
                ],
            },
        },
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path, cap=3)
    ids = [s["id"] for s in push["suggestions"]]
    assert any("post_sell:human-gate" in i for i in ids)
    assert len(push["suggestions"]) <= 3
    assert push["fail_closed"] is True


def test_push_ignores_legacy_items_headline_without_hub_feed(tmp_path: Path) -> None:
    """L619 fail-closed: legacy items/headline must not invent a Push card."""
    write_json(tmp_path / "ops_status.json", {"overall": "ok", "findings": []}, compact=False)
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
    push = build_daily_push_suggestions(data_dir=tmp_path)
    assert push["suggestions"] == []


def test_push_empty_when_hub_feed_has_only_explore(tmp_path: Path) -> None:
    write_json(tmp_path / "ops_status.json", {"overall": "ok", "findings": []}, compact=False)
    write_json(tmp_path / "engineering_tasks.json", {"tasks": []}, compact=False)
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    write_json(
        tmp_path / POST_SELL_CUE_DIGEST_FILENAME,
        {
            "generated_at": "2026-10-23T07:45:00Z",
            "timing_cues": [{"cue_id": "t1"}],
            "selection_cues": [{"cue_id": "s1"}],
            "hub_feed": {
                "schema_version": 1,
                "explore_candidates": [
                    {
                        "id": "post_sell:t1",
                        "claim": "Explore only",
                        "why_matters": "Learning",
                        "falsify_or_promote": "Gate",
                        "not_today": True,
                    }
                ],
                "push_candidates": [],
            },
        },
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    assert push["suggestions"] == []
    assert push["empty_ok"] is True


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


def test_merged_and_cancelled_eng_not_in_push(tmp_path: Path) -> None:
    """Terminal eng statuses must leave Push — no stale eng theater."""
    write_json(tmp_path / "ops_status.json", {"overall": "ok", "findings": []}, compact=False)
    write_json(
        tmp_path / "engineering_tasks.json",
        {
            "tasks": [
                {
                    "id": "eng-merged-01",
                    "status": "merged",
                    "title": "Already merged gap-closure",
                },
                {
                    "id": "eng-cancelled-01",
                    "status": "cancelled",
                    "title": "Cancelled duplicate hunter",
                },
                {
                    "id": "eng-completed-01",
                    "status": "completed",
                    "title": "Legacy completed",
                },
            ],
            "queue_clearing": {"attention_parked_count": 0, "pause_active": False},
        },
        compact=False,
    )
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    eng_push_ids = [
        s["id"] for s in push["suggestions"] if str(s.get("id") or "").startswith("push:eng:")
    ]
    assert eng_push_ids == []
    cites = [str((s.get("cite") or {}).get("ref") or "") for s in push["suggestions"]]
    assert "eng-merged-01" not in cites
    assert "eng-cancelled-01" not in cites


def test_stale_parked_ops_finding_drops_from_push_when_eng_quiet(tmp_path: Path) -> None:
    """Stale ops parked-eng finding must not Push when live queue has 0 parked."""
    write_json(
        tmp_path / "ops_status.json",
        {
            "overall": "warn",
            "findings": [
                {
                    "severity": "warn",
                    "title": "Parked engineering tasks need manual review",
                    "summary": "1 parked task(s): eng-old-parked",
                    "auto_fixable": False,
                    "fixed": False,
                }
            ],
        },
        compact=False,
    )
    write_json(
        tmp_path / "engineering_tasks.json",
        {
            "tasks": [
                {
                    "id": "eng-old-parked",
                    "status": "merged",
                    "title": "Was parked; now merged",
                }
            ],
            "queue_clearing": {"attention_parked_count": 0, "pause_active": False},
        },
        compact=False,
    )
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    titles = [s["title"] for s in push["suggestions"]]
    assert not any("parked backlog" in str(t).lower() for t in titles)
    assert push["mapped_warns_open"] == []
    assert push["suggestions"] == []


def test_open_eng_still_suggested_in_push(tmp_path: Path) -> None:
    write_json(tmp_path / "ops_status.json", {"overall": "ok", "findings": []}, compact=False)
    write_json(
        tmp_path / "engineering_tasks.json",
        {
            "tasks": [
                {
                    "id": "eng-open-01",
                    "status": "open",
                    "title": "Close stubborn ingest gaps for KGF.L",
                }
            ],
            "queue_clearing": {"attention_parked_count": 0, "pause_active": False},
        },
        compact=False,
    )
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    assert any(s["id"] == "push:eng:eng-open-01" for s in push["suggestions"])


def test_live_parked_eng_finding_still_pushes(tmp_path: Path) -> None:
    write_json(
        tmp_path / "ops_status.json",
        {
            "overall": "warn",
            "findings": [
                {
                    "severity": "warn",
                    "title": "Parked engineering tasks need manual review",
                    "summary": "1 parked task(s): eng-parked-01",
                    "auto_fixable": False,
                }
            ],
        },
        compact=False,
    )
    write_json(
        tmp_path / "engineering_tasks.json",
        {
            "tasks": [
                {
                    "id": "eng-parked-01",
                    "status": "parked",
                    "title": "Needs human triage",
                    "attention": "attention",
                }
            ],
            "queue_clearing": {"attention_parked_count": 1, "pause_active": True},
        },
        compact=False,
    )
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    titles = [s["title"] for s in push["suggestions"]]
    assert any("parked backlog" in str(t).lower() for t in titles) or any(
        "eng-parked-01" in str(s.get("id") or "") for s in push["suggestions"]
    )


def test_stale_orphaned_pr_open_drops_from_status(tmp_path: Path) -> None:
    write_json(
        tmp_path / "ops_status.json",
        {
            "overall": "warn",
            "findings": [
                {
                    "severity": "warn",
                    "title": "Orphaned pr_open engineering tasks",
                    "summary": "Tasks without matching open PR: eng-old-pr",
                    "auto_fixable": True,
                    "fixed": False,
                }
            ],
        },
        compact=False,
    )
    write_json(
        tmp_path / "assessment_scoreboard.json",
        {"headline": "quiet"},
        compact=False,
    )
    write_json(
        tmp_path / "engineering_tasks.json",
        {
            "tasks": [
                {"id": "eng-old-pr", "status": "merged", "title": "PR merged; stamp lagged"},
            ]
        },
        compact=False,
    )
    write_json(tmp_path / "automation.json", {}, compact=False)
    write_json(tmp_path / "post_run_clearance.json", {}, compact=False)
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    report = build_daily_status_report(data_dir=tmp_path, local_date="2026-10-15")
    titles = [str(f.get("title") or "") for f in report["ops_findings"]]
    assert not any("Orphaned pr_open" in t for t in titles)


def test_status_report_excludes_terminal_eng(tmp_path: Path) -> None:
    write_json(tmp_path / "ops_status.json", {"overall": "ok", "findings": []}, compact=False)
    write_json(
        tmp_path / "assessment_scoreboard.json",
        {"headline": "quiet"},
        compact=False,
    )
    write_json(
        tmp_path / "engineering_tasks.json",
        {
            "tasks": [
                {"id": "eng-m", "status": "merged", "title": "done"},
                {"id": "eng-o", "status": "open", "title": "live"},
            ]
        },
        compact=False,
    )
    write_json(tmp_path / "automation.json", {}, compact=False)
    write_json(tmp_path / "post_run_clearance.json", {}, compact=False)
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )
    report = build_daily_status_report(data_dir=tmp_path, local_date="2026-10-15")
    ids = [row["id"] for row in report["engineering_open"]]
    assert "eng-o" in ids
    assert "eng-m" not in ids


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
        {
            "generated_at": "2026-10-23T07:45:00Z",
            "timing_cues": [{"cue_id": "t1"}, {"cue_id": "t2"}],
            "selection_cues": [{"cue_id": "s1"}],
            "sunday_nest": {
                "summary": "2 timing + 1 selection cues; control closed sells=3",
            },
            "hub_feed": {
                "schema_version": 1,
                "explore_candidates": [{"id": "post_sell:t1"}],
                "push_candidates": [],
            },
        },
        compact=False,
    )
    report = build_daily_status_report(data_dir=tmp_path, local_date="2026-10-14")
    assert report["scoreboard_headline"] == "primary behind"
    digest_row = report["post_sell_cue_digest"]
    assert digest_row["present"] is True
    assert digest_row["item_count"] == 3
    assert digest_row["hub_feed_present"] is True
    assert digest_row["explore_candidate_count"] == 1
    assert digest_row["push_candidate_count"] == 0
    assert "items=None" not in digest_row["headline"]
    assert "2 timing + 1 selection" in digest_row["headline"]
    status_row = next(r for r in report["rows"] if r["id"] == "post_sell_cue_digest")
    assert "items=None" not in status_row["value"]
    assert "2 timing + 1 selection" in status_row["value"]


def test_explore_consumes_hub_feed_candidates(tmp_path: Path) -> None:
    """L619: Explore ≤2 from hub_feed.explore_candidates — not the twin stub."""
    write_json(
        tmp_path / POST_SELL_CUE_DIGEST_FILENAME,
        {
            "generated_at": "2026-10-23T07:45:00Z",
            "timing_cues": [],
            "selection_cues": [],
            "hub_feed": {
                "schema_version": 1,
                "explore_candidates": [
                    {
                        "id": "post_sell:cue-a",
                        "claim": "N200 entry lever win",
                        "why_matters": "Factory timing signal",
                        "falsify_or_promote": "Volume gate + thicker cohort",
                        "not_today": True,
                        "source": "post_sell_cue_digest",
                    },
                    {
                        "id": "post_sell:cue-b",
                        "claim": "Exit-time buy-set empty",
                        "why_matters": "Selection thesis check",
                        "falsify_or_promote": "Current-epoch join only",
                        "not_today": True,
                    },
                    {
                        "id": "post_sell:cue-c",
                        "claim": "Third cue should be capped out",
                        "why_matters": "Cap at 2",
                        "falsify_or_promote": "D7A",
                        "not_today": True,
                    },
                ],
                "push_candidates": [],
            },
        },
        compact=False,
    )
    explore = build_daily_explore_suggestions(data_dir=tmp_path, cap=2)
    assert explore["hub_feed_used"] is True
    assert len(explore["suggestions"]) == 2
    ids = [s["id"] for s in explore["suggestions"]]
    assert ids[0] == "explore:post_sell:cue-a"
    assert ids[1] == "explore:post_sell:cue-b"
    assert all(s["label"] == "not-today" for s in explore["suggestions"])
    assert "explore:post-sell-cue-twin" not in ids


def test_explore_fail_closed_without_hub_feed_no_post_sell_stub(tmp_path: Path) -> None:
    """Missing hub_feed must not invent the anachronistic post-sell twin stub."""
    write_json(
        tmp_path / POST_SELL_CUE_DIGEST_FILENAME,
        {"generated_at": "2026-10-23T07:45:00Z", "items": [1]},
        compact=False,
    )
    explore = build_daily_explore_suggestions(data_dir=tmp_path, cap=2)
    assert explore["hub_feed_used"] is False
    ids = [s["id"] for s in explore["suggestions"]]
    assert "explore:post-sell-cue-twin" not in ids
    # Non-post-sell editorial default may still appear.
    assert all("still_in_buy_set" not in str(s.get("claim") or "") for s in explore["suggestions"])


def _write_b3_demotion(tmp_path: Path, *, primary: str = "ai_judgment_fair") -> None:
    write_json(
        tmp_path / "paper_automation" / "assessment_model.json",
        {
            "primary_track": primary,
            "policy_changes": [{"id": "evidentiary_demotion_ai_judgment_fair_v1"}],
        },
        compact=False,
    )
    write_json(
        tmp_path / "b3_scoreboard_epoch_registration.json",
        {
            "policy_change_id": "evidentiary_demotion_ai_judgment_fair_v1",
            "demoted_evidentiary_primary": "ai_judgment_fair",
            "owner_lock": {"anti_C": "no_mid_flight_enlarge_live_3_name_book"},
        },
        compact=False,
    )


def _quiet_eng(tmp_path: Path) -> None:
    write_json(tmp_path / "engineering_tasks.json", {"tasks": []}, compact=False)
    write_json(
        tmp_path / "deferred_trigger_check.json",
        {"met": [], "unmet": []},
        compact=False,
    )


def test_b3_demotion_drops_trail_and_demoted_saturation_from_push(tmp_path: Path) -> None:
    _write_b3_demotion(tmp_path)
    _quiet_eng(tmp_path)
    write_json(
        tmp_path / "ops_status.json",
        {
            "overall": "warn",
            "findings": [
                {
                    "severity": "warn",
                    "title": "Primary book trails its control on total return",
                    "summary": "ai_judgment_fair total return -10.0% vs buy_tier_level +0.1%",
                    "auto_fixable": False,
                },
                {
                    "severity": "warn",
                    "title": "Decision-review knobs saturated at bounds",
                    "summary": (
                        "Proposal rules still fire — "
                        "ai_judgment_fair: sector_cap lower at 0.2. "
                        "Human review: policy change or no action."
                    ),
                    "auto_fixable": False,
                },
                {
                    "severity": "info",
                    "title": "N200 volume gate ready for review",
                    "auto_fixable": False,
                },
            ],
        },
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    titles = [s["title"] for s in push["suggestions"]]
    assert not any("scoreboard" in t.lower() or "trails" in t.lower() for t in titles)
    assert not any("saturated" in t.lower() for t in titles)
    assert any("N200" in t for t in titles)
    assert push["mapped_warns_open"] == []
    reasons = {row["reason"] for row in push["non_actionable_observes"]}
    assert reasons == {"b3_evidentiary_demotion", "b3_anti_c_no_enlarge"}
    assert [row["id"] for row in push["later_suggestions"]] == [LATER_CROWN_ID]
    assert push["later_suggestions"][0]["timing"] == "later"
    assert "crown" in push["later_suggestions"][0]["gap"].lower()
    report = build_daily_status_report(data_dir=tmp_path, local_date="2026-10-16")
    status_titles = [str(row.get("title") or "") for row in report["ops_findings"]]
    assert "Primary book trails its control on total return" not in status_titles
    assert "Decision-review knobs saturated at bounds" not in status_titles
    assert "N200 volume gate ready for review" in status_titles
    observe = next(row for row in report["rows"] if row["id"] == "non_actionable_observes")
    assert "not Push" in observe["label"] or observe["id"] == "non_actionable_observes"
    assert "b3_evidentiary_demotion" in observe["value"]


def test_mixed_saturation_keeps_one_now_gap_card(tmp_path: Path) -> None:
    _write_b3_demotion(tmp_path)
    _quiet_eng(tmp_path)
    write_json(
        tmp_path / "ops_status.json",
        {
            "overall": "warn",
            "findings": [
                {
                    "severity": "warn",
                    "title": "Decision-review knobs saturated at bounds",
                    "summary": (
                        "axis — ai_judgment_fair: sector_cap lower at 0.2; "
                        "other_book: max_positions upper at 30. Human review: decide."
                    ),
                    "auto_fixable": False,
                }
            ],
        },
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    assert len(push["suggestions"]) == 1
    card = push["suggestions"][0]
    assert card["timing"] == "now"
    assert card["gap_tracks"] == ["other_book"]
    assert "ai_judgment_fair" not in card["gap_tracks"]
    assert "other_book" in card["why_now"]
    assert "max_positions upper at 30" in card["why_now"]
    assert "ai_judgment_fair" in card["why_now"]
    assert "Completed half omitted" in card["why_now"]
    assert push["later_suggestions"] == []
    assert "Decision-review knobs saturated at bounds" in push["mapped_warns_open"]


def test_without_demotion_stamp_both_findings_stay_push(tmp_path: Path) -> None:
    _quiet_eng(tmp_path)
    write_json(
        tmp_path / "ops_status.json",
        {
            "overall": "warn",
            "findings": [
                {
                    "severity": "warn",
                    "title": "Primary book trails its control on total return",
                    "summary": "ai_judgment_fair trails",
                },
                {
                    "severity": "warn",
                    "title": "Decision-review knobs saturated at bounds",
                    "summary": "ai_judgment_fair: sector_cap lower at 0.2",
                },
            ],
        },
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    titles = [s["title"] for s in push["suggestions"]]
    assert any("scoreboard" in t.lower() for t in titles)
    assert any("saturated" in t.lower() for t in titles)
    assert push["later_suggestions"] == []


def test_switched_primary_trail_stays_actionable(tmp_path: Path) -> None:
    _write_b3_demotion(tmp_path, primary="n210_ai_judgment")
    _quiet_eng(tmp_path)
    write_json(
        tmp_path / "ops_status.json",
        {
            "overall": "warn",
            "findings": [
                {
                    "severity": "warn",
                    "title": "Primary book trails its control on total return",
                    "summary": "new primary trails",
                }
            ],
        },
        compact=False,
    )
    push = build_daily_push_suggestions(data_dir=tmp_path)
    assert any("scoreboard" in s["title"].lower() for s in push["suggestions"])
    assert push["later_suggestions"] == []


def test_merged_pr_and_sha_drop_hub_task(tmp_path: Path) -> None:
    write_json(
        tmp_path / "engineering_tasks.json",
        {
            "tasks": [
                {
                    "id": "eng-done",
                    "status": "merged",
                    "pr_number": 1091,
                    "evidence": {"merge_sha": "abc1234def"},
                    "title": "B3 lock",
                },
                {
                    "id": "eng-live",
                    "status": "open",
                    "title": "still open",
                },
            ]
        },
        compact=False,
    )
    write_json(
        tmp_path / "pr_fix_occasions.json",
        {"occasions": [{"pr_number": 1091, "head_sha": "abc1234def"}]},
        compact=False,
    )
    tasks = [
        {
            "task_ref": "push:eng:eng-done",
            "title": "Confirm eng merged still P1-aligned: eng-done",
            "cite": {"kind": "engineering_task", "ref": "eng-done"},
            "closed": False,
        },
        {
            "task_ref": "push:eng:eng-missing",
            "title": "Phantom eng",
            "cite": {"kind": "engineering_task", "ref": "eng-missing"},
            "closed": False,
        },
        {
            "task_ref": "work:pr",
            "title": "Finish PR",
            "pr_number": 1091,
            "closed": False,
        },
        {
            "task_ref": "work:sha",
            "title": "Finish sha",
            "merge_sha": "abc1234def",
            "closed": False,
        },
        {
            "task_ref": "push:eng:eng-live",
            "title": "Confirm eng open still P1-aligned: eng-live",
            "cite": {"kind": "engineering_task", "ref": "eng-live"},
            "closed": False,
        },
        {
            "task_ref": "human:sunday-assessment-scoreboard",
            "source": "human_tasks",
            "title": "Read the assessment scoreboard",
            "closed": False,
        },
    ]
    kept, dropped = apply_hub_task_relevance(
        tasks,
        data_dir=tmp_path,
        disposed_checklist_ids={"sunday-assessment-scoreboard"},
    )
    assert [row["task_ref"] for row in kept] == ["push:eng:eng-live"]
    reasons = {row["task_ref"]: row["reason"] for row in dropped}
    assert reasons["push:eng:eng-done"] == "eng_terminal"
    assert reasons["push:eng:eng-missing"] == "eng_absent"
    assert reasons["work:pr"] == "merged_pr"
    assert reasons["work:sha"] == "merged_sha"
    assert reasons["human:sunday-assessment-scoreboard"] == "disposition_locked"
