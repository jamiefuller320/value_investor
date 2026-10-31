"""Stored-file FTSE gap checks, including the handover examples still on disk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from value_investor.ftse_gap_scan import (
    HOW_TO_ADD_A_CHECK,
    RosterName,
    ScreenRow,
    _eps_scale_pairs,
    _income_sign_gaps,
    _net_normalized_gaps,
    _revenue_year_without_eps,
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
    assert bab.dividend_yield_raw == pytest.approx(0.73)
    assert bab.yield_display == "73.0%"
    assert "raw_yield_below_one_displayed_as_percent" in _ids(bab)

    iii = rows["III.L"]
    assert iii.displayed_fcf is not None
    assert iii.operating_cashflow is None
    assert "fcf_stored_operating_cashflow_missing" in _ids(iii)

    barc = rows["BARC.L"]
    assert barc.operating_cashflow == pytest.approx(18_739_000_000.0)
    assert barc.fcf_is_object
    assert barc.displayed_fcf == pytest.approx(16_880_000_000.0)
    assert barc.fcf_has_figure is True
    assert "empty_fcf_object_with_operating_cashflow" not in _ids(barc)
    empty_fcf = _row(fcf_is_object=True, fcf_has_figure=False, operating_cashflow=1.0)
    assert "empty_fcf_object_with_operating_cashflow" in _ids(empty_fcf)

    bhmg = rows["BHMG.L"]
    assert bhmg.pe_display == "418.0"
    assert bhmg.history_price == pytest.approx(419.0)
    assert "screen_pe_equals_pence_price" not in _ids(bhmg)
    matched_price = _row(pe_display="419.0", history_price=419.0)
    assert "screen_pe_equals_pence_price" in _ids(matched_price)


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


def test_unflagged_filing_aligned_can_match_the_other_screen_figures():
    quiet = _row(
        displayed_fcf=27_800_000.0,
        filing_aligned=27_800_000.0,
        company_adjusted=27_800_000.0,
        screen_ttm=27_800_000.0,
        statement_fcf=31_900_000.0,
        fcf_divergence_flagged=True,
    )
    assert "filing_aligned_differs_from_statement_fcf" not in _ids(quiet)
    assert "fcf_figures_disagree" not in _ids(quiet)
    same_line = _row(
        displayed_fcf=31_900_000.0,
        filing_aligned=31_900_000.0,
        screen_ttm=31_900_000.0,
        statement_fcf=31_900_000.0,
        fcf_divergence_flagged=False,
    )
    assert "filing_aligned_differs_from_statement_fcf" not in _ids(same_line)
    untagged = _row(
        displayed_fcf=10.0,
        filing_aligned=12.0,
        statement_fcf=31.0,
        fcf_divergence_flagged=False,
    )
    assert "filing_aligned_differs_from_statement_fcf" not in _ids(untagged)
    missing_flag = _row(
        displayed_fcf=27_800_000.0,
        filing_aligned=27_800_000.0,
        screen_ttm=27_800_000.0,
        statement_fcf=31_900_000.0,
    )
    assert "filing_aligned_differs_from_statement_fcf" not in _ids(missing_flag)
    hit = _row(
        displayed_fcf=27_800_000.0,
        filing_aligned=27_800_000.0,
        company_adjusted=27_800_000.0,
        screen_ttm=27_800_000.0,
        statement_fcf=31_900_000.0,
        fcf_divergence_flagged=False,
    )
    detail = next(
        item.detail
        for item in hits_for(hit)
        if item.rule_id == "filing_aligned_differs_from_statement_fcf"
    )
    assert "filing_aligned 27800000" in detail
    assert "statement free cash flow 31900000" in detail
    assert "fcf_figures_disagree" not in _ids(hit)


def test_bmy_and_cch_filing_aligned_match_the_statement_line():
    """Stored screen now puts filing_aligned on the statement line.

    BMY's screen_ttm still differs from the statement line, so the TTM check fires.
    CCH's flag is true, so neither unflagged disagreement check fires. Constructed
    rows above still cover filing_aligned differing from the statement.
    """
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    bmy = rows["BMY.L"]
    assert bmy.displayed_fcf == pytest.approx(31_900_000.0)
    assert bmy.filing_aligned == pytest.approx(31_900_000.0)
    assert bmy.statement_fcf == pytest.approx(31_900_000.0)
    assert bmy.screen_ttm == pytest.approx(35_000_000.0)
    assert bmy.fcf_divergence_flagged is False
    assert "filing_aligned_differs_from_statement_fcf" not in _ids(bmy)
    assert "screen_ttm_differs_filing_aligned_matches_statement" in _ids(bmy)
    cch = rows["CCH.L"]
    assert cch.displayed_fcf == pytest.approx(760_900_000.0)
    assert cch.filing_aligned == pytest.approx(760_900_000.0)
    assert cch.statement_fcf == pytest.approx(760_900_000.0)
    assert cch.screen_ttm == pytest.approx(1_593_175_040.0)
    assert cch.fcf_divergence_flagged is True
    assert "filing_aligned_differs_from_statement_fcf" not in _ids(cch)
    assert "screen_ttm_differs_filing_aligned_matches_statement" not in _ids(cch)


def test_byg_and_dln_are_trust_rows_with_revenue_and_no_price():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    byg = rows["BYG.L"]
    assert byg.trust is True
    assert byg.statement_revenue == pytest.approx(209_084_000.0)
    assert byg.discount_display == "29.2%"
    assert byg.fcf_has_figure is False
    assert byg.history_price is None
    assert "trust_revenue_discount_without_fcf_or_price" in _ids(byg)
    dln = rows["DLN.L"]
    assert dln.trust is True
    assert dln.statement_revenue == pytest.approx(388_700_000.0)
    assert dln.discount_display == "39.2%"
    assert dln.fcf_has_figure is False
    assert dln.history_price is None
    assert "trust_revenue_discount_without_fcf_or_price" in _ids(dln)


def test_trust_revenue_check_needs_each_stored_gap():
    hit = _row(
        trust=True,
        statement_revenue=209_084_000.0,
        discount_display="39.7%",
        fcf_has_figure=False,
        history_price=None,
        has_annual_statement=True,
    )
    assert "trust_revenue_discount_without_fcf_or_price" in _ids(hit)
    assert "trust_revenue_discount_without_fcf_or_price" not in _ids(
        _row(**{**hit.__dict__, "trust": False})
    )
    assert "trust_revenue_discount_without_fcf_or_price" not in _ids(
        _row(trust=True, discount_display="39.7%", fcf_has_figure=False)
    )
    assert "trust_revenue_discount_without_fcf_or_price" not in _ids(
        _row(trust=True, statement_revenue=1.0, fcf_has_figure=False)
    )
    assert "trust_revenue_discount_without_fcf_or_price" not in _ids(
        _row(
            trust=True,
            statement_revenue=1.0,
            discount_display="39.7%",
            fcf_has_figure=True,
            displayed_fcf=1.0,
        )
    )
    assert "trust_revenue_discount_without_fcf_or_price" not in _ids(
        _row(
            trust=True,
            statement_revenue=1.0,
            discount_display="39.7%",
            history_price=100.0,
        )
    )
    premium = _row(
        trust=True,
        statement_revenue=1_405_000_000.0,
        premium_display="213.7%",
        pe_display="16.2",
        yield_display="3.7%",
        key_metric_names=frozenset({"Premium", "P/B", "Yield", "P/E"}),
        fcf_has_figure=False,
        history_price=None,
    )
    assert "trust_revenue_discount_without_fcf_or_price" in _ids(premium)


def test_emg_premium_counts_on_the_trust_revenue_check():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    emg = rows["EMG.L"]
    latest = json.loads((ROOT / "docs/data/latest.json").read_text())
    stored = next(raw for raw in latest["trust_reports"] if raw.get("ticker") == "EMG.L")
    assert stored["key_metrics"]["P/B"] == "3.12"
    assert emg.trust is True
    assert emg.premium_display == "212.1%"
    assert emg.discount_display is None
    assert emg.pe_display == "15.9"
    assert emg.yield_display == "3.8%"
    assert "P/B" in emg.key_metric_names
    assert emg.fcf_has_figure is False
    assert emg.history_price is None
    assert emg.statement_revenue is not None
    detail = next(
        hit.detail
        for hit in hits_for(emg)
        if hit.rule_id == "trust_revenue_discount_without_fcf_or_price"
    )
    assert "premium 212.1%" in detail


def _income_pair(ticker: str, year: str) -> tuple[float, float]:
    path = ROOT / "docs/data/research" / ticker / "sources" / "financials_annual.json"
    row = json.loads(path.read_text())["income_statement"][year]
    return float(row["Net Income"]), float(row["Normalized Income"])


def test_ten_times_compares_stored_income_without_rescaling():
    assert _net_normalized_gaps({"2026": {"Net Income": 110, "Normalized Income": 10}}) == (
        ("2026", 110.0, 10.0),
    )
    assert _net_normalized_gaps({"2026": {"Net Income": 100, "Normalized Income": 10}}) == ()
    assert _net_normalized_gaps({"2026": {"Net Income": 0, "Normalized Income": 10}}) == ()
    assert _net_normalized_gaps({"2026": {"Net Income": -110, "Normalized Income": 10}}) == (
        ("2026", -110.0, 10.0),
    )
    assert _net_normalized_gaps({"2026": {"Normalized Income": 10}}) == ()
    assert "net_income_ten_times_normalized" in _ids(
        _row(net_normalized_gaps=(("2026", 55_454_000.0, 4_768_754.870575),))
    )
    assert "net_income_ten_times_normalized" not in _ids(_row())


def test_fras_gdwn_and_has_2026_income_pairs():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    fras_net, fras_norm = _income_pair("FRAS.L", "2026")
    assert fras_net == pytest.approx(375_000_000)
    assert fras_norm == pytest.approx(192_273_600)
    assert "net_income_ten_times_normalized" not in _ids(rows["FRAS.L"])

    gdwn_net, gdwn_norm = _income_pair("GDWN.L", "2026")
    assert gdwn_net == pytest.approx(55_454_000)
    assert gdwn_norm == pytest.approx(4_768_754.87)
    gdwn_gaps = rows["GDWN.L"].net_normalized_gaps
    assert len(gdwn_gaps) == 1
    assert gdwn_gaps[0][0] == "2026"
    assert gdwn_gaps[0][1] == pytest.approx(gdwn_net)
    assert gdwn_gaps[0][2] == pytest.approx(gdwn_norm)
    detail = next(
        hit.detail
        for hit in hits_for(rows["GDWN.L"])
        if hit.rule_id == "net_income_ten_times_normalized"
    )
    assert "2026 net income 55454000 beside normalized income 4768754.870575" in detail

    has_net, has_norm = _income_pair("HAS.L", "2026")
    assert has_net == pytest.approx(-58_200_000)
    assert has_norm == pytest.approx(-21_150_000)
    assert "net_income_ten_times_normalized" not in _ids(rows["HAS.L"])


def test_hbr_and_elm_positive_pe_beside_negative_diluted_eps():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    hbr = rows["HBR.L"]
    assert hbr.pe_display == "25.7"
    assert hbr.diluted_eps == pytest.approx(-0.16)
    assert "positive_screen_pe_beside_negative_diluted_eps" in _ids(hbr)
    elm = rows["ELM.L"]
    assert elm.pe_display == "20.8"
    assert elm.diluted_eps == pytest.approx(-0.078)
    assert "positive_screen_pe_beside_negative_diluted_eps" in _ids(elm)
    assert "positive_screen_pe_beside_negative_diluted_eps" not in _ids(
        _row(pe_display="23.4", diluted_eps=0.16)
    )
    assert "positive_screen_pe_beside_negative_diluted_eps" not in _ids(
        _row(pe_display="-23.4", diluted_eps=-0.16)
    )
    assert "positive_screen_pe_beside_negative_diluted_eps" not in _ids(
        _row(pe_display="0", diluted_eps=-0.16)
    )
    assert "positive_screen_pe_beside_negative_diluted_eps" not in _ids(_row(pe_display="23.4"))


def test_jemi_and_fcss_have_a_pe_and_neither_discount_nor_premium():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    for ticker, pe in (("JEMI.L", "3.2"), ("FCSS.L", "7.7")):
        row = rows[ticker]
        assert row.trust is True
        assert row.pe_display == pe
        assert "P/E" in row.key_metric_names
        assert "Discount" not in row.key_metric_names
        assert "Premium" not in row.key_metric_names
        assert row.discount_display is None
        assert row.premium_display is None
        assert "trust_pe_without_discount_or_premium" in _ids(row)
        assert "trust_revenue_discount_without_fcf_or_price" not in _ids(row)
    wider = _row(
        trust=True,
        pe_display="12.0",
        key_metric_names=frozenset({"P/E", "Yield"}),
    )
    assert "trust_pe_without_discount_or_premium" in _ids(wider)
    assert "trust_row_pe_only" not in _ids(wider)
    assert "trust_pe_without_discount_or_premium" not in _ids(
        _row(trust=True, pe_display="39.7%", key_metric_names=frozenset({"P/E", "Discount"}))
    )
    assert "trust_pe_without_discount_or_premium" not in _ids(
        _row(trust=True, pe_display="16.2", key_metric_names=frozenset({"P/E", "Premium"}))
    )
    assert "trust_pe_without_discount_or_premium" not in _ids(
        _row(trust=True, key_metric_names=frozenset({"Yield"}))
    )
    assert "trust_pe_without_discount_or_premium" not in _ids(
        _row(trust=False, pe_display="5.0", key_metric_names=frozenset({"P/E"}))
    )


def test_screen_pe_beside_a_revenue_year_with_no_eps_line():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    expected = {
        "LRE.L": ("7.2", "2025", 1_883_400_000.0, 293_400_000.0),
        "LWDB.L": ("5.2", "2025", 366_003_000.0, 304_670_000.0),
        "INPP.L": ("10.7", "2025", 267_760_000.0, 263_704_000.0),
        "JEDT.L": ("5.3", "2026", 114_629_000.0, 112_129_000.0),
    }
    for ticker, (pe, year, revenue, net) in expected.items():
        row = rows[ticker]
        assert row.pe_display == pe
        assert "P/E" in row.key_metric_names
        assert row.diluted_eps is None
        assert row.revenue_year_without_eps is not None
        stored_year, stored_revenue, stored_net = row.revenue_year_without_eps
        assert stored_year == year
        assert stored_revenue == pytest.approx(revenue)
        assert stored_net == pytest.approx(net)
        assert "screen_pe_without_diluted_eps_line" in _ids(row)
        detail = next(
            hit.detail
            for hit in hits_for(row)
            if hit.rule_id == "screen_pe_without_diluted_eps_line"
        )
        assert f"screen P/E {pe}" in detail
        assert "no diluted EPS line" in detail
    assert _revenue_year_without_eps(
        {
            "2025": {"Total Revenue": 10, "Net Income": 2},
            "2024": {"Total Revenue": 9, "Net Income": 1, "Diluted EPS": 0.1},
        }
    ) == ("2025", 10.0, 2.0)
    assert (
        _revenue_year_without_eps(
            {"2025": {"Total Revenue": 10, "Net Income": 2, "Diluted EPS": 0.1}}
        )
        is None
    )
    assert "screen_pe_without_diluted_eps_line" not in _ids(
        _row(revenue_year_without_eps=("2025", 10.0, 2.0), key_metric_names=frozenset())
    )
    assert "screen_pe_without_diluted_eps_line" in _ids(
        _row(
            pe_display="6.7",
            key_metric_names=frozenset({"P/E"}),
            revenue_year_without_eps=("2025", 10.0, 2.0),
        )
    )


def _eps_and_income(ticker: str) -> dict[str, tuple[float, float]]:
    path = ROOT / "docs/data/research" / ticker / "sources" / "financials_annual.json"
    income = json.loads(path.read_text())["income_statement"]
    stored: dict[str, tuple[float, float]] = {}
    for year, row in income.items():
        if not isinstance(row, dict):
            continue
        if "Diluted EPS" not in row or "Net Income" not in row:
            continue
        stored[str(year)] = (float(row["Diluted EPS"]), float(row["Net Income"]))
    return stored


def test_oci_and_oxb_eps_years_differ_while_net_income_stays_close():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    oci = _eps_and_income("OCI.L")
    assert oci["2023"][0] == pytest.approx(0.0027)
    assert oci["2023"][1] == pytest.approx(47_488_000)
    assert oci["2022"][0] == pytest.approx(1.26)
    assert oci["2024"][0] == pytest.approx(0.15)
    assert oci["2025"][0] == pytest.approx(0.34)
    assert "diluted_eps_ten_times_while_net_income_within_ten" in _ids(rows["OCI.L"])
    oci_detail = next(
        hit.detail
        for hit in hits_for(rows["OCI.L"])
        if hit.rule_id == "diluted_eps_ten_times_while_net_income_within_ten"
    )
    assert "2023 diluted EPS 0.0027" in oci_detail
    assert "2022 diluted EPS 1.26" in oci_detail
    assert "2024 diluted EPS 0.15" in oci_detail
    assert "2025 diluted EPS 0.34" in oci_detail

    oxb = _eps_and_income("OXB.L")
    assert oxb["2024"][0] == pytest.approx(-41.75)
    assert oxb["2024"][1] == pytest.approx(-43_190_000)
    assert oxb["2022"][0] == pytest.approx(-0.4129)
    assert oxb["2023"][0] == pytest.approx(-1.6311)
    assert oxb["2025"][0] == pytest.approx(-0.2692)
    assert "diluted_eps_ten_times_while_net_income_within_ten" in _ids(rows["OXB.L"])
    oxb_detail = next(
        hit.detail
        for hit in hits_for(rows["OXB.L"])
        if hit.rule_id == "diluted_eps_ten_times_while_net_income_within_ten"
    )
    assert "2024 diluted EPS -41.75" in oxb_detail

    within = {
        "2023": {"Diluted EPS": 0.0027, "Net Income": 47_488_000},
        "2022": {"Diluted EPS": 1.26, "Net Income": 222_960_000},
    }
    assert len(_eps_scale_pairs(within)) == 1
    assert (
        _eps_scale_pairs(
            {
                "2024": {"Diluted EPS": 10, "Net Income": 1},
                "2025": {"Diluted EPS": 1, "Net Income": 1},
            }
        )
        == ()
    )
    assert (
        _eps_scale_pairs(
            {
                "2024": {"Diluted EPS": 12, "Net Income": 100},
                "2025": {"Diluted EPS": 1, "Net Income": 1},
            }
        )
        == ()
    )
    assert (
        _eps_scale_pairs(
            {
                "2024": {"Diluted EPS": 0, "Net Income": 10},
                "2025": {"Diluted EPS": 1, "Net Income": 10},
            }
        )
        == ()
    )


def test_chart_gbp_matches_a_quote_currency_other_than_pounds():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    ihg = rows["IHG.L"]
    ihg_chart = json.loads((ROOT / "docs/data/charts/IHG.L.json").read_text())
    ihg_quote = json.loads((ROOT / "docs/data/research/IHG.L/sources/price_quote.json").read_text())
    assert ihg_chart["currency"] == "GBP"
    assert ihg_quote["quote_currency"] == "USD"
    assert ihg.chart_currency == "GBP"
    assert ihg.price_quote_currency == "USD"
    assert ihg.history_price == pytest.approx(159.05)
    assert "chart_gbp_quote_not_pound" in _ids(ihg)

    mtln = rows["MTLN.L"]
    mtln_quote = json.loads(
        (ROOT / "docs/data/research/MTLN.L/sources/price_quote.json").read_text()
    )
    assert mtln.chart_currency == "GBP"
    assert mtln_quote["quote_currency"] == "EUR"
    assert mtln.price_quote_currency == "EUR"
    assert mtln.history_price == pytest.approx(48.76)
    assert "chart_gbp_quote_not_pound" in _ids(mtln)

    assert "chart_gbp_quote_not_pound" not in _ids(
        _row(chart_currency="GBP", price_quote_currency="GBp", history_price=159.05)
    )
    assert "chart_gbp_quote_not_pound" not in _ids(
        _row(chart_currency="GBP", price_quote_currency="GBP", history_price=48.76)
    )
    assert "chart_gbp_quote_not_pound" not in _ids(
        _row(chart_currency="USD", price_quote_currency="EUR", history_price=48.76)
    )
    assert "chart_gbp_quote_not_pound" in _ids(
        _row(chart_currency="GBP", price_quote_currency="EUR", history_price=48.76)
    )


def test_chart_gbp_with_price_and_no_quote_file():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    expected = {
        "GSK.L": 1750.0,
        "REL.L": 2720.0,
        "HLN.L": 349.20001220703125,
        "FRES.L": 2756.0,
        "SGE.L": 1071.5,
        "SN.L": 1020.5,
        "RTO.L": 303.0,
        "CCC.L": 5550.0,
        "ABDN.L": 243.0,
        "BBY.L": 876.0,
    }
    for ticker, price in expected.items():
        row = rows[ticker]
        quote_path = ROOT / "docs/data/research" / ticker / "sources" / "price_quote.json"
        chart = json.loads((ROOT / "docs/data/charts" / f"{ticker}.json").read_text())
        assert chart["currency"] == "GBP"
        assert not quote_path.exists()
        assert row.chart_currency == "GBP"
        assert row.has_price_quote_file is False
        assert row.price_quote_currency is None
        assert row.history_price == pytest.approx(price)
        assert "chart_gbp_price_without_quote_file" in _ids(row)
        assert "chart_gbp_quote_not_pound" not in _ids(row)

    assert "chart_gbp_price_without_quote_file" not in _ids(
        _row(chart_currency="GBP", history_price=1750.0, has_price_quote_file=True)
    )
    assert "chart_gbp_price_without_quote_file" not in _ids(
        _row(chart_currency="USD", history_price=1750.0, has_price_quote_file=False)
    )
    assert "chart_gbp_price_without_quote_file" not in _ids(
        _row(chart_currency="GBP", history_price=None, has_price_quote_file=False)
    )
    bare = _row(chart_currency="GBP", history_price=1750.0, has_price_quote_file=False)
    detail = next(
        hit.detail for hit in hits_for(bare) if hit.rule_id == "chart_gbp_price_without_quote_file"
    )
    assert "no price_quote.json" in detail
    assert "quote currency" not in detail


def test_screen_ttm_differs_while_filing_aligned_matches_the_statement():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    fres = rows["FRES.L"]
    assert fres.screen_ttm == pytest.approx(1_999_836_928)
    assert fres.filing_aligned == pytest.approx(1_889_566_000)
    assert fres.statement_fcf == pytest.approx(1_889_566_000)
    assert fres.fcf_divergence_flagged is False
    assert "screen_ttm_differs_filing_aligned_matches_statement" in _ids(fres)
    assert "filing_aligned_differs_from_statement_fcf" not in _ids(fres)
    fres_detail = next(
        hit.detail
        for hit in hits_for(fres)
        if hit.rule_id == "screen_ttm_differs_filing_aligned_matches_statement"
    )
    assert "screen_ttm 1999836928" in fres_detail
    assert "filing_aligned 1889566000" in fres_detail

    ccc = rows["CCC.L"]
    assert ccc.screen_ttm == pytest.approx(287_937_504)
    assert ccc.filing_aligned == pytest.approx(257_600_000)
    assert ccc.statement_fcf == pytest.approx(257_600_000)
    assert ccc.fcf_divergence_flagged is False
    assert "screen_ttm_differs_filing_aligned_matches_statement" in _ids(ccc)
    assert "filing_aligned_differs_from_statement_fcf" not in _ids(ccc)

    # GSK now matches filing-aligned (screen TTM still differs) — same class as FRES.
    gsk = rows["GSK.L"]
    assert gsk.screen_ttm == pytest.approx(5_328_500_224.0)
    assert gsk.filing_aligned == pytest.approx(4_756_000_000.0)
    assert gsk.statement_fcf == pytest.approx(4_756_000_000.0)
    assert gsk.fcf_divergence_flagged is False
    assert "screen_ttm_differs_filing_aligned_matches_statement" in _ids(gsk)
    # Counter-example: still-flagged divergence must not take the screen-ttm rule.
    flagged = rows["MEGP.L"]
    assert flagged.fcf_divergence_flagged is True
    assert "screen_ttm_differs_filing_aligned_matches_statement" not in _ids(flagged)

    rel = rows["REL.L"]
    assert rel.screen_ttm == pytest.approx(2_232_375_040.0)
    assert rel.filing_aligned == pytest.approx(2_311_000_000.0)
    assert rel.statement_fcf == pytest.approx(2_311_000_000.0)
    assert rel.fcf_divergence_flagged is False
    assert "screen_ttm_differs_filing_aligned_matches_statement" in _ids(rel)
    barc = rows["BARC.L"]
    assert barc.screen_ttm == pytest.approx(16_880_000_000.0)
    assert barc.filing_aligned == barc.screen_ttm
    assert barc.statement_fcf == barc.screen_ttm
    assert "screen_ttm_differs_filing_aligned_matches_statement" not in _ids(barc)

    same_screen = _row(
        displayed_fcf=1_889_566_000.0,
        filing_aligned=1_889_566_000.0,
        screen_ttm=1_999_836_928.0,
        statement_fcf=1_889_566_000.0,
        fcf_divergence_flagged=False,
    )
    assert "screen_ttm_differs_filing_aligned_matches_statement" in _ids(same_screen)
    assert "filing_aligned_differs_from_statement_fcf" not in _ids(same_screen)
    still_old = _row(
        displayed_fcf=27_800_000.0,
        filing_aligned=27_800_000.0,
        screen_ttm=27_800_000.0,
        statement_fcf=31_900_000.0,
        fcf_divergence_flagged=False,
    )
    assert "filing_aligned_differs_from_statement_fcf" in _ids(still_old)
    assert "screen_ttm_differs_filing_aligned_matches_statement" not in _ids(still_old)
    assert "screen_ttm_differs_filing_aligned_matches_statement" not in _ids(
        _row(
            screen_ttm=1_999_836_928.0,
            filing_aligned=1_889_566_000.0,
            statement_fcf=1_889_566_000.0,
            fcf_divergence_flagged=True,
        )
    )
    assert "screen_ttm_differs_filing_aligned_matches_statement" not in _ids(
        _row(
            screen_ttm=1_889_566_000.0,
            filing_aligned=1_889_566_000.0,
            statement_fcf=1_889_566_000.0,
            fcf_divergence_flagged=False,
        )
    )
    assert "screen_ttm_differs_filing_aligned_matches_statement" not in _ids(
        _row(
            screen_ttm=1_999_836_928.0,
            filing_aligned=1_889_566_000.0,
            statement_fcf=31_900_000.0,
            fcf_divergence_flagged=False,
        )
    )


def test_grg_cashflow_metrics_annual_fcf_without_ttm():
    """GRG remains the committed annual-without-TTM fixture; ATYM now has TTM."""
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    atym = rows["ATYM.L"]
    assert atym.cashflow_annual_fcf == pytest.approx(110_835_000)
    assert atym.cashflow_fcf_ttm == pytest.approx(137_175_000)
    assert "cashflow_metrics_annual_fcf_without_ttm" not in _ids(atym)
    grg = rows["GRG.L"]
    assert grg.cashflow_annual_fcf == pytest.approx(51_600_000)
    assert grg.cashflow_fcf_ttm is None
    assert "cashflow_metrics_annual_fcf_without_ttm" in _ids(grg)
    hik = rows["HIK.L"]
    assert hik.cashflow_fcf_ttm == pytest.approx(191_000_000)
    assert "cashflow_metrics_annual_fcf_without_ttm" not in _ids(hik)
    assert "cashflow_metrics_annual_fcf_without_ttm" in _ids(
        _row(cashflow_annual_fcf=110_835_000.0, cashflow_fcf_ttm=None)
    )
    assert "cashflow_metrics_annual_fcf_without_ttm" not in _ids(
        _row(cashflow_annual_fcf=110_835_000.0, cashflow_fcf_ttm=191_000_000.0)
    )
    assert "cashflow_metrics_annual_fcf_without_ttm" not in _ids(
        _row(cashflow_annual_fcf=None, cashflow_fcf_ttm=None)
    )


def test_non_gbp_fcf_currency_with_gbp_chart_and_no_quote_file():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    expected = {"ATYM.L": "EUR", "TRST.L": "USD", "HIK.L": "USD"}
    for ticker, currency in expected.items():
        row = rows[ticker]
        quote_path = ROOT / "docs/data/research" / ticker / "sources" / "price_quote.json"
        chart = json.loads((ROOT / "docs/data/charts" / f"{ticker}.json").read_text())
        assert chart["currency"] == "GBP"
        assert not quote_path.exists()
        assert row.chart_currency == "GBP"
        assert row.has_price_quote_file is False
        assert row.price_quote_currency is None
        assert row.fcf_currency == currency
        assert "fcf_currency_not_gbp_chart_without_quote_file" in _ids(row)
        detail = next(
            hit.detail
            for hit in hits_for(row)
            if hit.rule_id == "fcf_currency_not_gbp_chart_without_quote_file"
        )
        assert f"screen free-cash-flow currency {currency}" in detail
        assert "quote currency" not in detail
    assert "fcf_currency_not_gbp_chart_without_quote_file" not in _ids(
        _row(
            fcf_currency="GBP",
            chart_currency="GBP",
            has_price_quote_file=False,
        )
    )
    assert "fcf_currency_not_gbp_chart_without_quote_file" not in _ids(
        _row(fcf_currency=None, chart_currency="GBP", has_price_quote_file=False)
    )
    assert "fcf_currency_not_gbp_chart_without_quote_file" not in _ids(
        _row(fcf_currency="EUR", chart_currency="USD", has_price_quote_file=False)
    )
    assert "fcf_currency_not_gbp_chart_without_quote_file" not in _ids(
        _row(fcf_currency="EUR", chart_currency="GBP", has_price_quote_file=True)
    )


def test_vct_positive_eps_has_no_screen_pe_key():
    """HWG.L left the screen roster; VCT.L is the current positive-EPS / no-P/E example."""
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    vct = rows["VCT.L"]
    assert vct.diluted_eps == pytest.approx(0.318)
    assert "P/E" not in vct.key_metric_names
    assert "positive_diluted_eps_without_screen_pe" in _ids(vct)
    assert "positive_diluted_eps_without_screen_pe" not in _ids(
        _row(diluted_eps=0.318, key_metric_names=frozenset({"P/E"}))
    )
    assert "positive_diluted_eps_without_screen_pe" not in _ids(
        _row(diluted_eps=-0.16, key_metric_names=frozenset())
    )
    assert "positive_diluted_eps_without_screen_pe" not in _ids(
        _row(diluted_eps=0.0, key_metric_names=frozenset())
    )


def test_htg_and_ihp_income_signs_differ_without_changing_ten_times():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    htg_net, htg_norm = _income_pair("HTG.L", "2024")
    assert htg_net == pytest.approx(-28_000_000)
    assert htg_norm == pytest.approx(163_537_313.43)
    htg_signs = {year: (net, norm) for year, net, norm in rows["HTG.L"].income_sign_gaps}
    assert htg_signs["2024"][0] == pytest.approx(htg_net)
    assert htg_signs["2024"][1] == pytest.approx(htg_norm)
    assert "net_income_normalized_opposite_signs" in _ids(rows["HTG.L"])
    assert "2024" not in {year for year, _, _ in rows["HTG.L"].net_normalized_gaps}

    ihp_net, ihp_norm = _income_pair("IHP.L", "2025")
    assert ihp_net == pytest.approx(51_300_000)
    assert ihp_norm == pytest.approx(-1_981_350_000)
    ihp_signs = {year: (net, norm) for year, net, norm in rows["IHP.L"].income_sign_gaps}
    assert ihp_signs["2025"][0] == pytest.approx(ihp_net)
    assert ihp_signs["2025"][1] == pytest.approx(ihp_norm)
    assert "net_income_normalized_opposite_signs" in _ids(rows["IHP.L"])
    assert "2025" in {year for year, _, _ in rows["IHP.L"].net_normalized_gaps}

    assert (
        _income_sign_gaps(
            {"2024": {"Net Income": -28_000_000, "Normalized Income": 163_537_313.43}}
        )[0][0]
        == "2024"
    )
    assert _income_sign_gaps({"2024": {"Net Income": -28_000_000, "Normalized Income": -1.0}}) == ()
    assert _income_sign_gaps({"2024": {"Net Income": 0, "Normalized Income": -1.0}}) == ()
    assert (
        _net_normalized_gaps(
            {"2024": {"Net Income": -28_000_000, "Normalized Income": 163_537_313.43}}
        )
        == ()
    )


def test_stored_fcf_figures_stay_distinct():
    same = _row(filing_aligned=10.0, company_adjusted=10.0, screen_ttm=10.0)
    assert "fcf_figures_disagree" not in _ids(same)
    one = _row(filing_aligned=10.0)
    assert "fcf_figures_disagree" not in _ids(one)
    split = _row(filing_aligned=10.0, company_adjusted=4.0, screen_ttm=10.0)
    detail = next(hit.detail for hit in hits_for(split) if hit.rule_id == "fcf_figures_disagree")
    assert "filing_aligned 10" in detail
    assert "company_adjusted 4" in detail
    assert "screen_ttm 10" in detail


def test_dividend_plus_repurchase_uses_only_stored_lines():
    covered = _row(cash_dividend=-5.0, repurchase=-1.0, filing_aligned=10.0)
    assert "dividend_plus_repurchase_against_filing_fcf" not in _ids(covered)
    missing_line = _row(cash_dividend=-5.0, filing_aligned=1.0)
    assert "dividend_plus_repurchase_against_filing_fcf" not in _ids(missing_line)
    over = _row(cash_dividend=-8.0, repurchase=-4.0, filing_aligned=10.0)
    detail = next(
        hit.detail
        for hit in hits_for(over)
        if hit.rule_id == "dividend_plus_repurchase_against_filing_fcf"
    )
    assert "is 12 against filing free cash flow 10" in detail


def test_unknown_currency_leaves_yield_and_pe_side_by_side():
    row = _row(
        cash_dividend=-10.0,
        yield_display="2.0%",
        history_price=200.0,
        ordinary_shares=100.0,
        price_quote_currency="GBp",
        pe_display="12.0",
        diluted_eps=0.5,
    )
    yield_detail = next(
        hit.detail for hit in hits_for(row) if hit.rule_id == "cash_dividend_over_cap_against_yield"
    )
    pe_detail = next(
        hit.detail
        for hit in hits_for(row)
        if hit.rule_id == "screen_pe_against_price_over_diluted_eps"
    )
    assert "readings left side by side" in yield_detail
    assert "readings left side by side" in pe_detail
    assert "percent" not in yield_detail
    assert "over diluted EPS" not in pe_detail


def test_known_currency_compares_yield_and_pe_without_replacing_either():
    match = _row(
        cash_dividend=-2.0,
        yield_display="2.0%",
        history_price=100.0,
        ordinary_shares=1.0,
        price_quote_currency="GBP",
        statement_currency="GBP",
        pe_display="10.0",
        diluted_eps=10.0,
    )
    assert "cash_dividend_over_cap_against_yield" not in _ids(match)
    assert "screen_pe_against_price_over_diluted_eps" not in _ids(match)
    differ = _row(
        cash_dividend=-4.0,
        yield_display="2.0%",
        history_price=100.0,
        ordinary_shares=1.0,
        price_quote_currency="GBp",
        statement_currency="GBP",
        pe_display="10.0",
        diluted_eps=0.05,
    )
    texts = {hit.rule_id: hit.detail for hit in hits_for(differ)}
    assert "displayed yield 2.0%" in texts["cash_dividend_over_cap_against_yield"]
    assert "screen P/E 10.0" in texts["screen_pe_against_price_over_diluted_eps"]
    assert "over diluted EPS" in texts["screen_pe_against_price_over_diluted_eps"]


def test_screen_roe_and_unusual_items_use_stored_figures():
    agree = _row(screen_roe=0.10, net_income=10.0, stockholders_equity=100.0)
    assert "screen_roe_against_net_income_over_equity" not in _ids(agree)
    disagree = _row(screen_roe=0.337, net_income=10.0, stockholders_equity=100.0)
    detail = next(
        hit.detail
        for hit in hits_for(disagree)
        if hit.rule_id == "screen_roe_against_net_income_over_equity"
    )
    assert "screen ROE" in detail
    assert "net income 10" in detail
    same_items = _row(unusual_items=(("Total Unusual Items", 1.0), ("Special Income Charges", 1.0)))
    assert "unusual_items_disagree" not in _ids(same_items)
    items = _row(
        unusual_items=(
            ("Total Unusual Items", 2108000.0),
            ("Special Income Charges", 1787000.0),
        )
    )
    item_detail = next(
        hit.detail for hit in hits_for(items) if hit.rule_id == "unusual_items_disagree"
    )
    assert "2108000" in item_detail
    assert "1787000" in item_detail


def test_megp_unusual_items_and_fgp_fcf_figures_when_files_contain_them():
    rows = {row.ticker: row for row in load_screen_rows(ROOT)}
    megp = rows["MEGP.L"]
    assert any(value == 2108000.0 for _name, value in megp.unusual_items)
    assert "unusual_items_disagree" in _ids(megp)
    fgp = rows["FGP.L"]
    assert fgp.filing_aligned == pytest.approx(362600000.0)
    assert fgp.company_adjusted == pytest.approx(73800000.0)
    assert fgp.screen_ttm == pytest.approx(302812512.0)
    assert "fcf_figures_disagree" in _ids(fgp)


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
