"""The conftest guard stops real library screens from writing committed docs/."""

from __future__ import annotations

from pathlib import Path

import pytest

from value_investor import library_ladder, library_screen
from value_investor.library_screen import run_library_screen

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_LIBRARY = REPO_ROOT / "docs" / "data" / "library"


@pytest.mark.parametrize(
    "call",
    [
        lambda root: library_screen.run_library_screen(root, "omxs30"),
        lambda root: library_ladder.run_library_screen(root, "omxs30"),
        lambda root: run_library_screen(root, "omxs30"),
    ],
    ids=["module_attr", "ladder_import_binding", "test_module_binding"],
)
def test_repo_library_root_fails_before_writing(call):
    screen_dir = REPO_LIBRARY / "markets" / "omxs30" / "screen"
    before = sorted(p.name for p in screen_dir.glob("*")) if screen_dir.exists() else []
    with pytest.raises(AssertionError, match="test_repo_library_root_fails_before_writing"):
        call(REPO_LIBRARY)
    after = sorted(p.name for p in screen_dir.glob("*")) if screen_dir.exists() else []
    assert after == before


def test_relative_default_root_from_repo_cwd_is_blocked(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    with pytest.raises(AssertionError, match="committed"):
        library_screen.run_library_screen(Path("docs/data/library"), "omxs30")


def test_tmp_path_root_still_reaches_real_screen(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="No metrics for omxs30"):
        library_screen.run_library_screen(tmp_path / "library", "omxs30")
