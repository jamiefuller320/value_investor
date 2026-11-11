"""Tests for EODHD coverage check (plan step 3.3). No network."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from value_investor import eodhd_coverage_check as ecc
from value_investor.eodhd_coverage_check import (
    CHECK_A_MIN_FOUND_WITH_PRICES_TO_END,
    CHECK_A_MIN_WITH_FUNDAMENTALS,
    EodhdClient,
    assert_report_has_no_licensed_numbers,
    compute_verdict,
    main,
    redact_token,
    resolve_known_failure,
    run_eodhd_coverage_check,
    write_report,
)


class _MockResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _MockResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _mock_opener(
    routes: dict[str, Any], *, default_eod: Any | None = None, default_fund: Any | None = None
):
    default_eod = default_eod or _eod_series("2024-06-01", "2012-01-01")
    default_fund = default_fund or {
        **_annual_fundamentals(2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017),
        "outstandingShares": {
            "annual": {
                "2010-12-31": {"date": "2010-12-31", "shares": 100},
                "2020-12-31": {"date": "2020-12-31", "shares": 100},
            }
        },
    }

    def opener(url: str, timeout: int = 0) -> _MockResponse:
        for key, payload in routes.items():
            if key in url:
                return _MockResponse(json.dumps(payload))
        if "eod/" in url:
            return _MockResponse(json.dumps(default_eod))
        if "fundamentals/" in url:
            return _MockResponse(json.dumps(default_fund))
        if "exchange-symbol-list/" in url:
            return _MockResponse(json.dumps([{"Code": "AAA", "Name": "Sample plc"}] * 50))
        if "search/" in url:
            return _MockResponse(json.dumps([{"Code": "AAA", "Name": "Sample plc"}]))
        raise AssertionError(f"Unexpected URL {url}")

    return opener


def _annual_fundamentals(*years: int, dated: bool = True) -> dict[str, Any]:
    yearly = {}
    for y in years:
        yearly[str(y)] = {
            "date": f"{y}-12-31",
            "filing_date": f"{y + 1}-03-01" if dated else None,
        }
    return {
        "General": {"CurrencyCode": "GBP"},
        "Financials": {"Income_Statement": {"yearly": yearly}},
        "outstandingShares": {"annual": {"2020-12-31": {"date": "2020-12-31", "shares": 1}}},
    }


def _eod_series(last: str, first: str = "2012-01-01") -> list[dict[str, Any]]:
    return [
        {"date": first, "adjusted_close": 1.0, "close": 1.0},
        {"date": last, "adjusted_close": 0.5, "close": 0.5},
    ]


def test_redact_token_in_errors() -> None:
    msg = redact_token("failed https://eodhd.com/api/?api_token=SECRET123", "SECRET123")
    assert "SECRET123" not in msg
    assert "***" in msg


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ecc, "MIN_INTERVAL_SEC", 0.0)


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    for market, tickers in (
        ("dax", ["ADS.DE", "ALV.DE", "BAS.DE", "BMW.DE", "SAP.DE"]),
        ("cac40", ["AIR.PA", "BNP.PA", "MC.PA", "OR.PA", "SAN.PA"]),
    ):
        const_dir = tmp_path / "markets" / market / "constituents"
        const_dir.mkdir(parents=True)
        rows = [{"ticker": t, "name": t} for t in tickers]
        (const_dir / "latest.json").write_text(json.dumps(rows), encoding="utf-8")
    return tmp_path


def _passing_routes() -> dict[str, Any]:
    delisted_lse = [
        {"Code": "CARIL", "Name": "Carillion plc"},
        {"Code": "SKYOLD", "Name": "Sky plc"},
    ]
    routes: dict[str, Any] = {
        "exchange-symbol-list/LSE?": delisted_lse,
        "exchange-symbol-list/LSE": delisted_lse,
        "exchange-symbol-list/XETRA": [{"Code": "WDI", "Name": "Wirecard AG"}],
    }

    def add_search(name: str, code: str) -> None:
        routes[f"search/{name.replace(' ', '%20')}"] = [{"Code": code, "Name": name}]
        routes[f"search/{name}"] = [{"Code": code, "Name": name}]

    for case in ecc.KNOWN_FAILURE_CASES:
        code = "CARIL" if case["key"] == "carillion" else case["key"][:4].upper()
        add_search(str(case["name"]), code)
        sym = f"{code}.{case['exchange']}"
        routes[f"eod/{sym}"] = _eod_series(str(case["known_end"]))
        routes[f"fundamentals/{sym}"] = _annual_fundamentals(2012, 2013, 2014, 2015)

    for ticker in ["AAA.L", "BBB.L"]:
        sym = f"{ticker.split('.')[0]}.LSE"
        routes[f"eod/{sym}"] = _eod_series("2024-01-01", "2012-01-01")
        routes[f"fundamentals/{sym}"] = _annual_fundamentals(2012, 2013, 2014, 2015, 2016)

    for ticker in ["ADS.DE", "ALV.DE"]:
        sym = f"{ticker.split('.')[0]}.XETRA"
        routes[f"eod/{sym}"] = _eod_series("2024-01-01", "2012-01-01")
        routes[f"fundamentals/{sym}"] = _annual_fundamentals(2012, 2013, 2014, 2015)

    routes["exchange-symbol-list/LSE?delisted"] = delisted_lse
    routes["exchange-symbol-list/LSE?type=common_stock"] = [{"Code": "AAA"}] * 100
    return routes


def test_check_a_pass_and_fail_paths() -> None:
    client = EodhdClient("tok", opener=_mock_opener(_passing_routes()))
    row = resolve_known_failure(client, ecc.KNOWN_FAILURE_CASES[0])
    assert row["found"] is True
    assert row["resolved_code"] != "absent"

    fail_routes = {"search/Carillion": [{"Code": "TOTALLY", "Name": "Other plc"}]}
    client2 = EodhdClient("tok", opener=_mock_opener(fail_routes))
    row2 = resolve_known_failure(client2, ecc.KNOWN_FAILURE_CASES[0])
    assert row2["found"] is False


def test_resolution_prefers_name_match_over_reused_code() -> None:
    routes = {
        "search/Carillion": [{"Code": "TSCO", "Name": "Tesco PLC"}],
        "exchange-symbol-list/LSE": [
            {"Code": "CARIL", "Name": "Carillion plc", "Type": "Common Stock"}
        ],
    }
    client = EodhdClient("tok", opener=_mock_opener(routes))
    row = resolve_known_failure(client, ecc.KNOWN_FAILURE_CASES[0])
    assert row["found"] is True
    assert row["resolved_code"] == "CARIL"
    assert row["match_source"] == "delisted_list"


def _ftse_rows(frame: pd.DataFrame) -> list[dict[str, str]]:
    return [{"ticker": str(t), "name": str(t), "market": "ftse350"} for t in frame["ticker"]]


def test_name_match_needs_whole_words() -> None:
    assert ecc._name_matches("Sky", "Sky PLC")
    assert not ecc._name_matches("Sky", "SkyePharma PLC")
    assert not ecc._name_matches("Sky", "")
    assert ecc._name_matches("Thomas Cook Group", "Thomas Cook Group plc")


def test_prices_after_the_event_still_reach_it() -> None:
    assert ecc._prices_to_known_end("2018-11-07", "2018-09-26")
    assert ecc._prices_to_known_end("2018-09-20", "2018-09-26")
    assert not ecc._prices_to_known_end("2018-06-01", "2018-09-26")


def test_earnings_history_is_not_a_shares_history() -> None:
    summary = ecc._fundamentals_summary({"Earnings": {"History": {"2020-12-31": {}}}})
    assert summary["shares_outstanding_history_present"] is False


def test_ftse_sample_is_spread_across_the_committed_list(tmp_path: Path) -> None:
    rows = [{"ticker": f"{chr(65 + i // 4)}{i}.L"} for i in range(100)]
    path = tmp_path / ecc.FTSE350_SAMPLE_SOURCE
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    picked = ecc._load_ftse350_tickers(tmp_path, limit=30)
    assert len(picked) == 30
    assert len({row["ticker"][0] for row in picked}) > 15


def test_missing_fields_become_absent() -> None:
    summary = ecc._fundamentals_summary({"General": {}, "Financials": {}})
    assert summary["currency_code"] == "absent"
    assert summary["fundamentals_years_from_2013"] == "absent"


def test_call_budget_stops_with_partial_reason(library_root: Path) -> None:
    routes = _passing_routes()
    client = EodhdClient("tok", max_calls=5, opener=_mock_opener(routes))
    ftse = pd.DataFrame({"ticker": ["AAA.L"], "name": ["A"]})
    with patch.object(ecc, "_load_ftse350_tickers", return_value=_ftse_rows(ftse)):
        payload = run_eodhd_coverage_check(client, library_root=library_root)
    assert client.budget_exhausted is True
    assert payload["verdict"] in {"partial", "fail"}
    assert any("budget" in r.lower() for r in payload["reasons"])


def test_report_has_no_prices_or_financial_values(tmp_path: Path, library_root: Path) -> None:
    routes = _passing_routes()
    client = EodhdClient("tok", max_calls=5000, opener=_mock_opener(routes))
    ftse = pd.DataFrame({"ticker": [f"T{i:02d}.L" for i in range(30)], "name": ["n"] * 30})
    with patch.object(ecc, "_load_ftse350_tickers", return_value=_ftse_rows(ftse)):
        payload = run_eodhd_coverage_check(client, library_root=library_root)
    out = tmp_path / "report.json"
    write_report(payload, out)
    text = out.read_text(encoding="utf-8")
    assert re.search(r'"adjusted_close"\s*:', text) is None
    assert re.search(r'"close"\s*:\s*[0-9]', text) is None
    assert_report_has_no_licensed_numbers(payload)
    for line in text.splitlines():
        if re.search(r'"(close|revenue|open)":\s*[0-9]', line):
            pytest.fail(f"numeric price field in report: {line}")


def test_missing_token_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--out", "/tmp/absent.json"])
    assert code == 0
    assert "not set" in capsys.readouterr().err.lower()


def test_token_not_in_http_error() -> None:
    token = "MY-SECRET-TOKEN"

    def boom(url: str, timeout: int = 0) -> None:
        raise RuntimeError(f"http error for {url}")

    client = EodhdClient(token, opener=boom)
    with pytest.raises(RuntimeError) as exc:
        client.get_json("search/foo")
    assert token not in str(exc.value)


def test_compute_verdict_paths() -> None:
    check_a = {"pass": True}
    check_b = {"pass": True}
    check_d = {"pass": True}
    assert compute_verdict(check_a, check_b, check_d)["verdict"] == "pass"
    check_b["pass"] = False
    assert compute_verdict(check_a, check_b, check_d)["verdict"] == "partial"
    check_a["pass"] = False
    assert compute_verdict(check_a, check_b, check_d)["verdict"] == "fail"


def test_ops_monitor_absent_pass_unreadable(tmp_path: Path) -> None:
    from value_investor.ops_monitor import check_eodhd_coverage

    assert check_eodhd_coverage(repo_root=tmp_path) == []

    store = tmp_path / "docs" / "data" / "eodhd_coverage_check.json"
    store.parent.mkdir(parents=True)
    store.write_text(
        json.dumps(
            {
                "verdict": "pass",
                "generated_at": "2026-11-11T00:00:00+00:00",
                "calls_used": 1,
                "max_calls": 3000,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    [info] = check_eodhd_coverage(repo_root=tmp_path)
    assert info.severity == "info"
    assert "pass" in info.summary

    store.write_text("{not json", encoding="utf-8")
    [warn] = check_eodhd_coverage(repo_root=tmp_path)
    assert warn.severity == "warn"


def test_full_run_verdict_pass_with_mocks(library_root: Path) -> None:
    routes = _passing_routes()
    client = EodhdClient("tok", max_calls=8000, opener=_mock_opener(routes))
    ftse = pd.DataFrame({"ticker": [f"T{i:02d}.L" for i in range(30)], "name": ["n"] * 30})
    with patch.object(ecc, "_load_ftse350_tickers", return_value=_ftse_rows(ftse)):
        payload = run_eodhd_coverage_check(client, library_root=library_root)
    assert (
        payload["checks"]["a_survivorship"]["found_with_prices_to_end_count"]
        >= CHECK_A_MIN_FOUND_WITH_PRICES_TO_END
    )
    assert (
        payload["checks"]["a_survivorship"]["with_fundamentals_count"]
        >= CHECK_A_MIN_WITH_FUNDAMENTALS
    )
    assert payload["verdict"] == "pass"


def test_eodhd_workflow_uses_shared_commit_helper() -> None:
    text = Path(".github/workflows/eodhd-coverage-check.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "scripts/gha_commit_artifacts.sh" in text
    assert "docs/data/eodhd_coverage_check.json" in text
    assert "EODHD_API_TOKEN" in text
