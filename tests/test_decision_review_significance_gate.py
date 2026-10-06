"""Decision-review apply is gated on statistically real active return (significance_gate_v1)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from value_investor.assessment_model import (
    ASSESSMENT_MODEL_FILENAME,
    apply_assessment_model,
    legacy_knob_apply_audit,
    policy_changes,
    record_policy_change,
)
from value_investor.decision_review import (
    APPLY_POLICY,
    GATE_CLOSED_BY_EVIDENCE,
    GATE_CLOSED_BY_STATISTICS,
    GATE_STARVED_TITLE,
    KNOB_EPOCH_FILENAME,
    REVIEW_HISTORY_FILENAME,
    TRACK_STATISTICS_MAX_AGE_DAYS,
    format_review_text,
    run_decision_review,
    significance_gate,
)
from value_investor.paper_automation import AutomationConfig, ensure_learning_track_configs
from value_investor.paper_fund import PaperFund, PaperFundConfig

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _stats(
    tmp_path: Path,
    *,
    verdict: str = "negative",
    status: str = "ok",
    updated_at: datetime | None = None,
    benchmark_ticker: str = "^FTSE",
    track_id: str = "rules",
) -> Path:
    path = tmp_path / "track_statistics.json"
    payload = {
        "updated_at": (updated_at or datetime.now(UTC)).isoformat(),
        "benchmark_ticker": benchmark_ticker,
        "tracks": {
            track_id: {
                "status": status,
                "verdict": verdict,
                "periods": 40,
                "ci_annualized_active_return": [-0.3, -0.05],
                "significant_after_correction": False,
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _churn_book(tmp_path: Path) -> tuple[Path, dict]:
    fund = PaperFund.create(
        PaperFundConfig(
            name="Auto", mode="automated", initial_cash=1000, trade_cost_pct=0.03, max_positions=5
        )
    )
    for i, ticker in enumerate(["AAA.L", "BBB.L", "CCC.L", "DDD.L"]):
        fund.buy(
            ticker=ticker,
            price=10,
            sizing_mode="cash",
            amount=200,
            sector="Banks",
            name=ticker,
            acted_at=f"2026-01-0{i + 1}T12:00:00+00:00",
        )
    for ticker in ["AAA.L", "BBB.L"]:
        fund.sell(
            ticker=ticker,
            price=9,
            sizing_mode="shares",
            amount=fund.holdings[ticker].shares,
            acted_at="2026-02-01T12:00:00+00:00",
        )
    for i in range(4):
        fund.record_mark(
            {t: 9.5 for t in fund.holdings},
            note=f"m{i}",
            acted_at=f"2026-03-0{i + 1}T12:00:00+00:00",
        )
    out = tmp_path / "paper"
    out.mkdir()
    config = AutomationConfig(
        max_positions=5, skip_timing_wait=True, min_conviction=0.0, sector_cap=0.5
    ).to_dict()
    (out / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (out / "automated_fund.json").write_text(json.dumps(fund.to_dict()), encoding="utf-8")
    return out, config


def test_gate_fails_closed_when_statistics_missing(tmp_path: Path):
    gate = significance_gate("rules", statistics_path=tmp_path / "nope.json", now=NOW)
    assert gate["passed"] is False
    assert gate["policy"] == APPLY_POLICY
    assert gate["closed_by"] == GATE_CLOSED_BY_STATISTICS
    assert "missing" in gate["reason"]


def test_gate_fails_closed_when_statistics_stale(tmp_path: Path):
    stale = NOW - timedelta(days=TRACK_STATISTICS_MAX_AGE_DAYS + 1)
    path = _stats(tmp_path, updated_at=stale)
    gate = significance_gate("rules", statistics_path=path, now=NOW)
    assert gate["passed"] is False
    assert "days old" in gate["reason"]


def test_gate_fails_closed_on_insufficient_data(tmp_path: Path):
    path = _stats(tmp_path, status="insufficient_data", verdict="", updated_at=NOW)
    gate = significance_gate("rules", statistics_path=path, now=NOW)
    assert gate["passed"] is False
    assert "insufficient_data" in gate["reason"]


def test_gate_fails_closed_for_unknown_track(tmp_path: Path):
    path = _stats(tmp_path, updated_at=NOW)
    gate = significance_gate("technical", statistics_path=path, now=NOW)
    assert gate["passed"] is False


def test_gate_fails_closed_when_indistinguishable_from_noise(tmp_path: Path):
    path = _stats(tmp_path, verdict="indistinguishable_from_noise", updated_at=NOW)
    gate = significance_gate("rules", statistics_path=path, now=NOW)
    assert gate["passed"] is False
    assert "noise" in gate["reason"]
    assert gate["verdict"] == "indistinguishable_from_noise"
    assert gate["closed_by"] == GATE_CLOSED_BY_EVIDENCE


def test_gate_fails_closed_on_benchmark_mismatch(tmp_path: Path):
    path = _stats(tmp_path, benchmark_ticker="^FTSE", updated_at=NOW)
    gate = significance_gate("rules", statistics_path=path, benchmark_ticker="^STOXX50E", now=NOW)
    assert gate["passed"] is False
    assert "^STOXX50E" in gate["reason"]


@pytest.mark.parametrize("verdict", ["positive", "negative"])
def test_gate_opens_on_significant_verdict(tmp_path: Path, verdict: str):
    path = _stats(tmp_path, verdict=verdict, updated_at=NOW)
    gate = significance_gate("rules", statistics_path=path, benchmark_ticker="^FTSE", now=NOW)
    assert gate["passed"] is True
    assert gate["closed_by"] is None
    assert gate["ci_annualized_active_return"] == [-0.3, -0.05]


@pytest.mark.parametrize("force", [False, True])
def test_closed_gate_keeps_config_and_epoch_even_when_forced(tmp_path: Path, force: bool):
    out, config_before = _churn_book(tmp_path)
    path = _stats(tmp_path, verdict="indistinguishable_from_noise")
    result = run_decision_review(
        output_dir=out,
        apply=True,
        force=force,
        fetch_benchmark=False,
        benchmark_return=0.05,
        statistics_path=path,
    )
    assert result.proposed_changes, "fixture must produce a proposal"
    assert result.applied is False
    assert "significance gate closed" in result.note
    assert result.knobs_after == result.knobs_before
    assert json.loads((out / "config.json").read_text(encoding="utf-8")) == config_before
    assert not (out / KNOB_EPOCH_FILENAME).exists()
    row = json.loads((out / REVIEW_HISTORY_FILENAME).read_text(encoding="utf-8"))[-1]
    assert row["apply_policy"] == APPLY_POLICY
    assert row["significance_gate"]["passed"] is False
    assert "Significance gate (significance_gate_v1): closed" in format_review_text(result)


def test_open_gate_applies(tmp_path: Path):
    out, config_before = _churn_book(tmp_path)
    result = run_decision_review(
        output_dir=out,
        apply=True,
        fetch_benchmark=False,
        benchmark_return=0.05,
        statistics_path=_stats(tmp_path, verdict="negative"),
    )
    assert result.proposed_changes
    assert result.applied is True
    assert result.significance_gate["passed"] is True
    assert json.loads((out / "config.json").read_text(encoding="utf-8")) != config_before
    assert (out / KNOB_EPOCH_FILENAME).exists()


def test_propose_only_review_records_gate_without_applying(tmp_path: Path):
    out, config_before = _churn_book(tmp_path)
    result = run_decision_review(
        output_dir=out,
        apply=False,
        fetch_benchmark=False,
        benchmark_return=0.05,
        statistics_path=_stats(tmp_path, verdict="negative"),
    )
    assert result.applied is False
    assert result.significance_gate["passed"] is True
    assert json.loads((out / "config.json").read_text(encoding="utf-8")) == config_before


def test_record_policy_change_is_idempotent_and_survives_model_switch(tmp_path: Path):
    base = tmp_path / "auto"
    ensure_learning_track_configs(base)
    (base / "decision_review_history.json").write_text(
        json.dumps(
            [
                {"reviewed_at": "2026-08-01", "applied": True, "proposed_changes": {"a": 1}},
                {"reviewed_at": "2026-08-02", "applied": False, "proposed_changes": {"a": 1}},
                {"reviewed_at": "2026-08-03", "applied": True, "proposed_changes": {}},
                {"reviewed_at": "2026-08-04", "applied": True, "proposed_changes": {"b": 2}},
            ]
        ),
        encoding="utf-8",
    )
    audit = legacy_knob_apply_audit(base)
    assert audit["rules"] == {
        "reviews": 4,
        "applied_knob_changes": 2,
        "first_applied_at": "2026-08-01",
        "last_applied_at": "2026-08-04",
    }
    assert audit["ai_judgment"]["applied_knob_changes"] == 0

    first = record_policy_change(
        base,
        policy_id=APPLY_POLICY,
        summary="gate",
        history_note="before is legacy",
        audit=audit,
        now=NOW,
    )
    again = record_policy_change(
        base, policy_id=APPLY_POLICY, summary="other", history_note="other", now=NOW
    )
    assert again == first
    assert [row["id"] for row in policy_changes(base)] == [APPLY_POLICY]

    apply_assessment_model(
        base, primary="ai_judgment", control="rules", freeze={}, reason="noop", now=NOW
    )
    model = json.loads((base / ASSESSMENT_MODEL_FILENAME).read_text(encoding="utf-8"))
    assert [row["id"] for row in model["policy_changes"]] == [APPLY_POLICY]


def _review_with_gate(root: Path, gate: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {"benchmark_ticker": "^FTSE", "reviews": {"rules": {"significance_gate": gate}}}
    (root / "learning_tracks_review.json").write_text(json.dumps(payload), encoding="utf-8")


def test_ops_check_warns_when_store_still_unusable(tmp_path: Path):
    from value_investor.ops_monitor import check_decision_review_significance_gate

    root = tmp_path / "paper"
    gate = significance_gate("rules", statistics_path=tmp_path / "missing.json", now=NOW)
    _review_with_gate(root, gate)
    findings = check_decision_review_significance_gate(
        paper_root=root, statistics_path=tmp_path / "missing.json", now=NOW
    )
    assert [f.title for f in findings] == [GATE_STARVED_TITLE]
    assert findings[0].auto_fixable is False
    assert "rules" in findings[0].summary


def test_ops_check_quiet_once_store_refreshed(tmp_path: Path):
    from value_investor.ops_monitor import check_decision_review_significance_gate

    root = tmp_path / "paper"
    _review_with_gate(
        root, significance_gate("rules", statistics_path=tmp_path / "missing.json", now=NOW)
    )
    fresh = _stats(tmp_path, verdict="indistinguishable_from_noise", updated_at=NOW)
    assert (
        check_decision_review_significance_gate(paper_root=root, statistics_path=fresh, now=NOW)
        == []
    )


def test_ops_check_quiet_when_gate_closed_on_evidence(tmp_path: Path):
    from value_investor.ops_monitor import check_decision_review_significance_gate

    root = tmp_path / "paper"
    path = _stats(tmp_path, verdict="indistinguishable_from_noise", updated_at=NOW)
    gate = significance_gate("rules", statistics_path=path, now=NOW)
    assert gate["closed_by"] == GATE_CLOSED_BY_EVIDENCE
    _review_with_gate(root, gate)
    stale_now = NOW + timedelta(days=30)
    assert (
        check_decision_review_significance_gate(
            paper_root=root, statistics_path=path, now=stale_now
        )
        == []
    )
