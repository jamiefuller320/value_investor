"""Belgium official-register / Euronext Brussels harvest."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.research.belgium_official import (
    apply_belgium_recency_bound,
    euronext_regulated_info_url,
    fetch_filings_belgium_official,
    is_brussels_ticker,
    parse_euronext_regulated_info_html,
    resolve_belgium_identity,
)

_FIXTURE_HTML = """
<html>
  <body>
    <h1>Regulated information</h1>
    <ul>
      <li>
        <a href="/sites/default/files/2026-03/AEDIFICA-RA25_EN.pdf">
          Annual financial report 2025 — 24 March 2026
        </a>
      </li>
      <li>
        <a href="https://live.euronext.com/sites/default/files/2025-08/aedifica-half-year-2025.pdf">
          Half-year results 2025 — 2025-08-21
        </a>
      </li>
      <li>
        <a href="/themes/custom/cookies-policy.pdf">Cookie policy</a>
      </li>
      <li>
        <a href="/en/product/equities/BE0003851681-XBRU">Quote page</a>
      </li>
    </ul>
  </body>
</html>
"""

_OLD_ONLY_HTML = """
<html>
  <body>
    <a href="/sites/default/files/2022-03/AEDIFICA-RA21_EN.pdf">
      Annual financial report 2021 — 2022-03-15
    </a>
    <a href="/sites/default/files/2021-03/AEDIFICA-RA20_EN.pdf">
      Annual financial report 2020 — 2021-03-18
    </a>
  </body>
</html>
"""


def test_is_brussels_ticker_only_br_suffix():
    assert is_brussels_ticker("AED.BR") is True
    assert is_brussels_ticker("ABI.BR") is True
    assert is_brussels_ticker("RAND.AS") is False
    assert is_brussels_ticker("AED") is False


def test_euronext_url_uses_isin_and_xbru():
    assert euronext_regulated_info_url("BE0003851681") == (
        "https://live.euronext.com/en/product/equities/BE0003851681-XBRU/regulated-information"
    )


def test_resolve_belgium_identity_builtins(tmp_path: Path):
    path = tmp_path / "ids.json"
    identity = resolve_belgium_identity("AED.BR", path=path, persist=True)
    assert identity["isin"] == "BE0003851681"
    assert identity["cbe"] == "0877248501"
    assert identity["lei"] == "529900DTKNXL0AXQFN28"
    persisted = resolve_belgium_identity("AED.BR", path=path, persist=False)
    assert persisted["isin"] == "BE0003851681"


def test_parse_euronext_html_keeps_filing_pdfs():
    rows = parse_euronext_regulated_info_html(
        _FIXTURE_HTML,
        page_url="https://live.euronext.com/en/product/equities/BE0003851681-XBRU/regulated-information",
        ticker="AED.BR",
    )
    urls = [row["url"] for row in rows]
    assert any(url.endswith("AEDIFICA-RA25_EN.pdf") for url in urls)
    assert any("half-year-2025.pdf" in url for url in urls)
    assert all("cookies-policy" not in url for url in urls)
    annual = next(row for row in rows if "RA25" in row["url"])
    assert annual["source"] == "belgium_official"
    assert annual["period"] == "annual"
    assert annual["period_end"] == "2026-03-24"
    interim = next(row for row in rows if "half-year" in row["url"])
    assert interim["period"] == "interim"
    assert interim["period_end"] == "2025-08-21"


def test_fetch_skips_non_brussels_without_http():
    def boom(*_args, **_kwargs):
        raise AssertionError("HTTP should not run for non-.BR tickers")

    assert (
        fetch_filings_belgium_official(
            ticker="RAND.AS",
            company_name="Randstad N.V.",
            http_get=boom,
            persist_identity=False,
        )
        == []
    )


def test_fetch_parses_injected_html(tmp_path: Path):
    def fake_get(url: str, **_kwargs):
        assert "BE0003851681-XBRU/regulated-information" in url
        return _FIXTURE_HTML.encode("utf-8")

    rows = fetch_filings_belgium_official(
        ticker="AED.BR",
        company_name="Aedifica NV/SA",
        identity_path=tmp_path / "ids.json",
        persist_identity=True,
        http_get=fake_get,
        now=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert len(rows) == 2
    assert {row["period"] for row in rows} == {"annual", "interim"}
    assert all(row["isin"] == "BE0003851681" for row in rows)


def test_recency_floor_keeps_two_old_annuals():
    rows = parse_euronext_regulated_info_html(
        _OLD_ONLY_HTML,
        page_url="https://live.euronext.com/en/product/equities/BE0003851681-XBRU/regulated-information",
        ticker="AED.BR",
    )
    kept = apply_belgium_recency_bound(
        rows,
        lookback_days=800,
        official_annual_floor=2,
        now=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert [row["period_end"] for row in kept] == ["2022-03-15", "2021-03-18"]


def test_recency_lookback_keeps_recent_without_floor():
    rows = parse_euronext_regulated_info_html(
        _FIXTURE_HTML,
        page_url="https://live.euronext.com/en/product/equities/BE0003851681-XBRU/regulated-information",
        ticker="AED.BR",
    )
    kept = apply_belgium_recency_bound(
        rows,
        lookback_days=800,
        official_annual_floor=2,
        now=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert {row["period"] for row in kept} == {"annual", "interim"}
