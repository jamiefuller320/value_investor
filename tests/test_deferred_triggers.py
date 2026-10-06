"""Structured deferred-idea triggers and the daily ops-monitor check."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from value_investor.deferred_ideas import add_idea, load_store, render_markdown, set_idea_trigger
from value_investor.deferred_ideas_cli import main as defer_main
from value_investor.deferred_triggers import (
    FROZEN_TITLE,
    MET_TITLE,
    MISSING,
    UNREADABLE_TITLE,
    check_deferred_triggers,
    evaluate_trigger,
    ops_findings_from_trigger_check,
    resolve_path,
    validate_trigger,
)
from value_investor.ops_monitor import check_deferred_triggers as ops_check

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
REVIEW = "docs/data/paper_automation/learning_tracks_review.json"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _repo(tmp_path: Path, *, cost_drag: float = 0.018) -> Path:
    _write(
        tmp_path / REVIEW,
        {"reviews": {"ai_judgment_fair": {"metrics": {"epoch": {"cost_drag": cost_drag}}}}},
    )
    _write(
        tmp_path / "docs/data/assessment_scoreboard.json",
        {"tracks": [{"track_id": "ai_judgment_fair", "statistics": {"verdict": "noise"}}]},
    )
    _write(
        tmp_path / "docs/data/paper_automation/assessment_model.json",
        {
            "frozen_tracks": {
                "still_in_buy_set": {"frozen_at": "2026-10-06T08:56:59+00:00"},
                "rules": {"frozen_at": "2026-10-06T08:56:59+00:00"},
            }
        },
    )
    return tmp_path


def _cost_trigger(threshold: float = 0.01) -> dict:
    return {
        "all": [
            {
                "file": REVIEW,
                "path": "reviews.ai_judgment_fair.metrics.epoch.cost_drag",
                "op": ">",
                "value": threshold,
            }
        ]
    }


def _idea(idea_id: str, **extra) -> dict:
    return {
        "id": idea_id,
        "title": f"Idea {idea_id}",
        "status": "open",
        "added_at": "2026-09-01T00:00:00+00:00",
        **extra,
    }


@pytest.mark.parametrize(
    ("trigger", "fragment"),
    [
        ({}, "exactly one"),
        ({"all": []}, "non-empty"),
        ({"all": [{"file": "x.json", "path": "a", "op": "~", "value": 1}]}, "op must"),
        ({"all": [{"file": "x.json", "path": "a", "op": ">"}]}, "needs 'value'"),
        ({"all": [{"file": "/etc/x.json", "path": "a", "op": "exists"}]}, "repo-relative"),
        ({"any": [{"on_or_after": "soon"}]}, "YYYY-MM-DD"),
        ({"all": [{"path": "a", "op": "exists"}]}, "needs 'file'"),
    ],
)
def test_validate_trigger_rejects_bad_shapes(trigger: dict, fragment: str):
    problems = validate_trigger(trigger)
    assert problems and any(fragment in problem for problem in problems)


def test_resolve_path_supports_list_selectors():
    payload = {"tracks": [{"track_id": "a", "marks": 3}, {"track_id": "b", "marks": 9}]}
    assert resolve_path(payload, "tracks[track_id=b].marks") == 9
    assert resolve_path(payload, "tracks[track_id=c].marks") is MISSING
    assert resolve_path(payload, "tracks.marks") is MISSING


def test_evaluate_trigger_states(tmp_path: Path):
    repo = _repo(tmp_path)
    today = date(2026, 10, 6)
    assert evaluate_trigger(_cost_trigger(), repo_root=repo, today=today)["state"] == "met"
    assert evaluate_trigger(_cost_trigger(0.05), repo_root=repo, today=today)["state"] == "unmet"

    missing = {"all": [{"file": "docs/data/nope.json", "path": "a", "op": "exists"}]}
    result = evaluate_trigger(missing, repo_root=repo, today=today)
    assert result["state"] == "unknown"
    assert "not found" in result["reasons"][0]

    verdict = {
        "all": [
            {
                "file": "docs/data/assessment_scoreboard.json",
                "path": "tracks[track_id=ai_judgment_fair].statistics.verdict",
                "op": "==",
                "value": "positive",
            }
        ]
    }
    assert evaluate_trigger(verdict, repo_root=repo, today=today)["state"] == "unmet"

    non_numeric = {
        "all": [
            {
                "file": "docs/data/assessment_scoreboard.json",
                "path": "tracks[track_id=ai_judgment_fair].statistics.verdict",
                "op": ">",
                "value": 1,
            }
        ]
    }
    assert evaluate_trigger(non_numeric, repo_root=repo, today=today)["state"] == "unknown"

    either = {"any": [{"on_or_after": "2026-12-01"}, *_cost_trigger()["all"]]}
    assert evaluate_trigger(either, repo_root=repo, today=today)["state"] == "met"
    both = {"all": [{"on_or_after": "2026-12-01"}, *_cost_trigger()["all"]]}
    assert evaluate_trigger(both, repo_root=repo, today=today)["state"] == "unmet"


def test_check_keeps_first_met_and_unknown_since(tmp_path: Path):
    repo = _repo(tmp_path)
    store = {
        "ideas": [
            _idea("L1", trigger=_cost_trigger()),
            _idea(
                "L2", trigger={"all": [{"file": "docs/data/x.json", "path": "a", "op": "exists"}]}
            ),
            _idea("L3", trigger=_cost_trigger(0.5)),
            _idea("L4", status="drop", trigger=_cost_trigger()),
            _idea("L5"),
        ]
    }
    first = check_deferred_triggers(store, repo_root=repo, now=NOW)
    assert [row["id"] for row in first["met"]] == ["L1"]
    assert [row["id"] for row in first["unknown"]] == ["L2"]
    assert first["unmet"] == ["L3"]
    assert first["with_trigger"] == 3
    assert first["open_ideas"] == 4

    later = NOW + timedelta(days=3)
    second = check_deferred_triggers(store, repo_root=repo, previous=first, now=later)
    assert second["met"][0]["first_met_at"] == NOW.isoformat()
    assert second["unknown"][0]["unknown_since"] == NOW.isoformat()


def test_frozen_mentions_skip_bare_words_and_ideas_edited_after_freeze(tmp_path: Path):
    repo = _repo(tmp_path)
    store = {
        "ideas": [
            _idea("N1", revisit_when="still_in_buy_set twin shows churn"),
            _idea(
                "N2",
                revisit_when="primary marks (still_in_buy_set frozen 2026-10-06)",
                updated_at="2026-10-06T19:27:35+00:00",
            ),
            _idea("N3", revisit_when="archive labs replay overlay rules"),
            _idea("N4", revisit_when="ai_judgment_fair beats control"),
        ]
    }
    payload = check_deferred_triggers(store, repo_root=repo, now=NOW)
    assert payload["frozen_mentions"] == [
        {"id": "N1", "title": "Idea N1", "tracks": ["still_in_buy_set"]}
    ]


def test_findings_respect_unknown_grace(tmp_path: Path):
    repo = _repo(tmp_path)
    store = {
        "ideas": [
            _idea("L1", trigger=_cost_trigger()),
            _idea(
                "L2", trigger={"all": [{"file": "docs/data/x.json", "path": "a", "op": "exists"}]}
            ),
            _idea("L3", trigger={"all": [{"file": REVIEW, "path": "a", "op": "~"}]}),
            _idea("N1", revisit_when="still_in_buy_set twin shows churn"),
        ]
    }
    payload = check_deferred_triggers(store, repo_root=repo, now=NOW)
    titles = {row["title"]: row for row in ops_findings_from_trigger_check(payload, now=NOW)}
    assert set(titles) == {MET_TITLE, UNREADABLE_TITLE, FROZEN_TITLE}
    assert "L1 (2026-10-06)" in titles[MET_TITLE]["summary"]
    assert "L3" in titles[UNREADABLE_TITLE]["summary"]
    assert "L2" not in titles[UNREADABLE_TITLE]["summary"]

    later = NOW + timedelta(days=8)
    aged = check_deferred_triggers(store, repo_root=repo, previous=payload, now=later)
    unreadable = next(
        row
        for row in ops_findings_from_trigger_check(aged, now=later)
        if row["title"] == UNREADABLE_TITLE
    )
    assert "L2" in unreadable["summary"]


def test_ops_check_persists_and_is_warn_only(tmp_path: Path):
    repo = _repo(tmp_path)
    store_path = repo / "docs/deferred-ideas.json"
    _write(store_path, {"ideas": [_idea("L1", trigger=_cost_trigger())], "fragments": []})
    result_path = repo / "docs/data/deferred_trigger_check.json"

    findings = ops_check(store_path=store_path, result_path=result_path, repo_root=repo, now=NOW)
    assert [row.title for row in findings] == [MET_TITLE]
    assert all(row.auto_fixable is False and row.severity == "warn" for row in findings)
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["met"][0]["id"] == "L1"

    assert ops_check(store_path=repo / "missing.json", result_path=result_path) == []


def test_store_helpers_and_cli(tmp_path: Path, capsys):
    store_path = tmp_path / "ideas.json"
    markdown = tmp_path / "review.md"
    with pytest.raises(ValueError, match="Invalid trigger"):
        add_idea(title="Bad", summary="s", store_path=store_path, trigger={"all": []})

    idea, _ = add_idea(
        title="Cost drag",
        summary="s",
        revisit_when="epoch cost drag above 1%",
        store_path=store_path,
        trigger=_cost_trigger(),
    )
    assert load_store(store_path)["ideas"][0]["trigger"] == _cost_trigger()
    assert "_(machine-checked)_" in render_markdown(store_path=store_path)

    set_idea_trigger(idea["id"], None, store_path=store_path)
    assert "trigger" not in load_store(store_path)["ideas"][0]

    rc = defer_main(
        [
            "--store",
            str(store_path),
            "--markdown",
            str(markdown),
            "set-trigger",
            idea["id"],
            "--trigger",
            json.dumps({"any": [{"on_or_after": "2026-01-01"}]}),
            "--revisit-when",
            "New year",
        ]
    )
    assert rc == 0
    row = load_store(store_path)["ideas"][0]
    assert row["revisit_when"] == "New year"
    assert row["trigger"] == {"any": [{"on_or_after": "2026-01-01"}]}

    capsys.readouterr()
    assert defer_main(["--store", str(store_path), "triggers", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["met"][0]["id"] == idea["id"]
