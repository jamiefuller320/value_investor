"""Alone-path interestingness vs sample-thickness for sealed observe strands.

Owner lock 2026-10-31 (``volume-gates-redesign-2026-10-31``):

* **Sample-thickness** (``volume_gate.met`` = episodes ∧ weeks) = quiet
  pipeline badge / info noise — not Push heat.
* **Alone-path interestingness** = the only volume-adjacent finding that may
  raise human Push / checklist heat.

Still **F8**: no auto-promote, no ``decision-review --apply``, no second live
path. No peer NAV / MoM-vs-peer-book for these strands (MoM stays Package M /
MFT lab).
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1

N200_INTERESTINGNESS_TITLE = (
    "N200 alone-path interesting — promotion design optional (F8)"
)
N201_INTERESTINGNESS_TITLE = (
    "N201 alone-path interesting — promotion design optional (F8)"
)
N206_INTERESTINGNESS_TITLE = (
    "N206 alone-path interesting — promotion design optional (F8)"
)
N210_INTERESTINGNESS_TITLE = (
    "N210 alone-path interesting — promotion design optional (F8)"
)

VOLUME_THICKNESS_SUMMARY_SUFFIX = (
    "Sample-thickness / pipeline badge only — not promotion-design heat. "
    "No auto-promote (F8)."
)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def thickness_met(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    volume = payload.get("volume_gate")
    if not isinstance(volume, dict):
        return False
    return bool(volume.get("met"))


def _base(
    *,
    thick: bool,
    fair: float | None,
    fair_ok: bool,
    met: bool,
    rule: str,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "met": bool(met),
        "thickness_met": bool(thick),
        "fair_cost_median": fair,
        "fair_cost_median_ok": bool(fair_ok),
        "rule": rule,
        "not_auto_promote": True,
        "influences_live": False,
        "peer_nav_forbidden": True,
        "mom_peer_book_forbidden": True,
    }
    if extras:
        out.update(extras)
    return out


def evaluate_n200_interestingness(payload: dict[str, Any]) -> dict[str, Any]:
    """Thickness ∧ fair control median > 0 ∧ exit lever ≠ lose."""
    thick = thickness_met(payload)
    path = payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    fair = _as_float(path.get("control_smooth_ret_cohort_median"))
    levers = (
        payload.get("per_lever_scoreboards")
        if isinstance(payload.get("per_lever_scoreboards"), dict)
        else {}
    )
    exit_v = levers.get("exit_verdict")
    fair_ok = fair is not None and fair > 0.0
    exit_ok = exit_v is not None and str(exit_v) != "lose"
    met = thick and fair_ok and exit_ok
    return _base(
        thick=thick,
        fair=fair,
        fair_ok=fair_ok,
        met=met,
        rule="thickness && control_smooth_ret_cohort_median > 0 && exit_lever != lose",
        extras={"exit_lever": exit_v, "exit_lever_ok": exit_ok},
    )


def evaluate_n201_interestingness(payload: dict[str, Any]) -> dict[str, Any]:
    """Thickness ∧ phase floor ∧ fair median > 0 ∧ patient-hold excess > 0."""
    thick = thickness_met(payload)
    path = payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    phase = payload.get("phase") if isinstance(payload.get("phase"), dict) else {}
    fair = _as_float(path.get("smooth_ret_cohort_median"))
    excess = _as_float(path.get("patient_hold_excess_report_only"))
    phase_ok = bool(phase.get("floor_met"))
    fair_ok = fair is not None and fair > 0.0
    excess_ok = excess is not None and excess > 0.0
    met = thick and phase_ok and fair_ok and excess_ok
    return _base(
        thick=thick,
        fair=fair,
        fair_ok=fair_ok,
        met=met,
        rule=(
            "thickness && phase_floor_met && smooth_ret_cohort_median > 0 "
            "&& patient_hold_excess_report_only > 0"
        ),
        extras={
            "phase_floor_met": phase_ok,
            "patient_hold_excess": excess,
            "patient_hold_excess_ok": excess_ok,
        },
    )


def evaluate_n206_interestingness(payload: dict[str, Any]) -> dict[str, Any]:
    """Thickness ∧ fair median > 0; alone-first — never assessment crown."""
    thick = thickness_met(payload)
    path = payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    fair = _as_float(path.get("smooth_ret_cohort_median"))
    fair_ok = fair is not None and fair > 0.0
    met = thick and fair_ok
    return _base(
        thick=thick,
        fair=fair,
        fair_ok=fair_ok,
        met=met,
        rule="thickness && smooth_ret_cohort_median > 0 (alone; no assessment crown)",
        extras={
            "alone_first": True,
            "not_assessment_primary": True,
        },
    )


def evaluate_n210_interestingness(payload: dict[str, Any]) -> dict[str, Any]:
    """After thickness: fair median > 0. Matched-30 crown stays on B3 gates."""
    thick = thickness_met(payload)
    path = payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    fair = _as_float(path.get("smooth_ret_cohort_median"))
    fair_ok = fair is not None and fair > 0.0
    met = thick and fair_ok
    return _base(
        thick=thick,
        fair=fair,
        fair_ok=fair_ok,
        met=met,
        rule="thickness && smooth_ret_cohort_median > 0 (matched-30 separate)",
        extras={"matched30_crown_separate": True},
    )


def interestingness_finding(
    *,
    title: str,
    gate: dict[str, Any],
    strand_note: str,
) -> dict[str, Any] | None:
    """Build the actionable info finding when interestingness is met."""
    if not gate.get("met"):
        return None
    fair = gate.get("fair_cost_median")
    return {
        "severity": "info",
        "category": "research",
        "title": title,
        "summary": (
            f"{strand_note} Alone-path interestingness met "
            f"(fair_cost_median={fair}; rule={gate.get('rule')}). "
            "Human may open a deliberate promotion-*design* dialogue and must "
            "stamp disposition ack | no-design | design-open. "
            "No auto-promote, no decision-review --apply, no second live path (F8)."
        ),
        "auto_fixable": False,
    }
