"""Tests for the shared library gap-closure follow-up dispatcher."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/dispatch_library_gap_closure_followups.sh")


def test_dispatch_script_dry_run_single_and_batch(tmp_path: Path):
    single = tmp_path / "single.json"
    single.write_text(
        json.dumps(
            {
                "should_dispatch": True,
                "market_id": "euro_depth",
                "pin_ticker": "RAND.AS",
                "trigger": "stall_slowdown",
            }
        ),
        encoding="utf-8",
    )
    batch = tmp_path / "batch.json"
    batch.write_text(
        json.dumps(
            {
                "should_dispatch": True,
                "dispatches": [
                    {
                        "should_dispatch": True,
                        "market_id": "sp500",
                        "pin_ticker": "XYZ",
                        "trigger": "stall_slowdown",
                    },
                    {
                        "should_dispatch": True,
                        "market_id": "asx200",
                        "pin_ticker": "ABC.AX",
                        "trigger": "stall_slowdown",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "DRY_RUN": "1"}
    single_run = subprocess.run(
        ["bash", str(SCRIPT), str(single)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert single_run.returncode == 0, single_run.stderr
    assert "market=euro_depth pin_ticker=RAND.AS" in single_run.stdout

    batch_run = subprocess.run(
        ["bash", str(SCRIPT), str(batch)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert batch_run.returncode == 0, batch_run.stderr
    assert "market=sp500 pin_ticker=XYZ" in batch_run.stdout
    assert "market=asx200 pin_ticker=ABC.AX" in batch_run.stdout


def test_dispatch_script_no_rows(tmp_path: Path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"should_dispatch": False, "reason": "no gaps"}), encoding="utf-8")
    result = subprocess.run(
        ["bash", str(SCRIPT), str(empty)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DRY_RUN": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert "No library gap-closure follow-ups" in result.stdout
