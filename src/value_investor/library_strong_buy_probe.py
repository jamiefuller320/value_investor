"""Strong-buy-first metrics probe for the offline library ladder (L153).

When the engineering queue is idle, re-fetch metrics for offline screen
strong_buy/buy names so provider failures surface early and can draft coverage
tasks — without cloning FTSE filing ingest onto non-UK markets.
"""

from __future__ import annotations

import csv
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import (
    DEFAULT_LIBRARY_ROOT,
    load_manifest,
    market_dir,
    refresh_metrics,
)
from value_investor.library_grow_health import (
    has_open_library_coverage_tasks,
    snapshot_focus_market_health,
)
from value_investor.library_sim import observe_sim_markets_for_policy
from value_investor.market_shard_phases import weekly_paper_shard_markets_for_policy
from value_investor.storage import read_json

logger = logging.getLogger(__name__)

BUY_TIER_SIGNALS = ("strong_buy", "buy")
DEFAULT_PROBE_MAX_TICKERS = 25
DEFAULT_PROBE_MAX_MARKETS = 4
DEFAULT_TASKS_PATH = Path("docs/data/engineering_tasks.json")


def engineering_queue_is_idle(
    tasks_path: Path = DEFAULT_TASKS_PATH,
) -> bool:
    """True when no open or in-flight (pr_open) engineering tasks remain."""
    from value_investor.engineering_tasks import load_engineering_tasks

    if not Path(tasks_path).exists():
        return True
    rows = list(load_engineering_tasks(tasks_path).get("tasks") or [])
    for row in rows:
        status = str(row.get("status") or "open")
        if status in {"open", "pr_open"}:
            return False
    return True


def latest_screen_signals_path(root: Path, market_id: str) -> Path | None:
    screen_dir = market_dir(root, market_id) / "screen"
    if not screen_dir.is_dir():
        return None
    archives = sorted(screen_dir.glob("signals_*.csv"))
    return archives[-1] if archives else None


def load_buy_tier_tickers_from_screen(
    root: Path,
    market_id: str,
) -> dict[str, Any]:
    """Return strong_buy then buy ticker lists from the latest screen-lite CSV."""
    path = latest_screen_signals_path(root, market_id)
    if path is None:
        return {"strong_buy": [], "buy": []}
    strong_buy: list[str] = []
    buy: list[str] = []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                signal = str(row.get("signal") or "").strip()
                ticker = str(row.get("ticker") or "").strip()
                if not ticker or signal not in BUY_TIER_SIGNALS:
                    continue
                if signal == "strong_buy":
                    strong_buy.append(ticker)
                else:
                    buy.append(ticker)
    except (OSError, csv.Error) as exc:
        logger.warning("Failed reading screen signals for %s: %s", market_id, exc)
        return {"strong_buy": [], "buy": []}
    return {
        "strong_buy": list(dict.fromkeys(strong_buy)),
        "buy": list(dict.fromkeys(buy)),
        "signals_path": str(path),
    }


def _ticker_has_metric_errors(row: dict[str, Any] | None) -> bool:
    if not row:
        return True
    errors = row.get("errors")
    if errors:
        return True
    # Thin / failed fetch rows usually lack core fundamentals
    if row.get("trailing_pe") is None and row.get("market_cap") is None:
        return True
    return False


def _manifest_failed_tickers(manifest: dict[str, Any]) -> set[str]:
    failed: set[str] = set()
    state = manifest.get("ticker_state") or {}
    for ticker, entry in state.items():
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("fetch_status") or "").lower()
        if status in {"failed", "error", "fail"}:
            failed.add(str(ticker))
        if entry.get("errors"):
            failed.add(str(ticker))
    return failed


def prioritize_probe_tickers(
    root: Path,
    market_id: str,
    *,
    strong_buy: list[str],
    buy: list[str],
    max_tickers: int,
) -> list[str]:
    """
    Order candidates: errored/failed strong_buys → other strong_buys →
    errored buys → other buys. Cap at ``max_tickers``.
    """
    manifest = load_manifest(root, market_id)
    failed = _manifest_failed_tickers(manifest)
    metrics_path = market_dir(root, market_id) / "metrics" / "latest.json.gz"
    by_metrics: dict[str, dict[str, Any]] = {}
    if metrics_path.exists() or metrics_path.with_suffix("").exists():
        try:
            for row in read_json(metrics_path):
                ticker = str(row.get("ticker") or "")
                if ticker:
                    by_metrics[ticker] = row
        except (OSError, ValueError, TypeError, FileNotFoundError):
            by_metrics = {}

    def _split(tickers: list[str]) -> tuple[list[str], list[str]]:
        bad: list[str] = []
        ok: list[str] = []
        for ticker in tickers:
            row = by_metrics.get(ticker)
            if ticker in failed or _ticker_has_metric_errors(row):
                bad.append(ticker)
            else:
                ok.append(ticker)
        return bad, ok

    sb_bad, sb_ok = _split(strong_buy)
    buy_bad, buy_ok = _split(buy)
    ordered = list(dict.fromkeys([*sb_bad, *sb_ok, *buy_bad, *buy_ok]))
    return ordered[: max(0, int(max_tickers))]


def probe_markets_for_policy(
    policy: dict[str, Any],
    *,
    root: Path = DEFAULT_LIBRARY_ROOT,
    max_markets: int = DEFAULT_PROBE_MAX_MARKETS,
) -> list[str]:
    """Phase-2 weekly markets first, then observe-sim markets with a screen archive."""
    ordered: list[str] = []
    for mid in weekly_paper_shard_markets_for_policy(policy):
        if mid and mid not in ordered:
            ordered.append(mid)
    for mid in observe_sim_markets_for_policy(policy):
        if mid and mid not in ordered:
            ordered.append(mid)
    with_screen = [mid for mid in ordered if latest_screen_signals_path(root, mid) is not None]
    return with_screen[: max(0, int(max_markets))]


def draft_coverage_from_probe_market(
    market_id: str,
    *,
    root: Path,
    policy_path: Path,
    tasks_path: Path,
    health: dict[str, Any],
    probe_errors: int,
) -> dict[str, Any]:
    """Draft a coverage task when the probe surfaces fetch/metrics failures."""
    if probe_errors <= 0 and not health.get("latent_failure"):
        failed = int(health.get("failed_fetch_count") or 0)
        usable = int(health.get("usable_metrics_rows") or 0)
        tickers = int(health.get("ticker_count") or 0)
        if failed <= 0 and not (tickers > 0 and usable == 0):
            return {"drafted_count": 0, "reason": "no probe failures"}

    if has_open_library_coverage_tasks(tasks_path, market_id=market_id):
        return {
            "drafted_count": 0,
            "reason": f"open library coverage task already exists for {market_id}",
        }

    from value_investor.engineering_tasks import draft_library_ladder_engineering_tasks

    ladder_result = {
        "run_at": datetime.now(UTC).isoformat(),
        "focus_market": market_id,
        "layers": {
            "fundamentals": {"status": [{"market": market_id}]},
            "screen_lite": {
                "skipped": True,
                "reason": "strong_buy_metrics_probe_failures",
                "usable_metrics_rows": health.get("usable_metrics_rows"),
                "manifest_coverage_count": health.get("manifest_coverage_count"),
            },
        },
    }
    drafted = draft_library_ladder_engineering_tasks(
        ladder_result,
        root=root,
        policy_path=policy_path,
        tasks_path=tasks_path,
        committed_path=tasks_path,
        max_tasks=1,
    )
    return {
        "drafted_count": int(drafted.get("drafted_count") or 0),
        "task_ids": list(drafted.get("task_ids") or []),
        "market": market_id,
        "source": "strong_buy_metrics_probe",
    }


def run_strong_buy_metrics_probe(
    root: Path,
    policy: dict[str, Any],
    *,
    policy_path: Path | None = None,
    tasks_path: Path = DEFAULT_TASKS_PATH,
    fetch_fn: Any | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ladder layer: re-fetch metrics for offline buy-tier names when eng queue is idle.

    Policy knobs (under ``ladder``):
    - strong_buy_metrics_probe_after_maintenance (default True)
    - strong_buy_metrics_probe_when_eng_idle (default True)
    - strong_buy_metrics_probe_max_tickers (default 25)
    - strong_buy_metrics_probe_max_markets (default 4)
    """
    from value_investor.agent_model_policy import DEFAULT_POLICY_PATH

    policy_path = policy_path or DEFAULT_POLICY_PATH
    ladder = policy.get("ladder") or {}
    if not ladder.get("strong_buy_metrics_probe_after_maintenance", True):
        return {"skipped": True, "reason": "strong_buy_metrics_probe_after_maintenance is off"}

    require_idle = bool(ladder.get("strong_buy_metrics_probe_when_eng_idle", True))
    idle = engineering_queue_is_idle(tasks_path)
    if require_idle and not idle and not force:
        return {
            "skipped": True,
            "reason": "engineering queue not idle",
            "engineering_idle": False,
        }

    max_tickers = int(
        ladder.get("strong_buy_metrics_probe_max_tickers") or DEFAULT_PROBE_MAX_TICKERS
    )
    max_markets = int(
        ladder.get("strong_buy_metrics_probe_max_markets") or DEFAULT_PROBE_MAX_MARKETS
    )
    markets = probe_markets_for_policy(policy, root=root, max_markets=max_markets)
    if not markets:
        return {
            "skipped": True,
            "reason": "no Phase-2/observe markets with screen archives",
            "engineering_idle": idle,
        }

    markets_out: dict[str, Any] = {}
    drafted_ids: list[str] = []
    total_selected = 0
    total_errors = 0

    for market_id in markets:
        bands = load_buy_tier_tickers_from_screen(root, market_id)
        selected = prioritize_probe_tickers(
            root,
            market_id,
            strong_buy=list(bands.get("strong_buy") or []),
            buy=list(bands.get("buy") or []),
            max_tickers=max_tickers,
        )
        if not selected:
            markets_out[market_id] = {
                "skipped": True,
                "reason": "no buy-tier tickers on latest screen",
                "signals_path": bands.get("signals_path"),
            }
            continue
        try:
            grew = refresh_metrics(
                root,
                market_id,
                max_tickers=len(selected),
                only_tickers=selected,
                fetch_fn=fetch_fn,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Strong-buy metrics probe failed for %s: %s", market_id, exc)
            markets_out[market_id] = {"error": str(exc), "selected": selected}
            continue

        errors = int(grew.get("errors") or 0)
        total_selected += len(selected)
        total_errors += errors
        health = snapshot_focus_market_health(
            root=root, policy_path=policy_path, market_id=market_id
        )
        draft: dict[str, Any] = {"drafted_count": 0}
        if errors > 0 or health.get("latent_failure") or int(health.get("failed_fetch_count") or 0) > 0:
            # Only draft one coverage task per ladder run.
            if not drafted_ids:
                draft = draft_coverage_from_probe_market(
                    market_id,
                    root=root,
                    policy_path=policy_path,
                    tasks_path=tasks_path,
                    health=health,
                    probe_errors=errors,
                )
                drafted_ids.extend(str(x) for x in draft.get("task_ids") or [])

        markets_out[market_id] = {
            "selected": selected,
            "strong_buy_count": len(bands.get("strong_buy") or []),
            "buy_count": len(bands.get("buy") or []),
            "updated": grew.get("updated"),
            "errors": errors,
            "signals_path": bands.get("signals_path"),
            "health": {
                "usable_metrics_rows": health.get("usable_metrics_rows"),
                "failed_fetch_count": health.get("failed_fetch_count"),
                "latent_failure": health.get("latent_failure"),
                "sample_errors": health.get("sample_errors"),
            },
            "draft": draft,
        }

    return {
        "skipped": False,
        "engineering_idle": idle,
        "markets": markets_out,
        "market_ids": markets,
        "max_tickers": max_tickers,
        "total_selected": total_selected,
        "total_errors": total_errors,
        "drafted_task_ids": drafted_ids,
    }


__all__ = [
    "BUY_TIER_SIGNALS",
    "DEFAULT_PROBE_MAX_MARKETS",
    "DEFAULT_PROBE_MAX_TICKERS",
    "draft_coverage_from_probe_market",
    "engineering_queue_is_idle",
    "latest_screen_signals_path",
    "load_buy_tier_tickers_from_screen",
    "prioritize_probe_tickers",
    "probe_markets_for_policy",
    "run_strong_buy_metrics_probe",
]
