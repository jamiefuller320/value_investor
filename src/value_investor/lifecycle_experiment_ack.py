"""Dashboard Acknowledge for lifecycle recommend cards (observe-ack via Supabase).

Acknowledge never executes DCA, changes starter fraction, or touches primary/live
knobs. It only records ``ack_observe`` for a recommend row, then refreshes
assessment + lifecycle board artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.entry_dca_adoption import (
    evaluate_entry_dca_adoption_plan,
    first_entry_by_track,
    write_entry_dca_adoption_plan,
)
from value_investor.experiment_acks import (
    canonical_experiment_id,
    experiment_id_aliases,
    record_ack,
)
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
ACK_DECISION = "ack_observe"
SUPPORTED_ACK_KINDS = frozenset({"human_ack"})


def _assessment_experiment_ids(payload: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in payload.get("experiments") or []:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("experiment_id") or "").strip()
        if eid:
            ids.add(eid)
        track = str(item.get("track_id") or "").strip()
        if track:
            ids.add(track)
    return ids


def _assessment_row(payload: dict[str, Any], experiment_id: str) -> dict[str, Any]:
    aliases = experiment_id_aliases(experiment_id)
    for item in payload.get("experiments") or []:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("experiment_id") or "").strip()
        track = str(item.get("track_id") or "").strip()
        if eid in aliases or track in aliases:
            return item
    return {}


def _finding_for_experiment(data_dir: Path, paper_root: Path, experiment_id: str) -> dict[str, Any]:
    assessment_path = data_dir / ASSESSMENT_FILENAME
    try:
        payload = read_json(assessment_path)
    except FileNotFoundError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    row = _assessment_row(payload, experiment_id)
    evidence = row.get("forward_evidence") if isinstance(row.get("forward_evidence"), dict) else {}
    try:
        rollup = read_json(paper_root / "learning_tracks_entry_dca.json")
    except FileNotFoundError:
        rollup = {}
    if not isinstance(rollup, dict):
        rollup = {}
    # Track recommend rows (e.g. graduated_allocation) do not carry DCA forward_evidence;
    # only fall back to the entry-DCA rollup when the ledger row is that overlay.
    use_rollup = str(row.get("experiment_id") or "") == "entry_dca_overlay" or not row
    finding: dict[str, Any] = {
        "leading_cadence": evidence.get("leading_cadence")
        or (rollup.get("leading_cadence") if use_rollup else None),
        "ready_for_cadence_analysis": bool(
            evidence.get("ready_for_cadence_analysis")
            or (
                (rollup.get("readiness") or {}).get("ready_for_cadence_analysis")
                if use_rollup
                else False
            )
        ),
        "scored_count": evidence.get("scored_count")
        or (rollup.get("scored_count") if use_rollup else None),
        "tracks_with_closed": evidence.get("tracks_with_closed")
        or (rollup.get("tracks_with_closed") if use_rollup else None),
        "model_independent_hint": (
            evidence.get("model_independent_hint")
            if "model_independent_hint" in evidence
            else (rollup.get("model_independent_hint") if use_rollup else None)
        ),
    }
    if use_rollup:
        finding["first_entry_by_track"] = first_entry_by_track(rollup)
    if row.get("gate_marks") is not None:
        finding["gate_marks"] = row.get("gate_marks")
    if row.get("gate_excess_after_costs") is not None:
        finding["gate_excess_after_costs"] = row.get("gate_excess_after_costs")
    return finding


def run_lifecycle_experiment_ack(
    data_dir: Path | None = None,
    *,
    experiment_id: str,
    factor_id: str | None = None,
    kind: str | None = None,
    decision: str = ACK_DECISION,
    note: str = "",
    source: str = "dashboard_bridge",
    acked_by: str = "dashboard",
    paper_root: Path | None = None,
    refresh_board: bool = True,
) -> dict[str, Any]:
    """Record observe-ack from a dashboard Acknowledge click and refresh artifacts."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    paper_root = Path(paper_root or data_dir / "paper_automation")
    experiment_id = str(experiment_id or "").strip()
    if not experiment_id:
        raise ValueError("experiment_id is required")
    kind_key = str(kind or "human_ack").strip() or "human_ack"
    if kind_key not in SUPPORTED_ACK_KINDS:
        raise ValueError(
            f"Dashboard Acknowledge only supports {sorted(SUPPORTED_ACK_KINDS)}; got {kind_key!r}"
        )
    decision_key = str(decision or ACK_DECISION).strip() or ACK_DECISION
    if decision_key != ACK_DECISION:
        raise ValueError(
            f"Dashboard Acknowledge only records {ACK_DECISION!r}; got {decision_key!r}"
        )

    try:
        assessment_payload = read_json(data_dir / ASSESSMENT_FILENAME)
    except FileNotFoundError:
        assessment_payload = {}
    if not isinstance(assessment_payload, dict):
        assessment_payload = {}
    known_ids = _assessment_experiment_ids(assessment_payload)
    ledger_experiment_id = canonical_experiment_id(experiment_id, known_ids=known_ids)
    finding = _finding_for_experiment(data_dir, paper_root, ledger_experiment_id)
    ack_note = str(note or "").strip()
    if factor_id and "factor=" not in ack_note:
        ack_note = f"{ack_note} factor={factor_id}".strip()
    ack = record_ack(
        data_dir,
        experiment_id=ledger_experiment_id,
        decision=decision_key,
        note=ack_note,
        finding=finding,
        source=source,
        acked_by=acked_by,
        known_ids=known_ids,
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
        "experiment_id": ledger_experiment_id,
        "requested_experiment_id": experiment_id,
        "kind": kind_key,
        "decision": decision_key,
        "observe_only": True,
    }


__all__ = [
    "ACK_DECISION",
    "SUPPORTED_ACK_KINDS",
    "run_lifecycle_experiment_ack",
]
