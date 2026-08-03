"""Tests for engineering PR email notifications."""

from __future__ import annotations

from unittest.mock import patch

from value_investor.engineering_pr_notify import (
    EngineeringPrNotification,
    format_engineering_pr_text,
    send_engineering_pr_email,
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
