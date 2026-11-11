"""Step 3.2 proof board: seven bars, point-in-time FX, sealed-section hash."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from value_investor.ops_monitor import check_strategy_book_proof, collect_ops_findings
from value_investor.strategy_book_proof import (
    BAR_ORDER,
    BOOTSTRAP_SEED,
    OWNER_NOTE,
    UNCERTAINTY_DRAWS,
    FxHistory,
    block_bootstrap_medians,
    build_proof_board,
    evaluate_population,
    findings_for_store,
    linear_percentile,
    main,
    seal_phrase_problems,
    sealed_section_sha256,
    sterling_return,
)
from value_investor.strategy_book_rules import REGISTRATION_STORE_NAME

ROOT = Path(__file__).resolve().parents[1]
SEALED_HASH = "4e99e9ad1b741a6fc8816575f1fcf6a9ac717c5693ad0244b9e46f9c7a207349"


def _episode(
    ticker: str,
    *,
    market: str = "ftse350",
    excess: float | None = 0.04,
    fair: float | None = 0.08,
    basket: float | None = 0.01,
    regime: str = "above",
    listed: bool | str = True,
    week: str = "2026-W30",
    fill: str = "2026-07-21",
    exit_on: str | None = "2026-08-18",
    provenance: bool = False,
    mature: bool = True,
    column: str = "primary",
    currency: str = "GBP",
    fallback: bool = False,
    source: str = "buy_tier",
    status: str = "closed",
    decision: float | None = None,
) -> dict:
    basket_row = None
    if basket is not None or fallback or source:
        basket_row = {
            "source": source,
            "fallback": fallback,
            "basket_gross": basket,
            "count": 8,
        }
    return {
        "episode_id": f"{market}:{ticker}:{column}:{fill}",
        "market": market,
        "ticker": ticker,
        "column": column,
        "status": status,
        "mature": mature,
        "provenance_missing": provenance,
        "fill_session": fill,
        "exit_session": exit_on,
        "entry_week": week,
        "matched_excess": excess,
        "fair_cost_return": fair,
        "decision_return_floor": fair if decision is None else decision,
        "basket": basket_row,
        "regime": regime,
        "t212_listed": listed,
        "currency": currency,
    }


def _passing_book() -> list[dict]:
    """24 counted episodes that clear every bar in sterling without FX."""
    rows = []
    for index in range(24):
        above = index < 12
        market = "ftse350" if index < 13 else "sp500"
        # 12 above (7 FTSE + 5 US) and 12 below (6 FTSE + 6 US). FTSE is larger.
        if above:
            market = "ftse350" if index < 7 else "sp500"
        else:
            market = "ftse350" if index < 19 else "sp500"
        rows.append(
            _episode(
                f"T{index:02d}",
                market=market,
                regime="above" if above else "below",
                week=f"2026-W{28 + (index % 4):02d}",
                currency="GBP" if market == "ftse350" else "GBP",
            )
        )
    return rows


def _fx() -> FxHistory:
    return FxHistory({})


def _board(episodes: list[dict], **kwargs) -> dict:
    return evaluate_population(episodes, fx=_fx(), bootstrap_draws=30, **kwargs)


def test_linear_percentile_matches_rank_rule() -> None:
    assert linear_percentile([10.0], 5) == 10.0
    # rank = 0.05 * 19 = 0.95, between the first and second sorted values.
    values = [-0.50] + [0.0] * 19
    assert linear_percentile(values, 5) == pytest.approx(-0.50 * 0.05)


def test_all_seven_bars_pass_and_overall_requires_every_bar() -> None:
    board = _board(_passing_book())
    assert board["n"] == 24
    assert board["all_bars_met"] is True
    assert board["verdict"] == "all_bars_met"
    assert board["influences_live"] is False
    assert board["opens_live_capital"] is False
    assert OWNER_NOTE in board["owner_note"]
    for key in BAR_ORDER:
        assert board["bars"][key]["verdict"] == "pass", key
    failed = _board([_episode("Z", excess=-0.2, fair=-0.5, decision=-0.5)])
    assert failed["all_bars_met"] is False
    assert failed["verdict"] == "not_met"


def test_each_bar_fail_and_insufficient() -> None:
    uncertainty_fail = _board(
        [_episode("A", excess=-0.05), _episode("B", excess=-0.04, week="2026-W31")]
    )
    assert uncertainty_fail["bars"]["uncertainty"]["verdict"] == "fail"

    tail_fail = _board([_episode("A", decision=-0.25, fair=-0.25)])
    assert tail_fail["bars"]["tail_loss"]["verdict"] == "fail"
    tail_edge = _board([_episode("A", decision=-0.20, fair=-0.20)])
    assert tail_edge["bars"]["tail_loss"]["verdict"] == "pass"
    assert tail_edge["bars"]["tail_loss"]["statistic"]["fair_cost_percentile_5"] == -0.20

    drawdown_fail = _board([_episode("A", fair=-0.50, basket=-0.05, excess=0.02)])
    assert drawdown_fail["bars"]["drawdown"]["verdict"] == "fail"
    slot_fall = drawdown_fail["bars"]["drawdown"]["statistic"]["slot_fall"]
    basket_fall = drawdown_fail["bars"]["drawdown"]["statistic"]["basket_fall"]
    assert slot_fall > 1.5 * basket_fall

    sterling_fail = _board([_episode("A", fair=0.01, basket=0.20, excess=0.02)])
    assert sterling_fail["bars"]["sterling_slot_book"]["verdict"] == "fail"

    market_fail = _board(
        [
            _episode("A", market="ftse350", excess=0.2),
            _episode(
                "B",
                market="ftse350",
                excess=0.2,
            ),
            _episode("C", market="sp500", excess=-0.1, currency="GBP"),
        ]
    )
    assert market_fail["bars"]["market_spread"]["verdict"] == "fail"
    assert market_fail["bars"]["market_spread"]["statistic"]["removed_market"] == "ftse350"

    market_zero = _board(
        [
            _episode("A", market="ftse350", excess=0.2),
            _episode(
                "B",
                market="ftse350",
                excess=0.2,
            ),
            _episode("C", market="sp500", excess=0.0, currency="GBP"),
        ]
    )
    assert market_zero["bars"]["market_spread"]["verdict"] == "fail"

    one_market = _board(
        [
            _episode("A"),
            _episode(
                "B",
            ),
        ]
    )
    assert one_market["bars"]["market_spread"]["verdict"] == "insufficient_data"

    regime_fail = _board(
        [_episode(f"A{i}", regime="above", excess=-0.01) for i in range(12)]
        + [_episode(f"B{i}", regime="below", excess=0.02, market="sp500") for i in range(12)]
    )
    assert regime_fail["bars"]["regime_spread"]["verdict"] == "fail"

    regime_short = _board(
        [_episode(f"A{i}", regime="above", excess=0.02) for i in range(12)]
        + [_episode(f"B{i}", regime="below", excess=0.02, market="sp500") for i in range(11)]
    )
    assert regime_short["bars"]["regime_spread"]["verdict"] == "insufficient_data"

    empty = _board([])
    for key in BAR_ORDER:
        assert empty["bars"][key]["verdict"] == "insufficient_data"
    assert empty["verdict"] == "insufficient_data"
    assert empty["all_bars_met"] is False

    no_excess = _board([_episode("A", excess=None)])
    assert no_excess["bars"]["uncertainty"]["verdict"] == "insufficient_data"
    no_fair = _board([_episode("A", fair=None, decision=None)])
    assert no_fair["bars"]["tail_loss"]["verdict"] == "insufficient_data"


def test_regime_unknown_sits_out_and_does_not_spoil_a_pass() -> None:
    rows = [_episode(f"A{i}", regime="above", excess=0.03) for i in range(12)]
    rows += [_episode(f"B{i}", regime="below", excess=0.03, market="sp500") for i in range(12)]
    rows += [
        _episode(f"U{i}", regime="regime_unknown", excess=-0.80, market="asx200") for i in range(15)
    ]
    board = _board(rows)
    regime = board["bars"]["regime_spread"]
    assert regime["verdict"] == "pass"
    assert regime["statistic"]["regime_unknown_sitting_out"] == 15
    assert regime["statistic"]["above"]["n"] == 12
    assert regime["statistic"]["below"]["n"] == 12
    assert regime["statistic"]["above"]["median_matched_excess"] > 0


def test_provenance_missing_is_excluded_from_the_largest_market() -> None:
    rows = [
        _episode("A", market="ftse350", excess=0.20),
        _episode(
            "B",
            market="ftse350",
            excess=0.20,
        ),
        _episode("C", market="sp500", excess=-0.40, currency="GBP"),
    ]
    rows += [
        _episode(
            f"P{i}",
            market="sp500",
            excess=-0.90,
            provenance=True,
            currency="GBP",
        )
        for i in range(8)
    ]
    board = _board(rows)
    assert board["provenance_missing_excluded"] == 8
    assert board["n"] == 3
    market = board["bars"]["market_spread"]
    assert market["statistic"]["removed_market"] == "ftse350"
    assert market["verdict"] == "fail"
    immature = _board([_episode("Q", mature=False, excess=5)])
    assert immature["n"] == 0
    other_column = _board([_episode("Q", column="buy_on_signal", excess=5)])
    assert other_column["n"] == 0
    pending = _board([_episode("Q", status="pending_fill")])
    assert pending["n"] == 0
    assert pending["pending_fill_excluded"] == 1


def test_tradable_subset_uses_only_listed_episodes() -> None:
    unknown = _board([_episode("A", listed="unknown", excess=0.5)])
    assert unknown["bars"]["tradable_subset"]["verdict"] == "insufficient_data"
    negative = _board([_episode("A", listed=True, excess=-0.01)])
    assert negative["bars"]["tradable_subset"]["verdict"] == "fail"
    positive = _board(
        [
            _episode("A", listed=True, excess=0.02),
            _episode(
                "B",
                listed=False,
                excess=-0.50,
            ),
            _episode(
                "C",
                listed="unknown",
                excess=-0.50,
            ),
        ]
    )
    assert positive["bars"]["tradable_subset"]["verdict"] == "pass"
    assert positive["bars"]["tradable_subset"]["n"] == 1


def test_block_bootstrap_is_deterministic_and_moves_whole_weeks() -> None:
    weeks = {"2026-W28": [0.0, 1.0], "2026-W29": [0.2]}
    first = block_bootstrap_medians(weeks, draws=UNCERTAINTY_DRAWS, seed=BOOTSTRAP_SEED)
    second = block_bootstrap_medians(weeks, draws=UNCERTAINTY_DRAWS, seed=BOOTSTRAP_SEED)
    assert first == second
    assert len(first) == UNCERTAINTY_DRAWS
    # A drawn week keeps both of its values, so a median of 0 (three zeros) cannot occur.
    assert 0.0 not in first
    assert set(first) <= {0.2, 0.5}
    assert 0.2 in first and 0.5 in first
    other = block_bootstrap_medians(weeks, draws=UNCERTAINTY_DRAWS, seed=BOOTSTRAP_SEED + 1)
    assert other != first


def test_point_in_time_fx_uses_as_of_not_a_later_spot(tmp_path: Path) -> None:
    macro = tmp_path / "docs" / "data" / "library" / "macro"
    macro.mkdir(parents=True)

    def _snap(name: str, as_of: str, gbp_usd: float) -> None:
        payload = {
            "domains": {
                "uk": {"markers": {"gbp_usd": {"value": gbp_usd, "as_of": as_of}}},
            }
        }
        (macro / name).write_text(json.dumps(payload), encoding="utf-8")

    _snap("2026-01-02.json", "2026-01-01T00:00:00+00:00", 1.50)
    _snap("2026-01-03.json", "2026-01-01T00:00:00+00:00", 9.99)
    _snap("2026-06-02.json", "2026-06-01T22:00:00+00:00", 1.20)
    # File name is January, but the quote is February: not usable in January.
    _snap("2026-01-01.json", "2026-02-01T00:00:00+00:00", 1.40)
    history = FxHistory.load(tmp_path)
    # 15 Jan: the January quote (1.50), not its later restatement (9.99)
    # and not the February quote stored in a file named 1 Jan.
    early, early_reason = history.gbp_per_unit("USD", date(2026, 1, 15))
    assert early_reason == ""
    assert early == 1.0 / 1.50
    march, _march_reason = history.gbp_per_unit("USD", date(2026, 3, 1))
    assert march == 1.0 / 1.40
    later, _later_reason = history.gbp_per_unit("USD", date(2026, 7, 1))
    assert later == 1.0 / 1.20
    missing, missing_reason = history.gbp_per_unit("USD", date(2025, 12, 1))
    assert missing is None
    assert "2025-12-01" in missing_reason
    chf, chf_reason = history.gbp_per_unit("CHF", date(2026, 7, 1))
    assert chf is None
    assert "CHF" in chf_reason
    gbp, gbp_reason = history.gbp_per_unit("GBP", date(2020, 1, 1))
    assert gbp == 1.0
    assert gbp_reason == ""

    flat, _flat_reason = sterling_return(0.0, "USD", date(2026, 3, 1), date(2026, 3, 15), history)
    assert flat == 0.0
    gained, _gained_reason = sterling_return(
        0.0, "USD", date(2026, 5, 1), date(2026, 7, 1), history
    )
    # May still sees the February quote; July sees June. June is not used early.
    assert gained == (1.40 / 1.20) - 1.0


def test_missing_fx_makes_sterling_bars_insufficient_data() -> None:
    rows = [_episode("USD1", market="sp500", currency="USD", fair=0.10, basket=0.01, excess=0.05)]
    board = evaluate_population(rows, fx=FxHistory({}), bootstrap_draws=5)
    for key in ("drawdown", "sterling_slot_book"):
        assert board["bars"][key]["verdict"] == "insufficient_data"
        assert any("GBPUSD" in reason for reason in board["bars"][key]["reasons"])
        assert board["bars"][key]["statistic"] is None


def test_whole_screen_fallback_is_the_sealed_matched_basket() -> None:
    rows = [_episode("A", fallback=True, source="whole_screen")]
    board = _board(rows)
    for key in ("drawdown", "sterling_slot_book"):
        assert board["bars"][key]["verdict"] in {"pass", "fail"}
        assert board["bars"][key]["statistic"] is not None


def test_archive_pass_does_not_set_the_forward_verdict(tmp_path: Path) -> None:
    board = build_proof_board(
        tmp_path,
        fx=_fx(),
        forward_episodes=[],
        archive_episodes=_passing_book(),
        scoring_date=date(2026, 8, 18),
        now=datetime(2026, 11, 11, tzinfo=UTC),
    )
    assert board["forward"]["all_bars_met"] is False
    assert board["all_bars_met"] is False
    assert board["archive_replay_report_only"]["not_proof"] is True
    assert board["archive_replay_report_only"]["survivorship_biased"] is True
    assert board["archive_replay_report_only"]["label"] == "archive_replay_report_only"
    assert board["opens_live_capital"] is False
    assert board["influences_live"] is False


def test_sealed_section_hash_and_phrase_check() -> None:
    plan = (ROOT / "docs/ops/strategy-reorientation-plan.md").read_text(encoding="utf-8")
    assert sealed_section_sha256(plan) == SEALED_HASH
    registration = json.loads(
        (ROOT / "docs" / "data" / REGISTRATION_STORE_NAME).read_text(encoding="utf-8")
    )
    sealed = registration["sealed_documents"]["docs/ops/strategy-reorientation-plan.md"]
    assert sealed["section_sha256"] == SEALED_HASH
    rows = [
        {"requirement": row["requirement"], "bar": row["bar"]}
        for row in registration["step_3_2_proof_numbers"]
    ]
    assert seal_phrase_problems(rows) == []


def test_build_on_committed_data_does_not_touch_sealed_inputs() -> None:
    observe = ROOT / "docs/data/strategy_book_observe.json"
    registration = ROOT / "docs/data/strategy_book_registration.json"
    plan = ROOT / "docs/ops/strategy-reorientation-plan.md"
    before = (observe.read_bytes(), registration.read_bytes(), plan.read_bytes())
    board = build_proof_board(ROOT, now=datetime(2026, 11, 11, 12, tzinfo=UTC))
    assert (observe.read_bytes(), registration.read_bytes(), plan.read_bytes()) == before
    assert board["seal_ok"] is True
    assert board["sealed_section_sha256"] == SEALED_HASH
    assert board["influences_live"] is False
    assert board["opens_live_capital"] is False
    assert board["owner_may_consider_step"] == "5.5"
    assert set(board["forward"]["bars"]) == set(BAR_ORDER)
    archive = board["archive_replay_report_only"]
    assert archive["not_proof"] is True
    assert archive["survivorship_biased"] is True
    if archive.get("n"):
        assert archive["bars"]["uncertainty"]["statistic"]["draws"] == UNCERTAINTY_DRAWS
        assert archive["bars"]["uncertainty"]["statistic"]["seed"] == BOOTSTRAP_SEED
    source = inspect.getsource(build_proof_board)
    module = (ROOT / "src/value_investor/strategy_book_proof.py").read_text(encoding="utf-8")
    assert "fetch_fx_rates(" not in module
    assert "yfinance" not in module
    assert OBSERVE_WRITE_GUARD not in source


OBSERVE_WRITE_GUARD = "strategy_book_observe.json"


def test_cli_writes_the_proof_store_only(tmp_path: Path, capsys) -> None:
    data = tmp_path / "docs" / "data"
    data.mkdir(parents=True)
    observe = data / "strategy_book_observe.json"
    observe.write_text(
        json.dumps(
            {
                "episodes": [],
                "generated_at": "2026-11-11T00:00:00+00:00",
                "scoring_date": "2026-11-11",
            }
        ),
        encoding="utf-8",
    )
    before = observe.read_bytes()
    assert main(["--repo-root", str(tmp_path)]) == 0
    assert observe.read_bytes() == before
    written = json.loads((data / "strategy_book_proof_board.json").read_text(encoding="utf-8"))
    assert written["influences_live"] is False
    assert written["forward"]["all_bars_met"] is False
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == written["verdict"]


def test_ops_monitor_warns_only_when_the_store_is_unusable(tmp_path: Path) -> None:
    missing = check_strategy_book_proof(repo_root=tmp_path, now=datetime(2026, 11, 11, tzinfo=UTC))
    assert missing[0].title == "Strategy book proof board missing"
    assert missing[0].severity == "warn"
    assert missing[0].auto_fixable is False

    path = tmp_path / "docs" / "data" / "strategy_book_proof_board.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    broken = check_strategy_book_proof(repo_root=tmp_path, now=datetime(2026, 11, 11, tzinfo=UTC))
    assert broken[0].title == "Strategy book proof board unreadable"
    assert broken[0].auto_fixable is False

    fresh = {
        "generated_at": "2026-11-11T00:00:00+00:00",
        "verdict": "insufficient_data",
        "forward": {"bars_passed": 0, "n": 0, "verdict": "insufficient_data"},
    }
    path.write_text(json.dumps(fresh), encoding="utf-8")
    info = check_strategy_book_proof(repo_root=tmp_path, now=datetime(2026, 11, 12, tzinfo=UTC))
    assert info[0].title == "Strategy book proof board"
    assert info[0].severity == "info"
    assert info[0].auto_fixable is False
    assert "0 of 7" in info[0].summary
    assert "n=0" in info[0].summary
    assert "step 5.5" in info[0].summary

    stale_at = (datetime(2026, 11, 11, tzinfo=UTC) - timedelta(days=6)).isoformat()
    path.write_text(
        json.dumps({**fresh, "generated_at": stale_at}),
        encoding="utf-8",
    )
    stale = findings_for_store(tmp_path, now=datetime(2026, 11, 11, tzinfo=UTC))
    assert stale[0]["title"] == "Strategy book proof board stale"
    assert stale[0]["auto_fixable"] is False
    assert "check_strategy_book_proof" in inspect.getsource(collect_ops_findings)
