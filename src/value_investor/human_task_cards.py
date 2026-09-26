"""Human-task board: enrich checklist rows with existing analysis + ack sort.

Does not invent a second data plane — snippets come from committed ops artifacts
already produced by analysis-review / project-traffic / eng queue / etc.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.human_task_acks import annotate_task_ack, load_human_task_acks
from value_investor.human_tasks_checklist import doc_url_for_task, load_human_tasks_checklist
from value_investor.storage import read_json, write_json

BOARD_FILENAME = "human_tasks_board.json"
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_CHECKLIST_PATH = Path("docs/human_tasks_checklist.json")

# Task ids that are capital / promotion gates — show Approve (observe record only).
APPROVAL_GATE_IDS: dict[str, str] = {
    "sunday-phase-c-readiness-gate": "Approve Phase C start",
    "sunday-promote-knobs-gate": "Approve knob promote",
    "sunday-fair-cost-promotion-gate": "Approve fair-cost view",
    "sunday-spawn-fair-twins": "Approve spawn fair twins",
    "sunday-exclusion-shadow-spawn": "Approve spawn shadow",
    "monthly-euro-depth-parity": "Approve Phase 3 / AI gate",
    "monthly-cycle-budget-surplus": "Approve surplus bump",
    "adhoc-live-capital-pack": "Approve live capital",
}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _read(data_dir: Path, name: str) -> dict[str, Any]:
    try:
        raw = read_json(Path(data_dir) / name)
    except FileNotFoundError:
        return {}
    return _as_dict(raw)


def _fingerprint(parts: dict[str, Any]) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _bullet(text: str) -> str:
    return str(text or "").strip()


def _analysis_for_task(task_id: str, data_dir: Path) -> dict[str, Any]:
    """Slim analysis view from existing artifacts. Empty when nothing published."""
    tid = str(task_id or "").strip()

    if tid == "weekday-engineering-parked-backlog-clear":
        eng = _read(data_dir, "engineering_tasks.json")
        tasks = [t for t in (eng.get("tasks") or []) if isinstance(t, dict)]
        parked = [t for t in tasks if str(t.get("status") or "") == "parked"]
        attention = [
            t
            for t in parked
            if str(t.get("park_kind") or t.get("attention") or "attention") != "ignore"
        ]
        traffic = _as_dict(eng.get("traffic_control"))
        bullets = [
            _bullet(f"Parked tasks: {len(parked)} (attention ~{len(attention)})"),
            _bullet(
                f"Traffic pause active: {bool(traffic.get('pause_active'))}"
                + (f" — {traffic.get('reason')}" if traffic.get("reason") else "")
            ),
        ]
        oldest = sorted(
            attention,
            key=lambda row: str(row.get("parked_at") or row.get("updated_at") or ""),
        )[:5]
        for row in oldest:
            bullets.append(
                _bullet(
                    f"{row.get('id') or '?'}: {row.get('title') or row.get('park_reason') or 'parked'}"
                )
            )
        fp = _fingerprint(
            {
                "n": len(parked),
                "ids": [str(t.get("id")) for t in oldest],
                "pause": traffic.get("pause_active"),
            }
        )
        return {
            "headline": f"{len(attention)} attention-parked eng tasks",
            "updated_at": eng.get("updated_at") or eng.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["engineering_tasks"],
        }

    if tid == "sunday-read-analysis-review":
        review = _read(data_dir, "analysis_review.json")
        chart = _read(data_dir, "chart_outcome_review.json")
        bullets = []
        if review.get("summary"):
            bullets.append(_bullet(str(review.get("summary"))[:280]) )
        mix = _as_dict(chart.get("mix") or chart.get("outcome_mix"))
        if mix:
            bullets.append(
                _bullet(
                    "Chart-outcome mix: "
                    + ", ".join(f"{k}={v}" for k, v in list(mix.items())[:6])
                )
            )
        fp = _fingerprint(
            {
                "review_at": review.get("generated_at") or review.get("updated_at"),
                "chart_at": chart.get("generated_at") or chart.get("updated_at"),
                "mix": mix,
            }
        )
        return {
            "headline": "Sunday analysis review synthesis",
            "updated_at": review.get("generated_at")
            or review.get("updated_at")
            or chart.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["analysis_review", "chart_outcome_review"],
        }

    if tid == "sunday-phase-c-readiness-gate":
        ready = _read(data_dir, "phase_c_readiness.json")
        status = str(ready.get("status") or ready.get("readiness") or "unknown")
        blockers = ready.get("blockers") or ready.get("missing") or []
        bullets = [_bullet(f"Status: {status}")]
        if isinstance(blockers, list):
            for item in blockers[:5]:
                bullets.append(_bullet(str(item)))
        elif blockers:
            bullets.append(_bullet(str(blockers)))
        fp = _fingerprint({"status": status, "blockers": blockers, "at": ready.get("generated_at")})
        return {
            "headline": f"Phase C readiness: {status}",
            "updated_at": ready.get("generated_at") or ready.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["phase_c_readiness"],
        }

    if tid in {"sunday-shard-epoch0-watch", "sunday-buy-cross-archive"}:
        if tid == "sunday-buy-cross-archive":
            payload = _read(data_dir, "buy_cross_archive_review.json")
            bullets = []
            if payload.get("summary"):
                bullets.append(_bullet(str(payload.get("summary"))[:280]))
            for key in ("cross_vs_level", "week_0_cash", "never_entered"):
                if payload.get(key) is not None:
                    bullets.append(_bullet(f"{key}: {payload.get(key)}"))
            fp = _fingerprint(
                {
                    "at": payload.get("generated_at") or payload.get("updated_at"),
                    "summary": payload.get("summary"),
                }
            )
            return {
                "headline": "Buy-cross archive review",
                "updated_at": payload.get("generated_at") or payload.get("updated_at"),
                "fingerprint": fp,
                "bullets": [b for b in bullets if b][:8],
                "source_keys": ["buy_cross_archive_review"],
            }
        # shard epoch-0 watch — market_status admitted books
        status = _read(data_dir, "market_status.json")
        markets = _as_dict(status.get("markets") or status.get("admitted") or {})
        bullets = []
        for mid, row in list(markets.items())[:8]:
            if not isinstance(row, dict):
                continue
            bullets.append(
                _bullet(
                    f"{mid}: epoch0={row.get('epoch0') or row.get('buy_tier_level') or '—'} "
                    f"marks={row.get('mark_count') or row.get('marks') or '—'}"
                )
            )
        fp = _fingerprint({"at": status.get("generated_at") or status.get("updated_at"), "n": len(markets)})
        return {
            "headline": "Admitted shard epoch-0 watch",
            "updated_at": status.get("generated_at") or status.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["market_status"],
        }

    if tid in {
        "sunday-knob-calibration-priors",
        "sunday-shadow-endurance",
        "sunday-shadow-vs-primary",
        "sunday-promote-knobs-gate",
        "sunday-spawn-fair-twins",
    }:
        assessment = _read(data_dir, "experiment_assessment.json")
        priors = _read(data_dir, "paper_automation/knob_calibration_priors.json")
        if not priors:
            priors = _read(data_dir, "knob_calibration_priors.json")
        experiments = [
            row
            for row in (assessment.get("experiments") or assessment.get("rows") or [])
            if isinstance(row, dict)
        ]
        recommend = [row for row in experiments if str(row.get("status") or "") == "recommend"]
        bullets = [
            _bullet(f"Recommend rows: {len(recommend)} / {len(experiments)} experiments"),
            _bullet(
                f"Priors ready_for_shadow_bootstrap="
                f"{priors.get('ready_for_shadow_bootstrap')} "
                f"ranking_mode={priors.get('ranking_mode')}"
            ),
        ]
        for row in recommend[:4]:
            bullets.append(
                _bullet(
                    f"{row.get('experiment_id')}: {row.get('status')} "
                    f"conf={(_as_dict(row.get('recommended_prior')).get('confidence') if isinstance(row.get('recommended_prior'), dict) else row.get('confidence'))}"
                )
            )
        fp = _fingerprint(
            {
                "assess_at": assessment.get("generated_at") or assessment.get("updated_at"),
                "priors_at": priors.get("generated_at") or priors.get("updated_at"),
                "recommend_ids": [str(r.get("experiment_id")) for r in recommend],
                "ready": priors.get("ready_for_shadow_bootstrap"),
            }
        )
        return {
            "headline": f"Experiment assessment · {len(recommend)} recommend",
            "updated_at": assessment.get("generated_at")
            or assessment.get("updated_at")
            or priors.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["experiment_assessment", "knob_calibration_priors"],
        }

    if tid in {"sunday-fair-cost-promotion-gate", "sunday-suite-b-fair-lab"}:
        assessment = _read(data_dir, "experiment_assessment.json")
        bullets = [_bullet("Require fair-cost view before treating 3% stress excess as deployable.")]
        fair = [
            row
            for row in (assessment.get("experiments") or [])
            if isinstance(row, dict)
            and "fair" in str(row.get("experiment_id") or "").lower()
        ]
        for row in fair[:5]:
            bullets.append(
                _bullet(f"{row.get('experiment_id')}: {row.get('status')} excess={row.get('excess_vs_ftse')}")
            )
        fp = _fingerprint(
            {
                "at": assessment.get("generated_at"),
                "fair_ids": [str(r.get("experiment_id")) for r in fair],
            }
        )
        return {
            "headline": "Fair-cost Suite B lab",
            "updated_at": assessment.get("generated_at") or assessment.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["experiment_assessment"],
        }

    if tid == "sunday-entry-dca-cadence":
        plan = _read(data_dir, "entry_dca_adoption_plan.json")
        stage = plan.get("adoption_stage") or plan.get("stage") or "—"
        ready = _as_dict(plan.get("readiness") or plan.get("gates"))
        bullets = [
            _bullet(f"Adoption stage: {stage}"),
            _bullet(f"paper_execute_graduated ready: {ready.get('paper_execute_graduated')}"),
            _bullet("Acknowledge is observe-only — use Lifecycle Start to execute."),
        ]
        fp = _fingerprint({"stage": stage, "ready": ready, "at": plan.get("updated_at")})
        return {
            "headline": f"Entry DCA adoption · {stage}",
            "updated_at": plan.get("updated_at") or plan.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["entry_dca_adoption_plan"],
        }

    if tid == "sunday-sleeve-episodes-readiness":
        # Prefer learning_tracks_review sidecar fields if present under data
        review = _read(data_dir, "paper_learning_review.json")
        sleeve = _as_dict(review.get("sleeve_episodes") or review.get("learning_tracks_sleeve_episodes"))
        ready = _as_dict(sleeve.get("readiness"))
        bullets = [
            _bullet(
                f"ready_for_sleeve_timing_analysis="
                f"{ready.get('ready_for_sleeve_timing_analysis')}"
            ),
            _bullet(f"closed cohorts: {sleeve.get('closed_counts') or sleeve.get('counts') or '—'}"),
        ]
        fp = _fingerprint({"ready": ready, "at": review.get("generated_at")})
        return {
            "headline": "Dual-path sleeve episodes readiness",
            "updated_at": review.get("generated_at") or review.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["paper_learning_review"],
        }

    if tid == "sunday-hypothesis-integrity":
        # Look for per-track hypothesis under paper automation is heavy; use review summary
        review = _read(data_dir, "paper_learning_review.json")
        hi = _as_dict(review.get("hypothesis_integrity") or review.get("learning_tracks_hypothesis_integrity"))
        bullets = [
            _bullet(f"within_tolerance={hi.get('within_tolerance')}"),
            _bullet(f"broken_loser_count={hi.get('broken_loser_count')}"),
            _bullet(f"flags={hi.get('selection_feedback_flags') or hi.get('flags') or '—'}"),
        ]
        fp = _fingerprint({"hi": hi, "at": review.get("generated_at")})
        return {
            "headline": "Hypothesis integrity",
            "updated_at": review.get("generated_at") or review.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["paper_learning_review"],
        }

    if tid in {"sunday-analysis-tasks", "sunday-triage-plr-director-tasks"}:
        path = "analysis_tasks.json" if tid == "sunday-analysis-tasks" else "paper_learning_tasks.json"
        payload = _read(data_dir, path)
        tasks = [t for t in (payload.get("tasks") or payload.get("items") or []) if isinstance(t, dict)]
        open_tasks = [
            t
            for t in tasks
            if str(t.get("status") or "open") in {"open", "proposed", "watch", "continue"}
        ]
        bullets = [_bullet(f"Open/proposed: {len(open_tasks)} / {len(tasks)}")]
        for row in open_tasks[:5]:
            bullets.append(
                _bullet(f"{row.get('id') or '?'}: {row.get('title') or row.get('status')}")
            )
        fp = _fingerprint(
            {
                "at": payload.get("updated_at") or payload.get("generated_at"),
                "ids": [str(t.get("id")) for t in open_tasks[:10]],
            }
        )
        return {
            "headline": f"Triage queue · {len(open_tasks)} open",
            "updated_at": payload.get("updated_at") or payload.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": [path.replace(".json", "")],
        }

    if tid == "monthly-horizon-scan":
        scan = _read(data_dir, "horizon_scan.json")
        bullets = [
            _bullet(f"Open fragments: {scan.get('open_fragment_count') or scan.get('open_count') or '—'}"),
            _bullet(f"Suggested promotes: {scan.get('promote_count') or '—'}"),
        ]
        if scan.get("summary"):
            bullets.append(_bullet(str(scan.get("summary"))[:280]))
        fp = _fingerprint({"at": scan.get("generated_at"), "open": scan.get("open_fragment_count")})
        return {
            "headline": "Horizon scan + deferred fragments",
            "updated_at": scan.get("generated_at") or scan.get("updated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["horizon_scan"],
        }

    if tid == "monthly-cycle-budget-surplus":
        surplus = _read(data_dir, "cycle_budget_surplus.json")
        bullets = [
            _bullet(f"Decision: {surplus.get('decision') or surplus.get('status') or '—'}"),
            _bullet(f"Unused Ultra fraction: {surplus.get('unused_ultra_fraction') or '—'}"),
        ]
        fp = _fingerprint({"at": surplus.get("updated_at"), "decision": surplus.get("decision")})
        return {
            "headline": "Cycle-end Cursor surplus",
            "updated_at": surplus.get("updated_at") or surplus.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["cycle_budget_surplus"],
        }

    if tid == "monthly-pr-fix-common-issues":
        occasions = _read(data_dir, "pr_fix_occasions.json")
        digest = _read(data_dir, "project_traffic_digest.json")
        common = _as_dict(occasions.get("common_issues") or digest.get("pr_fix_common_issues"))
        top = common.get("by_reason") or common.get("reasons") or common.get("top") or []
        bullets = [_bullet(f"Occasions logged: {len(occasions.get('occasions') or [])}")]
        if isinstance(top, list):
            for row in top[:5]:
                if isinstance(row, dict):
                    bullets.append(
                        _bullet(f"{row.get('reason') or row.get('key')}: {row.get('count')}")
                    )
                else:
                    bullets.append(_bullet(str(row)))
        elif isinstance(top, dict):
            for key, val in list(top.items())[:5]:
                bullets.append(_bullet(f"{key}: {val}"))
        fp = _fingerprint(
            {
                "n": len(occasions.get("occasions") or []),
                "at": occasions.get("updated_at") or digest.get("generated_at"),
                "common": common,
            }
        )
        return {
            "headline": "PR fix common issues",
            "updated_at": occasions.get("updated_at") or digest.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["pr_fix_occasions", "project_traffic_digest"],
        }

    if tid == "adhoc-review-ingest-deviations":
        payload = _read(data_dir, "ingest_deviations.json")
        open_items = [
            row
            for row in (payload.get("open_items") or payload.get("items") or [])
            if isinstance(row, dict) and (not row.get("status") or row.get("status") == "open")
        ]
        bullets = [_bullet(f"Open deviations: {len(open_items)}")]
        for row in open_items[:5]:
            bullets.append(
                _bullet(f"{row.get('ticker')}: {row.get('kind')} — {row.get('summary')}")
            )
        fp = _fingerprint(
            {
                "n": len(open_items),
                "ids": [str(r.get("id") or r.get("ticker")) for r in open_items[:10]],
                "at": payload.get("updated_at"),
            }
        )
        return {
            "headline": f"Ingest deviations · {len(open_items)} open",
            "updated_at": payload.get("updated_at") or payload.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["ingest_deviations"],
        }

    if tid == "quarterly-deferred-review":
        # deferred-review.md is generated; horizon_tasks may hold promotes
        tasks = _read(data_dir, "horizon_tasks.json")
        items = [t for t in (tasks.get("tasks") or tasks.get("items") or []) if isinstance(t, dict)]
        bullets = [_bullet(f"Horizon/deferred triage items: {len(items)}")]
        for row in items[:5]:
            bullets.append(_bullet(f"{row.get('id')}: {row.get('title') or row.get('status')}"))
        fp = _fingerprint({"n": len(items), "at": tasks.get("updated_at")})
        return {
            "headline": "Deferred ideas review",
            "updated_at": tasks.get("updated_at") or tasks.get("generated_at"),
            "fingerprint": fp,
            "bullets": [b for b in bullets if b][:8],
            "source_keys": ["horizon_tasks"],
        }

    # Generic fallback — checklist summary only
    return {
        "headline": "See runbook for analysis inputs",
        "updated_at": None,
        "fingerprint": _fingerprint({"task_id": tid, "generic": True}),
        "bullets": [],
        "source_keys": [],
    }


def _sort_bucket(ack: dict[str, Any]) -> str:
    if ack.get("stale"):
        return "new_info"
    if not ack.get("acked"):
        return "unacked"
    return "acked"


_BUCKET_RANK = {"new_info": 0, "unacked": 1, "acked": 2}


def build_human_tasks_board(
    *,
    data_dir: Path | None = None,
    checklist_path: Path | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    checklist = load_human_tasks_checklist(checklist_path or DEFAULT_CHECKLIST_PATH)
    acks = load_human_task_acks(data_dir)
    repo_docs_base = str(checklist.get("repo_docs_base") or "")
    human_rows: list[dict[str, Any]] = []
    automated_rows: list[dict[str, Any]] = []

    for section in checklist.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for task in section.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                continue
            analysis = _analysis_for_task(task_id, data_dir)
            fingerprint = str(analysis.get("fingerprint") or "")
            ack = annotate_task_ack(task, acks, fingerprint=fingerprint)
            approval_label = APPROVAL_GATE_IDS.get(task_id)
            # Checklist may override
            if task.get("approval_gate") is False:
                approval_label = None
            elif task.get("approval_gate") and not approval_label:
                approval_label = str(task.get("approval_label") or "Approve")
            row = {
                "id": task_id,
                "title": task.get("title"),
                "summary": task.get("summary"),
                "automated": bool(task.get("automated")),
                "cadence": section.get("cadence"),
                "section_id": section.get("id"),
                "section_title": section.get("title"),
                "doc_path": task.get("doc_path"),
                "doc_anchor": task.get("doc_anchor"),
                "doc_url": doc_url_for_task(task, repo_docs_base=repo_docs_base),
                "approval_gate": bool(approval_label),
                "approval_label": approval_label,
                "analysis": analysis,
                "ack": ack,
                "sort_bucket": _sort_bucket(ack) if not task.get("automated") else "automated",
            }
            if row["automated"]:
                automated_rows.append(row)
            else:
                human_rows.append(row)

    open_rows = [r for r in human_rows if r.get("sort_bucket") in {"new_info", "unacked"}]
    acked_rows = [r for r in human_rows if r.get("sort_bucket") == "acked"]

    by_bucket: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in open_rows:
        by_bucket[_BUCKET_RANK.get(str(row.get("sort_bucket")), 9)].append(row)
    open_ordered: list[dict[str, Any]] = []
    for bucket in sorted(by_bucket):
        group = by_bucket[bucket]
        present = [r for r in group if _as_dict(r.get("analysis")).get("updated_at")]
        missing = [r for r in group if not _as_dict(r.get("analysis")).get("updated_at")]
        present.sort(
            key=lambda row: str(_as_dict(row.get("analysis")).get("updated_at") or ""),
            reverse=True,
        )
        missing.sort(key=lambda row: str(row.get("id") or ""))
        open_ordered.extend(present + missing)
    acked_rows.sort(
        key=lambda row: str(_as_dict(row.get("ack")).get("acked_at") or ""),
        reverse=True,
    )
    ordered = open_ordered + acked_rows

    counts = {
        "new_info": sum(1 for r in ordered if r.get("sort_bucket") == "new_info"),
        "unacked": sum(1 for r in ordered if r.get("sort_bucket") == "unacked"),
        "acked": sum(1 for r in ordered if r.get("sort_bucket") == "acked"),
        "automated": len(automated_rows),
        "human": len(ordered),
    }
    return {
        "schema_version": 1,
        "generated_at": _utcnow(),
        "title": checklist.get("title") or "Human tasks",
        "summary": checklist.get("summary"),
        "runbook_path": checklist.get("runbook_path"),
        "repo_docs_base": repo_docs_base,
        "checklist_updated_at": checklist.get("updated_at"),
        "counts": counts,
        "tasks": ordered,
        "automated_tasks": automated_rows,
    }


def write_human_tasks_board(
    *,
    data_dir: Path | None = None,
    checklist_path: Path | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    board = build_human_tasks_board(data_dir=data_dir, checklist_path=checklist_path)
    dest = data_dir / BOARD_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, board, compact=False)
    board["path"] = str(dest)
    return board


__all__ = [
    "APPROVAL_GATE_IDS",
    "BOARD_FILENAME",
    "build_human_tasks_board",
    "write_human_tasks_board",
]
