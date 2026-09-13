"""Durable human acks for experiment_assessment recommend rows.

Sunday ``ftse-experiment-assess refresh`` rebuilds the ledger from evidence.
Acks live in ``docs/data/experiment_acks.json`` so a human read/ack is not
wiped. Matching is by experiment id plus leading finding key (for the DCA
overlay: ``leading_cadence``). A new leading cadence re-opens ack.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

ACKS_FILENAME = "experiment_acks.json"
ACK_DECISIONS = frozenset({"ack_observe"})


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def load_acks(data_dir: Path) -> dict[str, Any]:
    path = Path(data_dir) / ACKS_FILENAME
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return {"schema_version": 1, "acks": []}
    if not isinstance(raw, dict):
        return {"schema_version": 1, "acks": []}
    acks = [row for row in (raw.get("acks") or []) if isinstance(row, dict)]
    return {"schema_version": 1, "acks": acks, "updated_at": raw.get("updated_at")}


def finding_from_experiment(row: dict[str, Any] | None) -> dict[str, Any]:
    row = _as_dict(row)
    evidence = _as_dict(row.get("forward_evidence"))
    return {
        "leading_cadence": evidence.get("leading_cadence") or row.get("leading_cadence"),
        "ready_for_cadence_analysis": bool(
            evidence.get("ready_for_cadence_analysis") or row.get("ready_for_cadence_analysis")
        ),
        "scored_count": evidence.get("scored_count"),
        "tracks_with_closed": evidence.get("tracks_with_closed"),
        "model_independent_hint": evidence.get("model_independent_hint"),
    }


def matching_ack(
    acks: dict[str, Any] | None,
    *,
    experiment_id: str,
    finding: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    experiment_id = str(experiment_id or "").strip()
    if not experiment_id:
        return None
    finding = _as_dict(finding)
    lead = str(finding.get("leading_cadence") or "").strip() or None
    for row in (acks or {}).get("acks") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("experiment_id") or "") != experiment_id:
            continue
        if str(row.get("status") or "open") != "open":
            continue
        ack_lead = str((_as_dict(row.get("finding")).get("leading_cadence")) or "").strip() or None
        if lead and ack_lead and lead != ack_lead:
            continue
        return row
    return None


def apply_ack_to_experiment(row: dict[str, Any], acks: dict[str, Any] | None) -> dict[str, Any]:
    """Annotate a recommend row when a matching human ack exists. Never auto-applies."""
    if not isinstance(row, dict):
        return row
    if str(row.get("status") or "") != "recommend":
        return row
    hit = matching_ack(
        acks,
        experiment_id=str(row.get("experiment_id") or ""),
        finding=finding_from_experiment(row),
    )
    if not hit:
        return row
    row["human_ack_required"] = False
    row["human_acked"] = True
    row["acked_at"] = hit.get("acked_at")
    row["ack_decision"] = hit.get("decision")
    return row


def record_ack(
    data_dir: Path,
    *,
    experiment_id: str,
    decision: str = "ack_observe",
    note: str = "",
    finding: dict[str, Any] | None = None,
    source: str = "",
    acked_by: str = "human",
) -> dict[str, Any]:
    """Append or refresh an open ack. Returns the stored ack row."""
    experiment_id = str(experiment_id or "").strip()
    if not experiment_id:
        raise ValueError("experiment_id is required")
    decision = str(decision or "ack_observe").strip()
    if decision not in ACK_DECISIONS:
        raise ValueError(f"Unknown ack decision {decision!r}; allowed: {sorted(ACK_DECISIONS)}")
    store = load_acks(data_dir)
    finding = _as_dict(finding)
    existing = matching_ack(store, experiment_id=experiment_id, finding=finding)
    now = _utcnow()
    row = {
        "experiment_id": experiment_id,
        "decision": decision,
        "status": "open",
        "acked_at": now,
        "acked_by": acked_by,
        "note": str(note or "").strip(),
        "finding": finding,
        "source": str(source or "").strip(),
    }
    acks = list(store.get("acks") or [])
    if existing:
        acks = [item for item in acks if item is not existing]
    acks.append(row)
    payload = {"schema_version": 1, "updated_at": now, "acks": acks}
    dest = Path(data_dir) / ACKS_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, payload, compact=False)
    row["path"] = str(dest)
    return row
