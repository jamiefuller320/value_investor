"""Gated universe filing archive pack run + post-run bottleneck review.

Minimum runnable lane under ``archive_lane_gate``:

- Quiet window + focus-pressure suspend (fail-open exit 0)
- Week-first then iterative-backward pack plan (no fourth sprint stream)
- Dry assemble by default; ``--apply`` runs the thin quiet cold-store writer
  pilot (tiny max_units, archive budgets only — not a fourth equal sprint)
- Post-run bottleneck review artifact for pipeline tuning (no eng-spray)

Artifacts:

- ``docs/data/universe_filing_archive_pack_run.json`` — last run summary
- ``docs/data/universe_filing_archive_bottleneck_review.json`` — stage timings /
  throughput / errors by market (and source when fetches exist)
- Cold packs under ``docs/data/archive/universe_filings/`` (apply only; not
  committed by the weekday workflow)
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json
from value_investor.universe_filing_archive_hydrate import DEFAULT_COLD_ROOT
from value_investor.universe_filing_archive_isolation import (
    ARCHIVE_LANE_BUDGET_ID,
    DEFAULT_DISPATCH_PATH,
    DEFAULT_MARKET_STATUS_PATH,
    archive_lane_gate,
)
from value_investor.universe_filing_archive_pack_order import (
    DEFAULT_LOOKBACK_WEEKS,
    PACK_ORDER_ID,
    build_week_first_pack_plan,
    summarize_plan_by_week,
)
from value_investor.universe_filing_archive_writer import (
    DEFAULT_APPLY_MAX_UNITS,
    DEFAULT_LIBRARY_ROOT,
    DEFAULT_MAX_BODIES_PER_TICKER,
    DEFAULT_MAX_HTTP_FETCHES,
    DEFAULT_MAX_TICKERS_PER_UNIT,
    assemble_archive_pack_units,
)

SCHEMA_VERSION = 1
DEFAULT_PACK_RUN_PATH = Path("docs/data/universe_filing_archive_pack_run.json")
DEFAULT_BOTTLENECK_PATH = Path("docs/data/universe_filing_archive_bottleneck_review.json")
DEFAULT_POLICY_PATH = Path("docs/data/library/policy.json")
LIVE_SCREEN_MARKET = "ftse350"

FINDING_TITLE_STALE = "Universe archive pack bottleneck review stale"
FINDING_TITLE_BOTTLENECK = "Universe archive pack processing bottleneck"

# Weekday cron is 22:00 UTC; allow one miss before warn.
DEFAULT_STALE_AFTER_HOURS = 36.0
# Observe-only warn when one stage dominates wall time on an allowed dry pass.
DEFAULT_DOMINANT_STAGE_SHARE = 0.6


def _now() -> datetime:
    return datetime.now(UTC)


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _safe_read(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class _StageTimer:
    def __init__(self, stage_id: str) -> None:
        self.stage_id = stage_id
        self.status = "pending"
        self.detail: dict[str, Any] = {}
        self.error: str | None = None
        self._t0 = 0.0
        self.elapsed_ms = 0

    def start(self) -> None:
        self._t0 = time.perf_counter()
        self.status = "running"

    def finish(self, status: str = "ok", **detail: Any) -> dict[str, Any]:
        self.elapsed_ms = int(round((time.perf_counter() - self._t0) * 1000))
        self.status = status
        if detail:
            self.detail.update(detail)
        return self.to_dict()

    def skip(self, reason: str, **detail: Any) -> dict[str, Any]:
        self.elapsed_ms = 0
        self.status = "skipped"
        self.detail = {"reason": reason, **detail}
        return self.to_dict()

    def fail(self, exc: BaseException, **detail: Any) -> dict[str, Any]:
        self.elapsed_ms = int(round((time.perf_counter() - self._t0) * 1000))
        self.status = "error"
        self.error = str(exc)
        self.detail = detail
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": self.stage_id,
            "elapsed_ms": self.elapsed_ms,
            "status": self.status,
            "detail": dict(self.detail),
        }
        if self.error:
            row["error"] = self.error
        return row


def resolve_archive_market_roster(
    *,
    market_status_path: Path = DEFAULT_MARKET_STATUS_PATH,
    policy_path: Path = DEFAULT_POLICY_PATH,
    market_status: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    include_live_screen: bool = True,
) -> list[str]:
    """Admitted learning markets (+ live FTSE screen) for archive broad surface."""
    status = market_status if market_status is not None else _safe_read(Path(market_status_path))
    pol = policy if policy is not None else _safe_read(Path(policy_path))
    roster: list[str] = []
    if include_live_screen:
        roster.append(LIVE_SCREEN_MARKET)
    admitted = _as_list(status.get("admitted_markets"))
    if not admitted:
        admitted = _as_list(pol.get("ftse_equivalent_markets")) + _as_list(pol.get("market_queue"))
        focus = str(pol.get("focus_market") or "").strip()
        if focus:
            admitted = [focus, *admitted]
    for mid in admitted:
        text = str(mid or "").strip()
        if text and text not in roster:
            roster.append(text)
    return roster


def _empty_by_source() -> dict[str, Any]:
    return {
        "sec": {"attempts": 0, "errors": 0, "elapsed_ms": 0},
        "companies_house": {"attempts": 0, "errors": 0, "elapsed_ms": 0},
        "esef": {"attempts": 0, "errors": 0, "elapsed_ms": 0},
        "news": {"attempts": 0, "errors": 0, "elapsed_ms": 0},
        "ir_pdf": {"attempts": 0, "errors": 0, "elapsed_ms": 0},
        "yahoo": {"attempts": 0, "errors": 0, "elapsed_ms": 0},
    }


def _by_market_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, dict[str, Any]] = {}
    for unit in _as_list(plan.get("units")):
        if not isinstance(unit, dict):
            continue
        mid = str(unit.get("market_id") or "").strip()
        if not mid:
            continue
        row = counts.setdefault(
            mid,
            {
                "units_planned": 0,
                "units_attempted": 0,
                "units_completed": 0,
                "errors": 0,
                "elapsed_ms": 0,
            },
        )
        row["units_planned"] = int(row["units_planned"]) + 1
    return counts


def build_bottleneck_review(
    *,
    run_id: str,
    generated_at: datetime,
    outcome: str,
    gate: dict[str, Any],
    plan: dict[str, Any] | None,
    stages: list[dict[str, Any]],
    dry_run: bool,
    errors: list[str] | None = None,
    by_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the observe-only post-run bottleneck review payload."""
    plan = plan or {}
    stage_rows = list(stages)
    total_ms = sum(int(s.get("elapsed_ms") or 0) for s in stage_rows)
    dominant = None
    dominant_share = 0.0
    timed = [s for s in stage_rows if int(s.get("elapsed_ms") or 0) > 0]
    if timed and total_ms > 0:
        dominant = max(timed, key=lambda s: int(s.get("elapsed_ms") or 0))
        dominant_share = round(int(dominant.get("elapsed_ms") or 0) / total_ms, 4)

    bottlenecks: list[dict[str, Any]] = []
    if outcome in {"suspend", "quiet_only"}:
        reasons = _as_list(gate.get("focus_pressure_reasons"))
        bottlenecks.append(
            {
                "kind": "gate_block",
                "stage": "gate",
                "summary": (
                    f"Lane {outcome}: "
                    + (
                        ", ".join(str(r) for r in reasons)
                        if reasons
                        else str(gate.get("decision") or outcome)
                    )
                ),
            }
        )
    if (
        dominant
        and dominant_share >= DEFAULT_DOMINANT_STAGE_SHARE
        and outcome
        in {
            "dry_complete",
            "apply_complete",
        }
    ):
        bottlenecks.append(
            {
                "kind": "dominant_stage",
                "stage": dominant.get("id"),
                "share": dominant_share,
                "elapsed_ms": dominant.get("elapsed_ms"),
                "summary": (
                    f"Stage {dominant.get('id')} used {dominant_share:.0%} of "
                    f"pass wall time ({dominant.get('elapsed_ms')} ms)"
                ),
            }
        )
    for err in errors or []:
        bottlenecks.append({"kind": "error", "summary": err})

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "run_id": run_id,
        "lane": ARCHIVE_LANE_BUDGET_ID,
        "pack_order": PACK_ORDER_ID,
        "outcome": outcome,
        "dry_run": dry_run,
        "observe_only": True,  # bottleneck never eng-sprays (N181)
        "auto_rewrite_deepen": False,
        "gate": {
            "decision": gate.get("decision"),
            "allowed": gate.get("allowed"),
            "in_quiet_window": gate.get("in_quiet_window"),
            "focus_pressure_reasons": list(gate.get("focus_pressure_reasons") or []),
            "focus_market": gate.get("focus_market"),
            "ingest_sprint_complete": gate.get("ingest_sprint_complete"),
        },
        "stages": stage_rows,
        "by_week": summarize_plan_by_week(plan) if plan.get("units") else [],
        "by_market": _by_market_from_plan(plan),
        "by_source": by_source if by_source is not None else _empty_by_source(),
        "throughput": {
            "units_planned": int(plan.get("unit_count") or 0),
            "units_attempted": 0,
            "units_completed": 0,
            "errors": len(errors or []),
            "total_elapsed_ms": total_ms,
        },
        "dominant_stage": (
            {
                "id": (dominant or {}).get("id"),
                "elapsed_ms": (dominant or {}).get("elapsed_ms"),
                "share": dominant_share,
            }
            if dominant
            else None
        ),
        "bottlenecks": bottlenecks,
        "errors": list(errors or []),
        "note": (
            "Post-run bottleneck review for archive pack tuning. Observe/report "
            "only — does not auto-rewrite live deepen or steal the fat slot."
        ),
    }


def format_bottleneck_review_summary(payload: dict[str, Any]) -> str:
    """Human-readable CLI summary of the bottleneck review."""
    outcome = str(payload.get("outcome") or "")
    throughput = _as_dict(payload.get("throughput"))
    gate = _as_dict(payload.get("gate"))
    lines = [
        f"Archive pack run outcome: {outcome}",
        f"Pack order: {payload.get('pack_order') or PACK_ORDER_ID}",
        f"Dry run: {bool(payload.get('dry_run', True))}",
        (
            f"Gate: decision={gate.get('decision')} allowed={gate.get('allowed')} "
            f"quiet={gate.get('in_quiet_window')} focus={gate.get('focus_market')}"
        ),
        (
            f"Throughput: planned={throughput.get('units_planned')} "
            f"attempted={throughput.get('units_attempted')} "
            f"completed={throughput.get('units_completed')} "
            f"errors={throughput.get('errors')} "
            f"total_ms={throughput.get('total_elapsed_ms')}"
        ),
    ]
    dominant = _as_dict(payload.get("dominant_stage"))
    if dominant.get("id"):
        lines.append(
            f"Dominant stage: {dominant.get('id')} "
            f"({dominant.get('elapsed_ms')} ms, share={dominant.get('share')})"
        )
    for stage in _as_list(payload.get("stages")):
        if not isinstance(stage, dict):
            continue
        lines.append(
            f"  stage {stage.get('id')}: {stage.get('status')} {stage.get('elapsed_ms')} ms"
        )
    for bn in _as_list(payload.get("bottlenecks")):
        if isinstance(bn, dict) and bn.get("summary"):
            lines.append(f"Bottleneck: {bn.get('summary')}")
    return "\n".join(lines)


def ops_finding_from_bottleneck_review(
    payload: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
) -> dict[str, Any] | None:
    """Observe-only finding from bottleneck review (no eng spray / deepen)."""
    clock = now or _now()
    if not payload:
        return {
            "severity": "warn",
            "category": "ingest",
            "title": FINDING_TITLE_STALE,
            "summary": (
                "Universe archive pack bottleneck review missing — weekday "
                "22:00 UTC lane may not be writing docs/data/"
                "universe_filing_archive_bottleneck_review.json."
            ),
            "auto_fixable": False,
        }

    generated = _parse_dt(payload.get("generated_at"))
    if generated is None:
        return {
            "severity": "warn",
            "category": "ingest",
            "title": FINDING_TITLE_STALE,
            "summary": "Archive pack bottleneck review lacks generated_at.",
            "auto_fixable": False,
        }
    age_h = (clock - generated).total_seconds() / 3600.0
    if age_h > float(stale_after_hours):
        return {
            "severity": "warn",
            "category": "ingest",
            "title": FINDING_TITLE_STALE,
            "summary": (
                f"Archive pack bottleneck review age {age_h:.1f}h exceeds "
                f"{stale_after_hours:.0f}h (expected weekday 22:00 UTC refresh)."
            ),
            "auto_fixable": False,
        }

    outcome = str(payload.get("outcome") or "")
    # Suspend / quiet_only while euro fat is expected — no warn spam.
    if outcome in {"suspend", "quiet_only"}:
        return None

    dominant = _as_dict(payload.get("dominant_stage"))
    share = float(dominant.get("share") or 0.0)
    if (
        outcome == "dry_complete"
        and dominant.get("id")
        and share >= DEFAULT_DOMINANT_STAGE_SHARE
        and int(dominant.get("elapsed_ms") or 0) >= 500
    ):
        return {
            "severity": "info",
            "category": "ingest",
            "title": FINDING_TITLE_BOTTLENECK,
            "summary": (
                f"Archive pack dry pass dominated by stage "
                f"{dominant.get('id')} ({share:.0%} / {dominant.get('elapsed_ms')} ms). "
                "Observe-only — tune pipeline; do not auto-rewrite deepen."
            ),
            "auto_fixable": False,
        }

    errors = _as_list(payload.get("errors"))
    if errors:
        return {
            "severity": "warn",
            "category": "ingest",
            "title": FINDING_TITLE_BOTTLENECK,
            "summary": (
                f"Archive pack pass recorded {len(errors)} error(s); first={errors[0]!s}"[:400]
            ),
            "auto_fixable": False,
        }
    return None


def _finalize_and_persist(
    *,
    run_id: str,
    clock: datetime,
    outcome: str,
    gate: dict[str, Any],
    plan: dict[str, Any],
    roster: list[str],
    stages: list[dict[str, Any]],
    dry_run: bool,
    errors: list[str],
    lookback_weeks: int,
    pack_run_path: Path,
    bottleneck_path: Path,
    persist: bool,
    assemble: dict[str, Any] | None = None,
    max_units: int | None = None,
) -> dict[str, Any]:
    write_timer = _StageTimer("write_artifacts")
    write_timer.start()
    assemble = assemble or {}
    isolation = (
        assemble.get("capacity_isolation")
        if isinstance(assemble.get("capacity_isolation"), dict)
        else {}
    )
    pack_run = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "run_id": run_id,
        "lane": ARCHIVE_LANE_BUDGET_ID,
        "outcome": outcome,
        "dry_run": dry_run,
        "pack_order": PACK_ORDER_ID,
        "gate": {
            "decision": gate.get("decision"),
            "allowed": gate.get("allowed"),
            "in_quiet_window": gate.get("in_quiet_window"),
            "focus_pressure_reasons": list(gate.get("focus_pressure_reasons") or []),
            "focus_market": gate.get("focus_market"),
            "ingest_sprint_complete": gate.get("ingest_sprint_complete"),
        },
        "markets": list(roster),
        "plan_unit_count": int(plan.get("unit_count") or 0),
        "lookback_weeks": int(plan.get("lookback_weeks") or lookback_weeks),
        "max_units": max_units,
        "fourth_equal_sprint_stream": False,
        "preemptible": True,
        "units_attempted": int(assemble.get("units_attempted") or 0),
        "units_completed": int(assemble.get("units_completed") or 0),
        "objects_written": int(assemble.get("objects_written") or 0),
        "hydrate_hits": int(assemble.get("hydrate_hits") or 0),
        "capacity_isolation": isolation,
        "assemble_caps": assemble.get("caps") or {},
        "bottleneck_review_path": str(bottleneck_path),
        "week_summary": summarize_plan_by_week(plan)[:4] if plan.get("units") else [],
        "note": (
            "Week-first archive pack pass under archive_lane_gate. "
            "Apply uses thin quiet cold-store writers (archive budgets, tiny caps); "
            "not a fourth equal sprint; bottleneck never eng-sprays (N180/N181)."
            if not dry_run
            else (
                "Week-first archive pack dry pass under archive_lane_gate. "
                "Use --apply for thin quiet cold-store writers."
            )
        ),
    }
    try:
        if persist:
            # Placeholder — final bottleneck written after stage list is complete.
            write_json(Path(pack_run_path), pack_run)
        stages.append(
            write_timer.finish(
                "ok",
                pack_run_path=str(pack_run_path),
                bottleneck_path=str(bottleneck_path),
                persisted=persist,
            )
        )
    except Exception as exc:  # noqa: BLE001 — fail-open for cron
        stages.append(write_timer.fail(exc))
        errors.append(f"write_artifacts: {exc}")
        outcome = "error"
        pack_run["outcome"] = outcome

    bn_timer = _StageTimer("bottleneck_review")
    bn_timer.start()
    by_source = assemble.get("by_source") if isinstance(assemble.get("by_source"), dict) else None
    review = build_bottleneck_review(
        run_id=run_id,
        generated_at=clock,
        outcome=outcome,
        gate=gate,
        plan=plan,
        stages=stages,
        dry_run=dry_run,
        errors=errors,
        by_source=by_source,
    )
    review["throughput"]["units_attempted"] = int(assemble.get("units_attempted") or 0)
    review["throughput"]["units_completed"] = int(assemble.get("units_completed") or 0)
    review["throughput"]["objects_written"] = int(assemble.get("objects_written") or 0)
    if isolation:
        review["capacity_isolation"] = isolation
    bn_row = bn_timer.finish("ok", bottlenecks=len(review.get("bottlenecks") or []))
    stages.append(bn_row)
    review["stages"] = list(stages)
    review["throughput"]["total_elapsed_ms"] = sum(int(s.get("elapsed_ms") or 0) for s in stages)
    pack_run["outcome"] = outcome
    status_payload: dict[str, Any] | None = None
    if persist:
        write_json(Path(pack_run_path), pack_run)
        write_json(Path(bottleneck_path), review)
        try:
            from value_investor.universe_filing_archive_status import (
                write_universe_filing_archive_status,
            )

            status_payload = write_universe_filing_archive_status(
                pack_run=pack_run,
                bottleneck=review,
                pack_run_path=Path(pack_run_path),
                bottleneck_path=Path(bottleneck_path),
                status_path=Path(pack_run_path).parent / "universe_filing_archive_status.json",
                now=clock,
            )
        except Exception:  # noqa: BLE001 — status panel must not fail the lane
            status_payload = None

    exit_code = 0 if outcome != "error" else 1
    return {
        "pack_run": pack_run,
        "bottleneck_review": review,
        "status": status_payload,
        "exit_code": exit_code,
        "assemble": assemble,
    }


def run_universe_filing_archive_pack(
    *,
    now: datetime | None = None,
    dry_run: bool = True,
    require_quiet_window: bool = True,
    allow_outside_quiet_for_pilot: bool = False,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
    max_units: int | None = None,
    dispatch_path: Path = DEFAULT_DISPATCH_PATH,
    market_status_path: Path = DEFAULT_MARKET_STATUS_PATH,
    policy_path: Path = DEFAULT_POLICY_PATH,
    pack_run_path: Path = DEFAULT_PACK_RUN_PATH,
    bottleneck_path: Path = DEFAULT_BOTTLENECK_PATH,
    cold_root: Path = DEFAULT_COLD_ROOT,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    max_tickers_per_unit: int = DEFAULT_MAX_TICKERS_PER_UNIT,
    max_bodies_per_ticker: int = DEFAULT_MAX_BODIES_PER_TICKER,
    max_http_fetches: int = DEFAULT_MAX_HTTP_FETCHES,
    persist: bool = True,
    force_allow_for_test: bool = False,
    discover_fn: Any | None = None,
    body_fetch_fn: Any | None = None,
) -> dict[str, Any]:
    """Execute one gated archive pack pass (dry by default) + bottleneck review.

    Always fail-open for cron: suspend / quiet_only outcomes still exit success
    at the CLI layer and still write the bottleneck review.

    When ``dry_run=False``, runs the thin quiet writer pilot with archive-only
    budgets and tiny caps (default ``max_units`` = ``DEFAULT_APPLY_MAX_UNITS``).
    """
    clock = now or _now()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    else:
        clock = clock.astimezone(UTC)

    effective_max_units = max_units
    if not dry_run and effective_max_units is None:
        effective_max_units = DEFAULT_APPLY_MAX_UNITS

    run_id = f"uap-{clock.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    stages: list[dict[str, Any]] = []
    errors: list[str] = []
    plan: dict[str, Any] = {}
    roster: list[str] = []
    assemble: dict[str, Any] = {}

    gate_timer = _StageTimer("gate")
    gate_timer.start()
    try:
        if force_allow_for_test:
            gate: dict[str, Any] = {
                "decision": "allow",
                "allowed": True,
                "in_quiet_window": True,
                "focus_pressure_reasons": [],
                "focus_market": "test",
                "ingest_sprint_complete": True,
                "preemptible": True,
                "fourth_equal_sprint_stream": False,
            }
        else:
            gate = archive_lane_gate(
                now=clock,
                dispatch_path=Path(dispatch_path),
                market_status_path=Path(market_status_path),
                require_quiet_window=require_quiet_window,
                allow_outside_quiet_for_pilot=allow_outside_quiet_for_pilot,
            )
        stages.append(
            gate_timer.finish(
                "ok",
                decision=gate.get("decision"),
                allowed=bool(gate.get("allowed")),
            )
        )
    except Exception as exc:  # noqa: BLE001 — fail-open lane
        stages.append(gate_timer.fail(exc))
        errors.append(f"gate: {exc}")
        gate = {
            "decision": "suspend",
            "allowed": False,
            "focus_pressure_reasons": ["gate_exception"],
            "in_quiet_window": False,
        }

    allowed = bool(gate.get("allowed"))
    decision = str(gate.get("decision") or "")

    if not allowed:
        outcome = "suspend" if decision == "suspend" else "quiet_only"
        stages.append(_StageTimer("roster").skip(outcome))
        stages.append(_StageTimer("pack_plan").skip(outcome))
        stages.append(_StageTimer("assemble_dry" if dry_run else "assemble").skip(outcome))
        return _finalize_and_persist(
            run_id=run_id,
            clock=clock,
            outcome=outcome,
            gate=gate,
            plan={},
            roster=[],
            stages=stages,
            dry_run=dry_run,
            errors=errors,
            lookback_weeks=lookback_weeks,
            pack_run_path=Path(pack_run_path),
            bottleneck_path=Path(bottleneck_path),
            persist=persist,
            max_units=effective_max_units,
        )

    roster_timer = _StageTimer("roster")
    roster_timer.start()
    try:
        roster = resolve_archive_market_roster(
            market_status_path=Path(market_status_path),
            policy_path=Path(policy_path),
        )
        stages.append(roster_timer.finish("ok", market_count=len(roster)))
    except Exception as exc:  # noqa: BLE001
        stages.append(roster_timer.fail(exc))
        errors.append(f"roster: {exc}")
        roster = []

    plan_timer = _StageTimer("pack_plan")
    plan_timer.start()
    try:
        plan = build_week_first_pack_plan(
            roster,
            as_of=clock,
            lookback_weeks=lookback_weeks,
            max_units=effective_max_units,
        )
        stages.append(
            plan_timer.finish(
                "ok",
                unit_count=int(plan.get("unit_count") or 0),
                lookback_weeks=int(plan.get("lookback_weeks") or lookback_weeks),
                pack_order=PACK_ORDER_ID,
                max_units=effective_max_units,
            )
        )
    except Exception as exc:  # noqa: BLE001
        stages.append(plan_timer.fail(exc))
        errors.append(f"pack_plan: {exc}")
        plan = {}

    stage_name = "assemble_dry" if dry_run else "assemble"
    assemble_timer = _StageTimer(stage_name)
    assemble_timer.start()
    try:
        if dry_run:
            assemble = {
                "mode": "dry",
                "units_planned": int(plan.get("unit_count") or 0),
                "units_attempted": 0,
                "units_completed": 0,
                "objects_written": 0,
                "capacity_isolation": {
                    "lane_budget": ARCHIVE_LANE_BUDGET_ID,
                    "source_budgets_used": [],
                    "http_fetches": 0,
                    "shared_critical_path": False,
                    "isolation_ok": True,
                    "preemptible": True,
                    "fourth_equal_sprint_stream": False,
                },
            }
            stages.append(
                assemble_timer.finish(
                    "ok",
                    mode="dry",
                    units_planned=int(plan.get("unit_count") or 0),
                    units_fetched=0,
                    note="Dry assemble — plan only; no source fetches",
                )
            )
        else:
            assemble = assemble_archive_pack_units(
                plan,
                cold_root=Path(cold_root),
                library_root=Path(library_root),
                max_tickers_per_unit=int(max_tickers_per_unit),
                max_bodies_per_ticker=int(max_bodies_per_ticker),
                max_http_fetches=int(max_http_fetches),
                discover_fn=discover_fn,
                body_fetch_fn=body_fetch_fn,
            )
            for err in assemble.get("errors") or []:
                errors.append(str(err))
            stages.append(
                assemble_timer.finish(
                    "ok",
                    mode="apply",
                    units_planned=int(assemble.get("units_planned") or 0),
                    units_attempted=int(assemble.get("units_attempted") or 0),
                    units_completed=int(assemble.get("units_completed") or 0),
                    objects_written=int(assemble.get("objects_written") or 0),
                    http_fetches=int(
                        (assemble.get("capacity_isolation") or {}).get("http_fetches") or 0
                    ),
                    isolation_ok=bool(
                        (assemble.get("capacity_isolation") or {}).get("isolation_ok")
                    ),
                    note=str(assemble.get("note") or "Thin quiet cold-store assemble"),
                )
            )
    except Exception as exc:  # noqa: BLE001
        stages.append(assemble_timer.fail(exc))
        errors.append(f"assemble: {exc}")

    if errors and not dry_run and int(assemble.get("units_completed") or 0) == 0:
        outcome = "error"
    elif dry_run:
        outcome = "error" if errors else "dry_complete"
    else:
        outcome = "apply_complete"

    return _finalize_and_persist(
        run_id=run_id,
        clock=clock,
        outcome=outcome,
        gate=gate,
        plan=plan,
        roster=roster,
        stages=stages,
        dry_run=dry_run,
        errors=errors,
        lookback_weeks=lookback_weeks,
        pack_run_path=Path(pack_run_path),
        bottleneck_path=Path(bottleneck_path),
        persist=persist,
        assemble=assemble,
        max_units=effective_max_units,
    )


__all__ = [
    "DEFAULT_BOTTLENECK_PATH",
    "DEFAULT_DOMINANT_STAGE_SHARE",
    "DEFAULT_LOOKBACK_WEEKS",
    "DEFAULT_PACK_RUN_PATH",
    "DEFAULT_POLICY_PATH",
    "DEFAULT_STALE_AFTER_HOURS",
    "FINDING_TITLE_BOTTLENECK",
    "FINDING_TITLE_STALE",
    "LIVE_SCREEN_MARKET",
    "SCHEMA_VERSION",
    "build_bottleneck_review",
    "format_bottleneck_review_summary",
    "ops_finding_from_bottleneck_review",
    "resolve_archive_market_roster",
    "run_universe_filing_archive_pack",
]
