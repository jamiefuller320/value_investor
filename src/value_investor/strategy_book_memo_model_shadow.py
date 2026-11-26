"""Outcome-scored memo model shadow (L703). Observe-only.

Both the incumbent memo model (``composer-2.5``) and the comparison
challenger (``grok-4.6``) can write a shadow memo on a real strategy-book
signal. Each model's block or pass is scored against that name's 63-session
outcome, using the same early marks as the memo-free shadow (10 and 20
sessions, then the 63-session fair-cost return).

Nothing here feeds the strategy book, changes a fill, rewrites a live research
memo, or switches the live model. ``decision.json`` outcome
``inconclusive_keep`` leaves ``composer-2.5`` in place. A missing or stale
cite is no score and no effect. ``authorize_live_llm_influence`` fail-closes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from value_investor.decision_input_inventory import _memo_age_days
from value_investor.llm_agree_veto_shadow import authorize_live_llm_influence
from value_investor.storage import read_json, write_json
from value_investor.strategy_book_forward import latest_forward_slot
from value_investor.strategy_book_memo_free_shadow import (
    EARLY_SESSIONS,
    OUTCOME_SESSIONS,
    _chart_series,
    early_marks_for_series,
)
from value_investor.strategy_book_prices import latest_completed_session
from value_investor.strategy_book_rules import (
    MEMO_MAX_AGE_DAYS,
    OBSERVE_STORE_NAME,
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
)

STORE_NAME = "strategy_book_memo_model_shadow.json"
MEMO_LOG_NAME = "strategy_book_memo_model_shadow_memos.jsonl"
DECISION_REL = Path("docs/data/memo_model_comparison/decision.json")
RULE_ID = "l703-outcome-score-v1"
EARLY_MARK_SOURCE = "strategy_book_memo_free_shadow.early_marks_for_series"
INSTRUMENT = "strategy_book_memo_model_shadow"

INCUMBENT_MODEL = "composer-2.5"
CHALLENGER_MODEL = "grok-4.6"
LIVE_MODEL = INCUMBENT_MODEL
MODELS = (INCUMBENT_MODEL, CHALLENGER_MODEL)
KEEP_OUTCOMES = frozenset({"keep", "inconclusive_keep", "switch"})

# Same floor as the memo-free early-outcome board. Below it the hit rate is null.
MIN_SCORED = 8
MAX_SIGNALS_PER_RUN = 3
WEEKLY_CAP_USD = 24.0
INCUMBENT_MEMO_USD = 0.40

TITLE_REFRESHED = "Strategy book memo model shadow refreshed"
TITLE_MISSING = "Strategy book memo model shadow missing"
TITLE_STALE = "Strategy book memo model shadow stale"
TITLE_UNREADABLE = "Strategy book memo model shadow unreadable"
TITLE_FAIL_CLOSED = "Strategy book memo model shadow fail-closed"

ENTRY_OUTCOMES = frozenset({"pending_fill", "filled", "memo_not_ready", "memo_blocked"})
APPENDIX = """SHADOW EVIDENCE (required for this run, after RESEARCH VERDICT)
Write this section exactly, with paths relative to the sources folder above:

EVIDENCE
- [filings/bodies/<file>] "<verbatim quote, at most 200 characters>" — <what it supports>
(3 to 8 lines. Quote the file exactly.)

A verdict without a quote that appears in the cited file is not used."""


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "")[:10]
    return text if parse_day(text) else ""


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


def _clip(value: Any, limit: int = 400) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("market") or ""),
        str(row.get("ticker") or ""),
        _iso(row.get("signal_session") or row.get("session")),
    )


def entry_effect(verdict: str | None) -> str | None:
    """``block`` when the book would refuse the entry, ``pass`` when it would allow it.

    Research verdict ``pass`` blocks the entry. ``accumulate`` and ``neutral``
    let it through. An empty verdict is neither.
    """
    from value_investor.memo_model_comparison import book_effect

    effect = book_effect(verdict, "buy")
    if effect == "blocks":
        return "block"
    if effect == "allows":
        return "pass"
    return None


def outcome_hit(effect: str | None, outcome: float | None) -> bool | None:
    """True when a block avoided a loss, or a pass kept a non-loss.

    A missing effect or a missing 63-session return is no score.
    """
    if effect not in {"block", "pass"} or not isinstance(outcome, (int, float)):
        return None
    if effect == "block":
        return float(outcome) < 0.0
    return float(outcome) >= 0.0


def evidence_ok(memo: dict[str, Any] | None) -> bool:
    """A usable cite is a rationale plus one quote the writer already resolved."""
    if not isinstance(memo, dict):
        return False
    if not _clip(memo.get("rationale")):
        return False
    rows = memo.get("evidence")
    if not isinstance(rows, list):
        return False
    return any(
        isinstance(row, dict)
        and str(row.get("source") or "").strip()
        and row.get("quote_found") is True
        for row in rows
    )


def memo_cutoff(market: str, fill_session: date | None) -> datetime | None:
    if fill_session is None:
        return None
    try:
        return session_close(market, fill_session)
    except UnknownMarketClose:
        return None


def still_open_for_memo(
    market: str,
    signal_session: date | None,
    fill_session: date | None,
    now: datetime,
) -> bool:
    """True when a memo written now would still be in force at the fill close.

    The fill close is the book's memo cutoff. After it, a new memo cannot
    score that signal. A signal on the latest completed session, with no fill
    yet, is still open: the next session has not closed.
    """
    cutoff = memo_cutoff(market, fill_session)
    if cutoff is not None:
        return cutoff >= now
    if signal_session is None:
        return False
    completed = latest_completed_session(market, now)
    return completed is not None and signal_session == completed


def load_decision(repo_root: Path) -> dict[str, Any]:
    """Read the comparison decision. The live model is never taken from it."""
    path = Path(repo_root) / DECISION_REL
    payload: dict[str, Any] | None
    error = None
    try:
        loaded = read_json(path) if path.is_file() else None
    except (OSError, ValueError, TypeError) as exc:
        loaded = None
        error = str(exc)
    payload = loaded if isinstance(loaded, dict) else None
    outcome = str(payload.get("outcome") or "") if payload else ""
    if error:
        status = "unreadable"
    elif not outcome:
        status = "missing"
    elif outcome not in KEEP_OUTCOMES:
        status = "unrecognised"
    else:
        status = "recorded"
    return {
        "path": DECISION_REL.as_posix(),
        "outcome": outcome or None,
        "judge_trusted": payload.get("judge_trusted") if payload else None,
        "governing": payload.get("governing") if payload else None,
        "status": status,
        "error": error,
        "live_model": LIVE_MODEL,
        "live_model_changed": False,
        "switch_applied": False,
        "composer_stays": True,
        "feeds_strategy_book": False,
        "note": (
            "composer-2.5 stays on keep and inconclusive_keep. A switch in "
            "decision.json is not applied here. This shadow does not write the "
            "research store, the memo log, or the strategy book."
        ),
    }


def collect_signals(
    episodes: list[dict[str, Any]] | None,
    memo_rows: list[dict[str, Any]] | None,
    candidates: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Primary book entries, then entry candidates, then signal-day memo rows.

    The first row for a market, ticker and signal session wins, so a filled
    episode keeps its fill date.
    """
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(row: dict[str, Any]) -> None:
        key = _key(row)
        if not all(key) or key in seen:
            return
        seen.add(key)
        found.append(row)

    for episode in episodes or []:
        if not isinstance(episode, dict) or episode.get("column") != "primary":
            continue
        exited = bool(_iso(episode.get("exit_session")))
        realized = episode.get("fair_cost_return")
        add(
            {
                "market": str(episode.get("market") or ""),
                "ticker": str(episode.get("ticker") or ""),
                "signal_session": _iso(episode.get("signal_session")),
                "fill_session": _iso(episode.get("fill_session")) or None,
                "exit_session": _iso(episode.get("exit_session")) or None,
                "fair_cost_return": (
                    float(realized) if exited and isinstance(realized, (int, float)) else None
                ),
                "status": str(episode.get("status") or "filled"),
                "source": "primary_episode",
            }
        )
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        outcome = str(candidate.get("outcome") or "")
        if outcome not in ENTRY_OUTCOMES:
            continue
        add(
            {
                "market": str(candidate.get("market") or ""),
                "ticker": str(candidate.get("ticker") or ""),
                "signal_session": _iso(candidate.get("session")),
                "fill_session": _iso(candidate.get("fill_session")) or None,
                "exit_session": None,
                "fair_cost_return": None,
                "status": outcome,
                "source": "forward_status",
            }
        )
    for row in memo_rows or []:
        if not isinstance(row, dict):
            continue
        if row.get("kind") != "signal_day" or row.get("action") != "requested":
            continue
        add(
            {
                "market": str(row.get("market") or ""),
                "ticker": str(row.get("ticker") or ""),
                "signal_session": _iso(row.get("session")),
                "fill_session": None,
                "exit_session": None,
                "fair_cost_return": None,
                "status": "memo_logged",
                "source": "memo_log",
            }
        )
    return found


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _memo_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    """Latest requested shadow memo per signal and model."""
    found: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("action") != "requested":
            continue
        model = str(row.get("model") or "")
        if model not in MODELS:
            continue
        key = (
            str(row.get("market") or ""),
            str(row.get("ticker") or ""),
            _iso(row.get("session")),
            model,
        )
        if not all(key[:3]):
            continue
        found[key] = row
    return found


def score_model(
    memo: dict[str, Any] | None,
    *,
    cutoff: datetime | None,
    outcome: float | None,
    decision_recorded: bool,
) -> dict[str, Any]:
    """One model's score. Missing or stale evidence has no effect."""
    rationale = _clip(memo.get("rationale")) if isinstance(memo, dict) else ""
    evidence = list(memo.get("evidence") or []) if isinstance(memo, dict) else []
    card = {
        "influences_live": False,
        "observe_only": True,
        "reasons": [rationale] if rationale else [],
        "evidence": evidence,
    }
    authorized = authorize_live_llm_influence(card)
    scored: dict[str, Any] = {
        "effect": None,
        "hit": None,
        "score_status": "no_memo",
        "verdict": None,
        "finished_at": None,
        "live_influence_authorized": bool(authorized),
        "feeds_strategy_book": False,
    }
    if authorized or not decision_recorded:
        scored["score_status"] = "fail_closed" if authorized else "decision_evidence_missing"
        return scored
    if not isinstance(memo, dict):
        return scored
    verdict = memo.get("verdict")
    scored["verdict"] = verdict
    scored["finished_at"] = memo.get("finished_at")
    effect = entry_effect(str(verdict) if verdict else None)
    if effect is None:
        scored["score_status"] = "missing_verdict"
        return scored
    if not evidence_ok(memo):
        scored["score_status"] = "missing_evidence"
        return scored
    finished = _aware(memo.get("finished_at"))
    if finished is None:
        scored["score_status"] = "missing_finished_at"
        return scored
    if cutoff is None:
        scored["score_status"] = "no_fill_close"
        return scored
    if finished > cutoff:
        scored["score_status"] = "memo_after_fill_close"
        return scored
    age = _memo_age_days(finished, now=cutoff)
    if age is None or age > float(MEMO_MAX_AGE_DAYS):
        scored["score_status"] = "stale_memo"
        return scored
    scored["effect"] = effect
    if not isinstance(outcome, (int, float)):
        scored["score_status"] = "outcome_not_yet"
        return scored
    scored["hit"] = outcome_hit(effect, float(outcome))
    scored["score_status"] = "scored"
    return scored


def score_signal(
    signal: dict[str, Any],
    memos: dict[tuple[str, str, str, str], dict[str, Any]],
    series: tuple[list[date], list[float], list[float] | None, list[float] | None] | None,
    *,
    decision_recorded: bool,
) -> dict[str, Any]:
    """Attach early marks, the 63-session outcome, and both model scores."""
    market = str(signal.get("market") or "")
    ticker = str(signal.get("ticker") or "")
    signal_day = parse_day(signal.get("signal_session"))
    fill = parse_day(signal.get("fill_session"))
    exit_day = parse_day(signal.get("exit_session"))
    realized = signal.get("fair_cost_return")
    realized_value = float(realized) if isinstance(realized, (int, float)) else None
    if series is None or fill is None:
        marks = {
            f"s{sessions_after}": {
                "available": False,
                "reason": "no_chart" if series is None else "no_fill",
                "sessions_after_fill": sessions_after,
            }
            for sessions_after in EARLY_SESSIONS
        }
        outcome, basis = None, ("no_chart" if series is None else "no_fill")
    else:
        sessions, closes, highs, lows = series
        marks, outcome, basis = early_marks_for_series(
            sessions,
            closes,
            fill_session=fill,
            highs=highs,
            lows=lows,
            market=market,
            exit_session=exit_day,
            realized=realized_value,
        )
    cutoff = memo_cutoff(market, fill)
    models: dict[str, Any] = {}
    identity = (market, ticker, _iso(signal_day))
    for model in MODELS:
        models[model] = score_model(
            memos.get((*identity, model)),
            cutoff=cutoff,
            outcome=outcome,
            decision_recorded=decision_recorded,
        )
    s10 = marks.get("s10") if isinstance(marks.get("s10"), dict) else {}
    s20 = marks.get("s20") if isinstance(marks.get("s20"), dict) else {}
    return {
        "market": market,
        "ticker": ticker,
        "signal_session": _iso(signal_day),
        "fill_session": _iso(fill) or None,
        "exit_session": _iso(exit_day) or None,
        "status": signal.get("status"),
        "source": signal.get("source"),
        "outcome_63": outcome,
        "outcome_63_basis": basis,
        "outcome_sessions": OUTCOME_SESSIONS,
        "early_marks": marks,
        "early_indicator": {
            "source": EARLY_MARK_SOURCE,
            "s10_available": bool(s10.get("available")),
            "s20_available": bool(s20.get("available")),
            "s10_return": s10.get("return_from_fill"),
            "s20_return": s20.get("return_from_fill"),
        },
        "models": models,
        "feeds_strategy_book": False,
    }


def _hit_board(rows: list[dict[str, Any]]) -> dict[str, Any]:
    board: dict[str, Any] = {}
    for model in MODELS:
        scored_rows = [
            row["models"][model]
            for row in rows
            if isinstance(row.get("models"), dict)
            and isinstance(row["models"].get(model), dict)
            and row["models"][model].get("score_status") == "scored"
        ]
        hits = sum(1 for row in scored_rows if row.get("hit") is True)
        count = len(scored_rows)
        with_s10 = sum(
            1
            for row in rows
            if isinstance(row.get("models"), dict)
            and isinstance(row["models"].get(model), dict)
            and row["models"][model].get("score_status") == "scored"
            and isinstance(row.get("early_indicator"), dict)
            and row["early_indicator"].get("s10_available")
        )
        board[model] = {
            "scored": count,
            "hits": hits,
            "misses": count - hits,
            "hit_rate": (hits / count) if count >= MIN_SCORED else None,
            "status": "ok" if count >= MIN_SCORED else "insufficient_data",
            "scored_with_s10": with_s10,
        }
    return board


def _reason_tally(rows: list[dict[str, Any]]) -> dict[str, int]:
    found: Counter[str] = Counter()
    for row in rows:
        models = row.get("models") if isinstance(row.get("models"), dict) else {}
        for model in MODELS:
            cell = models.get(model) if isinstance(models.get(model), dict) else {}
            found[str(cell.get("score_status") or "no_memo")] += 1
    return dict(sorted(found.items()))


def challenger_configured() -> str:
    from value_investor.memo_model_comparison import CHALLENGER_MODEL as configured

    return str(configured)


def model_cost(model: str) -> float:
    if model == INCUMBENT_MODEL:
        return INCUMBENT_MEMO_USD
    from value_investor.memo_model_comparison import estimated_memo_usd

    return float(estimated_memo_usd(model))


def _week_key(moment: datetime) -> str:
    year, week, _day = moment.isocalendar()
    return f"{year}-W{week:02d}"


def _spent_this_week(rows: list[dict[str, Any]], moment: datetime) -> float:
    week = _week_key(moment)
    total = 0.0
    for row in rows:
        if row.get("action") != "requested":
            continue
        stamp = _aware(row.get("requested_at"))
        if stamp is None or _week_key(stamp) != week:
            continue
        amount = row.get("estimated_spend_usd")
        if isinstance(amount, (int, float)):
            total += float(amount)
    return round(total, 2)


def _has_memo(rows: list[dict[str, Any]], key: tuple[str, str, str, str]) -> bool:
    market, ticker, session, model = key
    for row in rows:
        if row.get("action") != "requested":
            continue
        if (
            str(row.get("market") or "") == market
            and str(row.get("ticker") or "") == ticker
            and _iso(row.get("session")) == session
            and str(row.get("model") or "") == model
        ):
            return True
    return False


def _screen_row(repo_root: Path, market: str, ticker: str, session: date) -> dict[str, Any]:
    paths = repo_paths(repo_root)
    _path, payload, _day = newest_screen_run(history_dir_for(paths, market), session)
    return dict(screen_rows(payload).get(ticker) or {})


def _quotes(raw: str, sources_dir: Path, as_of: date) -> list[dict[str, Any]]:
    if not raw.strip() or not sources_dir.is_dir():
        return []
    from value_investor.memo_model_comparison import score_memo

    scored = score_memo(raw, sources_dir=sources_dir, as_of=as_of)
    found: list[dict[str, Any]] = []
    for item in scored.get("evidence") or []:
        if not isinstance(item, dict) or not item.get("parsed"):
            continue
        found.append(
            {
                "source": item.get("path"),
                "kind": "memo_quote",
                "detail": "quote_found" if item.get("quote_found") else "quote_missing",
                "quote_found": bool(item.get("quote_found")),
            }
        )
    return found


def default_shadow_runner(
    *,
    market: str,
    ticker: str,
    model: str,
    sources_dir: Path,
    screen_row: dict[str, Any],
    as_of_date: str,
    repo_root: Path,
) -> dict[str, Any]:
    """One shadow memo in a temp copy of sources. Does not touch the research store."""
    if model not in MODELS:
        raise RuntimeError(f"refusing model {model}")
    api_key = (
        os.environ.get("CURSOR_API_KEY_V2", "").strip()
        or os.environ.get("CURSOR_API_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError("CURSOR_API_KEY missing")
    from value_investor.research.agent import run_initial_research_agent
    from value_investor.summary import CompanyReport

    work = Path(tempfile.mkdtemp(prefix="l703-shadow-"))
    try:
        dest = work / "sources"
        if sources_dir.is_dir():
            shutil.copytree(sources_dir, dest)
        else:
            raise RuntimeError("sources missing")
        report = CompanyReport.from_dict(
            {
                **screen_row,
                "ticker": ticker,
                "name": screen_row.get("name") or ticker,
                "signal": screen_row.get("signal") or "buy",
            }
        )
        capture: dict[str, Any] = {}
        doc, _agent_id = run_initial_research_agent(
            report=report,
            sources_dir=dest,
            api_key=api_key,
            model=model,
            cwd=str(work),
            job="l703_memo_model_shadow",
            pool="weekly_ops",
            as_of_date=as_of_date,
            prompt_appendix=APPENDIX,
            capture=capture,
        )
        raw = str(capture.get("raw_text") or "")
        rationale = _clip(getattr(doc, "research_rationale", None))
        return {
            "verdict": getattr(doc, "research_verdict", None),
            "rationale": rationale,
            "evidence": _quotes(raw, dest, date.fromisoformat(as_of_date)),
            "finished_at": datetime.now(UTC).isoformat(),
            "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "written_paths": [],
            "market": market,
            "repo_root": str(repo_root),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _live_research_path(path: str) -> bool:
    text = path.replace("\\", "/")
    return "/research/" in text and "memo_model_shadow" not in text


def request_shadow_memos(
    signals: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    repo_root: Path,
    now: datetime,
    apply: bool,
    decision_recorded: bool,
    configured_challenger: str,
    runner: Any = None,
    list_models: Any = None,
    budget_status: Any = None,
    record_spend: Any = None,
) -> dict[str, Any]:
    """Write missing shadow memos for signals still inside the fill-close window.

    Refuses a live research path. Does not call a model when the decision
    evidence is missing, the runtime model list fails, or the caps are full.
    """
    moment = now if now.tzinfo else now.replace(tzinfo=UTC)
    spent = _spent_this_week(existing, moment)
    rows: list[dict[str, Any]] = []
    call = runner
    if not decision_recorded:
        return {
            "requested": 0,
            "estimated_spend_usd": 0.0,
            "spent_before_usd": spent,
            "skipped_reason": "decision_evidence_missing",
            "names": rows,
            "influences_live": False,
        }
    if configured_challenger != CHALLENGER_MODEL:
        challenger_block = "challenger_mismatch"
    else:
        challenger_block = None
    eligible = []
    for signal in signals:
        signal_day = parse_day(signal.get("signal_session"))
        fill = parse_day(signal.get("fill_session"))
        if not still_open_for_memo(str(signal.get("market") or ""), signal_day, fill, moment):
            continue
        missing = [
            model
            for model in MODELS
            if not _has_memo(
                existing,
                (
                    str(signal.get("market") or ""),
                    str(signal.get("ticker") or ""),
                    _iso(signal_day),
                    model,
                ),
            )
        ]
        if missing:
            eligible.append((signal, missing))
    eligible.sort(
        key=lambda item: (_iso(item[0].get("signal_session")), str(item[0].get("ticker") or ""))
    )
    eligible = list(reversed(eligible))[:MAX_SIGNALS_PER_RUN]
    listed: list[str] | None = None
    list_error = None
    if apply and eligible:
        try:
            listed = list(list_models() if list_models is not None else _runtime_models())
        except Exception as exc:  # noqa: BLE001 — fail closed, no model call
            list_error = str(exc)
            listed = []
    reserved = 0.0
    spent_now = 0.0
    log_path = repo_paths(repo_root).data / MEMO_LOG_NAME
    for signal, missing in eligible:
        for model in missing:
            cost = model_cost(model)
            record: dict[str, Any] = {
                "market": signal.get("market"),
                "ticker": signal.get("ticker"),
                "session": _iso(signal.get("signal_session")),
                "model": model,
                "role": "incumbent" if model == INCUMBENT_MODEL else "challenger",
                "action": "planned" if not apply else "skipped",
                "skip_reason": None,
                "estimated_spend_usd": 0.0,
                "requested_at": moment.isoformat(),
                "verdict": None,
                "rationale": None,
                "evidence": [],
                "finished_at": None,
                "influences_live": False,
                "live_research_written": False,
                "feeds_strategy_book": False,
            }
            if model == CHALLENGER_MODEL and challenger_block:
                record["skip_reason"] = challenger_block
            elif list_error:
                record["skip_reason"] = f"model_check_failed: {list_error}"
            elif listed is not None and model not in listed:
                record["skip_reason"] = "model_not_listed"
            elif spent + reserved + cost > WEEKLY_CAP_USD:
                record["skip_reason"] = "weekly_cap"
            elif apply:
                status = budget_status() if budget_status is not None else _budget()
                budget = status if isinstance(status, dict) else {}
                if not _headroom(budget, reserved=reserved, cost=cost):
                    record["skip_reason"] = "memo_not_ready_budget"
                else:
                    try:
                        outcome = (call or default_shadow_runner)(
                            market=str(signal.get("market") or ""),
                            ticker=str(signal.get("ticker") or ""),
                            model=model,
                            sources_dir=_sources(
                                repo_root,
                                str(signal.get("market") or ""),
                                str(signal.get("ticker") or ""),
                            ),
                            screen_row=_screen_row(
                                repo_root,
                                str(signal.get("market") or ""),
                                str(signal.get("ticker") or ""),
                                parse_day(signal.get("signal_session")) or moment.date(),
                            ),
                            as_of_date=_iso(signal.get("signal_session")),
                            repo_root=repo_root,
                        )
                    except Exception as exc:  # noqa: BLE001 — one name must not stop the others
                        record["skip_reason"] = f"runner_error: {exc}"
                    else:
                        paths = [str(item) for item in (outcome or {}).get("written_paths") or []]
                        if any(_live_research_path(item) for item in paths):
                            record["skip_reason"] = "rejected_live_write"
                            record["live_research_written"] = False
                        elif isinstance(outcome, dict):
                            record["action"] = "requested"
                            record["verdict"] = outcome.get("verdict")
                            record["rationale"] = _clip(outcome.get("rationale"))
                            record["evidence"] = list(outcome.get("evidence") or [])
                            record["finished_at"] = outcome.get("finished_at")
                            record["raw_sha256"] = outcome.get("raw_sha256")
                            record["estimated_spend_usd"] = cost
                            reserved += cost
                            spent_now += cost
                            if record_spend is not None:
                                record_spend(cost)
                            else:
                                _record(cost)
            if record["skip_reason"]:
                record["action"] = "skipped"
            rows.append(record)
            if apply:
                _append_jsonl(log_path, record)
    return {
        "requested": sum(1 for row in rows if row.get("action") == "requested"),
        "estimated_spend_usd": round(spent_now, 2),
        "spent_before_usd": spent,
        "weekly_cap_usd": WEEKLY_CAP_USD,
        "max_signals_per_run": MAX_SIGNALS_PER_RUN,
        "skipped_reason": None,
        "names": rows,
        "influences_live": False,
        "feeds_strategy_book": False,
    }


def _sources(repo_root: Path, market: str, ticker: str) -> Path:
    return research_root_for(repo_paths(repo_root), market) / ticker / "sources"


def _runtime_models() -> list[str]:
    from value_investor.memo_model_comparison import runtime_models

    api_key = (
        os.environ.get("CURSOR_API_KEY_V2", "").strip()
        or os.environ.get("CURSOR_API_KEY", "").strip()
    )
    return runtime_models(api_key)


def _budget() -> dict[str, Any]:
    from value_investor.agent_model_policy import weekly_ops_budget_status

    return weekly_ops_budget_status(estimated_memo_usd=INCUMBENT_MEMO_USD)


def _record(amount: float) -> None:
    from value_investor.agent_model_policy import SPEND_POOL_WEEKLY_OPS, record_estimated_spend

    record_estimated_spend(amount, pool=SPEND_POOL_WEEKLY_OPS)


def _headroom(budget: dict[str, Any], *, reserved: float, cost: float) -> bool:
    from value_investor.research.weekday_rememo import DEFAULT_MIN_HEADROOM_USD

    if budget.get("constraining"):
        return False
    remaining = float(budget.get("remaining_weekly_ops_usd") or 0.0) - reserved
    return remaining >= (cost + float(DEFAULT_MIN_HEADROOM_USD))


def _load_book_inputs(
    root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    paths = repo_paths(root)
    observe = _read_object(paths.observe)
    episodes = observe.get("episodes") if isinstance(observe.get("episodes"), list) else []
    forward = _read_object(paths.data / "strategy_book_forward_status.json")
    candidates = forward.get("candidates") if isinstance(forward.get("candidates"), list) else []
    return (
        [row for row in episodes if isinstance(row, dict)],
        _read_jsonl(paths.memo_log),
        [row for row in candidates if isinstance(row, dict)],
    )


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def run_shadow(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    apply: bool = False,
    request_memos: bool = False,
    signals: list[dict[str, Any]] | None = None,
    series_for: Any = None,
    memo_rows: list[dict[str, Any]] | None = None,
    decision: dict[str, Any] | None = None,
    runner: Any = None,
    list_models: Any = None,
    budget_status: Any = None,
    record_spend: Any = None,
) -> dict[str, Any]:
    """Score stored shadow memos. Optionally request missing ones. Write only this store."""
    root = Path(repo_root) if repo_root is not None else Path()
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    paths = repo_paths(root)
    decision_row = decision if decision is not None else load_decision(root)
    recorded = decision_row.get("status") == "recorded"
    if signals is None:
        episodes, book_memos, candidates = _load_book_inputs(root)
        signals = collect_signals(episodes, book_memos, candidates)
    log_path = paths.data / MEMO_LOG_NAME
    existing = list(memo_rows) if memo_rows is not None else _read_jsonl(log_path)
    memo_run = {
        "requested": 0,
        "estimated_spend_usd": 0.0,
        "names": [],
        "influences_live": False,
    }
    if request_memos:
        memo_run = request_shadow_memos(
            signals,
            existing,
            repo_root=root,
            now=moment,
            apply=apply,
            decision_recorded=recorded,
            configured_challenger=challenger_configured(),
            runner=runner,
            list_models=list_models,
            budget_status=budget_status,
            record_spend=record_spend,
        )
        if apply:
            existing = _read_jsonl(log_path)
    index = _memo_index(existing)
    if series_for is None:

        def series_for(market: str, ticker: str):
            return _chart_series(paths, market, ticker, moment)
    scored = [
        score_signal(
            signal,
            index,
            series_for(str(signal.get("market") or ""), str(signal.get("ticker") or "")),
            decision_recorded=recorded,
        )
        for signal in signals
    ]
    early_with_s10 = sum(
        1
        for row in scored
        if isinstance(row.get("early_indicator"), dict)
        and row["early_indicator"].get("s10_available")
    )
    with_outcome = sum(1 for row in scored if isinstance(row.get("outcome_63"), (int, float)))
    store = {
        "instrument": INSTRUMENT,
        "rule_id": RULE_ID,
        "schema_version": 1,
        "registration_id": "owner-strategy-book-v0",
        "influences_live": False,
        "feeds_strategy_book": False,
        "rememo_live": False,
        "generated_at": moment.isoformat(),
        "scoring_date": moment.date().isoformat(),
        "models": {"incumbent": INCUMBENT_MODEL, "challenger": CHALLENGER_MODEL},
        "live_model": LIVE_MODEL,
        "live_model_changed": False,
        "decision": decision_row,
        "rule": {
            "id": RULE_ID,
            "block_hit": "block and 63-session fair-cost return < 0",
            "pass_hit": "pass and 63-session fair-cost return >= 0",
            "min_scored": MIN_SCORED,
            "outcome": (
                "fair-cost return at 63 sessions after the fill, or the realized "
                "exit if it came first"
            ),
            "early_marks": EARLY_MARK_SOURCE,
            "fail_closed": "missing or stale evidence is no score and no effect",
        },
        "signals": scored,
        "by_model": _hit_board(scored),
        "score_status_counts": _reason_tally(scored),
        "early_indicator": {
            "source": EARLY_MARK_SOURCE,
            "signals_with_s10": early_with_s10,
            "signals_with_outcome_63": with_outcome,
            "observe_store": OBSERVE_STORE_NAME,
        },
        "memo_run": {
            "requested": memo_run.get("requested"),
            "estimated_spend_usd": memo_run.get("estimated_spend_usd"),
            "spent_before_usd": memo_run.get("spent_before_usd"),
            "weekly_cap_usd": WEEKLY_CAP_USD,
            "skipped_reason": memo_run.get("skipped_reason"),
            "names": memo_run.get("names") or [],
        },
        "observe_memo_spend_usd": memo_run.get("estimated_spend_usd") or 0.0,
        "errors": [],
    }
    if apply:
        write_json(paths.data / STORE_NAME, store, compact=False)
    summary = public_summary(store)
    summary["wrote"] = bool(apply)
    summary["dry_run"] = not apply
    return summary


def public_summary(store: dict[str, Any]) -> dict[str, Any]:
    """Counts for stdout and the ops finding. No per-name bodies."""
    decision = store.get("decision") if isinstance(store.get("decision"), dict) else {}
    early = store.get("early_indicator") if isinstance(store.get("early_indicator"), dict) else {}
    memo_run = store.get("memo_run") if isinstance(store.get("memo_run"), dict) else {}
    return {
        "instrument": store.get("instrument"),
        "influences_live": False,
        "feeds_strategy_book": False,
        "live_model": LIVE_MODEL,
        "live_model_changed": False,
        "decision_outcome": decision.get("outcome"),
        "decision_status": decision.get("status"),
        "generated_at": store.get("generated_at"),
        "signals": len(store.get("signals") or []),
        "by_model": store.get("by_model") or {},
        "score_status_counts": store.get("score_status_counts") or {},
        "early_indicator": {
            "signals_with_s10": early.get("signals_with_s10"),
            "signals_with_outcome_63": early.get("signals_with_outcome_63"),
        },
        "memo_requests": int(memo_run.get("requested") or 0),
        "observe_memo_spend_usd": store.get("observe_memo_spend_usd") or 0.0,
        "errors": list(store.get("errors") or []),
    }


def _finding(severity: str, title: str, summary: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": "research",
        "title": title,
        "summary": summary,
        "auto_fixable": False,
    }


def _model_text(board: dict[str, Any]) -> str:
    parts: list[str] = []
    for model in MODELS:
        cell = board.get(model) if isinstance(board.get(model), dict) else {}
        rate = cell.get("hit_rate")
        rate_text = "n/a" if rate is None else f"{float(rate):.2f}"
        parts.append(
            f"{model} scored {int(cell.get('scored') or 0)} "
            f"hits {int(cell.get('hits') or 0)} hit_rate {rate_text}"
        )
    return "; ".join(parts)


def findings_from_store(
    store: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    unreadable: str | None = None,
) -> list[dict[str, Any]]:
    """Read-only findings. Warns when the store or the decision evidence fails."""
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
                "docs/data/strategy_book_memo_model_shadow.json is missing. "
                "The weekday forward workflow writes it. No rememo and no model switch.",
            )
        ]
    slot = latest_forward_slot(moment)
    stamp = _aware(store.get("generated_at"))
    if stamp is None or stamp < slot:
        return [
            _finding(
                "warn",
                TITLE_STALE,
                f"Shadow store is older than the {slot.isoformat()} slot "
                f"(generated_at {store.get('generated_at')}). No rememo and no model switch.",
            )
        ]
    summary = public_summary(store)
    decision = store.get("decision") if isinstance(store.get("decision"), dict) else {}
    early = summary.get("early_indicator")
    if not isinstance(early, dict):
        early = {}
    text = (
        f"Signals {summary.get('signals')}. {_model_text(summary.get('by_model') or {})}. "
        f"Early marks with s10 {early.get('signals_with_s10')}; "
        f"63-session outcomes {early.get('signals_with_outcome_63')}. "
        f"Decision {summary.get('decision_outcome') or 'missing'} "
        f"({summary.get('decision_status')}). Live model {LIVE_MODEL} unchanged. "
        "Observe-only. It does not feed the book or rememo live names."
    )
    rows = [_finding("info", TITLE_REFRESHED, text)]
    claimed = (
        decision.get("status") != "recorded"
        or decision.get("live_model_changed") is True
        or store.get("live_model_changed") is True
        or store.get("influences_live") is True
        or store.get("feeds_strategy_book") is True
    )
    if claimed:
        rows.append(
            _finding(
                "warn",
                TITLE_FAIL_CLOSED,
                "Decision evidence is missing or a live-model change was requested. "
                "Scores have no effect. composer-2.5 stays. No rememo.",
            )
        )
    return rows


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
        description=(
            "Outcome-scored memo model shadow (observe-only; does not write the "
            "book, rememo live names, or switch the live model)"
        )
    )
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument("--apply", action="store_true", help="Write the shadow store")
    parser.add_argument(
        "--request-memos",
        action="store_true",
        help=(
            "Ask both models for shadow memos on signals still inside the fill-close "
            f"window, up to {MAX_SIGNALS_PER_RUN} signals and ${WEEKLY_CAP_USD:.0f} this "
            "ISO week. Does not write the research store."
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
