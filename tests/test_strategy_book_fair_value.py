"""Verdict paths for the observe-only strategy-book fair-value range."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from value_investor.ops_monitor import check_strategy_book_fair_value
from value_investor.strategy_book_fair_value import (
    BUCKET_MIN_N,
    ENTRY_REFERENCE,
    REASON_CLOSE_MISSING,
    REASON_CURRENCY,
    REASON_CURRENCY_DISAGREE,
    REASON_FEW_YEARS,
    REASON_FINANCIALS_AFTER,
    REASON_FINANCIALS_MISSING,
    REASON_FINANCIALS_UNDATED,
    REASON_FX,
    REASON_IMPLAUSIBLE,
    REASON_NON_POSITIVE,
    REASON_SIGNAL_SESSION,
    TITLE_INFO,
    TITLE_MISSING,
    TITLE_STALE,
    TITLE_UNREADABLE,
    FxHistory,
    _bucket_id,
    _note_currency,
    build_fair_value_store,
    closes_in_window,
    currencies_in_statement_text,
    currency_from_filings,
    evaluate_statements,
    findings_for_store,
    load_json_known_on,
    main,
    recovery_from_closes,
    resolve_statement_currency,
    score_rows,
    store_path,
    write_store,
)

SIGNAL = date(2026, 11, 10)
FETCHED = "2026-11-01T00:00:00+00:00"


def _fx(usd_per_gbp: float = 1.25) -> FxHistory:
    return FxHistory({"GBP": [(date(2026, 11, 9), usd_per_gbp)]})


def _statements(
    earnings: list[tuple[int, float]],
    *,
    fetched: str | None = FETCHED,
    cash: list[tuple[int, float]] | None = None,
    shares: float | None = 1_000_000.0,
) -> dict:
    income: dict[str, dict] = {}
    for year, eps in earnings:
        row: dict = {"Diluted EPS": eps}
        if shares is not None:
            row["Diluted Average Shares"] = shares
        income[str(year)] = row
    flow: dict[str, dict] = {}
    for year, fcf in cash or []:
        flow[str(year)] = {"Free Cash Flow": fcf}
    payload: dict = {"income_statement": income, "cash_flow": flow}
    if fetched is not None:
        payload["fetched_at"] = fetched
    return payload


def _evaluate(**overrides):
    base = {
        "signal_session": SIGNAL,
        "entry_price": 1500.0,
        "price_unit": "GBX",
        "major_currency": "GBP",
        "financials": _statements([(2022, 1.0), (2023, 2.0), (2024, 3.0)]),
        "financials_state": "file",
        "financials_path": "docs/data/research/AAA.L/sources/financials_annual.json",
        "statement_currency": "GBP",
        "currency_detail": {"currency": "GBP", "sources": []},
        "fx": None,
        "window_closes": [],
        "closed": False,
    }
    base.update(overrides)
    return evaluate_statements(**base)


def test_range_uses_normalised_eps_and_london_pence():
    # Mean EPS £2 × 100 = 200p. Mid is 15 × 200p = 3000p. Close 1500p.
    row = _evaluate()
    assert row["verdict"] == "range"
    assert row["method"] == "normalised_earnings"
    assert row["entry_reference"] == ENTRY_REFERENCE
    assert row["price_unit"] == "GBX"
    assert row["entry_reference_unit"] == "GBX"
    assert row["range"]["unit"] == "GBX"
    assert row["range"]["low"] == pytest.approx(2000.0)
    assert row["range"]["mid"] == pytest.approx(3000.0)
    assert row["range"]["high"] == pytest.approx(4000.0)
    assert row["margin_of_safety"] == pytest.approx(0.5)
    assert row["inputs"]["normalised_per_share"] == pytest.approx(2.0)
    assert row["inputs"]["years"] == [
        {"year": 2022, "eps": 1.0, "fcf": None, "shares": 1_000_000.0, "fcf_per_share": None},
        {"year": 2023, "eps": 2.0, "fcf": None, "shares": 1_000_000.0, "fcf_per_share": None},
        {"year": 2024, "eps": 3.0, "fcf": None, "shares": 1_000_000.0, "fcf_per_share": None},
    ]
    assert row["reverse_dcf"]["status"] == "computed"
    assert row["recovery"]["label"] == "not_closed"


def test_usd_statements_on_a_london_quote_use_fx_then_pence():
    # £ per $ = 1/1.25 = 0.8. EPS $4 → 320p. Mid 15 × 320 = 4800p.
    row = _evaluate(
        financials=_statements([(2022, 4.0), (2023, 4.0), (2024, 4.0)]),
        statement_currency="USD",
        currency_detail={"currency": "USD"},
        entry_price=4000.0,
        fx=_fx(1.25),
    )
    assert row["verdict"] == "range"
    assert row["range"]["mid"] == pytest.approx(4800.0)
    assert row["margin_of_safety"] == pytest.approx(1.0 - 4000.0 / 4800.0, abs=1e-6)
    assert row["inputs"]["fx"]["pair"] == "GBP per USD"
    assert row["inputs"]["fx"]["rate"] == pytest.approx(0.8)


def test_us_listing_is_not_scaled_into_pence():
    row = _evaluate(
        price_unit="USD",
        major_currency="USD",
        statement_currency="USD",
        entry_price=100.0,
        financials=_statements([(2022, 10.0), (2023, 10.0), (2024, 10.0)]),
    )
    assert row["verdict"] == "range"
    assert row["range"]["unit"] == "USD"
    assert row["range"]["mid"] == pytest.approx(150.0)
    assert row["margin_of_safety"] == pytest.approx(1.0 - 100.0 / 150.0, abs=1e-6)


def test_margin_is_negative_when_the_close_is_above_the_mid():
    row = _evaluate(entry_price=4500.0)
    assert row["verdict"] == "range"
    assert row["margin_of_safety"] == pytest.approx(-0.5)
    assert row["entry_vs_range"] == "above_high"


def test_margin_buckets_include_zero_and_the_boundary():
    assert _bucket_id(-0.01) == "below_0"
    assert _bucket_id(0.0) == "zero_to_0.33"
    assert _bucket_id(0.33) == "zero_to_0.33"
    assert _bucket_id(0.330001) == "above_0.33"


def test_each_insufficient_data_reason():
    missing = _evaluate(financials=None, financials_state="missing")
    assert missing["reason"] == REASON_FINANCIALS_MISSING

    undated = _evaluate(
        financials=_statements([(2022, 1.0), (2023, 1.0), (2024, 1.0)], fetched=None)
    )
    assert undated["reason"] == REASON_FINANCIALS_UNDATED

    late = _evaluate(
        financials=_statements(
            [(2022, 1.0), (2023, 1.0), (2024, 1.0)],
            fetched="2026-11-11T00:00:00+00:00",
        )
    )
    assert late["reason"] == REASON_FINANCIALS_AFTER

    short = _evaluate(financials=_statements([(2023, 1.0), (2024, 1.0)]))
    assert short["reason"] == REASON_FEW_YEARS

    future_only = _evaluate(
        signal_session=date(2024, 6, 1),
        financials=_statements([(2025, 1.0), (2026, 1.0), (2027, 1.0)], fetched="2024-01-01"),
    )
    assert future_only["reason"] == REASON_FEW_YEARS
    assert future_only["inputs"]["years"] == []

    negative = _evaluate(financials=_statements([(2022, -1.0), (2023, -1.0), (2024, 0.5)]))
    assert negative["reason"] == REASON_NON_POSITIVE

    no_close = _evaluate(entry_price=None)
    assert no_close["reason"] == REASON_CLOSE_MISSING

    no_currency = _evaluate(
        statement_currency=None,
        currency_detail={"reason": REASON_CURRENCY, "detail": "none"},
    )
    assert no_currency["reason"] == REASON_CURRENCY

    disagree = _evaluate(
        statement_currency=None,
        currency_detail={"reason": REASON_CURRENCY_DISAGREE, "detail": "USD vs GBP"},
    )
    assert disagree["reason"] == REASON_CURRENCY_DISAGREE

    no_fx = _evaluate(
        statement_currency="USD",
        currency_detail={"currency": "USD"},
        fx=FxHistory({}),
    )
    assert no_fx["reason"] == REASON_FX

    too_low = _evaluate(
        financials=_statements([(2022, 1.0), (2023, 1.0), (2024, 1.0)]),
        entry_price=150.0,
    )
    assert too_low["reason"] == REASON_IMPLAUSIBLE
    assert too_low["verdict"] == "insufficient_data"
    assert too_low["range"] is None
    assert "1.50" in too_low["reason_detail"]
    assert too_low["inputs"]["implied_trailing_pe"] == pytest.approx(1.5)

    too_high = _evaluate(
        financials=_statements([(2022, 1.0), (2023, 1.0), (2024, 1.0)]),
        entry_price=25000.0,
    )
    assert too_high["reason"] == REASON_IMPLAUSIBLE
    assert too_high["inputs"]["implied_trailing_pe"] == pytest.approx(250.0)
    assert "250.00" in too_high["reason_detail"]

    no_session = _evaluate(signal_session=None)
    assert no_session["reason"] == REASON_SIGNAL_SESSION


def test_later_fiscal_year_is_excluded_and_does_not_change_the_average():
    row = _evaluate(
        signal_session=date(2024, 6, 1),
        financials=_statements(
            [(2021, 1.0), (2022, 1.0), (2023, 1.0), (2024, 1.0), (2027, 100.0)],
            fetched="2024-05-01",
        ),
        entry_price=1500.0,
    )
    assert row["verdict"] == "range"
    assert [item["year"] for item in row["inputs"]["years"]] == [2021, 2022, 2023, 2024]
    assert row["inputs"]["normalised_per_share"] == pytest.approx(1.0)
    assert 2027 not in [item["year"] for item in row["inputs"]["years"]]


def test_fcf_per_share_fills_the_gap_when_eps_years_are_short():
    income_years = [(2022, None), (2023, None), (2024, 1.0), (2025, 1.0)]
    financials = _statements([], cash=[(year, 2_000_000.0) for year, _eps in income_years])
    financials["income_statement"] = {
        str(year): {
            "Diluted Average Shares": 1_000_000.0,
            **({} if eps is None else {"Diluted EPS": eps}),
        }
        for year, eps in income_years
    }
    row = _evaluate(financials=financials)
    assert row["verdict"] == "range"
    assert row["method"] == "fcf_per_share"
    assert row["reason"] is None
    # £2 per share × 100 = 200p, mid 3000p.
    assert row["range"]["mid"] == pytest.approx(3000.0)


def test_currency_sources_must_agree():
    code, detail = resolve_statement_currency(
        session=SIGNAL,
        sec={
            "fetched_at": "2026-11-01",
            "annual": [{"first_filed": "2026-01-27", "currency": "USD"}],
        },
        sec_state="file",
        sec_path="sec.json",
        screen_currency="GBP",
        screen_detail={"source": "screen_action_note", "path": "run.json", "as_of": "2026-11-10"},
    )
    assert code is None
    assert detail["reason"] == REASON_CURRENCY_DISAGREE

    code, detail = resolve_statement_currency(
        session=SIGNAL,
        sec={
            "fetched_at": "2026-11-01",
            "annual": [{"first_filed": "2026-01-27", "currency": "USD"}],
        },
        sec_state="file",
        sec_path="sec.json",
        screen_currency=None,
        screen_detail=None,
        explicit=[("USD", {"source": "financials_annual.financialCurrency", "path": "fin.json"})],
    )
    assert code == "USD"
    assert len(detail["sources"]) == 2


def test_snapshot_currency_and_bare_dollar_are_not_evidence(tmp_path: Path):
    code, detail = resolve_statement_currency(
        session=SIGNAL,
        sec=None,
        sec_state="missing",
        sec_path=None,
        screen_currency=None,
        screen_detail=None,
        explicit=[],
    )
    assert code is None
    assert detail["reason"] == REASON_CURRENCY

    assert _note_currency("filing $127M") is None
    assert _note_currency("filing (primary) $88.4M") is None
    assert _note_currency("") is None
    assert _note_currency("Strong Buy — neutral timing | filing £25.2M") == "GBP"
    assert _note_currency("filing €110.8M") == "EUR"
    ignored, ignored_detail = resolve_statement_currency(
        session=SIGNAL,
        sec=None,
        sec_state="missing",
        sec_path=None,
        screen_currency="USD",
        screen_detail={"source": "screen_action_note", "path": "run.json"},
    )
    assert ignored is None
    assert ignored_detail["reason"] == REASON_CURRENCY

    sources = tmp_path / "docs" / "data" / "research" / "BGEO.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(_statements([(2022, 30.0), (2023, 30.0), (2024, 49.5)])),
        encoding="utf-8",
    )
    (sources / "screening_snapshot.json").write_text(
        json.dumps(
            {
                "fcf": {"currency": "GBP", "bridge_resolved": True},
                "fcf_basis_registry": {"currency": "GBP"},
            }
        ),
        encoding="utf-8",
    )
    charts = tmp_path / "docs" / "data" / "charts"
    charts.mkdir(parents=True)
    (charts / "BGEO.L.json").write_text(
        json.dumps(
            {
                "ticker": "BGEO.L",
                "currency": "GBP",
                "dates": ["2026-11-10"],
                "closes": [13480.0],
            }
        ),
        encoding="utf-8",
    )
    observe = {
        "registration_id": "owner-strategy-book-v0",
        "data_commit": "abc",
        "generated_at": "2026-11-11T00:00:00+00:00",
        "episodes": [_episode("BGEO.L")],
    }
    data = tmp_path / "docs" / "data"
    (data / "strategy_book_observe.json").write_text(json.dumps(observe), encoding="utf-8")
    payload = build_fair_value_store(tmp_path, now=datetime(2026, 11, 11, tzinfo=UTC))
    row = payload["episodes"][0]
    assert row["reason"] == REASON_CURRENCY
    assert row["verdict"] == "insufficient_data"
    assert row["statement_currency"] is None


def test_explicit_pound_source_still_builds_a_range():
    code, detail = resolve_statement_currency(
        session=SIGNAL,
        sec=None,
        sec_state="missing",
        sec_path=None,
        screen_currency="GBP",
        screen_detail={"source": "screen_action_note", "path": "run.json", "as_of": "2026-11-10"},
    )
    assert code == "GBP"
    assert detail["sources"][0]["source"] == "screen_action_note"
    row = _evaluate(statement_currency=code, currency_detail=detail)
    assert row["verdict"] == "range"
    assert row["range"]["mid"] == pytest.approx(3000.0)
    assert row["inputs"]["implied_trailing_pe"] == pytest.approx(5.0)


def test_filing_body_unit_is_evidence_and_a_mixed_unit_is_not(tmp_path: Path):
    assert currencies_in_statement_text("profit of GEL 49.5 million") == {"GEL"}
    assert currencies_in_statement_text("filing $127M and US$m 74.6") == {"USD"}
    assert "USD" not in currencies_in_statement_text("filing $127M")
    assert currencies_in_statement_text("in millions of Canadian dollars") == {"CAD"}
    # A stated reporting currency beats a stray sterling amount in the same filing.
    stated = (
        "The Group reports in US dollars, its primary trading currency. "
        "Operating loss of £0.3m on the overdraft."
    )
    assert currencies_in_statement_text(stated) == {"USD"}

    sources = tmp_path / "docs" / "data" / "research" / "CP.TO" / "sources"
    body = sources / "filings" / "bodies"
    body.mkdir(parents=True)
    (body / "cad.txt").write_text(
        "For the year ended (in millions of Canadian dollars) 3.98",
        encoding="utf-8",
    )
    (body / "mixed.txt").write_text("profit of GEL 10 million and £12 million", encoding="utf-8")
    index = {
        "filings": [
            {
                "headline": "10-K: 10-K",
                "published_at": "2026-02-26",
                "has_body": True,
                "period": "annual",
                "body_path": "docs/data/research/CP.TO/sources/filings/bodies/cad.txt",
            },
            {
                "headline": "3rd Quarter Results",
                "published_at": "2026-11-04",
                "has_body": True,
                "period": "interim",
                "body_path": "docs/data/research/CP.TO/sources/filings/bodies/mixed.txt",
            },
        ]
    }
    (sources / "filings" / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    code, detail = currency_from_filings(tmp_path, sources, SIGNAL)
    assert code is None
    assert detail is None

    index["filings"][1]["published_at"] = "2026-11-12"
    (sources / "filings" / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    code, detail = currency_from_filings(tmp_path, sources, SIGNAL)
    assert code == "CAD"
    assert detail is not None
    assert detail["published_at"] == "2026-02-26"


def test_closes_after_the_exit_do_not_count_as_recovery():
    sessions = [date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)]
    window = closes_in_window(sessions, [100.0, 150.0, 500.0], after=sessions[0], until=sessions[1])
    assert window == [150.0]
    assert recovery_from_closes(window, low=200.0, mid=300.0, closed=True)["label"] == "not_reached"
    reached = recovery_from_closes([150.0, 300.0], low=200.0, mid=300.0, closed=True)
    assert reached["label"] == "reached_mid"
    assert reached["reached_low"] is True
    assert reached["reached_mid"] is True
    low_only = recovery_from_closes([250.0], low=200.0, mid=300.0, closed=True)
    assert low_only["label"] == "reached_low_only"
    assert recovery_from_closes([999.0], low=1.0, mid=1.0, closed=False)["label"] == "not_closed"


def _scored_row(margin: float, fair: float, excess: float, *, closed: bool = True) -> dict:
    return {
        "column": "primary",
        "verdict": "range",
        "status": "closed" if closed else "open",
        "mature": True,
        "margin_of_safety": margin,
        "fair_cost_return": fair,
        "matched_excess": excess,
        "recovery": {"label": "not_reached"},
    }


def test_bucket_scoring_is_insufficient_when_a_bucket_has_too_few():
    scored = score_rows([_scored_row(-0.1, 0.01, 0.0), _scored_row(0.1, 0.02, 0.0)])
    assert scored["verdict"] == "insufficient_data"
    assert all(bucket["verdict"] == "insufficient_data" for bucket in scored["buckets"])
    assert all(bucket["median_fair_cost_return"] is None for bucket in scored["buckets"])
    assert scored["recovery"]["verdict"] == "insufficient_data"


def test_bucket_scoring_reports_medians_when_every_bucket_has_enough():
    rows = []
    for _ in range(BUCKET_MIN_N):
        rows.append(_scored_row(-0.2, -0.10, -0.01))
        rows.append(_scored_row(0.10, 0.05, 0.02))
        rows.append(_scored_row(0.50, 0.20, 0.04))
    scored = score_rows(rows)
    assert scored["verdict"] == "scored"
    by_id = {bucket["id"]: bucket for bucket in scored["buckets"]}
    assert by_id["below_0"]["n"] == BUCKET_MIN_N
    assert by_id["below_0"]["median_fair_cost_return"] == pytest.approx(-0.10)
    assert by_id["below_0"]["median_matched_excess"] == pytest.approx(-0.01)
    assert by_id["zero_to_0.33"]["median_fair_cost_return"] == pytest.approx(0.05)
    assert by_id["above_0.33"]["median_matched_excess"] == pytest.approx(0.04)
    assert scored["recovery"]["verdict"] == "scored"
    assert scored["recovery"]["not_reached"] == BUCKET_MIN_N * 3


def _write_name(root: Path, ticker: str, financials: dict, closes: list[float], dates: list[str]):
    sources = root / "docs" / "data" / "research" / ticker / "sources"
    sources.mkdir(parents=True)
    payload = dict(financials)
    payload.setdefault("financialCurrency", "GBP")
    (sources / "financials_annual.json").write_text(json.dumps(payload), encoding="utf-8")
    (sources / "screening_snapshot.json").write_text(
        json.dumps({"fcf": {"currency": "GBP"}}),
        encoding="utf-8",
    )
    charts = root / "docs" / "data" / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    (charts / f"{ticker}.json").write_text(
        json.dumps({"ticker": ticker, "currency": "GBP", "dates": dates, "closes": closes}),
        encoding="utf-8",
    )


def _episode(ticker: str, **overrides) -> dict:
    row = {
        "episode_id": f"ftse350:{ticker}:primary:2026-11-10",
        "market": "ftse350",
        "ticker": ticker,
        "column": "primary",
        "status": "open",
        "signal_session": "2026-11-10",
        "exit_session": None,
        "mature": False,
        "fair_cost_return": 0.01,
        "matched_excess": 0.0,
    }
    row.update(overrides)
    return row


def test_store_write_recovery_and_cli_no_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    dates = ["2026-11-10", "2026-11-11", "2026-11-12"]
    _write_name(
        tmp_path,
        "AAA.L",
        _statements([(2022, 1.0), (2023, 2.0), (2024, 3.0)]),
        [1500.0, 3000.0, 9000.0],
        dates,
    )
    _write_name(
        tmp_path,
        "BBB.L",
        _statements([(2022, 1.0), (2023, 2.0), (2024, 3.0)]),
        [1500.0, 1600.0, 9000.0],
        dates,
    )
    observe = {
        "registration_id": "owner-strategy-book-v0",
        "data_commit": "abc",
        "generated_at": "2026-11-11T00:00:00+00:00",
        "episodes": [
            _episode("BBB.L", column="buy_on_signal", status="closed", exit_session="2026-11-11"),
            _episode("AAA.L", status="closed", exit_session="2026-11-11", mature=True),
        ],
    }
    data = tmp_path / "docs" / "data"
    (data / "strategy_book_observe.json").write_text(json.dumps(observe), encoding="utf-8")

    payload = build_fair_value_store(
        tmp_path, now=datetime(2026, 11, 11, tzinfo=UTC), fx=FxHistory({})
    )
    assert payload["influences_live"] is False
    assert payload["registration_id"] == "owner-strategy-book-v0"
    assert payload["observe_data_commit"] == "abc"
    assert [row["ticker"] for row in payload["episodes"]] == ["AAA.L", "BBB.L"]
    primary = payload["episodes"][0]
    assert primary["column"] == "primary"
    assert primary["verdict"] == "range"
    assert primary["entry_reference_price"] == pytest.approx(1500.0)
    assert primary["recovery"]["label"] == "reached_mid"
    assert primary["recovery"]["closes_used"] == 1
    other = payload["episodes"][1]
    assert other["recovery"]["label"] == "not_reached"
    assert payload["scoring"]["primary"]["verdict"] == "insufficient_data"

    assert main(["--repo-root", str(tmp_path), "--no-write"]) == 0
    assert not store_path(tmp_path).exists()
    printed = json.loads(capsys.readouterr().out)
    assert printed["store"] is None
    assert printed["influences_live"] is False
    assert printed["coverage"]["primary_with_range"] == 1

    assert main(["--repo-root", str(tmp_path)]) == 0
    written = json.loads(store_path(tmp_path).read_text(encoding="utf-8"))
    assert written["influences_live"] is False
    assert written["episodes"][0]["range"]["mid"] == pytest.approx(3000.0)


def test_git_blob_drops_statements_fetched_after_the_signal(tmp_path: Path):
    repo = tmp_path / "repo"
    sources = repo / "docs" / "data" / "research" / "AAA.L" / "sources"
    sources.mkdir(parents=True)
    path = sources / "financials_annual.json"
    early = _statements(
        [(2022, 1.0), (2023, 2.0), (2024, 3.0)], fetched="2026-11-01T00:00:00+00:00"
    )
    path.write_text(json.dumps(early), encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = "2026-11-01T12:00:00+00:00"
    env["GIT_COMMITTER_DATE"] = "2026-11-01T12:00:00+00:00"
    subprocess.run(["git", "add", "docs"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-m", "early"], cwd=repo, check=True, env=env)
    late = _statements([(2022, 9.0), (2023, 9.0), (2024, 9.0)], fetched="2026-11-12T00:00:00+00:00")
    path.write_text(json.dumps(late), encoding="utf-8")
    late_env = os.environ.copy()
    late_env["GIT_AUTHOR_DATE"] = "2026-11-12T12:00:00+00:00"
    late_env["GIT_COMMITTER_DATE"] = "2026-11-12T12:00:00+00:00"
    subprocess.run(["git", "add", "docs"], cwd=repo, check=True, env=late_env)
    subprocess.run(["git", "commit", "-m", "late"], cwd=repo, check=True, env=late_env)

    loaded, state = load_json_known_on(repo, path, SIGNAL, date_field="fetched_at")
    assert state == "git_as_of"
    assert loaded is not None
    assert loaded["income_statement"]["2024"]["Diluted EPS"] == 3.0
    row = evaluate_statements(
        signal_session=SIGNAL,
        entry_price=1500.0,
        price_unit="GBX",
        major_currency="GBP",
        financials=loaded,
        financials_state=state,
        financials_path="docs/data/research/AAA.L/sources/financials_annual.json",
        statement_currency="GBP",
        currency_detail={"currency": "GBP"},
        fx=None,
        window_closes=[],
        closed=False,
    )
    assert row["verdict"] == "range"
    assert row["inputs"]["normalised_per_share"] == pytest.approx(2.0)


def _finding_store(tmp_path: Path, generated_at: str | None, *, broken: bool = False) -> None:
    path = store_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if broken:
        path.write_text("{", encoding="utf-8")
        return
    payload = {
        "generated_at": generated_at,
        "coverage": {
            "primary_episodes": 2,
            "primary_with_range": 2,
            "primary_insufficient_data": 0,
            "primary_margin_median": 0.25,
            "with_range": 4,
            "insufficient_data": 1,
        },
        "scoring": {"primary": {"verdict": "insufficient_data"}},
    }
    write_store(tmp_path, payload)


def test_ops_monitor_missing_stale_and_fresh(tmp_path: Path):
    now = datetime(2026, 11, 11, tzinfo=UTC)
    missing = check_strategy_book_fair_value(repo_root=tmp_path, now=now)
    assert missing[0].title == TITLE_MISSING
    assert missing[0].severity == "warn"
    assert missing[0].auto_fixable is False

    _finding_store(tmp_path, None, broken=True)
    unreadable = findings_for_store(tmp_path, now=now)
    assert unreadable[0]["title"] == TITLE_UNREADABLE
    assert check_strategy_book_fair_value(repo_root=tmp_path, now=now)[0].title == TITLE_UNREADABLE

    stale_at = (now - timedelta(days=6)).isoformat()
    _finding_store(tmp_path, stale_at)
    stale = check_strategy_book_fair_value(repo_root=tmp_path, now=now)
    assert stale[0].title == TITLE_STALE
    assert stale[0].severity == "warn"
    assert stale[0].auto_fixable is False

    _finding_store(tmp_path, now.isoformat())
    fresh = check_strategy_book_fair_value(repo_root=tmp_path, now=now)
    assert fresh[0].title == TITLE_INFO
    assert fresh[0].severity == "info"
    assert fresh[0].auto_fixable is False
    assert "2 of 2" in fresh[0].summary
    assert "0.250" in fresh[0].summary
    assert "insufficient_data" in fresh[0].summary
