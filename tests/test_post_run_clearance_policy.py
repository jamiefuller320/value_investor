"""Canonical ops policy doc for post-run persistent weaknesses."""

from pathlib import Path

POLICY = Path("docs/ops/post-run-improvement-clearance.md")


def test_post_run_improvement_clearance_policy_exists():
    text = POLICY.read_text(encoding="utf-8")
    assert "Persistent weaknesses ≠ engineering backlog" in text
    assert "Lane A — Ingest factory" in text
    assert "Lane B — Engineering queue" in text
    assert "Lane C — Narrative refresh" in text
    assert "compile-cap drain" in text
    assert "so-what" in text
    assert "run-post-run-clearance" in text


def test_agents_md_references_clearance_policy():
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    assert "post-run-improvement-clearance.md" in agents
    assert "three-lane model" in agents
