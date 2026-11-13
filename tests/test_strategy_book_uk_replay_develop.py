"""UK replay develop/reveal at full-cache scale: equal outputs, plus the marked fixes."""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

import pytest
from _uk_replay_synthetic import _business_days, run_pipeline, synthetic_records

from value_investor import strategy_book_uk_replay as uk
from value_investor import strategy_book_uk_tape as tape

# Digests on ``synthetic_records(shares_as_list=True)``. The first set is the
# pre-refactor runner (develop-scale-v1 matched it exactly). Marker
# prior-year-visible-v1 changed the outputs on purpose; GOLDEN is after it.
PRE_REFACTOR = {
    "assembled_meta": "bbc88349f8b21d9d67d2525c3b1fc4cf3bb2db8179179a57660bcc75108ea2c6",
    "specs_before_sector": "9029fc9d88bb241c642dd9f665a60d72d28106b5b8ccccff8a23b5bb710cc432",
    "specs_after_sector": "187be0e92168c1b99f56dbea3dd361268fb38080acb62405554839a0bfc29791",
    "results": "49f300c403076552dd5db4d9405f4cff4f7f603e0790ca9946ca228b7f8ffe76",
    "store": "ba85faec06f2e0860500041b860b729cabb33c06d750a5d53d4e3579af1b476a",
}
GOLDEN = {
    "assembled_meta": "91654bc4d002f0fd3cbc60eaa182ccbbb6de95a5e539c444cb2a1c9a65d36e7f",
    "specs_before_sector": "130e51b55577ae54926ac58da71915946a4be86ea1f8ce365cbec5ba322c7b98",
    "specs_after_sector": "ec91afbc985da85ea0601f0214d6ee3a6fe47505c1ed9488082501cbd0a7e0e8",
    "results": "9d86a4523efb7a2b413b38a3297bbae3268480fe7878c5e65dd6f3eb413da0f3",
    "store": "4f61f0d2d6a7f83be7c6f08618050ea65e93f3cb101c94d5c22c1f837adb76e4",
}


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "docs/data").mkdir(parents=True)
    return tmp_path


def test_develop_outputs_are_pinned(tmp_path: Path) -> None:
    out = run_pipeline(synthetic_records(shares_as_list=True), _repo(tmp_path))
    assert out == GOLDEN
    assert all(out[key] != PRE_REFACTOR[key] for key in out)


def test_dict_keyed_outstanding_shares_rank_like_a_list(tmp_path: Path) -> None:
    out = run_pipeline(synthetic_records(), _repo(tmp_path))
    assert out == GOLDEN


def test_select_shares_reads_eodhd_dict_periods() -> None:
    annual = {
        "0": {"dateFormatted": "2015-12-31", "shares": 120.0},
        "1": {"dateFormatted": "2014-12-31", "shares": 100.0},
    }
    picked = tape.select_shares(annual, {}, date(2016, 3, 1))
    assert picked == {"shares": 120.0, "date": date(2015, 12, 31), "period": "annual"}
    assert tape.select_shares(list(annual.values()), None, date(2016, 3, 1)) == picked


def test_interim_checks_survive_a_29_february_period_end() -> None:
    quarterly = [
        {"period_end": date(2019, 2, 28), "visible_from": date(2019, 4, 1), "total_revenue": 100.0},
        {"period_end": date(2020, 2, 29), "visible_from": date(2020, 4, 1), "total_revenue": 80.0},
    ]
    interim = [
        {"period_end": row["period_end"], "visible_from": row["visible_from"], "eps": eps}
        | {"eps_basis": "vendor_eps"}
        for row, eps in zip(quarterly, (1.0, 0.5), strict=True)
    ]
    verdict = tape.decline_verdict([], quarterly, interim, date(2020, 5, 1))
    assert verdict["checks"]["interim_revenue"]["change_pct"] == pytest.approx(-0.2)
    assert verdict["checks"]["eps_interim"]["change_pct"] == pytest.approx(-0.5)
    assert tape.year_before(date(2020, 2, 29)) == date(2019, 2, 28)


def test_fx_series_matches_the_linear_scan() -> None:
    rng = random.Random(7)
    days = [date(2020, 1, 1) + timedelta(days=rng.randint(0, 900)) for _ in range(300)]
    plain = {day: rng.uniform(0.7, 0.9) for day in days}
    indexed = tape.FxSeries(plain)
    for offset in range(-10, 920):
        session = date(2020, 1, 1) + timedelta(days=offset)
        assert tape._fx_on(indexed, session) == tape._fx_on(plain, session)


def test_verdict_tape_matches_decline_verdict_every_day() -> None:
    record = synthetic_records(lse_names=3, xetra_names=0)[1]
    slim = uk._slim_record(record)
    annual = tape.merge_statement_years(slim["eodhd_annual"], [])
    verdicts = uk._VerdictTape(annual, slim["quarterly"], slim["interim"])
    day = date(2011, 1, 1)
    while day <= date(2017, 6, 30):
        expected = tape.decline_verdict(annual, slim["quarterly"], slim["interim"], day)
        assert verdicts.verdicts[verdicts.segment(day)] == expected
        day += timedelta(days=1)


def _naive_sector(day, peers, series, verdict_on):
    """The pre-refactor per-name ``_sector_on`` loop."""
    lookback = int(uk.REGISTRATION_CONSTANTS["RETURN_LOOKBACK_126D"])
    sma = int(uk.REGISTRATION_CONSTANTS["REGIME_SMA_SESSIONS"])
    members = below = with_sma = with_verdict = declining = 0
    trend_values = []
    for ticker in peers:
        days, values = series[ticker]
        if day not in days:
            continue
        members += 1
        position = days.index(day)
        if position + 1 >= sma:
            window = values[position - sma + 1 : position + 1]
            with_sma += 1
            if values[position] < sum(window) / len(window):
                below += 1
        if position >= lookback:
            base = values[position - lookback]
            if base and base > 0:
                trend_values.append(values[position] / base - 1.0)
        verdict = verdict_on(ticker, day)
        if verdict in {"clear", "declining"}:
            with_verdict += 1
            declining += int(verdict == "declining")
    return uk._sector_decision_from(members, with_sma, below, trend_values, with_verdict, declining)


def test_sector_table_matches_naive_loop_with_ties_and_jumps() -> None:
    rng = random.Random(11)
    calendar = _business_days(date(2012, 1, 2), date(2014, 12, 31))
    series = {}
    for index in range(7):
        days = [day for day in calendar if rng.random() > 0.03 * index]
        price = 10.0 ** rng.randint(-1, 3)
        values = []
        for position, _day in enumerate(days):
            if index == 0 or (index == 1 and position < 400):
                values.append(5.0)  # flat: close equals its 200-day mean
            elif position % 250 == 0:
                price *= 10.0 ** rng.choice((-2, 2))
                values.append(price)
            else:
                price *= math.exp(rng.gauss(0.0, 0.02))
                values.append(price)
        series[f"N{index}"] = (days, values)
    peers = list(series) + ["N3"]
    verdict_names = ("clear", "declining", "insufficient_data")

    class _Fixed:
        def __init__(self, ticker):
            self.points = []
            self.verdicts = {0: {"verdict": verdict_names[int(ticker[1:]) % 3]}}

        def segment(self, _day):
            return 0

    verdicts = {ticker: _Fixed(ticker) for ticker in series}
    table = uk._sector_table(peers, series, verdicts)
    for day in calendar:
        expected = _naive_sector(
            day, peers, series, lambda ticker, _day: verdicts[ticker].verdicts[0]["verdict"]
        )
        assert table.get(day, uk._sector_decision_from(0, 0, 0, [], 0, 0)) == expected, day


def _store_record(symbol: str, name: str, last: date) -> dict:
    record = synthetic_records(lse_names=1, xetra_names=0, shares_as_list=True)[0]
    record = dict(record, symbol=symbol, name=name, ch_key=None, ch_filings=None)
    record["eod"] = [row for row in record["eod"] if row["date"] <= last.isoformat()]
    record["delisted"] = True
    return record


def test_sector_pass_and_probe_read_store_matched_filings() -> None:
    last = date(2015, 6, 30)
    record = _store_record("ZZQ_old.LSE", "Zed Holdings plc", last)
    filings = [
        {
            "fiscal_year": year,
            "fiscal_year_end": f"{year}-12-31",
            "filing_date": f"{year + 1}-04-01",
            "fields": {"revenue": {"value": 1000 + year, "scale": "millions"}},
        }
        for year in range(2003, 2007)
    ]
    store = {
        "names": [
            {
                "key": "zed",
                "epic": "ZZQ",
                "leaving_date": (last + timedelta(days=3)).isoformat(),
                "filings": filings,
            }
        ]
    }
    assert tape.match_ch_record(store, symbol="ZZQ_old.LSE", name=None, last_bar=last) == "zed"
    fx = {day: 0.85 for day in _business_days(date(2011, 1, 3), date(2016, 1, 31))}
    assembled = uk.assemble_specs([record], eurgbp=fx, usdgbp=fx, ch_store=store, score=False)
    row = assembled["prepared"][0]
    assert row["ch_key"] == "zed"
    years = {item["year"] for item in row["annual"]}
    assert {2003, 2004, 2005, 2006} <= years
    view = uk._prepared_view([record])[0]
    assert not {2003, 2004, 2005, 2006} & {item["year"] for item in view["annual"]}


def test_develop_keeps_the_cache_and_reveal_deletes_it(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path / "repo")
    cache = tmp_path / "cache"
    record = synthetic_records(lse_names=4, xetra_names=0, shares_as_list=True)[0]
    raw = cache / "raw" / record["symbol"]
    raw.mkdir(parents=True)
    for kind in ("eod", "fundamentals", "dividends", "splits"):
        (raw / f"{kind}.json").write_text(json.dumps(record.get(kind) or []), encoding="utf-8")
    (cache / "lists").mkdir()
    code = record["symbol"].split(".")[0]
    (cache / "lists" / "LSE:delisted.json").write_text(
        json.dumps([{"Code": code, "Name": record["name"], "Currency": "GBX"}]), encoding="utf-8"
    )
    (cache / "fx").mkdir()
    (cache / "fx" / "EURGBP.FOREX.json").write_text("[]", encoding="utf-8")
    loaded = uk._records_from_cache(cache)
    assert [row["symbol"] for row in loaded] == [record["symbol"]]
    assert loaded[0]["slim"] and "eod" not in loaded[0]

    summary = {"status": "complete", "calls": [], "europe_not_fetched": False}
    monkeypatch.setattr(uk, "require_sealed", lambda _root: {})
    monkeypatch.setattr(uk, "run_fetch", lambda *_a, **_k: dict(summary))
    monkeypatch.setattr(uk, "_load_ch", lambda _root: {"names": []})
    uk.develop(repo_root=repo, client=object(), cache=cache, score=False)
    assert (cache / "raw").exists() and (cache / "fx").exists()

    monkeypatch.setattr(
        uk, "load_registration", lambda _root: {"reveal_stamp": {"at": "x", "by": "owner"}}
    )
    uk.reveal(repo_root=repo, client=object(), cache=cache, score=False)
    assert not (cache / "raw").exists() and not (cache / "fx").exists()


def test_develop_refuses_an_empty_cache(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path / "repo")
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(uk, "require_sealed", lambda _root: {})
    monkeypatch.setattr(
        uk,
        "run_fetch",
        lambda *_a, **_k: {"status": "complete", "calls": [], "europe_not_fetched": False},
    )
    with pytest.raises(uk.ReplayRefused, match="Re-run fetch"):
        uk.develop(repo_root=repo, client=object(), cache=cache)
    assert not (repo / uk.STORE_PATH).exists()


def _annual(year: int, revenue: float) -> dict:
    end = date(year, 12, 31)
    return {
        "year": year,
        "period_end": end,
        "visible_from": tape.first_visible_session(period_end=end, filing_date=None, annual=True),
        "source": "primary",
        "total_revenue": revenue,
        "operating_income": revenue * 0.1,
        "ebit": revenue * 0.1,
        "eps": revenue / 100,
        "eps_basis": "vendor_eps",
    }


def test_prior_year_needs_to_be_visible_not_fresh() -> None:
    annual = [_annual(2014, 100.0), _annual(2015, 90.0)]
    session = annual[1]["visible_from"] + timedelta(days=10)
    assert tape.is_stale(session, annual[0]["period_end"])
    verdict = tape.decline_verdict(annual, [], [], session)
    assert verdict["revenue_evaluable"]
    assert verdict["checks"]["revenue"]["change_pct"] == pytest.approx(-0.1)
    assert "revenue_decline" in verdict["checks"]["hard_reasons"]
    stale_latest = annual[1]["period_end"] + timedelta(days=457)
    assert not tape.decline_verdict(annual, [], [], stale_latest)["revenue_evaluable"]


def test_year_earlier_quarter_needs_to_be_visible_not_young() -> None:
    quarterly = [
        {"period_end": date(2014, 3, 31), "visible_from": date(2014, 7, 1), "total_revenue": 100.0},
        {"period_end": date(2015, 3, 31), "visible_from": date(2015, 7, 1), "total_revenue": 90.0},
    ]
    session = date(2015, 7, 10)
    assert (session - quarterly[0]["period_end"]).days > 460
    verdict = tape.decline_verdict([], quarterly, [], session)
    assert verdict["checks"]["interim_revenue"]["change_pct"] == pytest.approx(-0.1)
    old = date(2016, 7, 10)
    assert (
        tape.decline_verdict([], quarterly, [], old)["checks"]["interim_revenue"]["change_pct"]
        is None
    )


def _marker(repo: Path, marker_id: str, recompute: bool) -> None:
    path = repo / uk.REGISTRATION_PATH
    payload = json.loads(path.read_text()) if path.exists() else {"change_markers": []}
    payload["change_markers"].append({"marker_id": marker_id, "recompute_development": recompute})
    path.write_text(json.dumps(payload))


def test_amend_recomputes_development_once_per_marker(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    records = synthetic_records(lse_names=4, xetra_names=0, shares_as_list=True)
    fx = {day: 0.85 for day in _business_days(date(2011, 1, 3), date(2017, 1, 31))}
    run = dict(records=records, eurgbp=fx, usdgbp=fx, ch_store={"names": []}, score=False)
    _marker(repo, "m-old", recompute=False)
    first = uk.develop(repo_root=repo, **run)
    with pytest.raises(uk.ReplayRefused, match="amendment"):
        uk.develop(repo_root=repo, **run)
    with pytest.raises(uk.ReplayRefused, match="No unlogged change marker"):
        uk.develop(repo_root=repo, amend=True, **run)
    _marker(repo, "m-fix", recompute=True)
    amended = uk.develop(repo_root=repo, amend=True, **run)
    (row,) = amended["amendments"]
    assert row["marker_ids"] == ["m-fix"]
    superseded = row["superseded_development"]
    assert superseded["computed_at"] == first["development"]["computed_at"]
    assert len(superseded["sha256"]) == 64
    with pytest.raises(uk.ReplayRefused, match="No unlogged change marker"):
        uk.develop(repo_root=repo, amend=True, **run)


def test_amend_needs_a_committed_development(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _marker(repo, "m-fix", recompute=True)
    with pytest.raises(uk.ReplayRefused, match="No committed development"):
        uk.develop(repo_root=repo, records=[], amend=True)


def test_ops_finding_warns_while_development_is_superseded(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / uk.STORE_PATH).write_text(
        json.dumps({"phase": "development", "development": {"computed_at": "x"}})
    )
    _marker(repo, "m-old", recompute=False)
    assert uk.findings(repo)[0]["severity"] == "info"
    _marker(repo, "m-fix", recompute=True)
    row = uk.findings(repo)[0]
    assert row["severity"] == "warn" and "development-amendment" in row["summary"]
