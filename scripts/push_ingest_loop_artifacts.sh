#!/usr/bin/env bash
# Push weekday ingest-loop artifacts to main with retry (handles concurrent automation).
#
# Only restore files this job actually dirtied. Checking out a full docs/data/
# stash overlay resurrects stale copies of allowlisted files (notably
# engineering_tasks.json) that concurrent engineering-queue commits advanced
# after the job started — that clobber blocked hunter auto-merge on 2026-09-11.
set -euo pipefail

COMMIT_MESSAGE="${1:-chore: weekday ingest loop [skip ci]}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-4}"

# Only these paths may be restored from the stash and committed.
INGEST_ARTIFACT_PATHS=(
  docs/data/ingest_health_log.json
  docs/data/ingest_improvement_summary.json
  docs/data/ingest_bootstrap_summary.json
  docs/data/ingest_discovery_scan_summary.json
  docs/data/ingest_discovery_curiosity.json
  docs/data/ingest_trials.json
  docs/data/engineering_tasks.json
  docs/data/research
  docs/data/ingest_backlog.json
)

git_clean_state() {
  git merge --abort 2>/dev/null || true
  git rebase --abort 2>/dev/null || true
  if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null || true)" ]; then
    git reset --hard HEAD
  fi
}

path_is_allowed() {
  local path="$1" prefix
  for prefix in "${INGEST_ARTIFACT_PATHS[@]}"; do
    case "$path" in
      "$prefix"|"$prefix"/*) return 0 ;;
    esac
  done
  return 1
}

stage_ingest_artifacts() {
  local path
  for path in "${INGEST_ARTIFACT_PATHS[@]}"; do
    # Skip backlog here — handled with -u below so deletions stage.
    if [ "$path" = "docs/data/ingest_backlog.json" ]; then
      continue
    fi
    if [ -e "$path" ] || git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
      git add -- "$path" 2>/dev/null || true
    fi
  done
  # -u stages updates and deletions (backlog is removed when a pass completes).
  if [ -e docs/data/ingest_backlog.json ] || git ls-files --error-unmatch docs/data/ingest_backlog.json >/dev/null 2>&1; then
    git add -u -- docs/data/ingest_backlog.json 2>/dev/null || true
  fi
}

collect_dirty_artifact_paths() {
  {
    git diff --name-only HEAD -- "${INGEST_ARTIFACT_PATHS[@]}"
    git ls-files --others --exclude-standard -- "${INGEST_ARTIFACT_PATHS[@]}"
  } | sort -u
}

stash_ref_for_label() {
  local label="$1"
  git stash list --format='%gd %s' | awk -v label="$label" 'index($0, label) { print $1; exit }'
}

STASH_LABEL="ingest-loop-artifacts-$(date +%s)"
DIRTY_LIST="$(mktemp)"
trap 'rm -f "$DIRTY_LIST"' EXIT

stage_ingest_artifacts
if git diff --cached --quiet && [ -z "$(git status --porcelain -- "${INGEST_ARTIFACT_PATHS[@]}" 2>/dev/null || true)" ]; then
  echo "No ingest artifact changes to push"
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
        git checkout "$ref" -- "$path" 2>/dev/null || true
      fi
    done < "$DIRTY_LIST"
  fi

  stage_ingest_artifacts
  if git diff --cached --quiet; then
    echo "No ingest artifact changes after sync"
    if [ -n "${ref:-}" ]; then
      git stash drop "$ref" 2>/dev/null || true
    fi
    exit 0
  fi

  while IFS= read -r path; do
    [ -z "$path" ] && continue
    if ! path_is_allowed "$path"; then
      echo "Refusing to commit non-ingest path from stash overlay: $path" >&2
      git reset HEAD -- "$path" >/dev/null 2>&1 || true
      git checkout -- "$path" 2>/dev/null || true
    fi
  done < <(git diff --cached --name-only)

  if git diff --cached --quiet; then
    echo "No ingest artifact changes after allowlist filter"
    if [ -n "${ref:-}" ]; then
      git stash drop "$ref" 2>/dev/null || true
    fi
    exit 0
  fi

  git commit -m "$COMMIT_MESSAGE"
  if git push origin HEAD:main; then
    echo "Ingest artifacts pushed to main"
    if [ -n "${ref:-}" ]; then
      git stash drop "$ref" 2>/dev/null || true
    fi
    exit 0
  fi

  echo "Push failed — retrying after backoff"
  sleep $((4 * attempt))
  attempt=$((attempt + 1))
done

echo "Failed to push ingest artifacts after $MAX_ATTEMPTS attempts" >&2
exit 1
