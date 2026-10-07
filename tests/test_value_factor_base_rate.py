"""Parser and freshness checks for the Ken French value-factor summary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.value_factor_base_rate import (
    DEFAULT_STORE_PATH,
    MISSING_TITLE,
    STALE_TITLE,
    base_rate_is_stale,
    finding_for_store,
    ops_finding_from_base_rate,
    parse_french_monthly_csv,
    parse_uk_local_monthly,
    summarise_percent,
)

_FACTORS = """
,Mkt-RF,SMB,HML,RF
199007,1.00,0.10,2.00,0.50
199008,-1.00,0.00,-1.00,0.50
Annual Factors: January-December
1990,0,0,0,0
"""

_PORTFOLIOS = """
  Value Weight Returns -- Monthly
,Lo 30,Hi 30
199007,1.00,4.00
199008,2.00,0.00

  Equal Weight Returns -- Monthly
,Lo 30,Hi 30
199007,1.50,5.00
199008,2.50,1.00

  Number of Firms in Portfolios
,Lo 30,Hi 30
199007,10,12
"""

_UK = """
     Value-Weight Dollar Returns      All 4 Data Items Not Reqd
          Mkt   High    Low   High    Low   High    Low   High    Low   Zero
197501  1.00   9.00   1.00   1.00   1.00   1.00   1.00   1.00   1.00   1.00

     Value-Weight Local  Returns      All 4 Data Items Not Reqd
                -- BE/ME --   --- E/P ---   --- CE/P --   ------  Yld  -----
          Mkt   High    Low   High    Low   High    Low   High    Low   Zero
197501  10.00  12.00   8.00  11.00   9.00  13.00   7.00  14.00   6.00   1.00
197502  -5.00  -4.00  -6.00  -3.00  -7.00  -2.00  -8.00  -1.00  -9.00 -99.99

     Value-Weight Dollar Returns      All 4 Data Items Required
          Mkt   High    Low   High    Low   High    Low   High    Low   Zero
197501  99.00  99.00  99.00  99.00  99.00  99.00  99.00  99.00  99.00  99.00
"""


def test_factor_parser_stops_at_annual_block() -> None:
    blocks = parse_french_monthly_csv(_FACTORS)
    assert len(blocks) == 1
    assert blocks[0]["rows"][199007]["HML"] == 2.0
    assert blocks[0]["rows"][199008]["Mkt-RF"] == -1.0
    assert 1990 not in blocks[0]["rows"]


def test_portfolio_parser_keeps_return_blocks_only() -> None:
    blocks = parse_french_monthly_csv(_PORTFOLIOS)
    titles = [block["title"] for block in blocks]
    assert titles == [
        "Value Weight Returns -- Monthly",
        "Equal Weight Returns -- Monthly",
    ]
    assert blocks[0]["rows"][199007]["Hi 30"] == 4.0
    assert blocks[1]["rows"][199008]["Lo 30"] == 2.5


def test_uk_parser_uses_local_currency_not_required_block() -> None:
    rows = parse_uk_local_monthly(_UK)
    assert set(rows) == {197501, 197502}
    assert rows[197501]["mkt"] == 10.0
    assert rows[197501]["bm_high"] == 12.0
    assert rows[197502]["ep_low"] == -7.0
    assert "dp_zero" not in rows[197502]


def test_summarise_percent_uses_percent_units() -> None:
    # 1% every month compounds to about 12.68% geometric.
    stats = summarise_percent([1.0] * 24)
    assert stats["months"] == 24
    assert stats["annualised_arithmetic_pct"] == 12.0
    assert stats["annualised_geometric_pct"] == 12.68
    assert stats["t_stat"] is None


def test_stale_and_missing_findings() -> None:
    assert ops_finding_from_base_rate(None)["title"] == MISSING_TITLE
    fresh = {"source": {"us_data_cut": "202608"}}
    assert ops_finding_from_base_rate(fresh, today=datetime(2026, 10, 7, tzinfo=UTC)) is None
    assert base_rate_is_stale(fresh, today=datetime(2026, 10, 7, tzinfo=UTC)) is False
    old = {"source": {"us_data_cut": "202001"}}
    stale = ops_finding_from_base_rate(old, today=datetime(2026, 10, 7, tzinfo=UTC))
    assert stale is not None
    assert stale["title"] == STALE_TITLE


def test_store_check_warns_when_file_missing(tmp_path: Path) -> None:
    finding = finding_for_store(tmp_path / "missing.json")
    assert finding is not None
    assert finding["title"] == MISSING_TITLE


def test_committed_summary_matches_the_french_cut() -> None:
    payload = json.loads(DEFAULT_STORE_PATH.read_text(encoding="utf-8"))
    assert payload["source"]["us_data_cut"] == "202608"
    assert payload["source"]["raw_files_stored"] is False
    us_hml = payload["us_hml"]["windows"]["full"]
    assert us_hml["annualised_arithmetic_pct"] == 4.22
    assert us_hml["t_stat"] == 3.43
    uk_earnings = payload["uk_local_value_weight"]["earnings_price"]["high_minus_market"]
    assert uk_earnings["windows"]["full"]["annualised_arithmetic_pct"] == 2.72
    assert uk_earnings["windows"]["full"]["t_stat"] == 2.55
    ex_div = payload["us_sorts_ex_dividend"]["book_to_market"]["value_weight"]["high_minus_market"]
    assert ex_div["windows"]["full"]["annualised_arithmetic_pct"] == -0.19
    europe_rebuilt = payload["europe_big_value"]["rebuilt_hml"]["windows"]["full"]
    europe_hml = payload["europe_hml"]["windows"]["full"]
    assert europe_rebuilt["annualised_arithmetic_pct"] == europe_hml["annualised_arithmetic_pct"]
