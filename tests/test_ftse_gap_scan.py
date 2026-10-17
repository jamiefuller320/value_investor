"""Stored-file FTSE gap checks, including the handover examples still on disk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from value_investor.ftse_gap_scan import (
    HOW_TO_ADD_A_CHECK,
    RosterName,
    ScreenRow,
    _statement_shares,
    hits_for,
    load_screen_rows,
    render_roster_split,
    scan_ftse_gaps,
)
from value_investor.ftse_gap_scan_cli import build_parser
from value_investor.ftse_statement_fetch import (
    EMPTY_RECORD_NAME,
    STATEMENT_NAME,
    fetch_one_annual_statement,
    persist_missing_annual_statements,
    write_fetched_statement,
)

ROOT = Path(__file__).resolve().parents[1]


def _row(**overrides: object) -> ScreenRow:
    base = dict(
        ticker="TEST.L",
        name="Test",
        trust=False,
        dividend_yield_raw=None,
        yield_display=None,
        pe_display=None,
        key_metric_names=frozenset(),
        displayed_fcf=None,
        operating_cashflow=None,
        filing_aligned=None,
        fcf_is_object=False,
        fcf_has_figure=False,
        has_annual_statement=True,
        history_price=None,
        ordinary_shares=None,
    )
    base.update(overrides)
    return ScreenRow(**base)  # type: ignore[arg-type]


def _ids(row: ScreenRow) -> set[str]:
    return {hit.rule_id for hit in hits_for(row)}


def test_help_explains_how_a_question_becomes_one_check(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    assert "becomes one check" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["scan", "--help"])
    assert exc.value.code == 0
    scan_help = capsys.readouterr().out
    assert "Register that function in CHECKS" in scan_help
    assert HOW_TO_ADD_A_CHECK.splitlines()[0] in scan_help


def test_known_examples_when_files_contain_them():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}

    bab = rows["BAB.L"]
    assert bab.dividend_yield_raw == pytest.approx(0.82)
    assert bab.yield_display == "82.0%"
    assert "raw_yield_below_one_displayed_as_percent" in _ids(bab)

    blnd = rows["BLND.L"]
    assert blnd.displayed_fcf is not None
    assert blnd.operating_cashflow is None
    assert "fcf_stored_operating_cashflow_missing" in _ids(blnd)

    barc = rows["BARC.L"]
    assert barc.operating_cashflow is not None
    assert barc.fcf_is_object
    assert barc.fcf_has_figure is False
    assert "empty_fcf_object_with_operating_cashflow" in _ids(barc)

    bhmg = rows["BHMG.L"]
    assert bhmg.pe_display == "419.0"
    assert bhmg.history_price == pytest.approx(419.0)
    assert "screen_pe_equals_pence_price" in _ids(bhmg)


def test_ba_and_zig_share_counts_come_from_the_statement():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    ba = rows["BA.L"]
    assert ba.history_price == pytest.approx(1860.0)
    assert ba.has_annual_statement
    assert ba.ordinary_shares == pytest.approx(2927288632.0)
    assert "price_without_ordinary_share_count" not in _ids(ba)
    zig = rows["ZIG.L"]
    assert zig.history_price == pytest.approx(439.5)
    assert zig.has_annual_statement
    assert zig.ordinary_shares == pytest.approx(224362270.0)
    assert "price_without_ordinary_share_count" not in _ids(zig)
    missing = _row(history_price=1860.0, ordinary_shares=None, has_annual_statement=False)
    assert "price_without_ordinary_share_count" in _ids(missing)


def test_blank_or_null_share_field_is_not_a_count(tmp_path):
    path = tmp_path / "financials_annual.json"
    path.write_text(
        json.dumps(
            {
                "balance_sheet": {
                    "2025": {
                        "Ordinary Shares Number": None,
                        "Share Issued": "",
                        "Basic Average Shares": "  ",
                    },
                    "2024": {"Ordinary Shares Number": "null"},
                }
            }
        ),
        encoding="utf-8",
    )
    assert _statement_shares(path) is None


def test_rules_do_not_flag_a_clean_row():
    clean = _row(
        dividend_yield_raw=3.05,
        yield_display="3.0%",
        pe_display="11.2",
        key_metric_names=frozenset({"P/E", "Yield", "FCF"}),
        displayed_fcf=100.0,
        operating_cashflow=200.0,
        filing_aligned=100.0,
        fcf_is_object=True,
        fcf_has_figure=True,
        has_annual_statement=True,
        history_price=3793.5,
        ordinary_shares=1_000.0,
    )
    assert _ids(clean) == set()


def test_zero_and_raw_one_are_not_the_below_one_yield_rule():
    zero = _row(dividend_yield_raw=0.0, yield_display="0.0%")
    raw_one = _row(dividend_yield_raw=1.0, yield_display="100.0%")
    assert "raw_yield_below_one_displayed_as_percent" not in _ids(zero)
    assert "raw_yield_below_one_displayed_as_percent" not in _ids(raw_one)


def test_fcf_comparisons_stay_on_their_own_side():
    greater = _row(displayed_fcf=-1.0, operating_cashflow=-5.0, fcf_has_figure=True)
    more_negative = _row(displayed_fcf=-80.0, operating_cashflow=-6.0, fcf_has_figure=True)
    assert _ids(greater) == {"fcf_greater_than_operating_cashflow"}
    assert _ids(more_negative) == {"fcf_more_negative_than_operating_cashflow"}


def test_trust_rules_match_only_their_shape():
    pe_only = _row(trust=True, key_metric_names=frozenset({"P/E"}), pe_display="8.5")
    missing_yield = _row(
        trust=True,
        key_metric_names=frozenset({"Discount", "P/B", "P/E"}),
        pe_display="2.2",
    )
    full = _row(
        trust=True,
        key_metric_names=frozenset({"Discount", "P/B", "P/E", "Yield"}),
        yield_display="4.6%",
    )
    assert _ids(pe_only) >= {"trust_row_pe_only", "trust_row_missing_yield_key"}
    assert "trust_row_pe_only" not in _ids(missing_yield)
    assert "trust_row_missing_yield_key" in _ids(missing_yield)
    assert _ids(full).isdisjoint({"trust_row_pe_only", "trust_row_missing_yield_key"})


def test_roster_split_from_rank_131():
    roster = [
        RosterName(130, "BLND.L", "British Land"),
        RosterName(131, "BMY.L", "Bloomsbury"),
        RosterName(132, "BNKR.L", "Bankers"),
    ]
    hits = scan_ftse_gaps(ROOT)
    text = render_roster_split(
        hits=hits,
        roster=roster,
        from_rank=131,
        screen_tickers={row.ticker for row in load_screen_rows(ROOT)},
    )
    covered = text.split("## Covered by a known rule", 1)[1].split("## Still need an agent", 1)[0]
    needs = text.split("## Still need an agent", 1)[1]
    assert "| 130 | BLND.L |" not in covered
    assert "| 130 | BLND.L |" not in needs
    assert "| 131 | BMY.L |" in covered or "| 131 | BMY.L |" in needs
    assert "| 132 | BNKR.L |" in covered or "| 132 | BNKR.L |" in needs
    covered_n = covered.count("\n| 13")
    needs_n = needs.count("\n| 13")
    assert covered_n + needs_n == 2


def test_fetch_one_statement_is_a_dry_run_until_a_directory_is_given(tmp_path):
    calls: list[str] = []

    def fake(ticker: str, **_kwargs: object) -> dict:
        calls.append(ticker)
        return {
            "ticker": ticker,
            "income_statement": {"2025": {}},
            "balance_sheet": {"2025": {}},
            "cash_flow": {"2025": {}},
        }

    dry = fetch_one_annual_statement("BMY.L", fetcher=fake)
    assert calls == ["BMY.L"]
    assert dry.dry_run is True
    assert dry.written is None
    assert list(tmp_path.iterdir()) == []

    written = fetch_one_annual_statement("BMY.L", sources_dir=tmp_path, fetcher=fake)
    assert written.written == tmp_path / "financials_annual.json"
    payload = json.loads(written.written.read_text(encoding="utf-8"))
    assert payload["ticker"] == "BMY.L"
    assert payload["income_statement"] == {"2025": {}}
    assert calls == ["BMY.L", "BMY.L"]


def test_default_fetcher_is_fetch_annual_financials(monkeypatch):
    from value_investor.research import ingest

    calls: list[str] = []

    def fake(ticker: str, **_kwargs: object) -> dict:
        calls.append(ticker)
        return {"ticker": ticker, "income_statement": {}, "balance_sheet": {}, "cash_flow": {}}

    monkeypatch.setattr(ingest, "fetch_annual_financials", fake)
    result = fetch_one_annual_statement("BAB.L")
    assert calls == ["BAB.L"]
    assert result.dry_run is True
    assert result.written is None


def test_fetch_refuses_to_walk_the_list():
    with pytest.raises(ValueError, match="does not walk"):
        fetch_one_annual_statement("  ")


def test_bmy_written_file_matches_the_dry_run(tmp_path):
    calls: list[str] = []
    payload = {
        "ticker": "BMY.L",
        "fetched_at": "2026-10-17T00:00:00+00:00",
        "income_statement": {"2025": {"Net Income": 10.0}},
        "balance_sheet": {"2025": {"Ordinary Shares Number": 80.0}},
        "cash_flow": {"2025": {"Free Cash Flow": 4.0}},
    }

    def fake(ticker: str, **_kwargs: object) -> dict:
        calls.append(ticker)
        return json.loads(json.dumps(payload))

    dry = fetch_one_annual_statement("BMY.L", fetcher=fake)
    written = write_fetched_statement(dry, tmp_path)
    assert calls == ["BMY.L"]
    assert dry.dry_run is True
    assert json.loads(written.read_text(encoding="utf-8")) == dry.payload


def test_missing_statements_start_with_bloomsbury_and_skip_empties(tmp_path):
    calls: list[str] = []
    pauses: list[float] = []

    def fake(ticker: str, **_kwargs: object) -> dict:
        calls.append(ticker)
        if ticker == "NONE.L":
            return {
                "ticker": ticker,
                "fetched_at": "2026-10-17T00:00:00+00:00",
                "income_statement": {},
                "balance_sheet": {},
                "cash_flow": {},
            }
        return {
            "ticker": ticker,
            "income_statement": {"2025": {"Net Income": 1.0}},
            "balance_sheet": {"2025": {}},
            "cash_flow": {"2025": {}},
        }

    first = persist_missing_annual_statements(
        ["ZZ.L", "NONE.L", "BMY.L"],
        root=tmp_path,
        fetcher=fake,
        sleeper=pauses.append,
        pause_seconds=2.0,
        attempts=1,
    )
    assert [item.ticker for item in first] == ["BMY.L", "ZZ.L", "NONE.L"]
    assert [item.outcome for item in first] == ["written", "written", "empty"]
    assert calls == ["BMY.L", "ZZ.L", "NONE.L"]
    assert pauses == [2.0, 2.0]
    bmy_path = tmp_path / "docs/data/research/BMY.L/sources" / STATEMENT_NAME
    assert json.loads(bmy_path.read_text(encoding="utf-8"))["ticker"] == "BMY.L"
    empty_path = tmp_path / "docs/data/research/NONE.L/sources" / EMPTY_RECORD_NAME
    assert json.loads(empty_path.read_text(encoding="utf-8"))["reason"] == "empty"
    assert not (tmp_path / "docs/data/research/NONE.L/sources" / STATEMENT_NAME).exists()

    present = tmp_path / "docs/data/research/KEEP.L/sources"
    present.mkdir(parents=True)
    (present / STATEMENT_NAME).write_text("{}", encoding="utf-8")
    second = persist_missing_annual_statements(
        ["KEEP.L", "NONE.L", "BMY.L"],
        root=tmp_path,
        fetcher=fake,
        sleeper=pauses.append,
        pause_seconds=2.0,
        attempts=1,
    )
    assert [item.ticker for item in second] == ["BMY.L", "KEEP.L", "NONE.L"]
    assert [item.outcome for item in second] == [
        "skipped_present",
        "skipped_present",
        "skipped_empty",
    ]
    assert calls == ["BMY.L", "ZZ.L", "NONE.L"]
    assert pauses == [2.0, 2.0]
