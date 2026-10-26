"""Cue-consumer mid-flight-tune observe lab (``cue_consumer_mft`` / super book).

Package **M** observe-only skeleton. Mid-flight tunes apply on **this lab only**.
``influences_live=false`` always. Never Package L on sealed cue books; never
silent strand-A promote; never credit cue-book historical NAV as lab wins.

Learning question: given frozen cue-sources, can a declared-incomparable
fixed-stake cue-consumer sleeve that rolls critique into mid-flight tunes on
itself prove/falsify lesson incorporation on five fair-cost levers, emit thin
but novel hardened proposals into a lineage-tracked, cap-bounded sealed-twin
population with declared periodic cull?

See ``docs/ops/cue-consumer-mft.md``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import write_json

SCHEMA_VERSION = 1
LAB_ID = "cue_consumer_mft"
REGISTRATION_ID = "cue-consumer-mft-v0"
EVOLUTIONARY_ROOT_ID = "cue-consumer-mft-root-v0"
DEFERRED_ID = "N222"
SCOREBOARD_ID = "incomparable_midflight_tune"
METRIC_SPEC_ID = "mft-fair-cost-5lever-v0"
CUE_WHITELIST_ID = "mft-short-whitelist-v0"
KNOB_SET_ID = "mft-knob-set-v0"
TUNE_SPEC_ID = "mft-tune-spec-epoch0-v0"
CULL_SPEC_ID = "mft-cull-spec-v0"
NOVELTY_SPEC_ID = "mft-novelty-spec-v0"
FIXED_STAKE_UNITS = 100.0
THIN_EMIT_MIN_CLOSES = 3
PER_ROOT_ACTIVE_CAP = 3
CALENDAR_FALLBACK = "2026-12-01"
# Q8B: named frozen open-autopsy cohort — not active_count==0 forever-wait.
START_CHECKPOINT_ID = "open_autopsy_cohort_2026_q4"
# Concrete cohort selection (prefs: prefer identity-break / non-mechanical).
COHORT_SELECTION_ID = "non_mechanical_open_autopsy_v0"
COHORT_EXIT_REASON_PREFIXES = ("identity_break", "quality_break")
PIPELINE_STATUS_SKELETON = "skeleton_registered"
PIPELINE_STATUS_ARMED = "armed_observe_awaiting_q8b"
PIPELINE_STATUS_SHADOWS_OK = "armed_observe_q8b_eligible"
LAB_ARM_MARKER_ID = "mft-lab-arm-epoch0-v0"
JUDGMENT_RUBRIC_ID = "judgment_in_the_round_v0"
AUTOPSY_FEED_CAP = 25

FINDING_TITLE = "Cue-consumer MFT lab refreshed"
STORE_FAILED_TITLE = "Cue-consumer MFT lab failed"
START_GATE_ELIGIBLE_TITLE = "Cue-consumer MFT start gate eligible (evolutionary shadows)"
LAB_ARMED_TITLE = "Cue-consumer MFT lab armed (observe)"
COHORT_FREEZE_PROPOSED_TITLE = "Cue-consumer MFT Q8B cohort freeze proposed — owner confirm"
CATEGORY = "research"

DEFAULT_OUTPUT_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/cue_consumer_mft_observe.json")
DEFAULT_REGISTRATION_PATH = Path("docs/data/cue_consumer_mft_registration.json")
DEFAULT_START_GATE_PATH = Path("docs/data/cue_consumer_mft_start_gate.json")
DEFAULT_OPS_DOC = Path("docs/ops/cue-consumer-mft.md")
DEFAULT_QUEUE_PATH = Path("docs/data/post_sale_review_queue.json")
DEFAULT_LABELS_PATH = Path("docs/data/post_sale_review_labels.json")

LEARNING_QUESTION = (
    "Given frozen cue-sources, can a declared-incomparable fixed-stake "
    "cue-consumer sleeve that rolls critique into mid-flight tunes on itself "
    "prove/falsify lesson incorporation on five fair-cost levers, emit thin but "
    "novel hardened proposals into a lineage-tracked, cap-bounded sealed-twin "
    "population with declared periodic cull, without credit-claim, Package L on "
    "sealed, silent strand-A promote, or active-model noise spray?"
)

# Short whitelist (Q1 default C): sealed/control cue sources only, PIT at T≤decision.
CUE_WHITELIST: tuple[dict[str, str], ...] = (
    {
        "cue_source_id": "n200_raw_buy_tier",
        "registration_id": "strand-b-plain-value-tech-timing-v0",
        "role": "buy_recommendation_cue",
        "pit_rule": "cue_visible_at_or_before_decision_ts",
    },
    {
        "cue_source_id": "n210_ai_filter",
        "registration_id": "strand-e-ai-judgment-fixed-stake-v0",
        "role": "buy_recommendation_cue",
        "pit_rule": "cue_visible_at_or_before_decision_ts",
    },
    {
        "cue_source_id": "ftse_control_buy_tier",
        "registration_id": "buy_tier_level",
        "role": "buy_recommendation_cue",
        "pit_rule": "cue_visible_at_or_before_decision_ts",
    },
)

MOM_LEVERS: tuple[dict[str, str], ...] = (
    {
        "id": "stock_choice",
        "definition": "Accepted vs skipped PIT cues; fair-cost forward %",
        "not": "cue-book path %; live NAV",
    },
    {
        "id": "buy_timing",
        "definition": "vs immediate-on-cue; fair-cost delta",
        "not": "watermark brackets (N217)",
    },
    {
        "id": "buy_strategy",
        "definition": "Single-shot vs scale-in within fixed stake",
        "not": "DCA / cash drag (later twins)",
    },
    {
        "id": "sell_timing",
        "definition": (
            "vs registered hold counterfactuals; default bias against same-calendar-day exit"
        ),
        "not": "N200 leave-tier as this lab's skill; same-day without error evidence",
    },
    {
        "id": "sell_strategy",
        "definition": (
            "Rule-family by epoch; fair-cost; same-day exit allowed only as "
            "major_error_reverse with durable cites"
        ),
        "not": "Hard live veto; Package L; silent same-day churn",
    },
)

SAME_DAY_POLICY = {
    "default": "undesirable",
    "soft_bias": True,
    "hard_ban": False,
    "exception": "major_error_reverse",
    "exception_requires": (
        "durable intraday / decision-reason evidence in trail "
        "(decision reasons + optional geometry/autopsy cite)"
    ),
    "scoreboard_levers": ["sell_timing", "sell_strategy"],
}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def same_day_round_trip(
    *,
    entry_at: Any = None,
    exit_at: Any = None,
    hold_days: Any = None,
) -> bool:
    """True when entry/exit share a calendar day or hold_days < 1."""
    if isinstance(hold_days, (int, float)) and hold_days < 1:
        return True
    entry_d = _parse_date(entry_at)
    exit_d = _parse_date(exit_at)
    if entry_d is not None and exit_d is not None:
        return entry_d == exit_d
    return False


def assess_same_day_round_trip(
    *,
    entry_at: Any = None,
    exit_at: Any = None,
    hold_days: Any = None,
    major_error_reverse: bool = False,
    evidence_cites: list[str] | None = None,
) -> dict[str, Any]:
    """Soft bias assessment — not a hard ban.

    Default ``likely_weakness`` when same-day; ``major_error_reverse`` only when
    caller supplies the flag **and** at least one durable evidence cite.
    """
    is_same = same_day_round_trip(entry_at=entry_at, exit_at=exit_at, hold_days=hold_days)
    cites = [str(c).strip() for c in (evidence_cites or []) if str(c).strip()]
    if not is_same:
        return {
            "same_day_round_trip": False,
            "same_day_assessment": "not_applicable",
            "soft_penalty": False,
            "hard_ban": False,
            "evidence_cites": [],
        }
    if major_error_reverse and cites:
        return {
            "same_day_round_trip": True,
            "same_day_assessment": "major_error_reverse",
            "soft_penalty": False,
            "hard_ban": False,
            "evidence_cites": cites,
        }
    return {
        "same_day_round_trip": True,
        "same_day_assessment": "likely_weakness",
        "soft_penalty": True,
        "hard_ban": False,
        "evidence_cites": cites,
        "note": (
            "Same-day buy→sell is default undesirable; mark major_error_reverse "
            "only with durable intraday / reason evidence — soft bias, not hard ban."
        ),
    }


def _is_non_mechanical_exit_reason(exit_reason: Any) -> bool:
    text = str(exit_reason or "").strip().lower()
    if not text:
        return False
    return any(text.startswith(prefix) for prefix in COHORT_EXIT_REASON_PREFIXES)


def propose_start_cohort(
    queue: dict[str, Any] | None,
    *,
    checkpoint_id: str = START_CHECKPOINT_ID,
    selection_id: str = COHORT_SELECTION_ID,
) -> dict[str, Any]:
    """Build the concrete Q8B named-cohort proposal from the open autopsy queue.

    Selection (locked definition for ``open_autopsy_cohort_2026_q4``):
    - Active ``post_sale_review_queue`` rows only (snapshot at propose time)
    - Exclude ``reply:`` dialogue thread ids
    - Keep non-mechanical exits whose ``exit_reason`` starts with
      ``identity_break`` or ``quality_break`` (prefs: prefer these over
      max-days / leave-buy-cohort mechanical piles)
    - Sorted by ``sold_at`` / ``exit_at`` ascending for stable freeze order

    This does **not** write ``cohort_review_ids`` — owner must confirm via
    ``freeze_start_cohort(..., apply=True)`` (human gate).
    """
    active = []
    if isinstance(queue, dict):
        raw = queue.get("active") or []
        if isinstance(raw, list):
            active = [row for row in raw if isinstance(row, dict)]

    selected: list[dict[str, Any]] = []
    for row in active:
        rid = str(row.get("review_id") or row.get("id") or "").strip()
        if not rid or rid.startswith("reply:"):
            continue
        if not _is_non_mechanical_exit_reason(row.get("exit_reason")):
            continue
        selected.append(
            {
                "review_id": rid,
                "book_id": row.get("book_id"),
                "ticker": row.get("ticker"),
                "exit_reason": row.get("exit_reason"),
                "sold_at": row.get("sold_at") or row.get("exit_at"),
                "learning_point_forward": row.get("learning_point_forward"),
            }
        )

    def _sort_key(item: dict[str, Any]) -> str:
        return str(item.get("sold_at") or "") + "|" + str(item.get("review_id") or "")

    selected.sort(key=_sort_key)
    review_ids = [str(item["review_id"]) for item in selected]
    by_reason: dict[str, int] = {}
    by_book: dict[str, int] = {}
    for item in selected:
        reason = str(item.get("exit_reason") or "unknown")
        book = str(item.get("book_id") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1
        by_book[book] = by_book.get(book, 0) + 1

    return {
        "checkpoint_id": checkpoint_id,
        "selection_id": selection_id,
        "mode": "q8b_named_cohort_checkpoint",
        "proposed_cohort_review_ids": review_ids,
        "proposed_cohort_size": len(review_ids),
        "proposed_cohort_sample": selected[:10],
        "by_exit_reason": by_reason,
        "by_book_id": by_book,
        "excludes": [
            "reply_dialogue_threads",
            "hold_trading_days_mechanical",
            "leave_buy_tier_mechanical",
            "blank_exit_reason",
        ],
        "how_measured": (
            f"Freeze proposed_cohort_review_ids into cohort_review_ids under "
            f"checkpoint_id={checkpoint_id}. Checkpoint completes when every "
            "frozen id is Accept/Comment-actioned in post_sale_review_labels; "
            "new just_sold refill does not reopen. Calendar alternate "
            f"{CALENDAR_FALLBACK}."
        ),
        "owner_decision": (
            "Confirm freeze of this named non-mechanical open-autopsy cohort "
            "(or shrink/rebuild via CLI propose-cohort before freeze). "
            "Evolutionary shadows wait on freeze+completion (or calendar)."
        ),
        "influences_live": False,
        "auto_apply": False,
    }


def freeze_start_cohort(
    *,
    start_gate: dict[str, Any] | None,
    proposal: dict[str, Any] | None = None,
    review_ids: list[str] | None = None,
    apply: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Copy proposed (or explicit) review_ids into ``cohort_review_ids``.

    Dry-run by default (``apply=False``). Never invents ids; never clears an
    already-frozen cohort unless ``review_ids`` is explicitly supplied with
    ``apply=True`` (owner re-freeze).
    """
    when = generated_at or _utcnow()
    gate = (
        dict(start_gate)
        if isinstance(start_gate, dict)
        else default_start_gate_payload(generated_at=when)
    )
    existing = [str(x).strip() for x in (gate.get("cohort_review_ids") or []) if str(x).strip()]
    if review_ids is not None:
        ids = [str(x).strip() for x in review_ids if str(x).strip()]
    elif isinstance(proposal, dict):
        ids = [
            str(x).strip()
            for x in (proposal.get("proposed_cohort_review_ids") or [])
            if str(x).strip()
        ]
    else:
        ids = [
            str(x).strip() for x in (gate.get("proposed_cohort_review_ids") or []) if str(x).strip()
        ]

    result = {
        "apply": bool(apply),
        "would_freeze_n": len(ids),
        "already_frozen_n": len(existing),
        "checkpoint_id": str(gate.get("checkpoint_id") or START_CHECKPOINT_ID),
        "influences_live": False,
    }
    if not ids:
        result["status"] = "noop_empty_proposal"
        result["gate"] = gate
        return result
    if existing and review_ids is None:
        result["status"] = "noop_already_frozen"
        result["gate"] = gate
        return result
    if not apply:
        result["status"] = "dry_run"
        result["preview_review_ids"] = ids[:20]
        result["gate"] = gate
        return result

    gate["cohort_review_ids"] = ids
    gate["cohort_frozen_at"] = when
    gate["opened_at"] = gate.get("opened_at") or when
    gate["checkpoint_status"] = "open"
    gate["completed_at"] = None
    gate["cohort_selection_id"] = (
        (proposal or {}).get("selection_id")
        if isinstance(proposal, dict)
        else gate.get("cohort_selection_id") or COHORT_SELECTION_ID
    )
    gate["proposed_cohort_review_ids"] = ids
    gate["proposed_at"] = gate.get("proposed_at") or when
    gate["generated_at"] = when
    result["status"] = "frozen"
    result["gate"] = gate
    return result


def judgment_in_the_round_stub() -> dict[str, Any]:
    """Observe-only checklist schema (design lock) — N228 fills later."""
    buy = {
        key: {"answer": None, "confidence": None, "cites": [], "unknown": True}
        for key in ("B1", "B2", "B3", "B4", "B5", "B6")
    }
    sell = {
        key: {"answer": None, "confidence": None, "cites": [], "unknown": True}
        for key in ("S1", "S2", "S3", "S4", "S5", "S6")
    }
    return {
        "rubric_id": JUDGMENT_RUBRIC_ID,
        "influences_live": False,
        "observe_only": True,
        "rules_role": "scaffold_propose",
        "buy": buy,
        "sell": sell,
        "rule_candidates": [],
        "llm_stance": None,
        "misfit_evidence": None,
        "deferred_id": "N228",
        "note": (
            "Schema stub only — deterministic/LLM fill + misfit trail remain "
            "N228. Missing cites fail-close influence."
        ),
    }


def build_autopsy_alignment_feed(
    queue: dict[str, Any] | None,
    *,
    cap: int = AUTOPSY_FEED_CAP,
) -> dict[str, Any]:
    """Package M → lab observe feed: learning_point_forward rows (no auto-tune)."""
    active: list[dict[str, Any]] = []
    if isinstance(queue, dict):
        raw = queue.get("active") or []
        if isinstance(raw, list):
            active = [row for row in raw if isinstance(row, dict)]

    rows: list[dict[str, Any]] = []
    for item in active:
        rid = str(item.get("review_id") or "").strip()
        if not rid or rid.startswith("reply:"):
            continue
        forward = str(item.get("learning_point_forward") or "").strip()
        if not forward:
            continue
        if not _is_non_mechanical_exit_reason(item.get("exit_reason")):
            continue
        rows.append(
            {
                "review_id": rid,
                "book_id": item.get("book_id"),
                "ticker": item.get("ticker"),
                "exit_reason": item.get("exit_reason"),
                "learning_point_forward": forward,
                "same_day_assessment": item.get("same_day_assessment"),
            }
        )
        if len(rows) >= cap:
            break

    return {
        "source": "post_sale_review_queue.active",
        "package": "M",
        "role": "alignment_inform_lab_only",
        "auto_tune": False,
        "package_l": False,
        "count": len(rows),
        "rows": rows,
        "note": (
            "Autopsy learning_point_forward informs the lab observe trail. "
            "Does not auto-tune sealed books or open Package L."
        ),
    }


def select_pit_cues(
    candidates: list[dict[str, Any]] | None,
    *,
    decision_ts: str | None,
    whitelist: tuple[dict[str, str], ...] = CUE_WHITELIST,
) -> list[dict[str, Any]]:
    """Stub PIT cue filter: keep whitelist sources with cue_ts ≤ decision_ts."""
    allowed = {row["cue_source_id"] for row in whitelist}
    decision_d = _parse_date(decision_ts)
    out: list[dict[str, Any]] = []
    for raw in candidates or []:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("cue_source_id") or "").strip()
        if source not in allowed:
            continue
        cue_d = _parse_date(raw.get("cue_ts") or raw.get("visible_at"))
        if decision_d is not None and cue_d is not None and cue_d > decision_d:
            continue  # look-ahead reject
        if decision_d is not None and cue_d is None:
            continue  # fail-closed: missing PIT stamp
        row = dict(raw)
        row["pit_ok"] = True
        row["cue_whitelist_id"] = CUE_WHITELIST_ID
        out.append(row)
    return out


def novelty_fingerprint(
    *,
    levers_touched: list[str] | None = None,
    cue_whitelist_id: str = CUE_WHITELIST_ID,
    timing_sell_family: str = "default_v0",
    recipe_note: str = "",
) -> str:
    """v0 novelty fingerprint (interface for N226 gate)."""
    payload = {
        "levers": sorted({str(x) for x in (levers_touched or []) if str(x).strip()}),
        "cue_whitelist_id": cue_whitelist_id,
        "timing_sell_family": timing_sell_family,
        "recipe_note": str(recipe_note or "").strip()[:120],
        "novelty_spec_id": NOVELTY_SPEC_ID,
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def novelty_gate_stub(
    proposal: dict[str, Any],
    *,
    active_fingerprints: list[str] | None = None,
) -> dict[str, Any]:
    """Stub novelty/similarity gate (N226 remainder).

    Returns ``reject`` | ``merge`` | ``spawn`` without sealing children.
    """
    fp = str(proposal.get("novelty_fingerprint") or "").strip()
    active = {str(x).strip() for x in (active_fingerprints or []) if str(x).strip()}
    if not fp:
        return {
            "action": "reject",
            "reason": "missing_novelty_fingerprint",
            "stub": True,
            "deferred_id": "N226",
        }
    if fp in active:
        return {
            "action": "merge",
            "reason": "fingerprint_matches_active_lineage_member",
            "stub": True,
            "deferred_id": "N226",
            "novelty_fingerprint": fp,
        }
    return {
        "action": "spawn",
        "reason": "novel_vs_active_set_stub",
        "stub": True,
        "deferred_id": "N226",
        "novelty_fingerprint": fp,
        "note": "Full similarity distance / lever-subset merge rules remain N226.",
    }


def concurrent_cap_stub(
    *,
    active_child_count: int,
    per_root_cap: int = PER_ROOT_ACTIVE_CAP,
) -> dict[str, Any]:
    """Stub per-root concurrent cap (N227 remainder)."""
    at_cap = active_child_count >= per_root_cap
    return {
        "at_cap": at_cap,
        "active_child_count": active_child_count,
        "per_root_cap": per_root_cap,
        "policy": "cull_or_replace_before_spawn" if at_cap else "spawn_ok_if_novel",
        "stub": True,
        "deferred_id": "N227",
        "note": (
            "Prefer cull/replace over accumulate. Full cull factory + archive "
            "losers remain N227 / L631."
        ),
    }


def cull_stub(
    *,
    active_children: list[dict[str, Any]] | None = None,
    cull_spec_id: str = CULL_SPEC_ID,
) -> dict[str, Any]:
    """Stub periodic cull (N227 / L631). Declared criteria only — no opaque rank."""
    children = [c for c in (active_children or []) if isinstance(c, dict)]
    return {
        "cull_spec_id": cull_spec_id,
        "criteria": [
            "fair_cost_episode_pct_alone_first_after_volume",
            "named_mom_lever_scores",
        ],
        "cadence": "sunday_bundle_or_spawn_at_cap",
        "active_considered": len(children),
        "suggested_archive": [],
        "cull_equals_live_promote": False,
        "stub": True,
        "deferred_ids": ["N227", "L631"],
        "note": (
            "Cull ≠ auto-promote to live capital. Loser fate = archive/freeze "
            "(L631). Full factory not in this skeleton."
        ),
    }


def thin_emit_readiness(
    *,
    closed_episodes_citing_levers: int,
    proposal_hygiene_ok: bool,
    mom_window_complete: bool | None = None,
) -> dict[str, Any]:
    """Q6B closes-primary soft readiness (L629 scaffolding).

    MoM window is diagnostic/companion only — not a mandatory emit gate.
    """
    closes_ok = closed_episodes_citing_levers >= THIN_EMIT_MIN_CLOSES
    soft_ready = closes_ok and proposal_hygiene_ok
    return {
        "soft_ready": soft_ready,
        "closes_primary": True,
        "min_closes": THIN_EMIT_MIN_CLOSES,
        "closed_episodes_citing_levers": closed_episodes_citing_levers,
        "closes_ok": closes_ok,
        "proposal_hygiene_ok": proposal_hygiene_ok,
        "mom_window_complete": mom_window_complete,
        "mom_role": "optional_diagnostic_companion",
        "mom_required_for_emit": False,
        "emit_equals_keep_forever": False,
        "requires_cull_willingness": True,
        "metric_spec_id": METRIC_SPEC_ID,
        "deferred_scaffolding_id": "L629",
        "note": (
            "Passing soft readiness creates a novelty/cap candidate only — "
            "emit ≠ keep; novelty + per-root cap + cull/archive required (N226/N227)."
        ),
    }


def build_hardened_proposal_stub(
    *,
    levers_touched: list[str],
    tune_spec_id: str = TUNE_SPEC_ID,
    knob_epoch_started_at: str | None = None,
    falsify_or_incorporate_note: str = "",
    closed_episodes_citing_levers: int = 0,
) -> dict[str, Any]:
    """Scaffold a hardened_ruleset_proposal candidate (no seal)."""
    fp = novelty_fingerprint(levers_touched=levers_touched)
    hygiene_ok = bool(falsify_or_incorporate_note.strip()) and bool(tune_spec_id)
    readiness = thin_emit_readiness(
        closed_episodes_citing_levers=closed_episodes_citing_levers,
        proposal_hygiene_ok=hygiene_ok,
        mom_window_complete=None,
    )
    proposal_id = f"hrp-{fp[:12]}"
    return {
        "proposal_id": proposal_id,
        "kind": "hardened_ruleset_proposal",
        "tune_spec_id": tune_spec_id,
        "knob_epoch_started_at": knob_epoch_started_at,
        "levers_touched": list(levers_touched),
        "novelty_fingerprint": fp,
        "falsify_or_incorporate_note": falsify_or_incorporate_note,
        "thin_emit_readiness": readiness,
        "influences_live": False,
        "spawn_status": "scaffold_only",
        "deferred_spawn_id": "N223",
        "note": (
            "Scaffold only — novelty/cap/cull gates must pass before any new "
            "sealed child; never silent strand A; never Package L on sealed cues."
        ),
    }


def _label_history_index(labels: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map review_id → latest label row from post_sale_review_labels.json."""
    if not isinstance(labels, dict):
        return {}
    index: dict[str, dict[str, Any]] = {}
    history = labels.get("history") or labels.get("labels") or []
    if isinstance(labels.get("by_review_id"), dict):
        for rid, row in labels["by_review_id"].items():
            if isinstance(row, dict):
                index[str(rid)] = row
    for row in history if isinstance(history, list) else []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("review_id") or row.get("id") or "").strip()
        if rid:
            index[rid] = row
    return index


def _actioned_review_ids(labels: dict[str, Any] | None) -> set[str]:
    """Review IDs that left the active queue via Accept/Comment (or reply Accept)."""
    actioned: set[str] = set()
    index = _label_history_index(labels)
    clearing = {
        "accept",
        "comment",
        "duplicate",
        "accepted",
        "commented",
        "duplicated",
    }
    for rid, row in index.items():
        action = str(row.get("action") or row.get("label") or row.get("kind") or "").strip().lower()
        if action in clearing:
            actioned.add(rid)
        # Nested events list
        for ev in row.get("events") or []:
            if not isinstance(ev, dict):
                continue
            ev_action = (
                str(ev.get("action") or ev.get("label") or ev.get("kind") or "").strip().lower()
            )
            if ev_action in clearing:
                actioned.add(rid)
    return actioned


def evaluate_start_gate(
    *,
    start_gate: dict[str, Any] | None,
    labels: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Q8B practical lock: named open-autopsy cohort checkpoint.

    How measured
    ------------
    1. Freeze a cohort of ``review_id``s into ``cohort_review_ids`` when the
       checkpoint opens (named ``checkpoint_id``).
    2. Checkpoint **completes** when every frozen id is actioned in
       ``post_sale_review_labels`` (Accept or Comment) — **even if** today's
       ``post_sale_review_queue.active_count`` is non-zero because new
       ``just_sold`` rows refilled the active queue.
    3. Alternate: calendar ``on_or_after`` ``CALENDAR_FALLBACK`` (2026-12-01).

    Explicitly **not** ``active_count == 0`` forever-wait (Q8A rejected as sole gate).
    """
    gate = dict(start_gate) if isinstance(start_gate, dict) else {}
    checkpoint_id = str(gate.get("checkpoint_id") or START_CHECKPOINT_ID)
    cohort = [str(x).strip() for x in (gate.get("cohort_review_ids") or []) if str(x).strip()]
    status = str(gate.get("checkpoint_status") or "open").strip().lower()
    actioned = _actioned_review_ids(labels)
    remaining = [rid for rid in cohort if rid not in actioned]
    cohort_complete = bool(cohort) and not remaining
    if status in {"complete", "completed", "done"} and gate.get("completed_at"):
        cohort_complete = True
        remaining = []

    today_d = today or datetime.now(UTC).date()
    fallback_d = date.fromisoformat(CALENDAR_FALLBACK)
    calendar_ok = today_d >= fallback_d

    eligible = cohort_complete or calendar_ok
    reason: str
    if cohort_complete:
        reason = "named_open_autopsy_cohort_checkpoint_complete"
    elif calendar_ok:
        reason = "calendar_fallback_on_or_after"
    elif not cohort:
        reason = "checkpoint_open_cohort_not_frozen_yet"
    else:
        reason = "checkpoint_open_cohort_incomplete"

    return {
        "mode": "q8b_named_cohort_checkpoint",
        "checkpoint_id": checkpoint_id,
        "checkpoint_status": "complete" if cohort_complete else "open",
        "cohort_size": len(cohort),
        "cohort_actioned": len(cohort) - len(remaining),
        "cohort_remaining": remaining[:20],
        "cohort_complete": cohort_complete,
        "calendar_fallback": CALENDAR_FALLBACK,
        "calendar_ok": calendar_ok,
        "eligible": eligible,
        "eligibility_reason": reason,
        "not_gate": "active_count==0_forever_wait_while_just_sold_refills",
        "how_measured": (
            "Freeze open-autopsy review_ids into cue_consumer_mft_start_gate.json "
            f"cohort_review_ids under checkpoint_id={checkpoint_id}. Complete when "
            "each id is Accept/Comment-actioned in post_sale_review_labels — new "
            "just_sold refill of the active queue does not reopen the checkpoint. "
            f"Alternate: on_or_after {CALENDAR_FALLBACK}."
        ),
        "evolutionary_shadows_note": (
            "First evolutionary shadows / thin sealed children become eligible "
            "only when this gate is eligible; lab skeleton may refresh before that."
        ),
    }


def default_start_gate_payload(*, generated_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": generated_at or _utcnow(),
        "checkpoint_id": START_CHECKPOINT_ID,
        "checkpoint_status": "open",
        "opened_at": None,
        "completed_at": None,
        "cohort_review_ids": [],
        "cohort_frozen_at": None,
        "cohort_selection_id": COHORT_SELECTION_ID,
        "proposed_cohort_review_ids": [],
        "proposed_at": None,
        "calendar_fallback": CALENDAR_FALLBACK,
        "mode": "q8b_named_cohort_checkpoint",
        "how_measured": (
            "Named cohort = currently-open non-mechanical autopsy rows "
            f"({COHORT_SELECTION_ID}: exit_reason identity_break* / "
            "quality_break*; exclude reply: threads). Owner confirms freeze of "
            "proposed_cohort_review_ids → cohort_review_ids. Gate completes when "
            "all frozen ids are Accept/Comment-actioned; daily just_sold refill "
            "does not reset the cohort. Calendar alternate 2026-12-01."
        ),
        "influences_live": False,
        "ops_doc": str(DEFAULT_OPS_DOC),
    }


def build_registration_payload(*, sealed_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "lab_id": LAB_ID,
        "evolutionary_root_id": EVOLUTIONARY_ROOT_ID,
        "deferred_id": DEFERRED_ID,
        "status": "observe_lab_armed",
        "pipeline_status": PIPELINE_STATUS_ARMED,
        "lab_arm_marker_id": LAB_ARM_MARKER_ID,
        "observe_only": True,
        "influences_live": False,
        "auto_fixable": False,
        "sealed_at": sealed_at or "2026-10-25",
        "learning_question": LEARNING_QUESTION,
        "scoreboard_id": SCOREBOARD_ID,
        "metric_spec_id": METRIC_SPEC_ID,
        "cue_whitelist_id": CUE_WHITELIST_ID,
        "knob_set_id": KNOB_SET_ID,
        "tune_spec_id": TUNE_SPEC_ID,
        "cull_spec_id": CULL_SPEC_ID,
        "novelty_spec_id": NOVELTY_SPEC_ID,
        "declared_incomparable": True,
        "incomparable_banner": (
            "Scoreboard = mid-flight MoM on five fair-cost levers — not peer NAV; "
            "never claim cue-book historical NAV as lab wins."
        ),
        "sizing": {
            "mode": "fixed_stake",
            "stake_units": FIXED_STAKE_UNITS,
            "cash_fund_nav": "parked",
            "scoreboard_unit": "fair_cost_episode_pct",
            "dca": "not_on_v0",
        },
        "mid_flight_tune": {
            "allowed_on": "this_lab_only",
            "knob_epoch_started_at_required": True,
            "tune_spec_id_immutable_prior": True,
            "package_l_on_sealed": False,
            "mediation": "human_confirm_q3a",
        },
        "export": {
            "artifact": "hardened_ruleset_proposal",
            "destination": "new_sealed_twin_or_merge",
            "never": ["silent_strand_a", "rewrite_sealed_midflight", "credit_cue_nav"],
        },
        "anti_noise": {
            "novelty_gate": "N226_stub",
            "per_root_cap": PER_ROOT_ACTIVE_CAP,
            "cull_replace": "N227_stub",
            "archive_losers": "L631_deferred",
        },
        "start_gate": {
            "mode": "q8b_named_cohort_checkpoint",
            "checkpoint_id": START_CHECKPOINT_ID,
            "cohort_selection_id": COHORT_SELECTION_ID,
            "calendar_fallback": CALENDAR_FALLBACK,
        },
        "spend_guard": {
            "lane": "investment_observe",
            "steals_data_p1_fat_slot": False,
            "fail_closed_if_would_steal_p1": True,
        },
        "same_day_policy": SAME_DAY_POLICY,
        "ops_doc": str(DEFAULT_OPS_DOC),
    }


def build_lab_payload(
    *,
    start_gate_eval: dict[str, Any],
    generated_at: str | None = None,
    knob_epoch_started_at: str | None = None,
    lab_armed_at: str | None = None,
    closed_lab_episodes: list[dict[str, Any]] | None = None,
    active_children: list[dict[str, Any]] | None = None,
    autopsy_alignment_feed: dict[str, Any] | None = None,
    start_gate_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build observe store payload (armed observe — no live fills / no episode walker)."""
    when = generated_at or _utcnow()
    epoch_at = knob_epoch_started_at or when
    armed_at = lab_armed_at or when
    closed = [e for e in (closed_lab_episodes or []) if isinstance(e, dict)]
    children = [c for c in (active_children or []) if isinstance(c, dict)]
    gate_store = start_gate_store if isinstance(start_gate_store, dict) else {}
    shadows_ok = bool(start_gate_eval.get("eligible"))
    pipeline_status = PIPELINE_STATUS_SHADOWS_OK if shadows_ok else PIPELINE_STATUS_ARMED
    sample_proposal = build_hardened_proposal_stub(
        levers_touched=["sell_timing"],
        tune_spec_id=TUNE_SPEC_ID,
        knob_epoch_started_at=epoch_at,
        falsify_or_incorporate_note=(
            "Skeleton hygiene example — replace with real incorporate/falsify "
            "note before any spawn candidate."
        ),
        closed_episodes_citing_levers=len(closed),
    )
    novelty = novelty_gate_stub(
        sample_proposal,
        active_fingerprints=[str(c.get("novelty_fingerprint") or "") for c in children],
    )
    cap = concurrent_cap_stub(active_child_count=len(children))
    cull = cull_stub(active_children=children)
    feed = autopsy_alignment_feed or build_autopsy_alignment_feed(None)

    levers_board = []
    for lever in MOM_LEVERS:
        levers_board.append(
            {
                **lever,
                "mom_score": None,
                "status": "awaiting_lab_closes",
                "diagnostic_only_until_volume": True,
            }
        )

    proposed_n = len(
        [x for x in (gate_store.get("proposed_cohort_review_ids") or []) if str(x).strip()]
    )
    frozen_n = len([x for x in (gate_store.get("cohort_review_ids") or []) if str(x).strip()])

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": when,
        "lab_id": LAB_ID,
        "registration_id": REGISTRATION_ID,
        "evolutionary_root_id": EVOLUTIONARY_ROOT_ID,
        "deferred_id": DEFERRED_ID,
        "status": "observe_lab_armed",
        "pipeline_status": pipeline_status,
        "lab_arm_marker_id": LAB_ARM_MARKER_ID,
        "lab_armed_at": armed_at,
        "observe_only": True,
        "influences_live": False,
        "auto_fixable": False,
        "declared_incomparable": True,
        "scoreboard_id": SCOREBOARD_ID,
        "metric_spec_id": METRIC_SPEC_ID,
        "learning_question": LEARNING_QUESTION,
        "spend_guard": {
            "lane": "investment_observe",
            "steals_data_p1_fat_slot": False,
            "fail_closed_if_would_steal_p1": True,
            "note": (
                "Lab refresh/arm is JSON observe-only — never claims the Data "
                "P1 ingest fat slot / fourth equal sprint."
            ),
        },
        "sizing": {
            "mode": "fixed_stake",
            "stake_units": FIXED_STAKE_UNITS,
            "cash_fund_nav": "parked",
            "scoreboard_unit": "fair_cost_episode_pct",
        },
        "mid_flight_tune": {
            "knob_epoch_started_at": epoch_at,
            "tune_spec_id": TUNE_SPEC_ID,
            "knob_set_id": KNOB_SET_ID,
            "allowed_on": "this_lab_only",
            "package_l_on_sealed": False,
            "lab_arm_marker_id": LAB_ARM_MARKER_ID,
        },
        "cue_selection": {
            "cue_whitelist_id": CUE_WHITELIST_ID,
            "whitelist": list(CUE_WHITELIST),
            "pit_rule": "cue_ts_lte_decision_ts",
            "stub": True,
            "note": "PIT selection stub — short whitelist only; no look-ahead.",
        },
        "judgment_in_the_round": judgment_in_the_round_stub(),
        "autopsy_alignment_feed": feed,
        "observe_shadow_pass": {
            "kind": "autopsy_alignment_plus_judgment_schema",
            "fills": False,
            "evolutionary_spawn": False,
            "influences_live": False,
            "rows_considered": int(feed.get("count") or 0),
            "note": (
                "Observe shadow hook: Package M learning_point_forward feed + "
                "judgment checklist schema. No paper fills; no sealed spawn "
                "until Q8B + novelty/cap (N223/N226/N227)."
            ),
        },
        "mom_levers": levers_board,
        "same_day_policy": SAME_DAY_POLICY,
        "closed_lab_episodes": len(closed),
        "closed_episodes_sample": closed[:10],
        "active_sealed_children": len(children),
        "active_children_sample": children[:10],
        "thin_emit": {
            "min_closes": THIN_EMIT_MIN_CLOSES,
            "mom_role": "optional_diagnostic_companion",
            "scaffold_proposal": sample_proposal,
        },
        "novelty_gate": novelty,
        "concurrent_cap": cap,
        "cull": cull,
        "start_gate": start_gate_eval,
        "start_gate_cohort": {
            "proposed_n": proposed_n,
            "frozen_n": frozen_n,
            "selection_id": gate_store.get("cohort_selection_id") or COHORT_SELECTION_ID,
            "owner_freeze_pending": bool(proposed_n) and frozen_n == 0,
        },
        "evolutionary_shadows_eligible": shadows_ok,
        "remainder_deferred": {
            "N223": "hardened proposals → new sealed twins (spawn path)",
            "N226": "full novelty/similarity distance gate",
            "N227": "full per-root cap + cull/replace factory",
            "L630": "lineage fork markers on real spawns",
            "L631": "archive frozen cull losers",
            "N228": "rule-aware LLM decide + misfit evidence trail",
            "N229": "human chart draw tools (keep deferred)",
        },
        "soft_gaps": [
            "Armed observe — still no episode walker / no live cue fills.",
            "Do not back-label cue-book NAV as lab wins.",
            "Do not open Package L on sealed; cull ≠ live promote.",
            "Evolutionary shadows wait on Q8B start gate (or calendar fallback).",
            "Owner must confirm freeze of proposed non-mechanical autopsy cohort.",
        ],
        "ops_doc": str(DEFAULT_OPS_DOC),
    }


def refresh_cue_consumer_mft(
    *,
    output_dir: Path | None = None,
    store_path: Path | None = None,
    registration_path: Path | None = None,
    start_gate_path: Path | None = None,
    queue_path: Path | None = None,
    labels_path: Path | None = None,
    persist: bool = True,
    generated_at: str | None = None,
    today: date | None = None,
    refresh_proposal: bool = False,
) -> dict[str, Any]:
    """Arm/refresh lab + start-gate evaluation; persist observe stores.

    Proposes the Q8B named cohort when none is frozen yet (sticky proposal
    unless ``refresh_proposal``). Never auto-freezes — owner CLI confirm.
    """
    data_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    reg_path = (
        Path(registration_path) if registration_path is not None else DEFAULT_REGISTRATION_PATH
    )
    gate_path = Path(start_gate_path) if start_gate_path is not None else DEFAULT_START_GATE_PATH
    labels = _safe_read(Path(labels_path) if labels_path is not None else DEFAULT_LABELS_PATH)
    queue = _safe_read(Path(queue_path) if queue_path is not None else DEFAULT_QUEUE_PATH)

    when = generated_at or _utcnow()
    prior = _safe_read(store) if store.is_file() else None
    prior_epoch = None
    prior_armed = None
    if isinstance(prior, dict):
        mid = prior.get("mid_flight_tune")
        if isinstance(mid, dict):
            prior_epoch = mid.get("knob_epoch_started_at")
        prior_armed = prior.get("lab_armed_at")

    gate_store = _safe_read(gate_path) if gate_path.is_file() else None
    if not isinstance(gate_store, dict):
        gate_store = default_start_gate_payload(generated_at=when)
    else:
        gate_store = dict(gate_store)

    frozen = [str(x).strip() for x in (gate_store.get("cohort_review_ids") or []) if str(x).strip()]
    proposed = [
        str(x).strip()
        for x in (gate_store.get("proposed_cohort_review_ids") or [])
        if str(x).strip()
    ]
    # Propose sticky cohort when nothing frozen yet (do not invent freeze).
    if not frozen and (refresh_proposal or not proposed):
        proposal = propose_start_cohort(queue)
        gate_store["proposed_cohort_review_ids"] = list(
            proposal.get("proposed_cohort_review_ids") or []
        )
        gate_store["proposed_at"] = when
        gate_store["cohort_selection_id"] = proposal.get("selection_id") or COHORT_SELECTION_ID
        gate_store["proposal_summary"] = {
            "proposed_cohort_size": proposal.get("proposed_cohort_size"),
            "by_exit_reason": proposal.get("by_exit_reason"),
            "by_book_id": proposal.get("by_book_id"),
            "owner_decision": proposal.get("owner_decision"),
            "excludes": proposal.get("excludes"),
        }

    start_eval = evaluate_start_gate(start_gate=gate_store, labels=labels, today=today)
    gate_store["generated_at"] = when
    gate_store["checkpoint_id"] = gate_store.get("checkpoint_id") or START_CHECKPOINT_ID
    gate_store["cohort_selection_id"] = gate_store.get("cohort_selection_id") or COHORT_SELECTION_ID
    gate_store["checkpoint_status"] = start_eval["checkpoint_status"]
    if start_eval["cohort_complete"] and not gate_store.get("completed_at"):
        gate_store["completed_at"] = when
    gate_store["last_evaluation"] = {
        "eligible": start_eval["eligible"],
        "eligibility_reason": start_eval["eligibility_reason"],
        "cohort_remaining_n": len(start_eval.get("cohort_remaining") or []),
        "calendar_ok": start_eval["calendar_ok"],
        "proposed_n": len(
            [x for x in (gate_store.get("proposed_cohort_review_ids") or []) if str(x).strip()]
        ),
        "frozen_n": len(frozen),
        "evaluated_at": when,
    }

    feed = build_autopsy_alignment_feed(queue)
    payload = build_lab_payload(
        start_gate_eval=start_eval,
        generated_at=when,
        knob_epoch_started_at=str(prior_epoch) if prior_epoch else when,
        lab_armed_at=str(prior_armed) if prior_armed else when,
        autopsy_alignment_feed=feed,
        start_gate_store=gate_store,
    )
    registration = build_registration_payload()

    if persist:
        store.parent.mkdir(parents=True, exist_ok=True)
        write_json(store, payload, compact=False)
        write_json(reg_path, registration, compact=False)
        write_json(gate_path, gate_store, compact=False)
        payload["store_path"] = str(store)
        payload["registration_path"] = str(reg_path)
        payload["start_gate_path"] = str(gate_path)
        _ = data_dir
    return payload


def ops_findings_from_cue_consumer_mft(payload: dict[str, Any]) -> list[dict[str, Any]]:
    gate = payload.get("start_gate") if isinstance(payload.get("start_gate"), dict) else {}
    cohort = (
        payload.get("start_gate_cohort")
        if isinstance(payload.get("start_gate_cohort"), dict)
        else {}
    )
    findings: list[dict[str, Any]] = [
        {
            "severity": "info",
            "category": CATEGORY,
            "title": FINDING_TITLE,
            "summary": (
                f"Lab {LAB_ID} ({REGISTRATION_ID}) armed/refreshed; "
                f"pipeline={payload.get('pipeline_status')}; "
                f"closed_lab_episodes={payload.get('closed_lab_episodes', 0)}; "
                f"start_gate_eligible={bool(payload.get('evolutionary_shadows_eligible'))} "
                f"({gate.get('eligibility_reason')}). "
                "Observe-only; influences_live=false; declared incomparable; "
                "no Package L / no strand-A promote; does not steal Data P1 fat slot."
            ),
            "auto_fixable": False,
        }
    ]
    if payload.get("lab_armed_at") and payload.get("pipeline_status") in {
        PIPELINE_STATUS_ARMED,
        PIPELINE_STATUS_SHADOWS_OK,
    }:
        findings.append(
            {
                "severity": "info",
                "category": CATEGORY,
                "title": LAB_ARMED_TITLE,
                "summary": (
                    f"Lab arm marker {LAB_ARM_MARKER_ID} at "
                    f"{payload.get('lab_armed_at')}; epoch "
                    f"{(payload.get('mid_flight_tune') or {}).get('knob_epoch_started_at')}; "
                    f"tune_spec={TUNE_SPEC_ID}. Observe shadow pass runs "
                    "(autopsy alignment feed + judgment schema stub). No fills; "
                    "evolutionary shadows still gated by Q8B/calendar."
                ),
                "auto_fixable": False,
            }
        )
    if cohort.get("owner_freeze_pending"):
        findings.append(
            {
                "severity": "info",
                "category": CATEGORY,
                "title": COHORT_FREEZE_PROPOSED_TITLE,
                "summary": (
                    f"Q8B checkpoint {START_CHECKPOINT_ID} has "
                    f"{cohort.get('proposed_n')} proposed non-mechanical "
                    f"review_ids ({cohort.get('selection_id')}) and 0 frozen. "
                    "Owner decision: confirm freeze via "
                    "`ftse-cue-consumer-mft freeze-cohort --apply` (or rebuild "
                    "with propose-cohort). Evolutionary shadows wait on "
                    f"freeze+completion or calendar {CALENDAR_FALLBACK}. "
                    "Still observe-only; no Package L."
                ),
                "auto_fixable": False,
            }
        )
    if payload.get("evolutionary_shadows_eligible"):
        findings.append(
            {
                "severity": "info",
                "category": CATEGORY,
                "title": START_GATE_ELIGIBLE_TITLE,
                "summary": (
                    f"Q8B start gate eligible via {gate.get('eligibility_reason')} "
                    f"(checkpoint={gate.get('checkpoint_id')}). First evolutionary "
                    "shadows may be considered under novelty/cap/cull — still "
                    "observe-only; cull≠live promote; no Package L."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def format_cue_consumer_mft_text(payload: dict[str, Any]) -> str:
    gate = payload.get("start_gate") if isinstance(payload.get("start_gate"), dict) else {}
    cohort = (
        payload.get("start_gate_cohort")
        if isinstance(payload.get("start_gate_cohort"), dict)
        else {}
    )
    lines = [
        f"Cue-consumer MFT lab ({payload.get('registration_id')})",
        f"  status: {payload.get('status')} / {payload.get('pipeline_status')}",
        f"  lab_armed_at: {payload.get('lab_armed_at')}",
        f"  influences_live: {payload.get('influences_live')}",
        f"  scoreboard: {payload.get('scoreboard_id')} (declared incomparable)",
        f"  closed_lab_episodes: {payload.get('closed_lab_episodes')}",
        f"  start_gate eligible: {payload.get('evolutionary_shadows_eligible')} "
        f"({gate.get('eligibility_reason')})",
        f"  cohort proposed/frozen: {cohort.get('proposed_n')}/{cohort.get('frozen_n')} "
        f"(owner_freeze_pending={cohort.get('owner_freeze_pending')})",
        f"  ops: {payload.get('ops_doc')}",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "CALENDAR_FALLBACK",
    "COHORT_FREEZE_PROPOSED_TITLE",
    "COHORT_SELECTION_ID",
    "CUE_WHITELIST",
    "CUE_WHITELIST_ID",
    "DEFAULT_OPS_DOC",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_REGISTRATION_PATH",
    "DEFAULT_START_GATE_PATH",
    "DEFAULT_STORE_PATH",
    "FINDING_TITLE",
    "FIXED_STAKE_UNITS",
    "LAB_ARMED_TITLE",
    "LAB_ARM_MARKER_ID",
    "LAB_ID",
    "PER_ROOT_ACTIVE_CAP",
    "PIPELINE_STATUS_ARMED",
    "REGISTRATION_ID",
    "SCOREBOARD_ID",
    "START_CHECKPOINT_ID",
    "START_GATE_ELIGIBLE_TITLE",
    "STORE_FAILED_TITLE",
    "THIN_EMIT_MIN_CLOSES",
    "TUNE_SPEC_ID",
    "assess_same_day_round_trip",
    "build_autopsy_alignment_feed",
    "build_hardened_proposal_stub",
    "build_lab_payload",
    "build_registration_payload",
    "concurrent_cap_stub",
    "cull_stub",
    "default_start_gate_payload",
    "evaluate_start_gate",
    "format_cue_consumer_mft_text",
    "freeze_start_cohort",
    "judgment_in_the_round_stub",
    "novelty_fingerprint",
    "novelty_gate_stub",
    "ops_findings_from_cue_consumer_mft",
    "propose_start_cohort",
    "refresh_cue_consumer_mft",
    "same_day_round_trip",
    "select_pit_cues",
    "thin_emit_readiness",
]
