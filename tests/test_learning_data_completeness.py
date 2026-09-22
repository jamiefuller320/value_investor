"""Learning data completeness score."""

from __future__ import annotations

from value_investor.learning_data_completeness import compute_learning_data_completeness


def test_completeness_score_penalizes_high_flags():
    snapshot = {
        "assessed_at": "2026-09-21T12:00:00+00:00",
        "flag_count": 2,
        "high_flag_count": 2,
        "layers": {
            "apply": {
                "buy_tier_count": 10,
                "buy_tier_wired_count": 10,
                "strong_buy_count": 2,
                "strong_buy_wired_count": 2,
            },
            "publish": {"research_index_count": 50, "index_missing_committed_verdicts": 0},
            "produce": {
                "live_committed": {
                    "committed_count": 40,
                    "committed_with_verdict": 40,
                    "thin_or_zero_body": 0,
                }
            },
        },
    }
    good = compute_learning_data_completeness(snapshot)
    assert good["score"] is not None
    assert good["score"] >= 75

    snapshot["high_flag_count"] = 4
    snapshot["flag_count"] = 4
    weak = compute_learning_data_completeness(snapshot)
    assert weak["score"] < good["score"]


def test_system_gap_findings_in_so_what_scan(tmp_path):
    from value_investor.so_what_closure import CLOSURE_HUMAN_GATE, scan_so_what_issues
    from value_investor.storage import write_json

    data = tmp_path / "docs/data"
    data.mkdir(parents=True)
    write_json(
        data / "system_gaps.json",
        {
            "flags": [
                {
                    "id": "research_skipped_already_done",
                    "severity": "high",
                    "layer": "produce",
                    "title": "Research skipped",
                    "summary": "executed=0",
                }
            ]
        },
    )
    write_json(data / "latest.json", {"reports": []})
    write_json(data / "engineering_tasks.json", {"tasks": []})

    findings = scan_so_what_issues(
        reports=[],
        latest_path=data / "latest.json",
        artifacts_dir=data,
        tasks_path=data / "engineering_tasks.json",
    )
    kinds = {f.kind for f in findings}
    assert "system_gap_research_skipped_already_done" in kinds
    gap = next(f for f in findings if f.kind.startswith("system_gap_"))
    assert gap.recommended_closure == CLOSURE_HUMAN_GATE
