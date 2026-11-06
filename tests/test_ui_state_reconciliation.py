"""UI ↔ system-state reconciliation builder."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.storage import write_json
from value_investor.ui_state_reconciliation import (
    FINDING_TITLE,
    build_ui_state_reconciliation,
    ops_finding_from_reconciliation,
    write_ui_state_reconciliation,
)


def _docs_data_dir(tmp_root: Path) -> Path:
    d = tmp_root / "docs" / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _copy_v2_shell(tmp_root: Path) -> None:
    repo_docs = Path(__file__).resolve().parent.parent / "docs"
    repo_docs_v2 = repo_docs / "v2"
    dst = tmp_root / "docs" / "v2"
    if not dst.exists():
        shutil.copytree(repo_docs_v2, dst)
    # index.html references `../dashboard_bridge.js` and v2 scripts load `../human_tasks_checklist.json`.
    for name in ("dashboard_bridge.js", "human_tasks_checklist.json"):
        src = repo_docs / name
        out = tmp_root / "docs" / name
        if not out.is_file():
            shutil.copy2(src, out)


def _seed_v2_today_stores(data_dir: Path, *, now: datetime, replay_day: str | None = None) -> None:
    """Minimal JSON so dashboard_v2_stores_present_and_fresh stays ok."""
    day = replay_day or now.date().isoformat()
    write_json(
        data_dir / "strategy_book_registration.json",
        {"schema_version": 1, "generated_at": now.isoformat()},
        compact=False,
    )
    write_json(
        data_dir / "market_status.json",
        {"schema_version": 1, "generated_at": now.isoformat()},
        compact=False,
    )
    write_json(
        data_dir / "ops_status.json",
        {"schema_version": 1, "run_at": now.isoformat()},
        compact=False,
    )
    write_json(
        data_dir / "total_return_view.json",
        {"schema_version": 1, "generated_at": now.isoformat()},
        compact=False,
    )
    write_json(
        data_dir / "assessment_scoreboard.json",
        {"schema_version": 1, "generated_at": now.isoformat()},
        compact=False,
    )
    (data_dir / "strategy_book_replay_episodes.json.gz").write_bytes(b"")
    write_json(
        data_dir / "strategy_book_memo_job.json",
        {"schema_version": 1, "generated_at": now.isoformat()},
        compact=False,
    )
    write_json(
        data_dir / "operating_decline_gate.json",
        {"schema_version": 1, "generated_at": now.isoformat(), "as_of": day},
        compact=False,
    )
    write_json(
        data_dir / "sector_headwind_gate.json",
        {"schema_version": 1, "generated_at": now.isoformat(), "as_of": day},
        compact=False,
    )
    write_json(
        data_dir / "decision_input_inventory.json",
        {"schema_version": 1, "generated_at": now.isoformat()},
        compact=False,
    )
    write_json(
        data_dir / "library_decision_input_inventory.json",
        {"schema_version": 1, "generated_at": now.isoformat(), "as_of": now.isoformat()},
        compact=False,
    )
    write_json(
        data_dir / "strategy_book_replay.json",
        {
            "archive_buy_tier_only": {"scoring_date": day},
            "archive_full_strategy": {"scoring_date": day},
            "lookahead_current_gates": {"scoring_date": day},
        },
        compact=False,
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
    data_dir = _docs_data_dir(tmp_path)
    _copy_v2_shell(tmp_path)
    _seed(data_dir, dual={"suite_a": {}, "suite_b": {}})
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "human_tasks_board.json",
        {
            "schema_version": 1,
            "generated_at": now.isoformat(),
            "tasks": [
                {
                    "id": "t1",
                    "analysis": {"fingerprint": "aaaaaaaaaaaaaaaa"},
                    "ack": {"acked": True, "stale": False},
                }
            ],
        },
        compact=False,
    )
    write_json(
        data_dir / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
        },
        compact=False,
    )
    _seed_v2_today_stores(data_dir, now=now, replay_day="2026-09-28")
    payload = build_ui_state_reconciliation(data_dir=data_dir, now=now)
    assert payload["overall"] == "ok"
    assert payload["surface_freshness"] == "fresh"
    assert payload["summary"]["ok"] >= 5
    assert ops_finding_from_reconciliation(payload) is None
    ids = {c["id"] for c in payload["checks"]}
    assert "progress_report_vs_email_overlay" in ids
    assert "learning_tracks_dual_suite_present" in ids
    assert "human_task_ack_fp_stable" in ids
    assert "lifecycle_board_age" in ids
    assert "daily_hub_local_date_matches_today" in ids
    assert "dashboard_v2_stores_present_and_fresh" in ids


def test_daily_hub_local_date_warns_after_deadline(tmp_path: Path) -> None:
    data_dir = _docs_data_dir(tmp_path)
    _copy_v2_shell(tmp_path)
    _seed(data_dir, dual={"suite_a": {}})
    now_warn = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "human_tasks_board.json",
        {
            "schema_version": 1,
            "generated_at": now_warn.isoformat(),
            "tasks": [
                {
                    "id": "t1",
                    "analysis": {"fingerprint": "aaaaaaaaaaaaaaaa"},
                    "ack": {"acked": True, "stale": False},
                }
            ],
        },
        compact=False,
    )
    _seed_v2_today_stores(data_dir, now=now_warn, replay_day="2026-09-28")
    # 05:00 UTC on 29 Sep ≈ 06:00 BST — past 04:00 London deadline.
    now = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)
    write_json(
        data_dir / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": "2026-09-28T22:32:36Z",
            "stale_for_local_date": False,
        },
        compact=False,
    )
    payload = build_ui_state_reconciliation(data_dir=data_dir, now=now)
    check = next(c for c in payload["checks"] if c["id"] == "daily_hub_local_date_matches_today")
    assert check["status"] == "warn"
    assert check["drift_class"] == "stale_surface"
    assert payload["overall"] == "warn"


def test_dual_suite_publish_lag_warns(tmp_path: Path) -> None:
    data_dir = _docs_data_dir(tmp_path)
    _copy_v2_shell(tmp_path)
    _seed(data_dir, dual=None)
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "human_tasks_board.json",
        {
            "schema_version": 1,
            "generated_at": now.isoformat(),
            "tasks": [
                {
                    "id": "t1",
                    "analysis": {"fingerprint": "aaaaaaaaaaaaaaaa"},
                    "ack": {"acked": True, "stale": False},
                }
            ],
        },
        compact=False,
    )
    write_json(
        data_dir / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
        },
        compact=False,
    )
    _seed_v2_today_stores(data_dir, now=now, replay_day="2026-09-28")
    payload = build_ui_state_reconciliation(data_dir=data_dir, now=now)
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
    data_dir = _docs_data_dir(tmp_path)
    _copy_v2_shell(tmp_path)
    _seed(data_dir, dual={"suite_a": {}}, board_age_hours=40.0)
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "human_tasks_board.json",
        {
            "schema_version": 1,
            "generated_at": now.isoformat(),
            "tasks": [
                {
                    "id": "t1",
                    "analysis": {"fingerprint": "aaaaaaaaaaaaaaaa"},
                    "ack": {"acked": True, "stale": False},
                }
            ],
        },
        compact=False,
    )
    write_json(
        data_dir / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
        },
        compact=False,
    )
    _seed_v2_today_stores(data_dir, now=now, replay_day="2026-09-28")
    payload = build_ui_state_reconciliation(data_dir=data_dir, now=now)
    life = next(c for c in payload["checks"] if c["id"] == "lifecycle_board_age")
    assert life["status"] == "warn"
    assert life["drift_class"] == "publish_lag"


def test_write_ui_state_reconciliation_persists(tmp_path: Path) -> None:
    data_dir = _docs_data_dir(tmp_path)
    _copy_v2_shell(tmp_path)
    _seed(data_dir, dual={"suite_a": {}})
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "human_tasks_board.json",
        {
            "schema_version": 1,
            "generated_at": now.isoformat(),
            "tasks": [
                {
                    "id": "t1",
                    "analysis": {"fingerprint": "aaaaaaaaaaaaaaaa"},
                    "ack": {"acked": True, "stale": False},
                }
            ],
        },
        compact=False,
    )
    write_json(
        data_dir / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
        },
        compact=False,
    )
    _seed_v2_today_stores(data_dir, now=now, replay_day="2026-09-28")
    payload = write_ui_state_reconciliation(data_dir=data_dir)
    stored = (data_dir / "ui_state_reconciliation.json").read_text(encoding="utf-8")
    assert '"schema_version": 1' in stored
    assert payload["generated_at"]


def test_dashboard_v2_missing_required_store_warns(tmp_path: Path) -> None:
    data_dir = _docs_data_dir(tmp_path)
    _copy_v2_shell(tmp_path)
    _seed(data_dir, dual={"suite_a": {}, "suite_b": {}})
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "human_tasks_board.json",
        {"schema_version": 1, "generated_at": now.isoformat(), "tasks": []},
        compact=False,
    )
    write_json(
        data_dir / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
        },
        compact=False,
    )
    _seed_v2_today_stores(data_dir, now=now, replay_day="2026-09-28")
    (data_dir / "decision_input_inventory.json").unlink()
    payload = build_ui_state_reconciliation(data_dir=data_dir, now=now)
    v2 = next(c for c in payload["checks"] if c["id"] == "dashboard_v2_stores_present_and_fresh")
    assert v2["status"] == "warn"
    det = v2["details"]
    assert "../data/decision_input_inventory.json" in det["missing_stores"]
    assert any(
        s["store"] == "decision_input_inventory.json" and s["reason"] == "missing file"
        for s in det["stale_stores"]
    )
    assert "missing stores" in v2["detail"]


def test_dashboard_v2_optional_forward_missing_ok(tmp_path: Path) -> None:
    data_dir = _docs_data_dir(tmp_path)
    _copy_v2_shell(tmp_path)
    _seed(data_dir, dual={"suite_a": {}, "suite_b": {}})
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "human_tasks_board.json",
        {"schema_version": 1, "generated_at": now.isoformat(), "tasks": []},
        compact=False,
    )
    write_json(
        data_dir / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
        },
        compact=False,
    )
    _seed_v2_today_stores(data_dir, now=now, replay_day="2026-09-28")
    (data_dir / "strategy_book_forward_status.json").unlink(missing_ok=True)
    payload = build_ui_state_reconciliation(data_dir=data_dir, now=now)
    v2 = next(c for c in payload["checks"] if c["id"] == "dashboard_v2_stores_present_and_fresh")
    assert v2["status"] == "ok"
    assert v2["details"]["missing_stores"] == []


def test_dashboard_v2_stale_store_warns(tmp_path: Path) -> None:
    data_dir = _docs_data_dir(tmp_path)
    _copy_v2_shell(tmp_path)
    _seed(data_dir, dual={"suite_a": {}, "suite_b": {}})
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "human_tasks_board.json",
        {"schema_version": 1, "generated_at": now.isoformat(), "tasks": []},
        compact=False,
    )
    write_json(
        data_dir / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
        },
        compact=False,
    )
    stale_at = now - timedelta(hours=40)
    _seed_v2_today_stores(data_dir, now=stale_at, replay_day="2026-09-20")
    payload = build_ui_state_reconciliation(data_dir=data_dir, now=now)
    v2 = next(c for c in payload["checks"] if c["id"] == "dashboard_v2_stores_present_and_fresh")
    assert v2["status"] == "warn"
    stale = v2["details"]["stale_stores"]
    assert any(
        s["store"] == "strategy_book_memo_job.json" and s["reason"] == "stale" for s in stale
    )


def test_dashboard_v2_missing_date_warns(tmp_path: Path) -> None:
    data_dir = _docs_data_dir(tmp_path)
    _copy_v2_shell(tmp_path)
    _seed(data_dir, dual={"suite_a": {}, "suite_b": {}})
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "human_tasks_board.json",
        {"schema_version": 1, "generated_at": now.isoformat(), "tasks": []},
        compact=False,
    )
    write_json(
        data_dir / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
        },
        compact=False,
    )
    _seed_v2_today_stores(data_dir, now=now, replay_day="2026-09-28")
    write_json(data_dir / "sector_headwind_gate.json", {"schema_version": 1}, compact=False)
    payload = build_ui_state_reconciliation(data_dir=data_dir, now=now)
    v2 = next(c for c in payload["checks"] if c["id"] == "dashboard_v2_stores_present_and_fresh")
    assert v2["status"] == "warn"
    assert any(
        s["store"] == "sector_headwind_gate.json" and s["reason"] == "date missing"
        for s in v2["details"]["stale_stores"]
    )


def test_dashboard_v2_missing_script_warns(tmp_path: Path) -> None:
    data_dir = _docs_data_dir(tmp_path)
    _copy_v2_shell(tmp_path)
    (tmp_path / "docs" / "v2" / "proof.js").unlink()
    _seed(data_dir, dual={"suite_a": {}, "suite_b": {}})
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        data_dir / "human_tasks_board.json",
        {"schema_version": 1, "generated_at": now.isoformat(), "tasks": []},
        compact=False,
    )
    write_json(
        data_dir / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
        },
        compact=False,
    )
    _seed_v2_today_stores(data_dir, now=now, replay_day="2026-09-28")
    payload = build_ui_state_reconciliation(data_dir=data_dir, now=now)
    v2 = next(c for c in payload["checks"] if c["id"] == "dashboard_v2_stores_present_and_fresh")
    assert v2["status"] == "warn"
    assert "proof.js" in "".join(v2["details"]["missing_page_assets"])


def test_dashboard_v2_check_skipped_outside_docs_tree(tmp_path: Path) -> None:
    payload = build_ui_state_reconciliation(
        data_dir=tmp_path, now=datetime(2026, 11, 6, 9, tzinfo=UTC)
    )
    assert all(c["id"] != "dashboard_v2_stores_present_and_fresh" for c in payload["checks"])
