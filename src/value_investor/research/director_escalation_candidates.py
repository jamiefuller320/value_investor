"""Aggregate director escalation candidates for human approval (no auto-run)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import load_policy
from value_investor.research.director_shadow import (
    DEFAULT_DW_SHADOW_LOG,
    RECOMMEND_ESCALATE,
    RECOMMEND_RE_ESCALATE,
    load_shadow_log,
)
from value_investor.research.director_worker_cap import (
    check_director_worker_cap,
    director_worker_policy,
    iso_week_id,
)
from value_investor.storage import write_json

DEFAULT_ESCALATION_CANDIDATES_PATH = Path(
    "docs/data/research_director_worker/escalation_candidates.json"
)

CANDIDATE_ACTIONS = frozenset({RECOMMEND_ESCALATE, RECOMMEND_RE_ESCALATE})


@dataclass(frozen=True)
class DirectorEscalationCandidates:
    candidates: list[dict[str, Any]]
    cap_status: dict[str, Any]
    auto_escalate_enabled: bool
    surface_in_email: bool
    week_id: str
    generated_at: str
    source_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "week_id": self.week_id,
            "auto_escalate_enabled": self.auto_escalate_enabled,
            "surface_in_email": self.surface_in_email,
            "cap_status": self.cap_status,
            "source_counts": dict(self.source_counts),
            "candidates": list(self.candidates),
            "approval_note": (
                "Director–worker runs are not dispatched automatically. "
                "Approve with: ftse-research --director-worker <TICKER>"
            ),
        }


def _entry_timestamp(entry: dict[str, Any]) -> str:
    return str(entry.get("recorded_at") or entry.get("generated_at") or "")


def _entry_week_id(entry: dict[str, Any]) -> str | None:
    recorded = _entry_timestamp(entry)
    if not recorded:
        return None
    try:
        when = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
    except ValueError:
        return None
    return iso_week_id(when)


def _is_candidate(entry: dict[str, Any]) -> bool:
    return str(entry.get("recommended_action") or "") in CANDIDATE_ACTIONS


def _merge_candidate_entries(
    *,
    run_entries: list[dict[str, Any]] | None,
    shadow_log_path: Path,
    week_id: str | None,
) -> list[dict[str, Any]]:
    """Dedupe by ticker; prefer newest entry. Default scope: current ISO week."""
    week_id = week_id or iso_week_id()
    by_ticker: dict[str, dict[str, Any]] = {}

    log = load_shadow_log(shadow_log_path)
    for entry in log.get("entries") or []:
        if not isinstance(entry, dict) or not _is_candidate(entry):
            continue
        if _entry_week_id(entry) != week_id:
            continue
        ticker = str(entry.get("ticker") or "").upper()
        if not ticker:
            continue
        prior = by_ticker.get(ticker)
        if prior is None or _entry_timestamp(entry) >= _entry_timestamp(prior):
            by_ticker[ticker] = dict(entry)

    for entry in run_entries or []:
        if not isinstance(entry, dict) or not _is_candidate(entry):
            continue
        ticker = str(entry.get("ticker") or "").upper()
        if not ticker:
            continue
        merged = dict(entry)
        merged.setdefault("recorded_at", datetime.now(UTC).isoformat())
        prior = by_ticker.get(ticker)
        if prior is None or _entry_timestamp(merged) >= _entry_timestamp(prior):
            by_ticker[ticker] = merged

    ordered = sorted(
        by_ticker.values(),
        key=lambda row: (
            0 if row.get("recommended_action") == RECOMMEND_RE_ESCALATE else 1,
            str(row.get("ticker") or ""),
        ),
    )
    return ordered


def aggregate_escalation_candidates(
    *,
    run_entries: list[dict[str, Any]] | None = None,
    shadow_log_path: Path = DEFAULT_DW_SHADOW_LOG,
    week_id: str | None = None,
    policy_path: Path | None = None,
    when: datetime | None = None,
) -> DirectorEscalationCandidates:
    """Build approval queue from this run's shadow entries plus the weekly log."""
    when = when or datetime.now(UTC)
    week_id = week_id or iso_week_id(when)
    policy = load_policy(policy_path)
    dw_policy = director_worker_policy(policy)
    candidates = _merge_candidate_entries(
        run_entries=run_entries,
        shadow_log_path=shadow_log_path,
        week_id=week_id,
    )
    sample_ticker = str(candidates[0].get("ticker") or "") if candidates else ""
    cap = check_director_worker_cap(sample_ticker, policy_path=policy_path, when=when)
    source_counts: dict[str, int] = {}
    for entry in run_entries or []:
        action = str(entry.get("recommended_action") or "")
        source_counts[action] = source_counts.get(action, 0) + 1

    return DirectorEscalationCandidates(
        candidates=candidates,
        cap_status=cap.to_dict(),
        auto_escalate_enabled=bool(dw_policy.get("auto_escalate_director", False)),
        surface_in_email=bool(dw_policy.get("surface_escalation_candidates_in_email", True)),
        week_id=week_id,
        generated_at=when.isoformat(),
        source_counts=source_counts,
    )


def write_escalation_candidates(
    summary: DirectorEscalationCandidates,
    *,
    path: Path = DEFAULT_ESCALATION_CANDIDATES_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, summary.to_dict(), compact=False)
    return path


def load_escalation_candidates(
    path: Path = DEFAULT_ESCALATION_CANDIDATES_PATH,
) -> DirectorEscalationCandidates | None:
    if not path.exists():
        return None
    from value_investor.storage import read_json

    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return DirectorEscalationCandidates(
        candidates=list(payload.get("candidates") or []),
        cap_status=dict(payload.get("cap_status") or {}),
        auto_escalate_enabled=bool(payload.get("auto_escalate_enabled")),
        surface_in_email=bool(payload.get("surface_in_email", True)),
        week_id=str(payload.get("week_id") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        source_counts=dict(payload.get("source_counts") or {}),
    )


__all__ = [
    "CANDIDATE_ACTIONS",
    "DEFAULT_ESCALATION_CANDIDATES_PATH",
    "DirectorEscalationCandidates",
    "aggregate_escalation_candidates",
    "load_escalation_candidates",
    "write_escalation_candidates",
]
