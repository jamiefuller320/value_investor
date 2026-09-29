"""UI ↔ system-state reconciliation builder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.storage import write_json
from value_investor.ui_state_reconciliation import (
    FINDING_TITLE,
    build_ui_state_reconciliation,
    ops_finding_from_reconciliation,
    write_ui_state_reconciliation,
)


def _seed(data_dir: Path, *, dual: dict | None, board_age_hours: float = 1.0) -> None:
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "progress_report.json",
        {"schema_version": 1, "generated_at": now.isoformat()},
        compact=False,
    )
    write_json(
        data_dir / "latest.json",
        {
            "learning_tracks_dual_suite": dual,
            "paper_automation": {"learning_tracks_review": {"tracks": [{"id": "x"}]}},
        },
        compact=False,
    )
    write_json(
        data_dir / "human_tasks_board.json",
        {
            "tasks": [
                {
                    "id": "t1",
                    "analysis": {"fingerprint": "aaaaaaaaaaaaaaaa"},
                    "ack": {"acked": True, "stale": False},
                }
            ]
        },
        compact=False,
    )
    write_json(
        data_dir / "human_task_acks.json",
        {
            "acks": [
                {
                    "task_id": "t1",
                    "status": "open",
                    "finding_fingerprint": "aaaaaaaaaaaaaaaa",
                }
            ]
        },
        compact=False,
    )
    board_at = now - timedelta(hours=board_age_hours)
    write_json(
        data_dir / "lifecycle_board.json",
        {"generated_at": board_at.isoformat()},
        compact=False,
    )


def test_reconciliation_ok_when_artifacts_healthy(tmp_path: Path) -> None:
    _seed(tmp_path, dual={"suite_a": {}, "suite_b": {}})
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        tmp_path / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
        },
        compact=False,
    )
    payload = build_ui_state_reconciliation(data_dir=tmp_path, now=now)
    assert payload["overall"] == "ok"
    assert payload["surface_freshness"] == "fresh"
    assert payload["summary"]["ok"] >= 3
    assert ops_finding_from_reconciliation(payload) is None
    ids = {c["id"] for c in payload["checks"]}
    assert "progress_report_vs_email_overlay" in ids
    assert "learning_tracks_dual_suite_present" in ids
    assert "human_task_ack_fp_stable" in ids
    assert "lifecycle_board_age" in ids
    assert "daily_hub_local_date_matches_today" in ids


def test_daily_hub_local_date_warns_after_deadline(tmp_path: Path) -> None:
    _seed(tmp_path, dual={"suite_a": {}})
    # 05:00 UTC on 29 Sep ≈ 06:00 BST — past 04:00 London deadline.
    now = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)
    write_json(
        tmp_path / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": "2026-09-28T22:32:36Z",
            "stale_for_local_date": False,
        },
        compact=False,
    )
    payload = build_ui_state_reconciliation(data_dir=tmp_path, now=now)
    check = next(c for c in payload["checks"] if c["id"] == "daily_hub_local_date_matches_today")
    assert check["status"] == "warn"
    assert check["drift_class"] == "stale_surface"
    assert payload["overall"] == "warn"


def test_dual_suite_publish_lag_warns(tmp_path: Path) -> None:
    _seed(tmp_path, dual=None)
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    payload = build_ui_state_reconciliation(data_dir=tmp_path, now=now)
    assert payload["overall"] == "warn"
    dual = next(c for c in payload["checks"] if c["id"] == "learning_tracks_dual_suite_present")
    assert dual["status"] == "warn"
    assert dual["drift_class"] == "publish_lag"
    finding = ops_finding_from_reconciliation(payload)
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False
    assert finding["category"] == "dashboard_health"


def test_lifecycle_board_stale_warns(tmp_path: Path) -> None:
    _seed(tmp_path, dual={"suite_a": {}}, board_age_hours=40.0)
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    payload = build_ui_state_reconciliation(data_dir=tmp_path, now=now)
    life = next(c for c in payload["checks"] if c["id"] == "lifecycle_board_age")
    assert life["status"] == "warn"
    assert life["drift_class"] == "publish_lag"


def test_write_ui_state_reconciliation_persists(tmp_path: Path) -> None:
    _seed(tmp_path, dual={"suite_a": {}})
    payload = write_ui_state_reconciliation(data_dir=tmp_path)
    stored = (tmp_path / "ui_state_reconciliation.json").read_text(encoding="utf-8")
    assert '"schema_version": 1' in stored
    assert payload["generated_at"]
