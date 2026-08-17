"""Guardrails for agent inspection defaults (token efficiency)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BULK_PATHS = [
    "docs/data/library/",
    "docs/data/research/",
    "docs/data/charts/",
    "docs/data/archive/",
    "docs/data/history/",
    "docs/data/research_director_worker/",
    "docs/data/paper_automation/",
    "docs/data/latest.json",
]

# Ops/state files agents must keep discoverable / readable by name.
OPS_FILES_NOT_IGNORED = [
    "docs/data/engineering_tasks.json",
    "docs/data/automation.json",
    "docs/data/ops_status.json",
]


def test_cursorindexingignore_lists_bulk_artifacts_only():
    path = ROOT / ".cursorindexingignore"
    text = path.read_text(encoding="utf-8")
    assert ".cursorignore" not in text or "Do NOT move these to .cursorignore" in text
    for entry in BULK_PATHS:
        assert entry in text, f"missing bulk path: {entry}"
    for ops in OPS_FILES_NOT_IGNORED:
        assert ops not in text, f"ops path must stay readable/indexed: {ops}"
    assert not (ROOT / ".cursorignore").exists()


def test_agents_md_documents_inspection_and_defer_defaults():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Codebase inspection" in text
    assert "ftse-defer list" in text
    assert ".cursorindexingignore" in text
    for entry in ("docs/data/library/", "docs/data/research/"):
        assert entry in text


def test_cursor_rules_cover_inspection_and_defer():
    rules = ROOT / ".cursor" / "rules"
    inspection = (rules / "codebase-inspection.mdc").read_text(encoding="utf-8")
    defer = (rules / "deferred-ideas.mdc").read_text(encoding="utf-8")
    assert "alwaysApply: true" in inspection
    assert "docs/data/library/" in inspection
    assert "ftse-defer list" in defer or "ftse-defer add" in defer
    assert "deferred-ideas.json" in defer
