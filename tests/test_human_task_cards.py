"""Tests for human-task acks and board sort / enrichment."""

from __future__ import annotations

from pathlib import Path

from value_investor.human_task_ack import run_human_task_ack
from value_investor.human_task_acks import load_human_task_acks, record_human_task_ack
from value_investor.human_task_cards import (
    APPROVAL_GATE_IDS,
    KNOB_PRIORS_REVIEW_TASK_ID,
    apply_knob_priors_observe_auto_ack,
    build_human_tasks_board,
    knob_priors_ack_sufficient,
    write_human_tasks_board,
)
from value_investor.human_tasks_checklist import load_human_tasks_checklist
from value_investor.storage import write_json


def _write_low_conf_zero_gap_priors(data_dir: Path) -> None:
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True, exist_ok=True)
    write_json(
        paper / "knob_calibration_priors.json",
        {
            "scope": "knob_calibration_multi",
            "calibrated_at": "2026-09-28T10:00:00+00:00",
            "tracks": {
                "rules": {
                    "track_id": "rules",
                    "readiness": {
                        "ready_for_priors": False,
                        "ready_for_shadow_bootstrap": False,
                        "score_gap_vs_runner_up": 0.0,
                    },
                    "recommended_prior": {"confidence": "low", "knobs": {"max_positions": 3}},
                },
                "ai_judgment": {
                    "track_id": "ai_judgment",
                    "readiness": {
                        "ready_for_priors": False,
                        "ready_for_shadow_bootstrap": False,
                        "score_gap_vs_runner_up": 0.0,
                    },
                    "recommended_prior": {
                        "confidence": "insufficient",
                        "knobs": {"max_positions": 4},
                    },
                },
            },
        },
    )


def test_knob_priors_ack_sufficient_when_low_conf_and_zero_gap():
    status = knob_priors_ack_sufficient(
        {
            "tracks": {
                "rules": {
                    "readiness": {"score_gap_vs_runner_up": 0.0},
                    "recommended_prior": {"confidence": "low"},
                },
                "ai_judgment": {
                    "readiness": {"score_gap_vs_runner_up": 0.001},
                    "recommended_prior": {"confidence": "insufficient"},
                },
            }
        }
    )
    assert status["ack_sufficient"] is True
    assert status["reason"] == "low_confidence_and_no_discrimination"
    assert len(status["tracks"]) == 2


def test_knob_priors_ack_not_sufficient_when_gap_or_confidence_rises():
    high_gap = knob_priors_ack_sufficient(
        {
            "tracks": {
                "rules": {
                    "readiness": {"score_gap_vs_runner_up": 0.02},
                    "recommended_prior": {"confidence": "low"},
                }
            }
        }
    )
    assert high_gap["ack_sufficient"] is False
    medium = knob_priors_ack_sufficient(
        {
            "tracks": {
                "rules": {
                    "readiness": {"score_gap_vs_runner_up": 0.0},
                    "recommended_prior": {"confidence": "medium"},
                }
            }
        }
    )
    assert medium["ack_sufficient"] is False


def test_board_marks_knob_priors_auto_ackable(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_low_conf_zero_gap_priors(data_dir)
    board = build_human_tasks_board(data_dir=data_dir)
    hit = next(row for row in board["tasks"] if row["id"] == KNOB_PRIORS_REVIEW_TASK_ID)
    assert hit["auto_ackable"] is True
    assert hit["ack_sufficient"] is True
    assert hit["analysis"]["ack_sufficient"] is True
    assert hit["analysis"]["headline"].startswith("Knob priors · ack sufficient")


def test_write_board_auto_acks_knob_priors_observe_only(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_low_conf_zero_gap_priors(data_dir)
    # Promote gate must remain unacked even when review auto-acks.
    board = write_human_tasks_board(data_dir=data_dir)
    review = next(row for row in board["tasks"] if row["id"] == KNOB_PRIORS_REVIEW_TASK_ID)
    promote = next(row for row in board["tasks"] if row["id"] == "sunday-promote-knobs-gate")
    assert review["sort_bucket"] == "acked"
    assert review["ack"]["decision"] == "ack_observe"
    assert review["ack"]["stale"] is False
    assert promote["sort_bucket"] == "unacked"
    store = load_human_task_acks(data_dir)
    row = next(r for r in store["acks"] if r["task_id"] == KNOB_PRIORS_REVIEW_TASK_ID)
    assert row["decision"] == "ack_observe"
    assert row["source"] == "board_auto_no_discrimination"
    assert row["acked_by"] == "system"
    # Idempotent second write
    assert apply_knob_priors_observe_auto_ack(data_dir) is None


def test_knob_priors_auto_ack_skips_when_not_sufficient(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True, exist_ok=True)
    write_json(
        paper / "knob_calibration_priors.json",
        {
            "tracks": {
                "rules": {
                    "readiness": {"score_gap_vs_runner_up": 0.05},
                    "recommended_prior": {"confidence": "medium"},
                }
            }
        },
    )
    assert apply_knob_priors_observe_auto_ack(data_dir) is None
    board = write_human_tasks_board(data_dir=data_dir)
    review = next(row for row in board["tasks"] if row["id"] == KNOB_PRIORS_REVIEW_TASK_ID)
    assert review["auto_ackable"] is False
    assert review["sort_bucket"] == "unacked"


def test_timestamp_only_republish_does_not_stale_ack(tmp_path: Path):
    """Ack stays bottom/disabled when artifacts only bump generated_at."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_json(
        data_dir / "ingest_deviations.json",
        {
            "updated_at": "2026-09-27T12:00:00+00:00",
            "open_items": [{"id": "x1", "ticker": "AAA", "kind": "leftover", "status": "open"}],
        },
    )
    write_json(
        data_dir / "market_status.json",
        {
            "generated_at": "2026-09-27T12:00:00+00:00",
            "admitted_markets": ["sp500"],
            "markets": [
                {
                    "market_id": "sp500",
                    "is_admitted": True,
                    "epoch0": {
                        "ai_judgment": False,
                        "knob_apply": False,
                        "acted": True,
                        "holdings": 10,
                    },
                    "learning": {"current_phase": 1, "blockers": ["need marks"]},
                }
            ],
        },
    )
    write_json(
        data_dir / "pr_fix_occasions.json",
        {
            "updated_at": "2026-09-27T12:00:00+00:00",
            "occasions": [{"pr": 1}, {"pr": 2}],
            "common_issues": {
                "by_reason": [{"failure_reason": "merge conflict", "count": 2}],
            },
        },
    )
    board = build_human_tasks_board(data_dir=data_dir)
    targets = {
        "adhoc-review-ingest-deviations",
        "sunday-shard-epoch0-watch",
        "monthly-pr-fix-common-issues",
    }
    fps = {}
    for row in board["tasks"]:
        if row["id"] in targets:
            fps[row["id"]] = row["analysis"]["fingerprint"]
            record_human_task_ack(
                data_dir,
                task_id=row["id"],
                decision="ack_observe",
                finding_fingerprint=row["analysis"]["fingerprint"],
            )
    assert len(fps) == 3

    # Republish with only timestamps changed — content identical
    write_json(
        data_dir / "ingest_deviations.json",
        {
            "updated_at": "2026-09-28T08:00:00+00:00",
            "open_items": [{"id": "x1", "ticker": "AAA", "kind": "leftover", "status": "open"}],
        },
    )
    write_json(
        data_dir / "market_status.json",
        {
            "generated_at": "2026-09-28T08:00:00+00:00",
            "admitted_markets": ["sp500"],
            "markets": [
                {
                    "market_id": "sp500",
                    "is_admitted": True,
                    "epoch0": {
                        "ai_judgment": False,
                        "knob_apply": False,
                        "acted": True,
                        "holdings": 10,
                        "last_run_at": "2026-09-28T07:30:00+00:00",
                        "nav": 999.0,
                    },
                    "learning": {"current_phase": 1, "blockers": ["need marks"]},
                }
            ],
        },
    )
    write_json(
        data_dir / "pr_fix_occasions.json",
        {
            "updated_at": "2026-09-28T08:00:00+00:00",
            "occasions": [{"pr": 1}, {"pr": 2}],
            "common_issues": {
                "by_reason": [{"failure_reason": "merge conflict", "count": 2}],
            },
        },
    )
    board2 = build_human_tasks_board(data_dir=data_dir)
    for row in board2["tasks"]:
        if row["id"] not in targets:
            continue
        assert row["analysis"]["fingerprint"] == fps[row["id"]]
        assert row["sort_bucket"] == "acked"
        assert row["ack"]["acked"] is True
        assert row["ack"]["stale"] is False


def test_content_change_marks_ack_stale(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_json(
        data_dir / "ingest_deviations.json",
        {
            "updated_at": "2026-09-27T12:00:00+00:00",
            "open_items": [],
        },
    )
    board = build_human_tasks_board(data_dir=data_dir)
    hit = next(row for row in board["tasks"] if row["id"] == "adhoc-review-ingest-deviations")
    record_human_task_ack(
        data_dir,
        task_id="adhoc-review-ingest-deviations",
        decision="ack_observe",
        finding_fingerprint=hit["analysis"]["fingerprint"],
    )
    write_json(
        data_dir / "ingest_deviations.json",
        {
            "updated_at": "2026-09-27T12:00:00+00:00",
            "open_items": [
                {"id": "y1", "ticker": "BBB", "kind": "buy", "status": "open", "summary": "pin"}
            ],
        },
    )
    board2 = build_human_tasks_board(data_dir=data_dir)
    hit2 = next(row for row in board2["tasks"] if row["id"] == "adhoc-review-ingest-deviations")
    assert hit2["sort_bucket"] == "new_info"
    assert hit2["ack"]["stale"] is True


def test_board_sorts_new_info_before_acked(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # Minimal analysis artifacts so fingerprints differ
    write_json(
        data_dir / "experiment_assessment.json",
        {
            "generated_at": "2026-09-26T12:00:00+00:00",
            "experiments": [{"experiment_id": "u4", "status": "recommend"}],
        },
    )
    write_json(
        data_dir / "engineering_tasks.json",
        {
            "updated_at": "2026-09-26T11:00:00+00:00",
            "tasks": [
                {
                    "id": "eng-old",
                    "status": "parked",
                    "title": "Old park",
                    "parked_at": "2026-09-01T00:00:00+00:00",
                }
            ],
            "traffic_control": {"pause_active": False},
        },
    )
    # Copy checklist path is default — board loads from repo checklist
    board = build_human_tasks_board(data_dir=data_dir)
    human = board["tasks"]
    assert human
    assert all(not row["automated"] for row in human)
    # Ack one task with matching fingerprint → goes to acked bucket
    target = next(row for row in human if row["id"] == "sunday-promote-knobs-gate")
    fp = target["analysis"]["fingerprint"]
    record_human_task_ack(
        data_dir,
        task_id="sunday-promote-knobs-gate",
        decision="ack_observe",
        finding_fingerprint=fp,
    )
    board2 = build_human_tasks_board(data_dir=data_dir)
    buckets = [row["sort_bucket"] for row in board2["tasks"]]
    assert "acked" in buckets
    acked_ids = [row["id"] for row in board2["tasks"] if row["sort_bucket"] == "acked"]
    assert acked_ids[-1] == "sunday-promote-knobs-gate" or "sunday-promote-knobs-gate" in acked_ids
    # Last group should be acked
    assert board2["tasks"][-1]["sort_bucket"] == "acked"

    # Stale fingerprint → new_info rises
    record_human_task_ack(
        data_dir,
        task_id="sunday-promote-knobs-gate",
        decision="ack_observe",
        finding_fingerprint="stale-old-fp",
    )
    board3 = build_human_tasks_board(data_dir=data_dir)
    promote = next(row for row in board3["tasks"] if row["id"] == "sunday-promote-knobs-gate")
    assert promote["sort_bucket"] == "new_info"
    assert board3["tasks"][0]["sort_bucket"] in {"new_info", "unacked"}
    assert promote["ack"]["stale"] is True


def test_approval_gates_cover_promotion_ids():
    assert "sunday-promote-knobs-gate" in APPROVAL_GATE_IDS
    assert "adhoc-live-capital-pack" in APPROVAL_GATE_IDS
    board = build_human_tasks_board(data_dir=Path("docs/data"))
    promote = next(row for row in board["tasks"] if row["id"] == "sunday-promote-knobs-gate")
    assert promote["approval_gate"] is True


def test_run_human_task_ack_rebinds_stale_ui_fingerprint(tmp_path: Path):
    """UI may send a lagging board fingerprint; rebind to live analysis so board is acked."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_json(
        data_dir / "analysis_review.json",
        {"generated_at": "2026-09-26T10:00:00+00:00", "summary": "ok"},
    )
    result = run_human_task_ack(
        data_dir,
        task_id="sunday-read-analysis-review",
        decision="ack_observe",
        finding_fingerprint="ui-lagging-fingerprint",
        source="test",
    )
    assert result["ok"] is True
    store = load_human_task_acks(data_dir)
    row = next(r for r in store["acks"] if r["task_id"] == "sunday-read-analysis-review")
    assert row["finding_fingerprint"] != "ui-lagging-fingerprint"
    board = build_human_tasks_board(data_dir=data_dir)
    hit = next(r for r in board["tasks"] if r["id"] == "sunday-read-analysis-review")
    assert hit["sort_bucket"] == "acked"
    assert hit["ack"]["stale"] is False
    assert result["counts"]["acked"] >= 1


def test_euro_ingest_cron_reimport_is_automated():
    payload = load_human_tasks_checklist()
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == "adhoc-euro-ingest-cron-reimport")
    assert row["automated"] is True
    assert "import-ingest-crons" in row["summary"]


def test_checklist_human_count_matches_board():
    checklist = load_human_tasks_checklist()
    human_ids = {
        task["id"]
        for section in checklist["sections"]
        for task in section["tasks"]
        if not task.get("automated")
    }
    board = build_human_tasks_board(data_dir=Path("docs/data"))
    board_ids = {row["id"] for row in board["tasks"]}
    assert board_ids == human_ids


def test_checklist_knob_priors_review_summary_mentions_ack_stop():
    payload = load_human_tasks_checklist()
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == KNOB_PRIORS_REVIEW_TASK_ID)
    assert "Acknowledge" in row["summary"] or "ack" in row["summary"].lower()
    assert "do not promote" in row["summary"].lower() or "Promotion is a separate" in row["summary"]
