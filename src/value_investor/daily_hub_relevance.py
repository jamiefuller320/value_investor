"""Daily hub Focus / north-star relevance vs standing P1/P2 spend priorities.

Cheap deterministic phrase/anchor check (no LLM). Observe/warn-only —
never rewrites Focus from the finding alone.

Canonical anchors: ``docs/data/daily_hub_priority_anchors.json``.
Result store: ``docs/data/daily_hub_relevance.json`` (ops-monitor optional commit).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import write_json

FINDING_TITLE = "Daily hub Focus stale vs spend priorities"
STORE_FAILED_TITLE = "Daily hub Focus relevance check failed"
DEFAULT_ANCHORS_PATH = Path("docs/data/daily_hub_priority_anchors.json")
DEFAULT_RESULT_PATH = Path("docs/data/daily_hub_relevance.json")
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_AIM_PATH = Path("docs/app.js")
CATEGORY = "dashboard_health"

_AIM_RE = re.compile(
    r'class="daily-hub-aim[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def load_anchors(path: Path | None = None) -> dict[str, Any]:
    anchors_path = Path(path or DEFAULT_ANCHORS_PATH)
    payload = _safe_read(anchors_path)
    if not payload:
        raise ValueError(f"priority anchors missing or unreadable: {anchors_path}")
    if not isinstance(payload.get("required_groups"), list):
        raise ValueError("priority anchors missing required_groups")
    if not isinstance(payload.get("stale_phrases"), list):
        raise ValueError("priority anchors missing stale_phrases")
    return payload


def extract_aim_text(aim_path: Path | None = None) -> str:
    """Pull Daily hub aim copy from ``docs/app.js`` (deterministic, no DOM)."""
    path = Path(aim_path or DEFAULT_AIM_PATH)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = _AIM_RE.search(text)
    if not match:
        return ""
    raw = match.group(1)
    # Strip trivial HTML entities that appear in the aim line.
    raw = raw.replace("&ne;", "≠").replace("&#8800;", "≠")
    return re.sub(r"<[^>]+>", " ", raw)


def _focus_corpus_from_lines(lines: list[Any]) -> str:
    parts: list[str] = []
    for row in lines:
        if not isinstance(row, dict):
            continue
        parts.append(str(row.get("title") or ""))
        parts.append(str(row.get("summary") or ""))
    return _norm(" ".join(parts))


def collect_focus_corpus(
    *,
    data_dir: Path | None = None,
    seed_path: Path | None = None,
    focus_path: Path | None = None,
    aim_path: Path | None = None,
) -> dict[str, Any]:
    """Build the text corpus checked for relevance.

    Prefer seed ``focus_lines`` (editorial source of truth); fall back to
    published ``daily_focus.json`` Focus lines. Always include the aim line.
    """
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    seed = _safe_read(Path(seed_path or (data_dir / "project_daily_seed.json"))) or {}
    hub = _safe_read(Path(focus_path or (data_dir / "daily_focus.json"))) or {}
    seed_lines = list(seed.get("focus_lines") or []) if isinstance(seed, dict) else []
    hub_lines = list(hub.get("focus_lines") or []) if isinstance(hub, dict) else []
    source = "project_daily_seed"
    lines = seed_lines
    if not lines:
        source = "daily_focus"
        lines = hub_lines
    aim = extract_aim_text(aim_path)
    focus_text = _focus_corpus_from_lines(lines)
    combined = _norm(f"{focus_text} {aim}")
    return {
        "source": source,
        "focus_line_count": len([r for r in lines if isinstance(r, dict)]),
        "focus_titles": [
            str(r.get("title") or "").strip()
            for r in lines
            if isinstance(r, dict) and str(r.get("title") or "").strip()
        ],
        "aim_present": bool(aim.strip()),
        "aim_excerpt": aim.strip()[:240],
        "corpus": combined,
    }


def evaluate_relevance(
    corpus: dict[str, Any],
    anchors: dict[str, Any],
) -> dict[str, Any]:
    """Return match detail + whether Focus looks relevant."""
    text = str(corpus.get("corpus") or "")
    missing_groups: list[dict[str, Any]] = []
    matched_groups: list[dict[str, Any]] = []
    for group in anchors.get("required_groups") or []:
        if not isinstance(group, dict):
            continue
        gid = str(group.get("id") or "").strip() or "unnamed"
        label = str(group.get("label") or gid)
        any_of = [str(p).lower() for p in (group.get("any_of") or []) if str(p).strip()]
        hit = next((p for p in any_of if p and p in text), None)
        row = {"id": gid, "label": label, "matched_phrase": hit}
        if hit:
            matched_groups.append(row)
        else:
            missing_groups.append(row)

    stale_hits: list[dict[str, Any]] = []
    for row in anchors.get("stale_phrases") or []:
        if not isinstance(row, dict):
            continue
        phrase = str(row.get("phrase") or "").lower().strip()
        if not phrase:
            continue
        if phrase in text:
            stale_hits.append(
                {
                    "id": str(row.get("id") or phrase),
                    "phrase": phrase,
                    "note": str(row.get("note") or ""),
                }
            )

    empty_focus = int(corpus.get("focus_line_count") or 0) <= 0
    relevant = (not empty_focus) and (not missing_groups) and (not stale_hits)
    return {
        "relevant": relevant,
        "empty_focus": empty_focus,
        "matched_groups": matched_groups,
        "missing_groups": missing_groups,
        "stale_hits": stale_hits,
    }


def ops_findings_from_relevance(
    evaluation: dict[str, Any],
    *,
    corpus: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Warn-only findings when Focus looks stale vs spend-priority anchors."""
    if evaluation.get("relevant"):
        return []
    bits: list[str] = []
    if evaluation.get("empty_focus"):
        bits.append("no Focus lines in seed or daily_focus.json")
    for group in evaluation.get("missing_groups") or []:
        bits.append(
            f"missing required group `{group.get('id')}` "
            f"({group.get('label')}) — none of its any_of phrases appear"
        )
    for hit in evaluation.get("stale_hits") or []:
        note = str(hit.get("note") or "").strip()
        bits.append(f"stale phrase `{hit.get('phrase')}`" + (f" — {note}" if note else ""))
    titles = (corpus or {}).get("focus_titles") or []
    title_bit = f" Current Focus titles: {titles}." if titles else ""
    return [
        {
            "severity": "warn",
            "category": CATEGORY,
            "title": FINDING_TITLE,
            "summary": (
                "Daily hub Focus / aim looks stale vs committed spend-priority "
                "anchors (docs/data/daily_hub_priority_anchors.json). "
                + "; ".join(bits)
                + "."
                + title_bit
                + " Observe-only — rewrite project_daily_seed.json / aim copy; "
                "do not auto-rewrite Focus from this finding. "
                "See docs/ops/ops-monitor.md#daily-hub-focus-relevance."
            ),
            "auto_fixable": False,
        }
    ]


def refresh_daily_hub_relevance(
    *,
    data_dir: Path | None = None,
    anchors_path: Path | None = None,
    result_path: Path | None = None,
    aim_path: Path | None = None,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate Focus relevance and optionally persist the result store."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    clock = now or _utcnow()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    anchors = load_anchors(anchors_path)
    corpus = collect_focus_corpus(data_dir=data_dir, aim_path=aim_path)
    evaluation = evaluate_relevance(corpus, anchors)
    findings = ops_findings_from_relevance(evaluation, corpus=corpus)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": clock.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "definition": str(anchors.get("definition") or ""),
        "anchors_path": str(Path(anchors_path or DEFAULT_ANCHORS_PATH)),
        "anchors_updated_at": anchors.get("updated_at"),
        "corpus": {
            "source": corpus.get("source"),
            "focus_line_count": corpus.get("focus_line_count"),
            "focus_titles": corpus.get("focus_titles"),
            "aim_present": corpus.get("aim_present"),
            "aim_excerpt": corpus.get("aim_excerpt"),
        },
        "evaluation": evaluation,
        "finding_titles": [f.get("title") for f in findings],
        "observe_only": True,
        "auto_fixable": False,
    }
    if persist:
        out = Path(result_path or (data_dir / "daily_hub_relevance.json"))
        write_json(out, payload, compact=False)
    return payload


__all__ = [
    "CATEGORY",
    "DEFAULT_AIM_PATH",
    "DEFAULT_ANCHORS_PATH",
    "DEFAULT_DATA_DIR",
    "DEFAULT_RESULT_PATH",
    "FINDING_TITLE",
    "STORE_FAILED_TITLE",
    "collect_focus_corpus",
    "evaluate_relevance",
    "extract_aim_text",
    "load_anchors",
    "ops_findings_from_relevance",
    "refresh_daily_hub_relevance",
]
