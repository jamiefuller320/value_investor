"""Retry spend commits so parallel engineering-agent runs do not fail the PR path."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

from value_investor.agent_model_policy import load_policy, save_policy
from value_investor.engineering_cli import main as engineering_main

SCRIPT = Path("scripts/gha_commit_engineering_spend.sh")
WORKFLOW = Path(".github/workflows/engineering-agent.yml")


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _write_policy(path: Path, *, spend: float, focus: str = "euro_depth") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "focus_market": focus,
                "ladder": {
                    "spend_since_checkpoint_usd": spend,
                    "spend_checkpoint_usd": 60.0,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _policy_spend(path: Path) -> float:
    return float(json.loads(path.read_text(encoding="utf-8"))["ladder"]["spend_since_checkpoint_usd"])


def _seed_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "clone", str(remote), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "test")

    _write_policy(work / "docs" / "data" / "library" / "policy.json", spend=10.0)
    (work / "src").mkdir()
    (work / "src" / "keep.py").write_text("value = 1\n", encoding="utf-8")
    script = work / "scripts" / "gha_commit_engineering_spend.sh"
    script.parent.mkdir()
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    increment = work / "scripts" / "increment_spend.py"
    increment.write_text(
        textwrap.dedent(
            """\
            import json
            from pathlib import Path
            path = Path("docs/data/library/policy.json")
            data = json.loads(path.read_text(encoding="utf-8"))
            ladder = data.setdefault("ladder", {})
            ladder["spend_since_checkpoint_usd"] = (
                float(ladder.get("spend_since_checkpoint_usd") or 0.0) + 1.2
            )
            path.write_text(json.dumps(data, indent=2) + "\\n", encoding="utf-8")
            print(json.dumps({"spend_since_checkpoint_usd": ladder["spend_since_checkpoint_usd"]}))
            """
        ),
        encoding="utf-8",
    )

    _git(work, "add", "docs", "src", "scripts")
    _git(work, "commit", "-m", "seed")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-u", "origin", "main")
    return remote, work


def _install_pre_receive(remote: Path, *, reject_first_n: int) -> Path:
    hook = remote / "hooks" / "pre-receive"
    count = remote / "reject_count"
    count.write_text("0\n", encoding="utf-8")
    hook.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            count_file="{count}"
            n=$(cat "$count_file")
            n=$((n + 1))
            echo "$n" > "$count_file"
            if [ "$n" -le {int(reject_first_n)} ]; then
              echo "test race: reject push $n" >&2
              exit 1
            fi
            exit 0
            """
        ),
        encoding="utf-8",
    )
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    return count


def _run_script(work: Path, *, attempts: str = "5") -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GHA_COMMIT_ATTEMPTS": attempts,
        "GHA_COMMIT_SLEEP_BASE": "0",
        "RECORD_SPEND_CMD": "python3 scripts/increment_spend.py",
    }
    return subprocess.run(
        ["bash", "scripts/gha_commit_engineering_spend.sh"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_spend_commit_retries_after_main_race(tmp_path: Path):
    remote, work = _seed_repo(tmp_path)
    _install_pre_receive(remote, reject_first_n=1)
    (work / "src" / "keep.py").write_text("value = 2\n", encoding="utf-8")
    (work / "docs" / "data" / "library" / "policy.json").write_text(
        json.dumps({"ladder": {"spend_since_checkpoint_usd": 10.0, "stale": True}}, indent=2)
        + "\n",
        encoding="utf-8",
    )

    result = _run_script(work)
    assert result.returncode == 0, textwrap.dedent(
        f"""
        spend retry script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )
    assert "attempt 2/5" in result.stdout
    assert (work / "src" / "keep.py").read_text(encoding="utf-8") == "value = 2\n"
    latest = tmp_path / "latest"
    _git(tmp_path, "clone", str(remote), str(latest))
    assert _policy_spend(latest / "docs" / "data" / "library" / "policy.json") == 11.2
    assert "stale" not in (latest / "docs" / "data" / "library" / "policy.json").read_text(
        encoding="utf-8"
    )


def test_spend_commit_reapplies_increment_on_latest_policy(tmp_path: Path):
    remote, work = _seed_repo(tmp_path)
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(remote), str(other))
    _git(other, "config", "user.email", "other@example.com")
    _git(other, "config", "user.name", "other")
    _write_policy(
        other / "docs" / "data" / "library" / "policy.json",
        spend=15.0,
        focus="sp500",
    )
    _git(other, "add", "docs/data/library/policy.json")
    _git(other, "commit", "-m", "concurrent policy")
    _git(other, "push", "origin", "main")

    (work / "src" / "keep.py").write_text("value = 9\n", encoding="utf-8")
    result = _run_script(work)
    assert result.returncode == 0, result.stderr
    latest = tmp_path / "latest"
    _git(tmp_path, "clone", str(remote), str(latest))
    payload = json.loads(
        (latest / "docs" / "data" / "library" / "policy.json").read_text(encoding="utf-8")
    )
    assert payload["focus_market"] == "sp500"
    assert payload["ladder"]["spend_since_checkpoint_usd"] == 16.2
    assert (work / "src" / "keep.py").read_text(encoding="utf-8") == "value = 9\n"


def test_spend_commit_restores_work_when_retries_exhausted(tmp_path: Path):
    remote, work = _seed_repo(tmp_path)
    _install_pre_receive(remote, reject_first_n=9)
    (work / "src" / "keep.py").write_text("value = 3\n", encoding="utf-8")

    result = _run_script(work, attempts="2")
    assert result.returncode == 1
    assert "Could not push engineering spend" in result.stderr
    assert (work / "src" / "keep.py").read_text(encoding="utf-8") == "value = 3\n"


def test_record_spend_cli_increments_policy(tmp_path: Path, capsys):
    path = tmp_path / "policy.json"
    save_policy(load_policy(path), path)
    before = load_policy(path)
    assert engineering_main(["--policy", str(path), "--json", "record-spend", "--estimated-usd", "1.2"]) == 0
    payload = json.loads(capsys.readouterr().out)
    after = load_policy(path)
    assert payload["estimated_usd"] == 1.2
    assert after["budget"]["estimated_spend_usd_this_week"] == round(
        float(before["budget"].get("estimated_spend_usd_this_week") or 0.0) + 1.2,
        4,
    )


def test_engineering_agent_workflow_uses_spend_retry() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/gha_commit_engineering_spend.sh" in text
    assert "continue-on-error: true" in text
    spend_idx = text.index("Commit ad-hoc spend to main")
    next_commit = text.find("uses: stefanzweifel/git-auto-commit-action@v6", spend_idx)
    assert next_commit == -1 or next_commit > text.find("Clear stale engineering branch", spend_idx)
    assert "file_pattern: docs/data/library/policy.json" not in text
