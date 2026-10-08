"""Sharadar adapter for the historical screen replay, on synthetic tables only.

The fixtures reuse Sharadar column names but every value is made up: the
licence forbids committing vendor rows, including free-tier samples.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from value_investor import historical_screen_replay as hsr
from value_investor import sharadar_replay_adapter as sra

pytestmark = pytest.mark.usefixtures("isolated_cwd")

CALENDAR = pd.bdate_range("1998-01-01", "2001-06-29")
SPLIT_TICKER, SPLIT_DATE = "A00", pd.Timestamp("2000-03-01")
DELISTED = {"DEAD": pd.Timestamp("2000-05-15"), "GONE": pd.Timestamp("2000-08-15")}
REMOVED_LIVE = ("OLD", pd.Timestamp("2000-04-10"))
ADDED_LATE = ("LATE", pd.Timestamp("2000-06-15"))
CORE = [f"A{i:02d}" for i in range(30)]
ALL = [*CORE, "EURCO", "DEAD", "GONE", "OLD", "LATE"]
QUARTERLY_GROWTH = 1.02


def _close(ticker: str, day_index: int) -> float:
    drift = 1.0 + 0.0002 * (ALL.index(ticker) % 7)
    return 40.0 * drift**day_index


def _stocks() -> pd.DataFrame:
    rows = []
    for t in ALL:
        end = DELISTED.get(t, CALENDAR[-1])
        for k, d in enumerate(CALENDAR):
            if d > end:
                break
            close = _close(t, k)
            unadj = close * 2.0 if t == SPLIT_TICKER and d < SPLIT_DATE else close
            rows.append(
                {
                    "ticker": t,
                    "date": d.date().isoformat(),
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "closeadj": close * 1.00001**k,
                    "closeunadj": unadj,
                    "volume": 1000,
                }
            )
    return pd.DataFrame(rows)


def _unadj_on(stocks: pd.DataFrame, ticker: str, day: pd.Timestamp) -> float:
    s = stocks.loc[stocks["ticker"] == ticker].copy()
    s["date"] = pd.to_datetime(s["date"])
    return float(s.loc[s["date"] <= day, "closeunadj"].iloc[-1])


def _fundamentals(stocks: pd.DataFrame) -> pd.DataFrame:
    rows = []
    quarters = pd.date_range("1998-03-31", "2001-03-31", freq="QE")
    for t in ALL:
        for q, cal in enumerate(quarters):
            filed = cal + pd.Timedelta(days=45)
            if t in DELISTED and filed > DELISTED[t]:
                break
            shares = 2e6 if t == SPLIT_TICKER and filed >= SPLIT_DATE else 1e6
            quarter_rev = 250.0 * QUARTERLY_GROWTH**q
            ttm_rev = sum(250.0 * QUARTERLY_GROWTH ** (q - j) for j in range(4))
            common = {
                "ticker": t,
                "calendardate": cal.date().isoformat(),
                "datekey": filed.date().isoformat(),
                "reportperiod": cal.date().isoformat(),
                "lastupdated": "2020-01-01",
                "marketcap": shares * _unadj_on(stocks, t, filed),
                "equity": 500.0,
                "debt": 200.0,
                "assets": 2000.0,
                "assetsc": 800.0,
                "liabilities": 1200.0,
                "liabilitiesc": 400.0,
                "cashneq": 100.0,
                "currentratio": 2.0,
                "divyield": 0.03,
                "roe": 0.12,
                "roa": 0.05 + 0.001 * q,
                "netmargin": 0.1,
                "grossmargin": 0.4,
                "fcf": 80.0,
                "ncfo": 120.0,
                "ebitda": 150.0,
                "ebit": 110.0,
                "intexp": 5.0,
                "bvps": 0.5,
                "sharesbas": shares,
            }
            rows.append(
                {**common, "dimension": "ART", "revenue": ttm_rev, "netinccmn": ttm_rev * 0.1}
            )
            rows.append(
                {
                    **common,
                    "dimension": "ARQ",
                    "revenue": quarter_rev,
                    "netinccmn": quarter_rev * 0.1,
                }
            )
            rows.append({**common, "dimension": "MRT", "revenue": -1.0, "netinccmn": -1.0})
    return pd.DataFrame(rows)


def _sp500() -> pd.DataFrame:
    rows = [
        {"date": "2001-06-29", "action": "current", "ticker": t}
        for t in [*CORE, "EURCO", ADDED_LATE[0]]
    ]
    for t, d in [*DELISTED.items(), REMOVED_LIVE]:
        rows.append(
            {
                "date": (d + pd.Timedelta(days=1)).date().isoformat(),
                "action": "removed",
                "ticker": t,
            }
        )
    rows.append(
        {"date": ADDED_LATE[1].date().isoformat(), "action": "added", "ticker": ADDED_LATE[0]}
    )
    return pd.DataFrame(rows).assign(name="", contraticker="", contraname="", note="")


def _tickers() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "table": "SF1",
                "ticker": t,
                "name": f"Synthetic {t}",
                "sector": "Technology" if i % 2 else "Energy",
                "currency": "EUR" if t == "EURCO" else "USD",
                "isdelisted": "Y" if t in DELISTED else "N",
            }
            for i, t in enumerate(ALL)
        ]
        + [
            {
                "table": "SEP",
                "ticker": "A00",
                "name": "dup",
                "sector": "",
                "currency": "USD",
                "isdelisted": "N",
            }
        ]
    )


def _actions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2000-08-15",
                "action": "acquisitionby",
                "ticker": "GONE",
                "name": "",
                "value": "",
                "contraticker": "A01",
                "contraname": "",
            },
            {
                "date": "2000-05-15",
                "action": "delisted",
                "ticker": "DEAD",
                "name": "",
                "value": "",
                "contraticker": "",
                "contraname": "",
            },
        ]
    )


@pytest.fixture(scope="module")
def sharadar_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("sharadar")
    stocks = _stocks()
    stocks.to_csv(root / "SHARADAR_SEP_test.csv", index=False)
    _fundamentals(stocks).to_csv(
        root / "SHARADAR_SF1_test.zip",
        index=False,
        compression={"method": "zip", "archive_name": "SHARADAR_SF1_test.csv"},
    )
    _sp500().to_csv(root / "SHARADAR_SP500_test.csv", index=False)
    _tickers().to_csv(root / "SHARADAR_TICKERS_test.csv", index=False)
    _actions().to_csv(root / "SHARADAR_ACTIONS_test.csv", index=False)
    return root


def _registration() -> dict:
    reg = hsr.load_registration()
    reg["windows"] = {
        "development": {"first_entry": "2000-01-31", "last_entry": "2000-06-30"},
        "holdout": {"first_entry": "2000-07-31", "last_entry": "2000-12-29"},
    }
    reg["horizons_days"] = [30, 91]
    reg["primary"] = {**reg["primary"], "horizon_days": 30, "confirmation_horizon_days": 91}
    reg["screen_code_fingerprint"] = hsr.screen_code_fingerprint()
    return reg


def test_membership_from_snapshot_and_by_walking_back():
    sp = pd.DataFrame(
        [{"date": "2005-12-31", "action": "current", "ticker": t} for t in ("A", "B", "D")]
        + [{"date": "2003-03-31", "action": "historical", "ticker": t} for t in ("A", "B", "C")]
        + [
            {"date": "2003-06-01", "action": "added", "ticker": "D"},
            {"date": "2003-06-01", "action": "removed", "ticker": "C"},
            {"date": "2002-06-01", "action": "added", "ticker": "C"},
            {"date": "2002-06-01", "action": "removed", "ticker": "E"},
        ]
    )
    sp["date"] = pd.to_datetime(sp["date"])
    got = sra.membership_on(
        sp, [pd.Timestamp(d) for d in ("2002-01-31", "2002-06-01", "2003-04-30", "2003-06-30")]
    )
    assert got[pd.Timestamp("2003-04-30")] == {"A", "B", "C"}
    assert got[pd.Timestamp("2003-06-30")] == {"A", "B", "D"}
    assert got[pd.Timestamp("2002-06-01")] == {"A", "B", "C"}
    assert got[pd.Timestamp("2002-01-31")] == {"A", "B", "E"}
    assert sra.ever_members(sp, pd.Timestamp("2002-01-01"), pd.Timestamp("2003-12-31")) == {
        "A",
        "B",
        "C",
        "D",
        "E",
    }


def test_month_end_trading_days_inside_window():
    days = pd.bdate_range("2000-01-01", "2000-04-30").delete(-1)  # drop Fri 28 Apr
    got = sra.month_end_trading_days(days, pd.Timestamp("2000-02-29"), pd.Timestamp("2000-04-30"))
    assert [d.date().isoformat() for d in got] == ["2000-02-29", "2000-03-31", "2000-04-27"]


def test_filings_need_two_days_before_rebalance():
    d = pd.Timestamp("2000-05-31")
    fundamentals = pd.DataFrame(
        [
            {
                "ticker": "X",
                "dimension": "ART",
                "filed": pd.Timestamp(f),
                "calendardate": c,
                "marketcap": mc,
                "netinccmn": 10.0,
                "equity": 50.0,
            }
            for f, c, mc in [
                ("2000-05-29", pd.Timestamp("2000-03-31"), 2000.0),
                ("2000-05-30", pd.Timestamp("2000-03-31"), 9999.0),
            ]
        ]
    )
    stocks = pd.DataFrame(
        {
            "ticker": "X",
            "date": pd.bdate_range("2000-05-01", "2000-05-31"),
            "close": 10.0,
            "closeadj": 10.0,
            "closeunadj": 10.0,
        }
    )
    panel, counts = sra.build_panel(
        {d: {"X"}},
        fundamentals,
        stocks,
        pd.DataFrame({"sector": ["Energy"], "currency": ["USD"]}, index=["X"]),
    )
    assert panel.loc[0, "market_cap"] == pytest.approx(2000.0)
    assert panel.loc[0, "trailing_pe"] == pytest.approx(200.0)
    assert counts["panel_rows"] == 1


def test_build_writes_point_in_time_panel(sharadar_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    report = sra.build_replay_inputs(sharadar_dir, out, _registration())
    panel = pd.read_csv(out / "panel.csv.gz")
    stocks = _stocks()

    assert report["rebalance_dates"] == 12
    assert report["counts"]["dropped_non_usd"] == 12
    assert "EURCO" not in set(panel["ticker"])
    assert "errors" not in panel.columns
    assert set(panel.columns) == set(sra.PANEL_COLUMNS)

    by_date = panel.groupby("as_of")["ticker"].apply(set)
    assert "OLD" in by_date["2000-03-31"] and "OLD" not in by_date["2000-04-28"]
    assert "LATE" not in by_date["2000-05-31"] and "LATE" in by_date["2000-06-30"]
    assert "DEAD" in by_date["2000-04-28"] and "DEAD" not in by_date["2000-05-31"]

    split_row = panel.loc[(panel["ticker"] == SPLIT_TICKER) & (panel["as_of"] == "2000-03-31")]
    expected_cap = 2e6 * _unadj_on(stocks, SPLIT_TICKER, pd.Timestamp("2000-03-31"))
    assert split_row["market_cap"].iloc[0] == pytest.approx(expected_cap, rel=1e-9)

    row = panel.loc[(panel["ticker"] == "A05") & (panel["as_of"] == "2000-06-30")].iloc[0]
    assert row["revenue_growth"] == pytest.approx(QUARTERLY_GROWTH**4 - 1)
    assert row["earnings_growth"] == pytest.approx(QUARTERLY_GROWTH**4 - 1)
    assert row["debt_to_equity"] == pytest.approx(40.0)
    assert row["ncav"] == pytest.approx(-400.0)
    assert row["current_ratio_bs"] == pytest.approx(2.0)
    assert row["return_on_assets_prev"] == pytest.approx(row["return_on_assets"] - 0.004)
    assert 2.5 < row["dividend_yield"] < 3.5  # percent, the live Yahoo unit

    terminal = pd.read_csv(out / "terminal_baseline.csv")
    sensitivity = pd.read_csv(out / "terminal_sensitivity.csv").set_index("ticker")["haircut"]
    assert set(terminal["ticker"]) == {"DEAD", "GONE"}
    assert (terminal["haircut"] == 0.0).all()
    assert sensitivity["DEAD"] == pytest.approx(-0.3)
    assert sensitivity["GONE"] == 0.0
    assert report["delisting"] == {
        "delisted_members": 2,
        "delisted_via_merger": 1,
        "delisted_other": 1,
    }

    daily = pd.read_csv(out / "daily.csv.gz")
    a05 = daily.loc[daily["ticker"] == "A05"].set_index("date")
    assert a05.index.min() < "1999-01-01"
    assert a05["high"].div(a05["close"]).round(6).eq(1.01).all()
    assert "EURCO" in set(daily["ticker"])

    prices = pd.read_csv(out / "prices.csv.gz")
    assert prices["date"].nunique() < len(CALENDAR) / 4
    assert "2000-05-15" in set(prices.loc[prices["ticker"] == "DEAD", "date"])
    report_text = (out / "build_report.json").read_text()
    assert "A05" not in report_text and "DEAD" not in report_text


def test_build_then_replay_end_to_end(sharadar_dir: Path, tmp_path: Path):
    reg_path = tmp_path / "registration.json"
    reg_path.write_text(json.dumps(_registration()))
    store = tmp_path / "store.json"
    out = tmp_path / "out"
    hsr.build_panel_files(sharadar_dir, out, registration_path=reg_path)

    payload = hsr.run_replay(
        out / "panel.csv.gz",
        out / "prices.csv.gz",
        terminal_path=out / "terminal_baseline.csv",
        registration_path=reg_path,
        store_path=store,
    )
    results = payload["results"]
    assert results["rebalance_dates"] == 12
    assert set(results["horizons"]) == {"30", "91"}
    assert results["horizons"]["30"]["development"]["cohorts"] >= 5
    assert results["horizons"]["30"]["holdout"]["sealed"] is True
    assert payload["holdout_reveals"] == []
    first_used = payload["licensed_data"]["first_used_at"]

    sens = hsr.run_replay(
        out / "panel.csv.gz",
        out / "prices.csv.gz",
        terminal_path=out / "terminal_sensitivity.csv",
        registration_path=reg_path,
        store_path=store,
        variant="delisting_sensitivity",
    )
    assert sens["results"] == results
    assert sens["results_delisting_sensitivity"]["horizons"]["30"]["holdout"]["sealed"] is True
    assert sens["holdout_reveals"] == []
    assert sens["licensed_data"]["first_used_at"] == first_used
    with pytest.raises(ValueError, match="Only the baseline"):
        hsr.run_replay(
            out / "panel.csv.gz",
            out / "prices.csv.gz",
            registration_path=reg_path,
            store_path=store,
            variant="delisting_sensitivity",
            reveal_holdout=True,
        )


def test_build_refuses_paths_inside_repo(sharadar_dir: Path):
    with pytest.raises(ValueError, match="inside the repository"):
        hsr.build_panel_files(sharadar_dir, hsr.REPO_ROOT / "tmp-replay-out")
    with pytest.raises(ValueError, match="inside the repository"):
        hsr.build_panel_files(hsr.REPO_ROOT / "docs", Path("/tmp/x"))
