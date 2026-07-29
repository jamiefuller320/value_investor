"""Regression tests for --json and shared flags after subcommands."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from value_investor.analysis_review_cli import main as analysis_main
from value_investor.data_backup_cli import main as backup_main
from value_investor.data_library_cli import main as library_main
from value_investor.deferred_ideas_cli import main as defer_main
from value_investor.engineering_cli import main as engineering_main
from value_investor.ingest_loop_cli import main as ingest_main
from value_investor.ingest_loop import IngestLoopResult
from value_investor.ops_monitor import OpsMonitorReport
from value_investor.ops_monitor_cli import main as ops_main


def test_engineering_cli_accepts_json_after_subcommand():
    with patch("value_investor.engineering_cli.load_engineering_tasks", return_value={"tasks": []}):
        with patch("sys.stdout", StringIO()):
            assert engineering_main(["list", "--json"]) == 0


def test_engineering_cli_accepts_json_before_subcommand():
    with patch("value_investor.engineering_cli.load_engineering_tasks", return_value={"tasks": []}):
        with patch("sys.stdout", StringIO()):
            assert engineering_main(["--json", "list"]) == 0


def test_engineering_cli_accepts_shared_flags_after_subcommand():
    with patch("value_investor.engineering_cli.load_engineering_tasks", return_value={"tasks": []}) as mock_load:
        with patch("sys.stdout", StringIO()):
            assert engineering_main(["list", "--json", "--tasks-path", "docs/data/engineering_tasks.json"]) == 0
        mock_load.assert_called_once()
        assert mock_load.call_args.args[0] == Path("docs/data/engineering_tasks.json")


def test_library_cli_accepts_root_after_subcommand():
    with patch("value_investor.data_library_cli.library_status", return_value={"markets": []}) as mock_status:
        with patch("sys.stdout", StringIO()):
            assert library_main(["status", "--json", "--root", "docs/data/library"]) == 0
        assert mock_status.call_args.args[0] == Path("docs/data/library")


def test_library_cli_accepts_root_before_subcommand():
    with patch("value_investor.data_library_cli.list_markets", return_value=[]):
        with patch("sys.stdout", StringIO()):
            assert library_main(["--root", "docs/data/library", "list"]) == 0


def test_data_backup_cli_accepts_snapshot_json_after_subcommand(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    paper = repo / "docs/data/paper_automation"
    paper.mkdir(parents=True)
    (paper / "state.json").write_text("{}", encoding="utf-8")

    mock_snapshot = MagicMock()
    mock_snapshot.to_dict.return_value = {"archive_path": "out.tar.gz"}
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        "value_investor.data_backup_cli.create_backup_snapshot",
        lambda **kwargs: mock_snapshot,
    )
    with patch("sys.stdout", StringIO()):
        assert backup_main(["snapshot", "--json", "--backup-dir", str(tmp_path / "backups")]) == 0


def test_ingest_loop_cli_accepts_run_json_after_subcommand():
    result = IngestLoopResult(
        health_before={"zero_body_buy_tier": 2},
        health_after={"zero_body_buy_tier": 1},
        ingest_summary=None,
        micro_compiled=False,
    )
    with patch("value_investor.ingest_loop_cli.run_weekday_ingest_loop", return_value=result):
        with patch("sys.stdout", StringIO()):
            assert ingest_main(["run", "--json", "--max-targets", "2"]) == 0


def test_ops_monitor_cli_accepts_run_json_after_subcommand():
    with patch("value_investor.ops_monitor_cli.run_ops_monitor") as mock_run:
        mock_run.return_value = OpsMonitorReport(
            run_at="2026-07-29T00:00:00+00:00",
            overall="ok",
        )
        with patch("value_investor.ops_monitor_cli.append_monitor_log_entry"):
            with patch("sys.stdout", StringIO()):
                assert ops_main(["run", "--json", "--no-apply", "--no-draft"]) == 0


def test_deferred_ideas_cli_accepts_list_json_after_subcommand():
    with patch("value_investor.deferred_ideas_cli.load_store", return_value={"ideas": []}):
        with patch("sys.stdout", StringIO()):
            assert defer_main(["list", "--json"]) == 0


def test_engineering_check_pr_paths_skips_non_engineering_branch(tmp_path: Path):
    changed = tmp_path / "changed.txt"
    changed.write_text("docs/paper_sims.js\n", encoding="utf-8")
    with patch("sys.stdout", StringIO()):
        assert (
            engineering_main(
                [
                    "check-pr-paths",
                    "--branch",
                    "cursor/cli-audit-unrealized-pnl-f028",
                    "--changed-files",
                    str(changed),
                ]
            )
            == 0
        )


def test_analysis_review_cli_accepts_payload_json_after_subcommand():
    with patch(
        "value_investor.analysis_review_cli.build_analysis_payload",
        return_value={"history_run_count": 0},
    ):
        with patch(
            "value_investor.analysis_review_cli.has_enough_analysis_inputs",
            return_value=(True, "ok"),
        ):
            with patch("sys.stdout", StringIO()):
                assert analysis_main(["payload", "--json", "--allow-thin"]) == 0
