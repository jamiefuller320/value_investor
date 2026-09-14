"""Dashboard Start for lifecycle recommend cards (observe-ack via Supabase).

Start never auto-applies DCA, starter fraction, or primary/live knobs. The only
supported dashboard action is recording ``ack_observe`` for a recommend row,
then refreshing assessment + lifecycle board artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.entry_dca_adoption import (
    evaluate_entry_dca_adoption_plan,
    first_entry_by_track,
    write_entry_dca_adoption_plan,
)
from value_investor.experiment_acks import record_ack
from value_investor.experiment_assessment import (
    ASSESSMENT_FILENAME,
    refresh_experiment_assessment,
)
from value_investor.lifecycle_board import (
    DEFAULT_LATEST_PATH,
    DEFAULT_LIFECYCLE_BOARD_PATH,
    write_lifecycle_board,
)
from value_investor.storage import read_json

DEFAULT_DATA_DIR = Path("docs/data")
START_DECISION = "ack_observe"
SUPPORTED_START_KINDS = frozenset({"human_ack"})


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


def run_lifecycle_experiment_start(
    data_dir: Path | None = None,
    *,
    experiment_id: str,
    factor_id: str | None = None,
    kind: str | None = None,
    decision: str = START_DECISION,
    note: str = "",
    source: str = "dashboard_bridge",
    acked_by: str = "dashboard",
    paper_root: Path | None = None,
    refresh_board: bool = True,
) -> dict[str, Any]:
    """Record observe-ack from a dashboard Start click and refresh artifacts."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    paper_root = Path(paper_root or data_dir / "paper_automation")
    experiment_id = str(experiment_id or "").strip()
    if not experiment_id:
        raise ValueError("experiment_id is required")
    kind_key = str(kind or "human_ack").strip() or "human_ack"
    if kind_key not in SUPPORTED_START_KINDS:
        raise ValueError(
            f"Dashboard Start only supports {sorted(SUPPORTED_START_KINDS)}; got {kind_key!r}"
        )
    decision_key = str(decision or START_DECISION).strip() or START_DECISION
    if decision_key != START_DECISION:
        raise ValueError(f"Dashboard Start only records {START_DECISION!r}; got {decision_key!r}")

    finding = _finding_for_experiment(data_dir, paper_root, experiment_id)
    ack_note = str(note or "").strip()
    if factor_id and "factor=" not in ack_note:
        ack_note = f"{ack_note} factor={factor_id}".strip()
    ack = record_ack(
        data_dir,
        experiment_id=experiment_id,
        decision=decision_key,
        note=ack_note,
        finding=finding,
        source=source,
        acked_by=acked_by,
    )
    assessment = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    adoption = None
    if experiment_id == "entry_dca_overlay":
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
        "ack": ack,
        "assessment_summary": assessment.get("summary"),
        "adoption_stage": None if not isinstance(adoption, dict) else adoption.get("current_stage"),
        "lifecycle_board_path": None if board_path is None else str(board_path),
        "factor_id": factor_id,
        "experiment_id": experiment_id,
        "kind": kind_key,
        "decision": decision_key,
        "observe_only": True,
    }


__all__ = [
    "START_DECISION",
    "SUPPORTED_START_KINDS",
    "run_lifecycle_experiment_start",
]
