"""Tests for scratch fragments in deferred-ideas store."""

from pathlib import Path

from value_investor.deferred_ideas import (
    add_fragment,
    add_idea,
    list_open_fragments,
    load_store,
    render_markdown,
    set_fragment_status,
)


def test_add_fragment_dedupes_open_text(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    first, created1 = add_fragment(
        "Half-formed counterfactual thought",
        tags=["counterfactual"],
        store_path=store,
    )
    second, created2 = add_fragment(
        "Half-formed counterfactual thought",
        store_path=store,
    )
    assert created1 is True
    assert created2 is False
    assert first["id"] == second["id"]
    assert len(list_open_fragments(store_path=store)) == 1


def test_render_markdown_includes_fragments(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    add_fragment("Watch grace knobs until cohorts close", store_path=store)
    text = render_markdown(store_path=store)
    assert "Open fragments" in text
    assert "Watch grace knobs" in text


def test_fragment_status_marks_done(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    fragment, _ = add_fragment("Promote me later", store_path=store)
    updated = set_fragment_status(fragment["id"], "done", store_path=store)
    assert updated["status"] == "done"
    assert list_open_fragments(store_path=store) == []


def test_fragments_and_ideas_share_store(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    add_idea(
        title="Full defer",
        summary="Ready idea",
        category="later",
        store_path=store,
    )
    add_fragment("Scratch only", store_path=store)
    payload = load_store(store)
    assert len(payload.get("ideas") or []) == 1
    assert len(payload.get("fragments") or []) == 1
