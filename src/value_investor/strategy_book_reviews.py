"""Review layer for closed strategy-book episodes (plan step 2.4).

Learning question: for every closed strategy-book episode, what happened
(entry, path, exit reason versus the registered rule), was the outcome
attributable to entry timing, the exit rule, a thesis break, a gate miss or
market drift, and which of the five cue-consumer levers would have helped?

Observe-only. ``influences_live`` is false. Reads the forward observe store
and the gate log. Does not walk, write a book, or call a model. Reviews and
lever scores are evidence for the version review at the thickness gate.

The sealed post-sale queue is built from Lifecycle paper books and the FTSE
control, with its own attention window. Strategy-book closes, including
comparison, shadow, control and bench columns, live in a sibling store so
they do not crowd that queue. Primary closes are the attention list here.
Other columns are queued beside them.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.cue_consumer_mft import (
    METRIC_SPEC_ID,
    MOM_LEVERS,
    SAME_DAY_POLICY,
    assess_same_day_round_trip,
    authorize_judgment_live_influence,
    fill_judgment_in_the_round,
)
from value_investor.post_sale_review import episode_key, review_fingerprint
from value_investor.post_sale_review_labels import (
    is_actioned,
    load_post_sale_review_labels,
)
from value_investor.storage import read_json, write_json
from value_investor.strategy_book_exit_lab import (
    EXIT_CHANNEL_LOW,
    EXIT_NEW_LOW,
    EXIT_TRAIL,
    EXIT_TREND,
)
from value_investor.strategy_book_rules import (
    BENCH_COLUMNS,
    COLUMN_ALTERNATIVE,
    COLUMN_BUY_ON_SIGNAL,
    COLUMN_DECLINE_SHADOW,
    COLUMN_DRAFT,
    COLUMN_LADDER,
    COLUMN_LEAVE_TIER,
    COLUMN_PRIMARY,
    COLUMN_SECTOR_SHADOW,
    EXIT_FAIL_TO_LAUNCH,
    EXIT_FLOOR,
    EXIT_HOLD_63,
    EXIT_INELIGIBLE_RUNS,
    EXIT_RECOVERY_TARGET,
    EXIT_REVIEW_CAP,
    EXIT_REVIEW_INSUFFICIENT,
    EXIT_SWING_HIGH,
    EXIT_THESIS,
    EXIT_TIME_CAP,
    FAIL_TO_LAUNCH_INDEX,
    LOW_WINDOW_SESSIONS,
    REGISTRATION_ID,
)

SCHEMA_VERSION = 1
SOURCE = "strategy_book"
BOOK_TAG = "Strategy book"
LABELS_FILENAME = "strategy_book_review_labels.json"
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_STORE_NAME = "strategy_book_review_queue.json"
DEFAULT_OBSERVE_NAME = "strategy_book_observe.json"
DEFAULT_GATE_LOG_NAME = "strategy_book_gate_log.jsonl"
OPS_DOC = "docs/ops/strategy-book-reviews.md"
CATEGORY = "research"
FINDING_TITLE = "Strategy book reviews queued"
MISSING_TITLE = "Strategy book closes missing review"
STORE_FAILED_TITLE = "Strategy book reviews failed"

# A close with no queue row is a warn once it is older than this many calendar
# days. The daily refresh queues every close it can, so the warn means a close
# could not be given a stable episode id.
REVIEW_LAG_DAYS = 2
# Fair-cost returns on the observe store are fractions. Two percentage points
# is the band for "this difference is large enough to name a lever".
MATERIAL_RETURN = 0.02
PIT_GATE_CAP = 8
EXIT_DELISTED = "delisted"

LEARNING_QUESTION = (
    "For every closed strategy-book episode: what happened (entry, path, "
    "exit reason versus the registered rule), was the outcome attributable "
    "to entry timing, the exit rule, a thesis break, a gate miss or market "
    "drift, and which of the five levers would have helped?"
)

_LEVER_BY_ID = {str(row["id"]): row for row in MOM_LEVERS}
_COMPARISON_COLUMNS = frozenset(
    {COLUMN_DRAFT, COLUMN_LADDER, COLUMN_LEAVE_TIER, COLUMN_ALTERNATIVE}
)
_SHADOW_COLUMNS = frozenset({COLUMN_DECLINE_SHADOW, COLUMN_SECTOR_SHADOW})
_LADDER_FAMILY = frozenset(
    {
        EXIT_FLOOR,
        EXIT_FAIL_TO_LAUNCH,
        EXIT_TIME_CAP,
        EXIT_THESIS,
        EXIT_REVIEW_INSUFFICIENT,
        EXIT_REVIEW_CAP,
        EXIT_DELISTED,
    }
)
_DRAFT_FAMILY = frozenset(
    {
        EXIT_SWING_HIGH,
        EXIT_RECOVERY_TARGET,
        EXIT_THESIS,
        EXIT_REVIEW_INSUFFICIENT,
        EXIT_REVIEW_CAP,
        EXIT_DELISTED,
    }
)
_NO_DEADLINE_FAMILY = frozenset(
    {
        EXIT_FLOOR,
        EXIT_TIME_CAP,
        EXIT_THESIS,
        EXIT_REVIEW_INSUFFICIENT,
        EXIT_REVIEW_CAP,
        EXIT_DELISTED,
    }
)
_CONTROL_FAMILY = frozenset({EXIT_HOLD_63, EXIT_INELIGIBLE_RUNS, EXIT_DELISTED})
_LEAVE_FAMILY = frozenset({EXIT_INELIGIBLE_RUNS, EXIT_DELISTED})
_LAB_FAMILY = frozenset(
    {
        EXIT_THESIS,
        EXIT_FLOOR,
        EXIT_TRAIL,
        EXIT_TREND,
        EXIT_CHANNEL_LOW,
        EXIT_NEW_LOW,
        EXIT_FAIL_TO_LAUNCH,
        EXIT_REVIEW_INSUFFICIENT,
        EXIT_REVIEW_CAP,
        EXIT_DELISTED,
    }
)
_PRICE_OR_TIME_EXITS = frozenset(
    {
        EXIT_FLOOR,
        EXIT_FAIL_TO_LAUNCH,
        EXIT_TIME_CAP,
        EXIT_HOLD_63,
        EXIT_SWING_HIGH,
        EXIT_RECOVERY_TARGET,
        EXIT_TRAIL,
        EXIT_TREND,
        EXIT_CHANNEL_LOW,
        EXIT_NEW_LOW,
    }
)
_ATTRIBUTION_LABELS = frozenset(
    {
        "entry_timing",
        "exit_rule",
        "thesis_break",
        "gate_miss",
        "market_drift",
        "insufficient_data",
    }
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _day(value: Any) -> date | None:
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _pct(value: float | None) -> float | None:
    """Strategy-book returns are fractions. 0.12 is 12 percent."""
    if value is None:
        return None
    return round(value * 100.0, 2)


def _is_closed(episode: dict[str, Any]) -> bool:
    status = str(episode.get("status") or "").strip().lower()
    exit_session = str(episode.get("exit_session") or "").strip()
    return status == "closed" or bool(exit_session)


def column_role(column: str) -> str:
    """primary, comparison, control, shadow, bench, or other.

    Bench challengers on the forward book are flags on the primary episode,
    not their own closes. A column id that is a bench name, or a ``lab_``
    exit from the rehearsal, is still tagged bench so it cannot sit in the
    primary attention list.
    """
    name = str(column or "").strip()
    if name == COLUMN_PRIMARY:
        return "primary"
    if name in _COMPARISON_COLUMNS:
        return "comparison"
    if name == COLUMN_BUY_ON_SIGNAL:
        return "control"
    if name in _SHADOW_COLUMNS:
        return "shadow"
    if name in BENCH_COLUMNS or name.startswith("lab_"):
        return "bench"
    return "other"


def registered_exit_family(column: str) -> frozenset[str]:
    """Exit reasons the registration (or the exit lab) names for this column."""
    name = str(column or "").strip()
    if name == COLUMN_DRAFT:
        return _DRAFT_FAMILY
    if name == COLUMN_LADDER:
        return _NO_DEADLINE_FAMILY
    if name == COLUMN_BUY_ON_SIGNAL:
        return _CONTROL_FAMILY
    if name == COLUMN_LEAVE_TIER:
        return _LEAVE_FAMILY
    if name.startswith("lab_"):
        return _LAB_FAMILY
    if name in {
        COLUMN_PRIMARY,
        COLUMN_ALTERNATIVE,
        COLUMN_DECLINE_SHADOW,
        COLUMN_SECTOR_SHADOW,
        *BENCH_COLUMNS,
    }:
        return _LADDER_FAMILY
    return frozenset()


def _lever_shell(lever_id: str) -> dict[str, Any]:
    source = _LEVER_BY_ID.get(lever_id) or {"id": lever_id, "definition": "", "not": ""}
    return {
        "id": source.get("id") or lever_id,
        "definition": source.get("definition") or "",
        "not": source.get("not") or "",
        "metric_spec_id": METRIC_SPEC_ID,
        "would_have_helped": "insufficient_data",
        "status": "insufficient_data",
        "value": None,
        "unit": "fair_cost_episode_pct",
        "cites": [],
        "hindsight": [],
        "because": "",
    }


def _split_dated(
    rows: list[Any],
    exit_day: date | None,
    *,
    date_key: str = "session",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep dict rows dated on or before the exit. Undated and later are withheld."""
    kept: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = _day(row.get(date_key))
        if day is None:
            withheld.append({**row, "withheld": "undated"})
        elif exit_day is None or day > exit_day:
            withheld.append({**row, "withheld": "after_exit"})
        else:
            kept.append(row)
    return kept, withheld


def _cited_inputs(episode: dict[str, Any], exit_day: date | None) -> tuple[list[Any], list[Any]]:
    raw = episode.get("inputs")
    used: list[Any] = []
    withheld: list[Any] = []
    if isinstance(raw, list):
        used.extend(item for item in raw if isinstance(item, dict))
        return used, withheld
    if not isinstance(raw, dict):
        return used, withheld
    entry = raw.get("entry")
    if isinstance(entry, list):
        used.extend(item for item in entry if isinstance(item, dict))
    elif isinstance(entry, dict):
        used.append(entry)
    reviews = raw.get("reviews")
    if isinstance(reviews, list):
        kept, later = _split_dated(reviews, exit_day)
        used.extend(kept)
        withheld.extend(later)
    return used, withheld


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def _load_gate_log(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _gate_day(row: dict[str, Any]) -> date | None:
    return _day(row.get("session") or row.get("as_of"))


def _pit_gate_rows(
    rows: list[dict[str, Any]],
    *,
    market: str,
    ticker: str,
    exit_day: date | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("market") or "") != market or str(row.get("ticker") or "") != ticker:
            continue
        day = _gate_day(row)
        brief = {
            "kind": row.get("kind"),
            "as_of": str(row.get("session") or row.get("as_of") or "")[:10],
            "column": row.get("column"),
            "decline": row.get("decline"),
            "sector": row.get("sector"),
            "signal": row.get("signal"),
            "f9": row.get("f9"),
            "memo_verdict": row.get("memo_verdict"),
            "exit_reason": row.get("exit_reason"),
        }
        if day is None:
            withheld.append({**brief, "withheld": "undated"})
        elif exit_day is None or day > exit_day:
            withheld.append({**brief, "withheld": "after_exit"})
        else:
            kept.append(brief)
    kept.sort(key=lambda item: str(item.get("as_of") or ""))
    total = len(kept)
    return kept[-PIT_GATE_CAP:], withheld, total


def _same_name(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return str(left.get("market") or "") == str(right.get("market") or "") and str(
        left.get("ticker") or ""
    ) == str(right.get("ticker") or "")


def _same_entry(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _same_name(left, right) and str(left.get("signal_session") or "") == str(
        right.get("signal_session") or ""
    )


def _closed_by(
    episode: dict[str, Any],
    others: list[dict[str, Any]],
    *,
    exit_day: date | None,
    paired: bool,
    column: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Closed siblings whose exit is on or before ``exit_day``. Later closes are named, not used."""
    usable: list[dict[str, Any]] = []
    hindsight: list[str] = []
    own = str(episode.get("episode_id") or "")
    for other in others:
        if other is episode:
            continue
        eid = str(other.get("episode_id") or "")
        if own and eid == own:
            continue
        if column is not None and str(other.get("column") or "") != column:
            continue
        match = _same_entry(episode, other) if paired else _same_name(episode, other)
        if not match:
            continue
        if not _is_closed(other):
            if eid:
                hindsight.append(eid)
            continue
        oday = _day(other.get("exit_session"))
        if oday is None or exit_day is None or oday > exit_day:
            if eid:
                hindsight.append(eid)
            continue
        if _finite(other.get("fair_cost_return")) is None:
            continue
        usable.append(other)
    return usable, hindsight


def _session_gap(left: date, right: date) -> int:
    """Weekday steps from ``left`` to ``right``.

    Section 3's entry window is ``LOW_WINDOW_SESSIONS`` chart sessions. The
    review store has no per-name price calendar, so a session is a weekday.
    """
    if left == right:
        return 0
    step = 1 if right > left else -1
    cursor = left
    gap = 0
    while cursor != right:
        cursor += timedelta(days=step)
        if cursor.weekday() < 5:
            gap += 1
    return gap


def _nearest_fill(
    episode: dict[str, Any],
    pool: list[dict[str, Any]],
    *,
    window: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    """One counterfactual: nearest fill inside the entry window.

    A tie takes the earlier fill, then the episode id. Fills outside the
    window are returned as ids and are not a score.
    """
    own = _day(episode.get("fill_session"))
    outside: list[str] = []
    ranked: list[tuple[int, date, str, dict[str, Any]]] = []
    for row in pool:
        eid = str(row.get("episode_id") or "")
        fill = _day(row.get("fill_session"))
        if own is None or fill is None:
            if eid:
                outside.append(eid)
            continue
        gap = _session_gap(own, fill)
        if gap > window:
            if eid:
                outside.append(eid)
            continue
        ranked.append((gap, fill, eid, row))
    if not ranked:
        return None, outside
    ranked.sort(key=lambda item: (item[0], item[1].isoformat(), item[2]))
    return ranked[0][3], outside


def _beats(challenger: float, incumbent: float) -> bool:
    return challenger > incumbent + MATERIAL_RETURN


def _attribution(
    episode: dict[str, Any],
    *,
    role: str,
    family: frozenset[str],
    fair: float | None,
    excess: float | None,
) -> dict[str, Any]:
    exit_reason = str(episode.get("exit_reason") or "").strip()
    cites = [f"column={episode.get('column')}", f"column_role={role}"]
    if exit_reason:
        cites.append(f"exit_reason={exit_reason}")
    if fair is not None:
        cites.append(f"fair_cost_return={fair}")
    if excess is not None:
        cites.append(f"matched_excess={excess}")
    label = "insufficient_data"
    because = "exit_reason_or_return_missing"
    if not exit_reason or fair is None:
        label = "insufficient_data"
        because = "exit_reason_or_return_missing"
    elif role == "shadow":
        label = "gate_miss"
        because = "gate_rejected_shadow_column"
    elif exit_reason == EXIT_THESIS:
        label = "thesis_break"
        because = "registered_thesis_break"
    elif (
        role == "primary"
        and bool(episode.get("recovery_label"))
        and not bool(episode.get("launched"))
        and exit_reason == EXIT_FAIL_TO_LAUNCH
    ):
        label = "entry_timing"
        because = "recovery_label_before_launch_then_fail_to_launch"
        cites.append("recovery_label=true")
        cites.append("launched=false")
    elif (
        excess is not None
        and abs(excess) <= MATERIAL_RETURN
        and abs(fair) > MATERIAL_RETURN
        and exit_reason in _PRICE_OR_TIME_EXITS
    ):
        label = "market_drift"
        because = "matched_excess_inside_band_while_episode_return_is_outside_it"
    elif exit_reason in family:
        label = "exit_rule"
        because = "registered_exit_family_fired"
    else:
        label = "insufficient_data"
        because = "exit_reason_not_in_registered_family"
    if label not in _ATTRIBUTION_LABELS:
        label = "insufficient_data"
    return {
        "label": label,
        "because": because,
        "cites": cites,
        "counts_as_evidence": True,
    }


def _apply_provenance_block(
    attribution: dict[str, Any], levers: list[dict[str, Any]]
) -> dict[str, Any]:
    """A provenance miss is queued and described, and it is not evidence."""
    blocked = dict(attribution)
    blocked["provisional_label"] = blocked.get("label")
    blocked["label"] = "insufficient_data"
    blocked["because"] = "provenance_missing"
    blocked["counts_as_evidence"] = False
    for lever in levers:
        lever["would_have_helped"] = "insufficient_data"
        lever["status"] = "insufficient_data"
        lever["value"] = None
        lever["because"] = "provenance_missing"
        lever["hindsight"] = []
    return blocked


def _score_stock_choice(
    episode: dict[str, Any], *, role: str, fair: float | None
) -> dict[str, Any]:
    lever = _lever_shell("stock_choice")
    if fair is None:
        lever["because"] = "fair_cost_return_missing"
        return lever
    lever["cites"] = [f"fair_cost_return={fair}"]
    if role != "shadow":
        lever["because"] = "no_skipped_cue_counterfactual_on_this_row"
        return lever
    lever["value"] = _pct(fair)
    lever["status"] = "scored"
    if fair < -MATERIAL_RETURN:
        lever["would_have_helped"] = "yes"
        lever["because"] = "shadow_loss_so_the_skip_would_have_helped"
    elif fair > MATERIAL_RETURN:
        lever["would_have_helped"] = "no"
        lever["because"] = "shadow_gain_so_the_skip_would_not_have_helped"
    else:
        lever["would_have_helped"] = "no"
        lever["because"] = "shadow_return_inside_band"
    return lever


def _score_buy_timing(
    episode: dict[str, Any],
    others: list[dict[str, Any]],
    *,
    role: str,
    fair: float | None,
    exit_day: date | None,
) -> dict[str, Any]:
    lever = _lever_shell("buy_timing")
    if fair is None:
        lever["because"] = "fair_cost_return_missing"
        return lever
    if role == "control":
        pool, hindsight = _closed_by(
            episode,
            others,
            exit_day=exit_day,
            paired=False,
            column=COLUMN_PRIMARY,
        )
    else:
        pool, hindsight = _closed_by(
            episode,
            others,
            exit_day=exit_day,
            paired=False,
            column=COLUMN_BUY_ON_SIGNAL,
        )
    lever["hindsight"] = hindsight
    # Section 3: only a fill inside the 10-session entry window is a timing
    # counterfactual. Nearest fill wins; a tie takes the earlier entry.
    chosen, outside = _nearest_fill(episode, pool, window=LOW_WINDOW_SESSIONS)
    lever["outside_window"] = outside
    lever["entry_window_sessions"] = LOW_WINDOW_SESSIONS
    if chosen is None:
        lever["because"] = (
            "no_overlapping_counterfactual_entry"
            if pool
            else "no_point_in_time_buy_on_signal_or_primary_close"
        )
        lever["cites"] = [
            f"fair_cost_return={fair}",
            f"entry_window_sessions={LOW_WINDOW_SESSIONS}",
        ]
        return lever
    other_fair = _finite(chosen.get("fair_cost_return"))
    assert other_fair is not None
    own_fill = _day(episode.get("fill_session"))
    other_fill = _day(chosen.get("fill_session"))
    gap = 0 if own_fill is None or other_fill is None else _session_gap(own_fill, other_fill)
    delta = other_fair - fair
    lever["value"] = _pct(delta)
    lever["status"] = "scored"
    lever["cites"] = [
        f"fair_cost_return={fair}",
        f"counterfactual_episode_id={chosen.get('episode_id')}",
        f"counterfactual_column={chosen.get('column')}",
        f"counterfactual_fill_session={chosen.get('fill_session')}",
        f"counterfactual_exit_session={chosen.get('exit_session')}",
        f"counterfactual_fair_cost_return={other_fair}",
        f"session_gap={gap}",
        f"delta_vs_counterfactual={delta}",
    ]
    # Positive delta: the nearest counterfactual returned more than this close.
    if _beats(other_fair, fair):
        lever["would_have_helped"] = "yes"
        lever["because"] = "nearest_entry_counterfactual_beat_this_close"
    else:
        lever["would_have_helped"] = "no"
        lever["because"] = "nearest_entry_counterfactual_did_not_beat_this_close"
    return lever


def _score_buy_strategy(episode: dict[str, Any]) -> dict[str, Any]:
    lever = _lever_shell("buy_strategy")
    stake = _finite(episode.get("stake"))
    cites = ["sizing=fixed_stake_single_shot"]
    if stake is not None:
        cites.append(f"stake={stake}")
    lever["cites"] = cites
    lever["because"] = "no_scale_in_counterfactual_on_the_episode"
    return lever


def _score_sell(
    episode: dict[str, Any],
    others: list[dict[str, Any]],
    *,
    fair: float | None,
    exit_day: date | None,
    family: frozenset[str],
    same_day: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    timing = _lever_shell("sell_timing")
    strategy = _lever_shell("sell_strategy")
    exit_reason = str(episode.get("exit_reason") or "").strip()
    if fair is None or not exit_reason:
        timing["because"] = "fair_cost_return_or_exit_reason_missing"
        strategy["because"] = "fair_cost_return_or_exit_reason_missing"
        return timing, strategy
    pool, hindsight = _closed_by(episode, others, exit_day=exit_day, paired=True)
    same = bool(same_day.get("same_day_round_trip"))
    weakness = str(same_day.get("same_day_assessment") or "") == "likely_weakness"
    reverse = str(same_day.get("same_day_assessment") or "") == "major_error_reverse"
    timing["hindsight"] = list(hindsight)
    strategy["hindsight"] = list(hindsight)
    timing["cites"] = [
        f"exit_reason={exit_reason}",
        f"fair_cost_return={fair}",
        f"same_day_assessment={same_day.get('same_day_assessment')}",
    ]
    strategy["cites"] = [
        f"exit_reason={exit_reason}",
        f"registered_family_hit={exit_reason in family}",
        f"same_day_assessment={same_day.get('same_day_assessment')}",
    ]
    ordered = sorted(
        pool,
        key=lambda row: (str(row.get("column") or ""), str(row.get("episode_id") or "")),
    )
    deltas: list[float] = []
    for row in ordered:
        other_fair = _finite(row.get("fair_cost_return"))
        if other_fair is None:
            continue
        delta = other_fair - fair
        deltas.append(delta)
        cite = (
            f"alternative={row.get('episode_id')}:column={row.get('column')}:"
            f"exit_reason={row.get('exit_reason')}:delta={delta}"
        )
        timing["cites"].append(cite)
        strategy["cites"].append(cite)
    if deltas:
        median_delta = float(statistics.median(deltas))
        beating = sum(1 for delta in deltas if delta > MATERIAL_RETURN)
        for lever in (timing, strategy):
            lever["alternatives_n"] = len(deltas)
            lever["alternatives_beating_n"] = beating
            lever["median_delta"] = median_delta
            lever["value"] = _pct(median_delta)
            lever["status"] = "scored"
            lever["cites"].append(f"alternatives_n={len(deltas)}")
            lever["cites"].append(f"alternatives_beating_n={beating}")
            lever["cites"].append(f"median_delta={median_delta}")
        # Yes only when the median alternative beats this close. One strong
        # paired exit does not carry the label.
        if median_delta > MATERIAL_RETURN:
            timing["would_have_helped"] = "yes"
            timing["because"] = "median_paired_delta_beats_this_close"
            strategy["would_have_helped"] = "yes"
            strategy["because"] = "median_paired_delta_beats_this_close"
        else:
            timing["would_have_helped"] = "no"
            timing["because"] = "median_paired_delta_does_not_beat_this_close"
            strategy["would_have_helped"] = "no"
            strategy["because"] = "median_paired_delta_does_not_beat_this_close"
    else:
        timing["because"] = "no_paired_close_on_or_before_this_exit"
        if exit_reason in family:
            strategy["status"] = "rule_fired"
            strategy["because"] = "registered_family_fired_without_a_paired_counterfactual"
        else:
            strategy["because"] = "exit_reason_not_in_registered_family"
    if same and weakness:
        timing["would_have_helped"] = "yes"
        timing["status"] = "scored"
        timing["because"] = "same_calendar_day_exit_without_major_error_reverse"
        strategy["would_have_helped"] = "yes"
        strategy["status"] = "scored"
        strategy["because"] = "same_day_policy_scores_sell_strategy"
        timing["cites"].append("same_day_policy=soft_bias")
        strategy["cites"].append("same_day_policy=sell_strategy")
    elif same and reverse:
        timing["status"] = "scored"
        timing["would_have_helped"] = "no"
        timing["because"] = "major_error_reverse_with_durable_cites"
        strategy["status"] = "scored"
        strategy["would_have_helped"] = "no"
        strategy["because"] = "major_error_reverse_is_the_registered_same_day_exception"
    return timing, strategy


def _same_day_bundle(episode: dict[str, Any], pit_log: list[dict[str, Any]]) -> dict[str, Any]:
    exit_reason = str(episode.get("exit_reason") or "").strip()
    cites: list[str] = []
    for row in pit_log:
        reasons = row.get("reasons")
        if row.get("action") == EXIT_THESIS and isinstance(reasons, list) and reasons:
            text = ",".join(str(item) for item in reasons if str(item).strip())
            if text:
                cites.append(f"decision_log.reasons={text}")
    assessment = assess_same_day_round_trip(
        entry_at=episode.get("fill_session"),
        exit_at=episode.get("exit_session"),
        hold_days=episode.get("held_calendar_days"),
        major_error_reverse=exit_reason == EXIT_THESIS and bool(cites),
        evidence_cites=cites,
    )
    return {
        **assessment,
        "same_calendar_day": bool(assessment.get("same_day_round_trip")),
        "soft_bias": bool(assessment.get("soft_penalty")),
        "hard_ban": bool(assessment.get("hard_ban")),
        "major_error_reverse": assessment.get("same_day_assessment") == "major_error_reverse",
        "exception": (
            "major_error_reverse"
            if assessment.get("same_day_assessment") == "major_error_reverse"
            else None
        ),
    }


def _judgment_row(episode: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Fields the cue-consumer filler knows how to cite. Entry snapshot only."""
    row: dict[str, Any] = {}
    for key in (
        "passed_families",
        "models_passed",
        "weighted_model_score",
        "research_verdict",
        "fcf_basis_overlay",
        "earnings_basis_overlay",
        "data_quality_score",
        "timing_signal",
        "timing_score",
        "price_vs_sma200_pct",
        "volume_ratio_20",
        "signal_trend",
        "sector",
        "weeks_at_signal",
        "conviction_score",
        "research_confidence",
        "signal",
        "adjusted_signal",
        "trade_plan_summary",
        "tactical_stop_loss",
        "tactical_take_profit",
    ):
        if key in snapshot and snapshot.get(key) is not None:
            row[key] = snapshot.get(key)
    if episode.get("market") and "market" not in row:
        row["market"] = episode.get("market")
    if episode.get("adjusted_signal") and "adjusted_signal" not in row:
        row["adjusted_signal"] = episode.get("adjusted_signal")
    # Memo fields on the closed episode are the walker's record at exit.
    if episode.get("memo_verdict") and "research_verdict" not in row:
        row["research_verdict"] = episode.get("memo_verdict")
    return row


def _build_judgment(
    episode: dict[str, Any],
    *,
    snapshot: dict[str, Any],
    fair: float | None,
    same_day: dict[str, Any],
    provenance_missing: bool,
) -> dict[str, Any]:
    held = episode.get("held_sessions")
    hold_days = int(held) if isinstance(held, int) else None
    column = str(episode.get("column") or "")
    exit_reason = str(episode.get("exit_reason") or "").strip() or None
    detail = {
        "cue_source_id": str(episode.get("registration_id") or REGISTRATION_ID),
        "timing_signal": snapshot.get("timing_signal"),
        "research_verdict": snapshot.get("research_verdict") or episode.get("memo_verdict"),
        "signal": snapshot.get("signal"),
        "adjusted_signal": snapshot.get("adjusted_signal") or episode.get("adjusted_signal"),
        "conviction_score": snapshot.get("conviction_score"),
    }
    judgment = fill_judgment_in_the_round(
        side="both",
        cue_source_id=str(detail["cue_source_id"]),
        clear_note=f"column={column}",
        entry_detail=detail,
        row=_judgment_row(episode, snapshot),
        exit_reason=exit_reason,
        hold_trading_days=hold_days,
        same_day_assessment=same_day,
        return_pct=_pct(fair),
        hold_policy_days=int(FAIL_TO_LAUNCH_INDEX),
    )
    judgment["influences_live"] = False
    judgment["observe_only"] = True
    judgment["point_in_time"] = "exit_session"
    judgment["counts_as_evidence"] = not provenance_missing
    if provenance_missing:
        judgment["evidence_status"] = "insufficient_data"
        judgment["note"] = (
            "provenance_missing: trail is descriptive only and is not evidence. "
            + str(judgment.get("note") or "")
        )
    else:
        judgment["evidence_status"] = (
            "scored" if judgment.get("cells_cited") else "insufficient_data"
        )
    if authorize_judgment_live_influence(judgment):
        judgment["influences_live"] = False
        judgment["observe_only"] = True
        judgment["evidence_status"] = "insufficient_data"
        judgment["counts_as_evidence"] = False
    return judgment


def _review_row(
    episode: dict[str, Any],
    *,
    others: list[dict[str, Any]],
    gate_rows: list[dict[str, Any]],
    registration_id: str,
    actioned: bool,
) -> dict[str, Any]:
    column = str(episode.get("column") or "")
    role = column_role(column)
    family = registered_exit_family(column)
    exit_day = _day(episode.get("exit_session"))
    fair = _finite(episode.get("fair_cost_return"))
    excess = _finite(episode.get("matched_excess"))
    provenance_missing = bool(episode.get("provenance_missing"))
    snapshot = episode.get("snapshot") if isinstance(episode.get("snapshot"), dict) else {}
    decision_log = (
        episode.get("decision_log") if isinstance(episode.get("decision_log"), list) else []
    )
    reviews = episode.get("reviews") if isinstance(episode.get("reviews"), list) else []
    floor_history = (
        episode.get("floor_history") if isinstance(episode.get("floor_history"), list) else []
    )
    pit_log, late_log = _split_dated(decision_log, exit_day)
    pit_reviews, late_reviews = _split_dated(reviews, exit_day)
    pit_floor, late_floor = _split_dated(floor_history, exit_day)
    cited_inputs, late_inputs = _cited_inputs(episode, exit_day)
    pit_gate, late_gate, pit_gate_count = _pit_gate_rows(
        gate_rows,
        market=str(episode.get("market") or ""),
        ticker=str(episode.get("ticker") or ""),
        exit_day=exit_day,
    )
    same_day = _same_day_bundle(episode, pit_log)
    attribution = _attribution(episode, role=role, family=family, fair=fair, excess=excess)
    levers = [
        _score_stock_choice(episode, role=role, fair=fair),
        _score_buy_timing(episode, others, role=role, fair=fair, exit_day=exit_day),
        _score_buy_strategy(episode),
        *_score_sell(
            episode,
            others,
            fair=fair,
            exit_day=exit_day,
            family=family,
            same_day=same_day,
        ),
    ]
    if provenance_missing:
        attribution = _apply_provenance_block(attribution, levers)
    judgment = _build_judgment(
        episode,
        snapshot=snapshot,
        fair=fair,
        same_day=same_day,
        provenance_missing=provenance_missing,
    )
    episode_id = str(episode.get("episode_id") or "").strip()
    ticker = str(episode.get("ticker") or "")
    fill_session = str(episode.get("fill_session") or "") or None
    exit_session = str(episode.get("exit_session") or "") or None
    fingerprint = review_fingerprint(
        book_id=f"{SOURCE}:{column}",
        ticker=ticker,
        entry_at=fill_session,
        exit_at=exit_session,
    )
    ep_key = episode_key(
        book_id=f"{SOURCE}:{column}",
        ticker=ticker,
        entry_at=fill_session,
        exit_at=exit_session,
    )
    evidence_status = (
        "insufficient_data"
        if provenance_missing or attribution.get("label") == "insufficient_data"
        else "scored"
    )
    hindsight = [
        *({"kind": "decision_log", **row} for row in late_log),
        *({"kind": "review", **row} for row in late_reviews),
        *({"kind": "floor_history", **row} for row in late_floor),
        *(
            {"kind": "inputs", **row} if isinstance(row, dict) else {"kind": "inputs"}
            for row in late_inputs
        ),
        *({"kind": "gate_log", **row} for row in late_gate),
    ]
    return {
        "review_id": episode_id,
        "episode_id": episode_id,
        "review_fingerprint": fingerprint,
        "episode_key": ep_key,
        "source": SOURCE,
        "book": SOURCE,
        "book_id": registration_id,
        "book_tag": BOOK_TAG,
        "column": column,
        "column_role": role,
        "attention": "primary" if role == "primary" else "companion",
        "market": episode.get("market"),
        "ticker": ticker,
        "currency": episode.get("currency"),
        "signal_session": episode.get("signal_session"),
        "fill_session": fill_session,
        "exit_session": exit_session,
        "exit_reason": episode.get("exit_reason"),
        "exit_fill": episode.get("exit_fill"),
        "fair_cost_return": fair,
        "fair_cost_return_pct": _pct(fair),
        "matched_excess": excess,
        "matched_excess_pct": _pct(excess),
        "recovery_label": bool(episode.get("recovery_label")),
        "launched": bool(episode.get("launched")),
        "memo_verdict": episode.get("memo_verdict"),
        "memo_rationale": episode.get("memo_rationale"),
        "snapshot": snapshot,
        "decision_log": pit_log,
        "reviews": pit_reviews,
        "floor_history": pit_floor,
        "cited_inputs": cited_inputs,
        "pit_gate_log": pit_gate,
        "pit_gate_log_count": pit_gate_count,
        "hindsight": hindsight,
        "same_day": same_day,
        "attribution": attribution,
        "levers": levers,
        "judgment_in_the_round": judgment,
        "provenance_missing": provenance_missing,
        "evidence_status": evidence_status,
        "actioned": actioned,
        "opinion_llm": False,
        "influences_live": False,
        "observe_only": True,
        "status": "closed",
    }


def _missing_row(episode: dict[str, Any], *, now: datetime, reason: str) -> dict[str, Any]:
    exit_day = _day(episode.get("exit_session"))
    age = None if exit_day is None else (now.date() - exit_day).days
    return {
        "episode_id": str(episode.get("episode_id") or ""),
        "column": episode.get("column"),
        "market": episode.get("market"),
        "ticker": episode.get("ticker"),
        "exit_session": episode.get("exit_session"),
        "exit_reason": episode.get("exit_reason"),
        "age_days": age,
        "reason": reason,
        "older_than_lag": age is None or age > REVIEW_LAG_DAYS,
    }


def _sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("exit_session") or ""),
        str(row.get("ticker") or ""),
        str(row.get("episode_id") or ""),
    )


def build_strategy_book_review_queue(
    observe: dict[str, Any] | None,
    *,
    gate_rows: list[dict[str, Any]] | None = None,
    labels: dict[str, Any] | None = None,
    now: datetime | None = None,
    observe_status: str = "ok",
) -> dict[str, Any]:
    """Build the sibling queue. Does not write."""
    moment = now or _utcnow()
    store = observe if isinstance(observe, dict) else {}
    registration_id = str(store.get("registration_id") or REGISTRATION_ID)
    episodes = [row for row in (store.get("episodes") or []) if isinstance(row, dict)]
    gates = gate_rows if gate_rows is not None else []
    label_store = labels if isinstance(labels, dict) else {}
    closed = [row for row in episodes if _is_closed(row)]
    open_skipped = len(episodes) - len(closed)
    seen: set[str] = set()
    unique_closed: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for episode in closed:
        episode_id = str(episode.get("episode_id") or "").strip()
        if not episode_id:
            missing.append(_missing_row(episode, now=moment, reason="blank_episode_id"))
            continue
        if episode_id in seen:
            continue
        seen.add(episode_id)
        unique_closed.append(episode)
    rows: list[dict[str, Any]] = []
    for episode in unique_closed:
        episode_id = str(episode.get("episode_id") or "").strip()
        rows.append(
            _review_row(
                episode,
                others=unique_closed,
                gate_rows=gates,
                registration_id=registration_id,
                actioned=is_actioned(label_store, episode_id),
            )
        )
    primary = [row for row in rows if row.get("attention") == "primary"]
    companion = [row for row in rows if row.get("attention") != "primary"]
    primary.sort(key=_sort_key, reverse=True)
    companion.sort(key=lambda row: (str(row.get("column") or ""), *_sort_key(row)))
    ordered = primary + companion
    active = [row for row in primary if not row.get("actioned")]
    stale_missing = [row for row in missing if row.get("older_than_lag")]
    provenance = sum(1 for row in ordered if row.get("provenance_missing"))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": moment.isoformat(),
        "source": SOURCE,
        "book": SOURCE,
        "book_id": registration_id,
        "book_tag": BOOK_TAG,
        "registration_id": registration_id,
        "metric_spec_id": METRIC_SPEC_ID,
        "same_day_policy": SAME_DAY_POLICY,
        "learning_question": LEARNING_QUESTION,
        "observe_status": observe_status,
        "scoring_date": store.get("scoring_date"),
        "influences_live": False,
        "observe_only": True,
        "opinion_llm": False,
        "opinion_note": (
            "The post-sale opinion model is opt-in (FTSE_POST_SALE_LLM_REPLY) "
            "and is not called for strategy-book rows. This refresh does not "
            "attach an opinion or write a factory reply."
        ),
        "auto_fixable": False,
        "mid_run_tunes": False,
        "version_review_only": True,
        "review_lag_days": REVIEW_LAG_DAYS,
        "material_return": MATERIAL_RETURN,
        "hold_policy_sessions": FAIL_TO_LAUNCH_INDEX,
        "ops_doc": OPS_DOC,
        "labels_filename": LABELS_FILENAME,
        "queue_policy": {
            "primary": (
                "First-class attention list. Bench flags on a primary episode "
                "stay on that row; they are not extra cards."
            ),
            "companion": (
                "Comparison exits, the buy-on-signal control, gate-rejected "
                "shadows, bench columns and lab columns are queued with a "
                "column tag and are not in the primary attention list."
            ),
            "point_in_time": (
                "Cites use the episode and gate-log rows dated on or before "
                "the exit. Later rows are listed under hindsight and are not scores."
            ),
            "fail_closed": "Missing data is insufficient_data. A provenance miss is not evidence.",
        },
        "counts": {
            "episodes": len(episodes),
            "closed": len(ordered),
            "primary": len(primary),
            "companion": len(companion),
            "active": len(active),
            "open_skipped": open_skipped,
            "provenance_missing": provenance,
            "missing": len(missing),
            "missing_older_than_lag": len(stale_missing),
        },
        "active": active,
        "companion": companion,
        "rows": ordered,
        "missing_reviews": missing,
    }


def refresh_strategy_book_reviews(
    *,
    data_dir: Path | None = None,
    observe_path: Path | None = None,
    gate_log_path: Path | None = None,
    store_path: Path | None = None,
    now: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Read the observe store and rewrite the sibling review queue."""
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    observe_file = Path(observe_path) if observe_path is not None else root / DEFAULT_OBSERVE_NAME
    gate_file = Path(gate_log_path) if gate_log_path is not None else root / DEFAULT_GATE_LOG_NAME
    dest = Path(store_path) if store_path is not None else root / DEFAULT_STORE_NAME
    moment = now or _utcnow()
    if not observe_file.is_file():
        payload = build_strategy_book_review_queue(
            None,
            now=moment,
            observe_status="missing",
        )
    else:
        observe = _load_json(observe_file)
        if observe is None:
            raise ValueError(f"strategy book observe store is not a JSON object: {observe_file}")
        payload = build_strategy_book_review_queue(
            observe,
            gate_rows=_load_gate_log(gate_file),
            labels=load_post_sale_review_labels(dest.parent, filename=LABELS_FILENAME),
            now=moment,
            observe_status="ok",
        )
    payload["observe_path"] = str(observe_file)
    payload["gate_log_path"] = str(gate_file)
    if persist:
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_json(dest, payload, compact=False)
        payload["path"] = str(dest)
    return payload


def ops_findings_from_strategy_book_reviews(
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Info when the queue refreshed. Warn when an old close has no row."""
    if not isinstance(payload, dict):
        return [
            {
                "severity": "warn",
                "category": CATEGORY,
                "title": STORE_FAILED_TITLE,
                "summary": "Review payload was empty. Fail closed.",
                "auto_fixable": False,
            }
        ]
    if payload.get("observe_status") == "missing":
        return [
            {
                "severity": "warn",
                "category": CATEGORY,
                "title": STORE_FAILED_TITLE,
                "summary": (
                    "Strategy book observe store is missing, so no close can be "
                    "reviewed. Fail closed."
                ),
                "auto_fixable": False,
            }
        ]
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    closed = int(counts.get("closed") or 0)
    primary = int(counts.get("primary") or 0)
    companion = int(counts.get("companion") or 0)
    open_skipped = int(counts.get("open_skipped") or 0)
    provenance = int(counts.get("provenance_missing") or 0)
    summary = (
        f"Strategy book reviews: closed={closed} primary={primary} "
        f"companion={companion} open_skipped={open_skipped} "
        f"provenance_missing={provenance}. "
        "Primary closes are the attention list. Comparison, control, shadow "
        "and bench closes are queued beside them. influences_live=false. "
        "Opinion model off. Evidence for the version review only."
    )
    if closed == 0:
        summary += " Awaiting first close."
    findings = [
        {
            "severity": "info",
            "category": CATEGORY,
            "title": FINDING_TITLE,
            "summary": summary,
            "auto_fixable": False,
        }
    ]
    stale = int(counts.get("missing_older_than_lag") or 0)
    if stale:
        names = []
        for row in payload.get("missing_reviews") or []:
            if not isinstance(row, dict) or not row.get("older_than_lag"):
                continue
            names.append(
                f"{row.get('ticker') or '?'} {row.get('column') or '?'} "
                f"{row.get('exit_session') or '?'} ({row.get('reason')})"
            )
        listed = "; ".join(names[:8])
        findings.append(
            {
                "severity": "warn",
                "category": CATEGORY,
                "title": MISSING_TITLE,
                "summary": (
                    f"{stale} closed strategy-book episode(s) older than "
                    f"{REVIEW_LAG_DAYS} days have no queue row. {listed}. "
                    "Fail closed: they are not reviewed."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def format_strategy_book_reviews_text(payload: dict[str, Any]) -> str:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    return (
        f"strategy book reviews: closed={counts.get('closed', 0)} "
        f"primary={counts.get('primary', 0)} "
        f"companion={counts.get('companion', 0)} "
        f"open_skipped={counts.get('open_skipped', 0)} "
        f"provenance_missing={counts.get('provenance_missing', 0)} "
        f"missing={counts.get('missing', 0)} "
        f"observe_status={payload.get('observe_status')} "
        f"influences_live=false opinion_llm=false"
    )


def main(argv: list[str] | None = None) -> int:
    """Drill-down refresh. The daily path is ops-monitor."""
    parser = argparse.ArgumentParser(
        prog="ftse-strategy-book-reviews",
        description=(
            "Refresh the strategy-book review queue from the observe store. "
            "Observe-only. Does not call a model or change the book."
        ),
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--observe", type=Path, default=None)
    parser.add_argument("--gate-log", type=Path, default=None)
    parser.add_argument("--store", type=Path, default=None)
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = refresh_strategy_book_reviews(
        data_dir=args.data_dir,
        observe_path=args.observe,
        gate_log_path=args.gate_log,
        store_path=args.store,
        persist=not args.no_persist,
    )
    if args.json:
        brief = {
            "counts": payload.get("counts"),
            "observe_status": payload.get("observe_status"),
            "path": payload.get("path"),
            "influences_live": False,
            "opinion_llm": False,
        }
        print(json.dumps(brief, indent=2, sort_keys=True))
    else:
        print(format_strategy_book_reviews_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
