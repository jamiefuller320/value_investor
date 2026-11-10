"""Dated versions of the decline and sector gate stores.

The live stores (``operating_decline_gate.json``, ``sector_headwind_gate.json``)
are overwritten in place each refresh, with ``as_of`` set to the run date. A
verdict applies only to sessions strictly after its date (strategy-book
registration, section 2 "Gates"), so a reader scoring an earlier close needs
the version that existed then. Each refresh therefore also writes a gzipped
copy of the verdict maps to ``gate_history/<kind>/<date>.json.gz`` next to the
store. Readers take the latest version dated strictly before the session.

A version's date is the later of the store's ``as_of`` and the UTC day it was
generated, so a store generated after its ``as_of`` (the sector store dated to
a screen date in early November) is never applied before it existed.

Bootstrap: ``python -m value_investor.gate_store_history backfill-git`` replays
the committed store files from git history into the same directory.
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

DECLINE_KIND = "operating_decline"
SECTOR_KIND = "sector_headwind"
HISTORY_DIR_NAME = "gate_history"
# About 13 months of daily refreshes. The forward book rebuilds from its start
# date, so pruning must not reach a session it still walks (deferred L699).
MAX_VERSIONS = 400
STALE_AFTER_DAYS = 3
HISTORY_STALE_TITLE = "Gate verdict history stale"

_KEEP_KEYS = {
    DECLINE_KIND: ("schema_version", "generated_at", "as_of", "names"),
    SECTOR_KIND: ("schema_version", "generated_at", "as_of", "names", "names_by_market"),
}
_SUFFIX = ".json.gz"


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) > 10:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return stamp.astimezone(UTC).date() if stamp.tzinfo else stamp.date()
        return date.fromisoformat(text)
    except ValueError:
        return None


def version_date(payload: dict[str, Any] | None) -> date | None:
    """Later of the store ``as_of`` and the UTC day it was generated. None without ``as_of``."""
    if not isinstance(payload, dict):
        return None
    as_of = _day(payload.get("as_of"))
    if as_of is None:
        return None
    generated = _day(payload.get("generated_at"))
    return max(as_of, generated) if generated is not None else as_of


def history_dir(store_path: Path, kind: str) -> Path:
    return Path(store_path).parent / HISTORY_DIR_NAME / kind


def _generated(payload: dict[str, Any] | None) -> str:
    return str((payload or {}).get("generated_at") or "")


def _read_version(path: Path) -> dict[str, Any] | None:
    try:
        if path.name.endswith(_SUFFIX):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, EOFError):
        return None
    return payload if isinstance(payload, dict) else None


def archive_gate_version(
    store_path: Path,
    kind: str,
    payload: dict[str, Any],
    *,
    source: str = "refresh",
    max_versions: int = MAX_VERSIONS,
) -> Path | None:
    """Write the dated copy of one store payload. Returns the file, or None when skipped.

    One file per version date. A later refresh the same day replaces it; an
    older ``generated_at`` never replaces a newer one.
    """
    day = version_date(payload)
    if day is None or kind not in _KEEP_KEYS:
        return None
    folder = history_dir(store_path, kind)
    path = folder / f"{day.isoformat()}{_SUFFIX}"
    if path.is_file() and _generated(_read_version(path)) > _generated(payload):
        return None
    record = {key: payload.get(key) for key in _KEEP_KEYS[kind]}
    record["version_date"] = day.isoformat()
    record["source"] = source
    folder.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    tmp = path.with_name(path.name + ".tmp")
    # mtime=0 keeps identical payloads byte-identical, so a rerun is no git change.
    with tmp.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as handle:
        handle.write(blob.encode("utf-8"))
    tmp.replace(path)
    _prune(folder, max_versions)
    return path


def _version_files(folder: Path) -> list[tuple[date, Path]]:
    if not folder.is_dir():
        return []
    found: list[tuple[date, Path]] = []
    for path in folder.glob(f"*{_SUFFIX}"):
        day = _day(path.name[: -len(_SUFFIX)])
        if day is not None:
            found.append((day, path))
    return sorted(found)


def _prune(folder: Path, max_versions: int) -> None:
    files = _version_files(folder)
    for _, path in files[: max(0, len(files) - max_versions)]:
        path.unlink(missing_ok=True)


def _reader_view(raw: dict[str, Any], kind: str, day: date, path: Path) -> dict[str, Any]:
    """``as_of`` becomes the version date so the in-force rule reads one date.

    Sector stores before 2026-11-05 have only the flat FTSE ``names`` map;
    readers look up ``names_by_market``, so it is rebuilt from each entry's market.
    """
    view = {**raw, "as_of": day.isoformat(), "version_path": str(path)}
    if kind == SECTOR_KIND and not raw.get("names_by_market"):
        grouped: dict[str, dict[str, Any]] = {}
        for ticker, entry in (raw.get("names") or {}).items():
            if isinstance(entry, dict) and entry.get("market"):
                grouped.setdefault(str(entry["market"]), {})[ticker] = entry
        view["names_by_market"] = grouped
    return view


class GateVersion:
    """One dated store version. The payload is read on first use."""

    def __init__(
        self, kind: str, day: date, path: Path, payload: dict[str, Any] | None = None
    ) -> None:
        self.kind = kind
        self.day = day
        self.path = path
        self._payload = None if payload is None else _reader_view(payload, kind, day, path)

    @property
    def payload(self) -> dict[str, Any]:
        if self._payload is None:
            raw = _read_version(self.path) or {}
            self._payload = _reader_view(raw, self.kind, self.day, self.path)
        return self._payload

    def release(self) -> None:
        self._payload = None


def load_versions(store_path: Path, kind: str) -> list[GateVersion]:
    """Archived versions plus the live store, oldest first, one per date.

    The live store replaces the archived copy of its date only when it was
    generated later (it normally is that copy).
    """
    by_day = {
        day: GateVersion(kind, day, path)
        for day, path in _version_files(history_dir(store_path, kind))
    }
    live_path = Path(store_path)
    live = _read_version(live_path) if live_path.is_file() else None
    day = version_date(live)
    if live is not None and day is not None:
        held = by_day.get(day)
        if held is None or _generated(live) > _generated(_read_version(held.path)):
            by_day[day] = GateVersion(kind, day, live_path, live)
    return [by_day[day] for day in sorted(by_day)]


def in_force(versions: list[GateVersion], session: date) -> GateVersion | None:
    """Latest version dated strictly before ``session``."""
    chosen = None
    for version in versions:
        if version.day >= session:
            break
        chosen = version
    return chosen


def _payload_or_stub(versions: list[GateVersion], session: date) -> dict[str, Any] | None:
    version = in_force(versions, session)
    if version is not None:
        return version.payload
    if not versions:
        return None
    return {"as_of": versions[0].day.isoformat(), "names": {}, "names_by_market": {}}


def _advance(versions: list[GateVersion], index: int, day: date) -> int:
    """Index of the last version dated on or before ``day``; releases the one left behind."""
    moved = index
    while moved + 1 < len(versions) and versions[moved + 1].day <= day:
        moved += 1
    if moved != index and index >= 0:
        versions[index].release()
    return moved


def _entry_keys(
    decline: dict[str, Any] | None, sector: dict[str, Any] | None
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for ticker, entry in ((decline or {}).get("names") or {}).items():
        if isinstance(entry, dict) and entry.get("market"):
            keys.add((str(entry["market"]), str(ticker)))
    for market, names in ((sector or {}).get("names_by_market") or {}).items():
        if isinstance(names, dict):
            keys.update((str(market), str(ticker)) for ticker in names)
    return keys


class GateHistory:
    """Decline and sector versions for one run. Never reads a version dated on or after a session."""

    def __init__(self, decline: list[GateVersion], sector: list[GateVersion]) -> None:
        self.decline = decline
        self.sector = sector
        self._facts: dict[tuple[str, str], list[Any]] | None = None
        self._since: date | None = None

    @classmethod
    def load(cls, decline_store: Path, sector_store: Path) -> GateHistory:
        return cls(
            load_versions(decline_store, DECLINE_KIND), load_versions(sector_store, SECTOR_KIND)
        )

    def in_force(self, session: date) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Payloads in force at ``session``.

        With versions but none in force, the payload is a stub holding only the
        earliest version date and no verdicts, so readers report why
        (``verdict_not_in_force`` / ``store_after_session``) and cannot read a
        later verdict. With no versions at all it is None.
        """
        return _payload_or_stub(self.decline, session), _payload_or_stub(self.sector, session)

    def paths_in_force(self, session: date) -> list[Path]:
        return [
            version.path
            for version in (in_force(self.decline, session), in_force(self.sector, session))
            if version is not None
        ]

    def index_facts(self, since: date | None = None) -> None:
        """Build every name's ``GateFact`` list in one pass, one version in memory at a time.

        A fact per version date pairs the decline and sector versions dated on
        or before it. With ``since``, versions older than the one in force at
        ``since`` are skipped.
        """
        from value_investor.strategy_book_replay import _gate_for

        days = sorted({v.day for v in self.decline} | {v.day for v in self.sector})
        if since is not None:
            floor = max((day for day in days if day < since), default=None)
            days = [day for day in days if floor is None or day >= floor]
        facts: dict[tuple[str, str], list[Any]] = {}
        d_index = s_index = -1
        for day in days:
            d_index = _advance(self.decline, d_index, day)
            s_index = _advance(self.sector, s_index, day)
            decline = self.decline[d_index].payload if d_index >= 0 else None
            sector = self.sector[s_index].payload if s_index >= 0 else None
            for market, ticker in _entry_keys(decline, sector):
                found = _gate_for(decline, sector, market, ticker)
                if found:
                    facts.setdefault((market, ticker.upper()), []).extend(found)
        self._facts = facts
        self._since = since

    def facts_for(self, market: str, ticker: str) -> list[Any]:
        """``GateFact`` list for one name, oldest first."""
        if self._facts is None:
            self.index_facts()
        assert self._facts is not None
        return list(self._facts.get((market, str(ticker).strip().upper()), []))


def history_findings(
    store_path: Path, kind: str, *, today: date | None = None
) -> list[dict[str, Any]]:
    """Warn when the newest archived version is missing or older than ``STALE_AFTER_DAYS``."""
    folder = history_dir(store_path, kind)
    files = _version_files(folder)
    day = today or datetime.now(UTC).date()
    newest = files[-1][0] if files else None
    if newest is not None and (day - newest).days <= STALE_AFTER_DAYS:
        return []
    detail = "no archived version" if newest is None else f"newest version {newest.isoformat()}"
    return [
        {
            "severity": "warn",
            "category": "research",
            "title": HISTORY_STALE_TITLE,
            "summary": (
                f"{kind}: {detail} in {folder.as_posix()}. The strategy book reads the gate "
                "version dated strictly before each signal session; without a recent one "
                "signals fail parts 2/3. Check the gate refresh step."
            ),
            "auto_fixable": False,
        }
    ]


def _git_versions(repo_root: Path, rel: str) -> list[tuple[str, dict[str, Any]]]:
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--", rel],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    out: list[tuple[str, dict[str, Any]]] = []
    for sha in reversed(shas):
        shown = subprocess.run(
            ["git", "show", f"{sha}:{rel}"], cwd=repo_root, capture_output=True, text=True
        )
        if shown.returncode != 0:
            continue
        try:
            payload = json.loads(shown.stdout)
        except ValueError:
            continue
        if isinstance(payload, dict):
            out.append((sha, payload))
    return out


def backfill_from_git(repo_root: Path, store_path: Path, kind: str) -> list[str]:
    """Archive every committed version of one store. A date keeps its newest ``generated_at``."""
    root = Path(repo_root)
    rel = Path(store_path).as_posix()
    written: set[str] = set()
    for sha, payload in _git_versions(root, rel):
        path = archive_gate_version(root / rel, kind, payload, source=f"git:{sha[:12]}")
        if path is not None:
            written.add(path.name)
    return sorted(written)


DEFAULT_DECLINE_STORE = Path("docs/data/operating_decline_gate.json")
DEFAULT_SECTOR_STORE = Path("docs/data/sector_headwind_gate.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dated gate store versions")
    sub = parser.add_subparsers(dest="command", required=True)
    back = sub.add_parser("backfill-git", help="Archive committed store versions from git history")
    back.add_argument("--repo-root", type=Path, default=Path())
    show = sub.add_parser("in-force", help="Version dates in force for a session")
    show.add_argument("session")
    show.add_argument("--repo-root", type=Path, default=Path())
    args = parser.parse_args(argv)
    if args.command == "backfill-git":
        result: dict[str, Any] = {
            DECLINE_KIND: backfill_from_git(args.repo_root, DEFAULT_DECLINE_STORE, DECLINE_KIND),
            SECTOR_KIND: backfill_from_git(args.repo_root, DEFAULT_SECTOR_STORE, SECTOR_KIND),
        }
    else:
        session = date.fromisoformat(args.session)
        history = GateHistory.load(
            args.repo_root / DEFAULT_DECLINE_STORE, args.repo_root / DEFAULT_SECTOR_STORE
        )
        decline, sector = history.in_force(session)
        result = {
            "session": session.isoformat(),
            DECLINE_KIND: None if decline is None else decline.get("as_of"),
            SECTOR_KIND: None if sector is None else sector.get("as_of"),
        }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
