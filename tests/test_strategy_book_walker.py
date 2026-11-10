"""Walker and archive-replay tests on constructed series.

The registration is unsigned. Nothing here reads ``docs/data`` charts or runs.
Close refresh, the forward ops-monitor job, the gate log and the dashboard
strip are the next package and are not built here.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from value_investor.market_trading_costs import costs_for_market
from value_investor.n200_tech_timing_observe import episode_return
from value_investor.strategy_book_memo_job import spend_enabled
from value_investor.strategy_book_observe import (
    Download,
    F9Fact,
    GateFact,
    GateTape,
    ListingFact,
    MemoFact,
    NameSpec,
    ScreenFact,
    WalkOptions,
    add_bench_column,
    build_boards,
    capital_days_return,
    entry_week,
    entry_week_standard_error,
    filter_kept,
    period_halves,
    walk_book,
)
from value_investor.strategy_book_observe_cli import main as observe_main
from value_investor.strategy_book_replay import result_medians_are_separate, run_replay
from value_investor.strategy_book_replay_cli import main as replay_main
from value_investor.strategy_book_rules import (
    ALT_RSI_LEVEL,
    ALT_SMA_DISTANCE,
    ARCHIVE_BUY_TIER_ONLY,
    ARCHIVE_FULL_STRATEGY,
    BASKET_MIN_NAMES,
    BENCH_COLUMNS,
    BENCH_MIN_COUNTED,
    BENCH_SLOTS,
    BENCH_STANDARD_ERRORS,
    CHECKPOINTS,
    COLUMN_ALTERNATIVE,
    COLUMN_BUY_ON_SIGNAL,
    COLUMN_DECLINE_SHADOW,
    COLUMN_DRAFT,
    COLUMN_LADDER,
    COLUMN_LEAVE_TIER,
    COLUMN_PRIMARY,
    COOLDOWN_SESSIONS,
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
    LAUNCH_RETURN,
    LOOKAHEAD_CURRENT_GATES,
    LOW_WINDOW_SESSIONS,
    MARKET_CLOSE_LOCAL,
    MATURITY_SESSIONS,
    MAX_FILL_GAP_CALENDAR_DAYS,
    RECOVERY_DROP,
    REGISTRATION_ID,
    REVIEW_BENCH,
    RSI_LEVEL,
    SLOT_BOOK_RANDOM_SEED,
    SLOT_COUNT,
    STAKE_UNITS,
    T212_CATALOGUE_MAX_AGE_DAYS,
    THICKNESS_MAX_PER_ENTRY_WEEK,
    THICKNESS_MIN_COUNTED,
    TIME_CAP_INDEX,
    UnknownMarketClose,
    registration_signed,
    session_close,
)
from value_investor.strategy_book_signals import price_flags, session_end

START = date(2024, 1, 2)


def _weekdays(count: int, start: date = START) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _decline(count: int = 15, start: float = 80.0) -> list[float]:
    return [start - float(index) for index in range(count)]


def _spec(
    closes: list[float],
    *,
    ticker: str = "AAA",
    market: str = "ftse350",
    signal_index: int = 14,
    signal: str = "buy",
    adjusted: str | None = "buy",
    research: str = "hold",
    decline: str = "clear",
    sector: str = "sound",
    memo: bool = True,
    memo_verdict: str = "hold",
    memo_hours: int = 12,
    f9: bool = True,
    listing: ListingFact | None = None,
    seen: dict[date, datetime] | None = None,
    library: bool = False,
    graduated: bool = True,
    files: dict[str, bytes] | None = None,
    committed: dict[str, bytes] | None = None,
    paths: list[str] | None = None,
    omit: set[str] | None = None,
    extra_screens: list[ScreenFact] | None = None,
    extra_gates: list[GateFact] | None = None,
    fields: dict | None = None,
    start: date = START,
    downloads: list[Download] | None = None,
    screens: list[ScreenFact] | None = None,
    gates: list[GateFact] | None = None,
) -> NameSpec:
    days = _weekdays(len(closes), start)
    run_day = days[signal_index - 1] if signal_index else days[0] - timedelta(days=3)
    fill_day = days[signal_index + 1] if signal_index + 1 < len(days) else None
    screen_rows = (
        list(screens)
        if screens is not None
        else [
            ScreenFact(
                run_date=run_day,
                signal=signal,
                adjusted_signal=adjusted,
                research_verdict=research,
                fields=dict(fields or {}),
            )
        ]
    )
    if extra_screens:
        screen_rows.extend(extra_screens)
    gate_rows = (
        list(gates)
        if gates is not None
        else [GateFact(as_of=run_day, decline=decline, sector=sector, sector_basis="own_market")]
    )
    if extra_gates:
        gate_rows.extend(extra_gates)
    memos: list[MemoFact] = []
    if memo and fill_day is not None:
        memos.append(
            MemoFact(
                finished_at=datetime.combine(fill_day, time(0), tzinfo=UTC)
                + timedelta(hours=memo_hours),
                verdict=memo_verdict,
                rationale="fixture",
            )
        )
    f9_rows = None
    if f9:
        f9_rows = [
            F9Fact(
                as_of=days[signal_index],
                key_filing_bodies=True,
                fcf_basis_bound=True,
                overlay_bound=True,
                memo_recent=True,
            )
        ]
    return NameSpec(
        market=market,
        ticker=ticker,
        sessions=None if downloads else days,
        closes=None if downloads else [float(value) for value in closes],
        downloads=downloads,
        screens=screen_rows,
        gates=gate_rows,
        memos=memos,
        f9=f9_rows,
        listing=listing,
        signal_seen_at=seen,
        graduated=graduated,
        library=library,
        input_paths=list(paths or []),
        files=files,
        committed=committed,
        omit_hash_on=set(omit or []),
    )


def _walk(*specs: NameSpec, **options: object):
    if options:
        return walk_book(list(specs), options=WalkOptions(**options))  # type: ignore[arg-type]
    return walk_book(list(specs))


def _primary(result: dict, ticker: str | None = None) -> list[dict]:
    rows = (
        [
            row
            for row in result["episodes"]
            if row["column"] == COLUMN_PRIMARY and row["ticker"] == ticker
        ]
        if ticker
        else [row for row in result["episodes"] if row["column"] == COLUMN_PRIMARY]
    )
    return rows


def _one(result: dict, column: str = COLUMN_PRIMARY, ticker: str = "AAA") -> dict:
    rows = [
        row for row in result["episodes"] if row["column"] == column and row["ticker"] == ticker
    ]
    assert len(rows) == 1, (
        column,
        ticker,
        [(row["column"], row["ticker"], row.get("exit_reason")) for row in result["episodes"]],
    )
    return rows[0]


def _kind(result: dict, kind: str) -> list[dict]:
    return [event for event in result["events"] if event.get("kind") == kind]


def test_registered_numbers_match_the_text() -> None:
    assert RSI_LEVEL == 35
    assert LOW_WINDOW_SESSIONS == 10
    assert ALT_RSI_LEVEL == 40
    assert ALT_SMA_DISTANCE == 0.03
    assert MAX_FILL_GAP_CALENDAR_DAYS == 5
    assert LAUNCH_RETURN == 0.10
    assert CHECKPOINTS[0] == (0.10, 0.05)
    assert CHECKPOINTS[-1] == (1.00, 0.75)
    assert FAIL_TO_LAUNCH_INDEX == 63
    assert TIME_CAP_INDEX == 252
    assert RECOVERY_DROP == 0.08
    assert STAKE_UNITS == 100
    assert COOLDOWN_SESSIONS == 10
    assert MATURITY_SESSIONS == 63
    assert BASKET_MIN_NAMES == 5
    assert BENCH_SLOTS == 4
    assert BENCH_STANDARD_ERRORS == 2.5
    assert BENCH_MIN_COUNTED == 48
    assert SLOT_COUNT == 20
    assert THICKNESS_MIN_COUNTED == 48
    assert THICKNESS_MAX_PER_ENTRY_WEEK == 6
    assert T212_CATALOGUE_MAX_AGE_DAYS == 35
    assert REGISTRATION_ID == "owner-strategy-book-v0"
    assert SLOT_BOOK_RANDOM_SEED == 20261104


def test_entry_needs_rsi_below_35_and_a_ten_session_low() -> None:
    closes = _decline() + [100.0, 101.0]
    assert price_flags(_decline())["primary"] is True
    result = _walk(_spec(closes))
    episode = _one(result)
    assert episode["signal_session"] == _weekdays(len(closes))[14].isoformat()
    assert episode["entry_fill_first_seen"] == pytest.approx(100.0)


def test_high_rsi_does_not_enter_on_a_ten_session_low() -> None:
    rising = [100.0 + index * 0.4 for index in range(40)]
    series = rising + [rising[-1] - index * 0.05 for index in range(1, 11)]
    flags = price_flags(series)
    assert flags["ten_session_low"] is True
    assert flags["rsi"] is not None and flags["rsi"] > 35
    result = _walk(_spec(series, signal_index=len(series) - 2))
    assert _primary(result) == []


def test_leaving_the_buy_tier_does_not_exit() -> None:
    closes = _decline() + [100.0] + [104.0] * 25
    days = _weekdays(len(closes))
    result = _walk(
        _spec(
            closes,
            extra_screens=[ScreenFact(run_date=days[20], signal="hold", research_verdict="hold")],
        )
    )
    episode = _one(result)
    assert episode["status"] == "open"
    assert episode["exit_reason"] is None


def test_worked_ladder_launches_raises_the_floor_and_sells_the_next_close() -> None:
    path = [100.0] + [100.0] * 8 + [110.4] + [112.0] * 10 + [116.0] + [112.0] * 5 + [109.8, 109.5]
    result = _walk(_spec(_decline() + path))
    episode = _one(result)
    assert episode["launched"] is True
    assert episode["launch_index"] == 9
    floors = [row["floor"] for row in episode["floor_history"]]
    assert floors[0] == pytest.approx(0.05)
    assert 0.10 in floors
    assert floors == sorted(floors)
    assert episode["exit_reason"] == EXIT_FLOOR
    assert episode["exit_fill"] == pytest.approx(109.5)
    costs = costs_for_market("ftse350")
    assert costs.buy_pct == pytest.approx(0.00525)
    assert costs.sell_pct == pytest.approx(0.00025)
    expected = episode_return(
        100.0, 109.5, buy_cost_pct=costs.buy_pct, sell_cost_pct=costs.sell_pct
    )
    assert expected == pytest.approx(0.0895)
    assert episode["fair_cost_return"] == pytest.approx(expected)


def test_gap_fill_under_the_floor_is_scored_as_filled() -> None:
    path = [100.0] + [100.0] * 8 + [110.4] + [112.0] * 10 + [116.0] + [112.0] * 5 + [109.8, 100.0]
    result = _walk(_spec(_decline() + path))
    episode = _one(result)
    assert episode["exit_reason"] == EXIT_FLOOR
    assert episode["exit_fill"] == pytest.approx(100.0)
    assert episode["gap_shortfall"] > 0
    costs = costs_for_market("ftse350")
    assert episode["fair_cost_return"] == pytest.approx(
        episode_return(100.0, 100.0, buy_cost_pct=costs.buy_pct, sell_cost_pct=costs.sell_pct)
    )


def test_unlaunched_sells_at_index_63_and_a_launch_on_62_does_not() -> None:
    failed = [100.0] + [100.0] * 62 + [96.0, 95.6]
    result = _walk(_spec(_decline() + failed))
    episode = _one(result)
    assert episode["exit_reason"] == EXIT_FAIL_TO_LAUNCH
    assert episode["launched"] is False
    costs = costs_for_market("ftse350")
    assert episode["fair_cost_return"] == pytest.approx(
        episode_return(100.0, 95.6, buy_cost_pct=costs.buy_pct, sell_cost_pct=costs.sell_pct)
    )

    held = [100.0] + [100.0] * 61 + [110.4, 110.4]
    launched = _walk(_spec(_decline() + held))
    episode = _one(launched)
    assert episode["launch_index"] == 62
    assert episode["exit_reason"] is None
    assert episode["status"] == "open"


def test_session_index_252_sells_when_reviews_hold() -> None:
    path = [100.0] + [100.0] * 8 + [110.4] + [112.0] * (252 - 9) + [112.0]
    result = _walk(_spec(_decline() + path))
    episode = _one(result)
    assert episode["exit_reason"] == EXIT_TIME_CAP
    assert episode["launched"] is True
    assert episode["exit_signal_session"] != episode["exit_session"]


def test_eight_percent_drop_labels_recovery_and_does_not_sell() -> None:
    path = [100.0] + [100.0] * 4 + [91.0] + [100.0] * 10
    result = _walk(_spec(_decline() + path))
    episode = _one(result)
    assert episode["recovery_label"] is True
    assert episode["status"] == "open"
    assert episode["exit_reason"] is None


def test_both_comparison_exits_follow_the_primary_and_do_not_change_it() -> None:
    path = [100.0] + [101.0] * 9 + [105.0, 106.0] + [104.0] * 10
    result = _walk(_spec(_decline() + path))
    primary = _one(result)
    draft = _one(result, COLUMN_DRAFT)
    ladder = _one(result, COLUMN_LADDER)
    assert _one(result, COLUMN_LEAVE_TIER)["signal_session"] == primary["signal_session"]
    assert len(_primary(result)) == 1
    assert draft["exit_reason"] == EXIT_SWING_HIGH
    assert primary["status"] == "open"
    assert ladder["status"] == "open"
    assert result["boards"]["recovery_label"]["count"] == 0

    classified = [100.0] + [99.0] * 20
    held = _walk(_spec(_decline() + classified))
    assert _one(held)["recovery_label"] is False
    assert _one(held, COLUMN_DRAFT)["recovery_label"] is True
    assert held["boards"]["recovery_label"]["count"] == 0


def test_draft_recovery_sells_at_the_entry_and_review_four_caps_the_hold() -> None:
    dipped = [100.0] + [100.0] * 3 + [91.0] + [95.0] * 2 + [100.0, 101.0]
    early = _walk(_spec(_decline() + dipped))
    assert _one(early, COLUMN_DRAFT)["exit_reason"] == EXIT_RECOVERY_TARGET
    assert _one(early)["status"] == "open"
    assert _one(early)["recovery_label"] is True

    long = [100.0] + [99.0] * 268
    capped = _walk(_spec(_decline() + long))
    assert _one(capped, COLUMN_DRAFT)["exit_reason"] == EXIT_REVIEW_CAP
    assert _one(capped)["exit_reason"] == EXIT_FAIL_TO_LAUNCH
    ladder = _one(capped, COLUMN_LADDER)
    assert ladder["exit_reason"] == EXIT_REVIEW_CAP
    assert ladder["exit_fill"] != pytest.approx(100.0) or ladder["exit_fill"] == pytest.approx(99.0)


def test_two_avoid_rows_sell_and_one_does_not() -> None:
    closes = _decline() + [100.0] + [104.0] * 20
    days = _weekdays(len(closes))
    one = _walk(
        _spec(
            closes,
            extra_screens=[ScreenFact(run_date=days[18], signal="avoid", research_verdict="hold")],
        )
    )
    assert _one(one)["exit_reason"] is None

    two = _walk(
        _spec(
            closes,
            extra_screens=[
                ScreenFact(run_date=days[18], signal="avoid", research_verdict="hold"),
                ScreenFact(run_date=days[19], signal="avoid", research_verdict="hold"),
            ],
        )
    )
    episode = _one(two)
    assert episode["exit_reason"] == EXIT_THESIS
    reasons = []
    for row in episode["decision_log"]:
        if row.get("action") == EXIT_THESIS:
            reasons.extend(row.get("reasons") or [])
    assert "screen_avoid" in reasons


def test_insufficient_data_blocks_entry_and_does_not_break_a_hold() -> None:
    closes = _decline() + [100.0, 104.0]
    blocked = _walk(_spec(closes, decline="insufficient_data"))
    assert _primary(blocked) == []
    assert _kind(blocked, "insufficient_data")
    assert [row for row in blocked["episodes"] if row["column"] == COLUMN_DECLINE_SHADOW] == []

    held_closes = _decline() + [100.0] + [104.0] * 20
    days = _weekdays(len(held_closes))
    held = _walk(
        _spec(
            held_closes,
            extra_gates=[GateFact(as_of=days[20], decline="insufficient_data", sector="sound")],
        )
    )
    episode = _one(held)
    assert episode["status"] == "open"
    assert episode["exit_reason"] is None


def test_decision_median_uses_mature_episodes_and_an_open_floor() -> None:
    mature_path = [100.0] + [100.0] * 8 + [110.4] + [112.0] * 70
    young_path = [100.0] + [100.0] * 8 + [110.4] + [130.0] * 5
    result = _walk(
        _spec(mature_path and _decline() + mature_path, ticker="OLD"),
        _spec(_decline() + young_path, ticker="NEW"),
    )
    old = _one(result, ticker="OLD")
    new = _one(result, ticker="NEW")
    assert old["mature"] is True
    assert new["mature"] is False
    assert new["decision_return_floor"] is None
    floor_px = old["return_entry_fill"] * (1.0 + old["floor"])
    costs = costs_for_market("ftse350")
    floor_return = episode_return(
        old["return_entry_fill"], floor_px, buy_cost_pct=costs.buy_pct, sell_cost_pct=costs.sell_pct
    )
    assert old["decision_return_floor"] == pytest.approx(floor_return)
    assert old["decision_return_close"] != pytest.approx(floor_return)
    assert result["boards"]["overall"]["count"] == 1
    assert result["boards"]["overall"]["median_fair_cost"] == pytest.approx(floor_return)


def test_interim_standard_error_uses_entry_week_averages() -> None:
    def _row(ticker: str, column: str, week: str, floor: float, close: float, signal: str) -> dict:
        return {
            "column": column,
            "market": "ftse350",
            "ticker": ticker,
            "signal_session": signal,
            "fill_session": "2024-01-02" if week.endswith("01") else "2024-06-03",
            "entry_week": week,
            "mature": True,
            "status": "closed",
            "launched": True,
            "decision_return_floor": floor,
            "decision_return_close": close,
            "fair_cost_return": floor,
            "capital_return": close,
            "stake": 100,
            "held_calendar_days": 30,
            "held_sessions": 20,
            "provenance_missing": False,
            "exit_reason": EXIT_FLOOR,
            "recovery_label": False,
            "matched_excess": 0.0,
            "basket": {},
            "snapshot": {"composite_score": 1.0},
            "channels": {},
            "bench": {},
            "t212_listed": "unknown",
            "regime": "regime_unknown",
            "adjusted_signal": "buy",
        }

    episodes = [
        _row("A", COLUMN_PRIMARY, "2024-W01", 0.05, 0.05, "2024-01-02"),
        _row("A", COLUMN_DRAFT, "2024-W01", 0.0, 0.0, "2024-01-02"),
        _row("B", COLUMN_PRIMARY, "2024-W01", 0.01, 0.01, "2024-01-03"),
        _row("B", COLUMN_DRAFT, "2024-W01", 0.0, 0.0, "2024-01-03"),
        _row("C", COLUMN_PRIMARY, "2024-W23", 0.20, 0.20, "2024-06-03"),
        _row("C", COLUMN_DRAFT, "2024-W23", 0.0, 0.0, "2024-06-03"),
    ]
    boards = build_boards(episodes, scoring_date=date(2024, 8, 1))
    paired = boards["paired_exits"][COLUMN_DRAFT]
    week_means = {"2024-W01": [0.05, 0.01], "2024-W23": [0.20]}
    assert paired["standard_error"] == pytest.approx(entry_week_standard_error(week_means))
    episode_means = [0.05, 0.01, 0.20]
    episode_se = statistics.stdev(episode_means) / (len(episode_means) ** 0.5)
    assert paired["standard_error"] != pytest.approx(episode_se)
    assert boards["interim_read"]["published"] is True
    assert boards["interim_read"]["standard_error"] == pytest.approx(paired["standard_error"])


def test_declining_opens_a_shadow_and_not_a_book_episode() -> None:
    closes = _decline() + [100.0, 104.0]
    result = _walk(_spec(closes, decline="declining", sector="sound"))
    assert _primary(result) == []
    shadow = _one(result, COLUMN_DECLINE_SHADOW)
    assert shadow["column"] == COLUMN_DECLINE_SHADOW
    assert result["boards"]["thickness_gate"]["counted"] == 0


def test_snapshot_ignores_a_file_dated_on_the_signal_session() -> None:
    closes = _decline() + [100.0, 104.0]
    days = _weekdays(len(closes))
    result = _walk(
        _spec(
            closes,
            fields={"composite_score": 1.0},
            extra_screens=[
                ScreenFact(run_date=days[14], signal="buy", fields={"composite_score": 99.0})
            ],
            extra_gates=[GateFact(as_of=days[14], decline="clear", sector="sound")],
        )
    )
    snapshot = _one(result)["snapshot"]
    assert snapshot["composite_score"] == 1.0
    assert snapshot["gate_as_of"] != days[14].isoformat()
    assert snapshot["inputs_not_after_signal"] is True


def test_filter_challenger_keeps_book_entries_only() -> None:
    closes = _decline() + [100.0] + [90.0] * 12 + [100.0] * 10
    result = _walk(_spec(closes, adjusted="hold"))
    kept = filter_kept(result["episodes"], "fcf_agrees")
    primary_ids = {row["episode_id"] for row in _primary(result)}
    assert {row["episode_id"] for row in kept} <= primary_ids
    assert all(row["column"] == COLUMN_PRIMARY for row in kept)
    assert not any(row["column"] == "fcf_agrees" for row in result["episodes"])
    assert _one(result)["bench"]["fcf_agrees"] is False


def test_trend_not_falling_drops_entries_in_a_falling_channel() -> None:
    tail = _decline() + [100.0] + [90.0] * 12 + [100.0] * 10
    rising = _one(_walk(_spec([40.0 + i * 0.25 for i in range(150)] + tail, signal_index=164)))
    falling = _one(_walk(_spec([200.0 - i * 0.75 for i in range(150)] + tail, signal_index=164)))
    short = _one(_walk(_spec(tail)))
    assert rising["channels"]["ch126_direction"] == "rising"
    assert rising["bench"]["trend_not_falling"] is True
    assert falling["channels"]["ch126_direction"] == "falling"
    assert falling["bench"]["trend_not_falling"] is False
    assert short["channels"]["ch126_status"] == "insufficient_history"
    assert short["bench"]["trend_not_falling"] is False


def test_review_bench_columns_match_their_registration_seal() -> None:
    root = Path(__file__).resolve().parents[1]
    registration = json.loads(
        (root / "docs/data/strategy_book_registration.json").read_text(encoding="utf-8")
    )
    seals = {row["column"]: row for row in registration.get("bench_seals") or []}
    assert set(seals) == set(REVIEW_BENCH)
    assert len(BENCH_COLUMNS) <= BENCH_SLOTS
    for column, seal in seals.items():
        assert hashlib.sha256(seal["rule"].encode()).hexdigest() == seal["rule_sha256"]
        assert seal["rule"].startswith(f"{column} ")
        review = (root / seal["review_doc"]).read_text(encoding="utf-8")
        assert f"> {seal['rule']}" in review
    board = build_boards([])["bench"]
    assert set(board) == set(BENCH_COLUMNS)


def test_bench_column_after_scores_needs_a_version_review() -> None:
    store = {
        "episodes": [{"episode_id": "x"}],
        "bench_columns": ["deep_dip", "revenue_growing", "fcf_agrees"],
    }
    with pytest.raises(ValueError):
        add_bench_column(store, "new_filter")
    add_bench_column(store, "new_filter", version_review={"id": "review-1", "column": "new_filter"})
    assert store["bench_columns"][-1] == "new_filter"


def test_memo_bind_late_signal_and_a_failed_verdict() -> None:
    closes = _decline() + [100.0, 104.0]
    ready = _walk(_spec(closes, memo_hours=12))
    assert _one(ready)["memo_verdict"] == "hold"

    late_memo = _walk(_spec(closes, memo_hours=30))
    assert _primary(late_memo) == []
    assert _kind(late_memo, "memo_not_ready")

    blocked = _walk(_spec(closes, memo_verdict="pass"))
    assert _primary(blocked) == []
    assert _kind(blocked, "memo_blocked")
    assert _kind(blocked, "memo_blocked")[0]["verdict"] == "pass"

    days = _weekdays(len(closes))
    seen = {days[14]: session_end(days[15]) + timedelta(hours=1)}
    late = _walk(_spec(closes, seen=seen))
    assert _primary(late) == []
    assert _kind(late, "late_signal")


def test_matched_excess_and_the_five_name_fallback() -> None:
    path = [100.0] + [100.0] * 8 + [110.4] + [112.0] * 10 + [116.0] + [112.0] * 5 + [109.8, 109.5]
    base = _decline() + path
    names = [_spec(base, ticker="AAA")]
    flat = [50.0] * len(base)
    for index in range(4):
        names.append(_spec(flat, ticker=f"B{index}"))
    result = _walk(*names)
    episode = _one(result)
    basket = episode["basket"]
    assert basket["fallback"] is False
    assert basket["source"] == "buy_tier"
    assert basket["count"] == 5
    gross = 109.5 / 100.0 - 1.0
    assert episode["matched_excess"] == pytest.approx(gross - gross / 5.0)

    small = [_spec(base, ticker="AAA"), _spec(flat, ticker="B0"), _spec(flat, ticker="B1")]
    small.append(_spec(flat, ticker="H0", signal="hold"))
    small.append(_spec(flat, ticker="H1", signal="hold"))
    fallen = _walk(*small)
    fallback = _one(fallen)["basket"]
    assert fallback["fallback"] is True
    assert fallback["source"] == "whole_screen"
    assert fallback["count"] == 5


def test_t212_listing_and_regime_unknown() -> None:
    closes = _decline() + [100.0, 104.0]
    days = _weekdays(len(closes))
    fill = days[15]
    listed = _walk(_spec(closes, ticker="HIT", listing=ListingFact("catalogue_hit", fill)))
    allow = _walk(_spec(closes, ticker="ALW", listing=ListingFact("exchange_allowlist", fill)))
    stale = _walk(
        _spec(
            closes,
            ticker="OLD",
            listing=ListingFact("catalogue_hit", fill - timedelta(days=36)),
        )
    )
    assert _one(listed, ticker="HIT")["t212_listed"] is True
    assert _one(allow, ticker="ALW")["t212_listed"] is False
    assert _one(stale, ticker="OLD")["t212_listed"] == "unknown"
    assert _one(listed, ticker="HIT")["regime"] == "regime_unknown"


def test_split_and_a_later_download_do_not_rewrite_a_closed_return() -> None:
    path = [100.0] + [100.0] * 8 + [110.4] + [112.0] * 16 + [109.8, 109.5]
    full = _decline() + path
    half = [value / 2.0 for value in full]
    first = _one(_walk(_spec(full)))
    second = _one(_walk(_spec(half)))
    assert first["fair_cost_return"] == pytest.approx(second["fair_cost_return"])

    days = _weekdays(len(full))
    signal_at = 14
    sale_index = signal_at + 1 + 27
    floor_index = signal_at + 1 + 26
    early = Download(
        as_of=days[floor_index], sessions=days[: floor_index + 1], closes=full[: floor_index + 1]
    )
    rewritten = [40.0] * len(full)
    rewritten[signal_at + 1] = 50.0
    rewritten[sale_index] = 55.0
    late = Download(as_of=days[sale_index], sessions=days, closes=rewritten)
    moved = _walk(_spec(full, downloads=[early, late]))
    episode = _one(moved)
    costs = costs_for_market("ftse350")
    assert episode["fair_cost_return"] == pytest.approx(
        episode_return(50.0, 55.0, buy_cost_pct=costs.buy_pct, sell_cost_pct=costs.sell_pct)
    )
    assert episode["fair_cost_return"] != pytest.approx(
        episode_return(100.0, 55.0, buy_cost_pct=costs.buy_pct, sell_cost_pct=costs.sell_pct)
    )
    launch = [
        row for row in episode["decision_log"] if row.get("action") in {"launch", "checkpoint"}
    ]
    assert any(row["close"] == pytest.approx(110.4) for row in launch)
    assert episode["launched"] is True


def test_basket_uses_the_episode_download() -> None:
    path = [100.0] + [100.0] * 8 + [110.4] + [112.0] * 16 + [109.8, 109.5]
    full = _decline() + path
    days = _weekdays(len(full))
    sale_index = 14 + 1 + 27
    peer_early = Download(as_of=days[sale_index], sessions=days, closes=[50.0] * len(days))
    peer_later = Download(
        as_of=days[sale_index] + timedelta(days=10), sessions=days, closes=[200.0] * len(days)
    )
    names = [
        _spec(full, ticker="AAA"),
        _spec([50.0] * len(full), ticker="BBB", downloads=[peer_early, peer_later]),
        _spec([50.0] * len(full), ticker="CCC"),
        _spec([50.0] * len(full), ticker="DDD"),
        _spec([50.0] * len(full), ticker="EEE"),
    ]
    episode = _one(_walk(*names))
    member = next(row for row in episode["basket"]["members"] if row["ticker"] == "BBB")
    assert member["exit"] == pytest.approx(50.0)


def test_a_gap_over_five_days_does_not_fill_and_each_market_has_its_own_cost() -> None:
    sessions = _weekdays(30)
    sessions.append(sessions[-1] + timedelta(days=7))
    closes = [200.0 + index for index in range(15)] + _decline() + [50.0]
    spec = _spec(closes, signal_index=29)
    spec.sessions = sessions
    spec.screens[0].run_date = sessions[28]
    spec.gates[0].as_of = sessions[28]
    spec.f9[0].as_of = sessions[29]
    result = _walk(spec)
    assert _primary(result) == []
    assert _kind(result, "gap_drop")

    left = _one(_walk(_spec(_decline() + [100.0, 110.0], market="ftse350")))
    right = _one(
        _walk(_spec(_decline() + [100.0, 110.0], market="sp500", ticker="SP")), COLUMN_PRIMARY, "SP"
    )
    ftse = costs_for_market("ftse350")
    sp = costs_for_market("sp500")
    assert left["fair_cost_return"] == pytest.approx(
        episode_return(100.0, 110.0, buy_cost_pct=ftse.buy_pct, sell_cost_pct=ftse.sell_pct)
    )
    assert right["fair_cost_return"] == pytest.approx(
        episode_return(100.0, 110.0, buy_cost_pct=sp.buy_pct, sell_cost_pct=sp.sell_pct)
    )
    assert left["fair_cost_return"] != pytest.approx(right["fair_cost_return"])


def test_ungraduated_library_names_and_foreign_runs_do_not_enter() -> None:
    closes = _decline() + [100.0, 104.0]
    blocked = _walk(_spec(closes, library=True, graduated=False, market="asx200"))
    assert blocked["episodes"] == []
    home = _spec(closes, ticker="AAA", market="ftse350")
    other = _spec(closes, ticker="BBB", market="sp500", library=True, graduated=True)
    other.screens = []
    walked = _walk(home, other)
    assert _primary(walked, "AAA")
    assert _primary(walked, "BBB") == []


def _control_spec(closes: list[float], **kwargs: object) -> NameSpec:
    spec = _spec(closes, signal_index=1, **kwargs)  # type: ignore[arg-type]
    fill = _weekdays(len(closes))[1]
    spec.memos = [
        MemoFact(
            finished_at=datetime.combine(fill, time(12), tzinfo=UTC),
            verdict="hold",
            rationale="fixture",
        )
    ]
    return spec


def test_buy_on_signal_ignores_timing_and_closes_on_the_first_rule() -> None:
    rising = [100.0 + index for index in range(80)]
    opened = _walk(_control_spec(rising))
    assert _primary(opened) == []
    control = _one(opened, COLUMN_BUY_ON_SIGNAL)
    assert control["column"] == COLUMN_BUY_ON_SIGNAL

    timed = [100.0 + index for index in range(90)]
    days = _weekdays(len(timed))
    held = _walk(
        _control_spec(
            timed,
            extra_screens=[
                ScreenFact(run_date=days[10], signal="hold", research_verdict="hold"),
                ScreenFact(run_date=days[12], signal="hold", research_verdict="hold"),
            ],
        )
    )
    episode = _one(held, COLUMN_BUY_ON_SIGNAL)
    assert episode["exit_reason"] == EXIT_INELIGIBLE_RUNS
    assert episode["exit_session"] == days[13].isoformat()

    long = _walk(_control_spec([100.0 + index for index in range(90)]))
    assert _one(long, COLUMN_BUY_ON_SIGNAL)["exit_reason"] == EXIT_HOLD_63


def test_gate_count_caps_a_week_and_the_median_uses_every_mature_episode() -> None:
    blob = b"fixture-bytes"
    digest = hashlib.sha256(blob).hexdigest()
    specs = []
    for index, sale in enumerate([110.0, 110.0, 110.0, 110.0, 90.0, 90.0, 90.0, 90.0, 50.0]):
        closes = _decline() + [100.0] + [100.0] * 63 + [sale]
        bad = index == 8
        specs.append(
            _spec(
                closes,
                ticker=f"N{index}",
                files={"tape.json": blob},
                committed={"tape.json": b"other"} if bad else {"tape.json": blob},
                paths=["tape.json"],
            )
        )
    result = _walk(*specs)
    mature = [row for row in _primary(result) if row["mature"]]
    assert len(mature) == 9
    assert result["boards"]["overall"]["count"] == 9
    assert result["boards"]["overall"]["median_fair_cost"] == pytest.approx(
        statistics.median([row["decision_return_floor"] for row in mature])
    )
    gate = result["boards"]["thickness_gate"]
    assert gate["counted"] == 6
    assert gate["counted_before_cap"] == 8
    assert gate["provenance_missing_excluded"] == 1
    good = next(row for row in mature if not row["provenance_missing"])
    assert good["inputs"]["entry"][0]["sha256"] == digest
    missing = next(row for row in mature if row["provenance_missing"])
    assert missing in result["episodes"]
    bench = result["boards"]["bench"]["fcf_agrees"]
    assert bench["provenance_missing_excluded"] >= 1
    assert bench["counted_mature"] == 8


def test_single_market_dependence_on_a_constructed_book() -> None:
    def _closed(ticker: str, market: str, sale: float) -> NameSpec:
        closes = _decline() + [100.0] + [100.0] * 63 + [sale]
        return _spec(
            closes, ticker=ticker, market=market, library=market != "ftse350", graduated=True
        )

    result = _walk(
        _closed("A", "ftse350", 120.0),
        _closed("B", "ftse350", 120.0),
        _closed("C", "ftse350", 120.0),
        _closed("D", "sp500", 70.0),
    )
    assert result["boards"]["overall"]["median_fair_cost"] > 0
    assert result["boards"]["single_market_dependence"] is True
    alone = _walk(_closed("A", "ftse350", 120.0))
    assert alone["boards"]["single_market_dependence"] is False


def test_capital_days_slot_book_and_buy_and_hold() -> None:
    hand = capital_days_return(
        [
            {"capital_return": 0.10, "stake": 100, "held_calendar_days": 100},
            {"capital_return": -0.05, "stake": 100, "held_calendar_days": 50},
        ]
    )
    assert hand == pytest.approx((10.0 - 5.0) / 15000.0 * 365.0)
    sample = _walk(_spec(_decline() + [100.0, 110.0]))
    assert sample["boards"]["capital_view"]["capital_days_return"] == pytest.approx(
        capital_days_return(_primary(sample))
    )

    crowd = [_spec(_decline() + [100.0, 110.0], ticker=f"S{index:02d}") for index in range(21)]
    booked = _walk(*crowd)
    slot = booked["boards"]["capital_view"]["slot_book"]
    assert slot["trades_taken"] == 20
    assert slot["trades_skipped"] == 1
    solo = _one(_walk(_spec(_decline() + [100.0, 110.0], ticker="S00")), COLUMN_PRIMARY, "S00")
    group = _one(booked, COLUMN_PRIMARY, "S00")
    assert group["fair_cost_return"] == pytest.approx(solo["fair_cost_return"])

    days = _weekdays(40)
    flat = [100.0] * 40
    first = _spec(
        flat,
        ticker="AAA",
        screens=[
            ScreenFact(
                run_date=days[5], signal="buy", adjusted_signal="buy", research_verdict="hold"
            )
        ],
        gates=[GateFact(as_of=days[5], decline="clear", sector="sound")],
        f9=True,
        memo=False,
    )
    second = _spec(
        flat,
        ticker="BBB",
        screens=[
            ScreenFact(
                run_date=days[20], signal="buy", adjusted_signal="buy", research_verdict="hold"
            )
        ],
        gates=[GateFact(as_of=days[20], decline="clear", sector="sound")],
        f9=True,
        memo=False,
    )
    # The helper dates F9 on the default signal index. Stamp it on the screen run.
    first.f9 = [
        F9Fact(
            as_of=days[6],
            key_filing_bodies=True,
            fcf_basis_bound=True,
            overlay_bound=True,
            memo_recent=True,
        )
    ]
    second.f9 = [
        F9Fact(
            as_of=days[21],
            key_filing_bodies=True,
            fcf_basis_bound=True,
            overlay_bound=True,
            memo_recent=True,
        )
    ]
    held = _walk(first, second)
    positions = held["boards"]["capital_view"]["buy_and_hold"]["positions"]
    assert positions["ftse350:AAA"]["stake"] == 100
    assert positions["ftse350:BBB"]["stake"] == 100
    assert positions["ftse350:BBB"]["entry_session"] > positions["ftse350:AAA"]["entry_session"]


def test_fcf_agrees_keeps_buy_and_strong_buy_only() -> None:
    closes = _decline() + [100.0, 104.0]
    rows = []
    for ticker, adjusted in (
        ("B", "buy"),
        ("S", "strong_buy"),
        ("H", "hold"),
        ("A", "avoid"),
        ("M", None),
    ):
        rows.append(_one(_walk(_spec(closes, ticker=ticker, adjusted=adjusted)), ticker=ticker))
    flags = {row["ticker"]: row["bench"]["fcf_agrees"] for row in rows}
    assert flags == {"B": True, "S": True, "H": False, "A": False, "M": False}


def test_review_insufficient_data_sells_a_launched_hold() -> None:
    path = [100.0] + [100.0] * 8 + [110.4] + [112.0] * 55
    closes = _decline() + path
    days = _weekdays(len(closes))
    review_day = days[15 + 63]
    result = _walk(
        _spec(
            closes,
            extra_gates=[
                GateFact(as_of=days[15 + 62], decline="insufficient_data", sector="sound")
            ],
        )
    )
    episode = _one(result)
    assert episode["exit_reason"] == EXIT_REVIEW_INSUFFICIENT
    assert episode["exit_signal_session"] == review_day.isoformat()


def test_archive_replay_keeps_three_results_and_refuses_a_bad_tape(tmp_path: Path) -> None:
    root = tmp_path / "data"
    days = _weekdays(32)
    closes = _decline(30) + [100.0, 104.0]
    _chart(root, "AAA", days[: len(closes)], closes, signal="buy", levels={"stop": 1})
    _run(
        root,
        "ftse350",
        days[10],
        [{"ticker": "AAA", "signal": "buy", "adjusted_signal": "buy", "research_verdict": "hold"}],
    )
    _chart(root, "NOCHART", days, [100.0] * len(days))
    # Buy-tier name with no chart file.
    _run(
        root,
        "ftse350",
        days[10],
        [
            {
                "ticker": "AAA",
                "signal": "buy",
                "adjusted_signal": "buy",
                "research_verdict": "hold",
            },
            {"ticker": "MISSING", "signal": "buy", "research_verdict": "hold"},
        ],
        prices={"AAA": 1.0, "MISSING": 1.0},
    )
    thin_days = [START + timedelta(days=2 * index) for index in range(20)]
    _chart(root, "THIN", thin_days, [100.0 - index for index in range(20)])
    _run(
        root,
        "ftse350",
        thin_days[1],
        [{"ticker": "THIN", "signal": "strong_buy", "research_verdict": "hold"}],
        prices={"THIN": 1.0},
    )
    gap_days = _gappy_days()
    _chart(root, "GAPPY", gap_days, [80.0 - index * 0.2 for index in range(len(gap_days))])
    _run(
        root,
        "ftse350",
        gap_days[1],
        [{"ticker": "GAPPY", "signal": "buy", "research_verdict": "hold"}],
        prices={"GAPPY": 1.0},
    )

    alt = [100.0] * 30
    alt[-10] = 70.0
    alt[-1] = 90.0
    alt_days = _weekdays(len(alt) + 1)
    _chart(root, "ALT", alt_days[: len(alt)] + [alt_days[len(alt)]], alt + [91.0])
    _run(
        root,
        "ftse350",
        alt_days[28],
        [{"ticker": "ALT", "signal": "buy", "adjusted_signal": "buy", "research_verdict": "hold"}],
        prices={"ALT": 1.0},
    )

    _write(
        root / "market_status.json",
        {
            "markets": [
                {"market_id": "sp500", "is_graduated": True},
                {"market_id": "asx200", "is_graduated": False},
            ]
        },
    )
    lib_days = _weekdays(20)
    _chart(root, "BBB", lib_days, _decline(len(lib_days)))
    _run(
        root,
        "sp500",
        lib_days[2],
        [{"ticker": "BBB", "signal": "buy", "research_verdict": "hold"}],
        prices={"BBB": 1.0},
    )
    _chart(root, "CCC", lib_days, _decline(len(lib_days)))
    _run(
        root,
        "asx200",
        lib_days[2],
        [{"ticker": "CCC", "signal": "buy", "research_verdict": "hold"}],
        prices={"CCC": 1.0},
    )

    after = (days[-1] + timedelta(days=3)).isoformat()
    _write(
        root / "operating_decline_gate.json",
        {
            "as_of": after,
            "names": {
                "AAA": {"market": "ftse350", "verdict": "clear"},
                "ALT": {"market": "ftse350", "verdict": "clear"},
            },
        },
    )
    _write(
        root / "sector_headwind_gate.json",
        {
            "as_of": after,
            "names_by_market": {
                "ftse350": {
                    "AAA": {"sector_verdict": "sound", "sector_basis": "own_market"},
                    "ALT": {"sector_verdict": "sound", "sector_basis": "own_market"},
                }
            },
        },
    )
    payload = run_replay(root)
    assert result_medians_are_separate(payload)
    assert set(payload) >= {
        ARCHIVE_BUY_TIER_ONLY,
        ARCHIVE_FULL_STRATEGY,
        LOOKAHEAD_CURRENT_GATES,
        "buy_on_signal",
        "alternative",
    }
    full = payload[ARCHIVE_FULL_STRATEGY]
    assert full["episodes"] == []
    assert full["boards"]["overall"]["count"] == 0
    buy = payload[ARCHIVE_BUY_TIER_ONLY]
    assert any(
        row["ticker"] == "AAA" and row["column"] == COLUMN_PRIMARY for row in buy["episodes"]
    )
    aaa = next(
        row for row in buy["episodes"] if row["ticker"] == "AAA" and row["column"] == COLUMN_PRIMARY
    )
    assert aaa["entry_fill_first_seen"] != pytest.approx(1.0)
    assert aaa["f9_status"] == "f9_unverified"
    assert any(
        row["ticker"] == "ALT" and row["column"] == COLUMN_ALTERNATIVE
        for row in payload["alternative"]["episodes"]
    )
    assert not any(row["column"] == COLUMN_ALTERNATIVE for row in full["episodes"])
    assert not any(
        row["column"] == COLUMN_ALTERNATIVE for row in payload[LOOKAHEAD_CURRENT_GATES]["episodes"]
    )
    assert any(
        row["ticker"] == "AAA" and row["column"] == COLUMN_PRIMARY
        for row in payload[LOOKAHEAD_CURRENT_GATES]["episodes"]
    )
    assert {"market": "ftse350", "ticker": "MISSING"} in payload["no_chart"]
    assert any(
        event.get("kind") == "thinned" and event.get("ticker") == "THIN" for event in buy["events"]
    )
    assert any(
        event.get("kind") == "chart_not_daily" and event.get("ticker") == "GAPPY"
        for event in buy["events"]
    )
    assert "asx200" in payload["skipped_ungraduated"]
    assert not any(row["ticker"] == "CCC" for row in buy["episodes"])
    assert any(row["ticker"] == "BBB" and row["market"] == "sp500" for row in buy["episodes"])
    assert not any(row["ticker"] == "BBB" and row["market"] == "ftse350" for row in buy["episodes"])
    assert payload["buy_on_signal"]["episodes"]
    assert payload["buy_on_signal"]["eligibility"] == ARCHIVE_BUY_TIER_ONLY


def test_signature_refusal_blocks_real_data_and_allows_a_fixture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    data = repo / "docs" / "data"
    data.mkdir(parents=True)
    outside = tmp_path / "fixture"
    outside.mkdir()
    assert registration_signed(data / "strategy_book_registration.json") is False
    _write(
        data / "strategy_book_registration.json",
        {"signed_at": "2026-11-05", "spend_enabled": False},
    )
    assert registration_signed(data / "strategy_book_registration.json") is True
    assert spend_enabled(data / "strategy_book_registration.json") is False
    data.joinpath("strategy_book_registration.json").unlink()

    assert replay_main(["--repo-root", str(repo)]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "registration_unsigned"
    assert observe_main(["--repo-root", str(repo), "--fixture-dir", str(data)]) == 2
    body = json.loads(capsys.readouterr().out)
    assert body["error"] == "registration_unsigned"
    assert "episodes" not in body
    assert replay_main(["--repo-root", str(repo), "--fixture-dir", str(outside)]) == 0
    allowed = json.loads(capsys.readouterr().out)
    assert allowed[ARCHIVE_FULL_STRATEGY]["episodes"] == []
    assert "error" not in allowed


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _chart(root: Path, ticker: str, days: list[date], closes: list[float], **extra: object) -> None:
    _write(
        root / "charts" / f"{ticker}.json",
        {"dates": [day.isoformat() for day in days], "closes": closes, **extra},
    )


def _run(root: Path, market: str, when: date, rows: list[dict], prices: dict | None = None) -> None:
    if market == "ftse350":
        dest = root / "history" / f"run_{when.strftime('%Y%m%d')}_120000.json"
    else:
        dest = (
            root
            / "library"
            / "markets"
            / market
            / "screen"
            / "history"
            / f"run_{when.strftime('%Y%m%d')}_120000.json"
        )
    _write(
        dest,
        {
            "run_at": datetime.combine(when, time(12), tzinfo=UTC).isoformat(),
            "prices": prices or {row["ticker"]: 1.0 for row in rows},
            "signals": rows,
        },
    )


def _gappy_days() -> list[date]:
    days = [START]
    for _ in range(18):
        days.append(days[-1] + timedelta(days=1))
    days.append(days[-1] + timedelta(days=6))
    days.append(days[-1] + timedelta(days=1))
    days.append(days[-1] + timedelta(days=6))
    return days


def _start_so_fill_is(fill: date, index: int = 15) -> date:
    cursor = fill
    seen = 0
    while seen < index:
        cursor -= timedelta(days=1)
        if cursor.weekday() < 5:
            seen += 1
    return cursor


def test_memo_uses_the_local_close_and_an_unknown_market_is_not_ready() -> None:
    closes = _decline() + [100.0, 104.0]
    days = _weekdays(len(closes))
    hk_close = session_close("hang_seng", days[15])
    before = _spec(closes, market="hang_seng", library=True, graduated=True, memo=False)
    before.memos = [
        MemoFact(
            finished_at=hk_close - timedelta(minutes=30),
            verdict="hold",
            rationale="before the HKEX close",
        )
    ]
    assert _one(_walk(before))["memo_verdict"] == "hold"
    after = _spec(closes, market="hang_seng", library=True, graduated=True, memo=False)
    after.memos = [
        MemoFact(
            finished_at=hk_close + timedelta(minutes=30),
            verdict="hold",
            rationale="after the HKEX close",
        )
    ]
    missed = _walk(after)
    assert _primary(missed) == []
    assert _kind(missed, "memo_not_ready")

    # 16:00 UTC is 17:00 in BST and 16:00 in GMT. London cash close is 16:30.
    summer = date(2026, 7, 1)
    winter = date(2026, 1, 7)
    assert session_close("ftse350", summer) == datetime(2026, 7, 1, 15, 30, tzinfo=UTC)
    assert session_close("ftse350", winter) == datetime(2026, 1, 7, 16, 30, tzinfo=UTC)
    for day, opens in ((summer, False), (winter, True)):
        spec = _spec(closes, start=_start_so_fill_is(day), memo=False)
        spec.memos = [
            MemoFact(
                finished_at=datetime.combine(day, time(16), tzinfo=UTC),
                verdict="hold",
                rationale="sixteen utc",
            )
        ]
        result = _walk(spec)
        if opens:
            assert _one(result)["fill_session"] == day.isoformat()
        else:
            assert _primary(result) == []
            assert _kind(result, "memo_not_ready")

    with pytest.raises(UnknownMarketClose):
        session_close("not_a_market", winter)
    unknown = _spec(closes, market="not_a_market", library=True, graduated=True)
    refused = _walk(unknown)
    assert _primary(refused) == []
    assert _kind(refused, "memo_not_ready")


def test_close_table_covers_the_graduated_markets() -> None:
    from value_investor.library_decision_input_inventory import graduated_market_ids
    from value_investor.market_paper_shard import MARKET_SESSION_DEFAULTS

    graduated = set(graduated_market_ids(Path("docs/data/market_status.json")))
    assert set(MARKET_CLOSE_LOCAL) == graduated | {"ftse350"}
    assert "euro_depth" not in MARKET_CLOSE_LOCAL
    assert "sp400" not in MARKET_CLOSE_LOCAL
    for market_id, (zone, _hhmm) in MARKET_CLOSE_LOCAL.items():
        if market_id in MARKET_SESSION_DEFAULTS:
            assert zone == MARKET_SESSION_DEFAULTS[market_id]["timezone"]


def _half_episode(day: date, ret: float, *, kept: bool, ticker: str) -> dict:
    return {
        "column": COLUMN_PRIMARY,
        "mature": True,
        "provenance_missing": False,
        "market": "ftse350",
        "ticker": ticker,
        "entry_week": entry_week(day),
        "fill_session": day.isoformat(),
        "signal_session": day.isoformat(),
        "decision_return_floor": ret,
        "capital_return": ret,
        "stake": 100,
        "held_calendar_days": 10,
        "bench": {"fcf_agrees": kept, "deep_dip": False, "revenue_growing": False},
        "status": "closed",
        "launched": True,
    }


def test_period_halves_put_the_middle_week_in_the_first_half() -> None:
    start = date.fromisocalendar(2026, 2, 1)
    even = [
        _half_episode(start + timedelta(weeks=index), 0.01, kept=True, ticker=f"E{index}")
        for index in range(4)
    ]
    first, second = period_halves(even)
    assert [row["entry_week"] for row in first] == [
        entry_week(start + timedelta(weeks=index)) for index in range(2)
    ]
    assert [row["entry_week"] for row in second] == [
        entry_week(start + timedelta(weeks=index)) for index in range(2, 4)
    ]
    odd = [
        _half_episode(start + timedelta(weeks=index), 0.01, kept=True, ticker=f"O{index}")
        for index in range(5)
    ]
    first, second = period_halves(odd)
    assert [row["ticker"] for row in first] == ["O0", "O1", "O2"]
    assert [row["ticker"] for row in second] == ["O3", "O4"]


def test_bench_promotion_fails_when_the_halves_disagree() -> None:
    start = date.fromisocalendar(2026, 2, 1)
    rows: list[dict] = []
    serial = 0
    for index in range(20):
        day = start + timedelta(weeks=index)
        wobble = 0.002 * ((index % 3) - 1)
        for _kept in range(4):
            rows.append(_half_episode(day, 0.20 + wobble, kept=True, ticker=f"K{serial}"))
            serial += 1
        if index < 10:
            for other in range(4):
                rows.append(_half_episode(day, 0.0, kept=False, ticker=f"A{index}-{other}"))
        else:
            rows.append(_half_episode(day, 0.50, kept=False, ticker=f"B{index}"))
    bar = build_boards(rows)["bench"]["fcf_agrees"]["promotion_bar"]
    assert bar["count_met"] is True
    assert bar["difference_met"] is True
    assert bar["capital_days_met"] is True
    assert bar["first_half_difference"] > 0
    assert bar["second_half_difference"] < 0
    assert bar["both_halves_same_sign"] is False
    assert bar["met"] is False
    fifths = build_boards(rows)["selection_fifths"]["composite_score"]
    assert set(fifths) == {"whole", "first_half", "second_half"}


# --- US rehearsal mode (strategy-book-us-rehearsal-v0) ----------------------------------------

_LADDER = [100.0] + [100.0] * 8 + [110.4] + [112.0] * 10 + [116.0] + [112.0] * 5 + [109.8, 109.5]


def _rehearsal(**overrides: object) -> WalkOptions:
    import dataclasses

    from value_investor.strategy_book_observe import options_for

    return dataclasses.replace(options_for("us_rehearsal"), **overrides)


def _tape(days: list[date], decline: str = "clear", sector: str = "sound") -> GateTape:
    labels = (None, "clear", "declining", "insufficient_data", "sound", "headwind")
    return GateTape(
        [day - timedelta(days=1) for day in days],
        [labels.index(decline)] * len(days),
        [labels.index(sector)] * len(days),
        labels,
        lambda index: {"sector_basis": "price_only", "checks": {"revenue": {"change_pct": 0.02}}},
    )


def _us(closes: list[float], **kwargs: object) -> NameSpec:
    gates = kwargs.pop("gates", None)
    spec = _spec(
        closes, market=kwargs.pop("market", "sp500"), adjusted=None, research=None, **kwargs
    )
    if gates is not None:
        spec.gates = gates
    return spec


def test_a_gate_tape_walks_like_the_gate_facts_it_encodes() -> None:
    closes = _decline() + _LADDER
    days = _weekdays(len(closes))
    facts = [
        GateFact(as_of=day - timedelta(days=1), decline="clear", sector="sound") for day in days
    ]
    by_list = walk_book([_us(closes, gates=facts)], options=_rehearsal())
    by_tape = walk_book([_us(closes, gates=_tape(days))], options=_rehearsal())
    keep = (
        "column",
        "signal_session",
        "fill_session",
        "exit_reason",
        "exit_fill",
        "fair_cost_return",
    )
    assert [{k: row[k] for k in keep} for row in by_list["episodes"]] == [
        {k: row[k] for k in keep} for row in by_tape["episodes"]
    ]
    assert any(row["column"] == COLUMN_PRIMARY for row in by_tape["episodes"])
    declining = walk_book(
        [_us(closes, gates=_tape(days, decline="declining"))], options=_rehearsal()
    )
    assert [row for row in declining["episodes"] if row["column"] == COLUMN_PRIMARY] == []
    assert any(row["column"] == COLUMN_DECLINE_SHADOW for row in declining["episodes"])


def test_rehearsal_mode_labels_and_needs_no_memo_or_f9() -> None:
    closes = _decline() + _LADDER
    days = _weekdays(len(closes))
    result = walk_book([_us(closes, gates=_tape(days), memo=False, f9=False)], options=_rehearsal())
    episode = _one(result)
    assert episode["t212_listed"] == "not_applicable"
    assert episode["f9_status"] == "f9_unverified"
    assert episode["basket"]["members"] is None
    assert result["boards"] is None
    assert episode["bench"]["revenue_growing"] is True


def test_leaving_the_universe_stops_entry_and_keeps_an_open_episode() -> None:
    closes = _decline() + _LADDER
    days = _weekdays(len(closes))
    outside = _us(closes, gates=_tape(days))
    outside.universe = [(days[0], days[13])]
    assert _primary(walk_book([outside], options=_rehearsal())) == []
    held = _us(closes, gates=_tape(days))
    held.universe = [(days[0], days[15])]
    episode = _one(walk_book([held], options=_rehearsal()))
    assert episode["exit_reason"] == EXIT_FLOOR


def test_one_book_key_is_one_name_across_two_universes() -> None:
    closes = _decline() + _LADDER
    days = _weekdays(len(closes))
    big = _us(closes, gates=_tape(days), market="sp500")
    mid = _us(closes, gates=_tape(days), market="sp400")
    apart = walk_book([big, mid], options=_rehearsal())
    assert {row["market"] for row in _primary(apart)} == {"sp500", "sp400"}
    big.book_key = mid.book_key = "AAA"
    shared = walk_book([big, mid], options=_rehearsal())
    assert [row["market"] for row in _primary(shared)] == ["sp500"]


def test_a_delisted_name_exits_at_its_last_bar_with_the_haircut() -> None:
    closes = _decline() + [100.0, 101.0, 102.0, 101.5]
    days = _weekdays(len(closes))
    dead = _us(closes, gates=_tape(days), ticker="DEAD")
    dead.terminal_haircut = -0.30
    longer = _decline() + [100.0] * 30
    alive = _us(longer, gates=_tape(_weekdays(len(longer))), ticker="LIVE", signal="hold")
    result = walk_book([dead, alive], options=_rehearsal())
    episode = _one(result, ticker="DEAD")
    assert episode["exit_reason"] == "delisted"
    assert episode["exit_session"] == days[-1].isoformat()
    assert episode["exit_fill"] == pytest.approx(101.5 * 0.7)
    survivor = _us(closes, gates=_tape(days), ticker="DEAD")
    kept_open = _one(walk_book([survivor, alive], options=_rehearsal()), ticker="DEAD")
    assert kept_open["status"] == "open"


def test_entry_not_after_stops_new_signals_and_not_exits() -> None:
    closes = _decline() + _LADDER
    days = _weekdays(len(closes))
    late = walk_book([_us(closes, gates=_tape(days))], options=_rehearsal(entry_not_after=days[13]))
    assert _primary(late) == []
    on_time = walk_book(
        [_us(closes, gates=_tape(days))], options=_rehearsal(entry_not_after=days[14])
    )
    assert _one(on_time)["exit_reason"] == EXIT_FLOOR


def test_a_blank_carried_row_is_not_on_the_screen_for_the_basket() -> None:
    base = _decline() + _LADDER
    days = _weekdays(len(base))
    flat = [50.0] * len(base)
    names = [_us(base, gates=_tape(days))]
    for index in range(2):
        names.append(_us(flat, ticker=f"B{index}", gates=_tape(days)))
    for index in range(2):
        names.append(_us(flat, ticker=f"H{index}", signal="hold", gates=_tape(days)))
    names.append(_us(flat, ticker="GONE", signal=None, gates=_tape(days)))
    counted = _one(walk_book(names, options=_rehearsal(basket_skips_blank_screen=False)))
    skipped = _one(walk_book(names, options=_rehearsal()))
    assert counted["basket"]["count"] == 6
    assert skipped["basket"]["count"] == 5
    assert skipped["basket"]["fallback"] is True


def _batch_book(seed: int) -> list[NameSpec]:
    """Random US-rehearsal book: two markets, shared book keys, delistings, spans."""
    import random

    rng = random.Random(seed)
    days: list[date] = []
    day = date(1999, 1, 4)
    while len(days) < 900:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    month_ends = [days[i] for i in range(len(days) - 1) if days[i].month != days[i + 1].month]
    labels = (None, "clear", "declining", "insufficient_data", "sound", "headwind")
    specs: list[NameSpec] = []
    for index in range(36):
        ticker = f"B{index:02d}"
        start = 0 if index % 5 else rng.randrange(0, 300)
        stop = len(days) if index % 7 else rng.randrange(500, len(days))
        sessions = days[start:stop]
        price, closes = 50.0 + index, []
        for _ in sessions:
            price *= 1.0 + rng.gauss(0.0003, 0.025)
            closes.append(round(price, 4))
        markets = ["sp500"] if index < 14 else ["sp400"]
        if index in (10, 11, 20, 21):
            markets = ["sp500", "sp400"]
        cut = len(sessions) // 2
        for market in markets:
            screens = [
                ScreenFact(
                    run_date=end,
                    signal=rng.choice(["buy", "strong_buy", "hold", "avoid", "hold", None]),
                    sector="Tech",
                    fields={"composite_score": rng.random(), "weeks_at_signal": 2},
                )
                for end in month_ends
                if sessions and sessions[0] <= end <= sessions[-1]
            ]
            if len(markets) == 2:
                universe = (
                    [(sessions[0], sessions[cut - 1])]
                    if market == "sp500"
                    else [(sessions[cut], sessions[-1])]
                )
            else:
                universe = [(sessions[0], sessions[-1])] if index % 9 else []
            specs.append(
                NameSpec(
                    market=market,
                    ticker=ticker,
                    downloads=[Download(as_of=sessions[-1], sessions=sessions, closes=closes)],
                    screens=screens,
                    gates=GateTape(
                        [d - timedelta(days=1) for d in sessions],
                        [rng.choice([1, 1, 1, 2, 3]) for _ in sessions],
                        [rng.choice([4, 4, 4, 5]) for _ in sessions],
                        labels,
                        lambda i: {"sector_basis": "price_only", "checks": {}},
                    ),
                    universe=universe,
                    book_key=ticker,
                    terminal_haircut=0.0 if stop < len(days) else None,
                )
            )
    return specs


def _batched(
    specs: list[NameSpec], options: WalkOptions, size: int, haircut=None, walked=None
) -> dict:
    from value_investor.strategy_book_observe import CrossNameTape, recovery_cap

    walked = walked or specs

    groups: dict[str, list[int]] = {}
    for position, spec in enumerate(specs):
        groups.setdefault(spec.book_key or spec.ticker, []).append(position)
    batches: list[list[int]] = [[]]
    for members in groups.values():
        if batches[-1] and len(batches[-1]) + len(members) > size:
            batches.append([])
        batches[-1].extend(members)
    cross = CrossNameTape(options)
    for batch in batches:
        cross.add([specs[i] for i in batch])
    cross.finish()
    if haircut is not None:
        cross = cross.with_haircuts(haircut)
    order = {(spec.market, spec.ticker): i for i, spec in enumerate(specs)}
    episodes, events, counts = [], [], {}
    opened = [0] * len(cross.calendar)
    labelled = [0] * len(cross.calendar)
    for batch in batches:
        part = walk_book([walked[i] for i in batch], options=options, cross=cross)
        episodes.extend(part["episodes"])
        events.extend(part["events"])
        for key, value in part["counts"].items():
            counts[key] = counts.get(key, 0) + value
        opened = [a + b for a, b in zip(opened, part["recovery_open"], strict=True)]
        labelled = [a + b for a, b in zip(labelled, part["recovery_labelled"], strict=True)]
    episodes.sort(key=lambda row: order[(row["market"], row["ticker"])])
    cap_days, samples = recovery_cap(cross.calendar, opened, labelled)
    return {
        "episodes": episodes,
        "events": events,
        "counts": counts,
        "cap_would_block_days": cap_days,
        "recovery_share_samples": samples,
    }


@pytest.mark.parametrize("seed", [3, 11])
def test_a_batched_walk_matches_the_whole_book(seed: int) -> None:
    import dataclasses

    specs = _batch_book(seed)
    options = _rehearsal(entry_not_before=date(1999, 9, 1), entry_not_after=date(2002, 3, 29))
    whole = walk_book(specs, options=options)
    assert len(whole["episodes"]) > 50
    assert {e["basket"]["source"] for e in whole["episodes"] if e["basket"]} >= {"buy_tier"}

    def canon(rows: list[dict]) -> list[str]:
        return sorted(json.dumps(row, default=str, sort_keys=True) for row in rows)

    for size in (1, 7, 1000):
        part = _batched(specs, options, size)
        assert json.dumps(part["episodes"], default=str) == json.dumps(
            whole["episodes"], default=str
        )
        assert canon(part["events"]) == canon(whole["events"])
        assert part["counts"] == whole["counts"]
        assert part["cap_would_block_days"] == whole["cap_would_block_days"]
        assert part["recovery_share_samples"] == whole["recovery_share_samples"]

    cut = {spec.ticker: -0.3 for spec in specs if spec.terminal_haircut is not None}
    variant = [dataclasses.replace(s, terminal_haircut=cut.get(s.ticker)) for s in specs]
    whole_variant = walk_book(variant, options=options)
    part = _batched(specs, options, 5, haircut=cut.get, walked=variant)
    assert json.dumps(part["episodes"], default=str) == json.dumps(
        whole_variant["episodes"], default=str
    )
    assert json.dumps(part["episodes"], default=str) != json.dumps(whole["episodes"], default=str)


def test_a_batched_walk_refuses_a_split_book_key() -> None:
    from value_investor.strategy_book_observe import CrossNameTape

    specs = _batch_book(3)
    options = _rehearsal(entry_not_before=date(1999, 9, 1))
    cross = CrossNameTape(options)
    cross.add(specs)
    cross.finish()
    shared = [spec for spec in specs if spec.ticker == "B10"]
    with pytest.raises(ValueError, match="split across batches"):
        walk_book(shared[:1], options=options, cross=cross)
    with pytest.raises(ValueError, match="boards off"):
        walk_book(shared, options=_rehearsal(boards=True), cross=cross)
