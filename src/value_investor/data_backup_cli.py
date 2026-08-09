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
    merge_email_chunks,
    restore_backup_snapshot,
    run_restore_drill,
    send_backup_snapshot_email,
    snapshot_from_payload,
    try_send_backup_snapshot_email,
    try_upload_backup_snapshot,
    upload_backup_snapshot,
    verify_backup_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Snapshot, verify, upload, and restore tier-1 docs/data backups",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--repo-root", type=Path, default=Path.cwd())
    common.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser(
        "snapshot",
        parents=[common],
        help="Create a tier-1 tarball + manifest",
    )
    snap.add_argument(
        "--include-tier2",
        action="store_true",
        help="Also include small regenerable dashboard/queue JSON files",
    )
    snap.add_argument("--upload", action="store_true", help="Upload when BACKUP_S3_URI is set")
    snap.add_argument(
        "--email",
        action="store_true",
        help="Email manifest + chunked archive to BACKUP_EMAIL_TO (default: intellaigence101@gmail.com)",
    )
    snap.add_argument(
        "--strict-upload",
        action="store_true",
        help="Exit non-zero when --upload is set but upload fails",
    )
    snap.add_argument(
        "--strict-email",
        action="store_true",
        help="Exit non-zero when --email is set but email delivery fails",
    )
    snap.set_defaults(func=_cmd_snapshot)

    deliver = sub.add_parser(
        "deliver",
        parents=[common],
        help="Upload or email an existing snapshot described by snapshot --json output",
    )
    deliver.add_argument(
        "--from-json",
        type=Path,
        required=True,
        help="Path to snapshot JSON (updated in place when --upload/--email run)",
    )
    deliver.add_argument("--upload", action="store_true", help="Upload when BACKUP_S3_URI is set")
    deliver.add_argument("--email", action="store_true", help="Email manifest + chunked archive")
    deliver.add_argument("--strict-upload", action="store_true")
    deliver.add_argument("--strict-email", action="store_true")
    deliver.set_defaults(func=_cmd_deliver)

    sub.add_parser(
        "list",
        parents=[common],
        help="List local snapshots under output/backups",
    ).set_defaults(func=_cmd_list)

    verify = sub.add_parser(
        "verify",
        parents=[common],
        help="Verify archive checksum against manifest",
    )
    verify.add_argument("archive", type=Path)
    verify.add_argument("--manifest", type=Path, default=None)
    verify.set_defaults(func=_cmd_verify)

    restore = sub.add_parser(
        "restore",
        parents=[common],
        help="Restore archive into repo root (merge)",
    )
    restore.add_argument("archive", type=Path)
    restore.add_argument("--dry-run", action="store_true")
    restore.set_defaults(func=_cmd_restore)

    drill = sub.add_parser(
        "drill",
        parents=[common],
        help="Post-restore smoke: tier paths + history restore count",
    )
    drill.add_argument("--output-dir", type=Path, default=Path("output"))
    drill.set_defaults(func=_cmd_drill)

    reassemble = sub.add_parser(
        "reassemble",
        parents=[common],
        help="Merge emailed .partNNN chunks into a tarball",
    )
    reassemble.add_argument("chunks", nargs="+", type=Path, help="Chunk files (*.part001, *.part002, …)")
    reassemble.add_argument("--output", type=Path, required=True, help="Output .tar.gz path")
    reassemble.set_defaults(func=_cmd_reassemble)

    args = parser.parse_args(argv)
    return int(args.func(args))


def _upload_snapshot(
    snapshot,
    *,
    strict: bool,
) -> tuple[dict[str, object] | None, int]:
    try:
        upload_result = upload_backup_snapshot(snapshot)
    except RuntimeError as exc:
        if strict:
            print(str(exc), file=sys.stderr)
            return None, 1
        upload_result = {
            "uploaded": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
    if strict and not upload_result.get("uploaded") and upload_result.get("error"):
        print(str(upload_result.get("error")), file=sys.stderr)
        return upload_result, 1
    return upload_result, 0


def _email_snapshot(
    snapshot,
    *,
    strict: bool,
) -> tuple[dict[str, object] | None, int]:
    if strict:
        try:
            email_result = send_backup_snapshot_email(snapshot)
        except (ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return None, 1
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return None, 1
        return email_result, 0
    email_result = try_send_backup_snapshot_email(snapshot)
    if not email_result.get("emailed"):
        print(
            f"Backup email skipped/failed: {email_result.get('error', 'unknown')}",
            file=sys.stderr,
        )
    return email_result, 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    snapshot = create_backup_snapshot(
        repo_root=args.repo_root,
        backup_dir=args.backup_dir,
        include_tier2=args.include_tier2,
    )
    upload_result = None
    if args.upload:
        upload_result, code = _upload_snapshot(snapshot, strict=args.strict_upload)
        if code != 0:
            return code
    email_result = None
    if args.email:
        email_result, code = _email_snapshot(snapshot, strict=args.strict_email)
        if code != 0:
            return code
    payload = snapshot.to_dict()
    if upload_result is not None:
        payload["upload"] = upload_result
    if email_result is not None:
        payload["email"] = email_result
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Snapshot: {snapshot.archive_path}")
        print(f"  files: {snapshot.manifest.file_count}")
        print(f"  bytes: {snapshot.manifest.bytes}")
        print(f"  sha256: {snapshot.manifest.sha256}")
        if upload_result:
            print(f"  upload: {upload_result}")
        if email_result:
            print(f"  email: {email_result}")
    return 0


def _cmd_deliver(args: argparse.Namespace) -> int:
    if not args.upload and not args.email:
        print("deliver requires --upload and/or --email", file=sys.stderr)
        return 2
    payload = json.loads(args.from_json.read_text(encoding="utf-8"))
    snapshot = snapshot_from_payload(payload)
    if args.upload:
        upload_result, code = _upload_snapshot(snapshot, strict=args.strict_upload)
        if code != 0:
            return code
        payload["upload"] = upload_result
    if args.email:
        email_result, code = _email_snapshot(snapshot, strict=args.strict_email)
        if code != 0:
            return code
        payload["email"] = email_result
    args.from_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2))
    return 0


def _cmd_reassemble(args: argparse.Namespace) -> int:
    output = merge_email_chunks(args.chunks, args.output)
    if args.json:
        print(json.dumps({"output": str(output)}, indent=2))
    else:
        print(f"Reassembled: {output}")
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
