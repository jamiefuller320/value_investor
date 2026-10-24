"""Tests for week-first archive pack order, gated run, and bottleneck review."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from value_investor.ops_monitor import check_universe_filing_archive_pack_bottleneck
from value_investor.universe_filing_archive_pack_order import (
    PACK_ORDER_ID,
    build_week_first_pack_plan,
    iter_iso_weeks_backward,
    summarize_plan_by_week,
)
from value_investor.universe_filing_archive_pack_run import (
    FINDING_TITLE_STALE,
    build_bottleneck_review,
    format_bottleneck_review_summary,
    merge_unit_results_into_by_market,
    ops_finding_from_bottleneck_review,
    resolve_archive_market_roster,
    run_universe_filing_archive_pack,
    unit_status_counts,
)


def test_week_first_then_backward_order() -> None:
    as_of = date(2026, 10, 1)  # Thu → ISO week 40 of 2026
    weeks = iter_iso_weeks_backward(as_of=as_of, lookback_weeks=3)
    assert weeks[0][0] == 2026 and weeks[0][1] == 40
    assert weeks[1][1] == 39
    assert weeks[2][1] == 38

    plan = build_week_first_pack_plan(
        ["ftse350", "euro_depth", "sp500"],
        as_of=as_of,
        lookback_weeks=2,
    )
    assert plan["pack_order"] == PACK_ORDER_ID
    assert plan["unit_count"] == 6  # 2 weeks × 3 markets
    units = plan["units"]
    # Current week first across all markets, then prior week.
    assert units[0]["iso_week"] == 40 and units[0]["market_id"] == "ftse350"
    assert units[1]["iso_week"] == 40 and units[1]["market_id"] == "euro_depth"
    assert units[2]["iso_week"] == 40 and units[2]["market_id"] == "sp500"
    assert units[3]["iso_week"] == 39 and units[3]["market_id"] == "ftse350"
    by_week = summarize_plan_by_week(plan)
    assert by_week[0]["iso_week"] == 40
    assert by_week[0]["market_count"] == 3


def test_gated_run_suspends_on_body_stall_not_fat_slot(tmp_path: Path) -> None:
    dispatch = tmp_path / "dispatch.json"
    status = tmp_path / "market_status.json"
    policy = tmp_path / "policy.json"
    pack_run_path = tmp_path / "pack_run.json"
    bottleneck_path = tmp_path / "bottleneck.json"
    dispatch.write_text(
        json.dumps(
            {
                "mode": "sprint",
                "ingest_sprint_complete": False,
                "focus_market": "euro_depth",
                "ingest_cascade": {"head_needs_fat_slot": True},
                "filing_health": {"unmeasured_buy_tier": 1},
            }
        ),
        encoding="utf-8",
    )
    status.write_text(
        json.dumps({"admitted_markets": ["euro_depth", "sp500"]}),
        encoding="utf-8",
    )
    policy.write_text(json.dumps({"focus_market": "euro_depth"}), encoding="utf-8")

    # Quiet weekday night — body stall still suspends; the fat slot does not.
    result = run_universe_filing_archive_pack(
        now=datetime(2026, 10, 1, 22, 0, tzinfo=UTC),
        dry_run=True,
        dispatch_path=dispatch,
        market_status_path=status,
        policy_path=policy,
        pack_run_path=pack_run_path,
        bottleneck_path=bottleneck_path,
        persist=True,
    )
    assert result["exit_code"] == 0
    pack_run = result["pack_run"]
    review = result["bottleneck_review"]
    assert pack_run["outcome"] == "suspend"
    assert "focus_fat_slot_sprint_active" not in pack_run["gate"]["focus_pressure_reasons"]
    assert any(
        str(reason).startswith("focus_unmeasured")
        for reason in pack_run["gate"]["focus_pressure_reasons"]
    )
    assert pack_run["pack_order"] == PACK_ORDER_ID
    assert pack_run["fourth_equal_sprint_stream"] is False
    assert review["outcome"] == "suspend"
    assert review["auto_rewrite_deepen"] is False
    assert any(b.get("kind") == "gate_block" for b in review["bottlenecks"])
    stage_ids = [s["id"] for s in review["stages"]]
    assert stage_ids == [
        "gate",
        "roster",
        "pack_plan",
        "assemble_dry",
        "write_artifacts",
        "bottleneck_review",
    ]
    assert pack_run_path.exists()
    assert bottleneck_path.exists()
    # A real focus-pressure suspend must not raise an ops finding.
    # Pin now to the run clock so the 36h stale threshold is not a calendar flake.
    assert (
        ops_finding_from_bottleneck_review(
            review,
            now=datetime(2026, 10, 1, 22, 0, tzinfo=UTC),
        )
        is None
    )


def test_gated_run_allows_while_fat_slot_occupied(tmp_path: Path) -> None:
    dispatch = tmp_path / "dispatch.json"
    status = tmp_path / "market_status.json"
    policy = tmp_path / "policy.json"
    dispatch.write_text(
        json.dumps(
            {
                "mode": "sprint",
                "ingest_sprint_complete": False,
                "focus_market": "euro_depth",
                "ingest_cascade": {"head_needs_fat_slot": True},
                "filing_health": {"unmeasured_buy_tier": 0, "zero_body_buy_tier": 0},
            }
        ),
        encoding="utf-8",
    )
    status.write_text(json.dumps({"admitted_markets": ["euro_depth"]}), encoding="utf-8")
    policy.write_text(json.dumps({"focus_market": "euro_depth"}), encoding="utf-8")

    result = run_universe_filing_archive_pack(
        now=datetime(2026, 10, 1, 22, 0, tzinfo=UTC),
        dry_run=True,
        lookback_weeks=1,
        dispatch_path=dispatch,
        market_status_path=status,
        policy_path=policy,
        pack_run_path=tmp_path / "pack_run.json",
        bottleneck_path=tmp_path / "bottleneck.json",
        persist=False,
    )
    pack_run = result["pack_run"]
    assert pack_run["outcome"] == "dry_complete"
    assert pack_run["gate"]["allowed"] is True
    assert pack_run["gate"]["focus_pressure_reasons"] == []
    assert pack_run["fourth_equal_sprint_stream"] is False
    assert pack_run["plan_unit_count"] > 0


def test_gated_dry_complete_when_allowed(tmp_path: Path) -> None:
    pack_run_path = tmp_path / "pack_run.json"
    bottleneck_path = tmp_path / "bottleneck.json"
    status = tmp_path / "market_status.json"
    policy = tmp_path / "policy.json"
    status.write_text(
        json.dumps({"admitted_markets": ["euro_depth", "sp500", "asx200"]}),
        encoding="utf-8",
    )
    policy.write_text("{}", encoding="utf-8")

    result = run_universe_filing_archive_pack(
        now=datetime(2026, 10, 1, 22, 0, tzinfo=UTC),
        dry_run=True,
        lookback_weeks=2,
        pack_run_path=pack_run_path,
        bottleneck_path=bottleneck_path,
        market_status_path=status,
        policy_path=policy,
        persist=True,
        force_allow_for_test=True,
    )
    assert result["exit_code"] == 0
    pack_run = result["pack_run"]
    review = result["bottleneck_review"]
    assert pack_run["outcome"] == "dry_complete"
    # ftse350 + 3 admitted × 2 weeks
    assert pack_run["plan_unit_count"] == 8
    assert review["throughput"]["units_planned"] == 8
    assert review["throughput"]["units_attempted"] == 0  # dry — no fetches
    assert "ftse350" in pack_run["markets"]
    text = format_bottleneck_review_summary(review)
    assert "dry_complete" in text
    assert "week_first_then_backward" in text


def test_roster_prefers_admitted_markets() -> None:
    roster = resolve_archive_market_roster(
        market_status={"admitted_markets": ["sp500", "euro_depth"]},
        policy={"focus_market": "euro_depth", "market_queue": ["hang_seng"]},
    )
    assert roster[0] == "ftse350"
    assert "sp500" in roster and "euro_depth" in roster
    assert "hang_seng" not in roster  # admitted list wins over queue fallback


def test_ops_finding_stale_and_bottleneck_check(tmp_path: Path) -> None:
    assert ops_finding_from_bottleneck_review(None)["title"] == FINDING_TITLE_STALE

    stale = build_bottleneck_review(
        run_id="t1",
        generated_at=datetime(2026, 9, 1, 22, 0, tzinfo=UTC),
        outcome="suspend",
        gate={
            "decision": "suspend",
            "allowed": False,
            "focus_pressure_reasons": ["focus_unmeasured_buy_tier=1"],
        },
        plan={},
        stages=[{"id": "gate", "elapsed_ms": 1, "status": "ok", "detail": {}}],
        dry_run=True,
    )
    finding = ops_finding_from_bottleneck_review(
        stale,
        now=datetime(2026, 10, 1, 22, 0, tzinfo=UTC),
        stale_after_hours=36.0,
    )
    assert finding is not None
    assert finding["title"] == FINDING_TITLE_STALE
    assert finding["auto_fixable"] is False

    path = tmp_path / "bottleneck.json"
    path.write_text(json.dumps(stale), encoding="utf-8")
    ops = check_universe_filing_archive_pack_bottleneck(
        store_path=path,
        stale_after_hours=36.0,
    )
    assert len(ops) == 1
    assert ops[0].title == FINDING_TITLE_STALE


def test_workflow_pins_weekday_2200_utc_and_week_first() -> None:
    text = Path(".github/workflows/universe-filing-archive-pack.yml").read_text(encoding="utf-8")
    assert 'cron: "0 22 * * *"' in text
    assert 'cron: "0 22 * * 1-5"' not in text
    assert "cancel-in-progress: true" in text
    assert "ftse-universe-archive-pack" in text
    assert "universe_filing_archive_bottleneck_review.json" in text
    assert "fourth" not in text.lower() or "NOT a fourth" in text or "not a fourth" in text.lower()

    ops_doc = Path("docs/ops/universe-filing-archive-pack.md").read_text(encoding="utf-8")
    assert "week-first" in ops_doc.lower() or "Week-first" in ops_doc
    assert "week_first_then_backward" in ops_doc
    assert "22:00 UTC" in ops_doc
    assert "unit_results" in ops_doc


def test_merge_unit_results_into_by_market_dedupes_and_skips_budget() -> None:
    planned = {
        "ftse350": {
            "units_planned": 1,
            "units_attempted": 0,
            "units_completed": 0,
            "errors": 0,
            "elapsed_ms": 0,
        },
        "sp500": {
            "units_planned": 1,
            "units_attempted": 0,
            "units_completed": 0,
            "errors": 0,
            "elapsed_ms": 0,
        },
        "asx200": {
            "units_planned": 1,
            "units_attempted": 0,
            "units_completed": 0,
            "errors": 0,
            "elapsed_ms": 0,
        },
        "euro_depth": {
            "units_planned": 1,
            "units_attempted": 0,
            "units_completed": 0,
            "errors": 0,
            "elapsed_ms": 0,
        },
    }
    unit_results = [
        {"unit_id": "2026-W43:sp500", "market_id": "sp500", "status": "completed", "objects": 2},
        {"unit_id": "2026-W43:euro_depth", "market_id": "euro_depth", "status": "completed"},
        # Two ticker-level no_bodies rows for one unit → one attempted.
        {"unit_id": "2026-W43:ftse350", "market_id": "ftse350", "status": "no_bodies"},
        {"unit_id": "2026-W43:ftse350", "market_id": "ftse350", "status": "no_bodies"},
        {"unit_id": "2026-W43:asx200", "market_id": "asx200", "status": "empty"},
        {"unit_id": "2026-W42:sp500", "market_id": "sp500", "status": "skipped_budget"},
    ]
    by_market = merge_unit_results_into_by_market(planned, unit_results)
    assert by_market["sp500"]["units_attempted"] == 1
    assert by_market["sp500"]["units_completed"] == 1
    assert by_market["euro_depth"]["units_attempted"] == 1
    assert by_market["euro_depth"]["units_completed"] == 1
    assert by_market["ftse350"]["units_attempted"] == 1
    assert by_market["ftse350"]["units_completed"] == 0
    assert by_market["asx200"]["units_attempted"] == 1
    assert by_market["asx200"]["units_completed"] == 0
    assert unit_status_counts(unit_results) == {
        "completed": 2,
        "empty": 1,
        "no_bodies": 1,
        "skipped_budget": 1,
    }

    review = build_bottleneck_review(
        run_id="obs-1",
        generated_at=datetime(2026, 10, 24, 0, 26, tzinfo=UTC),
        outcome="apply_complete",
        gate={"decision": "allow", "allowed": True},
        plan={
            "unit_count": 4,
            "units": [
                {"unit_id": "2026-W43:ftse350", "market_id": "ftse350"},
                {"unit_id": "2026-W43:sp500", "market_id": "sp500"},
                {"unit_id": "2026-W43:asx200", "market_id": "asx200"},
                {"unit_id": "2026-W43:euro_depth", "market_id": "euro_depth"},
            ],
        },
        stages=[{"id": "assemble", "elapsed_ms": 10, "status": "ok", "detail": {}}],
        dry_run=False,
        unit_results=unit_results,
    )
    assert review["by_market"]["sp500"]["units_completed"] == 1
    assert review["by_market"]["ftse350"]["units_attempted"] == 1
    assert review["unit_status_counts"]["completed"] == 2
    assert len(review["unit_results"]) == 6
