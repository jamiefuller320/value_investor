"""Pre-registered historical screen replay: harness, parity, sealing, and findings."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from value_investor import historical_screen_replay as hsr
from value_investor.backtest import RunSnapshot
from value_investor.data_library import market_dir
from value_investor.library_screen import run_library_screen
from value_investor.screen_premise_backtest import build_screen_premise_backtest
from value_investor.storage import write_json

pytestmark = pytest.mark.usefixtures("isolated_cwd")


def _metric_rows(n: int = 30) -> list[dict]:
    return [
        {
            "ticker": f"T{i:03d}",
            "name": f"Test Co {i}",
            "sector": "Technology" if i % 2 == 0 else "Energy",
            "market_cap": 1e10 + i * 1e8,
            "trailing_pe": 8.0 + (i % 5),
            "price_to_book": 0.8 + (i % 3) * 0.2,
            "dividend_yield": 0.02 + (i % 4) * 0.01,
            "current_ratio": 1.5,
            "debt_to_equity": 40.0 + i,
            "return_on_equity": 0.12,
            "return_on_assets": 0.06,
            "profit_margins": 0.1,
            "revenue_growth": 0.05,
            "earnings_growth": 0.04,
            "free_cashflow": 1e9,
            "enterprise_value": 1.2e10,
            "ebitda": 2e9,
            "ebit": 1.5e9,
            "total_revenue": 5e9,
            "total_assets": 8e9,
            "total_current_liabilities": 2e9,
            "total_debt": 1e9,
            "total_cash": 5e8,
            "ncav": 1e9,
            "last_price": 50.0 + i,
            "errors": [],
        }
        for i in range(n)
    ]


def _seed(root: Path, market: str, rows: list[dict]) -> None:
    write_json(
        market_dir(root, market) / "metrics" / "latest.json.gz", rows, compact=True, compress=True
    )
    tickers = [r["ticker"] for r in rows]
    write_json(
        market_dir(root, market) / "manifest.json",
        {
            "ticker_count": len(tickers),
            "coverage_count": len(tickers),
            "coverage_pct": 1.0,
            "tickers": tickers,
        },
        compact=False,
    )


def test_fingerprint_tracks_screen_code_only(tmp_path: Path):
    pkg = tmp_path / "pkg"
    for rel in hsr.SCREEN_CODE_PATHS:
        src = hsr.PACKAGE_DIR / rel
        dest = pkg / rel
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dest)
    (pkg / "unrelated.py").write_text("x = 1\n")
    base = hsr.screen_code_fingerprint(pkg)
    assert base == hsr.screen_code_fingerprint(hsr.PACKAGE_DIR)
    (pkg / "unrelated.py").write_text("x = 2\n")
    assert hsr.screen_code_fingerprint(pkg) == base
    with (pkg / "signals.py").open("a") as fh:
        fh.write("\n# changed\n")
    assert hsr.screen_code_fingerprint(pkg) != base


def test_replay_screen_matches_direct_library_screen(tmp_path: Path):
    rows = _metric_rows()
    dates = [datetime(2010, 1, 29, tzinfo=UTC), datetime(2010, 2, 26, tzinfo=UTC)]
    panel = pd.DataFrame([{**r, "as_of": d} for d in dates for r in rows])
    replayed = hsr.replay_screen(panel, market_id="sp500", scratch_root=tmp_path / "scratch")

    direct_root = tmp_path / "direct"
    _seed(direct_root, "sp500", rows)
    for d in dates:
        direct = run_library_screen(direct_root, "sp500", run_at=d)
    last = replayed.loc[replayed["as_of"] == pd.Timestamp(dates[-1])].set_index("ticker")
    expected = direct.signals.set_index("ticker")
    assert set(last.index) == set(expected.index)
    assert (last["signal"] == expected.loc[last.index, "signal"]).all()
    assert last["conviction_score"].tolist() == pytest.approx(
        expected.loc[last.index, "conviction_score"].fillna(0.0).tolist()
    )
    assert last["earnings_yield"].notna().all()


def test_signal_cache_reused_until_panel_changes(tmp_path: Path, monkeypatch):
    rows = _metric_rows()
    panel = pd.DataFrame([{**r, "as_of": datetime(2010, 1, 29, tzinfo=UTC)} for r in rows])
    cache = tmp_path / "build" / hsr.SIGNAL_CACHE_NAME
    calls = []
    real = hsr.replay_screen

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(hsr, "replay_screen", counting)
    first = hsr.cached_replay_signals(panel, market_id="sp500", cache_path=cache)
    again = hsr.cached_replay_signals(panel, market_id="sp500", cache_path=cache)
    assert len(calls) == 1
    assert list(again.columns) == list(hsr.SIGNAL_COLUMNS)
    assert again["signal"].tolist() == first["signal"].tolist()
    assert again["as_of"].iloc[0] == pd.Timestamp("2010-01-29", tz="UTC")

    changed = panel.assign(trailing_pe=panel["trailing_pe"] * 2)
    hsr.cached_replay_signals(changed, market_id="sp500", cache_path=cache)
    assert len(calls) == 2

    with pytest.raises(ValueError, match="inside the repository"):
        hsr.cached_replay_signals(
            panel, market_id="sp500", cache_path=hsr.REPO_ROOT / "docs/data/x.csv.gz"
        )


def _prices(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "ticker", "close"])


def test_forward_returns_exit_rule_and_delistings():
    prices = _prices(
        [
            ("2020-01-31", "A", 10.0),
            ("2020-01-31", "B", 20.0),
            ("2020-01-31", "C", 5.0),
            ("2020-01-31", "D", 4.0),
            ("2020-02-10", "C", 4.0),
            ("2020-02-10", "D", 3.0),
            ("2020-02-28", "A", 11.0),
            ("2020-03-02", "A", 12.0),
            ("2020-03-02", "B", 0.0),
        ]
    )
    rets = hsr.forward_returns(prices, ["2020-01-31"], 30, terminal_haircuts={"C": -0.5})
    by = rets.set_index("ticker")
    assert by.at["A", "ret"] == pytest.approx(0.2)
    assert by.at["A", "exit"] == pd.Timestamp("2020-03-02", tz=UTC)
    assert by.at["C", "ret"] == pytest.approx(4.0 * 0.5 / 5.0 - 1.0)
    assert by.at["C", "exit_kind"] == "terminal"
    assert "B" not in by.index
    assert "D" not in by.index


def test_score_cohort_spreads_plain_value_and_turnover():
    tickers = [f"N{i}" for i in range(10)]
    cohort = pd.DataFrame(
        {
            "as_of": pd.Timestamp("2020-01-31", tz=UTC),
            "ticker": tickers,
            "signal": ["buy"] * 5 + ["hold"] * 3 + ["avoid"] * 2,
            "conviction_score": [float(10 - i) for i in range(10)],
            "earnings_yield": [0.1 - 0.01 * i for i in range(10)],
            "ret": [0.10, 0.08, 0.06, 0.04, 0.02, 0.0, 0.0, 0.0, -0.05, -0.05],
        }
    )
    scored = hsr.score_cohort(cohort, previous_buy={"N0", "N1", "X"})
    assert scored["universe_return"] == pytest.approx(0.02)
    assert scored["buy_tier_spread"] == pytest.approx(0.04)
    assert scored["avoid_spread"] == pytest.approx(-0.07)
    assert scored["buy_tier_turnover"] == pytest.approx(0.6)
    assert scored["rank_ic"] > 0.9
    assert scored["plain_value_spread"] is None


def _snapshot_dir(tmp_path: Path, weeks: int = 8, names: int = 30) -> Path:
    data_dir = tmp_path / "data"
    start = datetime(2026, 7, 5, 7, 0, tzinfo=UTC)
    for w in range(weeks):
        at = start + timedelta(days=7 * w)
        signals = [
            {
                "ticker": f"T{i:02d}.L",
                "signal": "buy" if i < 8 else ("avoid" if i >= 25 else "hold"),
                "conviction_score": 1.0 - i / names,
                "sector": "Industrials",
            }
            for i in range(names)
        ]
        prices = {
            f"T{i:02d}.L": 100.0 * (1 + (0.004 * (names - i) - 0.05) * w / 4) for i in range(names)
        }
        snap = RunSnapshot(run_at=at.isoformat(), prices=prices, signals=signals)
        write_json(
            data_dir / "history" / f"run_{at:%Y%m%d_%H%M%S}.json",
            snap.to_dict(),
            compact=True,
            compress=True,
        )
    return data_dir


def test_parity_with_screen_premise_backtest(tmp_path: Path):
    data_dir = _snapshot_dir(tmp_path)
    premise = build_screen_premise_backtest(data_dir)
    parity = hsr.parity_with_screen_premise(data_dir, premise)
    assert parity["status"] == "ok"
    assert parity["values_checked"] > 10
    assert parity["max_abs_diff"] == 0.0

    first = premise["horizons"]["7"]["cohorts"][0]
    first["buy_tier_spread"] = first["buy_tier_spread"] + 0.01
    broken = hsr.parity_with_screen_premise(data_dir, premise)
    assert broken["status"] == "mismatch"
    titles = [f["title"] for f in hsr.findings_from_store({"parity": broken})]
    assert hsr.PARITY_FINDING_TITLE in titles


def _registration() -> dict:
    return {
        "market_id": "sp500",
        "rebalance": {"step_days": 30},
        "windows": {
            "development": {"first_entry": "2000-01-31", "last_entry": "2000-06-30"},
            "holdout": {"first_entry": "2000-07-31", "last_entry": "2000-12-29"},
        },
        "horizons_days": [30],
        "primary": {
            "horizon_days": 30,
            "metric": "buy_tier_spread_net",
            "secondary_metric": "buy_minus_plain_value",
        },
        "costs": {"base_per_side": 0.0053, "stress_per_side": 0.03},
    }


def _synthetic_panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    month_ends = pd.date_range("2000-01-31", periods=13, freq="ME", tz=UTC)
    tickers = [f"S{i:02d}" for i in range(20)]
    signals = pd.DataFrame(
        [
            {
                "as_of": d,
                "ticker": t,
                "signal": "buy" if i < 6 else "hold",
                "conviction_score": float(20 - i),
                "earnings_yield": 0.2 - 0.01 * i,
            }
            for d in month_ends[:-1]
            for i, t in enumerate(tickers)
        ]
    )
    prices = pd.DataFrame(
        [
            {
                "date": d,
                "ticker": t,
                "close": 100.0 * (1.0 + (0.02 if i < 6 else 0.0) + 0.001 * j) ** k,
            }
            for k, d in enumerate(month_ends)
            for i, t in enumerate(tickers)
            for j in [k % 3]
        ]
    )
    return signals, prices


def test_holdout_sealed_unless_revealed():
    signals, prices = _synthetic_panels()
    sealed = hsr.build_replay_results(signals, prices, _registration())
    h30 = sealed["30"]
    assert h30["holdout"]["sealed"] is True
    assert h30["holdout"]["cohorts"] > 0
    assert "holdout_verdict" not in h30
    assert h30["development"]["buy_tier_spread"]["mean"] > 0
    assert h30["development_verdict"] == "pass"

    revealed = hsr.build_replay_results(signals, prices, _registration(), reveal_holdout=True)
    assert revealed["30"]["holdout_verdict"] == "pass"
    dev = h30["development"]
    assert dev["buy_tier_spread_net_stress"]["mean"] < dev["buy_tier_spread"]["mean"]
    assert revealed["30"]["holdout"]["mean_buy_tier_turnover"] == 0.0


def test_findings_for_drift_and_reused_holdout():
    drift = {"registration": {"matches_screen_code": False}, "holdout_reveals": []}
    (info,) = hsr.findings_from_store(drift)
    assert info["severity"] == "info" and info["title"] == hsr.STALE_REGISTRATION_TITLE

    spent = {
        "registration": {"matches_screen_code": False},
        "holdout_reveals": [{"at": "a", "evidence": True}, {"at": "b", "evidence": False}],
    }
    titles = {f["title"] for f in hsr.findings_from_store(spent)}
    assert titles == {hsr.STALE_VERDICT_TITLE, hsr.HOLDOUT_REUSED_TITLE}
    assert all(f["auto_fixable"] is False for f in hsr.findings_from_store(spent))

    clean = {"registration": {"matches_screen_code": True}, "parity": {"status": "ok"}}
    assert hsr.findings_from_store(clean) == []


def test_run_refuses_licensed_data_inside_repo(tmp_path: Path):
    with pytest.raises(ValueError, match="inside the repository"):
        hsr.run_replay(
            hsr.REPO_ROOT / "panel.csv",
            tmp_path / "prices.csv",
            store_path=tmp_path / "store.json",
        )


def test_register_refused_after_holdout_reveal(tmp_path: Path):
    reg_path = tmp_path / "reg.json"
    reg_path.write_text(json.dumps({"registration_id": "x", "screen_code_fingerprint": "old"}))
    store = tmp_path / "store.json"
    assert hsr.register(reg_path, store) == hsr.screen_code_fingerprint()
    store.write_text(json.dumps({"holdout_reveals": [{"at": "t", "evidence": True}]}))
    with pytest.raises(ValueError, match="new registration_id"):
        hsr.register(reg_path, store)


def test_committed_registration_is_complete():
    reg = hsr.load_registration()
    assert reg["registration_id"] and reg["market_id"] == "sp500"
    assert reg["primary"]["horizon_days"] in reg["horizons_days"]
    assert reg["windows"]["development"]["last_entry"] < reg["windows"]["holdout"]["first_entry"]
    assert len(reg["screen_code_fingerprint"]) == 64


def test_ops_monitor_check_writes_store_without_parity_finding(tmp_path: Path):
    from value_investor.ops_monitor import check_historical_screen_replay

    data_dir = _snapshot_dir(tmp_path)
    (data_dir / "screen_premise_backtest.json").write_text(
        json.dumps(build_screen_premise_backtest(data_dir))
    )
    store = tmp_path / "replay.json"
    findings = check_historical_screen_replay(data_dir=data_dir, store_path=store)
    assert hsr.PARITY_FINDING_TITLE not in {f.title for f in findings}
    payload = json.loads(store.read_text())
    assert payload["parity"]["status"] == "ok"
    assert payload["results"] is None
