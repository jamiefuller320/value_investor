"""Token-usage ledger: record, backfill, roll-up, and observe findings.

No SDK network calls. Agents are fakes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cursor_sdk import CursorAgentError

from value_investor.agent_model_policy import normalize_budget
from value_investor.agent_usage import (
    backfill_pending_costs,
    load_backfill_map,
    load_ledger_rows,
    prompt_and_record,
    read_usage_rows,
    record_agent_usage,
    reset_process_shard_state,
    shard_path_for_job,
)
from value_investor.agent_usage_report import (
    COMMIT_GAP_TITLE,
    COVERAGE_TITLE,
    MEASURING_TITLE,
    NEAR_TITLE,
    OVER_TITLE,
    build_usage_report,
    iso_week_id,
    plan_cycle_id,
    usage_warning_findings,
)
from value_investor.ops_monitor import OpsFinding, check_agent_token_usage
from value_investor.research import agent as research_agent

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
WEEK = iso_week_id(NOW)
CYCLE = plan_cycle_id(NOW, 8)


def _enable(monkeypatch: pytest.MonkeyPatch, log_path: Path) -> None:
    monkeypatch.setenv("FTSE_AGENT_USAGE_RECORD", "1")

    def _fixed_shard(_job: str, **_kwargs: object) -> Path:
        return log_path

    # Callers that omit log_path write a shard. Point that path at the test file.
    monkeypatch.setattr("value_investor.agent_usage.shard_path_for_job", _fixed_shard)


def _usage(
    *,
    input_tokens: int = 100,
    output_tokens: int = 20,
    cache_read_tokens: int = 5,
    cache_write_tokens: int = 2,
    total_tokens: int = 127,
    reasoning_tokens: int = 3,
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def _cost(raw: float | None, charged: float | None = 0.0) -> SimpleNamespace | None:
    if raw is None:
        return None
    return SimpleNamespace(raw_cost_cents=raw, charged_cents=charged)


def _agent_usage(
    runs: list[SimpleNamespace],
    *,
    cost: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(usage=_usage(), runs=runs, cost=cost)


def _run(
    run_id: str,
    *,
    raw: float | None = 40.0,
    charged: float = 0.0,
    total: int = 127,
) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=run_id,
        usage=_usage(total_tokens=total, input_tokens=total),
        cost=_cost(raw, charged),
    )


class _FakeAgent:
    def __init__(self, payload: SimpleNamespace | Exception, agent_id: str = "agent-1") -> None:
        self.agent_id = agent_id
        self.payload = payload
        self.calls: list[str | None] = []
        self.closed = False
        self.sent = False

    def get_usage(self, run_id: str | None = None) -> SimpleNamespace:
        self.calls.append(run_id)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def send(self, *_args: object, **_kwargs: object) -> None:
        self.sent = True
        raise AssertionError("get_usage backfill must not send")

    def close(self) -> None:
        self.closed = True


def _row(
    *,
    job: str = "research_memo",
    model: str = "composer-2.5",
    stamp: datetime = NOW,
    raw_cents: float | None = 40.0,
    charged_cents: float | None = 0.0,
    pending: bool = False,
    usage_error: str | None = None,
    tokens: int = 100,
    agent_id: str | None = "agent-1",
    row_id: str = "row",
) -> dict:
    return {
        "row_id": row_id,
        "timestamp": stamp.isoformat(),
        "job": job,
        "model": model,
        "agent_id": agent_id,
        "run_id": "run-client",
        "usage_run_id": "usage-1",
        "ticker": "ULVR.L",
        "pool": "weekly_ops",
        "input_tokens": tokens,
        "output_tokens": 10,
        "cache_read_tokens": 1,
        "cache_write_tokens": 1,
        "total_tokens": tokens + 12,
        "reasoning_tokens": 0,
        "raw_cost_cents": raw_cents,
        "charged_cents": charged_cents,
        "cost_pending": pending,
        "usage_error": usage_error,
    }


def test_record_writes_token_and_cost_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "agent_usage_log.jsonl"
    _enable(monkeypatch, log_path)
    payload = _agent_usage([_run("usage-1", raw=80.0, charged=0.0, total=50)])
    agent = _FakeAgent(payload, agent_id="ag-9")
    row = record_agent_usage(
        agent,
        job="research_memo",
        model="composer-2.5",
        run_id="usage-1",
        ticker="ULVR.L",
        pool="weekly_ops",
        extra={"note": "kept", "job": "should-not-overwrite"},
        log_path=log_path,
    )
    assert row is not None
    assert row["job"] == "research_memo"
    assert row["model"] == "composer-2.5"
    assert row["agent_id"] == "ag-9"
    assert row["run_id"] == "usage-1"
    assert row["usage_run_id"] == "usage-1"
    assert row["ticker"] == "ULVR.L"
    assert row["pool"] == "weekly_ops"
    assert row["input_tokens"] == 50
    assert row["total_tokens"] == 50
    assert row["raw_cost_cents"] == 80.0
    assert row["charged_cents"] == 0.0
    assert row["cost_pending"] is False
    assert row["usage_error"] is None
    assert row["note"] == "kept"
    assert row["timestamp"].endswith("+00:00")
    stored = read_usage_rows(log_path)
    assert len(stored) == 1
    assert stored[0]["row_id"] == row["row_id"]
    assert agent.calls == ["usage-1"]


def test_record_pending_when_cost_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "log.jsonl"
    _enable(monkeypatch, log_path)
    run = _run("usage-1", raw=None)
    payload = _agent_usage([run], cost=None)
    row = record_agent_usage(
        _FakeAgent(payload),
        job="gap_fill",
        model="composer-2.5",
        log_path=log_path,
    )
    assert row is not None
    assert row["cost_pending"] is True
    assert row["raw_cost_cents"] is None
    assert row["charged_cents"] is None


def test_record_swallows_get_usage_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "log.jsonl"
    _enable(monkeypatch, log_path)
    row = record_agent_usage(
        _FakeAgent(RuntimeError("usage down")),
        job="engineering",
        model="composer-2.5",
        log_path=log_path,
    )
    assert row is not None
    assert "usage down" in row["usage_error"]
    assert row["cost_pending"] is True
    assert read_usage_rows(log_path)[0]["usage_error"]


def test_record_swallows_write_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    _enable(monkeypatch, blocker / "log.jsonl")
    row = record_agent_usage(
        _FakeAgent(_agent_usage([_run("usage-1")])),
        job="engineering",
        model="composer-2.5",
        log_path=blocker / "log.jsonl",
    )
    assert row is None


def test_record_noop_without_get_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "log.jsonl"
    _enable(monkeypatch, log_path)
    assert record_agent_usage(object(), job="engineering", model=None, log_path=log_path) is None
    assert not log_path.exists()


def test_record_noop_under_pytest_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FTSE_AGENT_USAGE_RECORD", raising=False)
    log_path = tmp_path / "log.jsonl"
    row = record_agent_usage(
        _FakeAgent(_agent_usage([_run("usage-1")])),
        job="engineering",
        model="composer-2.5",
        log_path=log_path,
    )
    assert row is None
    assert not log_path.exists()


def test_client_run_id_is_not_sent_to_get_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "log.jsonl"
    _enable(monkeypatch, log_path)
    first = _run("usage-a", raw=10.0, total=10)
    last = _run("usage-b", raw=20.0, total=30)
    agent = _FakeAgent(_agent_usage([first, last]))
    row = record_agent_usage(
        agent,
        job="research_agent",
        model="composer-2.5",
        run_id="run-client-minted",
        log_path=log_path,
    )
    assert agent.calls == [None]
    assert row is not None
    assert row["usage_run_id"] == "usage-b"
    assert row["total_tokens"] == 30
    assert row["raw_cost_cents"] == 20.0


def test_concurrent_appends_stay_one_json_object_per_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "log.jsonl"
    _enable(monkeypatch, log_path)
    payload = _agent_usage([_run("usage-1", raw=1.0)])
    barrier = threading.Barrier(12)
    errors: list[BaseException] = []

    def _one() -> None:
        try:
            barrier.wait(timeout=5)
            record_agent_usage(
                _FakeAgent(payload),
                job="horizon_scan",
                model="composer-2.5",
                log_path=log_path,
            )
        except BaseException as exc:  # pragma: no cover - fail the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_one) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 12
    assert len({json.loads(line)["row_id"] for line in lines}) == 12


def _write_log(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_backfill_updates_only_pending_rows_and_never_sends(tmp_path: Path) -> None:
    log_path = tmp_path / "log.jsonl"
    done = _row(row_id="done", pending=False, raw_cents=10.0)
    waiting = _row(row_id="wait", pending=True, raw_cents=None, charged_cents=None)
    _write_log(log_path, [done, waiting])
    handle = _FakeAgent(_agent_usage([_run("usage-1", raw=55.0, charged=0.0)]))
    resumed: list[str] = []

    def resume(agent_id: str) -> _FakeAgent:
        resumed.append(agent_id)
        return handle

    before = log_path.read_bytes()
    report = backfill_pending_costs(log_path=log_path, now=NOW, resume_agent=resume)
    assert report["read_only"] is True
    assert report["shards_unchanged"] is True
    assert report["updated_rows"] == 1
    assert report["queried_agents"] == 1
    assert resumed == ["agent-1"]
    assert handle.sent is False
    assert handle.closed is True
    assert log_path.read_bytes() == before
    shards = {row["row_id"]: row for row in read_usage_rows(log_path)}
    assert shards["wait"]["cost_pending"] is True
    filled = load_backfill_map(log_path.parent / "agent_usage_cost_backfill.json")
    assert filled["wait"]["raw_cost_cents"] == 55.0
    assert filled["wait"]["charged_cents"] == 0.0
    assert filled["wait"]["filled_at"]
    assert "done" not in filled
    merged = {row["row_id"]: row for row in load_ledger_rows(log_path)}
    assert merged["done"]["raw_cost_cents"] == 10.0
    assert merged["wait"]["cost_pending"] is False
    assert merged["wait"]["raw_cost_cents"] == 55.0


def test_backfill_skips_rows_older_than_seven_days(tmp_path: Path) -> None:
    log_path = tmp_path / "log.jsonl"
    old = _row(
        row_id="old",
        pending=True,
        raw_cents=None,
        charged_cents=None,
        stamp=NOW - timedelta(days=8),
    )
    fresh = _row(
        row_id="fresh",
        pending=True,
        raw_cents=None,
        charged_cents=None,
        stamp=NOW - timedelta(days=1),
        agent_id="agent-fresh",
    )
    _write_log(log_path, [old, fresh])
    queried: list[str] = []

    def resume(agent_id: str) -> _FakeAgent:
        queried.append(agent_id)
        return _FakeAgent(_agent_usage([_run("usage-1", raw=12.0)]))

    before = log_path.read_bytes()
    report = backfill_pending_costs(log_path=log_path, now=NOW, resume_agent=resume)
    assert report["skipped_older_than_days"] == 1
    assert queried == ["agent-fresh"]
    assert log_path.read_bytes() == before
    shards = {row["row_id"]: row for row in read_usage_rows(log_path)}
    assert shards["old"]["cost_pending"] is True
    assert shards["fresh"]["cost_pending"] is True
    filled = load_backfill_map(log_path.parent / "agent_usage_cost_backfill.json")
    assert "old" not in filled
    assert filled["fresh"]["raw_cost_cents"] == 12.0


def test_backfill_disabled_under_pytest_does_not_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FTSE_AGENT_USAGE_BACKFILL", raising=False)
    log_path = tmp_path / "log.jsonl"
    _write_log(
        log_path,
        [_row(row_id="wait", pending=True, raw_cents=None, charged_cents=None)],
    )

    def boom(_agent_id: str) -> None:
        raise AssertionError("resume must not run")

    monkeypatch.setattr("cursor_sdk.Agent.resume", boom)
    report = backfill_pending_costs(log_path=log_path, now=NOW)
    assert report["skipped"] is True
    assert report["still_pending"] == 1
    assert read_usage_rows(log_path)[0]["cost_pending"] is True


def test_backfill_leaves_pending_when_resume_fails(tmp_path: Path) -> None:
    log_path = tmp_path / "log.jsonl"
    _write_log(
        log_path,
        [_row(row_id="wait", pending=True, raw_cents=None, charged_cents=None)],
    )

    def resume(_agent_id: str) -> None:
        raise RuntimeError("resume refused")

    report = backfill_pending_costs(log_path=log_path, now=NOW, resume_agent=resume)
    assert report["updated_rows"] == 0
    assert report["still_pending"] == 1
    assert report["errors"]
    assert read_usage_rows(log_path)[0]["cost_pending"] is True


def _policy(*, threshold: float | None, week_id: str = WEEK) -> dict:
    return {
        "budget": {
            "plan_refresh_day_of_month": 8,
            "token_usage_weekly_warning_raw_usd": threshold,
            "week_id": week_id,
            "cycle_id": CYCLE,
            "estimated_spend_usd_this_week": 42.0,
            "estimated_spend_usd_this_cycle": 63.2,
        },
        "ladder": {"estimated_memo_usd": 0.4},
    }


def test_rollup_week_cycle_memo_and_ledger() -> None:
    other = NOW - timedelta(days=14)
    rows = [
        _row(row_id="m1", raw_cents=40.0, job="research_memo", model="composer-2.5"),
        _row(row_id="m2", raw_cents=80.0, job="research_memo", model="composer-2.5"),
        _row(row_id="m3", raw_cents=120.0, job="research_memo", model="gpt-5"),
        _row(
            row_id="pending-memo",
            job="research_memo",
            pending=True,
            raw_cents=None,
            charged_cents=None,
        ),
        _row(row_id="gap", job="gap_fill", raw_cents=200.0, model="composer-2.5", tokens=10),
        _row(row_id="old", stamp=other, raw_cents=500.0, job="engineering", model="composer-2.5"),
    ]
    report = build_usage_report(rows, policy=_policy(threshold=None), now=NOW)
    weeks = {bucket["id"]: bucket for bucket in report["weeks"]}
    cycles = {bucket["id"]: bucket for bucket in report["cycles"]}
    assert report["current_week_id"] == WEEK
    assert report["current_cycle_id"] == CYCLE
    current = weeks[WEEK]
    assert current["runs"] == 5
    assert current["by_job"]["research_memo"]["runs"] == 4
    assert current["by_job"]["gap_fill"]["runs"] == 1
    assert current["by_model"]["composer-2.5"]["runs"] == 4
    assert current["by_model"]["gpt-5"]["runs"] == 1
    # 0.40 + 0.80 + 1.20 + 2.00; the pending memo is excluded.
    assert current["raw_cost_usd"] == 4.4
    memo = current["research_memo"]
    assert memo["runs"] == 4
    assert memo["runs_with_raw_cost"] == 3
    assert memo["raw_cost_usd_median"] == 0.8
    assert memo["raw_cost_usd_p90"] == 1.12
    assert memo["estimated_memo_usd"] == 0.4
    assert current["estimated_ledger_usd_this_week"] == 42.0
    assert current["estimated_ledger_week_matches"] is True
    assert weeks[iso_week_id(other)]["estimated_ledger_usd_this_week"] is None
    assert cycles[CYCLE]["estimated_ledger_usd_this_cycle"] == 63.2
    assert cycles[CYCLE]["research_memo"]["raw_cost_usd_median"] == 0.8
    assert cycles[plan_cycle_id(other, 8)]["id"].endswith("-d8")


def _findings(rows: list[dict], *, threshold: float | None, now: datetime = NOW) -> list[dict]:
    report = build_usage_report(rows, policy=_policy(threshold=threshold), now=now)
    return usage_warning_findings(report, now=now)


def test_findings_measuring_mode_is_info() -> None:
    findings = _findings([_row(raw_cents=40.0)], threshold=None)
    measuring = [item for item in findings if item["title"] == MEASURING_TITLE]
    assert len(measuring) == 1
    findings = measuring
    assert findings[0]["title"] == MEASURING_TITLE
    assert findings[0]["severity"] == "info"
    assert findings[0]["auto_fixable"] is False
    summary = findings[0]["summary"]
    assert "Measuring mode" in summary
    assert "$0.40" in summary
    assert "research_memo" in summary
    assert "$42.00" in summary


def test_findings_warn_at_80_and_100_percent() -> None:
    near = _findings([_row(raw_cents=800.0)], threshold=10.0)
    assert near[0]["title"] == NEAR_TITLE
    assert near[0]["severity"] == "warn"
    assert near[0]["auto_fixable"] is False
    over = _findings([_row(raw_cents=1000.0)], threshold=10.0)
    assert over[0]["title"] == OVER_TITLE
    assert over[0]["severity"] == "warn"
    under = _findings([_row(raw_cents=100.0)], threshold=10.0)
    assert under[0]["title"] == MEASURING_TITLE
    assert under[0]["severity"] == "info"
    assert "under 80%" in under[0]["summary"]


def test_findings_coverage_gap_above_10_percent_only() -> None:
    exact = [_row(row_id=f"ok-{i}", raw_cents=10.0) for i in range(9)]
    exact.append(_row(row_id="err", usage_error="boom", pending=True, raw_cents=None))
    assert all(item["title"] != COVERAGE_TITLE for item in _findings(exact, threshold=None))

    both = [_row(row_id=f"ok-{i}", raw_cents=10.0) for i in range(9)]
    both.append(
        _row(
            row_id="both",
            usage_error="boom",
            pending=True,
            raw_cents=None,
            charged_cents=None,
            stamp=NOW - timedelta(hours=49),
        )
    )
    assert all(item["title"] != COVERAGE_TITLE for item in _findings(both, threshold=None))

    over = [_row(row_id=f"ok-{i}", raw_cents=10.0) for i in range(8)]
    over.append(_row(row_id="e1", usage_error="a", pending=True, raw_cents=None))
    over.append(
        _row(
            row_id="stale",
            pending=True,
            raw_cents=None,
            charged_cents=None,
            stamp=NOW - timedelta(hours=49),
        )
    )
    gap = [item for item in _findings(over, threshold=None) if item["title"] == COVERAGE_TITLE]
    assert len(gap) == 1
    assert gap[0]["severity"] == "info"
    assert gap[0]["auto_fixable"] is False

    fresh_pending = [_row(row_id=f"ok-{i}", raw_cents=10.0) for i in range(8)]
    fresh_pending.append(
        _row(
            row_id="fresh-pending",
            pending=True,
            raw_cents=None,
            charged_cents=None,
            stamp=NOW - timedelta(hours=47),
        )
    )
    assert all(item["title"] != COVERAGE_TITLE for item in _findings(fresh_pending, threshold=None))


def test_findings_empty_when_current_week_has_no_runs() -> None:
    rows = [_row(stamp=NOW - timedelta(days=21), raw_cents=40.0)]
    findings = _findings(rows, threshold=None, now=NOW)
    assert [item["title"] for item in findings] == [COMMIT_GAP_TITLE]
    assert "engineering-hunter-fix.yml" in findings[0]["summary"]
    assert "hunter_verify" in findings[0]["summary"]
    assert findings[0]["auto_fixable"] is False


def test_check_agent_token_usage_maps_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "value_investor.agent_usage_report.collect_token_usage_report",
        lambda **_kwargs: (
            {},
            [
                {
                    "severity": "info",
                    "category": "budget",
                    "title": MEASURING_TITLE,
                    "summary": "week",
                    "auto_fixable": True,
                }
            ],
            None,
        ),
    )
    findings = check_agent_token_usage()
    assert len(findings) == 1
    assert isinstance(findings[0], OpsFinding)
    assert findings[0].title == MEASURING_TITLE
    assert findings[0].auto_fixable is False


def test_check_agent_token_usage_swallows_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr("value_investor.agent_usage_report.collect_token_usage_report", boom)
    findings = check_agent_token_usage()
    assert findings[0].severity == "warn"
    assert findings[0].title == "Agent token usage check failed"
    assert findings[0].auto_fixable is False


def test_prompt_and_record_returns_result_and_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "log.jsonl"
    _enable(monkeypatch, log_path)
    payload = _agent_usage([_run("usage-1", raw=15.0)])

    class AgentCls(_FakeAgent):
        def __init__(self) -> None:
            super().__init__(payload, agent_id="prompt-agent")

        @classmethod
        def create(cls, _options: object) -> AgentCls:
            return cls()

        def send(self, message: str) -> AgentCls:
            self.message = message
            return self

        def wait(self) -> SimpleNamespace:
            return SimpleNamespace(id="run-abc", result="memo text")

    result = prompt_and_record(
        "hello",
        options=None,
        job="engineering",
        model="composer-2.5",
        pool="ad_hoc",
        agent_cls=AgentCls,
    )
    assert result.result == "memo text"
    stored = read_usage_rows(log_path)
    assert stored[0]["job"] == "engineering"
    assert stored[0]["pool"] == "ad_hoc"
    assert stored[0]["run_id"] == "run-abc"
    assert stored[0]["raw_cost_cents"] == 15.0


def test_prompt_and_record_records_when_send_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "log.jsonl"
    _enable(monkeypatch, log_path)

    class AgentCls(_FakeAgent):
        def __init__(self) -> None:
            super().__init__(RuntimeError("no usage"), agent_id="fail-agent")

        @classmethod
        def create(cls, _options: object) -> AgentCls:
            return cls()

        def send(self, _message: str) -> None:
            raise CursorAgentError("model down")

    with pytest.raises(CursorAgentError, match="model down"):
        prompt_and_record("hello", options=None, job="hunter_fix", model="m", agent_cls=AgentCls)
    stored = read_usage_rows(log_path)
    assert stored[0]["job"] == "hunter_fix"
    assert "no usage" in stored[0]["usage_error"]


def test_run_agent_prompt_records_without_changing_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "log.jsonl"
    _enable(monkeypatch, log_path)
    payload = _agent_usage([_run("usage-z", raw=40.0, total=11)])

    class AgentCls:
        agent_id = "research-agent"

        def __init__(self) -> None:
            self.closed = False
            self.usage_run_id: str | None = "unset"

        def send(self, prompt: str) -> AgentCls:
            self.prompt = prompt
            return self

        def wait(self) -> SimpleNamespace:
            return SimpleNamespace(id="run-local", result="  verdict text  ")

        def get_usage(self, run_id: str | None = None) -> SimpleNamespace:
            self.usage_run_id = run_id
            return payload

        def close(self) -> None:
            self.closed = True

    created: list[AgentCls] = []

    def create(_options: object) -> AgentCls:
        agent = AgentCls()
        created.append(agent)
        return agent

    monkeypatch.setattr(research_agent.Agent, "create", create)
    text, agent_id = research_agent._run_agent_prompt(
        prompt="base prompt",
        api_key="test-key",
        model="composer-2.5",
        cwd=str(tmp_path),
        job="research_memo",
        ticker="ULVR.L",
        pool="weekly_ops",
    )
    assert text == "verdict text"
    assert agent_id == "research-agent"
    assert created[0].closed is True
    assert created[0].usage_run_id is None
    stored = read_usage_rows(log_path)
    assert stored[0]["job"] == "research_memo"
    assert stored[0]["ticker"] == "ULVR.L"
    assert stored[0]["pool"] == "weekly_ops"
    assert stored[0]["run_id"] == "run-local"


def test_run_agent_prompt_failure_still_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "log.jsonl"
    _enable(monkeypatch, log_path)

    class AgentCls:
        agent_id = "research-agent"

        def __init__(self) -> None:
            self.closed = False

        def send(self, _prompt: str) -> None:
            raise CursorAgentError("send failed")

        def get_usage(self, _run_id: str | None = None) -> None:
            raise RuntimeError("usage down")

        def close(self) -> None:
            self.closed = True

    holder: dict[str, AgentCls] = {}

    def create(_options: object) -> AgentCls:
        agent = AgentCls()
        holder["agent"] = agent
        return agent

    monkeypatch.setattr(research_agent.Agent, "create", create)
    with pytest.raises(RuntimeError, match="Agent run failed"):
        research_agent._run_agent_prompt(
            prompt="base",
            api_key="test-key",
            model="composer-2.5",
            cwd=str(tmp_path),
        )
    assert holder["agent"].closed is True
    stored = read_usage_rows(log_path)
    assert stored[0]["job"] == "research_agent"
    assert "usage down" in stored[0]["usage_error"]


def test_normalize_budget_token_warning_field() -> None:
    assert normalize_budget({})["token_usage_weekly_warning_raw_usd"] is None
    assert (
        normalize_budget({"token_usage_weekly_warning_raw_usd": ""})[
            "token_usage_weekly_warning_raw_usd"
        ]
        is None
    )
    assert (
        normalize_budget({"token_usage_weekly_warning_raw_usd": "12.5"})[
            "token_usage_weekly_warning_raw_usd"
        ]
        == 12.5
    )
    assert (
        normalize_budget({"token_usage_weekly_warning_raw_usd": -3})[
            "token_usage_weekly_warning_raw_usd"
        ]
        == 0.0
    )


_REPO = Path(__file__).resolve().parents[1]


def test_two_processes_write_separate_shards(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(
        "\n".join(
            [
                "import os, sys",
                "from pathlib import Path",
                "from types import SimpleNamespace",
                "os.environ['FTSE_AGENT_USAGE_RECORD'] = '1'",
                "from value_investor import agent_usage as ledger",
                "ledger.DEFAULT_SHARD_DIR = Path(sys.argv[1])",
                "ledger.reset_process_shard_state()",
                "class Agent:",
                "    agent_id = 'proc'",
                "    def get_usage(self, run_id=None):",
                "        usage = SimpleNamespace(",
                "            input_tokens=1, output_tokens=1, cache_read_tokens=0,",
                "            cache_write_tokens=0, total_tokens=2, reasoning_tokens=0,",
                "        )",
                "        return SimpleNamespace(runs=[], usage=usage, cost=None)",
                "ledger.record_agent_usage(Agent(), job=sys.argv[2], model='m')",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO / "src")
    env["FTSE_AGENT_USAGE_RECORD"] = "1"
    env.pop("GITHUB_RUN_ID", None)
    shard_dir = tmp_path / "shards"
    for _ in range(2):
        subprocess.run(
            [sys.executable, str(worker), str(shard_dir), "research_memo"],
            check=True,
            env=env,
            cwd=tmp_path,
        )
    files = sorted(shard_dir.rglob("*.jsonl"))
    assert len(files) == 2
    assert files[0] != files[1]
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.parent.name) for path in files)
    assert all("research_memo-" in path.name for path in files)
    assert files[0].read_text(encoding="utf-8").strip()
    assert files[1].read_text(encoding="utf-8").strip()


def test_github_run_id_is_in_the_shard_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FTSE_AGENT_USAGE_RECORD", "1")
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    reset_process_shard_state()
    try:
        path = shard_path_for_job("research_memo", now=NOW, shard_dir=tmp_path)
        assert path.parent.name == "2026-11-05"
        assert path.name.startswith(f"research_memo-4242-3-{os.getpid()}-")
        assert path.name.endswith(".jsonl")
        again = shard_path_for_job("research_memo", shard_dir=tmp_path)
        assert again == path
        other = shard_path_for_job("gap_fill", now=NOW, shard_dir=tmp_path)
        assert other != path
        assert other.name.startswith(f"gap_fill-4242-3-{os.getpid()}-")
    finally:
        reset_process_shard_state()


def test_report_merges_shards_backfill_and_dedupes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = tmp_path / "agent_usage" / "2026-11-05"
    day.mkdir(parents=True)
    pending = _row(row_id="same", pending=True, raw_cents=None, charged_cents=None)
    _write_log(day / "a-one.jsonl", [pending])
    _write_log(day / "b-two.jsonl", [pending])
    _write_log(
        day / "c-three.jsonl",
        [_row(row_id="other", raw_cents=10.0, job="engineering")],
    )
    legacy = tmp_path / "agent_usage_log.jsonl"
    _write_log(legacy, [_row(row_id="legacy", raw_cents=5.0, job="horizon_scan")])
    backfill = tmp_path / "agent_usage_cost_backfill.json"
    backfill.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": NOW.isoformat(),
                "by_row_id": {
                    "same": {
                        "raw_cost_cents": 25,
                        "charged_cents": 0,
                        "filled_at": NOW.isoformat(),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("value_investor.agent_usage.DEFAULT_LEGACY_LOG_PATH", legacy)
    monkeypatch.setattr("value_investor.agent_usage.DEFAULT_BACKFILL_PATH", backfill)
    before = {path: path.read_bytes() for path in day.glob("*.jsonl")}
    report = build_usage_report(log_path=day.parent, policy=_policy(threshold=None), now=NOW)
    assert {path: path.read_bytes() for path in day.glob("*.jsonl")} == before
    week = next(row for row in report["weeks"] if row["id"] == WEEK)
    assert week["runs"] == 3
    assert week["raw_cost_usd"] == 0.4
    loaded = {row["row_id"]: row for row in load_ledger_rows(day.parent)}
    assert set(loaded) == {"same", "other", "legacy"}
    assert loaded["same"]["raw_cost_cents"] == 25
    assert loaded["same"]["cost_pending"] is False
    assert read_usage_rows(day / "a-one.jsonl")[0]["cost_pending"] is True


def test_backfill_never_edits_shards(tmp_path: Path) -> None:
    shard_dir = tmp_path / "agent_usage"
    shard = shard_dir / "2026-11-05" / "research_memo-local.jsonl"
    shard.parent.mkdir(parents=True)
    _write_log(
        shard,
        [_row(row_id="wait", pending=True, raw_cents=None, charged_cents=None)],
    )
    before = shard.read_bytes()
    backfill = tmp_path / "agent_usage_cost_backfill.json"

    def resume(_agent_id: str) -> _FakeAgent:
        return _FakeAgent(_agent_usage([_run("usage-1", raw=9.0)]))

    report = backfill_pending_costs(
        shard_dir=shard_dir,
        backfill_path=backfill,
        now=NOW,
        resume_agent=resume,
    )
    assert report["updated_rows"] == 1
    assert report["shards_unchanged"] is True
    assert shard.read_bytes() == before
    assert read_usage_rows(shard)[0]["cost_pending"] is True
    stored = load_backfill_map(backfill)
    assert stored["wait"]["raw_cost_cents"] == 9.0
    assert not (shard_dir / "agent_usage_cost_backfill.json").exists()


def test_overlay_keeps_both_shards(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

    git("init", "-b", "main")
    git("config", "user.email", "usage@example.com")
    git("config", "user.name", "usage")
    day = repo / "docs/data/agent_usage/2026-11-05"
    day.mkdir(parents=True)
    (day / "job-aaaa.jsonl").write_text('{"row_id":"a"}\n', encoding="utf-8")
    git("add", "docs/data/agent_usage")
    git("commit", "-m", "shard A")
    (day / "job-bbbb.jsonl").write_text('{"row_id":"b"}\n', encoding="utf-8")
    snapshot = tmp_path / "snapshot"
    shutil.copytree(repo / "docs/data/agent_usage", snapshot)
    (day / "job-bbbb.jsonl").unlink()
    (day / "job-cccc.jsonl").write_text('{"row_id":"c"}\n', encoding="utf-8")
    git("add", "docs/data/agent_usage")
    git("commit", "-m", "shard C")
    git("reset", "--hard", "HEAD")
    for src in snapshot.rglob("*.jsonl"):
        dest = repo / "docs/data/agent_usage" / src.relative_to(snapshot)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
    names = sorted(path.name for path in day.glob("*.jsonl"))
    assert names == ["job-aaaa.jsonl", "job-bbbb.jsonl", "job-cccc.jsonl"]


def test_commit_lists_use_shard_dir_not_the_old_log() -> None:
    commit_paths = [
        _REPO / "scripts/gha_commit_ops_monitor.sh",
        _REPO / "scripts/gha_commit_engineering_spend.sh",
        _REPO / "scripts/push_weekday_rememo_artifacts.sh",
        _REPO / "scripts/push_library_ingest_artifacts.sh",
        _REPO / ".github/workflows/horizon-scan.yml",
        _REPO / ".github/workflows/learning-director-review.yml",
        _REPO / ".github/workflows/analysis-review.yml",
        _REPO / ".github/workflows/paper-learning-review.yml",
        _REPO / ".github/workflows/memo-backfill.yml",
        _REPO / ".github/workflows/library-grow.yml",
        _REPO / ".github/workflows/post-sale-review-ack.yml",
        _REPO / ".github/workflows/email-report.yml",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in commit_paths)
    assert "agent_usage_log.jsonl" not in text
    assert "merge-snapshot" not in text
    for path in commit_paths[:4]:
        assert "docs/data/agent_usage" in path.read_text(encoding="utf-8")
    paper = (_REPO / ".github/workflows/paper-auto.yml").read_text(encoding="utf-8")
    assert "file_pattern: docs/data/**" in paper
    email = (_REPO / ".github/workflows/email-report.yml").read_text(encoding="utf-8")
    assert "docs/data/agent_usage_cost_backfill.json" in email
    assert "docs/data/agent_usage_weekly.json" in email


def test_imports_and_appends_without_fcntl(tmp_path: Path) -> None:
    """Windows has no fcntl; the owner runs ftse-historical-replay there."""
    script = (
        "import sys\n"
        "sys.modules['fcntl'] = None\n"
        "from pathlib import Path\n"
        "import value_investor.agent_usage as au\n"
        "assert au.fcntl is None\n"
        f"log = Path({str(tmp_path / 'usage.jsonl')!r})\n"
        "with au._exclusive_lock(log):\n"
        "    au._append_line_unlocked(log, '{}')\n"
        "assert log.read_text() == '{}\\n' or log.read_text().startswith('{}')\n"
        "import value_investor.historical_screen_replay\n"
        "import value_investor.strategy_book_replay_cli\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        check=False,
    )
    assert result.returncode == 0, result.stderr
