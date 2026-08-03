"""Tests for engineering PR email notifications."""

from __future__ import annotations

from unittest.mock import patch

from value_investor.engineering_pr_notify import (
    EngineeringPrNotification,
    collect_queue_block_alerts,
    format_engineering_pr_text,
    send_engineering_pr_email,
    send_engineering_queue_block_email,
)


def test_format_engineering_pr_text_includes_ci_backup_without_pat():
    note = EngineeringPrNotification(
        task_id="eng-20260802-02",
        branch="cursor/eng-20260802-02-1de3",
        pr_url="https://github.com/example/pull/165",
        pr_number=165,
        is_draft=True,
        auto_merge=False,
        used_pat=False,
    )
    text = format_engineering_pr_text(note)
    assert "action_required" in text
    assert "Draft: yes" in text


def test_format_engineering_pr_text_omits_ci_backup_when_pat_used():
    note = EngineeringPrNotification(
        task_id="eng-20260802-02",
        branch="cursor/eng-20260802-02-1de3",
        pr_url="https://github.com/example/pull/165",
        pr_number=165,
        is_draft=False,
        auto_merge=True,
        used_pat=True,
    )
    text = format_engineering_pr_text(note)
    assert "action_required" not in text
    assert "Auto-merge eligible: yes" in text


@patch("value_investor.engineering_pr_notify.send_email")
def test_send_engineering_pr_email(mock_send):
    note = EngineeringPrNotification(
        task_id="eng-20260802-02",
        branch="cursor/eng-20260802-02-1de3",
        pr_url="https://github.com/example/pull/165",
        pr_number=165,
        is_draft=True,
        auto_merge=False,
        used_pat=False,
    )
    with patch("value_investor.engineering_pr_notify.EmailConfig.from_env") as mock_cfg:
        mock_cfg.return_value = object()
        assert send_engineering_pr_email(note) is True
    mock_send.assert_called_once()


def test_collect_queue_block_alerts_spend_blocked():
    alerts = collect_queue_block_alerts(
        dispatch={
            "reason": "ad-hoc spend checkpoint reached ($60.00 / $60.00)",
            "status": {
                "open_count": 2,
                "spend_blocked": True,
                "spend_since_checkpoint_usd": 60.0,
                "spend_checkpoint_usd": 60.0,
            },
        }
    )
    assert len(alerts) == 1
    assert alerts[0].kind == "spend_blocked"


def test_collect_queue_block_alerts_orphan_and_parked():
    alerts = collect_queue_block_alerts(
        recovery={
            "reconciled": ["eng-20260802-01"],
            "parked": [
                {
                    "task_id": "eng-20260802-02",
                    "reason": "draft PR #170 checks still failing",
                }
            ],
        }
    )
    kinds = {row.kind for row in alerts}
    assert kinds == {"orphan_reconcile", "task_parked"}


def test_collect_queue_block_alerts_agent_failure():
    alerts = collect_queue_block_alerts(
        sync={"recent_agent_failures": 2},
        dispatch={"status": {"open_count": 3, "in_flight_pr": None}},
    )
    assert alerts[0].kind == "agent_failure"


def test_collect_queue_block_alerts_idle_queue_empty():
    alerts = collect_queue_block_alerts(
        dispatch={
            "reason": "no open engineering tasks in queue",
            "status": {"open_count": 0, "spend_blocked": False},
        }
    )
    assert alerts == []


@patch("value_investor.engineering_pr_notify.send_email")
def test_send_engineering_queue_block_email(mock_send):
    alerts = collect_queue_block_alerts(
        recovery={"reconciled": ["eng-20260802-01"]},
    )
    with patch("value_investor.engineering_pr_notify.EmailConfig.from_env") as mock_cfg:
        mock_cfg.return_value = object()
        assert send_engineering_queue_block_email(alerts) is True
    mock_send.assert_called_once()
