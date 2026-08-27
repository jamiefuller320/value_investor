#!/usr/bin/env bash
# Push weekday ingest-loop artifacts to main with retry (handles concurrent automation).
set -euo pipefail

COMMIT_MESSAGE="${1:-chore: weekday ingest loop [skip ci]}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-4}"

# Only these paths may be restored from the stash and committed. Checking out the
# whole docs/data/ tree from a stash WIP commit also resurrects stale copies of
# unrelated files (e.g. ops_status.json) that landed on main after the job started.
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

stage_ingest_artifacts() {
  local path
  for path in \
    docs/data/ingest_health_log.json \
    docs/data/ingest_improvement_summary.json \
    docs/data/ingest_bootstrap_summary.json \
    docs/data/ingest_discovery_scan_summary.json \
    docs/data/ingest_discovery_curiosity.json \
    docs/data/ingest_trials.json \
    docs/data/engineering_tasks.json \
    docs/data/research
  do
    if [ -e "$path" ]; then
      git add -- "$path"
    fi
  done
  # -u stages updates and deletions (backlog is removed when a pass completes).
  if [ -e docs/data/ingest_backlog.json ] || git ls-files --error-unmatch docs/data/ingest_backlog.json >/dev/null 2>&1; then
    git add -u -- docs/data/ingest_backlog.json 2>/dev/null || true
  fi
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
    # Apply the stash overlay, then immediately drop anything outside the
    # ingest allowlist. Checking out stash -- docs/data/ stages the whole
    # docs/data tree from the stash WIP commit (including stale ops_status
    # that matches the pre-fetch tip) — that is what clobbered ops-monitor.
    git checkout stash@{0} -- docs/data/ 2>/dev/null || true
    git reset HEAD -- . >/dev/null 2>&1 || true
    while IFS= read -r path; do
      [ -z "$path" ] && continue
      allowed=false
      for prefix in "${INGEST_ARTIFACT_PATHS[@]}"; do
        case "$path" in
          "$prefix"|"$prefix"/*) allowed=true; break ;;
        esac
      done
      if [ "$allowed" != true ]; then
        git checkout HEAD -- "$path" 2>/dev/null || true
      fi
    done < <(git diff --name-only -- docs/data/)
  fi

  stage_ingest_artifacts
  if git diff --cached --quiet; then
    echo "No ingest artifact changes after sync"
    git stash drop 2>/dev/null || true
    exit 0
  fi

  # Guard: refuse to commit unrelated docs/data files (ops_status, automation, …).
  while IFS= read -r path; do
    [ -z "$path" ] && continue
    allowed=false
    for prefix in "${INGEST_ARTIFACT_PATHS[@]}"; do
      case "$path" in
        "$prefix"|"$prefix"/*) allowed=true; break ;;
      esac
    done
    if [ "$allowed" != true ]; then
      echo "Refusing to commit non-ingest path from stash overlay: $path" >&2
      git reset HEAD -- "$path" >/dev/null 2>&1 || true
      git checkout -- "$path" 2>/dev/null || true
    fi
  done < <(git diff --cached --name-only)

  if git diff --cached --quiet; then
    echo "No ingest artifact changes after allowlist filter"
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
