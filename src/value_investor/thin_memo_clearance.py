"""Track and run the so-what ``thin_memo_counted_as_coverage`` clearance path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.storage import read_json
from value_investor.system_gap_analysis import (
    COMMITTED_GAPS_PATH,
    THIN_MEMO_MIN,
    _library_focus_quality,
    _load_policy,
    _safe_read,
    build_system_gap_snapshot,
)

THIN_MEMO_FLAG_ID = "thin_memo_counted_as_coverage"


def _library_root(data_dir: Path) -> Path:
    root = data_dir / "library"
    if root.is_dir():
        return root
    from value_investor.system_gap_analysis import DEFAULT_LIBRARY_ROOT

    return DEFAULT_LIBRARY_ROOT


def build_thin_memo_clearance_status(
    *,
    data_dir: Path | None = None,
    library_root: Path | None = None,
    gaps_path: Path | None = None,
) -> dict[str, Any]:
    """
    Live rollup for the learning-path thin-memo flag (produce layer).

    Clearance: ``thin_or_zero_body`` in the focus library sample must drop
    below ``THIN_MEMO_MIN`` after ingest + body-lag rememo — not rememo widening.
    """
    data_dir = Path(data_dir or Path("docs/data"))
    library_root = Path(library_root or _library_root(data_dir))
    gaps_path = Path(gaps_path or data_dir / COMMITTED_GAPS_PATH.name)

    policy = _load_policy(library_root / "policy.json")
    ladder = _as_dict(_safe_read(library_root / "last_ladder.json"))
    focus = (
        str(ladder.get("focus_market") or policy.get("focus_market") or "euro_depth").strip()
        or "euro_depth"
    )
    quality = _library_focus_quality(library_root, policy, {"focus_market": focus})
    thin_count = int(quality.get("thin_or_zero_body") or 0)
    sampled = int(quality.get("sampled") or 0)
    memo_count = int(quality.get("memo_count") or 0)

    from value_investor.library_maintenance import list_thin_library_memos

    zero_body_targets = list_thin_library_memos(
        library_root,
        markets=[focus],
        max_with_body=0,
    )
    rememo_pending = _rememo_pending_after_ingest(library_root, focus)

    live_snapshot = build_system_gap_snapshot(
        data_dir=data_dir,
        library_root=library_root,
    )
    live_flag = _flag_row(live_snapshot, THIN_MEMO_FLAG_ID)
    committed = read_json(gaps_path) if gaps_path.exists() else {}
    committed_flag = _flag_row(committed if isinstance(committed, dict) else {}, THIN_MEMO_FLAG_ID)

    cleared = thin_count < THIN_MEMO_MIN
    deficit = max(0, thin_count - THIN_MEMO_MIN + 1) if not cleared else 0

    steps = [
        {
            "id": "ingest_deepen",
            "title": "Ingest filing bodies (library thin memos)",
            "command": f"ftse-library deepen-thin --markets {focus}",
            "status": "done" if cleared else ("needed" if zero_body_targets else "optional"),
        },
        {
            "id": "body_lag_rememo",
            "title": "Body-lag rememo when disk bodies increase",
            "command": (
                f"ftse-library deepen-thin --markets {focus} --rememo "
                "(or ftse-library admitted-rememo when eligible)"
            ),
            "status": (
                "needed"
                if rememo_pending
                else (
                    "pending"
                    if not cleared and zero_body_targets
                    else ("optional" if cleared else "blocked")
                )
            ),
        },
        {
            "id": "refresh_system_gaps",
            "title": "Refresh system_gaps.json",
            "command": "ftse-analysis-review system-gaps --write",
            "status": "done" if cleared and not live_flag else "needed",
        },
        {
            "id": "verify_so_what",
            "title": "Verify so-what learning-path row cleared",
            "command": "ftse-progress-report so-what",
            "status": "done" if cleared and not live_flag else "needed",
        },
    ]

    return {
        "flag_id": THIN_MEMO_FLAG_ID,
        "market_id": focus,
        "cleared": cleared,
        "thin_sample_count": thin_count,
        "thin_sample_threshold": THIN_MEMO_MIN,
        "memos_sampled": sampled,
        "memo_count": memo_count,
        "deficit_to_clear": deficit,
        "zero_body_target_count": len(zero_body_targets),
        "zero_body_tickers": [row["ticker"] for row in zero_body_targets[:24]],
        "rememo_pending_count": len(rememo_pending),
        "rememo_pending_tickers": rememo_pending[:24],
        "committed_flag_present": bool(committed_flag),
        "live_flag_would_fire": bool(live_flag),
        "committed_assessed_at": committed.get("assessed_at") if isinstance(committed, dict) else None,
        "live_assessed_at": live_snapshot.get("assessed_at"),
        "steps": steps,
        "summary": (
            f"{focus}: {thin_count}/{sampled} sampled memos thin/zero-body "
            f"(need <{THIN_MEMO_MIN} to clear {THIN_MEMO_FLAG_ID}). "
            f"{len(zero_body_targets)} memo(s) with 0 filing bodies on disk; "
            f"{len(rememo_pending)} pending body-lag rememo (disk has bodies, memo label stale)."
        ),
    }


def render_thin_memo_clearance_markdown(section: dict[str, Any]) -> str:
    if not section:
        return ""
    lines = [
        "## Thin-memo clearance (so-what learning path)",
        "",
        section.get("summary") or "",
        "",
        f"- **Cleared (live sample):** {'yes' if section.get('cleared') else 'no'} "
        f"· thin sample **{section.get('thin_sample_count')}** "
        f"(threshold **<{section.get('thin_sample_threshold')}**)",
        f"- **Zero-body memos on disk:** {section.get('zero_body_target_count')} "
        f"({', '.join(section.get('zero_body_tickers') or []) or '—'})",
        f"- **Body-lag rememo pending:** {section.get('rememo_pending_count')} "
        f"({', '.join(section.get('rememo_pending_tickers') or []) or '—'})",
        f"- **Committed system_gaps flag:** "
        f"{'present' if section.get('committed_flag_present') else 'absent'} "
        f"· live would fire: {'yes' if section.get('live_flag_would_fire') else 'no'}",
        "",
        "### Clearance sequence",
        "",
    ]
    for step in section.get("steps") or []:
        lines.append(
            f"- **{step.get('title')}** ({step.get('status')}): `{step.get('command')}`"
        )
    lines.append("")
    return "\n".join(lines)


def _flag_row(snapshot: dict[str, Any], flag_id: str) -> dict[str, Any] | None:
    for row in snapshot.get("flags") or []:
        if isinstance(row, dict) and row.get("id") == flag_id:
            return row
    return None


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _rememo_pending_after_ingest(library_root: Path, market_id: str) -> list[str]:
    """Tickers with filing bodies on disk but memo metadata still thin/zero-body."""
    from value_investor.library_maintenance import _filings_body_count
    from value_investor.system_gap_analysis import THIN_GRADES, _int, _slim_memo_meta

    research_root = Path(library_root) / "markets" / market_id / "screen" / "research"
    if not research_root.is_dir():
        return []
    pending: list[str] = []
    for entry in sorted(research_root.iterdir(), key=lambda path: path.name):
        if not entry.is_dir():
            continue
        meta = _slim_memo_meta(entry / "research.json")
        if meta is None:
            continue
        disk_bodies = _filings_body_count(entry / "sources")
        if disk_bodies <= 0:
            continue
        grade = str(meta.get("grade") or "")
        memo_bodies = _int(meta.get("filings_with_body"), 0)
        if grade in THIN_GRADES and memo_bodies <= 0:
            pending.append(str(meta.get("ticker") or entry.name))
    return pending
