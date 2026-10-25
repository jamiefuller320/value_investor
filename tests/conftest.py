"""Shared pytest fixtures, plus a guard against tests writing committed docs/ data."""

from __future__ import annotations

import inspect
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from pinned_time import weekday_noon_utc

REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCS_STATUS_KEY = pytest.StashKey[set[str] | None]()

# Name tokens for tests in test_research_filings.py that hit live IR/SEC/ASX
# endpoints. Eng preflight and PR/push CI (ci.yml) exclude ``live_network`` so
# the suite does not burn budget / hang a shard on CDN stalls. Nightly
# (ci-main-nightly.yml) still runs them.
_LIVE_NETWORK_NAME_TOKENS = (
    "live_fetch",
    "has_fetchable_ir",
    "annual_live",
    "interim_live",
    "live_sec",
    "trading_update_live",
    "h1_live",
    "_live_",  # e.g. f6k_live / leftover live helpers not covered above
    "sec_edgar_body_accepts_issuer_alias",
    "resolve_asx_publisher_document_url_fmg_marketindex_iwb_inline",
    "results_pdf_fetches",
)

_LIVE_FETCH_CALL_TOKENS = (
    "fetch_filing_body(",
    "_live_fetch_filing_body(",
    "_first_fetchable_allowlist_body(",
)


def _research_filings_unpatched_live_fetch(item: pytest.Item) -> bool:
    """True when the test body calls a live fetch helper without patching it."""
    obj = getattr(item, "obj", None)
    if obj is None:
        return False
    try:
        src = inspect.getsource(obj)
    except (OSError, TypeError):
        return False
    if not any(token in src for token in _LIVE_FETCH_CALL_TOKENS):
        return False
    # Decorator / in-body patch of fetch_filing_body → not a live CI fetch.
    header, _, body = src.partition("\ndef ")
    if "fetch_filing_body" in header and ("@patch" in header or "patch(" in header):
        return False
    if "monkeypatch" in src and "fetch_filing_body" in src:
        if any(
            needle in src
            for needle in (
                "filings.fetch_filing_body",
                'setattr(fetch_filing_body',
                'setattr("fetch_filing_body"',
                "setattr('fetch_filing_body'",
            )
        ):
            return False
        # Common pattern: monkeypatch.setattr("value_investor.research.filings.fetch_filing_body", ...)
        if "monkeypatch.setattr" in src and "fetch_filing_body" in src:
            return False
    if "patch(" in body and "fetch_filing_body" in body:
        return False
    return True


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_network: hits live IR/SEC/ASX endpoints (skipped in eng preflight + PR/push CI; nightly keeps them)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    mark = pytest.mark.live_network
    for item in items:
        if "test_research_filings.py" not in item.nodeid:
            continue
        name = item.name
        if any(token in name for token in _LIVE_NETWORK_NAME_TOKENS):
            item.add_marker(mark)
            continue
        if _research_filings_unpatched_live_fetch(item):
            item.add_marker(mark)


def _docs_status() -> set[str] | None:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", "docs"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return {line for line in out.splitlines() if line.strip()}


def _guard_active(config: pytest.Config) -> bool:
    return not hasattr(config, "workerinput") and not os.environ.get("FTSE_SKIP_DOCS_WRITE_GUARD")


def pytest_sessionstart(session: pytest.Session) -> None:
    if _guard_active(session.config):
        session.stash[_DOCS_STATUS_KEY] = _docs_status()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _guard_active(session.config):
        return
    before = session.stash.get(_DOCS_STATUS_KEY, None)
    after = _docs_status()
    if before is None or after is None:
        return
    new = sorted(after - before)
    if not new:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    lines = [
        "Tests wrote to committed docs/ paths (run them from tmp_path, e.g. the "
        "isolated_cwd fixture, or pass explicit paths):",
        *(f"  {row}" for row in new),
    ]
    if reporter is not None:
        reporter.write_sep("=", "docs/ write guard", red=True)
        for line in lines:
            reporter.write_line(line)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


_REPO_DOCS = (REPO_ROOT / "docs").resolve()


def _is_repo_docs_path(path: Path | str) -> bool:
    return Path(path).resolve().is_relative_to(_REPO_DOCS)


@pytest.fixture(autouse=True)
def _forbid_library_screen_into_repo_docs(monkeypatch, request):
    """Fail the offending test when a real library screen targets committed docs/.

    Callers bind ``run_library_screen`` at import time, so every loaded module
    holding the original is patched; tests that mock it themselves still win.
    """
    import sys

    from value_investor import library_screen

    original = library_screen.run_library_screen

    def guarded(root, market_id, *args, **kwargs):
        if _is_repo_docs_path(root):
            raise AssertionError(
                f"{request.node.nodeid} ran run_library_screen({market_id!r}) against "
                f"committed {root}; pass a tmp_path library root"
            )
        return original(root, market_id, *args, **kwargs)

    for name, module in list(sys.modules.items()):
        owned = (
            name == "value_investor"
            or name.startswith("value_investor.")
            or name.rpartition(".")[2].startswith("test_")
        )
        if owned and getattr(module, "run_library_screen", None) is original:
            monkeypatch.setattr(module, "run_library_screen", guarded)


@pytest.fixture
def pinned_weekday_noon_utc() -> datetime:
    return weekday_noon_utc()


@pytest.fixture
def isolated_cwd(tmp_path, monkeypatch):
    """Run from tmp_path so code using repo-relative docs/data defaults writes there."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def board_not_written(monkeypatch):
    """Dashboard bundle builds write the human-tasks board to docs/data; build it only."""
    from value_investor import human_task_cards

    monkeypatch.setattr(
        human_task_cards,
        "write_human_tasks_board",
        lambda *, data_dir=None, checklist_path=None: human_task_cards.build_human_tasks_board(
            data_dir=data_dir, checklist_path=checklist_path
        ),
    )
