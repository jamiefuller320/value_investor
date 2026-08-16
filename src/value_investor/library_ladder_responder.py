"""Classify library ladder workflow failures and choose safe recovery actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_RESPONDER_LOG = DEFAULT_LIBRARY_ROOT / "ladder_responder_log.json"
DEFAULT_WORKFLOW_PATH = Path(".github/workflows/library-grow.yml")

CLASS_PARTIAL_SUCCESS = "partial_success"
CLASS_CORRUPT_LAST_LADDER = "corrupt_last_ladder"
CLASS_TRANSIENT = "transient"
CLASS_METRICS_STALL = "metrics_stall"
CLASS_UNKNOWN = "unknown"

ACTION_RERUN = "rerun_workflow"
ACTION_DRAFT_TASK = "draft_engineering_task"
ACTION_NOOP = "noop_already_recovered"

RERUN_COOLDOWN_HOURS = 20.0


@dataclass(frozen=True)
class LadderFailureClassification:
    kind: str
    reasons: list[str]
    ladder_json_valid: bool
    workflow_fix_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "reasons": list(self.reasons),
            "ladder_json_valid": self.ladder_json_valid,
            "workflow_fix_present": self.workflow_fix_present,
        }


@dataclass(frozen=True)
class LadderResponderDecision:
    action: str
    classification: LadderFailureClassification
    should_rerun: bool
    should_draft_task: bool
    reason: str
    rerun_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "classification": self.classification.to_dict(),
            "should_rerun": self.should_rerun,
            "should_draft_task": self.should_draft_task,
            "reason": self.reason,
            "rerun_allowed": self.rerun_allowed,
        }


def _ladder_json_valid(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        read_json(path)
    except (OSError, ValueError, TypeError):
        return False
    return True


def workflow_fix_present(workflow_path: Path = DEFAULT_WORKFLOW_PATH) -> bool:
    """True when the ladder workflow no longer tees stdout over last_ladder.json."""
    if not workflow_path.exists():
        return False
    text = workflow_path.read_text(encoding="utf-8", errors="replace")
    if 'tee "$ROOT/last_ladder.json"' in text or "tee '$ROOT/last_ladder.json'" in text:
        return False
    return "run_library_ladder already writes" in text or "json.load(open('$ROOT/last_ladder.json'))" in text


def classify_library_ladder_failure(
    log_text: str,
    *,
    ladder_json_path: Path = DEFAULT_LIBRARY_ROOT / "last_ladder.json",
    workflow_path: Path = DEFAULT_WORKFLOW_PATH,
) -> LadderFailureClassification:
    """Bucket a failed library-grow run from CI log text and optional artifacts."""
    text = (log_text or "").lower()
    reasons: list[str] = []
    ladder_valid = _ladder_json_valid(ladder_json_path)
    fix_present = workflow_fix_present(workflow_path)

    if "jsondecodeerror" in text and "last_ladder" in text:
        reasons.append("JSONDecodeError while parsing last_ladder.json")
        return LadderFailureClassification(
            kind=CLASS_CORRUPT_LAST_LADDER,
            reasons=reasons,
            ladder_json_valid=ladder_valid,
            workflow_fix_present=fix_present,
        )

    if re.search(r"yahoo.*401|401.*yahoo|unauthorized", text):
        reasons.append("Yahoo metrics fetch unauthorized (401)")
        return LadderFailureClassification(
            kind=CLASS_METRICS_STALL,
            reasons=reasons,
            ladder_json_valid=ladder_valid,
            workflow_fix_present=fix_present,
        )

    if any(
        token in text
        for token in (
            "rate limit",
            "connection reset",
            "temporary failure",
            "503 service",
            "timed out",
            "timeout",
            "curl: (28)",
            "curl: (56)",
        )
    ):
        reasons.append("Transient network or upstream error in log")
        return LadderFailureClassification(
            kind=CLASS_TRANSIENT,
            reasons=reasons,
            ladder_json_valid=ladder_valid,
            workflow_fix_present=fix_present,
        )

    partial_markers = (
        "graduated market:",
        "queue_complete",
        "wrote: docs/data/automation.json",
        "focus market:",
    )
    if ladder_valid or any(marker in text for marker in partial_markers):
        reasons.append("Ladder body appears to have completed before post-step failure")
        return LadderFailureClassification(
            kind=CLASS_PARTIAL_SUCCESS,
            reasons=reasons,
            ladder_json_valid=ladder_valid,
            workflow_fix_present=fix_present,
        )

    reasons.append("No recognized recovery signature in failed run log")
    return LadderFailureClassification(
        kind=CLASS_UNKNOWN,
        reasons=reasons,
        ladder_json_valid=ladder_valid,
        workflow_fix_present=fix_present,
    )


def default_responder_log() -> dict[str, Any]:
    return {"schema_version": 1, "entries": [], "updated_at": None}


def load_responder_log(path: Path = DEFAULT_RESPONDER_LOG) -> dict[str, Any]:
    if not path.exists():
        return default_responder_log()
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return default_responder_log()
    base = default_responder_log()
    base.update(payload)
    base.setdefault("entries", [])
    return base


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def rerun_cooldown_active(
    *,
    log_path: Path = DEFAULT_RESPONDER_LOG,
    now: datetime | None = None,
    min_hours: float = RERUN_COOLDOWN_HOURS,
) -> tuple[bool, str]:
    """Return whether a guarded ladder rerun already fired within the cooldown window."""
    now = now or datetime.now(UTC)
    log = load_responder_log(log_path)
    cutoff = now - timedelta(hours=min_hours)
    for entry in reversed(list(log.get("entries") or [])):
        if str(entry.get("action") or "") != ACTION_RERUN:
            continue
        when = _parse_iso(str(entry.get("recorded_at") or ""))
        if when and when >= cutoff:
            return True, f"rerun dispatched {when.isoformat()} (cooldown {min_hours}h)"
    return False, ""


def evaluate_library_ladder_response(
    classification: LadderFailureClassification,
    *,
    log_path: Path = DEFAULT_RESPONDER_LOG,
    now: datetime | None = None,
) -> LadderResponderDecision:
    """Choose rerun vs engineering draft for a classified ladder failure."""
    now = now or datetime.now(UTC)
    cooldown_active, cooldown_reason = rerun_cooldown_active(log_path=log_path, now=now)

    if classification.kind == CLASS_METRICS_STALL:
        return LadderResponderDecision(
            action=ACTION_DRAFT_TASK,
            classification=classification,
            should_rerun=False,
            should_draft_task=True,
            reason="Metrics stall — draft library coverage engineering task",
            rerun_allowed=not cooldown_active,
        )

    if classification.kind == CLASS_UNKNOWN:
        return LadderResponderDecision(
            action=ACTION_DRAFT_TASK,
            classification=classification,
            should_rerun=False,
            should_draft_task=True,
            reason="Unclassified ladder failure — draft supervised ops task",
            rerun_allowed=not cooldown_active,
        )

    if classification.kind == CLASS_CORRUPT_LAST_LADDER:
        if classification.workflow_fix_present:
            if cooldown_active:
                return LadderResponderDecision(
                    action=ACTION_NOOP,
                    classification=classification,
                    should_rerun=False,
                    should_draft_task=False,
                    reason=cooldown_reason,
                    rerun_allowed=False,
                )
            return LadderResponderDecision(
                action=ACTION_RERUN,
                classification=classification,
                should_rerun=True,
                should_draft_task=False,
                reason="Workflow fix is on main — guarded ladder rerun",
                rerun_allowed=True,
            )
        return LadderResponderDecision(
            action=ACTION_DRAFT_TASK,
            classification=classification,
            should_rerun=False,
            should_draft_task=True,
            reason="Corrupt last_ladder.json and workflow fix not yet on main",
            rerun_allowed=False,
        )

    # partial_success or transient
    if cooldown_active:
        return LadderResponderDecision(
            action=ACTION_NOOP,
            classification=classification,
            should_rerun=False,
            should_draft_task=False,
            reason=cooldown_reason,
            rerun_allowed=False,
        )
    return LadderResponderDecision(
        action=ACTION_RERUN,
        classification=classification,
        should_rerun=True,
        should_draft_task=False,
        reason=(
            "Partial ladder success — rerun to commit artifacts"
            if classification.kind == CLASS_PARTIAL_SUCCESS
            else "Transient failure — single guarded rerun"
        ),
        rerun_allowed=True,
    )


def append_responder_log_entry(
    entry: dict[str, Any],
    *,
    log_path: Path = DEFAULT_RESPONDER_LOG,
    max_entries: int = 100,
) -> dict[str, Any]:
    log = load_responder_log(log_path)
    log.setdefault("entries", []).append(entry)
    log["entries"] = list(log["entries"])[-max_entries:]
    log["updated_at"] = datetime.now(UTC).isoformat()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(log_path, log, compact=False)
    return entry


def respond_to_library_ladder_failure(
    log_text: str,
    *,
    run_id: int | str | None = None,
    run_url: str | None = None,
    ladder_json_path: Path = DEFAULT_LIBRARY_ROOT / "last_ladder.json",
    workflow_path: Path = DEFAULT_WORKFLOW_PATH,
    log_path: Path = DEFAULT_RESPONDER_LOG,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Classify a failed library-grow run and return the recovery decision payload."""
    now = now or datetime.now(UTC)
    classification = classify_library_ladder_failure(
        log_text,
        ladder_json_path=ladder_json_path,
        workflow_path=workflow_path,
    )
    decision = evaluate_library_ladder_response(classification, log_path=log_path, now=now)
    payload = {
        "run_id": str(run_id) if run_id is not None else None,
        "run_url": run_url,
        "recorded_at": now.isoformat(),
        **decision.to_dict(),
    }
    append_responder_log_entry(payload, log_path=log_path)
    return payload


__all__ = [
    "ACTION_DRAFT_TASK",
    "ACTION_NOOP",
    "ACTION_RERUN",
    "CLASS_CORRUPT_LAST_LADDER",
    "CLASS_METRICS_STALL",
    "CLASS_PARTIAL_SUCCESS",
    "CLASS_TRANSIENT",
    "CLASS_UNKNOWN",
    "DEFAULT_RESPONDER_LOG",
    "LadderFailureClassification",
    "LadderResponderDecision",
    "append_responder_log_entry",
    "classify_library_ladder_failure",
    "evaluate_library_ladder_response",
    "respond_to_library_ladder_failure",
    "rerun_cooldown_active",
    "workflow_fix_present",
]
