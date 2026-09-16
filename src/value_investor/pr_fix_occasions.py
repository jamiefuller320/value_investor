"""Durable log of PR check / merge fix-request occasions.

Records each time a human (or the project-traffic controller asking for a
human/agent fix) requests that a PR's failing checks or merge conflict be
fixed, together with a normalized failure reason. Aggregates counts so
recurring issues can be identified and fixed at the root.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 1
DEFAULT_PR_FIX_OCCASIONS_PATH = Path("docs/data/pr_fix_occasions.json")
DEFAULT_KEEP = 500

SOURCE_HUMAN = "human_request"
SOURCE_TRAFFIC = "traffic_controller"

KIND_CI = "ci_check"
KIND_MERGE = "merge_conflict"
KIND_BOTH = "ci_and_merge"

VALID_SOURCES = frozenset({SOURCE_HUMAN, SOURCE_TRAFFIC})
VALID_KINDS = frozenset({KIND_CI, KIND_MERGE, KIND_BOTH})


def empty_pr_fix_occasions() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": None,
        "occasion_count": 0,
        "occasions": [],
        "common_issues": {
            "by_reason": [],
            "by_kind": [],
            "by_source": [],
        },
    }


def load_pr_fix_occasions(path: Path | None = None) -> dict[str, Any]:
    path = Path(path or DEFAULT_PR_FIX_OCCASIONS_PATH)
    if not path.exists():
        return empty_pr_fix_occasions()
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return empty_pr_fix_occasions()
    if not isinstance(payload, dict):
        return empty_pr_fix_occasions()
    occasions = payload.get("occasions")
    if not isinstance(occasions, list):
        occasions = []
    return {
        "schema_version": int(payload.get("schema_version") or SCHEMA_VERSION),
        "updated_at": payload.get("updated_at"),
        "occasion_count": int(payload.get("occasion_count") or len(occasions)),
        "occasions": [row for row in occasions if isinstance(row, dict)],
        "common_issues": payload.get("common_issues")
        if isinstance(payload.get("common_issues"), dict)
        else {"by_reason": [], "by_kind": [], "by_source": []},
    }


def normalize_failure_reason(
    *,
    kind: str,
    reason: str | None = None,
    failed_check_names: list[str] | None = None,
    mergeable_state: str | None = None,
) -> str:
    """Return a stable bucket label for aggregation."""
    explicit = " ".join(str(reason or "").split()).strip()
    if explicit:
        return explicit[:240]

    names = [str(n).strip() for n in (failed_check_names or []) if str(n).strip()]
    state = str(mergeable_state or "").strip().lower()

    if kind == KIND_MERGE:
        return f"merge_conflict:{state}" if state else "merge_conflict"
    if kind == KIND_BOTH:
        ci_part = f"ci_failing:{','.join(names[:5])}" if names else "ci_failing"
        merge_part = f"merge_conflict:{state}" if state else "merge_conflict"
        return f"{ci_part}+{merge_part}"
    if names:
        return f"ci_failing:{','.join(names[:5])}"
    return "ci_failing"


def _next_occasion_id(occasions: list[dict[str, Any]], *, now: datetime) -> str:
    stamp = now.strftime("%Y%m%d")
    prefix = f"prf-{stamp}-"
    seq = 0
    for row in occasions:
        oid = str(row.get("id") or "")
        if not oid.startswith(prefix):
            continue
        tail = oid[len(prefix) :]
        if tail.isdigit():
            seq = max(seq, int(tail))
    return f"{prefix}{seq + 1:03d}"


def summarize_common_failure_reasons(
    occasions: list[dict[str, Any]] | None = None,
    *,
    path: Path | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Aggregate occasions by reason / kind / source."""
    if occasions is None:
        occasions = list(load_pr_fix_occasions(path).get("occasions") or [])
    reason_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    reason_prs: dict[str, list[int]] = {}
    reason_sources: dict[str, Counter[str]] = {}

    for row in occasions:
        reason = str(row.get("failure_reason") or "unknown").strip() or "unknown"
        kind = str(row.get("kind") or "unknown")
        source = str(row.get("source") or "unknown")
        reason_counts[reason] += 1
        kind_counts[kind] += 1
        source_counts[source] += 1
        pr_number = row.get("pr_number")
        if isinstance(pr_number, int):
            bucket = reason_prs.setdefault(reason, [])
            if pr_number not in bucket:
                bucket.append(pr_number)
        reason_sources.setdefault(reason, Counter())[source] += 1

    by_reason = []
    for reason, count in reason_counts.most_common(max(1, int(limit))):
        by_reason.append(
            {
                "failure_reason": reason,
                "count": count,
                "sources": dict(reason_sources.get(reason) or {}),
                "recent_prs": list(reason_prs.get(reason) or [])[-8:],
            }
        )
    return {
        "occasion_count": len(occasions),
        "by_reason": by_reason,
        "by_kind": [{"kind": kind, "count": count} for kind, count in kind_counts.most_common()],
        "by_source": [
            {"source": source, "count": count} for source, count in source_counts.most_common()
        ],
    }


def format_common_issues_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# PR fix occasions — common issues",
        "",
        f"Occasion count: **{summary.get('occasion_count', 0)}**",
        "",
        "## By failure reason",
    ]
    by_reason = list(summary.get("by_reason") or [])
    if by_reason:
        for row in by_reason:
            prs = row.get("recent_prs") or []
            pr_bit = f" (PRs: {', '.join(f'#{n}' for n in prs)})" if prs else ""
            sources = row.get("sources") or {}
            src_bit = "; ".join(f"{k}={v}" for k, v in sorted(sources.items())) if sources else ""
            lines.append(
                f"- `{row.get('failure_reason')}` — {row.get('count')}×"
                + (f" [{src_bit}]" if src_bit else "")
                + pr_bit
            )
    else:
        lines.append("- _(none recorded yet)_")

    lines.extend(["", "## By kind"])
    by_kind = list(summary.get("by_kind") or [])
    if by_kind:
        lines.extend(f"- `{row.get('kind')}` — {row.get('count')}" for row in by_kind)
    else:
        lines.append("- _(none)_")

    lines.extend(["", "## By source"])
    by_source = list(summary.get("by_source") or [])
    if by_source:
        lines.extend(f"- `{row.get('source')}` — {row.get('count')}" for row in by_source)
    else:
        lines.append("- _(none)_")

    lines.extend(
        [
            "",
            'Record: `ftse-project-traffic record-fix --pr N --kind ci_check --reason "…"`',
            "Summarize: `ftse-project-traffic common-issues`",
        ]
    )
    return "\n".join(lines) + "\n"


def record_pr_fix_occasion(
    *,
    source: str,
    kind: str,
    failure_reason: str | None = None,
    pr_number: int | None = None,
    branch: str | None = None,
    title: str | None = None,
    url: str | None = None,
    task_id: str | None = None,
    head_sha: str | None = None,
    mergeable_state: str | None = None,
    failed_check_names: list[str] | None = None,
    notes: str | None = None,
    details: dict[str, Any] | None = None,
    path: Path | None = None,
    apply: bool = True,
    keep: int = DEFAULT_KEEP,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append one fix-request occasion and refresh common-issue aggregates."""
    source_norm = str(source or "").strip()
    kind_norm = str(kind or "").strip()
    if source_norm not in VALID_SOURCES:
        raise ValueError(f"source must be one of {sorted(VALID_SOURCES)}")
    if kind_norm not in VALID_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_KINDS)}")

    now = now or datetime.now(UTC)
    path = Path(path or DEFAULT_PR_FIX_OCCASIONS_PATH)
    payload = load_pr_fix_occasions(path)
    occasions = list(payload.get("occasions") or [])

    reason = normalize_failure_reason(
        kind=kind_norm,
        reason=failure_reason,
        failed_check_names=failed_check_names,
        mergeable_state=mergeable_state,
    )
    entry: dict[str, Any] = {
        "id": _next_occasion_id(occasions, now=now),
        "recorded_at": now.isoformat(),
        "source": source_norm,
        "kind": kind_norm,
        "failure_reason": reason,
        "pr_number": int(pr_number) if pr_number is not None else None,
        "branch": str(branch).strip() if branch else None,
        "title": str(title).strip() if title else None,
        "url": str(url).strip() if url else None,
        "task_id": str(task_id).strip() if task_id else None,
        "head_sha": str(head_sha).strip() if head_sha else None,
        "mergeable_state": str(mergeable_state).strip() if mergeable_state else None,
        "failed_check_names": [
            str(n).strip() for n in (failed_check_names or []) if str(n).strip()
        ],
        "notes": str(notes).strip() if notes else None,
        "details": dict(details) if isinstance(details, dict) else {},
    }
    occasions.append(entry)
    occasions = occasions[-max(1, int(keep)) :]
    summary = summarize_common_failure_reasons(occasions)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now.isoformat(),
        "occasion_count": len(occasions),
        "occasions": occasions,
        "common_issues": {
            "by_reason": summary["by_reason"],
            "by_kind": summary["by_kind"],
            "by_source": summary["by_source"],
        },
    }
    if apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, compact=False)
    return {"entry": entry, "payload": payload, "path": str(path)}


__all__ = [
    "DEFAULT_KEEP",
    "DEFAULT_PR_FIX_OCCASIONS_PATH",
    "KIND_BOTH",
    "KIND_CI",
    "KIND_MERGE",
    "SCHEMA_VERSION",
    "SOURCE_HUMAN",
    "SOURCE_TRAFFIC",
    "empty_pr_fix_occasions",
    "format_common_issues_markdown",
    "load_pr_fix_occasions",
    "normalize_failure_reason",
    "record_pr_fix_occasion",
    "summarize_common_failure_reasons",
]
