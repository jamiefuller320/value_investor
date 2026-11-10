"""Point-in-time dating of ``filings_index.json`` for the key-bodies bind.

The strategy book's F9 ``key_filing_bodies`` check counts an index only on
sessions ending after the index was last written by a pass that can add
bodies. Listing-only passes (scan-then-target discovery, listing refresh) add
rows without bodies, so they must not move that date: before this module the
discovery scan stamped ``fetched_at`` with the scan time on every run, and
every buy-tier name failed the check for the previous close.

``bodies_at`` is the date readers use. ``scan_fetched_at`` is what the
discovery merge writes. ``backfill`` restores ``fetched_at`` from git history
for indexes the scan already re-stamped.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import write_json

# Stamps written by passes that can add filing bodies. Listing-only stamps
# (``discovery_scan_at``, ``listing_refresh_at``) are left out on purpose.
BODY_STAMP_KEYS = (
    "fetched_at",
    "ch_refetched_at",
    "ir_refetched_at",
    "investegate_refetched_at",
    "residual_refetched_at",
    "ticker_rns_refetched_at",
    "refetched_at",
)

INDEX_GLOBS = (
    "docs/data/research/*/sources/filings/filings_index.json",
    "docs/data/library/markets/*/screen/research/*/sources/filings/filings_index.json",
)

BACKFILL_REPORT = Path("docs/data/filings_index_dating_backfill.json")


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def bodies_at(payload: dict[str, Any]) -> datetime | None:
    """Latest body-affecting stamp on an index payload, or None without one."""
    stamps = [_parse_dt(payload.get(key)) for key in BODY_STAMP_KEYS]
    found = [stamp for stamp in stamps if stamp is not None]
    return max(found) if found else None


def key_bodies(payload: dict[str, Any] | None) -> bool:
    """Same rule as ``buy_tier_flip_lag._key_bodies_ready`` on a payload."""
    from value_investor.buy_tier_flip_lag import _key_bodies_ready
    from value_investor.research.filings import summarize_filings

    if not payload:
        return False
    summary = dict(payload.get("summary") or {})
    if not summary.get("period_coverage"):
        filings = payload.get("filings")
        if isinstance(filings, list):
            summary = summarize_filings(filings)
    return _key_bodies_ready(
        dict(summary.get("period_coverage") or {}), int(summary.get("total") or 0)
    )


def scan_fetched_at(prior: dict[str, Any] | None, merged: dict[str, Any], now: datetime) -> str:
    """``fetched_at`` for a listing-only merge.

    Keeps the prior stamp unless the merge turned key bodies on, which a
    listing merge should not do; then the merge time is the honest date.
    """
    stamp = None if not prior else prior.get("fetched_at")
    if (
        stamp
        and _parse_dt(stamp) is not None
        and not (key_bodies(merged) and not key_bodies(prior))
    ):
        return str(stamp)
    return now.isoformat()


@dataclass(frozen=True)
class BackfillRow:
    path: str
    previous: str | None
    restored: str
    commit: str


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=data,
        capture_output=True,
        check=True,
    ).stdout


def _history(repo: Path, rev: str) -> dict[str, list[tuple[str, str]]]:
    """Path -> [(commit, committer ISO time)], newest first, for every index file."""
    out = _git(
        repo,
        "log",
        rev,
        "--format=>%H %cI",
        "--name-only",
        "--",
        *INDEX_GLOBS,
        *(f"{pattern}.gz" for pattern in INDEX_GLOBS),
    ).decode()
    versions: dict[str, list[tuple[str, str]]] = defaultdict(list)
    commit = when = ""
    for line in out.splitlines():
        if line.startswith(">"):
            commit, when = line[1:].split(" ", 1)
        elif line.strip():
            versions[line.strip().removesuffix(".gz")].append((commit, when))
    return versions


def _show(repo: Path, commit: str, path: str) -> dict[str, Any] | None:
    import gzip

    for candidate in (path, f"{path}.gz"):
        try:
            blob = _git(repo, "show", f"{commit}:{candidate}")
        except subprocess.CalledProcessError:
            continue
        if candidate.endswith(".gz"):
            blob = gzip.decompress(blob)
        try:
            payload = json.loads(blob)
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def established_at(
    repo: Path, path: str, versions: list[tuple[str, str]]
) -> tuple[str, str] | None:
    """Commit and time from which key bodies have held in every committed version.

    None when the newest committed version lacks key bodies.
    """
    found: tuple[str, str] | None = None
    for commit, when in versions:
        if not key_bodies(_show(repo, commit, path)):
            break
        found = (commit, when)
    return found


def backfill(repo: Path, *, rev: str = "HEAD", apply: bool = False) -> list[BackfillRow]:
    """Move ``fetched_at`` back to when the current key bodies were first committed.

    Only for indexes whose working copy has key bodies, matches the newest
    commit, and carries a later ``fetched_at``. The restored time is the
    committer time of the first version in the unbroken run of key-bodies
    versions, so it is never earlier than the bodies were in the repository.
    """
    from value_investor.storage import read_json, resolve_json_path

    rows: list[BackfillRow] = []
    for path, versions in sorted(_history(repo, rev).items()):
        target = resolve_json_path(repo / path)
        if target is None or not versions:
            continue
        payload = read_json(target)
        if not key_bodies(payload) or payload != _show(repo, versions[0][0], path):
            continue
        found = established_at(repo, path, versions)
        if found is None:
            continue
        commit, when = found
        restored = _parse_dt(when)
        current = _parse_dt(payload.get("fetched_at"))
        if restored is None or (current is not None and current <= restored):
            continue
        rows.append(BackfillRow(path, payload.get("fetched_at"), restored.isoformat(), commit))
        if apply:
            _replace_fetched_at(target, str(payload.get("fetched_at")), restored.isoformat())
    return rows


def _replace_fetched_at(target: Path, previous: str, restored: str) -> None:
    """Swap the one ``fetched_at`` value in place, keeping the file's layout."""
    import gzip
    import re

    from value_investor.storage import read_json

    raw = (
        gzip.decompress(target.read_bytes()) if target.name.endswith(".gz") else target.read_bytes()
    )
    text = raw.decode("utf-8")
    pattern = re.compile(r'("fetched_at"\s*:\s*)"' + re.escape(previous) + '"')
    updated, count = pattern.subn(lambda match: f'{match.group(1)}"{restored}"', text, count=1)
    if count != 1:
        raise ValueError(f"fetched_at not found once in {target}")
    blob = updated.encode("utf-8")
    target.write_bytes(gzip.compress(blob) if target.name.endswith(".gz") else blob)
    if read_json(target).get("fetched_at") != restored:
        raise ValueError(f"fetched_at did not round-trip in {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("backfill", help="restore fetched_at from git history")
    run.add_argument("--repo-root", type=Path, default=Path())
    run.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    repo = args.repo_root.resolve()
    rows = backfill(repo, apply=args.apply)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "applied": bool(args.apply),
        "rule": (
            "fetched_at set to the committer time of the first version in the unbroken "
            "run of committed versions with key bodies; only moved earlier"
        ),
        "count": len(rows),
        "rows": [row.__dict__ for row in rows],
    }
    if args.apply:
        write_json(repo / BACKFILL_REPORT, report, compact=False)
    print(json.dumps({key: report[key] for key in ("applied", "count")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
