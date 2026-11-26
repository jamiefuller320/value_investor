"""L703: shadow memos score block/pass against the 63-session outcome."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from value_investor.llm_agree_veto_shadow import authorize_live_llm_influence
from value_investor.ops_monitor import (
    check_strategy_book_memo_model_shadow,
    collect_ops_findings,
)
from value_investor.strategy_book_memo_model_shadow import (
    CHALLENGER_MODEL,
    INCUMBENT_MODEL,
    LIVE_MODEL,
    STORE_NAME,
    TITLE_FAIL_CLOSED,
    TITLE_MISSING,
    TITLE_REFRESHED,
    collect_signals,
    entry_effect,
    evidence_ok,
    findings_from_store,
    outcome_hit,
    request_shadow_memos,
    run_shadow,
    score_model,
    score_signal,
)

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / ".github" / "workflows" / "strategy-book-forward.yml"
EMAIL = ROOT / ".github" / "workflows" / "email-report.yml"
MODULE = ROOT / "src" / "value_investor" / "strategy_book_memo_model_shadow.py"

FILL = date(2026, 11, 23)
SIGNAL = date(2026, 11, 20)
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def _memo(**overrides: object) -> dict:
    row = {
        "action": "requested",
        "market": "ftse350",
        "ticker": "AAA.L",
        "session": SIGNAL.isoformat(),
        "model": INCUMBENT_MODEL,
        "verdict": "pass",
        "rationale": "Net debt rose in the cited filing.",
        "evidence": [
            {
                "source": "filings/bodies/annual.pdf",
                "kind": "memo_quote",
                "detail": "quote_found",
                "quote_found": True,
            }
        ],
        "finished_at": "2026-11-21T12:00:00+00:00",
    }
    row.update(overrides)
    return row


def _series(last: float) -> tuple[list[date], list[float], None, None]:
    days = [FILL + timedelta(days=index) for index in range(80)]
    closes = [100.0] * 80
    closes[63] = last
    return days, closes, None, None


def _signal() -> dict:
    return {
        "market": "ftse350",
        "ticker": "AAA.L",
        "signal_session": SIGNAL.isoformat(),
        "fill_session": FILL.isoformat(),
        "exit_session": None,
        "fair_cost_return": None,
        "status": "open",
        "source": "primary_episode",
    }


def _decision(outcome: str = "inconclusive_keep") -> dict:
    return {
        "outcome": outcome,
        "judge_trusted": False,
        "governing": "owner_sample",
        "status": "recorded",
        "live_model": LIVE_MODEL,
        "live_model_changed": False,
        "switch_applied": False,
        "composer_stays": True,
    }


def test_entry_effect_uses_the_book_block() -> None:
    assert entry_effect("pass") == "block"
    assert entry_effect("accumulate") == "pass"
    assert entry_effect("neutral") == "pass"
    assert entry_effect(None) is None
    assert outcome_hit("block", -0.04) is True
    assert outcome_hit("block", 0.02) is False
    assert outcome_hit("pass", 0.0) is True
    assert outcome_hit("pass", -0.01) is False
    assert outcome_hit("block", None) is None


def test_missing_or_stale_evidence_has_no_score() -> None:
    cutoff = datetime(2026, 11, 23, 16, 30, tzinfo=UTC)
    good = _memo()
    assert evidence_ok(good)
    scored = score_model(good, cutoff=cutoff, outcome=-0.05, decision_recorded=True)
    assert scored["effect"] == "block"
    assert scored["hit"] is True
    assert scored["live_influence_authorized"] is False
    assert scored["feeds_strategy_book"] is False

    missing = score_model(
        _memo(evidence=[]),
        cutoff=cutoff,
        outcome=-0.05,
        decision_recorded=True,
    )
    assert missing["hit"] is None
    assert missing["effect"] is None
    assert missing["score_status"] == "missing_evidence"

    late = score_model(
        _memo(finished_at="2026-11-23T18:00:00+00:00"),
        cutoff=cutoff,
        outcome=-0.05,
        decision_recorded=True,
    )
    assert late["score_status"] == "memo_after_fill_close"
    assert late["hit"] is None

    stale = score_model(
        _memo(finished_at="2026-10-01T12:00:00+00:00"),
        cutoff=cutoff,
        outcome=-0.05,
        decision_recorded=True,
    )
    assert stale["score_status"] == "stale_memo"
    assert stale["hit"] is None

    waiting = score_model(good, cutoff=cutoff, outcome=None, decision_recorded=True)
    assert waiting["effect"] == "block"
    assert waiting["hit"] is None
    assert waiting["score_status"] == "outcome_not_yet"

    closed = score_model(good, cutoff=cutoff, outcome=-0.05, decision_recorded=False)
    assert closed["score_status"] == "decision_evidence_missing"
    assert closed["hit"] is None
    assert closed["effect"] is None


def test_score_uses_the_63_session_outcome_and_early_marks() -> None:
    memo = _memo(verdict="accumulate", model=INCUMBENT_MODEL)
    index = {("ftse350", "AAA.L", SIGNAL.isoformat(), INCUMBENT_MODEL): memo}
    row = score_signal(_signal(), index, _series(120.0), decision_recorded=True)
    assert row["outcome_63_basis"] == "mark_at_s63"
    assert row["outcome_63"] > 0
    assert row["early_indicator"]["s10_available"] is True
    assert row["early_indicator"]["source"].endswith("early_marks_for_series")
    assert row["models"][INCUMBENT_MODEL]["effect"] == "pass"
    assert row["models"][INCUMBENT_MODEL]["hit"] is True
    assert row["models"][CHALLENGER_MODEL]["score_status"] == "no_memo"
    assert row["feeds_strategy_book"] is False
    card = {
        "influences_live": False,
        "observe_only": True,
        "reasons": ["cited"],
        "evidence": [{"source": "filings/bodies/annual.pdf"}],
    }
    assert authorize_live_llm_influence(card) is False


def test_live_model_stays_on_inconclusive_keep_and_on_switch() -> None:
    summary = run_shadow(
        repo_root=Path("/tmp/l703-does-not-write"),
        now=NOW,
        apply=False,
        signals=[_signal()],
        series_for=lambda _market, _ticker: _series(90.0),
        memo_rows=[_memo()],
        decision=_decision("inconclusive_keep"),
    )
    assert summary["live_model"] == "composer-2.5"
    assert summary["live_model_changed"] is False
    assert summary["feeds_strategy_book"] is False
    assert summary["decision_outcome"] == "inconclusive_keep"
    assert summary["by_model"][INCUMBENT_MODEL]["hits"] == 1
    assert summary["by_model"][INCUMBENT_MODEL]["hit_rate"] is None

    switched = run_shadow(
        repo_root=Path("/tmp/l703-does-not-write"),
        now=NOW,
        apply=False,
        signals=[_signal()],
        series_for=lambda _market, _ticker: _series(90.0),
        memo_rows=[_memo()],
        decision=_decision("switch"),
    )
    assert switched["live_model"] == "composer-2.5"
    assert switched["live_model_changed"] is False
    assert switched["decision_outcome"] == "switch"


def test_collect_signals_prefers_the_book_episode() -> None:
    rows = collect_signals(
        [
            {
                "column": "primary",
                "market": "ftse350",
                "ticker": "AAA.L",
                "signal_session": SIGNAL.isoformat(),
                "fill_session": FILL.isoformat(),
                "status": "open",
            }
        ],
        [
            {
                "kind": "signal_day",
                "action": "requested",
                "market": "ftse350",
                "ticker": "AAA.L",
                "session": SIGNAL.isoformat(),
            },
            {
                "kind": "signal_day",
                "action": "requested",
                "market": "ftse350",
                "ticker": "BBB.L",
                "session": SIGNAL.isoformat(),
            },
        ],
        [
            {
                "market": "ftse350",
                "ticker": "CCC.L",
                "session": SIGNAL.isoformat(),
                "outcome": "pending_fill",
            }
        ],
    )
    by_ticker = {row["ticker"]: row for row in rows}
    assert by_ticker["AAA.L"]["source"] == "primary_episode"
    assert by_ticker["AAA.L"]["fill_session"] == FILL.isoformat()
    assert by_ticker["BBB.L"]["source"] == "memo_log"
    assert by_ticker["CCC.L"]["source"] == "forward_status"


def test_request_writes_shadow_memos_and_rejects_a_live_research_path(tmp_path: Path) -> None:
    calls: list[str] = []

    def runner(**kwargs: object) -> dict:
        model = str(kwargs["model"])
        calls.append(model)
        if model == CHALLENGER_MODEL:
            return {"written_paths": ["docs/data/research/AAA.L/research.json"], "verdict": "pass"}
        return {
            "verdict": "accumulate",
            "rationale": "Quote checked.",
            "evidence": [{"source": "filings/bodies/annual.pdf", "quote_found": True}],
            "finished_at": "2026-11-22T12:00:00+00:00",
            "written_paths": [],
        }

    moment = datetime(2026, 11, 22, 18, 0, tzinfo=UTC)
    result = request_shadow_memos(
        [_signal()],
        [],
        repo_root=tmp_path,
        now=moment,
        apply=True,
        decision_recorded=True,
        configured_challenger=CHALLENGER_MODEL,
        runner=runner,
        list_models=lambda: [INCUMBENT_MODEL, CHALLENGER_MODEL],
        budget_status=lambda: {"constraining": False, "remaining_weekly_ops_usd": 100.0},
        record_spend=lambda _amount: None,
    )
    assert calls == [INCUMBENT_MODEL, CHALLENGER_MODEL]
    by_model = {row["model"]: row for row in result["names"]}
    assert by_model[INCUMBENT_MODEL]["action"] == "requested"
    assert by_model[INCUMBENT_MODEL]["live_research_written"] is False
    assert by_model[CHALLENGER_MODEL]["skip_reason"] == "rejected_live_write"
    assert by_model[CHALLENGER_MODEL]["verdict"] is None
    log = tmp_path / "docs" / "data" / "strategy_book_memo_model_shadow_memos.jsonl"
    stored = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert all(row["influences_live"] is False for row in stored)
    assert not any("research.json" in json.dumps(row) and row.get("verdict") for row in stored)


def test_missing_decision_does_not_call_a_model(tmp_path: Path) -> None:
    def runner(**_kwargs: object) -> dict:
        raise AssertionError("model called")

    result = request_shadow_memos(
        [_signal()],
        [],
        repo_root=tmp_path,
        now=datetime(2026, 11, 22, 18, 0, tzinfo=UTC),
        apply=True,
        decision_recorded=False,
        configured_challenger=CHALLENGER_MODEL,
        runner=runner,
        list_models=lambda: [INCUMBENT_MODEL, CHALLENGER_MODEL],
    )
    assert result["requested"] == 0
    assert result["skipped_reason"] == "decision_evidence_missing"
    assert not (tmp_path / "docs" / "data" / "strategy_book_memo_model_shadow_memos.jsonl").exists()


def test_findings_and_ops_check(tmp_path: Path) -> None:
    data = tmp_path / "docs" / "data"
    data.mkdir(parents=True)
    missing = check_strategy_book_memo_model_shadow(repo_root=tmp_path, now=NOW)
    assert missing[0].title == TITLE_MISSING
    assert missing[0].auto_fixable is False

    summary = run_shadow(
        repo_root=tmp_path,
        now=NOW,
        apply=True,
        signals=[_signal()],
        series_for=lambda _market, _ticker: None,
        memo_rows=[],
        decision=_decision(),
    )
    assert summary["wrote"] is True
    store = json.loads((data / STORE_NAME).read_text(encoding="utf-8"))
    assert store["influences_live"] is False
    assert store["live_model_changed"] is False
    assert store["rememo_live"] is False
    found = check_strategy_book_memo_model_shadow(repo_root=tmp_path, now=NOW)
    assert found[0].title == TITLE_REFRESHED
    assert found[0].severity == "info"
    assert found[0].auto_fixable is False
    assert "composer-2.5" in found[0].summary
    assert "unchanged" in found[0].summary

    store["decision"]["status"] = "missing"
    warned = findings_from_store(store, now=NOW)
    assert any(row["title"] == TITLE_FAIL_CLOSED and row["auto_fixable"] is False for row in warned)
    assert "check_strategy_book_memo_model_shadow" in inspect.getsource(collect_ops_findings)


def test_workflow_requests_memos_without_blocking_the_commit() -> None:
    workflow = FORWARD.read_text(encoding="utf-8")
    email = EMAIL.read_text(encoding="utf-8")
    text = MODULE.read_text(encoding="utf-8")
    assert "ftse-strategy-book-memo-model-shadow" in workflow
    assert "--request-memos" in workflow
    assert f"docs/data/{STORE_NAME}" in workflow
    assert f"docs/data/{STORE_NAME}" in email
    assert "continue-on-error: true" in workflow
    forward_at = workflow.index("ftse-strategy-book-forward")
    shadow_at = workflow.index("ftse-strategy-book-memo-model-shadow")
    commit_at = workflow.index("Commit strategy-book forward artifacts")
    assert forward_at < shadow_at < commit_at
    assert "ResearchStore" not in text
    assert "default_memo_runner" not in text
    assert "forward_live" not in text
