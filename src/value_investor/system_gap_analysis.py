"""Deterministic learning-path integrity snapshot for review agents.

Automated counters (budget remaining, memo-file existence, executed=0 skips)
can look healthy while the learning consumer is starved. This snapshot splits
produce / persist / publish / apply and filing-parity vs learning-clock so
analysis-review, learning-director, post-run, and horizon can interrogate
latent infrastructure gaps instead of stopping at the first green flag.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.paper_auto_publish import (
    OVERLAY_ROOT_FILES,
    OVERLAY_TRACK_FILES,
    SKIP_DIR_NAMES,
)
from value_investor.storage import read_json, write_json

DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_OUTPUT_DIR = Path("output")
COMMITTED_GAPS_PATH = DEFAULT_DATA_DIR / "system_gaps.json"
SCHEMA_VERSION = 1

BUY_TIER_SIGNALS = frozenset({"strong_buy", "buy"})
THIN_GRADES = frozenset({"thin", "poor", "adequate", ""})
OVERLAY_LAG_MIN = 3
THIN_MEMO_MIN = 5
LIBRARY_MEMO_SAMPLE = 40
HIGH_REMAINING_USD = 20.0

PROBE_QUESTIONS = (
    "Is the learning consumer seeing the research we already paid for?",
    "Would a new in-scope market inherit the same produce/persist/publish/apply miss?",
    "Which green counters (budget remaining, executed=0, memo-file coverage) "
    "would still be green if memo quality were zero?",
    "Does file existence mean freshness, or is rememo blocked by dedupe?",
    "Are observe-sim / paper clocks accumulating on markets that look ingest-healthy?",
)

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _safe_read(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except (OSError, ValueError, TypeError):
        return None


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _load_policy(policy_path: Path | None) -> dict[str, Any]:
    if policy_path is not None:
        if policy_path.exists():
            return _as_dict(_safe_read(policy_path))
        return {}
    try:
        from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy

        if DEFAULT_POLICY_PATH.exists():
            return _as_dict(load_policy(DEFAULT_POLICY_PATH))
    except (OSError, ValueError, TypeError):
        return {}
    return {}


def _budget_status(policy: dict[str, Any]) -> dict[str, Any]:
    try:
        from value_investor.agent_model_policy import weekly_ops_budget_status

        return dict(weekly_ops_budget_status(policy if policy else {"budget": {}}))
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def _slim_memo_meta(path: Path) -> dict[str, Any] | None:
    raw = _as_dict(_safe_read(path))
    if not raw:
        return None
    quality = _as_dict(raw.get("memo_quality"))
    sources = _as_dict(raw.get("source_counts"))
    bodies = quality.get("filings_with_body")
    if bodies is None:
        bodies = sources.get("filings_with_body")
    return {
        "ticker": _ticker(raw.get("ticker") or path.parent.name),
        "name": str(raw.get("name") or path.parent.name),
        "verdict": raw.get("research_verdict"),
        "mode": str(raw.get("mode") or ""),
        "grade": str(quality.get("grade") or "").strip().lower() or None,
        "filings_with_body": _int(bodies, 0),
    }


def _list_committed_memos(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/research.json")):
        meta = _slim_memo_meta(path)
        if meta is not None:
            rows.append(meta)
    return rows


def _library_research_rollup(research_root: Path) -> dict[str, Any]:
    if not research_root.is_dir():
        return {
            "memo_count": 0,
            "sampled": 0,
            "thin_or_zero_body": 0,
            "missing_verdict": 0,
            "mode_initial": 0,
            "samples": [],
        }
    entries = [
        entry
        for entry in research_root.iterdir()
        if entry.is_dir()
        and ((entry / "research.json").exists() or (entry / "research.md").exists())
    ]
    thin = 0
    missing_verdict = 0
    mode_initial = 0
    samples: list[dict[str, Any]] = []
    sampled = 0
    for entry in sorted(entries, key=lambda path: path.name)[:LIBRARY_MEMO_SAMPLE]:
        meta = _slim_memo_meta(entry / "research.json")
        if meta is None:
            continue
        sampled += 1
        grade = str(meta.get("grade") or "")
        bodies = _int(meta.get("filings_with_body"), 0)
        if grade in THIN_GRADES and bodies <= 0:
            thin += 1
        if not meta.get("verdict"):
            missing_verdict += 1
        if str(meta.get("mode") or "") == "initial":
            mode_initial += 1
        if len(samples) < 8:
            samples.append(meta)
    return {
        "memo_count": len(entries),
        "sampled": sampled,
        "thin_or_zero_body": thin,
        "missing_verdict": missing_verdict,
        "mode_initial": mode_initial,
        "samples": samples,
    }


def _latest_layers(latest: dict[str, Any]) -> dict[str, Any]:
    reports = [row for row in _as_list(latest.get("reports")) if isinstance(row, dict)]
    index = [row for row in _as_list(latest.get("research")) if isinstance(row, dict)]
    buy_tier = [
        row for row in reports if str(row.get("signal") or "").strip().lower() in BUY_TIER_SIGNALS
    ]
    strong_buy = [
        row for row in reports if str(row.get("signal") or "").strip().lower() == "strong_buy"
    ]
    wired = [row for row in reports if str(row.get("research_verdict") or "").strip()]
    index_tickers = {_ticker(row.get("ticker")) for row in index if _ticker(row.get("ticker"))}
    wired_tickers = {_ticker(row.get("ticker")) for row in wired if _ticker(row.get("ticker"))}
    buy_tier_wired = [row for row in buy_tier if str(row.get("research_verdict") or "").strip()]
    strong_wired = [row for row in strong_buy if str(row.get("research_verdict") or "").strip()]
    return {
        "report_count": len(reports),
        "buy_tier_count": len(buy_tier),
        "strong_buy_count": len(strong_buy),
        "wired_verdict_count": len(wired),
        "buy_tier_wired_count": len(buy_tier_wired),
        "strong_buy_wired_count": len(strong_wired),
        "research_index_count": len(index),
        "index_tickers": index_tickers,
        "wired_tickers": wired_tickers,
        "buy_tier_tickers": [_ticker(row.get("ticker")) for row in buy_tier],
        "strong_buy_tickers": [_ticker(row.get("ticker")) for row in strong_buy],
        "buy_tier_unwired": [
            _ticker(row.get("ticker"))
            for row in buy_tier
            if not str(row.get("research_verdict") or "").strip()
        ],
        "strong_buy_unwired": [
            _ticker(row.get("ticker"))
            for row in strong_buy
            if not str(row.get("research_verdict") or "").strip()
        ],
    }


def _committed_vs_overlay(
    committed: list[dict[str, Any]],
    layers: dict[str, Any],
) -> dict[str, Any]:
    committed_tickers = {_ticker(row.get("ticker")) for row in committed}
    with_verdict = [row for row in committed if str(row.get("verdict") or "").strip()]
    verdict_tickers = {_ticker(row.get("ticker")) for row in with_verdict}
    thin = [
        row
        for row in committed
        if str(row.get("grade") or "") in THIN_GRADES and _int(row.get("filings_with_body"), 0) <= 0
    ]
    initial = [row for row in committed if str(row.get("mode") or "") == "initial"]
    index_tickers = set(layers.get("index_tickers") or set())
    wired_tickers = set(layers.get("wired_tickers") or set())
    buy_unwired = [
        ticker for ticker in (layers.get("buy_tier_unwired") or []) if ticker in verdict_tickers
    ]
    strong_unwired = [
        ticker for ticker in (layers.get("strong_buy_unwired") or []) if ticker in verdict_tickers
    ]
    committed_not_indexed = sorted(verdict_tickers - index_tickers)
    committed_not_wired = sorted(verdict_tickers - wired_tickers)
    return {
        "committed_count": len(committed),
        "committed_with_verdict": len(with_verdict),
        "thin_or_zero_body": len(thin),
        "mode_initial": len(initial),
        "index_missing_committed_verdicts": len(committed_not_indexed),
        "wired_missing_committed_verdicts": len(committed_not_wired),
        "buy_tier_unwired_with_committed_verdict": buy_unwired[:12],
        "strong_buy_unwired_with_committed_verdict": strong_unwired[:12],
        "committed_not_indexed_sample": committed_not_indexed[:12],
        "buy_tier_count": layers.get("buy_tier_count"),
        "buy_tier_wired_count": layers.get("buy_tier_wired_count"),
        "strong_buy_count": layers.get("strong_buy_count"),
        "strong_buy_wired_count": layers.get("strong_buy_wired_count"),
        "research_index_count": layers.get("research_index_count"),
        "committed_tickers": len(committed_tickers),
    }


def _iter_track_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.iterdir() if path.is_dir() and path.name not in SKIP_DIR_NAMES
    )


def _persist_holes(paper_root: Path, output_dir: Path) -> dict[str, Any]:
    output_paper = Path(output_dir) / "paper_automation"
    missing_committed: list[str] = []
    in_output_not_committed: list[str] = []

    def _relatives(root: Path) -> set[str]:
        names: set[str] = set()
        if not root.is_dir():
            return names
        for name in OVERLAY_ROOT_FILES:
            if (root / name).is_file():
                names.add(name)
        for track in [root, *_iter_track_dirs(root)]:
            prefix = "" if track == root else f"{track.name}/"
            for name in OVERLAY_TRACK_FILES:
                if (track / name).is_file():
                    names.add(f"{prefix}{name}")
        return names

    committed_names = _relatives(paper_root)
    output_names = _relatives(output_paper)
    if paper_root.is_dir() and _iter_track_dirs(paper_root):
        for name in OVERLAY_ROOT_FILES:
            if name not in committed_names:
                missing_committed.append(name)
    in_output_not_committed = sorted(output_names - committed_names)
    return {
        "committed_overlay_files": sorted(committed_names),
        "output_overlay_files": sorted(output_names),
        "missing_committed_root_overlays": missing_committed,
        "in_output_not_committed": in_output_not_committed,
        "persist_hole": bool(in_output_not_committed),
    }


def _ladder_research(library_root: Path) -> dict[str, Any]:
    raw = _as_dict(_safe_read(Path(library_root) / "last_ladder.json"))
    if not raw:
        return {}
    layer = _as_dict((_as_dict(raw.get("layers"))).get("selective_research"))
    plan = _as_dict(raw.get("plan"))
    dedupe = _as_dict(layer.get("dedupe"))
    return {
        "run_at": raw.get("run_at"),
        "focus_market": raw.get("focus_market"),
        "allow_research": plan.get("allow_research", layer.get("allow_research")),
        "executed": _int(layer.get("executed"), 0),
        "created": _int(layer.get("created"), 0),
        "updated": _int(layer.get("updated"), 0),
        "skipped": bool(layer.get("skipped")),
        "budget_flag": layer.get("budget_flag"),
        "constraining": bool(layer.get("constraining")),
        "remaining_usd_before": layer.get("remaining_usd_before"),
        "already_researched_count": _int(dedupe.get("already_researched_count"), 0),
        "dedupe_skipped_count": _int(dedupe.get("skipped_count"), 0),
        "dedupe_note": dedupe.get("note"),
        "skipped_sample": list(dedupe.get("skipped_sample") or [])[:8],
    }


def _policy_markets(policy: dict[str, Any]) -> list[str]:
    ladder = _as_dict(policy.get("ladder"))
    markets: list[str] = []

    def _add(raw: object) -> None:
        name = str(raw or "").strip()
        if name and name not in markets:
            markets.append(name)

    _add(policy.get("focus_market"))
    for key in (
        "observe_sim_markets",
        "observe_sim_markets_extra",
        "weekly_paper_shard_markets",
    ):
        for mid in _as_list(ladder.get(key)):
            _add(mid)
    for key in (
        "ingest_parity_markets",
        "ingest_parallel_sprint",
        "ingest_parallel_sprint_2",
        "ftse_equivalent_markets",
    ):
        for mid in _as_list(policy.get(key)):
            _add(mid)
    try:
        from value_investor.library_sim import (
            ingest_profile_observe_sim_markets,
            observe_sim_markets_for_policy,
        )

        for mid in ingest_profile_observe_sim_markets(policy):
            _add(mid)
        for mid in observe_sim_markets_for_policy(policy):
            _add(mid)
    except Exception:  # noqa: BLE001 — clock list must still build
        pass
    return markets


def _learning_clocks(
    library_root: Path,
    policy: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    from value_investor.library_learning_depth import assess_screen_archive_span

    markets = _policy_markets(policy)
    depth_root = Path(library_root) / "markets"
    if depth_root.is_dir():
        for path in sorted(depth_root.glob("*/learning_depth.json")):
            mid = path.parent.name
            if mid not in markets:
                markets.append(mid)
    rows: list[dict[str, Any]] = []
    filing_ready_learning_stale: list[str] = []
    observe_stale: list[str] = []
    for mid in markets:
        depth = _as_dict(_safe_read(Path(library_root) / "markets" / mid / "learning_depth.json"))
        screen = _as_dict(depth.get("screen"))
        live = assess_screen_archive_span(library_root, mid, now=now)
        live_files = _int(live.get("archive_files"), 0)
        # Dated CSVs are the clock. A stale learning_depth.json snapshot is not.
        if live_files > 0:
            screen = {**screen, **live}
            stale = bool(live.get("stale"))
        else:
            stale = bool(screen.get("stale"))
        filing_ready = bool(depth.get("filing_ready"))
        learning_ready = bool(depth.get("learning_ready"))
        has_clock = bool(depth) or live_files > 0
        row = {
            "market_id": mid,
            "filing_ready": filing_ready if depth else None,
            "learning_ready": learning_ready if depth else None,
            "trajectory_ready": depth.get("trajectory_ready") if depth else None,
            "screen_stale": stale if has_clock else None,
            "unique_days": screen.get("unique_days"),
            "last_screen": screen.get("last_screen"),
            "observe_snapshots": _int(
                (_as_dict(depth.get("trajectory"))).get("snapshot_count"),
                default=_int(screen.get("archive_files"), 0),
            )
            if has_clock
            else None,
        }
        rows.append(row)
        if depth and filing_ready and not learning_ready:
            filing_ready_learning_stale.append(mid)
        if has_clock and stale:
            observe_stale.append(mid)
    return {
        "markets": rows,
        "filing_ready_learning_stale": filing_ready_learning_stale,
        "observe_clock_stale": observe_stale,
    }


def _library_focus_quality(
    library_root: Path,
    policy: dict[str, Any],
    ladder: dict[str, Any],
) -> dict[str, Any]:
    focus = str(ladder.get("focus_market") or policy.get("focus_market") or "").strip()
    if not focus:
        return {}
    research_root = Path(library_root) / "markets" / focus / "screen" / "research"
    rollup = _library_research_rollup(research_root)
    summary = _as_dict(
        _safe_read(Path(library_root) / "markets" / focus / "screen" / "latest_summary.json")
    )
    signal_counts = _as_dict(summary.get("signal_counts") or summary.get("signals"))
    buy_tier = _int(signal_counts.get("strong_buy"), 0) + _int(signal_counts.get("buy"), 0)
    return {
        "market_id": focus,
        "buy_tier_count": buy_tier or None,
        **rollup,
    }


def _flag(
    *,
    flag_id: str,
    severity: str,
    layer: str,
    title: str,
    summary: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": flag_id,
        "severity": severity,
        "layer": layer,
        "title": title,
        "summary": summary,
        "evidence": evidence,
    }


def _build_flags(
    *,
    overlay: dict[str, Any],
    persist: dict[str, Any],
    ladder: dict[str, Any],
    budget: dict[str, Any],
    clocks: dict[str, Any],
    library_quality: dict[str, Any],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    unwired_buy = list(overlay.get("buy_tier_unwired_with_committed_verdict") or [])
    missing_index = _int(overlay.get("index_missing_committed_verdicts"), 0)
    committed_verdicts = _int(overlay.get("committed_with_verdict"), 0)
    index_count = _int(overlay.get("research_index_count"), 0)

    if len(unwired_buy) >= OVERLAY_LAG_MIN:
        flags.append(
            _flag(
                flag_id="buy_tier_unwired_verdict",
                severity="high",
                layer="apply",
                title="Buy-tier names have committed verdicts the paper overlay does not see",
                summary=(
                    f"{len(unwired_buy)} buy-tier tickers have a committed research "
                    "verdict but no research_verdict on the live report the book reads."
                ),
                evidence={
                    "sample": unwired_buy[:8],
                    "buy_tier_wired": overlay.get("buy_tier_wired_count"),
                    "buy_tier_count": overlay.get("buy_tier_count"),
                    "committed_with_verdict": committed_verdicts,
                },
            )
        )

    if missing_index >= OVERLAY_LAG_MIN:
        flags.append(
            _flag(
                flag_id="overlay_lagging_committed",
                severity="high",
                layer="publish",
                title="Published research[] index lags the committed memo store",
                summary=(
                    f"{missing_index} committed memos with verdicts are absent from "
                    f"latest.json research[] ({index_count} indexed vs "
                    f"{committed_verdicts} committed verdicts)."
                ),
                evidence={
                    "research_index_count": index_count,
                    "committed_with_verdict": committed_verdicts,
                    "sample": overlay.get("committed_not_indexed_sample"),
                },
            )
        )

    if committed_verdicts > 0 and index_count > 0 and index_count * 2 < committed_verdicts:
        flags.append(
            _flag(
                flag_id="research_index_shrunk",
                severity="high",
                layer="publish",
                title="Research index looks like a replace, not a union",
                summary=(
                    f"research[] has {index_count} entries while {committed_verdicts} "
                    "committed memos carry verdicts — a short rememo publish may have "
                    "overwritten the Sunday union."
                ),
                evidence={
                    "research_index_count": index_count,
                    "committed_with_verdict": committed_verdicts,
                },
            )
        )

    thin_live = _int(overlay.get("thin_or_zero_body"), 0)
    thin_lib = _int(library_quality.get("thin_or_zero_body"), 0)
    memo_lib = _int(library_quality.get("memo_count"), 0)
    already = _int(ladder.get("already_researched_count"), 0)
    executed = _int(ladder.get("executed"), 0)
    if thin_lib >= THIN_MEMO_MIN and memo_lib > 0 and already > 0 and executed == 0:
        flags.append(
            _flag(
                flag_id="thin_memo_counted_as_coverage",
                severity="high",
                layer="produce",
                title="First-pass / zero-body memos are counted as research done",
                summary=(
                    f"{thin_lib} sampled {library_quality.get('market_id') or 'focus'} "
                    f"memos are thin or have 0 filing bodies, but the ladder skipped "
                    f"{already} names as already researched (executed={executed})."
                ),
                evidence={
                    "market_id": library_quality.get("market_id"),
                    "thin_or_zero_body": thin_lib,
                    "memo_count": memo_lib,
                    "already_researched_count": already,
                    "executed": executed,
                },
            )
        )
    elif thin_live >= THIN_MEMO_MIN and already > 0 and executed == 0:
        flags.append(
            _flag(
                flag_id="thin_memo_counted_as_coverage",
                severity="medium",
                layer="produce",
                title="Committed live memos include thin / zero-body files treated as done",
                summary=(
                    f"{thin_live} committed live memos are thin or have 0 filing bodies "
                    f"while the ladder reports already_researched={already} and executed=0."
                ),
                evidence={
                    "thin_or_zero_body": thin_live,
                    "already_researched_count": already,
                    "executed": executed,
                },
            )
        )

    remaining = _float(budget.get("remaining_weekly_ops_usd"), 0.0)
    allow_research = ladder.get("allow_research")
    constraining = bool(budget.get("constraining") or ladder.get("constraining"))
    if executed == 0 and already > 0 and allow_research is not False and not constraining:
        flags.append(
            _flag(
                flag_id="research_skipped_already_done",
                severity="high",
                layer="produce",
                title="Research skipped as already-done while the learning path may still be hungry",
                summary=(
                    f"Last ladder executed 0 memos and skipped {already} as already "
                    "researched. That is not proof the overlay or rememo path is fed."
                ),
                evidence={
                    "executed": executed,
                    "already_researched_count": already,
                    "dedupe_skipped_count": ladder.get("dedupe_skipped_count"),
                    "allow_research": allow_research,
                    "budget_flag": ladder.get("budget_flag") or budget.get("flag"),
                },
            )
        )

    if ladder and executed == 0 and remaining >= HIGH_REMAINING_USD and not constraining:
        flags.append(
            _flag(
                flag_id="unused_budget_zero_research",
                severity="medium",
                layer="produce",
                title="Weekly ops budget is unused while research executed nothing",
                summary=(
                    f"${remaining:.2f} remains on weekly_ops and last research "
                    "executed=0. Unused budget is not evidence that learning needs "
                    "are met."
                ),
                evidence={
                    "remaining_weekly_ops_usd": remaining,
                    "executed": executed,
                    "budget_flag": budget.get("flag"),
                },
            )
        )

    holes = list(persist.get("in_output_not_committed") or [])
    if persist.get("persist_hole") and holes:
        flags.append(
            _flag(
                flag_id="overlay_persist_hole",
                severity="high",
                layer="persist",
                title="Learning overlay exists in CI output but not in the committed store",
                summary=(
                    "Weekday paper-auto wrote overlay JSON under output/ that was not "
                    "copied to docs/data/paper_automation — the next run reseeds empty."
                ),
                evidence={"files": holes[:12]},
            )
        )

    stale_learning = list(clocks.get("filing_ready_learning_stale") or [])
    if stale_learning:
        flags.append(
            _flag(
                flag_id="filing_ready_learning_stale",
                severity="medium",
                layer="learning_clock",
                title="Filing parity is not the same as a learning clock",
                summary=(
                    f"{', '.join(stale_learning)} look filing-ready but are not "
                    "learning_ready (observe-sim / archive span still short or stale)."
                ),
                evidence={"markets": stale_learning},
            )
        )

    stale_obs = list(clocks.get("observe_clock_stale") or [])
    if stale_obs:
        flags.append(
            _flag(
                flag_id="observe_clock_stale",
                severity="medium",
                layer="learning_clock",
                title="Observe / screen-lite clock is stale on an in-scope market",
                summary=(
                    f"{', '.join(stale_obs)} have a stale screen archive. Ingest "
                    "health can stay green while the learning series stops."
                ),
                evidence={"markets": stale_obs},
            )
        )

    flags.sort(key=lambda row: (_SEVERITY_RANK.get(str(row.get("severity")), 9), row["id"]))
    return flags


def build_system_gap_snapshot(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    library_root: Path | None = None,
    latest_path: Path | None = None,
    committed_research: Path | None = None,
    paper_root: Path | None = None,
    policy_path: Path | None = None,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble a slim, deterministic learning-path integrity snapshot."""
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    library_root = Path(library_root or data_dir / "library")
    if not library_root.exists() and DEFAULT_LIBRARY_ROOT.exists():
        library_root = Path(DEFAULT_LIBRARY_ROOT)
    latest_path = Path(latest_path or data_dir / "latest.json")
    committed_research = Path(committed_research or data_dir / "research")
    paper_root = Path(paper_root or data_dir / "paper_automation")
    policy = _load_policy(policy_path or (library_root / "policy.json"))
    latest = _as_dict(_safe_read(latest_path))
    layers = _latest_layers(latest)
    committed = _list_committed_memos(committed_research)
    overlay = _committed_vs_overlay(committed, layers)
    persist = _persist_holes(paper_root, output_dir)
    ladder = _ladder_research(library_root)
    budget = _budget_status(policy)
    clocks = _learning_clocks(library_root, policy, now=run_at)
    library_quality = _library_focus_quality(library_root, policy, ladder)
    rememo_backlog = _as_dict(_safe_read(data_dir / "memo_rememo_backlog.json"))
    flags = _build_flags(
        overlay=overlay,
        persist=persist,
        ladder=ladder,
        budget=budget,
        clocks=clocks,
        library_quality=library_quality,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "assessed_at": (run_at or datetime.now(UTC)).isoformat(),
        "purpose": (
            "Latent learning-path gaps that healthy ops counters hide. "
            "Split produce / persist / publish / apply, and filing parity vs "
            "learning clock. Existence is not quality; unused budget is not demand met."
        ),
        "probe_questions": list(PROBE_QUESTIONS),
        "flag_count": len(flags),
        "high_flag_count": sum(1 for row in flags if row.get("severity") == "high"),
        "flags": flags,
        "layers": {
            "produce": {
                "ladder_research": ladder,
                "weekly_ops": {
                    "remaining_weekly_ops_usd": budget.get("remaining_weekly_ops_usd"),
                    "flag": budget.get("flag"),
                    "constraining": budget.get("constraining"),
                    "estimated_spend_weekly_ops_usd_this_week": budget.get(
                        "estimated_spend_weekly_ops_usd_this_week"
                    ),
                },
                "live_committed": {
                    "committed_count": overlay.get("committed_count"),
                    "committed_with_verdict": overlay.get("committed_with_verdict"),
                    "thin_or_zero_body": overlay.get("thin_or_zero_body"),
                    "mode_initial": overlay.get("mode_initial"),
                },
                "focus_library_research": library_quality,
                "rememo_backlog_count": rememo_backlog.get("backlog_count"),
                "rememo_action": rememo_backlog.get("action"),
            },
            "persist": persist,
            "publish": {
                "research_index_count": overlay.get("research_index_count"),
                "index_missing_committed_verdicts": overlay.get("index_missing_committed_verdicts"),
                "committed_not_indexed_sample": overlay.get("committed_not_indexed_sample"),
            },
            "apply": {
                "buy_tier_count": overlay.get("buy_tier_count"),
                "buy_tier_wired_count": overlay.get("buy_tier_wired_count"),
                "strong_buy_count": overlay.get("strong_buy_count"),
                "strong_buy_wired_count": overlay.get("strong_buy_wired_count"),
                "wired_missing_committed_verdicts": overlay.get("wired_missing_committed_verdicts"),
                "buy_tier_unwired_with_committed_verdict": overlay.get(
                    "buy_tier_unwired_with_committed_verdict"
                ),
                "strong_buy_unwired_with_committed_verdict": overlay.get(
                    "strong_buy_unwired_with_committed_verdict"
                ),
            },
            "learning_clock": clocks,
        },
        "healthy_counter_distrust": {
            "budget_remaining_is_not_demand_met": True,
            "executed_zero_can_mean_dedupe_not_coverage": True,
            "memo_file_existence_is_not_quality_or_freshness": True,
            "filing_parity_is_not_learning_ready": True,
        },
    }


def slim_system_gaps_for_review(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep flag + layer counts; drop large ticker dumps from agent payloads."""
    if not isinstance(snapshot, dict):
        return None
    layers = _as_dict(snapshot.get("layers"))
    apply_layer = _as_dict(layers.get("apply"))
    publish_layer = _as_dict(layers.get("publish"))
    produce = _as_dict(layers.get("produce"))
    persist = _as_dict(layers.get("persist"))
    clock = _as_dict(layers.get("learning_clock"))
    flags = []
    for row in _as_list(snapshot.get("flags")):
        if not isinstance(row, dict):
            continue
        flags.append(
            {
                "id": row.get("id"),
                "severity": row.get("severity"),
                "layer": row.get("layer"),
                "title": row.get("title"),
                "summary": row.get("summary"),
                "evidence": row.get("evidence") or {},
            }
        )
    return {
        "schema_version": snapshot.get("schema_version"),
        "assessed_at": snapshot.get("assessed_at"),
        "purpose": snapshot.get("purpose"),
        "probe_questions": list(snapshot.get("probe_questions") or PROBE_QUESTIONS),
        "flag_count": snapshot.get("flag_count"),
        "high_flag_count": snapshot.get("high_flag_count"),
        "flags": flags,
        "layers": {
            "produce": {
                "ladder_research": produce.get("ladder_research") or {},
                "weekly_ops": produce.get("weekly_ops") or {},
                "live_committed": produce.get("live_committed") or {},
                "focus_library_research": {
                    key: value
                    for key, value in _as_dict(produce.get("focus_library_research")).items()
                    if key != "samples"
                },
                "rememo_backlog_count": produce.get("rememo_backlog_count"),
                "rememo_action": produce.get("rememo_action"),
            },
            "persist": {
                "persist_hole": persist.get("persist_hole"),
                "in_output_not_committed": persist.get("in_output_not_committed") or [],
                "missing_committed_root_overlays": persist.get("missing_committed_root_overlays")
                or [],
            },
            "publish": {
                "research_index_count": publish_layer.get("research_index_count"),
                "index_missing_committed_verdicts": publish_layer.get(
                    "index_missing_committed_verdicts"
                ),
                "committed_not_indexed_sample": (
                    publish_layer.get("committed_not_indexed_sample") or []
                )[:8],
            },
            "apply": {
                "buy_tier_count": apply_layer.get("buy_tier_count"),
                "buy_tier_wired_count": apply_layer.get("buy_tier_wired_count"),
                "strong_buy_count": apply_layer.get("strong_buy_count"),
                "strong_buy_wired_count": apply_layer.get("strong_buy_wired_count"),
                "wired_missing_committed_verdicts": apply_layer.get(
                    "wired_missing_committed_verdicts"
                ),
                "buy_tier_unwired_sample": (
                    apply_layer.get("buy_tier_unwired_with_committed_verdict") or []
                )[:8],
                "strong_buy_unwired_sample": (
                    apply_layer.get("strong_buy_unwired_with_committed_verdict") or []
                )[:8],
            },
            "learning_clock": {
                "filing_ready_learning_stale": clock.get("filing_ready_learning_stale") or [],
                "observe_clock_stale": clock.get("observe_clock_stale") or [],
                "markets": clock.get("markets") or [],
            },
        },
        "healthy_counter_distrust": snapshot.get("healthy_counter_distrust") or {},
    }


def slim_system_gaps_for_dashboard(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Flag tiles only — no layer dumps for the overview card."""
    if not isinstance(snapshot, dict):
        return None
    flags = []
    for row in _as_list(snapshot.get("flags")):
        if not isinstance(row, dict):
            continue
        flags.append(
            {
                "id": row.get("id"),
                "severity": row.get("severity"),
                "layer": row.get("layer"),
                "title": row.get("title"),
                "summary": row.get("summary"),
            }
        )
    return {
        "schema_version": snapshot.get("schema_version"),
        "assessed_at": snapshot.get("assessed_at"),
        "purpose": snapshot.get("purpose"),
        "flag_count": snapshot.get("flag_count", len(flags)),
        "high_flag_count": snapshot.get(
            "high_flag_count",
            sum(1 for row in flags if row.get("severity") == "high"),
        ),
        "flags": flags,
    }


def write_system_gap_snapshot(
    snapshot: dict[str, Any],
    *,
    path: Path = COMMITTED_GAPS_PATH,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, snapshot, compact=False)
    return path


__all__ = [
    "COMMITTED_GAPS_PATH",
    "PROBE_QUESTIONS",
    "SCHEMA_VERSION",
    "build_system_gap_snapshot",
    "slim_system_gaps_for_dashboard",
    "slim_system_gaps_for_review",
    "write_system_gap_snapshot",
]
