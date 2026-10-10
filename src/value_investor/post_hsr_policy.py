"""Post-hsr freeze-extras policy (observe-only).

After hsr-v1 / hsr-mid-v1 / hrs-v1 / hms-v1 holdouts returned inconclusive
against plain value, the pre-registered decision is to freeze screen extras.
This module keeps a committed policy store and feeds a daily ops-monitor
check. It never changes signals, books, or knobs.

See ``docs/ops/post-hsr-freeze-extras.md`` (directional shift from PR #1035 /
L583–L585, N200–N201).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE_PATH = Path("docs/data/post_hsr_policy.json")
DEFAULT_OPS_DOC = Path("docs/ops/post-hsr-freeze-extras.md")
HSR_STORE = Path("docs/data/historical_screen_replay.json")
HSR_MIDCAP_STORE = Path("docs/data/historical_screen_replay_midcap.json")
HRS_STORE = Path("docs/data/historical_rule_search.json")
HMS_STORE = Path("docs/data/historical_model_mix.json")

POLICY_ID = "post-hsr-freeze-extras-v1"
SCHEMA_VERSION = 1

STRAND_A = {
    "id": "strand_a_current_stack",
    "status": "active",
    "title": "Current overarching model (strand A)",
    "summary": (
        "Existing composite / buy-tier stack. Keep its experiment grid on the "
        "current framework; do not discard it because extras failed to beat "
        "plain value in the US holdouts."
    ),
}

CANDIDATE_STRANDS = [
    {
        "id": "strand_b_plain_value_technical_timing",
        "status": "named_not_registered",
        "deferred_id": "N200",
        "title": "Technical entry/exit with plain-value identity backstop",
        "summary": (
            "Identity = plain value (or buy-tier); test technical timing for "
            "entry/exit as a sealed observe-only instrument — not a live "
            "replacement for the screen stack."
        ),
        "learning_question": None,
        "registration_id": None,
    },
    {
        "id": "strand_c_short_horizon_value_momentum",
        "status": "named_not_registered",
        "deferred_id": "N201",
        "title": "Global short-horizon value+momentum pipeline",
        "summary": (
            "Continuous small-weight short-hold (~3m) high-value book fed by "
            "global breadth — distinct from the patient value holdings book."
        ),
        "learning_question": None,
        "registration_id": None,
    },
]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _hsr_holdout_verdict(store: dict[str, Any] | None) -> str | None:
    if not store:
        return None
    results = store.get("results")
    if not isinstance(results, dict):
        return None
    horizons = results.get("horizons")
    if not isinstance(horizons, dict):
        return None
    primary = horizons.get("30")
    if not isinstance(primary, dict):
        return None
    verdict = primary.get("holdout_verdict")
    return str(verdict) if verdict is not None else None


def _hrs_evidence(store: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "chosen_config_id": None,
        "chosen_verdict_vs_plain_value": None,
        "chosen_minus_frozen_verdict": None,
    }
    if not store:
        return out
    search = store.get("search") if isinstance(store.get("search"), dict) else {}
    selection = search.get("selection") if isinstance(search.get("selection"), dict) else {}
    out["chosen_config_id"] = selection.get("config_id")
    holdout = store.get("holdout") if isinstance(store.get("holdout"), dict) else {}
    chosen = holdout.get("chosen") if isinstance(holdout.get("chosen"), dict) else {}
    base = chosen.get("base") if isinstance(chosen.get("base"), dict) else {}
    out["chosen_verdict_vs_plain_value"] = base.get("verdict_vs_plain_value")
    delta = (
        holdout.get("chosen_minus_frozen")
        if isinstance(holdout.get("chosen_minus_frozen"), dict)
        else {}
    )
    delta_base = delta.get("base") if isinstance(delta.get("base"), dict) else {}
    out["chosen_minus_frozen_verdict"] = delta_base.get("verdict")
    return out


def _hms_evidence(store: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {"decision": None, "kept": []}
    if not store:
        return out
    holdout = store.get("holdout") if isinstance(store.get("holdout"), dict) else {}
    out["decision"] = holdout.get("decision")
    search = store.get("search") if isinstance(store.get("search"), dict) else {}
    selection = search.get("selection") if isinstance(search.get("selection"), dict) else {}
    kept = selection.get("kept")
    if isinstance(kept, list):
        out["kept"] = [str(x) for x in kept]
    return out


def holdouts_justify_freeze(
    *,
    hsr_verdict: str | None,
    hsr_mid_verdict: str | None,
    hrs_verdict: str | None,
    hms_decision: str | None,
) -> bool:
    """True when revealed holdouts support the freeze-extras decision."""
    inconclusive = {"inconclusive"}
    if hsr_verdict in inconclusive and hsr_mid_verdict in inconclusive:
        return True
    if hrs_verdict in inconclusive:
        return True
    if hms_decision in {"no_gain_over_frozen_mix", "inconclusive"}:
        return True
    return False


def build_post_hsr_policy(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the committed policy payload from holdout stores + strand catalog."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    hsr = _load_json(root / HSR_STORE)
    mid = _load_json(root / HSR_MIDCAP_STORE)
    hrs = _load_json(root / HRS_STORE)
    hms = _load_json(root / HMS_STORE)

    hsr_verdict = _hsr_holdout_verdict(hsr)
    mid_verdict = _hsr_holdout_verdict(mid)
    hrs_ev = _hrs_evidence(hrs)
    hms_ev = _hms_evidence(hms)
    freeze = holdouts_justify_freeze(
        hsr_verdict=hsr_verdict,
        hsr_mid_verdict=mid_verdict,
        hrs_verdict=str(hrs_ev.get("chosen_verdict_vs_plain_value") or "") or None,
        hms_decision=str(hms_ev.get("decision") or "") or None,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "policy_id": POLICY_ID,
        "generated_at": generated_at or _utc_now(),
        "observe_only": True,
        "influences_live": False,
        "freeze_extras": freeze,
        "freeze_reason": (
            "hsr-v1 / hsr-mid-v1 / hrs-v1 / hms-v1 holdout primaries did not "
            "clearly beat plain value (or the frozen mix); pre-registered "
            "decision is freeze screen extras — AI layer and forward evidence "
            "must earn their keep separately."
            if freeze
            else "Holdout evidence does not currently justify freeze_extras."
        ),
        "evidence": {
            "hsr_v1_registration_id": (hsr or {}).get("registration_id"),
            "hsr_v1_holdout_verdict": hsr_verdict,
            "hsr_mid_v1_holdout_verdict": mid_verdict,
            "hrs_v1_chosen_config_id": hrs_ev.get("chosen_config_id"),
            "hrs_v1_chosen_verdict_vs_plain_value": hrs_ev.get(
                "chosen_verdict_vs_plain_value"
            ),
            "hrs_v1_chosen_minus_frozen_verdict": hrs_ev.get(
                "chosen_minus_frozen_verdict"
            ),
            "hms_v1_decision": hms_ev.get("decision"),
            "hms_v1_kept": hms_ev.get("kept") or [],
        },
        "strand_a": dict(STRAND_A),
        "candidate_strands": [dict(row) for row in CANDIDATE_STRANDS],
        "shared_timing_experiments": (
            "Entry/exit and cost experiments may be shared factorially across "
            "strands once registered; each strand keeps its own identity freeze."
        ),
        "prune_policy": (
            "Prefer orthogonal strands over near-copy screen / overlay / "
            "paper-track variants. No new screen extras (models, vetoes, "
            "composite knobs) without a new sealed registration_id and a "
            "pinned learning question."
        ),
        "ops_doc": str(DEFAULT_OPS_DOC),
        "related_deferred": ["L583", "L584", "L585", "N200", "N201"],
        "source_pr": 1035,
    }


def refresh_post_hsr_policy(
    *,
    store_path: Path | None = None,
    repo_root: Path | None = None,
    persist: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build and optionally persist ``docs/data/post_hsr_policy.json``."""
    payload = build_post_hsr_policy(repo_root=repo_root, generated_at=generated_at)
    if persist:
        path = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_findings_from_post_hsr_policy(
    payload: dict[str, Any],
    *,
    ops_doc_exists: bool | None = None,
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Map policy payload → ops-monitor finding dicts (observe-only)."""
    findings: list[dict[str, Any]] = []
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    if ops_doc_exists is None:
        ops_doc_exists = (root / DEFAULT_OPS_DOC).is_file()

    freeze = bool(payload.get("freeze_extras"))
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    hsr_v = evidence.get("hsr_v1_holdout_verdict")
    mid_v = evidence.get("hsr_mid_v1_holdout_verdict")
    candidates = payload.get("candidate_strands")
    n_candidates = len(candidates) if isinstance(candidates, list) else 0

    if not freeze and hsr_v == "inconclusive" and mid_v == "inconclusive":
        findings.append(
            {
                "severity": "warn",
                "category": "research",
                "title": "Post-hsr freeze-extras not declared after inconclusive holdout",
                "summary": (
                    "hsr-v1 and hsr-mid-v1 holdout primaries are inconclusive vs "
                    "plain value, but post_hsr_policy.freeze_extras is false. "
                    "See docs/ops/post-hsr-freeze-extras.md (PR #1035 / L585)."
                ),
                "auto_fixable": False,
            }
        )
        return findings

    if freeze and not ops_doc_exists:
        findings.append(
            {
                "severity": "warn",
                "category": "research",
                "title": "Post-hsr freeze-extras ops note missing",
                "summary": (
                    "freeze_extras is true but docs/ops/post-hsr-freeze-extras.md "
                    "is missing. Restore the runbook so the directional shift "
                    "stays operable."
                ),
                "auto_fixable": False,
            }
        )

    if freeze and n_candidates < 1:
        findings.append(
            {
                "severity": "warn",
                "category": "research",
                "title": "Post-hsr candidate strands not listed",
                "summary": (
                    "freeze_extras is on but candidate_strands is empty. Name at "
                    "least the N200/N201 peer strands before registering any."
                ),
                "auto_fixable": False,
            }
        )

    if freeze:
        strand_a = payload.get("strand_a") if isinstance(payload.get("strand_a"), dict) else {}
        named = [
            str(row.get("deferred_id") or row.get("id"))
            for row in (candidates or [])
            if isinstance(row, dict)
        ]
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": "Post-hsr freeze-extras policy in force",
                "summary": (
                    f"Screen extras frozen after inconclusive US holdouts "
                    f"(hsr={hsr_v}, mid={mid_v}). Strand A "
                    f"({strand_a.get('id') or 'strand_a_current_stack'}) stays "
                    f"active; named peer strands (not registered): "
                    f"{', '.join(named) or 'none'}. "
                    f"See docs/ops/post-hsr-freeze-extras.md."
                ),
                "auto_fixable": False,
            }
        )

    return findings
