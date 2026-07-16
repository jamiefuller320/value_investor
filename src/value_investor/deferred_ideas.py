"""Append-only store for parked / later ideas (periodic review)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Category = Literal["not_now", "later", "security", "both"]
Status = Literal["open", "done", "drop", "now"]

DEFAULT_STORE = Path("docs/deferred-ideas.json")
DEFAULT_MARKDOWN = Path("docs/deferred-review.md")

SECTION_LABELS = {
    "not_now": "Not relevant now (do not start yet)",
    "learning": "Learning & simulation",
    "universe": "Universe & data",
    "research": "Research & portfolio product",
    "ops": "Ops / reliability",
    "security": "Security / hygiene follow-ups",
}

CATEGORY_TO_SECTION = {
    "not_now": "not_now",
    "later": "learning",
    "security": "security",
    "both": "learning",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def load_store(path: Path = DEFAULT_STORE) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "updated_at": _utcnow(),
            "sessions_mined": [],
            "ideas": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def save_store(store: dict[str, Any], path: Path = DEFAULT_STORE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = _utcnow()
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def find_idea_by_title(store: dict[str, Any], title: str) -> dict[str, Any] | None:
    needle = _norm_title(title)
    for idea in store.get("ideas") or []:
        if _norm_title(str(idea.get("title") or "")) == needle:
            return idea
    return None


def _next_id(store: dict[str, Any], category: str) -> str:
    prefix = {"not_now": "N", "later": "L", "both": "L", "security": "S"}.get(category, "L")
    numbers: list[int] = []
    for idea in store.get("ideas") or []:
        idea_id = str(idea.get("id") or "")
        if idea_id.startswith(prefix) and idea_id[1:].isdigit():
            numbers.append(int(idea_id[1:]))
    return f"{prefix}{(max(numbers) if numbers else 0) + 1}"


def add_idea(
    *,
    title: str,
    summary: str,
    category: Category = "later",
    revisit_when: str = "",
    tags: list[str] | None = None,
    section: str | None = None,
    source: str = "",
    status: Status = "open",
    store_path: Path = DEFAULT_STORE,
    allow_duplicate: bool = False,
) -> tuple[dict[str, Any], bool]:
    """
    Append an idea to the store.

    Returns (idea, created). If a matching open title exists and allow_duplicate
    is False, returns the existing idea and created=False.
    """
    title = title.strip()
    summary = summary.strip()
    if not title or not summary:
        raise ValueError("title and summary are required")
    if category not in {"not_now", "later", "security", "both"}:
        raise ValueError(f"Unknown category: {category}")

    store = load_store(store_path)
    existing = find_idea_by_title(store, title)
    if existing and not allow_duplicate and existing.get("status", "open") == "open":
        return existing, False

    idea = {
        "id": _next_id(store, category),
        "category": category if category != "both" else "later",
        "section": section or CATEGORY_TO_SECTION.get(category, "learning"),
        "title": title,
        "summary": summary,
        "revisit_when": revisit_when.strip(),
        "tags": tags or [],
        "status": status,
        "source": source.strip(),
        "added_at": _utcnow(),
    }
    store.setdefault("ideas", []).append(idea)
    save_store(store, store_path)
    return idea, True


def set_idea_status(
    idea_id: str,
    status: Status,
    *,
    store_path: Path = DEFAULT_STORE,
) -> dict[str, Any]:
    store = load_store(store_path)
    for idea in store.get("ideas") or []:
        if idea.get("id") == idea_id:
            idea["status"] = status
            idea["updated_at"] = _utcnow()
            save_store(store, store_path)
            return idea
    raise KeyError(f"Unknown idea id: {idea_id}")


def render_markdown(store: dict[str, Any] | None = None, *, store_path: Path = DEFAULT_STORE) -> str:
    store = store or load_store(store_path)
    ideas = [i for i in store.get("ideas") or [] if i.get("status", "open") == "open"]
    sessions = store.get("sessions_mined") or []
    updated = store.get("updated_at") or _utcnow()

    lines: list[str] = [
        "# Parked & later ideas — periodic review",
        "",
        f"Auto-generated from [`docs/deferred-ideas.json`](deferred-ideas.json) "
        f"(updated `{updated}`).",
        "",
        "Agents append new parked ideas with `ftse-defer add …` (see `AGENTS.md`). "
        "Do not hand-edit this markdown; edit the JSON store or use the CLI, then "
        "`ftse-defer render`.",
        "",
        "**How to use:** Review quarterly (or after ~8–12 weekly archives). "
        "Move items to done/drop/now via `ftse-defer status`.",
        "",
        "---",
        "",
        "## Sessions mined",
        "",
        "| Agent | URL | Focus |",
        "|-------|-----|--------|",
    ]
    if sessions:
        for session in sessions:
            lines.append(
                f"| {session.get('name', '')} | {session.get('url', '')} | "
                f"{session.get('focus', '')} |"
            )
    else:
        lines.append("| — | — | — |")

    def _table(rows: list[dict[str, Any]], *, security: bool = False) -> list[str]:
        out = [
            "",
            "| # | Idea | Summary | Revisit when |",
            "|---|------|---------|--------------|",
        ]
        if security:
            out = [
                "",
                "| # | Item | Note | Revisit when |",
                "|---|------|------|--------------|",
            ]
        for idea in rows:
            out.append(
                f"| {idea.get('id', '')} | **{idea.get('title', '')}** | "
                f"{idea.get('summary', '')} | {idea.get('revisit_when', '') or '—'} |"
            )
        return out

    not_now = [i for i in ideas if i.get("category") == "not_now" or i.get("section") == "not_now"]
    later = [i for i in ideas if i.get("category") in {"later", "both"} and i.get("section") != "not_now"]
    security = [i for i in ideas if i.get("category") == "security" or i.get("section") == "security"]

    lines.extend(["", "---", "", f"## {SECTION_LABELS['not_now']}"])
    lines.extend(_table(not_now) if not_now else ["", "_None._"])

    lines.extend(["", "---", "", "## Potentially useful later"])
    for section_key in ("learning", "universe", "research", "ops"):
        section_rows = [
            i for i in later if (i.get("section") or "learning") == section_key
        ]
        lines.extend(["", f"### {SECTION_LABELS[section_key]}"])
        lines.extend(_table(section_rows) if section_rows else ["", "_None._"])

    lines.extend(["", "---", "", f"## {SECTION_LABELS['security']}"])
    lines.extend(_table(security, security=True) if security else ["", "_None._"])

    lines.extend(
        [
            "",
            "---",
            "",
            "## Suggested review cadence",
            "",
            "1. **After each ~4 weekly archives:** check decision-review / cron proof items.",
            "2. **After ~8–12 weeks:** re-open evolution and universe-expansion items.",
            "3. **When runtime or data quality hurts:** UK data, parallel fetch, storage.",
            "4. **When acting on the buy list feels underspecified:** trade plans → sim, sizing UI.",
            "",
        ]
    )
    return "\n".join(lines)


def write_markdown(
    *,
    store_path: Path = DEFAULT_STORE,
    markdown_path: Path = DEFAULT_MARKDOWN,
) -> Path:
    text = render_markdown(store_path=store_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(text, encoding="utf-8")
    return markdown_path
