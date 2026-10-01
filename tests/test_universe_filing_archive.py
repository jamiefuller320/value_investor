"""Tests for L499 universe filing archive scaffolds (isolation / miss-rate / hydrate)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.ops_monitor import check_universe_filing_archive_miss_rate
from value_investor.universe_filing_archive_hydrate import (
    hydrate_or_continue_live_deepen,
    pack_index_path,
    try_hydrate_pack,
)
from value_investor.universe_filing_archive_isolation import (
    ARCHIVE_LANE_BUDGET_ID,
    CRITICAL_PATH_BUDGET_ID,
    archive_budget_id,
    archive_lane_gate,
    budgets_share_quota,
    critical_budget_id,
    focus_pressure_reasons,
    in_quiet_window,
)
from value_investor.universe_filing_archive_miss_rate import (
    FINDING_TITLE,
    format_archive_miss_rate_summary,
    ops_finding_from_archive_miss_rate,
    update_universe_filing_archive_miss_rate,
)


def test_budget_ids_do_not_share_quota_across_lanes() -> None:
    assert archive_budget_id("sec").startswith(ARCHIVE_LANE_BUDGET_ID)
    assert critical_budget_id("sec").startswith(CRITICAL_PATH_BUDGET_ID)
    assert not budgets_share_quota(archive_budget_id("sec"), critical_budget_id("sec"))
    assert budgets_share_quota(archive_budget_id("sec"), archive_budget_id("ir_pdf"))


def test_quiet_window_weekend_and_weekday_band() -> None:
    saturday = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)  # Sat
    assert in_quiet_window(saturday) is True
    weekday_day = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)  # Thu noon
    assert in_quiet_window(weekday_day) is False
    weekday_night = datetime(2026, 10, 1, 22, 0, tzinfo=UTC)
    assert in_quiet_window(weekday_night) is True
    weekday_early = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    assert in_quiet_window(weekday_early) is True


def test_focus_pressure_suspends_while_fat_slot_sprint_active() -> None:
    reasons = focus_pressure_reasons(
        dispatch={
            "mode": "sprint",
            "ingest_sprint_complete": False,
            "focus_market": "euro_depth",
            "filing_health": {"unmeasured_buy_tier": 2, "zero_body_buy_tier": 1},
        }
    )
    assert "focus_fat_slot_sprint_active" in reasons
    assert any(r.startswith("focus_unmeasured") for r in reasons)
    assert any(r.startswith("focus_zero_body") for r in reasons)

    gate = archive_lane_gate(
        now=datetime(2026, 10, 3, 12, 0, tzinfo=UTC),  # quiet weekend
        dispatch={
            "mode": "sprint",
            "ingest_sprint_complete": False,
            "focus_market": "euro_depth",
            "filing_health": {},
        },
        market_status={},
    )
    assert gate["allowed"] is False
    assert gate["decision"] == "suspend"
    assert gate["preemptible"] is True
    assert gate["fourth_equal_sprint_stream"] is False


def test_archive_lane_allows_only_when_quiet_and_no_pressure() -> None:
    gate = archive_lane_gate(
        now=datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
        dispatch={
            "mode": "maintenance",
            "ingest_sprint_complete": True,
            "focus_market": "euro_depth",
            "filing_health": {"unmeasured_buy_tier": 0, "zero_body_buy_tier": 0},
        },
        market_status={},
    )
    assert gate["allowed"] is True
    assert gate["decision"] == "allow"
    assert gate["in_quiet_window"] is True

    daytime = archive_lane_gate(
        now=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        dispatch={
            "mode": "maintenance",
            "ingest_sprint_complete": True,
            "filing_health": {},
        },
        market_status={},
        require_quiet_window=True,
    )
    assert daytime["allowed"] is False
    assert daytime["decision"] == "quiet_only"


def test_hydrate_fail_open_on_miss_and_hit(tmp_path: Path) -> None:
    miss = try_hydrate_pack("euro_depth", "MC.PA", cold_root=tmp_path)
    assert miss.status == "miss"
    assert miss.fail_open is True
    wrapped = hydrate_or_continue_live_deepen("euro_depth", "MC.PA", cold_root=tmp_path)
    assert wrapped["continue_live_deepen"] is True
    assert wrapped["use_pack"] is False

    index = pack_index_path("euro_depth", "MC.PA", cold_root=tmp_path)
    index.parent.mkdir(parents=True)
    index.write_text(
        json.dumps({"objects": [{"id": "a1", "period": "annual"}]}),
        encoding="utf-8",
    )
    hit = try_hydrate_pack("euro_depth", "MC.PA", cold_root=tmp_path)
    assert hit.status == "hit"
    assert hit.object_count == 1
    assert hit.fail_open is True
    assert hit.to_dict()["continue_live_deepen"] is True


def test_miss_rate_rollup_and_ops_finding(tmp_path: Path) -> None:
    flip_path = tmp_path / "buy_tier_flip_lag.json"
    store_path = tmp_path / "universe_filing_archive_miss_rate.json"
    flip_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-10-01T08:00:00+00:00",
                "names": {
                    "ftse350:AAA.L": {
                        "key": "ftse350:AAA.L",
                        "market_id": "ftse350",
                        "ticker": "AAA.L",
                        "status": "open",
                        "blocking_stage": "no_key_bodies",
                        "hours_since_flip": 30,
                    },
                    "ftse350:BBB.L": {
                        "key": "ftse350:BBB.L",
                        "market_id": "ftse350",
                        "ticker": "BBB.L",
                        "status": "open",
                        "blocking_stage": "no_index",
                        "hours_since_flip": 12,
                    },
                    "ftse350:CCC.L": {
                        "key": "ftse350:CCC.L",
                        "market_id": "ftse350",
                        "ticker": "CCC.L",
                        "status": "usable",
                        "blocking_stage": None,
                        "flip_at": "2026-09-28T00:00:00+00:00",
                        "key_bodies_at": "2026-09-29T00:00:00+00:00",
                        "hours_to_usable": 24,
                    },
                    "ftse350:DDD.L": {
                        "key": "ftse350:DDD.L",
                        "market_id": "ftse350",
                        "ticker": "DDD.L",
                        "status": "usable",
                        "blocking_stage": None,
                        "flip_at": "2026-09-28T00:00:00+00:00",
                        "key_bodies_at": "2026-09-27T00:00:00+00:00",
                    },
                    "euro_depth:EEE.PA": {
                        "key": "euro_depth:EEE.PA",
                        "market_id": "euro_depth",
                        "ticker": "EEE.PA",
                        "status": "open",
                        "blocking_stage": "no_key_bodies",
                        "hours_since_flip": 40,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    payload = update_universe_filing_archive_miss_rate(
        flip_lag_path=flip_path,
        store_path=store_path,
        warn_min_cohort=5,
        warn_min_miss_rate=0.5,
        persist=True,
    )
    summary = payload["summary"]
    assert summary["cohort_count"] == 5
    assert summary["enter_body_miss_count"] == 4  # AAA BBB CCC EEE (DDD had bodies before flip)
    assert summary["open_still_missing_bodies"] == 3
    assert summary["warn"] is True
    assert store_path.exists()

    finding = ops_finding_from_archive_miss_rate(payload)
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False
    text = format_archive_miss_rate_summary(payload)
    assert "Cohort: 5" in text

    ops = check_universe_filing_archive_miss_rate(
        flip_lag_path=flip_path,
        store_path=store_path,
        persist=True,
    )
    assert len(ops) == 1
    assert ops[0].title == FINDING_TITLE
    assert ops[0].auto_fixable is False


def test_miss_rate_quiet_when_sample_small(tmp_path: Path) -> None:
    flip_path = tmp_path / "flip.json"
    store_path = tmp_path / "miss.json"
    flip_path.write_text(
        json.dumps(
            {
                "names": {
                    "ftse350:AAA.L": {
                        "market_id": "ftse350",
                        "ticker": "AAA.L",
                        "status": "open",
                        "blocking_stage": "no_key_bodies",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    payload = update_universe_filing_archive_miss_rate(
        flip_lag_path=flip_path,
        store_path=store_path,
        persist=False,
    )
    assert payload["summary"]["warn"] is False
    assert ops_finding_from_archive_miss_rate(payload) is None
