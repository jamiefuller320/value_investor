"""Market warning triage for Daily hub morning recommendations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.daily_focus import build_daily_focus
from value_investor.market_warning_triage import (
    NON_DISMISSABLE_FLAG_IDS,
    NON_PARKABLE_FLAG_IDS,
    build_market_warning_triage_items,
    collect_open_market_flags,
    propose_triage,
)
from value_investor.storage import write_json


def _market_status_fixture() -> dict:
    return {
        "schema_version": 3,
        "generated_at": "2026-09-29T08:00:00+00:00",
        "focus_market": "euro_depth",
        "summary": {
            "spare_sprint": {"1": "dax", "2": "aex"},
        },
        "markets": [
            {
                "market_id": "euro_depth",
                "label": "EU depth composite",
                "role": "focus",
                "is_focus": True,
                "health": "warn",
                "filing_gaps": 2,
                "filing_health": {
                    "zero_body_tickers": ["HM-B.ST"],
                    "unmeasured_tickers": ["OIZ.IR"],
                    "zero_body_buy_tier": 1,
                    "unmeasured_buy_tier": 1,
                },
                "sprint_progress": {
                    "admission_warnings": [
                        {
                            "id": "zero_body_stuck",
                            "severity": "high",
                            "summary": (
                                "1 zero-body buy-tier name(s) unchanged "
                                "(cannot park; blocks sprint_ingest_complete)"
                            ),
                        },
                        {
                            "id": "unmeasured_stuck",
                            "severity": "high",
                            "summary": (
                                "1 unmeasured buy-tier name(s) unchanged "
                                "(cannot park; blocks sprint_ingest_complete)"
                            ),
                        },
                    ],
                    "remaining": {"unmeasured": 1, "zero_body": 1, "filing_gaps": 2},
                },
            },
            {
                "market_id": "dax",
                "label": "DAX",
                "role": "sprint",
                "is_focus": False,
                "health": "warn",
                "filing_gaps": 1,
                "filing_health": {
                    "unmeasured_tickers": ["G1A.DE"],
                    "unmeasured_buy_tier": 1,
                    "zero_body_tickers": [],
                },
                "sprint_progress": {
                    "admission_warnings": [
                        {
                            "id": "zero_improve_stall",
                            "severity": "high",
                            "summary": "Last 2 days improved nobody while filing gaps remain",
                        },
                        {
                            "id": "unmeasured_stuck",
                            "severity": "high",
                            "summary": (
                                "1 unmeasured buy-tier name(s) unchanged "
                                "(cannot park; blocks sprint_ingest_complete)"
                            ),
                        },
                    ],
                    "remaining": {"unmeasured": 1, "zero_body": 0, "filing_gaps": 1},
                },
            },
            {
                "market_id": "aex",
                "label": "AEX",
                "role": "sprint",
                "is_focus": False,
                "health": "warn",
                "filing_gaps": 0,
                "filing_health": {},
                "sprint_progress": {
                    "admission_warnings": [
                        {
                            "id": "no_observe_benchmark",
                            "severity": "warn",
                            "summary": "No Yahoo benchmark — Sunday screen-lite cannot refresh",
                        }
                    ],
                    "remaining": {},
                },
            },
            {
                "market_id": "aim",
                "label": "AIM",
                "role": "admitted",
                "is_focus": False,
                "health": "warn",
                "filing_gaps": 0,
                "filing_health": {},
                "sprint_progress": {"admission_warnings": []},
            },
            {
                "market_id": "ibex35",
                "label": "IBEX 35",
                "role": "admitted",
                "is_focus": False,
                "health": "warn",
                "filing_gaps": 0,
                "filing_health": {},
                "sprint_progress": {"admission_warnings": []},
            },
            {
                "market_id": "euro_stoxx50",
                "label": "Euro STOXX 50",
                "role": "admitted",
                "is_focus": False,
                "health": "ok",
                "filing_gaps": 0,
                "filing_health": {},
                "sprint_progress": {"admission_warnings": []},
            },
        ],
    }


def test_zero_body_not_dismissable_or_parkable() -> None:
    assert "zero_body_stuck" in NON_DISMISSABLE_FLAG_IDS
    assert "zero_body_stuck" in NON_PARKABLE_FLAG_IDS
    assert "unmeasured_stuck" in NON_DISMISSABLE_FLAG_IDS
    flag = {
        "kind": "admission_warning",
        "flag_id": "zero_body_stuck",
        "market_id": "euro_depth",
        "is_focus": True,
        "is_spare": False,
        "tickers": "HM-B.ST",
        "summary": "stuck",
    }
    triage = propose_triage(flag)
    assert triage["action"] == "deepen"
    assert triage["dismissable"] is False
    assert triage["parkable"] is False
    assert triage["prefer_discuss"] is True


def test_dax_spare_unmeasured_deepen_accept_not_discuss() -> None:
    """Spare unmeasured cannot park, but Accept observes leave-on-spare (no euro divert)."""
    flag = {
        "kind": "admission_warning",
        "flag_id": "unmeasured_stuck",
        "market_id": "dax",
        "is_focus": False,
        "is_spare": True,
        "tickers": "G1A.DE",
        "summary": "stuck",
    }
    triage = propose_triage(flag)
    assert triage["action"] == "deepen"
    assert triage["dismissable"] is False
    assert triage["parkable"] is False
    assert triage["prefer_discuss"] is False
    assert "euro" in triage["rationale"].lower() or "fat slot" in triage["rationale"].lower()


def test_dax_spare_stall_parks_without_diverting_fat_slot() -> None:
    flag = {
        "kind": "admission_warning",
        "flag_id": "zero_improve_stall",
        "market_id": "dax",
        "is_focus": False,
        "is_spare": True,
        "tickers": "",
        "summary": "stall",
    }
    triage = propose_triage(flag)
    assert triage["action"] == "park"
    assert triage["prefer_discuss"] is False
    assert "fat slot" in triage["rationale"].lower() or "euro" in triage["rationale"].lower()


def test_collect_flags_covers_euro_dax_ritual_rollup() -> None:
    flags = collect_open_market_flags(_market_status_fixture())
    by_key = {(f["market_id"], f["flag_id"]): f for f in flags}
    assert ("euro_depth", "zero_body_stuck") in by_key
    assert ("euro_depth", "unmeasured_stuck") in by_key
    assert ("dax", "zero_improve_stall") in by_key
    assert ("dax", "unmeasured_stuck") in by_key
    assert ("aex", "no_observe_benchmark") in by_key
    # Admitted ritual ambers roll up — not one row per market.
    assert ("multi", "health_warn_rollup") in by_key
    rollup = by_key[("multi", "health_warn_rollup")]
    assert "aim" in (rollup.get("markets") or [])
    assert "ibex35" in (rollup.get("markets") or [])
    # euro_stoxx50 health=ok → not in ritual rollup
    assert "euro_stoxx50" not in (rollup.get("markets") or [])


def test_ingest_deviation_dismiss_observe_safe() -> None:
    flags = collect_open_market_flags(
        {"focus_market": "euro_depth", "summary": {}, "markets": []},
        ingest_deviations={
            "items": [
                {
                    "id": "dev-euro_depth-MC.PA-blocker_no_improve",
                    "status": "open",
                    "market": "euro_depth",
                    "ticker": "MC.PA",
                    "kind": "blocker_no_improve",
                    "signal_triage": {
                        "human_action": "dismiss",
                        "proposed_action": "dismiss",
                        "reason": "buy_patchy_leftover",
                    },
                }
            ]
        },
    )
    assert len(flags) == 1
    triage = propose_triage(flags[0])
    assert triage["action"] == "dismiss"
    assert triage["prefer_discuss"] is False
    assert "ingest-deviations dismiss" in (triage.get("cli_hint") or "")


def test_build_items_prefer_discuss_on_euro_zero_body() -> None:
    tasks, recs = build_market_warning_triage_items(
        market_status=_market_status_fixture(),
        priority_start=5,
        generated_at="2026-09-29T02:30:00Z",
    )
    assert tasks
    assert len(tasks) == len(recs)
    zero = next(t for t in tasks if t["task_ref"] == "mwarn:euro_depth:zero_body_stuck")
    assert zero["triage_action"] == "deepen"
    assert zero["prefer_discuss"] is True
    assert zero["dismissable"] is False
    assert zero["work_class"] == "surface"
    assert zero["source"] == "market_warning_triage"
    rec = next(r for r in recs if r["id"] == zero["recommendation_id"])
    assert rec["accept_action"]["kind"] == "focus-ack"
    assert "Discuss daily recommendation" in rec["discuss_prompt"]
    assert rec["triage_action"] == "deepen"

    dax_stall = next(t for t in tasks if t["task_ref"] == "mwarn:dax:zero_improve_stall")
    assert dax_stall["triage_action"] == "park"
    assert dax_stall["prefer_discuss"] is False

    # Focus deepen sorts before spare parks.
    assert tasks[0]["task_ref"].startswith("mwarn:euro_depth:")


def test_closed_ids_skip_triage_row() -> None:
    tasks, _recs = build_market_warning_triage_items(
        market_status=_market_status_fixture(),
        closed_ids={"mwarn:euro_depth:zero_body_stuck"},
    )
    refs = {t["task_ref"] for t in tasks}
    assert "mwarn:euro_depth:zero_body_stuck" not in refs
    assert "mwarn:euro_depth:unmeasured_stuck" in refs


def test_daily_focus_emits_market_warning_recommendations(tmp_path: Path) -> None:
    write_json(tmp_path / "market_status.json", _market_status_fixture(), compact=False)
    write_json(
        tmp_path / "project_daily_seed.json",
        {
            "schema_version": 1,
            "focus_lines": [
                {
                    "id": "focus-1",
                    "priority": 1,
                    "title": "P1 holdings rememo",
                    "summary": "Leave euro fat slot",
                }
            ],
        },
        compact=False,
    )
    write_json(
        tmp_path / "human_tasks_board.json",
        {"schema_version": 1, "counts": {}, "tasks": []},
        compact=False,
    )
    write_json(
        tmp_path / "progress_report.json",
        {"schema_version": 1, "actionable": {"defer_now": []}},
        compact=False,
    )
    write_json(
        tmp_path / "ui_state_reconciliation.json",
        {"schema_version": 1, "overall": "ok", "checks": []},
        compact=False,
    )
    write_json(tmp_path / "latest.json", {"learning_tracks_dual_suite": {}}, compact=False)
    write_json(
        tmp_path / "observe_utilization.json",
        {"surface_freshness": "fresh"},
        compact=False,
    )
    write_json(
        tmp_path / "ingest_deviations.json",
        {"schema_version": 1, "items": []},
        compact=False,
    )

    payload = build_daily_focus(
        data_dir=tmp_path,
        now=datetime(2026, 9, 29, 2, 30, tzinfo=UTC),
    )
    assert payload["counts"]["market_warnings"] >= 3
    mwarn = [t for t in payload["tasks"] if t.get("source") == "market_warning_triage"]
    assert mwarn
    assert all(t.get("recommendation") for t in mwarn)
    zero = next(t for t in mwarn if "zero_body_stuck" in t["task_ref"])
    assert zero["recommendation"]["prefer_discuss"] is True
    assert zero["status"]["ready"] is False
    park = next(t for t in mwarn if t["task_ref"] == "mwarn:dax:zero_improve_stall")
    assert park["recommendation"]["triage_action"] == "park"
    assert park["status"]["ready"] is True
