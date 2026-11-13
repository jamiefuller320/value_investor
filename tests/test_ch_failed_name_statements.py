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
    apply_value_gate,
    combined_check_a,
    merge_ocr_readings,
    ops_findings_from_ch_failed_name_statements,
    parse_amount,
    parse_statement_pages,
    plausibility_flags,
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
    assert "Leaver statements" not in info.summary
    payload["leaver_coverage"] = {
        "every_year": 4,
        "ch_applicable": 10,
        "with_any_statement": 6,
    }
    [with_leavers] = ops_findings_from_ch_failed_name_statements(payload)
    assert "9 of 11" in with_leavers["summary"]
    assert "4 of 10" in with_leavers["summary"]

    store.write_text("{not json", encoding="utf-8")
    [warn] = check_ch_failed_name_statements(repo_root=tmp_path)
    assert warn.severity == "warn"
    assert warn.auto_fixable is False


_IXBRL = """
<html><body>
<xbrli:context id="cy">
  <xbrli:period><xbrli:startDate>2016-01-01</xbrli:startDate><xbrli:endDate>2016-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="py">
  <xbrli:period><xbrli:startDate>2015-01-01</xbrli:startDate><xbrli:endDate>2015-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="seg">
  <xbrli:period><xbrli:startDate>2016-01-01</xbrli:startDate><xbrli:endDate>2016-12-31</xbrli:endDate></xbrli:period>
  <xbrldi:explicitMember dimension="ifrs-full:SegmentsAxis">retail</xbrldi:explicitMember>
</xbrli:context>
<ix:nonFraction name="ifrs-full:Revenue" contextRef="seg" unitRef="iso4217:GBP" scale="6">9</ix:nonFraction>
<ix:nonFraction name="ifrs-full:Revenue" contextRef="cy" unitRef="iso4217:GBP" scale="6">1,200</ix:nonFraction>
<ix:nonFraction name="ifrs-full:Revenue" contextRef="py" unitRef="iso4217:GBP" scale="6">1,000</ix:nonFraction>
<ix:nonFraction name="ifrs-full:OperatingProfitLoss" contextRef="cy" unitRef="iso4217:GBP" scale="6">150</ix:nonFraction>
<ix:nonFraction name="ifrs-full:ProfitLossAttributableToOwnersOfParent" contextRef="cy" unitRef="iso4217:GBP" scale="6">80</ix:nonFraction>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="cy" unitRef="iso4217:GBX" decimals="1">12.5</ix:nonFraction>
<ix:nonFraction name="ifrs-full:WeightedAverageNumberOfOrdinarySharesOutstanding" contextRef="cy" unitRef="shares" scale="6">640</ix:nonFraction>
<ix:nonFraction name="ifrs-full:CashFlowsFromUsedInOperatingActivities" contextRef="cy" unitRef="iso4217:GBP" scale="6">210</ix:nonFraction>
<ix:nonFraction name="ifrs-full:PurchaseOfPropertyPlantAndEquipment" contextRef="cy" unitRef="iso4217:GBP" scale="6" sign="-">40</ix:nonFraction>
<ix:nonFraction name="ifrs-full:PurchaseOfIntangibleAssets" contextRef="cy" unitRef="iso4217:GBP" scale="6">10</ix:nonFraction>
<ix:nonFraction name="ifrs-full:DilutedEarningsLossPerShare" contextRef="cy" unitRef="iso4217:GBX">11</ix:nonFraction>
</body></html>
"""


def test_ixbrl_prefers_undimensioned_group_figures() -> None:
    from value_investor.ch_leaver_statements import parse_ixbrl_html

    parsed = parse_ixbrl_html(
        _IXBRL, made_up_date="2016-12-31", filing_date="2017-03-01", transaction_id="tx1"
    )
    assert parsed is not None
    fields = parsed["fields"]
    assert fields["revenue"]["value"] == "1200"
    assert fields["revenue"]["scale"] == "millions"
    assert fields["revenue"]["currency"] == "GBP"
    assert fields["revenue"]["citation"]["page"] is None
    assert fields["revenue"]["citation"]["transaction_id"] == "tx1"
    assert "revenue" in fields["revenue"]["citation"]["line"]
    assert fields["basic_eps"]["value"] == "12.5"
    assert fields["basic_eps"]["unit"] == "pence"
    assert fields["capital_expenditure"]["value"] == "50"
    assert parsed["comparative"]["fiscal_year"] == 2015
    assert parsed["comparative"]["fields"]["revenue"]["value"] == "1000"
    assert parsed["methods"] == ["ixbrl"]


def test_leaver_filing_window_skips_post_takeover_subsidiary_accounts() -> None:
    from value_investor.ch_leaver_statements import filing_in_leaver_window

    group = {
        "made_up_date": "2018-12-31",
        "description": "accounts-with-accounts-type-group",
    }
    subsidiary = {
        "made_up_date": "2019-03-31",
        "description": "accounts-with-accounts-type-full",
    }
    assert filing_in_leaver_window(group, "2018-04-24") is True
    assert (
        filing_in_leaver_window(
            {"made_up_date": "2018-06-30", "description": "accounts-with-accounts-type-interim"},
            "2018-04-24",
        )
        is False
    )
    assert filing_in_leaver_window(subsidiary, "2018-04-24") is False
    assert (
        filing_in_leaver_window(
            {"made_up_date": "2011-12-31", "description": "accounts-with-accounts-type-group"},
            "2018-04-24",
        )
        is False
    )


def test_plausibility_flags_mark_and_do_not_drop() -> None:
    filings = [
        _filing(
            2016,
            basic_eps="10",
            eps_unit="pence",
            revenue="100",
            operating_profit="5",
            profit="64",
            shares="640",
        ),
        _filing(
            2017,
            basic_eps="200",
            eps_unit="pence",
            revenue="4",
            operating_profit="9",
            profit="64",
            shares="640",
        ),
    ]
    flags = plausibility_flags(filings)
    codes = {flag["code"] for flag in flags}
    assert "eps_jump" in codes
    assert "revenue_below_operating_profit" in codes
    assert filings[1]["fields"]["basic_eps"]["value"] == "200"
    consistent = _filing(
        2016,
        basic_eps="10",
        eps_unit="pence",
        revenue="100",
        operating_profit="5",
        profit="64",
        shares="640",
    )
    # 64 million / 640 million shares = £0.10 = 10 pence.
    assert plausibility_flags([consistent]) == []
    slipped = _filing(
        2016,
        basic_eps="10",
        eps_unit="pounds",
        revenue="100",
        operating_profit="5",
        profit="64",
        shares="640",
    )
    slip_codes = {flag["code"] for flag in plausibility_flags([slipped])}
    assert "pence_pound_unit_slip" in slip_codes


def _filing(
    year: int,
    *,
    basic_eps: str,
    eps_unit: str,
    revenue: str,
    operating_profit: str,
    profit: str,
    shares: str,
) -> dict:
    def money(value: str) -> dict:
        return {"value": value, "scale": "millions", "currency": "GBP", "unit": None}

    return {
        "fiscal_year": year,
        "fields": {
            "basic_eps": {"value": basic_eps, "unit": eps_unit, "scale": None},
            "revenue": money(revenue),
            "operating_profit": money(operating_profit),
            "profit_attributable_to_owners": money(profit),
            "weighted_average_basic_shares": {"value": shares, "scale": "millions", "unit": None},
        },
        "comparative": None,
    }


def test_resume_skips_complete_names_and_keeps_not_applicable() -> None:
    from value_investor.ch_leaver_statements import (
        iter_pending,
        name_is_complete,
        placeholder_name,
    )

    records = [
        {
            "key": "done",
            "name": "Done",
            "leaving_date": "2018-01-01",
            "leaving_year": 2018,
            "expected_years": [2013, 2014],
            "reason_class": "takeover",
            "ch_applicable": True,
            "company_number_status": "resolved",
        },
        {
            "key": "later",
            "name": "Later",
            "leaving_date": "2019-01-01",
            "leaving_year": 2019,
            "expected_years": [2013],
            "reason_class": "failure",
            "ch_applicable": False,
            "company_number_status": "not_applicable",
            "company_number_reason": "incorporated in Jersey",
        },
    ]
    done = {"done": {"key": "done", "extraction_status": "complete", "filings": []}}
    pending = iter_pending(records, done)
    assert [row["key"] for row in pending] == ["later"]
    assert name_is_complete(done["done"]) is True
    offshore = placeholder_name(
        records[1], status="not_applicable", reason="incorporated in Jersey"
    )
    assert offshore["ch_applicable"] is False
    assert offshore["filings"] == []
    assert offshore["leaver_coverage"]["statements_every_year"] is False
    assert name_is_complete(offshore) is True


def _income(text: str, *, end: str = "2012-03-31") -> dict:
    return parse_statement_pages(
        [StatementPage(page=1, text=text)],
        fiscal_year_end=end,
        filing_date="2012-06-30",
        transaction_id="tx",
    )


def test_revenue_label_is_the_revenue_line_not_a_tax_adjustment() -> None:
    # Essar Energy 2012. The sales-tax adjustment is 20,903.0; revenue is 21,956.7.
    both = _income(
        """
        Consolidated income statement
        15 months ended 31 March 2012
        2012 2010
        $ million $ million
        Revenue 21,956.7 10,005.6
        Adjustment for loss of sales tax benefit 8a 20,903.0 9,200.1
        """
    )
    assert both["fields"]["revenue"]["value"] == "21956.7"
    adjustment_only = _income(
        """
        Consolidated income statement
        15 months ended 31 March 2012
        2012 2010
        $ million $ million
        Adjustment for loss of sales tax benefit 8a 20,903.0 9,200.1
        """
    )
    assert adjustment_only["fields"]["revenue"]["value"] is None
    # The OCR line glued an extra digit. It is not repaired into 20,903.0.
    ocr = _income(
        """
        Consolidated income statement
        15 months ended 31 March 2012
        2012 2010
        $ million $ million
        Revenue 20,9030 10,0056
        """
    )
    assert ocr["fields"]["revenue"]["value"] is None
    assert repair_glued_thousands("20,9030") == "20,9030"
    assert repair_glued_thousands("3,3326") == "3,332.6"


def test_parenthesised_negative_keeps_every_digit() -> None:
    # Essar Energy 2014 income statement: Owners of the Company (310.1).
    assert parse_amount("(310.1)", scale="millions") == ("ok", "-310.1", None)
    assert parse_amount("(1,051.5)", scale="millions") == ("ok", "-1051.5", None)
    kind, value, _unit = parse_amount("3(10.1)", scale="millions")
    assert kind in {"unresolved", "no"}
    assert value is None
    assert repair_spaced_decimals("(3 10.1)") == "(310.1)"
    parsed = _income(
        """
        Consolidated income statement
        Year ended 31 March 2014
        2014 2013
        $ million $ million
        Attributable to
        Owners of the Company (310.1) (162.8)
        """,
        end="2014-03-31",
    )
    assert parsed["fields"]["profit_attributable_to_owners"]["value"] == "-310.1"
    split = _income(
        """
        Consolidated income statement
        Year ended 31 March 2014
        2014 2013
        $ million $ million
        Attributable to
        Owners of the Company (3 10.1) (162 8)
        """,
        end="2014-03-31",
    )
    assert split["fields"]["profit_attributable_to_owners"]["value"] == "-310.1"


def test_eps_keeps_its_decimal_from_the_tui_line() -> None:
    # TUI Travel 2012 OCR: 'Basic earnings per share 32 125 77'. The PDF is 12.5p.
    lost = _income(
        """
        Consolidated income statement
        Year ended 30 September 2012
        2012 2011
        £m £m
        Basic earnings per share 32 125 77
        """,
        end="2012-09-30",
    )
    assert lost["fields"]["basic_eps"]["value"] is None
    assert "decimal" in (lost["fields"]["basic_eps"]["absent_reason"] or "").lower()
    kept = _income(
        """
        Consolidated income statement
        Year ended 30 September 2012
        2012 2011
        £m £m
        Basic earnings per share 32 12.5 7.7
        """,
        end="2012-09-30",
    )
    assert kept["fields"]["basic_eps"]["value"] == "12.5"
    # Profit and the share count disagree with a 10x EPS, so the EPS is dropped.
    disagree = _income(
        """
        Consolidated income statement
        Year ended 30 September 2012
        2012 2011
        £m £m
        Attributable to
        Equity holders of the parent 138.0 85.0
        Basic earnings per share 12.5 7.7
        Weighted average number of shares (millions)
        Basic 100.0 90.0
        """,
        end="2012-09-30",
    )
    # 138m / 100m shares = 1.38 pounds, not 12.5 pence and not 12.5 pounds.
    assert disagree["fields"]["basic_eps"]["value"] is None


def test_profit_is_not_taken_from_comprehensive_income() -> None:
    # Invensys 2014 OCR. 2,464 is attributable comprehensive income, not profit.
    oci = _income(
        """
        Consolidated statement of comprehensive income
        For the year ended 31 March 2014
        2014 2013
        £m £m
        Profit for the year 2,806 118
        Total comprehensive income for the year 2,462 54
        Attributable to:
        Equity holders of the parent 2,464 53
        """,
        end="2014-03-31",
    )
    assert oci["fields"]["profit_attributable_to_owners"]["value"] is None
    both = _income(
        """
        Consolidated income statement
        For the year ended 31 March 2014
        2014 2013
        £m £m
        Profit attributable to
        Equity holders of the parent 100.2 80.0
        Consolidated statement of comprehensive income
        For the year ended 31 March 2014
        2014 2013
        £m £m
        Attributable to:
        Equity holders of the parent 2,464 53
        """,
        end="2014-03-31",
    )
    assert both["fields"]["profit_attributable_to_owners"]["value"] == "100.2"


def test_false_decimal_and_lost_intangible_decimal_are_left_absent() -> None:
    # Indivior 2020. The highlight row is 647, not 64.7. The other columns are integers.
    indivior = _income(
        """
        Consolidated income statement
        Historical financial information
        For the year ended 31 December 2020
        2020 2019 2018 2017 2016
        $m $m $m $m $m
        Revenue from continuing operations 64.7 785 1,005 1,093 1,058
        """,
        end="2020-12-31",
    )
    assert indivior["fields"]["revenue"]["value"] is None
    # A millions revenue whose comparative only lost its comma-decimal stays.
    essar_revenue = _income(
        """
        Consolidated income statement
        For the year ended 31 March 2014
        2014 2013
        $ million $ million
        Revenue 4 25,864.8 27,2577
        """,
        end="2014-03-31",
    )
    assert essar_revenue["fields"]["revenue"]["value"] == "25864.8"
    # Essar 2012 cash flow. PPE is (2,128.9). Intangibles are (4.1), read as (41) beside (1.2).
    essar_capex = _income(
        """
        Consolidated statement of cash flows
        15 months ended 31 March 2012
        2012 2010
        $ million $ million
        Purchase of property, plant and equipment (2,128 9) (2,496 5)
        Purchase of intangible assets (41) (1.2)
        """,
        end="2012-03-31",
    )
    assert essar_capex["fields"]["capital_expenditure"]["value"] is None
    stored = [
        {
            "fiscal_year": 2020,
            "fields": {
                "revenue": {
                    "value": "64.7",
                    "scale": "millions",
                    "citation": {
                        "line": "Revenue from continuing operations 64.7 785 1,005 1,093 1,058"
                    },
                }
            },
        },
        {
            "fiscal_year": 2012,
            "fields": {
                "capital_expenditure": {
                    "value": "-2169.9",
                    "scale": "millions",
                    "components": [
                        {"label": "Purchase of property, plant and equipment", "value": "-2128.9"},
                        {"label": "Purchase of intangible assets", "value": "-41"},
                    ],
                    "citation": {
                        "line": (
                            "Purchase of property, plant and equipment (2,128 9} (2,496 5) | "
                            "Purchase of intangible assets (41) (1.2)"
                        )
                    },
                }
            },
        },
    ]
    counts = apply_value_gate(stored, financial=False)
    assert stored[0]["fields"]["revenue"]["value"] is None
    assert stored[0]["fields"]["revenue"]["absent_reason"] == "row_decimal"
    assert stored[1]["fields"]["capital_expenditure"]["value"] is None
    assert stored[1]["fields"]["capital_expenditure"]["absent_reason"] == "row_decimal"
    assert counts["by_check"]["row_decimal"] == 2


def test_trailing_zero_in_the_citation_is_the_same_number() -> None:
    from decimal import Decimal

    from value_investor.ch_failed_name_statements import citation_supports

    # Spirit 2015. The stored 124 is the printed 124.0, not a dropped digit.
    assert citation_supports(
        Decimal("124"), "Net cash generated from operating activities 124.0 165.2"
    )[0]
    assert citation_supports(Decimal("10.6"), "Basic 5 10.60 15.59")[0]
    # Essar 2014 and the sales-tax line stay rejected.
    assert not citation_supports(Decimal("-10.1"), "Owners of the Company (310.1) (162.8)")[0]
    assert not citation_supports(Decimal("20903"), "Revenue 20,9030 10,0056")[0]
    restored = [
        {
            "fiscal_year": 2015,
            "fields": {
                "net_cash_from_operating_activities": {
                    "value": None,
                    "nulled_from": "124",
                    "absent_reason": "digit_count",
                    "scale": "millions",
                    "citation": {
                        "line": "Net cash generated from operating activities 124.0 165.2"
                    },
                }
            },
        }
    ]
    apply_value_gate(restored, financial=False)
    assert restored[0]["fields"]["net_cash_from_operating_activities"]["value"] == "124"


def test_value_gate_nulls_the_four_bad_citations_and_keeps_a_match() -> None:
    def field(value: str, line: str, **extra: object) -> dict:
        row = {
            "value": value,
            "scale": extra.get("scale"),
            "unit": extra.get("unit"),
            "currency": "GBP",
            "citation": {"line": line, "page": 1, "transaction_id": "tx"},
        }
        return row

    filings = [
        {
            "fiscal_year": 2012,
            "fields": {
                "revenue": field("20903", "Revenue 20,9030 10,0056", scale="millions"),
                "basic_eps": field("125", "Basic earnings per share 32 125 77"),
                "profit_attributable_to_owners": field(
                    "138", "Equity holders of the parent 138 85", scale="millions"
                ),
            },
            "comparative": None,
        },
        {
            "fiscal_year": 2013,
            "fields": {
                "revenue": field("14460", "Revenue 3 14,460 14,687", scale="millions"),
                "basic_eps": field("12.5", "Basic earnings per share 12.5 7.7", unit="pence"),
                "profit_attributable_to_owners": field(
                    "100", "Owners of the Company 100 80", scale="millions"
                ),
                "weighted_average_basic_shares": field(
                    "430.2", "Basic 430.2 429.1", scale="millions"
                ),
                "operating_profit": field("20000", "Operating profit 20,000 301", scale="millions"),
            },
            "comparative": None,
        },
    ]
    # 2013 EPS 12.5 pence vs profit 100m / 430.2m shares is about 23 pence.
    counts = apply_value_gate(filings, financial=False)
    assert filings[0]["fields"]["revenue"]["value"] is None
    assert filings[0]["fields"]["revenue"]["absent_reason"] == "digit_count"
    assert filings[0]["fields"]["basic_eps"]["value"] is None
    assert filings[0]["fields"]["basic_eps"]["absent_reason"] == "eps_decimal"
    assert filings[1]["fields"]["revenue"]["value"] == "14460"
    assert filings[1]["fields"]["basic_eps"]["value"] is None
    assert filings[1]["fields"]["basic_eps"]["absent_reason"] == "eps_versus_earnings"
    assert filings[1]["fields"]["profit_attributable_to_owners"]["value"] == "100"
    assert filings[1]["fields"]["operating_profit"]["value"] is None
    assert (
        filings[1]["fields"]["operating_profit"]["absent_reason"]
        == "operating_profit_above_revenue"
    )
    assert counts["total"] >= 4
    # A sign that disagrees with the parenthesis is nulled, not flipped.
    signed = [
        {
            "fiscal_year": 2014,
            "fields": {
                "profit_attributable_to_owners": field(
                    "310.1", "Owners of the Company (310.1) (162.8)", scale="millions"
                )
            },
            "comparative": None,
        }
    ]
    apply_value_gate(signed, financial=False)
    assert signed[0]["fields"]["profit_attributable_to_owners"]["value"] is None
    assert signed[0]["fields"]["profit_attributable_to_owners"]["absent_reason"] == "sign"
    # Adjacent years more than 5x apart are nulled when the line does not explain it.
    jumped = [
        {
            "fiscal_year": 2012,
            "fields": {"basic_eps": field("7.7", "Basic earnings per share 7.7 6.1", unit="pence")},
            "comparative": None,
        },
        {
            "fiscal_year": 2013,
            "fields": {
                "basic_eps": field("80.0", "Basic earnings per share 80.0 7.7", unit="pence")
            },
            "comparative": None,
        },
    ]
    apply_value_gate(jumped, financial=False)
    assert jumped[0]["fields"]["basic_eps"]["value"] == "7.7"
    assert jumped[1]["fields"]["basic_eps"]["value"] is None
    assert jumped[1]["fields"]["basic_eps"]["absent_reason"] == "scale_jump"
    # The hand-verified fixture still passes the gate.
    kept = _parse()
    before = kept["fields"]["basic_eps"]["value"]
    apply_value_gate([kept], financial=False)
    assert kept["fields"]["basic_eps"]["value"] == before
    assert kept["fields"]["revenue"]["value"] == "3332.6"
    assert kept["fields"]["capital_expenditure"]["value"] == "-28.1"


def test_merge_keeps_the_longer_parenthesis_and_fills_a_gap() -> None:
    # Rendered page read (310.1) and missed revenue. The fax read (10.1) and revenue.
    primary = {
        "fields": {
            "profit_attributable_to_owners": {"value": "-310.1"},
            "revenue": {"value": None},
        },
        "comparative": None,
    }
    secondary = {
        "fields": {
            "profit_attributable_to_owners": {"value": "-10.1"},
            "revenue": {"value": "25864.8", "scale": "millions"},
        },
        "comparative": None,
    }
    merged = merge_ocr_readings(primary, secondary)
    assert merged["fields"]["profit_attributable_to_owners"]["value"] == "-310.1"
    assert merged["fields"]["revenue"]["value"] == "25864.8"
    disagree = {
        "fields": {
            "revenue": {"value": "20903"},
            "profit_attributable_to_owners": {"value": None},
        }
    }
    other = {
        "fields": {
            "revenue": {"value": "21956.7"},
            "profit_attributable_to_owners": {"value": None},
        }
    }
    merged = merge_ocr_readings(disagree, other)
    assert merged["fields"]["revenue"]["value"] is None


def test_extraction_order_is_failure_then_other_then_takeover() -> None:
    from value_investor.ch_leaver_statements import extraction_rank, iter_pending

    records = [
        {
            "key": "late_takeover",
            "reason_class": "takeover",
            "leaving_date": "2020-01-01",
            "ch_applicable": True,
        },
        {
            "key": "early_takeover",
            "reason_class": "takeover",
            "leaving_date": "2014-01-01",
            "ch_applicable": True,
        },
        {
            "key": "listing_move",
            "reason_class": "other",
            "leaving_date": "2019-01-01",
            "ch_applicable": True,
        },
        {
            "key": "failed",
            "reason_class": "failure",
            "leaving_date": "2021-01-01",
            "ch_applicable": True,
        },
        {
            "key": "offshore",
            "reason_class": "other",
            "leaving_date": "2015-01-01",
            "ch_applicable": False,
        },
    ]
    pending = iter_pending(records, {})
    assert [row["key"] for row in pending] == [
        "failed",
        "listing_move",
        "early_takeover",
        "late_takeover",
        "offshore",
    ]
    assert extraction_rank(records[3]) < extraction_rank(records[2])
    again = iter_pending(
        records, {"early_takeover": {"extraction_status": "complete"}}, refresh={"early_takeover"}
    )
    assert "early_takeover" in [row["key"] for row in again]
