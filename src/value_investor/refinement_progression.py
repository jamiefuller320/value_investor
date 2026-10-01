"""Post-graduation refinement progression (observe-only).

When an experiment graduates or is adopted, open the next **bounded**
refinement lane from a small policy table. "Applied" means the child is
**spawned and marked** on the assessment ledger with ``parent_id`` /
``refinement_of`` — never a mid-flight rewrite of the live graduated book,
and never silent live capital influence.

LLM paths stay fail-closed: no judge A/B lane without a concrete disagreement
theme and justifying evidence rules (see ``llm_agree_veto_shadow``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

LANES_FILENAME = "refinement_lanes.json"
REFINEMENT_KINDS = frozenset(
    {
        "lifecycle_overlay_refinement",
        "judge_spec_refinement",
        "refinement_satisfied",
    }
)

# Minimum veto-on-sell marks before an LLM/heuristic judge challenger may open.
DISAGREEMENT_THEME_VETO_SELL_MIN = 3
DISAGREEMENT_THEME_TRACK_MIN = 2


@dataclass(frozen=True)
class RefinementPolicy:
    """One graduation → next observe instrument mapping."""

    parent_id: str
    child_id: str | None
    title: str
    kind: str
    instrument: str
    graduation_triggers: tuple[str, ...]
    gate: str
    influences_live: bool = False
    llm_evidence_required: bool = False
    note: str = ""


# Small policy table — prefer observe / twin / cold-start; never mid-flight live rewrite.
REFINEMENT_POLICY: tuple[RefinementPolicy, ...] = (
    RefinementPolicy(
        parent_id="entry_dca_overlay",
        child_id="entry_dca_timing_shift_overlay",
        title="DCA timing-shift overlay cadences (Q1 post-graduation)",
        kind="lifecycle_overlay_refinement",
        instrument="observe_overlay_cadences",
        graduation_triggers=(
            "human_acked",
            "paper_execute_graduated_ready",
            "execute_started",
        ),
        gate="dca_completed_window_or_execute_stage",
        note=(
            "First post-graduation DCA refinement: front-load vs equal weekly "
            "as extra overlay cadences on existing episodes. No new paper book."
        ),
    ),
    RefinementPolicy(
        parent_id="entry_dca_timing_shift_overlay",
        child_id="entry_dca_tranche_count_overlay",
        title="DCA tranche-count overlay (Q2; after timing-shift marks)",
        kind="lifecycle_overlay_refinement",
        instrument="observe_overlay_cadences",
        graduation_triggers=("child_lane_observing",),
        gate="timing_shift_marks_thick",
        note="Prefer after Q1 timing-shift marks; keep ID/timing/size questions separate.",
    ),
    RefinementPolicy(
        parent_id="still_in_buy_set",
        child_id=None,
        title="Sell-gate churn twin already open",
        kind="refinement_satisfied",
        instrument="twin_already_open",
        graduation_triggers=("twin_present",),
        gate="always",
        note=(
            "still_in_buy_set Suite A twin is the capital-path churn instrument; "
            "do not spawn a duplicate sell-gate refinement book."
        ),
    ),
    RefinementPolicy(
        parent_id="llm_agree_veto_shadow",
        child_id="llm_agree_veto_judge_ab",
        title="LLM agree/veto judge-spec A/B challenger (observe-only)",
        kind="judge_spec_refinement",
        instrument="observe_judge_spec_ab",
        graduation_triggers=("disagreement_theme",),
        gate="disagreement_theme_present",
        llm_evidence_required=True,
        note=(
            "Fail-closed: open only after multi-track veto-on-sell disagreement "
            "theme vs still_in_buy_set; challenger still influences_live=false."
        ),
    ),
)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _safe_read(path: Path) -> dict[str, Any]:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return {}
    return raw if isinstance(raw, dict) else {}


def load_refinement_lanes(data_dir: Path) -> dict[str, Any]:
    path = Path(data_dir) / LANES_FILENAME
    raw = _safe_read(path)
    if not raw:
        return {"schema_version": 1, "lanes": [], "satisfied": []}
    lanes = [row for row in (raw.get("lanes") or []) if isinstance(row, dict)]
    satisfied = [row for row in (raw.get("satisfied") or []) if isinstance(row, dict)]
    return {
        "schema_version": int(raw.get("schema_version") or 1),
        "lanes": lanes,
        "satisfied": satisfied,
        "updated_at": raw.get("updated_at"),
    }


def save_refinement_lanes(data_dir: Path, store: dict[str, Any]) -> Path:
    dest = Path(data_dir) / LANES_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": _utcnow(),
        "observe_only": True,
        "influences_live": False,
        "lanes": list(store.get("lanes") or []),
        "satisfied": list(store.get("satisfied") or []),
        "note": (
            "Graduation → refinement marks only. Not a dashboard registry; "
            "lineage lives on experiment_assessment rows (parent_id / refinement_of)."
        ),
    }
    write_json(dest, payload, compact=False)
    return dest


def disagreement_theme_ready(agree_veto_rollup: dict[str, Any] | None) -> dict[str, Any]:
    """Fail-closed gate for LLM/heuristic judge A/B challenger."""
    tracks = _as_dict(_as_dict(agree_veto_rollup).get("tracks"))
    veto_sell_total = 0
    tracks_with_veto = 0
    for row in tracks.values():
        if not isinstance(row, dict):
            continue
        count = int(row.get("veto_sell_count") or 0)
        if count <= 0:
            continue
        veto_sell_total += count
        tracks_with_veto += 1
    ready = (
        tracks_with_veto >= DISAGREEMENT_THEME_TRACK_MIN
        and veto_sell_total >= DISAGREEMENT_THEME_VETO_SELL_MIN
    )
    return {
        "ready": ready,
        "veto_sell_total": veto_sell_total,
        "tracks_with_veto": tracks_with_veto,
        "veto_sell_min": DISAGREEMENT_THEME_VETO_SELL_MIN,
        "tracks_min": DISAGREEMENT_THEME_TRACK_MIN,
        "fail_closed": not ready,
        "note": (
            "Judge-spec A/B stays closed until multi-track veto-on-sell marks "
            "show a concrete disagreement theme."
            if not ready
            else "Disagreement theme threshold met — observe-only A/B lane may open."
        ),
    }


def progression_triggers() -> list[dict[str, Any]]:
    """Documented triggers for ops / Sunday review (observe-only)."""
    return [
        {
            "id": "dca_timing_shift_after_graduation",
            "when": (
                "entry_dca_overlay human-acked, paper_execute_graduated ready, "
                "or execute_started — and cadence analysis / completed-window readiness"
            ),
            "open": "entry_dca_timing_shift_overlay",
            "mode": "observe_overlay_cadences",
            "do_not": "Mid-flight rewrite of graduated_allocation cadence or primary books",
        },
        {
            "id": "dca_tranche_count_after_timing_shift",
            "when": "Timing-shift child lane observing with thick completed-window marks",
            "open": "entry_dca_tranche_count_overlay",
            "mode": "observe_overlay_cadences",
            "do_not": "Open dynamic sizing (Q3) before fixed timing/count marks",
        },
        {
            "id": "sell_gate_twin_already_open",
            "when": "Sell/churn gate graduates or is adopted",
            "open": None,
            "mode": "twin_already_open",
            "do_not": "Spawn a second sell-gate paper book; use still_in_buy_set twin",
        },
        {
            "id": "llm_judge_ab_after_disagreement_theme",
            "when": (
                f"learning_tracks_llm_agree_veto shows ≥{DISAGREEMENT_THEME_TRACK_MIN} tracks "
                f"with veto-on-sell and ≥{DISAGREEMENT_THEME_VETO_SELL_MIN} veto_sell total"
            ),
            "open": "llm_agree_veto_judge_ab",
            "mode": "observe_judge_spec_ab",
            "do_not": (
                "Hard veto or live prompt swap — N173/L510; challenger influences_live=false"
            ),
        },
    ]


def _experiments_by_id(experiments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in experiments:
        if not isinstance(row, dict):
            continue
        exp_id = str(row.get("experiment_id") or "").strip()
        if exp_id:
            out[exp_id] = row
    return out


def _lane_open(store: dict[str, Any], child_id: str) -> dict[str, Any] | None:
    for row in store.get("lanes") or []:
        if isinstance(row, dict) and str(row.get("child_id") or "") == child_id:
            if str(row.get("status") or "open") == "open":
                return row
    return None


def _dca_gate_ready(adoption: dict[str, Any] | None) -> tuple[bool, str]:
    adoption = _as_dict(adoption)
    finding = _as_dict(adoption.get("finding"))
    stages = [row for row in (adoption.get("stages") or []) if isinstance(row, dict)]
    execute_row = next((row for row in stages if row.get("id") == "paper_execute_graduated"), {})
    if bool(adoption.get("execute_started")):
        return True, "execute_started"
    if bool(execute_row.get("ready")):
        return True, "paper_execute_graduated_ready"
    if bool(adoption.get("acked")) and bool(finding.get("ready_for_cadence_analysis")):
        return True, "human_acked"
    return False, "dca_not_ready"


def _parent_graduation_signal(
    policy: RefinementPolicy,
    *,
    experiments_by_id: dict[str, dict[str, Any]],
    adoption: dict[str, Any] | None,
    agree_veto_rollup: dict[str, Any] | None,
    paper_root: Path,
) -> tuple[bool, str]:
    """Return (graduated, signal_id). Fail-closed when unsure."""
    if policy.parent_id == "entry_dca_overlay":
        ready, signal = _dca_gate_ready(adoption)
        if ready and signal in policy.graduation_triggers:
            return True, signal
        return False, signal

    if policy.parent_id == "entry_dca_timing_shift_overlay":
        parent = experiments_by_id.get(policy.parent_id) or {}
        if not parent:
            return False, "timing_shift_lane_missing"
        # Thin scaffold: do not auto-open Q2 until the child has been observing
        # and someone has marked thick timing-shift evidence (forward_evidence flag).
        evidence = _as_dict(parent.get("forward_evidence"))
        if bool(evidence.get("timing_shift_marks_thick")):
            return True, "child_lane_observing"
        return False, "timing_shift_marks_thin"

    if policy.parent_id == "still_in_buy_set":
        twin_dir = Path(paper_root) / "still_in_buy_set"
        if twin_dir.exists():
            return True, "twin_present"
        return False, "twin_missing"

    if policy.parent_id == "llm_agree_veto_shadow":
        theme = disagreement_theme_ready(agree_veto_rollup)
        if theme["ready"]:
            return True, "disagreement_theme"
        return False, "disagreement_theme_absent"

    parent = experiments_by_id.get(policy.parent_id) or {}
    if parent.get("human_acked") or (
        parent.get("status") == "recommend" and parent.get("human_acked")
    ):
        return True, "human_acked"
    return False, "parent_not_graduated"


def _child_row(
    policy: RefinementPolicy,
    *,
    signal: str,
    opened_at: str,
) -> dict[str, Any]:
    assert policy.child_id
    return {
        "experiment_id": policy.child_id,
        "kind": policy.kind,
        "title": policy.title,
        "area": "paper_churn" if "dca" in policy.child_id else "paper_knobs",
        "pipeline": "refinement_progression",
        "status": "proposed",
        "source_status": "graduation_hook",
        "human_ack_required": False,
        "parent_id": policy.parent_id,
        "refinement_of": policy.parent_id,
        "observe_only": True,
        "influences_live": False,
        "refinement_instrument": policy.instrument,
        "forward_evidence": {
            "source": "refinement_progression",
            "opened_by": "graduation_hook",
            "opened_at": opened_at,
            "graduation_signal": signal,
            "gate": policy.gate,
            "llm_evidence_required": policy.llm_evidence_required,
            "note": policy.note,
        },
        "evidence_path": None,
        "initiated_at": opened_at,
    }


def preserve_lineage_fields(
    row: dict[str, Any],
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    """Copy parent_id / refinement_of / superseded_by from prior when unset."""
    prior = _as_dict(prior)
    for key in ("parent_id", "refinement_of", "superseded_by"):
        if row.get(key):
            continue
        if prior.get(key):
            row[key] = prior[key]
    # Keep aliases aligned when only one is set.
    if row.get("parent_id") and not row.get("refinement_of"):
        row["refinement_of"] = row["parent_id"]
    if row.get("refinement_of") and not row.get("parent_id"):
        row["parent_id"] = row["refinement_of"]
    return row


def merge_preserved_refinement_rows(
    experiments: list[dict[str, Any]],
    previous_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Re-attach prior refinement children that evidence rebuild does not emit."""
    known = {
        str(row.get("experiment_id") or "")
        for row in experiments
        if isinstance(row, dict) and row.get("experiment_id")
    }
    for exp_id, prior in previous_by_id.items():
        if exp_id in known:
            continue
        if not isinstance(prior, dict):
            continue
        kind = str(prior.get("kind") or "")
        if kind not in REFINEMENT_KINDS and not (
            prior.get("parent_id") or prior.get("refinement_of")
        ):
            continue
        experiments.append(dict(prior))
        known.add(exp_id)
    return experiments


def apply_graduation_refinements(
    experiments: list[dict[str, Any]],
    *,
    data_dir: Path,
    paper_root: Path,
    adoption: dict[str, Any] | None = None,
    agree_veto_rollup: dict[str, Any] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Open next observe refinement lanes when parents graduate.

    Mutates ``experiments`` in place. Returns a summary of opened / skipped /
    satisfied actions. Never sets influences_live; never edits live book config.
    """
    data_dir = Path(data_dir)
    paper_root = Path(paper_root)
    store = load_refinement_lanes(data_dir)
    by_id = _experiments_by_id(experiments)
    opened: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    satisfied: list[dict[str, Any]] = []
    now = _utcnow()

    if agree_veto_rollup is None:
        agree_veto_rollup = _safe_read(paper_root / "learning_tracks_llm_agree_veto.json")

    for policy in REFINEMENT_POLICY:
        graduated, signal = _parent_graduation_signal(
            policy,
            experiments_by_id=by_id,
            adoption=adoption,
            agree_veto_rollup=agree_veto_rollup,
            paper_root=paper_root,
        )
        if not graduated:
            skipped.append(
                {
                    "parent_id": policy.parent_id,
                    "child_id": policy.child_id,
                    "reason": signal,
                    "gate": policy.gate,
                }
            )
            continue

        if policy.child_id is None:
            # Satisfied without spawning (e.g. sell-gate twin already open).
            mark = {
                "parent_id": policy.parent_id,
                "instrument": policy.instrument,
                "graduation_signal": signal,
                "noted_at": now,
                "title": policy.title,
                "note": policy.note,
            }
            existing_sat = [
                row
                for row in (store.get("satisfied") or [])
                if isinstance(row, dict) and row.get("parent_id") == policy.parent_id
            ]
            if not existing_sat:
                store.setdefault("satisfied", []).append(mark)
            satisfied.append(mark)
            continue

        if policy.llm_evidence_required:
            theme = disagreement_theme_ready(agree_veto_rollup)
            if not theme["ready"]:
                skipped.append(
                    {
                        "parent_id": policy.parent_id,
                        "child_id": policy.child_id,
                        "reason": "llm_fail_closed_no_disagreement_theme",
                        "theme": theme,
                    }
                )
                continue

        existing_lane = _lane_open(store, policy.child_id)
        if policy.child_id in by_id or existing_lane:
            skipped.append(
                {
                    "parent_id": policy.parent_id,
                    "child_id": policy.child_id,
                    "reason": "already_open",
                    "graduation_signal": signal,
                }
            )
            # Ensure lineage fields on existing assessment row.
            if policy.child_id in by_id:
                preserve_lineage_fields(
                    by_id[policy.child_id],
                    {
                        "parent_id": policy.parent_id,
                        "refinement_of": policy.parent_id,
                    },
                )
            continue

        child = _child_row(policy, signal=signal, opened_at=now)
        experiments.append(child)
        by_id[policy.child_id] = child
        lane = {
            "child_id": policy.child_id,
            "parent_id": policy.parent_id,
            "status": "open",
            "opened_at": now,
            "graduation_signal": signal,
            "instrument": policy.instrument,
            "kind": policy.kind,
            "observe_only": True,
            "influences_live": False,
            "title": policy.title,
        }
        store.setdefault("lanes", []).append(lane)
        opened.append(lane)

        # Parent stays marked; child is the live complexity slot for the next question.
        parent = by_id.get(policy.parent_id)
        if parent is not None:
            parent.setdefault("superseded_by", policy.child_id)

    if persist and (opened or satisfied):
        save_refinement_lanes(data_dir, store)

    return {
        "observe_only": True,
        "influences_live": False,
        "opened": opened,
        "skipped": skipped,
        "satisfied": satisfied,
        "progression_triggers": progression_triggers(),
        "lanes_path": str(Path(data_dir) / LANES_FILENAME),
    }


__all__ = [
    "DISAGREEMENT_THEME_TRACK_MIN",
    "DISAGREEMENT_THEME_VETO_SELL_MIN",
    "LANES_FILENAME",
    "REFINEMENT_KINDS",
    "REFINEMENT_POLICY",
    "RefinementPolicy",
    "apply_graduation_refinements",
    "disagreement_theme_ready",
    "load_refinement_lanes",
    "merge_preserved_refinement_rows",
    "preserve_lineage_fields",
    "progression_triggers",
    "save_refinement_lanes",
]
