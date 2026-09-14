"""Dashboard Start for lifecycle recommend cards (graduated execute via Supabase).

Start never auto-applies on Sunday refresh. When the adoption stage
``paper_execute_graduated`` is ready, a human Start click authorizes and enables
4× weekly entry DCA on ``graduated_allocation`` only. Acknowledge remains the
observe-ack path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.entry_dca_adoption import (
    evaluate_entry_dca_adoption_plan,
    first_entry_by_track,
    write_entry_dca_adoption_plan,
)
from value_investor.entry_dca_execute import (
    DEFAULT_EXECUTE_CADENCE,
    DEFAULT_EXECUTE_TRACK,
    enable_graduated_entry_dca_execute,
    resolve_cadence,
)
from value_investor.experiment_assessment import (
    ASSESSMENT_FILENAME,
    refresh_experiment_assessment,
)
from value_investor.experiment_starts import matching_start, record_start, load_starts
from value_investor.lifecycle_board import (
    DEFAULT_LATEST_PATH,
    DEFAULT_LIFECYCLE_BOARD_PATH,
    write_lifecycle_board,
)
from value_investor.storage import read_json

DEFAULT_DATA_DIR = Path("docs/data")
START_DECISION = "start_execute_graduated"
SUPPORTED_START_KINDS = frozenset({"optional_execute"})
EXECUTE_STAGE_ID = "paper_execute_graduated"


def _finding_for_experiment(data_dir: Path, paper_root: Path, experiment_id: str) -> dict[str, Any]:
    assessment_path = data_dir / ASSESSMENT_FILENAME
    try:
        payload = read_json(assessment_path)
    except FileNotFoundError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    row: dict[str, Any] = {}
    for item in payload.get("experiments") or []:
        if isinstance(item, dict) and str(item.get("experiment_id") or "") == experiment_id:
            row = item
            break
    evidence = row.get("forward_evidence") if isinstance(row.get("forward_evidence"), dict) else {}
    try:
        rollup = read_json(paper_root / "learning_tracks_entry_dca.json")
    except FileNotFoundError:
        rollup = {}
    if not isinstance(rollup, dict):
        rollup = {}
    return {
        "leading_cadence": evidence.get("leading_cadence") or rollup.get("leading_cadence"),
        "ready_for_cadence_analysis": bool(
            evidence.get("ready_for_cadence_analysis")
            or (rollup.get("readiness") or {}).get("ready_for_cadence_analysis")
        ),
        "scored_count": evidence.get("scored_count") or rollup.get("scored_count"),
        "tracks_with_closed": evidence.get("tracks_with_closed")
        or rollup.get("tracks_with_closed"),
        "model_independent_hint": (
            evidence.get("model_independent_hint")
            if "model_independent_hint" in evidence
            else rollup.get("model_independent_hint")
        ),
        "first_entry_by_track": first_entry_by_track(rollup),
    }


def _require_execute_ready(adoption: dict[str, Any]) -> dict[str, Any]:
    current = str(adoption.get("current_stage") or "")
    stages = [row for row in (adoption.get("stages") or []) if isinstance(row, dict)]
    current_row = next((row for row in stages if row.get("id") == current), None) or {}
    if current != EXECUTE_STAGE_ID or not bool(current_row.get("ready")):
        raise ValueError(
            "Start execute requires adoption stage "
            f"{EXECUTE_STAGE_ID!r} ready; current={current!r} ready={current_row.get('ready')!r}"
        )
    return current_row


def run_lifecycle_experiment_start(
    data_dir: Path | None = None,
    *,
    experiment_id: str,
    factor_id: str | None = None,
    kind: str | None = None,
    decision: str = START_DECISION,
    note: str = "",
    source: str = "dashboard_bridge",
    started_by: str = "dashboard",
    acked_by: str | None = None,
    paper_root: Path | None = None,
    refresh_board: bool = True,
    track_id: str = DEFAULT_EXECUTE_TRACK,
    cadence: str | None = None,
) -> dict[str, Any]:
    """Authorize + enable graduated entry DCA execute from a dashboard Start click."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    paper_root = Path(paper_root or data_dir / "paper_automation")
    experiment_id = str(experiment_id or "").strip()
    if not experiment_id:
        raise ValueError("experiment_id is required")
    if experiment_id != "entry_dca_overlay":
        raise ValueError(
            "Dashboard Start execute currently supports entry_dca_overlay only; "
            f"got {experiment_id!r}"
        )
    kind_key = str(kind or "optional_execute").strip() or "optional_execute"
    if kind_key not in SUPPORTED_START_KINDS:
        raise ValueError(
            f"Dashboard Start only supports {sorted(SUPPORTED_START_KINDS)}; got {kind_key!r}. "
            "Use lifecycle-experiment-ack for observe-ack."
        )
    decision_key = str(decision or START_DECISION).strip() or START_DECISION
    if decision_key != START_DECISION:
        raise ValueError(f"Dashboard Start only records {START_DECISION!r}; got {decision_key!r}")

    track_key = str(track_id or DEFAULT_EXECUTE_TRACK).strip() or DEFAULT_EXECUTE_TRACK
    if track_key != DEFAULT_EXECUTE_TRACK:
        raise ValueError(
            f"Start execute is allowed only on {DEFAULT_EXECUTE_TRACK!r}; got {track_key!r}"
        )

    finding = _finding_for_experiment(data_dir, paper_root, experiment_id)
    cadence_key = (
        str(cadence or "").strip()
        or str(finding.get("leading_cadence") or "").strip()
        or DEFAULT_EXECUTE_CADENCE
    )
    if resolve_cadence(cadence_key) is None:
        raise ValueError(f"Unknown cadence {cadence_key!r}")

    existing = matching_start(load_starts(data_dir), experiment_id=experiment_id, finding=finding)
    if existing:
        raise ValueError(
            "Graduated entry DCA execute already started for this finding "
            f"(started_at={existing.get('started_at')})"
        )

    adoption = evaluate_entry_dca_adoption_plan(data_dir=data_dir, paper_root=paper_root)
    _require_execute_ready(adoption)

    start_note = str(note or "").strip()
    if factor_id and "factor=" not in start_note:
        start_note = f"{start_note} factor={factor_id}".strip()
    actor = str(started_by or acked_by or "dashboard").strip() or "dashboard"
    start = record_start(
        data_dir,
        experiment_id=experiment_id,
        decision=decision_key,
        note=start_note,
        finding=finding,
        source=source,
        started_by=actor,
        track_id=track_key,
        cadence=cadence_key,
    )
    enabled = enable_graduated_entry_dca_execute(
        paper_root, cadence=cadence_key, track_id=track_key
    )
    assessment = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    adoption = evaluate_entry_dca_adoption_plan(data_dir=data_dir, paper_root=paper_root)
    write_entry_dca_adoption_plan(adoption, data_dir=data_dir)
    board_path = None
    if refresh_board:
        board_path = write_lifecycle_board(
            latest_path=data_dir / Path(DEFAULT_LATEST_PATH).name,
            assessment_path=data_dir / ASSESSMENT_FILENAME,
            path=data_dir / Path(DEFAULT_LIFECYCLE_BOARD_PATH).name,
        )
    return {
        "ok": True,
        "start": start,
        "enabled": enabled,
        "assessment_summary": assessment.get("summary"),
        "adoption_stage": adoption.get("current_stage"),
        "lifecycle_board_path": None if board_path is None else str(board_path),
        "factor_id": factor_id,
        "experiment_id": experiment_id,
        "kind": kind_key,
        "decision": decision_key,
        "observe_only": False,
        "track_id": track_key,
        "cadence": cadence_key,
    }


__all__ = [
    "START_DECISION",
    "SUPPORTED_START_KINDS",
    "EXECUTE_STAGE_ID",
    "run_lifecycle_experiment_start",
]
