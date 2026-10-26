"""Tests for cue-consumer MFT observe lab skeleton (Package M)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from value_investor.cue_consumer_mft import (
    CALENDAR_FALLBACK,
    COHORT_FREEZE_PROPOSED_TITLE,
    COHORT_SELECTION_ID,
    FIXED_STAKE_UNITS,
    LAB_ARM_MARKER_ID,
    LAB_ARMED_TITLE,
    LAB_ID,
    PIPELINE_STATUS_ARMED,
    REGISTRATION_ID,
    SCOREBOARD_ID,
    START_CHECKPOINT_ID,
    THIN_EMIT_MIN_CLOSES,
    TUNE_SPEC_ID,
    assess_same_day_round_trip,
    build_hardened_proposal_stub,
    build_registration_payload,
    concurrent_cap_stub,
    evaluate_start_gate,
    freeze_start_cohort,
    judgment_in_the_round_stub,
    novelty_gate_stub,
    ops_findings_from_cue_consumer_mft,
    propose_start_cohort,
    refresh_cue_consumer_mft,
    select_pit_cues,
    thin_emit_readiness,
)
from value_investor.post_sale_review_opinion import (
    OPINION_SOURCE_DETERMINISTIC,
    build_initial_opinion,
    consider_human_comment,
    generate_factory_reply,
)


def test_registration_is_observe_only_fixed_stake():
    reg = build_registration_payload()
    assert reg["registration_id"] == REGISTRATION_ID
    assert reg["lab_id"] == LAB_ID
    assert reg["influences_live"] is False
    assert reg["observe_only"] is True
    assert reg["declared_incomparable"] is True
    assert reg["scoreboard_id"] == SCOREBOARD_ID
    assert reg["sizing"]["mode"] == "fixed_stake"
    assert reg["sizing"]["stake_units"] == FIXED_STAKE_UNITS
    assert reg["mid_flight_tune"]["package_l_on_sealed"] is False
    assert reg["tune_spec_id"] == TUNE_SPEC_ID


def test_pit_cue_selection_rejects_lookahead_and_unknown_sources():
    decision = "2026-10-20"
    selected = select_pit_cues(
        [
            {
                "cue_source_id": "n200_raw_buy_tier",
                "cue_ts": "2026-10-19",
                "ticker": "AAA.L",
            },
            {
                "cue_source_id": "n200_raw_buy_tier",
                "cue_ts": "2026-10-21",  # look-ahead
                "ticker": "BBB.L",
            },
            {
                "cue_source_id": "not_on_whitelist",
                "cue_ts": "2026-10-18",
                "ticker": "CCC.L",
            },
            {
                "cue_source_id": "n210_ai_filter",
                # missing PIT stamp → fail closed
                "ticker": "DDD.L",
            },
        ],
        decision_ts=decision,
    )
    assert len(selected) == 1
    assert selected[0]["ticker"] == "AAA.L"
    assert selected[0]["pit_ok"] is True


def test_same_day_soft_bias_not_hard_ban():
    weak = assess_same_day_round_trip(
        entry_at="2026-10-25T09:00:00+00:00",
        exit_at="2026-10-25T15:00:00+00:00",
        hold_days=0,
    )
    assert weak["same_day_round_trip"] is True
    assert weak["same_day_assessment"] == "likely_weakness"
    assert weak["soft_penalty"] is True
    assert weak["hard_ban"] is False

    reverse = assess_same_day_round_trip(
        entry_at="2026-10-25",
        exit_at="2026-10-25",
        major_error_reverse=True,
        evidence_cites=["decision_reasons.buy code=… mistaken entry"],
    )
    assert reverse["same_day_assessment"] == "major_error_reverse"
    assert reverse["soft_penalty"] is False
    assert reverse["hard_ban"] is False

    multi = assess_same_day_round_trip(
        entry_at="2026-10-01",
        exit_at="2026-10-20",
        hold_days=19,
    )
    assert multi["same_day_round_trip"] is False
    assert multi["same_day_assessment"] == "not_applicable"


def test_thin_emit_closes_primary_mom_optional():
    not_ready = thin_emit_readiness(
        closed_episodes_citing_levers=2,
        proposal_hygiene_ok=True,
        mom_window_complete=True,
    )
    assert not_ready["soft_ready"] is False
    assert not_ready["mom_required_for_emit"] is False
    assert not_ready["min_closes"] == THIN_EMIT_MIN_CLOSES

    ready = thin_emit_readiness(
        closed_episodes_citing_levers=3,
        proposal_hygiene_ok=True,
        mom_window_complete=False,
    )
    assert ready["soft_ready"] is True
    assert ready["mom_window_complete"] is False


def test_novelty_and_cap_stubs_document_remainder():
    proposal = build_hardened_proposal_stub(
        levers_touched=["sell_timing"],
        falsify_or_incorporate_note="test note",
        closed_episodes_citing_levers=3,
    )
    assert proposal["spawn_status"] == "scaffold_only"
    assert proposal["thin_emit_readiness"]["soft_ready"] is True

    merge = novelty_gate_stub(proposal, active_fingerprints=[proposal["novelty_fingerprint"]])
    assert merge["action"] == "merge"
    assert merge["deferred_id"] == "N226"

    spawn = novelty_gate_stub(proposal, active_fingerprints=[])
    assert spawn["action"] == "spawn"

    cap = concurrent_cap_stub(active_child_count=3)
    assert cap["at_cap"] is True
    assert cap["deferred_id"] == "N227"


def test_q8b_start_gate_named_cohort_not_active_count():
    # Incomplete cohort — not eligible before calendar.
    open_eval = evaluate_start_gate(
        start_gate={
            "checkpoint_id": START_CHECKPOINT_ID,
            "cohort_review_ids": ["rev-a", "rev-b"],
            "checkpoint_status": "open",
        },
        labels={"history": [{"review_id": "rev-a", "action": "accept"}]},
        today=date(2026, 10, 25),
    )
    assert open_eval["mode"] == "q8b_named_cohort_checkpoint"
    assert open_eval["eligible"] is False
    assert open_eval["cohort_remaining"] == ["rev-b"]
    assert open_eval["not_gate"] == "active_count==0_forever_wait_while_just_sold_refills"

    # Cohort complete even if a hypothetical active queue would be non-empty.
    done = evaluate_start_gate(
        start_gate={
            "checkpoint_id": START_CHECKPOINT_ID,
            "cohort_review_ids": ["rev-a", "rev-b"],
        },
        labels={
            "history": [
                {"review_id": "rev-a", "action": "accept"},
                {"review_id": "rev-b", "action": "comment"},
            ]
        },
        today=date(2026, 10, 25),
    )
    assert done["eligible"] is True
    assert done["eligibility_reason"] == "named_open_autopsy_cohort_checkpoint_complete"

    # Calendar fallback.
    cal = evaluate_start_gate(
        start_gate={"cohort_review_ids": []},
        labels={},
        today=date.fromisoformat(CALENDAR_FALLBACK),
    )
    assert cal["eligible"] is True
    assert cal["eligibility_reason"] == "calendar_fallback_on_or_after"


def test_propose_cohort_non_mechanical_excludes_reply_and_mechanical():
    queue = {
        "active": [
            {
                "review_id": "keep-ib",
                "book_id": "n206",
                "exit_reason": "identity_break_ey_band",
                "sold_at": "2026-10-20",
                "learning_point_forward": "lesson",
            },
            {
                "review_id": "skip-mech",
                "book_id": "n200",
                "exit_reason": "hold_trading_days",
                "sold_at": "2026-10-21",
            },
            {
                "review_id": "reply:abc",
                "book_id": "n206",
                "exit_reason": "identity_break_ey_band",
                "sold_at": "2026-10-19",
            },
            {
                "review_id": "keep-qb",
                "book_id": "n201",
                "exit_reason": "quality_break_financial_health",
                "sold_at": "2026-10-18",
            },
        ]
    }
    proposal = propose_start_cohort(queue)
    assert proposal["selection_id"] == COHORT_SELECTION_ID
    assert proposal["proposed_cohort_review_ids"] == ["keep-qb", "keep-ib"]
    assert proposal["auto_apply"] is False


def test_freeze_cohort_dry_run_then_apply():
    proposal = {
        "selection_id": COHORT_SELECTION_ID,
        "proposed_cohort_review_ids": ["a", "b"],
    }
    dry = freeze_start_cohort(start_gate={}, proposal=proposal, apply=False)
    assert dry["status"] == "dry_run"
    assert dry["would_freeze_n"] == 2
    assert not dry["gate"].get("cohort_review_ids")

    applied = freeze_start_cohort(start_gate={}, proposal=proposal, apply=True)
    assert applied["status"] == "frozen"
    assert applied["gate"]["cohort_review_ids"] == ["a", "b"]
    assert applied["gate"]["cohort_frozen_at"]

    noop = freeze_start_cohort(start_gate=applied["gate"], proposal=proposal, apply=True)
    assert noop["status"] == "noop_already_frozen"


def test_judgment_stub_fail_closed_and_observe_only():
    stub = judgment_in_the_round_stub()
    assert stub["influences_live"] is False
    assert stub["deferred_id"] == "N228"
    assert stub["buy"]["B1"]["unknown"] is True
    assert stub["sell"]["S4"]["cites"] == []


def test_refresh_persists_stores_and_findings(tmp_path: Path):
    queue_path = tmp_path / "post_sale_review_queue.json"
    queue_path.write_text(
        json.dumps(
            {
                "active": [
                    {
                        "review_id": "rev-ib",
                        "book_id": "n206",
                        "ticker": "AAA.L",
                        "exit_reason": "identity_break_ey_band",
                        "sold_at": "2026-10-20",
                        "learning_point_forward": "Wider TF before timing proof.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = refresh_cue_consumer_mft(
        output_dir=tmp_path,
        store_path=tmp_path / "cue_consumer_mft_observe.json",
        registration_path=tmp_path / "cue_consumer_mft_registration.json",
        start_gate_path=tmp_path / "cue_consumer_mft_start_gate.json",
        queue_path=queue_path,
        labels_path=tmp_path / "missing_labels.json",
        persist=True,
        today=date(2026, 10, 25),
    )
    assert payload["influences_live"] is False
    assert payload["registration_id"] == REGISTRATION_ID
    assert payload["status"] == "observe_lab_armed"
    assert payload["pipeline_status"] == PIPELINE_STATUS_ARMED
    assert payload["lab_arm_marker_id"] == LAB_ARM_MARKER_ID
    assert payload["spend_guard"]["steals_data_p1_fat_slot"] is False
    assert payload["judgment_in_the_round"]["rubric_id"]
    assert payload["autopsy_alignment_feed"]["count"] == 1
    assert payload["start_gate_cohort"]["owner_freeze_pending"] is True
    assert "knob_epoch_started_at" in payload["mid_flight_tune"]
    assert payload["mid_flight_tune"]["tune_spec_id"] == TUNE_SPEC_ID
    assert (tmp_path / "cue_consumer_mft_observe.json").is_file()
    assert (tmp_path / "cue_consumer_mft_registration.json").is_file()
    assert (tmp_path / "cue_consumer_mft_start_gate.json").is_file()

    findings = ops_findings_from_cue_consumer_mft(payload)
    assert findings
    assert all(f["auto_fixable"] is False for f in findings)
    assert any("Cue-consumer MFT lab refreshed" == f["title"] for f in findings)
    assert any(f["title"] == LAB_ARMED_TITLE for f in findings)
    assert any(f["title"] == COHORT_FREEZE_PROPOSED_TITLE for f in findings)

    gate = json.loads((tmp_path / "cue_consumer_mft_start_gate.json").read_text())
    assert gate["checkpoint_id"] == START_CHECKPOINT_ID
    assert gate["influences_live"] is False
    assert gate["proposed_cohort_review_ids"] == ["rev-ib"]
    assert gate["cohort_review_ids"] == []


def test_autopsy_voice_enrich_l633_and_same_day():
    item = {
        "book_tag": "N210",
        "ticker": "ZZZ.L",
        "hold_days": 0,
        "return_pct": -1.2,
        "exit_kind": "just_sold",
        "basis_label": "fair_cost_episode",
        "entry_at": "2026-10-25T09:00:00+00:00",
        "exit_at": "2026-10-25T14:00:00+00:00",
        "buy_decision": {
            "code": "ai_filter_clear",
            "label": "AI/filter clear",
            "join_ok": True,
        },
        "sell_decision": {
            "code": "manual_exit",
            "label": "Manual / other exit",
            "join_ok": True,
        },
    }
    opinion = build_initial_opinion(item)
    assert opinion["opinion_source"] == OPINION_SOURCE_DETERMINISTIC
    assert opinion["same_day_round_trip"] is True
    assert opinion["same_day_assessment"] == "likely_weakness"
    assert opinion["same_day_soft_penalty"] is True
    assert opinion["buy_strengths"]
    assert opinion["buy_weaknesses"]
    assert opinion["sell_strengths"]
    assert opinion["sell_weaknesses"]
    assert "same-calendar-day" in opinion["learning_point_forward"].lower() or (
        "same-day" in opinion["learning_point_forward"].lower()
    )
    assert "Same-day" in opinion["chart_annotations"]["episode"]
    assert opinion["influences_live"] is False

    considered = consider_human_comment(
        owner_comment="Premature sell — missed the climb",
        item={
            **item,
            "sell_decision": {
                "code": "leave_buy_tier",
                "label": "Left buy tier",
                "join_ok": True,
            },
        },
    )
    assert considered["stance"] == "partial"
    assert considered["influences_live"] is False

    reply = generate_factory_reply(
        owner_comment="Missed climb on wider TF",
        item={**item, "learning_point_forward": opinion["learning_point_forward"]},
        allow_llm=False,
    )
    assert reply["human_comment_consideration"]["stance"] in {
        "agree",
        "partial",
        "disagree",
        "unknown",
    }
    assert "Considered your Comment" in reply["text"]
    assert "Learning point forward" in reply["text"]
