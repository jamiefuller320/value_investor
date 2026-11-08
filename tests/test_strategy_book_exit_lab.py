"""Exit lab: trend-led exit variants on the US development window (exploratory)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_strategy_book_us_rehearsal import NAMES, licensed, make_repo  # noqa: F401

from value_investor import strategy_book_exit_lab as lab
from value_investor import strategy_book_us_rehearsal as rehearsal
from value_investor import strategy_book_us_tape as tape
from value_investor.strategy_book_rules import COLUMN_PRIMARY, EXIT_FAIL_TO_LAUNCH


def test_trailing_rule_sells_at_the_drop_from_the_peak():
    rule = lab.LabExit("t", "trail", 0.15, "none")
    assert lab.launched_signal(rule, close=86.0, peak=100.0, closes=[100.0, 86.0]) is None
    assert lab.launched_signal(rule, close=85.0, peak=100.0, closes=[100.0, 85.0]) == lab.EXIT_TRAIL


def test_sma_and_channel_low_rules_read_only_past_closes():
    sma = lab.LabExit("s", "sma", 3, "none")
    assert lab.launched_signal(sma, close=9.0, peak=12.0, closes=[9.0, 9.0]) is None
    assert (
        lab.launched_signal(sma, close=9.0, peak=12.0, closes=[12.0, 12.0, 9.0]) == lab.EXIT_TREND
    )
    low = lab.LabExit("l", "low", 3, "none")
    assert lab.launched_signal(low, close=10.0, peak=12.0, closes=[10.0, 11.0, 12.0, 10.0]) is None
    assert (
        lab.launched_signal(low, close=9.9, peak=12.0, closes=[10.0, 11.0, 12.0, 9.9])
        == lab.EXIT_CHANNEL_LOW
    )


def test_unlaunched_rules():
    deadline = lab.LabExit("d", "trail", 0.15, "deadline", 63)
    assert lab.unlaunched_signal(deadline, index=62, close=90.0, closes=[90.0]) is None
    assert (
        lab.unlaunched_signal(deadline, index=63, close=90.0, closes=[90.0]) == EXIT_FAIL_TO_LAUNCH
    )
    new_low = lab.LabExit("n", "trail", 0.15, "new_low", 3)
    history = [100.0, 95.0, 97.0]
    assert lab.unlaunched_signal(new_low, index=0, close=90.0, closes=[*history, 90.0]) is None
    assert lab.unlaunched_signal(new_low, index=1, close=95.0, closes=[*history, 95.0]) is None
    assert (
        lab.unlaunched_signal(new_low, index=1, close=94.9, closes=[*history, 94.9])
        == lab.EXIT_NEW_LOW
    )
    buffered = lab.LabExit("b", "trail", 0.15, "new_low", 3, 0.05)
    assert lab.unlaunched_signal(buffered, index=1, close=91.0, closes=[*history, 91.0]) is None
    assert (
        lab.unlaunched_signal(buffered, index=1, close=90.0, closes=[*history, 90.0])
        == lab.EXIT_NEW_LOW
    )
    none = lab.LabExit("x", "trail", 0.15, "none")
    assert lab.unlaunched_signal(none, index=500, close=1.0, closes=[100.0, 1.0]) is None


def test_variants_are_fixed_and_unique():
    columns = [rule.column for rule in lab.LAB_EXITS]
    assert len(columns) == len(set(columns)) == 8
    assert all(column.startswith(lab.LAB_PREFIX) for column in columns)
    assert all(rule.describe()["time_cap"] is None for rule in lab.LAB_EXITS)
    with pytest.raises(ValueError):
        lab.LabExit("bad", "stop", 0.1, "none")


def test_halves_split_at_the_calendar_midpoint():
    assert lab.halves_of("2000-01-01", "2012-12-31") == (
        ("2000-01-01", "2006-07-02"),
        ("2006-07-03", "2012-12-31"),
    )


def _walk(licensed: dict[str, Path], tmp_path: Path, exits: tuple) -> list[dict]:  # noqa: F811
    registration = json.loads(
        (make_repo(tmp_path / "repo") / rehearsal.REGISTRATION_PATH).read_text()
    )
    last = registration["windows"]["development"]["last_signal"]
    inputs = tape.build_inputs(
        tape.BuildDir(licensed["build"], "sp500"),
        tape.BuildDir(licensed["mid"], "midcap"),
        licensed["sharadar"],
        registration,
    )
    options = rehearsal.dataclasses.replace(
        rehearsal.walk_options(registration, last), exit_lab=exits
    )
    return rehearsal.sbo.walk_book(inputs.with_variant(rehearsal.BASELINE), options=options)[
        "episodes"
    ]


def test_lab_columns_do_not_change_the_registered_columns(
    licensed: dict[str, Path],  # noqa: F811
    tmp_path: Path,
):
    plain = _walk(licensed, tmp_path / "a", ())
    with_lab = _walk(licensed, tmp_path / "b", lab.LAB_EXITS)
    registered = [e for e in with_lab if not e["column"].startswith(lab.LAB_PREFIX)]
    assert json.dumps(registered, default=str) == json.dumps(plain, default=str)
    primary = {(e["ticker"], e["signal_session"]) for e in plain if e["column"] == COLUMN_PRIMARY}
    for rule in lab.LAB_EXITS:
        rows = [e for e in with_lab if e["column"] == rule.column]
        assert {(e["ticker"], e["signal_session"]) for e in rows} == primary
        assert all(e["exit_reason"] != "time_cap" for e in rows)


def test_exit_lab_commits_development_aggregates_only(
    licensed: dict[str, Path],  # noqa: F811
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    paths = (licensed["build"], licensed["mid"], licensed["sharadar"])
    with pytest.raises(rehearsal.RehearsalRefused, match="development"):
        rehearsal.exit_lab(*paths, repo_root=repo)
    rehearsal.develop(*paths, repo_root=repo)
    before = (repo / rehearsal.STORE_PATH).read_bytes()

    payload = rehearsal.exit_lab(*paths, repo_root=repo)["store"]
    text = (repo / rehearsal.EXIT_LAB_PATH).read_text()
    assert (repo / rehearsal.STORE_PATH).read_bytes() == before
    assert payload["exploratory"] is True and payload["evidence"] is False
    assert payload["development_reproduced"] is True
    assert payload["signal_window"] == {"first": "2000-01-01", "last": "2000-12-31"}
    whole = payload["boards"]["whole"]
    assert set(whole["variants"]) == {rule.column for rule in lab.LAB_EXITS}
    for board in whole["variants"].values():
        assert board["mature"] == whole["primary"]["mature"]
        assert board["paired"]["n"] == whole["primary"]["mature"]
    assert set(payload["boards"]) == {"whole", "first_half", "second_half"}
    for ticker in NAMES:
        assert ticker not in text
    assert rehearsal.privacy_violations(payload, NAMES) == []
    table = rehearsal.exit_lab_table(payload)
    assert [row["column"] for row in table][0] == COLUMN_PRIMARY
    assert len(table) == 1 + len(lab.LAB_EXITS)
    assert set(payload["choice"]) == {"eligible", "pick", "failed"}

    titles = {row["title"] for row in rehearsal.findings(repo)}
    assert rehearsal.TITLE_EXIT_LAB in titles

    store = json.loads(before)
    store["licensed_data"]["deleted_at"] = "2026-12-01T00:00:00+00:00"
    (repo / rehearsal.STORE_PATH).write_text(json.dumps(store))
    with pytest.raises(rehearsal.RehearsalRefused, match="deleted"):
        rehearsal.exit_lab(*paths, repo_root=repo)


def _half(primary_capital: float, variants: dict) -> dict:
    return {
        "primary": {"capital_days_return": primary_capital},
        "variants": {
            column: {
                "capital_days_return": capital,
                "paired": {"mean_difference_vs_primary": mean},
            }
            for column, (capital, mean) in variants.items()
        },
    }


def test_choice_rule_needs_both_halves_and_the_excess():
    boards = {
        "whole": {
            "primary": {"matched_excess_median": 0.0},
            "variants": {
                "lab_a": {"capital_days_return": 0.12, "matched_excess_median": 0.001},
                "lab_b": {"capital_days_return": 0.20, "matched_excess_median": 0.002},
                "lab_c": {"capital_days_return": 0.30, "matched_excess_median": -0.01},
                "lab_d": {"capital_days_return": 0.10, "matched_excess_median": 0.0},
            },
        },
        "first_half": _half(
            0.05,
            {
                "lab_a": (0.08, 0.01),
                "lab_b": (0.09, 0.02),
                "lab_c": (0.2, 0.03),
                "lab_d": (0.07, 0.01),
            },
        ),
        "second_half": _half(
            0.05,
            {
                "lab_a": (0.07, 0.01),
                "lab_b": (0.04, 0.02),
                "lab_c": (0.2, 0.03),
                "lab_d": (0.06, 0.0),
            },
        ),
    }
    out = lab.apply_choice_rule(boards)
    assert out["eligible"] == ["lab_a"]
    assert out["pick"] == "lab_a"
    assert out["failed"]["lab_b"] == ["capital_days_not_above_primary_second_half"]
    assert out["failed"]["lab_c"] == ["matched_excess_below_primary"]
    assert out["failed"]["lab_d"] == ["paired_mean_not_above_zero_second_half"]
    boards["whole"]["variants"].pop("lab_a")
    assert lab.apply_choice_rule(boards)["pick"] is None
