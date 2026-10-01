"""Observe-only: buy-tier enter without prior key bodies (L499 archive miss proxy).

Until a cold archive store exists, flip-lag ``no_index`` / ``no_key_bodies`` at
buy-tier enter is the best proxy for “would an archive pack have helped?”.

This instrument **does not** deepen ingest, rememo, or start a crawler. It rolls
up ``docs/data/buy_tier_flip_lag.json`` into
``docs/data/universe_filing_archive_miss_rate.json`` for the L499 revisit gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 1
DEFAULT_FLIP_LAG_PATH = Path("docs/data/buy_tier_flip_lag.json")
DEFAULT_STORE_PATH = Path("docs/data/universe_filing_archive_miss_rate.json")
FINDING_TITLE = "Universe archive body-miss rate elevated"

# Stages that mean no usable filing bodies existed at / since enter.
BODY_MISS_STAGES = frozenset({"no_index", "no_key_bodies"})

# Warn when miss rate is material and sample is large enough to be a signal.
DEFAULT_WARN_MIN_COHORT = 5
DEFAULT_WARN_MIN_MISS_RATE = 0.5


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


def _row_enter_body_miss(row: dict[str, Any]) -> bool:
    """True when the name lacked key bodies at enter (archive-miss proxy)."""
    stage = str(row.get("blocking_stage") or "").strip()
    if stage in BODY_MISS_STAGES:
        return True
    # Closed/usable rows: if they never had key_bodies_at before usable, treat
    # as recovered miss (live deepen caught up). Prefer explicit enter flags.
    enter_stage = str(row.get("enter_blocking_stage") or "").strip()
    if enter_stage in BODY_MISS_STAGES:
        return True
    # Heuristic: usable now but key_bodies arrived after flip (hours_to_usable
    # set and filings_with_body was 0 at first surface — encoded via events).
    if str(row.get("status") or "") == "usable":
        # If usable and we have no evidence of bodies at enter, check whether
        # index/key_bodies clocks are after flip — still a miss proxy.
        flip_at = str(row.get("flip_at") or row.get("signal_since") or "")
        key_at = str(row.get("key_bodies_at") or "")
        index_at = str(row.get("index_at") or "")
        if flip_at and key_at and key_at > flip_at:
            return True
        if flip_at and not key_at and index_at and index_at > flip_at:
            return True
    return False


def _classify_row(row: dict[str, Any]) -> dict[str, Any]:
    mid = str(row.get("market_id") or "").strip()
    tick = str(row.get("ticker") or "").strip().upper()
    stage = str(row.get("blocking_stage") or "").strip() or None
    status = str(row.get("status") or "").strip()
    miss = _row_enter_body_miss(row)
    open_missing = status == "open" and stage in BODY_MISS_STAGES
    return {
        "key": str(row.get("key") or f"{mid}:{tick}"),
        "market_id": mid,
        "ticker": tick,
        "status": status,
        "blocking_stage": stage,
        "enter_body_miss_proxy": miss,
        "open_still_missing_bodies": open_missing,
        "hours_since_flip": row.get("hours_since_flip"),
        "hours_to_usable": row.get("hours_to_usable"),
        "usable_mode": row.get("usable_mode"),
    }


def update_universe_filing_archive_miss_rate(
    *,
    flip_lag_path: Path = DEFAULT_FLIP_LAG_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
    flip_lag_payload: dict[str, Any] | None = None,
    warn_min_cohort: int = DEFAULT_WARN_MIN_COHORT,
    warn_min_miss_rate: float = DEFAULT_WARN_MIN_MISS_RATE,
    now: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Roll up flip-lag into an archive body-miss proxy store."""
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    else:
        clock = clock.astimezone(UTC)

    flip = flip_lag_payload if flip_lag_payload is not None else _safe_read(Path(flip_lag_path))
    names = _as_dict(flip.get("names"))
    rows = [_classify_row(_as_dict(v)) for v in names.values()]
    # Prefer active cohort listed in flip summary snapshots when present.
    snapshots = _as_list(flip.get("snapshots") or flip.get("cohort") or [])
    if snapshots and not rows:
        rows = [_classify_row(_as_dict(v)) for v in snapshots]

    cohort = len(rows)
    miss_rows = [r for r in rows if r.get("enter_body_miss_proxy")]
    open_missing = [r for r in rows if r.get("open_still_missing_bodies")]
    miss_count = len(miss_rows)
    miss_rate = round(miss_count / cohort, 4) if cohort else 0.0

    by_market: dict[str, dict[str, Any]] = {}
    for row in rows:
        mid = str(row.get("market_id") or "unknown")
        bucket = by_market.setdefault(
            mid,
            {
                "cohort_count": 0,
                "enter_body_miss_count": 0,
                "open_still_missing_bodies": 0,
            },
        )
        bucket["cohort_count"] += 1
        if row.get("enter_body_miss_proxy"):
            bucket["enter_body_miss_count"] += 1
        if row.get("open_still_missing_bodies"):
            bucket["open_still_missing_bodies"] += 1
    for bucket in by_market.values():
        c = int(bucket["cohort_count"])
        m = int(bucket["enter_body_miss_count"])
        bucket["miss_rate"] = round(m / c, 4) if c else 0.0

    warn = bool(
        cohort >= int(warn_min_cohort)
        and miss_rate >= float(warn_min_miss_rate)
        and len(open_missing) > 0
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": clock.isoformat(),
        "observe_only": True,
        "proxy_note": (
            "Proxy until cold packs exist: buy-tier enter with no_index/no_key_bodies "
            "(or bodies arriving after flip) ≈ archive-body miss. Not a crawler."
        ),
        "source_flip_lag_path": str(Path(flip_lag_path)),
        "source_flip_lag_updated_at": flip.get("updated_at"),
        "summary": {
            "cohort_count": cohort,
            "enter_body_miss_count": miss_count,
            "miss_rate": miss_rate,
            "open_still_missing_bodies": len(open_missing),
            "warn": warn,
            "warn_min_cohort": int(warn_min_cohort),
            "warn_min_miss_rate": float(warn_min_miss_rate),
            "by_market": by_market,
        },
        "names": {str(r["key"]): r for r in rows},
        "open_missing_sample": [
            f"{r.get('market_id')}/{r.get('ticker')}" for r in open_missing[:12]
        ],
    }
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, compact=False)
    return payload


def ops_finding_from_archive_miss_rate(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Warn-only finding when miss rate is elevated with open body gaps."""
    if not payload:
        return None
    summary = _as_dict(payload.get("summary"))
    if not summary.get("warn"):
        return None
    cohort = int(summary.get("cohort_count") or 0)
    miss_rate = float(summary.get("miss_rate") or 0.0)
    open_n = int(summary.get("open_still_missing_bodies") or 0)
    sample = _as_list(payload.get("open_missing_sample"))
    sample_txt = ", ".join(str(s) for s in sample[:6]) if sample else "—"
    return {
        "severity": "warn",
        "category": "ingest",
        "title": FINDING_TITLE,
        "summary": (
            f"Archive body-miss proxy {miss_rate:.0%} of {cohort} recent buy-tier "
            f"flips; {open_n} still open without key bodies "
            f"(sample: {sample_txt}). Observe-only — isolation + fail-open hydrate "
            "scaffolds exist; do not start a second crawler until focus head is at "
            "maintenance threshold."
        ),
        "auto_fixable": False,
    }


def format_archive_miss_rate_summary(payload: dict[str, Any]) -> str:
    summary = _as_dict(payload.get("summary"))
    lines = [
        "Universe filing archive miss-rate (proxy from flip-lag)",
        f"  Cohort: {summary.get('cohort_count')}",
        f"  Enter body-miss: {summary.get('enter_body_miss_count')} "
        f"({float(summary.get('miss_rate') or 0):.1%})",
        f"  Open still missing bodies: {summary.get('open_still_missing_bodies')}",
        f"  Warn: {summary.get('warn')}",
    ]
    by_market = _as_dict(summary.get("by_market"))
    for mid in sorted(by_market):
        b = _as_dict(by_market.get(mid))
        lines.append(
            f"  {mid}: cohort={b.get('cohort_count')} miss={b.get('enter_body_miss_count')} "
            f"rate={float(b.get('miss_rate') or 0):.1%} open_missing={b.get('open_still_missing_bodies')}"
        )
    return "\n".join(lines)


__all__ = [
    "BODY_MISS_STAGES",
    "DEFAULT_FLIP_LAG_PATH",
    "DEFAULT_STORE_PATH",
    "DEFAULT_WARN_MIN_COHORT",
    "DEFAULT_WARN_MIN_MISS_RATE",
    "FINDING_TITLE",
    "SCHEMA_VERSION",
    "format_archive_miss_rate_summary",
    "ops_finding_from_archive_miss_rate",
    "update_universe_filing_archive_miss_rate",
]
