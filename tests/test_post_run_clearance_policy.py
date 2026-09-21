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


def test_run_post_run_clearance_cli_exposes_max_tasks():
    """Regression: analysis-review clearance step crashed without --max-tasks (2026-09-21)."""
    from value_investor.engineering_cli import main

    # argparse exits 0 on --help; capture that --max-tasks is registered.
    import io
    import sys
    from contextlib import redirect_stdout

    buf = io.StringIO()
    old = sys.argv
    try:
        sys.argv = ["ftse-engineering", "run-post-run-clearance", "--help"]
        with redirect_stdout(buf):
            try:
                main()
            except SystemExit as exc:
                assert exc.code in (0, None)
    finally:
        sys.argv = old
    help_text = buf.getvalue()
    assert "--max-tasks" in help_text
