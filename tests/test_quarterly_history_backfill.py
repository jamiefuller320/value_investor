"""Quarterly history merge, git backfill, and the financials writer path."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import patch

from value_investor.ftse_statement_fetch import StatementFetch, write_fetched_statement
from value_investor.quarterly_history_backfill import (
    QUARTERLY_HISTORY_KEEP,
    backfill_file,
    collect_financials_paths,
    main,
    merge_quarterly_history,
    merge_quarterly_series,
    run_quarterly_backfill,
)
from value_investor.research.ingest import ingest_research_sources

AS_OF = date(2026, 11, 3)
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Quarterly History Test",
    "GIT_AUTHOR_EMAIL": "quarterly-history@example.com",
    "GIT_COMMITTER_NAME": "Quarterly History Test",
    "GIT_COMMITTER_EMAIL": "quarterly-history@example.com",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=_GIT_ENV, capture_output=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")


def _commit_financials(repo: Path, relative: str, payload: dict) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    _git(repo, "add", relative)
    _git(repo, "commit", "-m", f"update {path.name}")


def _revenue_row(amount: float) -> dict[str, float]:
    return {"Total Revenue": amount, "Diluted EPS": amount / 10}


def test_merge_unions_periods_and_incoming_wins():
    existing = {
        "2024-06-30": _revenue_row(1),
        "2024-09-30": _revenue_row(2),
    }
    incoming = {
        "2024-09-30": {"Total Revenue": 20},
        "2024-12-31": _revenue_row(3),
        "2025-03-31": _revenue_row(4),
    }
    merged = merge_quarterly_series(existing, incoming)
    assert list(merged) == ["2025-03-31", "2024-12-31", "2024-09-30", "2024-06-30"]
    assert merged["2024-09-30"] == {"Total Revenue": 20}
    assert merged["2024-06-30"]["Total Revenue"] == 1
    assert existing["2024-09-30"]["Total Revenue"] == 2


def test_merge_caps_at_newest_periods_and_orders_descending():
    existing = {f"2023-{month:02d}-28": _revenue_row(month) for month in range(1, 8)}
    incoming = {f"2024-{month:02d}-28": _revenue_row(month) for month in range(1, 7)}
    merged = merge_quarterly_series(existing, incoming, max_periods=QUARTERLY_HISTORY_KEEP)
    assert len(merged) == QUARTERLY_HISTORY_KEEP
    assert list(merged) == sorted(merged, reverse=True)
    assert "2023-01-28" not in merged
    assert merged["2024-06-28"]["Total Revenue"] == 6


def test_merge_malformed_input():
    incoming = {
        "2024-06-30T00:00:00": _revenue_row(3),
        "not-a-date": {"Total Revenue": 1},
        "2026": _revenue_row(9),
        "2024-01-01": "bad-row",
        "  ": _revenue_row(9),
    }
    merged = merge_quarterly_series(["nope"], incoming, max_periods=0)
    assert merged == {}
    merged = merge_quarterly_series("nope", incoming, max_periods="nope")
    assert list(merged) == ["2024-06-30", "not-a-date", "2026"]
    assert merged["2024-06-30"]["Total Revenue"] == 3
    assert "2026" in merge_quarterly_series(
        {"2026": _revenue_row(1), "2023-01-31": _revenue_row(1)},
        {f"2024-{month:02d}-28": _revenue_row(month) for month in range(1, 13)},
        max_periods=4,
    )
    assert merge_quarterly_series(None, None) == {}
    payload = merge_quarterly_history(
        {"quarterly_income": ["bad"], "ticker": "OLD"},
        {"ticker": "NEW", "income_statement": {"2025": {"Total Revenue": 5}}},
    )
    assert payload["ticker"] == "NEW"
    assert "quarterly_income" not in payload
    assert "quarterly_history_kept" not in payload


def test_merge_empty_incoming_keeps_existing_and_sets_count():
    existing = {
        "ticker": "SHEL.L",
        "income_statement": {"2024": {"Total Revenue": 1}},
        "quarterly_income": {"2024-09-30": _revenue_row(10), "2025-09-30": _revenue_row(11)},
        "quarterly_cashflow": {"2024-09-30": {"Free Cash Flow": 1}},
        "cashflow_metrics": {"free_cashflow": 99},
    }
    incoming = {
        "ticker": "SHEL.L",
        "fetched_at": "2026-11-03T00:00:00+00:00",
        "income_statement": {"2025": {"Total Revenue": 2}},
        "quarterly_income": {},
        "quarterly_cashflow": {"2025-09-30": {"Free Cash Flow": 4}},
        "cashflow_metrics": {"free_cashflow": 5},
    }
    merged = merge_quarterly_history(existing, incoming)
    assert merged["income_statement"] == {"2025": {"Total Revenue": 2}}
    assert merged["cashflow_metrics"]["free_cashflow"] == 5
    assert set(merged["quarterly_income"]) == {"2024-09-30", "2025-09-30"}
    assert set(merged["quarterly_cashflow"]) == {"2024-09-30", "2025-09-30"}
    assert merged["quarterly_cashflow"]["2025-09-30"]["Free Cash Flow"] == 4
    assert merged["quarterly_history_kept"] == 2
    assert incoming["quarterly_income"] == {}


def test_backfill_git_history_adds_older_periods_without_replacing_current(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    relative = "docs/data/research/AAA.L/sources/financials_annual.json"
    _commit_financials(
        repo,
        relative,
        {
            "ticker": "AAA.L",
            "marker": "old",
            "quarterly_income": {
                "2024-06-30": _revenue_row(1),
                "2025-06-30": _revenue_row(2),
                "2025-09-30": _revenue_row(8),
            },
            "quarterly_cashflow": {"2024-06-30": {"Free Cash Flow": 1}},
        },
    )
    current = {
        "ticker": "AAA.L",
        "marker": "current",
        "income_statement": {"2026": {"Total Revenue": 50}},
        "quarterly_income": {
            "2025-09-30": _revenue_row(80),
            "2025-12-31": _revenue_row(3),
            "2026-03-31": _revenue_row(4),
            "2026-06-30": _revenue_row(5),
        },
        "quarterly_cashflow": {"2026-06-30": {"Free Cash Flow": 9}},
        "cashflow_metrics": {"free_cashflow_ttm": 9},
    }
    path = repo / relative
    path.write_text(json.dumps(current, separators=(",", ":")), encoding="utf-8")
    _git(repo, "add", relative)
    _git(repo, "commit", "-m", "current quarters")

    dry = backfill_file(path, repo=repo, apply=False, as_of=AS_OF)
    assert dry["status"] == "would_write"
    assert dry["gained_prior_year"] is True
    assert dry["prior_year_after"] == "2025-06-30"
    assert json.loads(path.read_text(encoding="utf-8"))["marker"] == "current"

    written = backfill_file(path, repo=repo, apply=True, as_of=AS_OF)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert written["status"] == "wrote"
    assert payload["marker"] == "current"
    assert payload["income_statement"]["2026"]["Total Revenue"] == 50
    assert payload["cashflow_metrics"]["free_cashflow_ttm"] == 9
    assert payload["quarterly_income"]["2025-09-30"]["Total Revenue"] == 80
    assert payload["quarterly_income"]["2025-06-30"]["Total Revenue"] == 2
    assert payload["quarterly_income"]["2024-06-30"]["Total Revenue"] == 1
    assert payload["quarterly_cashflow"]["2024-06-30"]["Free Cash Flow"] == 1
    assert list(payload["quarterly_income"])[0] == "2026-06-30"
    assert payload["quarterly_history_kept"] == len(payload["quarterly_income"])

    again = backfill_file(path, repo=repo, apply=True, as_of=AS_OF)
    assert again["status"] == "unchanged"
    assert again["gained_prior_year"] is False


def test_backfill_prefers_newer_history_when_current_lacks_the_period(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    relative = "docs/data/research/BBB.L/sources/financials_annual.json"
    _commit_financials(
        repo,
        relative,
        {"ticker": "BBB.L", "quarterly_income": {"2024-06-30": _revenue_row(1)}},
    )
    _commit_financials(
        repo,
        relative,
        {"ticker": "BBB.L", "quarterly_income": {"2024-06-30": _revenue_row(7)}},
    )
    current = {
        "ticker": "BBB.L",
        "quarterly_income": {"2025-06-30": _revenue_row(3)},
    }
    path = repo / relative
    path.write_text(json.dumps(current, separators=(",", ":")), encoding="utf-8")
    _git(repo, "add", relative)
    _git(repo, "commit", "-m", "current")

    backfill_file(path, repo=repo, apply=True, as_of=AS_OF)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["quarterly_income"]["2024-06-30"]["Total Revenue"] == 7


def test_backfill_skips_newer_periods_and_trailing_cashflow(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    relative = "docs/data/research/BAR.L/sources/financials_annual.json"
    _commit_financials(
        repo,
        relative,
        {
            "ticker": "BAR.L",
            "quarterly_income": {
                "2026-09-30": _revenue_row(99),
                "2025-06-30": _revenue_row(2),
            },
            "quarterly_cashflow": {
                "2026-06-30": {"Free Cash Flow": 50},
                "2024-06-30": {"Free Cash Flow": 4},
            },
        },
    )
    current = {
        "ticker": "BAR.L",
        "quarterly_income": {"2026-06-30": _revenue_row(5)},
        "quarterly_cashflow": {"2025-06-30": {"Free Cash Flow": -1}},
        "quarterly_cashflow_source": "get_cashflow(trailing)",
        "cashflow_metrics": {"free_cashflow_ttm": -1},
    }
    path = repo / relative
    path.write_text(json.dumps(current, separators=(",", ":")), encoding="utf-8")
    _git(repo, "add", relative)
    _git(repo, "commit", "-m", "current")

    backfill_file(path, repo=repo, apply=True, as_of=AS_OF)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload["quarterly_income"]) == {"2026-06-30", "2025-06-30"}
    assert payload["quarterly_income"]["2026-06-30"]["Total Revenue"] == 5
    assert payload["quarterly_cashflow"] == {"2025-06-30": {"Free Cash Flow": -1}}
    assert payload["cashflow_metrics"]["free_cashflow_ttm"] == -1


def test_backfill_keeps_non_date_keys_and_does_not_import_them(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    relative = "docs/data/research/YEAR.L/sources/financials_annual.json"
    _commit_financials(
        repo,
        relative,
        {
            "ticker": "YEAR.L",
            "quarterly_income": {
                "2024": _revenue_row(4),
                "2024-06-30": _revenue_row(1),
            },
        },
    )
    current = {
        "ticker": "YEAR.L",
        "quarterly_income": {
            "2026-06-30": _revenue_row(5),
            "2026": _revenue_row(6),
        },
    }
    path = repo / relative
    path.write_text(json.dumps(current, separators=(",", ":")), encoding="utf-8")
    _git(repo, "add", relative)
    _git(repo, "commit", "-m", "current")

    backfill_file(path, repo=repo, apply=True, as_of=AS_OF)
    payload = json.loads(path.read_text(encoding="utf-8"))
    income = payload["quarterly_income"]
    assert income["2026"]["Total Revenue"] == 6
    assert income["2026-06-30"]["Total Revenue"] == 5
    assert income["2024-06-30"]["Total Revenue"] == 1
    assert "2024" not in income


def test_shallow_clone_reports_history_unavailable(tmp_path: Path):
    origin = tmp_path / "origin"
    _init_repo(origin)
    relative = "docs/data/research/AAA.L/sources/financials_annual.json"
    _commit_financials(
        origin,
        relative,
        {"ticker": "AAA.L", "quarterly_income": {"2024-06-30": _revenue_row(1)}},
    )
    _commit_financials(
        origin,
        relative,
        {"ticker": "AAA.L", "quarterly_income": {"2025-06-30": _revenue_row(2)}},
    )
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--depth", "1", origin.as_uri(), str(clone)],
        check=True,
        capture_output=True,
        env=_GIT_ENV,
    )
    report = run_quarterly_backfill(
        data_dir=clone / "docs" / "data",
        repo=clone,
        tickers=["AAA.L"],
        include_library=False,
        apply=True,
        as_of=AS_OF,
    )
    assert report["history"] == "history unavailable"
    assert report["summary"]["wrote"] == 0
    assert report["results"][0]["note"] == "history unavailable"
    stored = json.loads((clone / relative).read_text(encoding="utf-8"))
    assert "2024-06-30" not in stored["quarterly_income"]

    code = main(
        [
            "--repo",
            str(clone),
            "--data-dir",
            str(clone / "docs" / "data"),
            "--tickers",
            "AAA.L",
            "--apply",
            "--as-of",
            "2026-11-03",
        ]
    )
    assert code == 0


def test_cli_shallow_text_mentions_history_unavailable(tmp_path: Path, capsys):
    origin = tmp_path / "origin"
    _init_repo(origin)
    (origin / "README").write_text("x", encoding="utf-8")
    _git(origin, "add", "README")
    _git(origin, "commit", "-m", "init")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--depth", "1", origin.as_uri(), str(clone)],
        check=True,
        capture_output=True,
        env=_GIT_ENV,
    )
    code = main(["--repo", str(clone), "--data-dir", str(clone), "--tickers", "AAA.L"])
    captured = capsys.readouterr()
    assert code == 0
    assert "history unavailable" in captured.out


def test_collect_paths_limit_and_named_tickers(tmp_path: Path):
    data = tmp_path / "docs" / "data"
    for ticker in ("AAA.L", "BBB.L"):
        path = data / "research" / ticker / "sources"
        path.mkdir(parents=True)
        (path / "financials_annual.json").write_text("{}", encoding="utf-8")
    (data / "latest.json").write_text(
        json.dumps({"reports": [{"ticker": "BBB.L"}, {"ticker": "AAA.L"}, {"ticker": "NOPE.L"}]}),
        encoding="utf-8",
    )
    limited = collect_financials_paths(data, limit=1, include_library=False)
    assert len(limited) == 1
    named = collect_financials_paths(data, tickers=["AAA.L", "missing"], include_library=False)
    assert [path.parent.parent.name for path in named] == ["AAA.L", "MISSING"]


@patch("value_investor.research.ingest.fetch_google_news_rss", return_value=[])
@patch("value_investor.research.ingest.fetch_yfinance_news", return_value=[])
@patch("value_investor.research.ingest.fetch_annual_financials")
def test_ingest_writer_merges_existing_quarterly_series(
    mock_fetch, _mock_yf, _mock_google, tmp_path: Path
):
    sources = tmp_path / "sources"
    sources.mkdir()
    existing = {
        "ticker": "SHEL.L",
        "income_statement": {"2024": {"Total Revenue": 1}},
        "quarterly_income": {
            "2024-09-30": _revenue_row(10),
            "2025-06-30": _revenue_row(11),
        },
        "quarterly_cashflow": {"2024-09-30": {"Free Cash Flow": 1}},
        "cashflow_metrics": {"free_cashflow": 99},
    }
    (sources / "financials_annual.json").write_text(
        json.dumps(existing, separators=(",", ":")),
        encoding="utf-8",
    )
    mock_fetch.return_value = {
        "ticker": "SHEL.L",
        "fetched_at": "2026-11-03T00:00:00+00:00",
        "income_statement": {"2025": {"Total Revenue": 2}},
        "quarterly_income": {
            "2025-06-30": _revenue_row(110),
            "2025-09-30": _revenue_row(12),
            "2025-12-31": _revenue_row(13),
            "2026-03-31": _revenue_row(14),
        },
        "quarterly_cashflow": {"2025-09-30": {"Free Cash Flow": 2}},
        "cashflow_metrics": {"free_cashflow": 5, "free_cashflow_ttm": 5},
    }
    ingest_research_sources(
        ticker="SHEL.L",
        company_name="Shell",
        screening_snapshot={"ticker": "SHEL.L"},
        sources_dir=sources,
        include_filings=False,
    )
    payload = json.loads((sources / "financials_annual.json").read_text(encoding="utf-8"))
    assert payload["income_statement"] == {"2025": {"Total Revenue": 2}}
    assert payload["cashflow_metrics"]["free_cashflow_ttm"] == 5
    assert payload["quarterly_income"]["2025-06-30"]["Total Revenue"] == 110
    assert payload["quarterly_income"]["2024-09-30"]["Total Revenue"] == 10
    assert payload["quarterly_cashflow"]["2024-09-30"]["Free Cash Flow"] == 1
    assert list(payload["quarterly_income"])[0] == "2026-03-31"
    assert payload["quarterly_history_kept"] == 5


def test_statement_fetch_writer_merges_existing_quarterly_series(tmp_path: Path):
    existing = {
        "ticker": "BMY.L",
        "quarterly_income": {"2024-09-30": _revenue_row(3)},
        "income_statement": {"2024": {"Net Income": 1}},
    }
    (tmp_path / "financials_annual.json").write_text(
        json.dumps(existing, separators=(",", ":")),
        encoding="utf-8",
    )
    fresh = {
        "ticker": "BMY.L",
        "fetched_at": "2026-11-03T00:00:00+00:00",
        "income_statement": {"2025": {"Net Income": 10}},
        "quarterly_income": {"2025-09-30": _revenue_row(4)},
    }
    result = StatementFetch(ticker="BMY.L", payload=fresh, written=None, dry_run=True)
    written = write_fetched_statement(result, tmp_path)
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["income_statement"] == {"2025": {"Net Income": 10}}
    assert payload["quarterly_income"]["2024-09-30"]["Total Revenue"] == 3
    assert payload["quarterly_income"]["2025-09-30"]["Total Revenue"] == 4
    assert result.payload == fresh
