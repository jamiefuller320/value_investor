"""Post-ingest deviation list: auto-record, human review, optional reprocess.

Safe automation after a library deepen:

- Persist open deviations when a ticker exhausts IR retries or hits the weekday
  cap with no coverage gain and leftover IWB.
- Failed IR rows are already marked unfetchable by the refetch path.
- Do **not** auto-replace allowlist URLs (wrong-issuer vs official IR is judgment).
- Do **not** auto-pin every blocker (that starves the weekday batch).

Observe-only **signal triage** labels each open row from the latest library
screen (``strong_buy`` → pin, plain ``buy`` → park/hunter, else dismiss).
Labels never write pins or change status — humans (or an explicit review
command) still approve / dismiss.

Human review lives on the dashboard Automation tab. Reprocess is
``ftse-library ingest-deviations approve <id>`` (writes a dated intensive pin
the next scheduled euro slot will honour). Pages is static, so the dashboard
cannot dispatch workflows.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

DEFAULT_INGEST_DEVIATIONS_PATH = Path("docs/data/ingest_deviations.json")
DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_PIN_UNTIL_DAYS = 7.0
DISMISS_COOLDOWN_HOURS = 168.0  # 7 days
KIND_IR_EXHAUSTED = "ir_exhausted"
KIND_BLOCKER_NO_IMPROVE = "blocker_no_improve"
OPEN_STATUSES = frozenset({"open"})
REVIEWED_STATUSES = frozenset({"approved", "dismissed", "resolved"})

# Observe-only signal-tier triage (L455). Not an auto-apply path (N151).
SHADOW_ACTION_PIN = "pin_intensive"
SHADOW_ACTION_PARK = "park_hunter"
SHADOW_ACTION_DISMISS = "dismiss"
SHADOW_HUMAN_ACTION = {
    SHADOW_ACTION_PIN: "approve",
    SHADOW_ACTION_PARK: "dismiss",
    SHADOW_ACTION_DISMISS: "dismiss",
}


def deviation_id(market_id: str, ticker: str, kind: str) -> str:
    market = str(market_id or "").strip() or "unknown"
    name = str(ticker or "").strip().upper() or "UNKNOWN"
    return f"dev-{market}-{name}-{kind}"


def load_ingest_deviations(path: Path | None = None) -> dict[str, Any]:
    path = Path(path or DEFAULT_INGEST_DEVIATIONS_PATH)
    if not path.exists():
        return {
            "schema_version": 1,
            "updated_at": None,
            "items": [],
        }
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {"schema_version": 1, "updated_at": None, "items": []}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "updated_at": None, "items": []}
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    return {
        "schema_version": int(payload.get("schema_version") or 1),
        "updated_at": payload.get("updated_at"),
        "items": [row for row in items if isinstance(row, dict)],
    }


def open_ingest_deviations(path: Path | None = None) -> list[dict[str, Any]]:
    return [
        row
        for row in load_ingest_deviations(path).get("items") or []
        if str(row.get("status") or "") in OPEN_STATUSES
    ]


def collect_library_ingest_deviations(
    *,
    market_id: str,
    results: list[Any],
    run_at: str | None = None,
) -> list[dict[str, Any]]:
    """Build candidate deviation rows from one deepen pass (no I/O)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    stamp = str(run_at or datetime.now(UTC).isoformat())
    for raw in results or []:
        if not isinstance(raw, dict):
            continue
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        after = raw.get("after") if isinstance(raw.get("after"), dict) else {}
        iwb = int(after.get("indexed_without_body") or 0)
        ir_exhausted = bool(raw.get("ir_exhausted"))
        budget_hit = bool(raw.get("ticker_budget_hit"))
        improved = bool(raw.get("improved"))
        if ir_exhausted:
            kind = KIND_IR_EXHAUSTED
            recommended = "replace_allowlist_or_pin"
            summary = (
                f"{ticker} IR allowlist refetch failed with 0 bodies fetched. "
                "Failed rows are marked unfetchable; replace the URL or pin intensive."
            )
        elif budget_hit and not improved and iwb > 0:
            kind = KIND_BLOCKER_NO_IMPROVE
            recommended = "pin_intensive"
            summary = (
                f"{ticker} hit the weekday ticker cap with no coverage gain "
                f"and {iwb} indexed-without-body row(s). Pin intensive or fix sources."
            )
        else:
            continue
        key = deviation_id(market_id, ticker, kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": key,
                "market_id": str(market_id or "").strip(),
                "ticker": ticker,
                "kind": kind,
                "status": "open",
                "recommended_action": recommended,
                "summary": summary,
                "human_required": True,
                "auto_actions": (["ir_rows_marked_unfetchable"] if ir_exhausted else []),
                "evidence": {
                    "improved": improved,
                    "ticker_budget_hit": budget_hit,
                    "ir_exhausted": ir_exhausted,
                    "indexed_without_body": iwb,
                    "filings_with_body": int(after.get("filings_with_body") or 0),
                    "filings_total": int(after.get("filings_total") or 0),
                },
                "reprocess": {
                    "approve": f"ftse-library ingest-deviations approve {key}",
                    "dismiss": f"ftse-library ingest-deviations dismiss {key}",
                },
                "first_seen_at": stamp,
                "last_seen_at": stamp,
                "run_at": stamp,
            }
        )
    return out


def _parse_iso(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def _in_cooldown(row: dict[str, Any], *, now: datetime, hours: float) -> bool:
    reviewed = _parse_iso(str(row.get("reviewed_at") or row.get("resolved_at") or ""))
    if reviewed is None:
        return False
    age_hours = (now - reviewed).total_seconds() / 3600.0
    return 0 <= age_hours <= float(hours)


def record_library_ingest_deviations(
    *,
    market_id: str,
    results: list[Any],
    improved: list[str] | None = None,
    path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Merge this run's deviations into the committed store and auto-resolve improved names."""
    path = Path(path or DEFAULT_INGEST_DEVIATIONS_PATH)
    current = now or datetime.now(UTC)
    stamp = current.isoformat()
    store = load_ingest_deviations(path)
    existing = {str(row.get("id") or ""): dict(row) for row in store.get("items") or []}
    improved_set = {
        str(token or "").strip().upper() for token in (improved or []) if str(token).strip()
    }
    proposed = collect_library_ingest_deviations(
        market_id=market_id,
        results=results,
        run_at=stamp,
    )
    opened: list[str] = []
    refreshed: list[str] = []
    resolved: list[str] = []
    skipped_cooldown: list[str] = []

    for row in existing.values():
        ticker = str(row.get("ticker") or "").strip().upper()
        status = str(row.get("status") or "")
        if status in OPEN_STATUSES and ticker in improved_set:
            row["status"] = "resolved"
            row["resolved_at"] = stamp
            row["resolved_reason"] = "ticker_improved_on_later_ingest"
            resolved.append(str(row.get("id") or ""))

    for candidate in proposed:
        key = str(candidate["id"])
        prior = existing.get(key)
        if prior is None:
            existing[key] = candidate
            opened.append(key)
            continue
        status = str(prior.get("status") or "")
        if status in OPEN_STATUSES:
            prior["last_seen_at"] = stamp
            prior["run_at"] = stamp
            prior["evidence"] = candidate.get("evidence")
            prior["summary"] = candidate.get("summary")
            prior["auto_actions"] = candidate.get("auto_actions")
            refreshed.append(key)
            continue
        if status == "approved":
            skipped_cooldown.append(key)
            continue
        if status == "dismissed" and _in_cooldown(prior, now=current, hours=DISMISS_COOLDOWN_HOURS):
            skipped_cooldown.append(key)
            continue
        existing[key] = {
            **candidate,
            "first_seen_at": prior.get("first_seen_at") or stamp,
            "reopened_at": stamp,
            "previous_status": status,
        }
        opened.append(key)

    open_rows = [row for row in existing.values() if str(row.get("status") or "") in OPEN_STATUSES]
    closed_rows = [
        row for row in existing.values() if str(row.get("status") or "") not in OPEN_STATUSES
    ]
    open_rows.sort(key=lambda row: str(row.get("last_seen_at") or ""), reverse=True)
    closed_rows.sort(key=lambda row: str(row.get("last_seen_at") or ""), reverse=True)
    # Fresh observe-only labels for the dashboard static JSON.
    open_rows = annotate_deviations_with_signal_triage(open_rows)
    items = open_rows + closed_rows
    open_items = [row for row in items if str(row.get("status") or "") in OPEN_STATUSES]
    reviewed = [row for row in items if str(row.get("status") or "") in REVIEWED_STATUSES]
    reviewed.sort(key=lambda row: str(row.get("reviewed_at") or row.get("resolved_at") or ""))
    payload = {
        "schema_version": 1,
        "updated_at": stamp,
        "open_count": len(open_items),
        "open_items": open_items,
        "recent_reviewed": list(reversed(reviewed[-8:])),
        "signal_triage_policy": (
            "observe_only: leftover/dismiss, buy/park_hunter, strong_buy/pin_intensive"
        ),
        "items": items,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)
    return {
        "path": str(path),
        "opened": opened,
        "refreshed": refreshed,
        "resolved": resolved,
        "skipped_cooldown": skipped_cooldown,
        "open_count": payload["open_count"],
        "items": items,
    }


def _upsert_pin(
    *,
    ticker: str,
    market_id: str,
    reason: str,
    pins_path: Path,
    until: datetime,
) -> dict[str, Any]:
    path = Path(pins_path)
    if path.exists():
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            payload = {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    pins = [row for row in (payload.get("pins") or []) if isinstance(row, dict)]
    key = str(ticker).strip().upper()
    market = str(market_id or "").strip()
    replaced = False
    updated: list[dict[str, Any]] = []
    pin_row = {
        "ticker": key,
        "market_id": market,
        "reason": reason,
        "until": until.isoformat(),
    }
    for row in pins:
        same = (
            str(row.get("ticker") or "").strip().upper() == key
            and str(row.get("market_id") or "").strip() == market
        )
        if same:
            updated.append(pin_row)
            replaced = True
        else:
            updated.append(row)
    if not replaced:
        updated.append(pin_row)
    payload = {
        "schema_version": int(payload.get("schema_version") or 1),
        "note": payload.get("note")
        or "Committed intensive pins for library weekday ingest. Expired rows are ignored.",
        "pins": updated,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)
    return {"pins_path": str(path), "pin": pin_row, "replaced": replaced}


def review_ingest_deviation(
    deviation_id_value: str,
    *,
    action: str,
    path: Path | None = None,
    pins_path: Path | None = None,
    pin_until_days: float = DEFAULT_PIN_UNTIL_DAYS,
    now: datetime | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Approve (pin + close) or dismiss an open deviation."""
    wanted = str(deviation_id_value or "").strip()
    verb = str(action or "").strip().lower()
    if verb not in {"approve", "dismiss"}:
        raise ValueError("action must be approve or dismiss")
    path = Path(path or DEFAULT_INGEST_DEVIATIONS_PATH)
    store = load_ingest_deviations(path)
    current = now or datetime.now(UTC)
    stamp = current.isoformat()
    found: dict[str, Any] | None = None
    items: list[dict[str, Any]] = []
    for row in store.get("items") or []:
        item = dict(row)
        if str(item.get("id") or "") == wanted:
            found = item
        items.append(item)
    if found is None:
        raise KeyError(f"unknown deviation id: {wanted}")
    if str(found.get("status") or "") not in OPEN_STATUSES:
        raise ValueError(f"deviation {wanted} is {found.get('status')}, not open")

    pin_meta: dict[str, Any] | None = None
    if verb == "approve":
        until = current + timedelta(days=float(pin_until_days))
        pin_meta = _upsert_pin(
            ticker=str(found.get("ticker") or ""),
            market_id=str(found.get("market_id") or ""),
            reason=str(found.get("summary") or "ingest deviation approved"),
            pins_path=Path(pins_path)
            if pins_path is not None
            else Path("docs/data/library_ingest_pins.json"),
            until=until,
        )
        found["status"] = "approved"
        found["pin_until"] = until.isoformat()
    else:
        found["status"] = "dismissed"
    found["reviewed_at"] = stamp
    found["review_action"] = verb
    if note:
        found["review_note"] = note
    # Snapshot the observe-only triage that informed this review (if any).
    found = annotate_deviation_with_signal_triage(found)

    replaced = [found if str(row.get("id") or "") == wanted else row for row in items]
    open_items = annotate_deviations_with_signal_triage(
        [row for row in replaced if str(row.get("status") or "") in OPEN_STATUSES]
    )
    open_ids = {str(row.get("id") or "") for row in open_items}
    items_out = open_items + [
        found if str(row.get("id") or "") == wanted else row
        for row in replaced
        if str(row.get("id") or "") not in open_ids
    ]
    reviewed = [row for row in items_out if str(row.get("status") or "") in REVIEWED_STATUSES]
    reviewed.sort(key=lambda row: str(row.get("reviewed_at") or row.get("resolved_at") or ""))
    payload = {
        "schema_version": 1,
        "updated_at": stamp,
        "open_count": len(open_items),
        "open_items": open_items,
        "recent_reviewed": list(reversed(reviewed[-8:])),
        "signal_triage_policy": (
            "observe_only: leftover/dismiss, buy/park_hunter, strong_buy/pin_intensive"
        ),
        "items": items_out,
    }
    write_json(path, payload, compact=False)
    return {
        "id": wanted,
        "action": verb,
        "item": found,
        "pin": pin_meta,
        "open_count": payload["open_count"],
        "path": str(path),
    }


def _library_signals_csv(library_root: Path, market_id: str) -> Path:
    return Path(library_root) / "markets" / str(market_id).strip() / "screen" / "latest_signals.csv"


def load_library_screen_signal(
    market_id: str,
    ticker: str,
    *,
    library_root: Path | None = None,
) -> dict[str, Any]:
    """Read one ticker's latest library screen signal (csv; no pandas)."""
    root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    market = str(market_id or "").strip()
    name = str(ticker or "").strip().upper()
    path = _library_signals_csv(root, market)
    empty = {
        "ticker": name,
        "market_id": market,
        "signal": None,
        "conviction_score": None,
        "found": False,
        "path": str(path),
    }
    if not market or not name or not path.exists():
        return empty
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if str(row.get("ticker") or "").strip().upper() != name:
                    continue
                signal = str(row.get("signal") or "").strip().lower() or None
                conviction_raw = row.get("conviction_score")
                try:
                    conviction = float(conviction_raw) if conviction_raw not in (None, "") else None
                except (TypeError, ValueError):
                    conviction = None
                return {
                    "ticker": name,
                    "market_id": market,
                    "signal": signal,
                    "conviction_score": conviction,
                    "found": True,
                    "path": str(path),
                }
    except OSError:
        return empty
    return empty


def ticker_is_parked_leftover(
    market_id: str,
    ticker: str,
    *,
    library_root: Path | None = None,
) -> bool:
    """True when the ticker is in that market's ingest_exhaustion parked list."""
    root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    market = str(market_id or "").strip()
    name = str(ticker or "").strip().upper()
    if not market or not name:
        return False
    path = root / "markets" / market / "ingest_exhaustion.json"
    if not path.exists():
        return False
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    for row in payload.get("parked") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker") or "").strip().upper() == name:
            return True
    return False


def propose_signal_triage(
    *,
    signal: str | None,
    parked: bool = False,
    indexed_without_body: int | None = None,
    filings_with_body: int | None = None,
    filings_total: int | None = None,
) -> dict[str, Any]:
    """Map screen signal (+ leftover park) to an observe-only triage action.

    Policy (dialogue → instrument):
    - parked / off buy-tier leftovers → dismiss
    - plain ``buy`` → park_hunter (dismiss the deviation; rely on exhaustion + hunter)
    - ``strong_buy`` → pin_intensive (approve)
    """
    normalized = str(signal or "").strip().lower() or None
    iwb = int(indexed_without_body or 0)
    bodies = int(filings_with_body or 0)
    total = int(filings_total or 0)
    # Thin leftover IWB on an otherwise-bodied book (cold-start patchiness).
    patchy = bool(iwb > 0 and iwb <= 3 and (bodies > 0 or total > iwb))

    if normalized == "strong_buy":
        action = SHADOW_ACTION_PIN
        reason = "strong_buy"
        rationale = "Strong-buy — intensive pin so the next slot skips the weekday ticker cap."
    elif parked or normalized not in {"buy", "strong_buy"}:
        action = SHADOW_ACTION_DISMISS
        reason = (
            "parked_leftover"
            if parked
            else ("not_buy_tier" if normalized else "signal_missing")
        )
        rationale = (
            "Parked leftover — dismiss and leave to hunter / next report."
            if parked
            else "Not on current buy-tier (or signal missing) — dismiss patchy leftover."
        )
    else:
        # Plain buy: park/hunter path. Very thin leftover IWB still dismisses the
        # deviation row (same human action) so cold-start patchiness does not pin.
        action = SHADOW_ACTION_PARK
        reason = "buy_park_hunter" if not patchy else "buy_patchy_leftover"
        rationale = (
            "Plain buy with thin leftover IWB — dismiss; maintenance / park-hunter."
            if patchy
            else "Plain buy — dismiss deviation; rely on exhaustion park + source hunter."
        )

    return {
        "observe_only": True,
        "proposed_action": action,
        "human_action": SHADOW_HUMAN_ACTION[action],
        "reason": reason,
        "signal": normalized,
        "parked": bool(parked),
        "rationale": rationale,
        "policy": "leftover_dismiss__buy_park_hunter__strong_buy_pin",
    }


def annotate_deviation_with_signal_triage(
    row: dict[str, Any],
    *,
    library_root: Path | None = None,
    screen: dict[str, Any] | None = None,
    parked: bool | None = None,
) -> dict[str, Any]:
    """Attach a fresh ``signal_triage`` block (observe-only) onto one deviation row."""
    item = dict(row)
    market_id = str(item.get("market_id") or "").strip()
    ticker = str(item.get("ticker") or "").strip().upper()
    root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    lookup = screen if screen is not None else load_library_screen_signal(
        market_id, ticker, library_root=root
    )
    is_parked = (
        bool(parked)
        if parked is not None
        else ticker_is_parked_leftover(market_id, ticker, library_root=root)
    )
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    triage = propose_signal_triage(
        signal=lookup.get("signal") if isinstance(lookup, dict) else None,
        parked=is_parked,
        indexed_without_body=evidence.get("indexed_without_body"),
        filings_with_body=evidence.get("filings_with_body"),
        filings_total=evidence.get("filings_total"),
    )
    if isinstance(lookup, dict):
        triage["conviction_score"] = lookup.get("conviction_score")
        triage["screen_found"] = bool(lookup.get("found"))
    item["signal_triage"] = triage
    return item


def annotate_deviations_with_signal_triage(
    rows: list[dict[str, Any]],
    *,
    library_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Annotate many deviation rows with observe-only signal triage."""
    root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    return [
        annotate_deviation_with_signal_triage(row, library_root=root)
        for row in rows
        if isinstance(row, dict)
    ]


def slim_ingest_deviations_for_dashboard(
    payload: dict[str, Any] | None,
    *,
    library_root: Path | None = None,
    annotate_signal_triage: bool = True,
) -> dict[str, Any]:
    """Keep the dashboard payload small: open items plus recent reviewed."""
    items = [row for row in (payload or {}).get("items") or [] if isinstance(row, dict)]
    open_items = [row for row in items if str(row.get("status") or "") in OPEN_STATUSES]
    if annotate_signal_triage:
        open_items = annotate_deviations_with_signal_triage(
            open_items, library_root=library_root
        )
    reviewed = [row for row in items if str(row.get("status") or "") in REVIEWED_STATUSES]
    reviewed.sort(key=lambda row: str(row.get("reviewed_at") or row.get("resolved_at") or ""))
    return {
        "schema_version": 1,
        "updated_at": (payload or {}).get("updated_at"),
        "open_count": len(open_items),
        "open_items": open_items,
        "recent_reviewed": list(reversed(reviewed[-8:])),
        "signal_triage_policy": (
            "observe_only: leftover/dismiss, buy/park_hunter, strong_buy/pin_intensive"
            if annotate_signal_triage
            else None
        ),
    }
