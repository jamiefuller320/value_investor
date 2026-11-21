#!/usr/bin/env bash
# Push library ingest artifacts to main with retry (handles concurrent automation).
#
# The 2026-09-03 euro-ingest-loop failure left docs/data/engineering_tasks.json
# dirty and unstashed, so `git checkout -B main origin/main` aborted. Stash every
# allowlisted path, then restore only files this job actually changed so a
# concurrent engineering-queue update is not clobbered.
set -euo pipefail

COMMIT_MESSAGE="${1:-chore: euro_depth ingest loop [skip ci]}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-4}"

# Only these paths may be restored from the stash and committed.
LIBRARY_INGEST_ARTIFACT_PATHS=(
  docs/data/library
  docs/data/engineering_tasks.json
  docs/data/ingest_gap_closure_runs.json
  docs/data/ingest_deviations.json
  docs/data/market_status.json
  docs/data/agent_usage
)

USAGE_DIR="docs/data/agent_usage"
USAGE_SNAPSHOT=""
if [ -d "$USAGE_DIR" ]; then
  USAGE_SNAPSHOT="$(mktemp -d)"
  cp -a "$USAGE_DIR/." "$USAGE_SNAPSHOT/"
fi

restore_usage_shards() {
  git checkout HEAD -- "$USAGE_DIR" 2>/dev/null || true
  if [ -n "$USAGE_SNAPSHOT" ] && [ -d "$USAGE_SNAPSHOT" ]; then
    mkdir -p "$USAGE_DIR"
    cp -a "$USAGE_SNAPSHOT/." "$USAGE_DIR/"
  fi
}

git_clean_state() {
  git merge --abort 2>/dev/null || true
  git rebase --abort 2>/dev/null || true
  if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null || true)" ]; then
    git reset --hard HEAD
  fi
}

path_is_allowed() {
  local path="$1" prefix
  for prefix in "${LIBRARY_INGEST_ARTIFACT_PATHS[@]}"; do
    case "$path" in
      "$prefix"|"$prefix"/*) return 0 ;;
    esac
  done
  return 1
}

# Two lanes commit catalogue_explorer.json. Restoring one copy wholesale would
# drop the other lane's cursor or a finished ingest. Merge the origin file
# (already checked out) with the stashed copy.
CATALOGUE_STATE="docs/data/library/catalogue_explorer.json"

restore_artifact() {
  local path="$1" ref="$2"
  if [ "$path" != "$CATALOGUE_STATE" ]; then
    git checkout "$ref" -- "$path" 2>/dev/null || true
    return
  fi
  local base_tmp incoming_tmp src_root
  base_tmp="$(mktemp)"
  incoming_tmp="$(mktemp)"
  if [ -f "$path" ]; then
    cp "$path" "$base_tmp"
  else
    printf '%s\n' '{"schema_version":1,"completed":[],"runs":[],"handoffs":[]}' > "$base_tmp"
  fi
  if git cat-file -e "$ref:$path" 2>/dev/null; then
    git show "$ref:$path" > "$incoming_tmp"
  else
    cp "$base_tmp" "$incoming_tmp"
  fi
  src_root="$(cd "$(dirname "$0")/.." && pwd)"
  PYTHONPATH="${src_root}/src${PYTHONPATH:+:$PYTHONPATH}" \
    python3 - "$base_tmp" "$incoming_tmp" "$path" <<'PY'
import sys
from pathlib import Path

from value_investor.catalogue_explorer import merge_state_files

merge_state_files(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
PY
  rm -f "$base_tmp" "$incoming_tmp"
}

stage_library_ingest_artifacts() {
  local path
  for path in "${LIBRARY_INGEST_ARTIFACT_PATHS[@]}"; do
    if [ -e "$path" ] || git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
      git add -- "$path" 2>/dev/null || true
    fi
  done
}

collect_dirty_artifact_paths() {
  {
    git diff --name-only HEAD -- "${LIBRARY_INGEST_ARTIFACT_PATHS[@]}"
    git ls-files --others --exclude-standard -- "${LIBRARY_INGEST_ARTIFACT_PATHS[@]}"
  } | sort -u
}

stash_ref_for_label() {
  local label="$1"
  git stash list --format='%gd %s' | awk -v label="$label" 'index($0, label) { print $1; exit }'
}

STASH_LABEL="library-ingest-artifacts-$(date +%s)"
DIRTY_LIST="$(mktemp)"
trap 'rm -f "$DIRTY_LIST"' EXIT

stage_library_ingest_artifacts
if git diff --cached --quiet && [ -z "$(git status --porcelain -- "${LIBRARY_INGEST_ARTIFACT_PATHS[@]}" 2>/dev/null || true)" ]; then
  echo "No library ingest artifact changes to push"
  exit 0
fi

collect_dirty_artifact_paths > "$DIRTY_LIST"
# Stash the whole docs/data tree so leftover dirty files (ops_status, …)
# cannot fail `checkout -B main origin/main`. Restore is allowlisted + dirty-only.
git stash push -u -m "$STASH_LABEL" -- docs/data/

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "Push attempt $attempt/$MAX_ATTEMPTS"
  git_clean_state
  git fetch origin main
  git checkout -B main origin/main

  ref="$(stash_ref_for_label "$STASH_LABEL")"
  if [ -n "$ref" ]; then
    # Restore only files this job actually changed. Checking out the whole
    # stash tree would clobber concurrent engineering_tasks.json updates.
    while IFS= read -r path; do
      [ -z "$path" ] && continue
      if path_is_allowed "$path"; then
        restore_artifact "$path" "$ref"
      fi
    done < "$DIRTY_LIST"
  fi

  restore_usage_shards
  stage_library_ingest_artifacts
  if git diff --cached --quiet; then
    echo "No library ingest artifact changes after sync"
    if [ -n "${ref:-}" ]; then
      git stash drop "$ref" 2>/dev/null || true
    fi
    exit 0
  fi

  while IFS= read -r path; do
    [ -z "$path" ] && continue
    if ! path_is_allowed "$path"; then
      echo "Refusing to commit non-library-ingest path from stash overlay: $path" >&2
      git reset HEAD -- "$path" >/dev/null 2>&1 || true
      git checkout -- "$path" 2>/dev/null || true
    fi
  done < <(git diff --cached --name-only)

  if git diff --cached --quiet; then
    echo "No library ingest artifact changes after allowlist filter"
    if [ -n "${ref:-}" ]; then
      git stash drop "$ref" 2>/dev/null || true
    fi
    exit 0
  fi

  git commit -m "$COMMIT_MESSAGE"
  if git push origin HEAD:main; then
    echo "Library ingest artifacts pushed to main"
    if [ -n "${ref:-}" ]; then
      git stash drop "$ref" 2>/dev/null || true
    fi
    if [ "${DISPATCH_PAGES:-}" = "true" ]; then
      bash "$(dirname "$0")/dispatch_pages.sh" || echo "pages dispatch skipped"
    fi
    exit 0
  fi

  echo "Push failed — retrying after backoff"
  sleep $((4 * attempt))
  attempt=$((attempt + 1))
done

echo "Failed to push library ingest artifacts after $MAX_ATTEMPTS attempts" >&2
exit 1
