"""Daily forward walk for the strategy book (registration sections 9(b), 11, 12).

Calls ``walk_book`` and ``build_boards`` with ``options_for("forward")`` from
the seal's start date. August–October stays in the archive. The observe store
and the gate log are written only when the seal is signed and ``forward_live``
is true. Until then the job dry-runs and keeps a counts-only status.

The scored snapshot is rebuilt from the start date each run. ``signal_seen_at``
for an older session is the gate-log time, or ``now`` when that session was
never logged, so a rewalk cannot fill it quietly.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from value_investor.price_charts import chart_last_close_date
from value_investor.storage import read_json, write_json
from value_investor.strategy_book_memo_job import MEMO_NOT_READY_MAX_SHARE, TITLE_BEHIND
from value_investor.strategy_book_observe import (
    F9Fact,
    MemoFact,
    NameSpec,
    PriceBook,
    ScreenFact,
    _base_eligible,
    _downloads_of,
    _Name,
    options_for,
    series_refusal,
    sha256_bytes,
    walk_book,
)
from value_investor.strategy_book_prices import latest_completed_session
from value_investor.strategy_book_replay import _chart_file, _gate_for, _read_chart
from value_investor.strategy_book_rules import (
    CLOSES_STATE_NAME,
    COLUMN_PRIMARY,
    FORWARD_STATUS_NAME,
    GATE_LOG_NAME,
    INFLUENCES_LIVE,
    LATE_SIGNAL_MAX_SHARE,
    OBSERVE_STORE_NAME,
    REGISTRATION_ID,
    T212_CATALOGUE_MAX_AGE_DAYS,
    UnknownMarketClose,
    forward_live,
    forward_start_date,
    session_close,
)
from value_investor.strategy_book_signals import (
    BUY_SIGNALS,
    _binds,
    _filename_day,
    _run_calendar_day,
    history_dir_for,
    newest_screen_run,
    repo_paths,
    research_root_for,
    screen_rows,
    universe_markets,
)

# Not a registration threshold. Bounds which screen files this job opens.
SCREEN_LOOKBACK_DAYS = 14
SAMPLE_TICKERS = 8
FORWARD_SLOT_UTC = time(21, 30, tzinfo=UTC)

SIGNAL_KINDS = frozenset(
    {
        "filled",
        "pending_fill",
        "memo_not_ready",
        "memo_blocked",
        "late_signal",
        "gap_drop",
        "already_open_skip",
        "cooldown_skip",
    }
)
_ENTRY_KINDS = frozenset({"filled", "pending_fill"})
_RETURN_TOKENS = ("fair_cost", "median", "episodes", "gross_return", "capital_return")

TITLE_REFRESHED = "Strategy book observe refreshed"
TITLE_FAILED = "Strategy book observe failed"
TITLE_INTERIM = "Strategy book 26-week interim read published"
TITLE_THICKNESS = "Strategy book thickness gate ready for review"
TITLE_CLOSES_STALE = "Strategy book closes stale"
TITLE_LATE = "Strategy book late signals"
TITLE_T212 = "Strategy book Trading 212 catalogue stale"
TITLE_PENDING = "Strategy book forward go-live pending"

BlobReader = Callable[[str, str], bytes | None]


def latest_forward_slot(now: datetime) -> datetime:
    """Most recent 21:30 UTC weekday at or before ``now``."""
    moment = _aware(now)
    day = moment.date()
    for offset in range(10):
        candidate = day - timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue
        slot = datetime.combine(candidate, FORWARD_SLOT_UTC)
        if slot <= moment:
            return slot
    return datetime.combine(day, FORWARD_SLOT_UTC)


def counts_view(summary: dict[str, Any]) -> dict[str, Any]:
    """Counts for stdout and the status file. No returns and no episodes."""
    view = {
        "registration_id": summary.get("registration_id", REGISTRATION_ID),
        "influences_live": INFLUENCES_LIVE,
        "generated_at": summary.get("generated_at"),
        "start_date": summary.get("start_date"),
        "scoring_date": summary.get("scoring_date"),
        "forward_live": bool(summary.get("forward_live")),
        "dry_run": bool(summary.get("dry_run")),
        "signals": int(summary.get("signals") or 0),
        "entries_that_would_open": int(summary.get("entries_that_would_open") or 0),
        "filled": int(summary.get("filled") or 0),
        "pending_fill": int(summary.get("pending_fill") or 0),
        "late_signal": int(summary.get("late_signal") or 0),
        "memo_not_ready": int(summary.get("memo_not_ready") or 0),
        "memo_blocked": int(summary.get("memo_blocked") or 0),
        "blocked_reasons": dict(summary.get("blocked_reasons") or {}),
        "sample_tickers": list(summary.get("sample_tickers") or []),
        "phase_span_sessions": int(summary.get("phase_span_sessions") or 0),
        "mature_count": int(summary.get("mature_count") or 0),
        "freshness": summary.get("freshness") or {},
        "errors": list(summary.get("errors") or []),
        "provenance_mismatches": int(summary.get("provenance_mismatches") or 0),
        "provenance_pending": int(summary.get("provenance_pending") or 0),
        "interim_announce": bool(summary.get("interim_announce")),
        "interim_announced": bool(summary.get("interim_announced")),
        "thickness_ready": bool(summary.get("thickness_ready")),
        "disposition": bool(summary.get("disposition")),
        "wrote_observe": bool(summary.get("wrote_observe")),
        "wrote_gate_log": bool(summary.get("wrote_gate_log")),
        "wrote_status": bool(summary.get("wrote_status")),
    }
    _reject_scores(view)
    return view


def run_forward_job(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    apply: bool = False,
    persist: bool | None = None,
    data_commit: str | None = None,
    blob_reader: BlobReader | None = None,
) -> dict[str, Any]:
    """Walk from the seal start date. Write scores only when the book is live.

    ``persist`` defaults to ``apply``. A live apply writes the observe store
    and appends the gate log. Any persisted run writes the counts-only status.
    """
    moment = _aware(now or datetime.now(UTC))
    paths = repo_paths(repo_root)
    decision = moment.date()
    start = forward_start_date(paths.registration, decision=decision)
    live = forward_live(paths.registration)
    commit = data_commit if data_commit is not None else _head_commit(paths.root)
    should_persist = apply if persist is None else persist
    options = options_for("forward")
    options.entry_not_before = start
    options.scoring_date = decision
    options.data_commit = commit

    previous = _read_obj(paths.data / FORWARD_STATUS_NAME)
    prior_observe = _read_obj(paths.observe)
    log_rows = _read_log(paths.data / GATE_LOG_NAME)
    loaded = _load_forward_specs(
        paths,
        start=start,
        now=moment,
        commit=commit,
        log_rows=log_rows,
    )
    result = walk_book(loaded["specs"], options=options)
    tallied = _tally(result.get("events") or [], loaded["specs"], options, loaded["blocked"])
    health = _health(result.get("boards") or {})
    disposition = bool(prior_observe.get("disposition")) if prior_observe else False
    announced = bool(previous.get("interim_announced")) if previous else False
    interim_announce = bool(live and health["interim_published"] and not announced)
    if interim_announce:
        announced = True

    summary: dict[str, Any] = {
        "registration_id": REGISTRATION_ID,
        "influences_live": INFLUENCES_LIVE,
        "generated_at": moment.isoformat(),
        "start_date": start.isoformat(),
        "scoring_date": str(result.get("scoring_date") or decision.isoformat()),
        "forward_live": live,
        "dry_run": (not live) or (not apply),
        "data_commit": commit,
        "errors": loaded["errors"],
        "sample_tickers": tallied["sample_tickers"],
        "phase_span_sessions": health["phase_span_sessions"],
        "mature_count": health["mature_count"],
        "thickness_ready": bool(live and health["thickness_ready"]),
        "disposition": disposition,
        "interim_announce": interim_announce,
        "interim_announced": announced,
        "freshness": {
            "generated_at": moment.isoformat(),
            "scoring_date": str(result.get("scoring_date") or decision.isoformat()),
            "state": "live" if live else "dry_run",
        },
        **{
            key: tallied[key]
            for key in (
                "signals",
                "entries_that_would_open",
                "filled",
                "pending_fill",
                "late_signal",
                "memo_not_ready",
                "memo_blocked",
                "blocked_reasons",
            )
        },
    }

    wrote_observe = False
    wrote_log = False
    if live and apply and should_persist:
        payload = dict(result)
        payload["registration_id"] = REGISTRATION_ID
        payload["influences_live"] = INFLUENCES_LIVE
        payload["forward_live"] = True
        payload["start_date"] = start.isoformat()
        payload["generated_at"] = moment.isoformat()
        payload["data_commit"] = commit
        if prior_observe.get("disposition") is not None:
            payload["disposition"] = prior_observe.get("disposition")
        if prior_observe.get("change_markers") is not None:
            payload["change_markers"] = prior_observe.get("change_markers")
        dest = paths.data / OBSERVE_STORE_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_json(dest, payload, compact=False)
        wrote_observe = True
        wrote_log = _append_gate_log(
            paths.data / GATE_LOG_NAME,
            session_rows=loaded["session_rows"],
            episodes=list(result.get("episodes") or []),
            scored=loaded["scored"],
            already=log_rows,
            observed_at=moment,
            commit=commit,
        )
        log_rows = _read_log(paths.data / GATE_LOG_NAME)

    mismatches, pending = _provenance(
        log_rows,
        reader=blob_reader or (lambda commit_id, rel: git_blob_at(paths.root, commit_id, rel)),
    )
    summary["provenance_mismatches"] = len(mismatches)
    summary["provenance_pending"] = pending
    summary["wrote_observe"] = wrote_observe
    summary["wrote_gate_log"] = wrote_log
    summary["gate_logged_through"] = _logged_through(log_rows)
    summary["wrote_status"] = False
    public = counts_view(summary)
    if should_persist:
        stored = {**public, "gate_logged_through": summary["gate_logged_through"]}
        _reject_scores(stored)
        dest = paths.data / FORWARD_STATUS_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_json(dest, stored, compact=False)
        public["wrote_status"] = True
    return public


def git_blob_at(repo: Path, commit: str, relpath: str) -> bytes | None:
    """Bytes of ``relpath`` at ``commit``, or None when that commit lacks it.

    A missing blob is ``pending_commit`` (the starting commit does not hold
    files this run wrote). It is not a mismatch. This does not search for the
    later commit that first contains the log line.
    """
    if not commit or not relpath:
        return None
    spec = f"{commit}:{relpath}"
    try:
        probe = subprocess.run(
            ["git", "cat-file", "-e", spec],
            cwd=repo,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if probe.returncode != 0:
            return None
        show = subprocess.run(
            ["git", "show", spec],
            cwd=repo,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if show.returncode != 0:
        return None
    return show.stdout


def findings_from_state(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Ops findings from persisted files. Does not walk and does not download."""
    moment = _aware(now or datetime.now(UTC))
    paths = repo_paths(repo_root)
    status = _read_obj(paths.data / FORWARD_STATUS_NAME)
    closes = _read_obj(paths.data / CLOSES_STATE_NAME)
    live = forward_live(paths.registration)
    observe_exists = paths.observe.is_file()
    catalogue = _catalogue(paths.library, moment)
    findings: list[dict[str, Any]] = []
    slot = latest_forward_slot(moment)
    fresh = _status_fresh(status, slot)

    if not live:
        findings.append(
            _finding(
                "info",
                TITLE_PENDING,
                "forward_live is false. The forward job dry-runs and writes no scored "
                "store. Phase 1 governs this flag. See docs/ops/strategy-book-observe.md.",
            )
        )
    if status is None or not fresh:
        seen = None if status is None else status.get("generated_at")
        findings.append(
            _finding(
                "warn",
                TITLE_FAILED,
                f"Missed the {slot.isoformat()} slot (last status {seen}). "
                "The weekday job is strategy-book-forward.yml at 21:30 UTC.",
            )
        )
    else:
        reasons = (
            status.get("blocked_reasons") if isinstance(status.get("blocked_reasons"), dict) else {}
        )
        reason_text = (
            ", ".join(f"{key} {value}" for key, value in list(reasons.items())[:6]) or "none"
        )
        names = (
            ", ".join(str(item) for item in (status.get("sample_tickers") or [])[:SAMPLE_TICKERS])
            or "none"
        )
        findings.append(
            _finding(
                "info",
                TITLE_REFRESHED,
                f"Signals {status.get('signals', 0)}, entries that would open "
                f"{status.get('entries_that_would_open', 0)}. Blocked: {reason_text}. "
                f"First tickers: {names}.",
            )
        )
        errors = status.get("errors") if isinstance(status.get("errors"), list) else []
        mismatches = int(status.get("provenance_mismatches") or 0)
        if errors or mismatches:
            findings.append(
                _finding(
                    "warn",
                    TITLE_FAILED,
                    f"Errors {len(errors)}; provenance mismatches {mismatches}. "
                    "The gate log is not rewritten.",
                )
            )
        if status.get("interim_announce"):
            findings.append(
                _finding(
                    "info",
                    TITLE_INTERIM,
                    "The 26-week interim read is published on the forward book.",
                )
            )
        if (
            live
            and observe_exists
            and status.get("thickness_ready")
            and not status.get("disposition")
        ):
            findings.append(
                _finding(
                    "info",
                    TITLE_THICKNESS,
                    "The thickness gate is ready for review. No disposition is stored.",
                )
            )
        _append_memo_share(findings, status)
        _append_late(findings, status)

    for row in _stale_closes(closes):
        names = ", ".join(str(item) for item in row.get("sample_tickers") or []) or "none"
        findings.append(
            _finding(
                "warn",
                TITLE_CLOSES_STALE,
                f"{row.get('market')}: {row.get('behind')} of {row.get('buy_tier')} "
                f"buy-tier names are more than one session behind. First tickers: {names}. "
                "No rememo or ingest.",
            )
        )
    if catalogue.get("status") in {"missing", "stale"}:
        findings.append(
            _finding(
                "warn",
                TITLE_T212,
                f"Catalogue {catalogue.get('status')} at {catalogue.get('age_days')} days "
                f"(limit {T212_CATALOGUE_MAX_AGE_DAYS}). "
                "Distinct from the 14-day Trading 212 catalogue check.",
            )
        )
    return findings


def _append_memo_share(findings: list[dict[str, Any]], status: dict[str, Any]) -> None:
    ready = int(status.get("memo_not_ready") or 0)
    blocked = int(status.get("memo_blocked") or 0)
    filled = int(status.get("filled") or 0)
    denominator = filled + ready + blocked
    if denominator <= 0:
        return
    if ready / denominator > MEMO_NOT_READY_MAX_SHARE:
        findings.append(
            _finding(
                "warn",
                TITLE_BEHIND,
                f"memo_not_ready is {ready} of {denominator} memo-checked forward signals "
                f"(over {MEMO_NOT_READY_MAX_SHARE:.0%}). This is the walk share. "
                "A missed memo job is a separate finding.",
            )
        )


def _append_late(findings: list[dict[str, Any]], status: dict[str, Any]) -> None:
    signals = int(status.get("signals") or 0)
    late = int(status.get("late_signal") or 0)
    if signals <= 0:
        return
    if late / signals > LATE_SIGNAL_MAX_SHARE:
        findings.append(
            _finding(
                "warn",
                TITLE_LATE,
                f"late_signal is {late} of {signals} signals (over {LATE_SIGNAL_MAX_SHARE:.0%}).",
            )
        )


def _stale_closes(state: dict[str, Any]) -> list[dict[str, Any]]:
    from value_investor.strategy_book_prices import stale_markets

    return stale_markets(state)


def _catalogue(library: Path, now: datetime) -> dict[str, Any]:
    from value_investor.t212_coverage import assess_t212_catalogue_freshness

    return assess_t212_catalogue_freshness(
        library,
        now=now,
        stale_after_days=T212_CATALOGUE_MAX_AGE_DAYS,
    )


def _finding(severity: str, title: str, summary: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": "research",
        "title": title,
        "summary": summary,
        "auto_fixable": False,
    }


def _status_fresh(status: dict[str, Any], slot: datetime) -> bool:
    if not status:
        return False
    raw = status.get("generated_at")
    if not raw:
        return False
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp >= slot


def _load_forward_specs(
    paths: Any,
    *,
    start: date,
    now: datetime,
    commit: str | None,
    log_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    markets = universe_markets(paths.market_status)
    decline = _read_obj(paths.decline)
    sector = _read_obj(paths.sector)
    specs: list[NameSpec] = []
    blocked: Counter[str] = Counter()
    errors: list[str] = []
    session_rows: list[dict[str, Any]] = []
    scored: dict[str, date] = {}
    for market in markets:
        completed = latest_completed_session(market, now)
        if completed is None:
            errors.append(f"{market}: unknown close")
            continue
        scored[market] = completed
        screens, current = _screens_for(
            history_dir_for(paths, market), start=start, completed=completed
        )
        # Current buy tier is the no-session denominator. A name that was buy
        # earlier in the lookback is loaded only when its chart reaches start,
        # so an empty window does not count yesterday's tier as today's block.
        wanted = set(current) | set(_buy_tickers(screens))
        for ticker in sorted(wanted):
            chart_path = _chart_file(paths.charts, ticker)
            last = _chart_last(chart_path)
            if last is None or last < start:
                if ticker in current:
                    blocked["no_session_on_or_after_start"] += 1
                continue
            chart = _read_chart(chart_path) if chart_path is not None else None
            if chart is None:
                if ticker in current:
                    blocked["no_chart"] += 1
                continue
            sessions, closes, highs, lows = chart
            if not any(day >= start for day in sessions):
                if ticker in current:
                    blocked["no_session_on_or_after_start"] += 1
                continue
            try:
                row = _session_verdict(
                    paths,
                    market=market,
                    ticker=ticker,
                    scored=completed,
                    screens=screens.get(ticker) or [],
                    decline=decline,
                    sector=sector,
                    chart_path=chart_path,
                    commit=commit,
                    observed_at=now,
                )
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"{market}:{ticker}: {exc}")
                blocked["f9"] += 1
                continue
            seen = _seen_at(
                market=market,
                ticker=ticker,
                sessions=sessions,
                start=start,
                completed=completed,
                now=now,
                log_rows=log_rows,
            )
            specs.append(
                NameSpec(
                    market=market,
                    ticker=ticker,
                    sessions=sessions,
                    closes=closes,
                    highs=highs,
                    lows=lows,
                    screens=list(screens.get(ticker) or []),
                    gates=row["gates"],
                    memos=row["memos"],
                    f9=[row["f9"]] if row["f9"] is not None else [],
                    signal_seen_at=seen,
                    graduated=True,
                    library=market != "ftse350",
                    input_paths=row["input_paths"],
                    files=row["files"] or None,
                    committed=dict(row["files"]) if row["files"] else None,
                )
            )
            session_rows.append(row["log"])
    return {
        "specs": specs,
        "blocked": blocked,
        "errors": errors,
        "session_rows": session_rows,
        "scored": scored,
    }


def _screens_for(
    history: Path, *, start: date, completed: date
) -> tuple[dict[str, list[ScreenFact]], set[str]]:
    earliest = start - timedelta(days=SCREEN_LOOKBACK_DAYS)
    grouped: dict[str, list[ScreenFact]] = {}
    if history.is_dir():
        for path in sorted(history.iterdir()):
            if not path.is_file():
                continue
            hinted = _filename_day(path)
            if hinted is None or hinted < earliest or hinted >= completed:
                continue
            _add_screen_file(grouped, path)
    newest, payload, run_day = newest_screen_run(history, completed)
    current: set[str] = set()
    if newest is not None and payload is not None and run_day is not None:
        if not any(fact.path == str(newest) for facts in grouped.values() for fact in facts):
            _add_screen_payload(grouped, newest, payload, run_day)
        for ticker, row in screen_rows(payload).items():
            if str(row.get("signal") or "") in BUY_SIGNALS:
                current.add(ticker)
    return grouped, current


def _add_screen_file(grouped: dict[str, list[ScreenFact]], path: Path) -> None:
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return
    if not isinstance(payload, dict):
        return
    run_day = _run_calendar_day(path, payload)
    if run_day is None:
        return
    _add_screen_payload(grouped, path, payload, run_day)


def _add_screen_payload(
    grouped: dict[str, list[ScreenFact]],
    path: Path,
    payload: dict[str, Any],
    run_day: date,
) -> None:
    for ticker, row in screen_rows(payload).items():
        grouped.setdefault(ticker, []).append(_screen_fact(run_day, row, path))


def _screen_fact(run_day: date, row: dict[str, Any], path: Path) -> ScreenFact:
    skip = {"ticker", "signal", "adjusted_signal", "research_verdict", "sector"}
    fields = {key: value for key, value in row.items() if key not in skip}
    return ScreenFact(
        run_date=run_day,
        signal=_text(row.get("signal")),
        adjusted_signal=_text(row.get("adjusted_signal")),
        research_verdict=_text(row.get("research_verdict")),
        sector=_text(row.get("sector")),
        fields=fields,
        path=str(path),
    )


def _buy_tickers(screens: dict[str, list[ScreenFact]]) -> list[str]:
    found: list[str] = []
    for ticker, facts in screens.items():
        if any(str(fact.signal or "") in BUY_SIGNALS for fact in facts):
            found.append(ticker)
    return sorted(found)


def _session_verdict(
    paths: Any,
    *,
    market: str,
    ticker: str,
    scored: date,
    screens: list[ScreenFact],
    decline: dict[str, Any],
    sector: dict[str, Any],
    chart_path: Path | None,
    commit: str | None,
    observed_at: datetime,
) -> dict[str, Any]:
    in_force = [fact for fact in screens if fact.run_date < scored]
    latest = max(in_force, key=lambda item: item.run_date) if in_force else None
    row = {}
    if latest is not None:
        row = {
            "signal": latest.signal,
            "adjusted_signal": latest.adjusted_signal,
            "research_verdict": latest.research_verdict,
            **latest.fields,
        }
    try:
        memo_as_of = session_close(market, scored)
    except UnknownMarketClose:
        memo_as_of = observed_at
    binds, _bind_paths = _binds(
        market=market,
        ticker=ticker,
        row=row,
        research_root=research_root_for(paths, market),
        session=scored,
        memo_as_of=memo_as_of,
    )
    gaps = [name for name, check in binds.items() if not check.passed]
    f9 = F9Fact(
        as_of=scored,
        key_filing_bodies=bool(binds["key_filing_bodies"].passed),
        fcf_basis_bound=bool(binds["fcf_basis_bound"].passed),
        overlay_bound=bool(binds["overlay_bound"].passed),
        memo_recent=bool(binds["memo_recent"].passed),
    )
    memos: list[MemoFact] = []
    memo_at = binds["memo_recent"].detail.get("memo_at") if binds["memo_recent"].detail else None
    if memo_at:
        parsed = _parse_dt(memo_at)
        if parsed is not None:
            memos.append(
                MemoFact(
                    finished_at=parsed,
                    verdict=_text(binds["memo_recent"].detail.get("disk_verdict")),
                    by_signal_job=False,
                )
            )
    gates = _gate_for(decline, sector, market, ticker)
    gate = gates[0] if gates else None
    in_gate = gate is not None and gate.as_of < scored
    files = _hash_files(
        paths.root,
        [path for path in (chart_path, paths.decline, paths.sector) if path is not None],
    )
    if latest is not None and latest.path:
        files.update(_hash_files(paths.root, [Path(latest.path)]))
    inputs = [{"path": rel, "sha256": sha256_bytes(blob)} for rel, blob in sorted(files.items())]
    log = {
        "kind": "session",
        "market": market,
        "ticker": ticker,
        "as_of": scored.isoformat(),
        "decline": gate.decline if in_gate else None,
        "sector": gate.sector if in_gate else None,
        "gate_as_of": None if gate is None else gate.as_of.isoformat(),
        "signal": None if latest is None else latest.signal,
        "research_verdict": None if latest is None else latest.research_verdict,
        "f9": "pass" if not gaps else gaps,
        "inputs": inputs,
        "data_commit": commit,
        "observed_at": observed_at.isoformat(),
    }
    return {
        "gates": gates,
        "memos": memos,
        "f9": f9,
        "files": files,
        "input_paths": list(files),
        "log": log,
    }


def _seen_at(
    *,
    market: str,
    ticker: str,
    sessions: list[date],
    start: date,
    completed: date,
    now: datetime,
    log_rows: list[dict[str, Any]],
) -> dict[date, datetime]:
    seen: dict[date, datetime] = {}
    for day in sessions:
        if day < start:
            continue
        if day == completed:
            seen[day] = now
            continue
        logged = _logged_seen(log_rows, market, ticker, day)
        seen[day] = logged or now
    return seen


def _logged_seen(
    rows: list[dict[str, Any]], market: str, ticker: str, day: date
) -> datetime | None:
    token = day.isoformat()
    for row in rows:
        if row.get("market") != market or row.get("ticker") != ticker:
            continue
        if (
            str(row.get("as_of") or "")[:10] != token
            and str(row.get("session") or "")[:10] != token
        ):
            continue
        parsed = _parse_dt(row.get("observed_at"))
        if parsed is not None:
            return parsed
    return None


def _tally(
    events: list[dict[str, Any]],
    specs: list[NameSpec],
    options: Any,
    preset: Counter[str],
) -> dict[str, Any]:
    blocked = Counter(preset)
    signals = 0
    entries = 0
    filled = 0
    pending = 0
    late = 0
    memo_nr = 0
    memo_blocked = 0
    tickers: list[str] = []
    signaled: set[tuple[str, str]] = set()
    for event in events:
        kind = str(event.get("kind") or "")
        if kind not in SIGNAL_KINDS:
            continue
        if event.get("column") not in (None, COLUMN_PRIMARY):
            continue
        signals += 1
        market = str(event.get("market") or "")
        ticker = str(event.get("ticker") or "")
        signaled.add((market, ticker))
        if ticker and ticker not in tickers and len(tickers) < SAMPLE_TICKERS:
            tickers.append(ticker)
        if kind == "filled":
            filled += 1
            entries += 1
        elif kind == "pending_fill":
            pending += 1
            entries += 1
        else:
            blocked[kind] += 1
        if kind == "late_signal":
            late += 1
        elif kind == "memo_not_ready":
            memo_nr += 1
        elif kind == "memo_blocked":
            memo_blocked += 1
    for spec in specs:
        if (spec.market, spec.ticker) in signaled:
            continue
        session = _last_in_window(spec, options.entry_not_before)
        if session is None:
            blocked["no_session_on_or_after_start"] += 1
            continue
        book = PriceBook(_downloads_of(spec))
        refusal = series_refusal(book.calendar) if book.calendar else "no_chart"
        name = _Name(spec=spec, prices=book, refusal=refusal)
        ok, reason = _base_eligible(name, session, options, price=True)
        blocked[reason if not ok else "recovery_cap"] += 1
    return {
        "signals": signals,
        "entries_that_would_open": entries,
        "filled": filled,
        "pending_fill": pending,
        "late_signal": late,
        "memo_not_ready": memo_nr,
        "memo_blocked": memo_blocked,
        "blocked_reasons": {key: int(value) for key, value in sorted(blocked.items()) if value},
        "sample_tickers": tickers,
    }


def _last_in_window(spec: NameSpec, start: date | None) -> date | None:
    days = [day for day in (spec.sessions or []) if start is None or day >= start]
    return days[-1] if days else None


def _health(boards: dict[str, Any]) -> dict[str, Any]:
    gate = boards.get("thickness_gate") if isinstance(boards.get("thickness_gate"), dict) else {}
    launch = boards.get("launch") if isinstance(boards.get("launch"), dict) else {}
    interim = boards.get("interim_read") if isinstance(boards.get("interim_read"), dict) else {}
    return {
        "phase_span_sessions": int(gate.get("span_sessions") or 0),
        "mature_count": int(launch.get("mature") or 0),
        "interim_published": bool(interim.get("published")),
        "thickness_ready": bool(gate.get("ready")),
    }


def _append_gate_log(
    path: Path,
    *,
    session_rows: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    scored: dict[str, date],
    already: list[dict[str, Any]],
    observed_at: datetime,
    commit: str | None,
) -> bool:
    covered = _covered_dates(already)
    fresh_sessions = []
    for row in session_rows:
        day = _day(row.get("as_of"))
        market = str(row.get("market") or "")
        if day is None:
            continue
        seen = covered.get(market)
        if seen is not None and day <= seen:
            continue
        fresh_sessions.append(row)
    if not fresh_sessions and not episodes:
        return False
    markets = {str(row.get("market")) for row in fresh_sessions}
    extra = _episode_rows(episodes, scored, markets, observed_at, commit)
    rows = fresh_sessions + extra
    if not rows:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, default=str) + "\n")
    return True


def _episode_rows(
    episodes: list[dict[str, Any]],
    scored: dict[str, date],
    markets: set[str],
    observed_at: datetime,
    commit: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        market = str(episode.get("market") or "")
        if market not in markets:
            continue
        day = scored.get(market)
        if day is None:
            continue
        token = day.isoformat()
        inputs = episode.get("inputs") if isinstance(episode.get("inputs"), list) else []
        base = {
            "market": market,
            "ticker": episode.get("ticker"),
            "column": episode.get("column"),
            "as_of": token,
            "inputs": inputs,
            "data_commit": episode.get("data_commit") or commit,
            "observed_at": observed_at.isoformat(),
        }
        if episode.get("signal_session") == token or episode.get("fill_session") == token:
            rows.append(
                {
                    **base,
                    "kind": "entry",
                    "session": episode.get("signal_session"),
                    "fill_session": episode.get("fill_session"),
                }
            )
        if episode.get("exit_session") == token:
            rows.append(
                {
                    **base,
                    "kind": "exit",
                    "session": episode.get("exit_session"),
                    "exit_reason": episode.get("exit_reason"),
                }
            )
        for review in episode.get("reviews") or []:
            if not isinstance(review, dict) or str(review.get("session") or "")[:10] != token:
                continue
            rows.append(
                {
                    **base,
                    "kind": "review",
                    "index": review.get("index"),
                    "session": review.get("session"),
                    "action": review.get("action"),
                }
            )
    return rows


def _provenance(
    rows: list[dict[str, Any]], *, reader: BlobReader
) -> tuple[list[dict[str, str]], int]:
    bad: list[dict[str, str]] = []
    pending = 0
    for row in rows:
        commit = str(row.get("data_commit") or "")
        for item in row.get("inputs") or []:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or "")
            digest = item.get("sha256")
            if not rel or not commit or not isinstance(digest, str):
                pending += 1
                continue
            try:
                blob = reader(commit, rel)
            except (OSError, ValueError, TypeError):
                pending += 1
                continue
            if blob is None:
                pending += 1
                continue
            if sha256_bytes(blob) != digest:
                bad.append({"path": rel, "commit": commit})
    return bad, pending


def _covered_dates(rows: list[dict[str, Any]]) -> dict[str, date]:
    covered: dict[str, date] = {}
    for row in rows:
        if row.get("kind") != "session":
            continue
        market = str(row.get("market") or "")
        day = _day(row.get("as_of"))
        if not market or day is None:
            continue
        current = covered.get(market)
        if current is None or day > current:
            covered[market] = day
    return covered


def _logged_through(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {market: day.isoformat() for market, day in _covered_dates(rows).items()}


def _read_log(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _hash_files(root: Path, paths: list[Path]) -> dict[str, bytes]:
    blobs: dict[str, bytes] = {}
    for path in paths:
        if path is None or not path.is_file():
            continue
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            blobs[rel] = path.read_bytes()
        except OSError:
            continue
    return blobs


def _chart_last(path: Path | None) -> date | None:
    if path is None or not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return chart_last_close_date(payload)


def _read_obj(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _head_commit(repo: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    return text or None


def _reject_scores(payload: dict[str, Any]) -> None:
    text = json.dumps(payload)
    for token in _RETURN_TOKENS:
        if token in text:
            raise RuntimeError(f"counts view contains {token}")


def _aware(now: datetime) -> datetime:
    return now if now.tzinfo is not None else now.replace(tzinfo=UTC)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _day(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
