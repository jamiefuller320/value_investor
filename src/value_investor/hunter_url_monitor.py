"""Monitor merged hunter allowlist URLs and repair or re-queue on rot."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import load_policy
from value_investor.engineering_tasks import (
    BLOCKED_PATHS,
    COMMITTED_TASKS_PATH,
    HUNTER_URL_REPAIR_SOURCE,
    PARKED_SOURCE_HUNTER_PRIORITY_SCORE,
    EngineeringTask,
    _allowed_paths_for_area,
    _merge_task_rows,
    _next_engineering_seq_from_rows,
    load_engineering_tasks,
)
from value_investor.hunter_auto_merge import (
    HunterResolution,
    default_filings_path,
    hunter_task_ticker,
    hunter_ticker_resolution_in_filings,
    is_parked_source_hunter_task,
    live_fetch_hunter_urls,
)
from value_investor.storage import write_json

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_MARKET_IDS = ("euro_depth",)
FILINGS_PATH = Path("src/value_investor/research/filings.py")
CANONICAL_ASSIGN = "_IR_ALLOWLIST_URL_CANONICAL: dict[str, str] = {"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def hunter_url_monitor_policy() -> dict[str, Any]:
    engineering = load_policy().get("engineering") or {}
    block = engineering.get("hunter_url_monitor") or {}
    enabled = block.get("enabled")
    if enabled is None:
        enabled = True
    try:
        lookback_days = max(1, int(block.get("lookback_days") or DEFAULT_LOOKBACK_DAYS))
    except (TypeError, ValueError):
        lookback_days = DEFAULT_LOOKBACK_DAYS
    raw_markets = block.get("market_ids")
    if isinstance(raw_markets, list) and raw_markets:
        market_ids = tuple(str(row).strip() for row in raw_markets if str(row).strip())
    else:
        market_ids = DEFAULT_MARKET_IDS
    return {
        "enabled": bool(enabled),
        "lookback_days": lookback_days,
        "market_ids": market_ids,
    }


def allowlist_urls_for_ticker(ticker: str, *, filings_path: Path) -> list[str]:
    from value_investor.hunter_auto_merge import _parse_builtin_urls

    text = filings_path.read_text(encoding="utf-8")
    return list(_parse_builtin_urls(text).get(str(ticker or "").strip().upper()) or [])


def canonical_replacement_url(url: str, *, ticker: str) -> str | None:
    from value_investor.research.filings import _resolve_ir_allowlist_canonical

    cleaned = str(url or "").strip()
    if not cleaned:
        return None
    replacement = _resolve_ir_allowlist_canonical(cleaned, ticker)
    if replacement and replacement != cleaned:
        return replacement
    return None


def apply_known_canonical_allowlist_repair(
    *,
    ticker: str,
    old_url: str,
    new_url: str,
    filings_path: Path,
    apply: bool = True,
) -> dict[str, Any]:
    """Swap a dead allowlist URL for its known canonical replacement in filings.py."""
    old_url = str(old_url or "").strip()
    new_url = str(new_url or "").strip()
    if not old_url or not new_url or old_url == new_url:
        return {"applied": False, "reason": "invalid_urls"}
    if canonical_replacement_url(old_url, ticker=ticker) != new_url:
        return {"applied": False, "reason": "replacement_not_in_canonical_map"}

    filings_path = Path(filings_path)
    if not filings_path.exists():
        return {"applied": False, "reason": "filings_missing"}

    text = filings_path.read_text(encoding="utf-8")
    if f'"{old_url}"' not in text:
        return {"applied": False, "reason": "old_url_not_in_filings"}

    new_text = text
    canonical_key = f'"{old_url}":'
    if canonical_key not in new_text:
        marker = CANONICAL_ASSIGN
        idx = new_text.find(marker)
        if idx >= 0:
            insert_at = idx + len(marker)
            snippet = f'\n    "{old_url}": (\n        "{new_url}"\n    ),'
            new_text = new_text[:insert_at] + snippet + new_text[insert_at:]

    lines: list[str] = []
    for line in new_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f'"{old_url}":'):
            lines.append(line)
        elif f'"{old_url}"' in line:
            lines.append(line.replace(f'"{old_url}"', f'"{new_url}"'))
        else:
            lines.append(line)
    new_text = "\n".join(lines)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    if new_text == text:
        return {"applied": False, "reason": "no_file_changes"}

    if apply:
        filings_path.write_text(new_text, encoding="utf-8")
    return {
        "applied": True,
        "ticker": ticker,
        "old_url": old_url,
        "new_url": new_url,
        "filings_path": str(filings_path),
    }


def _task_market_id(row: dict[str, Any]) -> str:
    evidence = row.get("evidence") or {}
    return str(
        evidence.get("market_id")
        or evidence.get("hunter_market_id")
        or evidence.get("library_market")
        or ""
    ).strip()


def recent_merged_hunter_allowlist_tasks(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    market_ids: tuple[str, ...] = DEFAULT_MARKET_IDS,
    now: datetime | None = None,
    filings_path: Path | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=lookback_days)
    filings_path = filings_path or default_filings_path()
    filings_text = filings_path.read_text(encoding="utf-8") if filings_path.exists() else ""
    rows: list[dict[str, Any]] = []
    for row in load_engineering_tasks(tasks_path).get("tasks") or []:
        if not is_parked_source_hunter_task(row):
            continue
        if str(row.get("status") or "") != "merged":
            continue
        market_id = _task_market_id(row)
        if market_ids and market_id and market_id not in market_ids:
            continue
        merged_at = _parse_iso(str(row.get("merged_at") or row.get("completed_at") or ""))
        if merged_at is not None and merged_at < cutoff:
            continue
        ticker = hunter_task_ticker(row)
        if not ticker:
            continue
        if hunter_ticker_resolution_in_filings(filings_text, ticker) != HunterResolution.ALLOWLIST:
            continue
        rows.append(row)
    return rows


def _open_url_repair_exists(
    rows: list[dict[str, Any]],
    *,
    ticker: str,
    failed_url: str,
) -> bool:
    for row in rows:
        if str(row.get("source") or "") != HUNTER_URL_REPAIR_SOURCE:
            continue
        if str(row.get("status") or "") in {"merged", "completed", "cancelled"}:
            continue
        evidence = row.get("evidence") or {}
        if (
            str(evidence.get("hunter_ticker") or "").strip().upper() == ticker.upper()
            and str(evidence.get("failed_url") or "").strip() == failed_url
        ):
            return True
    return False


def draft_hunter_url_repair_task(
    *,
    parent_task: dict[str, Any],
    failed_url: str,
    failure_reason: str,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
    apply: bool = True,
) -> dict[str, Any]:
    ticker = hunter_task_ticker(parent_task) or ""
    failed_url = str(failed_url or "").strip()
    if not ticker or not failed_url:
        return {"drafted": False, "reason": "missing_ticker_or_url"}

    payload = load_engineering_tasks(committed_path)
    rows = list(payload.get("tasks") or [])
    if _open_url_repair_exists(rows, ticker=ticker, failed_url=failed_url):
        return {"drafted": False, "reason": "open_repair_already_queued", "hunter_ticker": ticker}

    market_id = _task_market_id(parent_task) or "euro_depth"
    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    seq = _next_engineering_seq_from_rows(rows, run_stamp)
    parent_id = str(parent_task.get("id") or "")
    title = f"Repair dead hunter allowlist URL for {ticker}"[:160]
    summary = (
        f"Monitor detected live-fetch failure for {failed_url} ({ticker}, {market_id}). "
        "Inspect whether the URL rot is fixable via a known canonical replacement, a fresh "
        "allowlist entry, or a PARKED_SOURCE_HUNTER_SKIP update. Do not invent URLs."
    )[:500]
    task = EngineeringTask(
        id=f"eng-{run_stamp}-{seq:02d}",
        area="ingest",
        title=title,
        summary=summary,
        priority="low",
        priority_score=PARKED_SOURCE_HUNTER_PRIORITY_SCORE,
        source=HUNTER_URL_REPAIR_SOURCE,
        auto_merge=False,
        evidence={
            "market_id": market_id,
            "library_market": market_id,
            "hunter_market_id": market_id,
            "hunter_ticker": ticker.upper(),
            "failed_url": failed_url,
            "monitor_reason": failure_reason[:500],
            "parent_task_id": parent_id,
            "parent_merged_at": parent_task.get("merged_at") or parent_task.get("completed_at"),
            "universe": "library",
            "doc": "docs/ops/ops-monitor.md",
        },
        acceptance_criteria=[
            f"Inspect IR / exchange sources for {ticker} only — do not invent URLs",
            f"Repair or replace the dead URL recorded for {ticker}",
            "Add/adjust regression coverage in tests/test_research_filings.py",
            "No change to live FTSE 350 ingest path, blocked_paths, or paper-fund",
        ],
        allowed_paths=_allowed_paths_for_area("ingest"),
        blocked_paths=list(BLOCKED_PATHS),
    )
    merged_rows = _merge_task_rows(rows, [task])
    if not apply:
        return {
            "drafted": True,
            "dry_run": True,
            "task_id": task.id,
            "hunter_ticker": ticker.upper(),
            "failed_url": failed_url,
        }

    payload = {
        **payload,
        "compiled_at": datetime.now(UTC).isoformat(),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "micro_compile_source": HUNTER_URL_REPAIR_SOURCE,
        "hunter_ticker": ticker.upper(),
        "failed_url": failed_url,
    }
    committed_path = Path(committed_path)
    tasks_path = Path(tasks_path)
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(committed_path, payload, compact=False)
    if tasks_path != committed_path:
        write_json(tasks_path, payload, compact=False)
    return {
        "drafted": True,
        "task_id": task.id,
        "hunter_ticker": ticker.upper(),
        "failed_url": failed_url,
        "parent_task_id": parent_id,
    }


@dataclass
class HunterUrlMonitorAction:
    task_id: str
    ticker: str
    url: str
    action: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "ticker": self.ticker,
            "url": self.url,
            "action": self.action,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class HunterUrlMonitorResult:
    checked_urls: int = 0
    actions: list[HunterUrlMonitorAction] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_urls": self.checked_urls,
            "actions": [row.to_dict() for row in self.actions],
            "skipped": self.skipped,
            "action_count": len(self.actions),
        }


def monitor_merged_hunter_allowlist_urls(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
    filings_path: Path | None = None,
    cwd: Path | None = None,
    apply: bool = True,
    now: datetime | None = None,
    policy: dict[str, Any] | None = None,
) -> HunterUrlMonitorResult:
    """Re-live-fetch recent hunter allowlist URLs; repair or re-queue on failure."""
    from value_investor.engineering_verify import (
        MAX_VERIFY_REWORK_ROUNDS,
        count_verify_chain_rounds,
        has_open_verify_rework_for_chain,
        verify_chain_root_id,
        verify_merged_task,
    )

    cfg = policy or hunter_url_monitor_policy()
    result = HunterUrlMonitorResult()
    if not cfg.get("enabled"):
        result.skipped.append({"reason": "hunter_url_monitor_disabled"})
        return result

    workdir = Path(cwd or Path.cwd())
    filings_path = filings_path or default_filings_path(cwd=workdir)
    tasks = recent_merged_hunter_allowlist_tasks(
        tasks_path=tasks_path,
        lookback_days=int(cfg["lookback_days"]),
        market_ids=tuple(cfg["market_ids"]),
        now=now,
        filings_path=filings_path,
    )
    if not tasks:
        result.skipped.append({"reason": "no_recent_merged_hunter_allowlist_tasks"})
        return result

    seen_urls: set[tuple[str, str]] = set()
    for row in tasks:
        task_id = str(row.get("id") or "")
        ticker = hunter_task_ticker(row) or ""
        if not task_id or not ticker:
            continue
        for url in allowlist_urls_for_ticker(ticker, filings_path=filings_path):
            key = (ticker.upper(), url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            result.checked_urls += 1

            ok, fetch_reason = live_fetch_hunter_urls([url], ticker=ticker)
            if ok:
                result.actions.append(
                    HunterUrlMonitorAction(
                        task_id=task_id,
                        ticker=ticker,
                        url=url,
                        action="ok",
                        reason=fetch_reason,
                    )
                )
                continue

            replacement = canonical_replacement_url(url, ticker=ticker)
            if replacement:
                repl_ok, repl_reason = live_fetch_hunter_urls([replacement], ticker=ticker)
                if repl_ok:
                    repair = apply_known_canonical_allowlist_repair(
                        ticker=ticker,
                        old_url=url,
                        new_url=replacement,
                        filings_path=filings_path,
                        apply=apply,
                    )
                    if repair.get("applied"):
                        result.actions.append(
                            HunterUrlMonitorAction(
                                task_id=task_id,
                                ticker=ticker,
                                url=url,
                                action="canonical_applied",
                                reason=repl_reason,
                                detail=repair,
                            )
                        )
                        continue

            evidence = row.get("evidence") or {}
            verify_status = str(evidence.get("verify_status") or "")
            chain_root = verify_chain_root_id(row)
            rounds = count_verify_chain_rounds(chain_root, tasks_path=tasks_path)
            if (
                verify_status not in {"passed", "exhausted"}
                and rounds < MAX_VERIFY_REWORK_ROUNDS
                and not has_open_verify_rework_for_chain(chain_root, tasks_path=tasks_path)
            ):
                verify_result = verify_merged_task(
                    task_id,
                    tasks_path=tasks_path,
                    cwd=workdir,
                    apply=apply,
                )
                if verify_result.get("action") in {"rework_queued", "exhausted"}:
                    result.actions.append(
                        HunterUrlMonitorAction(
                            task_id=task_id,
                            ticker=ticker,
                            url=url,
                            action=str(verify_result.get("action") or "verify_rework"),
                            reason=str(verify_result.get("reason") or fetch_reason),
                            detail=verify_result,
                        )
                    )
                    continue

            draft = draft_hunter_url_repair_task(
                parent_task=row,
                failed_url=url,
                failure_reason=fetch_reason,
                tasks_path=tasks_path,
                committed_path=committed_path,
                apply=apply,
            )
            if draft.get("drafted"):
                result.actions.append(
                    HunterUrlMonitorAction(
                        task_id=task_id,
                        ticker=ticker,
                        url=url,
                        action="repair_drafted",
                        reason=fetch_reason,
                        detail=draft,
                    )
                )
            else:
                result.actions.append(
                    HunterUrlMonitorAction(
                        task_id=task_id,
                        ticker=ticker,
                        url=url,
                        action="skipped",
                        reason=str(draft.get("reason") or fetch_reason),
                        detail=draft,
                    )
                )

    return result
