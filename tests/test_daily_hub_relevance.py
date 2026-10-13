"""Daily hub Focus relevance vs P1/P2 spend-priority anchors."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.daily_hub_relevance import (
    FINDING_TITLE,
    collect_focus_corpus,
    evaluate_relevance,
    extract_aim_text,
    load_anchors,
    ops_findings_from_relevance,
    refresh_daily_hub_relevance,
)
from value_investor.ops_monitor import check_daily_hub_relevance
from value_investor.storage import write_json


def _write_seed(data_dir: Path, titles: list[tuple[str, str]]) -> None:
    write_json(
        data_dir / "project_daily_seed.json",
        {
            "schema_version": 1,
            "focus_lines": [
                {
                    "id": f"focus-{i}",
                    "priority": i,
                    "title": title,
                    "summary": summary,
                    "source": "project_notes",
                    "tags": ["project_notes"],
                }
                for i, (title, summary) in enumerate(titles, start=1)
            ],
        },
        compact=False,
    )


def _write_aim(path: Path, text: str) -> None:
    path.write_text(
        f'<div class="daily-hub-aim muted small">{text}</div>\n',
        encoding="utf-8",
    )


def _anchors() -> dict:
    return load_anchors(Path("docs/data/daily_hub_priority_anchors.json"))


def test_extract_aim_text_from_app_js(tmp_path: Path) -> None:
    aim = tmp_path / "app.js"
    _write_aim(aim, "Aim: P1 bind and P2 offline ingest maintenance.")
    assert "p1 bind" in extract_aim_text(aim).lower()


def test_relevant_focus_and_aim_produces_no_finding(tmp_path: Path) -> None:
    _write_seed(
        tmp_path,
        [
            (
                "P1: Keep holdings ∪ strand A ∪ N200 bind green; N201 launch-queue waiter",
                "Do not steal P1 for N201.",
            ),
            (
                "P2: Offline ingest in maintenance; clash-aware ≤2 agents",
                "No fourth equal sprint.",
            ),
        ],
    )
    aim = tmp_path / "app.js"
    _write_aim(
        aim,
        "Aim: Focus tracks P1 live-path bind and P2 offline ingest maintenance.",
    )
    corpus = collect_focus_corpus(data_dir=tmp_path, aim_path=aim)
    evaluation = evaluate_relevance(corpus, _anchors())
    assert evaluation["relevant"] is True
    assert ops_findings_from_relevance(evaluation) == []


def test_stale_rat_l_and_hub_phase_flag(tmp_path: Path) -> None:
    _write_seed(
        tmp_path,
        [
            (
                "Watch RAT.L entry DCA / paper path; euro fat released",
                "Euro fat released — watch RAT.L.",
            ),
            (
                "Daily hub Phase 1 + Accept/Discuss land; keep clash-aware one PR",
                "Ship Automation Daily hub.",
            ),
        ],
    )
    aim = tmp_path / "app.js"
    _write_aim(aim, "do not ritual-clear badges or starve the euro fat slot.")
    corpus = collect_focus_corpus(data_dir=tmp_path, aim_path=aim)
    evaluation = evaluate_relevance(corpus, _anchors())
    assert evaluation["relevant"] is False
    phrases = {h["phrase"] for h in evaluation["stale_hits"]}
    assert "rat.l" in phrases
    assert "daily hub phase 1" in phrases
    assert "accept/discuss land" in phrases
    assert "starve the euro fat" in phrases
    findings = ops_findings_from_relevance(evaluation, corpus=corpus)
    assert len(findings) == 1
    assert findings[0]["title"] == FINDING_TITLE
    assert findings[0]["auto_fixable"] is False
    assert findings[0]["severity"] == "warn"


def test_missing_p1_group_flags(tmp_path: Path) -> None:
    _write_seed(
        tmp_path,
        [
            ("P2: Offline ingest in maintenance", "Cascade maintenance only."),
            ("Clash-aware eng capacity", "≤2 agents."),
        ],
    )
    aim = tmp_path / "app.js"
    _write_aim(aim, "P2 offline ingest maintenance.")
    corpus = collect_focus_corpus(data_dir=tmp_path, aim_path=aim)
    evaluation = evaluate_relevance(corpus, _anchors())
    assert evaluation["relevant"] is False
    missing_ids = {g["id"] for g in evaluation["missing_groups"]}
    assert "p1_live_path_bind" in missing_ids


def test_check_daily_hub_relevance_persists_and_warns(tmp_path: Path) -> None:
    _write_seed(
        tmp_path,
        [
            ("Watch RAT.L entry DCA", "RAT.L paper path."),
            ("Daily hub Phase 1 land", "Accept/Discuss land."),
        ],
    )
    aim = tmp_path / "app.js"
    _write_aim(aim, "starve the euro fat slot")
    findings = check_daily_hub_relevance(
        data_dir=tmp_path,
        anchors_path=Path("docs/data/daily_hub_priority_anchors.json"),
        result_path=tmp_path / "daily_hub_relevance.json",
        aim_path=aim,
        persist=True,
    )
    assert len(findings) == 1
    assert findings[0].title == FINDING_TITLE
    assert findings[0].auto_fixable is False
    stored = json.loads((tmp_path / "daily_hub_relevance.json").read_text(encoding="utf-8"))
    assert stored["evaluation"]["relevant"] is False
    assert stored["auto_fixable"] is False


def test_refresh_relevant_seed_clears_finding(tmp_path: Path) -> None:
    _write_seed(
        tmp_path,
        [
            (
                "P1: holdings ∪ strand A ∪ N200 bind; N201 launch-queue waiter",
                "No P1 steal.",
            ),
            (
                "P2: Offline cascade maintenance; clash-aware eng",
                "Spare auto-advance only.",
            ),
        ],
    )
    aim = tmp_path / "app.js"
    _write_aim(aim, "P1 live-path bind and P2 offline ingest.")
    payload = refresh_daily_hub_relevance(
        data_dir=tmp_path,
        anchors_path=Path("docs/data/daily_hub_priority_anchors.json"),
        result_path=tmp_path / "daily_hub_relevance.json",
        aim_path=aim,
        persist=True,
    )
    assert payload["evaluation"]["relevant"] is True
    assert payload["finding_titles"] == []
    findings = check_daily_hub_relevance(
        data_dir=tmp_path,
        anchors_path=Path("docs/data/daily_hub_priority_anchors.json"),
        result_path=tmp_path / "daily_hub_relevance.json",
        aim_path=aim,
        persist=False,
    )
    assert findings == []


def test_committed_anchors_file_loads() -> None:
    anchors = load_anchors()
    assert len(anchors["required_groups"]) >= 2
    assert any(g["id"] == "p1_live_path_bind" for g in anchors["required_groups"])
    assert any(g["id"] == "p2_offline_ingest" for g in anchors["required_groups"])
