"""Smoke checks for the progress-report GitHub Actions workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/progress-report.yml")


def test_progress_report_workflow_shape() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    assert data["name"] == "Progress report"
    # PyYAML coerces the key `on` to boolean True.
    on = data["on"] if "on" in data else data[True]
    assert "workflow_dispatch" in on
    assert on["workflow_dispatch"]["inputs"]["force"]["type"] == "boolean"
    assert on["repository_dispatch"]["types"] == ["progress-report"]
    assert data["permissions"]["contents"] == "write"
    assert data["permissions"]["actions"] == "write"

    assert "ftse-progress-report build --write" in text
    assert "docs/data/progress_report.json" in text
    assert "docs/data/progress_report.md" in text
    assert "docs/data/project_progress.json" in text
    assert "pages.yml" in text
    assert "[skip ci]" in text

    # Free-form inputs must not be interpolated into shell `run:` lines.
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("run:"):
            assert "${{" not in stripped
