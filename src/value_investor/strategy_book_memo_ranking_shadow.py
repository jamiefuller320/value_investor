"""Observe-only memo-led ranking shadow for the strategy book (L694).

Scores every same-day buy candidate the book signals: names the 20-slot book
fills, names it skips because the book is full, and names a gate rejects, in
every market that produces a signal. A missing or stale cite is no score.

``influences_live`` is false. ``authorize_live_llm_influence`` is called on
every card and fail-closes. The default path does not call a model and does
not read or write ``forward_live``. ``--request-memos`` asks for missing or
stale observe memos inside the existing memo raise. A memo dated after the
candidate session still does not score that session.

The readout rule lives in ``docs/ops/strategy-book-observe.md`` under
``l694-memo-ranking-readout-v1``. Outcome comparison stays null until that
text is in the file and the closed-count and date gates are met.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    SPEND_POOL_WEEKLY_OPS,
    record_estimated_spend,
    weekly_ops_budget_status,
)
from value_investor.decision_input_inventory import _memo_age_days, _overlay_bound
from value_investor.filings_index_dating import bodies_at, key_bodies
from value_investor.llm_agree_veto_shadow import _cite as cite_evidence
from value_investor.llm_agree_veto_shadow import authorize_live_llm_influence
from value_investor.research.verdict import ALLOWED_RISK_TAGS, coerce_research_verdict
from value_investor.storage import read_json, write_json
from value_investor.strategy_book_forward import latest_forward_slot
from value_investor.strategy_book_memo_job import ESTIMATED_MEMO_USD, _headroom_allows
from value_investor.strategy_book_rules import (
    MEMO_MAX_AGE_DAYS,
    SLOT_BOOK_RANDOM_SEED,
    SLOT_COUNT,
    SLOT_RANDOM_ORDERS,
    STAKE_UNITS,
    UnknownMarketClose,
    session_close,
)
from value_investor.strategy_book_signals import (
    history_dir_for,
    newest_screen_run,
    parse_day,
    repo_paths,
    research_root_for,
    screen_rows,
    session_end,
)

STORE_NAME = "strategy_book_memo_ranking_shadow.json"
MEMO_LOG_NAME = "strategy_book_memo_ranking_shadow_memos.jsonl"
JOB_LOG_NAME = "strategy_book_memo_log.jsonl"
RULE_ID = "l694-memo-ranking-readout-v1"
RULE_DOC = "docs/ops/strategy-book-observe.md"
SAMPLING_ID = "l694-memo-sample-v1"

TITLE_REFRESHED = "Strategy book memo-ranking shadow refreshed"
TITLE_MISSING = "Strategy book memo-ranking shadow missing"
TITLE_STALE = "Strategy book memo-ranking shadow stale"
TITLE_UNREADABLE = "Strategy book memo-ranking shadow unreadable"
TITLE_COST = "Strategy book memo-ranking cost"
TITLE_GAPS = "Strategy book memo-ranking input gaps"

# Readout dates. Fixed in the ops doc before any forward score is read.
RULE_FIXED_ON = date(2026, 11, 16)
EVIDENCE_START = date(2026, 11, 17)
HALF_A_END = date(2027, 5, 16)
HALF_B_START = date(2027, 5, 17)
HALF_B_END = date(2027, 11, 16)
MIN_CLOSED = 48
MIN_PER_HALF = 12
# Ranking-lab random-order range in a half, used here as a hurdle on the
# fair-cost episode fraction (1.5 percentage points).
NOISE_BAND = 0.015

# Existing weekly memo raise. This shadow does not change it.
WEEKLY_BUDGET_USD = 40.0
WEEKLY_CAP_MEMOS = 100

P1_SOURCES = (
    "key_filing_bodies",
    "fcf_basis_bound",
    "overlay_bound",
    "memo_recent",
)
GATE_COLUMNS = {
    "decline_rejected_shadow": "operating_decline",
    "sector_rejected_shadow": "sector_headwind",
}
VERDICT_POINTS = {"accumulate": 3.0, "neutral": 2.0, "caution": 1.0, "pass": 0.0}
RISK_POINTS = {"low": 0.2, "medium": 0.0, "high": -0.2}
RISK_LEVELS = frozenset(RISK_POINTS)

DISPOSITION_RANK = {"filled": 0, "skipped_no_slot": 1, "gate_rejected": 2}

SAMPLING_RULE: dict[str, Any] = {
    "id": SAMPLING_ID,
    "weekly_cap_memos": WEEKLY_CAP_MEMOS,
    "weekly_cap_usd": WEEKLY_BUDGET_USD,
    "priority": ["filled", "skipped_no_slot", "gate_rejected"],
    "within_priority": "ticker",
    "reuse_memo_within_days": MEMO_MAX_AGE_DAYS,
    "one_new_memo_per_name_per_iso_week": True,
    "turns_spend_on": False,
}


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")[:10]


def _cid(row: dict[str, Any]) -> str:
    return f"{row.get('market')}:{row.get('ticker')}:{row.get('session')}"


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        day = parse_day(text)
        if day is None:
            return None
        parsed = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _roster_gate(row: dict[str, Any]) -> str:
    if str(row.get("outcome") or "") == "f9":
        listed = row.get("f9")
        if isinstance(listed, list):
            for name in P1_SOURCES:
                if name in listed:
                    return name
        return "f9"
    if row.get("decline") not in (None, "clear"):
        return "operating_decline"
    if row.get("sector") not in (None, "sound"):
        return "sector_headwind"
    return "gate"


def slot_take(
    rows: list[dict[str, Any]],
    order_key,
    *,
    slot_count: int = SLOT_COUNT,
) -> tuple[set[str], int]:
    """Ids the 20-slot book takes, and how many slots are still open at the end.

    Exits are applied at the start of the exit session, matching the book's
    slot book. A same-day exit frees the slot on the next session.
    """
    offered = [row for row in rows if row.get("fill_session")]
    ordered = sorted(offered, key=order_key)
    days = sorted(
        {str(row["fill_session"]) for row in ordered}
        | {str(row["exit_session"]) for row in ordered if row.get("exit_session")}
    )
    due: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        due[str(row["fill_session"])].append(row)
    positions: list[dict[str, str | None]] = []
    taken: set[str] = set()
    for day in days:
        positions = [item for item in positions if item["exit"] not in (None, day)]
        for row in sorted(due.get(day, []), key=order_key):
            if len(positions) >= slot_count:
                continue
            taken.add(_cid(row))
            exit_session = str(row["exit_session"]) if row.get("exit_session") else ""
            positions.append({"exit": exit_session if exit_session > day else None})
    return taken, len(positions)


def collect_candidates(
    events: list[dict[str, Any]] | None,
    episodes: list[dict[str, Any]] | None,
    roster: list[dict[str, Any]] | None,
    *,
    slot_count: int = SLOT_COUNT,
) -> list[dict[str, Any]]:
    """Filled, slot-skipped, and gate-rejected candidates across signal markets.

    The buy-on-signal control is left out. Disposition for names the book
    offered follows the registered ticker order, not the memo score.
    """
    primary: dict[tuple[str, str, str], dict[str, Any]] = {}
    for episode in episodes or []:
        if not isinstance(episode, dict) or episode.get("column") != "primary":
            continue
        key = (
            str(episode.get("market") or ""),
            str(episode.get("ticker") or ""),
            _iso(episode.get("signal_session")),
        )
        primary[key] = episode

    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(row: dict[str, Any]) -> None:
        key = (row["market"], row["ticker"], row["session"], row["role"])
        if not all(key[:3]) or key in seen:
            return
        seen.add(key)
        found.append(row)

    for event in events or []:
        if not isinstance(event, dict):
            continue
        column = event.get("column")
        kind = str(event.get("kind") or "")
        market = str(event.get("market") or "")
        ticker = str(event.get("ticker") or "")
        session = _iso(event.get("session"))
        if column in GATE_COLUMNS:
            add(
                {
                    "market": market,
                    "ticker": ticker,
                    "session": session,
                    "role": "gate",
                    "gate": GATE_COLUMNS[str(column)],
                    "disposition": "gate_rejected",
                    "fill_session": _iso(event.get("fill_session")) or None,
                    "exit_session": None,
                    "fair_cost_return": None,
                    "offered": False,
                    "adjusted_signal": None,
                }
            )
            continue
        if column not in (None, "primary") or kind not in {"filled", "pending_fill"}:
            continue
        episode = primary.get((market, ticker, session))
        fill = _iso(event.get("fill_session")) or None
        exit_session = None
        fair = None
        if episode is not None:
            fill = fill or _iso(episode.get("fill_session")) or None
            exit_session = _iso(episode.get("exit_session")) or None
            if episode.get("status") == "closed" and episode.get("fair_cost_return") is not None:
                fair = float(episode["fair_cost_return"])
        add(
            {
                "market": market,
                "ticker": ticker,
                "session": session,
                "role": "primary",
                "gate": None,
                "disposition": "filled",
                "fill_session": fill,
                "exit_session": exit_session,
                "fair_cost_return": fair,
                "offered": True,
                "adjusted_signal": None,
            }
        )

    signals: dict[tuple[str, str, str], str | None] = {}
    for row in roster or []:
        if not isinstance(row, dict) or row.get("price_rule") is not True:
            continue
        outcome = str(row.get("outcome") or "")
        if outcome not in {"gate", "f9", "filled", "pending_fill"}:
            continue
        market = str(row.get("market") or "")
        ticker = str(row.get("ticker") or "")
        session = _iso(row.get("session"))
        adjusted = row.get("adjusted_signal")
        signals[(market, ticker, session)] = None if adjusted is None else str(adjusted)
        if outcome in {"filled", "pending_fill"}:
            if (market, ticker, session, "primary") in seen:
                continue
            add(
                {
                    "market": market,
                    "ticker": ticker,
                    "session": session,
                    "role": "primary",
                    "gate": None,
                    "disposition": "filled",
                    "fill_session": None,
                    "exit_session": None,
                    "fair_cost_return": None,
                    "offered": True,
                    "adjusted_signal": None if adjusted is None else str(adjusted),
                }
            )
            continue
        add(
            {
                "market": market,
                "ticker": ticker,
                "session": session,
                "role": "gate",
                "gate": _roster_gate(row),
                "disposition": "gate_rejected",
                "fill_session": None,
                "exit_session": None,
                "fair_cost_return": None,
                "offered": False,
                "adjusted_signal": None if adjusted is None else str(adjusted),
            }
        )

    for row in found:
        adjusted = signals.get((row["market"], row["ticker"], row["session"]))
        if adjusted and not row.get("adjusted_signal"):
            row["adjusted_signal"] = adjusted

    offered = [row for row in found if row["offered"]]
    taken, still_open = slot_take(
        offered,
        lambda row: (str(row.get("fill_session") or ""), str(row.get("ticker") or "")),
        slot_count=slot_count,
    )
    for row in offered:
        if not row.get("fill_session"):
            row["disposition"] = "skipped_no_slot" if still_open >= slot_count else "filled"
            continue
        row["disposition"] = "filled" if _cid(row) in taken else "skipped_no_slot"
    found.sort(key=lambda row: (row["session"], row["market"], row["ticker"], row["role"]))
    return found


def market_split(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    signal = sorted({str(row["market"]) for row in rows if row.get("market")})
    bought = sorted(
        {
            str(row["market"])
            for row in rows
            if row.get("disposition") == "filled" and row.get("market")
        }
    )
    return {
        "signal_markets": signal,
        "buy_markets": bought,
        "signal_markets_without_buys": [market for market in signal if market not in bought],
    }


@dataclass
class MemoFacts:
    verdict: str | None = None
    risk_level: str | None = None
    risk_tags: list[str] = field(default_factory=list)
    confidence: float | None = None
    memo_at: str | None = None
    filing_bodies_at: str | None = None
    filing_key_bodies: bool = False
    filing_source: str | None = None
    fcf_as_of: str | None = None
    fcf_bound: bool = False
    fcf_source: str | None = None
    adjusted_signal: str | None = None
    overlay_source: str | None = None


def _in_force(stamp: datetime | None, cutoff: datetime) -> bool:
    return stamp is not None and stamp <= cutoff


def score_candidate(candidate: dict[str, Any], facts: MemoFacts) -> dict[str, Any]:
    """One card. No score unless every cite is in force. Live influence stays closed.

    The returned card always has ``influences_live`` false. The authorize
    call is the fail-close: a missing cite, or this observe flag, means the
    card cannot move a fill.
    """
    session = parse_day(candidate.get("session"))
    gaps: list[str] = []
    gap_detail: dict[str, str] = {}
    reasons: list[str] = []
    evidence: list[dict[str, Any]] = []
    score: float | None = None
    no_score = "missing_evidence"

    file_cutoff = session_end(session) if session is not None else None
    try:
        memo_cutoff = (
            session_close(str(candidate.get("market") or ""), session) if session else None
        )
    except UnknownMarketClose:
        memo_cutoff = None

    def gap(source: str, kind: str) -> None:
        if source not in gaps:
            gaps.append(source)
        gap_detail[source] = kind

    bodies_at_stamp = _aware(facts.filing_bodies_at)
    if file_cutoff is None or not facts.filing_key_bodies or bodies_at_stamp is None:
        gap("key_filing_bodies", "missing")
    elif not _in_force(bodies_at_stamp, file_cutoff):
        gap("key_filing_bodies", "stale")
    else:
        evidence.append(
            cite_evidence(
                "filing",
                str(facts.filing_source or "filings_index"),
                f"bodies_at {bodies_at_stamp.isoformat()}",
                True,
            )
        )

    fcf_stamp = _aware(facts.fcf_as_of)
    if file_cutoff is None or not facts.fcf_bound or fcf_stamp is None:
        gap("fcf_basis_bound", "missing")
    elif not _in_force(fcf_stamp, file_cutoff):
        gap("fcf_basis_bound", "stale")
    else:
        evidence.append(
            cite_evidence(
                "fcf",
                str(facts.fcf_source or "fcf_basis"),
                f"fcf_as_of {fcf_stamp.date().isoformat()}",
                True,
            )
        )

    memo_stamp = _aware(facts.memo_at)
    verdict = coerce_research_verdict(facts.verdict)
    if memo_cutoff is None or memo_stamp is None:
        gap("memo_recent", "missing")
    elif not _in_force(memo_stamp, memo_cutoff):
        gap("memo_recent", "missing")
    else:
        age = _memo_age_days(memo_stamp, now=memo_cutoff)
        if age is None or age > float(MEMO_MAX_AGE_DAYS):
            gap("memo_recent", "stale")
        else:
            evidence.append(
                cite_evidence(
                    "memo",
                    str(facts.overlay_source or "research.json"),
                    f"memo_at {memo_stamp.isoformat()} age_days {age}",
                    verdict,
                )
            )

    adjusted = facts.adjusted_signal or candidate.get("adjusted_signal")
    overlay_ok = bool(_overlay_bound({"adjusted_signal": adjusted}, research_verdict=verdict))
    overlay_stamp = memo_stamp
    if file_cutoff is None or not overlay_ok or overlay_stamp is None:
        gap("overlay_bound", "missing")
    elif not _in_force(overlay_stamp, file_cutoff):
        gap("overlay_bound", "stale")
    else:
        evidence.append(
            cite_evidence(
                "overlay",
                str(facts.overlay_source or "research.json"),
                f"research_verdict {verdict} as_of {overlay_stamp.date().isoformat()}",
                verdict,
            )
        )

    if verdict is not None:
        reasons.append(f"verdict:{verdict}")
    risk = str(facts.risk_level or "").strip().lower()
    if risk in RISK_LEVELS:
        reasons.append(f"risk:{risk}")
    tags: list[str] = []
    for tag in facts.risk_tags:
        token = str(tag or "").strip().lower()
        if token in ALLOWED_RISK_TAGS and token not in tags:
            tags.append(token)
            reasons.append(f"risk_tag:{token}")
    confidence = facts.confidence
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        value = float(confidence)
        if 0.0 <= value <= 1.0:
            reasons.append(f"confidence:{value}")
            evidence.append(
                cite_evidence(
                    "memo",
                    str(facts.overlay_source or "research.json"),
                    "research_confidence",
                    value,
                )
            )

    p1_clear = not any(source in gaps for source in P1_SOURCES)
    input_gaps = [source for source in gaps if source != "overlay_bound"]
    if verdict not in VERDICT_POINTS and not input_gaps and session is not None:
        # A prose verdict is not a score, even when the other cites are in force.
        no_score = "unstructured_memo"
    elif not p1_clear:
        no_score = (
            "stale_inputs"
            if gaps and all(gap_detail.get(source) == "stale" for source in gaps)
            else "missing_evidence"
        )
    elif session is None:
        no_score = "missing_evidence"
    else:
        score = VERDICT_POINTS[verdict]
        if risk in RISK_POINTS:
            score = round(score + RISK_POINTS[risk], 4)
        no_score = ""
    if score is None:
        reasons = []
        evidence = []

    card = {
        "reasons": reasons,
        "evidence": evidence,
        "influences_live": False,
        "observe_only": True,
    }
    authorized = authorize_live_llm_influence(card)
    return {
        "candidate_id": f"{_cid(candidate)}:{candidate.get('role')}",
        "market": candidate.get("market"),
        "ticker": candidate.get("ticker"),
        "session": candidate.get("session"),
        "disposition": candidate.get("disposition"),
        "gate": candidate.get("gate"),
        "fill_session": candidate.get("fill_session"),
        "exit_session": candidate.get("exit_session"),
        "fair_cost_return": candidate.get("fair_cost_return"),
        "score": score,
        "score_status": "scored" if score is not None else "no_score",
        "no_score_reason": None if score is not None else no_score,
        "reasons": reasons,
        "evidence": evidence,
        "gaps": [source for source in P1_SOURCES if source in gaps],
        "gap_detail": gap_detail,
        "influences_live": False,
        "observe_only": True,
        "live_influence_authorized": bool(authorized),
        "stake_units": STAKE_UNITS,
    }


def rank_input_gaps(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank the four P1 cites by how many candidates that one cite would unlock."""
    sole: Counter[str] = Counter()
    blocked: Counter[str] = Counter()
    unstructured = 0
    for card in cards:
        gaps = [source for source in (card.get("gaps") or []) if source in P1_SOURCES]
        for source in gaps:
            blocked[source] += 1
        if len(gaps) == 1:
            sole[gaps[0]] += 1
        if card.get("no_score_reason") == "unstructured_memo" and not gaps:
            unstructured += 1
    ranked = [
        {
            "source": source,
            "would_unlock": int(sole[source]),
            "blocked": int(blocked[source]),
        }
        for source in P1_SOURCES
    ]
    ranked.sort(key=lambda row: (-row["would_unlock"], -row["blocked"], row["source"]))
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return {
        "p1_only": True,
        "universe": "strategy_book_candidates",
        "ranked_sources": ranked,
        "unstructured_memo": unstructured,
        "auto_fixable": False,
    }


def estimate_cost(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Full-width memo cost. Sampling is a proposal; spend stays off."""
    by_day: Counter[str] = Counter(
        str(card.get("session") or "") for card in cards if card.get("session")
    )
    days = len(by_day)
    latest = max(by_day) if by_day else None
    latest_n = by_day[latest] if latest else 0
    mean = (sum(by_day.values()) / days) if days else 0.0
    weekly_n = mean * 5.0
    weekly_usd = weekly_n * float(ESTIMATED_MEMO_USD)
    over = weekly_usd > WEEKLY_BUDGET_USD
    return {
        "usd_per_candidate_per_day": ESTIMATED_MEMO_USD,
        "latest_session": latest,
        "latest_session_candidates": latest_n,
        "latest_session_usd": round(latest_n * float(ESTIMATED_MEMO_USD), 2),
        "sessions": days,
        "mean_candidates_per_session": round(mean, 2),
        "weekday_week_candidates": round(weekly_n, 2),
        "weekday_week_usd": round(weekly_usd, 2),
        "weekly_budget_usd": WEEKLY_BUDGET_USD,
        "over_budget": over,
        "sampling": SAMPLING_RULE if over else None,
        "spend_enabled": False,
        "influences_live": False,
        "auto_fixable": False,
    }


def _week_key(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def memo_raise_spent_usd(repo_root: Path, *, now: datetime) -> float:
    """Estimated memo-raise dollars already requested in this ISO week."""
    week = _week_key(now.date())
    paths = repo_paths(repo_root)
    spent = 0.0
    for row in _jsonl_rows(paths.data / JOB_LOG_NAME):
        if row.get("action") != "requested":
            continue
        day = parse_day(row.get("session"))
        if day is None or _week_key(day) != week:
            continue
        spent += float(row.get("estimated_spend_usd") or ESTIMATED_MEMO_USD)
    for row in _jsonl_rows(paths.data / MEMO_LOG_NAME):
        if row.get("action") != "requested":
            continue
        stamp = _aware(row.get("requested_at"))
        if stamp is None or _week_key(stamp.date()) != week:
            continue
        spent += float(row.get("estimated_spend_usd") or ESTIMATED_MEMO_USD)
    return round(spent, 2)


def plan_observe_memos(
    names: list[dict[str, Any]],
    *,
    now: datetime,
    spent_this_week_usd: float,
    full_width_over_budget: bool,
) -> dict[str, Any]:
    """One memo per name. Fresh memos are reused. The $40 raise is the cap.

    Priority and the 100-memo sample apply when a full-width week is above
    $40. A memo younger than 21 days is not bought again.
    """
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    for row in names:
        market = str(row.get("market") or "")
        ticker = str(row.get("ticker") or "")
        if not market or not ticker:
            continue
        rank = DISPOSITION_RANK.get(str(row.get("disposition") or ""), 9)
        current = chosen.get((market, ticker))
        session = str(row.get("session") or "")
        if (
            current is None
            or rank < int(current["rank"])
            or (rank == int(current["rank"]) and session > str(current.get("session") or ""))
        ):
            chosen[(market, ticker)] = {**row, "market": market, "ticker": ticker, "rank": rank}
    due: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    for row in chosen.values():
        stamp = _aware(row.get("memo_at"))
        age = _memo_age_days(stamp, now=now) if stamp is not None else None
        if age is not None and age <= float(MEMO_MAX_AGE_DAYS):
            reused.append({"market": row["market"], "ticker": row["ticker"], "memo_age_days": age})
            continue
        due.append(row)
    due.sort(key=lambda row: (int(row["rank"]), str(row["ticker"]), str(row["market"])))
    room_usd = max(0.0, WEEKLY_BUDGET_USD - float(spent_this_week_usd))
    room_n = int(round(room_usd * 100)) // int(round(float(ESTIMATED_MEMO_USD) * 100))
    cap = min(room_n, WEEKLY_CAP_MEMOS)
    selected = due[:cap]
    held = due[cap:]
    return {
        "sampling_id": SAMPLING_ID if full_width_over_budget else None,
        "sampling_applied": bool(full_width_over_budget and held),
        "spent_this_week_usd": round(float(spent_this_week_usd), 2),
        "room_usd": round(room_usd, 2),
        "cap": cap,
        "selected": selected,
        "held_for_budget": held,
        "reused": reused,
    }


def _screen_row(repo_root: Path, market: str, ticker: str, now: datetime) -> dict[str, Any]:
    paths = repo_paths(repo_root)
    _path, payload, _day = newest_screen_run(
        history_dir_for(paths, market),
        now.date() + timedelta(days=1),
    )
    row = screen_rows(payload).get(ticker.upper())
    if isinstance(row, dict) and row:
        return dict(row)
    return {"ticker": ticker, "signal": "buy", "name": ticker}


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def request_observe_memos(
    names: list[dict[str, Any]],
    *,
    repo_root: Path,
    now: datetime,
    spent_this_week_usd: float,
    full_width_over_budget: bool,
    apply: bool,
    runner: Any = None,
    budget_status: Any = None,
    record_spend: Any = None,
) -> dict[str, Any]:
    """Ask for observe memos. Does not set a live-capital flag.

    Spend is the existing $0.40 estimate on ``weekly_ops``, and only after a
    memo returns. Headroom keeps the memo job's $8 reserve.
    """
    plan = plan_observe_memos(
        names,
        now=now,
        spent_this_week_usd=spent_this_week_usd,
        full_width_over_budget=full_width_over_budget,
    )
    rows: list[dict[str, Any]] = []
    for held in plan["held_for_budget"]:
        rows.append(
            {
                "market": held["market"],
                "ticker": held["ticker"],
                "disposition": held.get("disposition"),
                "action": "skipped",
                "skip_reason": "memo_raise_cap",
                "estimated_spend_usd": 0.0,
            }
        )
    if not apply:
        for item in plan["selected"]:
            rows.append(
                {
                    "market": item["market"],
                    "ticker": item["ticker"],
                    "disposition": item.get("disposition"),
                    "action": "planned",
                    "skip_reason": None,
                    "estimated_spend_usd": 0.0,
                }
            )
        spent = 0.0
    else:
        call = runner
        if call is None:
            from value_investor.strategy_book_memo_job import default_memo_runner

            call = default_memo_runner
        budget = budget_status or (
            lambda: weekly_ops_budget_status(estimated_memo_usd=float(ESTIMATED_MEMO_USD))
        )
        record = record_spend or (
            lambda amount: record_estimated_spend(amount, pool=SPEND_POOL_WEEKLY_OPS)
        )
        reserved = 0.0
        spent = 0.0
        log_path = repo_paths(repo_root).data / MEMO_LOG_NAME
        for item in plan["selected"]:
            record_row: dict[str, Any] = {
                "market": item["market"],
                "ticker": item["ticker"],
                "disposition": item.get("disposition"),
                "session": item.get("session"),
                "action": "skipped",
                "skip_reason": None,
                "estimated_spend_usd": 0.0,
                "requested_at": now.astimezone(UTC).isoformat(),
                "verdict": None,
                "memo_finished_at": None,
                "influences_live": False,
            }
            status = budget()
            if not _headroom_allows(status if isinstance(status, dict) else {}, reserved=reserved):
                record_row["skip_reason"] = "memo_not_ready_budget"
            else:
                try:
                    outcome = call(
                        market=item["market"],
                        ticker=item["ticker"],
                        screen_row=_screen_row(repo_root, item["market"], item["ticker"], now),
                        repo_root=repo_root,
                        session=str(item.get("session") or ""),
                    )
                except Exception as exc:  # noqa: BLE001 — one name must not stop the others
                    record_row["skip_reason"] = f"runner_error: {exc}"
                else:
                    record_row["action"] = "requested"
                    record_row["estimated_spend_usd"] = ESTIMATED_MEMO_USD
                    if isinstance(outcome, dict):
                        record_row["verdict"] = outcome.get("verdict")
                        record_row["memo_finished_at"] = outcome.get("finished_at")
                    record(float(ESTIMATED_MEMO_USD))
                    reserved += float(ESTIMATED_MEMO_USD)
                    spent += float(ESTIMATED_MEMO_USD)
            rows.append(record_row)
            _append_jsonl(log_path, record_row)
    requested = sum(1 for row in rows if row.get("action") == "requested")
    return {
        "observe_only": True,
        "influences_live": False,
        "spend_enabled": False,
        "sampling_id": plan["sampling_id"],
        "sampling_applied": plan["sampling_applied"],
        "spent_before_usd": plan["spent_this_week_usd"],
        "estimated_spend_usd": round(spent, 2),
        "requested": requested,
        "reused": len(plan["reused"]),
        "names": rows,
    }


def rule_text_in_force(text: str | None) -> bool:
    """True when the committed observe doc still carries this readout."""
    if not text:
        return False
    return (
        RULE_ID in text
        and "fair-cost episode" in text
        and EVIDENCE_START.isoformat() in text
        and str(MIN_CLOSED) in text
    )


def read_rule_text(repo_root: Path | None) -> str:
    path = (Path(repo_root) if repo_root is not None else Path()) / RULE_DOC
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _half(signal: date) -> str | None:
    if signal < EVIDENCE_START or signal > HALF_B_END:
        return None
    if signal <= HALF_A_END:
        return "a"
    if signal >= HALF_B_START:
        return "b"
    return None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _arm_median(
    pool: list[dict[str, Any]],
    order_key,
    *,
    slot_count: int,
) -> float | None:
    taken, _open = slot_take(pool, order_key, slot_count=slot_count)
    returns = [
        float(row["fair_cost_return"])
        for row in pool
        if _cid(row) in taken and row.get("fair_cost_return") is not None
    ]
    return _median(returns)


def _pool_row(card: dict[str, Any]) -> dict[str, Any] | None:
    if card.get("disposition") not in {"filled", "skipped_no_slot"}:
        return None
    if card.get("score") is None or card.get("fair_cost_return") is None:
        return None
    signal = parse_day(card.get("session"))
    if signal is None or _half(signal) is None:
        return None
    fill = card.get("fill_session") or card.get("session")
    return {
        "market": card.get("market"),
        "ticker": card.get("ticker"),
        "session": card.get("session"),
        "fill_session": fill,
        "exit_session": card.get("exit_session"),
        "fair_cost_return": float(card["fair_cost_return"]),
        "score": float(card["score"]),
        "half": _half(signal),
    }


def compare_outcomes(
    cards: list[dict[str, Any]],
    *,
    rule_text: str | None,
    slot_count: int = SLOT_COUNT,
) -> dict[str, Any]:
    """Fair-cost episode % for three arms. Null until the rule and the minimum.

    Nothing dated before the evidence start can enter the pool. The ranking
    lab windows are not passed in.
    """
    readout: dict[str, Any] = {
        "rule_id": RULE_ID,
        "rule_fixed_on": RULE_FIXED_ON.isoformat(),
        "rule_in_force": rule_text_in_force(rule_text),
        "metric": "fair_cost_episode_pct",
        "evidence_start": EVIDENCE_START.isoformat(),
        "half_a": [EVIDENCE_START.isoformat(), HALF_A_END.isoformat()],
        "half_b": [HALF_B_START.isoformat(), HALF_B_END.isoformat()],
        "minimum_closed": MIN_CLOSED,
        "minimum_per_half": MIN_PER_HALF,
        "noise_band": NOISE_BAND,
        "stake_units": STAKE_UNITS,
        "counts_as_evidence": False,
        "comparison": None,
        "closed_in_window": 0,
        "half_a_closed": 0,
        "half_b_closed": 0,
    }
    if not readout["rule_in_force"]:
        readout["status"] = "rule_not_in_force"
        return readout
    pool = [row for card in cards if (row := _pool_row(card)) is not None]
    readout["closed_in_window"] = len(pool)
    readout["half_a_closed"] = sum(1 for row in pool if row["half"] == "a")
    readout["half_b_closed"] = sum(1 for row in pool if row["half"] == "b")
    if (
        len(pool) < MIN_CLOSED
        or readout["half_a_closed"] < MIN_PER_HALF
        or readout["half_b_closed"] < MIN_PER_HALF
    ):
        readout["status"] = "awaiting_closed_outcomes"
        return readout

    def registered(row: dict[str, Any]) -> tuple[str, str]:
        return (str(row["fill_session"]), str(row["ticker"]))

    def memo_order(row: dict[str, Any]) -> tuple[str, float, str]:
        return (str(row["fill_session"]), -float(row["score"]), str(row["ticker"]))

    def arm(rows: list[dict[str, Any]], key) -> float | None:
        return _arm_median(rows, key, slot_count=slot_count)

    def pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
        memo_median = arm(rows, memo_order)
        registered_median = arm(rows, registered)
        random_medians: list[float] = []
        for offset in range(SLOT_RANDOM_ORDERS):
            rng = random.Random(SLOT_BOOK_RANDOM_SEED + offset)

            def _key(row: dict[str, Any], _rng: random.Random = rng) -> tuple[str, float]:
                return (str(row["fill_session"]), _rng.random())

            sample = arm(rows, _key)
            if sample is not None:
                random_medians.append(sample)
        random_median = _median(random_medians)
        ahead = (
            memo_median is not None
            and registered_median is not None
            and random_median is not None
            and memo_median > registered_median + NOISE_BAND
            and memo_median > random_median + NOISE_BAND
        )
        return {
            "n": len(rows),
            "memo_rank_median": memo_median,
            "registered_order_median": registered_median,
            "random_order_median": random_median,
            "ahead_of_both_by_noise_band": ahead,
        }

    halves = {
        "a": pack([row for row in pool if row["half"] == "a"]),
        "b": pack([row for row in pool if row["half"] == "b"]),
        "whole": pack(pool),
    }
    beats = bool(
        halves["a"]["ahead_of_both_by_noise_band"] and halves["b"]["ahead_of_both_by_noise_band"]
    )
    readout["status"] = "compared"
    readout["counts_as_evidence"] = True
    readout["comparison"] = {"halves": halves, "beats_registered_and_random": beats}
    return readout


def _run_date(path: str) -> str | None:
    marker = "run_"
    index = path.find(marker)
    if index < 0:
        return None
    token = path[index + len(marker) : index + len(marker) + 8]
    if len(token) == 8 and token.isdigit():
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    return None


def _fcf_date(gate_row: dict[str, Any]) -> str | None:
    for item in gate_row.get("inputs") or []:
        if not isinstance(item, dict):
            continue
        found = _run_date(str(item.get("path") or ""))
        if found:
            return found
    observed = _iso(gate_row.get("as_of"))
    return observed or None


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def load_facts(
    repo_root: Path,
    candidate: dict[str, Any],
    gate_row: dict[str, Any] | None,
) -> MemoFacts:
    """Point-in-time cites. A file dated after the session is left unused."""
    paths = repo_paths(repo_root)
    market = str(candidate.get("market") or "")
    root = research_root_for(paths, market)
    ticker = str(candidate.get("ticker") or "")
    # The memo job writes a name in its research home, which can differ from
    # the market that signalled it (VOE.VI is atx on the book and euro_depth
    # at home). Read that home when this market has no memo file.
    if ticker and not (root / ticker / "research.json").is_file():
        from value_investor.library_dedupe import research_home_market

        home = research_home_market(paths.library, ticker)
        if home and home != market:
            home_root = paths.library / "markets" / home / "screen" / "research"
            if (home_root / ticker / "research.json").is_file():
                root = home_root
    facts = MemoFacts(adjusted_signal=candidate.get("adjusted_signal"))
    session = parse_day(candidate.get("session"))
    cutoff = session_end(session) if session is not None else None
    index_path = root / ticker / "sources" / "filings" / "filings_index.json"
    if index_path.is_file():
        try:
            payload = read_json(index_path)
        except (OSError, ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            stamp = bodies_at(payload)
            if stamp is not None and cutoff is not None and stamp <= cutoff:
                facts.filing_bodies_at = stamp.isoformat()
                facts.filing_key_bodies = bool(key_bodies(payload))
                facts.filing_source = _relative(index_path, paths.root)
    research_path = root / ticker / "research.json"
    file_verdict = None
    file_memo_at = None
    if research_path.is_file():
        try:
            document = read_json(research_path)
        except (OSError, ValueError, TypeError):
            document = None
        if isinstance(document, dict):
            file_memo_at = document.get("updated_at") or document.get("created_at")
            file_verdict = document.get("research_verdict")
            facts.risk_level = document.get("research_risk_level")
            facts.risk_tags = [str(tag) for tag in (document.get("risk_tags") or [])]
            raw_confidence = document.get("research_confidence")
            if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool):
                facts.confidence = float(raw_confidence)
            facts.overlay_source = _relative(research_path, paths.root)
    try:
        memo_cutoff = (
            session_close(str(candidate.get("market") or ""), session) if session else None
        )
    except UnknownMarketClose:
        memo_cutoff = None
    file_stamp = _aware(file_memo_at)
    if file_stamp is not None and memo_cutoff is not None and file_stamp <= memo_cutoff:
        facts.memo_at = file_stamp.isoformat()
        facts.verdict = None if file_verdict is None else str(file_verdict)
    elif gate_row is not None:
        gate_stamp = _aware(gate_row.get("memo_at"))
        if gate_stamp is not None and memo_cutoff is not None and gate_stamp <= memo_cutoff:
            facts.memo_at = gate_stamp.isoformat()
            facts.verdict = gate_row.get("memo_verdict") or gate_row.get("research_verdict")
            facts.overlay_source = facts.overlay_source or "strategy_book_gate_log"
            facts.risk_level = None
            facts.risk_tags = []
            facts.confidence = None
    if gate_row is not None:
        listed = gate_row.get("f9")
        failed = set(listed) if isinstance(listed, list) else set()
        passed = listed == "pass" or (isinstance(listed, list) and "fcf_basis_bound" not in failed)
        if passed:
            dated = _fcf_date(gate_row)
            stamp = _aware(dated)
            if stamp is not None and cutoff is not None and stamp <= cutoff:
                facts.fcf_bound = True
                facts.fcf_as_of = stamp.date().isoformat()
                facts.fcf_source = "strategy_book_gate_log"
    return facts


def _gate_index(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    if not path.is_file():
        return index
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return index
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("kind") not in (None, "session"):
            continue
        key = (str(row.get("market") or ""), str(row.get("ticker") or ""))
        index[key].append(row)
    for rows in index.values():
        rows.sort(key=lambda item: str(item.get("as_of") or ""))
    return index


def _gate_row_for(
    index: dict[tuple[str, str], list[dict[str, Any]]],
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    rows = index.get((str(candidate.get("market") or ""), str(candidate.get("ticker") or ""))) or []
    session = str(candidate.get("session") or "")
    chosen = None
    for row in rows:
        if str(row.get("as_of") or "") <= session:
            chosen = row
    return chosen


def build_cards(
    candidates: list[dict[str, Any]],
    *,
    repo_root: Path,
    facts_for=None,
) -> list[dict[str, Any]]:
    index = _gate_index(repo_paths(repo_root).data / "strategy_book_gate_log.jsonl")
    cards: list[dict[str, Any]] = []
    for candidate in candidates:
        if facts_for is not None:
            facts = facts_for(candidate)
        else:
            facts = load_facts(repo_root, candidate, _gate_row_for(index, candidate))
        cards.append(score_candidate(candidate, facts))
    return cards


def build_store(
    *,
    cards: list[dict[str, Any]],
    markets: dict[str, list[str]],
    now: datetime,
    rule_text: str,
    memo_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counts = Counter(str(card.get("disposition") or "") for card in cards)
    scored = sum(1 for card in cards if card.get("score") is not None)
    return {
        "instrument": "strategy_book_memo_ranking_shadow",
        "rule_id": RULE_ID,
        "generated_at": now.astimezone(UTC).isoformat(),
        "influences_live": False,
        "observe_only": True,
        "spend_enabled": False,
        "stake_units": STAKE_UNITS,
        "counts": {
            "candidates": len(cards),
            "filled": int(counts["filled"]),
            "skipped_no_slot": int(counts["skipped_no_slot"]),
            "gate_rejected": int(counts["gate_rejected"]),
            "scored": scored,
            "no_score": len(cards) - scored,
        },
        "markets": markets,
        "input_gaps": rank_input_gaps(cards),
        "cost": estimate_cost(cards),
        "readout": compare_outcomes(cards, rule_text=rule_text),
        "memo_run": memo_run,
        "candidates": cards,
    }


def public_summary(store: dict[str, Any]) -> dict[str, Any]:
    counts = store.get("counts") if isinstance(store.get("counts"), dict) else {}
    cost = store.get("cost") if isinstance(store.get("cost"), dict) else {}
    readout = store.get("readout") if isinstance(store.get("readout"), dict) else {}
    markets = store.get("markets") if isinstance(store.get("markets"), dict) else {}
    return {
        "instrument": store.get("instrument"),
        "influences_live": False,
        "spend_enabled": False,
        "generated_at": store.get("generated_at"),
        "candidates": counts.get("candidates"),
        "filled": counts.get("filled"),
        "skipped_no_slot": counts.get("skipped_no_slot"),
        "gate_rejected": counts.get("gate_rejected"),
        "scored": counts.get("scored"),
        "signal_markets_without_buys": list(markets.get("signal_markets_without_buys") or []),
        "weekday_week_usd": cost.get("weekday_week_usd"),
        "over_budget": cost.get("over_budget"),
        "sampling": bool(cost.get("sampling")),
        "readout_status": readout.get("status"),
        "counts_as_evidence": readout.get("counts_as_evidence"),
        "observe_memo_spend_usd": (
            (store.get("memo_run") or {}).get("estimated_spend_usd")
            if isinstance(store.get("memo_run"), dict)
            else 0.0
        ),
    }


def run_shadow(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    apply: bool = False,
    events: list[dict[str, Any]] | None = None,
    episodes: list[dict[str, Any]] | None = None,
    roster: list[dict[str, Any]] | None = None,
    facts_for=None,
    request_memos: bool = False,
    memo_runner: Any = None,
    budget_status: Any = None,
    record_spend: Any = None,
) -> dict[str, Any]:
    """Build the shadow. Writes only its own store, and only when ``apply`` is set."""
    root = Path(repo_root) if repo_root is not None else Path()
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    paths = repo_paths(root)
    if events is None or episodes is None or roster is None:
        observe = _read_object(paths.observe)
        status = _read_object(paths.data / "strategy_book_forward_status.json")
        events = list(observe.get("events") or []) if events is None else events
        episodes = list(observe.get("episodes") or []) if episodes is None else episodes
        roster = list(status.get("candidates") or []) if roster is None else roster
    candidates = collect_candidates(events, episodes, roster)
    memo_run = None
    if request_memos:
        preview = (
            build_cards(candidates, repo_root=root, facts_for=facts_for)
            if facts_for is not None
            else None
        )
        index = (
            {}
            if facts_for is not None
            else _gate_index(paths.data / "strategy_book_gate_log.jsonl")
        )
        names: list[dict[str, Any]] = []
        for candidate in candidates:
            if facts_for is not None:
                memo_at = None
            else:
                memo_at = load_facts(root, candidate, _gate_row_for(index, candidate)).memo_at
            names.append(
                {
                    "market": candidate.get("market"),
                    "ticker": candidate.get("ticker"),
                    "disposition": candidate.get("disposition"),
                    "session": candidate.get("session"),
                    "memo_at": memo_at,
                }
            )
        if preview is not None:
            by_id = {
                (card.get("market"), card.get("ticker"), card.get("session")): card
                for card in preview
            }
            for name in names:
                card = by_id.get((name["market"], name["ticker"], name["session"]))
                if card and "memo_recent" not in (card.get("gaps") or []):
                    name["memo_at"] = moment.isoformat()
        width = estimate_cost([{"session": candidate.get("session")} for candidate in candidates])
        memo_run = request_observe_memos(
            names,
            repo_root=root,
            now=moment,
            spent_this_week_usd=memo_raise_spent_usd(root, now=moment),
            full_width_over_budget=bool(width.get("over_budget")),
            apply=apply,
            runner=memo_runner,
            budget_status=budget_status,
            record_spend=record_spend,
        )
    cards = build_cards(candidates, repo_root=root, facts_for=facts_for)
    store = build_store(
        cards=cards,
        markets=market_split(candidates),
        now=moment,
        rule_text=read_rule_text(root),
        memo_run=memo_run,
    )
    store["influences_live"] = False
    wrote = False
    if apply:
        write_json(paths.data / STORE_NAME, store)
        wrote = True
    summary = public_summary(store)
    summary["wrote"] = wrote
    summary["errors"] = []
    return summary


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _finding(severity: str, title: str, summary: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": "research",
        "title": title,
        "summary": summary,
        "auto_fixable": False,
    }


def _parse_dt(value: Any) -> datetime | None:
    stamp = _aware(value)
    return stamp


def findings_from_store(
    store: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    unreadable: str | None = None,
) -> list[dict[str, Any]]:
    """Warn only when the store is missing, stale, or unreadable. Spend stays off."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if unreadable:
        return [_finding("warn", TITLE_UNREADABLE, unreadable)]
    if not store:
        return [
            _finding(
                "warn",
                TITLE_MISSING,
                "docs/data/strategy_book_memo_ranking_shadow.json is missing. "
                "The weekday forward workflow writes it. No rememo, no ingest, no spend.",
            )
        ]
    slot = latest_forward_slot(moment)
    stamp = _parse_dt(store.get("generated_at"))
    if stamp is None or stamp < slot:
        return [
            _finding(
                "warn",
                TITLE_STALE,
                f"Memo-ranking shadow is older than the {slot.isoformat()} slot "
                f"(generated_at {store.get('generated_at')}). No rememo or ingest.",
            )
        ]
    summary = public_summary(store)
    markets = ", ".join(summary.get("signal_markets_without_buys") or []) or "none"
    cost = store.get("cost") if isinstance(store.get("cost"), dict) else {}
    gaps = store.get("input_gaps") if isinstance(store.get("input_gaps"), dict) else {}
    ranked = gaps.get("ranked_sources") or []
    top = ranked[0]["source"] if ranked else "none"
    sampling = cost.get("sampling")
    if sampling:
        cost_text = (
            f"Full width is ${cost.get('usd_per_candidate_per_day')} a candidate a day, "
            f"about ${cost.get('weekday_week_usd')} a weekday week, above the ${WEEKLY_BUDGET_USD} "
            f"memo raise. Proposal {SAMPLING_ID}: at most {WEEKLY_CAP_MEMOS} new memos a week, "
            "filled then slot-skipped then gate-rejected, ticker order, reuse a memo for "
            f"{MEMO_MAX_AGE_DAYS} days. Spend is not turned on."
        )
    else:
        cost_text = (
            f"Full width is ${cost.get('usd_per_candidate_per_day')} a candidate a day, "
            f"about ${cost.get('weekday_week_usd')} a weekday week, inside the ${WEEKLY_BUDGET_USD} "
            "memo raise. No sampling proposal. Spend is not turned on."
        )
    rank_text = ", ".join(
        f"{row.get('rank')}.{row.get('source')} unlocks {row.get('would_unlock')}" for row in ranked
    )
    return [
        _finding(
            "info",
            TITLE_REFRESHED,
            f"Candidates {summary.get('candidates')} "
            f"(filled {summary.get('filled')}, skipped for a slot {summary.get('skipped_no_slot')}, "
            f"gate-rejected {summary.get('gate_rejected')}, scored {summary.get('scored')}). "
            f"Signal markets with no buy: {markets}. "
            f"Readout {summary.get('readout_status')}; counts_as_evidence "
            f"{summary.get('counts_as_evidence')}. Observe-only.",
        ),
        _finding("info", TITLE_COST, cost_text),
        _finding(
            "info",
            TITLE_GAPS,
            f"P1 cite rank on strategy-book candidates, top {top}. {rank_text}. "
            "No ingest. Names outside this candidate set are not counted.",
        ),
    ]


def load_store(repo_root: Path | None = None) -> tuple[dict[str, Any] | None, str | None]:
    path = repo_paths(repo_root).data / STORE_NAME
    if not path.is_file():
        return None, None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "shadow store is not an object"
    payload["influences_live"] = False
    return payload, None


def check_findings(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    store, error = load_store(repo_root)
    if error:
        return findings_from_store(None, now=now, unreadable=error)
    return findings_from_store(store, now=now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Memo-led ranking shadow (observe-only, does not spend or write the book)"
    )
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument("--apply", action="store_true", help="Write the shadow store")
    parser.add_argument(
        "--request-memos",
        action="store_true",
        help=(
            "Ask for missing or stale observe memos inside the $40 raise. "
            "Does not set influences_live. A memo after the session does not score it."
        ),
    )
    parser.add_argument("--as-of", help="Override the run timestamp (ISO-8601)")
    args = parser.parse_args(argv)
    moment = None
    if args.as_of:
        moment = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    summary = run_shadow(
        repo_root=args.repo_root,
        now=moment,
        apply=args.apply,
        request_memos=args.request_memos,
    )
    print(json.dumps(summary, indent=2, default=str))
    return 1 if summary.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
