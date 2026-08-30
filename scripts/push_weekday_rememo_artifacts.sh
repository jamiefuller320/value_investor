#!/usr/bin/env bash
# Push weekday rememo artifacts to main with retry (handles concurrent automation).
set -euo pipefail

COMMIT_MESSAGE="${1:-chore: weekday memo rememo [skip ci]}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-4}"

# Rememo publish updates research trees + latest.json; keep the allowlist tight so
# stash overlays cannot resurrect ops_status / automation from an older tip.
REMEMO_ARTIFACT_PATHS=(
  docs/data/weekday_memo_rememo_summary.json
  docs/data/latest.json
  docs/data/research
  docs/research
)

git_clean_state() {
  git merge --abort 2>/dev/null || true
  git rebase --abort 2>/dev/null || true
  if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null || true)" ]; then
    git reset --hard HEAD
  fi
}

stage_rememo_artifacts() {
  local path
  for path in \
    docs/data/weekday_memo_rememo_summary.json \
    docs/data/latest.json \
    docs/data/research \
    docs/research
  do
    if [ -e "$path" ]; then
      git add -- "$path"
    fi
  done
}

path_allowed() {
  local path="$1"
  local prefix
  for prefix in "${REMEMO_ARTIFACT_PATHS[@]}"; do
    case "$path" in
      "$prefix"|"$prefix"/*) return 0 ;;
    esac
  done
  return 1
}

STASH_LABEL="weekday-rememo-artifacts-$(date +%s)"
stage_rememo_artifacts
if git diff --cached --quiet && [ -z "$(git status --porcelain docs/data/ docs/research/ 2>/dev/null || true)" ]; then
  echo "No weekday rememo artifact changes to push"
  exit 0
fi

git stash push -u -m "$STASH_LABEL" -- docs/data/ docs/research/

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "Push attempt $attempt/$MAX_ATTEMPTS"
  git_clean_state
  git fetch origin main
  git checkout -B main origin/main

  if git stash list | grep -q "$STASH_LABEL"; then
    git checkout stash@{0} -- docs/data/ docs/research/ 2>/dev/null || true
    git reset HEAD -- . >/dev/null 2>&1 || true
    while IFS= read -r path; do
      [ -z "$path" ] && continue
      if ! path_allowed "$path"; then
        git checkout HEAD -- "$path" 2>/dev/null || true
      fi
    done < <(git diff --name-only -- docs/data/ docs/research/)
  fi

  stage_rememo_artifacts
  if git diff --cached --quiet; then
    echo "No weekday rememo artifact changes after sync"
    git stash drop 2>/dev/null || true
    exit 0
  fi

  while IFS= read -r path; do
    [ -z "$path" ] && continue
    if ! path_allowed "$path"; then
      echo "Refusing to commit non-rememo path from stash overlay: $path" >&2
      git reset HEAD -- "$path" >/dev/null 2>&1 || true
      git checkout -- "$path" 2>/dev/null || true
    fi
  done < <(git diff --cached --name-only)

  if git diff --cached --quiet; then
    echo "No weekday rememo artifact changes after allowlist filter"
    git stash drop 2>/dev/null || true
    exit 0
  fi

  git commit -m "$COMMIT_MESSAGE"
  if git push origin HEAD:main; then
    echo "Weekday rememo artifacts pushed to main"
    git stash drop 2>/dev/null || true
    exit 0
  fi

  echo "Push failed — retrying after backoff"
  sleep $((4 * attempt))
  attempt=$((attempt + 1))
done

echo "Failed to push weekday rememo artifacts after $MAX_ATTEMPTS attempts" >&2
exit 1
