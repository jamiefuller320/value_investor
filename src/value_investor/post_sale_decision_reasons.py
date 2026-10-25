"""Bind structured buy / sell decision reasons onto post-sale review cards.

Package **M** alignment only — never invents narrative when the trail cannot
be joined. Prefer episode / rebalance structured fields over model prose.
``influences_live=false``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json

UNKNOWN_CODE = "unknown_unjoinable"
UNKNOWN_LABEL = "Unknown — unjoinable (no structured trail)"

# Human-readable labels for sealed / control reason codes we already emit.
REASON_LABELS: dict[str, str] = {
    "enter_buy_tier": "Entered buy-tier (new cross)",
    "leave_buy_tier": "Left buy-tier (identity exit)",
    "hold_trading_days": "Hold horizon (63 trading days)",
    "identity_break_ey_band": "Left EY top band (identity break)",
    "identity_break_missing_row": "Missing screen row (identity break)",
    "quality_break_financial_health": "Financial health fail (quality break)",
    "left_target_set": "Left target / buy-tier set (control)",
    "enter_target_set": "Entered target / buy-tier set (control)",
    "filters_newly_clear": "Filters newly cleared (entry)",
    "ai_filters_newly_clear": "AI/filter gates newly cleared (entry)",
}

# Observe store filenames (keep local to avoid importing sealed_lifecycle → pandas).
SEALED_OBSERVE_STORES: tuple[tuple[str, str], ...] = (
    ("n200", "n200_tech_timing_observe.json"),
    ("n201", "n201_value_mom_observe.json"),
    ("n206", "n206_plain_ey_observe.json"),
    ("n210", "n210_ai_judgment_observe.json"),
)

# Books whose exit rule is a single deterministic identity (not 63d-or-break).
N200_MODEL_IDS = frozenset({"n200"})
CONTROL_BOOK_IDS = frozenset({"ftse_control"})
CONTROL_REBALANCE_REL = Path("paper_automation/buy_tier_level/rebalance_log.json")


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _day_key(value: Any) -> str:
    parsed = _parse_dt(value)
    if parsed is None:
        return str(value or "").strip()[:10]
    return parsed.date().isoformat()


def _safe_read(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        payload = read_json(Path(path))
    except (OSError, FileNotFoundError, ValueError, TypeError):
        return None
    if isinstance(payload, (dict, list)):
        return payload
    return None


def reason_label(code: str | None, *, fallback: str | None = None) -> str:
    raw = str(code or "").strip()
    if not raw:
        return fallback or UNKNOWN_LABEL
    if raw in REASON_LABELS:
        return REASON_LABELS[raw]
    if raw.startswith("identity_break_"):
        return f"Identity break ({raw.removeprefix('identity_break_')})"
    if raw.startswith("quality_break_"):
        return f"Quality break ({raw.removeprefix('quality_break_')})"
    # Trade note already human — use as label when no known code.
    if " " in raw or "—" in raw or ("-" in raw and len(raw) > 24):
        return raw
    return fallback or raw.replace("_", " ")


def _decision(
    *,
    side: str,
    code: str | None,
    source: str,
    join_ok: bool,
    structured: dict[str, Any] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    resolved_code = str(code or "").strip() or None
    if not join_ok or not resolved_code:
        return {
            "side": side,
            "code": UNKNOWN_CODE,
            "label": UNKNOWN_LABEL,
            "source": source or "unjoinable",
            "join_ok": False,
            "structured": structured or {},
            "influences_live": False,
        }
    return {
        "side": side,
        "code": resolved_code,
        "label": label or reason_label(resolved_code),
        "source": source,
        "join_ok": True,
        "structured": structured or {},
        "influences_live": False,
    }


def _entry_code_from_detail(detail: Any, *, model_id: str | None) -> tuple[str | None, dict[str, Any]]:
    """Map a real ``entry_detail`` dict → code. Never invents when detail is missing."""
    if not isinstance(detail, dict) or not detail:
        return None, {}
    structured = {
        key: detail.get(key)
        for key in (
            "earnings_yield",
            "in_ey_top30_local",
            "momentum_12_1",
            "financial_health_pass",
            "require_momentum",
            "adjusted_signal",
            "research_verdict",
            "conviction_score",
            "timing_signal",
        )
        if key in detail
    }
    mid = str(model_id or "").strip().lower()
    if mid == "n210" or "research_verdict" in detail or "conviction_score" in detail:
        return "ai_filters_newly_clear", structured
    return "filters_newly_clear", structured


# Progressive sealed books whose *entry* rule is a single identity (exit is not).
SEALED_FILTER_ENTRY_MODELS: dict[str, str] = {
    "n201": "filters_newly_clear",
    "n206": "filters_newly_clear",
    "n210": "ai_filters_newly_clear",
}


def _entry_label_from_structured(code: str | None, structured: dict[str, Any]) -> str:
    base = reason_label(code)
    bits: list[str] = []
    if structured.get("in_ey_top30_local") is True:
        bits.append("EY top 30%")
    if structured.get("financial_health_pass") is True:
        bits.append("FH pass")
    if structured.get("require_momentum") is True and structured.get("momentum_12_1") is not None:
        bits.append("mom>0")
    if structured.get("require_momentum") is False:
        bits.append("no mom gate")
    verdict = structured.get("research_verdict")
    if verdict:
        bits.append(f"verdict={verdict}")
    if bits:
        return f"{base}: {', '.join(bits)}"
    return base


def _normalize_exit_code(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    lower = text.lower()
    if "left target" in lower or "left buy" in lower:
        return "left_target_set"
    if "enter" in lower and "buy" in lower:
        return "enter_buy_tier"
    if text in REASON_LABELS or text.startswith("identity_break_") or text.startswith(
        "quality_break_"
    ):
        return text
    # Keep machine codes; human notes stay as code when short.
    if " " not in text and len(text) <= 64:
        return text
    if "left target" in lower:
        return "left_target_set"
    return text


def _episode_key(ticker: str, entry_at: str | None, exit_at: str | None) -> str:
    return "|".join(
        [
            str(ticker or "").strip().upper(),
            _day_key(entry_at),
            _day_key(exit_at),
        ]
    )


def _index_observe_episodes(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key in ("lifecycle_episodes", "episodes_sample", "episodes"):
        block = payload.get(key)
        if not isinstance(block, list):
            continue
        for row in block:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").strip()
            if not ticker:
                continue
            entry = row.get("entry_run_at") or row.get("entry_at")
            exit_at = row.get("exit_run_at") or row.get("exit_at")
            # Prefer richer rows (with exit_reason) over slim ones.
            ek = _episode_key(ticker, entry, exit_at)
            prior = out.get(ek)
            richer = bool(row.get("exit_reason") or row.get("entry_detail") or row.get("entry_reason"))
            if prior is None or (richer and not (
                prior.get("exit_reason") or prior.get("entry_detail") or prior.get("entry_reason")
            )):
                out[ek] = row
    return out


def load_sealed_episode_indexes(
    data_dir: Path | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """model_id → episode_key → episode row (best available)."""
    root = Path(data_dir) if data_dir is not None else Path("docs/data")
    indexes: dict[str, dict[str, dict[str, Any]]] = {}
    for model_id, store_name in SEALED_OBSERVE_STORES:
        payload = _safe_read(root / store_name)
        indexes[model_id] = _index_observe_episodes(
            payload if isinstance(payload, dict) else None
        )
    return indexes


def _control_trade_index(entries: list[Any]) -> dict[str, list[dict[str, Any]]]:
    """ticker → list of {side, acted_at, note, day}."""
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for trade in entry.get("trades") or []:
            if not isinstance(trade, dict):
                continue
            ticker = str(trade.get("ticker") or "").strip().upper()
            side = str(trade.get("side") or "").strip().lower()
            if not ticker or side not in {"buy", "sell"}:
                continue
            acted = trade.get("acted_at") or entry.get("logged_at")
            row = {
                "side": side,
                "acted_at": acted,
                "day": _day_key(acted),
                "note": str(trade.get("note") or "").strip(),
                "position_closed": trade.get("position_closed"),
            }
            by_ticker.setdefault(ticker, []).append(row)
    return by_ticker


def load_control_trade_index(data_dir: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    root = Path(data_dir) if data_dir is not None else Path("docs/data")
    payload = _safe_read(root / CONTROL_REBALANCE_REL)
    if not isinstance(payload, list):
        return {}
    return _control_trade_index(payload)


def _match_control_trade(
    trades: list[dict[str, Any]],
    *,
    side: str,
    at: str | None,
) -> dict[str, Any] | None:
    day = _day_key(at)
    same_side = [row for row in trades if row.get("side") == side]
    if not same_side:
        return None
    if day:
        exact = [row for row in same_side if row.get("day") == day]
        if len(exact) == 1:
            return exact[0]
        if exact:
            # Prefer position_closed sells / first buy that day.
            closed = [row for row in exact if row.get("position_closed")]
            return closed[0] if closed else exact[0]
    # Fail closed on ambiguous multi-day without date match.
    if len(same_side) == 1 and not day:
        return same_side[0]
    return None


def bind_decision_reasons(
    item: dict[str, Any],
    *,
    sealed_indexes: dict[str, dict[str, dict[str, Any]]] | None = None,
    control_trades: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Attach ``buy_decision`` / ``sell_decision`` (fail-closed when unknown)."""
    book_id = str(item.get("book_id") or "").strip().lower()
    model_id = str(item.get("model_id") or book_id).strip().lower()
    ticker = str(item.get("ticker") or "").strip()
    entry_at = item.get("entry_at") or item.get("opened_at") or item.get("entry_run_at")
    exit_at = item.get("exit_at") or item.get("sold_at") or item.get("exit_run_at")

    buy = _decision(side="buy", code=None, source="unjoinable", join_ok=False)
    sell = _decision(side="sell", code=None, source="unjoinable", join_ok=False)

    # 1) Chip / item already carries structured fields (preferred).
    chip_exit = item.get("exit_reason") or item.get("sell_reason_code")
    chip_entry = item.get("entry_reason") or item.get("buy_reason_code")
    chip_detail = item.get("entry_detail") if isinstance(item.get("entry_detail"), dict) else None

    if chip_exit:
        code = _normalize_exit_code(chip_exit)
        sell = _decision(
            side="sell",
            code=code,
            source="episode.exit_reason",
            join_ok=True,
            structured={"raw": chip_exit},
        )
    if chip_entry or chip_detail:
        code, structured = _entry_code_from_detail(chip_detail, model_id=model_id)
        if chip_entry and not code:
            code = _normalize_exit_code(chip_entry)
            structured = dict(chip_detail or {})
        if code:
            buy = _decision(
                side="buy",
                code=code,
                source="episode.entry_reason" if chip_entry else "episode.entry_detail",
                join_ok=True,
                structured=structured,
                label=_entry_label_from_structured(code, structured),
            )

    # 2) Sealed observe store join (lifecycle + sample).
    if book_id not in CONTROL_BOOK_IDS and sealed_indexes is not None:
        index = sealed_indexes.get(model_id) or sealed_indexes.get(book_id) or {}
        ep = index.get(_episode_key(ticker, entry_at, exit_at))
        if isinstance(ep, dict):
            if not sell.get("join_ok") and ep.get("exit_reason"):
                code = _normalize_exit_code(ep.get("exit_reason"))
                sell = _decision(
                    side="sell",
                    code=code,
                    source="observe.exit_reason",
                    join_ok=True,
                    structured={"raw": ep.get("exit_reason")},
                )
            if not buy.get("join_ok"):
                detail = ep.get("entry_detail") if isinstance(ep.get("entry_detail"), dict) else None
                entry_reason = ep.get("entry_reason")
                code, structured = _entry_code_from_detail(detail, model_id=model_id)
                if entry_reason and not code:
                    code = _normalize_exit_code(entry_reason)
                if code:
                    buy = _decision(
                        side="buy",
                        code=code,
                        source="observe.entry",
                        join_ok=True,
                        structured=structured or {"raw": entry_reason},
                        label=_entry_label_from_structured(code, structured),
                    )

    # 3) Deterministic model identities — bind only when the rule has one code.
    # N200: entry + exit are both single-rule. N201/N206/N210: entry only
    # (exit is 63d-or-identity-break — require episode.exit_reason; never guess).
    if model_id in N200_MODEL_IDS or book_id in N200_MODEL_IDS:
        if not sell.get("join_ok"):
            sell = _decision(
                side="sell",
                code="leave_buy_tier",
                source="model_identity.n200",
                join_ok=True,
                structured={"rule": "first_leave_buy_tier"},
            )
        if not buy.get("join_ok"):
            buy = _decision(
                side="buy",
                code="enter_buy_tier",
                source="model_identity.n200",
                join_ok=True,
                structured={"rule": "newly_enters_buy_tier"},
            )
    entry_identity = SEALED_FILTER_ENTRY_MODELS.get(model_id) or SEALED_FILTER_ENTRY_MODELS.get(
        book_id
    )
    if entry_identity and not buy.get("join_ok"):
        buy = _decision(
            side="buy",
            code=entry_identity,
            source=f"model_identity.{model_id or book_id}",
            join_ok=True,
            structured={"rule": "progressive_filters_newly_clear"},
        )

    # 4) FTSE control — rebalance_log trade notes (fail-closed if no unique match).
    if book_id in CONTROL_BOOK_IDS and control_trades is not None:
        trades = control_trades.get(str(ticker).upper()) or []
        if not sell.get("join_ok"):
            matched = _match_control_trade(trades, side="sell", at=str(exit_at) if exit_at else None)
            if matched and matched.get("note"):
                code = _normalize_exit_code(matched.get("note"))
                sell = _decision(
                    side="sell",
                    code=code or "left_target_set",
                    source="rebalance_log.trade_note",
                    join_ok=True,
                    structured={"note": matched.get("note"), "acted_at": matched.get("acted_at")},
                    label=reason_label(code or "left_target_set"),
                )
        if not buy.get("join_ok"):
            matched = _match_control_trade(trades, side="buy", at=str(entry_at) if entry_at else None)
            if matched and matched.get("note"):
                note = str(matched.get("note") or "")
                # Control buys are "Automated buy" / similar — map to enter_target_set.
                code = "enter_target_set"
                buy = _decision(
                    side="buy",
                    code=code,
                    source="rebalance_log.trade_note",
                    join_ok=True,
                    structured={"note": note, "acted_at": matched.get("acted_at")},
                )

    item["buy_decision"] = buy
    item["sell_decision"] = sell
    item["buy_reason"] = buy.get("label")
    item["sell_reason"] = sell.get("label")
    item["decision_reasons_join_ok"] = bool(buy.get("join_ok") and sell.get("join_ok"))
    return item


def attach_decision_reasons(
    item: dict[str, Any],
    *,
    data_dir: Path | None = None,
    sealed_indexes: dict[str, dict[str, dict[str, Any]]] | None = None,
    control_trades: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper that loads indexes once when not provided."""
    indexes = sealed_indexes
    trades = control_trades
    if indexes is None or trades is None:
        root = Path(data_dir) if data_dir is not None else Path("docs/data")
        if indexes is None:
            indexes = load_sealed_episode_indexes(root)
        if trades is None:
            trades = load_control_trade_index(root)
    return bind_decision_reasons(item, sealed_indexes=indexes, control_trades=trades)


def format_decision_reasons_for_prompt(item: dict[str, Any] | None) -> dict[str, Any]:
    """Compact block for LLM / deterministic reply context."""
    snap = item if isinstance(item, dict) else {}
    buy = snap.get("buy_decision") if isinstance(snap.get("buy_decision"), dict) else {}
    sell = snap.get("sell_decision") if isinstance(snap.get("sell_decision"), dict) else {}
    return {
        "buy": {
            "code": buy.get("code") or UNKNOWN_CODE,
            "label": buy.get("label") or UNKNOWN_LABEL,
            "source": buy.get("source"),
            "join_ok": bool(buy.get("join_ok")),
            "structured": buy.get("structured") or {},
        },
        "sell": {
            "code": sell.get("code") or UNKNOWN_CODE,
            "label": sell.get("label") or UNKNOWN_LABEL,
            "source": sell.get("source"),
            "join_ok": bool(sell.get("join_ok")),
            "structured": sell.get("structured") or {},
        },
    }


__all__ = [
    "CONTROL_REBALANCE_REL",
    "REASON_LABELS",
    "UNKNOWN_CODE",
    "UNKNOWN_LABEL",
    "attach_decision_reasons",
    "bind_decision_reasons",
    "format_decision_reasons_for_prompt",
    "load_control_trade_index",
    "load_sealed_episode_indexes",
    "reason_label",
]
