"""Regression: library ingest push must stash engineering_tasks and not clobber it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _seed_library_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "clone", str(remote), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "test")

    library = work / "docs" / "data" / "library"
    library.mkdir(parents=True)
    (library / "euro_ingest_dispatch.json").write_text('{"mode":"sprint"}\n', encoding="utf-8")
    (work / "docs" / "data" / "engineering_tasks.json").write_text(
        '{"compiled_at":"old","tasks":[]}\n',
        encoding="utf-8",
    )
    (work / "docs" / "data" / "ops_status.json").write_text(
        '{"run_at":"old","overall":"ok"}\n',
        encoding="utf-8",
    )
    (work / "scripts").mkdir()
    script_src = Path("scripts/push_library_ingest_artifacts.sh").read_text(encoding="utf-8")
    script = work / "scripts" / "push_library_ingest_artifacts.sh"
    script.write_text(script_src, encoding="utf-8")
    os.chmod(script, 0o755)

    _git(
        work,
        "add",
        "docs/data/library/euro_ingest_dispatch.json",
        "docs/data/engineering_tasks.json",
        "docs/data/ops_status.json",
        "scripts",
    )
    _git(work, "commit", "-m", "seed")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-u", "origin", "main")
    return remote, work


def _run_push(work: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "MAX_ATTEMPTS": "2"}
    return subprocess.run(
        [
            "bash",
            "scripts/push_library_ingest_artifacts.sh",
            "chore: euro_depth ingest loop [skip ci]",
        ],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_push_survives_dirty_engineering_tasks_when_origin_moved(tmp_path: Path):
    """
    Reproduce the 2026-09-03 13:15 UTC euro-ingest-loop failure:

    1. Job dirty-writes engineering_tasks.json (micro-compile / compiled_at)
    2. Concurrent automation updates the same file on origin/main
    3. Push script must stash that file before checkout, then succeed
    """
    _remote, work = _seed_library_repo(tmp_path)

    other = tmp_path / "other"
    _git(tmp_path, "clone", str(_remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "test")
    (other / "docs" / "data" / "engineering_tasks.json").write_text(
        '{"compiled_at":"concurrent","tasks":[1]}\n',
        encoding="utf-8",
    )
    _git(other, "add", "docs/data/engineering_tasks.json")
    _git(other, "commit", "-m", "chore: engineering queue")
    _git(other, "push", "origin", "main")

    (work / "docs" / "data" / "library" / "euro_ingest_dispatch.json").write_text(
        '{"mode":"sprint","run":"job"}\n',
        encoding="utf-8",
    )
    (work / "docs" / "data" / "engineering_tasks.json").write_text(
        '{"compiled_at":"job","tasks":[{"id":"eng-job"}]}\n',
        encoding="utf-8",
    )

    result = _run_push(work)
    assert result.returncode == 0, textwrap.dedent(
        f"""
        push script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )

    _git(work, "fetch", "origin")
    dispatch = _git(work, "show", "origin/main:docs/data/library/euro_ingest_dispatch.json").stdout
    tasks = _git(work, "show", "origin/main:docs/data/engineering_tasks.json").stdout
    assert '"run":"job"' in dispatch.replace(" ", ""), dispatch
    assert '"compiled_at":"job"' in tasks.replace(" ", ""), tasks


def test_push_preserves_untouched_engineering_tasks(tmp_path: Path):
    """If ingest did not touch engineering_tasks.json, keep origin's concurrent update."""
    _remote, work = _seed_library_repo(tmp_path)

    other = tmp_path / "other"
    _git(tmp_path, "clone", str(_remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "test")
    (other / "docs" / "data" / "engineering_tasks.json").write_text(
        '{"compiled_at":"concurrent","tasks":[1]}\n',
        encoding="utf-8",
    )
    _git(other, "add", "docs/data/engineering_tasks.json")
    _git(other, "commit", "-m", "chore: engineering queue")
    _git(other, "push", "origin", "main")

    (work / "docs" / "data" / "library" / "euro_ingest_dispatch.json").write_text(
        '{"mode":"sprint","run":"job"}\n',
        encoding="utf-8",
    )

    result = _run_push(work)
    assert result.returncode == 0, textwrap.dedent(
        f"""
        push script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )

    _git(work, "fetch", "origin")
    dispatch = _git(work, "show", "origin/main:docs/data/library/euro_ingest_dispatch.json").stdout
    tasks = _git(work, "show", "origin/main:docs/data/engineering_tasks.json").stdout
    assert '"run":"job"' in dispatch.replace(" ", ""), dispatch
    assert '"compiled_at":"concurrent"' in tasks.replace(" ", ""), tasks


def test_push_does_not_commit_stale_ops_status(tmp_path: Path):
    _remote, work = _seed_library_repo(tmp_path)

    other = tmp_path / "other"
    _git(tmp_path, "clone", str(_remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "test")
    (other / "docs" / "data" / "ops_status.json").write_text(
        '{"run_at":"new","overall":"fail"}\n',
        encoding="utf-8",
    )
    _git(other, "add", "docs/data/ops_status.json")
    _git(other, "commit", "-m", "chore: ops monitor")
    _git(other, "push", "origin", "main")

    (work / "docs" / "data" / "library" / "euro_ingest_dispatch.json").write_text(
        '{"mode":"sprint","run":"job"}\n',
        encoding="utf-8",
    )
    (work / "docs" / "data" / "ops_status.json").write_text(
        '{"run_at":"stale-job","overall":"ok"}\n',
        encoding="utf-8",
    )

    result = _run_push(work)
    assert result.returncode == 0, textwrap.dedent(
        f"""
        push script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )

    _git(work, "fetch", "origin")
    ops = _git(work, "show", "origin/main:docs/data/ops_status.json").stdout
    dispatch = _git(work, "show", "origin/main:docs/data/library/euro_ingest_dispatch.json").stdout
    assert '"run_at":"new"' in ops.replace(" ", ""), f"ops_status was clobbered:\n{ops}"
    assert '"run":"job"' in dispatch.replace(" ", ""), dispatch


def test_ingest_and_action_workflows_dispatch_pages_after_skip_ci() -> None:
    script = Path("scripts/push_library_ingest_artifacts.sh").read_text(encoding="utf-8")
    assert "docs/data/market_status.json" in script
    assert "DISPATCH_PAGES" in script
    helper = Path("scripts/dispatch_pages.sh").read_text(encoding="utf-8")
    assert "gh workflow run pages.yml" in helper
    workflows = Path(".github/workflows")
    ingest = "\n".join(
        (workflows / name).read_text(encoding="utf-8")
        for name in (
            "euro-ingest-loop.yml",
            "library-ingest-maintenance.yml",
            "library-ingest-sprint.yml",
            "library-ingest-sprint-2.yml",
        )
    )
    assert ingest.count("DISPATCH_PAGES") >= 4
    assert "scripts/dispatch_pages.sh" in (workflows / "paper-auto.yml").read_text(encoding="utf-8")
    assert "scripts/dispatch_pages.sh" in (workflows / "engineering-queue.yml").read_text(
        encoding="utf-8"
    )
    grow = (workflows / "library-grow.yml").read_text(encoding="utf-8")
    assert "market-status" in grow
    assert "docs/data/market_status.json" in grow


def test_push_merges_catalogue_cursor_with_a_finished_handoff(tmp_path: Path):
    """A screen commit must not put a finished ingest back to pending."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "clone", str(remote), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "test")
    library = work / "docs" / "data" / "library"
    library.mkdir(parents=True)
    state = library / "catalogue_explorer.json"
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "completed": ["AAA_US_EQ"],
                "runs": [],
                "handoffs": [{"t212_ticker": "AAA_US_EQ", "status": "pending", "signal": "buy"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _git(work, "add", "docs/data/library/catalogue_explorer.json")
    _git(work, "commit", "-m", "seed")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-u", "origin", "main")

    other = tmp_path / "other"
    _git(tmp_path, "clone", str(remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "test")
    other_state = other / "docs" / "data" / "library" / "catalogue_explorer.json"
    other_state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "completed": ["AAA_US_EQ", "CCC_US_EQ"],
                "runs": [],
                "handoffs": [
                    {
                        "t212_ticker": "AAA_US_EQ",
                        "status": "done",
                        "signal": "buy",
                        "ingest": {"seconds": 4},
                    }
                ],
                "updated_at": "2026-11-21T01:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _git(other, "add", "docs/data/library/catalogue_explorer.json")
    _git(other, "commit", "-m", "handoff done")
    _git(other, "push", "origin", "main")

    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "completed": ["AAA_US_EQ", "BBB_US_EQ"],
                "runs": [
                    {
                        "t212_ticker": "BBB_US_EQ",
                        "at": "2026-11-21T02:00:00+00:00",
                        "signal": "hold",
                        "screen_seconds": 2.0,
                        "venue": "US",
                        "seconds": 2.5,
                        "outcome": "miss",
                    }
                ],
                "handoffs": [{"t212_ticker": "AAA_US_EQ", "status": "pending", "signal": "buy"}],
                "last": {
                    "t212_ticker": "BBB_US_EQ",
                    "at": "2026-11-21T02:00:00+00:00",
                    "seconds": 2.5,
                },
                "updated_at": "2026-11-21T02:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "push_library_ingest_artifacts.sh"
    result = subprocess.run(
        ["bash", str(script), "chore: catalogue explorer one name [skip ci]"],
        cwd=work,
        env={**os.environ, "MAX_ATTEMPTS": "2"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, textwrap.dedent(
        f"""
        push script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )
    _git(work, "fetch", "origin")
    raw = _git(work, "show", "origin/main:docs/data/library/catalogue_explorer.json").stdout
    merged = json.loads(raw)
    assert merged["completed"] == ["AAA_US_EQ", "CCC_US_EQ", "BBB_US_EQ"]
    saved = {row["t212_ticker"]: row for row in merged["handoffs"]}
    assert saved["AAA_US_EQ"]["status"] == "done"
    assert saved["AAA_US_EQ"]["ingest"]["seconds"] == 4
    assert merged["last"]["t212_ticker"] == "BBB_US_EQ"


def _race_env(
    tmp_path: Path, *, rejects: int, hard_fails: int, advance: Path | None
) -> dict[str, str]:
    git_real = shutil.which("git")
    assert git_real
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "git"
    wrapper.write_text(
        textwrap.dedent(
            """\
            #!/bin/bash
            set -u
            real="$GIT_REAL"
            is_main_push=0
            if [ "${1:-}" = "push" ]; then
              for arg in "$@"; do
                if [ "$arg" = "HEAD:main" ]; then
                  is_main_push=1
                  break
                fi
              done
            fi
            if [ "$is_main_push" -eq 1 ]; then
              n=0
              if [ -f "$RACE_COUNT_FILE" ]; then
                n=$(cat "$RACE_COUNT_FILE")
              fi
              n=$((n + 1))
              printf '%s\\n' "$n" > "$RACE_COUNT_FILE"
              if [ -n "${RACE_ADVANCE_SCRIPT:-}" ] && [ "$n" -le "${RACE_REJECTS:-0}" ]; then
                bash "$RACE_ADVANCE_SCRIPT" || exit 1
              fi
              if [ "$n" -le "${HARD_FAILS:-0}" ]; then
                echo " ! [remote rejected] HEAD -> main (pre-receive hook declined)" >&2
                exit 1
              fi
            fi
            exec "$real" "$@"
            """
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "GIT_REAL": git_real,
        "RACE_COUNT_FILE": str(tmp_path / "push_count"),
        "RACE_ADVANCE_SCRIPT": str(advance) if advance is not None else "",
        "RACE_REJECTS": str(rejects),
        "HARD_FAILS": str(hard_fails),
        "MAX_ATTEMPTS": "2",
        "RACE_MAX_ATTEMPTS": "6",
        "RACE_RETRY_SLEEP": "0",
        "PUSH_BACKOFF_SECONDS": "0",
    }
    return env


def _init_pair(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    other = tmp_path / "other"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "clone", str(remote), str(work))
    for repo in (work,):
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "test")
        _git(repo, "config", "core.autocrlf", "false")
    library = work / "docs" / "data" / "library"
    library.mkdir(parents=True)
    (library / "catalogue_explorer.json").write_text(
        json.dumps({"schema_version": 1, "completed": [], "runs": [], "handoffs": []}) + "\n",
        encoding="utf-8",
    )
    _git(work, "add", "docs/data/library/catalogue_explorer.json")
    _git(work, "commit", "-m", "seed")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-u", "origin", "main")
    _git(tmp_path, "clone", str(remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "test")
    _git(other, "config", "core.autocrlf", "false")
    return work, other


def _run_repo_push(
    work: Path, env: dict[str, str], message: str
) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "push_library_ingest_artifacts.sh"
    return subprocess.run(
        ["bash", str(script), message],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_push_wins_when_catalogue_screens_land_during_the_push(tmp_path: Path):
    """A finished screen and buy must land after main rejects the push.

    Runs 45187088011 (BWA) and 45163550295 (AROW) failed after four attempts.
    MAX_ATTEMPTS stays 2 here; the main-moved retries are what carry the commit.
    """
    work, other = _init_pair(tmp_path)
    state_path = work / "docs" / "data" / "library" / "catalogue_explorer.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "completed": ["BWA_US_EQ"],
                "runs": [],
                "handoffs": [
                    {
                        "t212_ticker": "BWA_US_EQ",
                        "status": "done",
                        "signal": "buy",
                        "ingest": {"seconds": 9},
                    }
                ],
                "updated_at": "2026-11-23T14:20:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    screen = (
        work / "docs/data/library/catalogue_explorer/research/BWA/sources/screening_snapshot.json"
    )
    screen.parent.mkdir(parents=True)
    screen.write_text('{"ticker":"BWA"}\n', encoding="utf-8")

    advance_tree = tmp_path / "advance"
    arow_state = advance_tree / "docs" / "data" / "library" / "catalogue_explorer.json"
    arow_state.parent.mkdir(parents=True)
    arow_state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "completed": ["AROW_US_EQ"],
                "runs": [],
                "handoffs": [],
                "updated_at": "2026-11-23T11:33:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    arow_screen = (
        advance_tree
        / "docs/data/library/catalogue_explorer/research/AROW/sources/screening_snapshot.json"
    )
    arow_screen.parent.mkdir(parents=True)
    arow_screen.write_text('{"ticker":"AROW"}\n', encoding="utf-8")
    advance = tmp_path / "advance.sh"
    env = _race_env(tmp_path, rejects=3, hard_fails=0, advance=advance)
    git_real = env["GIT_REAL"]
    advance.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                "set -euo pipefail",
                f"cp -a {advance_tree}/. {other}/",
                'n=$(cat "$RACE_COUNT_FILE")',
                f'echo "landed $n" >> {other}/docs/data/library/racing_screens.log',
                f"{git_real} -C {other} add docs/data/library",
                f'{git_real} -C {other} commit -m "chore: racing screen [skip ci]"',
                f"{git_real} -C {other} push origin HEAD:main",
                "",
            ]
        ),
        encoding="utf-8",
    )
    advance.chmod(0o755)

    result = _run_repo_push(work, env, "chore: catalogue explorer one name [skip ci]")
    assert result.returncode == 0, textwrap.dedent(
        f"""
        push script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )
    assert "Main moved — retrying" in result.stdout
    assert int((tmp_path / "push_count").read_text(encoding="utf-8")) == 4

    _git(work, "fetch", "origin")
    merged = json.loads(
        _git(work, "show", "origin/main:docs/data/library/catalogue_explorer.json").stdout
    )
    assert merged["completed"] == ["AROW_US_EQ", "BWA_US_EQ"]
    saved = {row["t212_ticker"]: row for row in merged["handoffs"]}
    assert saved["BWA_US_EQ"]["status"] == "done"
    assert saved["BWA_US_EQ"]["signal"] == "buy"
    assert saved["BWA_US_EQ"]["ingest"]["seconds"] == 9
    bwa = _git(
        work,
        "show",
        "origin/main:docs/data/library/catalogue_explorer/research/BWA/sources/screening_snapshot.json",
    ).stdout
    arow = _git(
        work,
        "show",
        "origin/main:docs/data/library/catalogue_explorer/research/AROW/sources/screening_snapshot.json",
    ).stdout
    assert '"ticker":"BWA"' in bwa.replace(" ", "")
    assert '"ticker":"AROW"' in arow.replace(" ", "")
    racing = _git(work, "show", "origin/main:docs/data/library/racing_screens.log").stdout
    assert racing.splitlines() == ["landed 1", "landed 2", "landed 3"]


def test_push_skips_when_the_finished_screen_is_already_on_main(tmp_path: Path):
    """A rejected push skips when the same screen file is already on main."""
    work, other = _init_pair(tmp_path)
    payload = '{"ticker":"BWA"}\n'
    payload_file = tmp_path / "screening_snapshot.json"
    payload_file.write_text(payload, encoding="utf-8")
    screen = (
        work / "docs/data/library/catalogue_explorer/research/BWA/sources/screening_snapshot.json"
    )
    screen.parent.mkdir(parents=True)
    shutil.copyfile(payload_file, screen)

    advance = tmp_path / "advance.sh"
    dest = (
        other / "docs/data/library/catalogue_explorer/research/BWA/sources/screening_snapshot.json"
    )
    env = _race_env(tmp_path, rejects=1, hard_fails=0, advance=advance)
    git_real = env["GIT_REAL"]
    advance.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                "set -euo pipefail",
                f"mkdir -p {dest.parent}",
                f"cp {payload_file} {dest}",
                f"{git_real} -C {other} add docs/data/library",
                f'{git_real} -C {other} commit -m "chore: racing screen [skip ci]"',
                f"{git_real} -C {other} push origin HEAD:main",
                "",
            ]
        ),
        encoding="utf-8",
    )
    advance.chmod(0o755)

    result = _run_repo_push(work, env, "chore: keep BWA [skip ci]")
    assert result.returncode == 0, textwrap.dedent(
        f"""
        push script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )
    assert "finished artifacts already on main" in result.stdout
    assert "Library ingest artifacts pushed to main" not in result.stdout
    assert int((tmp_path / "push_count").read_text(encoding="utf-8")) == 1
    _git(work, "fetch", "origin")
    landed = _git(
        work,
        "show",
        "origin/main:docs/data/library/catalogue_explorer/research/BWA/sources/screening_snapshot.json",
    ).stdout
    assert landed == payload
    log = _git(work, "log", "origin/main", "--format=%s").stdout
    assert "keep BWA" not in log


def test_push_still_stops_on_a_non_race_rejection(tmp_path: Path):
    """A hook rejection is not retried as a main-moved race."""
    work, _other = _init_pair(tmp_path)
    dispatch = work / "docs" / "data" / "library" / "euro_ingest_dispatch.json"
    dispatch.write_text('{"mode":"sprint","run":"job"}\n', encoding="utf-8")
    env = _race_env(tmp_path, rejects=0, hard_fails=2, advance=None)
    result = _run_repo_push(work, env, "chore: euro_depth ingest loop [skip ci]")
    assert result.returncode == 1
    assert "after 2 attempts" in result.stderr
    assert "while main moved" not in result.stderr
    assert int((tmp_path / "push_count").read_text(encoding="utf-8")) == 2
