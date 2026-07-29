"""CLI for tier-1 data backup snapshots and restore drills."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.data_backup import (
    DEFAULT_BACKUP_DIR,
    create_backup_snapshot,
    list_local_snapshots,
    restore_backup_snapshot,
    run_restore_drill,
    upload_backup_snapshot,
    verify_backup_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Snapshot, verify, upload, and restore tier-1 docs/data backups",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="Create a tier-1 tarball + manifest")
    snap.add_argument(
        "--include-tier2",
        action="store_true",
        help="Also include small regenerable dashboard/queue JSON files",
    )
    snap.add_argument("--upload", action="store_true", help="Upload when BACKUP_S3_URI is set")
    snap.set_defaults(func=_cmd_snapshot)

    sub.add_parser("list", help="List local snapshots under output/backups").set_defaults(func=_cmd_list)

    verify = sub.add_parser("verify", help="Verify archive checksum against manifest")
    verify.add_argument("archive", type=Path)
    verify.add_argument("--manifest", type=Path, default=None)
    verify.set_defaults(func=_cmd_verify)

    restore = sub.add_parser("restore", help="Restore archive into repo root (merge)")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--dry-run", action="store_true")
    restore.set_defaults(func=_cmd_restore)

    drill = sub.add_parser("drill", help="Post-restore smoke: tier paths + history restore count")
    drill.add_argument("--output-dir", type=Path, default=Path("output"))
    drill.set_defaults(func=_cmd_drill)

    args = parser.parse_args(argv)
    return int(args.func(args))


def _cmd_snapshot(args: argparse.Namespace) -> int:
    snapshot = create_backup_snapshot(
        repo_root=args.repo_root,
        backup_dir=args.backup_dir,
        include_tier2=args.include_tier2,
    )
    upload_result = None
    if args.upload:
        try:
            upload_result = upload_backup_snapshot(snapshot)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    payload = snapshot.to_dict()
    if upload_result is not None:
        payload["upload"] = upload_result
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Snapshot: {snapshot.archive_path}")
        print(f"  files: {snapshot.manifest.file_count}")
        print(f"  bytes: {snapshot.manifest.bytes}")
        print(f"  sha256: {snapshot.manifest.sha256}")
        if upload_result:
            print(f"  upload: {upload_result}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    rows = list_local_snapshots(args.backup_dir)
    if args.json:
        print(json.dumps(rows, indent=2))
    elif not rows:
        print("No local snapshots")
    else:
        for row in rows:
            print(
                f"{row['created_at']}  {row['bytes']} bytes  "
                f"{'ok' if row['archive_exists'] else 'missing archive'}  {row['archive_path']}"
            )
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    result = verify_backup_snapshot(args.archive, manifest_path=args.manifest)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Verify: {'ok' if result['ok'] else 'FAIL'}")
    return 0 if result["ok"] else 1


def _cmd_restore(args: argparse.Namespace) -> int:
    result = restore_backup_snapshot(
        args.archive,
        repo_root=args.repo_root,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        label = "Would restore" if args.dry_run else "Restored"
        print(f"{label} {result['restored_paths']} member(s) from {result['archive']}")
    return 0


def _cmd_drill(args: argparse.Namespace) -> int:
    result = run_restore_drill(repo_root=args.repo_root, output_dir=args.output_dir)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Drill ok={result['ok']}")
        if result["missing_tier_paths"]:
            print(f"  missing: {', '.join(result['missing_tier_paths'])}")
        print(f"  history files copied to output: {result['history_files_restored_to_output']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
