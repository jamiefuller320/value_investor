"""Hunt-commit-hunt slices, priority order, and unchanged ceilings."""

from __future__ import annotations

from pathlib import Path

from value_investor.ingest_hunt import (
    MAINTENANCE_SLOT_SECONDS,
    SPARE_WAIT_SECONDS,
    SPRINT_RUNTIME_CEILING_SECONDS,
    SPRINT_TARGET_CEILING,
    advance_maintenance,
    advance_sprint,
    build_priority_names,
    filing_coverage_needs_fetch,
    finish_maintenance_hunt,
    spare_budget_when_head_released,
    sprint_slice,
)
from value_investor.library_ingest_cascade import DEFAULT_SPARE_WAIT_SECONDS
from value_investor.library_ingest_dispatch import FTSE_MAINTENANCE_MAX_RUNTIME_SECONDS
from value_investor.library_ingest_scheduler import FULL_STREAM_RUNTIME, FULL_STREAM_TARGETS
from value_investor.library_maintenance_capacity import load_maintenance_capacity


def test_ceilings_match_the_existing_budgets():
    assert SPRINT_TARGET_CEILING == FULL_STREAM_TARGETS == 24
    assert SPRINT_RUNTIME_CEILING_SECONDS == FULL_STREAM_RUNTIME == 2100.0
    assert MAINTENANCE_SLOT_SECONDS == FTSE_MAINTENANCE_MAX_RUNTIME_SECONDS == 3600.0
    assert SPARE_WAIT_SECONDS == DEFAULT_SPARE_WAIT_SECONDS == 2400.0


def test_released_head_gives_smallcap_the_existing_full_slot():
    targets, runtime, mode = spare_budget_when_head_released(45, stream=2)
    assert (targets, runtime, mode) == (24, 2100.0, "full")


def test_released_head_does_not_raise_the_cap_for_a_short_book():
    targets, runtime, mode = spare_budget_when_head_released(3, stream=1)
    assert targets == 3
    assert runtime == 3 * 87.5
    assert mode == "full"
    assert runtime < 2100.0


def test_workflow_ceilings_and_timeouts_are_unchanged():
    sprint_1 = Path(".github/workflows/library-ingest-sprint.yml").read_text(encoding="utf-8")
    sprint_2 = Path(".github/workflows/library-ingest-sprint-2.yml").read_text(encoding="utf-8")
    maintenance = Path(".github/workflows/library-ingest-maintenance.yml").read_text(
        encoding="utf-8"
    )
    assert "timeout-minutes: 110" in sprint_1
    assert "timeout-minutes: 110" in sprint_2
    assert "timeout-minutes: 120" in maintenance
    assert 'MAX_WAIT_SECONDS: "2400"' in sprint_1
    assert 'MAX_WAIT_SECONDS: "2400"' in sprint_2
    assert 'MAX_WAIT_SECONDS: "2400"' in maintenance
    assert 'RUNTIME="2100"' in sprint_1
    assert 'RUNTIME="2100"' in sprint_2
    assert 'RUNTIME="3600"' in maintenance
    assert "library-ingest-sprint-3" not in sprint_1
    assert "library-ingest-sprint-3" not in sprint_2
    assert "--explore" in sprint_2
    assert "--explore" in sprint_1
    assert "ingest_hunt_commit.sh" in maintenance
    assert "Empty spare backlog — slot still runs so catalogue explore can take one name" in sprint_1
    assert "Empty spare backlog — slot still runs so catalogue explore can take one name" in sprint_2
    assert "No parallel sprint markets with filing gaps" not in sprint_1
    assert "No parallel sprint 2 markets with filing gaps" not in sprint_2
    assert "should_run', 'false'" not in sprint_1
    assert "should_run', 'false'" not in sprint_2


def test_priority_is_holdings_then_open_strategy_names():
    names = build_priority_names(
        holdings=["GSK.L", "BARC.L"],
        episodes=[
            {
                "ticker": "AAPL",
                "market": "sp500",
                "status": "open",
                "fill_session": "2026-01-01",
                "exit_session": None,
            },
            {
                "ticker": "BARC.L",
                "market": "ftse350",
                "status": "open",
                "fill_session": "2026-01-01",
            },
            {
                "ticker": "OLD.L",
                "market": "ftse350",
                "status": "closed",
                "fill_session": "2026-01-01",
                "exit_session": "2026-02-01",
            },
            {
                "ticker": "WAIT.L",
                "market": "ftse350",
                "status": "open",
                "fill_session": None,
            },
        ],
    )
    assert [item["ticker"] for item in names] == ["BARC.L", "GSK.L", "AAPL"]
    assert [item["source"] for item in names] == ["holding", "holding", "strategy_open"]
    assert names[0]["market"] == "ftse350"
    assert names[2]["market"] == "sp500"


def test_fresh_coverage_is_not_fetched():
    assert (
        filing_coverage_needs_fetch(
            {"filings_total": 4, "filings_with_body": 4, "indexed_without_body": 0}
        )
        is False
    )
    assert (
        filing_coverage_needs_fetch(
            {"filings_total": 4, "filings_with_body": 2, "indexed_without_body": 2}
        )
        is True
    )
    assert filing_coverage_needs_fetch({"filings_total": 0, "filings_with_body": 0}) is True


def test_maintenance_visits_gapped_holdings_before_the_sample():
    calls: list[str] = []

    def needs_fetch(name: dict) -> bool:
        return name["ticker"] in {"HIK.L", "AAPL"}

    def runner(item: dict, exclude: set[str]) -> dict:
        del exclude
        calls.append(str(item["source"]))
        if item["source"] == "sample":
            return {"targets": 1, "ticker": "SAM.L", "seconds": 2.0, "market": item["market"]}
        return {
            "targets": 1,
            "ticker": item["ticker"],
            "seconds": 3.0,
            "market": item["market"],
        }

    priority = [
        {"ticker": "BARC.L", "market": "ftse350", "source": "holding"},
        {"ticker": "HIK.L", "market": "ftse350", "source": "holding"},
        {"ticker": "AAPL", "market": "sp500", "source": "strategy_open"},
    ]
    state: dict = {}
    first = advance_maintenance(
        state,
        priority=priority,
        needs_fetch=needs_fetch,
        sample_markets=["aex"],
        runner=runner,
    )
    second = advance_maintenance(
        state,
        priority=[],
        needs_fetch=lambda name: False,
        sample_markets=[],
        runner=runner,
    )
    third = advance_maintenance(
        state,
        priority=[],
        needs_fetch=lambda name: False,
        sample_markets=[],
        runner=runner,
    )
    assert first["ticker"] == "HIK.L"
    assert first["source"] == "holding"
    assert second["ticker"] == "AAPL"
    assert second["source"] == "strategy_open"
    assert third["source"] == "sample"
    assert third["ticker"] == "SAM.L"
    assert calls == ["holding", "strategy_open", "sample"]
    assert state["priority_considered"] == 3
    assert state["priority_fresh"] == 1


def test_sprint_stops_at_the_name_ceiling_without_exploring():
    state: dict = {
        "planned": True,
        "plan": {"action": "run", "max_targets": 1, "max_runtime_seconds": 2100},
    }
    calls = {"n": 0}

    def runner(exclude: set[str]) -> dict:
        del exclude
        calls["n"] += 1
        return {"targets": 1, "ticker": f"N{calls['n']}", "seconds": 1, "market": "ftse_smallcap"}

    first = advance_sprint(
        state,
        stream=2,
        ceiling=1,
        runtime_ceiling=2100,
        runner=runner,
        explore_when_empty=True,
    )
    second = advance_sprint(
        state,
        stream=2,
        ceiling=1,
        runtime_ceiling=2100,
        runner=runner,
        explore_when_empty=True,
    )
    assert first["action"] == "ran"
    assert first["targets_ceiling"] == 1
    assert second["action"] == "idle"
    assert second["reason"] == "ceiling"
    assert second["explore"] is False
    assert calls["n"] == 1


def test_sprint_explores_only_when_the_seated_backlog_is_idle():
    def planner_empty() -> dict:
        return {
            "action": "skip",
            "code": "no_gaps",
            "markets": [],
            "max_targets": 24,
            "max_runtime_seconds": 2100.0,
        }

    idle = sprint_slice(
        {},
        library_root=Path("."),
        policy_path=Path("policy.json"),
        stream=2,
        markets=None,
        max_targets=24,
        max_runtime_seconds=2100.0,
        max_bodies=20,
        head_idle=True,
        deadline_epoch=None,
        planner=planner_empty,
        fetch_one=lambda *_args: {"targets": 1, "ticker": "SHOULD_NOT_RUN"},
    )
    assert idle["action"] == "idle"
    assert idle["explore"] is True
    assert idle["targets_ceiling"] == 24
    assert idle["runtime_ceiling_seconds"] == 2100.0

    stream_1 = sprint_slice(
        {},
        library_root=Path("."),
        policy_path=Path("policy.json"),
        stream=1,
        markets=None,
        max_targets=24,
        max_runtime_seconds=2100.0,
        max_bodies=20,
        head_idle=True,
        deadline_epoch=None,
        planner=planner_empty,
    )
    assert stream_1["action"] == "idle"
    assert stream_1["explore"] is True
    assert stream_1["reason"] == "no_gaps"


def test_a_spent_clock_does_not_start_the_catalogue():
    state = {
        "planned": True,
        "plan": {
            "action": "run",
            "max_targets": 24,
            "max_runtime_seconds": 2100.0,
            "markets": ["ftse_smallcap"],
        },
    }
    payload = advance_sprint(
        state,
        stream=2,
        ceiling=24,
        runtime_ceiling=2100.0,
        runner=lambda _exclude: {"targets": 1, "ticker": "LATE"},
        deadline_epoch=1.0,
        explore_when_empty=True,
    )
    assert payload["reason"] == "budget_spent"
    assert payload["explore"] is False


def test_finish_records_the_sample_and_leaves_matrix_off(tmp_path: Path):
    state = {
        "results": [
            {"source": "holding", "market": "ftse350", "ticker": "BARC.L", "seconds": 4},
            {"source": "sample", "market": "aex", "ticker": "ASML.AS", "seconds": 9},
        ],
        "sample": ["aex", "bel20"],
        "errors": [],
    }
    outcome = finish_maintenance_hunt(state, library_root=tmp_path)
    assert outcome["matrix_parallel_enabled"] is False
    assert outcome["last_head"] == "aex"
    capacity = load_maintenance_capacity(tmp_path)
    assert capacity["matrix_parallel"]["enabled"] is False
    cursor = (tmp_path / "maintenance_slot_cursor.json").read_text(encoding="utf-8")
    assert "aex" in cursor


def test_finish_does_not_move_the_cursor_when_only_priority_ran(tmp_path: Path):
    state = {
        "results": [
            {"source": "holding", "market": "ftse350", "ticker": "BARC.L", "seconds": 4},
        ],
        "sample": ["aex"],
        "errors": [],
    }
    outcome = finish_maintenance_hunt(state, library_root=tmp_path)
    assert outcome["cursor_written"] is False
    assert not (tmp_path / "maintenance_slot_cursor.json").exists()
    assert load_maintenance_capacity(tmp_path)["matrix_parallel"]["enabled"] is False
