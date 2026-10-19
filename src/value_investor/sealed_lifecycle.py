"""Display-only lifecycle chips for the four sealed observe books.

One page per ``sealed_observe_only`` registration (N200, N201, N206, N210).
Phases use the lifecycle board clocks (``JUST_BOUGHT_DAYS`` / ``JUST_SOLD_DAYS``,
both 14). Time in phase is the existing column clock: days since entry on
open phases, days since exit on sold phases. Chip percent is the episode
fair-cost return, or a mark already stored on an open row. It is never the
cohort median and never the sample-mean strip.

Does not promote, retune, or write a seal. ``influences_live`` stays false.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.lifecycle_board import (
    JUST_BOUGHT_DAYS,
    JUST_SOLD_DAYS,
    _days_since,
    _parse_dt,
    close_in_window,
)

SCHEMA_VERSION = 1
DEFAULT_PROJECTION_NAME = "sealed_lifecycle.json"

PHASE_IDS = ("just_bought", "holding", "just_sold", "post_sale")
PHASE_LABELS = {
    "just_bought": "Just bought",
    "holding": "Holding",
    "just_sold": "Just sold",
    "post_sale": "Post sale",
}

# Closed fair-cost episode return. First hit wins. Stress, patient-hold, and
# cohort-median keys are intentionally absent.
_CLOSED_RETURN_KEYS = ("fair_cost_return", "return_pct", "control_return")
# Marks already stored on an open observe row. Do not invent a price.
_OPEN_MARK_KEYS = (
    "open_mark_return",
    "mark_return_pct",
    "unrealized_return_pct",
    "unrealized_pnl_pct",
)

SEALED_MODELS: tuple[dict[str, str], ...] = (
    {
        "model_id": "n200",
        "label": "N200",
        "title": "Plain value tech timing",
        "registration_id": "strand-b-plain-value-tech-timing-v0",
        "store_name": "n200_tech_timing_observe.json",
        "registration_name": "n200_tech_timing_registration.json",
    },
    {
        "model_id": "n201",
        "label": "N201",
        "title": "Short-horizon value and momentum",
        "registration_id": "strand-c-short-horizon-value-mom-v0",
        "store_name": "n201_value_mom_observe.json",
        "registration_name": "n201_value_mom_registration.json",
    },
    {
        "model_id": "n206",
        "label": "N206",
        "title": "Patient plain earnings yield",
        "registration_id": "strand-d-plain-ey-identity-v0",
        "store_name": "n206_plain_ey_observe.json",
        "registration_name": "n206_plain_ey_registration.json",
    },
    {
        "model_id": "n210",
        "label": "N210",
        "title": "AI judgment fixed stake",
        "registration_id": "strand-e-ai-judgment-fixed-stake-v0",
        "store_name": "n210_ai_judgment_observe.json",
        "registration_name": "n210_ai_judgment_registration.json",
    },
)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _optional_float(row.get(key))
        if value is not None:
            return value
    return None


def slim_lifecycle_episode(episode: dict[str, Any]) -> dict[str, Any] | None:
    """Keep ticker, dates, and the one return a chip is allowed to show."""
    if not isinstance(episode, dict):
        return None
    ticker = str(episode.get("ticker") or "").strip()
    if not ticker:
        return None
    exit_at = episode.get("exit_run_at") or None
    status = str(episode.get("status") or "").strip().lower()
    if status not in {"open", "closed"}:
        status = "closed" if exit_at else "open"
    if status == "open":
        exit_at = None
    row: dict[str, Any] = {
        "ticker": ticker,
        "entry_run_at": episode.get("entry_run_at") or None,
        "exit_run_at": exit_at,
        "status": status,
    }
    if status == "closed":
        fair = _first_float(episode, _CLOSED_RETURN_KEYS)
        if fair is not None:
            row["fair_cost_return"] = fair
    else:
        mark = _first_float(episode, _OPEN_MARK_KEYS)
        if mark is not None:
            row["open_mark_return"] = mark
    return row


def slim_lifecycle_episodes(episodes: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        slim = slim_lifecycle_episode(episode) if isinstance(episode, dict) else None
        if slim is not None:
            rows.append(slim)
    return rows


def chip_return(row: dict[str, Any]) -> tuple[float | None, str]:
    """Episode fair-cost return, or a stored open mark. Never a cohort median."""
    status = str(row.get("status") or "").strip().lower()
    if status == "open" or not row.get("exit_run_at"):
        mark = _optional_float(row.get("open_mark_return"))
        if mark is None:
            mark = _first_float(row, _OPEN_MARK_KEYS)
        if mark is None:
            return None, "open_unmarked"
        return mark, "open_mark"
    fair = _optional_float(row.get("fair_cost_return"))
    if fair is None:
        fair = _first_float(row, _CLOSED_RETURN_KEYS)
    if fair is None:
        return None, "closed_missing_return"
    return fair, "fair_cost_episode"


def assign_sealed_phase(
    row: dict[str, Any],
    *,
    now: datetime,
    just_bought_days: int = JUST_BOUGHT_DAYS,
    just_sold_days: int = JUST_SOLD_DAYS,
) -> dict[str, Any] | None:
    """Place one episode. Missing ticker or clock date skips the chip."""
    ticker = str(row.get("ticker") or "").strip()
    if not ticker:
        return None
    status = str(row.get("status") or "").strip().lower()
    exit_raw = row.get("exit_run_at")
    entry_raw = row.get("entry_run_at")
    open_row = status == "open" or (status != "closed" and not exit_raw)
    if open_row:
        if _parse_dt(str(entry_raw) if entry_raw else None) is None:
            return None
        opened_days = _days_since(str(entry_raw), now)
        if opened_days is None:
            return None
        phase = "just_bought" if opened_days <= just_bought_days else "holding"
        days = int(max(0.0, opened_days))
        clock = "entry_run_at"
    else:
        if _parse_dt(str(exit_raw) if exit_raw else None) is None:
            return None
        sold_days = _days_since(str(exit_raw), now)
        if sold_days is None:
            return None
        phase = "just_sold" if sold_days <= just_sold_days else "post_sale"
        days = int(max(0.0, sold_days))
        clock = "exit_run_at"
    ret, basis = chip_return(row)
    chip: dict[str, Any] = {
        "ticker": ticker,
        "phase": phase,
        "days_in_phase": days,
        "phase_clock": clock,
        "return_pct": ret,
        "return_basis": basis,
        "status": "open" if open_row else "closed",
        "entry_run_at": entry_raw or None,
        "exit_run_at": None if open_row else exit_raw,
    }
    window = close_in_window(
        str(entry_raw) if entry_raw else None,
        None if open_row else (str(exit_raw) if exit_raw else None),
        before_days=just_bought_days,
        after_days=just_sold_days,
    )
    if window:
        chip["close_in"] = window
    return chip


def _source_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    stored = payload.get("lifecycle_episodes")
    if isinstance(stored, list) and stored:
        return [row for row in stored if isinstance(row, dict)]
    rows: list[dict[str, Any]] = []
    for key in ("episodes_sample", "open_episodes_sample", "open_episodes"):
        block = payload.get(key)
        if isinstance(block, list):
            rows.extend(item for item in block if isinstance(item, dict))
    return slim_lifecycle_episodes(rows)


def _cohort_median(payload: dict[str, Any]) -> float | None:
    path = payload.get("path_scoreboard")
    if not isinstance(path, dict):
        return None
    if path.get("smooth_ret_cohort_median") is not None:
        return _optional_float(path.get("smooth_ret_cohort_median"))
    return _optional_float(path.get("control_smooth_ret_cohort_median"))


def _as_of(payload: dict[str, Any], now: datetime | None) -> datetime:
    if now is not None:
        as_of = now if now.tzinfo else now.replace(tzinfo=UTC)
        return as_of.astimezone(UTC)
    parsed = _parse_dt(str(payload.get("generated_at") or ""))
    return parsed or datetime.now(UTC)


def build_model_lifecycle(
    payload: dict[str, Any],
    *,
    model_id: str,
    label: str,
    title: str,
    registration_id: str,
    now: datetime | None = None,
    just_bought_days: int = JUST_BOUGHT_DAYS,
    just_sold_days: int = JUST_SOLD_DAYS,
) -> dict[str, Any]:
    as_of = _as_of(payload, now)
    columns: dict[str, list[dict[str, Any]]] = {phase: [] for phase in PHASE_IDS}
    for raw in _source_rows(payload):
        chip = assign_sealed_phase(
            raw,
            now=as_of,
            just_bought_days=just_bought_days,
            just_sold_days=just_sold_days,
        )
        if chip is None or not chip.get("ticker"):
            continue
        columns[str(chip["phase"])].append(chip)
    for phase in PHASE_IDS:
        columns[phase].sort(
            key=lambda chip: (
                str(chip.get("ticker") or ""),
                str(chip.get("entry_run_at") or ""),
                str(chip.get("exit_run_at") or ""),
            )
        )
    packed = {
        phase: {
            "id": phase,
            "label": PHASE_LABELS[phase],
            "count": len(columns[phase]),
            "chips": columns[phase],
        }
        for phase in PHASE_IDS
    }
    return {
        "model_id": model_id,
        "label": label,
        "title": title,
        "registration_id": registration_id,
        "observe_only": True,
        "influences_live": False,
        "generated_at": payload.get("generated_at"),
        "as_of": as_of.isoformat(),
        "cohort_median": _cohort_median(payload),
        "cohort_median_role": "page_context_not_chip",
        "chip_count": sum(len(columns[phase]) for phase in PHASE_IDS),
        "columns": packed,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _registration_ok(reg: dict[str, Any] | None, registration_id: str) -> bool:
    if not isinstance(reg, dict):
        return False
    if str(reg.get("status") or "") != "sealed_observe_only":
        return False
    return str(reg.get("registration_id") or "") == registration_id


def build_sealed_lifecycle_projection(
    data_dir: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read the four observe stores and registrations. Display projection only."""
    root = Path(data_dir)
    models: list[dict[str, Any]] = []
    for spec in SEALED_MODELS:
        reg = _read_json(root / spec["registration_name"])
        if not _registration_ok(reg, spec["registration_id"]):
            continue
        payload = _read_json(root / spec["store_name"]) or {}
        if (
            str(payload.get("registration_id") or spec["registration_id"])
            != spec["registration_id"]
        ):
            continue
        models.append(
            build_model_lifecycle(
                payload,
                model_id=spec["model_id"],
                label=spec["label"],
                title=spec["title"],
                registration_id=spec["registration_id"],
                now=now,
            )
        )
    generated = datetime.now(UTC).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "observe_only": True,
        "influences_live": False,
        "generated_at": generated,
        "just_bought_days": JUST_BOUGHT_DAYS,
        "just_sold_days": JUST_SOLD_DAYS,
        "phase_ids": list(PHASE_IDS),
        "note": (
            "Display only. One line per episode: ticker, days in the current "
            "lifecycle column, and that episode's fair-cost return (closed) or "
            "a mark already stored on the open row. Not the cohort median and "
            "not the sample-mean strip. influences_live stays false."
        ),
        "models": models,
    }


def publish_sealed_lifecycle_projection(
    data_dir: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write ``sealed_lifecycle.json`` beside the observe stores."""
    root = Path(data_dir)
    payload = build_sealed_lifecycle_projection(root, now=now)
    path = root / DEFAULT_PROJECTION_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
