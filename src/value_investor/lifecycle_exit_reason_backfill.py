"""L632 — rewrite sealed observe ``lifecycle_episodes`` with exit/entry reasons.

Owner lock 2026-11-01: eng backfill (not accept/done-only). Re-runs N200/N201/N206
observe refresh so ``slim_lifecycle_episode`` rewrites the committed lifecycle list
from full scored episodes (exit_reason on closed; entry_detail/entry_reason on
open+closed). Post-sale joins then cover the full set, not only ``episodes_sample``.

Observe-only — no live books, knobs, or rememo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

DEFAULT_DATA_DIR = Path("docs/data")


def _strand_table() -> tuple[tuple[str, str, Callable[..., dict[str, Any]]], ...]:
    from value_investor.n200_tech_timing_observe import refresh_n200_tech_timing_observe
    from value_investor.n201_value_mom_observe import refresh_n201_value_mom_observe
    from value_investor.n206_plain_ey_observe import refresh_n206_plain_ey_observe

    return (
        ("n200", "n200_tech_timing_observe.json", refresh_n200_tech_timing_observe),
        ("n201", "n201_value_mom_observe.json", refresh_n201_value_mom_observe),
        ("n206", "n206_plain_ey_observe.json", refresh_n206_plain_ey_observe),
    )


def lifecycle_reason_coverage(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Counts for closed/open exit_reason + entry trail fields."""
    rows = (payload or {}).get("lifecycle_episodes")
    if not isinstance(rows, list):
        rows = []
    closed = [r for r in rows if isinstance(r, dict) and str(r.get("status") or "") == "closed"]
    open_rows = [r for r in rows if isinstance(r, dict) and str(r.get("status") or "") == "open"]

    def _blank_exit(items: list[dict[str, Any]]) -> int:
        return sum(1 for r in items if not str(r.get("exit_reason") or "").strip())

    def _missing_entry(items: list[dict[str, Any]]) -> int:
        return sum(
            1
            for r in items
            if not str(r.get("entry_reason") or "").strip()
            and not (isinstance(r.get("entry_detail"), dict) and r.get("entry_detail"))
        )

    return {
        "lifecycle_n": len([r for r in rows if isinstance(r, dict)]),
        "closed_n": len(closed),
        "open_n": len(open_rows),
        "closed_blank_exit_reason": _blank_exit(closed),
        "open_blank_exit_reason": _blank_exit(open_rows),
        "closed_missing_entry_trail": _missing_entry(closed),
        "open_missing_entry_trail": _missing_entry(open_rows),
    }


def run_l632_backfill(
    data_dir: Path | None = None,
    *,
    persist: bool = True,
    include_admitted_markets: bool = True,
) -> dict[str, Any]:
    """One-shot refresh rewrite for N200/N201/N206 lifecycle_episodes."""
    root = Path(data_dir or DEFAULT_DATA_DIR)
    results: list[dict[str, Any]] = []
    for strand_id, store_name, refresh in _strand_table():
        store_path = root / store_name
        before: dict[str, Any] | None = None
        if store_path.is_file():
            try:
                before = json.loads(store_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                before = None
        before_cov = lifecycle_reason_coverage(before)
        kwargs: dict[str, Any] = {
            "output_dir": root,
            "store_path": store_path,
            "persist": persist,
        }
        # N201/N206 accept admitted-market panels; N200 does not.
        if strand_id in {"n201", "n206"}:
            kwargs["include_admitted_markets"] = include_admitted_markets
        payload = refresh(**kwargs)
        after_cov = lifecycle_reason_coverage(payload)
        results.append(
            {
                "strand": strand_id,
                "store": str(store_path),
                "before": before_cov,
                "after": after_cov,
                "completed_entry_episodes": payload.get("completed_entry_episodes"),
                "generated_at": payload.get("generated_at"),
            }
        )
    return {
        "schema_version": 1,
        "observe_only": True,
        "influences_live": False,
        "deferred_id": "L632",
        "strands": results,
    }


__all__ = [
    "DEFAULT_DATA_DIR",
    "lifecycle_reason_coverage",
    "run_l632_backfill",
]
