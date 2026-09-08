"""Tests for the supervised engineering-agent prompt."""

from __future__ import annotations

from pathlib import Path

from value_investor.engineering_agent import _build_engineering_prompt
from value_investor.engineering_tasks import EngineeringTask


def test_engineering_prompt_forbids_incidental_research_artifacts():
    task = EngineeringTask(
        id="eng-20260908-09",
        area="scoring",
        title="Honour FCF action-note enforcement for IMB.L",
        summary="Wire note to overlay",
        priority="medium",
        priority_score=70.0,
        source="so_what_closure",
        allowed_paths=["src/value_investor/summary.py", "tests/test_summary.py"],
    )
    prompt = _build_engineering_prompt(
        task=task,
        task_path=Path("output/engineering_task_eng-20260908-09.json"),
        output_dir=Path("output"),
    )
    assert "docs/research/" in prompt
    assert "screening_snapshot.json" in prompt
    assert "peer_model_pass_table.json" in prompt
    assert "allowed_paths" in prompt
