"""Time-boxed first-run observe pin for the #953 weekday P1 round-trip.

Pinned question: after the first Sunday screen and first Monday paper-auto
following #953, do FTSE holdings ∪ buy-tier names carry EPS-from-body on
``reports[]`` and freeze those fields onto ``rebalance_log`` slim candidates?

Observe-only. Auto-oks when a count lands. One warn per surface if still 0/n
after that surface's run. Empty / pre-Sunday is not a warn. Window expires so
ops does not babysit forever. Does not rememo, change fills, fork AI-judgment,
or soak every merge.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.decision_input_inventory import (
    load_paper_holdings,
    primary_paper_fund_path,
    primary_paper_track_dir,
)
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.rebalance_log import load_rebalance_log
from value_investor.storage import read_json, write_json

DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_STORE_PATH = Path("docs/data/p1_first_run_pin.json")

SCHEMA_VERSION = 1
# #953 squash-merge onto main.
PIN_STARTED_AT = datetime(2026, 10, 3, 16, 19, 13, tzinfo=UTC)
DEFAULT_WINDOW_DAYS = 10

EPS_FIELDS: tuple[str, ...] = (
    "interim_eps_decline_pct",
    "adjusted_eps_growth_pct",
)

SUNDAY_FINDING_TITLE = "P1 first-run: EPS-from-body missing after Sunday screen"
MONDAY_FINDING_TITLE = "P1 first-run: slim freeze missing after Monday paper-auto"

STATUS_PRE_SUNDAY = "pre_sunday"
STATUS_PRE_MONDAY = "pre_monday"
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_EXPIRED = "expired"

LEARNING_QUESTION = (
    "After the first Sunday screen and first Monday paper-auto following #953, "
    "do FTSE holdings ∪ buy-tier names carry EPS-from-body on reports and freeze "
    "those fields onto rebalance_log slim candidates?"
)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _date_on_or_after_weekday(start: datetime, weekday: int) -> datetime:
    start = start.astimezone(UTC)
    delta = (weekday - start.weekday()) % 7
    day = start.date() + timedelta(days=delta)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _numeric_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, float) and value != value:
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def has_eps_from_body(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    return any(_numeric_present(row.get(key)) for key in EPS_FIELDS)


def _load_latest(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def inventory_reports(
    latest_payload: dict[str, Any],
    holdings: set[str],
) -> list[dict[str, Any]]:
    """Holdings ∪ buy-tier reports; held names missing from the screen are stubs."""
    by_ticker: dict[str, dict[str, Any]] = {}
    for row in latest_payload.get("reports") or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker:
            by_ticker[ticker] = row
    for ticker in holdings:
        if ticker not in by_ticker:
            by_ticker[ticker] = {"ticker": ticker, "signal": "hold"}
    out: list[dict[str, Any]] = []
    for ticker, row in by_ticker.items():
        signal = str(row.get("signal") or "")
        if signal in BUY_SIGNALS or ticker in holdings:
            out.append(row)
    out.sort(key=lambda r: str(r.get("ticker") or ""))
    return out


def _slim_rows_from_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    by_ticker: dict[str, dict[str, Any]] = {}
    for key in ("candidates", "screen_buy_tier"):
        for row in entry.get(key) or []:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker and ticker not in by_ticker:
                by_ticker[ticker] = row
    return list(by_ticker.values())


def _latest_paper_auto_since(
    entries: list[dict[str, Any]],
    *,
    since: datetime,
) -> dict[str, Any] | None:
    picked: tuple[datetime, dict[str, Any]] | None = None
    for entry in entries:
        logged = _parse_dt(entry.get("logged_at"))
        if logged is None or logged < since:
            continue
        if picked is None or logged >= picked[0]:
            picked = (logged, entry)
    return None if picked is None else picked[1]


def _surface_status(
    *,
    ran: bool,
    count: int,
    inventory_count: int,
    expired: bool,
    waiting_status: str,
) -> str:
    if not ran:
        return STATUS_EXPIRED if expired else waiting_status
    if count > 0:
        return STATUS_OK
    if expired:
        return STATUS_EXPIRED
    if inventory_count <= 0:
        return waiting_status
    return STATUS_WARN


def run_p1_first_run_pin(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    paper_fund_path: Path | None = None,
    paper_track_dir: Path | None = None,
    store_path: Path = DEFAULT_STORE_PATH,
    pin_started_at: datetime = PIN_STARTED_AT,
    window_days: float = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Refresh the first-run pin store. Does not rememo or change fills."""
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    clock = clock.astimezone(UTC)
    started = pin_started_at.astimezone(UTC)
    window_end = started + timedelta(days=float(window_days))
    expired = clock >= window_end
    first_sunday = _date_on_or_after_weekday(started, 6)
    first_monday = _date_on_or_after_weekday(started, 0)
    if first_monday < first_sunday:
        first_monday = first_sunday + timedelta(days=1)

    paper_fund_path = (
        Path(paper_fund_path) if paper_fund_path is not None else primary_paper_fund_path()
    )
    paper_track_dir = (
        Path(paper_track_dir) if paper_track_dir is not None else primary_paper_track_dir()
    )
    latest_payload = _load_latest(Path(latest_path))
    holdings = load_paper_holdings(paper_fund_path)
    reports = inventory_reports(latest_payload, holdings)
    inventory_count = len(reports)
    sunday_eps = sum(1 for row in reports if has_eps_from_body(row))
    screen_run_at = _parse_dt(latest_payload.get("run_at")) or _parse_dt(
        latest_payload.get("generated_at")
    )
    sunday_ran = bool(
        inventory_count > 0 and screen_run_at is not None and screen_run_at >= first_sunday
    )
    sunday_status = _surface_status(
        ran=sunday_ran,
        count=sunday_eps,
        inventory_count=inventory_count,
        expired=expired,
        waiting_status=STATUS_PRE_SUNDAY,
    )

    entries = load_rebalance_log(Path(paper_track_dir))
    monday_entry = _latest_paper_auto_since(entries, since=first_monday)
    slim_rows = _slim_rows_from_entry(monday_entry) if monday_entry else []
    inventory_tickers = {
        str(row.get("ticker") or "").strip().upper()
        for row in reports
        if str(row.get("ticker") or "").strip()
    }
    slim_inventory = [
        row
        for row in slim_rows
        if str(row.get("ticker") or "").strip().upper() in inventory_tickers
    ]
    monday_eps = sum(1 for row in slim_inventory if has_eps_from_body(row))
    monday_logged = _parse_dt((monday_entry or {}).get("logged_at"))
    monday_ran = monday_entry is not None and inventory_count > 0
    monday_status = _surface_status(
        ran=monday_ran,
        count=monday_eps,
        inventory_count=inventory_count,
        expired=expired,
        waiting_status=STATUS_PRE_MONDAY,
    )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "observe_only": True,
        "influences_live": False,
        "pin_started_at": started.isoformat(),
        "window_ends_at": window_end.isoformat(),
        "window_days": float(window_days),
        "first_sunday_at": first_sunday.isoformat(),
        "first_monday_at": first_monday.isoformat(),
        "learning_question": LEARNING_QUESTION,
        "latest_path": str(latest_path),
        "paper_fund_path": str(paper_fund_path),
        "paper_track_dir": str(paper_track_dir),
        "inventory_count": inventory_count,
        "holdings": sorted(holdings),
        "sunday": {
            "status": sunday_status,
            "screen_run_at": screen_run_at.isoformat() if screen_run_at else None,
            "eps_from_body_count": sunday_eps,
            "inventory_count": inventory_count,
            "ran": sunday_ran,
        },
        "monday": {
            "status": monday_status,
            "paper_auto_logged_at": monday_logged.isoformat() if monday_logged else None,
            "eps_from_body_count": monday_eps,
            "candidate_count": len(slim_inventory),
            "inventory_count": inventory_count,
            "ran": monday_ran,
        },
        "note": (
            "Time-boxed first-run pin after #953. Auto-ok when EPS-from-body "
            "lands on the relevant surface. Empty/pre-Sunday is not a warn. "
            "Does not rememo, change fills, or soak every merge."
        ),
    }
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, compact=False)
    return payload


def ops_findings_from_p1_first_run_pin(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Warn-only findings for surfaces still 0/n after their run, inside the window."""
    findings: list[dict[str, Any]] = []
    sunday = payload.get("sunday") or {}
    monday = payload.get("monday") or {}
    n = int(payload.get("inventory_count") or sunday.get("inventory_count") or 0)
    if sunday.get("status") == STATUS_WARN:
        count = int(sunday.get("eps_from_body_count") or 0)
        findings.append(
            {
                "severity": "warn",
                "category": "research",
                "title": SUNDAY_FINDING_TITLE,
                "summary": (
                    f"Sunday screen ran and EPS-from-body is still {count}/{n} on "
                    "FTSE holdings ∪ buy-tier reports (`interim_eps_decline_pct` / "
                    "`adjusted_eps_growth_pct`). Observe-only first-run pin after #953 "
                    "— do not rememo or ingest from this alert. Auto-oks when a count "
                    "lands; expires after the pin window."
                ),
                "auto_fixable": False,
            }
        )
    if monday.get("status") == STATUS_WARN:
        count = int(monday.get("eps_from_body_count") or 0)
        findings.append(
            {
                "severity": "warn",
                "category": "paper",
                "title": MONDAY_FINDING_TITLE,
                "summary": (
                    f"Monday paper-auto ran and slim freeze of EPS-from-body is still "
                    f"{count}/{n} on rebalance_log candidates. Observe-only first-run "
                    "pin after #953 — does not change fills. Auto-oks when slim copies "
                    "the field; expires after the pin window."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def format_p1_first_run_summary(payload: dict[str, Any]) -> str:
    sunday = payload.get("sunday") or {}
    monday = payload.get("monday") or {}
    n = payload.get("inventory_count")
    lines = [
        "P1 first-run observe pin (#953 round-trip, time-boxed)",
        f"  Generated: {payload.get('generated_at')}",
        f"  Window: {payload.get('pin_started_at')} → {payload.get('window_ends_at')}",
        f"  Inventory: {n}",
        (
            f"  Sunday reports EPS-from-body: {sunday.get('eps_from_body_count')}/{n} "
            f"({sunday.get('status')})"
        ),
        (
            f"  Monday slim EPS-from-body: {monday.get('eps_from_body_count')}/{n} "
            f"({monday.get('status')})"
        ),
    ]
    note = payload.get("note")
    if note:
        lines.append(f"  Note: {note}")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_STORE_PATH",
    "DEFAULT_WINDOW_DAYS",
    "EPS_FIELDS",
    "LEARNING_QUESTION",
    "MONDAY_FINDING_TITLE",
    "PIN_STARTED_AT",
    "SUNDAY_FINDING_TITLE",
    "format_p1_first_run_summary",
    "has_eps_from_body",
    "ops_findings_from_p1_first_run_pin",
    "run_p1_first_run_pin",
]
