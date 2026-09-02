"""Periodic honest status + so-what gap-closure for no-judgment findings.

Adapts the existing progress-report / ops-monitor / engineering-queue loop so
enforcement gaps (e.g. FCF basis mismatch noted but strong_buy left uncapped)
are queued for auto-dispatch without waiting for a human prompt. Judgment calls
(which filing FCF to lock in a bridge) remain human_gate.
"""

from __future__ import annotations

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


def _bridge_resolved(bridge: dict[str, Any] | None, fcf: dict[str, Any]) -> bool:
    if bool(fcf.get("bridge_resolved")):
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
    fcf = report.get("fcf") if isinstance(report.get("fcf"), dict) else {}
    screen = _as_float(fcf.get("screen_ttm"))
    filing = _as_float(fcf.get("filing_aligned"))
    overlay = bool(report.get("fcf_basis_overlay"))
    action_note = str(report.get("action_note") or "").strip()
    bridge = _load_bridge(ticker, artifacts_dir=artifacts_dir)
    bridge_ok = _bridge_resolved(bridge, fcf)

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

    if buy_tier and (material_mismatch or note_flag) and not bridge_ok:
        findings.append(
            SoWhatFinding(
                finding_id=f"fcf_bridge_needed:{ticker}",
                kind="fcf_bridge_needed",
                ticker=ticker,
                severity="medium",
                so_what=(
                    "Mismatch is visible on a buy-tier name; choosing the reviewed "
                    "policy FCF still needs a human (or explicit source policy). "
                    "Enforcement overlay alone does not replace a durable bridge."
                ),
                recommended_closure=CLOSURE_HUMAN_GATE,
                evidence={
                    "signal": signal,
                    "adjusted_signal": effective,
                    "screen_ttm": screen,
                    "filing_aligned": filing,
                    "gap_pct": round(gap * 100.0, 1) if gap is not None else None,
                    "fcf_basis_overlay": overlay,
                    "bridge_present": bridge is not None,
                },
                human_action=(
                    f"Review filings for {ticker} and write "
                    f"docs/data/research/{ticker}/sources/fcf_bridge.json "
                    "(policy_fcf + policy_basis + source_refs; set resolved=true)."
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
    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    next_seq = _next_engineering_seq_from_rows(rows, run_stamp)

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    generated: list[EngineeringTask] = []

    for finding in auto:
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
                "ticker": f.ticker,
                "so_what": f.so_what,
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
                "ticker": f.get("ticker"),
                "so_what": f.get("so_what"),
                "recommended_closure": f.get("recommended_closure"),
            }
            for f in high[:12]
        ],
        "human_gates_preview": human_gates[:8],
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
                    "ticker": f.ticker,
                    "so_what": f.so_what,
                    "human_action": f.human_action,
                    "human_doc_path": f.human_doc_path,
                }
                for f in findings
                if f.recommended_closure == CLOSURE_HUMAN_GATE
            ],
        }
    return so_what_summary_for_progress(snapshot)


def render_so_what_markdown(section: dict[str, Any] | None = None) -> str:
    """Render markdown from a progress-report so_what section (or full snapshot)."""
    if section is None:
        summary = so_what_summary_for_progress()
    elif "high_severity" in section:
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
    ]
    high = summary.get("high_severity") or []
    if high:
        lines.extend(["", "### High-severity so-whats", ""])
        for row in high:
            lines.append(
                f"- `{row.get('ticker')}` ({row.get('recommended_closure')}): {row.get('so_what')}"
            )
    gates = summary.get("human_gates_preview") or []
    if gates:
        lines.extend(["", "### Human gates", ""])
        for row in gates:
            action = row.get("human_action") or row.get("so_what")
            lines.append(f"- `{row.get('ticker')}`: {action}")
    lines.append("")
    return "\n".join(lines)
