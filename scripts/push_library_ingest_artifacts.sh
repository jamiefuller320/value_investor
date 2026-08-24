#!/usr/bin/env bash
# Push weekday euro_depth library ingest artifacts to main with retry.
set -euo pipefail

COMMIT_MESSAGE="${1:-chore: euro_depth ingest loop [skip ci]}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-4}"

git_clean_state() {
  git merge --abort 2>/dev/null || true
  git rebase --abort 2>/dev/null || true
  if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null || true)" ]; then
    git reset --hard HEAD
  fi
}

stage_library_ingest_artifacts() {
  git add docs/data/library/euro_ingest_health_log.json \
    docs/data/library/euro_ingest_summary.json \
    docs/data/library/euro_ingest_dispatch.json \
    docs/data/library/markets \
    docs/data/engineering_tasks.json \
    docs/data/ingest_gap_closure_runs.json 2>/dev/null || true
}

STASH_LABEL="library-ingest-artifacts-$(date +%s)"
stage_library_ingest_artifacts
if git diff --cached --quiet && [ -z "$(git status --porcelain docs/data/library/ 2>/dev/null || true)" ]; then
  echo "No library ingest artifact changes to push"
  exit 0
fi

git stash push -u -m "$STASH_LABEL" -- docs/data/library/

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "Push attempt $attempt/$MAX_ATTEMPTS"
  git_clean_state
  git fetch origin main
  git checkout -B main origin/main

  if git stash list | grep -q "$STASH_LABEL"; then
    git checkout stash -- docs/data/library/ 2>/dev/null || true
  fi

  stage_library_ingest_artifacts
  if git diff --cached --quiet; then
    echo "No library ingest artifact changes after sync"
    git stash drop 2>/dev/null || true
    exit 0
  fi

  git commit -m "$COMMIT_MESSAGE"
  if git push origin HEAD:main; then
    echo "Library ingest artifacts pushed to main"
    git stash drop 2>/dev/null || true
    exit 0
  fi

  echo "Push failed — retrying after backoff"
  sleep $((4 * attempt))
  attempt=$((attempt + 1))
done

echo "Failed to push library ingest artifacts after $MAX_ATTEMPTS attempts" >&2
exit 1
