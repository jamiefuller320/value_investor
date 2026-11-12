"""UK/Europe strategy-book replay. Every HTTP call is a fixture. Nothing is sealed."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from value_investor import strategy_book_uk_replay as uk
from value_investor import strategy_book_uk_tape as tape
from value_investor.eodhd_coverage_check import EodhdClient
from value_investor.ops_monitor import check_strategy_book_uk_replay
from value_investor.strategy_book_observe import GateTape, NameSpec, ScreenFact
from value_investor.strategy_book_uk_replay import (
    BASELINE,
    REGISTRATION_CONSTANTS,
    REGISTRATION_PATH,
    SENSITIVITY,
    STORE_PATH,
    TITLE,
    TITLE_FAILED,
    RevealRefused,
    UnsealedRegistration,
    WeightProbeFailed,
    assert_store_has_no_licensed_numbers,
    committed_store,
    fetch_plan,
    registration_payload,
    require_sealed,
    run_fetch,
    seal_registration,
    walk_variants,
    write_registration,
)

START = date(2024, 1, 2)
_LADDER = [100.0, 101.0, 102.0, 101.5]


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


def _tape(days: list[date]) -> GateTape:
    labels = (
        None,
        "clear",
        "declining",
        "insufficient_data",
        "sound",
        "headwind",
        "sector_missing",
    )
    return GateTape(
        [day - timedelta(days=1) for day in days],
        [labels.index("clear")] * len(days),
        [labels.index("sound")] * len(days),
        labels,
    )


def _name(closes: list[float], ticker: str, signal: str) -> NameSpec:
    days = _weekdays(len(closes))
    return NameSpec(
        market="ftse350",
        ticker=ticker,
        sessions=days,
        closes=closes,
        screens=[
            ScreenFact(
                run_date=days[13],
                signal=signal,
                adjusted_signal=None,
                research_verdict="absent",
            )
        ],
        gates=_tape(days),
    )


def _repo(tmp_path: Path, *, sealed: bool = False) -> Path:
    root = tmp_path / "repo"
    (root / "docs/ops").mkdir(parents=True)
    (root / "docs/data").mkdir(parents=True)
    (root / "docs/ops/strategy-book-uk-replay-registration-draft.md").write_text(
        "draft registration\n", encoding="utf-8"
    )
    write_registration(registration_payload(), root)
    if sealed:
        seal_registration("owner", root)
    return root


class _Headers:
    def __init__(self, pairs: dict[str, str]) -> None:
        self._pairs = list(pairs.items())

    def items(self) -> list[tuple[str, str]]:
        return self._pairs


class _Resp:
    def __init__(self, body: object, headers: dict[str, str] | None = None) -> None:
        self._body = json.dumps(body).encode()
        self.headers = _Headers(headers or {})

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


def _route(url: str, headers: dict[str, str] | None = None) -> _Resp:
    if "exchange-symbol-list" in url:
        return _Resp(
            [{"Code": "AAA", "Name": "Aaa plc", "Type": "Common Stock", "Currency": "GBP"}]
        )
    if "EURGBP.FOREX" in url:
        return _Resp([{"date": "2024-01-02", "close": 0.85}])
    if "USDGBP.FOREX" in url:
        return _Resp([{"date": "2024-01-02", "close": 0.78}])
    if "fundamentals/" in url:
        return _Resp({"General": {"Type": "Common Stock"}}, headers)
    if "div/" in url:
        return _Resp([])
    if "splits/" in url:
        return _Resp([])
    if "eod/" in url:
        return _Resp([{"date": "2024-01-02", "close": 1.0, "adjusted_close": 1.0}])
    raise AssertionError(url)


def test_pence_and_pounds_and_the_implausible_cap_guard() -> None:
    session = date(2024, 6, 3)
    pence = tape.cap_in_rank_currency(
        250, "GBp", 1_000_000, rank_currency="GBP", session=session, eurgbp={}, usdgbp={}
    )
    pounds = tape.cap_in_rank_currency(
        250, "GBP", 1_000_000, rank_currency="GBP", session=session, eurgbp={}, usdgbp={}
    )
    assert pence["reason"] is None
    assert pence["cap"] == pytest.approx(2_500_000)
    assert pounds["cap"] == pytest.approx(250_000_000)
    tiny = tape.cap_in_rank_currency(
        100, "GBX", 1_000, rank_currency="GBP", session=session, eurgbp={}, usdgbp={}
    )
    huge = tape.cap_in_rank_currency(
        600, "GBP", 1_000_000_000, rank_currency="GBP", session=session, eurgbp={}, usdgbp={}
    )
    missing = tape.cap_in_rank_currency(
        100, None, 1_000_000, rank_currency="GBP", session=session, eurgbp={}, usdgbp={}
    )
    assert tiny["reason"] == "cap_unit_implausible"
    assert huge["reason"] == "cap_unit_implausible"
    assert missing["reason"] == "cap_not_computable"
    counted = tape.rank_month(
        [
            {"symbol": "X", "cap": None, "cap_reason": "cap_unit_implausible"},
            {"symbol": "Y", "cap": None, "cap_reason": "cap_not_computable"},
        ],
        rank_count=1,
    )
    assert counted["cap_unit_implausible"] == 1
    assert counted["cap_not_computable"] == 1
    assert counted["members"] == []


def test_rank_keeps_a_delisted_name_and_breaks_ties_by_symbol() -> None:
    last = date(2014, 1, 31)
    assert tape.listed_on(last, delisted=True, last_bar=last)
    assert not tape.listed_on(date(2014, 2, 28), delisted=True, last_bar=last)
    ranked = tape.rank_month(
        [
            {"symbol": "BBB.LSE", "cap": 10.0, "cap_reason": None, "general_type": "Common Stock"},
            {"symbol": "AAA.LSE", "cap": 10.0, "cap_reason": None, "general_type": "Common Stock"},
            {"symbol": "DEL.LSE", "cap": 50.0, "cap_reason": None, "general_type": "Common Stock"},
        ],
        rank_count=2,
    )
    assert ranked["members"] == ["DEL.LSE", "AAA.LSE"]
    assert ranked["cap_tie_broken_by_symbol"] == 1


def test_cap_not_computable_is_counted_and_not_carried() -> None:
    january = tape.rank_month(
        [{"symbol": "AAA.LSE", "cap": 10.0, "cap_reason": None, "general_type": "Common Stock"}],
        rank_count=1,
    )
    february = tape.rank_month(
        [
            {
                "symbol": "AAA.LSE",
                "cap": None,
                "cap_reason": "cap_not_computable",
                "general_type": "Common Stock",
            }
        ],
        rank_count=1,
    )
    assert january["members"] == ["AAA.LSE"]
    assert february["members"] == []
    assert february["cap_not_computable"] == 1


def test_shares_use_date_formatted_and_splits_scale() -> None:
    chosen = tape.select_shares(
        [
            {"date": "2020", "shares": 1},
            {"dateFormatted": "2020-06-01", "shares": 100},
        ],
        [{"dateFormatted": "2020-06-01", "shares": 80}],
        date(2020, 12, 31),
    )
    assert chosen is not None
    assert chosen["shares"] == 80
    assert chosen["period"] == "quarterly"
    later = tape.select_shares(
        [{"dateFormatted": "2020-09-01", "shares": 50}],
        [{"dateFormatted": "2020-03-01", "shares": 80}],
        date(2020, 12, 31),
    )
    assert later is not None and later["shares"] == 50
    scaled, bad = tape.scale_shares(
        100, date(2020, 1, 1), [{"date": "2020-06-01", "split": "2/1"}], date(2020, 12, 31)
    )
    assert scaled == 200 and bad is False
    missing, unparsed = tape.scale_shares(
        100, date(2020, 1, 1), [{"date": "2020-06-01", "split": "2"}], date(2020, 12, 31)
    )
    assert missing is None and unparsed is True


def test_availability_is_filing_date_or_period_end_plus_lags() -> None:
    filed = tape.first_visible_session(
        period_end=date(2013, 12, 31), filing_date=date(2014, 3, 1), annual=True
    )
    lagged = tape.first_visible_session(
        period_end=date(2013, 12, 31), filing_date=None, annual=True
    )
    interim = tape.first_visible_session(
        period_end=date(2014, 3, 31), filing_date=None, annual=False
    )
    assert filed == date(2014, 3, 3)
    assert lagged == date(2013, 12, 31) + timedelta(days=180 + 2)
    assert interim == date(2014, 3, 31) + timedelta(days=90 + 2)


def _ch_filing() -> dict:
    def money(value: str) -> dict:
        return {"value": value, "scale": "millions", "unit": None, "source": "primary"}

    return {
        "fiscal_year": 2014,
        "fiscal_year_end": "2014-12-31",
        "filing_date": "2015-03-18",
        "fields": {
            "revenue": money("100"),
            "operating_profit": money("10"),
            "profit_attributable_to_owners": money("8"),
            "basic_eps": {"value": "12.5", "scale": "units", "unit": "pence", "source": "primary"},
            "weighted_average_basic_shares": {
                "value": "50",
                "scale": "millions",
                "unit": None,
                "source": "primary",
            },
            "net_cash_from_operating_activities": money("20"),
            "capital_expenditure": money("5"),
        },
        "comparative": {
            "fiscal_year": 2013,
            "fiscal_year_end": "2013-12-31",
            "filing_date": "2015-03-18",
            "fields": {
                "revenue": {
                    "value": "90",
                    "scale": "millions",
                    "unit": None,
                    "source": "comparative",
                },
                "basic_eps": {
                    "value": "10",
                    "scale": "units",
                    "unit": "pence",
                    "source": "comparative",
                },
            },
        },
    }


def test_companies_house_fills_only_a_year_eodhd_lacks_and_does_not_carry() -> None:
    eodhd = tape.eodhd_annual_statements(
        {
            "Financials": {
                "Income_Statement": {
                    "yearly": {
                        "2014-12-31": {
                            "totalRevenue": 1.0,
                            "netIncome": 1.0,
                            "filing_date": "2015-03-01",
                        }
                    }
                },
                "Cash_Flow": {
                    "yearly": {
                        "2014-12-31": {
                            "totalCashFromOperatingActivities": 5,
                            "capitalExpenditures": 2,
                        }
                    }
                },
            }
        }
    )
    assert eodhd[0]["free_cashflow"] is None
    flipped = tape.eodhd_annual_statements(
        {
            "Financials": {
                "Income_Statement": {"yearly": {"2014-12-31": {"totalRevenue": 1, "netIncome": 1}}},
                "Cash_Flow": {
                    "yearly": {
                        "2014-12-31": {
                            "totalCashFromOperatingActivities": 5,
                            "capitalExpenditures": -2,
                        }
                    }
                },
            }
        }
    )
    assert flipped[0]["free_cashflow"] == 3
    merged = tape.merge_statement_years(eodhd, tape.ch_statements([_ch_filing()]))
    by_year = {row["year"]: row for row in merged}
    assert by_year[2014]["total_revenue"] == 1.0
    assert by_year[2013]["source"] == "comparative"
    assert by_year[2013]["filing_date"] == date(2015, 3, 18)
    assert tape.first_visible_session(
        period_end=by_year[2013]["period_end"],
        filing_date=by_year[2013]["filing_date"],
        annual=True,
    ) == date(2015, 3, 20)
    assert 2015 not in by_year
    blocked = tape.merge_statement_years(
        eodhd
        + [
            {
                "year": 2013,
                "period_end": date(2013, 12, 31),
                "filing_date": date(2014, 3, 1),
                "total_revenue": 1.0,
                "source": "primary",
            }
        ],
        tape.ch_statements([_ch_filing()]),
    )
    kept = {row["year"]: row for row in blocked}
    assert kept[2013]["total_revenue"] == 1.0
    assert kept[2013]["source"] == "primary"


def test_delisting_exit_uses_the_last_close_and_the_sensitivity_haircut() -> None:
    closes = _decline() + _LADDER
    dead = _name(closes, "DEAD", "buy")
    longer = _decline() + [100.0] * 30
    alive = _name(longer, "LIVE", "hold")
    haircuts = {"DEAD": {BASELINE: 0.0, SENSITIVITY: -0.30}}
    results = walk_variants([dead, alive], haircuts, last_signal="2025-09-30")
    baseline = next(
        row
        for row in results[BASELINE]["episodes"]
        if row["column"] == "primary" and row["ticker"] == "DEAD"
    )
    sensitive = next(
        row
        for row in results[SENSITIVITY]["episodes"]
        if row["column"] == "primary" and row["ticker"] == "DEAD"
    )
    assert baseline["exit_reason"] == "delisted"
    assert baseline["exit_fill"] == pytest.approx(101.5)
    assert sensitive["exit_fill"] == pytest.approx(101.5 * 0.7)
    assert tape.haircut_for("sirius", variant="sensitivity", delisted=True) == 0.0
    assert tape.haircut_for("carillion", variant="sensitivity", delisted=True) == -0.30
    store = committed_store(results=results, phase="development", markets=["ftse350"])
    assert_store_has_no_licensed_numbers(store)
    text = json.dumps(store)
    assert "adjusted_close" not in text
    assert "exit_fill" not in text
    tainted = json.loads(text)
    tainted["close"] = 123.4
    with pytest.raises(ValueError, match="Forbidden licensed field"):
        assert_store_has_no_licensed_numbers(tainted)


def test_unsealed_registration_refuses_before_any_eodhd_call(tmp_path: Path) -> None:
    root = _repo(tmp_path, sealed=False)
    called: list[str] = []

    def opener(url: str, timeout: int = 60) -> _Resp:
        del timeout
        called.append(url)
        raise AssertionError("EODHD was called")

    client = EodhdClient("secret-token", opener=opener, min_interval=0)
    with pytest.raises(UnsealedRegistration):
        run_fetch(client, repo_root=root, cache=tmp_path / "cache", exchanges=["LSE"])
    assert called == []


def test_reveal_refuses_without_the_owner_stamp(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / STORE_PATH).write_text(
        json.dumps({"development": {"counts": {"episodes": 1}}, "reveal": None}),
        encoding="utf-8",
    )
    with pytest.raises(RevealRefused, match="stamp"):
        uk.reveal(repo_root=root, records=[])
    with pytest.raises(RevealRefused, match="development"):
        uk.stamp_reveal("owner", root / "missing")


def test_budget_partial_resumes_on_the_next_utc_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path, sealed=True)
    monkeypatch.setitem(REGISTRATION_CONSTANTS, "DAILY_CALL_BUDGET_SOFT_CAP", 15)
    calls: list[str] = []

    def opener(url: str, timeout: int = 60) -> _Resp:
        del timeout
        calls.append(url)
        return _route(url)

    cache = tmp_path / "cache"
    client = EodhdClient("secret-token", opener=opener, min_interval=0)
    first = run_fetch(
        client,
        repo_root=root,
        cache=cache,
        today=date(2026, 11, 18),
        exchanges=["LSE"],
    )
    assert first["status"] == "partial"
    assert first["done_symbols"] == 0
    assert first["weighted"] == 15
    assert not any("eod/AAA.LSE" in url for url in calls)
    second = run_fetch(
        client,
        repo_root=root,
        cache=cache,
        today=date(2026, 11, 19),
        exchanges=["LSE"],
    )
    assert second["status"] == "complete"
    assert second["done_symbols"] == 1
    assert second["weighted"] == 2
    assert any("eod/AAA.LSE" in url for url in calls)
    cursor = json.loads((cache / "cursor.json").read_text(encoding="utf-8"))
    assert cursor["history"][0]["partial"] is True
    assert cursor["history"][0]["weighted"] == 15


def test_a_wrong_probe_weight_stops_before_the_name_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path, sealed=True)
    monkeypatch.setitem(REGISTRATION_CONSTANTS, "DAILY_CALL_BUDGET_SOFT_CAP", 100)
    calls: list[str] = []

    def opener(url: str, timeout: int = 60) -> _Resp:
        del timeout
        calls.append(url)
        headers = {"x-call-weight": "5"} if "fundamentals/" in url else None
        return _route(url, headers)

    with pytest.raises(WeightProbeFailed):
        run_fetch(
            EodhdClient("secret-token", opener=opener, min_interval=0),
            repo_root=root,
            cache=tmp_path / "cache",
            today=date(2026, 11, 18),
            exchanges=["LSE"],
        )
    assert any("fundamentals/" in url for url in calls)
    assert not any("eod/AAA.LSE" in url for url in calls)


def test_fetch_plan_matches_the_measured_lse_list() -> None:
    plan = fetch_plan()
    assert plan["weighted"] == 86818
    assert plan["http"] == 26716
    assert plan["headroom"] == 3182
    assert plan["sealed_total"] == 86818
    assert plan["europe_name_cap"] == 6922
    assert plan["weighted"] == REGISTRATION_CONSTANTS["LSE_WEIGHTED_CALLS"]
    assert plan["weighted"] < REGISTRATION_CONSTANTS["DAILY_CALL_BUDGET_SOFT_CAP"]


def test_committed_registration_is_sealed_to_the_document() -> None:
    payload = json.loads((Path(uk.REPO_ROOT) / REGISTRATION_PATH).read_text(encoding="utf-8"))
    assert payload["sealed"] is True
    assert payload["registration_id"] == "strategy-book-uk-replay-v0"
    assert payload["influences_live"] is False
    assert payload["reveal_stamp"] is None
    assert payload["constants"]["DAILY_CALL_BUDGET_SOFT_CAP"] == 90000
    assert payload["constants"]["FAMILY_SIZE"] == 4
    assert payload["constants"]["SUBSCRIPTION_END"] == "2026-12-10"
    require_sealed(Path(uk.REPO_ROOT))


def test_a_changed_document_breaks_the_seal(tmp_path: Path) -> None:
    root = _repo(tmp_path, sealed=True)
    require_sealed(root)
    (root / "docs/ops/strategy-book-uk-replay-registration-draft.md").write_text(
        "changed\n", encoding="utf-8"
    )
    with pytest.raises(UnsealedRegistration, match="sha256"):
        require_sealed(root)


def test_ops_finding_is_absent_info_or_warn(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    (empty / "docs/data").mkdir(parents=True)
    assert check_strategy_book_uk_replay(repo_root=empty) == []
    bad = tmp_path / "bad"
    (bad / STORE_PATH).parent.mkdir(parents=True)
    (bad / STORE_PATH).write_text("{", encoding="utf-8")
    warned = check_strategy_book_uk_replay(repo_root=bad)
    assert warned[0].severity == "warn"
    assert warned[0].title == TITLE_FAILED
    assert warned[0].auto_fixable is False
    good = tmp_path / "good"
    (good / STORE_PATH).parent.mkdir(parents=True)
    (good / STORE_PATH).write_text(
        json.dumps(
            {"phase": "fetch", "status": "partial", "holdout": None, "markets_scored": ["ftse350"]}
        ),
        encoding="utf-8",
    )
    found = check_strategy_book_uk_replay(repo_root=good)
    assert found[0].severity == "info"
    assert found[0].title == TITLE
    assert found[0].auto_fixable is False
    assert "fetch" in found[0].summary
    assert "not_revealed" in found[0].summary


def test_plan_does_not_need_a_seal_and_a_missing_token_is_a_soft_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert fetch_plan()["names"] == 3794 + 2884
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    monkeypatch.setattr(uk, "REPO_ROOT", _repo(tmp_path))
    assert uk.main(["fetch"]) == 0
    monkeypatch.setenv("EODHD_API_TOKEN", "secret-token")
    assert uk.main(["fetch"]) == 2


def test_workflow_keeps_the_cache_outside_the_checkout() -> None:
    text = (Path(uk.REPO_ROOT) / ".github/workflows/strategy-book-uk-replay.yml").read_text(
        encoding="utf-8"
    )
    for line in text.splitlines():
        if "uk-replay-cache" in line and ("path:" in line or "_CACHE:" in line or "CACHE_" in line):
            assert "${{ runner.temp }}/" in line, line
    assert "--cache uk-replay-cache" not in text


def test_time_budget_stops_cleanly_and_the_next_run_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path, sealed=True)
    monkeypatch.setitem(REGISTRATION_CONSTANTS, "DAILY_CALL_BUDGET_SOFT_CAP", 100)
    calls: list[str] = []

    def opener(url: str, timeout: int = 60) -> _Resp:
        del timeout
        calls.append(url)
        return _route(url)

    ticks = iter(range(1000))
    cache = tmp_path / "cache"
    client = EodhdClient("secret-token", opener=opener, min_interval=0)
    first = run_fetch(
        client,
        repo_root=root,
        cache=cache,
        today=date(2026, 11, 18),
        exchanges=["LSE"],
        max_minutes=3 / 60,
        clock=lambda: float(next(ticks)),
    )
    assert first["status"] == "partial"
    assert first["stopped_by"] == "time_budget"
    cursor = json.loads((cache / "cursor.json").read_text(encoding="utf-8"))
    assert cursor["today_weighted"] == first["weighted"] > 0
    before = len(calls)
    second = run_fetch(
        client, repo_root=root, cache=cache, today=date(2026, 11, 18), exchanges=["LSE"]
    )
    assert second["status"] == "complete"
    assert second["stopped_by"] is None
    assert second["weighted"] > first["weighted"]
    assert len(calls) > before


def test_a_truncated_raw_file_is_fetched_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path, sealed=True)
    monkeypatch.setitem(REGISTRATION_CONSTANTS, "DAILY_CALL_BUDGET_SOFT_CAP", 100)
    calls: list[str] = []

    def opener(url: str, timeout: int = 60) -> _Resp:
        del timeout
        calls.append(url)
        return _route(url)

    cache = tmp_path / "cache"
    client = EodhdClient("secret-token", opener=opener, min_interval=0)
    run_fetch(client, repo_root=root, cache=cache, today=date(2026, 11, 18), exchanges=["LSE"])
    eod = cache / "raw" / "AAA.LSE" / "eod.json"
    eod.write_text('[{"date": "2020-01-0', encoding="utf-8")
    cursor = json.loads((cache / "cursor.json").read_text(encoding="utf-8"))
    cursor["done"] = {}
    (cache / "cursor.json").write_text(json.dumps(cursor), encoding="utf-8")
    calls.clear()
    run_fetch(client, repo_root=root, cache=cache, today=date(2026, 11, 18), exchanges=["LSE"])
    assert [url for url in calls if "eod/AAA.LSE" in url]
    assert not [url for url in calls if "fundamentals/AAA.LSE" in url]
    json.loads(eod.read_text(encoding="utf-8"))
    assert not list(cache.rglob("*.partial"))
