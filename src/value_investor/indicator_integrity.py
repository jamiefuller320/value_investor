"""Claimed-vs-landed indicator integrity (L389).

Known-issue monitors miss false greens: a workflow or field looks healthy while
the artifact that matters did not move. These helpers compare *claims*
(receipts / present fields) to *landings* (committed mode flips, persist counts).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.phase_c_readiness import STRUCTURED_VERDICT_MODES
from value_investor.storage import read_json, write_json

DEFAULT_RECEIPT_PATH = Path("docs/data/research_docs_receipt.json")
DEFAULT_RESEARCH_ROOT = Path("docs/data/research")
RECEIPT_SCHEMA_VERSION = 1
RECEIPT_LOOKBACK_DAYS = 10
MIN_VERDICT_WITHOUT_STRUCTURED = 5
ESSAY_MODES = frozenset({"initial", "weekly_update", "gap_fill", ""})


@dataclass
class ResearchStoreModeStats:
    sampled: int = 0
    structured: int = 0
    essay: int = 0
    verdict_without_structured: int = 0
    structured_examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def count_research_store_modes(
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    *,
    limit: int = 200,
) -> ResearchStoreModeStats:
    """Scan committed research.json files for structured vs essay modes."""
    stats = ResearchStoreModeStats()
    if not research_root.is_dir():
        return stats
    for path in sorted(research_root.glob("*/research.json"))[: max(0, int(limit))]:
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        stats.sampled += 1
        mode = str(payload.get("mode") or "").strip()
        has_verdict = bool(str(payload.get("research_verdict") or "").strip())
        if mode in STRUCTURED_VERDICT_MODES:
            stats.structured += 1
            if len(stats.structured_examples) < 5:
                stats.structured_examples.append(f"{path.parent.name}:{mode}")
        else:
            if mode in ESSAY_MODES or mode not in STRUCTURED_VERDICT_MODES:
                if mode in ESSAY_MODES or not mode:
                    stats.essay += 1
                if has_verdict and mode not in STRUCTURED_VERDICT_MODES:
                    stats.verdict_without_structured += 1
    return stats


def build_research_docs_receipt(
    *,
    run_at: datetime | str,
    created: int,
    updated: int,
    skipped: int,
    errors: list[str],
    active_count: int,
    alumni_count: int,
    persisted_trees: int,
    touched_tickers: list[str],
    research_root: Path = DEFAULT_RESEARCH_ROOT,
) -> dict[str, Any]:
    """Build a claim receipt after Sunday ``--research-docs``."""
    if isinstance(run_at, datetime):
        run_at_text = run_at.astimezone(UTC).isoformat()
    else:
        run_at_text = str(run_at)
    stats = count_research_store_modes(research_root)
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "research_docs",
        "claimed": True,
        "run_at": run_at_text,
        "active_count": int(active_count),
        "alumni_count": int(alumni_count),
        "created": int(created),
        "updated": int(updated),
        "skipped": int(skipped),
        "error_count": len(errors),
        "errors": list(errors)[:20],
        "persisted_trees": int(persisted_trees),
        "touched_tickers": [str(t).strip().upper() for t in touched_tickers if str(t).strip()][
            :40
        ],
        "structured_modes_in_committed_after": stats.structured,
        "essay_modes_in_committed_after": stats.essay,
        "sampled_committed_docs": stats.sampled,
    }


def write_research_docs_receipt(
    receipt: dict[str, Any],
    *,
    committed_path: Path = DEFAULT_RECEIPT_PATH,
    output_path: Path | None = None,
) -> Path:
    """Persist receipt under docs/data (and optionally output/)."""
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(committed_path, receipt, compact=False)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(output_path, receipt, compact=False)
    return committed_path


def load_research_docs_receipt(path: Path = DEFAULT_RECEIPT_PATH) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def receipt_is_fresh(
    receipt: dict[str, Any],
    *,
    now: datetime | None = None,
    lookback_days: int = RECEIPT_LOOKBACK_DAYS,
) -> bool:
    now = now or datetime.now(UTC)
    run_at = _parse_ts(receipt.get("run_at"))
    if run_at is None:
        return False
    return run_at >= now - timedelta(days=max(1, int(lookback_days)))


@dataclass
class IntegrityFinding:
    """Plain finding payload; ops-monitor maps into OpsFinding."""

    severity: str
    check_id: str
    title: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_research_docs_receipt(
    receipt: dict[str, Any] | None,
    *,
    live_stats: ResearchStoreModeStats | None = None,
    now: datetime | None = None,
    lookback_days: int = RECEIPT_LOOKBACK_DAYS,
) -> list[IntegrityFinding]:
    """Flag false greens from a research-docs claim receipt."""
    if not receipt or not receipt.get("claimed"):
        return []
    if not receipt_is_fresh(receipt, now=now, lookback_days=lookback_days):
        return []

    findings: list[IntegrityFinding] = []
    created = int(receipt.get("created") or 0)
    updated = int(receipt.get("updated") or 0)
    writes = created + updated
    active = int(receipt.get("active_count") or 0)
    alumni = int(receipt.get("alumni_count") or 0)
    targets = active + alumni
    persisted = int(receipt.get("persisted_trees") or 0)
    structured_after = int(receipt.get("structured_modes_in_committed_after") or 0)
    live_structured = (
        int(live_stats.structured) if live_stats is not None else structured_after
    )
    run_at = str(receipt.get("run_at") or "")

    if targets > 0 and writes == 0:
        findings.append(
            IntegrityFinding(
                severity="fail",
                check_id="research_docs_claimed_zero_writes",
                title="Claimed research-docs wrote zero memos",
                summary=(
                    f"research_docs receipt at {run_at} claimed a run with "
                    f"active={active} alumni={alumni} but created+updated=0 "
                    f"(skipped={receipt.get('skipped')}, errors={receipt.get('error_count')}). "
                    "Workflow looked green while no memo artifacts landed."
                ),
            )
        )

    if writes > 0 and persisted == 0:
        findings.append(
            IntegrityFinding(
                severity="fail",
                check_id="research_docs_writes_not_persisted",
                title="Research-docs writes not persisted to committed store",
                summary=(
                    f"receipt at {run_at} reports created+updated={writes} but "
                    f"persisted_trees=0 — output/ may have moved without "
                    f"docs/data/research landing."
                ),
            )
        )

    if writes > 0 and live_structured == 0:
        findings.append(
            IntegrityFinding(
                severity="fail",
                check_id="research_docs_writes_without_structured_modes",
                title="Research-docs writes left zero structured_verdict modes",
                summary=(
                    f"receipt at {run_at} reports writes={writes} / persisted={persisted}, "
                    f"but committed store still has 0 structured_verdict* modes "
                    f"(sampled={getattr(live_stats, 'sampled', receipt.get('sampled_committed_docs'))}). "
                    "Claimed progress without Phase B mode landing."
                ),
            )
        )

    return findings


def evaluate_verdict_without_structured_mode(
    stats: ResearchStoreModeStats,
    *,
    min_deceptive: int = MIN_VERDICT_WITHOUT_STRUCTURED,
) -> list[IntegrityFinding]:
    """Flag present research_verdict fields while structured modes never landed."""
    if stats.structured > 0:
        return []
    if stats.verdict_without_structured < max(1, int(min_deceptive)):
        return []
    return [
        IntegrityFinding(
            severity="fail",
            check_id="verdict_fields_without_structured_mode",
            title="Verdict fields present without structured_verdict modes",
            summary=(
                f"{stats.verdict_without_structured}/{stats.sampled} committed memos have "
                f"research_verdict set while mode is still essay/initial "
                f"(structured=0). Looks researched; Phase B producer has not landed."
            ),
        )
    ]


def evaluate_indicator_integrity(
    *,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
    now: datetime | None = None,
    lookback_days: int = RECEIPT_LOOKBACK_DAYS,
    min_verdict_without_structured: int = MIN_VERDICT_WITHOUT_STRUCTURED,
) -> list[IntegrityFinding]:
    """Run the L389 claimed-vs-landed suite."""
    stats = count_research_store_modes(research_root)
    receipt = load_research_docs_receipt(receipt_path)
    findings: list[IntegrityFinding] = []
    findings.extend(
        evaluate_research_docs_receipt(
            receipt,
            live_stats=stats,
            now=now,
            lookback_days=lookback_days,
        )
    )
    findings.extend(
        evaluate_verdict_without_structured_mode(
            stats,
            min_deceptive=min_verdict_without_structured,
        )
    )
    return findings
