"""Automated Phase C readiness assessment (deliberate, evidence-backed).

Phase C (PIT decision autopsy) must not start on vibes. This module scores the
locked prerequisites from ``docs/ops/pit-decision-autopsy.md`` and emits a
machine-readable verdict.

Required checks (all must ``pass`` for overall ready):

1. **Phase B slim** — research store shows structured-verdict modes (or operator
   force override for dry-runs).
2. **Rebalance log span** — AI-judgment ``rebalance_log.json`` covers ≥8 weeks
   with buy-tier / candidates fields on most rows.
3. **Feature coverage** — filing / FCF / overlay / verdict signals are not almost
   always absent on FTSE buy-tier ∪ holdings samples.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

CheckStatus = Literal["pass", "fail", "unknown"]

# Keep in sync with value_investor.research.agent.STRUCTURED_VERDICT_MODES
STRUCTURED_VERDICT_MODES = frozenset(
    {
        "structured_verdict",
        "structured_verdict_update",
        "structured_verdict_gap_fill",
    }
)

DEFAULT_AI_JUDGMENT_DIR = Path("docs/data/paper_automation/ai_judgment")
DEFAULT_RESEARCH_ROOT = Path("docs/data/research")
DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
MIN_REBALANCE_SPAN_DAYS = 56  # 8 weeks
MIN_STRUCTURED_DOCS = 3
MIN_FEATURE_COVERAGE = 0.25


@dataclass
class ReadinessCheck:
    id: str
    title: str
    status: CheckStatus
    required: bool = True
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseCReadinessReport:
    assessed_at: str
    ready: bool
    summary: str
    checks: list[ReadinessCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessed_at": self.assessed_at,
            "ready": self.ready,
            "summary": self.summary,
            "checks": [asdict(c) for c in self.checks],
        }


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _rebalance_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("entries", "log", "rows"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def check_phase_b_slim(
    research_root: Path,
    *,
    force_phase_b_done: bool = False,
) -> ReadinessCheck:
    title = "Phase B structured-verdict slim in flight or done"
    if force_phase_b_done:
        return ReadinessCheck(
            id="phase_b_slim",
            title=title,
            status="pass",
            detail="Forced pass via --force-phase-b-done (operator override).",
            evidence={"forced": True},
        )
    if not research_root.exists():
        return ReadinessCheck(
            id="phase_b_slim",
            title=title,
            status="unknown",
            detail=f"Research root missing: {research_root}",
            evidence={"research_root": str(research_root)},
        )

    structured = 0
    essay = 0
    sampled = 0
    examples: list[str] = []
    for path in sorted(research_root.glob("*/research.json"))[:200]:
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        sampled += 1
        mode = str(payload.get("mode") or "")
        if mode in STRUCTURED_VERDICT_MODES:
            structured += 1
            if len(examples) < 5:
                examples.append(f"{path.parent.name}:{mode}")
        elif mode in {"initial", "weekly_update", "gap_fill"}:
            essay += 1

    if structured >= MIN_STRUCTURED_DOCS:
        status: CheckStatus = "pass"
        detail = (
            f"Found {structured} structured-verdict docs "
            f"(legacy essay modes still present: {essay})."
        )
    elif structured > 0:
        status = "fail"
        detail = f"Only {structured} structured-verdict docs (need ≥{MIN_STRUCTURED_DOCS})."
    else:
        status = "fail"
        detail = "No structured_verdict* modes in research store yet."

    return ReadinessCheck(
        id="phase_b_slim",
        title=title,
        status=status,
        detail=detail,
        evidence={
            "sampled_docs": sampled,
            "structured_docs": structured,
            "essay_docs": essay,
            "examples": examples,
            "min_structured_docs": MIN_STRUCTURED_DOCS,
        },
    )


def check_rebalance_log_span(ai_judgment_dir: Path) -> ReadinessCheck:
    title = "AI-judgment rebalance_log ≥8 weeks with buy-tier/candidates"
    log_path = ai_judgment_dir / "rebalance_log.json"
    payload = _load_json(log_path)
    entries = _rebalance_entries(payload)
    if not entries:
        return ReadinessCheck(
            id="rebalance_log_span",
            title=title,
            status="unknown" if not log_path.exists() else "fail",
            detail=(
                f"No rebalance_log entries at {log_path}"
                if not log_path.exists()
                else "rebalance_log exists but has no entries"
            ),
            evidence={"path": str(log_path), "entry_count": 0},
        )

    timestamps: list[datetime] = []
    with_universe = 0
    for row in entries:
        screen_source = row.get("screen_source")
        ts = (
            _parse_ts(row.get("logged_at"))
            or _parse_ts(row.get("as_of"))
            or _parse_ts(row.get("run_at"))
            or (_parse_ts(screen_source.get("run_at")) if isinstance(screen_source, dict) else None)
        )
        if ts is not None:
            timestamps.append(ts)
        if row.get("screen_buy_tier") or row.get("candidates"):
            with_universe += 1

    if not timestamps:
        return ReadinessCheck(
            id="rebalance_log_span",
            title=title,
            status="fail",
            detail="Entries present but no parseable timestamps.",
            evidence={
                "entry_count": len(entries),
                "with_universe_fields": with_universe,
            },
        )

    span_days = (max(timestamps) - min(timestamps)).total_seconds() / 86400.0
    universe_ok = with_universe >= max(1, int(0.8 * len(entries)))
    span_ok = span_days + 1e-9 >= MIN_REBALANCE_SPAN_DAYS
    status: CheckStatus = "pass" if span_ok and universe_ok else "fail"
    return ReadinessCheck(
        id="rebalance_log_span",
        title=title,
        status=status,
        detail=(
            f"Span {span_days:.1f} days across {len(entries)} entries "
            f"({with_universe} with buy-tier/candidates). "
            f"Need ≥{MIN_REBALANCE_SPAN_DAYS} days and universe fields on ≥80% of rows."
        ),
        evidence={
            "path": str(log_path),
            "entry_count": len(entries),
            "span_days": round(span_days, 2),
            "min_span_days": MIN_REBALANCE_SPAN_DAYS,
            "with_universe_fields": with_universe,
            "first": min(timestamps).isoformat(),
            "last": max(timestamps).isoformat(),
        },
    )


def _feature_flag_true(row: dict[str, Any]) -> bool:
    if row.get("fcf_basis_overlay") is True:
        return True
    if row.get("fcf_basis_bound") is True:
        return True
    if row.get("eps_overlay_bound") is True:
        return True
    if row.get("overlay_bound") is True:
        return True
    if row.get("research_verdict"):
        return True
    try:
        if int(row.get("filings_with_body") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    quality = row.get("memo_quality") if isinstance(row.get("memo_quality"), dict) else {}
    try:
        if int(quality.get("filings_with_body") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return False


def check_feature_flag_coverage(latest_path: Path) -> ReadinessCheck:
    title = "FTSE holdings/buy-tier feature flags non-trivial"
    payload = _load_json(latest_path)
    if not isinstance(payload, dict):
        return ReadinessCheck(
            id="feature_flag_coverage",
            title=title,
            status="unknown",
            detail=f"Could not read reports from {latest_path}",
            evidence={"path": str(latest_path)},
        )

    reports = payload.get("reports") or payload.get("companies") or []
    if not isinstance(reports, list) or not reports:
        return ReadinessCheck(
            id="feature_flag_coverage",
            title=title,
            status="unknown",
            detail="latest.json has no reports list",
            evidence={"path": str(latest_path)},
        )

    sampled: list[dict[str, Any]] = []
    for row in reports:
        if not isinstance(row, dict):
            continue
        signal = str(row.get("signal") or row.get("adjusted_signal") or "").lower()
        in_buy = signal in {"strong_buy", "buy"} or bool(row.get("in_buy_tier"))
        held = bool(row.get("held") or row.get("in_portfolio") or row.get("position"))
        if in_buy or held:
            sampled.append(row)
    if not sampled:
        sampled = [row for row in reports if isinstance(row, dict)]
    if not sampled:
        return ReadinessCheck(
            id="feature_flag_coverage",
            title=title,
            status="unknown",
            detail="No sample rows available for feature-flag coverage.",
            evidence={"path": str(latest_path)},
        )

    positive = sum(1 for row in sampled if _feature_flag_true(row))
    coverage = positive / len(sampled)
    status: CheckStatus = "pass" if coverage >= MIN_FEATURE_COVERAGE else "fail"
    return ReadinessCheck(
        id="feature_flag_coverage",
        title=title,
        status=status,
        detail=(
            f"{positive}/{len(sampled)} sampled buy-tier/held rows show a positive "
            f"filing/FCF/overlay/verdict feature ({coverage:.0%}; "
            f"need ≥{MIN_FEATURE_COVERAGE:.0%})."
        ),
        evidence={
            "path": str(latest_path),
            "sampled": len(sampled),
            "positive": positive,
            "coverage": round(coverage, 4),
            "min_coverage": MIN_FEATURE_COVERAGE,
        },
    )


def assess_phase_c_readiness(
    *,
    ai_judgment_dir: Path = DEFAULT_AI_JUDGMENT_DIR,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    latest_path: Path = DEFAULT_LATEST_PATH,
    force_phase_b_done: bool = False,
    now: datetime | None = None,
) -> PhaseCReadinessReport:
    assessed_at = (now or datetime.now(UTC)).isoformat()
    checks = [
        check_phase_b_slim(research_root, force_phase_b_done=force_phase_b_done),
        check_rebalance_log_span(ai_judgment_dir),
        check_feature_flag_coverage(latest_path),
    ]
    failed = [c for c in checks if c.required and c.status != "pass"]
    ready = not failed
    if ready:
        summary = "Phase C prerequisites satisfied — freeze writer may proceed."
    else:
        summary = "Phase C not ready: " + ", ".join(f"{c.id}={c.status}" for c in failed)
    return PhaseCReadinessReport(
        assessed_at=assessed_at,
        ready=ready,
        summary=summary,
        checks=checks,
    )


def write_phase_c_readiness_report(report: PhaseCReadinessReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def format_phase_c_readiness_text(report: PhaseCReadinessReport) -> str:
    lines = [
        f"Phase C readiness: {'READY' if report.ready else 'NOT READY'}",
        f"Assessed at: {report.assessed_at}",
        report.summary,
        "",
    ]
    for check in report.checks:
        req = "required" if check.required else "optional"
        lines.append(f"- [{check.status}] {check.id} ({req}): {check.title}")
        if check.detail:
            lines.append(f"    {check.detail}")
    return "\n".join(lines) + "\n"
