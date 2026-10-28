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
PIPELINE_STATUS_WALKER = "episode_walker_active"
LAB_ARM_MARKER_ID = "mft-lab-arm-epoch0-v0"
JUDGMENT_RUBRIC_ID = "judgment_in_the_round_v0"
AUTOPSY_FEED_CAP = 25

FINDING_TITLE = "Cue-consumer MFT lab refreshed"
STORE_FAILED_TITLE = "Cue-consumer MFT lab failed"
START_GATE_ELIGIBLE_TITLE = "Cue-consumer MFT start gate eligible (evolutionary shadows)"
LAB_ARMED_TITLE = "Cue-consumer MFT lab armed (observe)"
COHORT_FREEZE_PROPOSED_TITLE = "Cue-consumer MFT Q8B cohort freeze proposed — owner confirm"
WALKER_FINDING_TITLE = "Cue-consumer MFT episode walker (lab paper fills)"
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


def _judgment_cell(
    *,
    answer: Any = None,
    confidence: str | None = None,
    cites: list[str] | None = None,
    unknown: bool | None = None,
) -> dict[str, Any]:
    cite_list = [str(c).strip() for c in (cites or []) if str(c).strip()]
    is_unknown = bool(unknown) if unknown is not None else (answer is None and not cite_list)
    return {
        "answer": None if is_unknown and answer is None else answer,
        "confidence": confidence,
        "cites": cite_list,
        "unknown": is_unknown,
    }


def judgment_in_the_round_stub() -> dict[str, Any]:
    """Empty observe-only checklist schema (fail-closed; no live influence)."""
    buy = {key: _judgment_cell(unknown=True) for key in ("B1", "B2", "B3", "B4", "B5", "B6")}
    sell = {key: _judgment_cell(unknown=True) for key in ("S1", "S2", "S3", "S4", "S5", "S6")}
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
        "fill_status": "schema_only",
        "fill_source": None,
        "note": (
            "Schema stub — use fill_judgment_in_the_round for durable cites. "
            "Missing cites fail-close influence (influences_live=false)."
        ),
    }


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _row_cite(row: dict[str, Any], key: str) -> str | None:
    if key not in row:
        return None
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    if len(text) > 160:
        text = text[:157] + "..."
    return f"{key}={text}"


def authorize_judgment_live_influence(judgment: dict[str, Any] | None) -> bool:
    """Fail-closed: lab judgment never authorizes live capital influence.

    Even a fully cited checklist stays observe-only on ``cue_consumer_mft``.
    """
    if not isinstance(judgment, dict):
        return False
    if judgment.get("influences_live") is True:
        # Hard strip path — never honor a true flag on this instrument.
        return False
    if judgment.get("observe_only") is False:
        return False
    return False


def judgment_has_durable_cites(judgment: dict[str, Any] | None) -> bool:
    """True when at least one buy/sell cell carries a non-empty cite list."""
    if not isinstance(judgment, dict):
        return False
    for side in ("buy", "sell"):
        block = judgment.get(side) or {}
        if not isinstance(block, dict):
            continue
        for cell in block.values():
            if isinstance(cell, dict) and any(str(c).strip() for c in (cell.get("cites") or [])):
                return True
    return False


def fill_judgment_in_the_round(
    *,
    side: str = "buy",
    cue_source_id: str | None = None,
    clear_note: str | None = None,
    entry_detail: dict[str, Any] | None = None,
    row: dict[str, Any] | None = None,
    exit_reason: str | None = None,
    hold_trading_days: int | None = None,
    same_day_assessment: dict[str, Any] | None = None,
    return_pct: float | None = None,
    autopsy_alignment_rows: list[dict[str, Any]] | None = None,
    hold_policy_days: int = 63,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic N228 enrich: cite screen/cue/exit fields into the checklist.

    Observe-only. Missing fields stay ``unknown`` (fail-closed). Never sets
    ``influences_live=true``. Rules remain scaffold/propose; misfits emit
    structured ``misfit_evidence`` rather than silent knobs.
    """
    judgment = base if isinstance(base, dict) else judgment_in_the_round_stub()
    # Always clone so callers cannot mutate a shared stub.
    judgment = json.loads(json.dumps(judgment))
    judgment["influences_live"] = False
    judgment["observe_only"] = True
    judgment["rules_role"] = "scaffold_propose"
    judgment["fill_source"] = "deterministic_n228_v0"
    judgment.pop("deferred_id", None)

    detail = entry_detail if isinstance(entry_detail, dict) else {}
    screen = row if isinstance(row, dict) else {}
    cue_id = str(cue_source_id or detail.get("cue_source_id") or "").strip() or None
    note = str(clear_note or "").strip() or None

    buy = judgment.setdefault("buy", {})
    sell = judgment.setdefault("sell", {})

    if side in {"buy", "both"}:
        # B1 — fundamentals / bind cheapness (screen families + research).
        b1_cites: list[str] = []
        for key in (
            "passed_families",
            "models_passed",
            "weighted_model_score",
            "research_verdict",
            "fcf_basis_overlay",
            "earnings_basis_overlay",
            "data_quality_score",
        ):
            cite = _row_cite(screen, key)
            if cite:
                b1_cites.append(cite)
        verdict = detail.get("research_verdict")
        if verdict is not None and not any(c.startswith("research_verdict=") for c in b1_cites):
            b1_cites.append(f"research_verdict={verdict}")
        families = str(screen.get("passed_families") or "").lower()
        if b1_cites:
            cheap = "cheapness" in families or "cheap" in families
            answer = (
                "screen_families_include_cheapness"
                if cheap
                else "fundamentals_cited_partial"
            )
            buy["B1"] = _judgment_cell(
                answer=answer,
                confidence="medium" if cheap else "low",
                cites=b1_cites,
                unknown=False,
            )
        else:
            buy["B1"] = _judgment_cell(unknown=True)

        # B2 — technicals / timing at entry.
        b2_cites: list[str] = []
        timing = detail.get("timing_signal")
        if timing is None:
            timing = screen.get("timing_signal")
        if timing is not None and str(timing).strip() and str(timing).lower() != "nan":
            b2_cites.append(f"timing_signal={timing}")
        for key in ("timing_score", "price_vs_sma200_pct", "volume_ratio_20", "signal_trend"):
            cite = _row_cite(screen, key)
            if cite:
                b2_cites.append(cite)
        if b2_cites:
            timing_txt = str(timing or "").strip().lower()
            if timing_txt == "wait":
                answer_b2 = "timing_wait_not_ideal"
                conf_b2 = "low"
            elif timing_txt in {"buy", "enter", "ok", "neutral"}:
                answer_b2 = f"timing_{timing_txt}_cited"
                conf_b2 = "medium" if timing_txt != "neutral" else "low"
            else:
                answer_b2 = "technicals_cited"
                conf_b2 = "low"
            buy["B2"] = _judgment_cell(
                answer=answer_b2, confidence=conf_b2, cites=b2_cites, unknown=False
            )
        else:
            buy["B2"] = _judgment_cell(unknown=True)

        # B3 — market / peer context (thin: sector + weeks_at_signal).
        b3_cites: list[str] = []
        for key in ("sector", "weeks_at_signal", "market_id", "market"):
            cite = _row_cite(screen, key)
            if cite:
                b3_cites.append(cite)
        if b3_cites:
            buy["B3"] = _judgment_cell(
                answer="sector_context_cited",
                confidence="low",
                cites=b3_cites,
                unknown=False,
            )
        else:
            buy["B3"] = _judgment_cell(unknown=True)

        # B4 — registered rule / cue proposes (scaffold).
        b4_cites: list[str] = []
        if cue_id:
            b4_cites.append(f"cue_source_id={cue_id}")
        b4_cites.append(f"cue_whitelist_id={CUE_WHITELIST_ID}")
        if note:
            b4_cites.append(f"clear_note={note}")
        signal = detail.get("signal") or screen.get("signal")
        if signal is not None and str(signal).strip():
            b4_cites.append(f"signal={signal}")
        adjusted = detail.get("adjusted_signal") or screen.get("adjusted_signal")
        if adjusted is not None and str(adjusted).strip():
            b4_cites.append(f"adjusted_signal={adjusted}")
        if cue_id:
            buy["B4"] = _judgment_cell(
                answer="cue_whitelist_proposes",
                confidence="medium" if note and "clear" in note else "low",
                cites=b4_cites,
                unknown=False,
            )
        else:
            buy["B4"] = _judgment_cell(unknown=True)

        judgment["rule_candidates"] = (
            [
                {
                    "rule_id": cue_id,
                    "role": "scaffold_propose",
                    "cue_whitelist_id": CUE_WHITELIST_ID,
                    "clear_note": note,
                }
            ]
            if cue_id
            else []
        )

        # B5 — confidence + why.
        b5_cites: list[str] = []
        conviction = _finite_float(detail.get("conviction_score"))
        if conviction is None:
            conviction = _finite_float(screen.get("conviction_score"))
        if conviction is not None:
            b5_cites.append(f"conviction_score={conviction}")
        research_conf = _finite_float(screen.get("research_confidence"))
        if research_conf is not None:
            b5_cites.append(f"research_confidence={research_conf}")
        if verdict is not None:
            b5_cites.append(f"research_verdict={verdict}")
        if b5_cites:
            if conviction is not None and conviction >= 0.6 and str(verdict) == "accumulate":
                answer_b5 = "high_conviction_accumulate"
                conf_b5 = "high"
            elif conviction is not None and conviction >= 0.4:
                answer_b5 = "moderate_conviction"
                conf_b5 = "medium"
            else:
                answer_b5 = "low_or_partial_conviction"
                conf_b5 = "low"
            buy["B5"] = _judgment_cell(
                answer=answer_b5, confidence=conf_b5, cites=b5_cites, unknown=False
            )
        else:
            buy["B5"] = _judgment_cell(unknown=True)

        # B6 — mitigate if wrong (pre-declared exit family / trade plan cites).
        b6_cites = [
            f"hold_policy_trading_days={hold_policy_days}",
            "exit_family=hold_trading_days_or_identity_break",
            "sizing=fixed_stake_v0",
        ]
        plan = _row_cite(screen, "trade_plan_summary")
        if plan:
            b6_cites.append(plan)
        for key in ("tactical_stop_loss", "tactical_take_profit"):
            cite = _row_cite(screen, key)
            if cite:
                b6_cites.append(cite)
        for feed_row in (autopsy_alignment_rows or [])[:3]:
            if not isinstance(feed_row, dict):
                continue
            forward = str(feed_row.get("learning_point_forward") or "").strip()
            rid = str(feed_row.get("review_id") or "").strip()
            if forward and rid:
                b6_cites.append(f"autopsy_learning_point_forward:{rid}={forward[:120]}")
        buy["B6"] = _judgment_cell(
            answer="predeclared_hold_or_identity_break_within_fixed_stake",
            confidence="medium",
            cites=b6_cites,
            unknown=False,
        )

    if side in {"sell", "both"}:
        exit_txt = str(exit_reason or "").strip()
        same_day = same_day_assessment if isinstance(same_day_assessment, dict) else {}

        # S1 — thesis still valid?
        s1_cites: list[str] = []
        if exit_txt:
            s1_cites.append(f"exit_reason={exit_txt}")
        if cue_id:
            s1_cites.append(f"entry_cue_source_id={cue_id}")
        if note:
            s1_cites.append(f"entry_clear_note={note}")
        if s1_cites:
            if exit_txt.startswith("identity_break"):
                answer_s1 = "entry_identity_broken"
            elif exit_txt == "hold_trading_days":
                answer_s1 = "hold_horizon_reached_thesis_timebox"
            else:
                answer_s1 = "exit_reason_cited"
            sell["S1"] = _judgment_cell(
                answer=answer_s1, confidence="medium", cites=s1_cites, unknown=False
            )
        else:
            sell["S1"] = _judgment_cell(unknown=True)

        # S2 — target realistic now? (fair-cost path cite when closed).
        s2_cites: list[str] = []
        ret = _finite_float(return_pct)
        if ret is not None:
            s2_cites.append(f"fair_cost_return_pct={ret}")
        if hold_trading_days is not None:
            s2_cites.append(f"hold_trading_days={hold_trading_days}")
        if s2_cites:
            sell["S2"] = _judgment_cell(
                answer="path_cited_at_exit",
                confidence="low",
                cites=s2_cites,
                unknown=False,
            )
        else:
            sell["S2"] = _judgment_cell(unknown=True)

        # S3 — market agree with trajectory?
        s3_cites: list[str] = []
        if ret is not None:
            s3_cites.append(f"fair_cost_return_pct={ret}")
            s3_cites.append(
                "path_sign=" + ("positive" if ret > 0 else "negative" if ret < 0 else "flat")
            )
        if same_day.get("same_calendar_day") is not None:
            s3_cites.append(f"same_calendar_day={same_day.get('same_calendar_day')}")
        if s3_cites:
            sell["S3"] = _judgment_cell(
                answer="exit_path_cited",
                confidence="low",
                cites=s3_cites,
                unknown=False,
            )
        else:
            sell["S3"] = _judgment_cell(unknown=True)

        # S4 — registered exit rule fires?
        s4_cites: list[str] = []
        if exit_txt:
            s4_cites.append(f"exit_reason={exit_txt}")
            s4_cites.append("rules_role=scaffold_propose")
        if s4_cites:
            sell["S4"] = _judgment_cell(
                answer="registered_lab_exit_rule_fires",
                confidence="medium",
                cites=s4_cites,
                unknown=False,
            )
        else:
            sell["S4"] = _judgment_cell(unknown=True)

        # S5 — confidence + why.
        s5_cites: list[str] = []
        if exit_txt:
            s5_cites.append(f"exit_reason={exit_txt}")
        if same_day:
            s5_cites.append(f"same_day_soft_bias={same_day.get('soft_bias')}")
            s5_cites.append(f"same_day_hard_ban={same_day.get('hard_ban')}")
            if same_day.get("exception"):
                s5_cites.append(f"same_day_exception={same_day.get('exception')}")
        if s5_cites:
            conf_s5 = "low" if same_day.get("same_calendar_day") else "medium"
            sell["S5"] = _judgment_cell(
                answer="exit_confidence_from_rule_and_same_day_policy",
                confidence=conf_s5,
                cites=s5_cites,
                unknown=False,
            )
        else:
            sell["S5"] = _judgment_cell(unknown=True)

        # S6 — mitigate.
        s6_cites = [
            "sizing=fixed_stake_v0",
            "observe_only=true",
            "package_l=false",
        ]
        if hold_trading_days is not None:
            s6_cites.append(f"hold_trading_days={hold_trading_days}")
        for feed_row in (autopsy_alignment_rows or [])[:3]:
            if not isinstance(feed_row, dict):
                continue
            forward = str(feed_row.get("learning_point_forward") or "").strip()
            rid = str(feed_row.get("review_id") or "").strip()
            if forward and rid:
                s6_cites.append(f"autopsy_learning_point_forward:{rid}={forward[:120]}")
        sell["S6"] = _judgment_cell(
            answer="fixed_stake_close_plus_hold_counterfactual_trail",
            confidence="medium",
            cites=s6_cites,
            unknown=False,
        )

    # Stance + misfit trail (deterministic agree/veto within rule set).
    misfit: dict[str, Any] | None = None
    stance = "agree"
    timing_val = str(
        (entry_detail or {}).get("timing_signal")
        or (row or {}).get("timing_signal")
        or ""
    ).strip().lower()
    if side in {"buy", "both"} and timing_val == "wait" and cue_id:
        stance = "misfit"
        misfit = {
            "rule_id": cue_id,
            "decision_code": "timing_wait_vs_cue_propose",
            "cite": [
                f"timing_signal={timing_val}",
                f"cue_source_id={cue_id}",
            ],
            "why_unfit": (
                "Whitelist cue proposes entry while timing_signal=wait — "
                "record misfit for future experimental timing rule; do not "
                "silently invent live knobs."
            ),
            "proposed_experiment_hint": "entry_lens_timing_wait_gate",
        }
    if side in {"sell", "both"} and isinstance(same_day_assessment, dict):
        if same_day_assessment.get("same_calendar_day") and not same_day_assessment.get(
            "major_error_reverse"
        ):
            stance = "misfit" if stance == "agree" else stance
            misfit = {
                "rule_id": str(exit_reason or "same_day_exit"),
                "decision_code": "same_day_exit_without_major_error_reverse",
                "cite": [
                    f"same_calendar_day={same_day_assessment.get('same_calendar_day')}",
                    f"exit_reason={exit_reason}",
                ],
                "why_unfit": (
                    "Same-calendar-day exit without durable major_error_reverse "
                    "evidence — soft-bias misfit for sell_timing lever."
                ),
                "proposed_experiment_hint": "sell_lens_same_day_bias",
            }

    judgment["llm_stance"] = stance
    judgment["misfit_evidence"] = misfit

    # Coverage + fail-closed note.
    unknown_cells: list[str] = []
    cited_cells: list[str] = []
    for label, block in (("B", judgment.get("buy") or {}), ("S", judgment.get("sell") or {})):
        if not isinstance(block, dict):
            continue
        for key, cell in block.items():
            if not isinstance(cell, dict):
                continue
            name = str(key)
            if cell.get("unknown"):
                unknown_cells.append(name)
            elif cell.get("cites"):
                cited_cells.append(name)

    judgment["fill_status"] = "filled" if cited_cells else "schema_only"
    judgment["cells_cited"] = cited_cells
    judgment["cells_unknown"] = unknown_cells
    judgment["influences_live"] = False
    judgment["note"] = (
        "N228 deterministic judgment-in-the-round fill on decide trail. "
        "Rules scaffold/propose; missing cells stay unknown; "
        "authorize_judgment_live_influence always false."
    )
    # Belt-and-braces: never allow influence even if a caller flipped flags.
    assert authorize_judgment_live_influence(judgment) is False
    return judgment


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


_CLEARING_LABEL_ACTIONS = frozenset(
    {
        "accept",
        "comment",
        "duplicate",
        "accepted",
        "commented",
        "duplicated",
    }
)


def _label_history_index(labels: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map review_id → latest label row from post_sale_review_labels.json."""
    if not isinstance(labels, dict):
        return {}
    index: dict[str, dict[str, Any]] = {}
    # Canonical Package M store uses top-level ``events`` (kind=accept/comment/…).
    # Older fixtures used ``history`` / ``labels`` / ``by_review_id``.
    history = labels.get("history") or labels.get("labels") or labels.get("events") or []
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


def _row_clearing_action(row: dict[str, Any]) -> str:
    return str(row.get("action") or row.get("label") or row.get("kind") or "").strip().lower()


def _actioned_review_ids(labels: dict[str, Any] | None) -> set[str]:
    """Review IDs that left the active queue via Accept/Comment (or Duplicate).

    Joins the live Package M labels shape:
    - canonical ``actioned_review_ids`` list (same source as queue clear)
    - top-level ``events`` rows with ``kind`` in accept/comment/duplicate
    - legacy ``history`` / ``by_review_id`` fixtures (``action`` / ``label`` / ``kind``)
    """
    actioned: set[str] = set()
    if not isinstance(labels, dict):
        return actioned

    for item in labels.get("actioned_review_ids") or []:
        rid = str(item or "").strip()
        if rid:
            actioned.add(rid)

    # Top-level events (and nested events under indexed rows).
    for row in labels.get("events") or []:
        if not isinstance(row, dict):
            continue
        if _row_clearing_action(row) not in _CLEARING_LABEL_ACTIONS:
            continue
        rid = str(row.get("review_id") or row.get("id") or "").strip()
        if rid:
            actioned.add(rid)

    index = _label_history_index(labels)
    for rid, row in index.items():
        if _row_clearing_action(row) in _CLEARING_LABEL_ACTIONS:
            actioned.add(rid)
        for ev in row.get("events") or []:
            if not isinstance(ev, dict):
                continue
            if _row_clearing_action(ev) in _CLEARING_LABEL_ACTIONS:
                actioned.add(rid)
    return actioned


def _usable_active_review_ids(queue: dict[str, Any] | None) -> set[str]:
    """Active queue ids the dashboard can render (ticker + book present).

    Matches ``postSaleReviewCardUsable`` in ``docs/app.js`` — blank/? cards are
    invisible to the owner even when still listed in ``active``.
    """
    usable: set[str] = set()
    if not isinstance(queue, dict):
        return usable
    for row in queue.get("active") or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("review_id") or "").strip()
        if not rid:
            continue
        ticker = str(row.get("ticker") or "").strip()
        book = str(row.get("book_tag") or row.get("book_id") or "").strip()
        if not ticker or ticker == "?" or not book or book == "?":
            continue
        usable.add(rid)
    return usable


def classify_cohort_remaining(
    remaining: list[str],
    *,
    queue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Split gate remaining into renderable-active vs ghosts (not UI-visible)."""
    rem = [str(x).strip() for x in remaining if str(x).strip()]
    usable = _usable_active_review_ids(queue)
    in_active = [rid for rid in rem if rid in usable]
    ghosts = [rid for rid in rem if rid not in usable]
    return {
        "remaining_in_active": in_active,
        "remaining_in_active_n": len(in_active),
        "remaining_ghosts": ghosts,
        "remaining_ghosts_n": len(ghosts),
    }


def heal_q8b_cohort_ghosts(
    data_dir: Path,
    *,
    start_gate: dict[str, Any] | None,
    labels: dict[str, Any] | None,
    queue: dict[str, Any] | None,
    source: str = "q8b_start_gate_ghost_heal",
    acted_by: str = "ops_heal",
) -> dict[str, Any]:
    """Durable Duplicate-clear frozen cohort ids the owner cannot see on the list.

    Ghosts = checkpoint remaining that are absent from the usable active queue
    (ENI/STR/LOGN pattern: left active unlabeled, or blank/? unrenderable cards).
    Does **not** auto-clear unique usable active episodes — those need owner
    Accept/Comment/Duplicate or an explicit ops clear.
    """
    from value_investor.post_sale_review_labels import record_duplicate

    gate = start_gate if isinstance(start_gate, dict) else {}
    cohort = [str(x).strip() for x in (gate.get("cohort_review_ids") or []) if str(x).strip()]
    actioned = _actioned_review_ids(labels)
    remaining = [rid for rid in cohort if rid not in actioned]
    classified = classify_cohort_remaining(remaining, queue=queue)
    ghosts = list(classified.get("remaining_ghosts") or [])
    cleared: list[str] = []
    errors: list[dict[str, str]] = []
    active_by_id = {
        str(row.get("review_id") or "").strip(): row
        for row in ((queue or {}).get("active") or [])
        if isinstance(row, dict) and str(row.get("review_id") or "").strip()
    }
    note = (
        "Q8B ghost clear: frozen cohort id not renderable on autopsy list "
        "(absent from usable active queue); durable Duplicate so checkpoint "
        "cannot remain pointing at an invisible card. No fabricated "
        "Accept/Comment text."
    )
    for rid in ghosts:
        snap = active_by_id.get(rid) if rid in active_by_id else {"review_id": rid}
        try:
            record_duplicate(
                Path(data_dir),
                review_id=rid,
                tag_at_action="new",
                note=note,
                source=source,
                acted_by=acted_by,
                snapshot=snap if isinstance(snap, dict) else {"review_id": rid},
            )
            cleared.append(rid)
        except Exception as exc:  # noqa: BLE001 — heal must not abort refresh
            errors.append({"review_id": rid, "error": str(exc)})
    return {
        "ghosts_found": ghosts,
        "ghosts_found_n": len(ghosts),
        "cleared": cleared,
        "cleared_n": len(cleared),
        "errors": errors,
        "remaining_in_active_n": int(classified.get("remaining_in_active_n") or 0),
    }


def evaluate_start_gate(
    *,
    start_gate: dict[str, Any] | None,
    labels: dict[str, Any] | None = None,
    queue: dict[str, Any] | None = None,
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
    classified = classify_cohort_remaining(remaining, queue=queue)
    cohort_complete = bool(cohort) and not remaining
    if status in {"complete", "completed", "done"} and gate.get("completed_at"):
        cohort_complete = True
        remaining = []
        classified = classify_cohort_remaining([], queue=queue)

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
        "cohort_remaining_n": len(remaining),
        "cohort_remaining": remaining[:20],
        "cohort_remaining_in_active": list(classified.get("remaining_in_active") or [])[:20],
        "cohort_remaining_in_active_n": int(classified.get("remaining_in_active_n") or 0),
        "cohort_remaining_ghosts": list(classified.get("remaining_ghosts") or [])[:20],
        "cohort_remaining_ghosts_n": int(classified.get("remaining_ghosts_n") or 0),
        "cohort_complete": cohort_complete,
        "calendar_fallback": CALENDAR_FALLBACK,
        "calendar_ok": calendar_ok,
        "eligible": eligible,
        "eligibility_reason": reason,
        "not_gate": "active_count==0_forever_wait_while_just_sold_refills",
        "how_measured": (
            "Freeze open-autopsy review_ids into cue_consumer_mft_start_gate.json "
            f"cohort_review_ids under checkpoint_id={checkpoint_id}. Complete when "
            "each id is Accept/Comment-actioned in post_sale_review_labels "
            "(actioned_review_ids + events.kind) — new just_sold refill of the "
            "active queue does not reopen the checkpoint. "
            "Remaining ids absent from the usable active autopsy list are ghosts "
            "(auto Duplicate-healed on refresh). "
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
    open_lab_episodes: list[dict[str, Any]] | None = None,
    active_children: list[dict[str, Any]] | None = None,
    autopsy_alignment_feed: dict[str, Any] | None = None,
    start_gate_store: dict[str, Any] | None = None,
    episode_walker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build observe store payload (armed observe + optional lab paper walker)."""
    when = generated_at or _utcnow()
    epoch_at = knob_epoch_started_at or when
    armed_at = lab_armed_at or when
    closed = [e for e in (closed_lab_episodes or []) if isinstance(e, dict)]
    open_eps = [e for e in (open_lab_episodes or []) if isinstance(e, dict)]
    children = [c for c in (active_children or []) if isinstance(c, dict)]
    gate_store = start_gate_store if isinstance(start_gate_store, dict) else {}
    shadows_ok = bool(start_gate_eval.get("eligible"))
    walker = episode_walker if isinstance(episode_walker, dict) else {}
    walker_active = str(walker.get("status") or "") == "active"
    if walker_active:
        pipeline_status = PIPELINE_STATUS_WALKER
    elif shadows_ok:
        pipeline_status = PIPELINE_STATUS_SHADOWS_OK
    else:
        pipeline_status = PIPELINE_STATUS_ARMED
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
        status = "awaiting_lab_closes" if not closed else "diagnostic_partial"
        levers_board.append(
            {
                **lever,
                "mom_score": None,
                "status": status,
                "diagnostic_only_until_volume": True,
            }
        )

    proposed_n = len(
        [x for x in (gate_store.get("proposed_cohort_review_ids") or []) if str(x).strip()]
    )
    frozen_n = len([x for x in (gate_store.get("cohort_review_ids") or []) if str(x).strip()])
    path_board = (
        walker.get("path_scoreboard")
        if isinstance(walker.get("path_scoreboard"), dict)
        else {
            "unit": "fair_cost_episode_pct",
            "smooth_ret_cohort_median": None,
            "completed_n": len(closed),
            "open_n": len(open_eps),
            "declared_incomparable": True,
        }
    )

    soft_gaps = [
        "Do not back-label cue-book NAV as lab wins.",
        "Do not open Package L on sealed; cull ≠ live promote.",
        "Sealed spawn / novelty / cull remain N223/N226/N227 — lab fills only in v0.",
        "N228 judgment fill is deterministic cite enrich (not live LLM API); "
        "influences_live=false forever on this lab until a separate promote gate.",
    ]
    if not shadows_ok:
        soft_gaps.insert(
            0,
            "Episode walker gated — evolutionary_shadows_eligible false (Q8B/calendar).",
        )
    elif not walker_active:
        soft_gaps.insert(0, "Start gate eligible but walker did not activate.")
    if frozen_n == 0 and proposed_n and not shadows_ok:
        soft_gaps.append("Owner must confirm freeze of proposed non-mechanical autopsy cohort.")

    # Representative judgment trail: prefer a closed/open episode evidence block.
    judgment_payload = judgment_in_the_round_stub()
    for sample in list(closed[:1]) + list(open_eps[:1]):
        if not isinstance(sample, dict):
            continue
        ev = sample.get("evidence") if isinstance(sample.get("evidence"), dict) else {}
        j = ev.get("judgment_in_the_round")
        if isinstance(j, dict) and j.get("fill_status") == "filled":
            judgment_payload = j
            break
    judgment_payload = dict(judgment_payload)
    judgment_payload["influences_live"] = False
    judgment_payload["observe_only"] = True

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
                "Lab refresh/arm + walker are JSON observe-only — never claim "
                "the Data P1 ingest fat slot / fourth equal sprint."
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
            "stub": False if walker_active else True,
            "note": (
                "PIT short whitelist; walker consumes progressive cue clears "
                "from archive screens when eligible."
                if walker_active
                else "PIT selection stub — short whitelist only; no look-ahead."
            ),
        },
        "judgment_in_the_round": judgment_payload,
        "autopsy_alignment_feed": feed,
        "observe_shadow_pass": {
            "kind": (
                "lab_paper_episode_walker"
                if walker_active
                else "autopsy_alignment_plus_judgment_schema"
            ),
            "fills": bool(walker_active),
            "evolutionary_spawn": False,
            "influences_live": False,
            "rows_considered": int(feed.get("count") or 0),
            "cues_accepted": (int(walker.get("cues_accepted") or 0) if walker_active else 0),
            "note": (
                "Lab paper fills from PIT whitelist cues (fixed-stake v0). "
                "No sealed spawn; Package L closed; influences_live=false."
                if walker_active
                else (
                    "Observe shadow hook: Package M learning_point_forward feed + "
                    "judgment checklist schema. Walker waits on Q8B/calendar."
                )
            ),
        },
        "episode_walker": {
            "walker_marker_id": walker.get("walker_marker_id"),
            "status": walker.get("status") or "absent",
            "reason": walker.get("reason"),
            "cues_considered": walker.get("cues_considered"),
            "cues_accepted": walker.get("cues_accepted"),
            "skipped_at_open_cap": walker.get("skipped_at_open_cap"),
            "hold_trading_days": walker.get("hold_trading_days"),
            "max_open_positions": walker.get("max_open_positions"),
            "path_scoreboard": path_board,
            "evolutionary_spawn": False,
            "package_l": False,
        },
        "mom_levers": levers_board,
        "same_day_policy": SAME_DAY_POLICY,
        "closed_lab_episodes": len(closed),
        "open_lab_episodes": len(open_eps),
        "closed_episodes_sample": closed[:10],
        "open_episodes_sample": open_eps[:10],
        "path_scoreboard": path_board,
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
            "N228": "shipped_deterministic_fill_v0",
            "N229": "human chart draw tools (keep deferred)",
            "L640": "dashboard / observe-utilization strip",
            "N228_llm_api": (
                "optional later: remote LLM agree/veto voice on the same "
                "checklist — still influences_live=false until promote gate"
            ),
        },
        "soft_gaps": soft_gaps,
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

    # Durable heal first: frozen cohort ids invisible on the autopsy list must
    # not keep the start gate open (ENI/STR/LOGN ghost pattern).
    ghost_heal = heal_q8b_cohort_ghosts(
        data_dir,
        start_gate=gate_store,
        labels=labels,
        queue=queue,
    )
    if int(ghost_heal.get("cleared_n") or 0) > 0:
        labels = _safe_read(Path(labels_path) if labels_path is not None else DEFAULT_LABELS_PATH)

    start_eval = evaluate_start_gate(start_gate=gate_store, labels=labels, queue=queue, today=today)
    gate_store["generated_at"] = when
    gate_store["checkpoint_id"] = gate_store.get("checkpoint_id") or START_CHECKPOINT_ID
    gate_store["cohort_selection_id"] = gate_store.get("cohort_selection_id") or COHORT_SELECTION_ID
    gate_store["checkpoint_status"] = start_eval["checkpoint_status"]
    if start_eval["cohort_complete"] and not gate_store.get("completed_at"):
        gate_store["completed_at"] = when
    gate_store["last_evaluation"] = {
        "eligible": start_eval["eligible"],
        "eligibility_reason": start_eval["eligibility_reason"],
        "cohort_remaining_n": int(
            start_eval.get("cohort_remaining_n")
            if start_eval.get("cohort_remaining_n") is not None
            else len(start_eval.get("cohort_remaining") or [])
        ),
        "cohort_actioned": int(start_eval.get("cohort_actioned") or 0),
        "cohort_remaining_in_active_n": int(start_eval.get("cohort_remaining_in_active_n") or 0),
        "cohort_remaining_ghosts_n": int(start_eval.get("cohort_remaining_ghosts_n") or 0),
        "ghost_heal_cleared_n": int(ghost_heal.get("cleared_n") or 0),
        "calendar_ok": start_eval["calendar_ok"],
        "proposed_n": len(
            [x for x in (gate_store.get("proposed_cohort_review_ids") or []) if str(x).strip()]
        ),
        "frozen_n": len(frozen),
        "evaluated_at": when,
    }

    feed = build_autopsy_alignment_feed(queue)
    epoch_at = str(prior_epoch) if prior_epoch else when

    # Lab paper episode walker — only when Q8B/calendar eligible. No sealed spawn.
    from value_investor.backtest import load_run_snapshots
    from value_investor.cue_consumer_mft_walker import (
        gated_walker_payload,
        walk_lab_paper_episodes,
    )

    if start_eval.get("eligible"):
        snapshots = load_run_snapshots(data_dir)
        walker = walk_lab_paper_episodes(
            snapshots,
            knob_epoch_started_at=epoch_at,
            lab_arm_marker_id=LAB_ARM_MARKER_ID,
            generated_at=when,
            autopsy_alignment_rows=list(feed.get("rows") or []),
        )
    else:
        walker = gated_walker_payload(
            reason=str(start_eval.get("eligibility_reason") or "start_gate_not_eligible"),
            generated_at=when,
        )

    closed_eps = [e for e in (walker.get("closed_episodes") or []) if isinstance(e, dict)]
    open_eps = [e for e in (walker.get("open_episodes") or []) if isinstance(e, dict)]
    # Persist compact samples in the store; drop full episode lists from walker blob.
    walker_public = {
        k: v for k, v in walker.items() if k not in {"closed_episodes", "open_episodes"}
    }

    payload = build_lab_payload(
        start_gate_eval=start_eval,
        generated_at=when,
        knob_epoch_started_at=epoch_at,
        lab_armed_at=str(prior_armed) if prior_armed else when,
        closed_lab_episodes=closed_eps,
        open_lab_episodes=open_eps,
        autopsy_alignment_feed=feed,
        start_gate_store=gate_store,
        episode_walker=walker_public,
    )
    registration = build_registration_payload()
    if payload.get("pipeline_status") == PIPELINE_STATUS_WALKER:
        registration["pipeline_status"] = PIPELINE_STATUS_WALKER
        registration["walker_marker_id"] = walker.get("walker_marker_id")
        registration["status"] = "observe_lab_walker_active"
    elif start_eval.get("eligible"):
        registration["pipeline_status"] = PIPELINE_STATUS_SHADOWS_OK

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
    walker = (
        payload.get("episode_walker") if isinstance(payload.get("episode_walker"), dict) else {}
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
                f"open_lab_episodes={payload.get('open_lab_episodes', 0)}; "
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
        PIPELINE_STATUS_WALKER,
    }:
        fill_note = (
            f"Lab paper walker active "
            f"(open={payload.get('open_lab_episodes', 0)}, "
            f"closed={payload.get('closed_lab_episodes', 0)}); "
            "no sealed spawn."
            if payload.get("pipeline_status") == PIPELINE_STATUS_WALKER
            else (
                "Observe shadow pass runs (autopsy alignment feed + judgment "
                "schema stub). Walker waits on Q8B/calendar."
            )
        )
        findings.append(
            {
                "severity": "info",
                "category": CATEGORY,
                "title": LAB_ARMED_TITLE,
                "summary": (
                    f"Lab arm marker {LAB_ARM_MARKER_ID} at "
                    f"{payload.get('lab_armed_at')}; epoch "
                    f"{(payload.get('mid_flight_tune') or {}).get('knob_epoch_started_at')}; "
                    f"tune_spec={TUNE_SPEC_ID}. {fill_note}"
                ),
                "auto_fixable": False,
            }
        )
    if walker.get("status") == "active":
        path = (
            walker.get("path_scoreboard") if isinstance(walker.get("path_scoreboard"), dict) else {}
        )
        findings.append(
            {
                "severity": "info",
                "category": CATEGORY,
                "title": WALKER_FINDING_TITLE,
                "summary": (
                    f"Walker {walker.get('walker_marker_id')} recorded lab paper "
                    f"fills: open={payload.get('open_lab_episodes', 0)} "
                    f"closed={payload.get('closed_lab_episodes', 0)}; "
                    f"cues_accepted={walker.get('cues_accepted')}; "
                    f"median_fair_cost_episode_pct={path.get('smooth_ret_cohort_median')}. "
                    "Fixed-stake v0; influences_live=false; declared incomparable; "
                    "no sealed spawn / no Package L; does not steal Data P1."
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
    walker = (
        payload.get("episode_walker") if isinstance(payload.get("episode_walker"), dict) else {}
    )
    path = (
        payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    )
    lines = [
        f"Cue-consumer MFT lab ({payload.get('registration_id')})",
        f"  status: {payload.get('status')} / {payload.get('pipeline_status')}",
        f"  lab_armed_at: {payload.get('lab_armed_at')}",
        f"  influences_live: {payload.get('influences_live')}",
        f"  scoreboard: {payload.get('scoreboard_id')} (declared incomparable)",
        f"  closed_lab_episodes: {payload.get('closed_lab_episodes')} "
        f"(open={payload.get('open_lab_episodes', 0)})",
        f"  walker: {walker.get('status')} (cues_accepted={walker.get('cues_accepted')})",
        f"  median fair-cost episode %: {path.get('smooth_ret_cohort_median')}",
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
    "PIPELINE_STATUS_SHADOWS_OK",
    "PIPELINE_STATUS_WALKER",
    "REGISTRATION_ID",
    "SCOREBOARD_ID",
    "START_CHECKPOINT_ID",
    "START_GATE_ELIGIBLE_TITLE",
    "STORE_FAILED_TITLE",
    "THIN_EMIT_MIN_CLOSES",
    "TUNE_SPEC_ID",
    "WALKER_FINDING_TITLE",
    "assess_same_day_round_trip",
    "build_autopsy_alignment_feed",
    "build_hardened_proposal_stub",
    "build_lab_payload",
    "build_registration_payload",
    "classify_cohort_remaining",
    "concurrent_cap_stub",
    "cull_stub",
    "default_start_gate_payload",
    "evaluate_start_gate",
    "format_cue_consumer_mft_text",
    "freeze_start_cohort",
    "heal_q8b_cohort_ghosts",
    "authorize_judgment_live_influence",
    "fill_judgment_in_the_round",
    "judgment_has_durable_cites",
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
