#!/usr/bin/env bash
# Commit owned artifact pathspecs onto latest origin/<ref> with push retry.
#
# Snapshots matching working-tree files (tracked + untracked) before
# `git reset --hard`, restores them each attempt, then push-retries. That avoids
# the email-report failure mode where `git pull --rebase --autostash` refuses to
# overwrite untracked research bodies, and the library-grow race where a lone
# rebase-push still loses to concurrent main writers.
#
# Owned pathspecs overlay the files this job actually changed (git status:
# tracked edits and untracked files, including under globs). Unmodified files
# stay at origin/<ref> after reset, so a concurrent catalogue-explorer or
# ingest commit is not rewound. Optional pathspecs overlay only when
# origin/<ref> has not changed that exact file since START_SHA (ops-monitor
# queue/health guard). Excluded pathspecs are never restored (email-report
# must not clobber fresher ops_status.json / progress_report.json).
#
# JSON freshness: when restoring an owned *.json file this job changed, if
# origin/<ref> already has a strictly newer top-level `generated_at` than the
# job snapshot, skip the overlay. That stops a long screen from resurrecting
# a stale copy of a file it rewrote (market_status, progress-report, etc.).
#
# Do not copy or freshness-check the whole owned tree. email-report owns
# docs/data (~96k files, 3.2GB). Copying that tree and `git show`'ing every
# JSON took ~45 min per attempt, longer than catalogue-explorer's one-name
# push interval (~90s, ~10s in bursts), so every push was rejected and attempt
# 3/5 was still overlaying when the 6h job limit cancelled the run
# (email-report 45048271823, 2026-11-22). The same full-tree `git show` lost
# Library epoch-0 weekday run 45136445860 (2026-11-23) on a smaller tree.
# Snapshot only the dirty delta; compare those blob hashes to HEAD; freshness
# check the JSON that differ in one `git cat-file --batch`.
#
# docs/data/latest.json is the screen bundle. Its run_at is the screen clock
# and outranks generated_at: a queue refresh can stamp generated_at on a stale
# checkout and would otherwise drop Sunday's new screen (email-report
# 2026-11-15). A newer local run_at always lands. An older local run_at never
# overwrites a newer screen, even when the snapshot's generated_at is later.
#
# Usage:
#   GHA_COMMIT_OWNED='docs/data/foo.json docs/data/bar' \
#   COMMIT_MESSAGE='chore: …' \
#   bash scripts/gha_commit_artifacts.sh
#
# Env:
#   GHA_COMMIT_OWNED       required — space/newline separated files, dirs, or globs
#   GHA_COMMIT_OPTIONAL    optional exact file paths (conditional overlay)
#   GHA_COMMIT_EXCLUDE     exact file paths skipped even when under an owned dir;
#                          an entry ending in / skips every file under that dir
#   GHA_COMMIT_PRESERVE_NEWER_GENERATED_AT
#                          default 1 — skip owned JSON overlay when remote
#                          generated_at is newer than the job snapshot
#   COMMIT_MESSAGE         commit message (required for a real commit)
#   GHA_COMMIT_REF         default main
#   GHA_COMMIT_REMOTE      default origin
#   GHA_COMMIT_ATTEMPTS    default 5
#   GHA_COMMIT_SLEEP_BASE  default 3
#   GHA_COMMIT_SLEEP_CAP   default 15 — max seconds between push retries
#   GHA_COMMIT_LABEL       log label (default artifacts)
#   GHA_COMMIT_RESULT_FILE optional path written with "pushed" or "noop"

set -euo pipefail

REMOTE="${GHA_COMMIT_REMOTE:-origin}"
REF="${GHA_COMMIT_REF:-main}"
MAX_ATTEMPTS="${GHA_COMMIT_ATTEMPTS:-5}"
SLEEP_BASE="${GHA_COMMIT_SLEEP_BASE:-3}"
SLEEP_CAP="${GHA_COMMIT_SLEEP_CAP:-15}"
LABEL="${GHA_COMMIT_LABEL:-artifacts}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-}"
PRESERVE_NEWER_GENERATED_AT="${GHA_COMMIT_PRESERVE_NEWER_GENERATED_AT:-1}"

if [ -z "${GHA_COMMIT_OWNED:-}" ]; then
  echo "::error::GHA_COMMIT_OWNED must list at least one pathspec" >&2
  exit 2
fi
if [ -z "$COMMIT_MESSAGE" ]; then
  echo "::error::COMMIT_MESSAGE is required" >&2
  exit 2
fi

read_pathspec_list() {
  # shellcheck disable=SC2001
  echo "$1" | sed 's/[[:space:]]\+/\n/g' | sed '/^$/d'
}

mapfile -t OWNED_SPECS < <(read_pathspec_list "$GHA_COMMIT_OWNED")
OPTIONAL_SPECS=()
if [ -n "${GHA_COMMIT_OPTIONAL:-}" ]; then
  mapfile -t OPTIONAL_SPECS < <(read_pathspec_list "$GHA_COMMIT_OPTIONAL")
fi
EXCLUDE_SPECS=()
if [ -n "${GHA_COMMIT_EXCLUDE:-}" ]; then
  mapfile -t EXCLUDE_SPECS < <(read_pathspec_list "$GHA_COMMIT_EXCLUDE")
fi

START_SHA="$(git rev-parse HEAD)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
OWNED_MANIFEST="$WORKDIR/owned.txt"
OPTIONAL_MANIFEST="$WORKDIR/optional.txt"
: >"$OWNED_MANIFEST"
: >"$OPTIONAL_MANIFEST"

blob_at() {
  local rev="$1"
  local path="$2"
  # --verify --quiet prints nothing for a missing path; plain rev-parse echoes the
  # unresolved "rev:path" spec, so a new file never matched across two revisions.
  git rev-parse --verify --quiet "${rev}:${path}" 2>/dev/null || true
}


emit_result() {
  local result="$1"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    {
      echo "result=$result"
      if [ "$result" = "pushed" ]; then
        echo "changes_detected=true"
      else
        echo "changes_detected=false"
      fi
    } >>"$GITHUB_OUTPUT"
  fi
  if [ -n "${GHA_COMMIT_RESULT_FILE:-}" ]; then
    echo "$result" >"$GHA_COMMIT_RESULT_FILE"
  fi
}

save_file() {
  local path="$1"
  local manifest="$2"
  if [ ! -f "$path" ]; then
    return 0
  fi
  mkdir -p "$WORKDIR/$(dirname "$path")"
  cp "$path" "$WORKDIR/$path"
  printf '%s\n' "$path" >>"$manifest"
}

restore_file() {
  local path="$1"
  if [ ! -f "$WORKDIR/$path" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$path")"
  cp "$WORKDIR/$path" "$path"
}

# Blind overlay of daily_focus_acks.json loses accept rows when a concurrent
# discuss/ack job started from a stale checkout. Merge by (local_date, task_ref).
restore_or_merge_owned_file() {
  local path="$1"
  local remote_rev="$2"
  if [ ! -f "$WORKDIR/$path" ]; then
    return 0
  fi
  case "$path" in
    */daily_focus_acks.json|daily_focus_acks.json) ;;
    *)
      restore_file "$path"
      return 0
      ;;
  esac
  mkdir -p "$(dirname "$path")"
  local remote_file
  remote_file="$(mktemp "$WORKDIR/remote_acks.XXXXXX.json")"
  if ! git show "${remote_rev}:${path}" >"$remote_file" 2>/dev/null; then
    rm -f "$remote_file"
    restore_file "$path"
    return 0
  fi
  if python3 - "$WORKDIR/$path" "$remote_file" "$path" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

def load(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": 1, "acks": []}
    return raw if isinstance(raw, dict) else {"schema_version": 1, "acks": []}

def key(row: dict) -> tuple[str, str]:
    return (
        str(row.get("local_date") or "").strip(),
        str(row.get("task_ref") or row.get("focus_id") or "").strip(),
    )

def ts(row: dict) -> str:
    return str(row.get("acked_at") or "").strip()

local = load(Path(sys.argv[1]))
remote = load(Path(sys.argv[2]))
by_key: dict[tuple[str, str], dict] = {}
for store in (remote, local):
    for row in store.get("acks") or []:
        if not isinstance(row, dict):
            continue
        k = key(row)
        if not k[0] or not k[1]:
            continue
        prev = by_key.get(k)
        if prev is None or ts(row) >= ts(prev):
            by_key[k] = dict(row)
acks = sorted(
    by_key.values(),
    key=lambda r: (str(r.get("local_date") or ""), str(r.get("acked_at") or ""), key(r)[1]),
)
stamps = []
for store in (remote, local):
    stamp = store.get("updated_at")
    if isinstance(stamp, str) and stamp.strip():
        stamps.append(stamp.strip())
updated = max(stamps) if stamps else datetime.now(timezone.utc).isoformat()
out = {"schema_version": 1, "updated_at": updated, "acks": acks}
Path(sys.argv[3]).write_text(json.dumps(out, indent=2, sort_keys=False) + "\n", encoding="utf-8")
print(f"merged {len(acks)} ack rows")
PY
  then
    echo "Merged ${path} with ${remote_rev} (union by local_date+task_ref)" >&2
    rm -f "$remote_file"
    return 0
  fi
  echo "Warn: daily_focus_acks merge failed; falling back to local overlay" >&2
  rm -f "$remote_file"
  restore_file "$path"
}

# Snapshot only the owned files this job changed. A full-tree copy of
# docs/data is what made each email-report retry take ~45 minutes.
OWNED_SPECS_FILE="$WORKDIR/owned_specs.txt"
EXCLUDE_SPECS_FILE="$WORKDIR/exclude_specs.txt"
OPTIONAL_EXACT_FILE="$WORKDIR/optional_exact.txt"
COLLECTED_FILE="$WORKDIR/collected.txt"
printf '%s\n' "${OWNED_SPECS[@]}" >"$OWNED_SPECS_FILE"
: >"$EXCLUDE_SPECS_FILE"
if [ "${#EXCLUDE_SPECS[@]}" -gt 0 ]; then
  printf '%s\n' "${EXCLUDE_SPECS[@]}" >"$EXCLUDE_SPECS_FILE"
fi
: >"$OPTIONAL_EXACT_FILE"
if [ "${#OPTIONAL_SPECS[@]}" -gt 0 ]; then
  printf '%s\n' "${OPTIONAL_SPECS[@]}" >"$OPTIONAL_EXACT_FILE"
fi

python3 - \
  "$OWNED_SPECS_FILE" \
  "$EXCLUDE_SPECS_FILE" \
  "$OPTIONAL_EXACT_FILE" \
  "$COLLECTED_FILE" \
  "$LABEL" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

specs_file, exclude_file, optional_file, out_file, label = sys.argv[1:6]

def read_lines(path: str) -> list[str]:
    return [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line]

specs = read_lines(specs_file)
excludes = read_lines(exclude_file)
optional = set(read_lines(optional_file))

def is_excluded(path: str) -> bool:
    for opt in excludes:
        if path == opt or (opt.endswith("/") and path.startswith(opt)):
            return True
    return False

def parse_status(blob: bytes) -> list[str]:
    parts = blob.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    paths: list[str] = []
    index = 0
    while index < len(parts):
        raw = parts[index]
        index += 1
        if len(raw) < 4:
            continue
        status = raw[:2].decode("ascii", "replace")
        path = raw[3:].decode("utf-8", "surrogateescape")
        if "R" in status or "C" in status:
            if index < len(parts):
                index += 1
        if "D" in status and "R" not in status and "C" not in status:
            continue
        paths.append(path)
    return paths

def git_status(pathspecs: list[str]) -> bytes:
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "-uall", "--", *pathspecs],
        capture_output=True,
    )
    if proc.returncode != 0:
        sys.stderr.buffer.write(proc.stderr)
        raise SystemExit(proc.returncode)
    return proc.stdout

literals: list[str] = []
globs: list[str] = []
for spec in specs:
    if any(char in spec for char in "*?["):
        globs.append(spec)
    else:
        literals.append(spec)

found: list[str] = []
if literals:
    found.extend(parse_status(git_status(literals)))
for spec in globs:
    found.extend(parse_status(git_status([f":(glob){spec}"])))

seen: set[str] = set()
kept: list[str] = []
for opt in excludes:
    if opt.endswith("/"):
        continue
    if Path(opt).is_file():
        print(f"Excluding {opt} from {label} owned overlay", file=sys.stderr)
        seen.add(opt)
for path in found:
    if path in seen:
        continue
    seen.add(path)
    if path in optional:
        continue
    if is_excluded(path):
        print(f"Excluding {path} from {label} owned overlay", file=sys.stderr)
        continue
    candidate = Path(path)
    if candidate.is_dir():
        for dirpath, _, names in os.walk(path):
            for name in names:
                child = str(Path(dirpath) / name)
                if child in seen or child in optional or is_excluded(child):
                    if is_excluded(child):
                        print(
                            f"Excluding {child} from {label} owned overlay",
                            file=sys.stderr,
                        )
                    continue
                seen.add(child)
                if Path(child).is_file():
                    kept.append(child)
        continue
    if candidate.is_file():
        kept.append(path)

Path(out_file).write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
noun = "file" if len(kept) == 1 else "files"
print(f"{label} snapshot {len(kept)} changed owned {noun}")
PY

while IFS= read -r path; do
  [ -n "$path" ] || continue
  save_file "$path" "$OWNED_MANIFEST"
done <"$COLLECTED_FILE"

for spec in "${OPTIONAL_SPECS[@]+"${OPTIONAL_SPECS[@]}"}"; do
  save_file "$spec" "$OPTIONAL_MANIFEST"
done

sort -u -o "$OWNED_MANIFEST" "$OWNED_MANIFEST"
sort -u -o "$OPTIONAL_MANIFEST" "$OPTIONAL_MANIFEST"

# Git blob id of each snapshot file (sha1). Compared to HEAD each attempt so
# unchanged artifacts skip the generated_at git-show. Object format other than
# sha1 simply never matches, and those files take the full overlay path.
SNAPSHOT_INDEX="$WORKDIR/snapshot_blobs.tsv"
python3 - "$OWNED_MANIFEST" "$OPTIONAL_MANIFEST" "$SNAPSHOT_INDEX" "$WORKDIR" <<'PY'
import hashlib
import sys
from pathlib import Path

def blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()

root = Path(sys.argv[4])
seen: set[str] = set()
lines: list[str] = []
for manifest in sys.argv[1:3]:
    for raw in Path(manifest).read_text(encoding="utf-8").splitlines():
        path = raw.strip()
        if not path or path in seen:
            continue
        seen.add(path)
        file = root / path
        if not file.is_file():
            continue
        lines.append(f"{blob_sha1(file.read_bytes())}\t{path}")
Path(sys.argv[3]).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
PY

declare -A UNCHANGED_BLOBS=()

refresh_unchanged_set() {
  local path listing
  # Not `local listing=$(...)`: bash makes `local` succeed even when python fails.
  listing="$(python3 - "$SNAPSHOT_INDEX" <<'PY'
import subprocess
import sys
from pathlib import Path

rows: list[tuple[str, str]] = []
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not line:
        continue
    digest, path = line.split("\t", 1)
    rows.append((digest, path))
if not rows:
    raise SystemExit(0)
proc = subprocess.run(
    ["git", "cat-file", "--batch-check"],
    input="".join(f"HEAD:{path}\n" for _, path in rows),
    text=True,
    capture_output=True,
    check=True,
)
lines = proc.stdout.splitlines()
if len(lines) != len(rows):
    raise SystemExit(
        f"git cat-file returned {len(lines)} lines for {len(rows)} paths"
    )
for (digest, path), line in zip(rows, lines):
    oid = line.split(" ", 1)[0]
    if oid == digest:
        print(path)
PY
)"
  unset UNCHANGED_BLOBS
  declare -g -A UNCHANGED_BLOBS=()
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    UNCHANGED_BLOBS["$path"]=1
  done <<<"$listing"
}

snapshot_matches_head() {
  local path="$1"
  [ -n "${UNCHANGED_BLOBS[$path]:-}" ]
}

# One cat-file batch for the dirty owned set. Prints:
#   UNCHANGED <n>
#   RESTORE <path>
# Skip messages go to stderr (same text as the old per-file freshness check).
classify_owned_overlays() {
  local remote_rev="$1"
  # Not `local listing=$(...)`: bash makes `local` succeed even when python fails.
  python3 - \
    "$SNAPSHOT_INDEX" \
    "$remote_rev" \
    "$PRESERVE_NEWER_GENERATED_AT" \
    "$WORKDIR" \
    "$LABEL" \
    "$OWNED_MANIFEST" <<'PY'
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

index_path, remote_rev, preserve, workdir, label, owned_manifest = sys.argv[1:7]
root = Path(workdir)
owned = {
    line.strip()
    for line in Path(owned_manifest).read_text(encoding="utf-8").splitlines()
    if line.strip()
}

def parse_iso(value: str):
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None

def remote_newer(local_iso: str, remote_iso: str) -> bool:
    if not local_iso or not remote_iso:
        return False
    local = parse_iso(local_iso)
    remote = parse_iso(remote_iso)
    if local is None or remote is None:
        return False
    return remote > local

def top_string(data, key: str) -> str:
    if isinstance(data, dict):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def load_json(blob: bytes):
    try:
        return json.loads(blob.decode("utf-8"))
    except Exception:
        return None

rows: list[tuple[str, str]] = []
for line in Path(index_path).read_text(encoding="utf-8").splitlines():
    if not line or "\t" not in line:
        continue
    digest, path = line.split("\t", 1)
    if path not in owned:
        continue
    rows.append((digest, path))

unchanged: list[str] = []
differ: list[str] = []
if rows:
    proc = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        input="".join(f"HEAD:{path}\n" for _, path in rows),
        text=True,
        capture_output=True,
        check=True,
    )
    lines = proc.stdout.splitlines()
    if len(lines) != len(rows):
        raise SystemExit(
            f"git cat-file returned {len(lines)} lines for {len(rows)} paths"
        )
    for (digest, path), line in zip(rows, lines):
        oid = line.split(" ", 1)[0]
        if oid == digest:
            unchanged.append(path)
        else:
            differ.append(path)

restore: list[str] = []
need: list[str] = []
if preserve == "0":
    restore.extend(differ)
else:
    for path in differ:
        if path.endswith(".json"):
            need.append(path)
        else:
            restore.append(path)

remote_blobs: dict[str, bytes | None] = {}
if need:
    proc = subprocess.run(
        ["git", "cat-file", "--batch"],
        input="".join(f"{remote_rev}:{path}\n" for path in need).encode(),
        capture_output=True,
        check=True,
    )
    data = proc.stdout
    pos = 0
    for path in need:
        newline = data.find(b"\n", pos)
        if newline < 0:
            raise SystemExit("truncated cat-file batch")
        header = data[pos:newline].decode("utf-8", "replace")
        pos = newline + 1
        if header.endswith(" missing"):
            remote_blobs[path] = None
            continue
        parts = header.split()
        if len(parts) < 3:
            raise SystemExit(f"bad cat-file header: {header}")
        size = int(parts[-1])
        blob = data[pos : pos + size]
        pos += size
        if pos < len(data) and data[pos : pos + 1] == b"\n":
            pos += 1
        remote_blobs[path] = blob
    if pos != len(data) and data[pos:] not in (b"", b"\n"):
        raise SystemExit("cat-file batch did not consume cleanly")

for path in need:
    remote = remote_blobs.get(path)
    if remote is None:
        restore.append(path)
        continue
    local_doc = load_json((root / path).read_bytes())
    remote_doc = load_json(remote)
    if path == "docs/data/latest.json":
        local_run = top_string(local_doc, "run_at")
        remote_run = top_string(remote_doc, "run_at")
        if local_run and remote_run:
            if remote_newer(remote_run, local_run):
                # Job snapshot screen is newer than origin. Land it.
                restore.append(path)
                continue
            if remote_newer(local_run, remote_run):
                print(
                    f"Preserving newer {remote_rev} {path} "
                    f"(generated_at ahead of {label} snapshot)",
                    file=sys.stderr,
                )
                continue
    local_iso = top_string(local_doc, "generated_at")
    remote_iso = top_string(remote_doc, "generated_at")
    if local_iso and remote_newer(local_iso, remote_iso):
        print(
            f"Preserving newer {remote_rev} {path} "
            f"(generated_at ahead of {label} snapshot)",
            file=sys.stderr,
        )
        continue
    restore.append(path)

print(f"UNCHANGED {len(unchanged)}")
for path in restore:
    print(f"RESTORE {path}")
PY
}

git config user.name "${GIT_AUTHOR_NAME:-github-actions[bot]}"
git config user.email "${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "${LABEL} commit attempt $attempt/$MAX_ATTEMPTS"
  git fetch "$REMOTE" "$REF"
  git reset --hard "${REMOTE}/${REF}"
  if [ -s "$OPTIONAL_MANIFEST" ]; then
    refresh_unchanged_set
  fi

  restored=()
  unchanged=0
  classify_file="$WORKDIR/classify.txt"
  classify_owned_overlays "${REMOTE}/${REF}" >"$classify_file"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      UNCHANGED\ *)
        unchanged="${line#UNCHANGED }"
        ;;
      RESTORE\ *)
        path="${line#RESTORE }"
        [ -n "$path" ] || continue
        restore_or_merge_owned_file "$path" "${REMOTE}/${REF}"
        if [ -e "$path" ]; then
          restored+=("$path")
        fi
        ;;
      "")
        ;;
      *)
        echo "::error::Unexpected overlay classify line: $line" >&2
        exit 1
        ;;
    esac
  done <"$classify_file"

  while IFS= read -r path; do
    [ -n "$path" ] || continue
    if [ ! -f "$WORKDIR/$path" ]; then
      continue
    fi
    if snapshot_matches_head "$path"; then
      unchanged=$((unchanged + 1))
      continue
    fi
    base_blob="$(blob_at "$START_SHA" "$path")"
    main_blob="$(blob_at "${REMOTE}/${REF}" "$path")"
    if [ "$base_blob" = "$main_blob" ]; then
      restore_file "$path"
      if [ -e "$path" ]; then
        restored+=("$path")
      fi
    else
      echo "Skipping $path — ${REMOTE}/${REF} changed it since checkout ${START_SHA:0:12}" >&2
    fi
  done <"$OPTIONAL_MANIFEST"

  if [ "$unchanged" -eq 1 ]; then
    echo "Leaving 1 unchanged artifact file off the ${LABEL} commit"
  elif [ "$unchanged" -gt 1 ]; then
    echo "Leaving ${unchanged} unchanged artifact files off the ${LABEL} commit"
  fi

  if [ "${#restored[@]}" -eq 0 ]; then
    echo "No ${LABEL} artifact delta"
    emit_result noop
    exit 0
  fi

  # Avoid ARG_MAX on large dashboard trees (email-report).
  printf '%s\0' "${restored[@]}" | xargs -0 git add --
  if git diff --cached --quiet; then
    echo "No ${LABEL} artifact delta"
    emit_result noop
    exit 0
  fi

  git commit -m "$COMMIT_MESSAGE"
  if git push "$REMOTE" "HEAD:${REF}"; then
    echo "${LABEL} artifacts committed on attempt $attempt"
    emit_result pushed
    exit 0
  fi

  echo "${LABEL} push rejected (attempt $attempt/$MAX_ATTEMPTS); retrying" >&2
  git reset --hard "${REMOTE}/${REF}"
  if [ "$attempt" -eq "$MAX_ATTEMPTS" ]; then
    break
  fi
  delay=$((SLEEP_BASE * attempt))
  if [ "$delay" -gt "$SLEEP_CAP" ]; then
    delay="$SLEEP_CAP"
  fi
  echo "Retrying in ${delay}s…" >&2
  sleep "$delay"
  attempt=$((attempt + 1))
done

echo "::error::Could not push ${LABEL} artifacts after $MAX_ATTEMPTS attempts" >&2
emit_result failed
exit 1
