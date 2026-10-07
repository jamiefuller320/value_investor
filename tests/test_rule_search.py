"""Pre-registered rule search (hrs-v1) on synthetic replay inputs (no licensed rows)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from value_investor import historical_screen_replay as hsr
from value_investor import rule_search as rs
from value_investor.technical_analysis import TradePlanConfig

TICKERS = [f"S{i:02d}" for i in range(24)]
DELISTED = "S11"


def _registration() -> dict:
    reg = rs.load_registration()
    reg = json.loads(json.dumps(reg))
    reg["windows"] = {
        "development": {"first_entry": "2000-01-31", "last_entry": "2001-12-31"},
        "holdout": {"first_entry": "2002-01-31", "last_entry": "2002-12-31"},
    }
    reg["grid"]["selection"] = {
        "tier": ["buy_tier", "strong_buy"],
        "top_n": [None, 4],
        "exit_rule": ["tier1", "tier3", "rerate50", "thesis"],
    }
    reg["grid"]["tactical"].update(limit=["default", "deep"], stop=["default"], target=["default"])
    reg["overfitting"]["cscv_blocks"] = 4
    reg["objective"]["horizon_months"] = 12
    reg["objective"]["report_horizons_months"] = [3, 12]
    reg["screen_code_fingerprint"] = hsr.screen_code_fingerprint()
    reg["rule_code_fingerprint"] = rs.rule_code_fingerprint()
    return reg


def _signal(i: int, month: int) -> str:
    if i == 5 and month % 4 == 2:
        return "hold"  # a buy name that dips out of the tier for one screen
    if 12 <= i < 16:
        return "buy" if month < 8 else "hold"  # re-rated: left the tier for good
    if i < 4:
        return "strong_buy"
    if i < 12:
        return "buy"
    if i < 20:
        return "hold"
    return "avoid" if month % 2 else "hold"


def _build(root: Path) -> Path:
    rng = np.random.default_rng(11)
    days = pd.bdate_range("1998-06-01", "2003-01-31")
    month_ends = pd.Series(days).groupby(days.to_period("M")).max()
    screens = [d for d in month_ends if d >= pd.Timestamp("1999-12-31")]
    daily_rows, sig_rows, panel_rows = [], [], []
    for i, ticker in enumerate(TICKERS):
        drift = 0.0006 if i < 12 else 0.0001
        rets = rng.normal(drift, 0.015, len(days))
        close = 50 * np.exp(np.cumsum(rets))
        n = len(days) if ticker != DELISTED else int(np.searchsorted(days, "2001-06-15"))
        for k in range(n):
            c = close[k]
            daily_rows.append(
                (ticker, days[k].date().isoformat(), c * 1.001, c * 1.012, c * 0.988, c)
            )
        for m, d in enumerate(screens):
            if ticker == DELISTED and d > days[n - 1]:
                continue
            sig_rows.append(
                {
                    "as_of": d.tz_localize("UTC"),
                    "ticker": ticker,
                    "signal": _signal(i, m),
                    "conviction_score": float(100 - i),
                    "sector": "Industrials",
                    "earnings_yield": 0.01 if 12 <= i < 16 and m >= 8 else 0.12 - 0.004 * i,
                    "composite_score": 0.5,
                    "data_quality_score": 1.0,
                }
            )
            panel_rows.append(
                {"as_of": d.date().isoformat(), "ticker": ticker, "market_cap": 1e9 * (1 + i)}
            )
    build = root / "build"
    build.mkdir()
    pd.DataFrame(daily_rows, columns=["ticker", "date", "open", "high", "low", "close"]).to_csv(
        build / "daily.csv.gz", index=False
    )
    panel = pd.DataFrame(panel_rows)
    panel.to_csv(build / "panel.csv.gz", index=False)
    pd.DataFrame([{"ticker": DELISTED, "haircut": 0.0}]).to_csv(
        build / "terminal_baseline.csv", index=False
    )
    cache = build / hsr.SIGNAL_CACHE_NAME
    pd.DataFrame(sig_rows).to_csv(cache, index=False)
    key = {
        "screen_code": hsr.screen_code_fingerprint(),
        "panel": hsr._data_fingerprint(pd.read_csv(build / "panel.csv.gz")),
    }
    cache.with_name(cache.name + ".key.json").write_text(json.dumps(key))
    return build


@pytest.fixture
def built(tmp_path: Path):
    build = _build(tmp_path)
    reg_path = tmp_path / "hrs.json"
    reg_path.write_text(json.dumps(_registration()))
    return build, reg_path, tmp_path / "historical_rule_search.json"


def test_committed_registration_grid():
    reg = rs.load_registration()
    configs = rs.grid_configs(reg)
    assert len(configs) == 840
    for key in reg["grid"]["selection"]["exit_rule"]:
        assert reg["exit_rules"][key]["kind"] in {"tier", "thesis"}
    assert rs.frozen_config(reg).id in {c.id for c in configs}
    fields = set(TradePlanConfig.__dataclass_fields__)
    for dim in ("limit", "stop", "target"):
        variants = reg["grid"]["tactical"]["variants"][dim]
        assert set(variants) == set(reg["grid"]["tactical"][dim])
        for overrides in variants.values():
            assert set(overrides) <= fields
    default = rs.trade_plan_config(reg, "limit=default|stop=default|target=default")
    market = rs.trade_plan_config_for_market("sp500")
    assert default == market
    deep = rs.trade_plan_config(reg, "limit=deep|stop=wide|target=far")
    assert deep.tactical_limit_below_spot == 0.92 and deep.atr_stop_multiplier == 3.0
    assert set(reg["closes"]) == {"L573", "L574"}


def test_neighbours_step_one_dimension():
    reg = rs.load_registration()
    frozen = rs.frozen_config(reg)
    near = rs.neighbours(frozen, reg)
    assert len(near) == 1 + 1 + 1 + 2 * 3
    assert all(n.id != frozen.id for n in near)


def test_selection_top_n_and_exit_rules(built):
    build, reg_path, _ = built
    reg = json.loads(reg_path.read_text())
    data = rs.load_search_data(build, reg)
    dates = data.window_dates(reg["windows"]["development"])
    assert len(dates) == 25

    top = rs.select(data.screens[1], rs.RuleConfig("buy_tier", 4, 1, None))
    assert top == ["S00", "S01", "S02", "S03"]
    strong = rs.select(data.screens[1], rs.RuleConfig("strong_buy", None, 1, None))
    assert strong == ["S00", "S01", "S02", "S03"]

    quick, quick_exits = rs.holdings_by_month(
        data, rs.RuleConfig("buy_tier", None, "tier1", None), dates
    )
    patient, _ = rs.holdings_by_month(data, rs.RuleConfig("buy_tier", None, "tier3", None), dates)
    dip = [k for k, d in enumerate(dates[:-1]) if "S05" not in quick[k]]
    assert dip and all("S05" in patient[k] for k in dip)
    assert all(not ({"S20", "S21"} & set(h)) for h in quick)
    assert quick_exits["left_selection"] >= 4

    rerate, rerate_exits = rs.holdings_by_month(
        data, rs.RuleConfig("buy_tier", None, "rerate50", None), dates
    )
    thesis, thesis_exits = rs.holdings_by_month(
        data, rs.RuleConfig("buy_tier", None, "thesis", None), dates
    )
    assert "S12" in quick[6] and "S12" not in quick[7]  # dev month k is synthetic month k + 1
    assert "S12" in rerate[7] and "S12" not in rerate[8]
    assert rerate_exits["rerated"] == 4
    assert all("S12" in h for h in thesis[1:])
    assert "rerated" not in thesis_exits and "left_selection" not in thesis_exits
    assert all("S05" in h for h in thesis[1:])
    assert thesis_exits.get("left_universe") == 1  # the delisted name


def _screen(signal: str, ey_pct: float | None) -> rs.ScreenDate:
    return rs.ScreenDate(
        date=pd.Timestamp("2005-01-31"),
        signal={"A": signal},
        conviction={"A": 1.0},
        market_cap={"A": 1.0},
        ey_pct={} if ey_pct is None else {"A": ey_pct},
    )


def test_thesis_exit_needs_confirmed_avoid_and_rerate_needs_a_streak():
    reg = rs.load_registration()
    thesis, rerate = reg["exit_rules"]["thesis"], reg["exit_rules"]["rerate50"]
    st = rs._Streaks()
    assert rs.exit_reason(thesis, st, _screen("avoid", 0.1), "A", False) is None
    assert rs.exit_reason(thesis, st, _screen("hold", 0.1), "A", False) is None
    assert rs.exit_reason(thesis, st, _screen("avoid", 0.1), "A", False) is None
    assert rs.exit_reason(thesis, st, _screen("avoid", 0.1), "A", False) == "thesis_break"

    st = rs._Streaks()
    assert rs.exit_reason(rerate, st, _screen("hold", 0.2), "A", False) is None
    assert rs.exit_reason(rerate, st, _screen("hold", None), "A", False) is None
    assert st.rerated == 1  # a missing yield leaves the streak
    assert rs.exit_reason(rerate, st, _screen("hold", 0.3), "A", False) == "rerated"

    st = rs._Streaks()
    rs.exit_reason(rerate, st, _screen("hold", 0.2), "A", False)
    assert rs.exit_reason(rerate, st, _screen("buy", 0.2), "A", True) is None
    assert st.rerated == 0  # back in the selection: still cheap by the screen
    assert rs.exit_reason(rerate, st, _screen("hold", 0.7), "A", False) is None

    tier = reg["exit_rules"]["tier3"]
    assert rs.exit_reason(tier, rs._Streaks(), _screen("avoid", 0.9), "A", False) == "avoid"


def test_horizon_probability_tracks_drift():
    rng = np.random.default_rng(3)
    up = rng.normal(0.01, 0.04, 600)
    res = rs.horizon_probability(up, 36, lag=12, z=1.645)
    expected = rs.NORMAL.cdf(np.mean(up) * 6 / np.std(up))
    assert res["p"] == pytest.approx(expected, abs=0.05)
    assert res["p_lower"] < res["p"]
    assert res["empirical_hit_rate"] > 0.85
    flat = rs.horizon_probability(rng.normal(0, 0.04, 600), 36, lag=12, z=1.645)
    assert 0.25 < flat["p"] < 0.75
    assert rs.horizon_probability(np.array([0.01]), 36, lag=12, z=1.645)["p"] is None


def test_overfitting_measures():
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 0.04, (160, 20))
    pbo_noise = rs.pbo_cscv(noise, blocks=8)
    assert 0.2 <= pbo_noise <= 0.8
    edge = noise.copy()
    edge[:, 0] += 0.03
    assert rs.pbo_cscv(edge, blocks=8) < 0.1
    assert rs.pbo_cscv(noise[:10], blocks=8) is None

    trials = [float(np.mean(c) / np.std(c, ddof=1)) for c in noise.T]
    assert rs.deflated_sharpe(edge[:, 0], trials) > 0.95
    assert rs.deflated_sharpe(noise[:, 0], trials) < 0.95
    assert rs.deflated_sharpe(edge[:, 0], trials[:1]) is None


def test_choose_prefers_plateau_then_core_only():
    reg = rs.load_registration()
    configs = rs.grid_configs(reg)
    flat = {c.id: 0.5 for c in configs}
    chosen, _ = rs.choose(flat, configs, reg)
    assert chosen.tactical is None and chosen.id == rs.frozen_config(reg).core_only().id

    spike = rs.RuleConfig("strong_buy", 20, "thesis", "limit=deep|stop=tight|target=far")
    centre = rs.RuleConfig("buy_tier", 40, "rerate50", "limit=default|stop=default|target=default")
    scores = dict(flat)
    scores[spike.id] = 0.95
    for c in [centre, *rs.neighbours(centre, reg)]:
        scores[c.id] = 0.7
    chosen, plateau = rs.choose(scores, configs, reg)
    assert chosen.id == centre.id and plateau == 0.7


def test_search_reveal_and_holdout_order(built, tmp_path: Path):
    build, reg_path, store = built
    replay_store = tmp_path / "historical_screen_replay.json"

    with pytest.raises(ValueError, match="no committed selection"):
        hsr.run_replay(
            tmp_path / "x" / "panel.csv",
            tmp_path / "x" / "prices.csv",
            store_path=replay_store,
            reveal_holdout=True,
            rule_search_registration_path=reg_path,
        )
    with pytest.raises(ValueError, match="No committed search selection"):
        rs.reveal(build, registration_path=reg_path, store_path=store)

    payload = rs.search(build, registration_path=reg_path, store_path=store)
    result = payload["search"]
    assert result["configs_tested"] == 48
    assert set(result["overfitting"]) == {"pbo_cscv", "deflated_sharpe_chosen"}
    rows = {r["id"]: r["development"] for r in result["configs"]}
    tactical = [d for i, d in rows.items() if not i.endswith("tac=off")]
    assert any(d["tactical"]["round_trips"] > 0 for d in tactical)
    assert all("tactical_increment_monthly" in d for d in tactical)
    assert max(d["tactical"]["round_trips_per_holding_year"] or 0 for d in tactical) > 0
    assert all(d["months"] == 24 for d in rows.values())
    quick = rows["buy_tier|top=all|exit=tier1|tac=off"]["holding"]
    patient = rows["buy_tier|top=all|exit=thesis|tac=off"]["holding"]
    assert patient["median_months"] > quick["median_months"]
    assert patient["open_at_window_end"] > quick["open_at_window_end"]
    assert rows["buy_tier|top=all|exit=rerate50|tac=off"]["holding"]["exits"]["rerated"] == 4
    assert "S0" not in json.dumps(result)  # aggregates only, no per-name rows

    with pytest.raises(FileNotFoundError):
        hsr.run_replay(
            tmp_path / "x" / "panel.csv",
            tmp_path / "x" / "prices.csv",
            store_path=replay_store,
            reveal_holdout=True,
            rule_search_registration_path=reg_path,
        )

    revealed = rs.reveal(build, registration_path=reg_path, store_path=store)
    holdout = revealed["holdout"]
    assert holdout["frozen"]["base"]["metrics"]["months"] == 12
    assert "tactical_increment_monthly" in holdout["frozen"]["stress"]
    assert holdout["frozen"]["base"]["verdict_vs_market"] in {
        "pass",
        "fail",
        "inconclusive",
        "too_thin",
    }
    assert revealed["holdout_reveals"] == [{"at": holdout["run_at"], "evidence": True}]

    block = rs.status_block(reg_path, store)
    assert block["selection"] == result["selection"]["config_id"]
    assert block["matches_rule_code"] is True
    assert rs.findings_from_block(block) == []

    rs.reveal(build, registration_path=reg_path, store_path=store)
    titles = {f["title"] for f in rs.findings_from_block(rs.status_block(reg_path, store))}
    assert titles == {rs.HOLDOUT_REUSED_TITLE}
    with pytest.raises(ValueError, match="already revealed"):
        rs.search(build, registration_path=reg_path, store_path=store)
    with pytest.raises(ValueError, match="already revealed"):
        rs.register(reg_path, store)


def test_tactical_off_matches_core_only_and_costs_lower_returns(built):
    build, reg_path, _ = built
    reg = json.loads(reg_path.read_text())
    data = rs.load_search_data(build, reg)
    window = reg["windows"]["development"]
    core = rs.RuleConfig("buy_tier", None, "tier1", None)
    cheap = rs.simulate(data, core, window, cost_per_side=0.0)
    dear = rs.simulate(data, core, window, cost_per_side=0.03)
    assert np.all(dear.portfolio <= cheap.portfolio + 1e-12)
    assert dear.tactical_trades == []
    assert len(cheap.cap_weighted) == len(cheap.portfolio) == 24


def test_findings_for_stale_registration():
    stale = {"matches_screen_code": True, "matches_rule_code": False, "holdout_reveals": []}
    (finding,) = rs.findings_from_block(stale)
    assert finding["title"] == rs.STALE_REGISTRATION_TITLE and finding["severity"] == "info"
    spent = {**stale, "holdout_reveals": [{"at": "a", "evidence": True}]}
    assert {f["title"] for f in rs.findings_from_block(spent)} == {rs.STALE_VERDICT_TITLE}
    assert rs.findings_from_block(None) == []


def test_refuses_build_inside_repo():
    with pytest.raises(ValueError, match="inside the repository"):
        rs.load_search_data(hsr.REPO_ROOT / "docs/data", rs.load_registration())


def test_committed_registration_fingerprints_match_code():
    reg = rs.load_registration()
    assert reg["screen_code_fingerprint"] == hsr.screen_code_fingerprint()
    assert reg["rule_code_fingerprint"] == rs.rule_code_fingerprint()
    hsr_reg = hsr.load_registration()
    assert reg["windows"]["development"] == hsr_reg["windows"]["development"]
    assert reg["windows"]["holdout"]["first_entry"] == hsr_reg["windows"]["holdout"]["first_entry"]
