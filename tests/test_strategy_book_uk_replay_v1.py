"""UK replay v1: Companies House share counts for the cap when EODHD has none."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from _uk_replay_synthetic import _business_days, synthetic_records

from value_investor import strategy_book_uk_replay as uk
from value_investor import strategy_book_uk_tape as tape


def _filing(year: int, filed: str | None, **fields: dict) -> dict:
    return {
        "fiscal_year": year,
        "fiscal_year_end": f"{year}-12-31",
        "filing_date": filed,
        "fields": fields,
    }


def _shares(value: str, scale: str = "units") -> dict:
    return {"value": value, "scale": scale}


@pytest.fixture
def v1():
    with uk.registration("v1"):
        yield


def test_ch_shares_on_reads_the_latest_visible_filing(v1) -> None:
    filings = [
        _filing(2012, "2013-03-01", shares_in_issue=_shares("400000000")),
        _filing(2013, "2014-03-03", shares_in_issue=_shares("430.25", "millions")),
    ]
    assert tape.ch_shares_on(filings, date(2013, 3, 2)) is None
    assert tape.ch_shares_on(filings, date(2013, 3, 3)) == {
        "shares": 400_000_000.0,
        "date": date(2012, 12, 31),
        "source": "ch_shares_in_issue",
    }
    later = tape.ch_shares_on(filings, date(2014, 3, 5))
    assert later["shares"] == pytest.approx(430_250_000.0)
    assert later["date"] == date(2013, 12, 31)


def test_ch_shares_on_is_stale_after_456_days(v1) -> None:
    filings = [_filing(2012, "2013-03-01", shares_in_issue=_shares("400000000"))]
    assert tape.ch_shares_on(filings, date(2012, 12, 31) + timedelta(days=456)) is not None
    assert tape.ch_shares_on(filings, date(2012, 12, 31) + timedelta(days=457)) is None


def test_ch_shares_on_falls_back_to_weighted_shares_on_the_same_filing_only(v1) -> None:
    weighted = [
        _filing(
            2012,
            "2013-03-01",
            shares_in_issue={"value": None, "absent_reason": "note not found"},
            weighted_average_basic_shares=_shares("395", "millions"),
        )
    ]
    picked = tape.ch_shares_on(weighted, date(2013, 6, 1))
    assert picked["source"] == "ch_weighted_average_basic_shares"
    assert picked["shares"] == pytest.approx(395_000_000.0)
    # The latest filing has no count: an earlier filing is not used in its place.
    gap = [
        _filing(2012, "2013-03-01", shares_in_issue=_shares("400000000")),
        _filing(2013, "2014-03-03", revenue={"value": "1", "scale": "millions"}),
    ]
    assert tape.ch_shares_on(gap, date(2014, 6, 1)) is None


def test_ch_shares_on_without_a_filing_date_uses_the_statement_lag(v1) -> None:
    filings = [_filing(2012, None, shares_in_issue=_shares("400000000"))]
    first = date(2012, 12, 31) + timedelta(days=180 + 2)
    assert tape.ch_shares_on(filings, first - timedelta(days=1)) is None
    assert tape.ch_shares_on(filings, first) is not None


def _carillion_case() -> tuple[list[dict], dict, dict]:
    records = synthetic_records(lse_names=4, xetra_names=0, shares_as_list=True)
    last = date(2015, 6, 30)
    record = dict(records[0], symbol="ZZQ.LSE", name="Carillion plc", ch_key=None, ch_filings=None)
    record["eod"] = [row for row in record["eod"] if row["date"] <= last.isoformat()]
    record["delisted"] = True
    record["splits"] = []
    record["fundamentals"] = dict(record["fundamentals"])
    del record["fundamentals"]["outstandingShares"]
    records[0] = record
    store = {
        "names": [
            {
                "key": "carillion",
                "epic": "ZZQ",
                "leaving_date": (last + timedelta(days=3)).isoformat(),
                "filings": [
                    _filing(year, f"{year + 1}-03-01", shares_in_issue=_shares("430254629"))
                    for year in range(2011, 2015)
                ],
            }
        ]
    }
    fx = {day: 0.85 for day in _business_days(date(2011, 1, 3), date(2016, 7, 31))}
    return records, store, fx


def test_v0_cannot_rank_a_name_without_eodhd_shares() -> None:
    records, store, fx = _carillion_case()
    assembled = uk.assemble_specs(records, eurgbp=fx, usdgbp=fx, ch_store=store, score=False)
    assert "ZZQ.LSE" not in assembled["ranked_symbols"]
    assert "cap_report" not in assembled


def test_v1_ranks_it_from_companies_house_shares(v1) -> None:
    records, store, fx = _carillion_case()
    assembled = uk.assemble_specs(records, eurgbp=fx, usdgbp=fx, ch_store=store, score=False)
    assert "ZZQ.LSE" in assembled["ranked_symbols"]
    report = assembled["cap_report"]["development"]
    assert report["cap_source_counts"]["ch_shares_in_issue"] > 0
    assert report["cap_source_counts"]["eodhd"] > 0
    assert report["ch_cap_leavers"] == 1
    assert report["named_failures_ranked"] == {
        "carillion": True,
        "thomas_cook": "not_in_store",
        "debenhams": "not_in_store",
        "intu": "not_in_store",
    }
    holdout = assembled["cap_report"]["holdout"]
    assert holdout["ch_cap_leavers"] == 0
    assert holdout["named_failures_ranked"]["carillion"] is False


def test_v1_develop_writes_its_own_store_with_the_cap_report(tmp_path: Path, v1) -> None:
    (tmp_path / "docs/data").mkdir(parents=True)
    records, store, fx = _carillion_case()
    payload = uk.develop(
        repo_root=tmp_path, records=records, eurgbp=fx, usdgbp=fx, ch_store=store, score=False
    )
    assert payload["registration_id"] == "strategy-book-uk-replay-v1"
    assert not (tmp_path / uk.REGISTRATIONS["v0"]["store_path"]).exists()
    written = json.loads((tmp_path / uk.REGISTRATIONS["v1"]["store_path"]).read_text("utf-8"))
    report = written["development"]["cap_report"]
    assert report["named_failures_ranked"]["carillion"] is True
    uk.assert_store_has_no_licensed_numbers(written)


def test_v1_constants_only_add_the_fallback() -> None:
    v0 = uk.REGISTRATIONS["v0"]["constants"]
    v1 = uk.REGISTRATIONS["v1"]["constants"]
    assert "CH_SHARES_FALLBACK" not in v0
    added = {key for key in v1 if key not in v0}
    assert added == {
        "supersedes_registration_id",
        "CH_SHARES_FALLBACK",
        "CH_SHARES_FIELDS",
        "CH_SHARES_STALE_DAYS",
        "CH_SHARES_LAG_DAYS",
        "NAMED_FAILURES",
        "NAMED_FAILURE_MONTHS",
    }
    changed = {key for key in v0 if v0[key] != v1[key]}
    assert changed == {"registration_id"}
    assert v1["CH_SHARES_STALE_DAYS"] == v0["STALE_FILING_DAYS"]
    assert v1["CH_SHARES_LAG_DAYS"] == v0["FILING_LAG_DAYS"]


def test_v1_registration_file_matches_the_constants() -> None:
    entry = uk.REGISTRATIONS["v1"]
    payload = json.loads((Path(uk.REPO_ROOT) / entry["registration_path"]).read_text("utf-8"))
    assert payload["registration_id"] == "strategy-book-uk-replay-v1"
    assert payload["document"] == str(entry["document_path"])
    assert payload["constants"] == json.loads(json.dumps(entry["constants"]))
    assert payload["influences_live"] is False
    assert (Path(uk.REPO_ROOT) / entry["document_path"]).exists()


def test_v1_refuses_eodhd_until_sealed(tmp_path: Path, v1) -> None:
    (tmp_path / "docs/data").mkdir(parents=True)
    uk.write_registration(uk.registration_payload(), tmp_path)
    assert (tmp_path / "docs/data/strategy_book_uk_replay_v1_registration.json").exists()
    with pytest.raises(uk.UnsealedRegistration):
        uk.require_sealed(tmp_path)


def test_cli_registration_flag_does_not_leak(tmp_path: Path, capsys) -> None:
    assert uk.main(["--registration", "v1", "plan"]) == 0
    assert uk.ACTIVE_REGISTRATION == "v0"
    assert uk.STORE_PATH == Path("docs/data/strategy_book_uk_replay.json")


def test_findings_cover_each_store(tmp_path: Path) -> None:
    (tmp_path / "docs/data").mkdir(parents=True)
    assert uk.findings(tmp_path) == []
    (tmp_path / uk.REGISTRATIONS["v1"]["store_path"]).write_text(
        json.dumps({"phase": "development", "markets_scored": ["ftse350"]}), encoding="utf-8"
    )
    rows = uk.findings(tmp_path)
    assert [row["title"] for row in rows] == ["Strategy-book UK replay v1"]
    (tmp_path / uk.REGISTRATIONS["v0"]["store_path"]).write_text("{", encoding="utf-8")
    titles = [row["title"] for row in uk.findings(tmp_path)]
    assert titles == ["Strategy-book UK replay store unreadable", "Strategy-book UK replay v1"]
