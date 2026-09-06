"""Park leftover thin/IWB names after ingest avenues are exhausted."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.euro_depth_ingest_dispatch import (
    MODE_EXHAUSTED,
    MODE_MAINTENANCE,
    MODE_SPRINT,
    cron_enabled_for_dispatch,
    evaluate_euro_ingest_dispatch,
)
from value_investor.ingest_gap_closure import _library_outstanding_ingest_gaps
from value_investor.library_ingest_dispatch import ingest_parity_met, sprint_ingest_complete
from value_investor.library_ingest_exhaustion import (
    DEFAULT_EXHAUSTION_ZERO_RUNS,
    REASON_AWAITING_PERIODIC,
    REASON_UNFETCHABLE_IWB,
    count_trailing_complete_zero_improve_runs,
    overlay_exhaustion_on_health,
    refresh_library_ingest_exhaustion,
)
from value_investor.library_ingest_maintenance import maybe_advance_parallel_sprint_on_parity
from value_investor.library_learning_depth import assess_library_learning_depth
from value_investor.storage import write_json
from value_investor.summary import CompanyReport


def _health(
    *,
    unmeasured: int = 0,
    zero_body: int = 0,
    thin: int = 0,
    iwb: int = 0,
    unmeasured_tickers: list[str] | None = None,
    zero_body_tickers: list[str] | None = None,
    thin_tickers: list[str] | None = None,
    iwb_tickers: list[str] | None = None,
    iwb_by_ticker: dict[str, int] | None = None,
) -> dict:
    return {
        "unmeasured_buy_tier": unmeasured,
        "zero_body_buy_tier": zero_body,
        "thin_body_buy_tier": thin,
        "indexed_without_body": iwb,
        "unmeasured_tickers": list(unmeasured_tickers or []),
        "zero_body_tickers": list(zero_body_tickers or []),
        "thin_body_tickers": list(thin_tickers or []),
        "indexed_without_body_tickers": list(iwb_tickers or []),
        "indexed_without_body_by_ticker": dict(iwb_by_ticker or {}),
    }


def _log_entry(
    *,
    improved: int = 0,
    targets: int = 8,
    runtime_cutoff: bool = False,
    partial: bool = False,
) -> dict:
    return {
        "market_id": "sp500",
        "improved": improved,
        "targets": targets,
        "runtime_cutoff": runtime_cutoff,
        "partial": partial,
        "health_after": _health(thin=1, iwb=5, thin_tickers=["JBH.AX"], iwb_tickers=["FICO"]),
    }


def _write_index(root: Path, market: str, ticker: str, *, total: int, with_body: int) -> None:
    filings_dir = root / "markets" / market / "screen" / "research" / ticker / "sources" / "filings"
    filings_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        filings_dir / "filings_index.json",
        {
            "summary": {
                "total": total,
                "with_body": with_body,
                "indexed_without_body": max(0, total - with_body),
            },
            "filings": [],
        },
        compact=False,
    )


def _report(ticker: str, signal: str = "buy") -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=f"{ticker} Co",
        sector="X",
        signal=signal,
        models_passed=5,
        model_count=10,
        composite_score=0.6,
        sector_composite_score=0.55,
        families_passed=3,
        passed_families="cheapness",
        data_quality_score=0.8,
        metrics_present=10,
        metrics_total=12,
        weeks_at_signal=1,
        signal_trend="stable",
        conviction_score=0.5,
        stability_label="stable",
        timing_signal="hold",
        timing_score=0.0,
        rsi_14=None,
        price_vs_sma200_pct=None,
        action_note="",
        trade_plan=None,
        summary="",
        passed_models=[],
        key_metrics={},
    )


def test_ingest_parity_met_ignores_parked_leftovers():
    health = overlay_exhaustion_on_health(
        _health(
            thin=1,
            iwb=5,
            thin_tickers=["JBH.AX"],
            iwb_tickers=["FICO"],
            iwb_by_ticker={"FICO": 5},
        ),
        {
            "exhausted": True,
            "parked": [{"ticker": "JBH.AX"}, {"ticker": "FICO"}],
        },
    )
    assert health["ingest_exhausted"] is True
    assert health["effective_thin_body_buy_tier"] == 0
    assert health["effective_indexed_without_body"] == 0
    assert ingest_parity_met(health) is False
    assert sprint_ingest_complete(health) is True


def test_cutoff_runs_do_not_count_toward_exhaustion(tmp_path: Path):
    log_path = tmp_path / "ingest_health_log.json"
    write_json(
        log_path,
        {
            "entries": [
                _log_entry(runtime_cutoff=True, targets=2),
                _log_entry(),
                _log_entry(),
            ]
        },
        compact=False,
    )
    count, had_targets = count_trailing_complete_zero_improve_runs(log_path, market_id="sp500")
    assert count == 2
    assert had_targets is True


def test_improved_run_breaks_exhaustion_streak(tmp_path: Path):
    log_path = tmp_path / "ingest_health_log.json"
    write_json(
        log_path,
        {
            "entries": [
                _log_entry(),
                _log_entry(improved=1),
                _log_entry(),
            ]
        },
        compact=False,
    )
    count, _had = count_trailing_complete_zero_improve_runs(log_path, market_id="sp500")
    assert count == 1


def test_refresh_parks_leftover_iwb_and_thin_after_zero_improve_runs(tmp_path: Path):
    root = tmp_path / "library"
    market = "sp500"
    _write_index(root, market, "FICO", total=19, with_body=14)
    _write_index(root, market, "JBH.AX", total=2, with_body=2)
    log_path = root / "markets" / market / "ingest_health_log.json"
    write_json(
        log_path,
        {"entries": [_log_entry(), _log_entry(), _log_entry()]},
        compact=False,
    )
    health = _health(
        thin=1,
        iwb=5,
        thin_tickers=["JBH.AX"],
        iwb_tickers=["FICO"],
        iwb_by_ticker={"FICO": 5},
    )
    payload = refresh_library_ingest_exhaustion(
        market,
        library_root=root,
        health=health,
        health_log_path=log_path,
        min_zero_runs=DEFAULT_EXHAUSTION_ZERO_RUNS,
    )
    tickers = {row["ticker"]: row for row in payload["parked"]}
    assert payload["exhausted"] is True
    assert set(tickers) == {"FICO", "JBH.AX"}
    assert tickers["FICO"]["reason"] == REASON_UNFETCHABLE_IWB
    assert tickers["JBH.AX"]["reason"] == REASON_AWAITING_PERIODIC


def test_refresh_never_parks_unmeasured_or_zero_body(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    _write_index(root, market, "AED.BR", total=0, with_body=0)
    _write_index(root, market, "THIN.DE", total=2, with_body=2)
    log_path = root / "markets" / market / "ingest_health_log.json"
    write_json(
        log_path,
        {
            "entries": [
                {**_log_entry(), "market_id": market},
                {**_log_entry(), "market_id": market},
                {**_log_entry(), "market_id": market},
            ]
        },
        compact=False,
    )
    payload = refresh_library_ingest_exhaustion(
        market,
        library_root=root,
        health=_health(
            unmeasured=1,
            thin=1,
            unmeasured_tickers=["AED.BR"],
            thin_tickers=["THIN.DE"],
        ),
        health_log_path=log_path,
    )
    assert payload["exhausted"] is False
    assert payload["parked"] == []


def test_refresh_unparks_when_coverage_improves(tmp_path: Path):
    root = tmp_path / "library"
    market = "asx200"
    _write_index(root, market, "JBH.AX", total=4, with_body=4)
    path = root / "markets" / market / "ingest_exhaustion.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        path,
        {
            "schema_version": 1,
            "market_id": market,
            "exhausted": True,
            "parked": [
                {
                    "ticker": "JBH.AX",
                    "reason": REASON_AWAITING_PERIODIC,
                    "filings_total": 2,
                    "filings_with_body": 2,
                    "indexed_without_body": 0,
                    "thin": True,
                }
            ],
        },
        compact=False,
    )
    payload = refresh_library_ingest_exhaustion(
        market,
        library_root=root,
        health=_health(thin=0, thin_tickers=[]),
        health_log_path=root / "markets" / market / "ingest_health_log.json",
    )
    assert payload["parked"] == []
    assert payload["exhausted"] is False


def test_evaluate_dispatch_exhausted_stops_sprint_keeps_maintenance():
    phase = {"phase3_ready": False, "blockers": []}
    health = overlay_exhaustion_on_health(
        _health(
            thin=2,
            iwb=15,
            thin_tickers=["JBH.AX", "DNL.AX"],
            iwb_tickers=["FICO"],
        ),
        {
            "exhausted": True,
            "parked": [{"ticker": "JBH.AX"}, {"ticker": "DNL.AX"}, {"ticker": "FICO"}],
        },
    )
    with (
        patch(
            "value_investor.library_ingest_dispatch.evaluate_market_phase",
            return_value=phase,
        ),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
    ):
        result = evaluate_euro_ingest_dispatch(market_id="sp500")
    assert result["mode"] == MODE_EXHAUSTED
    assert result["ingest_parity_met"] is False
    assert result["ingest_exhausted"] is True
    assert result["ingest_sprint_complete"] is True
    assert result["should_run_sprint_ingest"] is False
    assert result["should_run_maintenance_ingest"] is True
    assert result["should_run_ingest"] is False
    assert result["cron_maintenance"] is True
    assert result["max_targets"] == 62
    assert cron_enabled_for_dispatch(result)["morning"] is False
    assert cron_enabled_for_dispatch(result)["maintenance"] is True


def test_evaluate_dispatch_still_sprints_when_leftover_not_parked():
    phase = {"phase3_ready": False, "blockers": []}
    health = _health(thin=1, iwb=15, thin_tickers=["JBH.AX"], iwb_tickers=["FICO"])
    with (
        patch(
            "value_investor.library_ingest_dispatch.evaluate_market_phase",
            return_value=phase,
        ),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
    ):
        result = evaluate_euro_ingest_dispatch(market_id="sp500")
    assert result["mode"] == MODE_SPRINT
    assert result["should_run_sprint_ingest"] is True
    assert MODE_MAINTENANCE != result["mode"]


def test_maybe_advance_on_exhaustion_vacates_and_records_maintenance(tmp_path: Path):
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500", "asx200", "ftse_smallcap"],
        "ingest_parallel_sprint": ["sp500"],
        "ingest_parallel_sprint_2": ["asx200"],
        "ingest_parity_markets": ["euro_depth"],
        "ftse_equivalent_markets": ["sp500"],
        "focus_graduation": {"advance_parallel_sprint_on_ingest_parity": True},
    }
    exhausted = overlay_exhaustion_on_health(
        _health(iwb=15, iwb_tickers=["FICO"], iwb_by_ticker={"FICO": 15}),
        {"exhausted": True, "parked": [{"ticker": "FICO"}]},
    )
    sprint_health = _health(unmeasured=2, unmeasured_tickers=["AAA"])
    saved: dict = {}

    def _health_for(market_id: str, **_kwargs):
        if market_id == "sp500":
            return exhausted
        return sprint_health

    with (
        patch(
            "value_investor.library_ingest_maintenance.load_policy",
            return_value=dict(policy),
        ),
        patch(
            "value_investor.library_ingest_maintenance.save_policy",
            side_effect=lambda updated, _path: saved.update(updated),
        ),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            side_effect=_health_for,
        ),
        patch(
            "value_investor.library_ingest_dispatch.refresh_euro_ingest_dispatch",
            return_value={},
        ),
    ):
        event = maybe_advance_parallel_sprint_on_parity(
            market_id="sp500",
            library_root=tmp_path,
            policy_path=tmp_path / "policy.json",
            health=exhausted,
        )

    assert event["advanced"] is True
    assert event["to_market"] == "ftse_smallcap"
    assert event["parity_event"]["reason"] == "ingest_exhausted_leftover_gaps"
    assert event["parity_event"]["recorded"] is False
    assert event["parity_event"]["exhausted_maintenance_recorded"] is True
    assert "sp500" not in saved["ingest_parity_markets"]
    assert saved["ingest_exhausted_markets"] == ["sp500"]
    assert saved["ingest_parallel_sprint"] == ["ftse_smallcap"]


def test_outstanding_gap_closure_ignores_parked_iwb():
    health = overlay_exhaustion_on_health(
        _health(iwb=15, iwb_tickers=["FICO"], iwb_by_ticker={"FICO": 15}),
        {"exhausted": True, "parked": [{"ticker": "FICO"}]},
    )
    assert _library_outstanding_ingest_gaps(health) == 0


def test_filing_ready_excludes_parked_leftovers(tmp_path: Path):
    root = tmp_path / "library"
    policy = {"ftse_equivalent_markets": ["sp500"]}
    _write_index(root, "sp500", "AAPL", total=12, with_body=12)
    _write_index(root, "sp500", "FICO", total=19, with_body=14)
    reports = [_report("AAPL"), _report("FICO")]
    exhaustion = {
        "schema_version": 1,
        "market_id": "sp500",
        "exhausted": True,
        "parked": [{"ticker": "FICO", "reason": REASON_UNFETCHABLE_IWB}],
    }
    write_json(root / "markets" / "sp500" / "ingest_exhaustion.json", exhaustion, compact=False)
    with patch(
        "value_investor.library_ingest_loop.load_library_buy_tier_reports",
        return_value=reports,
    ):
        payload = assess_library_learning_depth(
            "sp500",
            library_root=root,
            policy=policy,
        )
    assert payload["filing"]["thin_body_buy_tier"] == 0
    assert payload["filing"]["indexed_without_body"] > 0
    assert payload["filing_ready"] is True
    assert payload["filing"]["ingest_parity_met"] is False
    assert payload["filing"]["ingest_exhausted"] is True


def test_select_targets_skips_parked_leftovers(tmp_path: Path):
    from value_investor.library_ingest_loop import select_library_ingest_targets

    root = tmp_path / "library"
    _write_index(root, "sp500", "FICO", total=19, with_body=14)
    _write_index(root, "sp500", "AAPL", total=0, with_body=0)
    write_json(
        root / "markets" / "sp500" / "ingest_exhaustion.json",
        {
            "schema_version": 1,
            "market_id": "sp500",
            "exhausted": True,
            "parked": [{"ticker": "FICO", "reason": REASON_UNFETCHABLE_IWB}],
        },
        compact=False,
    )
    targets = select_library_ingest_targets(
        [_report("FICO"), _report("AAPL")],
        library_root=root,
        market_id="sp500",
        max_targets=5,
        canonical_only=True,
    )
    assert [row.ticker for row in targets] == ["AAPL"]
    assert targets[0].reason == "unmeasured"


def test_paper_bundle_excludes_parked_tickers(tmp_path: Path):
    import pandas as pd

    from value_investor.market_paper_adapter import build_market_reports_bundle

    root = tmp_path / "library"
    screen_dir = root / "markets" / "sp500" / "screen"
    screen_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"ticker": "AAPL", "signal": "buy", "composite_score": 0.8, "last_price": 10.0},
            {"ticker": "FICO", "signal": "buy", "composite_score": 0.7, "last_price": 11.0},
        ]
    ).to_csv(screen_dir / "latest_signals.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "model_score": 0.8,
                "score": 0.8,
                "passed": True,
                "model_name": "value",
            },
            {
                "ticker": "FICO",
                "model_score": 0.7,
                "score": 0.7,
                "passed": True,
                "model_name": "value",
            },
        ]
    ).to_csv(screen_dir / "latest_model_results.csv", index=False)
    write_json(
        root / "markets" / "sp500" / "ingest_exhaustion.json",
        {"schema_version": 1, "market_id": "sp500", "parked": [{"ticker": "FICO"}]},
        compact=False,
    )
    bundle = build_market_reports_bundle(root, "sp500")
    tickers = [row["ticker"] for row in bundle["reports"]]
    assert "AAPL" in tickers
    assert "FICO" not in tickers
