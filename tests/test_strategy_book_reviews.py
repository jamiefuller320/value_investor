"""Strategy-book review queue: closes, levers, and ops-monitor findings."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.cue_consumer_mft import MOM_LEVERS, authorize_judgment_live_influence
from value_investor.ops_monitor import check_strategy_book_reviews, collect_ops_findings
from value_investor.post_sale_review_labels import record_accept
from value_investor.strategy_book_reviews import (
    FINDING_TITLE,
    LABELS_FILENAME,
    MISSING_TITLE,
    REVIEW_LAG_DAYS,
    STORE_FAILED_TITLE,
    build_strategy_book_review_queue,
    refresh_strategy_book_reviews,
)

NOW = datetime(2026, 11, 11, tzinfo=UTC)
FLOOR_ID = "ftse350:AAA.L:primary:2026-01-05"
FAIL_ID = "ftse350:BBB.L:primary:2026-01-12"
THESIS_ID = "ftse350:CCC.L:primary:2026-02-02"
PROVENANCE_ID = "ftse350:DDD.L:primary:2026-02-10"
DRAFT_ID = "ftse350:AAA.L:draft_v0_exit:2026-01-05"
SHADOW_ID = "ftse350:EEE.L:decline_rejected_shadow:2026-01-20"
CONTROL_ID = "ftse350:AAA.L:buy_on_signal:2026-01-08"
OPEN_ID = "ftse350:FFF.L:primary:2026-03-02"
DRIFT_ID = "ftse350:GGG.L:primary:2026-01-15"


def _episode(**overrides: object) -> dict:
    row = {
        "episode_id": FLOOR_ID,
        "market": "ftse350",
        "ticker": "AAA.L",
        "column": "primary",
        "status": "closed",
        "currency": "GBP",
        "signal_session": "2026-01-05",
        "fill_session": "2026-01-06",
        "exit_session": "2026-03-02",
        "exit_reason": "floor_exit",
        "exit_fill": 110.0,
        "fair_cost_return": 0.12,
        "matched_excess": 0.08,
        "recovery_label": False,
        "launched": True,
        "held_calendar_days": 55,
        "held_sessions": 40,
        "stake": 100.0,
        "provenance_missing": False,
        "memo_verdict": "accumulate",
        "memo_rationale": "Cheap and not declining at the signal.",
        "snapshot": {
            "signal": "buy",
            "research_verdict": "accumulate",
            "timing_signal": "buy",
            "sector": "Industrials",
            "conviction_score": 0.55,
            "data_quality_score": 0.8,
            "market": "ftse350",
        },
        "decision_log": [
            {
                "session": "2026-03-02",
                "action": "floor_exit",
                "close": 110.0,
                "entry_fill": 100.0,
            }
        ],
        "floor_history": [{"session": "2026-02-01", "floor": 0.05}],
        "reviews": [{"session": "2026-02-20", "action": "hold"}],
        "inputs": {
            "entry": [{"path": "docs/data/charts/AAA.L.json", "sha256": "abc"}],
            "reviews": [
                {
                    "session": "2026-02-20",
                    "inputs": [{"path": "docs/data/charts/AAA.L.json", "sha256": "abc"}],
                },
                {
                    "session": "2026-04-01",
                    "inputs": [{"path": "docs/data/charts/AAA.L.json", "sha256": "later"}],
                },
            ],
        },
    }
    row.update(overrides)
    return row


def _observe() -> dict:
    return {
        "registration_id": "owner-strategy-book-v0",
        "scoring_date": "2026-11-10",
        "influences_live": False,
        "episodes": [
            _episode(),
            _episode(
                episode_id=FAIL_ID,
                ticker="BBB.L",
                signal_session="2026-01-12",
                fill_session="2026-01-13",
                exit_session="2026-04-15",
                exit_reason="fail_to_launch",
                fair_cost_return=-0.06,
                matched_excess=-0.04,
                recovery_label=True,
                launched=False,
                held_calendar_days=90,
                held_sessions=63,
            ),
            _episode(
                episode_id=THESIS_ID,
                ticker="CCC.L",
                signal_session="2026-02-02",
                fill_session="2026-02-03",
                exit_session="2026-05-01",
                exit_reason="thesis_break",
                fair_cost_return=-0.11,
                matched_excess=-0.09,
                recovery_label=False,
                launched=False,
                decision_log=[
                    {
                        "session": "2026-05-01",
                        "action": "thesis_break",
                        "reasons": ["declining"],
                    },
                    {
                        "session": "2026-06-01",
                        "action": "thesis_break",
                        "reasons": ["later_hindsight"],
                    },
                ],
            ),
            _episode(
                episode_id=PROVENANCE_ID,
                ticker="DDD.L",
                signal_session="2026-02-10",
                fill_session="2026-02-11",
                exit_session="2026-05-20",
                exit_reason="floor_exit",
                fair_cost_return=0.04,
                matched_excess=0.03,
                provenance_missing=True,
            ),
            _episode(
                episode_id=DRAFT_ID,
                column="draft_v0_exit",
                exit_session="2026-02-02",
                exit_reason="swing_high",
                fair_cost_return=0.04,
                matched_excess=0.01,
                launched=False,
            ),
            _episode(
                episode_id=SHADOW_ID,
                ticker="EEE.L",
                column="decline_rejected_shadow",
                signal_session="2026-01-20",
                fill_session="2026-01-21",
                exit_session="2026-04-01",
                exit_reason="floor_exit",
                fair_cost_return=-0.1,
                matched_excess=-0.08,
            ),
            _episode(
                episode_id=CONTROL_ID,
                column="buy_on_signal",
                signal_session="2026-01-08",
                fill_session="2026-01-09",
                exit_session="2026-04-02",
                exit_reason="hold_63",
                fair_cost_return=0.02,
                matched_excess=0.0,
                launched=False,
            ),
            _episode(
                episode_id=OPEN_ID,
                ticker="FFF.L",
                status="open",
                signal_session="2026-03-02",
                fill_session="2026-03-03",
                exit_session=None,
                exit_reason=None,
                fair_cost_return=None,
                matched_excess=None,
            ),
            _episode(
                episode_id=DRIFT_ID,
                ticker="GGG.L",
                signal_session="2026-01-15",
                fill_session="2026-01-16",
                exit_session="2026-03-20",
                exit_reason="floor_exit",
                fair_cost_return=0.1,
                matched_excess=0.0,
            ),
        ],
    }


def _gate_log() -> list[dict]:
    return [
        {
            "kind": "session",
            "market": "ftse350",
            "ticker": "AAA.L",
            "as_of": "2026-01-05",
            "decline": "clear",
            "sector": "sound",
            "signal": "buy",
            "f9": "pass",
        },
        {
            "kind": "session",
            "market": "ftse350",
            "ticker": "AAA.L",
            "as_of": "2026-04-01",
            "decline": "declining",
            "sector": "headwind",
            "signal": "avoid",
        },
    ]


def _queue() -> dict:
    return build_strategy_book_review_queue(
        _observe(),
        gate_rows=_gate_log(),
        now=NOW,
    )


def _by_id(payload: dict) -> dict[str, dict]:
    return {row["episode_id"]: row for row in payload["rows"]}


def test_closed_primaries_are_queued_and_open_is_not() -> None:
    payload = _queue()
    rows = _by_id(payload)
    assert OPEN_ID not in rows
    assert payload["counts"]["open_skipped"] == 1
    for episode_id, label in (
        (FLOOR_ID, "exit_rule"),
        (FAIL_ID, "entry_timing"),
        (THESIS_ID, "thesis_break"),
    ):
        row = rows[episode_id]
        assert row["attention"] == "primary"
        assert row["column"] == "primary"
        assert row["source"] == "strategy_book"
        assert row["book"] == "strategy_book"
        assert row["review_id"] == episode_id
        assert row["attribution"]["label"] == label
        assert row["evidence_status"] == "scored"
        assert row["fair_cost_return"] is not None
        assert row["matched_excess"] is not None
        assert row["cited_inputs"]
        assert row["influences_live"] is False
        assert authorize_judgment_live_influence(row["judgment_in_the_round"]) is False
        assert row["judgment_in_the_round"]["influences_live"] is False
        assert row["judgment_in_the_round"]["observe_only"] is True
        assert [lever["id"] for lever in row["levers"]] == [item["id"] for item in MOM_LEVERS]
        assert row["levers"][0]["definition"] == MOM_LEVERS[0]["definition"]
    assert rows[DRIFT_ID]["attribution"]["label"] == "market_drift"
    assert all(row["opinion_llm"] is False for row in payload["rows"])
    assert payload["opinion_llm"] is False
    assert payload["influences_live"] is False


def test_comparison_control_and_shadow_do_not_crowd_primary() -> None:
    payload = _queue()
    active = {row["episode_id"] for row in payload["active"]}
    companion = {row["episode_id"] for row in payload["companion"]}
    assert FLOOR_ID in active
    assert FAIL_ID in active
    assert THESIS_ID in active
    assert DRAFT_ID not in active
    assert CONTROL_ID not in active
    assert SHADOW_ID not in active
    assert {DRAFT_ID, CONTROL_ID, SHADOW_ID} <= companion
    draft = _by_id(payload)[DRAFT_ID]
    assert draft["column"] == "draft_v0_exit"
    assert draft["column_role"] == "comparison"
    shadow = _by_id(payload)[SHADOW_ID]
    assert shadow["attribution"]["label"] == "gate_miss"
    assert shadow["levers"][0]["would_have_helped"] == "yes"
    attentions = [row["attention"] for row in payload["rows"]]
    assert attentions.index("companion") > attentions.index("primary")
    assert "companion" not in attentions[: attentions.index("companion")]


def test_point_in_time_withholds_later_gate_log_and_later_control() -> None:
    row = _by_id(_queue())[FLOOR_ID]
    pit_dates = [item.get("as_of") for item in row["pit_gate_log"]]
    assert "2026-01-05" in pit_dates
    assert "2026-04-01" not in pit_dates
    assert any(
        item.get("as_of") == "2026-04-01" and item.get("withheld") == "after_exit"
        for item in row["hindsight"]
    )
    assert all("2026-04-01" not in str(cite) for lever in row["levers"] for cite in lever["cites"])
    timing = next(lever for lever in row["levers"] if lever["id"] == "buy_timing")
    assert timing["would_have_helped"] == "insufficient_data"
    assert CONTROL_ID in timing["hindsight"]
    sell = next(lever for lever in row["levers"] if lever["id"] == "sell_timing")
    assert sell["would_have_helped"] == "no"
    assert DRAFT_ID in " ".join(sell["cites"])
    strategy = next(lever for lever in row["levers"] if lever["id"] == "buy_strategy")
    assert strategy["would_have_helped"] == "insufficient_data"
    thesis = _by_id(_queue())[THESIS_ID]
    actions = [item.get("action") for item in thesis["decision_log"]]
    assert actions == ["thesis_break"]
    assert any(item.get("withheld") == "after_exit" for item in thesis["hindsight"])
    late_inputs = [
        item
        for item in row["cited_inputs"]
        if isinstance(item, dict) and str(item.get("session") or "") == "2026-04-01"
    ]
    assert late_inputs == []


def test_provenance_missing_is_queued_and_not_evidence() -> None:
    row = _by_id(_queue())[PROVENANCE_ID]
    assert row["provenance_missing"] is True
    assert row["attention"] == "primary"
    assert row["evidence_status"] == "insufficient_data"
    assert row["attribution"]["label"] == "insufficient_data"
    assert row["attribution"]["because"] == "provenance_missing"
    assert row["attribution"]["provisional_label"] == "exit_rule"
    assert row["attribution"]["counts_as_evidence"] is False
    assert row["judgment_in_the_round"]["counts_as_evidence"] is False
    for lever in row["levers"]:
        assert lever["would_have_helped"] == "insufficient_data"
        assert lever["status"] == "insufficient_data"
        assert lever["value"] is None


def test_refresh_is_idempotent_and_accept_does_not_duplicate(tmp_path: Path) -> None:
    data = tmp_path / "docs" / "data"
    data.mkdir(parents=True)
    observe = data / "strategy_book_observe.json"
    observe.write_text(json.dumps(_observe()), encoding="utf-8")
    gate = data / "strategy_book_gate_log.jsonl"
    gate.write_text(
        "\n".join(json.dumps(row) for row in _gate_log()) + "\n",
        encoding="utf-8",
    )
    store = data / "strategy_book_review_queue.json"
    first = refresh_strategy_book_reviews(
        data_dir=data,
        observe_path=observe,
        gate_log_path=gate,
        store_path=store,
        now=NOW,
    )
    second = refresh_strategy_book_reviews(
        data_dir=data,
        observe_path=observe,
        gate_log_path=gate,
        store_path=store,
        now=NOW,
    )
    assert [row["episode_id"] for row in first["rows"]] == [
        row["episode_id"] for row in second["rows"]
    ]
    assert len(first["rows"]) == len({row["episode_id"] for row in first["rows"]})
    left = {key: value for key, value in first.items() if key not in {"generated_at", "path"}}
    right = {key: value for key, value in second.items() if key not in {"generated_at", "path"}}
    assert left == right
    record_accept(
        data,
        review_id=FLOOR_ID,
        source="strategy_book",
        filename=LABELS_FILENAME,
        snapshot={
            "book_id": "owner-strategy-book-v0",
            "book_tag": "Strategy book",
            "ticker": "AAA.L",
        },
    )
    third = refresh_strategy_book_reviews(
        data_dir=data,
        observe_path=observe,
        gate_log_path=gate,
        store_path=store,
        now=NOW,
    )
    assert FLOOR_ID in {row["episode_id"] for row in third["rows"]}
    assert FLOOR_ID not in {row["episode_id"] for row in third["active"]}
    assert sum(1 for row in third["rows"] if row["episode_id"] == FLOOR_ID) == 1


def test_ops_monitor_info_when_every_close_is_queued(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "strategy_book_observe.json").write_text(json.dumps(_observe()), encoding="utf-8")
    findings = check_strategy_book_reviews(data_dir=data, now=NOW)
    assert [row.title for row in findings] == [FINDING_TITLE]
    assert findings[0].severity == "info"
    assert findings[0].auto_fixable is False
    assert "primary=" in findings[0].summary
    assert (data / "strategy_book_review_queue.json").is_file()


def test_ops_monitor_warns_when_an_old_close_has_no_row(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    observe = {
        "registration_id": "owner-strategy-book-v0",
        "episodes": [
            _episode(episode_id="", exit_session="2026-01-01"),
            _episode(
                episode_id="",
                ticker="HHH.L",
                exit_session="2026-11-10",
                signal_session="2026-11-09",
            ),
        ],
    }
    (data / "strategy_book_observe.json").write_text(json.dumps(observe), encoding="utf-8")
    findings = check_strategy_book_reviews(data_dir=data, now=NOW)
    titles = [row.title for row in findings]
    assert FINDING_TITLE in titles
    warn = next(row for row in findings if row.title == MISSING_TITLE)
    assert warn.severity == "warn"
    assert warn.auto_fixable is False
    assert "AAA.L" in warn.summary
    assert "HHH.L" not in warn.summary
    assert REVIEW_LAG_DAYS == 2


def test_ops_monitor_fails_closed_when_the_store_cannot_be_read(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    missing = check_strategy_book_reviews(data_dir=data, now=NOW)
    assert [row.title for row in missing] == [STORE_FAILED_TITLE]
    assert missing[0].severity == "warn"
    assert missing[0].auto_fixable is False
    (data / "strategy_book_observe.json").write_text("{", encoding="utf-8")
    broken = check_strategy_book_reviews(data_dir=data, now=NOW)
    assert [row.title for row in broken] == [STORE_FAILED_TITLE]
    assert broken[0].auto_fixable is False


def test_collect_ops_findings_calls_the_review_check() -> None:
    source = inspect.getsource(collect_ops_findings)
    assert "check_strategy_book_reviews" in source


def _closed_named(
    episode_id: str,
    *,
    column: str,
    fill: str,
    exit_at: str,
    fair: float,
    signal: str = "2026-01-05",
    ticker: str = "ZZZ.L",
) -> dict:
    return _episode(
        episode_id=episode_id,
        ticker=ticker,
        column=column,
        signal_session=signal,
        fill_session=fill,
        exit_session=exit_at,
        exit_reason="hold_63" if column == "buy_on_signal" else "floor_exit",
        fair_cost_return=fair,
        matched_excess=0.05,
        recovery_label=False,
        launched=True,
        held_calendar_days=40,
    )


def test_buy_timing_ignores_a_better_control_outside_the_entry_window() -> None:
    own = "ftse350:ZZZ.L:primary:2026-01-05"
    far = "ftse350:ZZZ.L:buy_on_signal:2026-02-02"
    payload = build_strategy_book_review_queue(
        {
            "registration_id": "owner-strategy-book-v0",
            "episodes": [
                _closed_named(
                    own, column="primary", fill="2026-01-06", exit_at="2026-06-01", fair=0.0
                ),
                _closed_named(
                    far,
                    column="buy_on_signal",
                    fill="2026-02-02",
                    exit_at="2026-04-01",
                    fair=0.25,
                ),
            ],
        },
        now=NOW,
    )
    timing = next(lever for lever in _by_id(payload)[own]["levers"] if lever["id"] == "buy_timing")
    assert timing["would_have_helped"] == "insufficient_data"
    assert timing["because"] == "no_overlapping_counterfactual_entry"
    assert far in timing["outside_window"]
    assert far not in " ".join(timing["cites"])


def test_buy_timing_uses_the_nearest_fill_inside_the_window() -> None:
    own = "ftse350:ZZZ.L:primary:2026-01-05"
    near = "ftse350:ZZZ.L:buy_on_signal:2026-01-07"
    further = "ftse350:ZZZ.L:buy_on_signal:2026-01-20"
    outside = "ftse350:ZZZ.L:buy_on_signal:2026-02-02"
    payload = build_strategy_book_review_queue(
        {
            "registration_id": "owner-strategy-book-v0",
            "episodes": [
                _closed_named(
                    own, column="primary", fill="2026-01-06", exit_at="2026-06-01", fair=0.0
                ),
                _closed_named(
                    near,
                    column="buy_on_signal",
                    fill="2026-01-07",
                    exit_at="2026-04-01",
                    fair=0.0,
                ),
                _closed_named(
                    further,
                    column="buy_on_signal",
                    fill="2026-01-20",
                    exit_at="2026-04-01",
                    fair=0.25,
                ),
                _closed_named(
                    outside,
                    column="buy_on_signal",
                    fill="2026-02-02",
                    exit_at="2026-04-01",
                    fair=0.5,
                ),
            ],
        },
        now=NOW,
    )
    timing = next(lever for lever in _by_id(payload)[own]["levers"] if lever["id"] == "buy_timing")
    cites = " ".join(timing["cites"])
    assert timing["would_have_helped"] == "no"
    assert f"counterfactual_episode_id={near}" in cites
    assert f"counterfactual_episode_id={further}" not in cites
    assert further not in timing["outside_window"]
    assert outside in timing["outside_window"]
    assert "session_gap=1" in cites


def test_sell_levers_follow_the_median_not_the_best_pair() -> None:
    own = "ftse350:ZZZ.L:primary:2026-01-05"
    draft = "ftse350:ZZZ.L:draft_v0_exit:2026-01-05"
    ladder = "ftse350:ZZZ.L:ladder_no_deadline:2026-01-05"
    leave = "ftse350:ZZZ.L:leave_tier:2026-01-05"
    payload = build_strategy_book_review_queue(
        {
            "registration_id": "owner-strategy-book-v0",
            "episodes": [
                _closed_named(
                    own, column="primary", fill="2026-01-06", exit_at="2026-06-01", fair=0.0
                ),
                _closed_named(
                    draft,
                    column="draft_v0_exit",
                    fill="2026-01-06",
                    exit_at="2026-03-01",
                    fair=0.25,
                ),
                _closed_named(
                    ladder,
                    column="ladder_no_deadline",
                    fill="2026-01-06",
                    exit_at="2026-03-02",
                    fair=-0.25,
                ),
                _closed_named(
                    leave,
                    column="leave_tier",
                    fill="2026-01-06",
                    exit_at="2026-03-03",
                    fair=-0.125,
                ),
            ],
        },
        now=NOW,
    )
    row = _by_id(payload)[own]
    for lever_id in ("sell_timing", "sell_strategy"):
        lever = next(item for item in row["levers"] if item["id"] == lever_id)
        cites = " ".join(lever["cites"])
        assert lever["would_have_helped"] == "no"
        assert lever["alternatives_n"] == 3
        assert lever["alternatives_beating_n"] == 1
        assert lever["median_delta"] == -0.125
        assert f"alternative={draft}" in cites
        assert f"alternative={ladder}" in cites
        assert f"alternative={leave}" in cites
        assert "median_delta=-0.125" in cites
