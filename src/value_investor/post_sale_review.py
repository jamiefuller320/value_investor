"""Post-sale review queue — all sealed Lifecycle books + FTSE control.

Package **M** attention / alignment (not Package L auto-tune).
Observe-only: ``influences_live=false``. Never changes fills or knobs.

L622: sortable queue + dual-horizon cards + deterministic framing.
L623: Accept/Comment clear active queue; Comment spawns factory reply stub.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.lifecycle_board import (
    JUST_BOUGHT_DAYS,
    JUST_SOLD_DAYS,
    POST_SALE_DAYS,
    close_in_window,
)
from value_investor.post_sale_review_labels import (
    LABELS_FILENAME,
    comments_awaiting_reply,
    is_actioned,
    load_post_sale_review_labels,
)
from value_investor.sealed_lifecycle import SEALED_MODELS
from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 1
FINDING_TITLE = "Post-sale review queue (observe)"
STORE_FAILED_TITLE = "Post-sale review queue observe failed"
UNACKED_COMMENTS_TITLE = "Post-sale review comments awaiting factory reply"
PENDING_REPLIES_TITLE = "Post-sale review reply tags awaiting owner"
EMPTY_TRAIL_TITLE = "Post-sale review queue empty while sealed exits exist"
DEFAULT_STORE_PATH = Path("docs/data/post_sale_review_queue.json")
DEFAULT_DATA_DIR = Path("docs/data")
OPS_DOC = "docs/ops/post-sale-review-queue.md"
CATEGORY = "research"
CONTROL_BOOK_ID = "ftse_control"
CONTROL_BOOK_TAG = "FTSE control"
CONTROL_TRACK_ID = "buy_tier_level"
CONTROL_MARKET_IDS = frozenset({"ftse350", "ftse_350", "ftse"})
# Wider TF pad around the episode (dual-horizon companion to close_in).
WIDER_BEFORE_DAYS = 180
WIDER_AFTER_DAYS = 90
# Cap sealed post_sale tenure on the candidate set (match board POST_SALE_DAYS).
SEALED_POST_SALE_MAX_DAYS = POST_SALE_DAYS
# Attention filter for active queue (Package M — not dump-all theater).
# just_sold + reply always; post_sale only when fresh or material loss.
POST_SALE_ATTENTION_MAX_DAYS = 21
POST_SALE_ATTENTION_LOSS_PCT = -5.0


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


def _hold_days(entry_at: str | None, exit_at: str | None) -> int | None:
    start = _parse_dt(entry_at)
    end = _parse_dt(exit_at)
    if start is None or end is None:
        return None
    return max(0, (end.date() - start.date()).days)


def _as_pct_display(value: Any, *, already_percent: bool = False) -> float | None:
    """Normalize return to percent points for framing (e.g. -8.66)."""
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if already_percent:
        return round(num, 2)
    # Sealed fair_cost_return is typically a fraction; board realized is fraction too.
    if abs(num) <= 2.0:
        return round(num * 100.0, 2)
    return round(num, 2)


def review_fingerprint(
    *,
    book_id: str,
    ticker: str,
    entry_at: str | None,
    exit_at: str | None,
    kind: str = "exit",
) -> str:
    raw = "|".join(
        [
            str(book_id or "").strip(),
            str(ticker or "").strip().upper(),
            str(entry_at or "").strip(),
            str(exit_at or "").strip(),
            str(kind or "exit").strip(),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def wider_tf_window(
    entry_at: str | None,
    exit_at: str | None,
    *,
    before_days: int = WIDER_BEFORE_DAYS,
    after_days: int = WIDER_AFTER_DAYS,
) -> dict[str, Any] | None:
    """Wider timeframe pad around the episode (climbing-trend read context)."""
    return close_in_window(
        entry_at,
        exit_at,
        before_days=before_days,
        after_days=after_days,
    )


def _framing_line(item: dict[str, Any]) -> str:
    book = str(item.get("book_tag") or item.get("book_id") or "?")
    ticker = str(item.get("ticker") or "?")
    exit_at = str(item.get("exit_at") or "")[:10] or "?"
    hold = item.get("hold_days")
    hold_bit = f"hold {hold}d" if hold is not None else "hold ?"
    exit_kind = str(item.get("exit_kind") or "").strip()
    kind_bit = f" · {exit_kind}" if exit_kind else ""
    basis = str(item.get("basis_label") or "return")
    pct = item.get("return_pct")
    pct_bit = f"{pct}%" if pct is not None else "n/a"
    return (
        f"[{book}] {ticker} · {exit_at} · {hold_bit}{kind_bit}\n"
        f"Charts: episode window + wider TF (owner verifies both)\n"
        f"Outcome ({basis}): {pct_bit}\n"
        f"Context read-only — not a new veto. influences_live=false"
    )


def _base_item(
    *,
    book_id: str,
    book_tag: str,
    ticker: str,
    entry_at: str | None,
    exit_at: str | None,
    exit_kind: str,
    return_pct: float | None,
    basis_label: str,
    model_id: str | None = None,
    registration_id: str | None = None,
    avg_cost: float | None = None,
    exit_price: float | None = None,
    population: str,
    epoch_join_ok: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    close_in = close_in_window(entry_at, exit_at)
    wider = wider_tf_window(entry_at, exit_at)
    rid = review_fingerprint(
        book_id=book_id,
        ticker=ticker,
        entry_at=entry_at,
        exit_at=exit_at,
    )
    item: dict[str, Any] = {
        "review_id": rid,
        "review_fingerprint": rid,
        "tag": "new",
        "book_id": book_id,
        "book_tag": book_tag,
        "model_id": model_id,
        "registration_id": registration_id,
        "ticker": ticker,
        "entry_at": entry_at,
        "exit_at": exit_at,
        "opened_at": entry_at,
        "sold_at": exit_at,
        "hold_days": _hold_days(entry_at, exit_at),
        "exit_kind": exit_kind,
        "return_pct": return_pct,
        "basis_label": basis_label,
        "close_in": close_in,
        "wider_tf": wider,
        "charts": {"episode": close_in, "wider_tf": wider},
        "avg_cost": avg_cost,
        "exit_price": exit_price,
        "population": population,
        "influences_live": False,
        "observe_only": True,
        "package": "M",
    }
    if epoch_join_ok is not None:
        item["epoch_join_ok"] = epoch_join_ok
    if extra:
        item.update(extra)
    item["framing"] = _framing_line(item)
    return item


def _sealed_items(sealed: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(sealed, dict):
        return []
    model_meta = {row["model_id"]: row for row in SEALED_MODELS}
    out: list[dict[str, Any]] = []
    for model in sealed.get("models") or []:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("model_id") or "").strip()
        if not model_id:
            continue
        meta = model_meta.get(model_id) or {}
        book_tag = str(model.get("label") or meta.get("label") or model_id.upper())
        registration_id = str(
            model.get("registration_id") or meta.get("registration_id") or ""
        ).strip() or None
        columns = model.get("columns") if isinstance(model.get("columns"), dict) else {}
        for phase in ("just_sold", "post_sale"):
            packed = columns.get(phase) if isinstance(columns.get(phase), dict) else {}
            chips = packed.get("chips") or packed.get("shown") or []
            for chip in chips:
                if not isinstance(chip, dict):
                    continue
                ticker = str(chip.get("ticker") or "").strip()
                if not ticker:
                    continue
                if str(chip.get("status") or "closed") != "closed":
                    continue
                exit_at = str(chip.get("exit_run_at") or "").strip() or None
                entry_at = str(chip.get("entry_run_at") or "").strip() or None
                if not exit_at:
                    continue
                days = chip.get("days_in_phase")
                try:
                    days_n = int(days) if days is not None else None
                except (TypeError, ValueError):
                    days_n = None
                if phase == "post_sale" and days_n is not None and days_n > SEALED_POST_SALE_MAX_DAYS:
                    continue
                pct = _as_pct_display(chip.get("return_pct"))
                basis = str(chip.get("return_basis") or "fair_cost_episode")
                out.append(
                    _base_item(
                        book_id=model_id,
                        book_tag=book_tag,
                        ticker=ticker,
                        entry_at=entry_at,
                        exit_at=exit_at,
                        exit_kind=phase,
                        return_pct=pct,
                        basis_label=basis,
                        model_id=model_id,
                        registration_id=registration_id,
                        population="sealed_lifecycle",
                        extra={
                            "days_since_exit": days_n,
                            "phase_clock": chip.get("phase_clock"),
                        },
                    )
                )
    return out


def _is_ftse_control_market(market: dict[str, Any]) -> bool:
    mid = str(market.get("market_id") or "").strip().lower()
    if mid in CONTROL_MARKET_IDS:
        return True
    if market.get("is_live") and "ftse" in mid:
        return True
    label = str(market.get("label") or "").lower()
    return mid == "ftse350" or "ftse 350" in label


def _control_items(board: dict[str, Any] | None) -> list[dict[str, Any]]:
    """FTSE control buy_tier_level sold cards. Epoch join fail-closed OK (tagged)."""
    if not isinstance(board, dict):
        return []
    out: list[dict[str, Any]] = []
    for market in board.get("markets") or []:
        if not isinstance(market, dict) or not _is_ftse_control_market(market):
            continue
        for track in market.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            if str(track.get("track_id") or "").strip() != CONTROL_TRACK_ID:
                continue
            columns = (
                track.get("position_columns")
                if isinstance(track.get("position_columns"), dict)
                else {}
            )
            for phase in ("just_sold", "post_sale"):
                packed = columns.get(phase) if isinstance(columns.get(phase), dict) else {}
                for card in packed.get("shown") or []:
                    if not isinstance(card, dict):
                        continue
                    ticker = str(card.get("ticker") or "").strip()
                    if not ticker:
                        continue
                    exit_at = str(card.get("sold_at") or "").strip() or None
                    entry_at = str(card.get("opened_at") or "").strip() or None
                    if not exit_at:
                        continue
                    pct = _as_pct_display(card.get("realized_exit_pnl_pct"))
                    # Board cards may omit epoch keys — fail-closed mark, still queue.
                    epoch_ok = bool(card.get("knob_epoch_started_at") is not None) or bool(
                        card.get("epoch_join_ok")
                    )
                    # Prefer honest null: board tenure path is allowed without join.
                    if "epoch_join_ok" in card:
                        epoch_ok = bool(card.get("epoch_join_ok"))
                    else:
                        epoch_ok = True  # board population already tenure-gated
                    out.append(
                        _base_item(
                            book_id=CONTROL_BOOK_ID,
                            book_tag=CONTROL_BOOK_TAG,
                            ticker=ticker,
                            entry_at=entry_at,
                            exit_at=exit_at,
                            exit_kind=phase,
                            return_pct=pct,
                            basis_label="realized_exit",
                            model_id=CONTROL_TRACK_ID,
                            registration_id=None,
                            avg_cost=_optional_float(card.get("avg_cost")),
                            exit_price=_optional_float(card.get("exit_price")),
                            population="ftse_control_buy_tier_level",
                            epoch_join_ok=epoch_ok,
                            extra={
                                "market_id": market.get("market_id"),
                                "track_id": CONTROL_TRACK_ID,
                                "days_since_exit": card.get("days_in_column"),
                                "name": card.get("name"),
                            },
                        )
                    )
    return out


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        rid = str(item.get("review_id") or "")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(item)
    return out


def _in_attention_queue(item: dict[str, Any]) -> bool:
    """Active-queue attention gate (coverage still counted in candidates)."""
    if str(item.get("tag") or "") == "reply":
        return True
    kind = str(item.get("exit_kind") or "")
    if kind == "just_sold":
        return True
    if kind != "post_sale":
        return True
    days = item.get("days_since_exit")
    try:
        days_n = int(days) if days is not None else None
    except (TypeError, ValueError):
        days_n = None
    if days_n is not None and days_n <= POST_SALE_ATTENTION_MAX_DAYS:
        return True
    pct = item.get("return_pct")
    try:
        pct_n = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct_n = None
    if pct_n is not None and pct_n <= POST_SALE_ATTENTION_LOSS_PCT:
        return True
    return False


def _sort_key(item: dict[str, Any], sort_by: str) -> tuple[Any, ...]:
    key = str(sort_by or "exit_at").strip()
    exit_at = str(item.get("exit_at") or "")
    ticker = str(item.get("ticker") or "")
    book = str(item.get("book_tag") or item.get("book_id") or "")
    tag = str(item.get("tag") or "new")
    pct = item.get("return_pct")
    pct_n = float(pct) if isinstance(pct, (int, float)) else 0.0
    if key == "loss_size":
        return (pct_n, exit_at, book, ticker)
    if key == "book":
        return (book, exit_at, ticker)
    if key == "tag":
        # reply before new for attention
        tag_rank = 0 if tag == "reply" else 1
        return (tag_rank, exit_at, book, ticker)
    if key == "ticker":
        return (ticker, exit_at, book)
    # default exit_at desc → caller reverses
    return (exit_at, book, ticker)


def sort_queue_items(
    items: list[dict[str, Any]],
    *,
    sort_by: str = "exit_at",
    descending: bool | None = None,
) -> list[dict[str, Any]]:
    key = str(sort_by or "exit_at").strip()
    if descending is None:
        descending = key in {"exit_at", "loss_size"}
    ordered = sorted(items, key=lambda row: _sort_key(row, key))
    if descending:
        ordered.reverse()
    return ordered


def build_post_sale_review_queue(
    *,
    data_dir: Path | None = None,
    sealed: dict[str, Any] | None = None,
    board: dict[str, Any] | None = None,
    labels: dict[str, Any] | None = None,
    sort_by: str = "exit_at",
) -> dict[str, Any]:
    """Build active queue + history pointers. Never influences live."""
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    sealed_payload = sealed if sealed is not None else _safe_read(root / "sealed_lifecycle.json")
    board_payload = board if board is not None else _safe_read(root / "lifecycle_board.json")
    labels_store = (
        labels if labels is not None else load_post_sale_review_labels(root)
    )

    candidates = _dedupe_items(_sealed_items(sealed_payload) + _control_items(board_payload))
    active_exits = [
        item
        for item in candidates
        if not is_actioned(labels_store, str(item.get("review_id")))
        and _in_attention_queue(item)
    ]
    reply_cards: list[dict[str, Any]] = []
    for row in labels_store.get("active_replies") or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("review_id") or "").strip()
        if not rid or is_actioned(labels_store, rid):
            continue
        card = dict(row)
        card["tag"] = "reply"
        card["influences_live"] = False
        card["observe_only"] = True
        if not card.get("framing"):
            card["framing"] = _framing_line(card)
        reply_cards.append(card)

    active = sort_queue_items(reply_cards + active_exits, sort_by=sort_by, descending=True)
    sealed_n = sum(1 for row in candidates if row.get("population") == "sealed_lifecycle")
    control_n = sum(
        1 for row in candidates if row.get("population") == "ftse_control_buy_tier_level"
    )
    just_sold_n = sum(1 for row in candidates if row.get("exit_kind") == "just_sold")
    by_book: dict[str, int] = {}
    for row in active:
        key = str(row.get("book_tag") or row.get("book_id") or "?")
        by_book[key] = by_book.get(key, 0) + 1

    awaiting = comments_awaiting_reply(labels_store)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utcnow().isoformat(),
        "observe_only": True,
        "influences_live": False,
        "package": "M",
        "ops_doc": OPS_DOC,
        "product_claim": (
            "Per-exit post-sale review queue across sealed Lifecycle books + "
            "FTSE control — alignment Accept/Comment/reply; never fills or knobs"
        ),
        "learning_question": (
            "Are relevant charts reviewed with the same big-picture issues the "
            "owner sees, and are missed patterns captured into a development "
            "loop that responds?"
        ),
        "clocks": {
            "just_bought_days": JUST_BOUGHT_DAYS,
            "just_sold_days": JUST_SOLD_DAYS,
            "post_sale_days": POST_SALE_DAYS,
            "sealed_post_sale_max_days": SEALED_POST_SALE_MAX_DAYS,
            "wider_before_days": WIDER_BEFORE_DAYS,
            "wider_after_days": WIDER_AFTER_DAYS,
        },
        "coverage": {
            "sealed_models": [row["model_id"] for row in SEALED_MODELS],
            "control": {
                "book_id": CONTROL_BOOK_ID,
                "track_id": CONTROL_TRACK_ID,
                "tag": CONTROL_BOOK_TAG,
                "epoch_join": "fail_closed_ok",
            },
            "candidate_exits": len(candidates),
            "sealed_candidate_exits": sealed_n,
            "control_candidate_exits": control_n,
            "just_sold_candidates": just_sold_n,
            "attention_filter": {
                "just_sold": "always",
                "reply": "always",
                "post_sale_max_days": POST_SALE_ATTENTION_MAX_DAYS,
                "post_sale_loss_pct_at_or_below": POST_SALE_ATTENTION_LOSS_PCT,
            },
        },
        "attention_note": (
            "Active queue = just_sold + reply + post_sale within "
            f"{POST_SALE_ATTENTION_MAX_DAYS}d or return ≤ {POST_SALE_ATTENTION_LOSS_PCT}% "
            f"(candidates within {SEALED_POST_SALE_MAX_DAYS}d still counted for coverage)."
        ),
        "labels_store": LABELS_FILENAME,
        "active_count": len(active),
        "actioned_count": len(labels_store.get("actioned_review_ids") or []),
        "reply_count": sum(1 for row in active if row.get("tag") == "reply"),
        "new_count": sum(1 for row in active if row.get("tag") != "reply"),
        "by_book": by_book,
        "sort_default": sort_by,
        "active": active,
        "unreplied_comments": len(awaiting),
        "history_event_count": len(labels_store.get("events") or []),
    }


def refresh_post_sale_review_queue(
    *,
    data_dir: Path | None = None,
    store_path: Path | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    payload = build_post_sale_review_queue(data_dir=root)
    if persist:
        dest = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_json(dest, payload, compact=False)
        payload["path"] = str(dest)
    return payload


def ops_findings_from_queue(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Observe findings for ops-monitor (never auto_fixable)."""
    if not isinstance(payload, dict):
        return []
    findings: list[dict[str, Any]] = []
    active = int(payload.get("active_count") or 0)
    replies = int(payload.get("reply_count") or 0)
    unreplied = int(payload.get("unreplied_comments") or 0)
    candidates = int((payload.get("coverage") or {}).get("candidate_exits") or 0)
    actioned = int(payload.get("actioned_count") or 0)

    summary = (
        f"Active post-sale reviews: {active} "
        f"(new={payload.get('new_count')}, reply={replies}); "
        f"actioned history={actioned}; "
        f"candidates sealed+control={candidates}. "
        f"Accept/Comment observe-only (influences_live=false)."
    )
    findings.append(
        {
            "severity": "info",
            "category": CATEGORY,
            "title": FINDING_TITLE,
            "summary": summary,
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
                    f"{unreplied} owner Comment(s) lack a factory reply. "
                    "Development loop must respond (stub or LLM reply text) — "
                    "never silent ignore; never auto-apply knobs."
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
                    f"{replies} reply-tagged item(s) await owner Accept/Comment "
                    "on the factory response (alignment only)."
                ),
                "auto_fixable": False,
            }
        )
    just_sold = int((payload.get("coverage") or {}).get("just_sold_candidates") or 0)
    if active == 0 and just_sold > 0 and actioned == 0:
        findings.append(
            {
                "severity": "warn",
                "category": CATEGORY,
                "title": EMPTY_TRAIL_TITLE,
                "summary": (
                    f"Queue active=0 while {just_sold} just_sold candidates exist "
                    "and labels history is empty — refresh or check coverage."
                ),
                "auto_fixable": False,
            }
        )
    return findings


__all__ = [
    "CONTROL_BOOK_ID",
    "CONTROL_BOOK_TAG",
    "DEFAULT_DATA_DIR",
    "DEFAULT_STORE_PATH",
    "EMPTY_TRAIL_TITLE",
    "FINDING_TITLE",
    "PENDING_REPLIES_TITLE",
    "STORE_FAILED_TITLE",
    "UNACKED_COMMENTS_TITLE",
    "WIDER_AFTER_DAYS",
    "WIDER_BEFORE_DAYS",
    "build_post_sale_review_queue",
    "ops_findings_from_queue",
    "refresh_post_sale_review_queue",
    "review_fingerprint",
    "sort_queue_items",
    "wider_tf_window",
]
