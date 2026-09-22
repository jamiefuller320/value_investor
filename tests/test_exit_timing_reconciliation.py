"""Tests for live vs archive exit-timing denominator reconciliation (L121)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.exit_timing_reconciliation import (
    build_exit_timing_reconciliation,
    canonicalize_hold_close_reasons,
    write_exit_timing_reconciliation,
)
from value_investor.review_payload_slim import slim_exit_timing_reconciliation


def test_canonicalize_hold_close_reasons_maps_live_and_archive_labels():
    raw = {
        "sold_while_recovered": 2,
        "underwater_archive_end": 3,
        "recovered_max_window": 1,
    }
    canonical = canonicalize_hold_close_reasons(raw)
    assert canonical["recovered_at_close"] == 3
    assert canonical["not_recovered_at_close"] == 3


def test_build_reconciliation_flags_non_comparable_hold_populations(tmp_path: Path):
    paper = tmp_path / "paper_automation"
    rules = paper / "rules"
    rules.mkdir(parents=True)
    (rules / "exit_timing_cohorts_review.json").write_text(
        json.dumps(
            {
                "track_id": "rules",
                "readiness": {
                    "ready_for_probability_analysis": False,
                    "hold_closed_count": 7,
                    "swap_closed_count": 0,
                },
                "hold_recovery": {
                    "closed": {
                        "count": 7,
                        "recovered_to_breakeven": 3,
                        "close_reasons": {
                            "sold_while_recovered": 3,
                            "sold_while_underwater": 4,
                        },
                    }
                },
                "swap_rotation": {"closed": {"count": 0}},
            }
        ),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "exit_timing_near_miss_review.json").write_text(
        json.dumps(
            {
                "track_id": "archive_near_miss",
                "scope": "archive_near_miss",
                "readiness": {
                    "ready_for_probability_analysis": True,
                    "hold_closed_count": 20,
                    "swap_closed_count": 12,
                },
                "hold_recovery": {
                    "closed": {
                        "count": 20,
                        "recovered_to_breakeven": 14,
                        "close_reasons": {
                            "recovered_archive_end": 14,
                            "underwater_archive_end": 6,
                        },
                    }
                },
                "swap_rotation": {
                    "closed": {
                        "count": 12,
                        "verdicts": {"replacement_outperformed": 7},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    rec = build_exit_timing_reconciliation(paper_root=paper, data_dir=data_dir)
    comp = rec["comparability"]
    assert comp["hold_recovery_rates_directly_comparable"] is False
    assert comp["archive_may_inform_priors_while_live_collects"] is True
    assert comp["swap_rotation_rates_directly_comparable"] is False
    assert rec["sources"]["live_primary"]["hold_recovery"]["hold_recovery_rate"] == round(3 / 7, 4)

    written = write_exit_timing_reconciliation(paper_root=paper, data_dir=data_dir)
    assert (data_dir / "exit_timing_reconciliation.json").exists()
    slim = slim_exit_timing_reconciliation(written)
    assert slim is not None
    assert slim["comparability"]["blended_rate_narrative_allowed"] is True
