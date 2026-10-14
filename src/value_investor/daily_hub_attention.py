"""Daily hub attention: status report, Push ranker, Explore lane (locked D1–D7).

Deterministic extractors — no LLM. Push fails closed when nothing high-signal;
Explore is labeled not-today with a quality bar. Optional Push source
``post_sell_cue_digest.json`` is consumed when present (sibling package M);
this module does not generate that digest.
"""

from __future__ import annotations

import hashlib
import json
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
        "N200 volume gate ready for review",
        "adhoc-n200-n201-volume-gate-review",
        "Review N200 volume gate (no auto-promote)",
        "docs/ops/n200-tech-timing-observe.md#human-volume-gate-review",
    ),
    (
        "N201 volume gate ready for review",
        "adhoc-n200-n201-volume-gate-review",
        "Review N201 volume gate (no auto-promote)",
        "docs/ops/n201-value-mom-observe.md#human-volume-gate-review",
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

# Ritual market-warn flag ids excluded from hub (D2) — stay ops-email / status.
RITUAL_MARKET_WARN_FLAG_IDS = frozenset({"health_warn", "health_warn_rollup"})

# Sibling package M may publish this; Push consumes when present.
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

    findings = [f for f in (ops.get("findings") or []) if isinstance(f, dict)]
    warn_fail = [
        {
            "severity": f.get("severity"),
            "title": f.get("title"),
            "auto_fixable": f.get("auto_fixable"),
            "category": f.get("category"),
        }
        for f in findings
        if str(f.get("severity") or "") in {"warn", "fail", "info"}
    ]
    # Prefer warn/fail first in the strip; keep a few info that are action-mapped.
    warn_fail_sorted = sorted(
        warn_fail,
        key=lambda r: {"fail": 0, "warn": 1, "info": 2}.get(str(r.get("severity")), 9),
    )

    tasks = eng.get("tasks") if isinstance(eng.get("tasks"), list) else []
    eng_open = [
        {
            "id": t.get("id"),
            "status": t.get("status"),
            "title": t.get("title"),
        }
        for t in tasks
        if isinstance(t, dict) and t.get("status") in {"open", "parked", "pr_open", "in_progress"}
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

    digest_row: dict[str, Any] | None = None
    if digest:
        digest_row = {
            "present": True,
            "generated_at": digest.get("generated_at") or digest.get("updated_at"),
            "item_count": (
                len(digest.get("items") or [])
                if isinstance(digest.get("items"), list)
                else digest.get("count")
            ),
            "headline": digest.get("headline") or digest.get("summary") or "",
        }

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
        "rows": _status_rows(
            ops_overall=ops.get("overall"),
            findings=warn_fail_sorted,
            scoreboard_headline=str(scoreboard.get("headline") or ""),
            eng_open=eng_open,
            queue_headline=str(queue_health.get("headline") or ""),
            last_run=last_run,
            met_count=len(met),
            focus_relevant=focus_relevant,
            digest_row=digest_row,
        ),
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
                    digest_row.get("headline")
                    or f"present (items={digest_row.get('item_count')})"
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

    findings = [f for f in (ops.get("findings") or []) if isinstance(f, dict)]
    by_title = {str(f.get("title") or ""): f for f in findings}
    suggestions: list[dict[str, Any]] = []

    # Priority 0 (when present): sibling post-sell cue digest — do not invent it.
    if digest:
        dig_id = f"push:post_sell_cue_digest:{_stable_id(str(digest.get('generated_at') or 'v0'))}"
        if dig_id not in closed_ids and f"push:{dig_id}" not in closed_ids:
            items = digest.get("items") if isinstance(digest.get("items"), list) else []
            headline = str(digest.get("headline") or digest.get("summary") or "").strip()
            if headline or items:
                suggestions.append(
                    {
                        "id": dig_id,
                        "lane": "push",
                        "priority": 0,
                        "title": "Review post-sell cue digest",
                        "why_now": headline
                        or f"Committed {POST_SELL_CUE_DIGEST_FILENAME} has {len(items)} item(s)",
                        "cite": {
                            "kind": "artifact",
                            "ref": POST_SELL_CUE_DIGEST_FILENAME,
                            "field": "headline" if headline else "items",
                        },
                        "checklist_task_id": "",
                        "href": "#automation/daily",
                        "leverage": "Consume sibling package-M digest — do not invent cues here",
                    }
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
        pid = f"push:{_stable_id(title, checklist_id)}"
        if pid in closed_ids:
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
                "href": f"#automation/human",
                "doc_path": href,
                "leverage": "Human judgment on existing gate — not a new strand",
            }
        )

    # Eng queue head when open/parked after self-heal context (status strip already notes).
    tasks = eng.get("tasks") if isinstance(eng.get("tasks"), list) else []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("status") not in {"open", "parked"}:
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
                "title": f"Confirm eng {t.get('status')} still P1-aligned: {tid}",
                "why_now": str(t.get("title") or tid),
                "cite": {"kind": "engineering_task", "ref": tid, "status": t.get("status")},
                "checklist_task_id": "weekday-engineering-parked-backlog-clear"
                if t.get("status") == "parked"
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
        "mapped_warns_open": _mapped_warns_open(findings),
        "push_empty_while_mapped_warns": bool(not capped and _mapped_warns_open(findings)),
    }


def _mapped_warns_open(findings: list[dict[str, Any]]) -> list[str]:
    titles = []
    for title, *_rest in _PUSH_FINDING_MAP:
        for f in findings:
            ft = str(f.get("title") or "")
            if ft == title or title.lower() in ft.lower():
                if str(f.get("severity") or "") in {"warn", "fail"}:
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
    """D7 A: daily ≤2 Explore cards — labeled not-today; quality bar required."""
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
    # Editorial defaults when seed empty — still quality-barred, not spray.
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
    """Seed-independent Explore defaults (≤2). Spec-challenging OK when labeled."""
    return [
        {
            "id": "explore:post-sell-cue-twin",
            "claim": "Post-sell cue twin: track still_in_buy_set + filing delta after exit",
            "why_matters": (
                "Separates timing vs thesis-break without a second live path; "
                "sibling package M may publish post_sell_cue_digest for Push"
            ),
            "falsify_or_promote": (
                "Thick closed exits; promote only if alone scoreboard beats "
                "hold-buffer twin readiness gate"
            ),
        },
        {
            "id": "explore:memo-change-my-mind-cites",
            "claim": "LLM extract of “what would change my mind” from memo → cite card",
            "why_matters": (
                "Feeds agree/veto shadow cites (AI path Phase 2) without rememo spray"
            ),
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


__all__ = [
    "EXPLORE_CAP",
    "POST_SELL_CUE_DIGEST_FILENAME",
    "PUSH_CAP",
    "RITUAL_MARKET_WARN_FLAG_IDS",
    "build_daily_explore_suggestions",
    "build_daily_push_suggestions",
    "build_daily_status_report",
    "check_daily_push_empty_while_mapped_warns",
    "filter_actionable_market_warn_tasks",
]
