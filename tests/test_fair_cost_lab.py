"""Tests for Suite B fair-cost lab spawn / warm-start / cost isolation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from value_investor.fair_cost_lab import (
    AI_JUDGMENT_FAIR_TRACK_ID,
    RULES_FAIR_TRACK_ID,
    discover_fair_cost_lab_track_ids,
    fair_twin_track_id,
    filter_track_ids_for_suite,
    recommend_rows_for_fair_twins,
    spawn_fair_cost_lab,
    spawn_fair_cost_twins_for_recommendations,
    warm_start_fair_cost_lab,
)
from value_investor.market_trading_costs import cost_fields_for_config
from value_investor.paper_automation import (
    AI_JUDGMENT_TRACK_ID,
    CONFIG_FILENAME,
    RULES_TRACK_ID,
    AutomationConfig,
    ensure_learning_track_configs,
    learning_track_dirs,
)
from value_investor.trading_costs_cli import main as trading_costs_main


def _seed_parent_paper_root(tmp_path: Path, repo_root: Path) -> Path:
    src = repo_root / "docs" / "data" / "paper_automation"
    root = tmp_path / "paper"
    (root / "ai_judgment").mkdir(parents=True)
    shutil.copy(src / "config.json", root / "config.json")
    shutil.copy(src / "ai_judgment" / "config.json", root / "ai_judgment" / "config.json")
    shutil.copy(src / "rebalance_log.json", root / "rebalance_log.json")
    shutil.copy(
        src / "ai_judgment" / "rebalance_log.json",
        root / "ai_judgment" / "rebalance_log.json",
    )
    return root


def test_spawn_and_ensure_keeps_fair_costs(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    root = _seed_parent_paper_root(tmp_path, repo)
    fair = cost_fields_for_config("ftse350")

    spawned = spawn_fair_cost_lab(root, force=True)
    assert spawned["created_count"] == 2
    assert spawned["spawned_count"] == 2

    configs = ensure_learning_track_configs(root)
    assert AI_JUDGMENT_FAIR_TRACK_ID in configs
    assert RULES_FAIR_TRACK_ID in configs
    assert AI_JUDGMENT_FAIR_TRACK_ID in learning_track_dirs(root)

    ai_fair = configs[AI_JUDGMENT_FAIR_TRACK_ID]
    rules_fair = configs[RULES_FAIR_TRACK_ID]
    assert ai_fair.is_fair_cost_lab is True
    assert ai_fair.is_primary_learning_track is False
    assert abs(float(ai_fair.trade_cost_pct) - float(fair["trade_cost_pct"])) < 1e-12
    assert abs(float(ai_fair.buy_cost_pct) - float(fair["buy_cost_pct"])) < 1e-12
    assert abs(float(rules_fair.sell_cost_pct) - float(fair["sell_cost_pct"])) < 1e-12

    # Suite A remains on stress.
    assert abs(float(configs[AI_JUDGMENT_TRACK_ID].trade_cost_pct) - 0.03) < 1e-12
    assert configs[AI_JUDGMENT_TRACK_ID].buy_cost_pct is None
    assert abs(float(configs[RULES_TRACK_ID].trade_cost_pct) - 0.03) < 1e-12

    # ensure must not wipe fair stamps back to 3%.
    persisted = json.loads((root / "ai_judgment_fair" / CONFIG_FILENAME).read_text())
    assert abs(float(persisted["trade_cost_pct"]) - float(fair["trade_cost_pct"])) < 1e-12
    assert persisted["is_fair_cost_lab"] is True


def test_warm_start_sets_endurance_zero_datum(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    root = _seed_parent_paper_root(tmp_path, repo)
    spawn_fair_cost_lab(root, force=True)
    warmed = warm_start_fair_cost_lab(root, force=True)
    assert warmed["warm_started_count"] == 2
    for row in warmed["tracks"]:
        assert row["warm_started"] is True
        zero = row["endurance_zero_datum"]
        assert zero.get("started_at")
        assert zero.get("suite") == "B"
        assert row["positions"] >= 1

    # Idempotent skip without force.
    again = warm_start_fair_cost_lab(root, force=False)
    assert again["warm_started_count"] == 0
    assert again["skipped_count"] == 2


def test_suite_filter_and_cli_spawn(tmp_path: Path, capsys):
    repo = Path(__file__).resolve().parents[1]
    root = _seed_parent_paper_root(tmp_path, repo)
    ids = [
        RULES_TRACK_ID,
        AI_JUDGMENT_TRACK_ID,
        AI_JUDGMENT_FAIR_TRACK_ID,
        RULES_FAIR_TRACK_ID,
        "ai_judgment_calibrated",
    ]
    assert filter_track_ids_for_suite(ids, "B") == [
        AI_JUDGMENT_FAIR_TRACK_ID,
        RULES_FAIR_TRACK_ID,
    ]
    assert AI_JUDGMENT_FAIR_TRACK_ID not in filter_track_ids_for_suite(ids, "A")

    rc = trading_costs_main(["spawn-fair-lab", "--paper-root", str(root), "--force", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created_count"] == 2


def _write_parent_shadow(root: Path, track_id: str) -> Path:
    parent_dir = root / track_id
    parent_dir.mkdir(parents=True)
    cfg = AutomationConfig(
        track_id=track_id,
        track_label=f"{track_id} shadow",
        is_primary_learning_track=False,
        is_calibration_shadow=True,
        calibration_parent_track="ai_judgment",
        use_adjusted_signal=True,
        require_research_accumulate=True,
        trade_cost_pct=0.03,
        max_positions=4,
        min_conviction=0.15,
    )
    (parent_dir / CONFIG_FILENAME).write_text(
        json.dumps(cfg.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return parent_dir


def _write_assessment(data_dir: Path, experiments: list[dict]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "experiment_assessment.json").write_text(
        json.dumps({"schema_version": 2, "experiments": experiments}),
        encoding="utf-8",
    )


def test_recommend_rows_skip_base_and_non_mirrorable():
    rows = recommend_rows_for_fair_twins(
        {
            "experiments": [
                {
                    "experiment_id": "ai_judgment",
                    "kind": "experimental_paper_track",
                    "status": "recommend",
                    "track_id": "ai_judgment",
                },
                {
                    "experiment_id": "entry_dca_overlay",
                    "kind": "lifecycle_overlay",
                    "status": "recommend",
                    "track_id": "",
                },
                {
                    "experiment_id": "ai_judgment_calibrated",
                    "kind": "calibration_shadow",
                    "status": "fail",
                    "track_id": "ai_judgment_calibrated",
                },
                {
                    "experiment_id": "ai_judgment_calibrated_r2",
                    "kind": "calibration_shadow",
                    "status": "recommend",
                    "track_id": "ai_judgment_calibrated_r2",
                },
            ]
        }
    )
    assert [row["track_id"] for row in rows] == ["ai_judgment_calibrated_r2"]


def test_spawn_fair_twins_dry_run_empty_and_apply(tmp_path: Path, capsys):
    root = tmp_path / "paper"
    data = tmp_path / "data"
    _write_assessment(data, [])
    empty = spawn_fair_cost_twins_for_recommendations(root, data, dry_run=True)
    assert empty["recommend_count"] == 0
    assert empty["selected_count"] == 0
    assert empty["tracks"] == []

    _write_parent_shadow(root, "ai_judgment_calibrated")
    _write_parent_shadow(root, "ai_judgment_calibrated_r2")
    _write_assessment(
        data,
        [
            {
                "experiment_id": "ai_judgment_calibrated",
                "kind": "calibration_shadow",
                "status": "recommend",
                "track_id": "ai_judgment_calibrated",
            },
            {
                "experiment_id": "ai_judgment_calibrated_r2",
                "kind": "calibration_shadow",
                "status": "recommend",
                "track_id": "ai_judgment_calibrated_r2",
            },
            {
                "experiment_id": "ai_judgment_exclusion",
                "kind": "exclusion_shadow",
                "status": "recommend",
                "track_id": "ai_judgment_exclusion",
            },
        ],
    )

    preview = spawn_fair_cost_twins_for_recommendations(root, data, dry_run=True, max_spawns=2)
    assert preview["dry_run"] is True
    assert preview["recommend_count"] == 3
    assert preview["selected_count"] == 2
    assert preview["spawned_count"] == 0
    assert len(preview["skipped_budget"]) == 1
    assert not (root / "ai_judgment_calibrated_fair").exists()

    applied = spawn_fair_cost_twins_for_recommendations(root, data, dry_run=False, max_spawns=2)
    assert applied["spawned_count"] == 2
    assert applied["created_count"] == 2
    twin_id = fair_twin_track_id("ai_judgment_calibrated")
    assert twin_id == "ai_judgment_calibrated_fair"
    twin_cfg = json.loads((root / twin_id / CONFIG_FILENAME).read_text())
    assert twin_cfg["is_fair_cost_lab"] is True
    assert twin_cfg["fair_cost_parent_track"] == "ai_judgment_calibrated"
    assert twin_cfg["is_primary_learning_track"] is False
    assert abs(float(twin_cfg["trade_cost_pct"]) - 0.03) > 1e-4
    assert "ai_judgment_calibrated_fair" in discover_fair_cost_lab_track_ids(root)
    assert "ai_judgment_calibrated_r2_fair" in filter_track_ids_for_suite(
        ["ai_judgment", "ai_judgment_calibrated_r2_fair"], "B"
    )

    rc = trading_costs_main(
        [
            "spawn-fair-twins",
            "--paper-root",
            str(root),
            "--data-dir",
            str(data),
            "--json",
        ]
    )
    assert rc == 0
    cli = json.loads(capsys.readouterr().out)
    assert cli["dry_run"] is True
    assert cli["recommend_count"] == 3
