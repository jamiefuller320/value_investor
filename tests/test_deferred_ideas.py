"""Tests for deferred-ideas store and markdown render."""

from pathlib import Path

from value_investor.deferred_ideas import add_idea, load_store, render_markdown, write_markdown


def test_add_idea_dedupes_by_title(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    md = tmp_path / "deferred-review.md"
    first, created1 = add_idea(
        title="Evolutionary genomes",
        summary="Stage 2 after decision review",
        category="later",
        revisit_when="Many tens of weekly runs",
        store_path=store,
    )
    second, created2 = add_idea(
        title="Evolutionary genomes",
        summary="Different summary should not duplicate",
        category="later",
        store_path=store,
    )
    assert created1 is True
    assert created2 is False
    assert first["id"] == second["id"]
    assert len(load_store(store)["ideas"]) == 1
    write_markdown(store_path=store, markdown_path=md)
    text = md.read_text(encoding="utf-8")
    assert "Evolutionary genomes" in text
    assert "Auto-generated" in text


def test_render_includes_not_now_and_security(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    add_idea(
        title="Widen universe first",
        summary="Not enough weekly periods yet",
        category="not_now",
        section="not_now",
        store_path=store,
    )
    add_idea(
        title="Rotate API key",
        summary="May still be in git history",
        category="security",
        section="security",
        store_path=store,
    )
    text = render_markdown(store_path=store)
    assert "Not relevant now" in text
    assert "Widen universe first" in text
    assert "Rotate API key" in text
