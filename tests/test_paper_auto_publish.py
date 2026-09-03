"""Tests for paper-auto overlay seed/publish (DCA + sibling observe-only stores)."""

from pathlib import Path

from value_investor.paper_auto_publish import (
    OVERLAY_ROOT_FILES,
    OVERLAY_TRACK_FILES,
    publish_overlay_artifacts,
    seed_paper_auto_state,
)


def test_seed_copies_every_track_dir_except_markets(tmp_path: Path):
    docs = tmp_path / "docs"
    out = tmp_path / "output"
    (docs / "ai_judgment_exclusion_u4").mkdir(parents=True)
    (docs / "markets").mkdir()
    (docs / "learning_tracks_entry_dca.json").write_text('{"scored_count": 1}\n')
    (docs / "ai_judgment_exclusion_u4" / "entry_dca_overlay.json").write_text('{"episodes": []}\n')
    (docs / "markets" / "ignore.json").write_text("{}\n")

    copied = seed_paper_auto_state(docs, out)

    assert "learning_tracks_entry_dca.json" in copied
    assert "ai_judgment_exclusion_u4/entry_dca_overlay.json" in copied
    assert (out / "learning_tracks_entry_dca.json").is_file()
    assert (out / "ai_judgment_exclusion_u4" / "entry_dca_overlay.json").is_file()
    assert not (out / "markets").exists()


def test_publish_persists_overlay_stores_across_tracks(tmp_path: Path):
    src = tmp_path / "output"
    dest = tmp_path / "docs"
    (src / "ai_judgment").mkdir(parents=True)
    (src / "markets").mkdir()
    (src / "learning_tracks_entry_dca.json").write_text('{"scored_count": 2}\n')
    (src / "entry_dca_overlay.json").write_text('{"episodes": [{"id": "rules"}]}\n')
    (src / "ai_judgment" / "entry_dca_overlay.json").write_text('{"episodes": [{"id": "ai"}]}\n')
    (src / "ai_judgment" / "entry_dca_overlay_review.json").write_text('{"scored_count": 0}\n')
    (src / "markets" / "entry_dca_overlay.json").write_text("{}\n")

    copied = publish_overlay_artifacts(src, dest)

    assert "learning_tracks_entry_dca.json" in copied
    assert "entry_dca_overlay.json" in copied
    assert "ai_judgment/entry_dca_overlay.json" in copied
    assert (dest / "learning_tracks_entry_dca.json").read_text().startswith("{")
    assert (dest / "entry_dca_overlay.json").is_file()
    assert (dest / "ai_judgment" / "entry_dca_overlay_review.json").is_file()
    assert not (dest / "markets").exists()


def test_overlay_file_lists_cover_dca_and_sibling_stores():
    assert "learning_tracks_entry_dca.json" in OVERLAY_ROOT_FILES
    assert "entry_dca_overlay.json" in OVERLAY_TRACK_FILES
    assert "entry_dca_overlay_review.json" in OVERLAY_TRACK_FILES
    assert "exit_timing_cohorts.json" in OVERLAY_TRACK_FILES
    assert "hypothesis_integrity.json" in OVERLAY_TRACK_FILES


def test_paper_auto_workflow_calls_overlay_seed_and_publish():
    text = Path(".github/workflows/paper-auto.yml").read_text(encoding="utf-8")
    assert "seed_paper_auto_state" in text
    assert "publish_overlay_artifacts" in text
