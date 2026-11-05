"""Token-usage ledger: record, backfill, roll-up, and observe findings.

No SDK network calls. Agents are fakes.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cursor_sdk import CursorAgentError

from value_investor.agent_model_policy import normalize_budget
from value_investor.agent_usage import (
    backfill_pending_costs,
    prompt_and_record,
    read_usage_rows,
    record_agent_usage,
)
from value_investor.agent_usage_report import (
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
    monkeypatch.setattr("value_investor.agent_usage.DEFAULT_LOG_PATH", log_path)


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

    report = backfill_pending_costs(log_path=log_path, now=NOW, resume_agent=resume)
    assert report["read_only"] is True
    assert report["updated_rows"] == 1
    assert report["queried_agents"] == 1
    assert resumed == ["agent-1"]
    assert handle.sent is False
    assert handle.closed is True
    rows = {row["row_id"]: row for row in read_usage_rows(log_path)}
    assert rows["done"]["raw_cost_cents"] == 10.0
    assert rows["wait"]["cost_pending"] is False
    assert rows["wait"]["raw_cost_cents"] == 55.0
    assert rows["wait"]["charged_cents"] == 0.0
    assert rows["wait"]["cost_backfilled_at"]


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

    report = backfill_pending_costs(log_path=log_path, now=NOW, resume_agent=resume)
    assert report["skipped_older_than_days"] == 1
    assert queried == ["agent-fresh"]
    rows = {row["row_id"]: row for row in read_usage_rows(log_path)}
    assert rows["old"]["cost_pending"] is True
    assert rows["fresh"]["cost_pending"] is False


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
    assert len(findings) == 1
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
    assert _findings(rows, threshold=None, now=NOW) == []


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
