"""Merge-safe IDs for the deferred-ideas store.

``ftse-defer add`` allocates the next number on the branch's own copy of
``docs/deferred-ideas.json``, so two open branches mint the same ID. Main's
numbering always wins: ``rebase_store`` keeps every base entry as-is and
renumbers only the branch's new entries that collide, and
``rewrite_id_references`` follows those renames in lines the branch added.
``check_store_ids`` is the CI guard (duplicate IDs, or a base ID whose title
changed).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from value_investor.deferred_ideas import DEFAULT_MARKDOWN, DEFAULT_STORE, _norm_title

IDEA_ID_RE = re.compile(r"^([A-Z])(\d+)$")
FRAGMENT_ID_RE = re.compile(r"^(frag-\d{8}-)(\d+)$")
STORE_PATHS = {str(DEFAULT_STORE), str(DEFAULT_MARKDOWN)}


def _next_idea_id(prefix: str, used: set[str]) -> str:
    numbers = [
        int(m.group(2)) for m in (IDEA_ID_RE.match(i) for i in used) if m and m.group(1) == prefix
    ]
    return f"{prefix}{max(numbers, default=0) + 1}"


def _next_fragment_id(prefix: str, used: set[str]) -> str:
    numbers = [
        int(m.group(2))
        for m in (FRAGMENT_ID_RE.match(i) for i in used)
        if m and m.group(1) == prefix
    ]
    return f"{prefix}{max(numbers, default=0) + 1:02d}"


def _newer(branch_row: dict[str, Any], base_row: dict[str, Any]) -> bool:
    return str(branch_row.get("updated_at") or "") > str(base_row.get("updated_at") or "")


def rebase_store(
    base: dict[str, Any], branch: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (merged store, {branch_id: new_id}) with base numbering preserved."""
    renames: dict[str, str] = {}
    ideas = [dict(row) for row in base.get("ideas") or []]
    by_id = {str(row.get("id")): index for index, row in enumerate(ideas)}
    by_title = {_norm_title(str(row.get("title") or "")): index for index, row in enumerate(ideas)}
    used = set(by_id)

    for row in branch.get("ideas") or []:
        branch_id = str(row.get("id") or "")
        title = _norm_title(str(row.get("title") or ""))
        index = by_id.get(branch_id)
        if index is None or _norm_title(str(ideas[index].get("title") or "")) != title:
            index = by_title.get(title)
        if index is not None:
            target_id = str(ideas[index]["id"])
            if target_id != branch_id:
                renames[branch_id] = target_id
            if _newer(row, ideas[index]):
                ideas[index] = {**ideas[index], **row, "id": target_id}
            continue
        match = IDEA_ID_RE.match(branch_id)
        new_id = branch_id
        if branch_id in used or match is None:
            new_id = _next_idea_id(match.group(1) if match else "L", used)
            renames[branch_id] = new_id
        used.add(new_id)
        ideas.append({**row, "id": new_id})
        by_title[title] = len(ideas) - 1

    fragments = [dict(row) for row in base.get("fragments") or []]
    frag_by_id = {str(row.get("id")): index for index, row in enumerate(fragments)}
    frag_by_text = {
        _norm_title(str(row.get("text") or "")): index for index, row in enumerate(fragments)
    }
    frag_used = set(frag_by_id)
    for row in branch.get("fragments") or []:
        branch_id = str(row.get("id") or "")
        text = _norm_title(str(row.get("text") or ""))
        index = frag_by_id.get(branch_id)
        if index is None or _norm_title(str(fragments[index].get("text") or "")) != text:
            index = frag_by_text.get(text)
        if index is not None:
            target_id = str(fragments[index]["id"])
            if target_id != branch_id:
                renames[branch_id] = target_id
            if _newer(row, fragments[index]):
                fragments[index] = {**fragments[index], **row, "id": target_id}
            continue
        new_id = branch_id
        if branch_id in frag_used:
            match = FRAGMENT_ID_RE.match(branch_id)
            new_id = _next_fragment_id(match.group(1) if match else "frag-", frag_used)
            renames[branch_id] = new_id
        frag_used.add(new_id)
        fragments.append({**row, "id": new_id})
        frag_by_text[text] = len(fragments) - 1

    sessions = list(base.get("sessions_mined") or [])
    for session in branch.get("sessions_mined") or []:
        if session not in sessions:
            sessions.append(session)

    merged = {**branch, **base}
    merged["ideas"] = ideas
    merged["fragments"] = fragments
    merged["sessions_mined"] = sessions
    return merged, renames


def check_store_ids(store: dict[str, Any], base: dict[str, Any] | None = None) -> list[str]:
    """Problems that mean the store needs ``ftse-defer rebase-ids``."""
    problems: list[str] = []
    for key in ("ideas", "fragments"):
        seen: set[str] = set()
        for row in store.get(key) or []:
            row_id = str(row.get("id") or "")
            if row_id in seen:
                problems.append(f"duplicate {key[:-1]} id {row_id}")
            seen.add(row_id)
    if base is not None:
        current: dict[str, dict[str, Any]] = {}
        for row in store.get("ideas") or []:
            current.setdefault(str(row.get("id")), row)
        for row in base.get("ideas") or []:
            row_id = str(row.get("id"))
            mine = current.get(row_id)
            if mine is None:
                problems.append(f"idea {row_id} on base is missing")
            elif _norm_title(str(mine.get("title") or "")) != _norm_title(
                str(row.get("title") or "")
            ):
                problems.append(
                    f"idea {row_id} is {mine.get('title')!r} here but {row.get('title')!r} on base"
                )
    return problems


def rewrite_id_references(text: str, renames: dict[str, str], lines: set[str]) -> str:
    """Apply ``renames`` (simultaneously) only on lines whose content is in ``lines``."""
    if not renames or not lines:
        return text
    pattern = re.compile(
        r"(?<![\w-])("
        + "|".join(re.escape(k) for k in sorted(renames, key=len, reverse=True))
        + r")(?![\w-])"
    )
    out = []
    for line in text.splitlines(keepends=True):
        if line.rstrip("\r\n") in lines:
            line = pattern.sub(lambda m: renames[m.group(1)], line)
        out.append(line)
    return "".join(out)


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def load_store_at(ref: str, *, repo: Path, store_path: Path = DEFAULT_STORE) -> dict[str, Any]:
    return json.loads(_git("show", f"{ref}:{store_path.as_posix()}", cwd=repo))


def branch_added_lines(base_ref: str, *, repo: Path) -> dict[str, set[str]]:
    """Lines the branch (HEAD) added since it forked from ``base_ref``, per file."""
    merge_base = _git("merge-base", base_ref, "HEAD", cwd=repo).strip()
    diff = _git("diff", "-U0", "--no-color", merge_base, "HEAD", cwd=repo)
    added: dict[str, set[str]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:]
            current = name[2:] if name.startswith("b/") else None
        elif current and line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, set()).add(line[1:])
    return {path: rows for path, rows in added.items() if path not in STORE_PATHS}


def rebase_ids(
    base_ref: str,
    *,
    repo: Path = Path("."),
    store_path: Path = DEFAULT_STORE,
    apply: bool = False,
) -> dict[str, Any]:
    """Rebase the branch's deferred IDs onto ``base_ref`` (run during or after a merge).

    The branch store is ``HEAD``'s copy, so a store left with conflict markers by
    ``git merge`` is fine. With ``apply`` the merged store is written and ID
    references are rewritten in lines the branch added.
    """
    repo = Path(repo)
    base = load_store_at(base_ref, repo=repo, store_path=store_path)
    branch = load_store_at("HEAD", repo=repo, store_path=store_path)
    merged, renames = rebase_store(base, branch)
    rewritten: list[str] = []
    if apply:
        (repo / store_path).write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        for rel, lines in sorted(branch_added_lines(base_ref, repo=repo).items()):
            path = repo / rel
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            new_text = rewrite_id_references(text, renames, lines)
            if new_text != text:
                path.write_text(new_text, encoding="utf-8")
                rewritten.append(rel)
    return {
        "base_ref": base_ref,
        "renames": renames,
        "rewritten_files": rewritten,
        "problems": check_store_ids(merged, base),
        "applied": apply,
    }
