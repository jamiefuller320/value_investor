"""Daily hub attention: status report, Push ranker, Explore lane (locked D1–D7).

Deterministic extractors — no LLM. Push fails closed when nothing high-signal;
Explore is labeled not-today with a quality bar. Package M digest
``post_sell_cue_digest.json`` is consumed via ``hub_feed`` only (L620):
Status uses cue counts / sunday nest summary; Explore ≤2 from
``hub_feed.explore_candidates``; Push only from ``hub_feed.push_candidates``
(empty unless a cue maps to a live human gate). Fail closed if ``hub_feed``
is missing — never invent ``items`` / ``headline`` / twin stubs. This module
does not generate that digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = Path("docs/data")
SCHEMA_VERSION = 1
PUSH_CAP = 3
EXPLORE_CAP = 2

# Ops finding titles that map to human judgment / checklist action (Push).
_PUSH_FINDING_MAP: tuple[tuple[str, str, str, str], ...] = (
    (
        "Decision-review knobs saturated at bounds",
        "sunday-saturated-knobs-judgment",
        "Judge saturated decision-review knobs",
        "docs/ops/decision-review.md#saturated-knobs",
    ),
    (
        "N200 alone-path interesting — promotion design optional (F8)",
        "adhoc-n200-n201-volume-gate-review",
        "N200 interestingness — stamp disposition (no auto-promote)",
        "docs/ops/n200-tech-timing-observe.md#human-volume-gate-review",
    ),
    (
        "N201 alone-path interesting — promotion design optional (F8)",
        "adhoc-n200-n201-volume-gate-review",
        "N201 interestingness — stamp disposition (no auto-promote)",
        "docs/ops/n201-value-mom-observe.md#human-volume-gate-review",
    ),
    (
        "N206 alone-path interesting — promotion design optional (F8)",
        "adhoc-n206-volume-gate-review",
        "N206 interestingness — alone design optional (no crown)",
        "docs/ops/n206-plain-ey-observe.md#human-volume-gate-review",
    ),
    (
        "N210 alone-path interesting — promotion design optional (F8)",
        "adhoc-n210-volume-gate-review",
        "N210 interestingness — stamp disposition (no auto-promote)",
        "docs/ops/n210-ai-judgment-observe.md#human-volume-gate-review",
    ),
    (
        "Parked engineering tasks need manual review",
        "weekday-engineering-parked-backlog-clear",
        "Clear engineering parked backlog when pause still fires",
        "docs/ops/ops-monitor.md#engineering-parked-backlog-clearing",
    ),
    (
        "Deferred idea triggers met",
        "sunday-deferred-triggers",
        "Act on met deferred triggers",
        "docs/ops/deferred-triggers.md#clearing-a-finding",
    ),
    (
        "Primary book trails its control on total return",
        "sunday-assessment-scoreboard",
        "Read assessment scoreboard — primary trails control",
        "docs/ops/assessment-scoreboard.md#assessment-scoreboard",
    ),
)

# Terminal eng statuses — never Push / never Status "open" strip.
ENG_TERMINAL_STATUSES = frozenset({"merged", "cancelled", "completed", "failed"})
# Eng head eligible for Push (human confirm / parked triage).
ENG_PUSH_STATUSES = frozenset({"open", "parked"})
# Status strip may also show in-flight PR work.
ENG_STATUS_OPEN_STATUSES = frozenset({"open", "parked", "pr_open", "in_progress"})
PARKED_ENG_FINDING_TITLE = "Parked engineering tasks need manual review"
ORPHANED_PR_OPEN_FINDING_PREFIX = "Orphaned pr_open engineering tasks"
# B3 lock stamp (see b3_epoch.POLICY_ID). Present ⇒ continuity primary is
# evidentiary-demoted and anti-C (no mid-flight enlarge) is already decided.
B3_DEMOTION_POLICY_ID = "evidentiary_demotion_ai_judgment_fair_v1"
B3_DEMOTED_TRACK = "ai_judgment_fair"
SCOREBOARD_TRAIL_FINDING_TITLE = "Primary book trails its control on total return"
SATURATED_KNOBS_FINDING_TITLE = "Decision-review knobs saturated at bounds"
_SATURATED_TRACK_RE = re.compile(r"(?:^|;\s*)([A-Za-z][A-Za-z0-9_]*):\s")

# Ritual market-warn flag ids excluded from hub (D2) — stay ops-email / status.
RITUAL_MARKET_WARN_FLAG_IDS = frozenset({"health_warn", "health_warn_rollup"})

# Sibling package M may publish this; Status/Push/Explore consume hub_feed only.
POST_SELL_CUE_DIGEST_FILENAME = "post_sell_cue_digest.json"


def _safe_read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _stable_id(*parts: str) -> str:
    raw = "|".join(str(p or "").strip() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def digest_hub_feed(digest: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return package-M ``hub_feed`` when present; else None (fail closed).

    Does not invent candidates from legacy ``items`` / ``headline`` keys.
    """
    if not isinstance(digest, dict):
        return None
    hub = digest.get("hub_feed")
    if not isinstance(hub, dict):
        return None
    return hub


def post_sell_digest_status_row(digest: dict[str, Any] | None) -> dict[str, Any] | None:
    """Status strip fields from real digest cues + optional hub_feed counts."""
    if not isinstance(digest, dict):
        return None
    timing_n = len(_list_of_dicts(digest.get("timing_cues")))
    selection_n = len(_list_of_dicts(digest.get("selection_cues")))
    nest = digest.get("sunday_nest") if isinstance(digest.get("sunday_nest"), dict) else {}
    hub = digest_hub_feed(digest)
    explore_n = len(_list_of_dicts(hub.get("explore_candidates"))) if hub else None
    push_n = len(_list_of_dicts(hub.get("push_candidates"))) if hub else None
    headline = str(nest.get("summary") or "").strip()
    if not headline and (timing_n or selection_n):
        headline = f"{timing_n} timing + {selection_n} selection cues"
    if not headline and hub is not None:
        headline = (
            f"hub_feed explore={explore_n or 0} push={push_n or 0} (no timing/selection cue lists)"
        )
    if not headline:
        # Digest file present but no usable Package M fields — fail closed copy.
        headline = "present (hub_feed missing; no cue counts)"
    return {
        "present": True,
        "generated_at": digest.get("generated_at") or digest.get("updated_at"),
        "item_count": timing_n + selection_n,
        "timing_cue_count": timing_n,
        "selection_cue_count": selection_n,
        "hub_feed_present": hub is not None,
        "explore_candidate_count": explore_n,
        "push_candidate_count": push_n,
        "headline": headline,
    }


def _push_cards_from_hub_feed(
    hub: dict[str, Any],
    *,
    closed_ids: set[str],
    generated_at: str = "",
) -> list[dict[str, Any]]:
    """Map ``hub_feed.push_candidates`` → Push cards; empty list if none."""
    out: list[dict[str, Any]] = []
    for cand in _list_of_dicts(hub.get("push_candidates")):
        claim = str(cand.get("claim") or cand.get("title") or "").strip()
        why = str(
            cand.get("why_matters") or cand.get("why_now") or cand.get("summary") or ""
        ).strip()
        if not claim:
            continue
        raw_id = str(cand.get("id") or "").strip()
        dig_id = raw_id or f"push:post_sell:{_stable_id(claim, generated_at or 'v0')}"
        if not dig_id.startswith("push:"):
            dig_id = f"push:{dig_id}"
        if dig_id in closed_ids or f"push:{dig_id}" in closed_ids:
            continue
        out.append(
            {
                "id": dig_id,
                "lane": "push",
                "priority": 0,
                "title": claim,
                "why_now": why or claim,
                "cite": {
                    "kind": "artifact",
                    "ref": POST_SELL_CUE_DIGEST_FILENAME,
                    "field": "hub_feed.push_candidates",
                    "cue_id": raw_id or None,
                },
                "checklist_task_id": str(cand.get("checklist_task_id") or ""),
                "href": str(cand.get("href") or "#automation/daily"),
                "leverage": str(
                    cand.get("leverage")
                    or "Package M hub_feed push candidate — live human gate only"
                ),
                "source": "post_sell_cue_digest.hub_feed",
            }
        )
    return out


def _explore_cards_from_hub_feed(
    hub: dict[str, Any],
    *,
    closed_ids: set[str],
    cap: int,
) -> list[dict[str, Any]]:
    """Map ``hub_feed.explore_candidates`` through the Explore quality bar."""
    cards: list[dict[str, Any]] = []
    for cand in _list_of_dicts(hub.get("explore_candidates")):
        card = _normalize_explore_card(cand)
        if card is None or card["id"] in closed_ids:
            continue
        card["source"] = str(cand.get("source") or "post_sell_cue_digest")
        cards.append(card)
        if len(cards) >= cap:
            break
    return cards


def _eng_tasks(eng: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(eng, dict):
        return []
    return [t for t in (eng.get("tasks") or []) if isinstance(t, dict)]


def eng_task_is_terminal(status: Any) -> bool:
    """True when eng status means done / non-actionable for Push."""
    return str(status or "").strip().lower() in ENG_TERMINAL_STATUSES


def eng_row_is_done(row: dict[str, Any] | None) -> bool:
    """Terminal status or a merge stamp — not an open task."""
    if not isinstance(row, dict):
        return False
    if eng_task_is_terminal(row.get("status")):
        return True
    return bool(row.get("merged_at"))


def parked_eng_still_actionable(eng: dict[str, Any] | None) -> bool:
    """True when live eng queue still has attention-parked work or a clearing pause.

    Fail-closed for Push: stale ops findings about parked eng must not linger
    after merge/cancel/housekeep left the gate quiet.
    """
    eng = eng if isinstance(eng, dict) else {}
    queue_clearing = (
        eng.get("queue_clearing") if isinstance(eng.get("queue_clearing"), dict) else {}
    )
    parked = [t for t in _eng_tasks(eng) if str(t.get("status") or "") == "parked"]
    attention_rows = [
        t
        for t in parked
        if str(t.get("park_kind") or t.get("attention") or "attention") != "ignore"
    ]
    raw_count = queue_clearing.get("attention_parked_count")
    try:
        attention_count = int(raw_count) if raw_count is not None else len(attention_rows)
    except (TypeError, ValueError):
        attention_count = len(attention_rows)
    pause_active = bool(queue_clearing.get("pause_active"))
    return attention_count > 0 or pause_active


def orphaned_pr_open_still_actionable(eng: dict[str, Any] | None) -> bool:
    """True when any live eng row is still ``pr_open`` (orphan finding may apply)."""
    return any(str(t.get("status") or "") == "pr_open" for t in _eng_tasks(eng))


def load_b3_push_disposition(data_dir: Path | None) -> dict[str, Any]:
    """Committed B3 stamps that already dispose the continuity-book Push asks.

    The observe warns may stay true. These stamps mean the owner decision
    (demote evidentiary primary; do not enlarge mid-flight; matched-30 epoch
    already spawned) is locked, so the warns are not a new Push action.
    """
    root = Path(data_dir or DEFAULT_DATA_DIR)
    model = _safe_read(root / "paper_automation" / "assessment_model.json") or {}
    epoch = _safe_read(root / "b3_scoreboard_epoch_registration.json") or {}
    policies = model.get("policy_changes") if isinstance(model.get("policy_changes"), list) else []
    policy_ids = {str(row.get("id") or "") for row in policies if isinstance(row, dict)}
    epoch_policy = str(epoch.get("policy_change_id") or "")
    policy_present = B3_DEMOTION_POLICY_ID in policy_ids or epoch_policy == B3_DEMOTION_POLICY_ID
    demoted = str(epoch.get("demoted_evidentiary_primary") or B3_DEMOTED_TRACK)
    primary = str(model.get("primary_track") or "")
    if not primary and policy_present:
        primary = demoted
    explicit_primary = str(model.get("primary_track") or "")
    continuity_primary_demoted = bool(
        policy_present
        and demoted == B3_DEMOTED_TRACK
        and primary == B3_DEMOTED_TRACK
        and (not explicit_primary or explicit_primary == B3_DEMOTED_TRACK)
    )
    return {
        "policy_present": policy_present,
        "continuity_primary_demoted": continuity_primary_demoted,
        "anti_c": policy_present,
        "demoted_track": B3_DEMOTED_TRACK if policy_present else "",
        "primary_track": primary,
    }


def saturated_track_ids_from_finding(finding: dict[str, Any]) -> list[str] | None:
    """Track ids named on a saturated-knobs finding, or None if unattributed.

    Empty attribution does not suppress: another book's clamp may still be
    an open judgment.
    """
    explicit = finding.get("saturated_tracks")
    if isinstance(explicit, list):
        ids = [str(track).strip() for track in explicit if str(track).strip()]
        return ids or None
    summary = str(finding.get("summary") or "").strip()
    if not summary:
        return None
    axis = summary.split("—", 1)[1] if "—" in summary else summary
    if ". Human review" in axis:
        axis = axis.split(". Human review", 1)[0]
    ids = _SATURATED_TRACK_RE.findall(axis.strip())
    return ids or None


def b3_push_block_reason(
    title: str,
    finding: dict[str, Any],
    disposition: dict[str, Any] | None,
) -> str | None:
    """Why a still-true observe warn is not a Push / open-task card.

    None means the finding stays actionable. Does not delete the warn.
    """
    if not disposition or not disposition.get("policy_present"):
        return None
    if not isinstance(finding, dict):
        return None
    title_l = str(title or finding.get("title") or "").strip()
    trail = SCOREBOARD_TRAIL_FINDING_TITLE
    saturated = SATURATED_KNOBS_FINDING_TITLE
    if title_l == trail or trail.lower() in title_l.lower():
        if disposition.get("continuity_primary_demoted"):
            return "b3_evidentiary_demotion"
        return None
    if title_l == saturated or saturated.lower() in title_l.lower():
        if not disposition.get("anti_c"):
            return None
        tracks = saturated_track_ids_from_finding(finding)
        demoted = str(disposition.get("demoted_track") or "")
        if tracks and demoted and set(tracks) <= {demoted}:
            return "b3_anti_c_no_enlarge"
        return None
    return None


def _saturation_clauses(finding: dict[str, Any]) -> dict[str, str]:
    summary = str(finding.get("summary") or "").strip()
    axis = summary.split("—", 1)[1] if "—" in summary else summary
    if ". Human review" in axis:
        axis = axis.split(". Human review", 1)[0]
    clauses: dict[str, str] = {}
    for part in axis.split(";"):
        piece = part.strip().strip(".")
        matched = re.match(r"([A-Za-z][A-Za-z0-9_]*):\s*(.+)", piece)
        if matched:
            clauses[matched.group(1)] = matched.group(2).strip()
    return clauses


def b3_partial_gap(
    title: str,
    finding: dict[str, Any],
    disposition: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Outstanding half of a B3-touched warn, if any.

    Full disposal returns None here (the block reason covers it). A mixed
    saturation list keeps the books that are not the demoted continuity track.
    The trail warn's outstanding half is later: do not crown a new primary.
    """
    if not disposition or not disposition.get("policy_present") or not isinstance(finding, dict):
        return None
    title_l = str(title or finding.get("title") or "").strip()
    demoted = str(disposition.get("demoted_track") or "")
    if (
        title_l == SATURATED_KNOBS_FINDING_TITLE
        or SATURATED_KNOBS_FINDING_TITLE.lower() in title_l.lower()
    ):
        if not disposition.get("anti_c") or not demoted:
            return None
        tracks = saturated_track_ids_from_finding(finding) or []
        if demoted not in tracks:
            return None
        open_tracks = [track for track in tracks if track != demoted]
        if not open_tracks:
            return None
        return {
            "timing": "now",
            "open_tracks": open_tracks,
            "done_tracks": [demoted],
            "clauses": _saturation_clauses(finding),
        }
    trail = SCOREBOARD_TRAIL_FINDING_TITLE
    if title_l == trail or trail.lower() in title_l.lower():
        if not disposition.get("continuity_primary_demoted"):
            return None
        return {
            "timing": "later",
            "open_tracks": [],
            "done_tracks": [demoted or B3_DEMOTED_TRACK],
            "clauses": {},
        }
    return None


LATER_CROWN_ID = "later:b3-crown-after-volume-gates"


def later_crown_gap_card() -> dict[str, Any]:
    """One later chip: the unfinished B3 half. Not a Push card."""
    return {
        "id": LATER_CROWN_ID,
        "lane": "later",
        "timing": "later",
        "title": "Crown assessment primary only after shadow volume gates",
        "gap": (
            "Outstanding: N210 fair-cost episode % and the matched-30 pair stay "
            "shadow until their volume gates. Do not crown either from the continuity book."
        ),
        "done": (
            "B3 already demoted ai_judgment_fair as evidentiary primary and spawned "
            "those shadows. The total-return trail is not a new judgment."
        ),
        "not_push": True,
        "checklist_task_id": "sunday-assessment-scoreboard",
        "href": "docs/ops/b3-scoreboard-epoch.md",
    }


def push_finding_still_actionable(
    title: str,
    finding: dict[str, Any],
    *,
    eng: dict[str, Any] | None = None,
    disposition: dict[str, Any] | None = None,
) -> bool:
    """Drop Push/Status rows when the mapped finding is healed or eng gate is quiet.

    Prefer live eng status over stale ``ops_status.json`` rows so merged /
    cancelled parks (and orphaned pr_open after merge) do not linger as theater.
    B3 demotion / anti-C stamps likewise keep the observe warn but drop the
    Push card: the disposition is already locked.
    """
    if not isinstance(finding, dict):
        return False
    if finding.get("fixed") is True:
        return False
    title_l = str(title or finding.get("title") or "").strip()
    if title_l == PARKED_ENG_FINDING_TITLE or PARKED_ENG_FINDING_TITLE.lower() in title_l.lower():
        return parked_eng_still_actionable(eng)
    if (
        title_l.startswith(ORPHANED_PR_OPEN_FINDING_PREFIX)
        or ORPHANED_PR_OPEN_FINDING_PREFIX.lower() in title_l.lower()
    ):
        return orphaned_pr_open_still_actionable(eng)
    if b3_push_block_reason(title_l, finding, disposition):
        return False
    return True


def _non_actionable_observe(
    finding: dict[str, Any],
    *,
    reason: str,
) -> dict[str, str]:
    return {
        "title": str(finding.get("title") or ""),
        "severity": str(finding.get("severity") or ""),
        "reason": reason,
        "label": "non_actionable_not_push",
    }


def filter_actionable_market_warn_tasks(
    tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """D2: keep deepen/dismiss and non-ritual park; drop bare health_warn rows."""
    out: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        mw = task.get("market_warning") if isinstance(task.get("market_warning"), dict) else {}
        flag_id = str(mw.get("flag_id") or "")
        action = str(task.get("triage_action") or "")
        if flag_id in RITUAL_MARKET_WARN_FLAG_IDS and action == "park":
            continue
        out.append(task)
    return out


def build_daily_status_report(
    data_dir: Path | None = None,
    *,
    local_date: str = "",
    focus_relevant: bool | None = None,
) -> dict[str, Any]:
    """Compact grounded status strip from committed artifacts (no LLM)."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    ops = _safe_read(data_dir / "ops_status.json") or {}
    scoreboard = _safe_read(data_dir / "assessment_scoreboard.json") or {}
    eng = _safe_read(data_dir / "engineering_tasks.json") or {}
    automation = _safe_read(data_dir / "automation.json") or {}
    clearance = _safe_read(data_dir / "post_run_clearance.json") or {}
    defer = _safe_read(data_dir / "deferred_trigger_check.json") or {}
    relevance = _safe_read(data_dir / "daily_hub_relevance.json") or {}
    focus = _safe_read(data_dir / "daily_focus.json") or {}
    digest = _safe_read(data_dir / POST_SELL_CUE_DIGEST_FILENAME)
    disposition = load_b3_push_disposition(data_dir)

    findings = [f for f in (ops.get("findings") or []) if isinstance(f, dict)]
    warn_fail = [f for f in findings if str(f.get("severity") or "") in {"warn", "fail", "info"}]
    # Prefer warn/fail first in the strip; keep a few info that are action-mapped.
    warn_fail_sorted = sorted(
        warn_fail,
        key=lambda r: {"fail": 0, "warn": 1, "info": 2}.get(str(r.get("severity")), 9),
    )

    eng_open = [
        {
            "id": t.get("id"),
            "status": t.get("status"),
            "title": t.get("title"),
        }
        for t in _eng_tasks(eng)
        if str(t.get("status") or "") in ENG_STATUS_OPEN_STATUSES and not eng_row_is_done(t)
    ]
    # Status strip: drop healed eng rows and B3-disposed observes (labeled, not deleted).
    actionable_findings: list[dict[str, Any]] = []
    non_actionable_observes: list[dict[str, str]] = []
    for row in warn_fail_sorted:
        reason = b3_push_block_reason(str(row.get("title") or ""), row, disposition)
        if reason:
            non_actionable_observes.append(_non_actionable_observe(row, reason=reason))
            continue
        if push_finding_still_actionable(str(row.get("title") or ""), row, eng=eng):
            actionable_findings.append(row)
    warn_fail_sorted = [
        {
            "severity": row.get("severity"),
            "title": row.get("title"),
            "auto_fixable": row.get("auto_fixable"),
            "category": row.get("category"),
        }
        for row in actionable_findings
    ]
    queue_health = (
        automation.get("queue_health") if isinstance(automation.get("queue_health"), dict) else {}
    )
    last_run = clearance.get("last_run") if isinstance(clearance.get("last_run"), dict) else {}
    met = defer.get("met") if isinstance(defer.get("met"), list) else []
    unmet = defer.get("unmet") if isinstance(defer.get("unmet"), list) else []

    eval_rel = relevance.get("evaluation") if isinstance(relevance.get("evaluation"), dict) else {}
    if focus_relevant is None:
        focus_relevant = bool(eval_rel.get("relevant")) if eval_rel else None

    digest_row = post_sell_digest_status_row(digest)

    rows = _status_rows(
        ops_overall=ops.get("overall"),
        findings=warn_fail_sorted,
        scoreboard_headline=str(scoreboard.get("headline") or ""),
        eng_open=eng_open,
        queue_headline=str(queue_health.get("headline") or ""),
        last_run=last_run,
        met_count=len(met),
        focus_relevant=focus_relevant,
        digest_row=digest_row,
    )
    if non_actionable_observes:
        rows.append(
            {
                "id": "non_actionable_observes",
                "label": "Observe (not Push)",
                "value": "; ".join(
                    f"{item['title']} ({item['reason']})" for item in non_actionable_observes
                ),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "local_date": local_date or str(focus.get("local_date") or ""),
        "ops_overall": ops.get("overall"),
        "ops_findings": warn_fail_sorted[:12],
        "scoreboard_headline": scoreboard.get("headline") or "",
        "primary_track": scoreboard.get("primary_track"),
        "control_track": scoreboard.get("control_track"),
        "primary_vs_control": scoreboard.get("primary_vs_control")
        if isinstance(scoreboard.get("primary_vs_control"), dict)
        else {},
        "engineering_open": eng_open[:8],
        "queue_health_headline": queue_health.get("headline") or "",
        "post_run_clearance": {
            "evaluated_at": last_run.get("evaluated_at"),
            "trigger": last_run.get("trigger"),
            "applied": last_run.get("applied"),
            "should_dispatch_engineering": last_run.get("should_dispatch_engineering"),
        },
        "deferred_triggers": {
            "met_count": len(met),
            "unmet_count": len(unmet),
            "met": met[:8],
            "generated_at": defer.get("generated_at"),
        },
        "focus_relevant": focus_relevant,
        "post_sell_cue_digest": digest_row,
        "rows": rows,
        "non_actionable_observes": non_actionable_observes,
    }


def _status_rows(
    *,
    ops_overall: Any,
    findings: list[dict[str, Any]],
    scoreboard_headline: str,
    eng_open: list[dict[str, Any]],
    queue_headline: str,
    last_run: dict[str, Any],
    met_count: int,
    focus_relevant: bool | None,
    digest_row: dict[str, Any] | None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    rows.append(
        {
            "id": "ops",
            "label": "Ops",
            "value": f"overall={ops_overall or 'unknown'}; "
            + (
                "; ".join(
                    f"{f.get('severity')}:{f.get('title')}" for f in findings[:5] if f.get("title")
                )
                or "no findings"
            ),
        }
    )
    if scoreboard_headline:
        rows.append({"id": "scoreboard", "label": "Scoreboard", "value": scoreboard_headline})
    if eng_open or queue_headline:
        eng_bits = ", ".join(
            f"{t.get('status')}:{t.get('id')}" for t in eng_open[:3] if t.get("id")
        )
        rows.append(
            {
                "id": "eng",
                "label": "Eng queue",
                "value": eng_bits or queue_headline or "quiet",
            }
        )
    if last_run:
        rows.append(
            {
                "id": "post_run",
                "label": "Post-run clearance",
                "value": (
                    f"{last_run.get('evaluated_at') or '?'} "
                    f"trigger={last_run.get('trigger') or '?'} "
                    f"applied={last_run.get('applied')}"
                ),
            }
        )
    rows.append(
        {
            "id": "defer",
            "label": "Deferred triggers",
            "value": f"met={met_count}",
        }
    )
    if focus_relevant is not None:
        rows.append(
            {
                "id": "focus_relevance",
                "label": "Focus relevance",
                "value": "relevant" if focus_relevant else "stale vs P1/P2",
            }
        )
    if digest_row and digest_row.get("present"):
        rows.append(
            {
                "id": "post_sell_cue_digest",
                "label": "Post-sell cue digest",
                "value": str(
                    digest_row.get("headline") or f"present (items={digest_row.get('item_count')})"
                ),
            }
        )
    return rows


def build_daily_push_suggestions(
    data_dir: Path | None = None,
    *,
    closed_ids: set[str] | None = None,
    cap: int = PUSH_CAP,
) -> dict[str, Any]:
    """Fail-closed Push lane: ≤3 suggestions citing committed facts (D3)."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    closed_ids = closed_ids or set()
    ops = _safe_read(data_dir / "ops_status.json") or {}
    eng = _safe_read(data_dir / "engineering_tasks.json") or {}
    defer = _safe_read(data_dir / "deferred_trigger_check.json") or {}
    digest = _safe_read(data_dir / POST_SELL_CUE_DIGEST_FILENAME)
    disposition = load_b3_push_disposition(data_dir)

    findings = [f for f in (ops.get("findings") or []) if isinstance(f, dict)]
    by_title = {str(f.get("title") or ""): f for f in findings}
    suggestions: list[dict[str, Any]] = []
    later_suggestions: list[dict[str, Any]] = []
    non_actionable_observes: list[dict[str, str]] = []

    # Priority 0: Package M hub_feed.push_candidates only (fail closed if absent/empty).
    hub = digest_hub_feed(digest)
    if hub:
        suggestions.extend(
            _push_cards_from_hub_feed(
                hub,
                closed_ids=closed_ids,
                generated_at=str((digest or {}).get("generated_at") or ""),
            )
        )

    for title, checklist_id, push_title, href in _PUSH_FINDING_MAP:
        finding = by_title.get(title)
        if not finding:
            # Allow prefix / contains for deferred-trigger family titles.
            finding = next(
                (f for f in findings if title.lower() in str(f.get("title") or "").lower()),
                None,
            )
        if not finding:
            continue
        sev = str(finding.get("severity") or "")
        if sev not in {"warn", "fail", "info"}:
            continue
        block_reason = b3_push_block_reason(title, finding, disposition)
        partial = b3_partial_gap(title, finding, disposition)
        if block_reason:
            non_actionable_observes.append(_non_actionable_observe(finding, reason=block_reason))
            if partial and partial.get("timing") == "later":
                later_suggestions.append(later_crown_gap_card())
            continue
        if not push_finding_still_actionable(title, finding, eng=eng, disposition=disposition):
            continue
        pid = f"push:{_stable_id(title, checklist_id)}"
        if pid in closed_ids:
            continue
        if partial and partial.get("timing") == "now":
            open_tracks = list(partial.get("open_tracks") or [])
            clauses = partial.get("clauses") if isinstance(partial.get("clauses"), dict) else {}
            outstanding = "; ".join(
                f"{track}: {clauses.get(track) or 'saturated'}" for track in open_tracks
            )
            done_tracks = ", ".join(str(track) for track in (partial.get("done_tracks") or []))
            suggestions.append(
                {
                    "id": f"{pid}:gap",
                    "lane": "push",
                    "timing": "now",
                    "priority": 1 if sev in {"warn", "fail"} else 2,
                    "title": "Judge saturated knobs still open on " + ", ".join(open_tracks),
                    "why_now": (
                        f"Outstanding ({sev}): {outstanding}. "
                        f"Completed half omitted: {done_tracks} already locked (anti-C, no enlarge)."
                    ),
                    "gap_tracks": open_tracks,
                    "done_tracks": list(partial.get("done_tracks") or []),
                    "cite": {
                        "kind": "ops_finding",
                        "ref": finding.get("title"),
                        "severity": sev,
                        "category": finding.get("category"),
                        "gap_tracks": open_tracks,
                    },
                    "checklist_task_id": checklist_id,
                    "href": "#automation/human",
                    "doc_path": href,
                    "leverage": "Human judgment on the outstanding book only — not a new strand",
                }
            )
            continue
        suggestions.append(
            {
                "id": pid,
                "lane": "push",
                "priority": 1 if sev in {"warn", "fail"} else 2,
                "title": push_title,
                "why_now": f"ops finding ({sev}): {finding.get('title')}",
                "cite": {
                    "kind": "ops_finding",
                    "ref": finding.get("title"),
                    "severity": sev,
                    "category": finding.get("category"),
                },
                "checklist_task_id": checklist_id,
                "href": "#automation/human",
                "doc_path": href,
                "leverage": "Human judgment on existing gate — not a new strand",
            }
        )

    # Eng queue head when open/parked after self-heal context (status strip already notes).
    # Terminal statuses (merged/cancelled/completed/failed) never enter Push.
    for t in _eng_tasks(eng):
        status = str(t.get("status") or "")
        if eng_row_is_done(t) or status not in ENG_PUSH_STATUSES:
            continue
        tid = str(t.get("id") or "")
        if not tid:
            continue
        pid = f"push:eng:{tid}"
        if pid in closed_ids:
            continue
        suggestions.append(
            {
                "id": pid,
                "lane": "push",
                "priority": 3,
                "title": f"Confirm eng {status} still P1-aligned: {tid}",
                "why_now": str(t.get("title") or tid),
                "cite": {"kind": "engineering_task", "ref": tid, "status": status},
                "checklist_task_id": "weekday-engineering-parked-backlog-clear"
                if status == "parked"
                else "",
                "href": "#automation/queue",
                "leverage": "Clash-aware eng head — cancel/merge/unpark; no spray",
            }
        )
        break  # only head

    met = defer.get("met") if isinstance(defer.get("met"), list) else []
    if met:
        pid = "push:defer-triggers-met"
        if pid not in closed_ids:
            suggestions.append(
                {
                    "id": pid,
                    "lane": "push",
                    "priority": 2,
                    "title": "Act on met deferred triggers",
                    "why_now": f"deferred_trigger_check met={len(met)}",
                    "cite": {
                        "kind": "artifact",
                        "ref": "deferred_trigger_check.json",
                        "field": "met",
                    },
                    "checklist_task_id": "sunday-deferred-triggers",
                    "href": "#automation/human",
                    "leverage": "Pick up / retarget / close named ideas",
                }
            )

    suggestions.sort(key=lambda s: (int(s.get("priority") or 9), str(s.get("id"))))
    # Deduplicate by checklist_task_id when set (keep first).
    seen_checklist: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for s in suggestions:
        cid = str(s.get("checklist_task_id") or "")
        if cid and cid in seen_checklist:
            continue
        if cid:
            seen_checklist.add(cid)
        deduped.append(s)
    capped = deduped[: max(0, int(cap))]
    mapped = _mapped_warns_open(findings, eng=eng, disposition=disposition)
    return {
        "schema_version": SCHEMA_VERSION,
        "lane": "push",
        "cap": cap,
        "fail_closed": True,
        "empty_ok": True,
        "empty_message": "No forced push — factory green; optional Sunday prep"
        if not capped
        else "",
        "suggestions": capped,
        "mapped_warns_open": mapped,
        "push_empty_while_mapped_warns": bool(not capped and mapped),
        "non_actionable_observes": non_actionable_observes,
        "later_suggestions": later_suggestions,
    }


def _mapped_warns_open(
    findings: list[dict[str, Any]],
    *,
    eng: dict[str, Any] | None = None,
    disposition: dict[str, Any] | None = None,
) -> list[str]:
    titles = []
    for title, *_rest in _PUSH_FINDING_MAP:
        for f in findings:
            ft = str(f.get("title") or "")
            if ft == title or title.lower() in ft.lower():
                if str(f.get("severity") or "") in {"warn", "fail"}:
                    if push_finding_still_actionable(title, f, eng=eng, disposition=disposition):
                        titles.append(ft)
                break
    return titles


def build_daily_explore_suggestions(
    data_dir: Path | None = None,
    *,
    seed_path: Path | None = None,
    closed_ids: set[str] | None = None,
    cap: int = EXPLORE_CAP,
) -> dict[str, Any]:
    """D7 A: daily ≤2 Explore cards — labeled not-today; quality bar required.

    Preference: seed ``explore_lines`` (editorial) → Package M
    ``hub_feed.explore_candidates`` → non-post-sell editorial defaults.
    Never invent post-sell twin stubs when ``hub_feed`` is missing.
    """
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    closed_ids = closed_ids or set()
    seed = _safe_read(Path(seed_path or data_dir / "project_daily_seed.json")) or {}
    raw = seed.get("explore_lines") if isinstance(seed.get("explore_lines"), list) else []
    cards: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        card = _normalize_explore_card(row)
        if card is None:
            continue
        if card["id"] in closed_ids:
            continue
        cards.append(card)
        if len(cards) >= cap:
            break
    hub_feed_used = False
    if len(cards) < cap:
        digest = _safe_read(data_dir / POST_SELL_CUE_DIGEST_FILENAME)
        hub = digest_hub_feed(digest)
        if hub:
            hub_feed_used = True
            for card in _explore_cards_from_hub_feed(
                hub, closed_ids=closed_ids, cap=cap - len(cards)
            ):
                if any(existing["id"] == card["id"] for existing in cards):
                    continue
                cards.append(card)
                if len(cards) >= cap:
                    break
    # Non-post-sell editorial defaults only when seed + hub_feed both empty.
    if not cards:
        for row in _default_explore_cards():
            card = _normalize_explore_card(row)
            if card is None or card["id"] in closed_ids:
                continue
            cards.append(card)
            if len(cards) >= cap:
                break
    return {
        "schema_version": SCHEMA_VERSION,
        "lane": "explore",
        "cap": cap,
        "label": "not-today",
        "may_sit_outside_north_star": True,
        "must_not_displace_push": True,
        "quality_bar": ["claim", "why_matters", "falsify_or_promote"],
        "hub_feed_used": hub_feed_used,
        "suggestions": cards[:cap],
    }


def _normalize_explore_card(row: dict[str, Any]) -> dict[str, Any] | None:
    claim = str(row.get("claim") or row.get("title") or "").strip()
    why = str(row.get("why_matters") or row.get("why") or row.get("summary") or "").strip()
    falsify = str(
        row.get("falsify_or_promote") or row.get("falsify") or row.get("evidence_gate") or ""
    ).strip()
    if not (claim and why and falsify):
        return None
    eid = str(row.get("id") or "").strip() or f"explore:{_stable_id(claim)}"
    return {
        "id": eid if eid.startswith("explore:") else f"explore:{eid}",
        "lane": "explore",
        "label": "not-today",
        "claim": claim,
        "why_matters": why,
        "falsify_or_promote": falsify,
        "title": claim,
        "summary": why,
        "defer_hint": "ftse-defer add|fragment — durable park, not eng dispatch",
        "href": "#automation/daily",
    }


def _default_explore_cards() -> list[dict[str, Any]]:
    """Seed/hub_feed-independent Explore defaults (≤2).

    Post-sell cues come from Package M ``hub_feed.explore_candidates`` (L620) —
    do not hardcode a twin stub here (anachronistic still_in_buy_set copy).
    """
    return [
        {
            "id": "explore:memo-change-my-mind-cites",
            "claim": "LLM extract of “what would change my mind” from memo → cite card",
            "why_matters": ("Feeds agree/veto shadow cites (AI path Phase 2) without rememo spray"),
            "falsify_or_promote": (
                "Cite precision vs heuristic; cost/latency; no live influence until N173 path"
            ),
        },
    ]


def check_daily_push_empty_while_mapped_warns(
    data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Ops finding (observe-only) when Push is empty but mapped warns are open."""
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    push = build_daily_push_suggestions(data_dir=data_dir)
    if not push.get("push_empty_while_mapped_warns"):
        return []
    mapped = push.get("mapped_warns_open") or []
    return [
        {
            "severity": "warn",
            "title": "Daily push suggestions empty while mapped warns open",
            "category": "dashboard_health",
            "auto_fixable": False,
            "detail": (
                "Push ranker returned no cards but ops still has mapped human warns: "
                + ", ".join(str(t) for t in mapped)
                + ". Check ranker mapping / closed_ids — do not eng-spray from this finding."
            ),
            "runbook": "docs/ops/ops-monitor.md#daily-hub-attention",
        }
    ]


def _sha_values(row: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key in ("merge_sha", "head_sha", "merge_commit_sha"):
        value = str(row.get(key) or "").strip()
        if value:
            found.append(value)
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    for key in ("merge_sha", "head_sha", "merge_commit_sha"):
        value = str(evidence.get(key) or "").strip()
        if value:
            found.append(value)
    return found


def load_completion_index(data_dir: Path | None = None) -> dict[str, Any]:
    """Live eng terminals, merged PR numbers, and merged fix SHAs.

    Surfaces that list work consult this instead of stale finding prose alone.
    """
    root = Path(data_dir or DEFAULT_DATA_DIR)
    eng = _safe_read(root / "engineering_tasks.json") or {}
    disposition = load_b3_push_disposition(root)
    terminal_ids: set[str] = set()
    known_ids: set[str] = set()
    merged_prs: set[int] = set()
    merged_shas: set[str] = set()
    for row in _eng_tasks(eng):
        tid = str(row.get("id") or "").strip()
        if tid:
            known_ids.add(tid)
        if not eng_row_is_done(row):
            continue
        if tid:
            terminal_ids.add(tid)
        raw_pr = row.get("pr_number")
        try:
            if raw_pr is not None and str(raw_pr).strip():
                merged_prs.add(int(raw_pr))
        except (TypeError, ValueError):
            pass
        merged_shas.update(_sha_values(row))
    occasions = _safe_read(root / "pr_fix_occasions.json") or {}
    for row in occasions.get("occasions") or []:
        if not isinstance(row, dict):
            continue
        try:
            number = int(row.get("pr_number")) if row.get("pr_number") is not None else None
        except (TypeError, ValueError):
            number = None
        sha = str(row.get("head_sha") or "").strip()
        if number is not None and number in merged_prs and sha:
            merged_shas.add(sha)
    return {
        "terminal_eng_ids": terminal_ids,
        "known_eng_ids": known_ids,
        "merged_pr_numbers": merged_prs,
        "merged_shas": merged_shas,
        "disposition": disposition,
    }


def _structured_completion_refs(task: dict[str, Any]) -> dict[str, set[Any]]:
    eng_ids: set[str] = set()
    pr_numbers: set[int] = set()
    shas: set[str] = set()
    explicit_eng: set[str] = set()
    task_ref = str(task.get("task_ref") or "")
    if task_ref.startswith("push:eng:"):
        explicit_eng.add(task_ref.split("push:eng:", 1)[1])
    cite = task.get("cite") if isinstance(task.get("cite"), dict) else {}
    push = task.get("push") if isinstance(task.get("push"), dict) else {}
    push_cite = push.get("cite") if isinstance(push.get("cite"), dict) else {}
    for blob in (cite, push_cite):
        if str(blob.get("kind") or "") == "engineering_task":
            ref = str(blob.get("ref") or "").strip()
            if ref:
                explicit_eng.add(ref)
        raw_pr = blob.get("pr_number")
        try:
            if raw_pr is not None and str(raw_pr).strip():
                pr_numbers.add(int(raw_pr))
        except (TypeError, ValueError):
            pass
        sha = str(blob.get("sha") or blob.get("merge_sha") or "").strip()
        if sha:
            shas.add(sha)
    for key in ("eng_id", "pr_number", "merge_sha"):
        if key == "eng_id" and task.get(key):
            explicit_eng.add(str(task.get(key)).strip())
        if key == "pr_number" and task.get(key) is not None:
            try:
                pr_numbers.add(int(task.get(key)))
            except (TypeError, ValueError):
                pass
        if key == "merge_sha" and task.get(key):
            shas.add(str(task.get(key)).strip())
    eng_ids.update(explicit_eng)
    return {
        "eng_ids": eng_ids,
        "explicit_eng_ids": explicit_eng,
        "pr_numbers": pr_numbers,
        "shas": shas,
    }


def hub_task_drop_reason(
    task: dict[str, Any],
    index: dict[str, Any],
    *,
    disposed_checklist_ids: set[str] | None = None,
) -> str | None:
    """Drop a hub row whose cited work is already merged, locked, or absent."""
    if not isinstance(task, dict) or task.get("closed"):
        return None
    disposed = disposed_checklist_ids or set()
    human = task.get("human_task") if isinstance(task.get("human_task"), dict) else {}
    human_id = str(human.get("id") or "")
    if not human_id and str(task.get("source") or "") == "human_tasks":
        ref = str(task.get("task_ref") or "")
        if ref.startswith("human:"):
            human_id = ref.split("human:", 1)[1]
    if human_id and human_id in disposed:
        return "disposition_locked"
    refs = _structured_completion_refs(task)
    terminal = index.get("terminal_eng_ids") or set()
    known = index.get("known_eng_ids") or set()
    for eng_id in refs["explicit_eng_ids"]:
        if eng_id in terminal:
            return "eng_terminal"
        if known and eng_id not in known:
            return "eng_absent"
    merged_prs = index.get("merged_pr_numbers") or set()
    for number in refs["pr_numbers"]:
        if number in merged_prs:
            return "merged_pr"
    merged_shas = index.get("merged_shas") or set()
    for sha in refs["shas"]:
        if sha in merged_shas:
            return "merged_sha"
    return None


def apply_hub_task_relevance(
    tasks: list[dict[str, Any]],
    *,
    data_dir: Path | None = None,
    disposed_checklist_ids: set[str] | None = None,
    index: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Fully done hub rows leave the actionable list. Partials are rewritten upstream."""
    completion = index if index is not None else load_completion_index(data_dir)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        reason = hub_task_drop_reason(
            task,
            completion,
            disposed_checklist_ids=disposed_checklist_ids,
        )
        if reason:
            dropped.append(
                {
                    "task_ref": str(task.get("task_ref") or ""),
                    "title": str(task.get("title") or ""),
                    "reason": reason,
                }
            )
            continue
        kept.append(task)
    return kept, dropped


__all__ = [
    "ENG_PUSH_STATUSES",
    "ENG_STATUS_OPEN_STATUSES",
    "ENG_TERMINAL_STATUSES",
    "EXPLORE_CAP",
    "ORPHANED_PR_OPEN_FINDING_PREFIX",
    "B3_DEMOTION_POLICY_ID",
    "B3_DEMOTED_TRACK",
    "PARKED_ENG_FINDING_TITLE",
    "POST_SELL_CUE_DIGEST_FILENAME",
    "SATURATED_KNOBS_FINDING_TITLE",
    "SCOREBOARD_TRAIL_FINDING_TITLE",
    "PUSH_CAP",
    "RITUAL_MARKET_WARN_FLAG_IDS",
    "LATER_CROWN_ID",
    "apply_hub_task_relevance",
    "b3_partial_gap",
    "build_daily_explore_suggestions",
    "build_daily_push_suggestions",
    "build_daily_status_report",
    "digest_hub_feed",
    "eng_row_is_done",
    "hub_task_drop_reason",
    "later_crown_gap_card",
    "load_completion_index",
    "check_daily_push_empty_while_mapped_warns",
    "eng_task_is_terminal",
    "filter_actionable_market_warn_tasks",
    "orphaned_pr_open_still_actionable",
    "parked_eng_still_actionable",
    "post_sell_digest_status_row",
    "push_finding_still_actionable",
]
