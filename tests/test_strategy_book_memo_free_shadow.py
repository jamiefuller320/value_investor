"""Memo-free shadow: binds are labels, gates still block, early marks stay off the book."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from value_investor.ops_monitor import check_strategy_book_memo_free_shadow, collect_ops_findings
from value_investor.strategy_book_memo_free_shadow import (
    DESIGN,
    EARLY_OUTCOME_MIN_N,
    STORE_NAME,
    TITLE_MISSING,
    TITLE_REFRESHED,
    TITLE_STALE,
    TITLE_UNREADABLE,
    build_boards,
    early_marks_for_series,
    early_outcome_board,
    findings_from_store,
    relax_spec,
    run_memo_free_shadow,
    score_names,
    shadow_options,
)
from value_investor.strategy_book_observe import (
    F9Fact,
    GateFact,
    MemoFact,
    NameSpec,
    ScreenFact,
    options_for,
    walk_book,
)
from value_investor.strategy_book_rules import COLUMN_PRIMARY, LAUNCH_RETURN, STAKE_UNITS

START = date(2024, 1, 2)
PLAN = Path(__file__).resolve().parents[1] / "docs" / "ops" / "strategy-reorientation-plan.md"
FORWARD_YML = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "strategy-book-forward.yml"
)
EMAIL_YML = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "email-report.yml"
SEALED_STEP_32 = "4e99e9ad1b741a6fc8816575f1fcf6a9ac717c5693ad0244b9e46f9c7a207349"


def _weekdays(count: int, start: date = START) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _decline(count: int = 15, start: float = 80.0) -> list[float]:
    return [start - float(index) for index in range(count)]


def _spec(
    closes: list[float],
    *,
    ticker: str = "AAA.L",
    signal_index: int = 14,
    signal: str = "buy",
    research: str = "hold",
    decline: str = "clear",
    sector: str = "sound",
    memo: bool = False,
    memo_verdict: str = "hold",
    binds: dict[str, bool] | None = None,
    extra_facts: list[F9Fact] | None = None,
    extra_gates: list[GateFact] | None = None,
    seen: dict[date, datetime] | None = None,
    f9: bool = True,
) -> NameSpec:
    days = _weekdays(len(closes))
    run_day = days[signal_index - 1]
    fill_day = days[signal_index + 1] if signal_index + 1 < len(days) else None
    flags = {
        "key_filing_bodies": True,
        "fcf_basis_bound": True,
        "overlay_bound": True,
        "memo_recent": True,
    }
    if binds:
        flags.update(binds)
    facts: list[F9Fact] | None = None
    if f9:
        facts = [
            F9Fact(as_of=days[signal_index], **flags),
            *(extra_facts or []),
        ]
    memos: list[MemoFact] = []
    if memo and fill_day is not None:
        memos.append(
            MemoFact(
                finished_at=datetime.combine(fill_day, time(12), tzinfo=UTC),
                verdict=memo_verdict,
                rationale="fixture",
            )
        )
    gates = [GateFact(as_of=run_day, decline=decline, sector=sector, sector_basis="own_market")]
    if extra_gates:
        gates.extend(extra_gates)
    return NameSpec(
        market="ftse350",
        ticker=ticker,
        sessions=days,
        closes=[float(value) for value in closes],
        screens=[
            ScreenFact(
                run_date=run_day,
                signal=signal,
                adjusted_signal=signal,
                research_verdict=research,
            )
        ],
        gates=gates,
        memos=memos,
        f9=facts,
        signal_seen_at=seen,
    )


def _primary(result: dict) -> list[dict]:
    return [row for row in result["episodes"] if row.get("column") == COLUMN_PRIMARY]


def _shadow(spec: NameSpec) -> dict:
    return score_names([spec], shadow_options())


def _forward_primary(spec: NameSpec) -> list[dict]:
    result = walk_book([spec], options=options_for("forward"))
    return [row for row in result["episodes"] if row.get("column") == COLUMN_PRIMARY]


def test_memo_bind_is_dropped_and_labelled() -> None:
    spec = _spec(_decline() + [100.0] * 5, binds={"memo_recent": False})
    assert _forward_primary(spec) == []
    episode = _primary(_shadow(spec))[0]
    assert "memo_recent" in episode["failed_binds"]
    assert episode["stake"] == STAKE_UNITS
    assert episode["column"] == COLUMN_PRIMARY


def test_memo_verdict_does_not_block_and_is_labelled() -> None:
    spec = _spec(_decline() + [100.0] * 5, memo=True, memo_verdict="avoid")
    assert _forward_primary(spec) == []
    episode = _primary(_shadow(spec))[0]
    assert episode["failed_binds"] == ["memo_verdict"]


def test_filing_fcf_and_overlay_are_labels_not_filters() -> None:
    spec = _spec(
        _decline() + [100.0] * 5,
        binds={
            "key_filing_bodies": False,
            "fcf_basis_bound": False,
            "overlay_bound": False,
            "memo_recent": False,
        },
    )
    assert _forward_primary(spec) == []
    episode = _primary(_shadow(spec))[0]
    assert episode["failed_binds"] == [
        "key_filing_bodies",
        "fcf_basis_bound",
        "overlay_bound",
        "memo_recent",
    ]


def test_decline_and_sector_gates_still_block() -> None:
    closes = _decline() + [100.0] * 5
    assert _primary(_shadow(_spec(closes, decline="declining"))) == []
    assert _primary(_shadow(_spec(closes, sector="headwind"))) == []
    assert _primary(_shadow(_spec(closes, research="avoid"))) == []


def test_one_open_per_name() -> None:
    # A continued decline keeps the price rule true, so later sessions try again.
    result = _shadow(_spec(_decline(40), binds={"memo_recent": False}))
    assert len(_primary(result)) == 1
    assert any(event.get("kind") == "already_open_skip" for event in result["events"])


def test_cooldown_after_a_thesis_exit() -> None:
    closes = _decline() + [100.0, 100.0, 90.0, 85.0, 80.0, 75.0, 70.0, 65.0, 60.0]
    days = _weekdays(len(closes))
    spec = _spec(
        closes,
        binds={"memo_recent": False},
        extra_gates=[
            GateFact(as_of=days[15], decline="declining", sector="sound"),
            GateFact(as_of=days[16], decline="declining", sector="sound"),
            GateFact(as_of=days[17], decline="clear", sector="sound"),
        ],
    )
    result = _shadow(spec)
    assert len(_primary(result)) == 1
    assert _primary(result)[0]["exit_reason"] == "thesis_break"
    assert any(event.get("kind") == "cooldown_skip" for event in result["events"])


def test_later_store_does_not_relabel_a_logged_session() -> None:
    closes = _decline() + [100.0] * 8
    days = _weekdays(len(closes))
    later = F9Fact(
        as_of=days[-1],
        key_filing_bodies=True,
        fcf_basis_bound=True,
        overlay_bound=True,
        memo_recent=True,
    )
    spec = _spec(
        closes,
        binds={"key_filing_bodies": False, "memo_recent": False},
        extra_facts=[later],
    )
    episode = _primary(_shadow(spec))[0]
    assert "key_filing_bodies" in episode["failed_binds"]
    assert "memo_recent" in episode["failed_binds"]
    assert "fcf_basis_bound" not in episode["failed_binds"]


def test_unlogged_session_fails_closed() -> None:
    closes = _decline() + [100.0] * 5
    days = _weekdays(len(closes))
    # Today's all-pass fact is dated after the signal, so it is not in force.
    only_later = _spec(closes, f9=False)
    only_later.f9 = [
        F9Fact(
            as_of=days[-1],
            key_filing_bodies=True,
            fcf_basis_bound=True,
            overlay_bound=True,
            memo_recent=True,
        )
    ]
    assert _primary(_shadow(only_later)) == []

    logged_pass = _spec(closes)
    logged_pass.signal_seen_at = {days[14]: datetime(2026, 11, 11, 15, tzinfo=UTC)}
    result = _shadow(logged_pass)
    assert _primary(result) == []
    assert any(event.get("kind") == "late_signal" for event in result["events"])


def test_relax_does_not_invent_a_fact() -> None:
    spec = _spec(_decline() + [100.0] * 3, f9=False)
    relaxed = relax_spec(spec)
    assert relaxed.f9 == []
    assert spec.f9 is None


def test_early_marks_at_s10_and_s20_and_outcome() -> None:
    path = [100.0] + [100.0] * 8 + [110.4] + [112.0] * 10 + [116.0] + [112.0] * 5 + [109.8, 109.5]
    result = _shadow(_spec(_decline() + path))
    episode = _primary(result)[0]
    s10 = episode["early_marks"]["s10"]
    s20 = episode["early_marks"]["s20"]
    assert s10["available"] is True
    assert s10["return_from_fill"] == pytest.approx(0.12)
    assert s10["launch_progress"] == pytest.approx(0.12 / LAUNCH_RETURN)
    assert s10["launched"] is True
    assert s10["max_drawdown"] == pytest.approx(0.0)
    assert s10["channel_direction_change"] is False
    assert s20["available"] is True
    assert s20["return_from_fill"] == pytest.approx(0.16)
    assert s20["launched"] is True
    assert episode["outcome_63_basis"] == "realized_exit"
    assert episode["outcome_63"] == pytest.approx(episode["fair_cost_return"])
    assert "early_marks" not in _forward_primary(_spec(_decline() + path, memo=True))[0]


def test_early_outcome_board_needs_a_minimum() -> None:
    def row(ret: float, *, launched: bool) -> dict:
        return {
            "outcome_63": 0.02,
            "early_marks": {
                "s10": {"available": True, "return_from_fill": ret},
                "s20": {"available": True, "return_from_fill": ret, "launched": launched},
            },
        }

    thin = early_outcome_board([row(0.01, launched=False)])
    assert thin["status"] == "insufficient_data"
    assert thin["min_n"] == EARLY_OUTCOME_MIN_N
    assert thin["by_s10_return_bucket"]["zero_to_plus_5"]["status"] == "insufficient_data"
    assert thin["by_s10_return_bucket"]["zero_to_plus_5"]["n"] == 1
    assert thin["by_s10_return_bucket"]["zero_to_plus_5"]["median_outcome_63"] is None

    thick = early_outcome_board([row(0.01, launched=True) for _ in range(EARLY_OUTCOME_MIN_N)])
    cell = thick["by_s20_return_bucket"]["zero_to_plus_5"]
    assert cell["status"] == "ok"
    assert cell["n"] == EARLY_OUTCOME_MIN_N
    assert cell["median_outcome_63"] == pytest.approx(0.02)
    assert thick["launched_by_s20"]["launched"]["status"] == "ok"
    assert thick["launched_by_s20"]["not_launched"]["n"] == 0


def test_channel_direction_change_is_recorded() -> None:
    rising = [100.0 + index * 0.4 for index in range(160)]
    falling = [rising[-1] - index * 1.5 for index in range(1, 40)]
    closes = rising + falling
    days = _weekdays(len(closes))
    fill = days[170]
    marks, _outcome, _basis = early_marks_for_series(days, closes, fill_session=fill)
    assert marks["s10"]["available"] is True
    assert marks["s10"]["channel_direction_at_fill"] in {"rising", "falling", "sideways"}
    assert isinstance(marks["s10"]["channel_direction_change"], bool)


def test_forward_walk_output_has_no_shadow_fields() -> None:
    episode = _forward_primary(_spec(_decline() + [100.0] * 5, memo=True))[0]
    assert "failed_binds" not in episode
    assert "early_marks" not in episode
    assert "outcome_63" not in episode


def test_sealed_step_32_hash_is_unchanged() -> None:
    text = PLAN.read_text(encoding="utf-8")
    start = text.index("#### Step 3.2 proof numbers")
    end = text.index("### Phase 4", start)
    digest = hashlib.sha256(text[start:end].encode()).hexdigest()
    assert digest == SEALED_STEP_32
    assert "memo-free forward shadow" in text.lower() or "Memo-free forward shadow" in text


def test_boards_split_by_market_and_label() -> None:
    spec = _spec(_decline() + [100.0] * 5, binds={"memo_recent": False})
    boards = build_boards(_primary(_shadow(spec)))
    assert boards["counted"] == 1
    assert boards["open"] == 1
    assert boards["mature"] == 0
    assert boards["median_fair_cost_return"] is None
    assert boards["by_market"]["ftse350"]["counted"] == 1
    assert boards["by_failed_bind"]["memo_recent"]["counted"] == 1
    assert boards["launch_share"] == 0.0
    assert boards["early_outcomes"]["status"] == "insufficient_data"


def test_run_does_not_rewrite_the_observe_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "docs" / "data"
    data.mkdir(parents=True)
    observe = data / "strategy_book_observe.json"
    sentinel = '{"sentinel": true, "episodes": []}\n'
    observe.write_text(sentinel, encoding="utf-8")
    (data / "strategy_book_registration.json").write_text(
        json.dumps({"signed": True, "forward_live": True, "forward_start": "2026-11-10"}),
        encoding="utf-8",
    )

    def _empty(*_args, **_kwargs):
        return {
            "specs": [],
            "blocked": {},
            "errors": ["euro_depth: unknown close"],
            "session_rows": [],
            "scored": {},
            "dropped": [],
        }

    monkeypatch.setattr(
        "value_investor.strategy_book_memo_free_shadow._load_forward_specs",
        _empty,
    )
    summary = run_memo_free_shadow(
        repo_root=tmp_path, now=datetime(2026, 11, 11, 18, tzinfo=UTC), apply=True
    )
    assert observe.read_text(encoding="utf-8") == sentinel
    assert summary["errors"] == []
    assert summary["wrote"] is True
    stored = json.loads((data / STORE_NAME).read_text(encoding="utf-8"))
    assert stored["influences_live"] is False
    assert stored["design"]["relaxed_binds"] == DESIGN["relaxed_binds"]
    assert stored["book_early_marks"]["counted"] == 0
    assert not (data / "strategy_book_gate_log.jsonl").exists()


def test_ops_monitor_warns_only_when_the_store_is_bad(tmp_path: Path) -> None:
    missing = check_strategy_book_memo_free_shadow(
        repo_root=tmp_path, now=datetime(2026, 11, 11, 22, tzinfo=UTC)
    )
    assert missing[0].title == TITLE_MISSING
    assert missing[0].severity == "warn"
    assert missing[0].auto_fixable is False

    data = tmp_path / "docs" / "data"
    data.mkdir(parents=True)
    path = data / STORE_NAME
    path.write_text("{", encoding="utf-8")
    broken = check_strategy_book_memo_free_shadow(repo_root=tmp_path)
    assert broken[0].title == TITLE_UNREADABLE
    assert broken[0].auto_fixable is False

    path.write_text(
        json.dumps(
            {"generated_at": "2026-11-01T00:00:00+00:00", "boards": {}, "book_early_marks": {}}
        ),
        encoding="utf-8",
    )
    stale = findings_from_store(
        json.loads(path.read_text(encoding="utf-8")),
        now=datetime(2026, 11, 11, 22, tzinfo=UTC),
    )
    assert stale[0]["title"] == TITLE_STALE
    assert stale[0]["auto_fixable"] is False

    fresh = {
        "generated_at": "2026-11-11T21:40:00+00:00",
        "boards": {
            "counted": 3,
            "open": 3,
            "mature": 0,
            "by_market": {"ftse350": {"counted": 3}},
            "by_failed_bind": {"memo_recent": {"counted": 2}},
            "early_outcomes": {"status": "insufficient_data", "min_n": 8},
        },
        "book_early_marks": {"counted": 1, "outcome_board": {"status": "insufficient_data"}},
    }
    ok = findings_from_store(fresh, now=datetime(2026, 11, 11, 22, tzinfo=UTC))
    assert ok[0]["title"] == TITLE_REFRESHED
    assert ok[0]["severity"] == "info"
    assert ok[0]["auto_fixable"] is False
    assert "check_strategy_book_memo_free_shadow" in inspect.getsource(collect_ops_findings)


def test_pending_fill_keeps_the_signal_labels() -> None:
    closes = _decline()
    result = score_names(
        [_spec(closes, binds={"memo_recent": False, "key_filing_bodies": False})],
        shadow_options(),
    )
    assert result["episodes"] == []
    assert len(result["pending"]) == 1
    assert result["pending"][0]["failed_binds"] == ["key_filing_bodies", "memo_recent"]
    assert result["pending"][0]["memo_verdict_checked"] is False


def test_book_early_marks_include_control_episodes() -> None:
    from value_investor.strategy_book_memo_free_shadow import book_early_marks

    days = _weekdays(12)
    section = book_early_marks(
        [
            {
                "episode_id": "aim:CAM.L:buy_on_signal:2026-11-09",
                "column": "buy_on_signal",
                "market": "aim",
                "ticker": "CAM.L",
                "status": "open",
                "fill_session": days[0].isoformat(),
                "fair_cost_return": None,
            }
        ],
        lambda _market, _ticker: (days, [100.0] * len(days), None, None),
    )
    assert section["counted"] == 1
    assert section["episodes"][0]["column"] == "buy_on_signal"
    assert section["episodes"][0]["early_marks"]["s10"]["available"] is True


def test_workflow_runs_the_shadow_without_blocking_the_commit() -> None:
    workflow = FORWARD_YML.read_text(encoding="utf-8")
    assert "ftse-strategy-book-memo-free-shadow" in workflow
    assert "continue-on-error: true" in workflow
    assert f"docs/data/{STORE_NAME}" in workflow
    email = EMAIL_YML.read_text(encoding="utf-8")
    assert f"docs/data/{STORE_NAME}" in email
    forward_at = workflow.index("ftse-strategy-book-forward")
    shadow_at = workflow.index("ftse-strategy-book-memo-free-shadow")
    commit_at = workflow.index("Commit strategy-book forward artifacts")
    assert forward_at < shadow_at < commit_at
