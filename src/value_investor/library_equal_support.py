"""Equal-support package for admitted learning markets (L321 / L320)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.exclusion_universe_archive_sim import run_exclusion_universe_archive_sim
from value_investor.exit_timing_archive_sim import run_exit_timing_archive_sim
from value_investor.library_dedupe import canonical_library_ticker
from value_investor.library_near_miss_watch import write_library_near_miss_watch
from value_investor.library_screen import screen_dir_for
from value_investor.library_sim import save_library_run_snapshots
from value_investor.library_timing import stamp_timing_on_signals, timing_candidate_tickers
from value_investor.market_shard_admission import admitted_learning_markets_for_policy
from value_investor.research.market_store import library_rememo_eligible_tickers
from value_investor.storage import write_json
from value_investor.technical_analysis import fetch_price_history

logger = logging.getLogger(__name__)

PACKAGE_FILENAME = "equal_support_status.json"
DEFAULT_REMEMO_BODY_LAG_THRESHOLD = 10


def equal_support_markets_for_policy(policy: dict[str, Any] | None) -> list[str]:
    """Admitted markets that should receive the same learning-support package."""
    return admitted_learning_markets_for_policy(policy)


def _parse_stamp(name: str) -> datetime | None:
    stem = Path(name).stem
    if not stem.startswith("signals_"):
        return None
    raw = stem.replace("signals_", "", 1)
    try:
        dt = datetime.strptime(raw, "%Y%m%d_%H%M%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC)


def stamp_library_timing_archives(
    library_root: Path,
    market_id: str,
    *,
    history: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Write PIT timing_signal onto latest + dated signals using market Yahoo symbols."""
    screen_dir = screen_dir_for(Path(library_root), market_id)
    latest_path = screen_dir / "latest_signals.csv"
    if not latest_path.exists():
        return {"skipped": True, "reason": "missing latest_signals.csv", "market_id": market_id}
    latest = pd.read_csv(latest_path)
    wanted = timing_candidate_tickers(latest)
    for path in screen_dir.glob("signals_*.csv"):
        try:
            frame = pd.read_csv(path)
        except (OSError, ValueError, TypeError):
            continue
        wanted.extend(timing_candidate_tickers(frame))
    wanted = list(dict.fromkeys(wanted))
    frames = history if history is not None else fetch_price_history(wanted, market=market_id)
    stamped_latest = stamp_timing_on_signals(latest, market=market_id, history=frames)
    stamped_latest.to_csv(latest_path, index=False)
    dated = 0
    for path in sorted(screen_dir.glob("signals_*.csv")):
        as_of = _parse_stamp(path.name)
        try:
            frame = pd.read_csv(path)
        except (OSError, ValueError, TypeError):
            continue
        stamped = stamp_timing_on_signals(frame, market=market_id, as_of=as_of, history=frames)
        stamped.to_csv(path, index=False)
        dated += 1
    wait_count = int(
        (stamped_latest.get("timing_signal") == "wait").sum()
        if "timing_signal" in stamped_latest.columns
        else 0
    )
    return {
        "skipped": False,
        "market_id": market_id,
        "tickers_fetched": len(wanted),
        "dated_archives_stamped": dated,
        "latest_wait_count": wait_count,
        "timing_signal_present": "timing_signal" in stamped_latest.columns,
    }


def admitted_buy_tier_rememo_targets(
    library_root: Path,
    policy: dict[str, Any],
    *,
    market_id: str,
) -> dict[str, str]:
    """Body-lag rememo set for one admitted market's current buy-tier (no 21-market spray)."""
    screen_dir = screen_dir_for(Path(library_root), market_id)
    path = screen_dir / "latest_signals.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    if frame.empty or "ticker" not in frame.columns or "signal" not in frame.columns:
        return {}
    buy = frame.loc[frame["signal"].astype(str).str.lower().isin({"buy", "strong_buy"})]
    tickers = [str(t).strip() for t in buy["ticker"].tolist() if str(t).strip()]
    ladder = policy.get("ladder") or {}
    threshold = int(ladder.get("rememo_body_lag_threshold") or DEFAULT_REMEMO_BODY_LAG_THRESHOLD)
    return library_rememo_eligible_tickers(
        Path(library_root),
        tickers=tickers,
        market_id=market_id,
        body_lag_threshold=threshold,
    )


def admitted_buy_tier_first_time_targets(
    library_root: Path,
    *,
    market_id: str,
) -> list[str]:
    """Buy-tier tickers on this market with no ``research.md`` in its screen store."""
    screen_dir = screen_dir_for(Path(library_root), market_id)
    path = screen_dir / "latest_signals.csv"
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    if frame.empty or "ticker" not in frame.columns or "signal" not in frame.columns:
        return []
    buy = frame.loc[frame["signal"].astype(str).str.lower().isin({"buy", "strong_buy"})]
    research = screen_dir / "research"
    missing: list[str] = []
    for raw in buy["ticker"].tolist():
        ticker = str(raw).strip()
        if not ticker:
            continue
        if (research / ticker / "research.md").exists():
            continue
        key = canonical_library_ticker(ticker)
        if research.is_dir() and any(
            entry.is_dir()
            and canonical_library_ticker(entry.name) == key
            and (entry / "research.md").exists()
            for entry in research.iterdir()
        ):
            continue
        missing.append(ticker)
    return missing


def _flatten_equal_support_market(row: dict[str, Any]) -> dict[str, Any]:
    near = row.get("near_miss") if isinstance(row.get("near_miss"), dict) else {}
    rememo = row.get("rememo") if isinstance(row.get("rememo"), dict) else {}
    first = row.get("first_time_memos") if isinstance(row.get("first_time_memos"), dict) else {}
    archives = row.get("archives") if isinstance(row.get("archives"), dict) else {}
    exclusion = archives.get("exclusion") if isinstance(archives.get("exclusion"), dict) else {}
    return {
        **row,
        "buy_tier_not_now_count": near.get("buy_tier_not_now_count"),
        "not_buy_tier_count": near.get("not_buy_tier_count"),
        "hold_near_buy_count": near.get("hold_near_buy_count"),
        "never_buy_tier_count": near.get("never_buy_tier_count"),
        "rememo_eligible_count": rememo.get("eligible_count"),
        "first_time_memo_count": first.get("missing_count"),
        "exclusion_ready_for_priors": exclusion.get("ready_for_priors"),
        "timing_signal_present": (row.get("timing") or {}).get("timing_signal_present")
        if isinstance(row.get("timing"), dict)
        else near.get("timing_signal_present"),
    }


def run_admitted_counterfactual_archives(
    library_root: Path,
    market_id: str,
) -> dict[str, Any]:
    """Run FTSE exclusion + exit-timing labs on this market's screen history."""
    screen_dir = screen_dir_for(Path(library_root), market_id)
    written = save_library_run_snapshots(Path(library_root), market_id)
    exclusion = run_exclusion_universe_archive_sim(screen_dir)
    exit_timing = run_exit_timing_archive_sim(screen_dir)
    return {
        "market_id": market_id,
        "snapshots_written": len(written),
        "exclusion": {
            "snapshot_count": exclusion.get("snapshot_count"),
            "ready_for_priors": (exclusion.get("readiness") or {}).get("ready_for_priors"),
            "universe_mode": exclusion.get("universe_mode"),
        },
        "exit_timing": {
            "snapshot_count": exit_timing.get("snapshot_count"),
            "ready_for_probability_analysis": (
                (exit_timing.get("readiness") or {}).get("ready_for_probability_analysis")
                if isinstance(exit_timing.get("readiness"), dict)
                else None
            ),
        },
    }


def run_equal_support_for_market(
    market_id: str,
    *,
    library_root: Path,
    policy: dict[str, Any],
    stamp_timing: bool = True,
    run_archives: bool = True,
    price_history: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """One admitted market: timing, near-miss groups, counterfactual archives, rememo list."""
    out: dict[str, Any] = {
        "market_id": market_id,
        "ingest_maintenance": True,
        "screen_cadence": True,
        "paper_instrument": "buy_tier_level",
        "ai_judgment": False,
        "knob_apply": False,
    }
    if stamp_timing:
        try:
            out["timing"] = stamp_library_timing_archives(
                library_root, market_id, history=price_history
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Timing stamp for %s failed: %s", market_id, exc)
            out["timing"] = {"skipped": True, "error": str(exc)}
    else:
        out["timing"] = {"skipped": True, "reason": "stamp_timing off"}
    out["near_miss"] = write_library_near_miss_watch(library_root, market_id)
    if run_archives:
        try:
            out["archives"] = run_admitted_counterfactual_archives(library_root, market_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Counterfactual archives for %s failed: %s", market_id, exc)
            out["archives"] = {"error": str(exc)}
    else:
        out["archives"] = {"skipped": True}
    rememo = admitted_buy_tier_rememo_targets(library_root, policy, market_id=market_id)
    out["rememo"] = {
        "eligible_count": len(rememo),
        "body_lag_threshold": int(
            (policy.get("ladder") or {}).get(
                "rememo_body_lag_threshold", DEFAULT_REMEMO_BODY_LAG_THRESHOLD
            )
        ),
        "sample": [{"ticker": t, "reason": rememo[t]} for t in sorted(rememo)[:20]],
        "note": "Same body-lag rule as focus buy-tier; not 21-market memo spray.",
    }
    first_time = admitted_buy_tier_first_time_targets(library_root, market_id=market_id)
    out["first_time_memos"] = {
        "missing_count": len(first_time),
        "sample": first_time[:20],
        "note": (
            "Buy-tier names with no research.md on this market. "
            "Sunday _research_markets prefers these before rememo; no weekday burst."
        ),
    }
    return out


def run_equal_support_package(
    library_root: Path,
    policy: dict[str, Any],
    *,
    markets: list[str] | None = None,
    stamp_timing: bool = True,
    run_archives: bool = True,
    census_only: bool = False,
    price_history: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Apply the admitted-set package. Does not fork AI or apply knobs.

    ``census_only`` refreshes ``equal_support_status.json`` without Yahoo timing
    stamps or archive labs (weekday keep-fresh).
    """
    if census_only:
        stamp_timing = False
        run_archives = False
    wanted = markets or equal_support_markets_for_policy(policy)
    markets_out: dict[str, Any] = {}
    for market_id in wanted:
        markets_out[market_id] = _flatten_equal_support_market(
            run_equal_support_for_market(
                market_id,
                library_root=Path(library_root),
                policy=policy,
                stamp_timing=stamp_timing,
                run_archives=run_archives,
                price_history=price_history,
            )
        )
    payload = {
        "schema_version": 1,
        "scope": "library_equal_support",
        "generated_at": datetime.now(UTC).isoformat(),
        "admitted": wanted,
        "ai_judgment": False,
        "knob_apply": False,
        "markets": markets_out,
    }
    status_path = Path(library_root) / PACKAGE_FILENAME
    write_json(status_path, payload, compact=False)
    payload["path"] = str(status_path)
    return payload


__all__ = [
    "PACKAGE_FILENAME",
    "admitted_buy_tier_first_time_targets",
    "admitted_buy_tier_rememo_targets",
    "equal_support_markets_for_policy",
    "run_admitted_counterfactual_archives",
    "run_equal_support_for_market",
    "run_equal_support_package",
    "stamp_library_timing_archives",
]
