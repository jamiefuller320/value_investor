"""Single assessment model for the paper learning tracks.

One committed file per paper root, ``assessment_model.json``, records:

- ``primary_track`` / ``control_track``: the book judged against the market and
  the book it must beat (switched at an explicit, recorded epoch);
- ``frozen_tracks``: books that stopped trading, with the date, reason, the book
  that supersedes them and their final NAV. A frozen book keeps its files and
  history; daily paper-auto and decision-review skip it and no new shadows spawn
  from a frozen parent.

Roots without the file (market shards) keep the legacy AI-judgment primary and
rules control.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ASSESSMENT_MODEL_FILENAME = "assessment_model.json"
SCHEMA_VERSION = 1

LEGACY_PRIMARY_TRACK_ID = "ai_judgment"
LEGACY_CONTROL_TRACK_ID = "rules"


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_assessment_model(base_dir: Path) -> dict[str, Any]:
    return _read(Path(base_dir) / ASSESSMENT_MODEL_FILENAME)


def primary_track_id(base_dir: Path) -> str:
    return str(load_assessment_model(base_dir).get("primary_track") or LEGACY_PRIMARY_TRACK_ID)


def control_track_id(base_dir: Path) -> str:
    return str(load_assessment_model(base_dir).get("control_track") or LEGACY_CONTROL_TRACK_ID)


def frozen_tracks(base_dir: Path) -> dict[str, dict[str, Any]]:
    rows = load_assessment_model(base_dir).get("frozen_tracks") or {}
    return {str(k): dict(v) for k, v in rows.items() if isinstance(v, dict)}


def is_track_frozen(base_dir: Path, track_id: str) -> bool:
    return str(track_id) in frozen_tracks(base_dir)


def _final_record(track_dir: Path) -> dict[str, Any]:
    fund = _read(track_dir / "automated_fund.json")
    marks = [m for m in fund.get("equity_curve") or [] if isinstance(m, dict)]
    last = marks[-1] if marks else {}
    holdings = fund.get("holdings") or {}
    tickers = sorted(holdings) if isinstance(holdings, dict) else []
    return {
        "final_mark_at": last.get("at"),
        "final_nav": last.get("portfolio_value"),
        "final_contributed_capital": last.get("contributed_capital"),
        "final_holdings": tickers,
        "trade_count": len(fund.get("trades") or []),
    }


def apply_assessment_model(
    base_dir: Path,
    *,
    primary: str,
    control: str,
    freeze: dict[str, dict[str, str]],
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record the primary/control switch and freeze books (idempotent per track).

    ``freeze`` maps track_id → {"reason": ..., "superseded_by": ...}. Already
    frozen tracks keep their original freeze record.
    """
    from value_investor.paper_automation import learning_track_dirs

    base_dir = Path(base_dir)
    when = (now or datetime.now(UTC)).isoformat()
    dirs = learning_track_dirs(base_dir)
    for track_id in (primary, control):
        if track_id not in dirs:
            raise ValueError(f"Unknown track {track_id!r}")
        if track_id in freeze:
            raise ValueError(f"{track_id!r} cannot be both active and frozen")
    model = load_assessment_model(base_dir)
    previous_primary = str(model.get("primary_track") or LEGACY_PRIMARY_TRACK_ID)
    previous_control = str(model.get("control_track") or LEGACY_CONTROL_TRACK_ID)
    switches = list(model.get("switches") or [])
    if (primary, control) != (previous_primary, previous_control):
        switches.append(
            {
                "at": when,
                "from": {"primary": previous_primary, "control": previous_control},
                "to": {"primary": primary, "control": control},
                "reason": reason,
            }
        )
    frozen = dict(model.get("frozen_tracks") or {})
    for track_id, meta in freeze.items():
        if track_id not in dirs:
            raise ValueError(f"Unknown track {track_id!r}")
        if track_id in frozen:
            continue
        frozen[track_id] = {
            "frozen_at": when,
            "reason": str(meta.get("reason") or reason),
            "superseded_by": meta.get("superseded_by"),
            **_final_record(dirs[track_id]),
        }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "primary_track": primary,
        "control_track": control,
        "switched_at": switches[-1]["at"] if switches else model.get("switched_at"),
        "switches": switches,
        "frozen_tracks": dict(sorted(frozen.items())),
        "note": (
            "Frozen books keep their history and stop trading. Do not edit their "
            "configs or funds; start a twin instead."
        ),
    }
    (base_dir / ASSESSMENT_MODEL_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload
