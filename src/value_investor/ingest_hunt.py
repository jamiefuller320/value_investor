"""Hunt one name, hand the artifacts back for a commit, then hunt again.

The FTSE ingest loop already flushes a partial summary when its own runtime
budget ends, so the workflow can commit. The library sprint and maintenance
jobs commit once, at the end. A GitHub job timeout before that step drops the
whole pass. These slices keep the same ceilings (24 names / 2100s on a spare
stream, 3600s for a maintenance slot, 2400s of waiting) and return after one
name so the workflow can commit what was saved.

Maintenance order is holdings, then strategy-book opens that still need a
filing body, then the rotating sample. A name that already has its bodies is
counted as visited and is not downloaded again. Rememo is not part of this
module.

Stream 2 sets ``explore`` only when the seated backlog is idle. Hitting the
clock or the 24-name ceiling leaves the catalogue for a later slot.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.library_ingest_cascade import (
    DEFAULT_SPARE_WAIT_SECONDS,
    load_cascade_config,
    scale_spare_budget,
)
from value_investor.library_ingest_dispatch import FTSE_MAINTENANCE_MAX_RUNTIME_SECONDS
from value_investor.library_ingest_scheduler import FULL_STREAM_RUNTIME, FULL_STREAM_TARGETS

logger = logging.getLogger(__name__)

MIN_SLICE_SECONDS = 45.0
EXPLORE_SKIP_CODES = frozenset({"no_gaps", "empty_strand"})
SPRINT_TARGET_CEILING = FULL_STREAM_TARGETS
SPRINT_RUNTIME_CEILING_SECONDS = FULL_STREAM_RUNTIME
MAINTENANCE_SLOT_SECONDS = FTSE_MAINTENANCE_MAX_RUNTIME_SECONDS
SPARE_WAIT_SECONDS = DEFAULT_SPARE_WAIT_SECONDS

NeedsFetch = Callable[[dict[str, Any]], bool]
Runner = Callable[[dict[str, Any], set[str]], dict[str, Any]]


def spare_budget_when_head_released(
    unfilled: int,
    *,
    stream: int = 2,
    requested_targets: int = SPRINT_TARGET_CEILING,
    requested_runtime: float = SPRINT_RUNTIME_CEILING_SECONDS,
) -> tuple[int, float, str]:
    """Width for a spare stream once the head has released the fat slot.

    The requested ceiling is the cap. A released head does not raise it, and
    it does not cut the spare to a fraction of the ceiling.
    """
    targets, runtime, mode = scale_spare_budget(
        stream,
        requested_targets,
        requested_runtime,
        config=load_cascade_config({}),
        head_needs_fat=False,
        unfilled=unfilled,
    )
    return targets, runtime, mode


def filing_coverage_needs_fetch(coverage: dict[str, Any] | None) -> bool:
    """True when the filing index is missing, empty, or still has a body gap."""
    row = coverage or {}
    total = int(row.get("filings_total") or 0)
    bodies = int(row.get("filings_with_body") or 0)
    indexed_without_body = row.get("indexed_without_body")
    if indexed_without_body is None:
        indexed_without_body = max(total - bodies, 0)
    return total == 0 or bodies == 0 or int(indexed_without_body) > 0


def market_for_holding(ticker: str, strategy_market: str | None = None) -> str:
    if strategy_market:
        return strategy_market
    upper = str(ticker or "").strip().upper()
    if upper.endswith(".L"):
        return "ftse350"
    if upper.endswith(".AX"):
        return "asx200"
    if upper.endswith(".DE"):
        return "dax"
    if upper and "." not in upper:
        return "sp500"
    return ""


def _open_episode(episode: dict[str, Any]) -> bool:
    if str(episode.get("status") or "") != "open":
        return False
    if episode.get("exit_session"):
        return False
    return bool(episode.get("fill_session"))


def build_priority_names(
    *,
    holdings: list[str] | set[str],
    episodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Holdings first, then filled strategy-book opens that are not holdings."""
    strategy_market: dict[str, str] = {}
    for episode in episodes:
        if not isinstance(episode, dict) or not _open_episode(episode):
            continue
        ticker = str(episode.get("ticker") or "").strip().upper()
        market = str(episode.get("market") or "").strip()
        if ticker and market:
            strategy_market.setdefault(ticker, market)
    names: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ticker in sorted({str(item).strip().upper() for item in holdings if str(item).strip()}):
        market = market_for_holding(ticker, strategy_market.get(ticker))
        if not market:
            continue
        names.append({"ticker": ticker, "market": market, "source": "holding"})
        seen.add(ticker)
    opens = [
        {"ticker": ticker, "market": market, "source": "strategy_open"}
        for ticker, market in strategy_market.items()
        if ticker not in seen
    ]
    opens.sort(key=lambda item: item["ticker"])
    return names + opens


def _loop_batch(state: dict[str, Any]) -> dict[str, Any]:
    loops = [row for row in (state.get("loops") or []) if isinstance(row, dict)]
    markets: list[str] = []
    for row in loops:
        market = str(row.get("market_id") or "").strip()
        if market and market not in markets:
            markets.append(market)
    return {"markets": markets, "results": loops, "errors": list(state.get("errors") or [])}


def _common(state: dict[str, Any], *, action: str, explore: bool, reason: str) -> dict[str, Any]:
    return {
        "action": action,
        "explore": explore,
        "reason": reason,
        "priority_considered": int(state.get("priority_considered") or 0),
        "priority_fresh": int(state.get("priority_fresh") or 0),
        "attempted": list(state.get("attempted") or []),
        "loop_batch": _loop_batch(state),
    }


def _budget_spent(deadline_epoch: float | None) -> bool:
    if deadline_epoch is None:
        return False
    return time.time() + MIN_SLICE_SECONDS > float(deadline_epoch)


def advance_maintenance(
    state: dict[str, Any],
    *,
    priority: list[dict[str, Any]],
    needs_fetch: NeedsFetch,
    sample_markets: list[str],
    runner: Runner,
    deadline_epoch: float | None = None,
) -> dict[str, Any]:
    """One maintenance name: a gapped holding or open, else the rotating sample."""
    if not state.get("built"):
        queue = [dict(name) for name in priority if needs_fetch(name)]
        state["built"] = True
        state["queue"] = queue
        state["sample"] = list(sample_markets)
        state["sample_i"] = 0
        state["attempted"] = []
        state["loops"] = []
        state["results"] = []
        state["errors"] = []
        state["priority_considered"] = len(priority)
        state["priority_fresh"] = len(priority) - len(queue)
    if _budget_spent(deadline_epoch):
        return _common(state, action="idle", explore=False, reason="budget_spent")

    queue = state.get("queue") or []
    while queue:
        item = queue.pop(0)
        ticker = str(item.get("ticker") or "")
        if ticker and ticker in state["attempted"]:
            continue
        outcome = runner(item, set(state["attempted"]))
        if ticker:
            state["attempted"].append(ticker)
        if int(outcome.get("targets") or 0) <= 0:
            if outcome.get("error"):
                state["errors"].append(str(outcome["error"]))
            continue
        _remember(state, item, outcome)
        payload = _common(state, action="ran", explore=False, reason="priority")
        payload.update(_ran_fields(item, outcome))
        return payload

    sample: list[str] = list(state.get("sample") or [])
    while int(state.get("sample_i") or 0) < len(sample):
        index = int(state["sample_i"])
        market = sample[index]
        item = {"ticker": None, "market": market, "source": "sample"}
        outcome = runner(item, set(state["attempted"]))
        ticker = str(outcome.get("ticker") or "")
        if int(outcome.get("targets") or 0) <= 0 or not ticker or ticker in state["attempted"]:
            state["sample_i"] = index + 1
            if outcome.get("error"):
                state["errors"].append(str(outcome["error"]))
            continue
        state["attempted"].append(ticker)
        item["ticker"] = ticker
        _remember(state, item, outcome)
        payload = _common(state, action="ran", explore=False, reason="sample")
        payload.update(_ran_fields(item, outcome))
        return payload
    return _common(state, action="idle", explore=False, reason="maintenance_idle")


def _remember(state: dict[str, Any], item: dict[str, Any], outcome: dict[str, Any]) -> None:
    loop = outcome.get("loop")
    if isinstance(loop, dict):
        state.setdefault("loops", []).append(loop)
    state.setdefault("results", []).append(
        {
            "source": item.get("source"),
            "market": outcome.get("market") or item.get("market"),
            "ticker": outcome.get("ticker") or item.get("ticker"),
            "seconds": outcome.get("seconds"),
            "runtime_cutoff": bool(outcome.get("runtime_cutoff")),
        }
    )


def _ran_fields(item: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": outcome.get("ticker") or item.get("ticker"),
        "market": outcome.get("market") or item.get("market"),
        "source": item.get("source"),
        "seconds": outcome.get("seconds"),
    }


def advance_sprint(
    state: dict[str, Any],
    *,
    stream: int,
    ceiling: int,
    runtime_ceiling: float,
    runner: Callable[[set[str]], dict[str, Any]],
    deadline_epoch: float | None = None,
    explore_when_empty: bool = False,
) -> dict[str, Any]:
    """One spare-stream name, stopping at the existing name ceiling or the clock."""
    state.setdefault("attempted", [])
    state.setdefault("loops", [])
    state.setdefault("errors", [])
    ceilings = {
        "targets_ceiling": int(ceiling),
        "runtime_ceiling_seconds": float(runtime_ceiling),
    }
    if _budget_spent(deadline_epoch):
        payload = _common(state, action="idle", explore=False, reason="budget_spent")
        payload.update(ceilings)
        return payload
    if len(state["attempted"]) >= max(0, int(ceiling)):
        payload = _common(state, action="idle", explore=False, reason="ceiling")
        payload.update(ceilings)
        return payload
    outcome = runner(set(state["attempted"]))
    for ticker in outcome.get("also_attempted") or []:
        token = str(ticker or "")
        if token and token not in state["attempted"]:
            state["attempted"].append(token)
    if int(outcome.get("targets") or 0) <= 0 or not outcome.get("ticker"):
        if outcome.get("error"):
            state["errors"].append(str(outcome["error"]))
        payload = _common(
            state,
            action="idle",
            explore=bool(explore_when_empty),
            reason="backlog_idle",
        )
        payload.update(ceilings)
        return payload
    ticker = str(outcome["ticker"])
    if ticker not in state["attempted"]:
        state["attempted"].append(ticker)
    item = {
        "ticker": ticker,
        "market": outcome.get("market"),
        "source": "sprint",
    }
    _remember(state, item, outcome)
    payload = _common(state, action="ran", explore=False, reason="sprint")
    payload.update(ceilings)
    payload.update(_ran_fields(item, outcome))
    return payload


def finish_maintenance_hunt(state: dict[str, Any], *, library_root: Path) -> dict[str, Any]:
    """Record the slot and advance the sample cursor. Does not enable matrix."""
    from value_investor.library_maintenance_capacity import (
        load_maintenance_capacity,
        record_maintenance_capacity_sample,
        review_maintenance_capacity,
    )
    from value_investor.library_maintenance_stagger import write_maintenance_slot_cursor

    root = Path(library_root)
    results = [row for row in (state.get("results") or []) if isinstance(row, dict)]
    sample_markets: list[str] = []
    for row in results:
        if row.get("source") != "sample":
            continue
        market = str(row.get("market") or "")
        if market and market not in sample_markets:
            sample_markets.append(market)
    cursor_written = False
    if sample_markets:
        write_maintenance_slot_cursor(
            root,
            last_head=sample_markets[-1],
            selected=sample_markets,
            deferred=[],
        )
        cursor_written = True
    recorded = False
    if results:
        outcome = {
            "run_at": datetime.now(UTC).isoformat(),
            "results": [
                {
                    "used_seconds": row.get("seconds"),
                    "targets": [row.get("ticker")] if row.get("ticker") else [],
                    "runtime_cutoff": bool(row.get("runtime_cutoff")),
                }
                for row in results
            ],
            "markets": sample_markets,
            "configured_markets": list(state.get("sample") or []),
            "deferred_markets": [],
            "stagger": {"max_markets_when_crowded": 3, "staggered": True},
            "errors": list(state.get("errors") or []),
        }
        record_maintenance_capacity_sample(root, outcome)
        review_maintenance_capacity(root, apply=True)
        recorded = True
    capacity = load_maintenance_capacity(root)
    matrix = capacity.get("matrix_parallel") if isinstance(capacity, dict) else {}
    enabled = bool((matrix or {}).get("enabled"))
    return {
        "cursor_written": cursor_written,
        "capacity_recorded": recorded,
        "matrix_parallel_enabled": enabled,
        "last_head": sample_markets[-1] if sample_markets else None,
    }


def _coverage_needs_fetch(name: dict[str, Any], *, library_root: Path, data_dir: Path) -> bool:
    ticker = str(name.get("ticker") or "")
    market = str(name.get("market") or "")
    try:
        if market == "ftse350":
            from value_investor.research.filings import filings_index_coverage

            coverage = filings_index_coverage(
                data_dir / "research" / ticker / "sources" / "filings"
            )
            return filing_coverage_needs_fetch(coverage)
        from value_investor.library_ingest_loop import _filing_coverage_for_ticker

        coverage = _filing_coverage_for_ticker(
            ticker,
            library_root=library_root,
            market_id=market,
        )
        return filing_coverage_needs_fetch(coverage)
    except Exception as exc:  # noqa: BLE001 — a lookup failure still visits the name
        logger.warning("Filing coverage lookup failed for %s/%s: %s", market, ticker, exc)
        return True


def _load_priority(data_dir: Path) -> list[dict[str, Any]]:
    from value_investor.decision_input_inventory import load_paper_holdings
    from value_investor.storage import read_json

    holdings = sorted(load_paper_holdings())
    path = data_dir / "strategy_book_observe.json"
    episodes: list[dict[str, Any]] = []
    if path.exists():
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            payload = {}
        if isinstance(payload, dict) and isinstance(payload.get("episodes"), list):
            episodes = [row for row in payload["episodes"] if isinstance(row, dict)]
    return build_priority_names(holdings=holdings, episodes=episodes)


def _remaining(deadline_epoch: float | None, fallback: float) -> float:
    if deadline_epoch is None:
        return max(1.0, float(fallback))
    return max(1.0, float(deadline_epoch) - time.time())


def _maintenance_runner(
    item: dict[str, Any],
    exclude: set[str],
    *,
    library_root: Path,
    max_bodies: int,
    deadline_epoch: float | None,
    slot_runtime: float,
) -> dict[str, Any]:
    from value_investor.ingest_loop import run_weekday_ingest_loop
    from value_investor.library_ingest_loop import run_library_ingest_loop

    runtime = _remaining(deadline_epoch, slot_runtime)
    market = str(item.get("market") or "")
    ticker = str(item.get("ticker") or "")
    started = time.perf_counter()
    if item.get("source") == "sample":
        chosen = _next_library_gap_ticker(market, library_root=library_root, exclude=exclude)
        if not chosen:
            return {"targets": 0, "market": market}
        ticker = chosen
    if not ticker:
        return {"targets": 0, "market": market}
    if market == "ftse350":
        result = run_weekday_ingest_loop(
            pin_tickers=[ticker],
            max_targets=1,
            max_runtime_seconds=runtime,
            max_bodies=max_bodies,
            market="ftse350",
        )
        summary = getattr(result, "ingest_summary", None)
        targets = []
        if summary is not None:
            for target in getattr(summary, "targets", None) or []:
                token = getattr(target, "ticker", None)
                if token is None and isinstance(target, dict):
                    token = target.get("ticker")
                if token:
                    targets.append(str(token))
        loop = result.to_dict()
        loop["market_id"] = "ftse350"
        got = len(targets)
        return {
            "targets": got,
            "ticker": targets[0] if targets else ticker,
            "market": market,
            "seconds": round(time.perf_counter() - started, 3),
            "loop": loop,
            "runtime_cutoff": bool(getattr(result, "partial", False)),
        }
    result = run_library_ingest_loop(
        market,
        library_root=library_root,
        max_targets=1,
        max_runtime_seconds=runtime,
        max_bodies=max_bodies,
        pin_tickers=[ticker],
        discovery_scan=False,
        maintenance_mode=True,
    )
    loop = result.to_dict()
    targets = [str(token) for token in (loop.get("targets") or []) if token]
    return {
        "targets": len(targets),
        "ticker": targets[0] if targets else "",
        "market": market,
        "seconds": round(result.used_seconds or (time.perf_counter() - started), 3),
        "loop": loop,
        "runtime_cutoff": bool(result.runtime_cutoff),
    }


def _next_library_gap_ticker(
    market: str,
    *,
    library_root: Path,
    exclude: set[str],
) -> str | None:
    from value_investor.library_ingest_loop import (
        load_library_buy_tier_reports,
        select_library_ingest_targets,
    )

    reports = load_library_buy_tier_reports(library_root, market)
    if not reports:
        return None
    blocked = {token.upper() for token in exclude}
    chosen = select_library_ingest_targets(
        reports,
        library_root=library_root,
        market_id=market,
        max_targets=min(60, len(blocked) + 5),
        gap_only=True,
    )
    for target in chosen:
        if str(target.ticker).upper() not in blocked:
            return str(target.ticker)
    return None


def _sample_markets(
    *,
    library_root: Path,
    policy_path: Path,
    markets: list[str] | None,
) -> list[str]:
    from value_investor.agent_model_policy import load_policy
    from value_investor.library_ingest_dispatch import list_library_ingest_maintenance_markets
    from value_investor.library_maintenance_stagger import plan_maintenance_slot

    if markets:
        return list(markets)
    policy = load_policy(policy_path)
    configured = list_library_ingest_maintenance_markets(library_root=library_root, policy=policy)
    slot = plan_maintenance_slot(configured, library_root=library_root)
    return [str(market) for market in (slot.get("selected") or []) if str(market).strip()]


def maintenance_slice(
    state: dict[str, Any],
    *,
    library_root: Path,
    policy_path: Path,
    data_dir: Path,
    markets: list[str] | None,
    max_bodies: int,
    slot_runtime: float,
    deadline_epoch: float | None,
) -> dict[str, Any]:
    if not state.get("built"):
        priority = _load_priority(data_dir)
        sample = _sample_markets(
            library_root=library_root,
            policy_path=policy_path,
            markets=markets,
        )

        def needs_fetch(name: dict[str, Any]) -> bool:
            return _coverage_needs_fetch(name, library_root=library_root, data_dir=data_dir)

    else:
        priority = []
        sample = []

        def needs_fetch(name: dict[str, Any]) -> bool:
            del name
            return False

    def runner(item: dict[str, Any], exclude: set[str]) -> dict[str, Any]:
        return _maintenance_runner(
            item,
            exclude,
            library_root=library_root,
            max_bodies=max_bodies,
            deadline_epoch=deadline_epoch,
            slot_runtime=slot_runtime,
        )

    payload = advance_maintenance(
        state,
        priority=priority,
        needs_fetch=needs_fetch,
        sample_markets=sample,
        runner=runner,
        deadline_epoch=deadline_epoch,
    )
    payload["lane"] = "maintenance"
    payload["runtime_ceiling_seconds"] = float(slot_runtime)
    return payload


def plan_sprint_from_disk(
    *,
    library_root: Path,
    policy_path: Path,
    stream: int,
    markets: list[str] | None,
    max_targets: int,
    max_runtime_seconds: float,
    head_idle: bool,
) -> dict[str, Any]:
    """Same scheduler decision the sprint command uses, for one-name slices."""
    from value_investor.agent_model_policy import load_policy
    from value_investor.library_ingest_cascade import filing_names_unfilled
    from value_investor.library_ingest_dispatch import (
        list_library_ingest_parallel_sprint_markets,
        sprint_expansion_market_order,
        sprint_ingest_complete,
    )
    from value_investor.library_ingest_escalation import snapshot_library_buy_tier_filing_health
    from value_investor.library_ingest_scheduler import evaluate_scheduler, load_runtime_state
    from value_investor.library_ingest_sprint import parallel_sprint_markets_needing_ingest

    try:
        from value_investor.library_ingest_maintenance import reconcile_parallel_sprint_queues

        reconcile_parallel_sprint_queues(library_root=library_root, policy_path=policy_path)
    except Exception as exc:  # noqa: BLE001 — reconcile is best-effort, as in the sprint command
        logger.warning("Parallel sprint queue reconcile failed: %s", exc)

    policy = load_policy(policy_path)
    head_id = str(policy.get("focus_market") or "").strip() or "euro_depth"
    head_health = snapshot_library_buy_tier_filing_health(
        head_id, library_root=library_root, policy=policy
    )
    phase2_ready = False
    try:
        from value_investor.market_shard_phases import evaluate_market_phase

        phase2_ready = bool(
            evaluate_market_phase(head_id, library_root=library_root, policy=policy).get(
                "phase2_ready"
            )
        )
    except Exception:  # noqa: BLE001
        phase2_ready = False
    needing = markets or parallel_sprint_markets_needing_ingest(
        library_root=library_root,
        policy=policy,
        parallel_stream=stream,
    )
    if markets is None:
        seated = list_library_ingest_parallel_sprint_markets(policy=policy, parallel_stream=stream)
        for name in sprint_expansion_market_order(policy):
            if not name or name == head_id or name in seated:
                continue
            health = snapshot_library_buy_tier_filing_health(
                name, library_root=library_root, policy=policy
            )
            if not sprint_ingest_complete(health) and name not in needing:
                needing = list(dict.fromkeys([*needing, name]))
    unfilled_by_market: dict[str, int] = {}
    for market_id in needing:
        spare_health = snapshot_library_buy_tier_filing_health(
            market_id, library_root=library_root, policy=policy
        )
        unfilled_by_market[market_id] = filing_names_unfilled(spare_health)
    head_open = not sprint_ingest_complete(head_health)
    decision = evaluate_scheduler(
        stream,
        policy=policy,
        head_at_parity=not head_open,
        needing_markets=list(needing),
        requested_targets=max_targets,
        requested_runtime=max_runtime_seconds,
        head_in_progress=False if head_idle else None,
        phase2_ready=phase2_ready,
        leftover_state=load_runtime_state(library_root / "ingest_cascade_runtime.json"),
        head_unfilled_names=filing_names_unfilled(head_health) if head_open else 0,
        unfilled_by_market=unfilled_by_market,
    )
    ceiling = min(int(decision.max_targets), int(max_targets))
    runtime = min(float(decision.max_runtime_seconds), float(max_runtime_seconds))
    return {
        "action": decision.action,
        "code": decision.code,
        "markets": [str(market) for market in decision.markets if str(market).strip()],
        "max_targets": ceiling,
        "max_runtime_seconds": runtime,
        "reason": decision.reason,
    }


def _fetch_one_sprint(
    markets: list[str],
    exclude: set[str],
    *,
    library_root: Path,
    max_bodies: int,
    deadline_epoch: float | None,
    runtime_ceiling: float,
) -> dict[str, Any]:
    from value_investor.library_ingest_loop import run_library_ingest_loop

    skipped: list[str] = []
    blocked = {token.upper() for token in exclude}
    for market in markets:
        if _budget_spent(deadline_epoch):
            break
        while len(skipped) < 30:
            ticker = _next_library_gap_ticker(
                market,
                library_root=library_root,
                exclude=blocked,
            )
            if not ticker:
                break
            started = time.perf_counter()
            result = run_library_ingest_loop(
                market,
                library_root=library_root,
                max_targets=1,
                max_runtime_seconds=_remaining(deadline_epoch, runtime_ceiling),
                max_bodies=max_bodies,
                pin_tickers=[ticker],
                discovery_scan=False,
            )
            loop = result.to_dict()
            targets = [str(token) for token in (loop.get("targets") or []) if token]
            if not targets:
                skipped.append(ticker)
                blocked.add(ticker.upper())
                continue
            return {
                "targets": len(targets),
                "ticker": targets[0],
                "market": market,
                "seconds": round(result.used_seconds or (time.perf_counter() - started), 3),
                "loop": loop,
                "runtime_cutoff": bool(result.runtime_cutoff),
                "also_attempted": skipped,
            }
    return {"targets": 0, "also_attempted": skipped}


def sprint_slice(
    state: dict[str, Any],
    *,
    library_root: Path,
    policy_path: Path,
    stream: int,
    markets: list[str] | None,
    max_targets: int,
    max_runtime_seconds: float,
    max_bodies: int,
    head_idle: bool,
    deadline_epoch: float | None,
    planner: Callable[[], dict[str, Any]] | None = None,
    fetch_one: Callable[[list[str], set[str], float], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not state.get("planned"):
        plan = (
            planner()
            if planner is not None
            else plan_sprint_from_disk(
                library_root=library_root,
                policy_path=policy_path,
                stream=stream,
                markets=markets,
                max_targets=max_targets,
                max_runtime_seconds=max_runtime_seconds,
                head_idle=head_idle,
            )
        )
        plan["max_targets"] = min(int(plan.get("max_targets") or 0), int(max_targets))
        plan["max_runtime_seconds"] = min(
            float(plan.get("max_runtime_seconds") or 0.0),
            float(max_runtime_seconds),
        )
        state["planned"] = True
        state["plan"] = plan
        state.setdefault("attempted", [])
        state.setdefault("loops", [])
    plan = state.get("plan") or {}
    ceiling = int(plan.get("max_targets") or 0)
    runtime_ceiling = float(plan.get("max_runtime_seconds") or max_runtime_seconds)
    if str(plan.get("action") or "") != "run":
        code = str(plan.get("code") or plan.get("action") or "skip")
        payload = _common(
            state,
            action="idle",
            explore=int(stream) == 2 and code in EXPLORE_SKIP_CODES,
            reason=code,
        )
        payload["targets_ceiling"] = ceiling
        payload["runtime_ceiling_seconds"] = runtime_ceiling
        payload["lane"] = "sprint"
        return payload

    def runner(exclude: set[str]) -> dict[str, Any]:
        if fetch_one is not None:
            return fetch_one(list(plan.get("markets") or []), exclude, runtime_ceiling)
        return _fetch_one_sprint(
            list(plan.get("markets") or []),
            exclude,
            library_root=library_root,
            max_bodies=max_bodies,
            deadline_epoch=deadline_epoch,
            runtime_ceiling=runtime_ceiling,
        )

    payload = advance_sprint(
        state,
        stream=stream,
        ceiling=ceiling,
        runtime_ceiling=runtime_ceiling,
        runner=runner,
        deadline_epoch=deadline_epoch,
        explore_when_empty=int(stream) == 2,
    )
    payload["lane"] = "sprint"
    return payload
