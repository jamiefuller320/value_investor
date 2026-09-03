"""Copy paper-auto artifacts between the CI output tree and committed dashboard data.

The workflow allowlist historically omitted observe-only overlay stores
(entry DCA, exit-timing, hypothesis). Those files must persist or weekday
marks reset every run and evidence never accumulates.
"""

from __future__ import annotations

import shutil
from pathlib import Path

SKIP_DIR_NAMES = frozenset({"markets"})

OVERLAY_ROOT_FILES = (
    "learning_tracks_entry_dca.json",
    "learning_tracks_exit_timing.json",
    "learning_tracks_hypothesis_integrity.json",
    "learning_tracks_hypothesis_outcomes.json",
)

OVERLAY_TRACK_FILES = (
    "entry_dca_overlay.json",
    "entry_dca_overlay_review.json",
    "exit_timing_cohorts.json",
    "exit_timing_cohorts_review.json",
    "hypothesis_integrity.json",
    "hypothesis_outcome_link.json",
    "hypothesis_outcome_link_review.json",
)


def _iter_track_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    dirs = [path for path in root.iterdir() if path.is_dir() and path.name not in SKIP_DIR_NAMES]
    return sorted(dirs, key=lambda path: path.name)


def _copy_if_present(src: Path, dest: Path) -> bool:
    if not src.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def seed_paper_auto_state(docs_root: Path, output_root: Path) -> list[str]:
    """Copy committed JSON (root + every track dir) into the CI working tree."""
    docs_root = Path(docs_root)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    if docs_root.is_dir():
        for src in sorted(docs_root.glob("*.json")):
            if _copy_if_present(src, output_root / src.name):
                copied.append(src.name)
        for src_dir in _iter_track_dirs(docs_root):
            dest_dir = output_root / src_dir.name
            dest_dir.mkdir(parents=True, exist_ok=True)
            for src in sorted(src_dir.glob("*.json")):
                rel = f"{src_dir.name}/{src.name}"
                if _copy_if_present(src, dest_dir / src.name):
                    copied.append(rel)
    return copied


def publish_overlay_artifacts(src_root: Path, dest_root: Path) -> list[str]:
    """Persist overlay stores/rollups that the historic allowlist omitted."""
    src_root = Path(src_root)
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in OVERLAY_ROOT_FILES:
        if _copy_if_present(src_root / name, dest_root / name):
            copied.append(name)
    for src_dir in [src_root, *_iter_track_dirs(src_root)]:
        prefix = "" if src_dir == src_root else f"{src_dir.name}/"
        dest_dir = dest_root if src_dir == src_root else dest_root / src_dir.name
        for name in OVERLAY_TRACK_FILES:
            if _copy_if_present(src_dir / name, dest_dir / name):
                copied.append(f"{prefix}{name}")
    return copied


__all__ = [
    "OVERLAY_ROOT_FILES",
    "OVERLAY_TRACK_FILES",
    "SKIP_DIR_NAMES",
    "publish_overlay_artifacts",
    "seed_paper_auto_state",
]
