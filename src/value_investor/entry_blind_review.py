"""Entry-blind review queue — thin v0 Package M instrument.

``entry_blind``: critique recent lab / interesting buys with PIT charts and buy
reasons only — **no** post-fill path, realized %, exit reason, or sell chrome.

Observe-only: ``influences_live=false``. Alignment-only — never knobs/fills.
See ``docs/ops/entry-blind-review.md``.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.entry_blind_review_labels import (
    LABELS_FILENAME,
    actioned_episode_keys,
    comments_awaiting_reply,
    heal_entry_blind_replies_file,
    is_actioned,
    load_entry_blind_review_labels,
    prune_active_replies,
)
from value_investor.lifecycle_board import JUST_BOUGHT_DAYS
from value_investor.post_sale_decision_reasons import (
    UNKNOWN_LABEL,
    bind_decision_reasons,
    load_control_trade_index,
    load_sealed_episode_indexes,
)
from value_investor.sealed_lifecycle import SEALED_MODELS
from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 1
STAGE_ID = "entry_blind"
FINDING_TITLE = "Entry-blind review queue (observe)"
STORE_FAILED_TITLE = "Entry-blind review queue observe failed"
UNACKED_COMMENTS_TITLE = "Entry-blind comments awaiting factory reply"
PENDING_REPLIES_TITLE = "Entry-blind reply tags awaiting owner"
DEFAULT_STORE_PATH = Path("docs/data/entry_blind_review_queue.json")
DEFAULT_DATA_DIR = Path("docs/data")
OPS_DOC = "docs/ops/entry-blind-review.md"
CATEGORY = "research"
LAB_BOOK_ID = "cue_consumer_mft"
LAB_BOOK_TAG = "Cue-consumer MFT"
# PIT lookback through buy day (hard clip — no forward bars).
PIT_BEFORE_DAYS = 180
# Cap active sealed spray; lab rows always keep priority within the cap.
ACTIVE_ATTENTION_CAP = 12
# Fields that must never appear on blind cards (outcome / exit leakage).
FORBIDDEN_OUTCOME_KEYS = frozenset(
    {
        "return_pct",
        "realized_pct",
        "fair_cost_return",
        "exit_at",
        "exit_price",
        "sold_at",
        "hold_days",
        "basis_label",
        "exit_kind",
        "exit_reason",
        "sell_decision",
        "sell_reason",
        "wider_tf",  # post-sale wider includes after-exit pad
        "close_in",  # open sleeve omits end → forward path risk
    }
)


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


def family_id(*, book_id: str, ticker: str, entry_at: str | None) -> str:
    """Durable family key for entry stages: book|TICKER|entry_day."""
    return "|".join(
        [
            str(book_id or "").strip(),
            str(ticker or "").strip().upper(),
            _date_key(entry_at),
        ]
    )


def review_fingerprint(
    *,
    book_id: str,
    ticker: str,
    entry_at: str | None,
    kind: str = STAGE_ID,
) -> str:
    """Stable Accept/Comment id — entry_blind kind (no exit timestamp)."""
    raw = "|".join(
        [
            str(book_id or "").strip(),
            str(ticker or "").strip().upper(),
            str(entry_at or "").strip(),
            str(kind or STAGE_ID).strip(),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def entry_blind_pit_window(
    entry_at: str | None,
    *,
    before_days: int = PIT_BEFORE_DAYS,
) -> dict[str, Any] | None:
    """PIT chart window hard-clipped at buy day — no forward path."""
    opened = _parse_dt(entry_at)
    if opened is None:
        return None
    buy_day = opened.date().isoformat()
    return {
        "start": (opened - timedelta(days=int(before_days))).date().isoformat(),
        "end": buy_day,
        "days_before": int(before_days),
        "days_after": 0,
        "blind_clip_at": "entry",
        "forbidden_forward_path": True,
        "asof": buy_day,
    }


def strip_outcome_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed strip of post-fill / exit leakage keys."""
    out = {k: v for k, v in item.items() if k not in FORBIDDEN_OUTCOME_KEYS}
    # Nested charts must not carry open-ended episode windows.
    charts = out.get("charts")
    if isinstance(charts, dict):
        out["charts"] = {
            k: v for k, v in charts.items() if k in {"pit", "entry_pit"} and isinstance(v, dict)
        }
    # Never leave sell chrome even if nested under decision blobs.
    out.pop("sell_decision", None)
    out.pop("sell_reason", None)
    out["stage"] = STAGE_ID
    out["outcome_fields_stripped"] = True
    out["influences_live"] = False
    out["observe_only"] = True
    return out


def assert_no_outcome_leakage(item: dict[str, Any]) -> list[str]:
    """Return forbidden keys present with non-empty values (for tests / guards)."""
    leaks: list[str] = []
    for key in FORBIDDEN_OUTCOME_KEYS:
        if key not in item:
            continue
        val = item.get(key)
        if val in (None, "", [], {}, False):
            continue
        leaks.append(key)
    charts = item.get("charts") if isinstance(item.get("charts"), dict) else {}
    for name, window in charts.items():
        if not isinstance(window, dict):
            continue
        if window.get("forbidden_forward_path") is not True and name != "pit":
            leaks.append(f"charts.{name}")
        end = str(window.get("end") or "")
        asof = str(window.get("asof") or item.get("entry_at") or "")[:10]
        if end and asof and end > asof:
            leaks.append(f"charts.{name}.end_after_entry")
    return leaks


def _framing_line(item: dict[str, Any]) -> str:
    book = str(item.get("book_tag") or item.get("book_id") or "?")
    ticker = str(item.get("ticker") or "?")
    entry_day = str(item.get("entry_at") or "")[:10] or "?"
    buy = item.get("buy_decision") if isinstance(item.get("buy_decision"), dict) else {}
    buy_bit = str(buy.get("label") or item.get("buy_reason") or UNKNOWN_LABEL)
    return (
        f"[{book}] {ticker} · bought {entry_day}\n"
        f"Stage: {STAGE_ID} (blind entry critique)\n"
        f"Bought because: {buy_bit}\n"
        f"Chart: PIT clip through buy day only — no post-fill path\n"
        f"Outcome fields stripped — influences_live=false"
    )


def _attach_entry_blind_opinion(item: dict[str, Any]) -> dict[str, Any]:
    """Deterministic entry-only opinion — never cites realized % / exit."""
    buy = item.get("buy_decision") if isinstance(item.get("buy_decision"), dict) else {}
    buy_label = str(buy.get("label") or UNKNOWN_LABEL)
    buy_ok = bool(buy.get("join_ok"))
    strengths: list[str] = []
    weaknesses: list[str] = []
    if buy_ok:
        strengths.append(f"Buy decision is joinable: {buy_label} — ground comments on that trail.")
    else:
        weaknesses.append(
            "Buy reason unjoinable / unknown — do not invent a thesis from the chart alone."
        )
    strengths.append(
        "Blind stage: critique entry quality from PIT chart + reasons only "
        "(no hindsight from the post-fill path)."
    )
    if not weaknesses:
        weaknesses.append(
            "Owner Comment can add entry-lens patterns (range location, thesis quality) "
            "without waiting for exit autopsy."
        )
    learning = (
        "Carry one concrete entry-lens pattern forward for super-book stock choice / "
        "buy timing / buy strategy — never auto-apply knobs (Package M)."
    )
    opinion = (
        f"Blind entry critique for {item.get('ticker') or '?'}: "
        f"bought because {buy_label}. "
        "Judge whether the entry was sound given only information at / just after the buy."
    )
    item["llm_opinion"] = opinion
    item["learning_points"] = [
        "No post-fill path or realized % on this card — keep critique entry-lens only.",
        learning,
    ]
    item["buy_strengths"] = strengths[:4]
    item["buy_weaknesses"] = weaknesses[:4]
    item["learning_point_forward"] = learning
    item["lens_side"] = "entry"
    item["opinion_source"] = "deterministic_entry_blind_v0"
    item["chart_annotations"] = {
        "pit": "PIT through buy day — forward bars forbidden on entry_blind."
    }
    if not item.get("dialogue"):
        item["dialogue"] = [
            {
                "role": "factory",
                "kind": "initial_opinion",
                "text": opinion,
                "learning_points": list(item["learning_points"]),
                "chart_annotations": dict(item["chart_annotations"]),
                "buy_strengths": list(item["buy_strengths"]),
                "buy_weaknesses": list(item["buy_weaknesses"]),
                "learning_point_forward": learning,
                "lens_side": "entry",
                "source": "deterministic_entry_blind_v0",
                "at": _utcnow().isoformat(),
                "influences_live": False,
            }
        ]
    return item


def _base_item(
    *,
    book_id: str,
    book_tag: str,
    ticker: str,
    entry_at: str | None,
    population: str,
    model_id: str | None = None,
    registration_id: str | None = None,
    name: str | None = None,
    days_since_entry: int | None = None,
    extra: dict[str, Any] | None = None,
    sealed_indexes: dict[str, dict[str, dict[str, Any]]] | None = None,
    control_trades: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    pit = entry_blind_pit_window(entry_at)
    rid = review_fingerprint(book_id=book_id, ticker=ticker, entry_at=entry_at)
    fam = family_id(book_id=book_id, ticker=ticker, entry_at=entry_at)
    item: dict[str, Any] = {
        "review_id": rid,
        "review_fingerprint": rid,
        "family_id": fam,
        "episode_key": fam,  # entry stages: family == episode without exit day
        "stage": STAGE_ID,
        "tag": "new",
        "book_id": book_id,
        "book_tag": book_tag,
        "model_id": model_id,
        "registration_id": registration_id,
        "ticker": ticker,
        "name": name,
        "entry_at": entry_at,
        "opened_at": entry_at,
        "days_since_entry": days_since_entry,
        "charts": {"pit": pit} if pit else {},
        "population": population,
        "package": "M",
        "influences_live": False,
        "observe_only": True,
        "outcome_fields_stripped": True,
    }
    if extra:
        for key, value in extra.items():
            if key not in FORBIDDEN_OUTCOME_KEYS:
                item[key] = value
    # Bind buy reasons; strip sell chrome immediately after.
    bind_decision_reasons(
        item,
        sealed_indexes=sealed_indexes if sealed_indexes is not None else {},
        control_trades=control_trades if control_trades is not None else {},
    )
    item = strip_outcome_fields(item)
    item["framing"] = _framing_line(item)
    _attach_entry_blind_opinion(item)
    return item


def _sealed_just_bought_items(
    sealed: dict[str, Any] | None,
    *,
    sealed_indexes: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Recent sealed open buys — interim interesting feed until lab fills land."""
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
        registration_id = (
            str(model.get("registration_id") or meta.get("registration_id") or "").strip() or None
        )
        columns = model.get("columns") if isinstance(model.get("columns"), dict) else {}
        packed = columns.get("just_bought") if isinstance(columns.get("just_bought"), dict) else {}
        chips = packed.get("chips") or packed.get("shown") or []
        for chip in chips:
            if not isinstance(chip, dict):
                continue
            ticker = str(chip.get("ticker") or "").strip()
            if not ticker:
                continue
            if str(chip.get("status") or "open") not in {"open", "held", ""}:
                # Skip closed chips that somehow land in just_bought.
                if str(chip.get("status") or "") == "closed":
                    continue
            entry_at = str(chip.get("entry_run_at") or chip.get("opened_at") or "").strip() or None
            if not entry_at:
                continue
            days = chip.get("days_in_phase")
            try:
                days_n = int(days) if days is not None else None
            except (TypeError, ValueError):
                days_n = None
            if days_n is not None and days_n > JUST_BOUGHT_DAYS:
                continue
            extra: dict[str, Any] = {"phase_clock": chip.get("phase_clock")}
            if chip.get("entry_reason"):
                extra["entry_reason"] = chip.get("entry_reason")
            if isinstance(chip.get("entry_detail"), dict):
                extra["entry_detail"] = chip.get("entry_detail")
            # Deliberately omit return_pct / exit_* from chip even if present.
            out.append(
                _base_item(
                    book_id=model_id,
                    book_tag=book_tag,
                    ticker=ticker,
                    entry_at=entry_at,
                    population="sealed_just_bought",
                    model_id=model_id,
                    registration_id=registration_id,
                    name=str(chip.get("name") or "").strip() or None,
                    days_since_entry=days_n,
                    extra=extra,
                    sealed_indexes=sealed_indexes,
                    control_trades={},
                )
            )
    return out


def _lab_buy_items(
    lab: dict[str, Any] | None,
    *,
    sealed_indexes: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Cue-consumer MFT lab buys when the observe store exposes them."""
    if not isinstance(lab, dict):
        return []
    out: list[dict[str, Any]] = []
    # Prefer explicit open / recent buy rows when the walker lands them.
    rows: list[Any] = []
    for key in ("open_lab_buys", "recent_lab_buys", "lab_buys", "closed_episodes_sample"):
        packed = lab.get(key)
        if isinstance(packed, list):
            rows.extend(packed)
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        entry_at = (
            str(row.get("entry_at") or row.get("bought_at") or row.get("opened_at") or "").strip()
            or None
        )
        if not ticker or not entry_at:
            continue
        out.append(
            _base_item(
                book_id=str(lab.get("lab_id") or LAB_BOOK_ID),
                book_tag=LAB_BOOK_TAG,
                ticker=ticker,
                entry_at=entry_at,
                population="lab",
                model_id=str(lab.get("lab_id") or LAB_BOOK_ID),
                registration_id=str(lab.get("registration_id") or "").strip() or None,
                name=str(row.get("name") or "").strip() or None,
                extra={"lab_source_key": "cue_consumer_mft"},
                sealed_indexes=sealed_indexes,
                control_trades={},
            )
        )
    return out


def _queue_card_usable(item: dict[str, Any]) -> bool:
    ticker = str(item.get("ticker") or "").strip()
    if not ticker or ticker == "?":
        return False
    book = str(item.get("book_tag") or item.get("book_id") or "").strip()
    if book in {"", "?"}:
        return False
    if not _date_key(item.get("entry_at")):
        return False
    return True


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one card per family_id (newest entry timestamp wins)."""
    by_family: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        fam = str(item.get("family_id") or item.get("episode_key") or "").strip()
        if not fam:
            continue
        prior = by_family.get(fam)
        if prior is None:
            by_family[fam] = item
            continue
        if str(item.get("entry_at") or "") >= str(prior.get("entry_at") or ""):
            by_family[fam] = item
    return list(by_family.values())


def _interest_rank(item: dict[str, Any]) -> int:
    """Lower = more interesting. Lab first; joinable buy reasons next."""
    pop = str(item.get("population") or "")
    if pop == "lab":
        return 0
    buy = item.get("buy_decision") if isinstance(item.get("buy_decision"), dict) else {}
    code = str(buy.get("code") or "")
    if buy.get("join_ok") and (
        code.startswith("identity_") or "break" in code or code in {"enter_target_set"}
    ):
        return 1
    if buy.get("join_ok"):
        return 2
    return 3


def _entry_at_desc_token(entry_at: str) -> str:
    text = str(entry_at or "")
    return "".join(chr(0x10FFFF - ord(ch)) for ch in text)


def sort_entry_blind_items(
    items: list[dict[str, Any]],
    *,
    sort_by: str = "interesting",
) -> list[dict[str, Any]]:
    key = str(sort_by or "interesting").strip()
    if key == "interesting":
        return sorted(
            items,
            key=lambda row: (
                0 if str(row.get("tag") or "") == "reply" else 1,
                _interest_rank(row),
                _entry_at_desc_token(str(row.get("entry_at") or "")),
                str(row.get("book_tag") or ""),
                str(row.get("ticker") or ""),
            ),
        )
    if key in {"ticker", "stock", "name"}:
        return sorted(
            items,
            key=lambda row: (
                str(row.get("name") or row.get("ticker") or "").casefold(),
                str(row.get("ticker") or "").casefold(),
            ),
        )
    if key == "book":
        return sorted(
            items,
            key=lambda row: (
                str(row.get("book_tag") or row.get("book_id") or ""),
                str(row.get("entry_at") or ""),
            ),
        )
    if key == "tag":
        return sorted(
            items,
            key=lambda row: (
                0 if str(row.get("tag") or "") == "reply" else 1,
                str(row.get("entry_at") or ""),
            ),
        )
    # Date = entry newest first
    return sorted(items, key=lambda row: str(row.get("entry_at") or ""), reverse=True)


def build_entry_blind_review_queue(
    *,
    data_dir: Path | None = None,
    sealed: dict[str, Any] | None = None,
    lab: dict[str, Any] | None = None,
    labels: dict[str, Any] | None = None,
    sort_by: str = "interesting",
    active_cap: int = ACTIVE_ATTENTION_CAP,
) -> dict[str, Any]:
    """Build active entry_blind queue. Never influences live."""
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    sealed_payload = sealed if sealed is not None else _safe_read(root / "sealed_lifecycle.json")
    lab_payload = lab if lab is not None else _safe_read(root / "cue_consumer_mft_observe.json")
    labels_store = labels if labels is not None else load_entry_blind_review_labels(root)
    sealed_indexes = load_sealed_episode_indexes(root)
    control_trades = load_control_trade_index(root)

    candidates = _dedupe_items(
        _lab_buy_items(lab_payload, sealed_indexes=sealed_indexes)
        + _sealed_just_bought_items(sealed_payload, sealed_indexes=sealed_indexes)
    )
    # Re-strip after any bind side effects; fail-closed leakage guard.
    candidates = [strip_outcome_fields(row) for row in candidates]
    candidates_by_id = {
        str(item.get("review_id") or "").strip(): item
        for item in candidates
        if str(item.get("review_id") or "").strip()
    }

    prune_active_replies(labels_store)
    cleared_families = actioned_episode_keys(labels_store)
    active_buys = [
        item
        for item in candidates
        if not is_actioned(labels_store, str(item.get("review_id")))
        and str(item.get("family_id") or item.get("episode_key") or "").strip()
        not in cleared_families
        and _queue_card_usable(item)
        and not assert_no_outcome_leakage(item)
    ]

    reply_cards: list[dict[str, Any]] = []
    seen_reply_ids: set[str] = set()
    for row in labels_store.get("active_replies") or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("review_id") or "").strip()
        if not rid or is_actioned(labels_store, rid) or rid in seen_reply_ids:
            continue
        card = strip_outcome_fields(dict(row))
        card["tag"] = "reply"
        card["stage"] = STAGE_ID
        parent_id = str(card.get("parent_review_id") or "").strip()
        parent = candidates_by_id.get(parent_id) if parent_id else None
        if parent and not _queue_card_usable(card):
            for key in ("book_id", "book_tag", "ticker", "entry_at", "family_id", "charts"):
                if card.get(key) in (None, "", "?") and parent.get(key) not in (None, ""):
                    card[key] = parent.get(key)
        if not card.get("buy_decision"):
            bind_decision_reasons(
                card,
                sealed_indexes=sealed_indexes,
                control_trades=control_trades,
            )
            card = strip_outcome_fields(card)
        if not card.get("framing"):
            card["framing"] = _framing_line(card)
        if not card.get("llm_opinion"):
            _attach_entry_blind_opinion(card)
        if not _queue_card_usable(card) or assert_no_outcome_leakage(card):
            continue
        seen_reply_ids.add(rid)
        reply_cards.append(card)

    ordered = sort_entry_blind_items(reply_cards + active_buys, sort_by=sort_by)
    # Cap: keep all replies; fill remaining slots with buys (lab already ranked first).
    capped: list[dict[str, Any]] = []
    buy_slots = max(0, int(active_cap))
    for row in ordered:
        if str(row.get("tag") or "") == "reply":
            capped.append(row)
            continue
        if buy_slots <= 0:
            continue
        capped.append(row)
        buy_slots -= 1

    lab_n = sum(1 for row in candidates if row.get("population") == "lab")
    sealed_n = sum(1 for row in candidates if row.get("population") == "sealed_just_bought")
    by_book: dict[str, int] = {}
    for row in capped:
        key = str(row.get("book_tag") or row.get("book_id") or "?")
        by_book[key] = by_book.get(key, 0) + 1

    awaiting = comments_awaiting_reply(labels_store)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utcnow().isoformat(),
        "stage": STAGE_ID,
        "observe_only": True,
        "influences_live": False,
        "package": "M",
        "ops_doc": OPS_DOC,
        "product_claim": (
            "Blind entry critique for lab / interesting buys — PIT chart through "
            "buy day + buy decision reasons; Accept/Comment; no post-fill path / "
            "no realized %; never fills or knobs"
        ),
        "learning_question": (
            "Given only information available at / just after the buy, was this a "
            "sound entry under the intended entry lens / policy?"
        ),
        "clocks": {
            "pit_before_days": PIT_BEFORE_DAYS,
            "just_bought_days": JUST_BOUGHT_DAYS,
            "active_attention_cap": int(active_cap),
            "entry_revisit_days": 28,  # sibling stage: entry_revisit queue
        },
        "coverage": {
            "candidate_buys": len(candidates),
            "lab_candidate_buys": lab_n,
            "sealed_just_bought_candidates": sealed_n,
            "scope": "lab_and_interesting_capped",
            "forbidden_outcome_keys": sorted(FORBIDDEN_OUTCOME_KEYS),
        },
        "attention_note": (
            f"Active cap {active_cap}: lab buys first, then sealed just_bought "
            f"(≤{JUST_BOUGHT_DAYS}d). Outcome fields stripped; PIT end=buy day."
        ),
        "sort_options": [
            {"id": "interesting", "label": "Interesting"},
            {"id": "entry_at", "label": "Date"},
            {"id": "ticker", "label": "Stock"},
            {"id": "book", "label": "Book"},
            {"id": "tag", "label": "Tag"},
        ],
        "sort_policy": {
            "default": "interesting",
            "interesting": {
                "high": "lab buys",
                "mid": "joinable / identity-ish buy reasons",
                "low": "unjoinable sealed just_bought",
            },
        },
        "labels_store": LABELS_FILENAME,
        "active_count": len(capped),
        "actioned_count": len(labels_store.get("actioned_review_ids") or []),
        "reply_count": sum(1 for row in capped if row.get("tag") == "reply"),
        "new_count": sum(1 for row in capped if row.get("tag") != "reply"),
        "by_book": by_book,
        "sort_default": sort_by or "interesting",
        "active": capped,
        "unreplied_comments": len(awaiting),
        "history_event_count": len(labels_store.get("events") or []),
        "stages_enabled": [STAGE_ID, "entry_revisit"],
        "stages_parked": ["exit_blind", "exit_revisit"],
    }


def refresh_entry_blind_review_queue(
    *,
    data_dir: Path | None = None,
    store_path: Path | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    heal_info = {"healed": False, "removed": 0}
    if persist:
        heal_info = heal_entry_blind_replies_file(root)
    payload = build_entry_blind_review_queue(data_dir=root)
    payload["labels_heal"] = heal_info
    if persist:
        dest = (
            Path(store_path) if store_path is not None else (root / "entry_blind_review_queue.json")
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_json(dest, payload, compact=False)
        payload["path"] = str(dest)
    return payload


def ops_findings_from_entry_blind_queue(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Observe findings for ops-monitor (never auto_fixable)."""
    if not isinstance(payload, dict):
        return []
    findings: list[dict[str, Any]] = []
    active = int(payload.get("active_count") or 0)
    replies = int(payload.get("reply_count") or 0)
    unreplied = int(payload.get("unreplied_comments") or 0)
    candidates = int((payload.get("coverage") or {}).get("candidate_buys") or 0)
    actioned = int(payload.get("actioned_count") or 0)
    summary = (
        f"Active entry_blind reviews: {active} "
        f"(new={payload.get('new_count')}, reply={replies}); "
        f"actioned history={actioned}; candidates={candidates}. "
        f"PIT-only; influences_live=false."
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
                    f"{unreplied} owner Comment(s) lack a factory reply on entry_blind. "
                    "Never silent ignore; never auto-apply knobs."
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
                    f"{replies} entry_blind reply-tagged item(s) await owner "
                    "Accept/Comment (alignment only)."
                ),
                "auto_fixable": False,
            }
        )
    return findings


__all__ = [
    "ACTIVE_ATTENTION_CAP",
    "DEFAULT_DATA_DIR",
    "DEFAULT_STORE_PATH",
    "FINDING_TITLE",
    "FORBIDDEN_OUTCOME_KEYS",
    "OPS_DOC",
    "PIT_BEFORE_DAYS",
    "STAGE_ID",
    "STORE_FAILED_TITLE",
    "assert_no_outcome_leakage",
    "build_entry_blind_review_queue",
    "entry_blind_pit_window",
    "family_id",
    "ops_findings_from_entry_blind_queue",
    "refresh_entry_blind_review_queue",
    "review_fingerprint",
    "sort_entry_blind_items",
    "strip_outcome_fields",
]
