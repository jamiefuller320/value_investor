"""Strategy dashboard v2 (docs/v2/) static page contract tests."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
V2_INDEX = REPO / "docs" / "v2" / "index.html"
V2_JS = REPO / "docs" / "v2" / "v2.js"
V2_CSS = REPO / "docs" / "v2" / "v2.css"
ROOT_INDEX = REPO / "docs" / "index.html"
DOCS_DATA = REPO / "docs" / "data"


def test_v2_shell_files_exist() -> None:
    assert V2_INDEX.is_file()
    assert V2_JS.is_file()
    assert V2_CSS.is_file()


def test_v2_index_cache_busts_assets() -> None:
    html = V2_INDEX.read_text(encoding="utf-8")
    assert re.search(r'href="v2\.css\?v=', html)
    assert re.search(r'src="v2\.js\?v=', html)
    assert 'src="../dashboard_bridge.js' in html


def test_v2_resolves_paths_from_its_own_folder() -> None:
    # A <base> tag would also rebase fetch() and #hash links, breaking both on Pages.
    html = V2_INDEX.read_text(encoding="utf-8")
    assert "<base" not in html
    assert 'DASHBOARD_BRIDGE_CONFIG_URL = "../data/dashboard_config.json"' in html
    bridge = (V2_INDEX.parents[1] / "dashboard_bridge.js").read_text(encoding="utf-8")
    assert "DASHBOARD_BRIDGE_CONFIG_URL" in bridge


def test_root_index_links_to_v2() -> None:
    html = ROOT_INDEX.read_text(encoding="utf-8")
    assert 'href="v2/"' in html


def test_v2_js_data_paths_exist_or_optional() -> None:
    text = V2_JS.read_text(encoding="utf-8")
    assert "latest.json" not in text
    assert "app.js" not in text
    assert '"human-task-ack"' in text

    optional = {"strategy_book_forward_status.json"}
    for match in re.finditer(r"\.\./data/([a-z0-9_]+\.json)", text):
        name = match.group(1)
        path = DOCS_DATA / name
        if name in optional:
            continue
        assert path.is_file(), f"missing docs/data/{name} referenced by v2.js"


def test_node_syntax_check_v2_js() -> None:
    if shutil.which("node") is None:
        return
    subprocess.run(
        ["node", "--check", str(V2_JS)],
        cwd=str(REPO),
        check=True,
        capture_output=True,
        text=True,
    )


def test_v2_today_sorts_strategy_decisions_first() -> None:
    js = (REPO / "docs" / "v2" / "v2.js").read_text(encoding="utf-8")
    assert "STRATEGY_TASK_PATTERN" in js
    assert js.count("renderOpenHumanTasks(") >= 3
