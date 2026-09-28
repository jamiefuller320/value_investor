#!/usr/bin/env bash
# Commit owned artifact pathspecs onto latest origin/<ref> with push retry.
#
# Snapshots matching working-tree files (tracked + untracked) before
# `git reset --hard`, restores them each attempt, then push-retries. That avoids
# the email-report failure mode where `git pull --rebase --autostash` refuses to
# overwrite untracked research bodies, and the library-grow race where a lone
# rebase-push still loses to concurrent main writers.
#
# Owned pathspecs always overlay. Optional pathspecs overlay only when
# origin/<ref> has not changed that exact file since START_SHA (ops-monitor
# queue/health guard). Excluded pathspecs are never restored from a broad
# owned dir (email-report must not clobber fresher ops_status.json /
# progress_report.json).
#
# JSON freshness: when restoring an owned *.json file, if origin/<ref> already
# has a strictly newer top-level `generated_at` than the job snapshot, skip the
# overlay. That stops long dashboard jobs from resurrecting stale foreign-owned
# artifacts (progress-report, ops-monitor, etc.) without listing every path.
#
# Usage:
#   GHA_COMMIT_OWNED='docs/data/foo.json docs/data/bar' \
#   COMMIT_MESSAGE='chore: …' \
#   bash scripts/gha_commit_artifacts.sh
#
# Env:
#   GHA_COMMIT_OWNED       required — space/newline separated files, dirs, or globs
#   GHA_COMMIT_OPTIONAL    optional exact file paths (conditional overlay)
#   GHA_COMMIT_EXCLUDE     exact file paths skipped even when under an owned dir
#   GHA_COMMIT_PRESERVE_NEWER_GENERATED_AT
#                          default 1 — skip owned JSON overlay when remote
#                          generated_at is newer than the job snapshot
#   COMMIT_MESSAGE         commit message (required for a real commit)
#   GHA_COMMIT_REF         default main
#   GHA_COMMIT_REMOTE      default origin
#   GHA_COMMIT_ATTEMPTS    default 5
#   GHA_COMMIT_SLEEP_BASE  default 3
#   GHA_COMMIT_LABEL       log label (default artifacts)
#   GHA_COMMIT_RESULT_FILE optional path written with "pushed" or "noop"

set -euo pipefail

REMOTE="${GHA_COMMIT_REMOTE:-origin}"
REF="${GHA_COMMIT_REF:-main}"
MAX_ATTEMPTS="${GHA_COMMIT_ATTEMPTS:-5}"
SLEEP_BASE="${GHA_COMMIT_SLEEP_BASE:-3}"
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
  git rev-parse "${rev}:${path}" 2>/dev/null || true
}

# Extract top-level JSON generated_at (ISO-8601). Empty if missing/unparseable.
json_generated_at() {
  local path="$1"
  if [ ! -f "$path" ]; then
    return 0
  fi
  case "$path" in
    *.json) ;;
    *) return 0 ;;
  esac
  python3 - "$path" <<'PY' 2>/dev/null || true
import json, sys
from pathlib import Path
try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
if isinstance(data, dict):
    value = data.get("generated_at")
    if isinstance(value, str) and value.strip():
        print(value.strip())
PY
}

# Return 0 when remote_iso is strictly newer than local_iso (both ISO-8601).
remote_generated_at_is_newer() {
  local local_iso="$1"
  local remote_iso="$2"
  if [ -z "$local_iso" ] || [ -z "$remote_iso" ]; then
    return 1
  fi
  python3 - "$local_iso" "$remote_iso" <<'PY' 2>/dev/null
import sys
from datetime import datetime

def parse(value: str):
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None

local = parse(sys.argv[1])
remote = parse(sys.argv[2])
if local is None or remote is None:
    raise SystemExit(1)
raise SystemExit(0 if remote > local else 1)
PY
}

should_skip_stale_json_overlay() {
  local path="$1"
  local remote_rev="$2"
  if [ "$PRESERVE_NEWER_GENERATED_AT" = "0" ]; then
    return 1
  fi
  case "$path" in
    *.json) ;;
    *) return 1 ;;
  esac
  local local_iso remote_file remote_iso
  local_iso="$(json_generated_at "$WORKDIR/$path")"
  if [ -z "$local_iso" ]; then
    return 1
  fi
  remote_file="$(mktemp "$WORKDIR/remote_json.XXXXXX.json")"
  if ! git show "${remote_rev}:${path}" >"$remote_file" 2>/dev/null; then
    rm -f "$remote_file"
    return 1
  fi
  remote_iso="$(json_generated_at "$remote_file")"
  rm -f "$remote_file"
  if remote_generated_at_is_newer "$local_iso" "$remote_iso"; then
    return 0
  fi
  return 1
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

# Expand pathspecs to concrete files currently in the working tree (including
# untracked). Supports exact files, directories, and bash globs (including **).
expand_to_files() {
  local spec="$1"
  local f
  if [ -f "$spec" ]; then
    printf '%s\n' "$spec"
    return 0
  fi
  if [ -d "$spec" ]; then
    find "$spec" -type f -print
    return 0
  fi
  (
    shopt -s nullglob globstar
    # shellcheck disable=SC2086
    for f in $spec; do
      if [ -f "$f" ]; then
        printf '%s\n' "$f"
      elif [ -d "$f" ]; then
        find "$f" -type f -print
      fi
    done
  )
}

is_optional_path() {
  local path="$1"
  local opt
  for opt in "${OPTIONAL_SPECS[@]+"${OPTIONAL_SPECS[@]}"}"; do
    if [ "$path" = "$opt" ]; then
      return 0
    fi
  done
  return 1
}

is_excluded_path() {
  local path="$1"
  local opt
  for opt in "${EXCLUDE_SPECS[@]+"${EXCLUDE_SPECS[@]}"}"; do
    if [ "$path" = "$opt" ]; then
      return 0
    fi
  done
  return 1
}

for spec in "${OWNED_SPECS[@]}"; do
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    if is_optional_path "$path"; then
      continue
    fi
    if is_excluded_path "$path"; then
      echo "Excluding $path from ${LABEL} owned overlay" >&2
      continue
    fi
    save_file "$path" "$OWNED_MANIFEST"
  done < <(expand_to_files "$spec")
done

for spec in "${OPTIONAL_SPECS[@]+"${OPTIONAL_SPECS[@]}"}"; do
  save_file "$spec" "$OPTIONAL_MANIFEST"
done

sort -u -o "$OWNED_MANIFEST" "$OWNED_MANIFEST"
sort -u -o "$OPTIONAL_MANIFEST" "$OPTIONAL_MANIFEST"

git config user.name "${GIT_AUTHOR_NAME:-github-actions[bot]}"
git config user.email "${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "${LABEL} commit attempt $attempt/$MAX_ATTEMPTS"
  git fetch "$REMOTE" "$REF"
  git reset --hard "${REMOTE}/${REF}"

  restored=()
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    if should_skip_stale_json_overlay "$path" "${REMOTE}/${REF}"; then
      echo "Preserving newer ${REMOTE}/${REF} $path (generated_at ahead of ${LABEL} snapshot)" >&2
      continue
    fi
    restore_file "$path"
    if [ -e "$path" ]; then
      restored+=("$path")
    fi
  done <"$OWNED_MANIFEST"

  while IFS= read -r path; do
    [ -n "$path" ] || continue
    if [ ! -f "$WORKDIR/$path" ]; then
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
  echo "Retrying in ${delay}s…" >&2
  sleep "$delay"
  attempt=$((attempt + 1))
done

echo "::error::Could not push ${LABEL} artifacts after $MAX_ATTEMPTS attempts" >&2
emit_result failed
exit 1
