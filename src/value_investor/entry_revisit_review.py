"""Entry-revisit review queue — fixed buy+28d outcome after entry_blind.

Stage ``entry_revisit``: once an ``entry_blind`` card is Accept/Comment-actioned
**and** ``asof >= buy_day + 28`` calendar days, surface the frozen blind
summary plus the path through buy+28d (still-open or already-exited).

Observe-only (``influences_live=false``). Package M alignment-only — never
knobs/fills. Does **not** rewrite sealed ``entry_blind`` Accept/Comment.
See ``docs/ops/entry-blind-review.md`` + blind-buy-exit design lock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.entry_blind_review import (
    LAB_BOOK_ID,
    family_id,
    review_fingerprint,
)
from value_investor.entry_blind_review_labels import load_entry_blind_review_labels
from value_investor.entry_revisit_review_labels import (
    LABELS_FILENAME,
    comments_awaiting_reply,
    heal_entry_revisit_replies_file,
    is_actioned,
    load_entry_revisit_review_labels,
)
from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 1
STAGE_ID = "entry_revisit"
PARENT_STAGE_ID = "entry_blind"
FINDING_TITLE = "Entry-revisit review queue (observe)"
STORE_FAILED_TITLE = "Entry-revisit review queue observe failed"
UNACKED_COMMENTS_TITLE = "Entry-revisit comments awaiting factory reply"
PENDING_REPLIES_TITLE = "Entry-revisit reply tags awaiting owner"
DEFAULT_STORE_PATH = Path("docs/data/entry_revisit_review_queue.json")
DEFAULT_DATA_DIR = Path("docs/data")
OPS_DOC = "docs/ops/entry-blind-review.md"
CATEGORY = "research"
ENTRY_REVISIT_DAYS = 28
ACTIVE_ATTENTION_CAP = 12
PIT_BEFORE_DAYS = 180

# Clearing blind actions that unlock revisit (Duplicate alone does not).
_BLIND_DONE_KINDS = frozenset({"accept", "comment"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        payload = read_json(Path(path))
    except (OSError, FileNotFoundError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _date_key(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if text else ""


def entry_revisit_due_at(entry_at: str | None, *, days: int = ENTRY_REVISIT_DAYS) -> str | None:
    opened = _parse_dt(entry_at)
    if opened is None:
        return None
    return (opened.date() + timedelta(days=int(days))).isoformat()


def entry_revisit_clock_ready(
    entry_at: str | None,
    *,
    asof: datetime | None = None,
    days: int = ENTRY_REVISIT_DAYS,
) -> bool:
    due = entry_revisit_due_at(entry_at, days=days)
    if not due:
        return False
    clock = (asof or _utcnow()).date().isoformat()
    return clock >= due


def entry_revisit_path_window(
    entry_at: str | None,
    *,
    before_days: int = PIT_BEFORE_DAYS,
    after_days: int = ENTRY_REVISIT_DAYS,
) -> dict[str, Any] | None:
    """Chart window: lookback before buy through fixed buy+28d (not beyond)."""
    opened = _parse_dt(entry_at)
    if opened is None:
        return None
    buy_day = opened.date()
    end = buy_day + timedelta(days=int(after_days))
    return {
        "start": (buy_day - timedelta(days=int(before_days))).isoformat(),
        "end": end.isoformat(),
        "days_before": int(before_days),
        "days_after": int(after_days),
        "blind_clip_at": None,
        "forbidden_forward_path": False,
        "asof": end.isoformat(),
        "revisit_horizon": "buy_plus_28d",
        "note": "Path revealed only through fixed buy+28d — not a full exit autopsy.",
    }


def _blind_done_events(blind_labels: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Latest Accept/Comment per blind review_id (immutable unlock for revisit)."""
    if not isinstance(blind_labels, dict):
        return []
    latest: dict[str, dict[str, Any]] = {}
    for event in blind_labels.get("events") or []:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "").strip().lower()
        if kind not in _BLIND_DONE_KINDS:
            continue
        rid = str(event.get("review_id") or "").strip()
        if not rid or rid.startswith("reply:"):
            continue
        stage = str(event.get("stage") or (event.get("snapshot") or {}).get("stage") or "").strip()
        if stage and stage != PARENT_STAGE_ID:
            continue
        prior = latest.get(rid)
        if prior is None or str(event.get("at") or "") >= str(prior.get("at") or ""):
            latest[rid] = event
    return list(latest.values())


def _lab_episode_index(lab: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Index lab episodes by ticker|entry_day for path status at +28d."""
    if not isinstance(lab, dict):
        return {}
    rows: list[Any] = []
    for key in (
        "open_episodes",
        "open_episodes_sample",
        "closed_episodes",
        "closed_episodes_sample",
        "open_lab_buys",
        "recent_lab_buys",
        "lab_buys",
    ):
        packed = lab.get(key)
        if isinstance(packed, list):
            rows.extend(packed)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        entry_at = (
            str(
                row.get("entry_run_at")
                or row.get("entry_at")
                or row.get("bought_at")
                or row.get("opened_at")
                or ""
            ).strip()
            or None
        )
        if not ticker or not entry_at:
            continue
        key = f"{ticker}|{_date_key(entry_at)}"
        prior = out.get(key)
        # Prefer closed over open when both present.
        if prior is None or (
            str(row.get("status") or "") == "closed"
            and str(prior.get("status") or "") != "closed"
        ):
            out[key] = row
    return out


def _path_status_for(
    *,
    book_id: str,
    ticker: str,
    entry_at: str | None,
    lab_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    due = entry_revisit_due_at(entry_at)
    key = f"{str(ticker or '').strip().upper()}|{_date_key(entry_at)}"
    ep = lab_index.get(key) if str(book_id) in {LAB_BOOK_ID, "cue_consumer_mft"} else None
    status = "still_open"
    return_pct = None
    exit_at = None
    exit_reason = None
    if isinstance(ep, dict):
        exit_at = str(ep.get("exit_run_at") or ep.get("exit_at") or "").strip() or None
        exit_reason = str(ep.get("exit_reason") or "").strip() or None
        if exit_at and due and _date_key(exit_at) <= due:
            status = "already_exited"
            raw_ret = ep.get("return_pct")
            try:
                return_pct = float(raw_ret) if raw_ret is not None else None
                if return_pct is not None and return_pct != return_pct:
                    return_pct = None
            except (TypeError, ValueError):
                return_pct = None
        elif str(ep.get("status") or "") == "closed" and exit_at:
            # Exited after +28d window — buy revisit still uses path-to-+28 only.
            status = "still_open_at_plus28_then_later_exit"
            exit_reason = exit_reason
        elif ep.get("open_mark_return") is not None:
            try:
                return_pct = float(ep.get("open_mark_return"))
            except (TypeError, ValueError):
                return_pct = None
    return {
        "status": status,
        "revisit_at": due,
        "fair_cost_return_pct_to_plus28": return_pct,
        "exit_at_if_before_plus28": exit_at if status == "already_exited" else None,
        "exit_reason_if_before_plus28": exit_reason if status == "already_exited" else None,
        "note": (
            "Fixed buy+28d outcome — not an exit autopsy. "
            "Blind Accept/Comment stays sealed."
        ),
    }


def _frozen_blind_summary(event: dict[str, Any]) -> dict[str, Any]:
    snap = event.get("snapshot") if isinstance(event.get("snapshot"), dict) else {}
    return {
        "blind_review_id": str(event.get("review_id") or "").strip() or None,
        "blind_action": str(event.get("kind") or "").strip() or None,
        "blind_actioned_at": str(event.get("at") or "").strip() or None,
        "blind_framing": snap.get("framing"),
        "blind_llm_opinion": snap.get("llm_opinion"),
        "blind_learning_point_forward": snap.get("learning_point_forward"),
        "blind_buy_decision": snap.get("buy_decision"),
        "blind_buy_reason": snap.get("buy_reason"),
        "immutable": True,
        "note": "Frozen entry_blind label snapshot — revisit must not rewrite it.",
    }


def _attach_revisit_opinion(item: dict[str, Any]) -> dict[str, Any]:
    path = item.get("path_status") if isinstance(item.get("path_status"), dict) else {}
    status = str(path.get("status") or "still_open")
    ret = path.get("fair_cost_return_pct_to_plus28")
    ret_bit = (
        f"fair-cost path to +28d ≈ {float(ret) * 100:.1f}%"
        if isinstance(ret, (int, float))
        else "fair-cost path to +28d unavailable"
    )
    opinion = (
        f"Entry revisit at fixed buy+28d for {item.get('ticker') or '?'}: "
        f"status={status}; {ret_bit}. "
        "Confirm, revise, or falsify the sealed blind critique — do not rewrite it."
    )
    learning = (
        "Carry one calibrated entry-lens lesson (stock choice / buy timing / buy strategy) "
        "from blind→+28d — Package M alignment only; never auto-apply knobs."
    )
    item["llm_opinion"] = opinion
    item["learning_points"] = [
        "Blind Accept/Comment is immutable on this card.",
        learning,
    ]
    item["learning_point_forward"] = learning
    item["lens_side"] = "entry"
    item["opinion_source"] = "deterministic_entry_revisit_v0"
    item["chart_annotations"] = {
        "path_to_plus28": "Path through fixed buy+28d only — not post-exit ladder."
    }
    if not item.get("dialogue"):
        item["dialogue"] = [
            {
                "role": "factory",
                "kind": "initial_opinion",
                "text": opinion,
                "learning_points": list(item["learning_points"]),
                "chart_annotations": dict(item["chart_annotations"]),
                "learning_point_forward": learning,
                "lens_side": "entry",
                "source": "deterministic_entry_revisit_v0",
                "at": _utcnow().isoformat(),
                "influences_live": False,
            }
        ]
    return item


def build_entry_revisit_card(
    blind_event: dict[str, Any],
    *,
    lab_index: dict[str, dict[str, Any]] | None = None,
    asof: datetime | None = None,
) -> dict[str, Any] | None:
    snap = blind_event.get("snapshot") if isinstance(blind_event.get("snapshot"), dict) else {}
    book_id = str(snap.get("book_id") or blind_event.get("book_id") or "").strip()
    ticker = str(snap.get("ticker") or blind_event.get("ticker") or "").strip()
    entry_at = str(snap.get("entry_at") or snap.get("opened_at") or "").strip() or None
    if not book_id or not ticker or not entry_at:
        return None
    if not entry_revisit_clock_ready(entry_at, asof=asof):
        return None

    blind_id = str(blind_event.get("review_id") or "").strip()
    rid = review_fingerprint(
        book_id=book_id, ticker=ticker, entry_at=entry_at, kind=STAGE_ID
    )
    fam = family_id(book_id=book_id, ticker=ticker, entry_at=entry_at)
    path = _path_status_for(
        book_id=book_id,
        ticker=ticker,
        entry_at=entry_at,
        lab_index=lab_index or {},
    )
    window = entry_revisit_path_window(entry_at)
    days_since = None
    opened = _parse_dt(entry_at)
    if opened is not None:
        days_since = ((asof or _utcnow()).date() - opened.date()).days

    item: dict[str, Any] = {
        "review_id": rid,
        "review_fingerprint": rid,
        "family_id": fam,
        "episode_key": fam,
        "stage": STAGE_ID,
        "tag": "new",
        "book_id": book_id,
        "book_tag": snap.get("book_tag") or book_id,
        "model_id": snap.get("model_id"),
        "registration_id": snap.get("registration_id"),
        "ticker": ticker,
        "name": snap.get("name"),
        "entry_at": entry_at,
        "opened_at": entry_at,
        "days_since_entry": days_since,
        "population": snap.get("population"),
        "package": "M",
        "influences_live": False,
        "observe_only": True,
        "blind_review_id": blind_id,
        "parent_review_id": blind_id,
        "frozen_blind": _frozen_blind_summary(blind_event),
        "path_status": path,
        "charts": {"path_to_plus28": window} if window else {},
        "buy_decision": snap.get("buy_decision"),
        "buy_reason": snap.get("buy_reason"),
        "revisit_days": ENTRY_REVISIT_DAYS,
        "outcome_fields_allowed": True,
        "fair_cost_return_pct_to_plus28": path.get("fair_cost_return_pct_to_plus28"),
        "episode_status_at_plus28": path.get("status"),
    }
    # Outcome fields are intentional here (unlike entry_blind) — keep sell chrome out.
    item.pop("sell_decision", None)
    item.pop("sell_reason", None)
    item["framing"] = (
        f"[{item.get('book_tag')}] {ticker} · bought {_date_key(entry_at)}\n"
        f"Stage: {STAGE_ID} (fixed buy+28d outcome)\n"
        f"Blind parent: {blind_id or '?'} ({item['frozen_blind'].get('blind_action')})\n"
        f"Path status: {path.get('status')} · influences_live=false"
    )
    _attach_revisit_opinion(item)
    return item


def build_entry_revisit_review_queue(
    *,
    data_dir: Path | None = None,
    asof: datetime | None = None,
    active_cap: int = ACTIVE_ATTENTION_CAP,
    sort_by: str | None = None,
) -> dict[str, Any]:
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    clock = asof or _utcnow()
    blind_labels = load_entry_blind_review_labels(root)
    revisit_labels = load_entry_revisit_review_labels(root)
    lab = _safe_read(root / "cue_consumer_mft_observe.json")
    lab_index = _lab_episode_index(lab)

    candidates: list[dict[str, Any]] = []
    for event in _blind_done_events(blind_labels):
        card = build_entry_revisit_card(event, lab_index=lab_index, asof=clock)
        if card is None:
            continue
        if is_actioned(revisit_labels, str(card["review_id"])):
            continue
        candidates.append(card)

    # Lab first, then by entry_at ascending (oldest due first).
    def _rank(item: dict[str, Any]) -> tuple[int, str]:
        pop = 0 if str(item.get("population") or "") == "lab" else 1
        return (pop, str(item.get("entry_at") or ""))

    sort_key = (sort_by or "interesting").strip().lower()
    if sort_key == "ticker":
        ordered = sorted(candidates, key=lambda r: str(r.get("ticker") or ""))
    elif sort_key in {"entry_at", "date"}:
        ordered = sorted(candidates, key=lambda r: str(r.get("entry_at") or ""))
    elif sort_key == "book":
        ordered = sorted(candidates, key=lambda r: str(r.get("book_tag") or r.get("book_id") or ""))
    else:
        ordered = sorted(candidates, key=_rank)

    capped = ordered[: max(0, int(active_cap))]
    # Attach reply tags from revisit labels.
    reply_cards: list[dict[str, Any]] = []
    for row in revisit_labels.get("active_replies") or []:
        if not isinstance(row, dict):
            continue
        if is_actioned(revisit_labels, str(row.get("review_id") or "")):
            continue
        card = dict(row)
        card["tag"] = "reply"
        card["stage"] = STAGE_ID
        card["influences_live"] = False
        reply_cards.append(card)

    active = reply_cards + capped
    awaiting = comments_awaiting_reply(revisit_labels)
    by_book: dict[str, int] = {}
    for row in active:
        key = str(row.get("book_tag") or row.get("book_id") or "?")
        by_book[key] = by_book.get(key, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "stage": STAGE_ID,
        "observe_only": True,
        "influences_live": False,
        "package": "M",
        "ops_doc": OPS_DOC,
        "product_claim": (
            "Fixed buy+28d entry outcome after entry_blind Accept/Comment — "
            "frozen blind summary + path through +28d; never rewrites blind labels; "
            "never fills or knobs"
        ),
        "learning_question": (
            "At fixed buy+28d, does the realized path confirm, revise, or falsify "
            "the sealed blind entry critique — without collapsing into exit autopsy?"
        ),
        "clocks": {
            "entry_revisit_days": ENTRY_REVISIT_DAYS,
            "active_attention_cap": int(active_cap),
            "requires_blind_action": sorted(_BLIND_DONE_KINDS),
        },
        "coverage": {
            "blind_done_events": len(_blind_done_events(blind_labels)),
            "due_candidates": len(candidates),
            "scope": "lab_and_interesting_after_blind",
        },
        "attention_note": (
            f"Active cap {active_cap}: due after buy+{ENTRY_REVISIT_DAYS}d and "
            "entry_blind Accept/Comment. Blind labels immutable."
        ),
        "sort_options": [
            {"id": "interesting", "label": "Interesting"},
            {"id": "entry_at", "label": "Date"},
            {"id": "ticker", "label": "Stock"},
            {"id": "book", "label": "Book"},
        ],
        "labels_store": LABELS_FILENAME,
        "active_count": len(active),
        "actioned_count": len(revisit_labels.get("actioned_review_ids") or []),
        "reply_count": sum(1 for row in active if row.get("tag") == "reply"),
        "new_count": sum(1 for row in active if row.get("tag") != "reply"),
        "by_book": by_book,
        "sort_default": sort_key or "interesting",
        "active": active,
        "unreplied_comments": len(awaiting),
        "history_event_count": len(revisit_labels.get("events") or []),
        "stages_enabled": [PARENT_STAGE_ID, STAGE_ID],
        "stages_parked": ["exit_blind", "exit_revisit"],
        "parent_stage": PARENT_STAGE_ID,
    }


def refresh_entry_revisit_review_queue(
    *,
    data_dir: Path | None = None,
    store_path: Path | None = None,
    persist: bool = True,
    asof: datetime | None = None,
) -> dict[str, Any]:
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    heal_info = {"healed": False, "removed": 0}
    if persist:
        heal_info = heal_entry_revisit_replies_file(root)
    payload = build_entry_revisit_review_queue(data_dir=root, asof=asof)
    payload["labels_heal"] = heal_info
    if persist:
        dest = (
            Path(store_path)
            if store_path is not None
            else (root / "entry_revisit_review_queue.json")
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_json(dest, payload, compact=False)
        payload["path"] = str(dest)
    return payload


def ops_findings_from_entry_revisit_queue(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    findings: list[dict[str, Any]] = []
    active = int(payload.get("active_count") or 0)
    replies = int(payload.get("reply_count") or 0)
    unreplied = int(payload.get("unreplied_comments") or 0)
    due = int((payload.get("coverage") or {}).get("due_candidates") or 0)
    actioned = int(payload.get("actioned_count") or 0)
    findings.append(
        {
            "severity": "info",
            "category": CATEGORY,
            "title": FINDING_TITLE,
            "summary": (
                f"Active entry_revisit reviews: {active} "
                f"(new={payload.get('new_count')}, reply={replies}); "
                f"actioned history={actioned}; due_candidates={due}. "
                f"Fixed buy+{ENTRY_REVISIT_DAYS}d; influences_live=false."
            ),
            "auto_fixable": False,
        }
    )
    if unreplied > 0:
        findings.append(
            {
                "severity": "warn",
                "category": CATEGORY,
                "title": UNACKED_COMMENTS_TITLE,
                "summary": (
                    f"{unreplied} entry_revisit Comment(s) awaiting factory reply "
                    "(Package M; no knobs)."
                ),
                "auto_fixable": False,
            }
        )
    if replies > 0:
        findings.append(
            {
                "severity": "warn",
                "category": CATEGORY,
                "title": PENDING_REPLIES_TITLE,
                "summary": (
                    f"{replies} entry_revisit reply tag(s) awaiting owner Accept/Comment."
                ),
                "auto_fixable": False,
            }
        )
    return findings


__all__ = [
    "ACTIVE_ATTENTION_CAP",
    "CATEGORY",
    "DEFAULT_DATA_DIR",
    "DEFAULT_STORE_PATH",
    "ENTRY_REVISIT_DAYS",
    "FINDING_TITLE",
    "OPS_DOC",
    "PENDING_REPLIES_TITLE",
    "SCHEMA_VERSION",
    "STAGE_ID",
    "STORE_FAILED_TITLE",
    "UNACKED_COMMENTS_TITLE",
    "build_entry_revisit_card",
    "build_entry_revisit_review_queue",
    "entry_revisit_clock_ready",
    "entry_revisit_due_at",
    "entry_revisit_path_window",
    "ops_findings_from_entry_revisit_queue",
    "refresh_entry_revisit_review_queue",
]
