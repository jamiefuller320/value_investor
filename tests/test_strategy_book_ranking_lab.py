"""Slot-ranking lab: which primary signals take a slot in the 20-slot book (exploratory)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from test_strategy_book_us_rehearsal import NAMES, licensed, make_repo  # noqa: F401

from value_investor import strategy_book_observe as sbo
from value_investor import strategy_book_ranking_lab as ranking
from value_investor import strategy_book_us_rehearsal as rehearsal
from value_investor.strategy_book_rules import COLUMN_PRIMARY, SLOT_COUNT


def _day(offset: int) -> str:
    return (date(2010, 1, 4) + timedelta(days=offset)).isoformat()


def _episode(
    ticker: str,
    signal: int,
    hold: int,
    ret: float,
    *,
    lo252: float | None = None,
    sma: float | None = None,
    ret126: float | None = None,
    excess: float | None = None,
) -> dict:
    return {
        "column": COLUMN_PRIMARY,
        "market": "sp500",
        "ticker": ticker,
        "episode_id": f"sp500:{ticker}:{_day(signal)}",
        "signal_session": _day(signal),
        "fill_session": _day(signal + 1),
        "exit_session": _day(signal + 1 + hold),
        "entry_week": _day(signal - signal % 7),
        "fair_cost_return": ret,
        "decision_return_floor": ret,
        "matched_excess": ret if excess is None else excess,
        "mature": True,
        "snapshot": {"close_vs_sma200": sma, "return_126": ret126},
        "channels": {"lo252_dist_pct": lo252},
    }


def _crowded_book() -> list[dict]:
    rows = []
    for day in range(0, 120, 3):
        for slot in range(9):
            rows.append(_episode(f"T{day:03d}{slot}", day, 20 + slot, 0.01 * (slot - 3)))
    return rows


def test_simulation_with_the_registered_order_is_the_book_slot_book():
    rows = _crowded_book()
    mine = ranking.simulate(rows, ranking.registered_order)
    book = sbo._slot_book(rows, seed=1)
    assert mine["trades_taken"] == book["trades_taken"]
    assert mine["trades_skipped"] == book["trades_skipped"]
    assert mine["annualised_return"] == pytest.approx(book["annualised_return"])
    assert mine["max_drawdown"] == pytest.approx(book["max_drawdown"])
    assert mine["trades_skipped"] > 0
    assert mine["contested_sessions"] > 0
    assert mine["skipped_contested"] + mine["skipped_full"] == mine["trades_skipped"]


def test_contested_session_counts_only_when_some_but_too_few_slots_are_free():
    rows = [_episode(f"A{i:02d}", 0, 50, 0.0) for i in range(SLOT_COUNT - 1)]
    rows += [_episode(f"B{i}", 5, 10, 0.0) for i in range(3)]
    rows += [_episode("C0", 7, 10, 0.0)]
    result = ranking.simulate(rows, ranking.registered_order)
    assert result["contested_sessions"] == 1
    assert result["skipped_contested"] == 2
    assert result["skipped_full"] == 1


def test_scores_read_only_earlier_signal_sessions(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ranking, "WARMUP_SIGNALS", 3)
    rows = [_episode(f"E{i}", i, 5, 0.0, lo252=float(i), sma=0.1 * i) for i in range(3)]
    rows += [
        _episode("HIGH", 10, 5, 0.0, lo252=100.0, sma=-1.0, ret126=0.5),
        _episode("LOW", 10, 5, 0.0, lo252=-1.0, sma=1.0),
        _episode("MID", 10, 5, 0.0, lo252=1.0),
    ]
    scores = ranking.point_in_time_scores(rows)
    assert scores[("sp500", "E2", _day(2))]["lo252"] is None
    high = scores[("sp500", "HIGH", _day(10))]
    assert high["lo252"] == 1.0
    assert high["sma200"] == 0.0
    assert high["ret126"] is None
    assert high["trend3"] == pytest.approx(0.5)
    assert scores[("sp500", "LOW", _day(10))]["lo252"] == 0.0
    assert scores[("sp500", "MID", _day(10))]["lo252"] == pytest.approx(0.5)
    assert scores[("sp500", "MID", _day(10))]["trend3"] is None


def test_rank_orders_within_the_fill_session_and_skip_drops_the_scored_bottom():
    scores = {
        ("sp500", "A", _day(0)): {"lo252": 0.9},
        ("sp500", "B", _day(0)): {"lo252": 0.1},
        ("sp500", "C", _day(0)): {"lo252": None},
    }
    rows = [_episode(t, 0, 5, 0.0) for t in ("A", "B", "C")]
    by_rule = {rule.column: rule for rule in ranking.RANK_RULES}
    high = sorted(rows, key=ranking.rule_order(by_rule["rank_lo252"], scores))
    assert [row["ticker"] for row in high] == ["A", "C", "B"]
    low = sorted(rows, key=ranking.rule_order(by_rule["rank_deep_dip"], scores))
    assert [row["ticker"] for row in low] == ["B", "C", "A"]
    keep, drop = ranking.kept(by_rule["skip_lo252"], rows, scores)
    assert [row["ticker"] for row in drop] == ["B"]
    assert [row["ticker"] for row in keep] == ["A", "C"]


def test_rules_are_fixed_and_unique():
    columns = [rule.column for rule in ranking.RANK_RULES]
    assert len(columns) == len(set(columns)) == 8
    assert {rule.rank for rule in ranking.RANK_RULES} <= {None, *ranking.FEATURES, "trend3"}
    assert all(rule.rank or rule.skip for rule in ranking.RANK_RULES)


def test_a_ranking_that_reads_the_winner_beats_the_registered_order(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(ranking, "WARMUP_SIGNALS", 5)
    rows = []
    for day in range(0, 400, 4):
        for slot in range(14):
            good = slot % 2 == 0
            rows.append(
                _episode(
                    f"Z{slot}{day:03d}",
                    day,
                    30,
                    0.05 if good else -0.05,
                    lo252=50.0 + slot if good else 1.0 + slot,
                    sma=0.1 if good else -0.2,
                    ret126=0.2 if good else -0.3,
                )
            )
    boards = ranking.lab_boards(rows, {"w": (_day(0), _day(400))})
    whole = boards["w"]["whole"]
    base = whole["registered_order"]["slot_book"]["annualised_return"]
    trend = whole["variants"]["rank_trend3"]
    assert trend["slot_book"]["annualised_return"] > base
    assert trend["annualised_vs_registered"] > 0
    assert whole["variants"]["rank_deep_dip"]["annualised_vs_registered"] < 0
    skip = whole["variants"]["skip_trend3"]["skip"]
    assert skip["mean_difference_kept_minus_dropped"] > 0
    assert set(boards["w"]) == {
        "signal_window",
        "whole",
        "first_half",
        "second_half",
        "end_cutoffs",
    }
    assert boards["w"]["end_cutoffs"]["lo252"]["value_at_skip_line"] is not None


def _half(base: float, random_median: float, variants: dict) -> dict:
    return {
        "registered_order": {
            "slot_book": {"annualised_return": base, "random_order_median": random_median}
        },
        "variants": {
            column: {"slot_book": {"annualised_return": value}}
            for column, value in variants.items()
        },
    }


def _window(halves: tuple[dict, dict], excess: dict, gains: dict, base_excess: float = 0.0):
    return {
        "whole": {
            "registered_order": {"taken": {"matched_excess_median": base_excess}},
            "variants": {
                column: {
                    "taken": {"matched_excess_median": excess[column]},
                    "annualised_vs_registered": gains[column],
                }
                for column in excess
            },
        },
        "first_half": halves[0],
        "second_half": halves[1],
    }


def test_choice_rule_needs_every_half_both_baselines_and_the_excess():
    good = {"win": 0.12, "random_only": 0.105, "excess_low": 0.12, "tie": 0.10}
    half = _half(0.10, 0.11, good)
    gains = {"win": 0.02, "random_only": 0.005, "excess_low": 0.03, "tie": 0.0}
    excess = {"win": 0.001, "random_only": 0.001, "excess_low": -0.01, "tie": 0.0}
    boards = {
        "development": _window((half, half), excess, gains),
        "confirmation": _window((half, half), excess, {**gains, "win": 0.01}),
    }
    choice = ranking.apply_choice_rule(boards)
    assert choice["eligible"] == ["win"]
    assert choice["pick"] == "win"
    assert "not_above_random_development_first_half" in choice["failed"]["random_only"]
    assert "matched_excess_below_registered_confirmation" in choice["failed"]["excess_low"]
    assert "not_above_registered_development_first_half" in choice["failed"]["tie"]

    weak = _half(0.10, 0.09, {**good, "win": 0.095})
    boards["confirmation"]["second_half"] = weak
    assert ranking.apply_choice_rule(boards)["pick"] is None


def test_ranking_lab_needs_the_reveal_and_commits_aggregates_only(
    licensed: dict[str, Path],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(ranking, "WARMUP_SIGNALS", 3)
    repo = make_repo(tmp_path / "repo")
    paths = (licensed["build"], licensed["mid"], licensed["sharadar"])
    with pytest.raises(rehearsal.RehearsalRefused, match="development"):
        rehearsal.ranking_lab(*paths, repo_root=repo)
    rehearsal.develop(*paths, repo_root=repo)
    with pytest.raises(rehearsal.RehearsalRefused, match="not revealed"):
        rehearsal.ranking_lab(*paths, repo_root=repo)
    rehearsal.reveal(*paths, repo_root=repo)
    before = (repo / rehearsal.STORE_PATH).read_bytes()

    payload = rehearsal.ranking_lab(*paths, repo_root=repo)["store"]
    text = (repo / rehearsal.RANKING_LAB_PATH).read_text()
    assert (repo / rehearsal.STORE_PATH).read_bytes() == before
    assert payload["exploratory"] is True and payload["evidence"] is False
    assert payload["influences_live"] is False
    assert payload["windows_reproduced"] == {"development": True, "confirmation": True}
    assert set(payload["boards"]) == {"development", "confirmation"}
    for block in payload["boards"].values():
        assert set(block["whole"]["variants"]) == {r.column for r in ranking.RANK_RULES}
    for ticker in NAMES:
        assert ticker not in text
    assert rehearsal.privacy_violations(payload, NAMES) == []
    assert set(payload["choice"]) == {"eligible", "pick", "failed"}
    table = rehearsal.ranking_lab_table(payload)
    assert len(table) == 2 * (1 + len(ranking.RANK_RULES))
    assert rehearsal.TITLE_RANKING_LAB in {row["title"] for row in rehearsal.findings(repo)}

    store = json.loads(before)
    store["licensed_data"]["deleted_at"] = "2026-12-01T00:00:00+00:00"
    (repo / rehearsal.STORE_PATH).write_text(json.dumps(store))
    with pytest.raises(rehearsal.RehearsalRefused, match="deleted"):
        rehearsal.ranking_lab(*paths, repo_root=repo)
