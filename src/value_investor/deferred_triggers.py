"""Machine-checkable revisit triggers for deferred ideas (observe-only).

``revisit_when`` stays free text for humans. An idea may also carry a structured
``trigger`` that ops-monitor evaluates daily against committed JSON::

    "trigger": {
      "all": [
        {"file": "docs/data/paper_automation/learning_tracks_review.json",
         "path": "reviews.ai_judgment_fair.metrics.epoch.cost_drag",
         "op": ">", "value": 0.01},
        {"on_or_after": "2026-11-01"}
      ]
    }

``all`` or ``any`` holds a list of conditions. A condition is either a JSON
lookup (``file`` + ``path`` + ``op`` [+ ``value``]) or a date
(``on_or_after``). Paths are dotted keys; ``key[field=value]`` selects the first
list row whose ``field`` equals ``value``. Missing files or paths are
``unknown``, never ``met``.

The check also flags open ideas whose free-text ``revisit_when`` names a frozen
paper book and that have not been edited since the book froze, so triggers that
can no longer fire surface instead of waiting forever.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_RESULT_PATH = Path("docs/data/deferred_trigger_check.json")
DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
SCHEMA_VERSION = 1
UNKNOWN_GRACE_DAYS = 7

MET_TITLE = "Deferred idea triggers met"
UNREADABLE_TITLE = "Deferred idea triggers unreadable"
FROZEN_TITLE = "Deferred idea triggers name frozen books"

COMPARE_OPS = {">=", ">", "<=", "<", "==", "!="}
UNARY_OPS = {"exists", "truthy"}
ALLOWED_OPS = COMPARE_OPS | UNARY_OPS | {"in"}

MET = "met"
UNMET = "unmet"
UNKNOWN = "unknown"

_SEGMENT = re.compile(r"^([^\[\]]+)((?:\[[^\]]+\])*)$")
_SELECTOR = re.compile(r"\[([^=\]]+)=([^\]]*)\]")
MISSING = object()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def validate_trigger(trigger: Any) -> list[str]:
    """Shape problems with a structured trigger (empty list when valid)."""
    if not isinstance(trigger, dict):
        return ["trigger must be an object"]
    modes = [key for key in ("all", "any") if key in trigger]
    if len(modes) != 1:
        return ["trigger needs exactly one of 'all' or 'any'"]
    conditions = trigger[modes[0]]
    if not isinstance(conditions, list) or not conditions:
        return [f"'{modes[0]}' must be a non-empty list"]
    problems: list[str] = []
    for index, cond in enumerate(conditions):
        label = f"condition {index}"
        if not isinstance(cond, dict):
            problems.append(f"{label} must be an object")
            continue
        if "on_or_after" in cond:
            try:
                date.fromisoformat(str(cond["on_or_after"]))
            except ValueError:
                problems.append(f"{label}: on_or_after must be YYYY-MM-DD")
            continue
        if not cond.get("file") or not cond.get("path"):
            problems.append(f"{label} needs 'file' and 'path' (or 'on_or_after')")
            continue
        if str(cond["file"]).startswith("/") or ".." in Path(str(cond["file"])).parts:
            problems.append(f"{label}: file must be repo-relative")
        op = cond.get("op")
        if op not in ALLOWED_OPS:
            problems.append(f"{label}: op must be one of {sorted(ALLOWED_OPS)}")
        elif op not in UNARY_OPS and "value" not in cond:
            problems.append(f"{label}: op {op!r} needs 'value'")
        elif op == "in" and not isinstance(cond.get("value"), list):
            problems.append(f"{label}: op 'in' needs a list value")
        if not all(_SEGMENT.match(part) for part in str(cond["path"]).split(".")):
            problems.append(f"{label}: unparseable path {cond['path']!r}")
    return problems


def resolve_path(payload: Any, path: str) -> Any:
    """Value at a dotted path with ``[field=value]`` list selectors, or ``MISSING``."""
    node = payload
    for part in str(path).split("."):
        match = _SEGMENT.match(part)
        if match is None or not isinstance(node, dict) or match.group(1) not in node:
            return MISSING
        node = node[match.group(1)]
        for field, wanted in _SELECTOR.findall(match.group(2) or ""):
            if not isinstance(node, list):
                return MISSING
            node = next(
                (row for row in node if isinstance(row, dict) and str(row.get(field)) == wanted),
                MISSING,
            )
            if node is MISSING:
                return MISSING
    return node


def _compare(actual: Any, op: str, expected: Any) -> bool | None:
    if op == "exists":
        return True
    if op == "truthy":
        return bool(actual)
    if op == "in":
        return actual in expected
    if op == "==":
        return actual == expected
    if op == "!=":
        return actual != expected
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return None
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        return None
    return {
        ">=": actual >= expected,
        ">": actual > expected,
        "<=": actual <= expected,
        "<": actual < expected,
    }[op]


def evaluate_condition(
    cond: dict[str, Any],
    *,
    repo_root: Path,
    today: date,
    cache: dict[str, Any],
) -> dict[str, Any]:
    if "on_or_after" in cond:
        due = date.fromisoformat(str(cond["on_or_after"]))
        return {
            "condition": cond,
            "state": MET if today >= due else UNMET,
            "actual": today.isoformat(),
        }
    rel = str(cond["file"])
    if rel not in cache:
        try:
            cache[rel] = json.loads((repo_root / rel).read_text(encoding="utf-8"))
        except FileNotFoundError:
            cache[rel] = MISSING
        except (OSError, ValueError):
            cache[rel] = None
    payload = cache[rel]
    if payload is MISSING:
        return {"condition": cond, "state": UNKNOWN, "reason": f"{rel} not found"}
    if payload is None:
        return {"condition": cond, "state": UNKNOWN, "reason": f"{rel} is not valid JSON"}
    actual = resolve_path(payload, str(cond["path"]))
    if actual is MISSING:
        return {"condition": cond, "state": UNKNOWN, "reason": f"{cond['path']} not in {rel}"}
    result = _compare(actual, str(cond["op"]), cond.get("value"))
    if result is None:
        return {
            "condition": cond,
            "state": UNKNOWN,
            "actual": actual,
            "reason": f"{cond['path']} is not numeric",
        }
    return {"condition": cond, "state": MET if result else UNMET, "actual": actual}


def evaluate_trigger(
    trigger: dict[str, Any],
    *,
    repo_root: Path,
    today: date,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    problems = validate_trigger(trigger)
    if problems:
        return {"state": UNKNOWN, "invalid": True, "reasons": problems, "conditions": []}
    mode = "all" if "all" in trigger else "any"
    cache = {} if cache is None else cache
    rows = [
        evaluate_condition(cond, repo_root=repo_root, today=today, cache=cache)
        for cond in trigger[mode]
    ]
    states = [row["state"] for row in rows]
    if mode == "all":
        state = UNMET if UNMET in states else (UNKNOWN if UNKNOWN in states else MET)
    else:
        state = MET if MET in states else (UNKNOWN if UNKNOWN in states else UNMET)
    return {
        "state": state,
        "mode": mode,
        "conditions": rows,
        "reasons": list(dict.fromkeys(row["reason"] for row in rows if row.get("reason"))),
    }


def frozen_book_mentions(
    ideas: list[dict[str, Any]],
    frozen: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Open ideas whose ``revisit_when`` names a frozen book and predates the freeze.

    Only ids containing ``_`` are matched: bare ids such as ``rules`` or
    ``technical`` are ordinary words in most triggers.
    """
    patterns = {
        track_id: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(track_id)}(?![A-Za-z0-9_])")
        for track_id in frozen
        if "_" in track_id
    }
    out: list[dict[str, Any]] = []
    for idea in ideas:
        text = str(idea.get("revisit_when") or "")
        edited = _parse_dt(idea.get("updated_at") or idea.get("added_at"))
        hits = []
        for track_id, pattern in sorted(patterns.items()):
            if not pattern.search(text):
                continue
            frozen_at = _parse_dt(frozen[track_id].get("frozen_at"))
            if edited is not None and frozen_at is not None and edited >= frozen_at:
                continue
            hits.append(track_id)
        if hits:
            out.append({"id": idea.get("id"), "title": idea.get("title"), "tracks": hits})
    return out


def _load_frozen(paper_root: Path) -> dict[str, dict[str, Any]]:
    from value_investor.assessment_model import frozen_tracks

    return frozen_tracks(paper_root)


def check_deferred_triggers(
    store: dict[str, Any],
    *,
    repo_root: Path = Path("."),
    paper_root: Path | None = None,
    previous: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate every open idea's structured trigger and scan free-text triggers."""
    now = now or datetime.now(UTC)
    today = now.date()
    repo_root = Path(repo_root)
    paper_root = Path(paper_root) if paper_root is not None else repo_root / DEFAULT_PAPER_ROOT
    prior_met = {
        str(row.get("id")): row.get("first_met_at") for row in (previous or {}).get("met") or []
    }
    prior_unknown = {
        str(row.get("id")): row.get("unknown_since")
        for row in (previous or {}).get("unknown") or []
    }
    open_ideas = [
        idea for idea in store.get("ideas") or [] if idea.get("status", "open") in {"open", "now"}
    ]
    cache: dict[str, Any] = {}
    met: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    unmet: list[str] = []
    for idea in open_ideas:
        trigger = idea.get("trigger")
        if not trigger:
            continue
        idea_id = str(idea.get("id"))
        result = evaluate_trigger(trigger, repo_root=repo_root, today=today, cache=cache)
        base = {"id": idea_id, "title": idea.get("title"), "status": idea.get("status", "open")}
        if result["state"] == MET:
            met.append(
                {
                    **base,
                    "first_met_at": prior_met.get(idea_id) or now.isoformat(),
                    "conditions": result["conditions"],
                }
            )
        elif result["state"] == UNKNOWN:
            since = prior_unknown.get(idea_id) or now.isoformat()
            unknown.append(
                {
                    **base,
                    "unknown_since": since,
                    "invalid": bool(result.get("invalid")),
                    "reasons": result["reasons"],
                }
            )
        else:
            unmet.append(idea_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "observe_only": True,
        "open_ideas": len(open_ideas),
        "with_trigger": len(met) + len(unknown) + len(unmet),
        "met": met,
        "unknown": unknown,
        "unmet": unmet,
        "frozen_mentions": frozen_book_mentions(open_ideas, _load_frozen(paper_root)),
        "unknown_grace_days": UNKNOWN_GRACE_DAYS,
    }


def overdue_unknown(payload: dict[str, Any], *, now: datetime | None = None) -> list[dict]:
    """Unknown triggers that are invalid or have stayed unreadable past the grace period."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=int(payload.get("unknown_grace_days") or UNKNOWN_GRACE_DAYS))
    out = []
    for row in payload.get("unknown") or []:
        since = _parse_dt(row.get("unknown_since"))
        if row.get("invalid") or (since is not None and since <= cutoff):
            out.append(row)
    return out


def ops_findings_from_trigger_check(
    payload: dict[str, Any], *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Warn-only findings (``auto_fixable=False``): a human picks up or retargets the idea."""
    findings: list[dict[str, Any]] = []
    met = payload.get("met") or []
    if met:
        ids = ", ".join(f"{row['id']} ({str(row.get('first_met_at'))[:10]})" for row in met)
        findings.append(
            {
                "severity": "warn",
                "category": "observe",
                "title": MET_TITLE,
                "summary": (
                    f"{len(met)} open deferred idea(s) have met their structured trigger: "
                    f"{ids}. Pick up, retarget, or close each with ftse-defer "
                    "(docs/ops/deferred-triggers.md)."
                ),
            }
        )
    stale = overdue_unknown(payload, now=now)
    if stale:
        detail = "; ".join(f"{row['id']}: {', '.join(row['reasons'])}" for row in stale)
        findings.append(
            {
                "severity": "warn",
                "category": "observe",
                "title": UNREADABLE_TITLE,
                "summary": (
                    f"{len(stale)} structured trigger(s) cannot be evaluated: {detail}. "
                    "Fix with ftse-defer set-trigger."
                ),
            }
        )
    frozen = payload.get("frozen_mentions") or []
    if frozen:
        detail = "; ".join(f"{row['id']} ({', '.join(row['tracks'])})" for row in frozen)
        findings.append(
            {
                "severity": "warn",
                "category": "observe",
                "title": FROZEN_TITLE,
                "summary": (
                    f"{len(frozen)} open idea(s) wait on a frozen book that will never "
                    f"change: {detail}. Retarget revisit_when to the primary/control or close."
                ),
            }
        )
    return findings


def refresh_deferred_trigger_check(
    *,
    store_path: Path,
    result_path: Path = DEFAULT_RESULT_PATH,
    repo_root: Path = Path("."),
    paper_root: Path | None = None,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    from value_investor.deferred_ideas import load_store

    try:
        previous = json.loads(Path(result_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    payload = check_deferred_triggers(
        load_store(Path(store_path)),
        repo_root=repo_root,
        paper_root=paper_root,
        previous=previous if isinstance(previous, dict) else None,
        now=now,
    )
    if persist:
        Path(result_path).parent.mkdir(parents=True, exist_ok=True)
        Path(result_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
