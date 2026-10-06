"""Merge-safe deferred IDs: rebase a branch's new entries onto main's numbering."""

import json
import subprocess
from pathlib import Path

from value_investor.deferred_ideas_cli import main as defer_main
from value_investor.deferred_ideas_rebase import (
    check_store_ids,
    rebase_store,
    rewrite_id_references,
)


def _idea(idea_id: str, title: str, **extra) -> dict:
    return {"id": idea_id, "title": title, "summary": "s", "status": "open", **extra}


def _store(ideas: list[dict], fragments: list[dict] | None = None) -> dict:
    return {"version": 1, "ideas": ideas, "fragments": fragments or [], "sessions_mined": []}


def test_branch_collision_is_renumbered_after_base():
    base = _store([_idea("L1", "Old"), _idea("L2", "Main new"), _idea("N1", "Park")])
    branch = _store([_idea("L1", "Old"), _idea("L2", "Branch new"), _idea("N2", "Branch park")])
    merged, renames = rebase_store(base, branch)
    assert renames == {"L2": "L3"}
    assert [(i["id"], i["title"]) for i in merged["ideas"]] == [
        ("L1", "Old"),
        ("L2", "Main new"),
        ("N1", "Park"),
        ("L3", "Branch new"),
        ("N2", "Branch park"),
    ]
    assert check_store_ids(merged, base) == []


def test_same_title_on_both_sides_is_not_duplicated():
    base = _store([_idea("L1", "Old"), _idea("L2", "Shared idea")])
    branch = _store([_idea("L1", "Old"), _idea("L3", "Shared  idea!")])
    merged, renames = rebase_store(base, branch)
    assert renames == {"L3": "L2"}
    assert len(merged["ideas"]) == 2


def test_newer_branch_status_change_wins_and_base_id_kept():
    base = _store([_idea("L1", "Old")])
    branch = _store([_idea("L1", "Old", status="done", updated_at="2026-10-06T10:00:00+00:00")])
    merged, renames = rebase_store(base, branch)
    assert renames == {}
    assert merged["ideas"][0]["status"] == "done"


def test_base_status_change_is_not_reverted_by_stale_branch():
    base = _store([_idea("L1", "Old", status="drop", updated_at="2026-10-06T10:00:00+00:00")])
    branch = _store([_idea("L1", "Old")])
    merged, _ = rebase_store(base, branch)
    assert merged["ideas"][0]["status"] == "drop"


def test_fragment_collisions_renumber_within_day():
    base = _store([], [{"id": "frag-20261006-01", "text": "main thought"}])
    branch = _store([], [{"id": "frag-20261006-01", "text": "branch thought"}])
    merged, renames = rebase_store(base, branch)
    assert renames == {"frag-20261006-01": "frag-20261006-02"}
    assert [f["id"] for f in merged["fragments"]] == ["frag-20261006-01", "frag-20261006-02"]


def test_check_flags_duplicates_and_retitled_base_ids():
    base = _store([_idea("L1", "Old"), _idea("L2", "Main")])
    bad = _store([_idea("L1", "Old"), _idea("L2", "Branch"), _idea("L2", "Other")])
    problems = check_store_ids(bad, base)
    assert any("duplicate idea id L2" in p for p in problems)
    assert any("L2 is 'Branch'" in p for p in problems)


def test_rewrite_only_touches_branch_lines_and_swaps_simultaneously():
    text = "main cites L2 here\nbranch cites L2 and L3 (not L23 or L2x)\n"
    renames = {"L2": "L3", "L3": "L4"}
    out = rewrite_id_references(text, renames, {"branch cites L2 and L3 (not L23 or L2x)"})
    assert out == "main cites L2 here\nbranch cites L3 and L4 (not L23 or L2x)\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _write(repo: Path, store: dict) -> None:
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "deferred-ideas.json").write_text(json.dumps(store, indent=2) + "\n")


def test_rebase_ids_cli_resolves_a_real_merge_conflict(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _write(repo, _store([_idea("L1", "Old")]))
    (repo / "docs" / "note.md").write_text("old note cites L1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")

    _git(repo, "checkout", "-qb", "feature")
    _write(repo, _store([_idea("L1", "Old"), _idea("L2", "Branch idea")]))
    (repo / "docs" / "note.md").write_text("old note cites L1\nbranch parks L2\n")
    _git(repo, "commit", "-qam", "branch defer")

    _git(repo, "checkout", "-q", "main")
    _write(repo, _store([_idea("L1", "Old"), _idea("L2", "Main idea")]))
    _git(repo, "commit", "-qam", "main defer")

    _git(repo, "checkout", "-q", "feature")
    merge = subprocess.run(["git", "merge", "main"], cwd=repo, capture_output=True, text=True)
    assert merge.returncode != 0

    monkeypatch.chdir(repo)
    assert defer_main(["rebase-ids", "--base", "main", "--apply"]) == 0
    store = json.loads((repo / "docs" / "deferred-ideas.json").read_text())
    assert [(i["id"], i["title"]) for i in store["ideas"]] == [
        ("L1", "Old"),
        ("L2", "Main idea"),
        ("L3", "Branch idea"),
    ]
    assert (repo / "docs" / "note.md").read_text() == "old note cites L1\nbranch parks L3\n"
    assert (repo / "docs" / "deferred-review.md").exists()
    assert defer_main(["check-ids", "--base", "main"]) == 0
