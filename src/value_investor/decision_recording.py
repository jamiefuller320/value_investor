"""Decision-time recording checklist (L386) and observe-only freeze preview.

Locks the four anticipation questions for model-dev / counterfactual work:

1. unit of analysis
2. must freeze at decision time t
3. may join later
4. must never backfill into t

Does **not** enable the Phase C autopsy freeze writer — that stays gated on
``ftse-phase-c-readiness`` exit 0.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

SCHEMA_VERSION = 1

PRIMARY_UNIT_OF_ANALYSIS = (
    "One ticker on one AI-judgment rebalance day — key (logged_at, ticker)."
)

PRIMARY_FREEZE_AT_T: tuple[str, ...] = (
    "logged_at",
    "track_id",
    "schema_version",
    "screen_source",
    "knob_epoch_started_at",
    "gate",
    "selection",
    "acted",
    "plan",
    "trades",
    "slim_candidate.ticker",
    "slim_candidate.name",
    "slim_candidate.signal",
    "slim_candidate.adjusted_signal",
    "slim_candidate.conviction_score",
    "slim_candidate.data_quality_score",
    "slim_candidate.timing_signal",
    "slim_candidate.sector",
    "slim_candidate.price",
    "slim_candidate.research_verdict",
    "membership.in_screen_buy_tier",
    "membership.in_candidates",
    "membership.in_gate_excluded",
    "membership.in_holdings_before",
    "autopsy_freeze.research_revision_id",
    "autopsy_freeze.research_as_of",
    "autopsy_freeze.sources_as_of",
    "autopsy_freeze.research_verdict_structured",
    "autopsy_freeze.research_confidence",
    "autopsy_freeze.research_risk_level",
    "autopsy_freeze.research_rationale_short",
    "autopsy_freeze.feature_flags.filings_with_body",
    "autopsy_freeze.feature_flags.fcf_basis_bound",
    "autopsy_freeze.feature_flags.eps_overlay_bound",
    "autopsy_freeze.feature_flags.overlay_bound",
    "autopsy_freeze.taken_action",
)

PRIMARY_JOIN_LATER: tuple[str, ...] = (
    "full_memo_sections_via_revision_id",
    "raw_filing_body_text",
    "forward_prices_and_fund_marks_1w_4w_8w_12w",
    "archive_signal_fields_weekly_slim",
)

PRIMARY_NEVER_BACKFILL: tuple[str, ...] = (
    "filing_bodies_fetched_after_logged_at",
    "fcf_or_eps_overlays_bound_only_on_later_report",
    "archive_only_numerics_absent_from_live_report_at_t",
    "post_hoc_would_have_known_labels",
)

LOG_TOP_FIELDS: tuple[str, ...] = (
    "logged_at",
    "track_id",
    "schema_version",
    "screen_source",
    "knob_epoch_started_at",
    "gate",
    "selection",
    "acted",
    "plan",
    "trades",
)

CANDIDATE_FIELDS: tuple[str, ...] = (
    "ticker",
    "name",
    "signal",
    "adjusted_signal",
    "conviction_score",
    "data_quality_score",
    "timing_signal",
    "sector",
    "price",
    "research_verdict",
)

AUTOPSY_FREEZE_FIELDS: tuple[str, ...] = (
    "research_revision_id",
    "research_as_of",
    "sources_as_of",
    "research_verdict_structured",
    "research_confidence",
    "research_risk_level",
    "research_rationale_short",
    "taken_action",
)

FEATURE_FLAG_FIELDS: tuple[str, ...] = (
    "filings_with_body",
    "fcf_basis_bound",
    "eps_overlay_bound",
    "overlay_bound",
)

REQUIRED_PLAN_KEYS = (
    "strand_id",
    "unit_of_analysis",
    "freeze_at_t",
    "join_later",
    "never_backfill",
)


@dataclass(frozen=True)
class PrimaryRecordingAnswers:
    """Locked answers for the primary AI-judgment learning track."""

    unit_of_analysis: str = PRIMARY_UNIT_OF_ANALYSIS
    freeze_at_t: tuple[str, ...] = PRIMARY_FREEZE_AT_T
    join_later: tuple[str, ...] = PRIMARY_JOIN_LATER
    never_backfill: tuple[str, ...] = PRIMARY_NEVER_BACKFILL
    consumer: str = "pit_autopsy_phase_c"
    writer_gate: str = "ftse-phase-c-readiness exit 0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "strand_id": "primary_ai_judgment",
            "unit_of_analysis": self.unit_of_analysis,
            "freeze_at_t": list(self.freeze_at_t),
            "join_later": list(self.join_later),
            "never_backfill": list(self.never_backfill),
            "consumer": self.consumer,
            "writer_gate": self.writer_gate,
        }


def primary_recording_answers() -> PrimaryRecordingAnswers:
    return PrimaryRecordingAnswers()


def validate_recording_plan(plan: dict[str, Any]) -> list[str]:
    """Return human-readable errors; empty list means the plan is complete."""
    errors: list[str] = []
    if not isinstance(plan, dict):
        return ["plan must be a JSON object"]

    for key in REQUIRED_PLAN_KEYS:
        if key not in plan:
            errors.append(f"missing required key: {key}")

    if "strand_id" in plan and not str(plan.get("strand_id") or "").strip():
        errors.append("strand_id must be a non-empty string")

    if "unit_of_analysis" in plan and len(str(plan.get("unit_of_analysis") or "").strip()) < 8:
        errors.append("unit_of_analysis must describe the grain (≥8 chars)")

    freeze = plan.get("freeze_at_t")
    if "freeze_at_t" in plan:
        if not isinstance(freeze, list) or not freeze:
            errors.append("freeze_at_t must be a non-empty list")
        else:
            for idx, item in enumerate(freeze):
                if isinstance(item, str):
                    if not item.strip():
                        errors.append(f"freeze_at_t[{idx}] is empty")
                elif isinstance(item, dict):
                    if not str(item.get("field") or "").strip():
                        errors.append(f"freeze_at_t[{idx}].field is required")
                else:
                    errors.append(f"freeze_at_t[{idx}] must be a string or object")

    for list_key in ("join_later", "never_backfill"):
        if list_key not in plan:
            continue
        value = plan.get(list_key)
        if not isinstance(value, list) or not value:
            errors.append(f"{list_key} must be a non-empty list")
        elif any(not str(item).strip() for item in value):
            errors.append(f"{list_key} entries must be non-empty")

    if isinstance(freeze, list) and isinstance(plan.get("never_backfill"), list):
        freeze_names = {
            (item if isinstance(item, str) else str(item.get("field") or "")).strip()
            for item in freeze
        }
        never = {str(item).strip() for item in plan["never_backfill"]}
        overlap = sorted(name for name in freeze_names & never if name)
        if overlap:
            errors.append(
                "fields listed in both freeze_at_t and never_backfill: " + ", ".join(overlap)
            )

    return errors


def load_recording_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("recording plan must be a JSON object")
    return payload


def _coverage(flags: dict[str, bool]) -> dict[str, Any]:
    total = len(flags)
    hit = sum(1 for ok in flags.values() if ok)
    return {
        "present": hit,
        "total": total,
        "ratio": round(hit / total, 4) if total else 0.0,
    }


def _as_ticker_set(values: Any) -> set[str]:
    out: set[str] = set()
    if not isinstance(values, list):
        return out
    for item in values:
        if isinstance(item, dict):
            ticker = item.get("ticker")
            if ticker:
                out.add(str(ticker))
        elif item:
            out.add(str(item))
    return out


def _candidate_rows(entry: dict[str, Any]) -> list[dict[str, Any]]:
    slim = entry.get("slim_candidate")
    if isinstance(slim, dict) and slim.get("ticker"):
        return [slim]
    candidates = entry.get("candidates")
    if isinstance(candidates, list):
        return [row for row in candidates if isinstance(row, dict) and row.get("ticker")]
    return []


def _membership_for(entry: dict[str, Any], ticker: str) -> dict[str, bool]:
    return {
        "in_screen_buy_tier": ticker in _as_ticker_set(entry.get("screen_buy_tier")),
        "in_candidates": ticker in {str(c.get("ticker")) for c in _candidate_rows(entry)},
        "in_gate_excluded": ticker in _as_ticker_set(entry.get("gate_excluded")),
        "in_holdings_before": ticker in _as_ticker_set(entry.get("holdings_before")),
    }


def preview_freeze_for_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Observe-only: which freeze fields are already available on one log entry."""
    top = {name: entry.get(name) is not None for name in LOG_TOP_FIELDS}
    autopsy = entry.get("autopsy_freeze") if isinstance(entry.get("autopsy_freeze"), dict) else {}
    autopsy_fields = {
        name: autopsy.get(name) is not None and autopsy.get(name) != ""
        for name in AUTOPSY_FREEZE_FIELDS
    }
    flags = autopsy.get("feature_flags") if isinstance(autopsy.get("feature_flags"), dict) else {}
    feature_flags = {name: flags.get(name) is not None for name in FEATURE_FLAG_FIELDS}

    tickers: list[dict[str, Any]] = []
    for candidate in _candidate_rows(entry):
        ticker = str(candidate.get("ticker") or "")
        cand_present = {name: candidate.get(name) is not None for name in CANDIDATE_FIELDS}
        tickers.append(
            {
                "ticker": ticker,
                "candidate_fields_present": cand_present,
                "candidate_coverage": _coverage(cand_present),
                "membership": _membership_for(entry, ticker),
            }
        )

    missing = [
        name
        for name, ok in {
            **{f"log.{key}": value for key, value in top.items()},
            **{f"autopsy_freeze.{key}": value for key, value in autopsy_fields.items()},
            **{f"feature_flags.{key}": value for key, value in feature_flags.items()},
        }.items()
        if not ok
    ]
    return {
        "logged_at": entry.get("logged_at"),
        "track_id": entry.get("track_id"),
        "log_top_present": top,
        "autopsy_freeze_present": autopsy_fields,
        "feature_flags_present": feature_flags,
        "tickers": tickers,
        "coverage": {
            "log_top": _coverage(top),
            "autopsy_freeze": _coverage(autopsy_fields),
            "feature_flags": _coverage(feature_flags),
            "ticker_rows": len(tickers),
        },
        "missing_for_phase_c": missing,
        "observe_only": True,
    }


def load_rebalance_log_entries(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict):
        for key in ("entries", "log", "rebalances"):
            rows = raw.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


@dataclass
class FreezePreviewReport:
    rebalance_log: str
    entry_count: int
    assessed_at: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    aggregate_missing: dict[str, int] = field(default_factory=dict)
    note: str = (
        "Observe-only preview. Does not write autopsy_freeze. "
        "Enable Phase C writer only when ftse-phase-c-readiness exits 0."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def preview_freeze_from_rebalance_log(
    path: Path,
    *,
    limit: int | None = None,
) -> FreezePreviewReport:
    entries = load_rebalance_log_entries(path)
    if limit is not None:
        entries = entries[-max(0, int(limit)) :]
    previews = [preview_freeze_for_entry(entry) for entry in entries]
    missing_counts: dict[str, int] = {}
    for preview in previews:
        for name in preview.get("missing_for_phase_c") or []:
            missing_counts[name] = missing_counts.get(name, 0) + 1
    return FreezePreviewReport(
        rebalance_log=str(path),
        entry_count=len(previews),
        assessed_at=datetime.now(timezone.utc).isoformat(),
        entries=previews,
        aggregate_missing=dict(
            sorted(missing_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
    )
