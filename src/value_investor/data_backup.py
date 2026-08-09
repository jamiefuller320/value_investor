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
DEFAULT_BACKUP_EMAIL_TO = "intellaigence101@gmail.com"
# Keep chunks below Gmail's 25MB attachment limit after base64 encoding.
DEFAULT_EMAIL_CHUNK_BYTES = 15 * 1024 * 1024

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


def backup_email_to() -> str:
    return (os.environ.get("BACKUP_EMAIL_TO") or DEFAULT_BACKUP_EMAIL_TO).strip()


def split_archive_for_email(
    archive_path: Path,
    *,
    chunk_bytes: int = DEFAULT_EMAIL_CHUNK_BYTES,
    output_dir: Path | None = None,
) -> list[Path]:
    """Split a tarball into numbered parts sized for SMTP attachment limits."""
    archive_path = Path(archive_path)
    output_dir = Path(output_dir or archive_path.parent)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = archive_path.name
    parts: list[Path] = []
    with archive_path.open("rb") as handle:
        index = 1
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            part_path = output_dir / f"{stem}.part{index:03d}"
            part_path.write_bytes(chunk)
            parts.append(part_path)
            index += 1
    return parts


def merge_email_chunks(chunk_paths: Iterable[Path], output_path: Path) -> Path:
    """Reassemble emailed backup parts into a single tarball."""
    ordered = sorted(Path(path) for path in chunk_paths)

    def _part_index(path: Path) -> int:
        suffix = path.name.rsplit(".part", 1)[-1]
        return int(suffix)

    ordered.sort(key=_part_index)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as out:
        for part_path in ordered:
            out.write(part_path.read_bytes())
    return output_path


def send_backup_snapshot_email(
    snapshot: BackupSnapshot,
    *,
    email_to: str | None = None,
    chunk_bytes: int = DEFAULT_EMAIL_CHUNK_BYTES,
) -> dict[str, Any]:
    """
    Email manifest + chunked archive to an off-GitHub mailbox.

    Large snapshots are split into multiple messages to stay under common SMTP
  attachment limits (~25MB for Gmail).
    """
    from value_investor.emailer import EmailConfig, send_email

    to_addr = (email_to or backup_email_to()).strip()
    if not to_addr:
        raise ValueError("BACKUP_EMAIL_TO is empty")

    config = EmailConfig.from_env(email_to=to_addr)

    parts = split_archive_for_email(
        snapshot.archive_path,
        chunk_bytes=chunk_bytes,
        output_dir=snapshot.archive_path.parent,
    )
    stamp = snapshot.manifest.created_at[:10]
    manifest_payload = snapshot.manifest_path.read_bytes()
    manifest_name = snapshot.manifest_path.name

    manifest_text = (
        f"FTSE tier-1 backup manifest ({stamp})\n\n"
        f"Archive: {snapshot.manifest.archive_name}\n"
        f"Bytes: {snapshot.manifest.bytes:,}\n"
        f"Files: {snapshot.manifest.file_count:,}\n"
        f"SHA256: {snapshot.manifest.sha256}\n"
        f"Email parts: {len(parts)}\n\n"
        "Restore from emailed chunks:\n"
        "  1. Save all .partNNN attachments to one folder\n"
        f"  2. ftse-data-backup reassemble --output {snapshot.manifest.archive_name} *.part*\n"
        f"  3. ftse-data-backup verify {snapshot.manifest.archive_name}\n"
        f"  4. ftse-data-backup restore {snapshot.manifest.archive_name}\n"
    )
    send_email(
        subject=f"FTSE tier-1 backup manifest ({stamp})",
        text_body=manifest_text,
        attachments=[(manifest_name, manifest_payload, "application/json")],
        config=config,
    )

    for index, part_path in enumerate(parts, start=1):
        part_text = (
            f"FTSE tier-1 backup part {index}/{len(parts)} ({stamp})\n\n"
            f"Archive: {snapshot.manifest.archive_name}\n"
            f"Part file: {part_path.name}\n"
            f"SHA256 (full archive): {snapshot.manifest.sha256}\n"
        )
        send_email(
            subject=f"FTSE tier-1 backup part {index}/{len(parts)} ({stamp})",
            text_body=part_text,
            attachments=[(part_path.name, part_path.read_bytes(), "application/gzip")],
            config=config,
        )

    return {
        "emailed": True,
        "email_to": to_addr,
        "parts": len(parts),
        "chunk_bytes": chunk_bytes,
        "part_paths": [str(path) for path in parts],
    }


def snapshot_from_payload(data: dict[str, Any]) -> BackupSnapshot:
    """Rebuild a ``BackupSnapshot`` from ``snapshot --json`` or ``deliver`` payload."""
    manifest = BackupManifest.from_dict(data.get("manifest") or {})
    archive_path = Path(data.get("archive_path") or "")
    manifest_path = Path(data.get("manifest_path") or "")
    if not archive_path or not manifest_path:
        raise ValueError("payload missing archive_path or manifest_path")
    return BackupSnapshot(
        archive_path=archive_path,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def try_upload_backup_snapshot(
    snapshot: BackupSnapshot,
    *,
    s3_uri: str | None = None,
) -> dict[str, Any]:
    """Upload snapshot; return a result dict instead of raising on failure."""
    try:
        return upload_backup_snapshot(snapshot, s3_uri=s3_uri)
    except RuntimeError as exc:
        logger.warning("Backup S3 upload failed: %s", exc)
        return {
            "uploaded": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


def try_send_backup_snapshot_email(
    snapshot: BackupSnapshot,
    *,
    email_to: str | None = None,
    chunk_bytes: int = DEFAULT_EMAIL_CHUNK_BYTES,
) -> dict[str, Any]:
    """Email snapshot; return a result dict instead of raising on SMTP/config errors."""
    try:
        return send_backup_snapshot_email(
            snapshot,
            email_to=email_to,
            chunk_bytes=chunk_bytes,
        )
    except (ValueError, OSError) as exc:
        logger.warning("Backup email failed: %s", exc)
        return {
            "emailed": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
    except Exception as exc:
        logger.warning("Backup email failed: %s", exc)
        return {
            "emailed": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
