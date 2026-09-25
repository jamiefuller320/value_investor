"""L468: ops-monitor light lifecycle_board refresh before maturity twin."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.ops_monitor import check_lifecycle_maturity_trajectory


def test_check_lifecycle_maturity_refreshes_board_when_persisting(tmp_path: Path) -> None:
    board = tmp_path / "lifecycle_board.json"
    store = tmp_path / "lifecycle_maturity_trajectory.json"
    ops = tmp_path / "ops_status.json"
    snap = {
        "schema_version": 1,
        "surface_freshness": "fresh",
        "markets": [],
        "separation": {"excludes": ["beat_market"]},
    }

    with (
        patch(
            "value_investor.lifecycle_board.maybe_refresh_lifecycle_board",
            return_value={"refreshed": True, "path": str(board)},
        ) as refresh_board,
        patch(
            "value_investor.lifecycle_maturity_trajectory.refresh_lifecycle_maturity_trajectory",
            return_value=snap,
        ) as refresh_maturity,
        patch(
            "value_investor.lifecycle_maturity_trajectory.ops_finding_from_maturity",
            return_value=None,
        ),
    ):
        findings = check_lifecycle_maturity_trajectory(
            board_path=board,
            store_path=store,
            ops_status_path=ops,
            persist=True,
            refresh_board=True,
        )

    assert findings == []
    refresh_board.assert_called_once_with(path=board)
    refresh_maturity.assert_called_once()


def test_check_lifecycle_maturity_skips_board_when_refresh_disabled(tmp_path: Path) -> None:
    board = tmp_path / "lifecycle_board.json"
    store = tmp_path / "lifecycle_maturity_trajectory.json"
    ops = tmp_path / "ops_status.json"
    snap = {"schema_version": 1, "surface_freshness": "fresh", "markets": []}

    with (
        patch(
            "value_investor.lifecycle_board.maybe_refresh_lifecycle_board",
        ) as refresh_board,
        patch(
            "value_investor.lifecycle_maturity_trajectory.refresh_lifecycle_maturity_trajectory",
            return_value=snap,
        ),
        patch(
            "value_investor.lifecycle_maturity_trajectory.ops_finding_from_maturity",
            return_value=None,
        ),
    ):
        check_lifecycle_maturity_trajectory(
            board_path=board,
            store_path=store,
            ops_status_path=ops,
            persist=True,
            refresh_board=False,
        )

    refresh_board.assert_not_called()


def test_check_lifecycle_maturity_skips_board_when_not_persisting(tmp_path: Path) -> None:
    board = tmp_path / "lifecycle_board.json"
    store = tmp_path / "lifecycle_maturity_trajectory.json"
    ops = tmp_path / "ops_status.json"
    snap = {"schema_version": 1, "surface_freshness": "fresh", "markets": []}

    with (
        patch(
            "value_investor.lifecycle_board.maybe_refresh_lifecycle_board",
        ) as refresh_board,
        patch(
            "value_investor.lifecycle_maturity_trajectory.build_lifecycle_maturity_snapshot",
            return_value=snap,
        ),
        patch(
            "value_investor.lifecycle_maturity_trajectory.ops_finding_from_maturity",
            return_value=None,
        ),
    ):
        check_lifecycle_maturity_trajectory(
            board_path=board,
            store_path=store,
            ops_status_path=ops,
            persist=False,
            refresh_board=True,
        )

    refresh_board.assert_not_called()
