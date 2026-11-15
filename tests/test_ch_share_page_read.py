from __future__ import annotations

import copy
import json
import statistics
from pathlib import Path

from value_investor.ch_share_page_read import (
    _apply_verified_weighted_shares,
    apply_verified_page_reads_to_store,
)

STORE = Path("docs/data/ch_failed_name_statements.json")
LEAVERS = Path("docs/data/ftse350_leavers_2013_2025.json")
_SCALE = {"units": 1, "thousands": 1e3, "millions": 1e6, "billions": 1e9}

# Real changes of more than 3x within one name's stored years.
SHARE_COUNT_JUMPS_ALLOWED: set[str] = set()


def _counts(name: dict) -> list[tuple[str, str, float]]:
    out = []
    for filing in name.get("filings") or []:
        for field in ("shares_in_issue", "weighted_average_basic_shares"):
            row = (filing.get("fields") or {}).get(field) or {}
            if row.get("value") in (None, ""):
                continue
            value = float(str(row["value"]).replace(",", ""))
            out.append(
                (
                    filing["fiscal_year_end"],
                    field,
                    value * _SCALE.get(row.get("scale") or "units", 1),
                )
            )
    return out


def test_weighted_average_reading_writes_units_and_a_withhold_clears() -> None:
    filing: dict = {
        "fields": {"weighted_average_basic_shares": {"value": "265.6", "scale": "units"}}
    }
    _apply_verified_weighted_shares(
        filing,
        {"value": "265,600,000", "page": 88, "line": "Weighted average 265.6m"},
        transaction_id="tx",
    )
    row = filing["fields"]["weighted_average_basic_shares"]
    assert (row["value"], row["scale"], row["extraction_method"]) == (
        "265600000",
        "units",
        "page_read",
    )
    assert row["citation"]["page"] == 88
    _apply_verified_weighted_shares(
        filing, {"withhold": True, "absent_reason": "page_read: no EPS note"}, transaction_id="tx"
    )
    row = filing["fields"]["weighted_average_basic_shares"]
    assert row["value"] is None
    assert row["absent_reason"] == "page_read: no EPS note"


def test_a_failed_reading_clears_an_old_unread_value(tmp_path: Path) -> None:
    store = json.loads(STORE.read_text())
    name = copy.deepcopy(next(n for n in store["names"] if n["key"] == "dairy_crest_group"))
    filing = next(f for f in name["filings"] if f["fiscal_year_end"] == "2018-03-31")
    filing["fields"]["shares_in_issue"] = {
        "value": "240000",
        "scale": "millions",
        "source": "primary",
    }
    store["names"] = [name]
    out = tmp_path / "store.json"
    out.write_text(json.dumps(store))
    verified = tmp_path / "verified.json"
    reading = {
        "key": "dairy_crest_group",
        "fiscal_year": filing["fiscal_year"],
        "fiscal_year_end": filing["fiscal_year_end"],
        "transaction_id": filing["transaction_id"],
        "value": "999",
        "page": 1,
        "line": "unclear",
        "column_year_clear": False,
        "weighted_average_basic_shares": {"value": "141000000", "page": 2, "line": "141.0m"},
    }
    verified.write_text(json.dumps({"readings": [reading]}))
    payload = apply_verified_page_reads_to_store(out, leaver_path=LEAVERS, verified_path=verified)
    got = next(
        f
        for n in payload["names"]
        if n["key"] == "dairy_crest_group"
        for f in n["filings"]
        if f["fiscal_year_end"] == "2018-03-31"
    )
    assert got["fields"]["shares_in_issue"]["value"] is None
    assert got["fields"]["shares_in_issue"]["absent_reason"].startswith("page_read: ")
    assert got["fields"]["weighted_average_basic_shares"]["value"] == "141000000"


def test_every_stored_share_count_is_page_read() -> None:
    store = json.loads(STORE.read_text())
    unread = [
        (n["key"], f["fiscal_year_end"], field)
        for n in store["names"]
        for f in n.get("filings") or []
        for field in ("shares_in_issue", "weighted_average_basic_shares")
        if ((f.get("fields") or {}).get(field) or {}).get("value") not in (None, "")
        and ((f.get("fields") or {}).get(field) or {}).get("extraction_method") != "page_read"
    ]
    assert unread == []


def test_stored_share_counts_are_plausible_within_each_name() -> None:
    store = json.loads(STORE.read_text())
    bad = []
    for name in store["names"]:
        counts = _counts(name)
        if not counts:
            continue
        median = statistics.median(v for _, _, v in counts)
        for year_end, field, value in counts:
            if value < 1_000_000:
                bad.append((name["key"], year_end, field, value))
            elif (
                name["key"] not in SHARE_COUNT_JUMPS_ALLOWED
                and not median / 3 <= value <= median * 3
            ):
                bad.append((name["key"], year_end, field, value))
    assert bad == []
