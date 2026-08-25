#!/usr/bin/env bash
# Push weekday ingest-loop artifacts to main with retry (handles concurrent automation).
set -euo pipefail

COMMIT_MESSAGE="${1:-chore: weekday ingest loop [skip ci]}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-4}"

git_clean_state() {
  git merge --abort 2>/dev/null || true
  git rebase --abort 2>/dev/null || true
  if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null || true)" ]; then
    git reset --hard HEAD
  fi
}

stage_ingest_artifacts() {
  git add docs/data/ingest_health_log.json \
    docs/data/ingest_improvement_summary.json \
    docs/data/ingest_bootstrap_summary.json \
    docs/data/ingest_discovery_scan_summary.json \
    docs/data/ingest_discovery_curiosity.json \
    docs/data/ingest_trials.json \
    docs/data/engineering_tasks.json \
    docs/data/research 2>/dev/null || true
  # -u stages updates and deletions (backlog is removed when a pass completes).
  git add -u docs/data/ingest_backlog.json 2>/dev/null || true
}

STASH_LABEL="ingest-loop-artifacts-$(date +%s)"
stage_ingest_artifacts
if git diff --cached --quiet && [ -z "$(git status --porcelain docs/data/ 2>/dev/null || true)" ]; then
  echo "No ingest artifact changes to push"
  exit 0
fi

git stash push -u -m "$STASH_LABEL" -- docs/data/

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "Push attempt $attempt/$MAX_ATTEMPTS"
  git_clean_state
  git fetch origin main
  git checkout -B main origin/main

  if git stash list | grep -q "$STASH_LABEL"; then
    git checkout stash -- docs/data/ 2>/dev/null || true
  fi

  stage_ingest_artifacts
  if git diff --cached --quiet; then
    echo "No ingest artifact changes after sync"
    git stash drop 2>/dev/null || true
    exit 0
  fi

  git commit -m "$COMMIT_MESSAGE"
  if git push origin HEAD:main; then
    echo "Ingest artifacts pushed to main"
    git stash drop 2>/dev/null || true
    exit 0
  fi

  echo "Push failed — retrying after backoff"
  sleep $((4 * attempt))
  attempt=$((attempt + 1))
done

echo "Failed to push ingest artifacts after $MAX_ATTEMPTS attempts" >&2
exit 1
