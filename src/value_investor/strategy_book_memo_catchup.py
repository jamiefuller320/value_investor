"""Replay ``memo_not_ready_budget`` skips and publish the memos.

The scheduled job does not revisit a close after ``last_session`` moves on.
A budget skip is still a deferral, but the library FCF figure lives on
``latest_signals.csv``, and a later screen snapshot is not in force for the
old session. This replay checks out the ``latest_signals.csv`` and
``latest_summary.json`` recorded on the skip (the bytes that passed), requests
the memo, then puts those two files back.

It does not walk the forward book, place orders, or set ``influences_live``.
Screen snapshots and ``policy.json`` are not published. New log rows are
appended onto the target ref so a stale checkout cannot replace the log.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from value_investor.strategy_book_signals import repo_paths

_SCREEN_NAMES = ("latest_signals.csv", "latest_summary.json")
_RESEARCH_NAMES = {"research.json", "research.md", "timeline.json", "agent_id.txt"}
_VENDOR_MARKERS = ("eodhd", "sharadar")


def _log_identity(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("market") or ""),
        str(row.get("ticker") or ""),
        str(row.get("kind") or ""),
        str(row.get("session") or ""),
        str(row.get("action") or ""),
    )


def _pinned_screen_path(path: str) -> bool:
    text = str(path or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or text.startswith("~"):
        return False
    parts = text.split("/")
    if ".." in parts:
        return False
    if not text.startswith("docs/data/library/markets/"):
        return False
    return parts[-1] in _SCREEN_NAMES


def _commit_sha(value: str) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 40 and all(ch in "0123456789abcdef" for ch in text)


def plan_budget_skip_catchup(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sessions and pinned screen files for budget skips that were never requested."""
    requested = {
        (
            str(row.get("market") or ""),
            str(row.get("ticker") or ""),
            str(row.get("kind") or ""),
            str(row.get("session") or ""),
        )
        for row in rows
        if row.get("action") == "requested"
    }
    sessions: dict[str, list[str]] = {}
    screens: dict[str, str] = {}
    pending: list[dict[str, str]] = []
    for row in rows:
        if row.get("action") != "skipped" or row.get("skip_reason") != "memo_not_ready_budget":
            continue
        market = str(row.get("market") or "").strip()
        ticker = str(row.get("ticker") or "").strip()
        kind = str(row.get("kind") or "").strip()
        session = str(row.get("session") or "").strip()
        if not market or not ticker or not session:
            continue
        if (market, ticker, kind, session) in requested:
            continue
        bucket = sessions.setdefault(market, [])
        if session not in bucket:
            bucket.append(session)
        pending.append({"market": market, "ticker": ticker, "kind": kind, "session": session})
        commit = str(row.get("data_commit") or "").strip().lower()
        for item in row.get("inputs") or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if not _pinned_screen_path(path):
                continue
            if not _commit_sha(commit):
                raise ValueError(f"budget skip for {ticker} has no data_commit")
            previous = screens.get(path)
            if previous is not None and previous != commit:
                raise ValueError(f"{path} is pinned to two commits")
            screens[path] = commit
    for market in sessions:
        sessions[market].sort()
    pending.sort(key=lambda item: (item["market"], item["session"], item["ticker"]))
    return {
        "sessions_by_market": sessions,
        "screen_snapshots": [{"path": path, "commit": screens[path]} for path in sorted(screens)],
        "pending": pending,
    }


def is_publishable_artifact(path: str) -> bool:
    """Memo and usage-shard paths. Not vendor files, screen snapshots, or policy."""
    text = str(path or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or ".." in text.split("/"):
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in _VENDOR_MARKERS):
        return False
    parts = text.split("/")
    if "sources" in parts or "charts" in parts:
        return False
    if text == "docs/data/library/policy.json" or text.endswith("/policy.json"):
        return False
    if parts[-1] in _SCREEN_NAMES:
        return False
    if text == "docs/data/strategy_book_memo_log.jsonl":
        return False
    if parts[-1] in _RESEARCH_NAMES and "/research/" in f"/{text}":
        return text.startswith("docs/data/") or text.startswith("docs/research/")
    if text == "docs/data/agent_usage_log.jsonl":
        return True
    return text.startswith("docs/data/agent_usage/") and text.endswith(".jsonl")


def merge_log_text(existing: str, new_rows: list[dict[str, Any]]) -> str:
    """Append log rows that are not already present. Keep the existing text."""
    seen: set[tuple[str, str, str, str, str]] = set()
    body = existing
    for line in existing.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            seen.add(_log_identity(row))
    if body and not body.endswith("\n"):
        body += "\n"
    for row in new_rows:
        if not isinstance(row, dict):
            continue
        identity = _log_identity(row)
        if identity in seen:
            continue
        body += json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        seen.add(identity)
    return body


def appended_suffix(before: bytes, after: bytes) -> bytes | None:
    """Bytes added at the end of a shard. A rewrite is not an append."""
    if after == before:
        return b""
    if not after.startswith(before):
        return None
    return after[len(before) :]


def _git(
    repo_root: Path, args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
    )


def restore_pinned_screens(repo_root: Path, snapshots: list[dict[str, str]]) -> list[str]:
    restored: list[str] = []
    try:
        for item in snapshots:
            path = str(item.get("path") or "")
            commit = str(item.get("commit") or "").lower()
            if not _pinned_screen_path(path) or not _commit_sha(commit):
                raise ValueError(f"refusing to check out {path} at {commit}")
            _git(repo_root, ["checkout", commit, "--", path])
            restored.append(path)
    except Exception:
        drop_pinned_screens(repo_root, restored)
        raise
    return restored


def drop_pinned_screens(repo_root: Path, paths: list[str]) -> None:
    safe = [path for path in paths if _pinned_screen_path(path)]
    if len(safe) != len(paths):
        raise ValueError("refusing to restore a path that is not a pinned screen snapshot")
    if not safe:
        return
    _git(repo_root, ["restore", "--source=HEAD", "--staged", "--worktree", "--", *safe])


def _read_log(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        row = json.loads(text)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _usage_files(repo_root: Path) -> list[Path]:
    found: list[Path] = []
    shard_dir = repo_root / "docs" / "data" / "agent_usage"
    if shard_dir.is_dir():
        found.extend(path for path in shard_dir.rglob("*.jsonl") if path.is_file())
    legacy = repo_root / "docs" / "data" / "agent_usage_log.jsonl"
    if legacy.is_file():
        found.append(legacy)
    return found


def _snapshot_bytes(repo_root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for path in _usage_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        if is_publishable_artifact(rel):
            out[rel] = path.read_bytes()
    return out


def _write_manifest(workdir: Path, payload: dict[str, Any]) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_catchup(repo_root: Path, workdir: Path) -> dict[str, Any]:
    """Request deferred budget skips. Copies publishable artifacts into ``workdir``."""
    from value_investor.strategy_book_memo_job import run_strategy_book_memo_job

    if not os.environ.get("CURSOR_API_KEY", "").strip():
        raise SystemExit("CURSOR_API_KEY missing; refusing to log a runner error")
    root = repo_root.resolve()
    paths = repo_paths(root)
    plan = plan_budget_skip_catchup(_read_log(paths.memo_log))
    if not plan["pending"]:
        result = {"pending": [], "logged": [], "written_paths": [], "not_requested": []}
        _write_manifest(workdir, {"log_rows": [], "files": [], "result": result})
        return result
    before_usage = _snapshot_bytes(root)
    restored = restore_pinned_screens(root, plan["screen_snapshots"])
    try:
        summary = run_strategy_book_memo_job(
            repo_root=root,
            markets=sorted(plan["sessions_by_market"]),
            sessions_by_market=plan["sessions_by_market"],
            persist=True,
        )
    finally:
        drop_pinned_screens(root, restored)
    logged = [row for row in summary.get("logged") or [] if isinstance(row, dict)]
    requested = {
        (
            str(row.get("market") or ""),
            str(row.get("ticker") or ""),
            str(row.get("kind") or ""),
            str(row.get("session") or ""),
        )
        for row in logged
        if row.get("action") == "requested"
    }
    not_requested = [
        item
        for item in plan["pending"]
        if (item["market"], item["ticker"], item["kind"], item["session"]) not in requested
    ]
    files: list[dict[str, str]] = []
    for rel in summary.get("written_paths") or []:
        text = str(rel)
        if not is_publishable_artifact(text):
            continue
        source = root / text
        if not source.is_file():
            continue
        dest = workdir / "files" / text
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
        files.append({"path": text, "mode": "replace"})
    after_usage = _snapshot_bytes(root)
    for rel, after in after_usage.items():
        suffix = appended_suffix(before_usage.get(rel, b""), after)
        if not suffix:
            continue
        dest = workdir / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(suffix)
        files.append({"path": rel, "mode": "append"})
    result = {
        "pending": plan["pending"],
        "logged": logged,
        "written_paths": [item["path"] for item in files if item["mode"] == "replace"],
        "not_requested": not_requested,
        "influences_live": False,
    }
    _write_manifest(workdir, {"log_rows": logged, "files": files, "result": result})
    return result


def apply_saved_artifacts(repo_root: Path, workdir: Path) -> list[str]:
    """Merge a saved catch-up onto the checkout. Does not push."""
    manifest_path = workdir / "manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = repo_root.resolve()
    log_path = root / "docs" / "data" / "strategy_book_memo_log.jsonl"
    existing = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    merged = merge_log_text(existing, list(manifest.get("log_rows") or []))
    changed: list[str] = []
    if merged != existing:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(merged, encoding="utf-8")
        changed.append("docs/data/strategy_book_memo_log.jsonl")
    for item in manifest.get("files") or []:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path") or "")
        mode = str(item.get("mode") or "")
        if not is_publishable_artifact(rel):
            raise ValueError(f"refusing to publish {rel}")
        blob = (workdir / "files" / rel).read_bytes()
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            previous = dest.read_bytes() if dest.is_file() else b""
            if blob and not previous.endswith(blob):
                dest.write_bytes(previous + blob)
                changed.append(rel)
        elif mode == "replace":
            if not dest.is_file() or dest.read_bytes() != blob:
                dest.write_bytes(blob)
                changed.append(rel)
        else:
            raise ValueError(f"unknown publish mode {mode}")
    return changed


def publish_main(repo_root: Path, workdir: Path) -> str:
    """Commit saved artifacts onto ``origin/main`` and push. Returns pushed or noop."""
    manifest_path = workdir / "manifest.json"
    if not manifest_path.is_file():
        return "noop"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("log_rows") and not manifest.get("files"):
        return "noop"
    root = repo_root.resolve()
    _git(root, ["config", "user.name", "github-actions[bot]"])
    _git(root, ["config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    for attempt in range(1, 6):
        # Artifacts already live in workdir. Drop the job checkout so main can be checked out.
        _git(root, ["reset", "--hard", "HEAD"])
        _git(root, ["clean", "-fd", "--", "docs/data", "docs/research"])
        _git(root, ["fetch", "origin", "main"])
        _git(root, ["checkout", "-B", "memo-catchup-publish", "origin/main"])
        changed = apply_saved_artifacts(root, workdir)
        if not changed:
            return "noop"
        _git(root, ["add", "--", *changed])
        diff = _git(root, ["diff", "--cached", "--quiet"], check=False)
        if diff.returncode == 0:
            return "noop"
        _git(
            root,
            [
                "commit",
                "-m",
                "chore: catch up 2026-W47 budget-skipped strategy-book memos [skip ci]",
            ],
        )
        push = _git(root, ["push", "origin", "HEAD:main"], check=False)
        if push.returncode == 0:
            return "pushed"
        print(push.stderr or push.stdout)
        print(f"push rejected on attempt {attempt}")
    raise SystemExit("could not publish the catch-up memos onto main")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Catch up strategy-book memos skipped for budget")
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--publish-main", action="store_true")
    args = parser.parse_args(argv)
    if args.publish_main:
        print(publish_main(args.repo_root, args.workdir))
        return 0
    result = run_catchup(args.repo_root, args.workdir)
    print(json.dumps(result, indent=2, default=str))
    errors = [
        row
        for row in result.get("logged") or []
        if str(row.get("skip_reason") or "").startswith("runner_error")
    ]
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
