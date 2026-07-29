"""Tier-1 data backup snapshots and restore for committed docs/data assets."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_DATA_ROOT = Path("docs/data")
DEFAULT_BACKUP_DIR = Path("output/backups")

# Paths expensive or impossible to regenerate quickly (see docs/ops/data-backup.md).
TIER1_RELATIVE_PATHS: tuple[str, ...] = (
    "docs/data/library",
    "docs/data/history",
    "docs/data/paper_automation",
    "docs/data/research",
)

TIER2_RELATIVE_PATHS: tuple[str, ...] = (
    "docs/data/engineering_tasks.json",
    "docs/data/latest.json",
    "docs/data/research_model_suggestions.json",
)


@dataclass
class BackupManifest:
    created_at: str
    tier: str
    archive_name: str
    paths: list[str]
    file_count: int
    bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "tier": self.tier,
            "archive_name": self.archive_name,
            "paths": self.paths,
            "file_count": self.file_count,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackupManifest:
        return cls(
            created_at=str(data["created_at"]),
            tier=str(data.get("tier") or "tier1"),
            archive_name=str(data["archive_name"]),
            paths=list(data.get("paths") or []),
            file_count=int(data.get("file_count") or 0),
            bytes=int(data.get("bytes") or 0),
            sha256=str(data.get("sha256") or ""),
        )


@dataclass
class BackupSnapshot:
    archive_path: Path
    manifest_path: Path
    manifest: BackupManifest

    def to_dict(self) -> dict[str, Any]:
        return {
            "archive_path": str(self.archive_path),
            "manifest_path": str(self.manifest_path),
            "manifest": self.manifest.to_dict(),
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_paths(repo_root: Path, relative_paths: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    for rel in relative_paths:
        path = repo_root / rel
        if path.exists():
            found.append(path)
    return found


def _archive_stamp(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    return current.strftime("%Y%m%dT%H%M%SZ")


def create_backup_snapshot(
    *,
    repo_root: Path | None = None,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    tier: str = "tier1",
    include_tier2: bool = False,
    now: datetime | None = None,
) -> BackupSnapshot:
    """Create a gzip tarball of tier-1 (and optional tier-2) committed data."""
    repo_root = Path(repo_root or Path.cwd())
    rel_paths = list(TIER1_RELATIVE_PATHS)
    if include_tier2 or tier == "tier1+tier2":
        rel_paths.extend(TIER2_RELATIVE_PATHS)
    sources = _existing_paths(repo_root, rel_paths)
    if not sources:
        raise FileNotFoundError("No tier backup paths exist under docs/data")

    stamp = _archive_stamp(now)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    archive_path = backup_dir / f"ftse-tier1-{stamp}.tar.gz"
    manifest_path = backup_dir / f"ftse-tier1-{stamp}.manifest.json"

    file_count = 0
    with tarfile.open(archive_path, "w:gz") as tar:
        for source in sources:
            rel = source.relative_to(repo_root).as_posix()
            tar.add(source, arcname=rel, recursive=True)
            if source.is_file():
                file_count += 1
            else:
                file_count += sum(1 for path in source.rglob("*") if path.is_file())

    digest = _sha256_file(archive_path)
    manifest = BackupManifest(
        created_at=(now or datetime.now(UTC)).isoformat(),
        tier="tier1+tier2" if include_tier2 else "tier1",
        archive_name=archive_path.name,
        paths=[path.relative_to(repo_root).as_posix() for path in sources],
        file_count=file_count,
        bytes=archive_path.stat().st_size,
        sha256=digest,
    )
    write_json(manifest_path, manifest.to_dict(), compact=False)
    return BackupSnapshot(archive_path=archive_path, manifest_path=manifest_path, manifest=manifest)


def verify_backup_snapshot(
    archive_path: Path,
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    archive_path = Path(archive_path)
    manifest_path = Path(
        manifest_path
        or archive_path.with_name(archive_path.name.replace(".tar.gz", ".manifest.json"))
    )
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found for {archive_path}")

    manifest = BackupManifest.from_dict(read_json(manifest_path))
    actual = _sha256_file(archive_path)
    ok = actual == manifest.sha256
    return {
        "ok": ok,
        "expected_sha256": manifest.sha256,
        "actual_sha256": actual,
        "manifest": manifest.to_dict(),
    }


def restore_backup_snapshot(
    archive_path: Path,
    *,
    repo_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Extract a backup archive into the repository root (merge overwrite)."""
    repo_root = Path(repo_root or Path.cwd())
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise FileNotFoundError(archive_path)

    restored: list[str] = []
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() and not member.isdir():
                continue
            target = repo_root / member.name
            restored.append(member.name)
            if dry_run:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            target.write_bytes(extracted.read())

    return {
        "archive": str(archive_path),
        "dry_run": dry_run,
        "restored_paths": len(restored),
        "members": restored[:50],
    }


def list_local_snapshots(backup_dir: Path = DEFAULT_BACKUP_DIR) -> list[dict[str, Any]]:
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted(backup_dir.glob("ftse-tier1-*.manifest.json"), reverse=True):
        try:
            manifest = BackupManifest.from_dict(read_json(manifest_path))
        except (OSError, ValueError, TypeError, KeyError):
            continue
        archive_path = backup_dir / manifest.archive_name
        rows.append(
            {
                "manifest_path": str(manifest_path),
                "archive_path": str(archive_path),
                "archive_exists": archive_path.exists(),
                "created_at": manifest.created_at,
                "bytes": manifest.bytes,
                "file_count": manifest.file_count,
            }
        )
    return rows


def upload_backup_snapshot(
    snapshot: BackupSnapshot,
    *,
    s3_uri: str | None = None,
) -> dict[str, Any]:
    """
    Upload archive + manifest to optional object storage.

  Env ``BACKUP_S3_URI`` (e.g. ``s3://my-bucket/ftse-value-investor/``) when ``s3_uri``
    is omitted. Requires AWS CLI on PATH when using S3.
    """
    s3_uri = (s3_uri or os.environ.get("BACKUP_S3_URI") or "").strip()
    if not s3_uri:
        return {"uploaded": False, "reason": "BACKUP_S3_URI not configured"}

    if not shutil.which("aws"):
        raise RuntimeError("aws CLI not found — install AWS CLI or upload artifact manually")

    base = s3_uri.rstrip("/")
    archive_dest = f"{base}/{snapshot.archive_path.name}"
    manifest_dest = f"{base}/{snapshot.manifest_path.name}"
    subprocess.run(["aws", "s3", "cp", str(snapshot.archive_path), archive_dest], check=True)
    subprocess.run(["aws", "s3", "cp", str(snapshot.manifest_path), manifest_dest], check=True)
    return {
        "uploaded": True,
        "archive_dest": archive_dest,
        "manifest_dest": manifest_dest,
    }


def run_restore_drill(
    *,
    repo_root: Path | None = None,
    output_dir: Path = Path("output"),
) -> dict[str, Any]:
    """
    Lightweight post-restore validation: required tier paths exist and history restores.
    """
    from value_investor.storage import restore_committed_run_history

    repo_root = Path(repo_root or Path.cwd())
    missing = [
        rel
        for rel in TIER1_RELATIVE_PATHS
        if not (repo_root / rel).exists()
    ]
    copied = restore_committed_run_history(output_dir, committed_dir=repo_root / "docs/data/history")
    return {
        "ok": not missing,
        "missing_tier_paths": missing,
        "history_files_restored_to_output": copied,
    }
