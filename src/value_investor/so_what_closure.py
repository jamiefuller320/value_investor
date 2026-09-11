"""Periodic honest status + so-what gap-closure for no-judgment findings.

Adapts the existing progress-report / ops-monitor / engineering-queue loop so
enforcement gaps (e.g. FCF basis mismatch noted but strong_buy left uncapped)
are queued for auto-dispatch without waiting for a human prompt. Policy FCF is
chosen automatically (majority among screen / filing / company-adjusted, else
filing-aligned fallback); human_gate remains only when no auto-resolvable basis
exists.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.engineering_tasks import (
    BLOCKED_PATHS,
    COMMITTED_TASKS_PATH,
    TERMINAL_TASK_STATUSES,
    EngineeringTask,
    _allowed_paths_for_area,
    _default_acceptance_criteria,
    _extract_tickers,
    _merge_task_rows,
    _next_engineering_seq_from_rows,
    load_engineering_tasks,
)
from value_investor.storage import read_json, write_json

ARTIFACTS_DIR = Path("docs/data")
SO_WHAT_PATH = ARTIFACTS_DIR / "so_what_closure.json"
DEFAULT_LATEST_PATH = ARTIFACTS_DIR / "latest.json"

BUY_TIER = frozenset({"buy", "strong_buy"})
ACTION_NOTE_MARKERS = (
    "fcf basis mismatch",
    "fcf basis",
    "fcf mismatch",
    "filing-aligned fcf",
    "screen vs filing fcf",
    "screen ttm",
)

CLOSURE_AUTO_QUEUE = "auto_queue"
CLOSURE_HUMAN_GATE = "human_gate"
CLOSURE_OBSERVE = "observe"

_BATCH_TASK_TITLES: dict[str, str] = {
    "fcf_note_without_overlay": "Honour FCF action-note enforcement (batched tickers)",
    "fcf_enforcement_gap": "Close FCF basis enforcement gap (batched tickers)",
}

_KIND_LABELS: dict[str, str] = {
    "fcf_enforcement_gap": (
        "Buy-tier signal remains uncapped while screen vs filing FCF diverge materially. "
        "Enforcement must fail closed (overlay) without waiting for a human prompt."
    ),
    "fcf_note_without_overlay": (
        "Action note flags an FCF basis concern but adjusted_signal was not downgraded. "
        "Treat as an enforcement gap."
    ),
    "fcf_bridge_needed": (
        "Buy-tier FCF concern with no filing-aligned or company-adjusted figure for auto "
        "majority / filing fallback. Optional human bridge can still lock policy FCF; "
        "default path remains fail-closed."
    ),
    "fcf_mild_mismatch": (
        "Mild screen vs filing FCF gap. Observe unless it widens past 25% or an action "
        "note appears on a buy-tier name."
    ),
}

_SHARED_HUMAN_ACTIONS: dict[str, str] = {
    "fcf_bridge_needed": (
        "If auto policy cannot run (missing filing/company figures), write "
        "docs/data/research/<ticker>/sources/fcf_bridge.json "
        "(policy_fcf + policy_basis + source_refs; set resolved=true). "
        "Otherwise leave the automatic majority / filing fallback in place."
    ),
}


def _kind_from_row(row: dict[str, Any]) -> str:
    kind = str(row.get("kind") or "").strip()
    if kind:
        return kind
    finding_id = str(row.get("finding_id") or "")
    if ":" in finding_id:
        return finding_id.split(":", 1)[0]
    return "unknown"


def _normalize_human_action(action: str | None, *, kind: str) -> str:
    shared = _SHARED_HUMAN_ACTIONS.get(kind)
    if shared:
        return shared
    text = str(action or "").strip()
    if not text:
        return ""
    # Collapse per-ticker research paths so identical actions group cleanly.
    parts = text.split("docs/data/research/")
    if len(parts) == 2 and "/sources/" in parts[1]:
        suffix = parts[1].split("/sources/", 1)[1]
        return f"{parts[0]}docs/data/research/<ticker>/sources/{suffix}"
    return text


def group_so_what_rows(
    rows: list[dict[str, Any]],
    *,
    closure_key: str = "recommended_closure",
) -> list[dict[str, Any]]:
    """Collapse same-kind findings into one row with a ticker list."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = _kind_from_row(row)
        closure = str(row.get(closure_key) or row.get("recommended_closure") or "").strip()
        buckets[(kind, closure)].append(row)

    grouped: list[dict[str, Any]] = []
    for (kind, closure), members in sorted(buckets.items()):
        tickers = sorted(
            {
                str(m.get("ticker") or "").strip()
                for m in members
                if str(m.get("ticker") or "").strip()
            }
        )
        sample = members[0]
        severities = {str(m.get("severity") or "") for m in members}
        severity = (
            "high"
            if "high" in severities
            else ("medium" if "medium" in severities else (next(iter(severities), "") or None))
        )
        grouped.append(
            {
                "kind": kind,
                "label": _KIND_LABELS.get(kind, kind),
                "recommended_closure": closure or None,
                "severity": severity,
                "so_what": _KIND_LABELS.get(kind) or sample.get("so_what"),
                "human_action": _normalize_human_action(sample.get("human_action"), kind=kind),
                "human_doc_path": sample.get("human_doc_path"),
                "count": len(tickers),
                "tickers": tickers,
                "tickers_preview": tickers[:12],
            }
        )
    grouped.sort(key=lambda g: (-int(g.get("count") or 0), str(g.get("kind") or "")))
    return grouped


@dataclass(frozen=True)
class SoWhatFinding:
    finding_id: str
    kind: str
    ticker: str
    severity: str
    so_what: str
    recommended_closure: str
    evidence: dict[str, Any]
    engineering_area: str | None = None
    engineering_title: str | None = None
    engineering_summary: str | None = None
    human_action: str | None = None
    human_doc_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _norm_signal(value: Any) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"strongbuy": "strong_buy", "accumulate": "buy"}
    return aliases.get(raw, raw)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rel_abs_diff(a: float, b: float) -> float | None:
    if a == 0.0 and b == 0.0:
        return 0.0
    denom = max(abs(a), abs(b), 1.0)
    return abs(a - b) / denom


def _load_bridge(ticker: str, *, artifacts_dir: Path = ARTIFACTS_DIR) -> dict[str, Any] | None:
    path = Path(artifacts_dir) / "research" / ticker / "sources" / "fcf_bridge.json"
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _policy_fcf_resolved(bridge: dict[str, Any] | None, fcf: dict[str, Any]) -> bool:
    """True when human bridge or deterministic auto policy can lock policy FCF."""
    if bool(fcf.get("bridge_resolved")) or bool(fcf.get("auto_policy_resolved")):
        return True
    source = str(fcf.get("source") or "")
    if _as_float(fcf.get("policy_fcf")) is not None and source.startswith(("auto_", "policy_")):
        return True
    # Auto majority / filing fallback does not need a reviewed bridge file.
    if _as_float(fcf.get("filing_aligned")) is not None:
        return True
    if _as_float(fcf.get("company_adjusted")) is not None:
        return True
    if not isinstance(bridge, dict):
        return False
    if not bool(bridge.get("resolved")):
        return False
    return _as_float(bridge.get("policy_fcf")) is not None


def _has_action_note_marker(report: dict[str, Any]) -> bool:
    note = str(report.get("action_note") or "").strip().lower()
    return any(marker in note for marker in ACTION_NOTE_MARKERS)


def _fcf_findings_from_report(
    report: dict[str, Any],
    *,
    artifacts_dir: Path = ARTIFACTS_DIR,
) -> list[SoWhatFinding]:
    ticker = str(report.get("ticker") or "").strip()
    if not ticker:
        return []

    signal = _norm_signal(report.get("signal"))
    effective = _norm_signal(report.get("adjusted_signal")) or signal
    # Recover structured bases from persisted mismatch notes when fcf was dropped
    # on overlay/export refresh (notes keep filing/screen figures; fcf blob does not).
    from value_investor.scoring.fcf import fcf_bundle_from_persisted_report

    raw_fcf = report.get("fcf") if isinstance(report.get("fcf"), dict) else None
    key_metrics = report.get("key_metrics") if isinstance(report.get("key_metrics"), dict) else None
    action_note = str(report.get("action_note") or "").strip()
    fcf = fcf_bundle_from_persisted_report(
        raw_fcf,
        action_note=action_note,
        key_metrics=key_metrics,
    )
    screen = _as_float(fcf.get("screen_ttm"))
    filing = _as_float(fcf.get("filing_aligned"))
    overlay = bool(report.get("fcf_basis_overlay"))
    bridge = _load_bridge(ticker, artifacts_dir=artifacts_dir)
    bridge_ok = _policy_fcf_resolved(bridge, fcf)

    findings: list[SoWhatFinding] = []

    gap: float | None = None
    if screen is not None and filing is not None:
        gap = _rel_abs_diff(screen, filing)

    material_mismatch = gap is not None and gap >= 0.25
    note_flag = _has_action_note_marker(report)
    buy_tier = effective in BUY_TIER or signal in BUY_TIER
    gap_label = f"~{gap:.0%}" if gap is not None else "unknown"

    if material_mismatch and buy_tier and not overlay:
        findings.append(
            SoWhatFinding(
                finding_id=f"fcf_enforcement_gap:{ticker}",
                kind="fcf_enforcement_gap",
                ticker=ticker,
                severity="high",
                so_what=(
                    "Buy-tier signal remains uncapped while screen vs filing FCF diverge "
                    f"by {gap_label}. Enforcement must fail closed (overlay) without "
                    "waiting for a human prompt."
                ),
                recommended_closure=CLOSURE_AUTO_QUEUE,
                evidence={
                    "signal": signal,
                    "adjusted_signal": effective,
                    "screen_ttm": screen,
                    "filing_aligned": filing,
                    "gap_pct": round(gap * 100.0, 1) if gap is not None else None,
                    "fcf_basis_overlay": overlay,
                    "bridge_resolved": bridge_ok,
                    "action_note": action_note or None,
                },
                engineering_area="scoring",
                engineering_title=f"Close FCF basis enforcement gap for {ticker}",
                engineering_summary=(
                    f"{ticker}: material FCF basis mismatch ({gap_label}) with buy-tier "
                    f"signal={signal!r} / adjusted={effective!r} and fcf_basis_overlay="
                    f"{overlay}. Implement fail-closed overlay so strong_buy cannot ship "
                    "uncapped on a divergent Yahoo TTM basis. Prefer code/policy fix over "
                    "one-off manual triage."
                ),
            )
        )

    if note_flag and buy_tier and not overlay and not material_mismatch:
        findings.append(
            SoWhatFinding(
                finding_id=f"fcf_note_without_overlay:{ticker}",
                kind="fcf_note_without_overlay",
                ticker=ticker,
                severity="medium",
                so_what=(
                    "Action note flags an FCF basis concern but adjusted_signal was not "
                    "downgraded. Treat as an enforcement gap."
                ),
                recommended_closure=CLOSURE_AUTO_QUEUE,
                evidence={
                    "signal": signal,
                    "adjusted_signal": effective,
                    "screen_ttm": screen,
                    "filing_aligned": filing,
                    "gap_pct": round(gap * 100.0, 1) if gap is not None else None,
                    "fcf_basis_overlay": overlay,
                    "action_note": action_note,
                },
                engineering_area="scoring",
                engineering_title=f"Honour FCF action-note enforcement for {ticker}",
                engineering_summary=(
                    f"{ticker}: action_note mentions FCF basis mismatch but "
                    f"fcf_basis_overlay={overlay} and buy-tier signal remains. "
                    "Wire note -> overlay/gate consistently so notes are not cosmetic."
                ),
            )
        )

    # Residual only: cannot auto-resolve (no filing-aligned / company-adjusted /
    # auto policy) yet buy-tier still shows a mismatch note.
    if buy_tier and (material_mismatch or note_flag) and not bridge_ok:
        findings.append(
            SoWhatFinding(
                finding_id=f"fcf_bridge_needed:{ticker}",
                kind="fcf_bridge_needed",
                ticker=ticker,
                severity="medium",
                so_what=(
                    "Buy-tier FCF concern with no filing-aligned or company-adjusted "
                    "figure for auto majority / filing fallback. Optional human "
                    "bridge can still lock policy FCF; default path remains fail-closed."
                ),
                recommended_closure=CLOSURE_HUMAN_GATE,
                evidence={
                    "signal": signal,
                    "adjusted_signal": effective,
                    "screen_ttm": screen,
                    "filing_aligned": filing,
                    "company_adjusted": _as_float(fcf.get("company_adjusted")),
                    "gap_pct": round(gap * 100.0, 1) if gap is not None else None,
                    "fcf_basis_overlay": overlay,
                    "bridge_present": bridge is not None,
                    "auto_policy_resolved": bool(fcf.get("auto_policy_resolved")),
                },
                human_action=(
                    f"If auto policy cannot run (missing filing/company figures), "
                    f"write docs/data/research/{ticker}/sources/fcf_bridge.json "
                    "(policy_fcf + policy_basis + source_refs; set resolved=true). "
                    "Otherwise leave the automatic majority / filing fallback in place."
                ),
                human_doc_path="docs/ops/fcf-basis-bridges.md",
            )
        )

    mild = (
        gap is not None
        and 0.10 <= gap < 0.25
        and (note_flag or buy_tier)
        and not overlay
        and not bridge_ok
        and not findings
    )
    if mild:
        findings.append(
            SoWhatFinding(
                finding_id=f"fcf_mild_mismatch:{ticker}",
                kind="fcf_mild_mismatch",
                ticker=ticker,
                severity="low",
                so_what=(
                    "Mild screen vs filing FCF gap. Observe unless it widens past 25% "
                    "or an action note appears on a buy-tier name."
                ),
                recommended_closure=CLOSURE_OBSERVE,
                evidence={
                    "signal": signal,
                    "adjusted_signal": effective,
                    "screen_ttm": screen,
                    "filing_aligned": filing,
                    "gap_pct": round(gap * 100.0, 1),
                },
            )
        )

    return findings


def scan_so_what_issues(
    *,
    reports: list[dict[str, Any]] | None = None,
    latest_path: Path = DEFAULT_LATEST_PATH,
    artifacts_dir: Path = ARTIFACTS_DIR,
) -> list[SoWhatFinding]:
    """Scan live reports for findings that need a so-what closure path."""
    if reports is None:
        path = Path(latest_path)
        latest = read_json(path) if path.exists() else {}
        reports = latest.get("reports") if isinstance(latest, dict) else None
        if not isinstance(reports, list):
            reports = []

    findings: list[SoWhatFinding] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        findings.extend(_fcf_findings_from_report(report, artifacts_dir=artifacts_dir))

    findings.sort(
        key=lambda f: ({"high": 0, "medium": 1, "low": 2}.get(f.severity, 9), f.ticker, f.kind)
    )
    return findings


def _existing_open_keys(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    open_keys: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "open").strip().lower() in TERMINAL_TASK_STATUSES:
            continue
        title = str(row.get("title") or "").strip()
        area = str(row.get("area") or "").strip()
        if title and area:
            open_keys.add((area, title))
    return open_keys


def _existing_open_batch_keys(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Open (area, kind) pairs for batched or legacy per-ticker so-what tasks."""
    keys: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "open").strip().lower() in TERMINAL_TASK_STATUSES:
            continue
        area = str(row.get("area") or "").strip()
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        kind = str(evidence.get("kind") or "").strip()
        if area and kind in _BATCH_TASK_TITLES:
            keys.add((area, kind))
    return keys


def _build_batch_engineering_task(
    *,
    area: str,
    kind: str,
    findings: list[SoWhatFinding],
    task_id: str,
) -> EngineeringTask:
    title = _BATCH_TASK_TITLES[kind]
    tickers = sorted({f.ticker for f in findings if f.ticker})
    ticker_sample = ", ".join(tickers[:8])
    if len(tickers) > 8:
        ticker_sample += f" (+{len(tickers) - 8} more)"
    severities = {f.severity for f in findings}
    severity = "high" if "high" in severities else "medium"
    if kind == "fcf_enforcement_gap":
        summary = (
            f"Batched so-what closure for {len(tickers)} buy-tier name(s) with material "
            f"FCF basis divergence and fcf_basis_overlay=False ({ticker_sample}). "
            "Implement fail-closed overlay once for all tickers; add regression tests per ticker."
        )
    else:
        summary = (
            f"Batched so-what closure for {len(tickers)} buy-tier name(s) where action_note "
            f"flags FCF basis but overlay is missing ({ticker_sample}). "
            "Wire note -> overlay/gate consistently; add regression tests per ticker."
        )
    return EngineeringTask(
        id=task_id,
        title=title[:160],
        summary=summary[:2000],
        area=area,
        priority="high" if severity == "high" else "medium",
        priority_score=82.0 if severity == "high" else 70.0,
        status="open",
        source="so_what_closure",
        evidence={
            "kind": kind,
            "batched": True,
            "tickers": tickers,
            "finding_count": len(findings),
            "findings": [
                {
                    "finding_id": f.finding_id,
                    "ticker": f.ticker,
                    "severity": f.severity,
                    **(f.evidence or {}),
                }
                for f in findings
            ],
        },
        acceptance_criteria=_default_acceptance_criteria(area, tickers),
        allowed_paths=_allowed_paths_for_area(area),
        blocked_paths=list(BLOCKED_PATHS),
    )


def apply_so_what_auto_queue(
    findings: list[SoWhatFinding] | None = None,
    *,
    dry_run: bool = False,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    snapshot_path: Path = SO_WHAT_PATH,
    latest_path: Path = DEFAULT_LATEST_PATH,
    artifacts_dir: Path = ARTIFACTS_DIR,
) -> dict[str, Any]:
    """Compile auto_queue findings into engineering_tasks.json (idempotent)."""
    findings = (
        findings
        if findings is not None
        else scan_so_what_issues(latest_path=latest_path, artifacts_dir=artifacts_dir)
    )
    auto = [f for f in findings if f.recommended_closure == CLOSURE_AUTO_QUEUE]
    human = [f for f in findings if f.recommended_closure == CLOSURE_HUMAN_GATE]
    observe = [f for f in findings if f.recommended_closure == CLOSURE_OBSERVE]

    tasks_path = Path(tasks_path)
    existing = load_engineering_tasks(tasks_path) if tasks_path.exists() else {"tasks": []}
    if not isinstance(existing, dict):
        existing = {"tasks": []}
    rows = [r for r in (existing.get("tasks") or []) if isinstance(r, dict)]
    open_keys = _existing_open_keys(rows)
    open_batch_keys = _existing_open_batch_keys(rows)
    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    next_seq = _next_engineering_seq_from_rows(rows, run_stamp)

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    generated: list[EngineeringTask] = []

    groups: dict[tuple[str, str], list[SoWhatFinding]] = defaultdict(list)
    ungrouped: list[SoWhatFinding] = []
    for finding in auto:
        area = str(finding.engineering_area or "scoring").strip() or "scoring"
        if finding.kind in _BATCH_TASK_TITLES:
            groups[(area, finding.kind)].append(finding)
        else:
            ungrouped.append(finding)

    for (area, kind), group_findings in sorted(groups.items()):
        if (area, kind) in open_batch_keys:
            for finding in group_findings:
                skipped.append(
                    {
                        "finding_id": finding.finding_id,
                        "reason": "batch_already_open",
                        "kind": kind,
                    }
                )
            continue
        if any(
            bp in " ".join(f.engineering_summary or "" for f in group_findings)
            for bp in BLOCKED_PATHS
        ):
            for finding in group_findings:
                skipped.append({"finding_id": finding.finding_id, "reason": "blocked_path"})
            continue

        task_id = f"eng-{run_stamp}-{next_seq:02d}"
        next_seq += 1
        task = _build_batch_engineering_task(
            area=area,
            kind=kind,
            findings=group_findings,
            task_id=task_id,
        )
        generated.append(task)
        open_batch_keys.add((area, kind))
        created.append(
            {
                "finding_id": group_findings[0].finding_id,
                "task_id": task_id,
                "title": task.title,
                "area": area,
                "severity": task.priority,
                "batched": True,
                "tickers": task.evidence.get("tickers") if isinstance(task.evidence, dict) else [],
                "finding_count": len(group_findings),
            }
        )

    for finding in ungrouped:
        area = str(finding.engineering_area or "scoring").strip() or "scoring"
        title = str(finding.engineering_title or "").strip()
        summary = str(finding.engineering_summary or finding.so_what).strip()
        if not title:
            skipped.append({"finding_id": finding.finding_id, "reason": "missing_title"})
            continue
        if (area, title) in open_keys:
            skipped.append(
                {"finding_id": finding.finding_id, "reason": "already_open", "title": title}
            )
            continue
        if any(bp in summary for bp in BLOCKED_PATHS):
            skipped.append({"finding_id": finding.finding_id, "reason": "blocked_path"})
            continue

        task_id = f"eng-{run_stamp}-{next_seq:02d}"
        next_seq += 1
        tickers = _extract_tickers(title, summary, finding.ticker)
        task = EngineeringTask(
            id=task_id,
            title=title[:160],
            summary=summary[:2000],
            area=area,
            priority="high" if finding.severity == "high" else "medium",
            priority_score=82.0 if finding.severity == "high" else 70.0,
            status="open",
            source="so_what_closure",
            evidence={
                "finding_id": finding.finding_id,
                "kind": finding.kind,
                "ticker": finding.ticker,
                "severity": finding.severity,
                **(finding.evidence or {}),
            },
            acceptance_criteria=_default_acceptance_criteria(area, tickers),
            allowed_paths=_allowed_paths_for_area(area),
            blocked_paths=list(BLOCKED_PATHS),
        )
        generated.append(task)
        open_keys.add((area, title))
        created.append(
            {
                "finding_id": finding.finding_id,
                "task_id": task_id,
                "title": title,
                "area": area,
                "severity": finding.severity,
            }
        )

    if generated and not dry_run:
        merged = _merge_task_rows(rows, generated)
        payload = {
            **existing,
            "schema_version": existing.get("schema_version") or "engineering_tasks.v1",
            "compiled_at": _iso_now(),
            "generated_at": _iso_now(),
            "source": "so_what_closure",
            "task_count": len(merged),
            "tasks": merged,
            "so_what_compiled": True,
        }
        tasks_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(tasks_path, payload, compact=False)

    snapshot = {
        "schema_version": "so_what_closure.v1",
        "generated_at": _iso_now(),
        "dry_run": dry_run,
        "counts": {
            "findings": len(findings),
            "auto_queue": len(auto),
            "human_gate": len(human),
            "observe": len(observe),
            "tasks_created": len(created),
            "tasks_skipped": len(skipped),
        },
        "findings": [f.to_dict() for f in findings],
        "created_tasks": created,
        "skipped_tasks": skipped,
        "human_gates": [
            {
                "finding_id": f.finding_id,
                "kind": f.kind,
                "ticker": f.ticker,
                "severity": f.severity,
                "so_what": f.so_what,
                "recommended_closure": f.recommended_closure,
                "human_action": f.human_action,
                "human_doc_path": f.human_doc_path,
            }
            for f in human
        ],
    }
    if not dry_run:
        snap = Path(snapshot_path)
        snap.parent.mkdir(parents=True, exist_ok=True)
        write_json(snap, snapshot, compact=False)
    return snapshot


def so_what_summary_for_progress(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compact rollup for progress-report consumers."""
    if snapshot is None:
        snapshot = read_json(SO_WHAT_PATH) if SO_WHAT_PATH.exists() else {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    counts = snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {}
    human_gates = (
        snapshot.get("human_gates") if isinstance(snapshot.get("human_gates"), list) else []
    )
    findings = snapshot.get("findings") if isinstance(snapshot.get("findings"), list) else []
    high = [f for f in findings if isinstance(f, dict) and f.get("severity") == "high"]
    high_groups = group_so_what_rows(high)
    human_gate_groups = group_so_what_rows(
        [g for g in human_gates if isinstance(g, dict)],
        closure_key="recommended_closure",
    )
    # Fall back: derive human-gate groups from findings when snapshot gates lack kind.
    if not human_gate_groups and findings:
        human_gate_groups = group_so_what_rows(
            [
                f
                for f in findings
                if isinstance(f, dict) and f.get("recommended_closure") == CLOSURE_HUMAN_GATE
            ]
        )
    return {
        "generated_at": snapshot.get("generated_at"),
        "counts": {
            "findings": int(counts.get("findings") or len(findings) or 0),
            "auto_queue": int(counts.get("auto_queue") or 0),
            "human_gate": int(counts.get("human_gate") or 0),
            "observe": int(counts.get("observe") or 0),
            "tasks_created": int(counts.get("tasks_created") or 0),
        },
        "high_severity": [
            {
                "finding_id": f.get("finding_id"),
                "kind": f.get("kind"),
                "ticker": f.get("ticker"),
                "so_what": f.get("so_what"),
                "recommended_closure": f.get("recommended_closure"),
            }
            for f in high[:12]
        ],
        "high_severity_groups": high_groups,
        "human_gates_preview": human_gates[:8],
        "human_gate_groups": human_gate_groups,
    }


def build_so_what_section(
    *,
    apply: bool = False,
    dry_run: bool = False,
    latest_path: Path = DEFAULT_LATEST_PATH,
    artifacts_dir: Path = ARTIFACTS_DIR,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    snapshot_path: Path = SO_WHAT_PATH,
) -> dict[str, Any]:
    """Scan (and optionally queue) so-what findings; return progress-report section."""
    findings = scan_so_what_issues(latest_path=latest_path, artifacts_dir=artifacts_dir)
    if apply or dry_run:
        snapshot = apply_so_what_auto_queue(
            findings,
            dry_run=dry_run or not apply,
            tasks_path=tasks_path,
            snapshot_path=snapshot_path,
            latest_path=latest_path,
            artifacts_dir=artifacts_dir,
        )
    else:
        snapshot = {
            "schema_version": "so_what_closure.v1",
            "generated_at": _iso_now(),
            "dry_run": True,
            "counts": {
                "findings": len(findings),
                "auto_queue": sum(
                    1 for f in findings if f.recommended_closure == CLOSURE_AUTO_QUEUE
                ),
                "human_gate": sum(
                    1 for f in findings if f.recommended_closure == CLOSURE_HUMAN_GATE
                ),
                "observe": sum(1 for f in findings if f.recommended_closure == CLOSURE_OBSERVE),
                "tasks_created": 0,
                "tasks_skipped": 0,
            },
            "findings": [f.to_dict() for f in findings],
            "created_tasks": [],
            "skipped_tasks": [],
            "human_gates": [
                {
                    "finding_id": f.finding_id,
                    "kind": f.kind,
                    "ticker": f.ticker,
                    "severity": f.severity,
                    "so_what": f.so_what,
                    "recommended_closure": f.recommended_closure,
                    "human_action": f.human_action,
                    "human_doc_path": f.human_doc_path,
                }
                for f in findings
                if f.recommended_closure == CLOSURE_HUMAN_GATE
            ],
        }
    return so_what_summary_for_progress(snapshot)


def _format_ticker_list(tickers: list[Any], *, limit: int = 12) -> str:
    names = [str(t).strip() for t in tickers if str(t).strip()]
    if not names:
        return "—"
    shown = names[:limit]
    text = ", ".join(f"`{name}`" for name in shown)
    remaining = len(names) - len(shown)
    if remaining > 0:
        text += f" (+{remaining} more)"
    return text


def render_so_what_markdown(section: dict[str, Any] | None = None) -> str:
    """Render markdown from a progress-report so_what section (or full snapshot)."""
    if section is None:
        summary = so_what_summary_for_progress()
    elif "high_severity" in section or "human_gate_groups" in section:
        summary = section
    else:
        summary = so_what_summary_for_progress(section)
    counts = summary.get("counts") or {}
    lines = [
        "## So what? (gap closure)",
        "",
        (
            f"- Findings: **{counts.get('findings', 0)}** "
            f"(auto_queue={counts.get('auto_queue', 0)}, "
            f"human_gate={counts.get('human_gate', 0)}, "
            f"observe={counts.get('observe', 0)}); "
            f"engineering tasks created this pass: **{counts.get('tasks_created', 0)}**."
        ),
        (
            "- Auto-queue covers no-judgment enforcement gaps (e.g. FCF mismatch with "
            "uncapped buy/strong_buy). Human gate covers policy FCF bridge reviews."
        ),
        "- Same-issue names are grouped by kind (one row + ticker list), matching batched "
        "engineering tasks.",
    ]
    high_groups = summary.get("high_severity_groups") or []
    if not high_groups and summary.get("high_severity"):
        high_groups = group_so_what_rows(
            [row for row in summary.get("high_severity") or [] if isinstance(row, dict)]
        )
    if high_groups:
        lines.extend(["", "### High-severity so-whats", ""])
        for group in high_groups:
            closure = group.get("recommended_closure") or "—"
            lines.append(
                f"- **{group.get('count', 0)} names** (`{group.get('kind')}`, {closure}): "
                f"{group.get('so_what') or group.get('label')}"
            )
            lines.append(f"  - Tickers: {_format_ticker_list(group.get('tickers') or [])}")
    gates_groups = summary.get("human_gate_groups") or []
    if not gates_groups and summary.get("human_gates_preview"):
        gates_groups = group_so_what_rows(
            [row for row in summary.get("human_gates_preview") or [] if isinstance(row, dict)]
        )
    if gates_groups:
        lines.extend(["", "### Human gates", ""])
        for group in gates_groups:
            action = group.get("human_action") or group.get("so_what") or group.get("label")
            lines.append(f"- **{group.get('count', 0)} names** (`{group.get('kind')}`): {action}")
            lines.append(f"  - Tickers: {_format_ticker_list(group.get('tickers') or [])}")
    lines.append("")
    return "\n".join(lines)
