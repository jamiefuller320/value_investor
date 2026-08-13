"""Tests for director–worker weekly cap ledger and auto-tighten."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.agent_model_policy import default_policy, load_policy, save_policy
from value_investor.research.director_worker_cap import (
    PHASE_EXPLORATION,
    PHASE_STEADY,
    check_director_worker_cap,
    default_director_worker_policy,
    director_worker_policy,
    maybe_auto_tighten,
    record_director_worker_run,
)


def _write_policy(tmp_path: Path, **dw_overrides) -> Path:
    policy = default_policy()
    policy["director_worker"] = {**default_director_worker_policy(), **dw_overrides}
    path = tmp_path / "policy.json"
    save_policy(policy, path)
    return path


def test_exploration_cap_allows_runs_until_limit(tmp_path: Path):
    policy_path = _write_policy(tmp_path, exploration_weekly_cap=2)
    ledger_path = tmp_path / "ledger.json"
    when = datetime(2026, 8, 13, tzinfo=UTC)

    first = check_director_worker_cap("AAA.L", policy_path=policy_path, ledger_path=ledger_path, when=when)
    assert first.allowed is True
    assert first.weekly_cap == 2
    assert first.phase == PHASE_EXPLORATION

    record_director_worker_run(
        ticker="AAA.L",
        run_id="run-1",
        policy_path=policy_path,
        ledger_path=ledger_path,
        when=when,
    )
    second = check_director_worker_cap("BBB.L", policy_path=policy_path, ledger_path=ledger_path, when=when)
    assert second.allowed is True
    assert second.runs_this_week == 1

    record_director_worker_run(
        ticker="BBB.L",
        run_id="run-2",
        policy_path=policy_path,
        ledger_path=ledger_path,
        when=when,
    )
    blocked = check_director_worker_cap("CCC.L", policy_path=policy_path, ledger_path=ledger_path, when=when)
    assert blocked.allowed is False
    assert blocked.runs_this_week == 2
    assert "cap reached" in blocked.reason.lower()


def test_reescalation_detected_on_repeat_ticker(tmp_path: Path):
    policy_path = _write_policy(tmp_path)
    ledger_path = tmp_path / "ledger.json"
    when = datetime(2026, 8, 13, tzinfo=UTC)

    record_director_worker_run(
        ticker="VTY.L",
        run_id="run-1",
        policy_path=policy_path,
        ledger_path=ledger_path,
        when=when,
    )
    status = check_director_worker_cap("VTY.L", policy_path=policy_path, ledger_path=ledger_path, when=when)
    assert status.is_reescalation is True


def test_auto_tighten_moves_to_steady_after_stable_window(tmp_path: Path):
    policy_path = _write_policy(
        tmp_path,
        auto_tighten_min_weeks=3,
        exploration_weekly_cap=10,
        steady_weekly_cap=5,
    )
    ledger_path = tmp_path / "ledger.json"
    base = datetime(2026, 6, 2, tzinfo=UTC)

    for week_offset in range(3):
        when = base.replace(day=base.day + week_offset * 7)
        info = record_director_worker_run(
            ticker=f"T{week_offset}.L",
            run_id=f"run-{week_offset}",
            policy_path=policy_path,
            ledger_path=ledger_path,
            when=when,
        )
        if week_offset == 2:
            assert info["auto_tighten"]["applied"] is True

    updated = director_worker_policy(load_policy(policy_path))
    assert updated["phase"] == PHASE_STEADY

    status = check_director_worker_cap("NEW.L", policy_path=policy_path, ledger_path=ledger_path, when=base)
    assert status.weekly_cap == 5


def test_auto_tighten_skipped_when_reescalation_rate_high(tmp_path: Path):
    policy_path = _write_policy(
        tmp_path,
        auto_tighten_min_weeks=2,
        auto_tighten_max_reescalation_rate=0.2,
    )
    ledger_path = tmp_path / "ledger.json"
    when = datetime(2026, 8, 13, tzinfo=UTC)

    record_director_worker_run(
        ticker="AAA.L", run_id="run-1", policy_path=policy_path, ledger_path=ledger_path, when=when
    )
    record_director_worker_run(
        ticker="AAA.L", run_id="run-2", policy_path=policy_path, ledger_path=ledger_path, when=when
    )

    tighten = maybe_auto_tighten(policy_path=policy_path, ledger_path=ledger_path)
    assert tighten["applied"] is False
    assert tighten["reason"] == "insufficient_weeks" or tighten["reason"] == "reescalation_rate_high"
