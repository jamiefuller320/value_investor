"""Post-hsr freeze-extras policy (PR #1035 / L585)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.ops_monitor import check_post_hsr_policy
from value_investor.post_hsr_policy import (
    build_post_hsr_policy,
    holdouts_justify_freeze,
    ops_findings_from_post_hsr_policy,
    refresh_post_hsr_policy,
)


def _write_hsr(path: Path, *, verdict: str, registration_id: str = "hsr-v1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "registration_id": registration_id,
                "results": {"horizons": {"30": {"holdout_verdict": verdict}}},
            }
        ),
        encoding="utf-8",
    )


def _write_hrs(path: Path, *, verdict: str = "inconclusive") -> None:
    path.write_text(
        json.dumps(
            {
                "search": {
                    "selection": {
                        "config_id": "buy_tier|top=40|exit=tier3|tac=off",
                    }
                },
                "holdout": {
                    "chosen": {
                        "config_id": "buy_tier|top=40|exit=tier3|tac=off",
                        "base": {"verdict_vs_plain_value": verdict},
                    },
                    "chosen_minus_frozen": {"base": {"verdict": "inconclusive"}},
                },
            }
        ),
        encoding="utf-8",
    )


def _write_hms(path: Path, *, decision: str = "no_gain_over_frozen_mix") -> None:
    path.write_text(
        json.dumps(
            {
                "search": {"selection": {"kept": ["fcf_yield", "magic_formula"]}},
                "holdout": {"decision": decision},
            }
        ),
        encoding="utf-8",
    )


def test_holdouts_justify_freeze() -> None:
    assert holdouts_justify_freeze(
        hsr_verdict="inconclusive",
        hsr_mid_verdict="inconclusive",
        hrs_verdict="inconclusive",
        hms_decision="no_gain_over_frozen_mix",
    )
    assert not holdouts_justify_freeze(
        hsr_verdict="pass",
        hsr_mid_verdict="pass",
        hrs_verdict="pass",
        hms_decision="adopt_mix",
    )


def test_build_policy_from_fixture_tree(tmp_path: Path) -> None:
    data = tmp_path / "docs" / "data"
    _write_hsr(data / "historical_screen_replay.json", verdict="inconclusive")
    _write_hsr(
        data / "historical_screen_replay_midcap.json",
        verdict="inconclusive",
        registration_id="hsr-mid-v1",
    )
    _write_hrs(data / "historical_rule_search.json")
    _write_hms(data / "historical_model_mix.json")
    (tmp_path / "docs" / "ops").mkdir(parents=True)
    (tmp_path / "docs" / "ops" / "post-hsr-freeze-extras.md").write_text("# ok\n")

    payload = build_post_hsr_policy(repo_root=tmp_path)
    assert payload["freeze_extras"] is True
    assert payload["evidence"]["hsr_v1_holdout_verdict"] == "inconclusive"
    assert payload["evidence"]["hsr_mid_v1_holdout_verdict"] == "inconclusive"
    assert payload["strand_a"]["id"] == "strand_a_current_stack"
    assert {row["deferred_id"] for row in payload["candidate_strands"]} == {
        "N200",
        "N201",
    }
    assert payload["influences_live"] is False


def test_ops_findings_in_force_and_warn_paths(tmp_path: Path) -> None:
    data = tmp_path / "docs" / "data"
    _write_hsr(data / "historical_screen_replay.json", verdict="inconclusive")
    _write_hsr(
        data / "historical_screen_replay_midcap.json",
        verdict="inconclusive",
        registration_id="hsr-mid-v1",
    )
    _write_hrs(data / "historical_rule_search.json")
    _write_hms(data / "historical_model_mix.json")
    (tmp_path / "docs" / "ops").mkdir(parents=True)
    (tmp_path / "docs" / "ops" / "post-hsr-freeze-extras.md").write_text("# ok\n")

    payload = build_post_hsr_policy(repo_root=tmp_path)
    findings = ops_findings_from_post_hsr_policy(payload, repo_root=tmp_path)
    assert any(f["title"] == "Post-hsr freeze-extras policy in force" for f in findings)
    assert all(f["severity"] == "info" for f in findings)
    assert all(f.get("auto_fixable") is False for f in findings)

    broken = dict(payload)
    broken["freeze_extras"] = False
    warns = ops_findings_from_post_hsr_policy(broken, repo_root=tmp_path)
    assert any(
        f["title"]
        == "Post-hsr freeze-extras not declared after inconclusive holdout"
        for f in warns
    )

    missing_doc = dict(payload)
    no_doc_root = tmp_path / "empty"
    no_doc_root.mkdir()
    docs_missing = ops_findings_from_post_hsr_policy(
        missing_doc, ops_doc_exists=False, repo_root=no_doc_root
    )
    assert any(
        f["title"] == "Post-hsr freeze-extras ops note missing" for f in docs_missing
    )

    empty_strands = dict(payload)
    empty_strands["candidate_strands"] = []
    strand_warn = ops_findings_from_post_hsr_policy(
        empty_strands, ops_doc_exists=True, repo_root=tmp_path
    )
    assert any(
        f["title"] == "Post-hsr candidate strands not listed" for f in strand_warn
    )


def test_check_post_hsr_policy_persists(tmp_path: Path) -> None:
    data = tmp_path / "docs" / "data"
    _write_hsr(data / "historical_screen_replay.json", verdict="inconclusive")
    _write_hsr(
        data / "historical_screen_replay_midcap.json",
        verdict="inconclusive",
        registration_id="hsr-mid-v1",
    )
    _write_hrs(data / "historical_rule_search.json")
    _write_hms(data / "historical_model_mix.json")
    (tmp_path / "docs" / "ops").mkdir(parents=True)
    (tmp_path / "docs" / "ops" / "post-hsr-freeze-extras.md").write_text("# ok\n")
    store = tmp_path / "post_hsr_policy.json"

    findings = check_post_hsr_policy(
        store_path=store, repo_root=tmp_path, persist=True
    )
    assert store.is_file()
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert saved["freeze_extras"] is True
    assert any(f.title == "Post-hsr freeze-extras policy in force" for f in findings)


def test_refresh_round_trip(tmp_path: Path) -> None:
    data = tmp_path / "docs" / "data"
    _write_hsr(data / "historical_screen_replay.json", verdict="inconclusive")
    _write_hsr(
        data / "historical_screen_replay_midcap.json",
        verdict="inconclusive",
        registration_id="hsr-mid-v1",
    )
    _write_hrs(data / "historical_rule_search.json")
    _write_hms(data / "historical_model_mix.json")
    store = tmp_path / "out.json"
    payload = refresh_post_hsr_policy(
        store_path=store, repo_root=tmp_path, persist=True
    )
    assert payload["policy_id"] == "post-hsr-freeze-extras-v1"
    assert json.loads(store.read_text(encoding="utf-8"))["freeze_extras"] is True
