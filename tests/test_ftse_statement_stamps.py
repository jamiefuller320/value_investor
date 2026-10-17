"""Stamps copied from a statement payload or a stored price file."""

from __future__ import annotations

import json

from value_investor.ftse_statement_stamps import (
    ORDINARY_SHARES_NAME,
    PRICE_QUOTE_NAME,
    REPORTING_CURRENCY_NAME,
    price_quote_from_stored,
    reporting_currency_from_payload,
    stamp_statement,
)


def test_share_stamp_uses_the_statement_and_skips_a_blank_count(tmp_path):
    payload = {
        "ticker": "BMY.L",
        "balance_sheet": {
            "2026": {"Ordinary Shares Number": None, "Share Issued": "  "},
            "2025": {"Ordinary Shares Number": 80.0},
        },
    }
    stamped = stamp_statement(payload, tmp_path)
    assert stamped.reporting_currency is None
    assert stamped.price_quote is None
    assert not (tmp_path / REPORTING_CURRENCY_NAME).exists()
    assert not (tmp_path / PRICE_QUOTE_NAME).exists()
    written = json.loads((tmp_path / ORDINARY_SHARES_NAME).read_text(encoding="utf-8"))
    assert written == {
        "ticker": "BMY.L",
        "field": "Ordinary Shares Number",
        "year": "2025",
        "ordinary_shares": 80.0,
    }


def test_reporting_currency_is_stored_only_when_the_payload_has_one(tmp_path):
    assert reporting_currency_from_payload({"balance_sheet": {}}) is None
    payload = {"ticker": "HSBA.L", "reporting_currency": "USD", "balance_sheet": {}}
    stamped = stamp_statement(payload, tmp_path)
    written = json.loads(stamped.reporting_currency.read_text(encoding="utf-8"))
    assert written == {"ticker": "HSBA.L", "reporting_currency": "USD"}


def test_price_quote_comes_from_a_stored_file_not_a_share_count(tmp_path):
    sourced = {
        "BMY.L": {"ordinary_shares": 999.0, "quote_currency": "GBp"},
        "BA.L": {"ordinary_shares": 1.0, "quote_currency": "  "},
    }
    assert price_quote_from_stored("BMY.L", history_price=673.0, sourced_shares=sourced) == (
        "GBp",
        "docs/data/ftse350_ordinary_shares.json",
    )
    assert price_quote_from_stored("BA.L", history_price=1860.0, sourced_shares=sourced) is None
    assert price_quote_from_stored("NEW.L", history_price=10.0, sourced_shares=sourced) is None
    assert price_quote_from_stored(
        "NEW.L",
        history_price={"close": 10.0, "quote_currency": "USD"},
        sourced_shares=sourced,
    ) == ("USD", "history price")

    stamped = stamp_statement(
        {"ticker": "BMY.L", "balance_sheet": {}},
        tmp_path,
        price_quote=price_quote_from_stored("BMY.L", sourced_shares=sourced),
    )
    written = json.loads((tmp_path / PRICE_QUOTE_NAME).read_text(encoding="utf-8"))
    assert written["quote_currency"] == "GBp"
    assert "ordinary_shares" not in written
    assert stamped.ordinary_shares is None
