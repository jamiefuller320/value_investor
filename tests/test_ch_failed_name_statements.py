"""Companies House failed-name statement extraction. Fixture text only; no network."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.ch_failed_name_statements import (
    CHECK_A_BAR,
    StatementPage,
    _Char,
    _insert_decimal_from_boxes,
    _token_text,
    combined_check_a,
    ops_findings_from_ch_failed_name_statements,
    parse_statement_pages,
    repair_glued_thousands,
    repair_spaced_decimals,
    statements_from_2013,
    years_with_eps,
)
from value_investor.eodhd_coverage_check import KNOWN_FAILURE_CASES

INCOME = """
Consolidated income statement
For the year ended 31 December 2013
2013 2012
£m £m
Total revenue 4,080.9 4,402.8
Group revenue 2 3,332.6 3,666.2
Group operating profit 3 124.4 159.6
Profit for the year 106.3 154.9
Profit attributable to
Equity holders of the parent 100.2 148.8
Earnings per share 8
Basic 23.3p 34.6p
Diluted 23.2p 34.4p
"""

CASH = """
Consolidated cash flow statement
For the year ended 31 December 2013
2013 2012
£m £m
Net cash flows from operating activities (78.4) (25.6)
Acquisition of intangible assets (6.5) (3.7)
Acquisition of property, plant and equipment (21.6) (14.6)
"""

NOTE = """
8 Earnings per share
2013 2012
Weighted average number of ordinary shares (millions)
Basic 430.2 429.1
"""


def _parse():
    return parse_statement_pages(
        [
            StatementPage(page=76, text=INCOME, method="fixture"),
            StatementPage(page=80, text=CASH, method="fixture"),
            StatementPage(page=92, text=NOTE, method="fixture"),
        ],
        fiscal_year_end="2013-12-31",
        filing_date="2014-05-12",
        transaction_id="tx-carillion-2013",
    )


def test_repairs_spaced_and_glued_decimals() -> None:
    assert "124.4" in repair_spaced_decimals("Group operating profit 3 124 4 159 6")
    assert "159.6" in repair_spaced_decimals("Group operating profit 3 124 4 159 6")
    assert repair_spaced_decimals("23 3p") == "23.3p"
    assert repair_spaced_decimals("(78 4)") == "(78.4)"
    assert repair_spaced_decimals("2 3,332.6") == "2 3,332.6"
    assert repair_glued_thousands("3,3326") == "3,332.6"
    assert repair_glued_thousands("76,641") == "76,641"
    assert repair_spaced_decimals("11,271 9,585") == "11,271 9,585"
    assert "4,080.9" in repair_spaced_decimals("Total revenue 4,080 9 4,402 8")


def test_two_digit_pence_gap_inserts_a_decimal() -> None:
    wide = [_Char("7", 0, 12, 0), _Char("6", 24, 36, 0)]
    tight = [_Char("7", 0, 12, 0), _Char("6", 14, 26, 0)]
    assert _insert_decimal_from_boxes("76", wide) == "7.6"
    assert _insert_decimal_from_boxes("76", tight) == "76"


def test_char_gap_inserts_a_decimal_before_the_last_digit() -> None:
    # Gaps of 4, 4, then 14 before the final digit.
    chars = [
        _Char("1", 0, 10, 0),
        _Char("5", 14, 24, 0),
        _Char("9", 28, 38, 0),
        _Char("6", 52, 62, 0),
    ]
    assert _token_text(chars) == "159.6"


def test_extracts_eps_in_pence_and_gbp_millions() -> None:
    parsed = _parse()
    fields = parsed["fields"]
    assert fields["basic_eps"]["value"] == "23.3"
    assert fields["basic_eps"]["unit"] == "pence"
    assert fields["revenue"]["value"] == "3332.6"
    assert fields["revenue"]["scale"] == "millions"
    assert fields["revenue"]["currency"] == "GBP"
    assert fields["operating_profit"]["value"] == "124.4"
    assert fields["profit_attributable_to_owners"]["value"] == "100.2"
    assert fields["net_cash_from_operating_activities"]["value"] == "-78.4"
    assert fields["capital_expenditure"]["value"] == "-28.1"
    assert fields["reporting_currency"]["value"] == "GBP"
    assert fields["weighted_average_basic_shares"]["value"] == "430.2"
    assert fields["weighted_average_basic_shares"]["scale"] == "millions"
    assert fields["fiscal_year_end"]["value"] == "2013-12-31"


def test_citation_names_transaction_page_and_line() -> None:
    revenue = _parse()["fields"]["revenue"]
    citation = revenue["citation"]
    assert citation["transaction_id"] == "tx-carillion-2013"
    assert citation["page"] == 76
    assert "Group revenue" in citation["line"]
    assert revenue["absent_reason"] is None


def test_absent_dividend_records_a_reason() -> None:
    row = _parse()["fields"]["dividends_per_share"]
    assert row["value"] is None
    assert row["absent_reason"]
    assert row["citation"] is None


def test_column_count_mismatch_is_an_absent_reason() -> None:
    text = """
    Consolidated income statement
    For the year ended 31 December 2013
    2013 2012
    £m £m
    Revenue 10.0 9.0
    Operating profit 1.0 2.0 3.0
    """
    parsed = parse_statement_pages(
        [StatementPage(page=4, text=text)],
        fiscal_year_end="2013-12-31",
        filing_date="2014-04-01",
        transaction_id="tx",
    )
    assert parsed["fields"]["revenue"]["value"] == "10"
    row = parsed["fields"]["operating_profit"]
    assert row["value"] is None
    assert "column count" in row["absent_reason"]


def test_sales_and_loss_per_share_and_whole_millions() -> None:
    text = """
    Consolidated income statement
    For the year ended 31 December 2013
    2013 2012
    £m £m
    Sales 2 7,136 6,510
    Group operating profit 1244 159.6
    Loss per share
    Basic and diluted (0.5)p (0.6)p
    """
    parsed = parse_statement_pages(
        [StatementPage(page=10, text=text)],
        fiscal_year_end="2013-12-31",
        filing_date="2014-04-01",
        transaction_id="tx",
    )
    assert parsed["fields"]["revenue"]["value"] == "7136"
    assert parsed["fields"]["operating_profit"]["value"] is None
    assert "decimal" in parsed["fields"]["operating_profit"]["absent_reason"]
    assert parsed["fields"]["basic_eps"]["value"] == "-0.5"
    share_line = """
    Consolidated income statement
    For the year ended 31 December 2013
    2013 2012
    £m £m
    Weighted average number of shares for basic and diluted loss per share 1,440 1,196
    """
    shares = parse_statement_pages(
        [StatementPage(page=11, text=share_line)],
        fiscal_year_end="2013-12-31",
        filing_date="2014-04-01",
        transaction_id="tx",
    )
    assert shares["fields"]["basic_eps"]["value"] is None
    assert shares["fields"]["weighted_average_basic_shares"]["value"] == "1440"
    dashed = """
    Consolidated income statement
    For the year ended 31 December 2013
    2013 2012
    £m £m
    Earnings per share — pence
    Continuing operations — basic 24.2 29.3
    """
    gkn = parse_statement_pages(
        [StatementPage(page=12, text=dashed)],
        fiscal_year_end="2013-12-31",
        filing_date="2014-04-01",
        transaction_id="tx",
    )
    assert gkn["fields"]["basic_eps"]["value"] == "24.2"
    assert gkn["fields"]["basic_eps"]["unit"] == "pence"
    assert parsed["fields"]["basic_eps"]["unit"] == "pence"


def test_keeps_current_year_when_the_comparative_decimal_is_lost() -> None:
    text = """
    Consolidated income statement
    For the year ended 31 December 2013
    2013 2012
    £m £m
    Group operating profit 3 124.4 1596
    """
    parsed = parse_statement_pages(
        [StatementPage(page=76, text=text)],
        fiscal_year_end="2013-12-31",
        filing_date="2014-05-12",
        transaction_id="tx",
    )
    assert parsed["fields"]["operating_profit"]["value"] == "124.4"
    assert (
        parsed["comparative"] is None or "operating_profit" not in parsed["comparative"]["fields"]
    )


def test_ocr_brace_is_read_as_a_negative_amount() -> None:
    text = """
    Consolidated cash flow statement
    For the year ended 31 December 2013
    2013 2012
    £m £m
    Net cash flows from operating activities (78 4} (25 6)
    """
    parsed = parse_statement_pages(
        [StatementPage(page=80, text=text)],
        fiscal_year_end="2013-12-31",
        filing_date="2014-05-12",
        transaction_id="tx",
    )
    assert parsed["fields"]["net_cash_from_operating_activities"]["value"] == "-78.4"


def test_comparative_is_labelled_and_does_not_replace_primary_eps() -> None:
    parsed = _parse()
    comparative = parsed["comparative"]
    assert comparative["source"] == "comparative"
    assert comparative["fiscal_year"] == 2012
    assert comparative["filing_date"] == "2014-05-12"
    assert comparative["fields"]["basic_eps"]["value"] == "34.6"
    assert comparative["fields"]["basic_eps"]["source"] == "comparative"
    assert comparative["fields"]["basic_eps"]["citation"]["transaction_id"] == "tx-carillion-2013"

    filings = [
        parsed,
        {
            "fiscal_year": 2012,
            "fiscal_year_end": "2012-12-31",
            "filing_date": "2013-04-20",
            "transaction_id": "tx-2012",
            "fields": {"basic_eps": {"value": "34.6"}},
            "comparative": None,
        },
    ]
    years = years_with_eps(filings)
    by_year = {row["year"]: row for row in years}
    assert by_year[2013]["source"] == "primary"
    assert by_year[2012]["source"] == "primary"
    assert by_year[2012]["transaction_id"] == "tx-2012"
    assert statements_from_2013(years) is True
    assert statements_from_2013([{"year": 2014, "source": "primary"}]) is False


def test_comparative_fills_a_year_with_no_primary_eps() -> None:
    filings = [
        {
            "fiscal_year": 2014,
            "fiscal_year_end": "2014-09-30",
            "filing_date": "2015-03-18",
            "transaction_id": "tx-2014",
            "fields": {"basic_eps": {"value": "10.41"}},
            "comparative": {
                "source": "comparative",
                "fiscal_year": 2013,
                "fiscal_year_end": "2013-09-30",
                "filing_date": "2015-03-18",
                "transaction_id": "tx-2014",
                "fields": {"basic_eps": {"value": "8.85", "source": "comparative"}},
            },
        }
    ]
    years = years_with_eps(filings)
    by_year = {row["year"]: row for row in years}
    assert by_year[2013]["source"] == "comparative"
    assert by_year[2013]["filing_date"] == "2015-03-18"
    assert statements_from_2013(years) is True


def test_combined_count_adds_ch_names_to_eodhd() -> None:
    rows = []
    for case in KNOWN_FAILURE_CASES:
        key = case["key"]
        depth = key in {"aggreko", "morrison", "wirecard"}
        rows.append(
            {
                "key": key,
                "fundamentals_depth_from_2013": depth,
            }
        )
    eodhd = {"checks": {"a_survivorship": {"rows": rows}}}
    # Four of the seven CH names gain a 2013 EPS. 3 EODHD + 4 CH = 7.
    coverage = [
        {"key": "carillion", "statements_from_2013": True},
        {"key": "thomas_cook", "statements_from_2013": True},
        {"key": "debenhams", "statements_from_2013": True},
        {"key": "sirius", "statements_from_2013": True},
        {"key": "patisserie_holdings", "statements_from_2013": False},
        {"key": "gkn", "statements_from_2013": False},
        {"key": "sky", "statements_from_2013": False},
    ]
    combined = combined_check_a(coverage, eodhd)
    assert combined["bar"] == CHECK_A_BAR == 7
    assert combined["combined_check_a_with_statements"] == 7
    assert combined["pass"] is True
    by_key = {row["key"]: row for row in combined["rows"]}
    assert by_key["wirecard"]["combined_statements_from_2013"] is True
    assert by_key["wirecard"]["ch_applicable"] is False
    assert by_key["carillion"]["eodhd_statements_from_2013"] is False
    assert by_key["carillion"]["combined_statements_from_2013"] is True
    assert by_key["intu"]["combined_statements_from_2013"] is False


def test_ops_finding_info_warn_and_absent(tmp_path: Path) -> None:
    from value_investor.ops_monitor import check_ch_failed_name_statements

    assert check_ch_failed_name_statements(repo_root=tmp_path) == []

    store = tmp_path / "docs" / "data" / "ch_failed_name_statements.json"
    store.parent.mkdir(parents=True)
    payload = {
        "generated_at": "2026-11-12T00:00:00+00:00",
        "combined_check_a_with_statements": 9,
        "combined": {
            "combined_check_a_with_statements": 9,
            "bar": 7,
            "total_names": 11,
        },
    }
    store.write_text(json.dumps(payload), encoding="utf-8")
    [info] = check_ch_failed_name_statements(repo_root=tmp_path)
    assert info.severity == "info"
    assert info.auto_fixable is False
    assert "9 of 11" in info.summary
    assert "bar 7" in info.summary
    direct = ops_findings_from_ch_failed_name_statements(payload)
    assert direct[0]["auto_fixable"] is False

    store.write_text("{not json", encoding="utf-8")
    [warn] = check_ch_failed_name_statements(repo_root=tmp_path)
    assert warn.severity == "warn"
    assert warn.auto_fixable is False
