"""Library F9-B binds: each path, point-in-time screen runs, and the observe finding."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.decision_input_inventory import DEFAULT_MEMO_MAX_AGE_DAYS
from value_investor.library_decision_input_inventory import (
    FINDING_TITLE,
    evaluate_library_fcf_basis,
    run_library_decision_input_inventory,
)
from value_investor.ops_monitor import check_library_decision_input_inventory
from value_investor.storage import write_json

AS_OF = datetime(2026, 11, 5, tzinfo=UTC)
FRESH = "2026-10-15T00:00:00+00:00"  # exactly 21 days before AS_OF
STALE = "2026-10-14T23:00:00+00:00"  # 21 days plus one hour
BEFORE = "2026-10-01T00:00:00+00:00"
AFTER = "2026-11-06T00:00:00+00:00"


def _write_status(path: Path, *, graduated: list[str], skipped: list[str]) -> None:
    markets = [{"market_id": market_id, "is_graduated": True} for market_id in graduated]
    markets.extend({"market_id": market_id, "is_graduated": False} for market_id in skipped)
    path.write_text(json.dumps({"markets": markets}), encoding="utf-8")


def _screen(root: Path, market_id: str) -> Path:
    screen = root / "markets" / market_id / "screen"
    screen.mkdir(parents=True, exist_ok=True)
    return screen


def _write_summary(screen: Path, run_at: str) -> None:
    (screen / "latest_summary.json").write_text(
        json.dumps({"run_at": run_at}),
        encoding="utf-8",
    )


def _write_signals(screen: Path, rows: list[dict[str, str]]) -> None:
    path = screen / "latest_signals.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ticker", "name", "signal", "free_cashflow"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_run(screen: Path, stamp: str, run_at: str, signals: list[dict[str, str]]) -> None:
    history = screen / "history"
    history.mkdir(parents=True, exist_ok=True)
    write_json(
        history / f"run_{stamp}.json.gz",
        {"run_at": run_at, "prices": {}, "signals": signals},
        compact=True,
        compress=True,
    )


def _write_index(research: Path, ticker: str, *, fetched_at: str, annual_bodies: int = 1) -> None:
    filings_dir = research / ticker / "sources" / "filings"
    filings_dir.mkdir(parents=True, exist_ok=True)
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "fetched_at": fetched_at,
                "summary": {
                    "total": 2,
                    "with_body": annual_bodies + 1,
                    "period_coverage": {
                        "annual": {"total": 1, "with_body": annual_bodies},
                        "interim": {"total": 1, "with_body": 1},
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _write_research(
    research: Path,
    ticker: str,
    *,
    updated_at: str,
    created_at: str | None = None,
    verdict: str | None = "accumulate",
) -> None:
    folder = research / ticker
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "research.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "created_at": created_at or updated_at,
                "updated_at": updated_at,
                "research_verdict": verdict,
            }
        ),
        encoding="utf-8",
    )


def _write_financials(
    research: Path,
    ticker: str,
    *,
    fetched_at: str | None,
    operating_cashflow: float = 200.0,
    capital_expenditure: float = -50.0,
) -> None:
    sources = research / ticker / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "ticker": ticker,
        "cash_flow": {
            "2024": {
                "Operating Cash Flow": operating_cashflow,
                "Capital Expenditure": capital_expenditure,
            }
        },
    }
    if fetched_at is not None:
        payload["fetched_at"] = fetched_at
    (sources / "financials_annual.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_sec(research: Path, ticker: str, *, fetched_at: str, free_cashflow: float) -> None:
    sources = research / ticker / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "sec_companyfacts.json").write_text(
        json.dumps(
            {
                "fetched_at": fetched_at,
                "latest": {"free_cashflow": free_cashflow, "currency": "USD"},
            }
        ),
        encoding="utf-8",
    )


def _write_bridge(research: Path, ticker: str, *, fetched_at: str, amount: float) -> None:
    sources = research / ticker / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "fcf_bridge.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "fetched_at": fetched_at,
                "resolved": True,
                "currency": "USD",
                "company_adjusted": amount,
                "policy_fcf": amount,
                "policy_basis": "company_adjusted",
            }
        ),
        encoding="utf-8",
    )


def _signal(ticker: str, signal: str, free_cashflow: str, *, adjusted: str, verdict: str) -> dict:
    return {
        "ticker": ticker,
        "signal": signal,
        "adjusted_signal": adjusted,
        "research_verdict": verdict,
        "free_cashflow": free_cashflow,
    }


def _row(payload: dict, market_id: str, ticker: str) -> dict:
    matches = [
        row for row in payload["rows"] if row["market_id"] == market_id and row["ticker"] == ticker
    ]
    assert len(matches) == 1, (market_id, ticker, [row["ticker"] for row in payload["rows"]])
    return matches[0]


def _build(root: Path) -> Path:
    status = root / "market_status.json"
    _write_status(status, graduated=["alpha", "beta"], skipped=["gamma"])

    alpha = _screen(root, "alpha")
    research = alpha / "research"
    _write_summary(alpha, "2026-11-04T00:00:00+00:00")
    _write_signals(
        alpha,
        [
            {"ticker": "AAA", "name": "Alpha Co", "signal": "strong_buy", "free_cashflow": "150"},
            {"ticker": "BBB", "name": "No Folder", "signal": "buy", "free_cashflow": "150"},
            {"ticker": "CCC", "name": "No Index", "signal": "buy", "free_cashflow": "150"},
            {"ticker": "DDD", "name": "Future FCF", "signal": "buy", "free_cashflow": "150"},
            {"ticker": "EEE", "name": "No Screen FCF", "signal": "buy", "free_cashflow": ""},
            {"ticker": "FFF", "name": "Diverges", "signal": "buy", "free_cashflow": "400"},
            {"ticker": "GGG", "name": "SEC Only", "signal": "buy", "free_cashflow": "150"},
            {"ticker": "HHH", "name": "Bridge Only", "signal": "buy", "free_cashflow": "150"},
            {"ticker": "III", "name": "Stale Memo", "signal": "buy", "free_cashflow": "150"},
            {"ticker": "JJJ", "name": "No Verdict", "signal": "buy", "free_cashflow": "150"},
            {"ticker": "KKK", "name": "Hold", "signal": "hold", "free_cashflow": "150"},
            {"ticker": "LLL", "name": "Thin Index", "signal": "buy", "free_cashflow": "150"},
        ],
    )
    early = [
        _signal("AAA", "strong_buy", "150", adjusted="strong_buy", verdict="accumulate"),
        _signal("CCC", "buy", "150", adjusted="buy", verdict="neutral"),
        _signal("DDD", "buy", "150", adjusted="buy", verdict="accumulate"),
        _signal("EEE", "buy", "10", adjusted="buy", verdict="accumulate"),
        _signal("FFF", "buy", "400", adjusted="hold", verdict="caution"),
        _signal("GGG", "buy", "150", adjusted="buy", verdict="accumulate"),
        _signal("HHH", "buy", "150", adjusted="buy", verdict="accumulate"),
        _signal("III", "buy", "150", adjusted="buy", verdict="accumulate"),
        _signal("JJJ", "buy", "150", adjusted="buy", verdict=""),
        _signal("LLL", "buy", "150", adjusted="buy", verdict="accumulate"),
        _signal("KKK", "hold", "150", adjusted="hold", verdict="neutral"),
    ]
    _write_run(alpha, "20261101_120000", "2026-11-01T12:00:00+00:00", early)
    _write_run(
        alpha,
        "20261106_120000",
        "2026-11-06T12:00:00+00:00",
        [_signal("AAA", "strong_buy", "150", adjusted="hold", verdict="avoid")],
    )

    _write_index(research, "AAA", fetched_at=BEFORE)
    _write_research(research, "AAA", updated_at=FRESH, verdict="avoid")
    _write_financials(research, "AAA", fetched_at=BEFORE)

    _write_research(research, "CCC", updated_at=FRESH)
    _write_financials(research, "CCC", fetched_at=BEFORE)

    _write_index(research, "DDD", fetched_at=BEFORE)
    _write_research(research, "DDD", updated_at=FRESH)
    _write_financials(research, "DDD", fetched_at=AFTER)

    _write_index(research, "EEE", fetched_at=BEFORE)
    _write_research(research, "EEE", updated_at=FRESH)
    _write_financials(research, "EEE", fetched_at=BEFORE)

    _write_index(research, "FFF", fetched_at=BEFORE)
    _write_research(research, "FFF", updated_at=FRESH)
    _write_financials(research, "FFF", fetched_at=BEFORE)

    _write_index(research, "GGG", fetched_at=BEFORE)
    _write_research(research, "GGG", updated_at=FRESH)
    _write_sec(research, "GGG", fetched_at=BEFORE, free_cashflow=150.0)

    _write_index(research, "HHH", fetched_at=BEFORE)
    _write_research(research, "HHH", updated_at=FRESH)
    _write_bridge(research, "HHH", fetched_at=BEFORE, amount=150.0)

    _write_index(research, "III", fetched_at=BEFORE)
    _write_research(research, "III", updated_at=STALE)
    _write_financials(research, "III", fetched_at=BEFORE)

    _write_index(research, "JJJ", fetched_at=BEFORE)
    _write_research(research, "JJJ", updated_at=FRESH, verdict=None)
    _write_financials(research, "JJJ", fetched_at=BEFORE)

    _write_index(research, "LLL", fetched_at=BEFORE, annual_bodies=0)
    _write_research(research, "LLL", updated_at=FRESH)
    _write_financials(research, "LLL", fetched_at=BEFORE)

    beta = _screen(root, "beta")
    beta_research = beta / "research"
    _write_summary(beta, "2026-11-04T00:00:00+00:00")
    _write_signals(
        beta,
        [{"ticker": "AAA", "name": "Alpha Elsewhere", "signal": "buy", "free_cashflow": "150"}],
    )
    _write_run(
        beta,
        "20261101_120000",
        "2026-11-01T12:00:00+00:00",
        [_signal("AAA", "buy", "150", adjusted="buy", verdict="caution")],
    )
    _write_index(beta_research, "AAA", fetched_at=BEFORE)
    _write_research(beta_research, "AAA", updated_at=FRESH, verdict="caution")
    _write_financials(beta_research, "AAA", fetched_at=BEFORE)

    gamma = _screen(root, "gamma")
    gamma_research = gamma / "research"
    _write_summary(gamma, "2026-11-04T00:00:00+00:00")
    _write_signals(
        gamma,
        [
            {
                "ticker": "AAA",
                "name": "Not Graduated",
                "signal": "strong_buy",
                "free_cashflow": "150",
            }
        ],
    )
    _write_run(
        gamma,
        "20261101_120000",
        "2026-11-01T12:00:00+00:00",
        [_signal("AAA", "strong_buy", "150", adjusted="strong_buy", verdict="accumulate")],
    )
    _write_index(gamma_research, "AAA", fetched_at=BEFORE)
    _write_research(gamma_research, "AAA", updated_at=FRESH)
    _write_financials(gamma_research, "AAA", fetched_at=BEFORE)
    return status


def test_each_bind_path_and_market_rules(tmp_path: Path) -> None:
    status = _build(tmp_path)
    payload = run_library_decision_input_inventory(
        library_root=tmp_path,
        market_status_path=status,
        store_path=tmp_path / "store.json",
        as_of=AS_OF,
        persist=True,
    )

    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert payload["memo_max_age_days"] == DEFAULT_MEMO_MAX_AGE_DAYS == 21
    assert payload["graduated_markets"] == ["alpha", "beta"]
    stored = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
    assert stored["summary"]["buy_tier_names"] == payload["summary"]["buy_tier_names"]

    green = _row(payload, "alpha", "AAA")
    assert green["key_filing_bodies"] is True
    assert green["fcf_basis_bound"] is True
    assert green["fcf_basis_overlay"] is False
    assert green["fcf_basis_source"] == "financials_annual"
    assert green["fcf_filing_aligned"] == 150.0
    assert green["overlay_bound"] is True
    assert green["memo_recent"] is True
    assert green["memo_age_days"] == 21.0
    assert green["all_four_green"] is True
    assert green["gaps"] == []
    assert green["research_verdict"] == "accumulate"
    assert green["research_verdict_source"] == "screen_run"
    assert green["adjusted_signal"] == "strong_buy"
    assert green["screen_run_at"] == "2026-11-01T12:00:00+00:00"
    assert green["screen_run_file"] == "run_20261101_120000.json.gz"
    assert green["filings_total"] == 2
    assert green["filings_with_body"] == 2

    missing_folder = _row(payload, "alpha", "BBB")
    assert missing_folder["has_research_folder"] is False
    assert missing_folder["has_index"] is False
    assert missing_folder["key_filing_bodies"] is False
    assert missing_folder["fcf_basis_bound"] is False
    assert missing_folder["fcf_basis_overlay"] is None
    assert missing_folder["overlay_bound"] is False
    assert missing_folder["memo_recent"] is False
    assert missing_folder["has_memo"] is False
    assert missing_folder["screen_run_at"] is None
    assert set(missing_folder["gaps"]) == set(
        ["key_filing_bodies", "fcf_basis_bound", "overlay_bound", "memo_recent"]
    )

    no_index = _row(payload, "alpha", "CCC")
    assert no_index["has_index"] is False
    assert no_index["key_filing_bodies"] is False
    assert no_index["fcf_basis_bound"] is True
    assert no_index["overlay_bound"] is True
    assert no_index["memo_recent"] is True

    future_fcf = _row(payload, "alpha", "DDD")
    assert future_fcf["fcf_basis_bound"] is False
    assert future_fcf["fcf_basis_overlay"] is None
    assert future_fcf["key_filing_bodies"] is True

    no_screen_fcf = _row(payload, "alpha", "EEE")
    assert no_screen_fcf["fcf_basis_bound"] is False
    assert no_screen_fcf["fcf_screen_ttm"] is None

    diverges = _row(payload, "alpha", "FFF")
    assert diverges["fcf_basis_bound"] is True
    assert diverges["fcf_basis_overlay"] is True
    assert diverges["overlay_bound"] is True
    assert diverges["adjusted_signal"] == "hold"
    assert diverges["research_verdict"] == "caution"

    sec_only = _row(payload, "alpha", "GGG")
    assert sec_only["fcf_basis_bound"] is True
    assert sec_only["fcf_basis_source"] == "sec_companyfacts"
    assert sec_only["fcf_basis_overlay"] is False

    bridge_only = _row(payload, "alpha", "HHH")
    assert bridge_only["fcf_basis_bound"] is True
    assert bridge_only["fcf_basis_source"] == "fcf_bridge"

    stale = _row(payload, "alpha", "III")
    assert stale["has_memo"] is True
    assert stale["memo_recent"] is False
    assert stale["memo_age_days"] == 21.04
    assert stale["key_filing_bodies"] is True
    assert stale["fcf_basis_bound"] is True
    assert stale["overlay_bound"] is True
    assert stale["gaps"] == ["memo_recent"]

    no_verdict = _row(payload, "alpha", "JJJ")
    assert no_verdict["overlay_bound"] is False
    assert no_verdict["adjusted_signal"] == "buy"
    assert no_verdict["research_verdict"] is None

    thin_index = _row(payload, "alpha", "LLL")
    assert thin_index["has_index"] is True
    assert thin_index["key_filing_bodies"] is False

    assert all(row["ticker"] != "KKK" for row in payload["rows"])

    other_market = _row(payload, "beta", "AAA")
    assert other_market["research_verdict"] == "caution"
    assert other_market["adjusted_signal"] == "buy"
    assert other_market["all_four_green"] is True
    assert [row["market_id"] for row in payload["rows"] if row["ticker"] == "AAA"] == [
        "alpha",
        "beta",
    ]
    assert all(row["market_id"] != "gamma" for row in payload["rows"])

    summary = payload["summary"]
    alpha_summary = next(item for item in summary["by_market"] if item["market_id"] == "alpha")
    assert alpha_summary["buy_tier_names"] == 11
    assert summary["buy_tier_names"] == 12
    assert "gamma" not in {item["market_id"] for item in summary["by_market"]}


def test_summary_after_as_of_uses_the_screen_run_only(tmp_path: Path) -> None:
    status = tmp_path / "market_status.json"
    _write_status(status, graduated=["alpha"], skipped=[])
    screen = _screen(tmp_path, "alpha")
    _write_summary(screen, AFTER)
    _write_signals(
        screen,
        [
            {"ticker": "RUN", "name": "On Run", "signal": "buy", "free_cashflow": "150"},
            {"ticker": "CSV", "name": "Csv Only", "signal": "strong_buy", "free_cashflow": "150"},
        ],
    )
    _write_run(
        screen,
        "20261101_120000",
        "2026-11-01T12:00:00+00:00",
        [
            _signal("RUN", "buy", "150", adjusted="buy", verdict="accumulate"),
            _signal("OLD", "hold", "150", adjusted="hold", verdict="neutral"),
        ],
    )
    _write_run(
        screen,
        "20261106_120000",
        "2026-11-06T12:00:00+00:00",
        [_signal("CSV", "strong_buy", "150", adjusted="strong_buy", verdict="accumulate")],
    )

    payload = run_library_decision_input_inventory(
        library_root=tmp_path,
        market_status_path=status,
        store_path=tmp_path / "store.json",
        as_of=AS_OF,
        persist=False,
    )
    assert [row["ticker"] for row in payload["rows"]] == ["RUN"]
    row = payload["rows"][0]
    assert row["signal_source"] == "screen_run"
    assert row["adjusted_signal"] == "buy"
    assert row["research_verdict"] == "accumulate"
    assert row["fcf_basis_bound"] is False


def test_disk_verdict_is_point_in_time(tmp_path: Path) -> None:
    status = tmp_path / "market_status.json"
    _write_status(status, graduated=["alpha"], skipped=[])
    screen = _screen(tmp_path, "alpha")
    research = screen / "research"
    _write_summary(screen, "2026-11-04T00:00:00+00:00")
    _write_signals(
        screen,
        [
            {"ticker": "OLD", "name": "Old Memo", "signal": "buy", "free_cashflow": "150"},
            {"ticker": "NEW", "name": "Future Memo", "signal": "buy", "free_cashflow": "150"},
        ],
    )
    _write_run(
        screen,
        "20261101_120000",
        "2026-11-01T12:00:00+00:00",
        [
            _signal("OLD", "buy", "150", adjusted="buy", verdict=""),
            _signal("NEW", "buy", "150", adjusted="buy", verdict=""),
        ],
    )
    _write_research(research, "OLD", updated_at=FRESH, verdict="accumulate")
    _write_research(
        research,
        "NEW",
        updated_at=AFTER,
        created_at="2026-09-01T00:00:00+00:00",
        verdict="avoid",
    )

    payload = run_library_decision_input_inventory(
        library_root=tmp_path,
        market_status_path=status,
        store_path=tmp_path / "store.json",
        as_of=AS_OF,
        persist=False,
    )
    old = _row(payload, "alpha", "OLD")
    assert old["overlay_bound"] is True
    assert old["research_verdict"] == "accumulate"
    assert old["research_verdict_source"] == "research_json"
    assert old["memo_recent"] is True

    future = _row(payload, "alpha", "NEW")
    assert future["overlay_bound"] is False
    assert future["research_verdict"] is None
    assert future["memo_recent"] is False
    assert future["memo_at"] == "2026-09-01T00:00:00+00:00"


def test_undated_bridge_does_not_bind(tmp_path: Path) -> None:
    research = tmp_path / "ZZZ"
    sources = research / "sources"
    sources.mkdir(parents=True)
    (sources / "fcf_bridge.json").write_text(
        json.dumps(
            {
                "ticker": "ZZZ",
                "resolved": True,
                "company_adjusted": 150.0,
                "policy_fcf": 150.0,
            }
        ),
        encoding="utf-8",
    )
    detail = evaluate_library_fcf_basis(research, screen_fcf=150.0, as_of=AS_OF)
    assert detail["fcf_basis_bound"] is False
    assert detail["fcf_basis_overlay"] is None


def test_ops_check_refreshes_store_and_stays_observe_only(tmp_path: Path) -> None:
    status = _build(tmp_path)
    store = tmp_path / "library_decision_input_inventory.json"
    findings = check_library_decision_input_inventory(
        library_root=tmp_path,
        market_status_path=status,
        store_path=store,
        as_of=AS_OF,
        persist=True,
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.title == FINDING_TITLE
    assert finding.severity == "info"
    assert finding.auto_fixable is False
    assert "do not rememo" in finding.summary
    assert store.is_file()
    payload = json.loads(store.read_text(encoding="utf-8"))
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert payload["summary"]["gap_counts"]["memo_recent"] >= 1
