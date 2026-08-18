"""Load and validate the human tasks checklist for dashboard + ops."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CHECKLIST_PATH = Path("docs/human_tasks_checklist.json")
_REQUIRED_TASK_KEYS = ("id", "title", "summary", "automated", "doc_path")
_REQUIRED_SECTION_KEYS = ("id", "title", "cadence", "tasks")


def load_human_tasks_checklist(path: Path | None = None) -> dict[str, Any]:
    checklist_path = path or DEFAULT_CHECKLIST_PATH
    payload = json.loads(checklist_path.read_text(encoding="utf-8"))
    errors = validate_human_tasks_checklist(payload)
    if errors:
        raise ValueError("; ".join(errors))
    return payload


def validate_human_tasks_checklist(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["checklist root must be an object"]
    for key in ("version", "title", "sections", "repo_docs_base"):
        if key not in payload:
            errors.append(f"missing top-level key: {key}")
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("sections must be a non-empty list")
        return errors
    seen_ids: set[str] = set()
    for section_index, section in enumerate(sections):
        if not isinstance(section, dict):
            errors.append(f"section[{section_index}] must be an object")
            continue
        for key in _REQUIRED_SECTION_KEYS:
            if key not in section:
                errors.append(f"section[{section_index}] missing key: {key}")
        tasks = section.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            errors.append(f"section[{section_index}] tasks must be a non-empty list")
            continue
        for task_index, task in enumerate(tasks):
            if not isinstance(task, dict):
                errors.append(f"section[{section_index}].tasks[{task_index}] must be an object")
                continue
            for key in _REQUIRED_TASK_KEYS:
                if key not in task:
                    errors.append(
                        f"section[{section_index}].tasks[{task_index}] missing key: {key}"
                    )
            task_id = str(task.get("id") or "")
            if task_id:
                if task_id in seen_ids:
                    errors.append(f"duplicate task id: {task_id}")
                seen_ids.add(task_id)
    return errors


def doc_url_for_task(task: dict[str, Any], *, repo_docs_base: str) -> str | None:
    doc_path = task.get("doc_path")
    if not doc_path:
        return None
    base = str(repo_docs_base).rstrip("/")
    path = str(doc_path).lstrip("/")
    anchor = task.get("doc_anchor")
    url = f"{base}/{path}"
    if anchor:
        url = f"{url}#{anchor}"
    return url
